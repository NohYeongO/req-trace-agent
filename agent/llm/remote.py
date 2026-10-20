"""실모델 공통 로직 — 프롬프트 조립, JSON 파싱, 형식 붕괴 시 보정.

하위 클래스는 _complete(system, user, schema)와 _stream(system, user, on_token) 두 개만
구현한다. Base 코드에서 ollama/openai 파일에 75% 가까이 복사돼 있던 로직을 여기로 모았다.
"""
import json
import re

from langsmith import traceable

from .. import prompts
from .rules import route_by_rule


def parse_json(content: str) -> dict:
    """모델 출력에서 JSON 객체 하나를 꺼낸다. <think> 블록·코드펜스·앞뒤 잡음을 견딘다."""
    content = re.sub(r"<think>.*?</think>", "", content, flags=re.S).strip()
    try:
        data = json.loads(content)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", content, re.S)
        if m:
            try:
                data = json.loads(m.group(0))
                return data if isinstance(data, dict) else {}
            except json.JSONDecodeError:
                pass
    return {}


def render_history(history: list[dict], turns: int) -> str:
    return "\n".join(f"{m['role']}: {m['content']}" for m in history[-turns * 2:])


class RemoteLLM:
    def __init__(self, model: str, usd_per_1k_tokens: float, history_turns: int = 10):
        self.model = model
        self.usd_per_1k = usd_per_1k_tokens
        self.history_turns = history_turns
        self.name = model

    def _usage(self, tokens: int, prompt: str | None = None) -> dict:
        u = {"model": self.name, "tokens": tokens,
             "usd": round(tokens / 1000 * self.usd_per_1k, 6)}
        if prompt is not None:
            u["prompt"] = prompt
        return u

    async def _complete(self, system: str, user: str, schema: dict | None) -> tuple[str, dict]:
        raise NotImplementedError

    async def _stream(self, system: str, user: str, on_token=None) -> tuple[str, dict]:
        raise NotImplementedError

    @traceable(run_type="llm", name="llm.route")
    async def route(self, query: str) -> tuple[dict, dict]:
        content, usage = await self._complete(prompts.ROUTE_SYSTEM, query, prompts.ROUTE_SCHEMA)
        route = parse_json(content).get("route")
        if route not in prompts.ROUTES:   # 형식 붕괴 — 키워드 규칙으로 보정
            route = route_by_rule(query)
        return {"route": route}, usage

    @traceable(run_type="llm", name="llm.chat")
    async def chat(self, query: str, history: list[dict], on_token=None) -> tuple[str, dict]:
        user = (f"## 지금까지의 대화\n{render_history(history, self.history_turns) or '(없음)'}\n\n"
                f"## 사용자의 새 메시지\n{query}")
        return await self._stream(prompts.CHAT_SYSTEM, user, on_token)
