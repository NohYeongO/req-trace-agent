"""완료 조건 초안 검증 — LLM이 쓴 초안을 저장하기 전에 코드로 확인한다.

두 단계로 나눈다.
- validate_criteria: 형식(개수·길이·중복)과, 요구사항과 아예 무관한 조건을 반려한다.
  무관함은 글자 2-gram이 원문과 거의 겹치지 않는 것으로 판단한다.
- beyond_source: 원문 단어로 설명되지 않는 비중이 큰 조건에 '원문 외 내용' 표시만 단다.
  사람이 쓰는 타당한 보완 조건(예: 없는 ID로 삭제하면 오류)도 여기에 걸리기 때문에 반려하지
  않고, 담당자가 확정할 때 눈여겨보게 하는 용도로만 쓴다.
"""
import re

MAX_ITEMS = 5
MIN_LEN, MAX_LEN = 4, 120
MIN_SHARED_BIGRAMS = 2
BEYOND_SOURCE_BELOW = 0.5
_STOP = {"할 ", "수 ", "있다", "한다", "다.", "있어", "어야"}
_ENDINGS = re.compile(r"(할 수 있다|수 있다|하지 못한다|못한다|가능하다|한다|된다|이다|있다|없다|"
                      r"에서|으로|를|을|이|가|은|는|에|의|로|와|과|도|만|시)$")


def _bigrams(text: str) -> set[str]:
    t = re.sub(r"\s+", " ", text)
    return {t[i:i + 2] for i in range(len(t) - 1)} - _STOP


def _source(req: dict) -> str:
    return f"{req['name']} {req.get('description', '')}"


def source_coverage(req: dict, text: str) -> float:
    """조건의 단어(어미·조사 제거) 중 앞 두 글자가 원문에 나오는 비율."""
    src = _source(req)
    words = [_ENDINGS.sub("", w) for w in re.sub(r"[()/,.·]", " ", text).split()]
    words = [w for w in words if len(w) >= 2]
    if not words:
        return 1.0
    return sum(1 for w in words if w[:2] in src) / len(words)


def beyond_source(req: dict, text: str) -> bool:
    return source_coverage(req, text) < BEYOND_SOURCE_BELOW


def validate_criteria(req: dict, items: list[str]) -> tuple[list[str], list[str]]:
    """(정리된 조건 목록, 문제 목록). 문제가 없으면 저장해도 된다."""
    problems: list[str] = []
    source = _bigrams(_source(req))
    clean: list[str] = []
    for raw in items:
        text = re.sub(r"\s+", " ", raw).strip().lstrip("-•·0123456789.) ").strip()
        if not text:
            continue
        if text in clean:
            problems.append(f"중복 조건: '{text}'")
            continue
        if not MIN_LEN <= len(text) <= MAX_LEN:
            problems.append(f"길이가 {MIN_LEN}~{MAX_LEN}자를 벗어남: '{text[:30]}'")
            continue
        if len(_bigrams(text) & source) < MIN_SHARED_BIGRAMS:
            problems.append(f"요구사항에 없는 내용으로 보임: '{text}'")
            continue
        clean.append(text)
    if not clean:
        problems.append("쓸 수 있는 조건이 하나도 없음")
    if len(clean) > MAX_ITEMS:
        problems.append(f"조건이 {len(clean)}개로 너무 많음(최대 {MAX_ITEMS}개)")
    return clean, problems
