"""요구사항 API — 업로드 → 조회 → AI 초안(SSE) → 수정·확정, MCP Tool로 같은 데이터 조회."""
import json

import pytest
from fastapi.testclient import TestClient

from agent.config import DATA_DIR


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "fake")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "req_trace.db"))
    monkeypatch.setenv("SESSION_DB_PATH", str(tmp_path / "session.db"))
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")
    import server
    with TestClient(server.app) as c:
        yield c


def _upload(client, path):
    with open(path, "rb") as f:
        return client.post("/requirements/upload", files={"file": (path.name, f)})


def test_upload_list_draft_confirm_flow(client):
    r = _upload(client, DATA_DIR / "requirements" / "zerofive_requirements.xlsx")
    assert r.status_code == 200
    body = r.json()
    assert len(body["added"]) == 32 and body["warnings"] == []

    again = _upload(client, DATA_DIR / "requirements" / "zerofive_requirements.xlsx").json()
    assert again["added"] == [] and len(again["unchanged"]) == 32

    sec = client.get("/requirements", params={"category": "보안"}).json()["requirements"]
    assert [x["id"] for x in sec] == ["SER-001", "SER-002", "SER-003"]

    with client.stream("GET", "/criteria/draft/stream", params={"req_ids": "SFR-005,SFR-009"}) as s:
        events = [json.loads(l[6:]) for l in s.iter_lines() if l.startswith("data: {")]
    types = [e["type"] for e in events]
    assert types[0] == "CriteriaSelected" and types[-1] == "Done"
    assert types.count("CriteriaDrafted") == 3          # 2건 + 반려된 SFR-009 재작성 1건
    assert sorted(events[-1]["saved"]) == ["SFR-005", "SFR-009"]

    detail = client.get("/requirements/SFR-005").json()
    assert detail["criteria_state"] == "draft"
    assert all("beyond_source" in c for c in detail["criteria"])
    items = [{"id": c["id"], "text": c["text"]} for c in detail["criteria"]]
    items[0]["text"] = "등록된 상품을 페이지 단위로 조회할 수 있다"
    ok = client.put("/requirements/SFR-005/criteria", json={"criteria": items, "confirm": True})
    assert ok.status_code == 200 and ok.json()["criteria_state"] == "confirmed"
    assert ok.json()["criteria"][0]["origin"] == "human"
    assert client.get("/health").json()["counts"]["requirements"] == 32


def test_upload_and_edit_errors(client):
    bad = client.post("/requirements/upload", files={"file": ("a.csv", b"id,name")})
    assert bad.status_code == 400 and "지원하지 않는" in bad.json()["detail"]
    broken = client.post("/requirements/upload", files={"file": ("a.xlsx", b"not a zip")})
    assert broken.status_code == 400
    assert client.get("/requirements/SFR-001").status_code == 404
    assert client.put("/requirements/SFR-001/criteria",
                      json={"criteria": [{"text": "x"}], "confirm": True}).status_code == 404
