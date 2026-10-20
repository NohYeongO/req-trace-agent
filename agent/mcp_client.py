"""MCP 서버 여러 개를 subprocess(stdio)로 1회씩 기동해 재사용하는 클라이언트.

서버(lifespan)에서 한 번만 연결을 만들고 모든 요청이 공유한다. Tool·Resource·Prompt를
요청할 때 어느 서버가 들고 있는지 호출하는 쪽이 알 필요가 없다 — 연결된 서버들을 조회해
이름이 맞는 서버를 찾고(find_*), Tool 소유 서버는 캐시한다.

Base 코드의 '첫 호출 일부러 타임아웃' 데모 장치는 제거했다. 대신 Tool 호출에 실제
타임아웃을 걸어 asyncio.TimeoutError가 나면 retry.with_retry가 재시도할 수 있게 했다.
"""
import asyncio
import json
import os
import sys
from contextlib import AsyncExitStack
from pathlib import Path

from langsmith import traceable
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER_DIR = Path(__file__).resolve().parent.parent
DEFAULT_SERVER_SCRIPTS = {
    "trace": SERVER_DIR / "mcp_server.py",
}


def _attr(obj, *names):
    """mcp SDK 버전에 따라 필드명이 camelCase(1.x)와 snake_case(2.x)로 갈린다 — 둘 다 시도한다."""
    for name in names:
        if hasattr(obj, name):
            return getattr(obj, name)
    raise AttributeError(f"{type(obj).__name__!r} has none of {names!r}")


class MCPClient:
    def __init__(self, server_scripts: dict[str, Path] | None = None,
                 env: dict[str, str] | None = None, tool_timeout: float = 30.0):
        self._server_scripts = server_scripts or DEFAULT_SERVER_SCRIPTS
        self._env = env or {}
        self._tool_timeout = tool_timeout
        self._stack: AsyncExitStack | None = None
        self.sessions: dict[str, ClientSession] = {}
        self._lock = asyncio.Lock()
        self._tool_owner: dict[str, str] = {}

    async def start(self) -> None:
        self._stack = AsyncExitStack()
        for server_name, script in self._server_scripts.items():
            params = StdioServerParameters(
                command=sys.executable, args=[str(script)],
                env={**os.environ, **self._env, "FASTMCP_LOG_LEVEL": "ERROR"})
            read, write = await self._stack.enter_async_context(stdio_client(params))
            session = await self._stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            self.sessions[server_name] = session

    async def stop(self) -> None:
        if self._stack is not None:
            await self._stack.aclose()
            self._stack = None
            self.sessions = {}
            self._tool_owner = {}

    @traceable(run_type="tool", name="mcp.find_tool")
    async def find_tool(self, tool_name: str) -> str:
        """연결된 서버들을 순서대로 조회해 tool_name을 제공하는 서버를 찾는다."""
        if tool_name not in self._tool_owner:
            for server_name, session in self.sessions.items():
                async with self._lock:
                    result = await session.list_tools()
                for tool in result.tools:
                    self._tool_owner.setdefault(tool.name, server_name)
        if tool_name not in self._tool_owner:
            raise ValueError(f"MCP tool not found on any connected server: {tool_name}")
        return self._tool_owner[tool_name]

    @traceable(run_type="tool", name="mcp.call_tool")
    async def call_tool(self, name: str, arguments: dict, server: str | None = None) -> dict:
        server = server or await self.find_tool(name)
        async with self._lock:
            result = await asyncio.wait_for(self.sessions[server].call_tool(name, arguments),
                                            timeout=self._tool_timeout)
        if getattr(result, "isError", False) or getattr(result, "is_error", False):
            raise RuntimeError(f"MCP tool {name} failed: {result.content[0].text}")
        return json.loads(result.content[0].text)

    @traceable(run_type="tool", name="mcp.find_resource_template")
    async def find_resource_template(self, template_name: str) -> tuple[str, str]:
        """연결된 서버들을 순서대로 조회해 template_name을 제공하는 서버를 찾는다."""
        for server_name, session in self.sessions.items():
            async with self._lock:
                result = await session.list_resource_templates()
            for t in _attr(result, "resourceTemplates", "resource_templates"):
                if t.name == template_name:
                    return server_name, _attr(t, "uriTemplate", "uri_template")
        raise ValueError(
            f"MCP resource template not found on any connected server: {template_name}")

    @traceable(run_type="tool", name="mcp.read_resource")
    async def read_resource(self, uri: str, server: str) -> str:
        async with self._lock:
            result = await self.sessions[server].read_resource(uri)
        return result.contents[0].text

    @traceable(run_type="tool", name="mcp.find_prompt")
    async def find_prompt(self, prompt_name: str) -> str:
        """연결된 서버들을 순서대로 조회해 prompt_name을 제공하는 서버를 찾는다."""
        for server_name, session in self.sessions.items():
            async with self._lock:
                result = await session.list_prompts()
            if any(p.name == prompt_name for p in result.prompts):
                return server_name
        raise ValueError(f"MCP prompt not found on any connected server: {prompt_name}")

    @traceable(run_type="tool", name="mcp.get_prompt")
    async def get_prompt(self, name: str, arguments: dict, server: str) -> str:
        async with self._lock:
            result = await self.sessions[server].get_prompt(name, arguments)
        return result.messages[0].content.text
