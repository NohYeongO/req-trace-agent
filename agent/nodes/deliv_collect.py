"""deliv_collect — 문서에 필요한 자료를 MCP Tool로 모은다(문서 종류별 Tool + 진척·완료 보고).

- 테스트 결과 보고서: artifact 서버 analyze_test_results(JUnit·JaCoCo 해석, 단위/통합 구분)
- 개발 명세서: artifact 서버 analyze_source_spec(엔티티·DDL·컨트롤러·DTO 분석)
- 공통: trace 서버 get_progress·list_reports — 요구사항 연결용. 세 호출은 독립이라 동시에 부른다.
"""
import asyncio

from langsmith import traceable

from ..deliverables import registry
from ..deps import SupervisorDeps
from ..retry import with_retry
from ..state import DeliverableState
from .common import with_event


@traceable(name="deliv_collect_node")
async def deliv_collect_node(state: DeliverableState, deps: SupervisorDeps) -> dict:
    mod = registry.get(state["doc_type"])
    (analysis, _), (progress, _), (reports, _) = await asyncio.gather(
        with_retry(deps.mcp.call_tool, mod.COLLECT_TOOL, mod.collect_args(state["source"])),
        with_retry(deps.mcp.call_tool, "get_progress", {}),
        with_retry(deps.mcp.call_tool, "list_reports", {"limit": 1000}))
    error = analysis.get("error")
    if not error and mod is registry.DOC_TYPES["test_report"] and not analysis["cases"]:
        error = "결과 자료에서 JUnit 테스트 케이스를 찾지 못했습니다."
    if not error and mod is registry.DOC_TYPES["dev_spec"] and not (analysis["endpoints"] or analysis["entities"]):
        error = "저장소에서 컨트롤러·엔티티를 찾지 못했습니다."
    if error:
        return {"error": error, "events": with_event(state, {"type": "Failed", "error": error})}
    if "cases" in analysis:
        kinds = [k["kind"] for k in analysis["kinds"].values()]
        event = {"type": "ResultsCollected", "cases": len(analysis["cases"]), "classes": len(analysis["kinds"]),
                 "coverage_modules": len(analysis["coverage"]), "integration": kinds.count("통합"),
                 "unit": kinds.count("단위"), "unknown": kinds.count("미확인"), "reports": len(reports["reports"])}
    else:
        event = {"type": "SourceAnalyzed", "endpoints": len(analysis["endpoints"]),
                 "entities": len(analysis["entities"]), "dtos": len(analysis["dtos"]),
                 "ddl_files": analysis["ddl_files"], "issues": sum(len(e["issues"]) for e in analysis["entities"]),
                 "head": analysis.get("artifact", {}).get("head"), "reports": len(reports["reports"])}
    return {"analysis": analysis, "progress": progress, "reports": reports["reports"],
            "events": with_event(state, event)}
