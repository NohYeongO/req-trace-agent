"""개발 명세서(인터페이스 정의서 + 테이블 정의서) 양식.

표의 사실(메서드·경로·파라미터·제약·컬럼·타입·NULL·PK·FK·불일치)은 소스와 DDL에서 코드가 뽑는다.
AI는 소스에 없는 '사람이 읽는 이름'만 채운다 — 테이블·컬럼 논리명, 설명이 없는 인터페이스의 설명,
종합 의견. AI가 채운 칸은 '(추정)'으로 표시한다. 소스에 이름이 있으면(@Operation summary, DDL
COMMENT, @Schema description) 그것을 쓰고 AI에게 묻지 않는다.

작업(task) 단위
- names:<테이블>   테이블·컬럼 논리명 (테이블마다 한 번)
- endpoints        설명이 없는 인터페이스들의 설명 (한 번에)
- opinion          종합 의견
"""
import re

from ..artifacts import _api_regex
from ..qa import check_answer
from ..store.db import DONE, PARTIAL
from .java_source import inner_type

DOC_TYPE = "dev_spec"
TITLE = "개발 명세서"
COLLECT_TOOL = "analyze_source_spec"


def collect_args(source: str) -> dict:
    return {}
GUESS = " (추정)"
_HANGUL = re.compile(r"[가-힣]")


def _if_ids(endpoints: list[dict]) -> list[str]:
    seq: dict[str, int] = {}
    ids = []
    for ep in endpoints:
        tag = re.sub(r"[^A-Z0-9]", "", ep["tag"].upper())[:8] or "API"
        seq[tag] = seq.get(tag, 0) + 1
        ids.append(f"IF-{tag}-{seq[tag]:03d}")
    return ids


def link_requirements(endpoints: list[dict], entities: list[dict], reports: list[dict]) -> tuple[dict, dict]:
    """완료 보고 근거로 인터페이스·테이블에 요구사항을 잇는다.
    API 근거 → 같은 메서드·경로 패턴의 인터페이스, 코드·파일 근거 → 같은 이름의 엔티티 클래스."""
    ep_links: dict[int, set] = {}
    tb_links: dict[str, set] = {}
    patterns = [(ep["method"], _api_regex(ep["path"])) for ep in endpoints]
    by_cls = {e["cls"]: e["table"] for e in entities}
    for rep in reports:
        for link in rep["links"]:
            for ev in link.get("evidence", []):
                if ev["type"] == "api":
                    method, _, path = ev["value"].partition(" ")
                    path = path.split("?")[0]
                    for i, (m, rx) in enumerate(patterns):
                        if m == method and rx.match(path):
                            ep_links.setdefault(i, set()).add(link["req_id"])
                elif ev["type"] in ("code", "file"):
                    name = ev["value"].rsplit("/", 1)[-1].split(".")[0]
                    if name in by_cls:
                        tb_links.setdefault(by_cls[name], set()).add(link["req_id"])
    return ep_links, tb_links


def build(spec: dict, progress: dict, reports: list[dict], meta: dict) -> dict:
    """분석 결과를 문서 모델로 정리한다. 표는 finalize에서 AI 이름을 채운 뒤 그린다."""
    endpoints, entities = spec["endpoints"], spec["entities"]
    meta = {**meta, "as_of": progress.get("as_of", "")}
    ids = _if_ids(endpoints)
    ep_links, tb_links = link_requirements(endpoints, entities, reports)
    for i, ep in enumerate(endpoints):
        ep["if_id"], ep["reqs"] = ids[i], sorted(ep_links.get(i, set()))
    for e in entities:
        e["reqs"] = sorted(tb_links.get(e["table"], set()))
    known = {r["id"]: r for r in progress["requirements"]}
    covered = set().union(*[set(ep["reqs"]) for ep in endpoints], *[set(e["reqs"]) for e in entities]) & set(known)
    issues = [(e["table"], i) for e in entities for i in e["issues"]]
    missing_summary = [ep["if_id"] for ep in endpoints if not ep["summary"]]

    facts = [f"[규모] 인터페이스 {len(endpoints)}개(컨트롤러 {len({ep['file'] for ep in endpoints})}개), "
             f"테이블 {len(entities)}개, DDL 파일 {len(spec['ddl_files'])}개",
             f"[요구사항 연결] 인터페이스·테이블과 연결된 요구사항 {len(covered)}건, "
             f"요구사항이 연결되지 않은 인터페이스 {sum(not ep['reqs'] for ep in endpoints)}개",
             f"[DDL 대조] 엔티티와 DDL 불일치 {len(issues)}건"
             + (f"(테이블 {', '.join(sorted({t for t, _ in issues}))})" if issues else "")
             + (f", 엔티티 없는 DDL 테이블 {', '.join(spec['ddl_only'])}" if spec["ddl_only"] else ""),
             f"[AI 추정] 설명이 없는 인터페이스 {len(missing_summary)}개, 논리명을 추정할 테이블 {len(entities)}개"]
    done_untraced = [r["id"] for r in progress["requirements"]
                     if r["status"] in (DONE, PARTIAL) and r["id"] not in covered]
    facts.append(f"[구현 근거 없음] 완료·부분완료인데 인터페이스·테이블과 연결되지 않은 요구사항 {len(done_untraced)}건")
    tasks = [f"names:{e['table']}" for e in entities] + (["endpoints"] if missing_summary else []) + ["opinion"]
    return {"doc_type": DOC_TYPE, "title": TITLE, "meta": meta, "sections": [], "facts": "\n".join(facts),
            "model": {"spec": spec, "covered": sorted(covered), "done_untraced": done_untraced},
            "names": {}, "summaries": {}, "tasks": tasks,
            "numbers": {"endpoints": len(endpoints), "tables": len(entities), "issues": len(issues),
                        "covered": len(covered)}}


