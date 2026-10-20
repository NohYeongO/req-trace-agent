"""공통 픽스처 — 네트워크·Ollama 없이 도는 테스트 환경.

SupervisorDeps에 FakeLLM과 메모리 MCP 스텁을 주입하면 그래프 코드를 한 줄도 바꾸지 않고
테스트할 수 있다(의존성 주입). MCP 실연동은 test_mcp.py가 실제 subprocess로 확인한다.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent.config import Settings          # noqa: E402
from agent.deps import SupervisorDeps      # noqa: E402
from agent.llm.fake import FakeLLM         # noqa: E402
from agent.store import ProjectStore, SqliteSessionStore   # noqa: E402


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(project_name="테스트 사업", db_path=tmp_path / "req_trace.db",
                    session_db_path=tmp_path / "session.db", output_dir=tmp_path / "out",
                    llm_backend="fake")


@pytest.fixture
def store(settings):
    s = ProjectStore(settings.db_path)
    yield s
    s.close()


class StubMCP:
    """mcp_server.py와 같은 Tool 이름·응답 형태를 메모리에서 흉내 낸다."""

    def __init__(self, store: ProjectStore):
        self.store = store
        self.sessions = {"trace": None}
        self.calls: list[str] = []

    async def call_tool(self, name: str, arguments: dict, server: str | None = None) -> dict:
        self.calls.append(name)
        if name == "get_store_status":
            return {"counts": self.store.counts()}
        if name == "list_requirements":
            return {"requirements": self.store.list_requirements()}
        if name == "get_requirement":
            return self.store.get_requirement(arguments["req_id"]) or {"error": "없음"}
        raise ValueError(name)


@pytest.fixture
def deps(settings, store):
    session = SqliteSessionStore(settings.session_db_path)
    d = SupervisorDeps(fast_llm=FakeLLM("fake:fast", 0.00015),
                       quality_llm=FakeLLM("fake:quality", 0.005),
                       mcp=StubMCP(store), store=store, session_store=session,
                       settings=settings)
    yield d
    session.close()
