"""req-trace-agent — FastAPI 백엔드.

- lifespan에서 Agent 번들(업무 DB·세션 DB·LLM·MCP 연결·그래프)을 프로세스당 1회만 만들고
  app.state로 모든 요청이 공유한다(creation_count/instance_id로 확인 가능).
- mcp_server.py를 subprocess(stdio)로 기동해 서버 수명 동안 연결을 유지한다.
- GET /chat/stream — 그래프의 노드별 진행 상황과 답변 토큰을 SSE로 스트리밍한다.
- LangSmith: 요청당 chat_request 루트 run 아래로 노드·LLM·MCP 호출이 계층 기록된다.
"""
import json
from contextlib import asynccontextmanager

from dotenv import load_dotenv

load_dotenv()   # LANGCHAIN_* · LLM_BACKEND 등 — agent import보다 먼저

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from langsmith import traceable
from langsmith.run_helpers import get_current_run_tree
from pydantic import BaseModel

from agent.config import get_settings
from agent.deps import SupervisorDeps
from agent.graphs import build_chat_graph
from agent.llm import build_llms
from agent.mcp_client import MCPClient
from agent.state import initial_state
from agent.store import ProjectStore, SqliteSessionStore

APP_VERSION = "0.1.0"
CREATION_COUNT = 0   # 프로세스 내 Agent 번들 생성 횟수 (항상 1이어야 정상)


class ChatRequest(BaseModel):
    message: str
    thread_id: str = "default"


@asynccontextmanager
async def lifespan(app: FastAPI):
    global CREATION_COUNT
    CREATION_COUNT += 1
    settings = get_settings()
    fast_llm, quality_llm = build_llms(settings)
    store = ProjectStore(settings.db_path)
    # MCP 서버는 별도 프로세스라 업무 DB 경로를 환경변수로 넘겨 같은 파일을 보게 한다.
    mcp = MCPClient(env={"DB_PATH": str(settings.db_path)})
    await mcp.start()
    deps = SupervisorDeps(fast_llm=fast_llm, quality_llm=quality_llm, mcp=mcp, store=store,
                          session_store=SqliteSessionStore(settings.session_db_path),
                          settings=settings)
    app.state.deps = deps
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
            "counts": deps.store.counts()}


@app.get("/version")
async def version():
    return {"version": APP_VERSION}


def _metadata(result: dict, run_id: str | None) -> dict:
    return {"route": result.get("route"), "cost_usd": result.get("cost_usd", 0.0),
            "llm_backend": app.state.deps.settings.llm_backend,
            "instance_id": app.state.instance_id, "langsmith_run_id": run_id}


@traceable(name="chat_request")
async def _handle_chat(message: str, thread_id: str) -> tuple[dict, str | None]:
    deps: SupervisorDeps = app.state.deps
    history = deps.session_store.load(thread_id)
    result = await app.state.chat_graph.ainvoke(initial_state(message, thread_id, history))
    deps.session_store.append(thread_id, "user", message)
    deps.session_store.append(thread_id, "assistant", result["final"])
    rt = get_current_run_tree()
    return result, (str(rt.id) if rt else None)


@app.post("/chat")
async def chat(req: ChatRequest):
    result, run_id = await _handle_chat(req.message, req.thread_id)
    return {"reply": result["final"], "events": result.get("events", []),
            "metadata": _metadata(result, run_id)}


def _sse(payload: dict | str) -> str:
    data = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return f"data: {data}\n\n"


@app.get("/chat/stream")
async def chat_stream(message: str, thread_id: str = "default"):
    """노드별 진행 이벤트와 답변 토큰을 SSE로 보낸다. 마지막에 FinalAnswer, [DONE] 순서.

    노드는 events 전체 목록을 돌려주므로, 지금까지 보낸 개수(sent) 뒤의 꼬리만 내보낸다.
    """
    deps: SupervisorDeps = app.state.deps

    async def gen():
        history = deps.session_store.load(thread_id)
        sent, final, last_prompt = 0, "", ""
        async for mode, payload in app.state.chat_graph.astream(
                initial_state(message, thread_id, history), stream_mode=["updates", "custom"]):
            if mode == "custom":
                yield _sse(payload)
                continue
            for node_name, delta in payload.items():
                events = delta.get("events") or []
                for ev in events[sent:]:
                    yield _sse({**ev, "node": node_name})
                sent = max(sent, len(events))
                final = delta.get("final") or final
                last_prompt = delta.get("last_prompt") or last_prompt
        yield _sse({"type": "FinalAnswer", "reply": final, "prompt": last_prompt})
        deps.session_store.append(thread_id, "user", message)
        deps.session_store.append(thread_id, "assistant", final)
        yield _sse("[DONE]")

    return StreamingResponse(gen(), media_type="text/event-stream")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8100, log_level="warning")
