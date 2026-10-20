"""요구사항 검색(RAG) — 완료 보고 문장으로 관련 요구사항 후보를 찾는다.

문서 단위는 '요구사항 1건(이름+상세설명)'과 '완료 조건 1개(요구사항명+조건)' 두 가지다.
개발자 보고는 보통 조건 하나 수준의 일을 말하므로 조건 문서가 더 정확히 걸리고, 결과는
요구사항 ID로 묶어 가장 높은 점수를 쓴다. 개발자는 'Owner 검색 API'처럼 영문 코드 이름을
섞어 쓰므로 문서 쪽에 용어 사전의 영문 표현을 덧붙여 색인한다.
"""
from pathlib import Path

from .glossary import Glossary
from .index import Doc, VectorIndex, content_key


class RequirementSearch:
    def __init__(self, store, embedder, glossary: Glossary, cache_dir: Path | None = None):
        self.store = store
        self.embedder = embedder
        self.glossary = glossary
        self.cache_dir = cache_dir
        self._index: VectorIndex | None = None

    def _docs(self) -> list[Doc]:
        docs: list[Doc] = []
        for r in self.store.list_requirements():
            req = self.store.get_requirement(r["id"])
            base = f"{req['name']} {req['description']}"
            docs.append(Doc(req["id"], req["id"], self.glossary.expand(base)))
            for c in req["criteria"]:
                text = f"{req['name']}: {c['text']}"
                docs.append(Doc(f"{req['id']}#c{c['id']}", req["id"], self.glossary.expand(text)))
        return docs

    def index(self) -> VectorIndex:
        """요구사항·조건이 바뀌었을 때만 다시 만든다(내용 해시 비교)."""
        docs = self._docs()
        if self._index is None or self._index.key != content_key(docs, self.embedder.name):
            self._index = VectorIndex(docs, self.embedder, self.cache_dir)
        return self._index

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        hits = self.index().search(query, top_k * 4)
        best: dict[str, dict] = {}
        for doc, score in hits:
            cur = best.get(doc.key)
            if cur is None or score > cur["score"]:
                best[doc.key] = {"req_id": doc.key, "score": round(score, 4), "matched": doc.id}
        return sorted(best.values(), key=lambda h: -h["score"])[:top_k]
