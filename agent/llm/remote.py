"""실모델 공통 로직 — 프롬프트 조립, JSON 파싱, 형식 붕괴 시 보정.

하위 클래스는 _complete(system, user, schema)와 _stream(system, user, on_token) 두 개만
구현한다. Base 코드에서 ollama/openai 파일에 75% 가까이 복사돼 있던 로직을 여기로 모았다.
"""
import json
import re

from langsmith import traceable

from .. import prompts
from ..requirements import REQ_ID_RE
from .rules import guard_route, route_by_rule


def parse_json(content: str) -> dict:
    """모델 출력에서 JSON 객체 하나를 꺼낸다. <think> 블록·코드펜스·앞뒤 잡음을 견딘다."""
    content = re.sub(r"<think>.*?</think>", "", content, flags=re.S).strip()
    try:
        data = json.loads(content)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", content, re.S)
        if m:
            try:
                data = json.loads(m.group(0))
                return data if isinstance(data, dict) else {}
            except json.JSONDecodeError:
                pass
    return {}


def render_history(history: list[dict], turns: int) -> str:
    return "\n".join(f"{m['role']}: {m['content']}" for m in history[-turns * 2:])


class RemoteLLM:
    def __init__(self, model: str, usd_per_1k_tokens: float, history_turns: int = 10):
        self.model = model
        self.usd_per_1k = usd_per_1k_tokens
        self.history_turns = history_turns
        self.name = model

    def _usage(self, tokens: int, prompt: str | None = None) -> dict:
        u = {"model": self.name, "tokens": tokens,
             "usd": round(tokens / 1000 * self.usd_per_1k, 6)}
        if prompt is not None:
            u["prompt"] = prompt
        return u

    async def _complete(self, system: str, user: str, schema: dict | None) -> tuple[str, dict]:
        raise NotImplementedError

    async def _stream(self, system: str, user: str, on_token=None) -> tuple[str, dict]:
        raise NotImplementedError

    @traceable(run_type="llm", name="llm.route")
    async def route(self, query: str) -> tuple[dict, dict]:
        content, usage = await self._complete(prompts.ROUTE_SYSTEM, query, prompts.ROUTE_SCHEMA)
        route = parse_json(content).get("route")
        if route not in prompts.ROUTES:   # 형식 붕괴 — 키워드 규칙으로 보정
            route = route_by_rule(query)
        return {"route": guard_route(query, route)}, usage

    @traceable(run_type="llm", name="llm.draft_criteria")
    async def draft_criteria(self, req: dict, feedback: str | None = None) -> tuple[list[str], dict]:
        user = prompts.render_requirement(req)
        if feedback:
            user += f"\n\n이전 초안이 반려된 이유(반드시 고쳐서 다시 작성): {feedback}"
        content, usage = await self._complete(prompts.CRITERIA_SYSTEM, user, prompts.CRITERIA_SCHEMA)
        items = parse_json(content).get("criteria", [])
        return [str(i).strip() for i in items if isinstance(i, (str, int, float))], usage

    @traceable(run_type="llm", name="llm.summarize_report")
    async def summarize_report(self, text: str) -> tuple[dict, dict]:
        content, usage = await self._complete(prompts.INTAKE_SUMMARY_SYSTEM, text,
                                              prompts.INTAKE_SUMMARY_SCHEMA)
        raw = parse_json(content)
        summary = str(raw.get("summary") or "").strip() or text.strip().split("\n")[0][:60]
        return {"summary": summary, "query": str(raw.get("query") or "").strip() or text}, usage

    @traceable(run_type="llm", name="llm.map_report")
    async def map_report(self, text: str, candidates: list[dict], procedure: str,
                         feedback: str | None = None) -> tuple[list[dict], dict]:
        user = (f"{procedure}\n\n## 후보 요구사항과 완료 조건\n{prompts.render_candidates(candidates)}")
        if feedback:
            user += f"\n\n## 이전 매핑이 반려된 이유(반드시 고칠 것)\n{feedback}"
        content, usage = await self._complete(prompts.INTAKE_MAP_SYSTEM, user, prompts.INTAKE_MAP_SCHEMA)
        links = []
        for l in parse_json(content).get("links", []):
            if isinstance(l, dict) and isinstance(l.get("req_id"), str):
                met = [int(m) for m in l.get("met", []) if str(m).lstrip("-").isdigit()]
                # 형식 보정: qwen3:8b는 "SFR-004 보호자 삭제"처럼 이름까지 붙여 쓰고, 반려 사유를
                # 줘도 반복했다. 내용이 아니라 형식 문제라 반려 대신 고유번호만 뽑아 쓴다.
                m = REQ_ID_RE.search(l["req_id"])
                links.append({"req_id": m.group(1) if m else l["req_id"].strip(), "met": met,
                              "reason": str(l.get("reason", ""))[:200]})
        return links, usage

    @traceable(run_type="llm", name="llm.answer_status")
    async def answer_status(self, query: str, facts: str, mode: str, feedback: str | None = None,
                            on_token=None) -> tuple[str, dict]:
        system = prompts.SUMMARY_SYSTEM if mode == "summary" else prompts.STATUS_SYSTEM
        return await self._stream(system, prompts.render_status_input(query, facts, feedback), on_token)

    @traceable(run_type="llm", name="llm.chat")
    async def chat(self, query: str, history: list[dict], on_token=None) -> tuple[str, dict]:
        user = (f"## 지금까지의 대화\n{render_history(history, self.history_turns) or '(없음)'}\n\n"
                f"## 사용자의 새 메시지\n{query}")
        return await self._stream(prompts.CHAT_SYSTEM, user, on_token)
