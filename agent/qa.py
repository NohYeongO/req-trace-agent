"""현황 질의응답·요약의 결정론 부분 — 도구 계획, 사실 정리, 답변 수치 검증, 안전한 대체 답변.

역할 분담(소형 모델에서 얻은 교훈):
- 어떤 MCP Tool을 부를지는 질문 속 고유번호·분류명·기간 표현으로 코드가 정한다.
- 답변 문장은 LLM이 쓰되, 근거는 여기서 정리한 '사실' 문단만 준다.
- 답변에 나온 숫자·고유번호가 사실에 있는지 코드가 검증하고, 끝내 틀리면 코드가 만든 답으로 대체한다.
"""
import re
from datetime import date, timedelta

from .store.db import DONE, NOT_STARTED, PARTIAL, UNDEFINED

CATEGORIES = ("기능", "보안", "데이터", "성능", "품질")
_NUM = re.compile(r"(?<![A-Za-z]-)(?<![\d.])\d+(?:\.\d+)?")
_ID = re.compile(r"(?<![A-Za-z0-9])[A-Z]{3}-\d{3}(?!\d)")


# ── 기간 ─────────────────────────────────────────────────────────────────
def parse_period(query: str, today: date) -> tuple[str, str, str] | None:
    """(라벨, 시작일, 종료일). 기간 표현이 없으면 None."""
    monday = today - timedelta(days=today.weekday())
    if re.search(r"지난\s*주|저번\s*주", query):
        s = monday - timedelta(days=7)
        return "지난주", s.isoformat(), (s + timedelta(days=6)).isoformat()
    if re.search(r"이번\s*주|금주|주간", query):
        return "이번 주", monday.isoformat(), today.isoformat()
    if "어제" in query:
        y = today - timedelta(days=1)
        return "어제", y.isoformat(), y.isoformat()
    if "오늘" in query:
        return "오늘", today.isoformat(), today.isoformat()
    if re.search(r"이번\s*달|이달", query):
        return "이번 달", today.replace(day=1).isoformat(), today.isoformat()
    m = re.search(r"최근\s*(\d+)\s*일", query)
    if m:
        return f"최근 {m.group(1)}일", (today - timedelta(days=int(m.group(1)) - 1)).isoformat(), today.isoformat()
    return None


# ── 도구 계획 ────────────────────────────────────────────────────────────
def plan_calls(query: str, route: str, today: date) -> list[dict]:
    calls = [{"tool": "get_progress", "args": {}}]
    for rid in list(dict.fromkeys(_ID.findall(query)))[:5]:
        calls.append({"tool": "get_requirement", "args": {"req_id": rid}})
    for cat in CATEGORIES:
        if cat in query:
            calls.append({"tool": "list_requirements", "args": {"category": cat}})
    period = parse_period(query, today)
    if route == "summary" and period is None:
        period = parse_period("이번 주", today)
    if period:
        calls.append({"tool": "list_reports", "args": {"since": period[1], "until": period[2], "limit": 50},
                      "period": period[0]})
    return calls


