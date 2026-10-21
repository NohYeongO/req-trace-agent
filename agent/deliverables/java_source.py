"""개발 명세서용 소스 분석 — JPA 엔티티, 요청·응답 DTO, 컨트롤러 상세, DDL(CREATE TABLE).

정식 Java·SQL 파서가 아니라 어노테이션·선언 문자열을 읽는 결정론 분석이다(spring_endpoints와
같은 방식). 읽지 못하는 것(상수로 만든 이름, @Embedded 내부 등)은 '미분석'으로 남긴다 — 한계.
"""
import re
from dataclasses import dataclass, field

from ..spring_endpoints import parse_controller

_ANN = r"@\w+(?:\.\w+)*(?:\s*\((?:[^()]|\([^()]*\))*\))?"
_FIELD = re.compile(r"((?:" + _ANN + r"\s*)*)(?:private|protected|public)\s+(?!static\b|class\b|record\b|interface\b|enum\b)"
                    r"(?:final\s+)?([\w.<>,?\[\]\s]+?)\s+(\w+)\s*(?:=[^;]*)?;")
_CLASS = re.compile(r"\b(?:public\s+)?(?:abstract\s+)?(class|record|enum|interface)\s+(\w+)")
_EXTENDS = re.compile(r"\bclass\s+\w+\s+extends\s+(\w+)")
_STR = re.compile(r'"((?:[^"\\]|\\.)*)"')


def _arg(ann: str, key: str) -> str | None:
    """@Column(name = "x", length = 50)에서 key 값. 문자열이면 따옴표를 뗀다."""
    m = re.search(rf"\b{key}\s*=\s*(\"(?:[^\"\\]|\\.)*\"|[\w.]+)", ann)
    if not m:
        return None
    v = m.group(1)
    return v[1:-1] if v.startswith('"') else v


def _anns(block: str) -> dict[str, str]:
    """어노테이션 블록 → {이름: 전체 문자열}"""
    return {m.group(0).split("(")[0].strip()[1:].split(".")[-1]: m.group(0) for m in re.finditer(_ANN, block)}


def snake(name: str) -> str:
    """Spring Boot 기본 이름 전략(camelCase → snake_case)."""
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name).lower()


def _split_top(text: str) -> list[str]:
    out, depth, cur = [], 0, ""
    for ch in text:
        if ch in "(<{[":
            depth += 1
        elif ch in ")>}]":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur)
    return out


def _matching(text: str, start: int) -> int:
    """text[start]가 '('일 때 짝이 맞는 ')' 위치."""
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return i
    return len(text)


def _strip_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group(0)), src, flags=re.S)
    return re.sub(r"//[^\n]*", "", src)


# ── 엔티티 ───────────────────────────────────────────────────────────────
JAVA_DB_TYPES = {"Long": "BIGINT", "long": "BIGINT", "Integer": "INT", "int": "INT", "Short": "SMALLINT",
                 "short": "SMALLINT", "Boolean": "BOOLEAN", "boolean": "BOOLEAN", "Double": "DOUBLE",
                 "double": "DOUBLE", "Float": "FLOAT", "float": "FLOAT", "BigDecimal": "DECIMAL",
                 "LocalDateTime": "DATETIME", "LocalDate": "DATE", "LocalTime": "TIME", "Instant": "TIMESTAMP",
                 "String": "VARCHAR", "UUID": "BINARY(16)", "byte[]": "BLOB"}
_PRIMITIVE = {"long", "int", "short", "boolean", "double", "float", "byte", "char"}


@dataclass
class Column:
    field: str
    name: str
    java_type: str
    db_type: str
    nullable: bool = True
    length: int | None = None
    pk: bool = False
    generated: str = ""
    unique: bool = False
    fk: str = ""                 # 참조 엔티티(연관관계)
    relation: str = ""           # ManyToOne 등
    note: str = ""
    comment: str = ""            # @Comment·columnDefinition COMMENT


