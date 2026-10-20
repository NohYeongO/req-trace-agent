"""LLM_BACKEND=openai — OpenAI Chat Completions(기본 fast=gpt-4o-mini, quality=gpt-4o).

실제 과금되는 원격 API다. 구조화 출력은 JSON 모드(response_format=json_object)로 강제하고
필드 정의는 시스템 프롬프트에 덧붙인다. Base 코드와 달리 답변도 토큰 단위로 스트리밍한다.
"""
import json
import os

import httpx

from .remote import RemoteLLM

OPENAI_URL = "https://api.openai.com/v1/chat/completions"


class OpenAILLM(RemoteLLM):
    def __init__(self, model: str, usd_per_1k_tokens: float, history_turns: int = 10):
        super().__init__(model, usd_per_1k_tokens, history_turns)
        self.name = f"openai:{model}"

    def _headers(self) -> dict:
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("OPENAI_API_KEY가 없습니다 — .env에 설정하세요.")
        return {"Authorization": f"Bearer {key}"}

    async def _complete(self, system: str, user: str, schema: dict | None) -> tuple[str, dict]:
        if schema is not None:
            system += ("\n반드시 다음 JSON 스키마를 따르는 JSON 객체 하나로만 답하라: "
                       + json.dumps(schema, ensure_ascii=False))
        payload = {"model": self.model, "temperature": 0,
                   "messages": [{"role": "system", "content": system},
                                {"role": "user", "content": user}]}
        if schema is not None:
            payload["response_format"] = {"type": "json_object"}
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(OPENAI_URL, json=payload, headers=self._headers())
            resp.raise_for_status()
            data = resp.json()
        tokens = data.get("usage", {}).get("total_tokens", 0)
        return data["choices"][0]["message"]["content"], self._usage(tokens)

    async def _stream(self, system: str, user: str, on_token=None) -> tuple[str, dict]:
        payload = {"model": self.model, "temperature": 0, "stream": True,
                   "stream_options": {"include_usage": True},
                   "messages": [{"role": "system", "content": system},
                                {"role": "user", "content": user}]}
        chunks: list[str] = []
        tokens = 0
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream("POST", OPENAI_URL, json=payload,
                                     headers=self._headers()) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data: ") or line == "data: [DONE]":
                        continue
                    data = json.loads(line[6:])
                    if data.get("usage"):
                        tokens = data["usage"].get("total_tokens", 0)
                    for choice in data.get("choices", []):
                        piece = choice.get("delta", {}).get("content") or ""
                        if piece:
                            chunks.append(piece)
                            if on_token is not None:
                                on_token(piece)
        return "".join(chunks), self._usage(tokens, f"[SYSTEM]\n{system}\n\n[USER]\n{user}")
