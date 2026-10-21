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


def _draft(client, text, author="김민준", **form):
    with client.stream("POST", "/reports/draft", json={"author": author, "text": text, **form}) as r:
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
    base = {"author": "김민준", "text": "장바구니 담기 끝냈습니다."}
    r = client.post("/reports/draft", json={**base, "require_evidence": True})       # 양식: 근거 필수
    assert r.status_code == 400 and "최소 1개" in r.json()["detail"]
    r = client.post("/reports/draft", json={**base, "evidence": [{"type": "pr", "value": "열두번"}]})
    assert r.status_code == 400 and "PR" in r.json()["detail"]
    r = client.post("/reports/draft", json={**base, "req_ids": ["SFR-999"]})
    assert r.status_code == 400 and "SFR-999" in r.json()["detail"]


def test_form_evidence_and_selected_requirement(client):
    events = _draft(client, "장바구니 담기 끝냈습니다. 상품을 장바구니에 담을 수 있습니다. CartController.java 추가",
                    evidence=[{"type": "pr", "value": "12"}, {"type": "api", "value": "post /api/cart/items"}],
                    req_ids=["SFR-021"], require_evidence=True)
    extracted = next(e for e in events if e["type"] == "ReportExtracted")
    assert extracted["form_evidence"] == 2 and extracted["selected"] == ["SFR-021"]
    confirm = events[-1]
    sources = {(e["type"], e["value"]): e["source"] for e in confirm["evidence_check"]}
    assert sources[("pr", "#12")] == "form" and sources[("api", "POST /api/cart/items")] == "form"
    assert sources[("file", "CartController.java")] == "text"
    picked = next(l for l in confirm["links"] if l["req_id"] == "SFR-021")   # 선택한 요구사항은 카드에 들어감
    assert picked["reason"].startswith("작성자가 선택")


async def test_selected_requirement_kept_even_if_ai_skips(deps):
    """AI(여기서는 아무것도 매핑하지 않는 LLM)가 고르지 않아도 작성자가 고른 요구사항은 확인 카드에 넣는다."""
    from agent.graphs import build_intake_graph
    from agent.graphs.intake import intake_config
    from agent.state import initial_intake_state
    from tools.seed_demo import seed

    class NoMap:
        name = "nomap"

        async def summarize_report(self, text):
            return {"summary": "요약", "query": text}, {"usd": 0.0}

        async def map_report(self, text, candidates, procedure, feedback=None):
            return [], {"usd": 0.0}

    seed(deps.store, reports=False)
    deps.quality_llm = NoMap()
    g = build_intake_graph(deps)
    await g.ainvoke(initial_intake_state("김민준", "리뷰 기능 작업", [{"type": "pr", "value": "#3", "source": "form"}],
                                         ["SFR-021"]), intake_config("sel"))
    snap = await g.aget_state(intake_config("sel"))
    card = snap.tasks[0].interrupts[0].value
    assert [l["req_id"] for l in card["links"]] == ["SFR-021"]
    assert "AI는 충족한 조건을 찾지 못했습니다" in card["links"][0]["reason"]


def test_evidence_preview(client):
    r = client.post("/reports/evidence", json={"text": "SFR-010 수량 변경, PATCH /api/cart/items/{itemId}, PR #13"})
    assert r.json() == {"evidence": [{"type": "api", "value": "PATCH /api/cart/items/{itemId}"},
                                     {"type": "pr", "value": "#13"}], "req_ids": ["SFR-010"]}
    assert client.post("/reports/nope/confirm", json={"decision": "cancel"}).status_code == 404
