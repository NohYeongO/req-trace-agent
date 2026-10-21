import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "fake")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "req_trace.db"))
    monkeypatch.setenv("SESSION_DB_PATH", str(tmp_path / "session.db"))
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "out"))
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")
    monkeypatch.setenv("FIXED_TODAY", "2026-03-10")
    import server
    from tools.seed_demo import seed
    with TestClient(server.app) as c:
        seed(server.app.state.deps.store)
        yield c


def test_dashboard_and_export(client, tmp_path):
    d = client.get("/dashboard").json()
    assert d["overall"]["counts"]["완료"] == 22 and d["project_name"] and d["as_of"] == "2026-03-10"
    assert client.get("/dashboard", params={"as_of": "2026-02-20"}).json()["overall"]["counts"]["완료"] == 16
    assert client.get("/dashboard", params={"as_of": "10월 8일"}).status_code == 400

    r = client.get("/export/rtm.xlsx", params={"as_of": "2026-02-20"})
    assert r.status_code == 200
    assert "spreadsheetml" in r.headers["content-type"]
    assert "20260220.xlsx" in r.headers["content-disposition"]
    path = tmp_path / "dl.xlsx"
    path.write_bytes(r.content)
    assert load_workbook(path)["표지·요약"]["B4"].value == "2026-02-20"


async def test_mcp_get_progress_matches_dashboard(store, settings):
    from agent.mcp_client import MCPClient
    from tools.seed_demo import seed
    seed(store)
    mcp = MCPClient(env={"DB_PATH": str(settings.db_path), "EMBEDDER": "hash"})
    await mcp.start()
    try:
        p = await mcp.call_tool("get_progress", {})
        assert p["overall"]["counts"]["완료"] == 22 and "trend" not in p
        assert (await mcp.call_tool("get_progress", {"as_of": "2026-02-20"}))["overall"]["counts"]["완료"] == 16
    finally:
        await mcp.stop()
