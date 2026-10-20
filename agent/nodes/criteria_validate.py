"""criteria_validate — 초안을 코드로 검증하고, 반려된 요구사항만 다시 쓰게 한다.

재시도 상한(settings.criteria_retries)을 넘기면 통과한 조건만 남기고, 남는 게 없으면
그 요구사항은 실패로 기록한다 — 그래프가 무한히 돌지 않게 하는 장치다.
"""
from langsmith import traceable

from ..criteria_rules import validate_criteria
from ..deps import SupervisorDeps
from ..state import CriteriaState
from .common import with_event


@traceable(name="criteria_validate_node")
async def criteria_validate_node(state: CriteriaState, deps: SupervisorDeps) -> dict:
    last_try = state["attempts"] > deps.settings.criteria_retries
    checked = list(state.get("feedback") or state["drafts"])
    drafts = dict(state["drafts"])
    failed = dict(state.get("failed") or {})
    feedback: dict[str, str] = {}
    for rid in checked:
        if rid not in drafts:
            continue
        clean, problems = validate_criteria(state["targets"][rid], drafts[rid])
        if not problems:
            drafts[rid] = clean
        elif last_try:
            if clean:
                drafts[rid] = clean[:5]
            else:
                drafts.pop(rid)
                failed[rid] = "; ".join(problems)
        else:
            feedback[rid] = "; ".join(problems)
    event = {"type": "CriteriaValidated", "attempt": state["attempts"], "checked": len(checked),
             "rejected": sorted(feedback), "reasons": feedback}
    return {"drafts": drafts, "failed": failed, "feedback": feedback,
            "events": with_event(state, event)}
