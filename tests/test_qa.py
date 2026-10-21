"""질의응답 결정론 부분 — 질문 분석, 도구 계획, 기간 해석, 답 본문, 코멘트 검증."""
from datetime import date

import pytest

from agent.answers import compose, josa, next_answer, pending_answer
from agent.qa import (analyze, check_answer, check_comment, clean_answer, keywords, match_by_name,
                      parse_period, plan_calls)
from agent.store import ProjectStore
from tools.seed_demo import seed

TODAY = date(2026, 10, 20)   # 화요일


def test_parse_period():
    assert parse_period("이번 주 정리", TODAY) == ("이번 주", "2026-10-19", "2026-10-20")
    assert parse_period("지난주에 뭐 했어", TODAY) == ("지난주", "2026-10-12", "2026-10-18")
    assert parse_period("어제 보고", TODAY) == ("어제", "2026-10-19", "2026-10-19")
    assert parse_period("최근 3일", TODAY) == ("최근 3일", "2026-10-18", "2026-10-20")
    assert parse_period("이번 달", TODAY)[1] == "2026-10-01"
    assert parse_period("SFR-005 어때", TODAY) is None


@pytest.mark.parametrize("q,route,intent", [
    ("SFR-018 남은 거 뭐야?", "status", "requirement"),
    ("결제 기능 끝났어?", "status", "lookup"),
    ("보안 요구사항 진행률 알려줘", "status", "category"),
    ("아직 안 된 요구사항 뭐 있어?", "status", "pending"),
    ("보안 쪽 미착수인 거 있어?", "status", "pending"),
    ("주의해야 할 요구사항 있어?", "status", "risks"),
    ("다음에 뭐부터 해야 해?", "status", "next"),
    ("박지훈님은 뭐 했어?", "status", "author"),
    ("전체 진척률 알려줘", "status", "overall"),
    ("지난주 정리해줘", "summary", "period"),
    ("정리해줘", "summary", "period"),
])
def test_analyze_intent(q, route, intent):
    assert analyze(q, route, TODAY)["intent"] == intent


def test_analyze_scope_and_follow_up():
    assert analyze("부분완료인 요구사항은?", "status", TODAY)["pending_scope"] == "partial"
    assert analyze("미착수 목록", "status", TODAY)["pending_scope"] == "not_started"
    hist = [{"role": "user", "content": "SFR-018 어떻게 됐어?"}, {"role": "assistant", "content": "..."}]
    t = analyze("남은 조건이 뭐야?", "status", TODAY, hist)
    assert t["intent"] == "requirement" and t["ids"] == ["SFR-018"] and t["carried_from"]
    # 이름으로 물었으면 직전 답에 나온 고유번호를 이어받는다(3개 이하일 때만)
    hist = [{"role": "user", "content": "결제 기능 끝났어?"}, {"role": "assistant", "content": "SFR-018 결제 처리는…"}]
    assert analyze("그럼 남은 거는?", "status", TODAY, hist)["ids"] == ["SFR-018"]
    # 새 대상이 있으면 이어받지 않는다
    assert analyze("그럼 보안은?", "status", TODAY, hist)["category"] == "보안"
    assert analyze("그럼 보안은?", "status", TODAY, hist)["ids"] == []


def test_plan_calls():
    tools = lambda q, r="status": [(c["tool"], c["args"]) for c in plan_calls(analyze(q, r, TODAY))]
    assert tools("SFR-005랑 SER-002 남은 거") == [
        ("get_progress", {}), ("get_requirement", {"req_id": "SFR-005"}),
        ("list_reports", {"req_id": "SFR-005", "limit": 3}),
        ("get_requirement", {"req_id": "SER-002"}), ("list_reports", {"req_id": "SER-002", "limit": 3})]
    assert tools("보안 요구사항 진행률") == [("get_progress", {})]       # 분류 집계는 get_progress에 있다
    assert tools("정리해줘", "summary")[-1] == ("list_reports", {"since": "2026-10-19", "until": "2026-10-20",
                                                                "limit": 50})
    assert tools("박지훈님은 뭐 했어?")[-1] == ("list_reports", {"limit": 200})


def test_keywords_and_name_match():
    reqs = [{"id": "SFR-009", "name": "장바구니 담기"}, {"id": "SFR-010", "name": "장바구니 수량 변경"},
            {"id": "SFR-018", "name": "결제 처리"}]
    assert keywords("장바구니 쪽은 다 됐어?") == ["장바구니"]
    assert match_by_name("장바구니 쪽은 다 됐어?", reqs) == ["SFR-009", "SFR-010"]
    assert match_by_name("결제 기능 끝났어?", reqs) == ["SFR-018"]
    assert match_by_name("장바구니 수량 바꾸는 거", reqs) == ["SFR-010"]   # 더 많이 맞는 것만
    assert match_by_name("날씨 어때", reqs) == []


