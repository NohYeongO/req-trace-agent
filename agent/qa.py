"""현황 질의응답·요약의 결정론 부분 — 질문 분석, 도구 계획, 코멘트 검증.

역할 분담(소형 모델에서 얻은 교훈):
- 질문이 무엇을 묻는지(유형·대상·기간)와 어떤 MCP Tool을 부를지는 코드가 정한다.
- 답의 본문(숫자·고유번호·상태)은 agent/answers.py가 조회 결과로 직접 쓴다. qwen3:8b에게 사실
  문단을 주고 답을 쓰게 했더니 숫자는 맞아도 묻지 않은 수치를 늘어놓거나('SFR-005 남은 거'에
  전체 진척률·미착수 건수까지), 문장이 어색하거나('다음과 있습니다'), 해석이 틀렸다.
- LLM은 본문 뒤에 붙일 짧은 코멘트만 쓰고, 코멘트도 숫자·고유번호를 검증해 틀리면 뺀다.

질문 유형(intent)
  requirement  특정 요구사항(고유번호)
  lookup       이름으로 묻는 기능('결제 기능 끝났어?') — 요구사항 이름 대조, 없으면 RAG 검색
  category     분류(기능·보안·성능·데이터·품질)
  author       담당자별 실적
  pending      미완료 목록 (부분완료·미착수로 좁힐 수 있음)
  risks        위험 신호
  next         다음 우선순위 제안
  period       기간 요약(이번 주·지난주·최근 N일 …)
  overall      전체 진척
"""
import re
from datetime import date, timedelta

CATEGORIES = ("기능", "보안", "데이터", "성능", "품질")
_NUM = re.compile(r"(?<![A-Za-z]-)(?<![\d.])\d+(?:\.\d+)?")
_ID = re.compile(r"(?<![A-Za-z0-9])[A-Z]{3}-\d{3}(?!\d)")

_NEXT = re.compile(r"다음에|뭐부터|무엇부터|먼저\s*(해야|할)|우선순위|추천|뭘\s*먼저|어떤\s*걸\s*먼저")
_RISK = re.compile(r"위험|주의|정체|지연|걱정|문제\s*있")
_PARTIAL = re.compile(r"부분\s*완료|부분적|일부만")
_NOT_STARTED = re.compile(r"미착수|시작\s*안|착수\s*안|손\s*안\s*댄")
_PENDING = re.compile(r"안\s*된|안\s*끝난|미완료|남은\s*요구사항|남아\s*있는|아직|못\s*한|미구현")
_AUTHOR_HINT = re.compile(r"님|한\s*거|한\s*일|실적|작업한|보고한|담당자")
_OVERALL = re.compile(r"전체|전반|총|진척률|진행률|현황|얼마나")
_FOLLOW = re.compile(r"^(그럼|그러면|그건|그거|그\s*중|거기|나머지|이건|이거|저건|그쪽|그\s*요구사항)"
                     r"|^(남은|충족한|충족된|완료된|안\s*된)\s*(조건|거|것)")
# 이름 대조에서 빼는 말 — 질문에 흔하지만 요구사항 이름을 가리키지 않는다.
_STOP = {"기능", "요구사항", "상태", "진행", "상황", "현황", "관련", "구현", "완료", "어떻게", "부분",
         "개발", "작업", "처리", "관리", "조회", "전체", "진척", "진척률", "진행률", "지금", "현재", "혹시",
         "그럼", "그러면", "얼마나", "다들", "우리"}
_PARTICLE = re.compile(r"(쪽은|쪽도|쪽|은|는|이|가|을|를|의|도|만|에서|으로|로|과|와|하고)$")
_VERB = re.compile(r".*(됐어|했어|났어|됐나|했나|줘|있어|없어|할까|해요|돼요|인가|일까|나요|어요|뭐야|어때)$")
_CATEGORY_NEXT = re.compile(r"^(요구사항|분류|부문|쪽|관련|항목)")
_LEAD = re.compile(r"^(그럼|그러면|그리고|혹시)\s*")


def find_category(query: str) -> str | None:
    """분류 이름이 '분류'를 가리킬 때만 고른다. '보안 요구사항', '그럼 보안은?'은 분류지만
    '결제 기능 끝났어?'의 '기능'은 분류가 아니다(앞말을 꾸미는 낱말)."""
    tokens = re.findall(r"[가-힣A-Za-z]+", _LEAD.sub("", query.strip()))
    for i, tok in enumerate(tokens):
        base = _PARTICLE.sub("", tok)
        if base not in CATEGORIES:
            continue
        nxt = tokens[i + 1] if i + 1 < len(tokens) else ""
        if i == 0 or base != tok or not nxt or _CATEGORY_NEXT.match(nxt):
            return base
    return None


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


