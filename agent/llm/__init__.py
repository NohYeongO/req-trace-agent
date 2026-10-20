"""LLM 백엔드 — fake(결정론) / ollama(로컬 sLLM) / openai(상용 API).

ollama와 openai는 공통 로직(RemoteLLM)을 공유하고 통신 방식(_complete/_stream)만 다르다.
"""
from ..config import Settings


def build_llms(settings: Settings):
    """(fast, quality) 모델 쌍을 만든다. LLM_BACKEND 값이 잘못되면 바로 실패시킨다."""
    backend = settings.llm_backend
    turns = settings.history_turns
    if backend == "ollama":
        from .ollama import OllamaLLM
        mk = lambda model, usd: OllamaLLM(model, usd, settings.ollama_url,
                                          settings.ollama_timeout, turns)
        return (mk(settings.ollama_fast_model, settings.fast_usd_per_1k),
                mk(settings.ollama_quality_model, settings.quality_usd_per_1k))
    if backend == "openai":
        from .openai import OpenAILLM
        return (OpenAILLM(settings.openai_fast_model, settings.fast_usd_per_1k, turns),
                OpenAILLM(settings.openai_quality_model, settings.quality_usd_per_1k, turns))
    if backend == "fake":
        from .fake import FakeLLM
        return (FakeLLM("fake:fast", settings.fast_usd_per_1k, turns),
                FakeLLM("fake:quality", settings.quality_usd_per_1k, turns))
    raise ValueError(f"알 수 없는 LLM_BACKEND: {backend!r} (fake | ollama | openai)")