@dataclass
class Entity:
    cls: str
    table: str
    path: str
    line: int
    extends: str = ""
    mapped_superclass: bool = False
    columns: list[Column] = field(default_factory=list)
    relations: list[str] = field(default_factory=list)      # 컬럼이 아닌 연관관계(OneToMany 등)
    unique_constraints: list[str] = field(default_factory=list)


def parse_entity(source: str, path: str = "") -> Entity | None:
    src = _strip_comments(source)
    is_entity = bool(re.search(r"@Entity\b(?!\w)", src)) and not re.search(r"@Entity(?:Listeners|Scan)", src.split("class")[0]) \
        or bool(re.search(r"^\s*@Entity\s*$", src, re.M))
    is_super = "@MappedSuperclass" in src
    if not (is_entity or is_super):
        return None
    cm = _CLASS.search(src)
    if not cm:
        return None
    head = src[:cm.start()]
    cls = cm.group(2)
    table_ann = _anns(head).get("Table", "")
    table = _arg(table_ann, "name") or snake(cls)
    ent = Entity(cls=cls, table=table, path=path, line=src[:cm.start()].count("\n") + 1,
                 extends=(_EXTENDS.search(src) or [None, ""])[1] or "", mapped_superclass=is_super and not is_entity)
    for uc in re.finditer(r"@UniqueConstraint\s*\(([^)]*)\)", table_ann):
        cols = _STR.findall(re.search(r"columnNames\s*=\s*\{?([^}]*)\}?", uc.group(1)).group(1)) \
            if "columnNames" in uc.group(1) else []
        ent.unique_constraints.append(f"{_arg(uc.group(1), 'name') or 'UK'}({', '.join(cols)})")
    body = src[src.index("{", cm.end()) + 1:]
    depth, chunks, cur = 0, [], ""
    for ch in body:           # 클래스 본문 바로 아래(메서드 밖)만 본다
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                break
            continue
        if depth == 0:
            cur += ch
    chunks.append(cur)
    for m in _FIELD.finditer(cur):
        anns, jtype, name = _anns(m.group(1)), " ".join(m.group(2).split()), m.group(3)
        if "Transient" in anns:
            continue
        rel = next((r for r in ("ManyToOne", "OneToOne", "OneToMany", "ManyToMany") if r in anns), "")
        if rel in ("OneToMany", "ManyToMany") or (rel == "OneToOne" and _arg(anns[rel], "mappedBy")):
            ent.relations.append(f"{rel} {name}: {jtype}")
            continue
        if "Embedded" in anns or "ElementCollection" in anns:
            ent.relations.append(f"미분석({'Embedded' if 'Embedded' in anns else 'ElementCollection'}) {name}: {jtype}")
            continue
        col_ann = anns.get("Column", "") or anns.get("JoinColumn", "")
        col_name = _arg(col_ann, "name") or (snake(name) + "_id" if rel else snake(name))
        enum = "Enumerated" in anns
        base = jtype.split("<")[0].split(".")[-1]
        if rel:
            db = "BIGINT"
        elif enum:
            db = "VARCHAR" if "STRING" in anns["Enumerated"] else "INT"
        else:
            db = JAVA_DB_TYPES.get(base, "미확인")
        length = _arg(col_ann, "length")
        c = Column(field=name, name=col_name, java_type=jtype, db_type=db,
                   nullable=not (_arg(col_ann, "nullable") == "false" or base in _PRIMITIVE or "Id" in anns
                                 or "NotNull" in anns or "NotBlank" in anns or _arg(anns.get(rel, ""), "optional") == "false"),
                   length=int(length) if length and length.isdigit() else (255 if db == "VARCHAR" else None),
                   pk="Id" in anns, generated=_arg(anns.get("GeneratedValue", ""), "strategy") or "",
                   unique=_arg(col_ann, "unique") == "true", fk=base if rel else "", relation=rel)
        if enum:
            c.note = f"enum {base}"
        cm_ = re.search(r"COMMENT\s+'([^']*)'", col_ann) or (re.search(r'"([^"]*)"', anns.get("Comment", "")) if "Comment" in anns else None)
        c.comment = cm_.group(1) if cm_ else ""
        ent.columns.append(c)
    return ent


