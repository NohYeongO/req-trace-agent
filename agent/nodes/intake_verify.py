"""intake_verify — 보고에 적힌 근거가 산출물에 실제로 있는지 MCP artifact 서버로 확인한다.

결과는 화면에 '근거 확인됨/없음'으로 표시만 한다. 근거가 없다고 보고를 막지는 않는다
(산출물이 아직 반영 전일 수 있고, 판단은 확인하는 사람의 몫이다).
"""
from langsmith import traceable

from ..deps import SupervisorDeps
from ..retry import with_retry
from ..state import IntakeState
from .common import with_event


@traceable(name="intake_verify_node")
async def intake_verify_node(state: IntakeState, deps: SupervisorDeps) -> dict:
    checked = []
    if state["evidence"]:
        result, _ = await with_retry(deps.mcp.call_tool, "verify_evidence",
                                     {"items": state["evidence"]})
        checked = result["results"]
    counts = {s: sum(1 for c in checked if c["status"] == s)
              for s in ("found", "not_found", "unchecked")}
    return {"evidence_check": checked,
            "events": with_event(state, {"type": "EvidenceChecked", **counts})}
