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
    r = await _run(deps, "SFR-018 남은 거 뭐야?")
    assert r["route"] == "status"
    assert set(deps.mcp.calls) == {"get_progress", "get_requirement", "list_reports"}
    types = [e["type"] for e in r["events"]]
    assert types == ["RouteDecided", "PlanCreated", "ToolsCalled", "AnswerValidated"]
    assert r["target"]["intent"] == "requirement"
    # 본문은 코드가 쓴다: 상태·충족 수·남은 조건. 그 뒤에 LLM 코멘트가 붙는다.
    assert r["final"].startswith("SFR-018 결제 처리는 부분완료 상태입니다. 완료 조건 3/4개를 충족했고 1개가 남았습니다.")
    assert "- 남은 조건: 실제 결제 대행사(PG)와 연동해 승인을 받는다" in r["final"]
    assert r["final"].endswith("남은 조건을 마무리하면 완료로 바뀝니다.") and not r["used_fallback"]


async def test_hallucinated_number_is_rejected_then_rewritten(deps):
    seed(deps.store)
    class OnceLiar:
        name = "once-liar"

        async def comment(self, query, core, feedback=None, on_token=None):
            text = "전체 진척률은 99.9%입니다." if feedback is None else "PG 연동만 남았습니다."
            return text, {"usd": 0.0}

    deps.quality_llm = OnceLiar()
    r = await _run(deps, "SFR-018 어떻게 됐어?")   # 첫 코멘트에 본문에 없는 99.9%를 섞는다
    checks = [e for e in r["events"] if e["type"] == "AnswerValidated"]
    assert checks[0]["retry"] and "99.9" in checks[0]["problems"][0]
    assert not checks[-1]["problems"] and r["attempts"] == 2
    assert "99.9" not in r["final"]


async def test_fallback_when_llm_keeps_inventing(deps):
    class Liar:
        name = "liar"

        async def comment(self, query, core, feedback=None, on_token=None):
            return "SFR-018은 이미 91.3% 끝났습니다.", {"usd": 0.0}

    seed(deps.store)
    deps.quality_llm = Liar()
    r = await _run(deps, "SFR-018 남은 거 뭐야?")
    assert r["attempts"] == 3 and r["used_fallback"]
    assert r["final"] == r["core"] and "91.3" not in r["final"]   # 코멘트를 빼고 본문만 준다


async def test_summary_reads_period_reports(deps):
    seed(deps.store)
    r = await _run(deps, "지난주 완료된 거 정리해줘")
    assert r["route"] == "summary" and "list_reports" in deps.mcp.calls
    assert r["target"]["period"][0] == "지난주"
    assert "완료 보고는 4건입니다." in r["core"]   # 3/2(월)~3/8 보고 4건(PR #7~#10)
    assert "작성자별: 박지훈 4건" in r["core"] and "SFR-019 조건 2개" in r["core"]


async def test_name_lookup_finds_requirement_without_id(deps):
    seed(deps.store)
    r = await _run(deps, "결제 기능 끝났어?")
    # 이름에 '결제'가 들어간 요구사항이 2건이라 둘 다 보여 준다
    assert r["target"]["intent"] == "lookup" and r["target"]["ids"] == ["SFR-018", "SFR-020"]
    assert r["final"].startswith("'결제' 관련 요구사항은 2건이고, 아직 완료된 것은 없습니다.")
    assert "- SFR-018 결제 처리 — 부분완료(3/4), 남은 조건: 실제 결제 대행사(PG)" in r["final"]
    r = await _run(deps, "장바구니 담기 끝났어?")                           # 더 많이 맞는 1건만
    assert r["target"]["ids"] == ["SFR-009"] and r["final"].startswith("SFR-009 장바구니 담기는 완료")


async def test_follow_up_carries_previous_target(deps):
    seed(deps.store)
    first = await _run(deps, "결제 기능 끝났어?")
    history = [{"role": "user", "content": "결제 기능 끝났어?"}, {"role": "assistant", "content": first["final"]}]
    r = await _run(deps, "남은 조건이 뭐야?", history)
    assert r["target"]["ids"] == ["SFR-018", "SFR-020"] and "PG" in r["final"]
    r = await _run(deps, "그럼 보안은?", [{"role": "user", "content": "품질 요구사항 진행률 알려줘"},
                                       {"role": "assistant", "content": "..."}])
    assert r["target"]["intent"] == "category" and r["final"].startswith("보안 요구사항은 3건 중 2건이 완료")


async def test_report_is_delegated_to_intake_agent(deps):
    seed(deps.store, reports=False)
    deps.agents["intake"] = build_intake_graph(deps)
    r = await _run(deps, "장바구니 담기 기능 완료했습니다. 상품을 장바구니에 담을 수 있다.", author="김민준")
    assert r["route"] == "report" and r["run_id"] and r["confirm"]["author"] == "김민준"
    assert any(l["req_id"] == "SFR-009" for l in r["confirm"]["links"])
    assert deps.store.counts()["reports"] == 0                      # 확인 전에는 저장 안 함

    intake, cfg = deps.agents["intake"], intake_config(r["run_id"])
    ids = [c["id"] for c in deps.store.get_requirement("SFR-009")["criteria"]][:1]
    done = await intake.ainvoke(Command(resume={"decision": "confirm",
                                                "links": [{"req_id": "SFR-009", "met_criteria": ids}]}), cfg)
    assert done["changes"][0]["after"] == "부분완료"
