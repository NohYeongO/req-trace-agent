"""채팅 그래프 — supervisor가 질문을 분류해 역할별 에이전트로 넘긴다.

route ─ chat    → chat_answer                          (대화 에이전트)
      ├ status  → plan → research → write → validate   (현황 질의응답 에이전트)
      ├ summary → plan → research → write → validate   (기간 요약 에이전트, 같은 노드·다른 계획과 프롬프트)
      └ report  → report_delegate                      (보고 정리 에이전트에 위임, 확인 대기)

validate가 반려하면 write로 돌아가 다시 쓴다(상한 settings.qa_retries, 넘으면 코드 답으로 대체).
모든 노드는 SupervisorDeps를 functools.partial로 주입받는다.
"""
from functools import partial

from langgraph.graph import END, StateGraph

from ..deps import SupervisorDeps
from ..nodes.chat import chat_answer_node
from ..nodes.qa_plan import qa_plan_node
from ..nodes.qa_research import qa_research_node
from ..nodes.qa_validate import qa_validate_node
from ..nodes.qa_write import qa_write_node
from ..nodes.report_delegate import report_delegate_node
from ..nodes.route import route_node
from ..state import ChatState

_ROUTE_TO = {"chat": "chat_answer", "status": "plan", "summary": "plan", "report": "report"}


def _after_route(state: ChatState) -> str:
    return _ROUTE_TO[state["route"]]


def _after_validate(state: ChatState) -> str:
    return "write" if state["feedback"] else "end"


def build_chat_graph(deps: SupervisorDeps):
    g = StateGraph(ChatState)
    node = lambda fn: partial(fn, deps=deps)
    g.add_node("route", node(route_node))
    g.add_node("chat_answer", node(chat_answer_node))
    g.add_node("plan", node(qa_plan_node))
    g.add_node("research", node(qa_research_node))
    g.add_node("write", node(qa_write_node))
    g.add_node("validate", node(qa_validate_node))
    g.add_node("report", node(report_delegate_node))

    g.set_entry_point("route")
    g.add_conditional_edges("route", _after_route, {v: v for v in _ROUTE_TO.values()})
    g.add_edge("chat_answer", END)
    g.add_edge("plan", "research")
    g.add_edge("research", "write")
    g.add_edge("write", "validate")
    g.add_conditional_edges("validate", _after_validate, {"write": "write", "end": END})
    g.add_edge("report", END)
    return g.compile()
