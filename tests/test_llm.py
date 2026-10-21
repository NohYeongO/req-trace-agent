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
    ("김민준이 한 거 알려줘", "status"),
    ("SFR-005 끝났어?", "status"),
    ("수정했는데 반영 됐나요?", "status"),
    ("보호자 검색 API 만들었고 testGetOwnersListSuccess 통과했습니다", "report"),
    ("진료 기록 삭제도 마무리했어요", "report"),
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


@pytest.mark.parametrize("query, llm, final", [
    ("SFR-005 끝났어?", "report", "status"),        # 질문을 보고로 받으면 저장 흐름으로 가므로 막는다
    ("수의사 API 만들었습니다", "chat", "report"),   # 업무 문장을 잡담으로 흘리지 않는다
    ("안녕하세요", "chat", "chat"),
    ("이번 주 정리해줘", "summary", "summary"),
])
def test_guard_route(query, llm, final):
    from agent.llm.rules import guard_route
    assert guard_route(query, llm) == final


async def test_remote_route_falls_back_to_rules_when_output_breaks():
    from agent.llm.remote import RemoteLLM

    class Broken(RemoteLLM):
        async def _complete(self, system, user, schema):
            return "모르겠습니다", self._usage(10)

    result, usage = await Broken("broken", 0.001).route("SFR-001 끝났어?")
    assert result == {"route": "status"}
    assert usage["tokens"] == 10
