"""코사인 벡터 인덱스. 문서 내용과 임베딩 모델 이름으로 만든 해시를 키로 디스크에 캐시한다
— 요구사항·조건이 바뀌면 키가 바뀌어 자동으로 다시 임베딩된다."""
import hashlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class Doc:
    id: str        # 문서 식별자 (예: "SFR-005", "SFR-005#c12")
    key: str       # 검색 결과를 묶을 단위 (요구사항 ID)
    text: str


def content_key(docs: list[Doc], embedder_name: str) -> str:
    h = hashlib.sha1(embedder_name.encode())
    for d in docs:
        h.update(d.id.encode())
        h.update(d.text.encode())
    return h.hexdigest()[:16]


class VectorIndex:
    def __init__(self, docs: list[Doc], embedder, cache_dir: Path | None = None):
        self.docs = docs
        self.embedder = embedder
        self.key = content_key(docs, embedder.name)
        self.matrix = self._load_or_build(cache_dir)

    def _load_or_build(self, cache_dir: Path | None) -> np.ndarray:
        if not self.docs:
            return np.zeros((0, 1), dtype=np.float32)
        path = cache_dir / f"{self.key}.npy" if cache_dir else None
        if path is not None and path.exists():
            return np.load(path)
        matrix = self.embedder.embed([d.text for d in self.docs])
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            np.save(path, matrix)
        return matrix

    def search(self, query: str, top_k: int) -> list[tuple[Doc, float]]:
        if not self.docs:
            return []
        q = self.embedder.embed([query])[0]
        scores = self.matrix @ q
        order = np.argsort(-scores)[:top_k]
        return [(self.docs[i], float(scores[i])) for i in order]
