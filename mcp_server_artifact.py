"""req-trace-agent — MCP 서버 "artifact" (산출물 근거 확인).

완료 보고에 적힌 파일·API·코드·테스트·커밋·PR이 산출물에 실제로 있는지 확인한다. 산출물은
공용 Git 저장소(ARTIFACT_REPO_URL, 확인할 때마다 fetch) 또는 로컬 폴더(ARTIFACT_ROOT)다.
업무 DB를 다루는 trace 서버와 관심사가 달라 별도 서버로 나눴다 — 에이전트는 Tool 이름만
알고, 어느 서버가 제공하는지는 MCPClient.find_tool이 찾는다.

- Tool verify_evidence(items) : [{type, value}] → 항목별 found / not_found / unchecked
- Tool artifact_status()      : 확인 대상(저장소·브랜치·HEAD 또는 폴더), 파일·엔드포인트 수
"""
import sys
from pathlib import Path

from dotenv import load_dotenv
from fastmcp import FastMCP

sys.path.insert(0, str(Path(__file__).resolve().parent))
load_dotenv()

from agent.artifacts import ArtifactChecker, make_checker   # noqa: E402
from agent.config import get_settings         # noqa: E402

mcp = FastMCP(name="req-trace-agent-artifact")
_checker: ArtifactChecker | None = None


def checker() -> ArtifactChecker:
    global _checker
    if _checker is None:
        _checker = make_checker(get_settings())
    return _checker


@mcp.tool()
def verify_evidence(items: list[dict]) -> dict:
    """근거 항목([{type: file|api|code|test|pr|commit, value}])이 산출물에 실제로 있는지 확인한다."""
    return {"results": checker().check(items)}


@mcp.tool()
def artifact_status() -> dict:
    """확인 대상(공용 저장소·브랜치·HEAD 또는 로컬 폴더)과 규모(파일·엔드포인트 수)."""
    return checker().status()


if __name__ == "__main__":
    try:
        mcp.run(show_banner=False)
    except TypeError:
        mcp.run()
