"""deliv_build — 분석 결과·진척·완료 보고로 문서의 표를 코드가 만든다(LLM 없음).

통과율·커버리지·컬럼·불일치·요구사항 연결은 모두 여기서 계산한다. AI가 쓸 부분은 작업(tasks)으로만 남긴다.
"""
from langsmith import traceable

from ..config import today_of
from ..deliverables import registry
from ..deps import SupervisorDeps
from ..state import DeliverableState
from .common import with_event


@traceable(name="deliv_build_node")
async def deliv_build_node(state: DeliverableState, deps: SupervisorDeps) -> dict:
    mod, a = registry.get(state["doc_type"]), state["analysis"]
    desc = a.get("description", "")
    art = a.get("artifact", {})
    repo = next((l.split(":", 1)[1].strip() for l in desc.splitlines() if l.startswith("저장소")), "") \
        or (f"{art['repo']} ({art.get('branch', '')} {art.get('head') or ''})".strip() if art.get("repo") else "")
    label = state["source"].split(":", 1)[1] if ":" in state["source"] else (art.get("head") or "현재")
    meta = {"project_name": deps.settings.project_name, "repo": repo, "run_label": label,
            "source": state["source"], "note": desc, "written_on": today_of(deps.settings).isoformat()}
    if mod.DOC_TYPE == "test_report":
        doc = mod.build(a, a["kinds"], state["progress"], state["reports"], meta)
    else:
        doc = mod.build(a, state["progress"], state["reports"], meta)
    event = {"type": "DocumentBuilt", "doc_type": mod.DOC_TYPE, "tasks": doc["tasks"],
             "numbers": {k: v for k, v in doc["numbers"].items() if isinstance(v, (int, float, type(None)))}}
    if mod.DOC_TYPE == "test_report":
        n = doc["numbers"]["total"]
        event.update(sections=len(doc["sections"]), total=n["total"], pass_rate=n["pass_rate"],
                     linked=doc["numbers"]["linked"])
    return {"doc": doc, "pending": list(doc["tasks"]), "events": with_event(state, event)}
