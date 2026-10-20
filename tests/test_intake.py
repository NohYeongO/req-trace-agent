"""완료 보고 정리 그래프 — 추출 → 후보(RAG) → 매핑 → 검증(반려·재매핑) → 근거 확인 → 확인(interrupt) → 저장."""
from langgraph.types import Command

from agent.graphs import build_intake_graph
from agent.state import initial_intake_state
from tools.seed_demo import seed_criteria

CFG = {"configurable": {"thread_id": "t1"}}
REPORT = ("보호자 검색은 성(lastName) 검색만 붙였습니다. GET /owners로 조회되고 OwnerController.listOwners를 "
          "수정했어요. 전화번호 검색은 아직입니다. OwnerControllerTests의 testListOwnersByLastName 통과.")


async def _until_confirm(deps, text, author="김민준"):
    seed_criteria(deps.store, force=False)
    g = build_intake_graph(deps)
    await g.ainvoke(initial_intake_state(author, text), CFG)
    return g, await g.aget_state(CFG)


async def test_maps_report_waits_for_developer_then_saves(deps):
    g, snap = await _until_confirm(deps, REPORT)
    assert snap.next == ("confirm",)                         # 저장 전에 멈춘다
    payload = snap.tasks[0].interrupts[0].value
    sfr5 = next(l for l in payload["links"] if l["req_id"] == "SFR-005")
    assert [c["met"] for c in sfr5["criteria"]] == [True, False]   # 성 검색만 충족
    assert {e["status"] for e in payload["evidence_check"]} == {"found"}
    assert deps.store.counts()["reports"] == 0
    assert "search_requirements" in deps.mcp.calls and "verify_evidence" in deps.mcp.calls

    met = [c["id"] for c in sfr5["criteria"] if c["met"]]
    result = await g.ainvoke(Command(resume={"decision": "confirm", "author": "김민준",
                                             "links": [{"req_id": "SFR-005", "met_criteria": met}]}), CFG)
    assert result["changes"] == [{"req_id": "SFR-005", "before": "미착수", "after": "부분완료",
                                  "met": 1, "total": 2}]
    saved = deps.store.list_reports()[0]
    assert saved["links"][0]["evidence_check"][0]["status"] == "found"


async def test_developer_edits_win_over_ai_suggestion(deps):
    g, snap = await _until_confirm(deps, REPORT)
    all5 = [c["id"] for c in deps.store.get_requirement("SFR-005")["criteria"]]
    result = await g.ainvoke(Command(resume={"decision": "confirm", "summary": "검색 전부 완료",
                                             "links": [{"req_id": "SFR-005", "met_criteria": all5}]}), CFG)
    assert result["changes"][0]["after"] == "완료"
    assert deps.store.list_reports()[0]["summary"] == "검색 전부 완료"


async def test_cancel_saves_nothing(deps):
    g, _ = await _until_confirm(deps, REPORT)
    result = await g.ainvoke(Command(resume={"decision": "cancel"}), CFG)
    assert "취소" in result["final"] and deps.store.counts()["reports"] == 0


async def test_fabricated_mapping_is_rejected_then_remapped(deps):
    # 후보에 SFR-009가 들어오면 FakeLLM이 첫 매핑에 ZZZ-999를 섞는다 → 검증 반려 → 재매핑
    _, snap = await _until_confirm(deps, "반려동물 종류 관리 API 완료. 반려동물 종류를 등록할 수 있다, 조회할 수 있다.")
    events = snap.values["events"]
    validated = [e for e in events if e["type"] == "MappingValidated"]
    assert validated[0]["retry"] and "ZZZ-999" in validated[0]["problems"][0]
    assert not validated[-1]["retry"]
    assert all(l["req_id"] != "ZZZ-999" for l in snap.values["links"])
    assert any(l["req_id"] == "SFR-009" for l in snap.values["links"])


async def test_mentioned_id_is_kept_for_developer_to_fill(deps):
    _, snap = await _until_confirm(deps, "SER-003 관련 작업 착수했습니다. 아직 끝난 건 없어요.")
    link = next(l for l in snap.values["links"] if l["req_id"] == "SER-003")
    assert link["met"] == [] and "고유번호" in link["reason"]
    assert snap.values["evidence"] == []
