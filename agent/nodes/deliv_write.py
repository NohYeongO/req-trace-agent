"""deliv_write — 서술 섹션(실패 원인 분석, 종합 의견)을 quality LLM이 쓴다(토큰 스트리밍).

검증을 아직 못 넘은 섹션만 다시 쓴다. 실패 원인 분석에는 [실패 원인] 사실만 준다 — 범위를 좁혀야
작은 모델이 다른 수치를 섞지 않는다.
"""
from langgraph.config import get_stream_writer
from langsmith import traceable

from ..deps import SupervisorDeps
from ..qa import clean_answer
from ..state import DeliverableState
from .common import add_cost, with_event


def section_facts(doc: dict, sid: str) -> str:
    if sid == "failure_analysis":
        return "\n".join(l for l in doc["facts"].splitlines() if l.startswith("[실패 원인]"))
    return doc["facts"]


@traceable(name="deliv_write_node")
async def deliv_write_node(state: DeliverableState, deps: SupervisorDeps) -> dict:
    writer = get_stream_writer()
    doc, attempt, cost = state["doc"], state["attempts"] + 1, state.get("cost_usd", 0.0)
    for sid in state["pending"]:
        text, usage = await deps.quality_llm.write_section(
            sid, section_facts(doc, sid), state["feedback"].get(sid) or None,
            on_token=lambda piece, sid=sid: writer({"type": "SectionToken", "section": sid, "delta": piece,
                                                    "attempt": attempt}))
        next(s for s in doc["sections"] if s["id"] == sid)["text"] = clean_answer(text)
        cost = add_cost({"cost_usd": cost}, usage)
    event = {"type": "SectionsWritten", "sections": state["pending"], "attempt": attempt}
    return {"doc": doc, "attempts": attempt, "cost_usd": cost, "events": with_event(state, event)}