def resolve_inheritance(entities: list[Entity]) -> list[Entity]:
    """@MappedSuperclass(BaseEntity 등)의 컬럼을 하위 엔티티 앞에 붙이고, 엔티티만 돌려준다."""
    by_cls = {e.cls: e for e in entities}

    def cols(e: Entity, seen=()) -> list[Column]:
        parent = by_cls.get(e.extends)
        inherited = cols(parent, seen + (e.cls,)) if parent and parent.cls not in seen else []
        return inherited + e.columns

    out = []
    for e in entities:
        if not e.mapped_superclass:
            e.columns = cols(e)
            out.append(e)
    return out


# ── DTO(요청·응답) ───────────────────────────────────────────────────────
_CONSTRAINTS = ("NotNull", "NotBlank", "NotEmpty", "Min", "Max", "Size", "Email", "Pattern", "Positive",
                "PositiveOrZero", "Past", "Future", "Length", "DecimalMin", "DecimalMax")


def _field_info(anns: dict[str, str], jtype: str, name: str) -> dict:
    cons = []
    for k in _CONSTRAINTS:
        if k in anns:
            arg = anns[k][len(k) + 1:].strip()
            cons.append(k + (arg if arg.startswith("(") else ""))
    schema = anns.get("Schema", "")
    return {"name": name, "type": " ".join(jtype.split()), "required": any(k in anns for k in ("NotNull", "NotBlank", "NotEmpty")),
            "constraints": ", ".join(cons), "description": _arg(schema, "description") or "",
            "example": _arg(schema, "example") or ""}


def parse_dto(source: str) -> dict | None:
    """record·class DTO의 필드와 검증 제약. {name, description, fields}"""
    src = _strip_comments(source)
    cm = _CLASS.search(src)
    if not cm or cm.group(1) not in ("record", "class"):
        return None
    desc = _arg(_anns(src[:cm.start()]).get("Schema", ""), "description") or ""
    fields = []
    if cm.group(1) == "record":
        start = src.index("(", cm.end())
        for comp in _split_top(src[start + 1:_matching(src, start)]):
            m = re.match(r"\s*((?:" + _ANN + r"\s*)*)([\w.<>,?\[\]\s]+?)\s+(\w+)\s*$", comp, re.S)
            if m:
                fields.append(_field_info(_anns(m.group(1)), m.group(2), m.group(3)))
    else:
        for m in _FIELD.finditer(src):
            fields.append(_field_info(_anns(m.group(1)), m.group(2), m.group(3)))
    return {"name": cm.group(2), "description": desc, "fields": fields}


