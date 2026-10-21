"""deliv_save — AI 결과를 반영해 표를 마무리하고(finalize) 초안을 업무 DB에 저장한다(status=draft).

검토는 그래프를 멈춰 기다리지 않고(interrupt) 저장된 초안을 화면에서 고친 뒤 확정하는 방식이다.
산출물은 며칠에 걸쳐 여러 사람이 검토하므로, 메모리 체크포인터보다 DB에 남는 편이 맞다.
"""
from langsmith import traceable

from ..deliverables import registry
from ..deps import SupervisorDeps
from ..state import DeliverableState
from .common import with_event


@traceable(name="deliv_save_node")
async def deliv_save_node(state: DeliverableState, deps: SupervisorDeps) -> dict:
    doc = state["doc"]
    registry.get(state["doc_type"]).finalize(doc)
    doc.pop("tasks", None)
    title = f"{doc['title']} ({doc['meta']['run_label']})"
    doc_id = deps.store.save_deliverable(doc["doc_type"], title, state["source"], doc)
    return {"doc_id": doc_id, "events": with_event(state, {"type": "DraftSaved", "doc_id": doc_id, "title": title,
                                                           "fallbacks": state.get("fallbacks", [])})}
