"""chat_answer — 가벼운 대화는 파이프라인 없이 대화 이력만 보고 바로 답한다.

사용자에게 그대로 보이는 답이라 quality 모델이 쓴다. qwen3:0.6b는 이전 턴에서 들은 이름을
두고도 "이름을 알려주시면"처럼 답해 대화 이력을 제대로 쓰지 못했다.

get_stream_writer()는 /chat/stream처럼 custom 모드로 소비될 때만 토큰을 실제로 내보내고,
/chat(ainvoke)에서는 no-op이다.
"""
from langgraph.config import get_stream_writer
from langsmith import traceable

from ..deps import SupervisorDeps
from ..state import ChatState
from .common import add_cost, with_event


@traceable(name="chat_answer_node")
async def chat_answer_node(state: ChatState, deps: SupervisorDeps) -> dict:
    writer = get_stream_writer()
    reply, usage = await deps.quality_llm.chat(
        state["query"], state.get("history", []),
        on_token=lambda piece: writer({"type": "AnswerToken", "delta": piece}))
    return {"final": reply, "last_prompt": usage.get("prompt", ""),
            "cost_usd": add_cost(state, usage),
            "events": with_event(state, {"type": "Finalize", "pipeline": "chat"})}