# ── AI 작업 ──────────────────────────────────────────────────────────────
def _table_items(doc: dict, table: str) -> tuple[str, list[str]]:
    e = next(x for x in doc["model"]["spec"]["entities"] if x["table"] == table)
    ddl = doc["model"]["spec"]["ddl"].get(table, {}).get("columns", {})
    keys = [table] + [f"{table}.{c['name']}" for c in e["columns"]
                      if not (c.get("comment") or ddl.get(c["name"], {}).get("comment"))]
    # 모델에게는 테이블 하나씩, 컬럼 이름 그대로를 key로 묻는다 — 'account.id'처럼 접두어를 붙여
    # 물었더니 qwen3:8b가 접두어를 떼고 'id'로 답했다. 접두어는 코드가 붙인다(_qualify).
    lines = [f"테이블 {table} (엔티티 {e['cls']})", "컬럼:"]
    for c in e["columns"]:
        if f"{table}.{c['name']}" in keys:
            lines.append(f"- {c['name']}: 필드 {c['field']}, 타입 {c['java_type']}"
                         + (f", 참조 {c['fk']}" if c["fk"] else ""))
    return "\n".join(lines), keys


def _qualify(table: str, names: dict) -> dict:
    out = {}
    for k, v in names.items():
        k = k.strip()
        if k in ("__table__", table):
            out[table] = v
        else:
            out[k if k.startswith(table + ".") else f"{table}.{k}"] = v
    return out


def _endpoint_items(doc: dict) -> tuple[str, list[str]]:
    eps = [ep for ep in doc["model"]["spec"]["endpoints"] if not ep["summary"]]
    lines = [f"- {ep['if_id']}: {ep['method']} {ep['path']}, 핸들러 {ep['handler']}, "
             f"요청 {ep['body'] or '-'}, 응답 {ep['returns']}" for ep in eps]
    return "\n".join(lines), [ep["if_id"] for ep in eps]


async def write_task(llm, doc: dict, task: str, feedback: str | None, on_token=None):
    if task == "opinion":
        return await llm.write_section("spec_opinion", doc["facts"], feedback, on_token=on_token)
    if task == "endpoints":
        items, _ = _endpoint_items(doc)
        return await llm.name_items("endpoints", items, feedback)
    table = task.split(":", 1)[1]
    items, _ = _table_items(doc, table)
    names, usage = await llm.name_items("columns", items, feedback)
    return _qualify(table, names), usage


def check_task(doc: dict, task: str, value) -> list[str]:
    if task == "opinion":
        problems = check_answer(value, doc["facts"], "")
        if not value.strip():
            problems.append("빈 글")
        if "**" in value:
            problems.append("굵게 표시(**) 없이 쓸 것")
        return problems
    keys = _endpoint_items(doc)[1] if task == "endpoints" else _table_items(doc, task.split(":", 1)[1])[1]
    limit = 25 if task == "endpoints" else 20
    problems = []
    missing = [k for k in keys if not value.get(k)]
    if missing:
        problems.append(f"이름이 빠진 key: {', '.join(missing[:8])}")
    for k in keys:
        name = value.get(k, "")
        ok_word = _HANGUL.search(name) or re.fullmatch(r"[A-Z]{2,5}", name)     # 'ID'·'URL' 같은 약어는 허용
        if name and (not ok_word or len(name) > limit or re.search(r"[\"'{}\[\]]", name)):
            problems.append(f"{k}: '{name}'은 {limit}자 이내 한글 이름이 아님")
    return problems


