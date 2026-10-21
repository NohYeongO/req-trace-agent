"""qa_plan — 질문에 답하려면 어떤 MCP Tool을 불러야 하는지 정한다.

소형 모델에게 도구 선택을 맡기면 흔들리므로, 질문 속 고유번호·분류명·기간 표현으로 코드가
정한다(agent/qa.py). 진척 집계(get_progress)는 항상 부른다.
"""
from datetime import date

from langsmith import traceable

from ..deps import SupervisorDeps
from ..qa import plan_calls
from ..state import ChatState
from .common import with_event


def today_of(deps: SupervisorDeps) -> date:
    return date.fromisoformat(deps.settings.fixed_today) if deps.settings.fixed_today else date.today()


@traceable(name="qa_plan_node")
async def qa_plan_node(state: ChatState, deps: SupervisorDeps) -> dict:
    calls = plan_calls(state["query"], state["route"], today_of(deps))
    event = {"type": "PlanCreated", "tools": [c["tool"] for c in calls],
             "period": next((c.get("period") for c in calls if c.get("period")), None)}
    return {"calls": calls, "events": with_event(state, event)}
