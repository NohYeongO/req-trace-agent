"""채팅 supervisor — 분류 후 대화·질의응답·요약·보고 정리 에이전트로 넘긴다."""
from langgraph.types import Command

from agent.graphs import build_chat_graph, build_intake_graph
from agent.graphs.intake import intake_config
from agent.state import initial_state
from tools.seed_demo import seed


async def _run(deps, query, history=None, author=""):
    return await build_chat_graph(deps).ainvoke(initial_state(query, "t1", history or [], author))


async def test_chat_route_answers_directly(deps):
    r = await _run(deps, "안녕, 너는 누구야?")
    assert r["route"] == "chat" and "진척 관리 도우미" in r["final"]
    assert [e["type"] for e in r["events"]] == ["RouteDecided", "Finalize"]
    assert deps.mcp.calls == []   # 가벼운 대화는 MCP를 부르지 않는다


async def test_chat_uses_session_history(deps):
    history = [{"role": "user", "content": "제 이름은 민수입니다"}, {"role": "assistant", "content": "반갑습니다."}]
    assert "민수" in (await _run(deps, "제 이름이 뭐였죠?", history))["final"]


async def test_status_answer_cites_tool_results(deps):
    seed(deps.store)
    r = await _run(deps, "SFR-005 남은 거 뭐야?")
    assert r["route"] == "status"
    assert set(deps.mcp.calls) == {"get_progress", "get_requirement"}
    types = [e["type"] for e in r["events"]]
    assert types == ["RouteDecided", "PlanCreated", "ToolsCalled", "AnswerValidated"]
    assert "SFR-005" in r["final"] and "1/2" in r["final"] and not r["used_fallback"]


async def test_hallucinated_number_is_rejected_then_rewritten(deps):
    seed(deps.store)
    r = await _run(deps, "SFR-009 어떻게 됐어?")   # FakeLLM이 첫 답에 사실에 없는 99.9%를 섞는다
    checks = [e for e in r["events"] if e["type"] == "AnswerValidated"]
    assert checks[0]["retry"] and "99.9" in checks[0]["problems"][0]
    assert not checks[-1]["problems"] and r["attempts"] == 2
    assert "99.9" not in r["final"]


async def test_fallback_when_llm_keeps_inventing(deps):
    class Liar:
        name = "liar"

        async def answer_status(self, query, facts, mode, feedback=None, on_token=None):
            return "SFR-005는 이미 77.7% 끝났습니다.", {"usd": 0.0}

    seed(deps.store)
    deps.quality_llm = Liar()
    r = await _run(deps, "SFR-005 남은 거 뭐야?")
    assert r["attempts"] == 3 and r["used_fallback"]
    assert r["final"].startswith("SFR-005 보호자 검색: 부분완료 (1/2)")


async def test_summary_reads_period_reports(deps):
    seed(deps.store)
    r = await _run(deps, "이번 주 완료된 거 정리해줘")
    assert r["route"] == "summary" and "list_reports" in deps.mcp.calls
    assert "이번 주 완료 보고 2건" in r["facts"]   # 10/19(월)~10/20 보고 2건


async def test_report_is_delegated_to_intake_agent(deps):
    seed(deps.store, reports=False)
    deps.agents["intake"] = build_intake_graph(deps)
    r = await _run(deps, "반려동물 종류 관리 API 완료했습니다. 반려동물 종류를 등록할 수 있다, 조회할 수 있다.",
                   author="김민준")
    assert r["route"] == "report" and r["run_id"] and r["confirm"]["author"] == "김민준"
    assert any(l["req_id"] == "SFR-009" for l in r["confirm"]["links"])
    assert deps.store.counts()["reports"] == 0                      # 확인 전에는 저장 안 함

    intake, cfg = deps.agents["intake"], intake_config(r["run_id"])
    ids = [c["id"] for c in deps.store.get_requirement("SFR-009")["criteria"]][:2]
    done = await intake.ainvoke(Command(resume={"decision": "confirm",
                                                "links": [{"req_id": "SFR-009", "met_criteria": ids}]}), cfg)
    assert done["changes"][0]["after"] == "부분완료"
