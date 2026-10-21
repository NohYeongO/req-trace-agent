"""qa_write — quality LLM이 '사실' 문단만 근거로 답을 쓴다(토큰 스트리밍).

재작성일 때는 반려 사유를 함께 준다. AnswerToken에 attempt를 붙여 화면이 재작성 시 말풍선을
새로 시작하게 한다.
"""
from langgraph.config import get_stream_writer
from langsmith import traceable

from ..deps import SupervisorDeps
from ..qa import clean_answer
from ..state import ChatState
from .common import add_cost


@traceable(name="qa_write_node")
async def qa_write_node(state: ChatState, deps: SupervisorDeps) -> dict:
    writer = get_stream_writer()
    attempt = state.get("attempts", 0) + 1
    draft, usage = await deps.quality_llm.answer_status(
        state["query"], state["facts"], state["route"], state.get("feedback") or None,
        on_token=lambda piece: writer({"type": "AnswerToken", "delta": piece, "attempt": attempt}))
    return {"draft": clean_answer(draft), "attempts": attempt, "last_prompt": usage.get("prompt", ""),
            "cost_usd": add_cost(state, usage)}
