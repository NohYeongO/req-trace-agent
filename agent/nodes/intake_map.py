"""intake_map — LLM이 후보 중 보고가 다룬 요구사항과 충족한 완료 조건 id를 고른다.

매핑 절차는 MCP Prompt(intake_mapping_prompt)에서 받는다. 검증에서 반려되면 반려 사유를
받아 다시 매핑한다.
"""
from langsmith import traceable

from ..deps import SupervisorDeps
from ..state import IntakeState
from .common import add_cost, with_event


@traceable(name="intake_map_node")
async def intake_map_node(state: IntakeState, deps: SupervisorDeps) -> dict:
    server = await deps.mcp.find_prompt("intake_mapping_prompt")
    procedure = await deps.mcp.get_prompt("intake_mapping_prompt", {"report": state["text"]}, server)
    links, usage = await deps.quality_llm.map_report(state["text"], state["candidates"], procedure,
                                                     state.get("feedback") or None)
    attempts = state.get("attempts", 0) + 1
    event = {"type": "ReportMapped", "attempt": attempts,
             "links": [{"req_id": l["req_id"], "met": l["met"]} for l in links]}
    return {"links": links, "attempts": attempts, "cost_usd": add_cost(state, usage),
            "events": with_event(state, event)}
