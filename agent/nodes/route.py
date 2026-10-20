"""route — 메시지를 chat / status / summary로 분류한다."""
from langsmith import traceable

from ..deps import SupervisorDeps
from ..state import ChatState
from .common import add_cost, with_event


@traceable(name="route_node")
async def route_node(state: ChatState, deps: SupervisorDeps) -> dict:
    result, usage = await deps.fast_llm.route(state["query"])
    return {"route": result["route"], "cost_usd": add_cost(state, usage),
            "events": with_event(state, {"type": "RouteDecided", "route": result["route"]})}
