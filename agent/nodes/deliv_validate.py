"""deliv_validate — 서술 속 숫자·고유번호가 사실(결과 파일에서 계산한 값)에 있는지 코드로 검증한다.

반려되면 사유를 붙여 그 섹션만 다시 쓰게 하고(상한 settings.deliverable_retries), 끝내 틀리면
코드 문장(test_report.fallback_text)으로 대체한다 — 지어낸 통과율이 검수 문서에 들어가지 않게 한다.
"""
from langsmith import traceable

from ..deliverables import test_report
from ..deps import SupervisorDeps
from ..qa import check_answer
from ..state import DeliverableState
from .common import with_event
from .deliv_write import section_facts


@traceable(name="deliv_validate_node")
async def deliv_validate_node(state: DeliverableState, deps: SupervisorDeps) -> dict:
    doc = state["doc"]
    retry_ok = state["attempts"] <= deps.settings.deliverable_retries
    pending, feedback, fallbacks, problems_by = [], {}, list(state.get("fallbacks", [])), {}
    for sid in state["pending"]:
        sec = next(s for s in doc["sections"] if s["id"] == sid)
        problems = check_answer(sec["text"], doc["facts"], "")
        if not sec["text"].strip():
            problems.append("빈 글")
        if "**" in sec["text"]:
            problems.append("굵게 표시(**) 없이 쓸 것")
        if problems:
            problems_by[sid] = problems
            if retry_ok:
                pending.append(sid)
                feedback[sid] = "; ".join(problems)
            else:
                sec["text"], sec["fallback"] = test_report.fallback_text(sec, doc), True
                fallbacks.append(sid)
        sec["facts"] = section_facts(doc, sid)
    event = {"type": "SectionsValidated", "attempt": state["attempts"], "problems": problems_by,
             "retry": pending, "fallback": [s for s in fallbacks if s not in state.get("fallbacks", [])]}
    return {"doc": doc, "pending": pending, "feedback": feedback, "fallbacks": fallbacks,
            "events": with_event(state, event)}
