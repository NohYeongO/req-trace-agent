"""intake_save — 개발자가 확인한 내용으로 완료 보고를 저장하고 진척 변화를 알려준다.

저장 값은 AI 제안이 아니라 개발자가 확인 단계에서 보낸 값(decision)이다.
"""
from langsmith import traceable

from ..deps import SupervisorDeps
from ..state import IntakeState
from .common import with_event


@traceable(name="intake_save_node")
async def intake_save_node(state: IntakeState, deps: SupervisorDeps) -> dict:
    d = state["decision"] or {}
    if d.get("decision") != "confirm":
        return {"final": "보고를 저장하지 않았습니다(취소).",
                "events": with_event(state, {"type": "ReportCancelled"})}
    before = deps.store.progress()
    links = [{"req_id": l["req_id"], "met_criteria": l.get("met_criteria", []),
              "evidence": state["evidence"], "evidence_check": state["evidence_check"]}
             for l in d.get("links", [])]
    report_id = deps.store.save_report(d.get("author") or state["author"], state["text"],
                                       d.get("summary") or state["summary"], links)
    after = deps.store.progress()
    changes = [{"req_id": l["req_id"], "before": before[l["req_id"]]["status"],
                "after": after[l["req_id"]]["status"], "met": after[l["req_id"]]["met"],
                "total": after[l["req_id"]]["total"]} for l in links]
    final = "보고를 저장했습니다. " + ", ".join(
        f"{c['req_id']} {c['before']}→{c['after']}({c['met']}/{c['total']})" for c in changes)
    return {"report_id": report_id, "changes": changes, "final": final,
            "events": with_event(state, {"type": "ReportSaved", "report_id": report_id,
                                         "changes": changes})}