def apply_task(doc: dict, task: str, value) -> None:
    if task == "opinion":
        doc["opinion"] = value
    elif task == "endpoints":
        doc["summaries"].update({k: v for k, v in value.items() if v})
    else:
        doc["names"].update({k: v for k, v in value.items() if v})


def fallback_task(doc: dict, task: str) -> None:
    """검증을 못 넘은 이름은 비워 두고(문서에 '미정'), 의견은 코드 문장으로."""
    if task == "opinion":
        n = doc["numbers"]
        doc["opinion"] = (f"인터페이스 {n['endpoints']}개, 테이블 {n['tables']}개를 소스에서 정리했다. "
                          f"엔티티와 DDL 불일치 {n['issues']}건은 확인이 필요하다. "
                          "AI가 추정한 논리명·설명은 담당자 검토가 필요하다.")
        doc["opinion_fallback"] = True


# ── 표 그리기 ────────────────────────────────────────────────────────────
def _name(doc: dict, key: str, source_name: str = "") -> str:
    if source_name:
        return source_name
    guess = doc["names"].get(key)
    return guess + GUESS if guess else "(미정)"


def _type_text(c: dict, d: dict | None) -> tuple[str, str]:
    if d:
        m = re.match(r"(\w+)(?:\(([^)]*)\))?", d["type"])
        return m.group(1), m.group(2) or ""
    return c["db_type"], str(c["length"] or "")


