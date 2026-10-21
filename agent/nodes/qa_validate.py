"""qa_validate — LLM 코멘트 속 숫자·고유번호가 답 본문에 있는지 코드로 검증한다.

틀리면 반려 사유를 붙여 다시 쓰게 하고(상한 settings.qa_retries), 끝내 틀리면 코멘트를 빼고
본문만 준다 — 본문은 조회 결과로 코드가 쓴 것이라 그대로 내보내도 안전하다.
"""
from langsmith import traceable

from ..deps import SupervisorDeps
from ..qa import check_comment
from ..state import ChatState
from .common import with_event


@traceable(name="qa_validate_node")
async def qa_validate_node(state: ChatState, deps: SupervisorDeps) -> dict:
    problems = check_comment(state["draft"], state["core"], state["query"])
    retry = bool(problems) and state["attempts"] <= deps.settings.qa_retries
    fallback = bool(problems) and not retry
    event = {"type": "AnswerValidated", "attempt": state["attempts"], "problems": problems,
             "retry": retry, "fallback": fallback}
    update = {"feedback": "; ".join(problems) if retry else "", "used_fallback": fallback,
              "events": with_event(state, event)}
    if not retry:
        comment = "" if fallback else state["draft"].strip()
        update["final"] = state["core"] + (f"\n\n{comment}" if comment else "")
    return update
