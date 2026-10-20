"""토큰화 — 코드 식별자(camelCase, snake_case)를 단어로 쪼갠다.

'addOwner'와 '보호자 등록'이 키워드 검색에서도 만나려면 식별자를 'add owner'로 풀고,
한글 쪽은 용어 사전으로 영문을 덧붙여야 한다(Glossary.expand).
"""
import re

_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_TOKEN = re.compile(r"[A-Za-z]+|[0-9]+|[가-힣]+")
_STOP = {"the", "a", "an", "of", "to", "and", "or", "in", "is", "by", "for", "with", "this",
         "new", "return", "public", "private", "final", "void", "override", "string", "integer",
         "response", "entity", "http", "status", "org", "springframework", "java", "util"}


def split_identifier(word: str) -> list[str]:
    return [p for p in _CAMEL.sub(" ", word).replace("_", " ").split() if p]


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for raw in _TOKEN.findall(text):
        for part in split_identifier(raw) if raw.isascii() else [raw]:
            t = part.lower()
            if len(t) > 1 and t not in _STOP:
                tokens.append(t)
    return tokens
