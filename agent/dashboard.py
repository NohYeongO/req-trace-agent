"""진척 집계 — 대시보드 화면, 검수용 추적표 엑셀, 채팅 질의응답이 모두 이 함수 하나를 쓴다.

같은 숫자가 화면·엑셀·답변에서 달라지지 않게 하기 위함이다. 모든 값은 업무 DB에 저장된
사실(확정된 완료 조건, 개발자가 확인한 완료 보고)에서 코드로 계산한다. LLM은 관여하지 않는다.

진척률은 두 가지로 낸다.
- 요구사항 기준: 완료 요구사항 수 / 조건이 확정된 요구사항 수
- 완료 조건 기준: 충족된 확정 조건 수 / 확정 조건 수 (부분완료의 진행 정도까지 반영)
"""
from collections import defaultdict
from datetime import date, datetime, timedelta

from .store.db import DONE, NOT_STARTED, PARTIAL, STATUSES, UNDEFINED, ProjectStore

HIGH_PRIORITY = {"상", "높음", "high", "1"}


def _rate(a: int, b: int) -> float:
    return round(100 * a / b, 1) if b else 0.0


def _day(ts: str) -> str:
    return ts[:10]


def build_dashboard(store: ProjectStore, as_of: str | None = None, stale_days: int = 7,
                    today: date | None = None) -> dict:
    """as_of(YYYY-MM-DD)를 주면 그날까지의 보고만 반영한 시점 진척을 만든다."""
    today = today or date.today()
    ref_day = date.fromisoformat(as_of) if as_of else today
    progress = store.progress(as_of)
    reqs = store.list_requirements()
    for r in reqs:   # list_requirements는 현재 기준이므로 시점 진척으로 덮어쓴다
        p = progress[r["id"]]
        r.update(status=p["status"], met=p["met"], total=p["total"],
                 completed_at=p["completed_at"], report_count=p["report_count"],
                 last_report_at=p["last_report_at"])
    reports = sorted(store.list_reports(limit=100000, until=as_of),
                     key=lambda x: (x["created_at"], x["id"]))

    # ── 전체 ──
    counts = {s: sum(1 for r in reqs if r["status"] == s) for s in STATUSES}
    defined = len(reqs) - counts[UNDEFINED]
    crit_total = sum(r["total"] for r in reqs)
    crit_met = sum(r["met"] for r in reqs)
    overall = {"requirements": len(reqs), "defined": defined, "counts": counts,
               "requirement_rate": _rate(counts[DONE], defined),
               "criteria_total": crit_total, "criteria_met": crit_met,
               "criteria_rate": _rate(crit_met, crit_total), "reports": len(reports)}

    # ── 분류별·우선순위별 ──
    def group(key: str) -> list[dict]:
        acc: dict[str, dict] = {}
        for r in reqs:
            g = acc.setdefault(r[key] or "(없음)", {key: r[key] or "(없음)", "total": 0,
                                                   "criteria_total": 0, "criteria_met": 0,
                                                   **{s: 0 for s in STATUSES}})
            g["total"] += 1
            g[r["status"]] += 1
            g["criteria_total"] += r["total"]
            g["criteria_met"] += r["met"]
        for g in acc.values():
            g["criteria_rate"] = _rate(g["criteria_met"], g["criteria_total"])
        return list(acc.values())

    # ── 담당자별: 보고 수, 다룬 요구사항, 처음 충족시킨 조건 수 ──
    confirmed = {c["id"] for r in reqs for c in store.list_criteria(r["id"]) if c["confirmed"]}
    first_met: dict[int, tuple[str, str]] = {}   # 조건 id → (충족일, 작성자)
    by_author: dict[str, dict] = {}
    for rep in reports:
        a = by_author.setdefault(rep["author"], {"author": rep["author"], "reports": 0,
                                                 "requirements": set(), "criteria_met": 0,
                                                 "last_report_at": None})
        a["reports"] += 1
        a["last_report_at"] = rep["created_at"]
        for link in rep["links"]:
            a["requirements"].add(link["req_id"])
            for c in link["met_criteria"]:
                if c["id"] in confirmed and c["id"] not in first_met:
                    first_met[c["id"]] = (_day(rep["created_at"]), rep["author"])
                    a["criteria_met"] += 1
    authors = [{**a, "requirements": sorted(a["requirements"])} for a in by_author.values()]
    authors.sort(key=lambda a: -a["criteria_met"])

    # ── 추이: 날짜별 누적 완료 요구사항·충족 조건 (burn-up) ──
    trend = []
    if reports:
        start = date.fromisoformat(_day(reports[0]["created_at"]))
        done_days = sorted(_day(r["completed_at"]) for r in reqs if r["completed_at"])
        met_days = sorted(d for d, _ in first_met.values())
        d = start
        while d <= ref_day:
            key = d.isoformat()
            trend.append({"date": key,
                          "requirements_done": sum(1 for x in done_days if x <= key),
                          "criteria_met": sum(1 for x in met_days if x <= key)})
            d += timedelta(days=1)

    # ── 위험 신호 ──
    risks = []
    stale_before = (ref_day - timedelta(days=stale_days)).isoformat()
    for r in reqs:
        base = {"req_id": r["id"], "name": r["name"], "status": r["status"]}
        if r["status"] == UNDEFINED:
            risks.append({**base, "kind": "조건 미확정",
                          "detail": "완료 조건이 확정되지 않아 진척을 계산할 수 없음"})
        elif r["status"] == NOT_STARTED and r["priority"] in HIGH_PRIORITY and not r["report_count"]:
            risks.append({**base, "kind": "중요 요구사항 미착수",
                          "detail": f"우선순위 '{r['priority']}'인데 완료 보고가 없음"})
        elif r["status"] == PARTIAL and _day(r["last_report_at"]) < stale_before:
            risks.append({**base, "kind": "부분완료 정체",
                          "detail": f"마지막 보고 {_day(r['last_report_at'])} 이후 {stale_days}일 넘게 진척 없음 "
                                    f"({r['met']}/{r['total']})"})
    unverified = [rep for rep in reports
                  if any(e.get("status") == "not_found"
                         for l in rep["links"] for e in l["evidence_check"])]
    for rep in unverified:
        missing = sorted({e["value"] for l in rep["links"] for e in l["evidence_check"]
                          if e.get("status") == "not_found"})
        risks.append({"req_id": ", ".join(l["req_id"] for l in rep["links"]), "name": "",
                      "status": "", "kind": "근거 미확인 보고",
                      "detail": f"보고 #{rep['id']}({rep['author']})의 근거를 산출물에서 찾지 못함: "
                                + ", ".join(missing)})

    return {"as_of": as_of or today.isoformat(), "generated_at": datetime.now().isoformat(timespec="seconds"),
            "overall": overall, "by_category": group("category"), "by_priority": group("priority"),
            "by_author": authors, "trend": trend, "risks": risks,
            "requirements": [{k: r[k] for k in ("id", "category", "name", "priority", "status", "met",
                                                "total", "completed_at", "report_count", "last_report_at")}
                             for r in reqs],
            "recent_reports": [{"id": r["id"], "author": r["author"], "created_at": r["created_at"],
                                "summary": r["summary"] or r["raw_text"][:60],
                                "req_ids": [l["req_id"] for l in r["links"]]}
                               for r in reversed(reports[-5:])]}
