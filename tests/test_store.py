from datetime import datetime

from agent.store import ProjectStore


def test_schema_creates_empty_tables(store):
    assert store.counts() == {"requirements": 0, "criteria": 0, "reports": 0, "report_links": 0}


def test_requirement_queries(store):
    store.conn.execute("INSERT INTO requirements(id, category, name, created_at) VALUES (?,?,?,?)",
                       ("SFR-001", "기능", "보호자 등록", datetime.now().isoformat()))
    store.conn.commit()
    assert store.list_requirements() == [
        {"id": "SFR-001", "category": "기능", "name": "보호자 등록", "priority": "",
         "criteria_count": 0, "criteria_state": "none", "status": "조건 미확정", "met": 0,
         "total": 0, "completed_at": None, "report_count": 0}]
    assert store.get_requirement("SFR-001")["name"] == "보호자 등록"
    assert store.get_requirement("SFR-999") is None


def test_reopen_keeps_data(settings):
    s = ProjectStore(settings.db_path)
    s.conn.execute("INSERT INTO reports(author, raw_text, created_at) VALUES ('김개발', '완료', 'now')")
    s.conn.commit()
    s.close()
    s2 = ProjectStore(settings.db_path)
    assert s2.counts()["reports"] == 1
    s2.close()


def test_criteria_origin_is_constrained(store):
    import sqlite3

    import pytest
    store.conn.execute("INSERT INTO requirements(id, name, created_at) VALUES ('SFR-001','x','now')")
    with pytest.raises(sqlite3.IntegrityError):
        store.conn.execute("INSERT INTO criteria(req_id, seq, text, origin, created_at) "
                           "VALUES ('SFR-001', 1, '조건', 'robot', 'now')")


from agent.requirements import Requirement  # noqa: E402


def _reqs(*specs):
    return [Requirement(i, "기능", n, d) for i, n, d in specs]


def test_upsert_reports_diff_and_never_deletes(store):
    first = store.upsert_requirements(_reqs(("SFR-001", "보호자 등록", "a"), ("SFR-002", "조회", "b")))
    assert first["added"] == ["SFR-001", "SFR-002"] and first["total"] == 2

    store.replace_criteria("SFR-001", [{"text": "보호자를 등록할 수 있다"}], confirm=True)
    second = store.upsert_requirements(_reqs(("SFR-001", "보호자 등록", "a 변경"), ("SFR-003", "수정", "c")))
    assert second["added"] == ["SFR-003"]
    assert second["updated"] == ["SFR-001"]
    assert second["missing"] == ["SFR-002"]          # 파일에 없어도 지우지 않는다
    assert second["review_needed"] == ["SFR-001"]    # 확정 조건이 있는데 내용이 바뀜
    assert second["total"] == 3
    # 명세서의 행 순서를 따른다
    assert [r["id"] for r in store.list_requirements()][:2] == ["SFR-001", "SFR-003"]


def test_replace_criteria_keeps_ids_and_tracks_origin(store):
    store.upsert_requirements(_reqs(("SFR-005", "보호자 검색", "성 또는 전화번호로 검색")))
    v1 = store.replace_criteria("SFR-005", [{"text": "성으로 검색", "origin": "ai"},
                                            {"text": "전화번호로 검색", "origin": "ai"}], confirm=False)
    assert store.get_requirement("SFR-005")["criteria_state"] == "draft"

    # 첫 조건은 그대로, 둘째는 사람이 고치고, 셋째를 추가한 뒤 확정
    v2 = store.replace_criteria("SFR-005", [
        {"id": v1[0]["id"], "text": "성으로 검색"},
        {"id": v1[1]["id"], "text": "전화번호 뒷자리로 검색"},
        {"text": "검색 결과가 없으면 빈 목록을 반환한다"}], confirm=True)
    assert [c["id"] for c in v2[:2]] == [v1[0]["id"], v1[1]["id"]]   # id 유지
    assert [c["origin"] for c in v2] == ["ai", "human", "human"]
    assert all(c["confirmed"] for c in v2)
    assert store.list_requirements()[0]["criteria_state"] == "confirmed"

    v3 = store.replace_criteria("SFR-005", [{"id": v2[0]["id"], "text": "성으로 검색"}], confirm=True)
    assert len(v3) == 1 and store.counts()["criteria"] == 1   # 목록에서 빠진 조건은 삭제


def test_replace_criteria_rejects_bad_input(store):
    import pytest
    store.upsert_requirements(_reqs(("SFR-001", "보호자 등록", "")))
    with pytest.raises(ValueError):
        store.replace_criteria("SFR-001", [{"text": "  "}], confirm=False)
    with pytest.raises(ValueError):
        store.replace_criteria("SFR-001", [], confirm=True)
    with pytest.raises(KeyError):
        store.replace_criteria("SFR-999", [{"text": "x"}], confirm=False)


def test_migration_adds_seq_to_old_db(tmp_path):
    import sqlite3
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE requirements (id TEXT PRIMARY KEY, category TEXT NOT NULL DEFAULT '',"
                 " name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',"
                 " priority TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL)")
    conn.execute("INSERT INTO requirements(id, name, created_at) VALUES ('SFR-001', 'x', 'now')")
    conn.commit()
    conn.close()
    s = ProjectStore(path)
    assert s.list_requirements()[0]["id"] == "SFR-001"
    s.close()