def test_josa():
    assert josa("SFR-018 결제 처리", "은는") == "SFR-018 결제 처리는"
    assert josa("SFR-001 회원가입", "은는") == "SFR-001 회원가입은"
    assert josa("SFR-099", "은는") == "SFR-099는"
    assert josa("SFR-018", "은는") == "SFR-018은"


@pytest.fixture
def prog(tmp_path):
    from agent.dashboard import build_dashboard
    s = ProjectStore(tmp_path / "p.db")
    seed(s)
    d = build_dashboard(s, today=date(2026, 3, 10))
    yield d, s
    s.close()


def test_answers_from_seed(prog):
    d, s = prog
    cat = compose({"intent": "category", "category": "보안"}, [{"tool": "get_progress", "result": d}], "보안")
    assert cat.splitlines()[0] == "보안 요구사항은 3건 중 2건이 완료되어 진척률 66.7%입니다. 남은 요구사항은 미착수 1건입니다."
    assert "- SER-003 관리자 권한 제어 — 미착수 0/2 · 우선순위 상" in cat

    pend = pending_answer(d, "all", None)
    assert pend.splitlines()[0] == "아직 완료되지 않은 요구사항은 10건입니다(부분완료 2건, 미착수 8건)."
    assert pend.splitlines()[1].startswith("- SFR-018 결제 처리 — 부분완료 3/4")   # 부분완료·우선순위 상 먼저

    from agent.answers import overall_answer
    assert overall_answer(d).splitlines()[-1] == ("- 가장 많이 남은 분류는 기능(9건)입니다. "
                                                  "그중 우선순위 상은 SFR-005, SFR-006, SFR-018, SFR-020입니다.")

    nxt = next_answer(d).splitlines()
    assert nxt[1].startswith("1. SFR-018 결제 처리 — 우선순위 상, 부분완료(3/4)로 남은 조건 1개만")
    assert nxt[2].startswith("2. SER-003") or nxt[2].startswith("2. SFR-005")

    unknown = compose({"intent": "requirement", "ids": ["SFR-099"]},
                      [{"tool": "get_progress", "result": d},
                       {"tool": "get_requirement", "args": {"req_id": "SFR-099"}, "result": {"error": "없음"}}], "")
    assert unknown.startswith("SFR-099는 등록되지 않은 요구사항 고유번호입니다.")


def test_check_answer_and_comment():
    core = "SFR-005는 부분완료입니다. 완료 조건 1/2개를 충족했고, 최근 보고는 10월 8일입니다. 진척률 58.6%"
    assert check_answer("SFR-005는 1/2 충족, 진척률 58.60%", core, "") == []
    assert check_answer("SFR-006은 60% 진행", core, "") == ["사실에 없는 고유번호 SFR-006", "사실에 없는 숫자 60"]
    assert check_answer("SFR-404 상태 알려드릴게요", core, "SFR-404 어때?") == []   # 질문에 나온 ID는 허용
    assert check_answer("아직 chưa 완료", core, "") == ["한국어가 아닌 표현 ư"]
    assert check_comment("", core, "") == []                                          # 덧붙일 말이 없으면 통과
    assert check_comment("전화번호 검색만 남았으니 먼저 끝내시면 좋겠습니다.", core, "") == []
    assert check_comment("가" * 200, core, "")[0].startswith("너무 김")
    assert check_comment("- 할 일 1/2", core, "") == ["목록을 쓰지 말고 문장으로만"]
    assert clean_answer('코멘트: "PG 연동만 남았습니다."') == "PG 연동만 남았습니다."


def test_comment_claims_and_skip():
    from agent.qa import check_claims, needs_comment
    core = ("미완료 2건입니다.\n- SFR-018 결제 처리 — 부분완료 3/4 · 우선순위 상\n"
            "- SFR-004 배송지 관리 — 부분완료 1/3 · 우선순위 중")
    assert check_claims("우선순위 상인 SFR-018부터 마무리하세요.", core) == []
    assert check_claims("우선순위 상인 SFR-018, SFR-004를 먼저 하세요.", core) == [
        "SFR-004의 우선순위는 '중'인데 '상'로 씀"]
    assert check_claims("SFR-004는 미착수라 서둘러야 합니다.", core) == ["SFR-004의 상태는 '부분완료'인데 '미착수'로 씀"]
    assert not needs_comment({"intent": "requirement"}, "SFR-019 주문 내역 조회는 완료되었습니다.")
    assert not needs_comment({"intent": "requirement"}, "SFR-099는 등록되지 않은 요구사항 고유번호입니다.")
    assert needs_comment({"intent": "requirement"}, "SFR-018 결제 처리는 부분완료 상태입니다.")
    assert needs_comment({"intent": "period"}, "지난주 완료 보고는 4건입니다.")
    assert not needs_comment({"intent": "pending"}, core)          # 목록·집계 답의 해석은 본문이 맡는다