# ── 사실 정리 ────────────────────────────────────────────────────────────
def build_facts(results: list[dict], query: str = "") -> str:
    """Tool 결과를 LLM에 줄 '사실' 문단으로 만든다. 답변 검증도 이 문단을 기준으로 한다.

    질문 대상(요구사항·분류·담당자·기간)이 있으면 그 대상의 사실만 넣는다. 전부 넣었더니
    qwen3:8b가 '보안 진행률' 질문에 전체 수치로 답하고, 기간 요약에 누적 담당자 실적을
    그 주에 한 일처럼 섞었다."""
    by_tool = {}
    for r in results:
        by_tool.setdefault(r["tool"], []).append(r)
    req_ids = [r["args"]["req_id"] for r in by_tool.get("get_requirement", [])]
    category = next((r["args"]["category"] for r in by_tool.get("list_requirements", [])), None)
    period = next((r for r in by_tool.get("list_reports", [])), None)
    prog = by_tool["get_progress"][0]["result"] if "get_progress" in by_tool else None
    authors = [a for a in (prog["by_author"] if prog else []) if a["author"] in query]
    general = not (req_ids or category or period or authors)

    focus = ([f"요구사항 {', '.join(req_ids)}"] if req_ids else []) + ([f"분류 {category}"] if category else []) \
        + ([f"담당자 {', '.join(a['author'] for a in authors)}"] if authors else []) \
        + ([f"기간 {period.get('period')} {period['args']['since']}~{period['args']['until']}"] if period else [])
    out: list[str] = [f"[질문 대상] {', '.join(focus) if focus else '전체 현황'}"]

    if prog:
        o, c = prog["overall"], prog["overall"]["counts"]
        out.append(f"[전체 진척 · 기준일 {prog['as_of']}] 요구사항 {o['requirements']}건 중 "
                   f"완료 {c[DONE]}건, 부분완료 {c[PARTIAL]}건, 미착수 {c[NOT_STARTED]}건, 조건 미확정 {c[UNDEFINED]}건. "
                   f"진척률(요구사항 기준) {o['requirement_rate']}%, 진척률(완료 조건 기준) {o['criteria_rate']}% "
                   f"(충족 {o['criteria_met']}/{o['criteria_total']}개). 반영된 완료 보고 {o['reports']}건.")
        for g in prog["by_category"]:
            if general or g["category"] == category:
                # 요구사항 기준 진척률도 코드가 계산해 이름을 붙여 둔다 — 없으면 모델이 조건 충족률을
                # '요구사항 기준 진척률'이라고 바꿔 부른다.
                req_rate = round(100 * g[DONE] / g["total"], 1) if g["total"] else 0.0
                out.append(f"[분류 {g['category']}] {g['total']}건 중 완료 {g[DONE]}건, 부분완료 {g[PARTIAL]}건, "
                           f"미착수 {g[NOT_STARTED]}건. 이 분류의 진척률(요구사항 기준) {req_rate}%, "
                           f"조건 충족률 {g['criteria_rate']}% (충족 {g['criteria_met']}/{g['criteria_total']}개)")
        for a in (prog["by_author"] if general else authors):
            out.append(f"[담당자 {a['author']} · 누적] 완료 보고 {a['reports']}건, 처음 충족시킨 조건 {a['criteria_met']}개, "
                       f"다룬 요구사항 {', '.join(a['requirements'])}")
        if general:
            pending = [x for x in prog["requirements"] if x["status"] != DONE]
            if pending:
                out.append("[미완료 요구사항] " + "; ".join(
                    f"{x['id']} {x['name']}({x['status']} {x['met']}/{x['total']})" for x in pending))
        cat_ids = {x["id"] for x in prog["requirements"] if x["category"] == category}
        for k in prog["risks"]:
            ids = set(_ID.findall(k["req_id"]))
            if general or period or ids & set(req_ids) or ids & cat_ids:
                out.append(f"[위험 신호] {k['kind']}: {k['req_id']} {k['name']} — {k['detail']}")

    for r in by_tool.get("get_requirement", []):
        data = r["result"]
        if "error" in data:
            out.append(f"[요구사항 {r['args']['req_id']}] 등록되지 않은 고유번호")
            continue
        p = data["progress"]
        crit = "; ".join(f"{'충족' if c['met_by'] else '미충족'} — {c['text']}"
                         for c in data["criteria"] if c["confirmed"])
        out.append(f"[요구사항 {data['id']} {data['name']}] 상태 {p['status']}, 충족 {p['met']}/{p['total']}, "
                   f"남은 조건 {p['total'] - p['met']}개, 완료 보고 {p['report_count']}건"
                   + (f", 완료일 {p['completed_at'][:10]}" if p["completed_at"] else "")
                   + f". 조건: {crit or '확정된 조건 없음'}")
    for r in by_tool.get("list_requirements", []):
        rows = r["result"]["requirements"]
        out.append(f"[분류 {r['args']['category']} 요구사항 목록 {len(rows)}건] " + "; ".join(
            f"{x['id']} {x['name']}({x['status']} {x['met']}/{x['total']})" for x in rows))
    if period:
        reps = period["result"]["reports"]
        out.append(f"[{period.get('period', '기간')} 완료 보고 {len(reps)}건 · "
                   f"{period['args']['since']}~{period['args']['until']}] (이 기간에 한 일은 아래 보고뿐이다)")
        # 작성자별 건수도 코드가 세어 둔다 — 모델이 직접 세면 사실에 없는 숫자로 반려된다.
        per_author: dict[str, int] = {}
        for rep in reps:
            per_author[rep["author"]] = per_author.get(rep["author"], 0) + 1
        if per_author:
            out.append("  [작성자별 보고 수] " + ", ".join(f"{a} {n}건" for a, n in per_author.items()))
        for rep in reps:
            met = ", ".join(f"{l['req_id']} {c['text']}" for l in rep["links"] for c in l["met_criteria"])
            out.append(f"  - {rep['created_at'][:10]} {rep['author']}: {rep['summary']} "
                       f"(요구사항 {', '.join(l['req_id'] for l in rep['links'])}; 충족 조건: {met or '없음'})")
    return "\n".join(out)


