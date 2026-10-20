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
    decision = interrupt({
        "author": state["author"], "summary": state["summary"], "text": state["text"],
        "links": suggestion, "evidence_check": state["evidence_check"],
        "other_candidates": [{"req_id": c["id"], "name": c["name"], "criteria": c["criteria"]}
                             for c in state["candidates"]
                             if c["id"] not in {l["req_id"] for l in state["links"]}],
    })
    return {"decision": decision}
