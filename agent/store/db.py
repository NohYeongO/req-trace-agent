"""업무 DB(SQLite) — 요구사항·완료 조건·완료 보고.

조회·저장 메서드는 기능 PR마다 여기에 추가한다. 서버(FastAPI)와 MCP 서버(별도 프로세스)가
같은 파일을 열기 때문에 WAL 모드로 동시 읽기를 허용한다.
"""
import sqlite3
from pathlib import Path

SCHEMA = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")
TABLES = ("requirements", "criteria", "reports", "report_links")


class ProjectStore:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.path = db_path
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def counts(self) -> dict[str, int]:
        return {t: self.conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in TABLES}

    def list_requirements(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT id, category, name, priority FROM requirements ORDER BY id").fetchall()
        return [dict(r) for r in rows]

    def get_requirement(self, req_id: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM requirements WHERE id=?", (req_id,)).fetchone()
        return dict(row) if row else None

    def close(self) -> None:
        self.conn.close()
