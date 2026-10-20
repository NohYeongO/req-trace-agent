from datetime import datetime

from agent.store import ProjectStore


def test_schema_creates_empty_tables(store):
    assert store.counts() == {"requirements": 0, "criteria": 0, "reports": 0, "report_links": 0}


def test_requirement_queries(store):
    store.conn.execute("INSERT INTO requirements(id, category, name, created_at) VALUES (?,?,?,?)",
                       ("SFR-001", "기능", "보호자 등록", datetime.now().isoformat()))
    store.conn.commit()
    assert store.list_requirements() == [
        {"id": "SFR-001", "category": "기능", "name": "보호자 등록", "priority": ""}]
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