# ── 컨트롤러 상세 ────────────────────────────────────────────────────────
def parse_controller_detail(source: str, path: str = "") -> list[dict]:
    """엔드포인트별 설명(@Operation), 파라미터(@PathVariable·@RequestParam·@RequestBody), 반환 타입, 인증."""
    src = _strip_comments(source)
    eps = parse_controller(src)
    if not eps:
        return []
    cls_head = src[:(_CLASS.search(src) or re.search(r"$", src)).start()]
    tag = _anns(cls_head).get("Tag", "")
    out = []
    for ep in eps:
        lines = src.splitlines()
        start = sum(len(l) + 1 for l in lines[:ep.line - 1])
        handler = ep.handler.split(".")[-1]
        hm = re.search(rf"([\w<>,?\[\]\s.]+?)\s+{handler}\s*\(", src[start:])
        if not hm:
            continue
        sig_open = start + hm.end() - 1
        params_txt = src[sig_open + 1:_matching(src, sig_open)]
        prev_end = max(src.rfind(";", 0, start), src.rfind("}", 0, start), src.rfind("{", 0, start))
        anns = _anns(src[prev_end + 1:start + hm.start()])
        params, body, auth = [], None, False
        for p in _split_top(params_txt):
            m = re.match(r"\s*((?:" + _ANN + r"\s*)*)(?:final\s+)?([\w.<>,?\[\]\s]+?)\s+(\w+)\s*$", p, re.S)
            if not m:
                continue
            pa, ptype, pname = _anns(m.group(1)), " ".join(m.group(2).split()), m.group(3)
            def bare(ann: str) -> str | None:      # @PathVariable("id") 처럼 첫 인자가 이름일 때만
                m2 = re.match(r'@\w+\s*\(\s*"([^"]*)"', ann)
                return m2.group(1) if m2 else None

            if "AuthenticationPrincipal" in pa:
                auth = True
                continue
            desc = _arg(pa.get("Parameter", ""), "description") or ""
            if "RequestBody" in pa:
                body = ptype
            elif "PathVariable" in pa:
                params.append({"in": "path", "name": _arg(pa["PathVariable"], "value") or _arg(pa["PathVariable"], "name")
                               or bare(pa["PathVariable"]) or pname, "type": ptype, "required": True,
                               "description": desc})
            elif "RequestParam" in pa:
                ra = pa["RequestParam"]
                params.append({"in": "query", "name": _arg(ra, "value") or _arg(ra, "name") or bare(ra) or pname,
                               "type": ptype, "required": _arg(ra, "required") != "false" and _arg(ra, "defaultValue") is None,
                               "description": desc})
            elif "ModelAttribute" in pa:
                params.append({"in": "query", "name": pname, "type": ptype, "required": False, "description": desc})
        ret = " ".join(re.sub(_ANN, " ", hm.group(1)).split())
        ret = re.sub(r"^.*?\b(?:public|protected|private)\s+", "", ret)
        ret = re.sub(r"^\w+Mapping\s+", "", ret).strip()
        out.append({"method": ep.method, "path": ep.path, "handler": ep.handler, "line": ep.line, "file": path,
                    "summary": _arg(anns.get("Operation", ""), "summary") or "",
                    "description": _arg(anns.get("Operation", ""), "description") or "",
                    "tag": _arg(tag, "name") or ep.handler.split(".")[0].replace("Controller", ""),
                    "tag_description": _arg(tag, "description") or "", "params": params, "body": body,
                    "returns": ret, "auth": auth or "PreAuthorize" in anns or "Secured" in anns})
    return out


def inner_type(t: str | None) -> str | None:
    """'ApiResult<List<CartResponse>>' → 'CartResponse' (가장 안쪽 사용자 타입)"""
    if not t:
        return None
    names = [n for n in re.findall(r"\w+", t) if n not in ("ApiResult", "ResponseEntity", "List", "Set", "Page",
                                                            "Optional", "Void", "void", "Map", "String", "Long")]
    return names[-1] if names else None


