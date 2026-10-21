"""검수 산출물 작성 그래프 (테스트 결과 보고서).

deliv_collect → deliv_build → deliv_write → deliv_validate ─(반려 있음)→ deliv_write
      │(자료 없음)                                         └(통과·상한 도달)→ deliv_save
      └→ END

collect는 MCP Tool(artifact·trace 서버)로 자료를 모으고, build는 코드가 표를 만들고, write는 LLM이
서술만 쓰고, validate는 서술 속 숫자를 결과와 대조한다. 검토·확정은 저장된 초안을 화면에서 한다.
"""
from functools import partial

from langgraph.graph import END, StateGraph

from ..deps import SupervisorDeps
from ..nodes.deliv_build import deliv_build_node
from ..nodes.deliv_collect import deliv_collect_node
from ..nodes.deliv_save import deliv_save_node
from ..nodes.deliv_validate import deliv_validate_node
from ..nodes.deliv_write import deliv_write_node
from ..state import DeliverableState


def _after_collect(state: DeliverableState) -> str:
    return "end" if state.get("error") else "build"


def _after_build(state: DeliverableState) -> str:
    return "write" if state["pending"] else "save"


def _after_validate(state: DeliverableState) -> str:
    return "write" if state["pending"] else "save"


def build_deliverable_graph(deps: SupervisorDeps):
    g = StateGraph(DeliverableState)
    node = lambda fn: partial(fn, deps=deps)
    g.add_node("collect", node(deliv_collect_node))
    g.add_node("build", node(deliv_build_node))
    g.add_node("write", node(deliv_write_node))
    g.add_node("validate", node(deliv_validate_node))
    g.add_node("save", node(deliv_save_node))

    g.set_entry_point("collect")
    g.add_conditional_edges("collect", _after_collect, {"build": "build", "end": END})
    g.add_conditional_edges("build", _after_build, {"write": "write", "save": "save"})
    g.add_edge("write", "validate")
    g.add_conditional_edges("validate", _after_validate, {"write": "write", "save": "save"})
    g.add_edge("save", END)
    return g.compile()
