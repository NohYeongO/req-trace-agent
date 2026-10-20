"""intake_validate — LLM 매핑을 코드로 검증한다.

- 후보에 없는 요구사항, 그 요구사항의 것이 아닌 조건 id는 반려한다(매핑 날조 차단).
- 재시도 상한을 넘기면 틀린 부분만 버리고 진행한다(무한 루프 방지).
- 보고에 고유번호가 적혔는데 매핑에서 빠졌으면 조건 없이 링크만 넣어 둔다 — 개발자가
  확인 단계에서 충족 조건을 체크하면 된다.
"""
from langsmith import traceable

from ..deps import SupervisorDeps
from ..state import IntakeState
from .common import with_event


@traceable(name="intake_validate_node")
async def intake_validate_node(state: IntakeState, deps: SupervisorDeps) -> dict:
    owned = {c["id"]: {cr["id"] for cr in c["criteria"]} for c in state["candidates"]}
    problems, clean, seen = [], [], set()
    for l in state["links"]:
        rid = l["req_id"]
        if rid not in owned:
            problems.append(f"{rid}는 후보 요구사항이 아님")
            continue
        if rid in seen:
            problems.append(f"{rid}가 중복됨")
            continue
        seen.add(rid)
        foreign = [m for m in l["met"] if m not in owned[rid]]
        if foreign:
            problems.append(f"{rid}의 조건이 아닌 id {foreign}")
        clean.append({**l, "met": [m for m in l["met"] if m in owned[rid]]})
    last_try = state["attempts"] > deps.settings.intake_retries
    feedback = "; ".join(problems) if problems and not last_try else ""
    if not feedback:
        for rid in state["mentioned"]:
            if rid in owned and rid not in seen:
                clean.append({"req_id": rid, "met": [], "reason": "보고에 고유번호가 적혀 있음"})
    event = {"type": "MappingValidated", "attempt": state["attempts"], "problems": problems,
             "retry": bool(feedback)}
    return {"links": clean if not feedback else state["links"], "feedback": feedback,
            "events": with_event(state, event)}
