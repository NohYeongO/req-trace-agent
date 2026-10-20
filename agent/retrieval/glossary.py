"""표준 용어 사전 기반 질의 확장."""
import json
from pathlib import Path


class Glossary:
    def __init__(self, terms: dict[str, list[str]]):
        # 긴 용어부터 매칭해 '처리 시간'이 '시간'보다 먼저 걸리게 한다.
        self.terms = dict(sorted(terms.items(), key=lambda kv: -len(kv[0])))

    @classmethod
    def load(cls, path: Path) -> "Glossary":
        if not path.exists():
            return cls({})
        return cls(json.loads(path.read_text(encoding="utf-8")).get("terms", {}))

    def english_terms(self, text: str) -> list[str]:
        found: list[str] = []
        for ko, en in self.terms.items():
            if ko in text:
                for e in en:
                    if e not in found:
                        found.append(e)
        return found

    def expand(self, text: str) -> str:
        """원문 뒤에 대응 영문 용어를 덧붙인 검색 질의."""
        extra = self.english_terms(text)
        return f"{text} {' '.join(extra)}" if extra else text

    def as_prompt_hint(self, text: str) -> str:
        pairs = [f"{ko}={'/'.join(en)}" for ko, en in self.terms.items() if ko in text]
        return ", ".join(pairs)
