"""deliv_build — 결과 파일·진척·완료 보고로 보고서의 표를 코드가 만든다(LLM 없음).

통과율·커버리지·건수·요구사항 연결은 모두 여기서 계산한다. 서술 섹션은 자리만 만들고 write로 넘긴다.
"""
from langsmith import traceable

from ..config import today_of
from ..deliverables import test_report
from ..deps import SupervisorDeps
from ..state import DeliverableState
from .common import with_event


@traceable(name="deliv_build_node")
async def deliv_build_node(state: DeliverableState, deps: SupervisorDeps) -> dict:
    a = state["analysis"]
    desc = a.get("description", "")
    repo = next((l.split(":", 1)[1].strip() for l in desc.splitlines() if l.startswith("저장소")), "") \
        or a.get("artifact", {}).get("repo", "")
    meta = {"project_name": deps.settings.project_name, "repo": repo,
            "run_label": state["source"].split(":", 1)[1], "source": state["source"],
            "note": desc, "written_on": today_of(deps.settings).isoformat()}
    doc = test_report.build(a, a["kinds"], state["progress"], state["reports"], meta)
    pending = [s["id"] for s in doc["sections"] if s["kind"] == "ai"]
    n = doc["numbers"]["total"]
    event = {"type": "DocumentBuilt", "sections": len(doc["sections"]), "ai_sections": pending,
             "total": n["total"], "pass_rate": n["pass_rate"], "linked": doc["numbers"]["linked"]}
    return {"doc": doc, "pending": pending, "events": with_event(state, event)}
