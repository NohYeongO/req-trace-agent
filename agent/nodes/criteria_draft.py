"""criteria_draft — 요구사항별 완료 조건 초안을 병렬로 쓴다.

첫 회차는 대상 전체, 이후 회차는 검증에서 반려된 요구사항만 반려 사유와 함께 다시 쓴다.
요구사항 하나가 끝날 때마다 CriteriaDrafted 이벤트를 흘려 화면이 진행률을 보여줄 수 있다.
LLM 호출이 실패한 요구사항은 그 건만 실패로 남기고 나머지는 계속 진행한다.
"""
import asyncio

from langgraph.config import get_stream_writer
from langsmith import traceable

from ..deps import SupervisorDeps
from ..state import CriteriaState
from .common import add_cost


@traceable(name="criteria_draft_node")
async def criteria_draft_node(state: CriteriaState, deps: SupervisorDeps) -> dict:
    writer = get_stream_writer()
    feedback = state.get("feedback") or {}
    ids = list(feedback) if feedback else list(state["targets"])
    sem = asyncio.Semaphore(deps.settings.llm_concurrency)
    total = len(ids)
    done = 0

    async def one(rid: str):
        nonlocal done
        async with sem:
            try:
                items, usage = await deps.quality_llm.draft_criteria(state["targets"][rid],
                                                                     feedback.get(rid))
                error = None
            except Exception as e:   # 한 건의 실패가 전체를 멈추지 않게
                items, usage, error = [], {"usd": 0.0}, f"{type(e).__name__}: {e}"
        done += 1
        writer({"type": "CriteriaDrafted", "req_id": rid, "count": len(items),
                "done": done, "total": total, "error": error})
        return rid, items, usage, error

    results = await asyncio.gather(*(one(r) for r in ids))
    drafts = dict(state.get("drafts") or {})
    failed = dict(state.get("failed") or {})
    cost = state.get("cost_usd", 0.0)
    for rid, items, usage, error in results:
        cost = add_cost({"cost_usd": cost}, usage)
        if error:
            failed[rid] = f"초안 작성 실패({error})"
            drafts.pop(rid, None)
        else:
            drafts[rid] = items
    return {"drafts": drafts, "failed": failed, "cost_usd": cost,
            "attempts": state.get("attempts", 0) + 1}
