"""intake_confirm — LangGraph interrupt()로 멈추고 개발자의 확인을 기다린다(Human-in-the-loop).

AI가 정리한 매핑은 제안일 뿐이다. 개발자가 화면에서 요구사항·충족 조건을 고치고 '확인'을
눌러야 저장된다. interrupt는 재개될 때 노드를 처음부터 다시 실행하므로 앞에 부수효과가 없다.
"""
from langgraph.types import interrupt
from langsmith import traceable

from ..deps import SupervisorDeps
from ..state import IntakeState


@traceable(name="intake_confirm_node")
async def intake_confirm_node(state: IntakeState, deps: SupervisorDeps) -> dict:
    by_id = {c["id"]: c for c in state["candidates"]}
    suggestion = []
    for l in state["links"]:
        c = by_id[l["req_id"]]
        suggestion.append({"req_id": c["id"], "name": c["name"], "reason": l.get("reason", ""),
                           "criteria": [{**cr, "met": cr["id"] in l["met"]} for cr in c["criteria"]]})
    # 작성자가 양식에서 고른 요구사항은 AI가 충족 조건을 못 찾았어도 카드에 넣는다(사람의 선택이 우선).
    selected = state.get("selected", [])
    for sg in suggestion:
        if sg["req_id"] in selected and not sg["reason"].startswith("작성자가 선택"):
            sg["reason"] = "작성자가 선택 · " + sg["reason"] if sg["reason"] else "작성자가 선택"
    linked = {s["req_id"] for s in suggestion}
    for rid in selected:
        if rid not in linked and rid in by_id:
            c = by_id[rid]
            suggestion.append({"req_id": rid, "name": c["name"],
                               "reason": "작성자가 선택한 요구사항 — AI는 충족한 조건을 찾지 못했습니다. 직접 체크해 주세요.",
                               "criteria": [{**cr, "met": False} for cr in c["criteria"]]})
    decision = interrupt({
        "author": state["author"], "summary": state["summary"], "text": state["text"],
        "links": suggestion, "evidence_check": state["evidence_check"],
        "other_candidates": [{"req_id": c["id"], "name": c["name"], "criteria": c["criteria"]}
                             for c in state["candidates"]
                             if c["id"] not in {l["req_id"] for l in state["links"]}],
    })
    return {"decision": decision}
