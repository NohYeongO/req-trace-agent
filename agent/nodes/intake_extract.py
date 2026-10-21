"""intake_extract — 보고에서 요구사항 ID·근거는 정규식으로, 요약·검색 질의는 LLM으로 뽑는다.

완료 보고 양식으로 받은 근거·요구사항이 있으면 그것을 먼저 쓰고, 문장에서 찾은 것을 덧붙인다.
"""
from langsmith import traceable

from ..deps import SupervisorDeps
from ..evidence import merge_evidence
from ..requirements import REQ_ID_RE
from ..state import IntakeState
from .common import add_cost, with_event


@traceable(name="intake_extract_node")
async def intake_extract_node(state: IntakeState, deps: SupervisorDeps) -> dict:
    text = state["text"]
    mentioned = list(dict.fromkeys(state.get("selected", []) + REQ_ID_RE.findall(text)))
    evidence = merge_evidence(state.get("form_evidence", []), text)
    result, usage = await deps.quality_llm.summarize_report(text)
    event = {"type": "ReportExtracted", "summary": result["summary"], "mentioned": mentioned,
             "evidence_count": len(evidence),
             "form_evidence": sum(e.get("source") == "form" for e in evidence),
             "selected": state.get("selected", [])}
    return {"mentioned": mentioned, "evidence": evidence, "summary": result["summary"],
            "query": result["query"], "cost_usd": add_cost(state, usage),
            "events": with_event(state, event)}
