"""완료 조건 초안 — 검증 규칙과 그래프(선택 → 작성 → 검증 → 재작성 → 저장)."""
from agent.criteria_rules import validate_criteria
from agent.graphs import build_criteria_graph
from agent.requirements import Requirement
from agent.state import initial_criteria_state

REQ = {"id": "SFR-005", "name": "보호자 검색", "description": "보호자를 성(last name) 또는 전화번호로 검색할 수 있어야 한다."}


def test_rules_accept_grounded_items():
    clean, problems = validate_criteria(REQ, ["1. 성(last name)으로 보호자를 검색할 수 있다",
                                              "- 전화번호로 보호자를 검색할 수 있다"])
    assert problems == []
    assert clean == ["성(last name)으로 보호자를 검색할 수 있다", "전화번호로 보호자를 검색할 수 있다"]


def test_rules_reject_added_content_duplicates_and_length():
    clean, problems = validate_criteria(REQ, [
        "전화번호로 보호자를 검색할 수 있다", "전화번호로 보호자를 검색할 수 있다",
        "블록체인 기반 위변조 방지 기능을 제공한다", "검색", "보" * 130])
    assert clean == ["전화번호로 보호자를 검색할 수 있다"]
    assert len(problems) == 4


def test_rules_reject_empty_and_too_many():
    assert validate_criteria(REQ, [])[1] == ["쓸 수 있는 조건이 하나도 없음"]
    many = [f"보호자 검색 조건 {i}번을 확인한다" for i in range(6)]
    assert "너무 많음" in validate_criteria(REQ, many)[1][0]


def _seed(store):
    store.upsert_requirements([
        Requirement("SFR-005", "기능", "보호자 검색", REQ["description"]),
        Requirement("SFR-009", "기능", "반려동물 종류 관리", "반려동물 종류(개, 고양이 등) 코드를 등록·조회·수정·삭제한다."),
        Requirement("SFR-010", "기능", "진료 방문 기록 등록", "진료 방문 일자와 진료 내용을 등록한다."),
    ])
    store.replace_criteria("SFR-010", [{"text": "진료 방문 일자를 등록한다"}], confirm=True)


async def test_graph_drafts_validates_redrafts_and_saves(deps):
    _seed(deps.store)
    graph = build_criteria_graph(deps)
    r = await graph.ainvoke(initial_criteria_state([], overwrite=False))

    types = [e["type"] for e in r["events"]]
    assert types == ["CriteriaSelected", "CriteriaValidated", "CriteriaValidated", "CriteriaSaved"]
    sel = r["events"][0]
    assert sel["count"] == 2 and sel["skipped"] == ["SFR-010"]   # 확정된 조건은 건드리지 않음
    # FakeLLM은 ID가 9로 끝나면 첫 초안에 무관한 조건을 섞는다 → 반려 → 재작성으로 통과
    assert r["events"][1]["rejected"] == ["SFR-009"]
    assert r["events"][2]["rejected"] == []
    assert sorted(r["saved"]) == ["SFR-005", "SFR-009"] and r["failed"] == {}

    saved = deps.store.get_requirement("SFR-009")
    assert saved["criteria_state"] == "draft"
    assert all(c["origin"] == "ai" and not c["confirmed"] for c in saved["criteria"])
    assert not any("블록체인" in c["text"] for c in saved["criteria"])
    assert deps.store.get_requirement("SFR-010")["criteria"][0]["text"] == "진료 방문 일자를 등록한다"


async def test_graph_overwrite_only_touches_drafts(deps):
    _seed(deps.store)
    deps.store.replace_criteria("SFR-005", [{"text": "예전 초안", "origin": "ai"}], confirm=False)
    graph = build_criteria_graph(deps)
    r = await graph.ainvoke(initial_criteria_state(["SFR-005", "SFR-010", "SFR-404"], overwrite=True))
    sel = r["events"][0]
    assert sel["count"] == 1 and sel["skipped"] == ["SFR-010"] and sel["unknown"] == ["SFR-404"]
    assert "예전 초안" not in [c["text"] for c in deps.store.get_requirement("SFR-005")["criteria"]]


async def test_graph_gives_up_after_retry_limit(deps):
    """매번 무관한 조건만 내는 모델 → 재시도 상한 후 실패로 기록하고 저장하지 않는다."""
    class Stubborn:
        name = "stubborn"

        async def draft_criteria(self, req, feedback=None):
            return ["블록체인 기반 위변조 방지 기능을 제공한다"], {"usd": 0.0}

    _seed(deps.store)
    deps.quality_llm = Stubborn()
    r = await build_criteria_graph(deps).ainvoke(initial_criteria_state(["SFR-005"], False))
    assert r["attempts"] == 2 and r["saved"] == []
    assert "요구사항에 없는 내용" in r["failed"]["SFR-005"]
    assert deps.store.get_requirement("SFR-005")["criteria_state"] == "none"


async def test_graph_isolates_llm_errors(deps):
    class Flaky:
        name = "flaky"

        async def draft_criteria(self, req, feedback=None):
            if req["id"] == "SFR-005":
                raise TimeoutError("ollama 응답 없음")
            return [f"{req['name']} 코드를 등록할 수 있다"], {"usd": 0.0}

    _seed(deps.store)
    deps.quality_llm = Flaky()
    r = await build_criteria_graph(deps).ainvoke(initial_criteria_state([], False))
    assert r["saved"] == ["SFR-009"]
    assert "TimeoutError" in r["failed"]["SFR-005"]


async def test_graph_with_nothing_to_do_ends_quietly(deps):
    r = await build_criteria_graph(deps).ainvoke(initial_criteria_state([], False))
    assert [e["type"] for e in r["events"]] == ["CriteriaSelected"]


def test_beyond_source_flags_padding_not_grounded_items():
    from agent.criteria_rules import beyond_source
    req = {"id": "SER-003", "name": "로그인 실패 시 계정 잠금", "description": "로그인 5회 연속 실패 시 해당 계정을 잠금 처리한다."}
    assert not beyond_source(req, "로그인 5회 연속 실패 시 해당 계정을 잠금 처리한다")
    # 실제 qwen3:8b가 첫 프롬프트에서 덧붙였던 조건들
    assert beyond_source(req, "계정 잠금 후 일정 시간 경과 시 자동 해제한다")
    assert beyond_source(req, "계정 잠금 시 사용자에게 알림을 제공한다")
