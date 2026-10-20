"""그래프 상태 정의."""
from typing import TypedDict


class ChatState(TypedDict, total=False):
    query: str
    thread_id: str
    history: list[dict]
    route: str            # chat | status | summary
    final: str
    last_prompt: str
    cost_usd: float
    events: list[dict]


def initial_state(query: str, thread_id: str, history: list[dict]) -> ChatState:
    return {"query": query, "thread_id": thread_id, "history": history, "route": "",
            "final": "", "last_prompt": "", "cost_usd": 0.0, "events": []}


class CriteriaState(TypedDict, total=False):
    req_ids: list[str]          # 요청한 대상(비우면 전체)
    overwrite: bool             # 검토 대기 중인 초안까지 다시 쓸지 (확정된 조건은 절대 안 씀)
    targets: dict               # req_id -> 요구사항 dict (이번에 초안을 쓸 대상)
    drafts: dict                # req_id -> 조건 문장 목록
    feedback: dict              # req_id -> 반려 사유 (다시 쓸 대상)
    failed: dict                # req_id -> 끝내 통과하지 못한 사유
    attempts: int
    saved: list[str]
    cost_usd: float
    events: list[dict]


def initial_criteria_state(req_ids: list[str], overwrite: bool) -> CriteriaState:
    return {"req_ids": req_ids, "overwrite": overwrite, "targets": {}, "drafts": {},
            "feedback": {}, "failed": {}, "attempts": 0, "saved": [], "cost_usd": 0.0,
            "events": []}


class IntakeState(TypedDict, total=False):
    author: str
    text: str
    summary: str
    query: str                  # 요구사항 검색 질의(LLM이 업무 용어로 다시 씀)
    mentioned: list[str]        # 보고에 직접 적힌 요구사항 ID
    evidence: list[dict]        # 정규식으로 뽑은 근거 [{type, value}]
    candidates: list[dict]      # 후보 요구사항(조건 포함)
    links: list[dict]           # 매핑 결과 [{req_id, met, reason}]
    feedback: str               # 매핑 반려 사유(비어 있으면 통과)
    attempts: int
    evidence_check: list[dict]  # 근거 실존 확인 결과
    decision: dict              # 개발자 확인 결과(interrupt 재개 값)
    report_id: int
    changes: list[dict]         # 요구사항별 진척 상태 변화
    final: str
    cost_usd: float
    events: list[dict]


def initial_intake_state(author: str, text: str) -> IntakeState:
    return {"author": author, "text": text, "summary": "", "query": "", "mentioned": [],
            "evidence": [], "candidates": [], "links": [], "feedback": "", "attempts": 0,
            "evidence_check": [], "decision": {}, "report_id": 0, "changes": [], "final": "",
            "cost_usd": 0.0, "events": []}
