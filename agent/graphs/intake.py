"""완료 보고 정리 그래프 (보고 정리 에이전트).

extract → candidates → map → validate ─(반려, 상한 이내)→ map
                                       └→ verify → confirm(interrupt, 개발자 확인) → save

confirm에서 멈췄다가 재개해야 하므로 체크포인터가 필요하다. 다음 단계에서 채팅 supervisor가
이 그래프를 서브그래프로 호출할 수 있게 그래프 조립만 여기서 한다.
"""
from functools import partial

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from ..deps import SupervisorDeps
from ..nodes.intake_candidates import intake_candidates_node
from ..nodes.intake_confirm import intake_confirm_node
from ..nodes.intake_extract import intake_extract_node
from ..nodes.intake_map import intake_map_node
from ..nodes.intake_save import intake_save_node
from ..nodes.intake_validate import intake_validate_node
from ..nodes.intake_verify import intake_verify_node
from ..state import IntakeState


def intake_config(run_id: str) -> dict:
    """보고 정리 실행 하나의 체크포인트 키 — 완료 보고 탭과 채팅 위임이 같은 규칙을 쓴다."""
    return {"configurable": {"thread_id": f"intake-{run_id}"}}


def _after_validate(state: IntakeState) -> str:
    return "map" if state["feedback"] else "verify"


def build_intake_graph(deps: SupervisorDeps, checkpointer=None):
    g = StateGraph(IntakeState)
    node = lambda fn: partial(fn, deps=deps)
    g.add_node("extract", node(intake_extract_node))
    g.add_node("candidates", node(intake_candidates_node))
    g.add_node("map", node(intake_map_node))
    g.add_node("validate", node(intake_validate_node))
    g.add_node("verify", node(intake_verify_node))
    g.add_node("confirm", node(intake_confirm_node))
    g.add_node("save", node(intake_save_node))

    g.set_entry_point("extract")
    g.add_edge("extract", "candidates")
    g.add_edge("candidates", "map")
    g.add_edge("map", "validate")
    g.add_conditional_edges("validate", _after_validate, {"map": "map", "verify": "verify"})
    g.add_edge("verify", "confirm")
    g.add_edge("confirm", "save")
    g.add_edge("save", END)
    return g.compile(checkpointer=checkpointer or MemorySaver())
