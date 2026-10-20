"""완료 조건 초안 그래프 (요구사항 등록 에이전트).

criteria_select → criteria_draft → criteria_validate ─(반려 있음)→ criteria_draft
                                                     └(통과·상한 도달)→ criteria_save

대상이 없으면 select에서 바로 끝난다.
"""
from functools import partial

from langgraph.graph import END, StateGraph

from ..deps import SupervisorDeps
from ..nodes.criteria_draft import criteria_draft_node
from ..nodes.criteria_save import criteria_save_node
from ..nodes.criteria_select import criteria_select_node
from ..nodes.criteria_validate import criteria_validate_node
from ..state import CriteriaState


def _after_select(state: CriteriaState) -> str:
    return "draft" if state["targets"] else "end"


def _after_validate(state: CriteriaState) -> str:
    return "draft" if state["feedback"] else "save"


def build_criteria_graph(deps: SupervisorDeps):
    g = StateGraph(CriteriaState)
    node = lambda fn: partial(fn, deps=deps)
    g.add_node("select", node(criteria_select_node))
    g.add_node("draft", node(criteria_draft_node))
    g.add_node("validate", node(criteria_validate_node))
    g.add_node("save", node(criteria_save_node))

    g.set_entry_point("select")
    g.add_conditional_edges("select", _after_select, {"draft": "draft", "end": END})
    g.add_edge("draft", "validate")
    g.add_conditional_edges("validate", _after_validate, {"draft": "draft", "save": "save"})
    g.add_edge("save", END)
    return g.compile()
