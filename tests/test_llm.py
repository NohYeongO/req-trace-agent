import pytest

from agent.config import Settings
from agent.llm import build_llms
from agent.llm.remote import parse_json
from agent.llm.rules import route_by_rule


@pytest.mark.parametrize("query, route", [
    ("안녕, 너는 누구야?", "chat"),
    ("SFR-005 완료됐어?", "status"),
    ("보안 요구사항 진행률 알려줘", "status"),
    ("담당자별 현황 보여줘", "status"),
    ("이번 주 완료된 거 정리해줘", "summary"),
    ("주간 보고서 만들어줘", "summary"),
])
def test_route_rules(query, route):
    assert route_by_rule(query) == route


@pytest.mark.parametrize("content, expected", [
    ('{"route": "status"}', {"route": "status"}),
    ('<think>음...</think>\n{"route": "chat"}', {"route": "chat"}),
    ('```json\n{"route": "summary"}\n```', {"route": "summary"}),
    ("분류 결과: status", {}),
    ("[1, 2]", {}),
])
def test_parse_json_tolerates_model_noise(content, expected):
    assert parse_json(content) == expected


def test_build_llms_rejects_unknown_backend():
    with pytest.raises(ValueError):
        build_llms(Settings(llm_backend="gemini"))


def test_build_llms_fake_pair():
    fast, quality = build_llms(Settings(llm_backend="fake"))
    assert fast.name == "fake:fast" and quality.name == "fake:quality"


async def test_remote_route_falls_back_to_rules_when_output_breaks():
    from agent.llm.remote import RemoteLLM

    class Broken(RemoteLLM):
        async def _complete(self, system, user, schema):
            return "모르겠습니다", self._usage(10)

    result, usage = await Broken("broken", 0.001).route("SFR-001 끝났어?")
    assert result == {"route": "status"}
    assert usage["tokens"] == 10
