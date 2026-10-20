"""채팅 그래프 (supervisor).

route → chat_answer            (가벼운 대화)
      → pending                (status·summary — 이후 PR에서 전용 에이전트로 교체)

모든 노드는 SupervisorDeps를 functools.partial로 주입받는다.
"""
from functools import partial

from langgraph.graph import END, StateGraph

from ..deps import SupervisorDeps
from ..nodes.chat import chat_answer_node
from ..nodes.pending import pending_node
from ..nodes.route import route_node
from ..state import ChatState


def _after_route(state: ChatState) -> str:
    return "chat_answer" if state["route"] == "chat" else "pending"


def build_chat_graph(deps: SupervisorDeps):
    g = StateGraph(ChatState)
    node = lambda fn: partial(fn, deps=deps)
    g.add_node("route", node(route_node))
    g.add_node("chat_answer", node(chat_answer_node))
    g.add_node("pending", node(pending_node))

    g.set_entry_point("route")
    g.add_conditional_edges("route", _after_route,
                            {"chat_answer": "chat_answer", "pending": "pending"})
    g.add_edge("chat_answer", END)
    g.add_edge("pending", END)
    return g.compile()
