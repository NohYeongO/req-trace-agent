"""req-trace-agent — FastAPI 백엔드.

- lifespan에서 Agent 번들(업무 DB·세션 DB·LLM·MCP 연결·그래프)을 프로세스당 1회만 만들고
  app.state로 모든 요청이 공유한다(creation_count/instance_id로 확인 가능).
- mcp_server.py를 subprocess(stdio)로 기동해 서버 수명 동안 연결을 유지한다.
- GET /chat/stream — 그래프의 노드별 진행 상황과 답변 토큰을 SSE로 스트리밍한다.
- LangSmith: 요청당 chat_request 루트 run 아래로 노드·LLM·MCP 호출이 계층 기록된다.
"""
import json
import uuid
from contextlib import asynccontextmanager
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()   # LANGCHAIN_* · LLM_BACKEND 등 — agent import보다 먼저

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from langgraph.types import Command
from langsmith import traceable
from langsmith.run_helpers import get_current_run_tree
from pydantic import BaseModel

from agent.config import get_settings, today_of
from agent.criteria_rules import beyond_source
from agent.dashboard import build_dashboard
from agent.evidence import extract_evidence, merge_evidence, normalize_evidence
from agent.rtm_export import export_rtm
from agent.deps import SupervisorDeps
from agent.graphs import build_chat_graph, build_criteria_graph, build_intake_graph
from agent.graphs.intake import intake_config
from agent.llm import build_llms
from agent.mcp_client import MCPClient
from agent.requirements import REQ_ID_RE, load_requirements
from agent.state import initial_criteria_state, initial_intake_state, initial_state
from agent.store import ProjectStore, SqliteSessionStore

APP_VERSION = "0.4.0"
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
CREATION_COUNT = 0   # 프로세스 내 Agent 번들 생성 횟수 (항상 1이어야 정상)


class ChatRequest(BaseModel):
    message: str
    thread_id: str = "default"
    author: str = ""          # 채팅으로 완료 보고할 때 작성자


class CriterionIn(BaseModel):
    id: int | None = None
    text: str
    origin: str | None = None


class CriteriaUpdate(BaseModel):
    criteria: list[CriterionIn]
    confirm: bool = False


class EvidenceIn(BaseModel):
    type: str                     # pr | commit | api | test | file | code
    value: str


class ReportDraft(BaseModel):
    author: str
    text: str
    evidence: list[EvidenceIn] = []     # 완료 보고 양식의 근거 칸
    req_ids: list[str] = []             # 작성자가 고른 요구사항(선택)
    require_evidence: bool = False      # 양식 제출이면 근거(칸 또는 문장) 최소 1개를 요구


class LinkIn(BaseModel):
    req_id: str
    met_criteria: list[int] = []


class ReportDecision(BaseModel):
    decision: str                 # confirm | cancel
    author: str | None = None
    summary: str | None = None
    links: list[LinkIn] = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    global CREATION_COUNT
    CREATION_COUNT += 1
    settings = get_settings()
    fast_llm, quality_llm = build_llms(settings)
    store = ProjectStore(settings.db_path)
    # MCP 서버는 별도 프로세스라 업무 DB 경로를 환경변수로 넘겨 같은 파일을 보게 한다.
    mcp = MCPClient(env={"DB_PATH": str(settings.db_path), "EMBEDDER": settings.embedder,
                         **({"ARTIFACT_ROOT": str(settings.artifact_root)} if settings.artifact_root else {})})
    await mcp.start()
    deps = SupervisorDeps(fast_llm=fast_llm, quality_llm=quality_llm, mcp=mcp, store=store,
                          session_store=SqliteSessionStore(settings.session_db_path),
                          settings=settings)
    app.state.deps = deps
    app.state.criteria_graph = build_criteria_graph(deps)
    app.state.intake_graph = build_intake_graph(deps)
    # 채팅 supervisor가 완료 보고를 넘길 하위 에이전트 — 완료 보고 탭과 같은 그래프·체크포인터
    deps.agents["intake"] = app.state.intake_graph
    app.state.chat_graph = build_chat_graph(deps)
    app.state.instance_id = id(deps)
    yield
    await mcp.stop()
    deps.session_store.close()
    store.close()
    try:   # 종료 전 LangSmith 배치 전송 플러시 — kill 시 run이 pending으로 남는 것 방지
        from langchain_core.tracers.langchain import wait_for_all_tracers
        wait_for_all_tracers()
    except Exception:
        pass


