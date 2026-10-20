"""환경변수·경로 설정을 한곳에 모은다.

Base 코드는 모델명·경로·폴백값이 server.py와 LLM 파일마다 흩어져 있었다. 여기서는 서버,
노드, MCP 서버가 모두 이 모듈만 참조한다 — 다른 사업에 쓰려면 .env 값만 바꾸면 된다.
"""
import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"


def _path(env: str, default: Path) -> Path:
    raw = os.environ.get(env)
    if not raw:
        return default
    p = Path(raw).expanduser()
    return p if p.is_absolute() else PROJECT_ROOT / p


def _env(name: str, default: str) -> str:
    return os.environ.get(name) or default


@dataclass(frozen=True)
class Settings:
    project_name: str = field(default_factory=lambda: _env("PROJECT_NAME", "데모 사업"))
    # 요구사항·완료 조건·완료 보고를 담는 업무 DB와, 채팅 이력만 담는 세션 DB를 분리한다.
    # 세션 DB는 실행 스크립트가 기동 때마다 비우지만 업무 DB는 절대 지우지 않는다.
    db_path: Path = field(default_factory=lambda: _path("DB_PATH", DATA_DIR / "req_trace.db"))
    session_db_path: Path = field(default_factory=lambda: _path(
        "SESSION_DB_PATH", PROJECT_ROOT / "session.db"))
    output_dir: Path = field(default_factory=lambda: _path("OUTPUT_DIR", PROJECT_ROOT / "output"))
    llm_backend: str = field(default_factory=lambda: _env("LLM_BACKEND", "fake"))
    ollama_url: str = field(default_factory=lambda: _env("OLLAMA_URL", "http://127.0.0.1:11434"))
    ollama_fast_model: str = field(default_factory=lambda: _env("OLLAMA_FAST_MODEL", "qwen3:0.6b"))
    ollama_quality_model: str = field(default_factory=lambda: _env("OLLAMA_QUALITY_MODEL", "qwen3:8b"))
    ollama_timeout: float = field(default_factory=lambda: float(_env("OLLAMA_TIMEOUT", "300")))
    openai_fast_model: str = field(default_factory=lambda: _env("OPENAI_FAST_MODEL", "gpt-4o-mini"))
    openai_quality_model: str = field(default_factory=lambda: _env("OPENAI_QUALITY_MODEL", "gpt-4o"))
    # 비용 비교용 가상 단가(USD / 1K tokens). 로컬 모델은 실제 과금이 없다.
    fast_usd_per_1k: float = 0.00015
    quality_usd_per_1k: float = 0.005
    history_turns: int = field(default_factory=lambda: int(_env("HISTORY_TURNS", "10")))
    # 요구사항 여러 건을 LLM에 동시에 보낼 상한 — 로컬 Ollama는 어차피 큐잉되므로 작게 둔다.
    llm_concurrency: int = field(default_factory=lambda: int(_env("LLM_CONCURRENCY", "4")))
    # 완료 조건 초안이 검증에서 반려되면 다시 쓰게 하는 횟수
    criteria_retries: int = field(default_factory=lambda: int(_env("CRITERIA_RETRIES", "1")))
    # ── 완료 보고 정리 ──
    # 근거(파일·API·테스트) 실존 확인 대상 산출물. 데모는 sh/fetch_artifacts.sh로 받는다.
    artifact_root: Path | None = field(default_factory=lambda: _optional_path(
        "ARTIFACT_ROOT", DATA_DIR / "artifacts" / "spring-petclinic-rest"))
    glossary_file: Path = field(default_factory=lambda: _path(
        "GLOSSARY_FILE", DATA_DIR / "glossary" / "standard_terms.json"))
    # 요구사항 검색 임베더: fake 백엔드는 해시(네트워크 없음), 실모델은 Ollama bge-m3
    embedder: str = field(default_factory=lambda: _env(
        "EMBEDDER", "hash" if _env("LLM_BACKEND", "fake") == "fake" else "ollama"))
    embed_model: str = field(default_factory=lambda: _env("OLLAMA_EMBED_MODEL", "bge-m3"))
    index_cache_dir: Path = field(default_factory=lambda: _path(
        "INDEX_CACHE_DIR", PROJECT_ROOT / "output" / ".index"))
    intake_top_k: int = field(default_factory=lambda: int(_env("INTAKE_TOP_K", "8")))
    # 매핑이 검증에서 반려되면 다시 매핑하는 횟수
    intake_retries: int = field(default_factory=lambda: int(_env("INTAKE_RETRIES", "2")))


def _optional_path(env: str, default: Path) -> Path | None:
    """설정 안 했고 기본 경로도 없으면 None — 근거 확인을 '확인 불가'로 처리한다."""
    p = _path(env, default)
    return p if os.environ.get(env) or p.exists() else None


def get_settings() -> Settings:
    """호출 시점의 환경변수로 새로 만든다(테스트에서 monkeypatch로 바꿀 수 있게)."""
    return Settings()