# ── 답변 검증 ────────────────────────────────────────────────────────────
_LIST_MARK = re.compile(r"^\s*\d+[.)]\s", re.M)


def _numbers(text: str) -> set[str]:
    """고유번호 안의 숫자와 줄머리 번호(1. 2))는 빼고, '08'과 '8', '58.60'과 '58.6'을 같게 본다."""
    text = _LIST_MARK.sub(" ", _ID.sub(" ", text))
    return {str(float(n)).rstrip("0").rstrip(".") if "." in n else str(int(n)) for n in _NUM.findall(text)}


_FOREIGN = re.compile(r"[\u00C0-\u024F\u1E00-\u1EFF\u4E00-\u9FFF\u3040-\u30FF]+")


_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def _date_variants(facts: str) -> set[str]:
    """사실의 날짜(2026-10-12)를 답에서 '10.12', '10월 12일'처럼 바꿔 써도 허용한다."""
    out = set()
    for _, m, d in _DATE.findall(facts):
        out |= {f"{int(m)}.{int(d)}", f"{int(m)}.{d}", f"{m}.{d}".lstrip("0")}
    return {str(float(x)).rstrip("0").rstrip(".") for x in out} | out


def clean_answer(answer: str) -> str:
    """사실 문단의 표시용 머리말([질문 대상] 등)이 답에 새어 나오면 지운다."""
    text = re.sub(r"\[질문 대상\]\s*(?:(?:분류|요구사항|담당자|기간|전체 현황)\s*\S*?(?:의|에|은|는)\s+)?",
                  "", answer)
    return re.sub(r"^(?:(?:에\s*)?따르면,?\s*|(?:에|의|은|는)\s+)", "", text.strip(), flags=re.M).strip()


def check_answer(answer: str, facts: str, query: str) -> list[str]:
    """답변 속 숫자·고유번호가 사실(또는 질문)에 있는지, 외국어 문자가 섞였는지 본다."""
    problems = []
    foreign = sorted(set(_FOREIGN.findall(answer)))
    if foreign:   # qwen3가 'chưa'(베트남어) 같은 토큰을 섞은 적이 있다
        problems.append(f"한국어가 아닌 표현 {', '.join(foreign)}")
    allowed_ids = set(_ID.findall(facts)) | set(_ID.findall(query))
    for rid in sorted(set(_ID.findall(answer)) - allowed_ids):
        problems.append(f"사실에 없는 고유번호 {rid}")
    allowed = _numbers(facts) | _numbers(query) | _date_variants(facts)
    for n in sorted(_numbers(answer) - allowed, key=lambda x: float(x)):
        problems.append(f"사실에 없는 숫자 {n}")
    if not answer.strip():
        problems.append("빈 답변")
    return problems


# ── 안전한 대체 답변 ─────────────────────────────────────────────────────
def fallback_answer(results: list[dict]) -> str:
    """LLM 답이 끝내 검증을 통과하지 못하면, 조회 결과로 코드가 직접 쓴 답을 준다."""
    lines = []
    for r in results:
        if r["tool"] == "get_requirement" and "error" not in r["result"]:
            d = r["result"]
            p = d["progress"]
            left = [c["text"] for c in d["criteria"] if c["confirmed"] and not c["met_by"]]
            lines.append(f"{d['id']} {d['name']}: {p['status']} ({p['met']}/{p['total']})"
                         + (f". 남은 조건: {', '.join(left)}" if left else ""))
        elif r["tool"] == "list_reports":
            reps = r["result"]["reports"]
            lines.append(f"{r.get('period', '기간')} 완료 보고 {len(reps)}건: " + "; ".join(
                f"{x['author']} — {x['summary']}" for x in reps[:10]) if reps else f"{r.get('period', '기간')} 완료 보고 없음")
    prog = next((r["result"] for r in results if r["tool"] == "get_progress"), None)
    if prog and not lines:
        o = prog["overall"]
        lines.append(f"전체 {o['requirements']}건 중 완료 {o['counts'][DONE]}건, 부분완료 {o['counts'][PARTIAL]}건, "
                     f"미착수 {o['counts'][NOT_STARTED]}건입니다. 진척률은 요구사항 기준 {o['requirement_rate']}%, "
                     f"완료 조건 기준 {o['criteria_rate']}%입니다.")
    return "\n".join(lines) or "조회된 정보가 없습니다."
