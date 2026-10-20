"""intake_extract — 보고에서 요구사항 ID·근거는 정규식으로, 요약·검색 질의는 LLM으로 뽑는다."""
from langsmith import traceable

from ..deps import SupervisorDeps
from ..evidence import extract_evidence
from ..requirements import REQ_ID_RE
from ..state import IntakeState
from .common import add_cost, with_event


@traceable(name="intake_extract_node")
async def intake_extract_node(state: IntakeState, deps: SupervisorDeps) -> dict:
    text = state["text"]
    mentioned = list(dict.fromkeys(REQ_ID_RE.findall(text)))
    evidence = extract_evidence(text)
    result, usage = await deps.quality_llm.summarize_report(text)
    event = {"type": "ReportExtracted", "summary": result["summary"], "mentioned": mentioned,
             "evidence_count": len(evidence)}
    return {"mentioned": mentioned, "evidence": evidence, "summary": result["summary"],
            "query": result["query"], "cost_usd": add_cost(state, usage),
            "events": with_event(state, event)}
