"""LLM_BACKEND=fake — 결정론 규칙 LLM(네트워크 없음). 단위 테스트·CI·화면 확인용.

실모델과 같은 인터페이스(route/chat)를 갖고, 판단은 rules.py의 키워드 규칙으로 한다.
답변 스트리밍도 흉내 내서 화면의 토큰 표시 경로를 실모델 없이 확인할 수 있다.
"""
import re

from langsmith import traceable

from .remote import render_history
from .rules import route_by_rule


class FakeLLM:
    def __init__(self, name: str, usd_per_1k_tokens: float, history_turns: int = 10):
        self.name = name
        self.usd_per_1k = usd_per_1k_tokens
        self.history_turns = history_turns

    def _usage(self, prompt: str, completion: str) -> dict:
        tokens = (len(prompt) + len(completion)) // 4 + 1
        return {"model": self.name, "tokens": tokens,
                "usd": round(tokens / 1000 * self.usd_per_1k, 6), "prompt": prompt}

    @traceable(run_type="llm", name="fake.route")
    async def route(self, query: str) -> tuple[dict, dict]:
        result = {"route": route_by_rule(query)}
        return result, self._usage(query, str(result))

    @traceable(run_type="llm", name="fake.chat")
    async def chat(self, query: str, history: list[dict], on_token=None) -> tuple[str, dict]:
        name = _remembered_name(history)
        if "이름" in query and name:
            reply = f"{name}님이라고 하셨어요."
        else:
            reply = ("안녕하세요. 요구사항 진척 관리 도우미입니다. 완료 보고를 요구사항과 연결해 "
                     "현황을 정리하고, 검수용 추적표를 만드는 일을 돕습니다.")
        for piece in reply.split(" "):
            if on_token is not None:
                on_token(piece + " ")
        prompt = f"{render_history(history, self.history_turns)}\nuser: {query}"
        return reply, self._usage(prompt, reply)


_NAME_RE = re.compile(r"제 이름은\s*([^\s.,!?]+?)(?:입니다|이에요|예요|이야|야)?[\s.,!?]*$")


def _remembered_name(history: list[dict]) -> str | None:
    for m in reversed(history):
        if m["role"] == "user":
            match = _NAME_RE.search(m["content"].strip())
            if match:
                return match.group(1)
    return None
