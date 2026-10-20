"""criteria_save — 검증을 통과한 초안을 '검토 대기'(origin=ai, confirmed=0)로 저장한다.

저장만 하고 확정하지 않는다. 진척 계산에는 담당자가 요구사항 화면에서 확정한 조건만 쓰인다.
"""
from langsmith import traceable

from ..deps import SupervisorDeps
from ..state import CriteriaState
from .common import with_event


@traceable(name="criteria_save_node")
async def criteria_save_node(state: CriteriaState, deps: SupervisorDeps) -> dict:
    saved = []
    for rid, items in state["drafts"].items():
        deps.store.replace_criteria(rid, [{"text": t, "origin": "ai"} for t in items], confirm=False)
        saved.append(rid)
    event = {"type": "CriteriaSaved", "saved": saved, "failed": state.get("failed") or {},
             "cost_usd": state.get("cost_usd", 0.0)}
    return {"saved": saved, "events": with_event(state, event)}
