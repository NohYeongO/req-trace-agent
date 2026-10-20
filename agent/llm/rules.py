"""LLM 없이 쓰는 결정론 규칙 — FakeLLM의 판단 근거이자 실모델 출력이 깨졌을 때의 보정값."""
import re

_REQ_ID = re.compile(r"\b[A-Z]{3}-\d{3}\b")
_SUMMARY = re.compile(r"정리|요약|리포트|보고서|주간|이번\s*주|지난\s*주|이번\s*달")
_STATUS = re.compile(r"진척|진행률|현황|완료|남은|미완료|미착수|부분|몇\s*건|담당자|요구사항")


def route_by_rule(query: str) -> str:
    if _SUMMARY.search(query):
        return "summary"
    if _REQ_ID.search(query) or _STATUS.search(query):
        return "status"
    return "chat"
