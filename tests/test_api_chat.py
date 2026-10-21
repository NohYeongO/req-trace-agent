"""채팅 API — supervisor 분류, 질의응답 스트리밍, 채팅으로 받은 완료 보고의 확인·저장(MCP 실제 subprocess)."""
import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    for k, v in {"LLM_BACKEND": "fake", "DB_PATH": str(tmp_path / "req_trace.db"),
                 "SESSION_DB_PATH": str(tmp_path / "session.db"), "INDEX_CACHE_DIR": str(tmp_path / "idx"),
                 "FIXED_TODAY": "2026-03-10", "LANGCHAIN_TRACING_V2": "false"}.items():
        monkeypatch.setenv(k, v)
    import server
    from tools.seed_demo import seed
    with TestClient(server.app) as c:
        seed(server.app.state.deps.store)
        yield c


def test_status_stream_shows_agent_steps(client):
    with client.stream("GET", "/chat/stream", params={"message": "보안 요구사항 진행률 알려줘", "thread_id": "a"}) as r:
        events = [json.loads(l[6:]) for l in r.iter_lines() if l.startswith("data: {")]
    types = [e["type"] for e in events]
    assert types[0] == "RouteDecided" and events[0]["route"] == "status"
    assert {"PlanCreated", "ToolsCalled", "AnswerToken", "AnswerValidated"} <= set(types)
    plan = next(e for e in events if e["type"] == "PlanCreated")
    assert plan["intent"] == "category" and plan["tools"] == ["get_progress"]
    final = events[-1]
    assert final["type"] == "FinalAnswer" and final["route"] == "status" and final["confirm"] is None


def test_report_via_chat_then_confirm(client):
    r = client.post("/chat", json={"message": "쿠폰 등록 API 끝냈습니다. 쿠폰명·할인 금액·유형·발급 수량으로 쿠폰을 등록할 수 있다.",
                                   "thread_id": "b", "author": "이서연"}).json()
    assert r["metadata"]["route"] == "report" and r["run_id"] and r["confirm"]["links"]
    link = next(l for l in r["confirm"]["links"] if l["req_id"] == "SFR-011")
    met = [c["id"] for c in link["criteria"] if c["met"]]
    before = client.get("/reports").json()["reports"][0]["id"]
    done = client.post(f"/reports/{r['run_id']}/confirm",
                       json={"decision": "confirm", "links": [{"req_id": "SFR-011", "met_criteria": met}]})
    assert done.status_code == 200
    latest = client.get("/reports").json()["reports"][0]
    assert latest["id"] > before and latest["author"] == "이서연"


def test_report_via_chat_needs_author(client):
    r = client.post("/chat", json={"message": "쿠폰 등록 API 끝냈습니다.", "thread_id": "c"}).json()
    assert r["metadata"]["route"] == "report"
    bad = client.post(f"/reports/{r['run_id']}/confirm",
                      json={"decision": "confirm", "links": [{"req_id": "SFR-011", "met_criteria": []}]})
    assert bad.status_code == 400 and "작성자" in bad.json()["detail"]
    ok = client.post(f"/reports/{r['run_id']}/confirm",
                     json={"decision": "confirm", "author": "이서연",
                           "links": [{"req_id": "SFR-011", "met_criteria": []}]})
    assert ok.status_code == 200
