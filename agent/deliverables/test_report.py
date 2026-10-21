"""테스트 결과 보고서(단위·통합) 양식 — 결과 파일과 업무 DB로 표를 만들고, 서술 섹션 자리를 둔다.

섹션 종류
- table : 코드가 계산한 표(고칠 수 없음)
- text  : 코드가 쓴 고정 문장(담당자가 고칠 수 있음)
- ai    : LLM이 쓴 서술(실패 원인 분석, 종합 의견). 숫자·고유번호는 facts와 대조해 검증한다.

요구사항과 테스트 연결
1) 완료 보고 근거: 개발자가 보고(양식의 '테스트' 칸 등)에 적은 테스트 클래스·메서드
2) 명명 규칙: 보고에 적은 코드 근거 'CartAppService'와 테스트 클래스 'CartAppServiceTest'
"""
from collections import defaultdict

from ..qa import check_answer
from ..store.db import DONE, NOT_STARTED, PARTIAL
from .junit import ERROR, FAILED, PASSED, SKIPPED, summarize, total_coverage

DOC_TYPE = "test_report"
TITLE = "테스트 결과 보고서"
COLLECT_TOOL = "analyze_test_results"


def collect_args(source: str) -> dict:
    return {"source": source}
KINDS = ("단위", "통합", "미확인")


def _pct(v) -> str:
    return "-" if v is None else f"{v}%"


def _test_class_of(value: str, classes: set[str]) -> str | None:
    """근거 값('CartAppServiceTest', 'CartAppServiceTest.addItem')이 가리키는 테스트 클래스."""
    head = value.split(".")[0].split("#")[0]
    return head if head in classes else None


def link_requirements(requirements: list[dict], reports: list[dict], classes: set[str]) -> dict[str, dict]:
    """요구사항별 연결된 테스트 클래스와 연결 근거. {req_id: {class: 근거}}"""
    links: dict[str, dict] = defaultdict(dict)
    for rep in reports:
        for link in rep["links"]:
            for ev in link.get("evidence", []):
                if ev["type"] == "test":
                    cls = _test_class_of(ev["value"], classes)
                    if cls:
                        links[link["req_id"]].setdefault(cls, f"완료 보고 #{rep['id']}")
                elif ev["type"] == "code":
                    name = ev["value"].split(".")[0]
                    for cls in (f"{name}Test", f"{name}Tests"):
                        if cls in classes:
                            links[link["req_id"]].setdefault(cls, f"명명 규칙({name}) · 보고 #{rep['id']}")
    known = {r["id"] for r in requirements}
    return {rid: v for rid, v in links.items() if rid in known}


_CHAINED = ("java.lang.ExceptionInInitializerError", "java.lang.NoClassDefFoundError")


def _root_cause(case: dict) -> str:
    for cause in reversed(case["causes"]):
        if not cause.startswith(_CHAINED):
            return cause
    return case["causes"][-1] if case["causes"] else (case["message"] or case["type"] or "원인 정보 없음")


def failure_groups(cases: list[dict]) -> list[dict]:
    """실패·오류를 근본 원인으로 묶는다 — 같은 원인을 한 번만 분석한다.

    JVM은 클래스 초기화(static)에 한 번 실패하면 그 뒤 테스트에는 'NoClassDefFoundError: Could not
    initialize class' 같은 연쇄 오류만 남긴다. 그런 케이스는 같은 테스트 클래스에서 먼저 나온 근본
    원인을 이어받는다(데모 1차 수행: Docker 원인 3건 + 연쇄 오류 5건 → 원인 1개, 8건)."""
    primary: dict[str, str] = {}
    failed = [c for c in cases if c["status"] in (FAILED, ERROR)]
    for c in failed:
        cause = _root_cause(c)
        if not cause.startswith(_CHAINED):
            primary.setdefault(c["class"], cause)
    groups: dict[str, dict] = {}
    for c in failed:
        cause = _root_cause(c)
        if cause.startswith(_CHAINED) and c["class"] in primary:
            cause = primary[c["class"]]
        c["root_cause"] = cause
        g = groups.setdefault(cause, {"cause": cause, "count": 0, "classes": []})
        g["count"] += 1
        if c["class"] not in g["classes"]:
            g["classes"].append(c["class"])
    return sorted(groups.values(), key=lambda g: -g["count"])


