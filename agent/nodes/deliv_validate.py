"""deliv_validate — AI 결과를 코드로 검증한다.

- 서술: 숫자·고유번호가 사실(결과 자료에서 계산한 값)에 있는지
- 이름 추정: 모든 key에 한글 이름이 있는지, 길이·형식
반려되면 사유를 붙여 그 작업만 다시 하고(상한 settings.deliverable_retries), 끝내 틀리면 대체한다
(서술은 코드 문장, 이름은 '미정') — 지어낸 수치가 검수 문서에 들어가지 않게 한다.
"""
from langsmith import traceable

from ..deliverables import registry
from ..deps import SupervisorDeps
from ..state import DeliverableState
from .common import with_event


@traceable(name="deliv_validate_node")
async def deliv_validate_node(state: DeliverableState, deps: SupervisorDeps) -> dict:
    mod = registry.get(state["doc_type"])
    doc, drafts = state["doc"], state["drafts"]
    retry_ok = state["attempts"] <= deps.settings.deliverable_retries
    pending, feedback, fallbacks, problems_by = [], {}, list(state.get("fallbacks", [])), {}
    for task in state["pending"]:
        problems = mod.check_task(doc, task, drafts[task])
        if not problems:
            mod.apply_task(doc, task, drafts[task])
            continue
        problems_by[task] = problems
        if retry_ok:
            pending.append(task)
            feedback[task] = "; ".join(problems)
        else:
            if isinstance(drafts[task], dict):          # 이름 추정은 통과한 이름만 쓰고 나머지는 미정
                mod.apply_task(doc, task, {k: v for k, v in drafts[task].items()
                                           if not any(p.startswith(f"{k}:") for p in problems)})
            mod.fallback_task(doc, task)
            fallbacks.append(task)
    event = {"type": "SectionsValidated", "attempt": state["attempts"], "problems": problems_by,
             "retry": pending, "fallback": [t for t in fallbacks if t not in state.get("fallbacks", [])]}
    return {"doc": doc, "pending": pending, "feedback": feedback, "fallbacks": fallbacks,
            "events": with_event(state, event)}
