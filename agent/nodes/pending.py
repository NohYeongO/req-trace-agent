"""status·summary 경로의 자리표시 노드.

현황 질의응답(status)과 요약 리포트(summary) 에이전트는 이후 PR에서 이 노드를 대체한다.
그때까지는 분류 결과만 확인할 수 있도록 안내 문구를 돌려준다.
"""
from langsmith import traceable

from ..deps import SupervisorDeps
from ..state import ChatState
from .common import with_event

_MESSAGES = {
    "status": "진척 현황 질의응답은 아직 연결되지 않았습니다. 요구사항과 완료 보고 기능이 들어간 뒤 답할 수 있습니다.",
    "summary": "완료 내역 요약은 아직 연결되지 않았습니다. 완료 보고 기능이 들어간 뒤 정리할 수 있습니다.",
}


@traceable(name="pending_node")
async def pending_node(state: ChatState, deps: SupervisorDeps) -> dict:
    return {"final": _MESSAGES[state["route"]],
            "events": with_event(state, {"type": "Finalize", "pipeline": f"{state['route']}-pending"})}