def build(results: dict, kinds: dict[str, dict], progress: dict, reports: list[dict], meta: dict) -> dict:
    """문서 본문(섹션 목록)과 서술 검증용 사실(facts)을 만든다.

    results: junit.read_results 결과, kinds: 클래스별 단위/통합, progress: get_progress(대시보드) 결과,
    reports: 완료 보고(근거 포함), meta: 사업명·기준일·수행 차수·저장소 등
    """
    cases = results["cases"]
    for c in cases:
        c["kind"] = kinds.get(c["class"], {}).get("kind", "미확인")
    total = summarize(cases)
    by_kind = {k: summarize([c for c in cases if c["kind"] == k]) for k in KINDS}
    cov = total_coverage(results["coverage"])
    classes = sorted({c["class"] for c in cases})
    dates = sorted({c["timestamp"][:10] for c in cases if c["timestamp"]})
    modules = sorted({c["module"] for c in cases})
    groups = failure_groups(cases)
    reqs = progress["requirements"]
    req_links = link_requirements(reqs, reports, set(classes))

    sections = []
    sections.append({"id": "overview", "title": "1. 개요", "kind": "table", "columns": ["항목", "내용"], "rows": [
        ["사업명", meta.get("project_name", "")],
        ["대상 시스템", meta.get("repo", "") or "-"],
        ["수행 차수", meta.get("run_label", "") or "-"],
        ["수행일", " ~ ".join(dict.fromkeys([dates[0], dates[-1]])) if dates else "-"],
        ["테스트 범위", f"모듈 {len(modules)}개({', '.join(modules)}), 테스트 클래스 {len(classes)}개"],
        ["결과 자료", "JUnit XML" + (", JaCoCo 커버리지 XML" if results["coverage"] else " (커버리지 자료 없음)")],
        ["진척 기준일", progress.get("as_of", "")],
    ]})

    rows = []
    for k in KINDS:
        s = by_kind[k]
        if s["total"]:
            rows.append([k, s["total"], s[PASSED], s[FAILED], s[ERROR], s[SKIPPED], _pct(s["pass_rate"])])
    rows.append(["합계", total["total"], total[PASSED], total[FAILED], total[ERROR], total[SKIPPED],
                 _pct(total["pass_rate"])])
    sections.append({"id": "summary", "title": "2. 수행 결과 요약", "kind": "table",
                     "columns": ["구분", "전체", "통과", "실패", "오류", "건너뜀", "통과율"], "rows": rows,
                     "note": "구분: 스프링 컨텍스트·DB 컨테이너를 띄우는 테스트(@SpringBootTest, Testcontainers 등)는 "
                             "통합, 그 밖은 단위. 저장소 테스트 소스로 판별했다."})

    if cov:
        crow = [[c["module"], _pct(c["line"]["rate"]), f"{c['line']['covered']}/{c['line']['covered'] + c['line']['missed']}",
                 _pct(c["branch"]["rate"])] for c in sorted(results["coverage"], key=lambda c: c["module"])]
        crow.append(["합계", _pct(cov["line"]["rate"]), f"{cov['line']['covered']}/{cov['line']['covered'] + cov['line']['missed']}",
                     _pct(cov["branch"]["rate"])])
        sections.append({"id": "coverage", "title": "3. 코드 커버리지", "kind": "table",
                         "columns": ["모듈", "라인 커버리지", "커버된 라인", "분기 커버리지"], "rows": crow,
                         "note": "JaCoCo 결과가 있는 모듈만 집계했다(테스트가 없는 모듈은 제외)."})
    else:
        sections.append({"id": "coverage", "title": "3. 코드 커버리지", "kind": "text",
                         "text": "자료 없음 — JaCoCo 결과 파일이 없어 커버리지를 산정하지 않았다."})

    crow = []
    for cls in classes:
        cs = [c for c in cases if c["class"] == cls]
        s = summarize(cs)
        crow.append([cs[0]["module"], cls, cs[0]["kind"], s["total"], s[PASSED], s[FAILED] + s[ERROR], f"{s['time']}s"])
    sections.append({"id": "classes", "title": "4. 테스트 클래스별 결과", "kind": "table",
                     "columns": ["모듈", "테스트 클래스", "구분", "케이스", "통과", "실패·오류", "수행 시간"], "rows": crow})

    fails = [c for c in cases if c["status"] in (FAILED, ERROR)]
    if fails:
        sections.append({"id": "failures", "title": "5. 실패·오류 목록", "kind": "table",
                         "columns": ["테스트 클래스", "테스트", "결과", "예외", "근본 원인"],
                         "rows": [[c["class"], c["name"], c["status"], c["type"].rsplit(".", 1)[-1],
                                   c["root_cause"][:160]] for c in fails]})
        sections.append({"id": "failure_analysis", "title": "5-1. 실패 원인 분석", "kind": "ai", "text": "",
                         "groups": groups})
    else:
        sections.append({"id": "failures", "title": "5. 실패·오류 목록", "kind": "text",
                         "text": "실패·오류 없음 — 수행한 테스트가 모두 통과했다."})

    status_of = {r["id"]: r for r in reqs}
    lrow = []
    for rid in sorted(req_links):
        r = status_of[rid]
        cs = [c for c in cases if c["class"] in req_links[rid]]
        s = summarize(cs)
        result = (f"실패 {s[FAILED] + s[ERROR]}건" if s[FAILED] + s[ERROR] else "통과") if cs else "결과 없음"
        lrow.append([rid, r["name"], r["status"], ", ".join(req_links[rid]), s["total"], result,
                     "; ".join(dict.fromkeys(req_links[rid].values()))])
    sections.append({"id": "req_links", "title": "6. 요구사항별 테스트 연결", "kind": "table",
                     "columns": ["요구사항", "요구사항명", "진척 상태", "테스트 클래스", "케이스", "결과", "연결 근거"],
                     "rows": lrow,
                     "note": "연결 근거: 완료 보고에 적힌 테스트, 또는 보고에 적힌 코드 이름 + 'Test' 명명 규칙."})

    untested = [r for r in reqs if r["status"] in (DONE, PARTIAL) and r["id"] not in req_links]
    sections.append({"id": "untested", "title": "7. 테스트가 연결되지 않은 요구사항", "kind": "table",
                     "columns": ["요구사항", "요구사항명", "진척 상태", "우선순위"],
                     "rows": [[r["id"], r["name"], r["status"], r["priority"]] for r in untested],
                     "note": f"완료·부분완료인데 연결된 테스트가 없는 요구사항. 미착수 "
                             f"{sum(r['status'] == NOT_STARTED for r in reqs)}건은 제외했다."})

    linked_classes = {c for v in req_links.values() for c in v}
    orphan = [c for c in classes if c not in linked_classes]
    if orphan:
        sections.append({"id": "orphans", "title": "8. 요구사항에 연결되지 않은 테스트", "kind": "table",
                         "columns": ["테스트 클래스", "구분"], "rows": [[c, kinds.get(c, {}).get("kind", "미확인")] for c in orphan],
                         "note": "완료 보고에 근거로 적히지 않은 테스트. 관련 요구사항을 보고에 연결하면 추적표에 반영된다."})

    sections.append({"id": "opinion", "title": "9. 종합 의견", "kind": "ai", "text": ""})

    # 서술 검증 기준 — LLM 입력이자, 서술 속 숫자·고유번호를 대조하는 근거
    facts = [f"[수행 결과] 전체 {total['total']}건, 통과 {total[PASSED]}건, 실패 {total[FAILED]}건, 오류 {total[ERROR]}건, "
             f"건너뜀 {total[SKIPPED]}건, 통과율 {_pct(total['pass_rate'])}, 수행일 {', '.join(dates) or '-'}"]
    for k in KINDS:
        s = by_kind[k]
        if s["total"]:
            facts.append(f"[{k} 테스트] {s['total']}건 중 통과 {s[PASSED]}건, 실패·오류 {s[FAILED] + s[ERROR]}건")
    if cov:
        facts.append(f"[커버리지] 라인 {_pct(cov['line']['rate'])}, 분기 {_pct(cov['branch']['rate'])} "
                     f"(JaCoCo가 있는 모듈 {len(results['coverage'])}개)")
    else:
        facts.append("[커버리지] 자료 없음")
    for g in groups:
        facts.append(f"[실패 원인] {g['cause']} — {g['count']}건, 대상 {', '.join(g['classes'])}")
    if not groups:
        facts.append("[실패] 없음 — 수행한 테스트가 모두 통과했다")
    facts.append(f"[요구사항 연결] 테스트가 연결된 요구사항 {len(req_links)}건, "
                 f"테스트가 없는 완료·부분완료 요구사항 {len(untested)}건"
                 + (f"({', '.join(r['id'] for r in untested)})" if untested else ""))
    failed_reqs = [row[0] for row in lrow if row[5].startswith("실패")]
    if failed_reqs:
        facts.append(f"[실패한 테스트가 연결된 요구사항] {', '.join(failed_reqs)} "
                     f"(진척 상태는 완료 보고로 계산하므로 테스트 결과로 바뀌지 않는다. 재수행 결과 확인 필요)")
    facts.append(f"[진척] 요구사항 {progress['overall']['requirements']}건 중 완료 {progress['overall']['counts'][DONE]}건, "
                 f"진척률 {progress['overall']['requirement_rate']}%")
    return {"doc_type": DOC_TYPE, "title": TITLE, "meta": meta, "sections": sections, "facts": "\n".join(facts),
            "tasks": [s["id"] for s in sections if s["kind"] == "ai"],
            "numbers": {"total": total, "by_kind": by_kind, "coverage": cov, "linked": len(req_links),
                        "untested": [r["id"] for r in untested], "failed_reqs": failed_reqs}}


