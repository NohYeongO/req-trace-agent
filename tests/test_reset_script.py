"""sh/reset_data.sh — 확인·백업·삭제·재시드. 경로는 환경변수로 임시 폴더를 가리킨다."""
import os
import shutil
import sqlite3
import subprocess

import pytest

from agent.config import PROJECT_ROOT
from agent.store import ProjectStore
from tools.seed_demo import seed

SCRIPT = PROJECT_ROOT / "sh" / "reset_data.sh"
pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="bash 필요")


@pytest.fixture
def env(tmp_path):
    paths = {"DB_PATH": tmp_path / "data" / "req_trace.db", "SESSION_DB_PATH": tmp_path / "session.db",
             "INDEX_CACHE_DIR": tmp_path / "out" / ".index", "REPO_CACHE_DIR": tmp_path / "repos",
             "OUTPUT_DIR": tmp_path / "out"}
    s = ProjectStore(paths["DB_PATH"])
    seed(s)
    s.close()
    paths["SESSION_DB_PATH"].write_text("x")
    paths["INDEX_CACHE_DIR"].mkdir(parents=True)
    (paths["INDEX_CACHE_DIR"] / "a.npy").write_text("x")
    (paths["OUTPUT_DIR"] / "결과.xlsx").write_text("keep")
    e = {**os.environ, **{k: str(v) for k, v in paths.items()},
         "LLM_BACKEND": "fake", "ARTIFACT_REPO_URL": "", "LANGCHAIN_TRACING_V2": "false",
         "AGENT_PORT": "1"}   # 개발 중에 8100에 서버가 떠 있어도 테스트가 영향받지 않게
    return paths, e


def run(e, *args, input_text=None):
    return subprocess.run(["bash", str(SCRIPT), *args], env=e, input=input_text,
                          capture_output=True, text=True, timeout=120)


def test_answer_no_keeps_everything(env):
    paths, e = env
    r = run(e, input_text="n\n")
    assert r.returncode == 1 and "중단" in r.stdout
    assert "요구사항 32건" in r.stdout and paths["DB_PATH"].exists()


def test_yes_backs_up_then_deletes_but_keeps_outputs(env):
    paths, e = env
    r = run(e, "--yes")
    assert r.returncode == 0, r.stdout + r.stderr
    assert not paths["DB_PATH"].exists() and not paths["SESSION_DB_PATH"].exists()
    assert not paths["INDEX_CACHE_DIR"].exists()
    assert (paths["OUTPUT_DIR"] / "결과.xlsx").exists()                 # 결과물은 남긴다
    backups = list((paths["OUTPUT_DIR"] / "backup").glob("req_trace_*.db"))
    assert len(backups) == 1
    assert sqlite3.connect(backups[0]).execute("SELECT COUNT(*) FROM reports").fetchone()[0] == 11
    assert "지울 데이터가 없습니다" in run(e, "--yes").stdout           # 두 번째는 할 일 없음


def test_seed_after_reset(env):
    paths, e = env
    r = run(e, "--yes", "--no-backup", "--seed")
    assert r.returncode == 0, r.stdout + r.stderr
    assert not (paths["OUTPUT_DIR"] / "backup").exists()
    c = sqlite3.connect(paths["DB_PATH"])
    assert c.execute("SELECT COUNT(*) FROM requirements").fetchone()[0] == 32


def test_unknown_option(env):
    assert run(env[1], "--nope").returncode == 2


def test_refuses_while_server_running(env, tmp_path):
    """서버가 떠 있으면(여기서는 /health에 응답하는 임시 HTTP 서버) 아무것도 지우지 않는다."""
    import http.server
    import threading

    class Health(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *a):
            pass

    httpd = http.server.HTTPServer(("127.0.0.1", 0), Health)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        paths, e = env
        r = run({**e, "AGENT_PORT": str(httpd.server_port)}, "--yes")
        assert r.returncode == 1 and "실행 중" in r.stdout and paths["DB_PATH"].exists()
    finally:
        httpd.shutdown()
