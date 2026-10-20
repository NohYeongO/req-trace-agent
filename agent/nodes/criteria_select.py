"""criteria_select — 초안을 쓸 요구사항을 고른다.

확정된 조건이 있는 요구사항은 어떤 경우에도 건드리지 않는다. 검토 대기 중인 초안은
overwrite=True일 때만 다시 쓴다.
"""
from langsmith import traceable

from ..deps import SupervisorDeps
from ..state import CriteriaState
from .common import with_event


@traceable(name="criteria_select_node")
async def criteria_select_node(state: CriteriaState, deps: SupervisorDeps) -> dict:
    listed = deps.store.list_requirements()
    wanted = set(state.get("req_ids") or [r["id"] for r in listed])
    allowed = {"none", "draft"} if state.get("overwrite") else {"none"}
    targets, skipped = {}, []
    for r in listed:
        if r["id"] not in wanted:
            continue
        if r["criteria_state"] in allowed:
            targets[r["id"]] = deps.store.get_requirement(r["id"])
        else:
            skipped.append(r["id"])
    unknown = sorted(wanted - {r["id"] for r in listed})
    event = {"type": "CriteriaSelected", "count": len(targets), "skipped": skipped,
             "unknown": unknown}
    return {"targets": targets, "events": with_event(state, event)}
