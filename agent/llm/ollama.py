"""LLM_BACKEND=ollama — 로컬 sLLM(기본 fast=qwen3:0.6b, quality=qwen3:8b).

구조화 출력은 Ollama의 format=<JSON Schema>로 강제하고, qwen3의 사고(think) 모드는 꺼서
지연을 줄인다. Base 코드의 동기 httpx 호출은 이벤트 루프를 막아 동시 요청이 직렬화됐으므로
모두 AsyncClient로 바꿨다.
"""
import json

import httpx

from .remote import RemoteLLM


class OllamaLLM(RemoteLLM):
    def __init__(self, model: str, usd_per_1k_tokens: float, base_url: str,
                 timeout: float, history_turns: int = 10):
        super().__init__(model, usd_per_1k_tokens, history_turns)
        self.name = f"ollama:{model}"
        self.url = base_url.rstrip("/") + "/api/chat"
        self.timeout = timeout

    def _payload(self, system: str, user: str, stream: bool) -> dict:
        # keep_alive: fast·quality 모델이 번갈아 쓰여 언로드/재로드가 반복되는 것을 막는다.
        return {"model": self.model, "stream": stream, "think": False, "keep_alive": "30m",
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": user}],
                "options": {"temperature": 0.0}}

    async def _complete(self, system: str, user: str, schema: dict | None) -> tuple[str, dict]:
        payload = self._payload(system, user, stream=False)
        if schema is not None:
            payload["format"] = schema
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(self.url, json=payload)
            resp.raise_for_status()
            data = resp.json()
        tokens = (data.get("prompt_eval_count") or 0) + (data.get("eval_count") or 0)
        return data["message"]["content"], self._usage(tokens)

    async def _stream(self, system: str, user: str, on_token=None) -> tuple[str, dict]:
        chunks: list[str] = []
        tokens = 0
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream("POST", self.url,
                                     json=self._payload(system, user, stream=True)) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    data = json.loads(line)
                    piece = data.get("message", {}).get("content", "")
                    if piece:
                        chunks.append(piece)
                        if on_token is not None:
                            on_token(piece)
                    if data.get("done"):
                        tokens = (data.get("prompt_eval_count") or 0) + (data.get("eval_count") or 0)
        return "".join(chunks), self._usage(tokens, f"[SYSTEM]\n{system}\n\n[USER]\n{user}")
