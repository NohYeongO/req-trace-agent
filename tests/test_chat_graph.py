from agent.graphs import build_chat_graph
from agent.state import initial_state


async def _run(deps, query, history=None):
    graph = build_chat_graph(deps)
    return await graph.ainvoke(initial_state(query, "t1", history or []))


async def test_chat_route_answers_directly(deps):
    r = await _run(deps, "안녕, 너는 누구야?")
    assert r["route"] == "chat"
    assert "진척 관리 도우미" in r["final"]
    assert [e["type"] for e in r["events"]] == ["RouteDecided", "Finalize"]
    assert deps.mcp.calls == []   # 가벼운 대화는 MCP를 부르지 않는다


async def test_chat_uses_session_history(deps):
    history = [{"role": "user", "content": "제 이름은 민수입니다"},
               {"role": "assistant", "content": "반갑습니다."}]
    r = await _run(deps, "제 이름이 뭐였죠?", history)
    assert "민수" in r["final"]


async def test_status_and_summary_routes_are_pending_for_now(deps):
    status = await _run(deps, "SFR-005 완료됐어?")
    summary = await _run(deps, "이번 주 완료된 거 정리해줘")
    assert status["route"] == "status" and "아직 연결되지 않았습니다" in status["final"]
    assert summary["route"] == "summary" and summary["events"][-1]["pipeline"] == "summary-pending"
