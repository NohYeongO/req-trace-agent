"""MCP 실연동 — mcp_server.py를 실제 subprocess(stdio)로 띄워 Tool·Resource를 호출한다."""
import json
from datetime import datetime

from agent.mcp_client import MCPClient


async def test_trace_server_tools_and_resource(store, settings):
    store.conn.execute("INSERT INTO requirements(id, category, name, created_at) VALUES (?,?,?,?)",
                       ("SFR-001", "기능", "보호자 등록", datetime.now().isoformat()))
    store.conn.commit()

    mcp = MCPClient(env={"DB_PATH": str(settings.db_path)})
    await mcp.start()
    try:
        assert await mcp.find_tool("list_requirements") == "trace"
        status = await mcp.call_tool("get_store_status", {})
        assert status["counts"]["requirements"] == 1
        store.replace_criteria("SFR-001", [{"text": "보호자를 등록할 수 있다"}], confirm=True)
        req = await mcp.call_tool("get_requirement", {"req_id": "SFR-001"})
        assert req["name"] == "보호자 등록"
        assert req["criteria_state"] == "confirmed" and req["criteria"][0]["text"] == "보호자를 등록할 수 있다"
        listed = await mcp.call_tool("list_requirements", {"category": "기능"})
        assert listed["requirements"][0]["criteria_count"] == 1
        assert (await mcp.call_tool("list_requirements", {"category": "보안"}))["requirements"] == []
        missing = await mcp.call_tool("get_requirement", {"req_id": "SFR-999"})
        assert "error" in missing

        server, template = await mcp.find_resource_template("requirement_resource")
        assert template == "requirement://{req_id}"
        text = await mcp.read_resource("requirement://SFR-001", server)
        assert json.loads(text)["id"] == "SFR-001"
    finally:
        await mcp.stop()
