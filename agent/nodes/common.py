"""노드 공통 도우미."""


def add_cost(state: dict, usage: dict) -> float:
    return round(state.get("cost_usd", 0.0) + usage.get("usd", 0.0), 6)


def with_event(state: dict, event: dict) -> list[dict]:
    """노드는 events 전체 목록을 돌려준다 — 서버의 SSE 중계가 새로 붙은 꼬리만 내보낸다."""
    return state.get("events", []) + [event]
