"""qa_validate — 답변 속 숫자·고유번호가 조회 결과(사실)에 있는지 코드로 검증한다.

틀리면 반려 사유를 붙여 다시 쓰게 하고(상한 settings.qa_retries), 끝내 틀리면 조회 결과로
코드가 직접 쓴 답으로 대체한다 — 진척 수치를 지어낸 답이 사용자에게 나가지 않게 하는 장치다.
"""
from langsmith import traceable

from ..deps import SupervisorDeps
from ..qa import check_answer, fallback_answer
from ..state import ChatState
from .common import with_event


@traceable(name="qa_validate_node")
async def qa_validate_node(state: ChatState, deps: SupervisorDeps) -> dict:
    problems = check_answer(state["draft"], state["facts"], state["query"])
    retry = bool(problems) and state["attempts"] <= deps.settings.qa_retries
    fallback = bool(problems) and not retry
    event = {"type": "AnswerValidated", "attempt": state["attempts"], "problems": problems,
             "retry": retry, "fallback": fallback}
    update = {"feedback": "; ".join(problems) if retry else "", "used_fallback": fallback,
              "events": with_event(state, event)}
    if not retry:
        update["final"] = fallback_answer(state["results"]) if fallback else state["draft"]
    return update