def finalize(doc: dict) -> None:
    spec, meta = doc["model"]["spec"], doc["meta"]
    eps, ents, dtos = spec["endpoints"], spec["entities"], spec["dtos"]
    S = doc["sections"] = []
    S.append({"id": "overview", "title": "1. 개요", "kind": "table", "columns": ["항목", "내용"], "rows": [
        ["사업명", meta.get("project_name", "")],
        ["대상 시스템", meta.get("repo", "") or "-"],
        ["분석 범위", f"인터페이스 {len(eps)}개, 테이블 {len(ents)}개, DDL {', '.join(spec['ddl_files']) or '없음'}"],
        ["작성 방법", "소스 정적 분석(컨트롤러·DTO·JPA 엔티티·DDL). 이름이 소스에 없는 칸은 AI가 추정해 '(추정)'으로 표시"],
        ["진척 기준일", meta.get("as_of", "")],
    ]})

    def ep_desc(ep):
        return ep["summary"] or (doc["summaries"].get(ep["if_id"], "") + GUESS if doc["summaries"].get(ep["if_id"]) else "(미정)")

    S.append({"id": "interfaces", "title": "2. 인터페이스 목록", "kind": "table",
              "columns": ["인터페이스 ID", "메서드", "URL", "설명", "인증", "관련 요구사항", "구현 위치"],
              "rows": [[ep["if_id"], ep["method"], ep["path"], ep_desc(ep), "필요" if ep["auth"] else "-",
                        ", ".join(ep["reqs"]) or "-", f"{ep['handler']} (L{ep['line']})"] for ep in eps],
              "note": "관련 요구사항: 완료 보고의 API 근거와 메서드·경로가 일치하는 인터페이스."})
    for k, ep in enumerate(eps, 1):
        rows = [["경로", p["name"], p["type"], "Y", "", p["description"]] for p in ep["params"] if p["in"] == "path"]
        rows += [["쿼리", p["name"], p["type"], "Y" if p["required"] else "N", "", p["description"]]
                 for p in ep["params"] if p["in"] == "query"]
        body = dtos.get(inner_type(ep["body"]) or "")
        if ep["body"]:
            if body:
                rows += [["요청 본문" + ("[]" if ep["body"].startswith(("List", "Set")) else ""), f["name"], f["type"],
                          "Y" if f["required"] else "N", f["constraints"], f["description"]] for f in body["fields"]]
            else:
                rows.append(["요청 본문", "-", ep["body"], "Y", "", "DTO 분석 불가"])
        resp = dtos.get(inner_type(ep["returns"]) or "")
        if resp:
            rows += [["응답", f["name"], f["type"], "", "", f["description"]] for f in resp["fields"]]
        else:
            rows.append(["응답", "-", ep["returns"], "", "", ""])
        S.append({"id": f"if_{k}", "title": f"2-{k}. {ep['if_id']} {ep['method']} {ep['path']}", "kind": "table",
                  "group": "interface_detail", "columns": ["구분", "항목", "타입", "필수", "제약", "설명"], "rows": rows,
                  "note": f"{ep_desc(ep)} · 인증 {'필요' if ep['auth'] else '불필요'} · 응답 {ep['returns']}"})

    S.append({"id": "tables", "title": "3. 테이블 목록", "kind": "table",
              "columns": ["테이블", "논리명", "엔티티", "컬럼 수", "관련 요구사항", "DDL 대조"],
              "rows": [[e["table"], _name(doc, e["table"]), e["cls"], len(e["columns"]), ", ".join(e["reqs"]) or "-",
                        f"불일치 {len(e['issues'])}건" if e["issues"] else "일치"] for e in ents],
              "note": "관련 요구사항: 완료 보고의 코드·파일 근거가 엔티티 클래스를 가리키는 경우."})
    for k, e in enumerate(ents, 1):
        ddl = spec["ddl"].get(e["table"], {}).get("columns", {})
        by_col = {}
        for issue in e["issues"]:
            by_col.setdefault(issue.split(":")[0], []).append(issue.split(":", 1)[1].strip() if ":" in issue else issue)
        rows = []
        for i, c in enumerate(e["columns"], 1):
            d = ddl.get(c["name"])
            typ, length = _type_text(c, d)
            nullable = (d["nullable"] if d else c["nullable"]) and not c["pk"]
            fk = (d or {}).get("fk") or (f"{c['fk']}(연관)" if c["fk"] else "")
            note = [c["note"]] if c["note"] else []
            note += (["UNIQUE"] if c["unique"] or (d or {}).get("unique") else []) + by_col.get(c["name"], [])
            if c["generated"]:
                note.append(f"자동 증가({c['generated'].split('.')[-1]})")
            comment = c.get("comment") or (d or {}).get("comment", "")
            rows.append([i, c["name"], _name(doc, f"{e['table']}.{c['name']}", comment), typ, length,
                         "Y" if nullable else "N", "PK" if c["pk"] else "", fk, (d or {}).get("default", ""),
                         "; ".join(note)])
        extra = [f"DDL에만 있는 컬럼 {k}" for k in ddl if k not in {c['name'] for c in e['columns']}]
        note = "; ".join([f"엔티티 {e['cls']} ({e['path']})"] + [f"연관관계 {r}" for r in e["relations"]]
                         + [f"유니크 {u}" for u in e["unique_constraints"]] + extra)
        S.append({"id": f"tb_{k}", "title": f"3-{k}. {e['table']} — {_name(doc, e['table'])}", "kind": "table",
                  "group": "table_detail",
                  "columns": ["No", "컬럼명", "논리명", "타입", "길이", "NULL", "PK", "FK", "기본값", "비고"],
                  "rows": rows, "note": note})
    issue_rows = [[e["table"], i] for e in ents for i in e["issues"]] + [[t, "엔티티 없음(DDL에만 있는 테이블)"]
                                                                       for t in spec["ddl_only"]]
    S.append({"id": "mismatch", "title": "4. 엔티티와 DDL 불일치", "kind": "table", "columns": ["테이블", "내용"],
              "rows": issue_rows,
              "note": "엔티티(JPA)와 DDL 스크립트의 컬럼 누락·타입 계열·NULL 허용 차이. 운영 DB 반영 전 정리가 필요하다."})
    untraced = doc["model"]["done_untraced"]
    S.append({"id": "untraced", "title": "5. 구현 근거와 연결되지 않은 요구사항", "kind": "table",
              "columns": ["요구사항", "비고"],
              "rows": [[r, "완료·부분완료인데 인터페이스·테이블과 연결된 완료 보고 근거가 없음"] for r in untraced]})
    S.append({"id": "opinion", "title": "6. 종합 의견", "kind": "ai", "text": doc.get("opinion", ""),
              "facts": doc["facts"], **({"fallback": True} if doc.get("opinion_fallback") else {})})
    guessed = sum(1 for s in S for r in s.get("rows", []) for v in r if isinstance(v, str) and v.endswith(GUESS))
    doc["numbers"]["guessed"] = guessed
    for heavy in ("model",):       # 저장 크기를 줄인다(표에 이미 반영)
        doc.pop(heavy, None)