def fallback_text(section: dict, doc: dict) -> str:
    """LLM 서술이 끝내 검증을 통과하지 못하면 쓰는 코드 문장."""
    n = doc["numbers"]
    t = n["total"]
    if section["id"] == "failure_analysis":
        return "\n".join(f"- {g['cause']}: {g['count']}건 실패(대상 {', '.join(g['classes'])}). "
                         f"원인을 조치한 뒤 재수행이 필요하다." for g in section.get("groups", []))
    lines = [f"전체 {t['total']}건 중 {t[PASSED]}건이 통과했다(통과율 {_pct(t['pass_rate'])})."]
    if t[FAILED] + t[ERROR]:
        lines.append(f"실패·오류 {t[FAILED] + t[ERROR]}건은 원인 조치 후 재수행이 필요하다.")
    if n["untested"]:
        lines.append(f"완료·부분완료인데 테스트가 연결되지 않은 요구사항 {len(n['untested'])}건은 테스트 보완이 필요하다.")
    return " ".join(lines)



# ── 작성 그래프가 부르는 작업 함수(dev_spec과 같은 형식) ────────────────────
def section_facts(doc: dict, sid: str) -> str:
    """실패 원인 분석에는 [실패 원인] 사실만 준다 — 범위를 좁혀야 작은 모델이 다른 수치를 섞지 않는다."""
    if sid == "failure_analysis":
        return "\n".join(l for l in doc["facts"].splitlines() if l.startswith("[실패 원인]"))
    return doc["facts"]


def _section(doc: dict, sid: str) -> dict:
    return next(s for s in doc["sections"] if s["id"] == sid)


async def write_task(llm, doc: dict, task: str, feedback: str | None, on_token=None):
    return await llm.write_section(task, section_facts(doc, task), feedback, on_token=on_token)


def check_task(doc: dict, task: str, value) -> list[str]:
    problems = check_answer(value, doc["facts"], "")
    if not value.strip():
        problems.append("빈 글")
    if "**" in value:
        problems.append("굵게 표시(**) 없이 쓸 것")
    return problems


def apply_task(doc: dict, task: str, value) -> None:
    _section(doc, task)["text"] = value


def fallback_task(doc: dict, task: str) -> None:
    sec = _section(doc, task)
    sec["text"], sec["fallback"] = fallback_text(sec, doc), True


def finalize(doc: dict) -> None:
    for sec in doc["sections"]:
        if sec["kind"] == "ai":
            sec["facts"] = section_facts(doc, sec["id"])
