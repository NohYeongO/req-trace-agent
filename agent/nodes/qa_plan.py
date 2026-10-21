"""qa_plan — 질문이 무엇을 묻는지 분석하고, 답하려면 어떤 MCP Tool을 불러야 하는지 정한다.

소형 모델에게 맡기면 흔들리므로 코드가 정한다(agent/qa.py). 질문 유형(요구사항·이름 조회·분류·
담당자·미완료·위험·우선순위·기간·전체)과 대상을 고르고, 대상을 생략한 후속 질문('그럼 보안은?',
'남은 조건은?')이면 직전 대화의 대상을 이어받는다. 진척 집계(get_progress)는 항상 부른다.
"""
from langsmith import traceable

from ..config import today_of
from ..deps import SupervisorDeps
from ..qa import analyze, plan_calls
from ..state import ChatState
from .common import with_event


@traceable(name="qa_plan_node")
async def qa_plan_node(state: ChatState, deps: SupervisorDeps) -> dict:
    target = analyze(state["query"], state["route"], today_of(deps.settings), state.get("history"))
    calls = plan_calls(target)
    event = {"type": "PlanCreated", "intent": target["intent"], "tools": [c["tool"] for c in calls],
             "period": target["period"][0] if target["period"] else None,
             "carried_from": target["carried_from"]}
    return {"target": target, "calls": calls, "events": with_event(state, event)}
