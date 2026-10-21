"""qa_research — 계획한 MCP Tool을 병렬로 호출하고, 결과를 '사실' 문단으로 정리한다."""
import asyncio
import time

from langsmith import traceable

from ..deps import SupervisorDeps
from ..qa import build_facts
from ..retry import with_retry
from ..state import ChatState
from .common import with_event


@traceable(name="qa_research_node")
async def qa_research_node(state: ChatState, deps: SupervisorDeps) -> dict:
    started = time.perf_counter()

    async def one(call: dict) -> dict:
        result, retries = await with_retry(deps.mcp.call_tool, call["tool"], call["args"])
        return {**call, "result": result, "retries": retries}

    results = await asyncio.gather(*(one(c) for c in state["calls"]))
    facts = build_facts(results, state["query"])
    event = {"type": "ToolsCalled", "count": len(results), "tools": [r["tool"] for r in results],
             "retries": sum(r["retries"] for r in results),
             "elapsed_ms": round((time.perf_counter() - started) * 1000)}
    return {"results": list(results), "facts": facts, "events": with_event(state, event)}
