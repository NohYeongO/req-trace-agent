"""deliv_collect — 보고서에 필요한 자료를 MCP Tool로 모은다.

- artifact 서버 analyze_test_results: JUnit·JaCoCo 해석, 저장소 테스트 소스로 단위/통합 구분
- trace 서버 get_progress·list_reports: 요구사항 진척과 완료 보고(근거 포함) — 요구사항별 테스트 연결용
세 호출은 서로 독립이라 동시에 부른다.
"""
import asyncio

from langsmith import traceable

from ..deps import SupervisorDeps
from ..retry import with_retry
from ..state import DeliverableState
from .common import with_event


@traceable(name="deliv_collect_node")
async def deliv_collect_node(state: DeliverableState, deps: SupervisorDeps) -> dict:
    (analysis, _), (progress, _), (reports, _) = await asyncio.gather(
        with_retry(deps.mcp.call_tool, "analyze_test_results", {"source": state["source"]}),
        with_retry(deps.mcp.call_tool, "get_progress", {}),
        with_retry(deps.mcp.call_tool, "list_reports", {"limit": 1000}))
    if "error" in analysis:
        return {"error": analysis["error"], "events": with_event(state, {"type": "Failed", "error": analysis["error"]})}
    if not analysis["cases"]:
        msg = "결과 자료에서 JUnit 테스트 케이스를 찾지 못했습니다."
        return {"error": msg, "events": with_event(state, {"type": "Failed", "error": msg})}
    kinds = [k["kind"] for k in analysis["kinds"].values()]
    event = {"type": "ResultsCollected", "cases": len(analysis["cases"]), "classes": len(analysis["kinds"]),
             "coverage_modules": len(analysis["coverage"]), "integration": kinds.count("통합"),
             "unit": kinds.count("단위"), "unknown": kinds.count("미확인"), "reports": len(reports["reports"])}
    return {"analysis": analysis, "progress": progress, "reports": reports["reports"],
            "events": with_event(state, event)}
