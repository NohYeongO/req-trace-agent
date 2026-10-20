"""완료 보고 저장과 진척 계산 — 상태는 확정 조건 충족 여부로 코드가 계산한다."""
import pytest

from agent.requirements import Requirement


@pytest.fixture
def ids(store):
    store.upsert_requirements([Requirement("SFR-005", "기능", "보호자 검색", "성 또는 전화번호로 검색"),
                               Requirement("SFR-009", "기능", "종류 관리", ""),
                               Requirement("SER-002", "보안", "비밀번호 암호화", "")])
    c5 = store.replace_criteria("SFR-005", [{"text": "성으로 검색"}, {"text": "전화번호로 검색"}], True)
    c9 = store.replace_criteria("SFR-009", [{"text": "종류 등록", "origin": "ai"}], False)  # 미확정
    return [c["id"] for c in c5], [c["id"] for c in c9]


def test_progress_follows_confirmed_criteria(store, ids):
    c5, c9 = ids
    assert store.progress()["SFR-005"]["status"] == "미착수"
    assert store.progress()["SER-002"]["status"] == "조건 미확정"

    store.save_report("김민준", "성 검색 끝", "성 검색", [{"req_id": "SFR-005", "met_criteria": [c5[0]]}],
                      created_at="2026-10-06T10:00:00")
    p = store.progress()["SFR-005"]
    assert (p["status"], p["met"], p["total"], p["completed_at"]) == ("부분완료", 1, 2, None)

    store.save_report("김민준", "전화번호 검색 끝", "전화번호", [{"req_id": "SFR-005", "met_criteria": [c5[1]]},
                                                       {"req_id": "SFR-009", "met_criteria": c9}],
                      created_at="2026-10-08T09:00:00")
    p = store.progress()
    assert (p["SFR-005"]["status"], p["SFR-005"]["completed_at"]) == ("완료", "2026-10-08T09:00:00")
    assert p["SFR-009"]["status"] == "조건 미확정"   # 확정 전 조건은 진척에 안 씀
    # 기준일 진척: 10월 7일 기준으로는 부분완료
    assert store.progress(as_of="2026-10-07")["SFR-005"]["status"] == "부분완료"

    detail = store.get_requirement("SFR-005")
    assert [len(c["met_by"]) for c in detail["criteria"]] == [1, 1]
    assert store.list_requirements()[0]["status"] == "완료"


def test_save_report_validation(store, ids):
    c5, c9 = ids
    with pytest.raises(ValueError, match="조건이 아닌"):
        store.save_report("a", "b", "", [{"req_id": "SFR-005", "met_criteria": c9}])
    with pytest.raises(ValueError, match="없습니다"):
        store.save_report("a", "b", "", [{"req_id": "SFR-404", "met_criteria": []}])
    with pytest.raises(ValueError, match="중복"):
        store.check_links([{"req_id": "SFR-005"}, {"req_id": "SFR-005"}])
    with pytest.raises(ValueError, match="작성자"):
        store.save_report(" ", "b", "", [{"req_id": "SFR-005", "met_criteria": []}])
    assert store.counts()["reports"] == 0


def test_list_reports_filters(store, ids):
    c5, _ = ids
    store.save_report("김민준", "성 검색", "", [{"req_id": "SFR-005", "met_criteria": [c5[0]]}], "2026-10-01T10:00:00")
    store.save_report("이서연", "기타", "", [{"req_id": "SER-002", "met_criteria": []}], "2026-10-03T10:00:00")
    assert [r["author"] for r in store.list_reports()] == ["이서연", "김민준"]
    assert [r["author"] for r in store.list_reports(author="김민준")] == ["김민준"]
    assert [r["author"] for r in store.list_reports(since="2026-10-02")] == ["이서연"]
    assert [r["author"] for r in store.list_reports(until="2026-10-01")] == ["김민준"]
    assert store.list_reports(req_id="SFR-005")[0]["links"][0]["met_criteria"][0]["text"] == "성으로 검색"
