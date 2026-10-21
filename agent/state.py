"""그래프 상태 정의."""
from typing import TypedDict


class ChatState(TypedDict, total=False):
    query: str
    thread_id: str
    author: str           # 화면에 저장된 작성자 이름(채팅으로 완료 보고할 때 씀)
    history: list[dict]
    route: str            # chat | status | summary | report
    target: dict          # 질의응답: 질문 분석(유형·대상·기간, agent/qa.py analyze)
    calls: list[dict]     # 질의응답: 부를 MCP Tool 계획
    results: list[dict]   # 질의응답: Tool 결과
    core: str             # 질의응답: 조회 결과로 코드가 쓴 답 본문(코멘트 검증 기준)
    draft: str            # 질의응답: LLM이 본문 뒤에 붙일 코멘트
    feedback: str         # 답변 검증 반려 사유
    attempts: int
    used_fallback: bool   # LLM 코멘트가 끝내 검증을 못 넘어 본문만 줬는지
    run_id: str           # 완료 보고 위임: 보고 정리 에이전트 실행 ID
    confirm: dict         # 완료 보고 위임: 개발자 확인 카드 내용
    final: str
    last_prompt: str
    cost_usd: float
    events: list[dict]


def initial_state(query: str, thread_id: str, history: list[dict], author: str = "") -> ChatState:
    return {"query": query, "thread_id": thread_id, "author": author, "history": history,
            "route": "", "target": {}, "calls": [], "results": [], "core": "", "draft": "", "feedback": "",
            "attempts": 0, "used_fallback": False, "run_id": "", "confirm": {}, "final": "",
            "last_prompt": "", "cost_usd": 0.0, "events": []}


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
    mentioned: list[str]        # 보고에 직접 적힌 요구사항 ID (양식에서 고른 것 포함)
    selected: list[str]         # 작성자가 양식에서 고른 요구사항 ID — AI가 매핑하지 않아도 확인 카드에 넣는다
    form_evidence: list[dict]   # 양식 근거 칸으로 받은 근거(정규화됨)
    evidence: list[dict]        # 양식 근거 + 문장에서 정규식으로 뽑은 근거 [{type, value, source}]
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


def initial_intake_state(author: str, text: str, evidence: list[dict] | None = None,
                         req_ids: list[str] | None = None) -> IntakeState:
    return {"author": author, "text": text, "summary": "", "query": "", "mentioned": [],
            "selected": list(req_ids or []), "form_evidence": list(evidence or []),
            "evidence": [], "candidates": [], "links": [], "feedback": "", "attempts": 0,
            "evidence_check": [], "decision": {}, "report_id": 0, "changes": [], "final": "",
            "cost_usd": 0.0, "events": []}