app = FastAPI(title="req-trace-agent", version=APP_VERSION, lifespan=lifespan)


@app.get("/health")
async def health():
    deps: SupervisorDeps = app.state.deps
    return {"status": "ok", "instance_id": app.state.instance_id,
            "creation_count": CREATION_COUNT,
            "project_name": deps.settings.project_name,
            "llm_backend": deps.settings.llm_backend,
            "fast_llm": deps.fast_llm.name, "quality_llm": deps.quality_llm.name,
            "mcp_servers": list(deps.mcp.sessions),
            "artifact_repo": deps.settings.artifact_repo_url or None,
            "artifact_branch": deps.settings.artifact_branch if deps.settings.artifact_repo_url else None,
            "artifact_root": (str(deps.settings.artifact_root)
                              if deps.settings.artifact_root and not deps.settings.artifact_repo_url else None),
            "counts": deps.store.counts()}


@app.get("/version")
async def version():
    return {"version": APP_VERSION}


def _metadata(result: dict, run_id: str | None) -> dict:
    return {"route": result.get("route"), "cost_usd": result.get("cost_usd", 0.0),
            "attempts": result.get("attempts", 0), "used_fallback": result.get("used_fallback", False),
            "tools": [c["tool"] for c in result.get("calls", [])],
            "llm_backend": app.state.deps.settings.llm_backend,
            "instance_id": app.state.instance_id, "langsmith_run_id": run_id}


@traceable(name="chat_request")
async def _handle_chat(message: str, thread_id: str, author: str) -> tuple[dict, str | None]:
    deps: SupervisorDeps = app.state.deps
    history = deps.session_store.load(thread_id)
    result = await app.state.chat_graph.ainvoke(initial_state(message, thread_id, history, author))
    deps.session_store.append(thread_id, "user", message)
    deps.session_store.append(thread_id, "assistant", result["final"])
    rt = get_current_run_tree()
    return result, (str(rt.id) if rt else None)


@app.post("/chat")
async def chat(req: ChatRequest):
    result, run_id = await _handle_chat(req.message, req.thread_id, req.author)
    return {"reply": result["final"], "events": result.get("events", []),
            "confirm": result.get("confirm") or None, "run_id": result.get("run_id") or None,
            "metadata": _metadata(result, run_id)}


def _sse(payload: dict | str) -> str:
    data = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return f"data: {data}\n\n"


async def _stream_graph(graph, state, result: dict, config: dict | None = None):
    """그래프 실행을 SSE 줄로 바꾼다. 노드별 진행 이벤트(updates)와 노드가 실행 중에 흘리는
    이벤트(custom: 답변 토큰, 건별 진행률)를 보낸다. 노드는 events 전체 목록을 돌려주므로
    지금까지 보낸 개수(sent) 뒤의 꼬리만 내보낸다. 마지막 상태 값은 result에 모은다.
    interrupt()로 멈추면 ConfirmRequired 이벤트로 확인할 내용을 보낸다."""
    sent = 0
    async for mode, payload in graph.astream(state, config, stream_mode=["updates", "custom"]):
        if mode == "custom":
            yield _sse(payload)
            continue
        if "__interrupt__" in payload:
            result["interrupted"] = True
            yield _sse({"type": "ConfirmRequired", **payload["__interrupt__"][0].value})
            continue
        for node_name, delta in payload.items():
            events = (delta or {}).get("events") or []
            for ev in events[sent:]:
                yield _sse({**ev, "node": node_name})
            sent = max(sent, len(events))
            result.update({k: v for k, v in (delta or {}).items() if v not in (None, "")})


@app.get("/chat/stream")
async def chat_stream(message: str, thread_id: str = "default", author: str = ""):
    """채팅을 SSE로 보낸다. 마지막에 FinalAnswer, [DONE] 순서. 완료 보고로 분류되면
    FinalAnswer에 확인 카드(confirm)와 실행 ID(run_id)가 실린다."""
    deps: SupervisorDeps = app.state.deps

    async def gen():
        history = deps.session_store.load(thread_id)
        result: dict = {}
        async for line in _stream_graph(app.state.chat_graph,
                                        initial_state(message, thread_id, history, author), result):
            yield line
        final = result.get("final", "")
        yield _sse({"type": "FinalAnswer", "reply": final, "prompt": result.get("last_prompt", ""),
                    "route": result.get("route"), "confirm": result.get("confirm") or None,
                    "run_id": result.get("run_id") or None})
        deps.session_store.append(thread_id, "user", message)
        deps.session_store.append(thread_id, "assistant", final)
        yield _sse("[DONE]")

    return StreamingResponse(gen(), media_type="text/event-stream")


