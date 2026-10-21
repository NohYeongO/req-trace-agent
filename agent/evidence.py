"""완료 보고 문장에서 근거 항목을 정규식으로 뽑는다.

근거(파일·API·테스트·코드 이름·PR)는 LLM에게 뽑게 하지 않는다 — 보고에 없는 근거를
지어낼 수 있어서다. 여기서 뽑은 항목만 이후 단계에서 실존 여부를 확인한다.
"""
import re

# 한글 조사가 바로 붙어도("OwnerTests의") 끊기도록 \b 대신 영숫자 기준 경계를 쓴다.
_L = r"(?<![A-Za-z0-9_])"
_R = r"(?![A-Za-z0-9_])"
_API = re.compile(_L + r"(GET|POST|PUT|PATCH|DELETE)\s+(/[A-Za-z0-9_\-/{}.]*)", re.I)
_FILE = re.compile(r"(?<![A-Za-z0-9_/])([A-Za-z0-9_\-]+(?:/[A-Za-z0-9_\-.]+)*\.(?:java|kt|py|ts|js|vue|xml|ya?ml|sql|json|properties))" + _R)
_TEST_CLASS = re.compile(_L + r"([A-Z][A-Za-z0-9]*Tests?)" + _R)
_TEST_METHOD = re.compile(_L + r"((?:test|should)[A-Z][A-Za-z0-9_]+)" + _R)
_CODE = re.compile(_L + r"([A-Z][a-z0-9]+(?:[A-Z][a-z0-9]*)+(?:\.[a-z][A-Za-z0-9_]*)?)" + _R)
_PR = re.compile(_L + r"(?:PR\s*#?\s*(\d+)|pull/(\d+))", re.I)
_COMMIT = re.compile(r"(?:커밋|commit)\s*[:#]?\s*([0-9a-f]{7,40})" + _R, re.I)


def extract_evidence(text: str) -> list[dict]:
    items: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def add(kind: str, value: str):
        if (kind, value) not in seen:
            seen.add((kind, value))
            items.append({"type": kind, "value": value})

    for m in _API.finditer(text):
        add("api", f"{m.group(1).upper()} {m.group(2).rstrip('.')}")
    files = {m.group(1) for m in _FILE.finditer(text)}
    for f in sorted(files, key=text.index):
        add("file", f)
    file_stems = {f.rsplit("/", 1)[-1].rsplit(".", 1)[0] for f in files}
    for m in _TEST_CLASS.finditer(text):
        if m.group(1) not in file_stems:
            add("test", m.group(1))
    for m in _TEST_METHOD.finditer(text):
        add("test", m.group(1))
    for m in _CODE.finditer(text):
        name = m.group(1)
        if name.split(".")[0] in file_stems or re.search(r"Tests?$", name.split(".")[0]):
            continue
        add("code", name)
    for m in _PR.finditer(text):
        add("pr", f"#{m.group(1) or m.group(2)}")
    for m in _COMMIT.finditer(text):
        add("commit", m.group(1))
    return items


# ── 양식으로 받은 근거 ───────────────────────────────────────────────────
EVIDENCE_TYPES = ("pr", "commit", "api", "test", "file", "code")
_TYPE_NAMES = {"pr": "PR", "commit": "커밋", "api": "API", "test": "테스트", "file": "파일", "code": "코드"}
_API_FORM = re.compile(r"^(GET|POST|PUT|PATCH|DELETE)\s+(/\S*)$", re.I)
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")


def normalize_evidence(items: list[dict]) -> tuple[list[dict], list[str]]:
    """완료 보고 양식의 근거 칸을 검사·정규화한다. 빈 칸은 건너뛰고, 형식이 틀린 칸은 사유를 돌려준다.
    (PR '12'·'#12'·'PR #12' → '#12', API 'get /x' → 'GET /x')"""
    out, errors, seen = [], [], set()
    for i, it in enumerate(items, 1):
        kind, value = (it.get("type") or "").strip().lower(), (it.get("value") or "").strip()
        if not value:
            continue
        name = _TYPE_NAMES.get(kind, kind)
        if kind not in EVIDENCE_TYPES:
            errors.append(f"{i}번째 근거: 알 수 없는 종류 '{kind}'")
            continue
        if kind == "pr":
            m = re.fullmatch(r"(?:PR\s*)?#?\s*(\d+)", value, re.I)
            value = f"#{m.group(1)}" if m else None
        elif kind == "commit":
            value = value.lower() if re.fullmatch(r"[0-9a-fA-F]{7,40}", value) else None
        elif kind == "api":
            m = _API_FORM.match(value)
            value = f"{m.group(1).upper()} {m.group(2)}" if m else None
        elif kind in ("test", "code"):
            value = value if _IDENT.match(value) else None
        if value is None:
            hint = {"pr": "숫자(예: 12 또는 #12)", "commit": "7~40자리 커밋 해시",
                    "api": "'메서드 경로' (예: GET /api/orders)", "test": "클래스·메서드 이름",
                    "code": "클래스·메서드 이름"}.get(kind, "")
            errors.append(f"{i}번째 근거({name}) 형식이 맞지 않습니다: {it.get('value')!r} → {hint}")
            continue
        if (kind, value) not in seen:
            seen.add((kind, value))
            out.append({"type": kind, "value": value, "source": "form"})
    return out, errors


def merge_evidence(form: list[dict], text: str) -> list[dict]:
    """양식 근거를 먼저 두고, 보고 문장에서 찾은 근거 중 양식에 없는 것을 덧붙인다."""
    seen = {(e["type"], e["value"]) for e in form}
    found = [{**e, "source": "text"} for e in extract_evidence(text) if (e["type"], e["value"]) not in seen]
    return list(form) + found