# ── 질문 분석 ────────────────────────────────────────────────────────────
def is_follow_up(query: str) -> bool:
    """'그럼 보안은?', '남은 조건이 뭐야?'처럼 앞 질문의 대상을 생략한 질문인가."""
    q = query.strip()
    return bool(_FOLLOW.search(q)) or (len(q) <= 10 and q.endswith(("은?", "는?", "도?")))


def _previous_target(history: list[dict]) -> tuple[list[str], str | None, str | None]:
    """직전 대화의 대상 — 사용자 질문에서 먼저 찾고, 없으면 직전 답에 나온 고유번호(3개 이하)를 쓴다.
    '결제 기능 끝났어?'처럼 이름으로 물은 뒤 '남은 조건은?'이라고 이어 물을 때 답에 나온 SFR-018을 쓴다."""
    users = [m["content"] for m in history if m.get("role") == "user"]
    bots = [m["content"] for m in history if m.get("role") == "assistant"]
    prev_q = users[-1] if users else ""
    ids = list(dict.fromkeys(_ID.findall(prev_q)))
    if not ids and bots:
        found = list(dict.fromkeys(_ID.findall(bots[-1])))
        ids = found if len(found) <= 3 else []
    return ids, find_category(prev_q), prev_q or None


def analyze(query: str, route: str, today: date, history: list[dict] | None = None) -> dict:
    """질문의 유형·대상·기간. 대상이 없는 후속 질문이면 직전 대화의 대상을 이어받는다."""
    ids = list(dict.fromkeys(_ID.findall(query)))
    category = find_category(query)
    period = parse_period(query, today)
    carried = None
    if not (ids or category or period) and history and is_follow_up(query):
        p_ids, p_cat, prev_q = _previous_target(history)
        if p_ids or p_cat:
            ids, category, carried = p_ids, p_cat, prev_q

    if route == "summary" or period:
        intent = "period"
        period = period or parse_period("이번 주", today)
    elif ids:
        intent = "requirement"
    elif _NEXT.search(query):
        intent = "next"
    elif _RISK.search(query):
        intent = "risks"
    elif _PARTIAL.search(query) or _NOT_STARTED.search(query) or _PENDING.search(query):
        intent = "pending"
    elif category:
        intent = "category"
    elif _AUTHOR_HINT.search(query):
        intent = "author"          # 실제 이름은 조회 결과의 담당자 목록과 대조해 answers에서 확정
    elif _OVERALL.search(query) and not keywords(query):
        intent = "overall"
    else:
        intent = "lookup"          # 이름으로 묻는 기능일 수 있다 → 요구사항 이름 대조·검색
    scope = "partial" if _PARTIAL.search(query) else "not_started" if _NOT_STARTED.search(query) else "all"
    return {"intent": intent, "ids": ids[:5], "category": category, "period": period,
            "pending_scope": scope, "carried_from": carried}


def keywords(query: str) -> list[str]:
    """요구사항 이름과 대조할 낱말(2자 이상 한글·영문, 조사 제거, 흔한 말 제외)."""
    out = []
    for w in re.findall(r"[가-힣A-Za-z]{2,}", query):
        w = _PARTICLE.sub("", w)
        if len(w) >= 2 and w not in _STOP and not _VERB.match(w) and \
                not re.fullmatch(r"(알려|정리|어떻|됐|끝났|했|뭐|있|다음|아직).*", w):
            out.append(w)
    return out


def match_by_name(query: str, requirements: list[dict], limit: int = 5) -> list[str]:
    """질문 낱말이 이름에 들어간 요구사항. 여러 낱말이면 더 많이 맞는 것만 남긴다."""
    words = keywords(query)
    scored = [(sum(w in r["name"] for w in words), r["id"]) for r in requirements]
    best = max((s for s, _ in scored), default=0)
    return [rid for s, rid in scored if s and s == best][:limit] if best else []


def plan_calls(target: dict) -> list[dict]:
    """질문 분석 결과로 부를 MCP Tool을 정한다. 진척 집계(get_progress)는 항상 부른다."""
    calls = [{"tool": "get_progress", "args": {}}]
    for rid in target["ids"]:
        calls.append({"tool": "get_requirement", "args": {"req_id": rid}})
        calls.append({"tool": "list_reports", "args": {"req_id": rid, "limit": 3}})
    if target["intent"] == "period":
        label, since, until = target["period"]
        calls.append({"tool": "list_reports", "args": {"since": since, "until": until, "limit": 50},
                      "period": label})
    if target["intent"] == "author":
        calls.append({"tool": "list_reports", "args": {"limit": 200}})
    return calls


# ── 코멘트 검증 ──────────────────────────────────────────────────────────
_LIST_MARK = re.compile(r"^\s*\d+[.)]\s", re.M)
_FOREIGN = re.compile(r"[À-ɏḀ-ỿ一-鿿぀-ヿ]+")
_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
MAX_COMMENT_CHARS = 160