# ── 요구사항 ────────────────────────────────────────────────────────────
@app.post("/requirements/upload")
async def upload_requirements(file: UploadFile = File(...)):
    """요구사항 명세서(xlsx/json)를 반영한다. 기존 요구사항은 지우지 않고 갱신한다."""
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "파일이 너무 큽니다(최대 5MB).")
    try:
        loaded = load_requirements(data, file.filename or "")
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:   # 손상된 엑셀 등
        raise HTTPException(400, f"파일을 읽지 못했습니다: {type(e).__name__}")
    if not loaded.requirements:
        raise HTTPException(400, {"message": "반영할 요구사항이 없습니다.", "warnings": loaded.warnings})
    diff = app.state.deps.store.upsert_requirements(loaded.requirements)
    return {**diff, "filename": file.filename, "warnings": loaded.warnings}


@app.get("/requirements")
async def list_requirements(category: str | None = None):
    return {"requirements": app.state.deps.store.list_requirements(category)}


@app.get("/requirements/{req_id}")
async def get_requirement(req_id: str):
    req = app.state.deps.store.get_requirement(req_id)
    if req is None:
        raise HTTPException(404, f"요구사항 {req_id}가 없습니다.")
    # AI 초안 중 원문 단어로 설명되지 않는 조건에 표시만 단다 — 확정할 때 눈여겨보라는 뜻.
    for c in req["criteria"]:
        c["beyond_source"] = c["origin"] == "ai" and beyond_source(req, c["text"])
    return req


@app.put("/requirements/{req_id}/criteria")
async def update_criteria(req_id: str, body: CriteriaUpdate):
    """완료 조건 목록 저장. confirm=true면 확정 — 이후 진척 계산의 기준이 된다."""
    try:
        items = app.state.deps.store.replace_criteria(
            req_id, [c.model_dump() for c in body.criteria], body.confirm)
    except KeyError:
        raise HTTPException(404, f"요구사항 {req_id}가 없습니다.")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"req_id": req_id, "criteria": items,
            "criteria_state": "confirmed" if body.confirm else "draft"}


@app.get("/criteria/draft/stream")
async def draft_criteria_stream(req_ids: str = "", overwrite: bool = False):
    """완료 조건 초안 생성(요구사항 등록 에이전트)을 SSE로 진행한다.
    req_ids를 비우면 조건이 없는 요구사항 전체가 대상이다. 마지막에 Done, [DONE] 순서."""
    ids = [r.strip() for r in req_ids.split(",") if r.strip()]

    async def gen():
        result: dict = {}
        async for line in _stream_graph(app.state.criteria_graph,
                                        initial_criteria_state(ids, overwrite), result):
            yield line
        yield _sse({"type": "Done", "saved": result.get("saved", []),
                    "failed": result.get("failed", {}), "cost_usd": result.get("cost_usd", 0.0)})
        yield _sse("[DONE]")

    return StreamingResponse(gen(), media_type="text/event-stream")


# ── 완료 보고 ──────────────────────────────────────────────────────────

