"""intake_candidates — 매핑할 후보 요구사항을 모은다.

보고에 고유번호(SFR-005 등)가 적혀 있으면 그것을 먼저 넣고, MCP search_requirements(RAG)로
의미가 가까운 요구사항을 더한다. 후보의 조건 목록은 MCP get_requirement로 가져온다.

다중 질의: 보고 하나에 기능 여러 개를 적는 경우가 많다(예: 반려동물 등록·수정·삭제). 질의
하나로 상위 몇 건만 가져오면 일부 요구사항이 후보에서 빠졌기 때문에, LLM이 다시 쓴 질의와
보고의 문장들로 각각 검색하고 요구사항별 최고 점수로 합친다.
"""
import re

from langsmith import traceable

from ..deps import SupervisorDeps
from ..retry import with_retry
from ..state import IntakeState
from .common import with_event


@traceable(name="intake_candidates_node")
async def intake_candidates_node(state: IntakeState, deps: SupervisorDeps) -> dict:
    queries = [state["query"] or state["text"]] + [
        s for s in re.split(r"(?<=[.!?。])\s+|\n|,\s*", state["text"]) if len(s.strip()) >= 8]
    best: dict[str, float] = {}
    for q in dict.fromkeys(queries):
        found, _ = await with_retry(deps.mcp.call_tool, "search_requirements",
                                    {"query": q, "top_k": 3})
        for h in found["results"]:
            best[h["req_id"]] = max(best.get(h["req_id"], 0.0), h["score"])
    ranked = sorted(best.items(), key=lambda kv: -kv[1])[:deps.settings.intake_top_k]
    searched = [rid for rid, _ in ranked]
    ids = list(dict.fromkeys(state["mentioned"] + searched))
    candidates, unknown = [], []
    for rid in ids:
        req = await deps.mcp.call_tool("get_requirement", {"req_id": rid})
        if "error" in req:
            unknown.append(rid)
            continue
        candidates.append({"id": req["id"], "name": req["name"],
                           "description": req["description"],
                           "criteria": [{"id": c["id"], "text": c["text"], "confirmed": c["confirmed"]}
                                        for c in req["criteria"]]})
    event = {"type": "CandidatesFound", "mentioned": state["mentioned"], "searched": searched,
             "scores": dict(ranked), "queries": len(dict.fromkeys(queries)), "unknown": unknown}
    return {"candidates": candidates, "events": with_event(state, event)}
