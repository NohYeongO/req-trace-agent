"""req-trace-agent — MCP 서버 "artifact" (산출물 근거 확인).

완료 보고에 적힌 파일·API·코드·테스트가 산출물(ARTIFACT_ROOT)에 실제로 있는지 확인한다.
업무 DB를 다루는 trace 서버와 관심사가 달라 별도 서버로 나눴다 — 에이전트는 Tool 이름만
알고, 어느 서버가 제공하는지는 MCPClient.find_tool이 찾는다.

- Tool verify_evidence(items) : [{type, value}] → 항목별 found / not_found / unchecked
- Tool artifact_status()      : 산출물 경로, 파일 수, OpenAPI 엔드포인트 수
"""
import sys
from pathlib import Path

from dotenv import load_dotenv
from fastmcp import FastMCP

sys.path.insert(0, str(Path(__file__).resolve().parent))
load_dotenv()

from agent.artifacts import ArtifactChecker   # noqa: E402
from agent.config import get_settings         # noqa: E402

mcp = FastMCP(name="req-trace-agent-artifact")
_checker: ArtifactChecker | None = None


def checker() -> ArtifactChecker:
    global _checker
    if _checker is None:
        _checker = ArtifactChecker(get_settings().artifact_root)
    return _checker


@mcp.tool()
def verify_evidence(items: list[dict]) -> dict:
    """근거 항목([{type: file|api|code|test|pr|commit, value}])이 산출물에 실제로 있는지 확인한다."""
    return {"results": checker().check(items)}


@mcp.tool()
def artifact_status() -> dict:
    """확인 대상 산출물 경로와 규모."""
    c = checker()
    if c.root is None:
        return {"root": None, "files": 0, "operations": 0}
    return {"root": str(c.root), "files": len(c.files), "operations": len(c.operations)}


if __name__ == "__main__":
    try:
        mcp.run(show_banner=False)
    except TypeError:
        mcp.run()
