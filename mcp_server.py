"""req-trace-agent — MCP 서버 "trace" (요구사항·진척 조회).

FastAPI 백엔드(server.py)가 lifespan에서 이 파일을 subprocess(stdio)로 1회 기동해
서버 수명 동안 재사용한다. 에이전트는 업무 DB를 직접 열지 않고 이 서버의 Tool/Resource로만
읽는다 — 조회 방법이 바뀌어도 에이전트 코드는 그대로다.

- Tool     get_store_status, list_requirements, get_requirement : 호출마다 결과가 바뀌는 동적 조회
- Tool     search_requirements(query) : 완료 보고 문장으로 관련 요구사항 찾기(RAG, 임베딩 검색)
- Tool     list_reports : 확인된 완료 보고 조회(기간·작성자·요구사항 필터)
- Tool     get_progress : 진척 집계(전체·분류별·우선순위별·담당자별·위험 신호) — 대시보드·엑셀과 같은 함수
- Resource requirement://{req_id} : 요구사항 1건 원문과 완료 조건(URI로 식별되는 문서)
- Prompt   intake_mapping_prompt : 완료 보고 → 요구사항·조건 매핑 표준 절차
"""
import json
import sys
from pathlib import Path

from dotenv import load_dotenv
from fastmcp import FastMCP

sys.path.insert(0, str(Path(__file__).resolve().parent))
load_dotenv()

from agent.config import get_settings, today_of   # noqa: E402
from agent.dashboard import build_dashboard   # noqa: E402
from agent.retrieval import Glossary, RequirementSearch, make_embedder   # noqa: E402
from agent.store import ProjectStore    # noqa: E402

mcp = FastMCP(name="req-trace-agent-trace")
_store: ProjectStore | None = None
_search: RequirementSearch | None = None


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


def search() -> RequirementSearch:
    global _search
    if _search is None:
        st = get_settings()
        _search = RequirementSearch(store(), make_embedder(st.embedder, st.embed_model, st.ollama_url),
                                    Glossary.load(st.glossary_file), st.index_cache_dir)
    return _search


@mcp.tool()
def search_requirements(query: str, top_k: int = 5) -> dict:
    """문장과 의미가 가까운 요구사항 후보(요구사항 문서·완료 조건 문서 임베딩 검색)."""
    return {"results": search().search(query, top_k), "embedder": search().embedder.name}


@mcp.tool()
def list_reports(since: str = "", until: str = "", author: str = "", req_id: str = "",
                 limit: int = 50) -> dict:
    """확인된 완료 보고(최근순). since/until은 YYYY-MM-DD."""
    return {"reports": store().list_reports(limit, author or None, since or None, until or None,
                                            req_id or None)}


@mcp.tool()
def get_progress(as_of: str = "") -> dict:
    """진척 집계. as_of(YYYY-MM-DD)를 주면 그날 기준. 추이(trend)는 크기 때문에 뺀다."""
    dash = build_dashboard(store(), as_of or None, today=today_of(get_settings()))
    dash.pop("trend")
    return dash


@mcp.prompt()
def intake_mapping_prompt(report: str) -> str:
    """완료 보고를 요구사항·완료 조건에 매핑하는 표준 절차 — intake 그래프의 map 단계가 따른다."""
    return f"""다음 개발 완료 보고를 요구사항과 완료 조건에 매핑하라.

## 완료 보고
{report}

## 절차
1. 보고가 직접 말하는 작업만 본다. 추측으로 범위를 넓히지 않는다.
2. 후보 요구사항 중 보고가 다룬 요구사항만 고른다. 후보에 없는 요구사항은 고르지 않는다.
3. 고른 요구사항마다, 보고 내용으로 '끝났다'고 볼 수 있는 완료 조건 id만 고른다.
   일부만 했다면 그 조건만 고른다. 애매하면 고르지 않는다(사람이 확인 단계에서 추가한다).
4. 고른 이유를 한 문장으로 쓴다.
"""


@mcp.resource("requirement://{req_id}")
def requirement_resource(req_id: str) -> str:
    """요구사항 1건 원문(JSON 문자열)."""
    return json.dumps(get_requirement(req_id), ensure_ascii=False)


if __name__ == "__main__":
    try:
        mcp.run(show_banner=False)
    except TypeError:   # 구버전 fastmcp 호환
        mcp.run()
