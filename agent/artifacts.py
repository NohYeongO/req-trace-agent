"""산출물 근거 확인 — 완료 보고에 적힌 파일·API·코드·테스트가 실제로 있는지만 본다.

구현이 '맞는지'는 판단하지 않는다(그건 개발자의 보고와 담당자 확인의 몫이다). 여기서는
보고에 적힌 이름이 산출물에 존재하는지를 코드로 확인해 '근거 확인됨/없음'을 표시한다.
PR·커밋은 외부 시스템이라 확인하지 않는다.
"""
import re
from functools import cached_property
from pathlib import Path

import yaml

_SKIP_DIRS = {".git", "target", "build", "node_modules", ".idea", ".gradle"}
_CODE_SUFFIXES = {".java", ".kt", ".py", ".ts", ".js", ".vue"}
_METHODS = ("get", "post", "put", "patch", "delete")


def _api_regex(path: str) -> re.Pattern:
    """'/owners/{ownerId}'와 '/owners/1' 둘 다 같은 엔드포인트로 맞추기 위한 정규식.
    경로 변수 이름이 ...Id면 숫자나 {변수}만 받는다 — '/owners/phone'이 '/owners/{ownerId}'로
    잘못 확인되지 않게 하기 위함이다."""
    parts = []
    for seg in path.strip("/").split("/"):
        if seg.startswith("{"):
            parts.append(r"(?:\d+|\{[^/]+\})" if seg[1:-1].lower().endswith("id") else r"[^/]+")
        else:
            parts.append(re.escape(seg))
    return re.compile("^/" + "/".join(parts) + "/?$")


class ArtifactChecker:
    def __init__(self, root: Path | None):
        self.root = root if root and root.exists() else None

    @cached_property
    def files(self) -> list[Path]:
        out = []
        for p in self.root.rglob("*"):
            if p.is_file() and not (_SKIP_DIRS & set(p.relative_to(self.root).parts)):
                out.append(p)
        return out

    @cached_property
    def specs(self) -> list[tuple[Path, dict]]:
        out = []
        for p in self.files:
            if p.suffix in (".yml", ".yaml", ".json") and re.match(r"(openapi|swagger)", p.name):
                try:
                    spec = yaml.safe_load(p.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if isinstance(spec, dict) and "paths" in spec:
                    out.append((p, spec))
        return out

    @cached_property
    def operations(self) -> list[tuple[str, str]]:
        ops = []
        for _, spec in self.specs:
            for path, item in (spec.get("paths") or {}).items():
                ops += [(m.upper(), path) for m in _METHODS if (item or {}).get(m)]
        return ops

    def _spec_schema(self, name: str) -> dict | None:
        """OpenAPI 스키마 이름(예: OwnerFields)도 코드 근거로 인정한다."""
        for p, spec in self.specs:
            if name in ((spec.get("components") or {}).get("schemas") or {}):
                return {"status": "found", "where": f"{self._rel(p)} (OpenAPI 스키마)"}
        return None

    def _rel(self, p: Path) -> str:
        return p.relative_to(self.root).as_posix()

    def _source(self, p: Path) -> str:
        try:
            return p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return ""

    def check_file(self, value: str) -> dict:
        want = value.strip("/")
        hits = [p for p in self.files if self._rel(p).endswith(want)]
        return {"status": "found", "where": self._rel(hits[0])} if hits else {"status": "not_found"}

    def check_api(self, value: str) -> dict:
        method, _, path = value.partition(" ")
        path = re.sub(r"^/api(?=/)", "", path.split("?")[0])
        for m, spec_path in self.operations:
            if m == method.upper() and (_api_regex(spec_path).match(path) or spec_path == path):
                return {"status": "found", "where": f"{m} {spec_path}"}
        return {"status": "not_found"}

    def _code_files(self, tests_only: bool) -> list[Path]:
        return [p for p in self.files if p.suffix in _CODE_SUFFIXES
                and (not tests_only or "test" in self._rel(p).lower())]

    def _find(self, files: list[Path], pattern: str) -> dict | None:
        for p in files:
            text = self._source(p)
            m = re.search(pattern, text)
            if m:
                line = text[:m.start()].count("\n") + 1
                return {"status": "found", "where": f"{self._rel(p)}:L{line}"}
        return None

    def check_symbol(self, value: str, tests_only: bool = False) -> dict:
        """Class / Class.method / 메서드 이름(testX)이 소스에 있는지.
        같은 이름의 클래스 파일이 없으면(라이브러리 클래스 등) 소스 안의 사용 위치를 찾는다."""
        cls, _, method = value.partition(".")
        if not cls[0].isupper():        # 메서드 이름만 주어진 경우(testCreateOwnerSuccess)
            cls, method = "", value
        files = self._code_files(tests_only)
        own = [p for p in files if p.stem == cls] if cls else files
        if cls and own and not method:
            return {"status": "found", "where": self._rel(own[0])}
        if method:
            hit = self._find(own, rf"\b{re.escape(method)}\s*\(")
            if hit:
                return hit
        if cls and not own:
            hit = self._find(files, rf"\b{re.escape(cls)}\b" + (
                rf"[\s\S]{{0,200}}\b{re.escape(method)}\s*\(" if method else ""))
            if hit:
                return {**hit, "where": hit["where"] + " (사용 위치)"}
            if not method and not tests_only:
                return self._spec_schema(cls) or {"status": "not_found"}
        return {"status": "not_found"}

    def check(self, items: list[dict]) -> list[dict]:
        out = []
        for item in items:
            kind, value = item.get("type"), str(item.get("value", ""))
            if self.root is None:
                result = {"status": "unchecked", "where": "산출물 경로(ARTIFACT_ROOT) 미설정"}
            elif kind == "file":
                result = self.check_file(value)
            elif kind == "api":
                result = self.check_api(value)
            elif kind == "code":
                result = self.check_symbol(value)
            elif kind == "test":
                result = self.check_symbol(value, tests_only=True)
            else:
                result = {"status": "unchecked", "where": "외부 시스템(PR·커밋)은 확인하지 않음"}
            out.append({"type": kind, "value": value, **result})
        return out
