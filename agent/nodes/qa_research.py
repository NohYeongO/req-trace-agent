"""qa_research — 계획한 MCP Tool을 병렬로 호출하고, 조회 결과로 답 본문을 쓴다(agent/answers.py).

이름으로 묻는 질문('결제 기능 끝났어?')은 먼저 요구사항 이름과 대조하고, 맞는 게 없으면
search_requirements(RAG)로 의미가 가장 가까운 요구사항을 찾은 뒤 그 요구사항을 조회한다.
"""
import asyncio
import time

from langsmith import traceable

from ..answers import compose
from ..deps import SupervisorDeps
from ..qa import keywords, match_by_name
from ..retry import with_retry
from ..state import ChatState
from .common import with_event


@traceable(name="qa_research_node")
async def qa_research_node(state: ChatState, deps: SupervisorDeps) -> dict:
    started = time.perf_counter()

    async def one(call: dict) -> dict:
        result, retries = await with_retry(deps.mcp.call_tool, call["tool"], call["args"])
        return {**call, "result": result, "retries": retries}

    target = dict(state["target"])
    results = list(await asyncio.gather(*(one(c) for c in state["calls"])))
    if target["intent"] == "lookup":
        prog = next(r["result"] for r in results if r["tool"] == "get_progress")
        ids, how = match_by_name(state["query"], prog["requirements"]), "name"
        if not ids and keywords(state["query"]):
            found = await one({"tool": "search_requirements", "args": {"query": state["query"], "top_k": 1}})
            results.append(found)
            ids, how = [h["req_id"] for h in found["result"]["results"]][:1], "search"
        target.update(ids=ids, match_how=how if ids else None, label=" ".join(keywords(state["query"])))
        more = [{"tool": "get_requirement", "args": {"req_id": rid}} for rid in ids] + \
               [{"tool": "list_reports", "args": {"req_id": rid, "limit": 3}} for rid in ids]
        results += await asyncio.gather(*(one(c) for c in more))
    core = compose(target, results, state["query"])
    event = {"type": "ToolsCalled", "count": len(results), "tools": [r["tool"] for r in results],
             "retries": sum(r["retries"] for r in results), "matched": target.get("ids"),
             "elapsed_ms": round((time.perf_counter() - started) * 1000)}
    return {"target": target, "results": results, "core": core, "events": with_event(state, event)}
