"""질문 유형별 답 본문 — 조회 결과(MCP Tool)로 코드가 직접 쓴다.

숫자·고유번호·상태는 모두 여기서 나온다. LLM은 이 본문 뒤에 짧은 코멘트만 붙인다(qa_write).
채팅 화면은 마크다운을 그리지 않으므로(white-space: pre-wrap) 굵게 표시(**) 없이 문장과
'-' 목록만 쓴다.
"""
from .store.db import DONE, NOT_STARTED, PARTIAL, UNDEFINED

_PRIORITY = {"상": 0, "중": 1, "하": 2}


# ── 표현 도우미 ──────────────────────────────────────────────────────────
_DIGIT_BATCHIM = {"0": True, "1": True, "2": False, "3": True, "4": False,
                  "5": False, "6": True, "7": True, "8": True, "9": False}


def _has_batchim(word: str) -> bool:
    ch = word.rstrip(" )")[-1:] or "가"
    if "가" <= ch <= "힣":
        return (ord(ch) - 0xAC00) % 28 != 0
    if ch.isdigit():
        return _DIGIT_BATCHIM[ch]
    return False


def josa(word: str, pair: str) -> str:
    """'은는', '이가', '을를', '과와' — 앞말 받침에 맞는 조사를 붙인다."""
    return word + (pair[0] if _has_batchim(word) else pair[1])


def day(iso: str | None) -> str:
    """'2026-03-07T10:16:00' → '3월 7일'"""
    if not iso:
        return ""
    _, m, d = iso[:10].split("-")
    return f"{int(m)}월 {int(d)}일"


def _label(r: dict) -> str:
    return f"{r['id']} {r['name']}"


def _short(r: dict) -> str:
    """목록 한 줄: 'SFR-018 결제 처리 — 부분완료 3/4 · 우선순위 상'"""
    state = r["status"] if r["status"] in (DONE, UNDEFINED) else f"{r['status']} {r['met']}/{r['total']}"
    return f"- {_label(r)} — {state} · 우선순위 {r['priority']}"


