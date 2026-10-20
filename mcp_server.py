"""req-trace-agent — MCP 서버 "trace" (요구사항·진척 조회).

FastAPI 백엔드(server.py)가 lifespan에서 이 파일을 subprocess(stdio)로 1회 기동해
서버 수명 동안 재사용한다. 에이전트는 업무 DB를 직접 열지 않고 이 서버의 Tool/Resource로만
읽는다 — 조회 방법이 바뀌어도 에이전트 코드는 그대로다.

- Tool     get_store_status, list_requirements, get_requirement : 호출마다 결과가 바뀌는 동적 조회
- Resource requirement://{req_id} : 요구사항 1건 원문과 완료 조건(URI로 식별되는 문서)

현황 집계·검색·완료 보고 조회 Tool과 Prompt는 기능 PR마다 여기에 추가한다.
"""
import json
import sys
from pathlib import Path

from dotenv import load_dotenv
from fastmcp import FastMCP

sys.path.insert(0, str(Path(__file__).resolve().parent))
load_dotenv()

from agent.config import get_settings   # noqa: E402
from agent.store import ProjectStore    # noqa: E402

mcp = FastMCP(name="req-trace-agent-trace")
_store: ProjectStore | None = None


def store() -> ProjectStore:
    """첫 호출 때 연다 — 서버(FastAPI)가 같은 DB 경로를 환경변수로 넘겨준다."""
    global _store
    if _store is None:
        _store = ProjectStore(get_settings().db_path)
    return _store


@mcp.tool()
def get_store_status() -> dict:
    """업무 DB에 들어 있는 요구사항·완료 조건·완료 보고 건수."""
    return {"counts": store().counts()}


@mcp.tool()
def list_requirements(category: str = "") -> dict:
    """요구사항 목록(고유번호·분류·이름·우선순위·완료 조건 개수와 상태). category로 분류 필터."""
    return {"requirements": store().list_requirements(category or None)}


@mcp.tool()
def get_requirement(req_id: str) -> dict:
    """요구사항 1건의 원문과 완료 조건 체크리스트. 없으면 error를 돌려준다."""
    req = store().get_requirement(req_id)
    return req if req else {"error": f"요구사항 {req_id}가 없습니다."}


@mcp.resource("requirement://{req_id}")
def requirement_resource(req_id: str) -> str:
    """요구사항 1건 원문(JSON 문자열)."""
    return json.dumps(get_requirement(req_id), ensure_ascii=False)


if __name__ == "__main__":
    try:
        mcp.run(show_banner=False)
    except TypeError:   # 구버전 fastmcp 호환
        mcp.run()
