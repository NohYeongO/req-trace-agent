"""report_delegate — 채팅으로 들어온 완료 보고를 보고 정리 에이전트(intake 그래프)에 넘긴다.

supervisor(채팅 그래프)는 보고를 직접 처리하지 않고 하위 에이전트를 호출한다. 하위 에이전트는
개발자 확인(interrupt)에서 멈추고, 채팅은 확인 카드 내용과 실행 ID를 돌려준다. 확인·취소는
완료 보고 탭과 같은 POST /reports/{run_id}/confirm으로 처리한다.
하위 에이전트의 진행 이벤트는 실행 중에 그대로 흘려보내 채팅 화면에 단계가 보이게 한다.
"""
import uuid

from langgraph.config import get_stream_writer
from langsmith import traceable

from ..deps import SupervisorDeps
from ..graphs.intake import intake_config
from ..state import ChatState, initial_intake_state
from .common import with_event


@traceable(name="report_delegate_node")
async def report_delegate_node(state: ChatState, deps: SupervisorDeps) -> dict:
    writer = get_stream_writer()
    run_id = uuid.uuid4().hex[:12]
    config = intake_config(run_id)
    agent = deps.agents["intake"]
    writer({"type": "AgentDelegated", "agent": "intake", "run_id": run_id})
    sent = 0
    async for update in agent.astream(initial_intake_state(state.get("author") or "", state["query"]),
                                      config, stream_mode="updates"):
        for node_name, delta in update.items():
            if node_name == "__interrupt__":
                continue
            events = (delta or {}).get("events") or []
            for ev in events[sent:]:
                writer({**ev, "node": f"intake.{node_name}"})
            sent = max(sent, len(events))
    snapshot = await agent.aget_state(config)
    confirm = snapshot.tasks[0].interrupts[0].value if snapshot.next == ("confirm",) else {}
    final = ("완료 보고로 이해하고 정리했습니다. 아래 카드에서 요구사항과 충족한 조건을 확인한 뒤 "
             "저장해 주세요." if confirm else "보고를 정리하지 못했습니다. 완료 보고 탭에서 다시 시도해 주세요.")
    event = {"type": "AgentDelegated", "agent": "intake", "run_id": run_id, "waiting": bool(confirm)}
    return {"run_id": run_id, "confirm": confirm, "final": final,
            "cost_usd": state.get("cost_usd", 0.0) + snapshot.values.get("cost_usd", 0.0),
            "events": with_event(state, event)}
