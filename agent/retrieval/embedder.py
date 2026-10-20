"""임베더 2종 — 같은 인터페이스(embed(list[str]) -> np.ndarray, name)로 갈아 끼운다.

- OllamaEmbedder: 로컬 Ollama의 다국어 임베딩 모델(기본 bge-m3). 개발자가 섞어 쓰는
  한글 설명과 영문 코드 이름을 의미 수준에서 요구사항에 연결한다. 데이터가 외부로 나가지 않는다.
- HashEmbedder: 단어+문자 n-gram을 해싱한 벡터. 네트워크·모델 없이 결정론적으로 동작해
  단위 테스트·CI·fake 백엔드에서 쓴다. 의미는 모르고 표면 형태만 본다.
"""
import hashlib

import httpx
import numpy as np

from .text import tokenize


def _normalize(arr: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    return arr / np.where(norms == 0, 1, norms)


class HashEmbedder:
    name = "hash-ngram-1024"

    def __init__(self, dim: int = 1024):
        self.dim = dim

    def _features(self, text: str) -> list[str]:
        toks = tokenize(text)
        feats = [f"w:{t}" for t in toks]
        for t in toks:
            padded = f"#{t}#"
            feats += [f"c:{padded[i:i + 3]}" for i in range(len(padded) - 2)]
        return feats

    def embed(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for row, text in enumerate(texts):
            for f in self._features(text):
                h = int(hashlib.md5(f.encode()).hexdigest()[:8], 16)
                out[row, h % self.dim] += 1.0 if f.startswith("w:") else 0.5
        return _normalize(out)


class OllamaEmbedder:
    def __init__(self, model: str, base_url: str, batch: int = 32, timeout: float = 120.0):
        self.model = model
        self.name = f"ollama:{model}"
        self.url = base_url.rstrip("/") + "/api/embed"
        self.batch = batch
        self.timeout = timeout

    def embed(self, texts: list[str]) -> np.ndarray:
        vectors: list[list[float]] = []
        with httpx.Client(timeout=self.timeout) as client:
            for i in range(0, len(texts), self.batch):
                resp = client.post(self.url, json={"model": self.model, "keep_alive": "30m",
                                                   "input": texts[i:i + self.batch]})
                resp.raise_for_status()
                vectors.extend(resp.json()["embeddings"])
        return _normalize(np.asarray(vectors, dtype=np.float32))


def make_embedder(kind: str, model: str, base_url: str):
    if kind == "ollama":
        return OllamaEmbedder(model, base_url)
    if kind == "hash":
        return HashEmbedder()
    raise ValueError(f"알 수 없는 EMBEDDER: {kind!r} (hash | ollama)")
