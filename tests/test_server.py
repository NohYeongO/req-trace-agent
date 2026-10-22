"""서버 전체 조립 — lifespan(실제 MCP subprocess 포함)부터 /chat, /chat/stream까지."""
import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "fake")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "req_trace.db"))
    monkeypatch.setenv("SESSION_DB_PATH", str(tmp_path / "session.db"))
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")
    import server
    with TestClient(server.app) as c:
        yield c


def test_health_reports_singleton_and_mcp(client):
    h = client.get("/health").json()
    assert h["status"] == "ok" and h["creation_count"] >= 1
    assert h["mcp_servers"] == ["trace", "artifact"]
    assert h["counts"]["requirements"] == 0


def test_chat_and_session_memory(client):
    client.post("/chat", json={"message": "제 이름은 민수입니다", "thread_id": "s1"})
    r = client.post("/chat", json={"message": "제 이름이 뭐였죠?", "thread_id": "s1"}).json()
    assert "민수" in r["reply"]
    assert r["metadata"]["route"] == "chat"


def test_stream_sends_events_tokens_and_done(client):
    with client.stream("GET", "/chat/stream", params={"message": "안녕", "thread_id": "s2"}) as r:
        lines = [l[6:] for l in r.iter_lines() if l.startswith("data: ")]
    assert lines[-1] == "[DONE]"
    events = [json.loads(l) for l in lines[:-1]]
    types = [e["type"] for e in events]
    assert types[0] == "RouteDecided" and "AnswerToken" in types
    assert types[-1] == "FinalAnswer" and events[-1]["reply"]


def test_trace_config_keeps_run_config():
    """LangSmith 트레이스 이름·메타데이터를 붙여도 체크포인트 키(configurable)는 그대로다."""
    import server
    from agent.graphs.intake import intake_config
    cfg = server._trace("report_intake", intake_config("abc"), run_id="abc", author="")
    assert cfg["configurable"] == {"thread_id": "intake-abc"}
    assert cfg["run_name"] == "report_intake" and cfg["tags"] == ["report_intake"]
    assert cfg["metadata"] == {"run_id": "abc"}                    # 빈 값은 빼고 보낸다
    assert server._trace("deliverable:dev_spec")["tags"] == ["deliverable"]