def _numbers(text: str) -> set[str]:
    """고유번호 안의 숫자와 줄머리 번호(1. 2))는 빼고, '08'과 '8', '58.60'과 '58.6'을 같게 본다."""
    text = _LIST_MARK.sub(" ", _ID.sub(" ", text))
    return {str(float(n)).rstrip("0").rstrip(".") if "." in n else str(int(n)) for n in _NUM.findall(text)}


def _date_variants(facts: str) -> set[str]:
    """사실의 날짜(2026-10-12)를 답에서 '10.12', '10월 12일'처럼 바꿔 써도 허용한다."""
    out = set()
    for _, m, d in _DATE.findall(facts):
        out |= {f"{int(m)}.{int(d)}", f"{int(m)}.{d}", f"{m}.{d}".lstrip("0")}
    return {str(float(x)).rstrip("0").rstrip(".") for x in out} | out


def clean_answer(answer: str) -> str:
    """모델이 붙이는 머리말('코멘트:', '따르면,')과 앞뒤 따옴표를 지운다."""
    text = re.sub(r"^\s*(?:코멘트|덧붙임|참고)\s*[:：]\s*", "", answer.strip())
    text = re.sub(r"^(?:(?:에\s*)?따르면,?\s*)", "", text, flags=re.M)
    return text.strip().strip('"').strip()


def check_answer(answer: str, facts: str, query: str) -> list[str]:
    """글 속 숫자·고유번호가 사실(또는 질문)에 있는지, 외국어 문자가 섞였는지 본다."""
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
    return problems


_STATUS_WORDS = ("부분완료", "미착수", "완료")
_PRIORITY_CLAIM = re.compile(r"우선순위\s*'?(상|중|하)")


def _core_facts(core: str) -> dict[str, dict]:
    """본문 각 줄에서 고유번호별 상태·우선순위를 읽는다(그 고유번호가 처음 나온 줄 기준)."""
    out: dict[str, dict] = {}
    for line in core.splitlines():
        for rid in _ID.findall(line):
            if rid in out:
                continue
            status = next((w for w in _STATUS_WORDS if w in line), None)
            pri = _PRIORITY_CLAIM.search(line)
            out[rid] = {"status": status, "priority": pri.group(1) if pri else None}
    return out


def check_claims(comment: str, core: str) -> list[str]:
    """코멘트가 고유번호에 붙인 우선순위·상태가 본문과 같은지 본다. qwen3:8b가 '우선순위 상인
    SFR-018, SER-003, SFR-004'처럼 '중'인 SFR-004를 '상'으로 묶은 적이 있다."""
    facts, problems = _core_facts(core), []
    for sentence in re.split(r"(?<=[.!?다])\s+", comment):
        ids = [i for i in _ID.findall(sentence) if i in facts]
        claim = _PRIORITY_CLAIM.search(sentence)
        for rid in ids:
            f = facts[rid]
            if claim and f["priority"] and f["priority"] != claim.group(1):
                problems.append(f"{rid}의 우선순위는 '{f['priority']}'인데 '{claim.group(1)}'로 씀")
            said = next((w for w in _STATUS_WORDS if w in sentence), None)
            if said and f["status"] and len(ids) == 1 and said != f["status"]:
                problems.append(f"{rid}의 상태는 '{f['status']}'인데 '{said}'로 씀")
    return problems


def needs_comment(target: dict, core: str) -> bool:
    """LLM 코멘트는 요구사항 하나·몇 건을 묻는 질문(남은 조건에 대한 조언)과 기간 요약(한 주 흐름)에만
    붙인다. 실측(qwen3:8b)에서 집계·목록 답에 붙인 코멘트는 '보안이 가장 낮다'(실제는 기능),
    이미 완료된 요구사항을 '남은'이라 부르기 등 해석이 자주 틀렸다 — 그런 답의 해석(가장 많이 남은
    분류, 다음 우선순위)은 본문에서 코드가 계산한다. 다 끝났거나 찾지 못한 경우에도 붙이지 않는다."""
    if "등록되지 않은" in core or "찾지 못했습니다" in core:
        return False
    intent = target.get("intent")
    if intent in ("requirement", "lookup"):
        return bool(re.search(r"부분완료|미착수|조건 미확정", core))
    return intent == "period"


def check_comment(comment: str, core: str, query: str) -> list[str]:
    """본문 뒤에 붙일 코멘트 검증. 빈 코멘트는 통과(덧붙일 말이 없을 수 있다)."""
    if not comment.strip():
        return []
    problems = check_answer(comment, core, query) + check_claims(comment, core)
    if len(comment) > MAX_COMMENT_CHARS:
        problems.append(f"너무 김({len(comment)}자, {MAX_COMMENT_CHARS}자 이내로)")
    if "\n-" in comment or comment.lstrip().startswith("-"):
        problems.append("목록을 쓰지 말고 문장으로만")
    return problems
