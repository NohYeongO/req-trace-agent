"""route — 메시지를 chat / status / summary / report로 분류한다.

'그럼 보안은?'처럼 대상을 생략한 후속 질문은 그 자체로는 잡담처럼 보인다. 직전 질문이 현황·요약
질문이었다면 같은 갈래로 보낸다(대상은 qa_plan이 직전 대화에서 이어받는다).
"""
from langsmith import traceable

from ..deps import SupervisorDeps
from ..llm.rules import route_by_rule
from ..qa import is_follow_up
from ..state import ChatState
from .common import add_cost, with_event


def _follow_up_route(query: str, history: list[dict]) -> str | None:
    prev = next((m["content"] for m in reversed(history or []) if m.get("role") == "user"), None)
    if prev and is_follow_up(query):
        rule = route_by_rule(prev)
        return "status" if rule in ("status", "summary") else None
    return None


@traceable(name="route_node")
async def route_node(state: ChatState, deps: SupervisorDeps) -> dict:
    result, usage = await deps.fast_llm.route(state["query"])
    route = result["route"]
    if route == "chat":
        route = _follow_up_route(state["query"], state.get("history")) or route
    return {"route": route, "cost_usd": add_cost(state, usage),
            "events": with_event(state, {"type": "RouteDecided", "route": route})}
