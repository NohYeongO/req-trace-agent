"""deliv_write — 문서의 AI 작업(서술·이름 추정)을 quality LLM이 한다.

검증을 아직 못 넘은 작업만 다시 한다. 서술은 토큰을 흘려 화면에 실시간으로 보이고, 이름 추정(JSON)은
작업이 끝날 때마다 진행 이벤트를 보낸다.
"""
from langgraph.config import get_stream_writer
from langsmith import traceable

from ..deliverables import registry
from ..deps import SupervisorDeps
from ..qa import clean_answer
from ..state import DeliverableState
from .common import add_cost, with_event


@traceable(name="deliv_write_node")
async def deliv_write_node(state: DeliverableState, deps: SupervisorDeps) -> dict:
    writer = get_stream_writer()
    mod = registry.get(state["doc_type"])
    doc, attempt, cost = state["doc"], state["attempts"] + 1, state.get("cost_usd", 0.0)
    drafts = dict(state.get("drafts", {}))
    for i, task in enumerate(state["pending"], 1):
        value, usage = await mod.write_task(
            deps.quality_llm, doc, task, state["feedback"].get(task) or None,
            on_token=lambda piece, t=task: writer({"type": "SectionToken", "section": t, "delta": piece,
                                                   "attempt": attempt}))
        drafts[task] = clean_answer(value) if isinstance(value, str) else value
        cost = add_cost({"cost_usd": cost}, usage)
        writer({"type": "TaskDone", "task": task, "index": i, "of": len(state["pending"]), "attempt": attempt})
    event = {"type": "SectionsWritten", "sections": state["pending"], "attempt": attempt}
    return {"drafts": drafts, "attempts": attempt, "cost_usd": cost, "events": with_event(state, event)}
