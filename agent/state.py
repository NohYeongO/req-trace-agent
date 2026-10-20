"""채팅 그래프 상태 정의."""
from typing import TypedDict


class ChatState(TypedDict, total=False):
    query: str
    thread_id: str
    history: list[dict]
    route: str            # chat | status | summary
    final: str
    last_prompt: str
    cost_usd: float
    events: list[dict]


def initial_state(query: str, thread_id: str, history: list[dict]) -> ChatState:
    return {"query": query, "thread_id": thread_id, "history": history, "route": "",
            "final": "", "last_prompt": "", "cost_usd": 0.0, "events": []}
