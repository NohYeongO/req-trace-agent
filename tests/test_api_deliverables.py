"""산출물 API — 자료 목록 → 초안(SSE) → 조회·수정(경고) → 확정(경고 확인) → docx. MCP 서버는 실제 subprocess."""
import io
import json
import zipfile

import pytest
from docx import Document
from fastapi.testclient import TestClient

from tests.conftest import FIXTURES


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "fake")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "req_trace.db"))
    monkeypatch.setenv("SESSION_DB_PATH", str(tmp_path / "session.db"))
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("ARTIFACT_ROOT", str(FIXTURES / "mini_artifact"))
    monkeypatch.setenv("ARTIFACT_REPO_URL", "")
    monkeypatch.setenv("INDEX_CACHE_DIR", str(tmp_path / "index"))
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")
    import server
    from tools.seed_demo import seed
    with TestClient(server.app) as c:
        seed(server.app.state.deps.store)
        yield c


def _draft(client, source):
    with client.stream("POST", "/deliverables/test-report/draft", json={"source": source}) as r:
        return [json.loads(l[6:]) for l in r.iter_lines() if l.startswith("data: {")]


def test_draft_review_confirm_docx(client):
    names = [s["source"] for s in client.get("/deliverables/sources").json()["sources"]]
    assert "demo:1차-2026-03-09" in names and "demo:2차-2026-03-10" in names

    events = _draft(client, "demo:1차-2026-03-09")
    types = [e["type"] for e in events]
    assert types[0] == "ResultsCollected" and "SectionToken" in types and types[-1] == "Done"
    doc_id = events[-1]["doc_id"]
    doc = client.get(f"/deliverables/{doc_id}").json()
    assert doc["status"] == "draft" and doc["warnings"] == {}
    assert [d["id"] for d in client.get("/deliverables").json()["documents"]] == [doc_id]

    # 담당자가 서술을 고친다 — 결과 자료에 없는 숫자를 넣으면 경고
    r = client.put(f"/deliverables/{doc_id}", json={"texts": {"opinion": "통과율은 90%이다."}})
    assert r.status_code == 200 and "사실에 없는 숫자 90" in r.json()["warnings"]["opinion"]
    assert client.put(f"/deliverables/{doc_id}", json={"texts": {"summary": "표 수정"}}).status_code == 400
    r = client.post(f"/deliverables/{doc_id}/confirm", json={"by": "이서연"})
    assert r.status_code == 409                                           # 경고가 있으면 확인 필요
    client.put(f"/deliverables/{doc_id}", json={"texts": {"opinion": "통과율은 76.5%이다. 환경 조치 후 재수행이 필요하다."}})
    r = client.post(f"/deliverables/{doc_id}/confirm", json={"by": "이서연"})
    assert r.status_code == 200 and r.json()["status"] == "confirmed"
    assert client.put(f"/deliverables/{doc_id}", json={"texts": {"opinion": "x"}}).status_code == 400

    r = client.get(f"/deliverables/{doc_id}/docx")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    d = Document(io.BytesIO(r.content))
    body = "\n".join(p.text for p in d.paragraphs)
    assert "76.5%이다. 환경 조치 후" in body and "※ 담당자 수정" in body


def test_upload_then_draft(client):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("build/test-results/test/TEST-a.CartAppServiceTest.xml",
                   '<testsuite name="c" tests="2" timestamp="2026-03-10T10:00:00">'
                   '<testcase name="담기" classname="a.CartAppServiceTest" time="0.1"/>'
                   '<testcase name="삭제" classname="a.CartAppServiceTest" time="0.1">'
                   '<failure message="expected 1 but was 2" type="org.opentest4j.AssertionFailedError"/></testcase>'
                   '</testsuite>')
    r = client.post("/deliverables/sources/upload", files={"file": ("results.zip", buf.getvalue(), "application/zip")})
    assert r.status_code == 200
    events = _draft(client, r.json()["source"])
    doc = client.get(f"/deliverables/{events[-1]['doc_id']}").json()["content"]
    rows = {s["id"]: s for s in doc["sections"]}
    assert rows["summary"]["rows"][-1] == ["합계", 2, 1, 1, 0, 0, "50.0%"]
    links = {x[0]: x for x in rows["req_links"]["rows"]}
    assert links["SFR-009"][5] == "실패 1건"
    bad = client.post("/deliverables/sources/upload", files={"file": ("x.txt", b"x", "text/plain")})
    assert bad.status_code == 400
