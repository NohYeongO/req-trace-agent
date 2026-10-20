"""의존성 주입.

노드 함수가 전역 변수나 closure에 기대지 않도록, 그래프가 쓰는 모든 의존성을
SupervisorDeps 하나에 명시적으로 담아 functools.partial로 각 노드에 주입한다.
테스트에서는 FakeLLM과 메모리 MCP 스텁을 꽂아 그래프 코드를 그대로 실행한다.
"""
from dataclasses import dataclass
from typing import Any

from .config import Settings


@dataclass
class SupervisorDeps:
    fast_llm: Any        # 분류·추출 등 짧은 단계용 저비용 모델
    quality_llm: Any     # 사용자에게 보여줄 답변 작성용 모델
    mcp: Any             # MCP stdio 클라이언트 (Tool/Resource/Prompt)
    store: Any           # 업무 DB (요구사항·완료 조건·완료 보고)
    session_store: Any   # 채팅 이력 DB
    settings: Settings
