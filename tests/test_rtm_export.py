"""검수용 추적표 엑셀 — 시트 구성, 대시보드와 같은 숫자, 기준일, 사람이 확인한 데이터만."""
from datetime import date

from openpyxl import load_workbook

from agent.dashboard import build_dashboard
from agent.rtm_export import TRACE_COLUMNS, export_rtm
from tools.seed_demo import seed

TODAY = date(2026, 10, 20)


def _cells(ws, col):
    return [ws.cell(row=r, column=col).value for r in range(2, ws.max_row + 1)]


def test_workbook_matches_dashboard(store, tmp_path):
    seed(store)
    out = tmp_path / "rtm.xlsx"
    result = export_rtm(store, out, "데모 사업", today=TODAY)
    wb = load_workbook(out)
    assert wb.sheetnames == ["표지·요약", "요구사항 추적표", "완료 보고 이력"]

    summary = {r[0]: r[1] for r in wb["표지·요약"].iter_rows(min_row=3, max_row=9, values_only=True)}
    assert summary["사업명"] == "데모 사업" and summary["요구사항 수"] == 29
    assert summary["진척률(요구사항 기준)"].startswith("58.6%")
    assert summary["진척률(완료 조건 기준)"].startswith("66.1%")

    trace = wb["요구사항 추적표"]
    assert [c.value for c in trace[1]] == [h for h, _ in TRACE_COLUMNS]
    statuses = _cells(trace, 8)
    dash = build_dashboard(store, today=TODAY)
    assert {s: statuses.count(s) for s in dash["overall"]["counts"]} == dash["overall"]["counts"]
    assert result["overall"] == dash["overall"]
    assert trace.freeze_panes == "C2" and trace.auto_filter.ref == "A1:O30"

    row = {trace.cell(row=r, column=1).value: [c.value for c in trace[r]] for r in range(2, trace.max_row + 1)}
    sfr5 = row["SFR-005"]
    assert sfr5[5] == "✔ 성(last name)으로 보호자를 검색할 수 있다\n☐ 전화번호로 보호자를 검색할 수 있다"
    assert (sfr5[6], sfr5[7], sfr5[9]) == ("1/2", "부분완료", "김민준")
    assert "– [API] GET /owners" in sfr5[10]   # 산출물 경로 없이 시드 → 확인 불가 표시
    assert row["SER-003"][9] is None and row["SER-003"][7] == "미착수"   # 보고 없음
    assert wb["완료 보고 이력"].max_row - 1 == 19


def test_as_of_and_unconfirmed_criteria(store, tmp_path):
    seed(store)
    store.replace_criteria("SER-004", [{"text": "AI 초안 조건", "origin": "ai"}], confirm=False)
    out = tmp_path / "rtm.xlsx"
    export_rtm(store, out, "데모", as_of="2026-10-08", today=TODAY)
    wb = load_workbook(out)
    trace = wb["요구사항 추적표"]
    row = {trace.cell(row=r, column=1).value: [c.value for c in trace[r]] for r in range(2, trace.max_row + 1)}
    assert row["SER-004"][5] == "(완료 조건 미확정)" and row["SER-004"][7] == "조건 미확정"
    assert row["SFR-011"][7] == "미착수"          # 10/10 보고는 기준일 이후라 반영 안 됨
    assert wb["완료 보고 이력"].max_row - 1 == 7
    assert wb["표지·요약"]["B4"].value == "2026-10-08"
