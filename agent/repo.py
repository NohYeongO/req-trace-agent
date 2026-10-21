"""공용 Git 저장소 연동 — 근거 확인을 '팀 저장소에 푸시된 코드' 기준으로 한다.

개발자는 각자 자기 PC에서 작업하므로 서버가 그 파일을 볼 수 없다. 대신 서버가 팀 저장소를
clone해 두고, 확인할 때마다 납품 브랜치(기본 main)를 fetch해 최신 상태로 맞춘다. 공공 SI
검수도 납품 저장소에 들어간 코드가 기준이라, 푸시되지 않은 작업은 근거로 인정하지 않는다.

- GitWorkspace: clone·fetch(간격 제한), HEAD, 커밋 확인(존재·브랜치 포함·바뀐 파일)
- GitHubPRs: PR 번호 확인(제목·브랜치·병합 여부). github.com 저장소만, 토큰은 선택

작업 사본(cache_dir 아래)은 이 서버 전용이다 — fetch 후 reset --hard로 원격과 똑같이 맞춘다.
"""
import os
import re
import subprocess
import time
from pathlib import Path

import httpx

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")
_GITHUB = re.compile(r"github\.com[:/]([^/]+)/([^/.]+?)(?:\.git)?/?$")


class GitError(RuntimeError):
    pass


def _git(args: list[str], cwd: Path | None = None, timeout: float = 120) -> str:
    try:
        r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout,
                           env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})   # 인증 프롬프트로 멈추지 않게
    except (OSError, subprocess.TimeoutExpired) as e:
        raise GitError(f"git {args[0]} 실패: {e}") from e
    if r.returncode != 0:
        raise GitError(f"git {' '.join(args[:2])} 실패: {r.stderr.strip()[:200]}")
    return r.stdout.strip()


class GitWorkspace:
    def __init__(self, url: str, branch: str, cache_dir: Path, fetch_interval: float = 60.0):
        self.url = url
        self.branch = branch
        self.path = cache_dir / _SAFE.sub("_", url.split("://")[-1]).strip("_")
        self.fetch_interval = fetch_interval
        self._last_fetch = 0.0
        self.head: str | None = None
        self.error: str | None = None

    def sync(self, force: bool = False) -> str | None:
        """저장소를 원격 납품 브랜치와 같게 맞추고 HEAD를 돌려준다. 네트워크가 안 되면 마지막
        상태를 그대로 쓰고 error에 사유를 남긴다(확인 자체를 막지 않기 위함)."""
        if not force and self.head and time.monotonic() - self._last_fetch < self.fetch_interval:
            return self.head
        try:
            if not (self.path / ".git").exists():
                self.path.parent.mkdir(parents=True, exist_ok=True)
                _git(["clone", "--quiet", "--filter=blob:none", "--branch", self.branch, self.url, str(self.path)],
                     timeout=300)
            else:
                _git(["fetch", "--quiet", "origin", self.branch], self.path)
                _git(["reset", "--quiet", "--hard", f"origin/{self.branch}"], self.path)
            self.head = _git(["rev-parse", "HEAD"], self.path)
            self.error = None
        except GitError as e:
            self.error = str(e)
            if (self.path / ".git").exists() and not self.head:
                self.head = _git(["rev-parse", "HEAD"], self.path)
        self._last_fetch = time.monotonic()
        return self.head

    def commit(self, sha: str) -> dict:
        """커밋이 있는지, 납품 브랜치에 들어갔는지, 무엇을 바꿨는지."""
        if not re.fullmatch(r"[0-9a-fA-F]{7,40}", sha):
            return {"status": "not_found", "where": "커밋 해시 형식이 아님"}
        try:
            full = _git(["rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}"], self.path)
        except GitError:
            return {"status": "not_found", "where": f"저장소에 없는 커밋({self.branch} 기준 fetch 결과)"}
        subject = _git(["log", "-1", "--format=%s", full], self.path)
        date = _git(["log", "-1", "--format=%cs", full], self.path)
        files = [f for f in _git(["show", "--name-only", "--format=", full], self.path).splitlines() if f]
        try:
            _git(["merge-base", "--is-ancestor", full, f"origin/{self.branch}"], self.path)
        except GitError:
            return {"status": "not_found", "where": f"커밋 '{subject}'은 있으나 {self.branch}에 병합되지 않음"}
        return {"status": "found", "where": f"커밋 {full[:7]} '{subject}' ({date}, 파일 {len(files)}개)",
                "files": files[:20]}


class GitHubPRs:
    """github.com 저장소의 PR 번호를 확인한다. 공개 저장소는 토큰 없이도 되지만 시간당 호출
    제한(60회)이 있어 결과를 캐시한다. 토큰(GITHUB_TOKEN)을 주면 제한이 늘고 비공개 저장소도 된다."""

    def __init__(self, repo_url: str, branch: str, token: str | None = None, timeout: float = 10.0):
        m = _GITHUB.search(repo_url or "")
        self.slug = f"{m.group(1)}/{m.group(2)}" if m else None
        self.branch = branch
        self.token = token
        self.timeout = timeout
        self._cache: dict[int, dict] = {}

    def check(self, number: int) -> dict:
        if self.slug is None:
            return {"status": "unchecked", "where": "GitHub 저장소가 아니라 PR을 확인하지 않음"}
        if number in self._cache:
            return self._cache[number]
        headers = {"Accept": "application/vnd.github+json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        try:
            r = httpx.get(f"https://api.github.com/repos/{self.slug}/pulls/{number}", headers=headers,
                          timeout=self.timeout)
        except httpx.HTTPError as e:
            return {"status": "unchecked", "where": f"GitHub 연결 실패({type(e).__name__})"}
        if r.status_code == 404:
            result = {"status": "not_found", "where": f"{self.slug}에 PR #{number} 없음"}
        elif r.status_code != 200:
            return {"status": "unchecked", "where": f"GitHub 응답 {r.status_code}(호출 제한일 수 있음)"}
        else:
            pr = r.json()
            title, head, base = pr["title"], pr["head"]["ref"], pr["base"]["ref"]
            if pr.get("merged_at") and base == self.branch:
                result = {"status": "found",
                          "where": f"PR #{number} '{title}' ({head} → {base}, 병합 {pr['merged_at'][:10]})"}
            else:
                state = "병합됨" if pr.get("merged_at") else ("열림" if pr["state"] == "open" else "닫힘(미병합)")
                result = {"status": "not_found",
                          "where": f"PR #{number} '{title}'은 {head} → {base}, {state} — {self.branch} 미반영"}
        self._cache[number] = result
        return result
