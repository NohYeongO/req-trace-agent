"""공용 Git 저장소 기준 근거 확인 — 네트워크 없이 임시 원격 저장소로 확인한다."""
import subprocess

import httpx
import pytest

from agent.artifacts import ArtifactChecker
from agent.repo import GitHubPRs, GitWorkspace

CONTROLLER = '''@RestController
@RequestMapping("/api/carts")
public class CartController {
    @GetMapping
    public Object getCart() { return null; }
}
'''


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def remote(tmp_path):
    """원격(bare) 저장소와, 개발자가 작업하는 별도 클론."""
    bare, dev = tmp_path / "remote.git", tmp_path / "dev"
    git(tmp_path, "init", "--quiet", "--bare", "-b", "main", str(bare))
    git(tmp_path, "clone", "--quiet", str(bare), str(dev))
    for k, v in (("user.email", "dev@example.com"), ("user.name", "dev")):
        git(dev, "config", k, v)
    (dev / "src").mkdir()
    (dev / "src" / "CartController.java").write_text(CONTROLLER)
    git(dev, "add", ".")
    git(dev, "commit", "--quiet", "-m", "장바구니 조회 구현")
    git(dev, "push", "--quiet", "origin", "HEAD:main")
    return bare, dev


def test_only_pushed_code_counts_and_new_push_is_seen(remote, tmp_path):
    bare, dev = remote
    ws = GitWorkspace(str(bare), "main", tmp_path / "cache", fetch_interval=0)
    checker = ArtifactChecker(workspace=ws)
    first = checker.check([{"type": "api", "value": "GET /api/carts"},
                           {"type": "file", "value": "CartService.java"}])
    assert [r["status"] for r in first] == ["found", "not_found"]
    assert checker.status()["mode"] == "repo" and checker.status()["operations"] == 1

    # 개발자가 로컬에서만 만든 파일은 근거가 아니다
    (dev / "src" / "CartService.java").write_text("public class CartService { void add() {} }")
    git(dev, "add", ".")
    git(dev, "commit", "--quiet", "-m", "장바구니 서비스")
    local_sha = git(dev, "rev-parse", "HEAD")
    assert checker.check([{"type": "file", "value": "CartService.java"}])[0]["status"] == "not_found"

    # 푸시하면 서버 재시작 없이 다음 확인부터 보인다
    git(dev, "push", "--quiet", "origin", "HEAD:main")
    after = checker.check([{"type": "file", "value": "CartService.java"},
                           {"type": "commit", "value": local_sha[:7]}])
    assert after[0]["status"] == "found"
    assert after[1]["status"] == "found" and "'장바구니 서비스'" in after[1]["where"]


def test_commit_on_unmerged_branch_is_not_evidence(remote, tmp_path):
    bare, dev = remote
    git(dev, "checkout", "--quiet", "-b", "feature/x")
    (dev / "src" / "X.java").write_text("class X {}")
    git(dev, "add", ".")
    git(dev, "commit", "--quiet", "-m", "미병합 작업")
    sha = git(dev, "rev-parse", "HEAD")
    git(dev, "push", "--quiet", "origin", "feature/x")
    ws = GitWorkspace(str(bare), "main", tmp_path / "cache", fetch_interval=0)
    ws.sync()
    git(ws.path, "fetch", "--quiet", "origin", "feature/x")   # 커밋 객체는 받아 와도
    r = ArtifactChecker(workspace=ws).check([{"type": "commit", "value": sha[:8]}])[0]
    assert r["status"] == "not_found" and "병합되지 않음" in r["where"]
    assert ArtifactChecker(workspace=ws).check([{"type": "commit", "value": "deadbee"}])[0]["status"] == "not_found"


def test_unreachable_repo_is_unchecked_not_crash(tmp_path):
    ws = GitWorkspace(str(tmp_path / "nope.git"), "main", tmp_path / "cache", fetch_interval=0)
    r = ArtifactChecker(workspace=ws).check([{"type": "file", "value": "A.java"}])[0]
    assert r["status"] == "unchecked" and "가져오지 못함" in r["where"]


class _Resp:
    def __init__(self, code, data=None):
        self.status_code, self._data = code, data

    def json(self):
        return self._data


def test_github_pr_check(monkeypatch):
    calls = []

    def fake_get(url, headers, timeout):
        calls.append(url)
        n = int(url.rsplit("/", 1)[1])
        if n == 10:
            return _Resp(200, {"title": "주문 조회 기능 구현", "state": "closed", "merged_at": "2026-03-07T04:17:10Z",
                               "head": {"ref": "feature/order"}, "base": {"ref": "main"}})
        if n == 11:
            return _Resp(200, {"title": "작업 중", "state": "open", "merged_at": None,
                               "head": {"ref": "feature/y"}, "base": {"ref": "main"}})
        if n == 12:
            return _Resp(403)
        return _Resp(404)

    monkeypatch.setattr(httpx, "get", fake_get)
    prs = GitHubPRs("https://github.com/NohYeongO/zerofive-store.git", "main")
    assert prs.slug == "NohYeongO/zerofive-store"
    assert prs.check(10)["status"] == "found" and "병합 2026-03-07" in prs.check(10)["where"]
    assert len(calls) == 1                                   # 같은 PR은 캐시
    assert prs.check(11)["status"] == "not_found" and "열림" in prs.check(11)["where"]
    assert prs.check(12)["status"] == "unchecked"            # 호출 제한 등
    assert prs.check(99)["status"] == "not_found"
    assert GitHubPRs("https://gitlab.example.com/a/b.git", "main").check(1)["status"] == "unchecked"


def test_local_folder_mode_rereads_files_each_check(tmp_path):
    (tmp_path / "A.java").write_text("class A {}")
    c = ArtifactChecker(tmp_path)
    assert c.check([{"type": "file", "value": "B.java"}])[0]["status"] == "not_found"
    (tmp_path / "B.java").write_text("class B {}")
    assert c.check([{"type": "file", "value": "B.java"}])[0]["status"] == "found"   # 재시작 없이 인식
    assert c.check([{"type": "pr", "value": "#1"}])[0]["status"] == "unchecked"
