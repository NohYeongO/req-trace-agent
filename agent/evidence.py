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