@app.post("/reports/draft")
async def draft_report(body: ReportDraft):
    """완료 보고를 정리한다(SSE). 개발자 확인이 필요한 지점에서 ConfirmRequired를 보내고 멈춘다.
    확인·취소는 POST /reports/{run_id}/confirm."""
    if not body.author.strip() or not body.text.strip():
        raise HTTPException(400, "작성자와 보고 내용을 입력해 주세요.")
    evidence, errors = normalize_evidence([e.model_dump() for e in body.evidence])
    if errors:
        raise HTTPException(400, " / ".join(errors))
    store = app.state.deps.store
    unknown = [rid for rid in body.req_ids if not store.get_requirement(rid)]
    if unknown:
        raise HTTPException(400, f"등록되지 않은 요구사항: {', '.join(unknown)}")
    if body.require_evidence and not merge_evidence(evidence, body.text):
        raise HTTPException(400, "구현 근거(PR·커밋·API·테스트·파일·코드)를 최소 1개 입력해 주세요. "
                                 "검수 추적표의 '구현 근거'가 됩니다.")
    run_id = uuid.uuid4().hex[:12]

    async def gen():
        yield _sse({"type": "RunStarted", "run_id": run_id})
        result: dict = {}
        async for line in _stream_graph(app.state.intake_graph,
                                        initial_intake_state(body.author.strip(), body.text.strip(), evidence,
                                                             list(dict.fromkeys(body.req_ids))),
                                        result, intake_config(run_id)):
            yield line
        yield _sse("[DONE]")

    return StreamingResponse(gen(), media_type="text/event-stream")


class EvidencePreview(BaseModel):
    text: str


@app.post("/reports/evidence")
async def preview_evidence(body: EvidencePreview):
    """보고 문장에서 찾은 근거·요구사항 ID — 양식의 빈 칸을 미리 채우는 데 쓴다(AI 아님, 정규식)."""
    return {"evidence": extract_evidence(body.text),
            "req_ids": list(dict.fromkeys(REQ_ID_RE.findall(body.text)))}


@app.post("/reports/{run_id}/confirm")
async def confirm_report(run_id: str, body: ReportDecision):
    graph, config = app.state.intake_graph, intake_config(run_id)
    snapshot = await graph.aget_state(config)
    if "confirm" not in (snapshot.next or ()):
        raise HTTPException(404, "확인을 기다리는 보고가 없습니다(이미 처리됐거나 서버가 재시작됨).")
    if body.decision not in ("confirm", "cancel"):
        raise HTTPException(400, "decision은 confirm 또는 cancel이어야 합니다.")
    if body.decision == "confirm" and not (body.author or snapshot.values.get("author") or "").strip():
        raise HTTPException(400, "작성자 이름을 입력해 주세요.")
    if body.decision == "confirm":
        # 재개하기 전에 먼저 검증한다 — 저장 단계에서 실패하면 그래프가 save 직전에 멈춰
        # 다시 확인할 수 없게 되기 때문이다.
        try:
            app.state.deps.store.check_links([l.model_dump() for l in body.links])
        except ValueError as e:
            raise HTTPException(400, str(e))
    result = await graph.ainvoke(Command(resume=body.model_dump()), config)
    return {"report_id": result.get("report_id") or None, "changes": result.get("changes", []),
            "message": result.get("final", "")}


@app.get("/reports")
async def list_reports(limit: int = 20, author: str | None = None, req_id: str | None = None):
    return {"reports": app.state.deps.store.list_reports(limit, author, req_id=req_id)}


# ── 대시보드·검수용 추적표 ─────────────────────────────────────────────
def _check_date(as_of: str | None) -> str | None:
    if not as_of:
        return None
    try:
        datetime.fromisoformat(as_of)
    except ValueError:
        raise HTTPException(400, "기준일은 YYYY-MM-DD 형식이어야 합니다.")
    return as_of[:10]


@app.get("/dashboard")
async def dashboard(as_of: str | None = None, stale_days: int = 7):
    """진척 집계. as_of를 주면 그날까지의 보고만 반영한다(엑셀·채팅과 같은 함수)."""
    deps: SupervisorDeps = app.state.deps
    return {"project_name": deps.settings.project_name,
            **build_dashboard(deps.store, _check_date(as_of), stale_days, today=today_of(deps.settings))}


@app.get("/export/rtm.xlsx")
async def export_rtm_xlsx(as_of: str | None = None):
    """검수용 요구사항 추적표 엑셀(표지·요약 / 추적표 / 완료 보고 이력)."""
    deps: SupervisorDeps = app.state.deps
    as_of = _check_date(as_of)
    stamp = (as_of or today_of(deps.settings).isoformat()).replace("-", "")
    name = f"요구사항추적표_{stamp}.xlsx"
    out = deps.settings.output_dir / f"rtm_{stamp}_{datetime.now().strftime('%H%M%S')}.xlsx"
    export_rtm(deps.store, out, deps.settings.project_name, as_of, today=today_of(deps.settings))
    return FileResponse(out, filename=name,
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8100, log_level="warning")
