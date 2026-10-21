"""진척 집계 — 시드 데이터(요구사항 29, 확정 조건 62, 보고 19)로 대시보드 숫자를 고정해 확인한다."""
from datetime import date

import pytest

from agent.dashboard import build_dashboard
from tools.seed_demo import seed

TODAY = date(2026, 3, 10)


@pytest.fixture
def seeded(store):
    seed(store)
    return store


def test_overall_and_groups(seeded):
    d = build_dashboard(seeded, today=TODAY)
    o = d["overall"]
    assert o["counts"] == {"완료": 22, "부분완료": 2, "미착수": 8, "조건 미확정": 0}
    assert (o["requirement_rate"], o["criteria_met"], o["criteria_total"], o["criteria_rate"]) == (68.8, 49, 63, 77.8)
    cat = {g["category"]: g for g in d["by_category"]}
    assert (cat["기능"]["total"], cat["기능"]["완료"], cat["보안"]["완료"], cat["품질"]["criteria_rate"]) == (22, 13, 2, 100.0)
    assert sum(g["total"] for g in d["by_priority"]) == 32


def test_authors_and_trend(seeded):
    d = build_dashboard(seeded, today=TODAY)
    authors = {a["author"]: a for a in d["by_author"]}
    assert {k: (v["reports"], v["criteria_met"]) for k, v in authors.items()} == {
        "박지훈": (5, 19), "이서연": (3, 16), "김민준": (3, 14)}
    assert sum(a["criteria_met"] for a in d["by_author"]) == d["overall"]["criteria_met"]
    assert d["trend"][0] == {"date": "2026-02-04", "requirements_done": 2, "criteria_met": 3}
    assert d["trend"][-1]["date"] == "2026-03-10" and d["trend"][-1]["requirements_done"] == 22
    assert all(a["requirements_done"] <= b["requirements_done"] for a, b in zip(d["trend"], d["trend"][1:]))


def test_risks(seeded):
    kinds = {(r["kind"], r["req_id"]) for r in build_dashboard(seeded, today=TODAY)["risks"]}
    assert kinds == {("부분완료 정체", "SFR-004"), ("중요 요구사항 미착수", "SFR-005"),
                     ("중요 요구사항 미착수", "SFR-006"), ("중요 요구사항 미착수", "SFR-020"),
                     ("중요 요구사항 미착수", "SER-003")}
    # 조건을 확정하지 않은 요구사항, 근거를 못 찾은 보고도 위험 신호로 잡는다
    seeded.replace_criteria("SFR-021", [{"text": "초안", "origin": "ai"}], confirm=False)
    sid = seeded.list_criteria("SFR-007")[0]["id"]
    seeded.save_report("김민준", "상품 검색", "", [{"req_id": "SFR-007", "met_criteria": [sid],
                       "evidence": [], "evidence_check": [{"type": "file", "value": "NoSuch.java",
                                                           "status": "not_found"}]}], "2026-03-10T09:00:00")
    kinds = {r["kind"] for r in build_dashboard(seeded, today=TODAY)["risks"]}
    assert {"조건 미확정", "근거 미확인 보고"} <= kinds


def test_as_of_snapshot(seeded):
    d = build_dashboard(seeded, as_of="2026-02-20", today=TODAY)
    assert d["overall"]["counts"]["완료"] == 16 and d["overall"]["reports"] == 7
    assert d["trend"][-1]["date"] == "2026-02-20"
    assert all(r["created_at"] <= "2026-02-20T99" for r in d["recent_reports"])


def test_empty_store(store):
    d = build_dashboard(store, today=TODAY)
    assert d["overall"]["requirements"] == 0 and d["trend"] == [] and d["risks"] == []
