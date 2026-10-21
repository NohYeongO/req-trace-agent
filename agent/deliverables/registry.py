"""산출물 양식 등록부 — 문서 종류별 모듈. 새 산출물은 같은 함수들을 가진 모듈을 하나 더하면 된다.

모듈이 갖출 것: DOC_TYPE, TITLE, COLLECT_TOOL(MCP Tool 이름), collect_args(source),
build(분석 결과, 진척, 완료 보고, meta) → doc(tasks 포함), write_task(llm, doc, task, feedback, on_token),
check_task(doc, task, value) → 문제 목록, apply_task, fallback_task, finalize(doc)
"""
from . import dev_spec, test_report

DOC_TYPES = {test_report.DOC_TYPE: test_report, dev_spec.DOC_TYPE: dev_spec}


def get(doc_type: str):
    if doc_type not in DOC_TYPES:
        raise ValueError(f"알 수 없는 문서 종류: {doc_type}")
    return DOC_TYPES[doc_type]
