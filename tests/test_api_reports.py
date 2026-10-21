"""완료 보고 API — 정리(SSE, 확인 대기) → 확인 → 목록·진척 반영. MCP 서버 2개는 실제 subprocess."""
import json

import pytest
from fastapi.testclient import TestClient

from tests.conftest import FIXTURES


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "fake")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "req_trace.db"))
    monkeypatch.setenv("SESSION_DB_PATH", str(tmp_path / "session.db"))
    monkeypatch.setenv("ARTIFACT_ROOT", str(FIXTURES / "mini_artifact"))
    monkeypatch.setenv("INDEX_CACHE_DIR", str(tmp_path / "index"))
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")
    import server
    from tools.seed_demo import seed_criteria
    with TestClient(server.app) as c:
        seed_criteria(server.app.state.deps.store, force=False)
        yield c


def _draft(client, text, author="김민준"):
    with client.stream("POST", "/reports/draft", json={"author": author, "text": text}) as r:
        assert r.status_code == 200
        return [json.loads(l[6:]) for l in r.iter_lines() if l.startswith("data: {")]


def test_draft_confirm_and_progress(client):
    events = _draft(client, "회원가입 API 완료했습니다. 이메일·비밀번호·이름으로 회원 가입할 수 있고 "
                            "POST /owners와 OwnerControllerTests의 testCreateOwnerSuccess로 확인했습니다.")
    types = [e["type"] for e in events]
    assert types[0] == "RunStarted" and types[-1] == "ConfirmRequired"
    assert {"ReportExtracted", "CandidatesFound", "ReportMapped", "MappingValidated", "EvidenceChecked"} <= set(types)
    run_id, confirm = events[0]["run_id"], events[-1]
    link = next(l for l in confirm["links"] if l["req_id"] == "SFR-001")
    met = [c["id"] for c in link["criteria"] if c["met"]]
    assert met                                                 # 등록 조건이 충족으로 제안됨

    r = client.post(f"/reports/{run_id}/confirm",
                    json={"decision": "confirm", "links": [{"req_id": "SFR-001", "met_criteria": met}]})
    assert r.status_code == 200 and r.json()["report_id"]
    assert r.json()["changes"][0]["after"] in ("부분완료", "완료")
    reports = client.get("/reports").json()["reports"]
    assert reports[0]["author"] == "김민준" and reports[0]["links"][0]["req_id"] == "SFR-001"
    req = next(x for x in client.get("/requirements").json()["requirements"] if x["id"] == "SFR-001")
    assert req["report_count"] == 1

    again = client.post(f"/reports/{run_id}/confirm", json={"decision": "cancel"})
    assert again.status_code == 404                            # 이미 처리된 실행


def test_confirm_rejects_bad_links_without_losing_the_run(client):
    events = _draft(client, "쿠폰 등록 API 끝냈습니다. 쿠폰명·할인 금액·유형·발급 수량으로 쿠폰을 등록할 수 있다.")
    run_id = events[0]["run_id"]
    other = client.get("/requirements/SFR-001").json()["criteria"][0]["id"]
    bad = client.post(f"/reports/{run_id}/confirm",
                      json={"decision": "confirm", "links": [{"req_id": "SFR-011", "met_criteria": [other]}]})
    assert bad.status_code == 400 and "조건이 아닌" in bad.json()["detail"]
    ok = client.post(f"/reports/{run_id}/confirm", json={"decision": "cancel"})
    assert ok.status_code == 200                               # 반려 후에도 같은 실행을 처리할 수 있다


def test_draft_input_validation(client):
    assert client.post("/reports/draft", json={"author": " ", "text": "x"}).status_code == 400
    assert client.post("/reports/nope/confirm", json={"decision": "cancel"}).status_code == 404
