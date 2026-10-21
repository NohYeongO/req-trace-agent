"""qa_write — 코드가 쓴 답 본문을 내보내고, quality LLM이 그 뒤에 붙일 짧은 코멘트를 쓴다.

본문(숫자·고유번호·상태)은 이미 정확하므로 LLM은 해석·조언 1~2문장만 쓴다. 덧붙일 말이
없는 답(모두 완료, 없는 고유번호)은 LLM을 부르지 않는다. 재작성일 때는
반려 사유를 함께 준다. AnswerToken에 attempt를 붙여 화면이 재작성 시 말풍선을 새로 시작하게 한다.
"""
from langgraph.config import get_stream_writer
from langsmith import traceable

from ..deps import SupervisorDeps
from ..qa import clean_answer, needs_comment
from ..state import ChatState
from .common import add_cost


@traceable(name="qa_write_node")
async def qa_write_node(state: ChatState, deps: SupervisorDeps) -> dict:
    writer = get_stream_writer()
    attempt = state.get("attempts", 0) + 1
    writer({"type": "AnswerToken", "delta": state["core"], "attempt": attempt})
    if not needs_comment(state["target"], state["core"]):
        return {"draft": "", "attempts": attempt}
    writer({"type": "AnswerToken", "delta": "\n\n", "attempt": attempt})
    comment, usage = await deps.quality_llm.comment(
        state["query"], state["core"], state.get("feedback") or None,
        on_token=lambda piece: writer({"type": "AnswerToken", "delta": piece, "attempt": attempt}))
    return {"draft": clean_answer(comment), "attempts": attempt, "last_prompt": usage.get("prompt", ""),
            "cost_usd": add_cost(state, usage)}
