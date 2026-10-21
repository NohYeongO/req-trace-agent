"""질의응답 결정론 부분 — 도구 계획, 기간 해석, 사실 정리, 답변 검증, 대체 답변."""
from datetime import date

from agent.qa import build_facts, check_answer, fallback_answer, parse_period, plan_calls

TODAY = date(2026, 10, 20)   # 화요일


def test_parse_period():
    assert parse_period("이번 주 정리", TODAY) == ("이번 주", "2026-10-19", "2026-10-20")
    assert parse_period("지난주에 뭐 했어", TODAY) == ("지난주", "2026-10-12", "2026-10-18")
    assert parse_period("어제 보고", TODAY) == ("어제", "2026-10-19", "2026-10-19")
    assert parse_period("최근 3일", TODAY) == ("최근 3일", "2026-10-18", "2026-10-20")
    assert parse_period("이번 달", TODAY)[1] == "2026-10-01"
    assert parse_period("SFR-005 어때", TODAY) is None


def test_plan_calls():
    tools = lambda q, r="status": [(c["tool"], c["args"]) for c in plan_calls(q, r, TODAY)]
    assert tools("SFR-005랑 SER-002 남은 거") == [("get_progress", {}), ("get_requirement", {"req_id": "SFR-005"}),
                                               ("get_requirement", {"req_id": "SER-002"})]
    assert ("list_requirements", {"category": "보안"}) in tools("보안 요구사항 진행률")
    summary = tools("정리해줘", "summary")
    assert summary[-1] == ("list_reports", {"since": "2026-10-19", "until": "2026-10-20", "limit": 50})


def test_check_answer():
    facts = "[전체] 완료 17건, 진척률 58.6%, 충족 41/62개\n[요구사항 SFR-005] 충족 1/2, 남은 조건 1개, 완료일 2026-10-08"
    assert check_answer("SFR-005는 1/2 충족, 남은 조건 1개입니다.\n1. 진척률 58.60%", facts, "SFR-005") == []
    assert check_answer("10월 8일에 완료", facts, "") == []                       # 08 = 8
    assert check_answer("SFR-006은 60% 진행", facts, "") == ["사실에 없는 고유번호 SFR-006", "사실에 없는 숫자 60"]
    assert check_answer("SFR-404 상태 알려드릴게요", facts, "SFR-404 어때?") == []   # 질문에 나온 ID는 허용
    assert check_answer("", facts, "") == ["빈 답변"]


def test_facts_and_fallback_from_tool_results():
    req = {"id": "SFR-005", "name": "보호자 검색",
           "progress": {"status": "부분완료", "met": 1, "total": 2, "report_count": 1, "completed_at": None},
           "criteria": [{"text": "성 검색", "confirmed": True, "met_by": [5]},
                        {"text": "전화번호 검색", "confirmed": True, "met_by": []}]}
    results = [{"tool": "get_requirement", "args": {"req_id": "SFR-005"}, "result": req},
               {"tool": "get_requirement", "args": {"req_id": "SFR-404"}, "result": {"error": "없음"}}]
    facts = build_facts(results)
    assert "상태 부분완료, 충족 1/2, 남은 조건 1개" in facts and "미충족 — 전화번호 검색" in facts
    assert "SFR-404] 등록되지 않은 고유번호" in facts
    fb = fallback_answer(results)
    assert fb == "SFR-005 보호자 검색: 부분완료 (1/2). 남은 조건: 전화번호 검색"
    assert check_answer(fb, facts, "") == []


def test_date_variants_and_clean_answer():
    from agent.qa import clean_answer
    facts = "  - 2026-10-12 박지훈: 접근통제 (요구사항 SER-001)"
    assert check_answer("10.12에 박지훈님이 접근통제를 했습니다. 10월 12일 보고", facts, "") == []
    assert check_answer("박지훈님이 4건 보고", facts, "") == ["사실에 없는 숫자 4"]
    assert clean_answer("[질문 대상] 분류 보안의 보안 요구사항은 4건") == "보안 요구사항은 4건"
    assert clean_answer("[질문 대상]에 따르면, 아직 안 된 요구사항") == "아직 안 된 요구사항"
    assert check_answer("아직 chưa 완료", "x", "") == ["한국어가 아닌 표현 ư"]