def _by_tool(results: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for r in results:
        out.setdefault(r["tool"], []).append(r)
    return out


def _ordered(rows: list[dict]) -> list[dict]:
    """부분완료 먼저, 그다음 우선순위 상→하, 같은 순위는 고유번호 순."""
    return sorted(rows, key=lambda r: (r["status"] != PARTIAL, _PRIORITY.get(r["priority"], 3), r["id"]))


# ── 유형별 본문 ──────────────────────────────────────────────────────────
def requirement_detail(d: dict, reports: list[dict], risks: list[dict]) -> str:
    p = d["progress"]
    name = _label(d)
    crit = [c for c in d["criteria"] if c["confirmed"]]
    left = [c["text"] for c in crit if not c["met_by"]]
    met = [c["text"] for c in crit if c["met_by"]]
    status = p["status"]
    if status == UNDEFINED:
        lines = [f"{josa(name, '은는')} 완료 조건이 아직 확정되지 않아 진척을 계산할 수 없습니다.",
                 "- 요구사항 탭에서 완료 조건을 확정하면 완료 보고와 연결됩니다."]
    elif status == DONE:
        lines = [f"{josa(name, '은는')} 완료되었습니다. 완료 조건 {p['met']}/{p['total']}개를 모두 충족했고, "
                 f"완료일은 {day(p['completed_at'])}입니다."]
    elif status == PARTIAL:
        lines = [f"{josa(name, '은는')} 부분완료 상태입니다. 완료 조건 {p['met']}/{p['total']}개를 충족했고 "
                 f"{p['total'] - p['met']}개가 남았습니다."]
        lines += [f"- 남은 조건: {t}" for t in left]
        lines += [f"- 충족한 조건: {t}" for t in met]
    else:
        left_txt = f"완료 조건 {p['total']}개가 모두 남아 있습니다." if p["total"] > 1 else "완료 조건이 그대로 남아 있습니다."
        lines = [f"{josa(name, '은는')} 아직 미착수입니다(우선순위 {d['priority']}). 완료 보고가 없고 {left_txt}"]
        lines += [f"- 해야 할 조건: {t}" for t in left]
    if reports:
        r = reports[0]
        lines.append(f"- 최근 보고: {day(r['created_at'])} {r['author']} — {r['summary']}")
    for k in risks:
        if k["req_id"] == d["id"] and status != DONE:
            lines.append(f"- 주의: {k['kind']} — {k['detail']}")
    return "\n".join(lines)


def requirement_list(header: str, details: list[dict]) -> str:
    lines = [header]
    for d in details:
        p = d["progress"]
        left = [c["text"] for c in d["criteria"] if c["confirmed"] and not c["met_by"]]
        if p["status"] == DONE:
            lines.append(f"- {_label(d)} — 완료({p['met']}/{p['total']}, {day(p['completed_at'])})")
        elif p["status"] == UNDEFINED:
            lines.append(f"- {_label(d)} — 조건 미확정")
        else:
            lines.append(f"- {_label(d)} — {p['status']}({p['met']}/{p['total']}), 남은 조건: {', '.join(left)}")
    return "\n".join(lines)


def category_answer(prog: dict, category: str) -> str:
    g = next((x for x in prog["by_category"] if x["category"] == category), None)
    if g is None or not g["total"]:
        return f"{category} 분류에 등록된 요구사항이 없습니다."
    rate = round(100 * g[DONE] / g["total"], 1)
    lines = [f"{category} 요구사항은 {g['total']}건 중 {g[DONE]}건이 완료되어 진척률 {rate}%입니다."]
    rest = [x for x in prog["requirements"] if x["category"] == category and x["status"] != DONE]
    if rest:
        parts = [f"{s} {n}건" for s in (PARTIAL, NOT_STARTED, UNDEFINED)
                 if (n := sum(x["status"] == s for x in rest))]
        lines[0] += f" 남은 요구사항은 {', '.join(parts)}입니다."
    else:
        lines[0] += " 모두 완료되었습니다."
    lines.append(f"완료 조건 기준으로는 {g['criteria_met']}/{g['criteria_total']}개를 충족해 {g['criteria_rate']}%입니다.")
    lines += [_short(x) for x in _ordered(rest)]
    return "\n".join(lines)


def overall_answer(prog: dict) -> str:
    o, c = prog["overall"], prog["overall"]["counts"]
    lines = [f"전체 요구사항 {o['requirements']}건 중 {c[DONE]}건이 완료되어 진척률은 {o['requirement_rate']}%입니다"
             f"(부분완료 {c[PARTIAL]}건, 미착수 {c[NOT_STARTED]}건).",
             f"완료 조건 기준으로는 {o['criteria_met']}/{o['criteria_total']}개를 충족해 {o['criteria_rate']}%입니다."]
    if c[UNDEFINED]:
        lines.append(f"완료 조건이 확정되지 않은 요구사항 {c[UNDEFINED]}건은 진척 계산에서 빠져 있습니다.")
    lines.append("- 분류별 완료: " + ", ".join(f"{g['category']} {g[DONE]}/{g['total']}"
                                              for g in prog["by_category"] if g["total"]))
    left = [(g["total"] - g[DONE], g["category"]) for g in prog["by_category"] if g["total"] > g[DONE]]
    if left:
        n, cat = max(left)
        top = [x for x in prog["requirements"] if x["category"] == cat and x["status"] != DONE
               and x["priority"] == "상"]
        lines.append(f"- 가장 많이 남은 분류는 {cat}({n}건)입니다."
                     + (f" 그중 우선순위 상은 {', '.join(x['id'] for x in top)}입니다." if top else ""))
    else:
        lines.append("- 모든 분류의 요구사항이 완료되었습니다.")
    return "\n".join(lines)


def pending_answer(prog: dict, scope: str, category: str | None) -> str:
    wanted = {"partial": {PARTIAL}, "not_started": {NOT_STARTED}}.get(scope, {PARTIAL, NOT_STARTED, UNDEFINED})
    rows = [x for x in prog["requirements"] if x["status"] in wanted and (not category or x["category"] == category)]
    where = f"{category} 요구사항 중 " if category else ""
    kind = {"partial": "부분완료인", "not_started": "미착수인"}.get(scope, "아직 완료되지 않은")
    if not rows:
        return f"{where}{kind} 요구사항은 없습니다."
    head = f"{where}{kind} 요구사항은 {len(rows)}건입니다."
    if scope == "all":
        parts = [f"{s} {n}건" for s in (PARTIAL, NOT_STARTED, UNDEFINED) if (n := sum(x["status"] == s for x in rows))]
        head = head[:-1] + f"({', '.join(parts)})."
    return "\n".join([head] + [_short(x) for x in _ordered(rows)])


def risks_answer(prog: dict) -> str:
    risks = prog["risks"]
    if not risks:
        return "현재 주의가 필요한 요구사항은 없습니다. 정체된 부분완료나 우선순위 '상' 미착수 항목이 없습니다."
    lines = [f"주의가 필요한 요구사항이 {len(risks)}건 있습니다."]
    lines += [f"- {k['req_id']} {k['name']} — {k['kind']}: {k['detail']}" for k in risks]
    return "\n".join(lines)


def next_answer(prog: dict, limit: int = 5) -> str:
    """다음 우선순위 제안. 규칙: 우선순위 상 부분완료 → 우선순위 상 미착수 → 정체된 부분완료 → 나머지."""
    stale = {k["req_id"] for k in prog["risks"] if k["kind"].startswith("부분완료")}
    rows = [x for x in prog["requirements"] if x["status"] in (PARTIAL, NOT_STARTED)]
    if not rows:
        return "남은 요구사항이 없습니다. 모든 요구사항이 완료되었습니다."

    def rank(x):
        hi = x["priority"] == "상"
        order = (0 if hi and x["status"] == PARTIAL else 1 if hi else 2 if x["id"] in stale
                 else 3 if x["status"] == PARTIAL else 4)
        return order, _PRIORITY.get(x["priority"], 3), x["id"]

    lines = ["남은 일 가운데 다음 순서로 진행하는 것을 제안합니다."]
    for i, x in enumerate(sorted(rows, key=rank)[:limit], 1):
        if x["status"] == PARTIAL:
            why = f"부분완료({x['met']}/{x['total']})로 남은 조건 {x['total'] - x['met']}개만 끝내면 완료됩니다"
            if x["id"] in stale:
                why += ". 최근 진척이 멈춰 있습니다"
        else:
            why = "아직 미착수입니다"
        lines.append(f"{i}. {_label(x)} — 우선순위 {x['priority']}, {why}.")
    lines.append("기준: 우선순위 '상'의 마무리 작업 → '상' 미착수 → 정체된 부분완료 → 나머지 순.")
    return "\n".join(lines)


def author_answer(prog: dict, query: str, reports: list[dict]) -> str:
    authors = prog["by_author"]
    named = [a for a in authors if a["author"] in query]
    if not named:
        if not authors:
            return "아직 확인된 완료 보고가 없어 담당자별 실적이 없습니다."
        lines = [f"완료 보고를 올린 담당자는 {len(authors)}명입니다."]
        lines += [f"- {a['author']}: 완료 보고 {a['reports']}건, 처음 충족시킨 완료 조건 {a['criteria_met']}개"
                  for a in authors]
        return "\n".join(lines)
    out = []
    for a in named:
        mine = [r for r in reports if r["author"] == a["author"]][:3]
        out.append(f"{a['author']}님은 완료 보고 {a['reports']}건을 올렸고, 완료 조건 {a['criteria_met']}개를 "
                   f"처음 충족시켰습니다.")
        out.append(f"- 다룬 요구사항({len(a['requirements'])}건): {', '.join(a['requirements'])}")
        out += [f"- {day(r['created_at'])} {r['summary']} ({', '.join(l['req_id'] for l in r['links'])})"
                for r in mine]
    return "\n".join(out)


def period_answer(prog: dict, call: dict) -> str:
    label, since, until = call.get("period", "기간"), call["args"]["since"], call["args"]["until"]
    reps = sorted(call["result"]["reports"], key=lambda r: r["created_at"])
    span = f"{label}({day(since)}~{day(until)})" if since != until else f"{label}({day(since)})"
    o = prog["overall"]
    now = f"현재 전체 진척률은 {o['requirement_rate']}%({o['counts'][DONE]}/{o['requirements']}건)입니다."
    if not reps:
        return f"{span}에는 확인된 완료 보고가 없습니다.\n{now}"
    lines = [f"{span} 완료 보고는 {len(reps)}건입니다."]
    for r in reps:
        links = ", ".join(f"{l['req_id']} 조건 {len(l['met_criteria'])}개" for l in r["links"])
        lines.append(f"- {day(r['created_at'])} {r['author']}: {r['summary']} → {links or '연결된 요구사항 없음'}")
    per: dict[str, int] = {}
    for r in reps:
        per[r["author"]] = per.get(r["author"], 0) + 1
    lines.append("작성자별: " + ", ".join(f"{a} {n}건" for a, n in per.items()))
    finished = [x for x in prog["requirements"]
                if x.get("completed_at") and since <= x["completed_at"][:10] <= until]
    if finished:
        lines.append("이 기간에 완료된 요구사항: " + ", ".join(_label(x) for x in finished))
    lines.append(now)
    return "\n".join(lines)


# ── 진입점 ───────────────────────────────────────────────────────────────
def compose(target: dict, results: list[dict], query: str) -> str:
    """질문 분석 결과와 Tool 결과로 답 본문을 쓴다."""
    t = _by_tool(results)
    prog = t["get_progress"][0]["result"]
    intent = target["intent"]
    reqs = [r for r in t.get("get_requirement", [])]
    by_req_reports = {r["args"]["req_id"]: r["result"]["reports"] for r in t.get("list_reports", [])
                      if r["args"].get("req_id")}

    if intent in ("requirement", "lookup") and reqs:
        found = [r["result"] for r in reqs if "error" not in r["result"]]
        missing = [r["args"]["req_id"] for r in reqs if "error" in r["result"]]
        parts = []
        if len(found) == 1:
            parts.append(requirement_detail(found[0], by_req_reports.get(found[0]["id"], []), prog["risks"]))
        elif found:
            what = f"'{target['label']}' 관련 요구사항은" if target.get("label") else "요청하신 요구사항은"
            done = sum(d["progress"]["status"] == DONE for d in found)
            tail = ("모두 완료되었습니다." if done == len(found) else
                    "아직 완료된 것은 없습니다." if done == 0 else f"그중 {done}건이 완료되었습니다.")
            head = f"{what} {len(found)}건이고, {tail}"
            parts.append(requirement_list(head, found))
        for rid in missing:
            parts.append(f"{josa(rid, '은는')} 등록되지 않은 요구사항 고유번호입니다. 요구사항 탭에서 목록을 확인해 주세요.")
        if target.get("match_how") == "search" and found:
            parts.append("(이름이 정확히 일치하는 요구사항이 없어 의미가 가장 가까운 요구사항으로 답했습니다.)")
        return "\n".join(parts)
    if intent == "lookup":
        return ("질문에 맞는 요구사항을 찾지 못했습니다. 요구사항 고유번호(예: SFR-001)나 기능 이름으로 "
                "다시 물어봐 주세요.\n" + overall_answer(prog))
    if intent == "category":
        return category_answer(prog, target["category"])
    if intent == "pending":
        return pending_answer(prog, target["pending_scope"], target["category"])
    if intent == "risks":
        return risks_answer(prog)
    if intent == "next":
        return next_answer(prog)
    if intent == "author":
        allrep = next((r["result"]["reports"] for r in t.get("list_reports", []) if not r["args"].get("req_id")), [])
        return author_answer(prog, query, allrep)
    if intent == "period":
        call = next(r for r in t["list_reports"] if r.get("period"))
        return period_answer(prog, call)
    return overall_answer(prog)