# ── DDL ──────────────────────────────────────────────────────────────────
_CREATE = re.compile(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?`?(\w+)`?\s*\(", re.I)


def parse_ddl(sql: str) -> dict[str, dict]:
    """CREATE TABLE 문 → {테이블: {columns: {이름: {type, nullable, default, pk, unique, auto, comment}}, fks, uniques}}"""
    sql = re.sub(r"--[^\n]*", "", sql)
    tables = {}
    for m in _CREATE.finditer(sql):
        start = m.end() - 1
        body = sql[start + 1:_matching(sql, start)]
        t = {"columns": {}, "fks": [], "uniques": []}
        for part in _split_top(body):
            p = " ".join(part.split())
            up = p.upper()
            if up.startswith(("PRIMARY KEY",)):
                for c in re.findall(r"\w+", p[p.index("(") + 1:p.index(")")]):
                    if c in t["columns"]:
                        t["columns"][c]["pk"] = True
            elif up.startswith(("FOREIGN KEY", "CONSTRAINT")) and "FOREIGN KEY" in up:
                fm = re.search(r"FOREIGN KEY\s*\(`?(\w+)`?\)\s*REFERENCES\s*`?(\w+)`?\s*\(`?(\w+)`?\)", p, re.I)
                if fm:
                    t["fks"].append({"column": fm.group(1), "ref_table": fm.group(2), "ref_column": fm.group(3)})
            elif up.startswith(("CONSTRAINT", "UNIQUE", "KEY", "INDEX")):
                if "UNIQUE" in up:
                    t["uniques"].append(p)
            else:
                cm = re.match(r"`?(\w+)`?\s+([A-Za-z]+(?:\s*\([^)]*\))?)(.*)$", p)
                if not cm:
                    continue
                rest = cm.group(3).upper()
                dm = re.search(r"DEFAULT\s+('[^']*'|[\w.()]+)", cm.group(3), re.I)
                com = re.search(r"COMMENT\s+'([^']*)'", cm.group(3), re.I)
                t["columns"][cm.group(1)] = {"type": cm.group(2).upper().replace(" ", ""),
                                             "nullable": "NOT NULL" not in rest and "PRIMARY KEY" not in rest,
                                             "default": dm.group(1) if dm else "", "pk": "PRIMARY KEY" in rest,
                                             "unique": " UNIQUE" in f" {rest}", "auto": "AUTO_INCREMENT" in rest,
                                             "comment": com.group(1) if com else ""}
        for fk in t["fks"]:
            if fk["column"] in t["columns"]:
                t["columns"][fk["column"]]["fk"] = f"{fk['ref_table']}.{fk['ref_column']}"
        tables[m.group(1)] = t
    return tables


_FAMILY = {"BIGINT": "int", "INT": "int", "INTEGER": "int", "SMALLINT": "int", "TINYINT": "bool", "BIT": "bool",
           "BOOLEAN": "bool", "BOOL": "bool", "VARCHAR": "str", "CHAR": "str", "TEXT": "str", "LONGTEXT": "str",
           "DATETIME": "time", "TIMESTAMP": "time", "DATE": "date", "TIME": "time", "DECIMAL": "num",
           "DOUBLE": "num", "FLOAT": "num"}


def compare(entity: Entity, ddl: dict | None) -> list[str]:
    """엔티티와 DDL의 차이(테이블·컬럼 누락, 타입 계열·NULL 허용 불일치)."""
    if ddl is None:
        return [f"DDL에 {entity.table} 테이블이 없음(엔티티 {entity.cls})"]
    issues = []
    cols = ddl["columns"]
    for c in entity.columns:
        d = cols.get(c.name)
        if d is None:
            issues.append(f"{c.name}: DDL에 없음(엔티티 필드 {c.field})")
            continue
        fam_e = _FAMILY.get(c.db_type.split("(")[0], "?")
        fam_d = _FAMILY.get(d["type"].split("(")[0], "?")
        if "?" not in (fam_e, fam_d) and fam_e != fam_d and not (fam_e == "int" and c.note.startswith("enum")):
            issues.append(f"{c.name}: 타입 불일치(엔티티 {c.java_type} / DDL {d['type']})")
        if not c.nullable and d["nullable"] and not d["pk"]:
            issues.append(f"{c.name}: 엔티티는 NOT NULL, DDL은 NULL 허용")
        if c.nullable and not d["nullable"] and not c.pk:
            issues.append(f"{c.name}: DDL은 NOT NULL, 엔티티는 NULL 허용")
    known = {c.name for c in entity.columns}
    for name in cols:
        if name not in known:
            issues.append(f"{name}: 엔티티에 없음(DDL에만 있음)")
    return issues
