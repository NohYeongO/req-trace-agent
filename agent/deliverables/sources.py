"""테스트 결과 자료의 위치 — 데모 자료(data/demo/test-results/<이름>)와 업로드 자료(uploads/test-results/<id>).

MCP Tool이 경로를 그대로 받지 않고 'demo:<이름>'·'upload:<id>' 형식의 이름만 받는다 — 허용한
폴더 밖의 파일을 읽지 못하게 하기 위함이다.
"""
import io
import re
import uuid
import zipfile
from pathlib import Path

from ..config import DATA_DIR

DEMO_DIR = DATA_DIR / "demo" / "test-results"
_NAME = re.compile(r"^[\w가-힣.\-]+$")
MAX_UPLOAD = 20 * 1024 * 1024
MAX_FILES = 2000


def upload_root(settings) -> Path:
    return settings.upload_dir / "test-results"


def resolve(source: str, settings) -> Path:
    kind, _, name = source.partition(":")
    if not _NAME.match(name or ""):
        raise ValueError(f"잘못된 자료 이름: {source}")
    base = {"demo": DEMO_DIR, "upload": upload_root(settings)}.get(kind)
    if base is None:
        raise ValueError(f"알 수 없는 자료 종류: {kind}")
    path = (base / name).resolve()
    if base.resolve() not in path.parents or not path.is_dir():
        raise ValueError(f"자료를 찾을 수 없습니다: {source}")
    return path


def describe(path: Path) -> str:
    meta = path / "META.txt"
    return meta.read_text(encoding="utf-8").strip() if meta.exists() else ""


def list_sources(settings) -> list[dict]:
    out = []
    for kind, base in (("demo", DEMO_DIR), ("upload", upload_root(settings))):
        if base.is_dir():
            for p in sorted(base.iterdir()):
                if p.is_dir():
                    out.append({"source": f"{kind}:{p.name}", "kind": kind, "name": p.name,
                                "files": sum(1 for _ in p.rglob("*.xml")), "description": describe(p)})
    return out


def save_upload(data: bytes, filename: str, settings, label: str = "") -> str:
    """결과 zip을 풀어 저장한다. XML만 꺼내고, 경로 조작(../)·용량·개수를 막는다."""
    if len(data) > MAX_UPLOAD:
        raise ValueError("파일이 너무 큽니다(최대 20MB).")
    if not filename.lower().endswith(".zip"):
        raise ValueError("테스트 결과 폴더(build/test-results, jacoco XML)를 zip으로 묶어 올려 주세요.")
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ValueError("zip 파일을 열 수 없습니다.")
    names = [n for n in zf.namelist() if n.lower().endswith(".xml") and not n.endswith("/")]
    if not names:
        raise ValueError("zip 안에 XML(JUnit·JaCoCo) 파일이 없습니다.")
    if len(names) > MAX_FILES:
        raise ValueError("파일이 너무 많습니다.")
    upload_id = uuid.uuid4().hex[:8]
    root = upload_root(settings) / upload_id
    for n in names:
        parts = [p for p in Path(n).parts if p not in ("", ".", "..") and not p.endswith(":")]
        target = (root / Path(*parts)).resolve()
        if root.resolve() not in target.parents:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(zf.read(n))
    (root / "META.txt").write_text(f"업로드: {filename}" + (f"\n{label}" if label else ""), encoding="utf-8")
    return f"upload:{upload_id}"
