"""LLM 없이 쓰는 결정론 규칙 — FakeLLM의 판단 근거이자 실모델 라우팅의 보정값."""
import re

_REQ_ID = re.compile(r"(?<![A-Za-z0-9])[A-Z]{3}-\d{3}(?!\d)")
_SUMMARY = re.compile(r"정리|요약|리포트|보고서|주간|이번\s*주|지난\s*주|이번\s*달|지난\s*달")
_STATUS = re.compile(r"진척|진행률|현황|완료|남은|미완료|미착수|부분|몇\s*건|담당자|요구사항|끝났|됐|안\s*된|한\s*(거|것|일)|했는지"
                     r"|뭐\s*했|뭘\s*했|우선순위|뭐부터|먼저\s*해|위험|주의|정체|조건")
# 완료 보고: 끝낸 일을 서술하는 문장(과거형 완료 동사). 질문이면 보고가 아니라 현황 질의다.
_REPORT = re.compile(r"끝냈|끝났습니다|끝났어요|완료했|완료됐습니다|완료되었습니다|만들었|구현했|붙였|"
                     r"마무리했|반영했|작업했|추가했|적용했|넣었|수정했|개발했")
_QUESTION = re.compile(r"\?|알려|뭐|무엇|얼마|어때|몇|어떻게|어디|인가요|나요|까요|했나|됐나|"
                       r"(끝났|됐|했)어\s*$|(끝났|됐|했)니")


def is_question(query: str) -> bool:
    return bool(_QUESTION.search(query.strip()))


def route_by_rule(query: str) -> str:
    if _REPORT.search(query) and not is_question(query):
        return "report"
    if _SUMMARY.search(query):
        return "summary"
    if _REQ_ID.search(query) or _STATUS.search(query):
        return "status"
    return "chat"


def guard_route(query: str, llm_route: str) -> str:
    """LLM 분류를 코드가 최종 확인한다 — 질문을 보고로 잘못 받아 저장 흐름으로 가거나,
    업무 질문을 잡담으로 흘려보내는 경우만 바로잡는다."""
    rule = route_by_rule(query)
    if llm_route == "report" and is_question(query):
        return rule if rule != "report" else "status"
    # 완료 동사로 끝낸 일을 서술했는데 질문 형태가 아니면 보고로 본다. qwen3:0.6b는 'API·완료'
    # 같은 단어만 보고 이런 문장을 현황 질의로 분류했다.
    if rule == "report" and llm_route != "report":
        return "report"
    if llm_route == "chat" and rule != "chat":
        return rule
    return llm_route
