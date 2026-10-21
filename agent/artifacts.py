"""산출물 근거 확인 — 완료 보고에 적힌 파일·API·코드·테스트·커밋·PR이 실제로 있는지만 본다.

구현이 '맞는지'는 판단하지 않는다(그건 개발자의 보고와 담당자 확인의 몫이다). 보고에 적힌
이름이 산출물에 존재하는지를 코드로 확인해 '근거 확인됨/없음'을 표시한다.

확인 대상은 두 가지 방식 중 하나다.
- 공용 Git 저장소(ARTIFACT_REPO_URL): 확인할 때마다 납품 브랜치를 fetch해 푸시된 코드만 본다.
  커밋은 저장소에서, PR은 GitHub API로 확인한다.
- 로컬 폴더(ARTIFACT_ROOT): 서버가 있는 컴퓨터의 폴더. 커밋·PR은 확인하지 않는다.

API는 OpenAPI 명세 파일과, 명세 파일이 없는 프로젝트를 위해 Spring 컨트롤러 어노테이션에서
뽑은 엔드포인트를 함께 본다. 파일 목록은 저장소 HEAD가 바뀌면(로컬 폴더면 매번) 다시 읽는다.
"""
import re
from pathlib import Path

import yaml

from .repo import GitHubPRs, GitWorkspace
from .spring_endpoints import parse_controller

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
    def __init__(self, root: Path | None = None, workspace: GitWorkspace | None = None,
                 prs: GitHubPRs | None = None):
        self.workspace = workspace
        self.prs = prs
        self._local = root if root and root.exists() else None
        self._version: str | None = None
        self._cache: dict = {}

    # ── 확인 대상과 캐시 ──────────────────────────────────────────────────
    @property
    def root(self) -> Path | None:
        if self.workspace is not None:
            return self.workspace.path if (self.workspace.path / ".git").exists() else None
        return self._local

    @property
    def mode(self) -> str:
        return "repo" if self.workspace is not None else ("local" if self._local else "none")

    def refresh(self) -> None:
        """저장소면 fetch해 HEAD가 바뀌었을 때, 로컬 폴더면 매번 파일 목록을 다시 읽는다."""
        version = self.workspace.sync() if self.workspace is not None else None
        if self.workspace is None or version != self._version:
            self._cache = {}
            self._version = version

    def _cached(self, key: str, build):
        if key not in self._cache:
            self._cache[key] = build()
        return self._cache[key]

    @property
    def files(self) -> list[Path]:
        def build():
            root = self.root
            return [p for p in root.rglob("*")
                    if p.is_file() and not (_SKIP_DIRS & set(p.relative_to(root).parts))]
        return self._cached("files", build)

    @property
    def specs(self) -> list[tuple[Path, dict]]:
        def build():
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
        return self._cached("specs", build)

    @property
    def operations(self) -> list[tuple[str, str, str]]:
        """(메서드, 경로, 출처). OpenAPI 명세와 Spring 컨트롤러 어노테이션을 함께 쓴다."""
        def build():
            ops = []
            for p, spec in self.specs:
                for path, item in (spec.get("paths") or {}).items():
                    ops += [(m.upper(), path, f"{self._rel(p)} (OpenAPI)") for m in _METHODS if (item or {}).get(m)]
            for p in self._code_files(False):
                if p.suffix in (".java", ".kt") and "Controller" in p.name:
                    ops += [(e.method, e.path, f"{self._rel(p)}:L{e.line} {e.handler}")
                            for e in parse_controller(self._source(p))]
            return ops
        return self._cached("operations", build)

    def _rel(self, p: Path) -> str:
        return p.relative_to(self.root).as_posix()

    def _source(self, p: Path) -> str:
        try:
            return p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return ""

    # ── 유형별 확인 ───────────────────────────────────────────────────────
    def _spec_schema(self, name: str) -> dict | None:
        """OpenAPI 스키마 이름(예: OwnerFields)도 코드 근거로 인정한다."""
        for p, spec in self.specs:
            if name in ((spec.get("components") or {}).get("schemas") or {}):
                return {"status": "found", "where": f"{self._rel(p)} (OpenAPI 스키마)"}
        return None

    def check_file(self, value: str) -> dict:
        want = value.strip("/")
        hits = [p for p in self.files if self._rel(p).endswith(want)]
        return {"status": "found", "where": self._rel(hits[0])} if hits else {"status": "not_found"}

    def check_api(self, value: str) -> dict:
        method, _, path = value.partition(" ")
        path = path.split("?")[0]
        # 보고에는 '/api'를 붙이기도 빼기도 한다 — 명세·코드 경로와 양쪽으로 맞춰 본다.
        candidates = {path, re.sub(r"^/api(?=/)", "", path), "/api" + path if not path.startswith("/api/") else path}
        for m, op_path, where in self.operations:
            if m == method.upper() and any(op_path == c or _api_regex(op_path).match(c) for c in candidates):
                return {"status": "found", "where": f"{m} {op_path} — {where}"}
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

    def check_commit(self, value: str) -> dict:
        if self.workspace is None or self.root is None:
            return {"status": "unchecked", "where": "공용 저장소(ARTIFACT_REPO_URL) 미설정이라 커밋을 확인하지 않음"}
        return self.workspace.commit(value)

    def check_pr(self, value: str) -> dict:
        if self.prs is None:
            return {"status": "unchecked", "where": "공용 저장소(ARTIFACT_REPO_URL) 미설정이라 PR을 확인하지 않음"}
        return self.prs.check(int(value.lstrip("#")))

    def check(self, items: list[dict]) -> list[dict]:
        self.refresh()
        out = []
        for item in items:
            kind, value = item.get("type"), str(item.get("value", ""))
            if kind == "pr":
                result = self.check_pr(value)
            elif kind == "commit":
                result = self.check_commit(value)
            elif self.root is None:
                why = (f"저장소를 가져오지 못함: {self.workspace.error}" if self.workspace is not None
                       else "산출물 경로(ARTIFACT_ROOT·ARTIFACT_REPO_URL) 미설정")
                result = {"status": "unchecked", "where": why}
            elif kind == "file":
                result = self.check_file(value)
            elif kind == "api":
                result = self.check_api(value)
            elif kind == "code":
                result = self.check_symbol(value)
            elif kind == "test":
                result = self.check_symbol(value, tests_only=True)
            else:
                result = {"status": "unchecked", "where": "알 수 없는 근거 유형"}
            out.append({"type": kind, "value": value, **result})
        return out

    def status(self) -> dict:
        self.refresh()
        base = {"mode": self.mode, "root": str(self.root) if self.root else None}
        if self.workspace is not None:
            base.update(repo=self.workspace.url, branch=self.workspace.branch,
                        head=(self.workspace.head or "")[:7] or None, error=self.workspace.error)
        if self.root is not None:
            base.update(files=len(self.files), operations=len(self.operations))
        return base


def make_checker(settings) -> ArtifactChecker:
    """설정으로 확인기를 만든다. 공용 저장소가 지정되면 그것이 우선이다."""
    if settings.artifact_repo_url:
        ws = GitWorkspace(settings.artifact_repo_url, settings.artifact_branch,
                          settings.repo_cache_dir, settings.repo_fetch_interval)
        return ArtifactChecker(workspace=ws,
                               prs=GitHubPRs(settings.artifact_repo_url, settings.artifact_branch,
                                             settings.github_token or None))
    return ArtifactChecker(settings.artifact_root)
