"""업무 DB(SQLite) — 요구사항·완료 조건·완료 보고.

조회·저장 메서드는 기능 PR마다 여기에 추가한다. 서버(FastAPI)와 MCP 서버(별도 프로세스)가
같은 파일을 열기 때문에 WAL 모드로 동시 읽기를 허용한다.
"""
import sqlite3
from datetime import datetime
from pathlib import Path

from ..requirements import Requirement

SCHEMA = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")
TABLES = ("requirements", "criteria", "reports", "report_links")
REQ_FIELDS = ("category", "name", "description", "priority")
# 이전 버전 스키마로 만든 DB 파일에 나중에 추가된 열을 붙인다(열 이름, 정의).
_MIGRATIONS = {"requirements": [("seq", "INTEGER NOT NULL DEFAULT 0")]}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def criteria_state(items: list[dict]) -> str:
    """요구사항 하나의 완료 조건 상태: none(미작성) | draft(검토 대기) | confirmed(확정)."""
    if not items:
        return "none"
    return "confirmed" if all(c["confirmed"] for c in items) else "draft"


class ProjectStore:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.path = db_path
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.commit()

    def _migrate(self) -> None:
        for table, columns in _MIGRATIONS.items():
            have = {r["name"] for r in self.conn.execute(f"PRAGMA table_info({table})")}
            for name, ddl in columns:
                if name not in have:
                    self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")

    def counts(self) -> dict[str, int]:
        return {t: self.conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in TABLES}

    # ── 요구사항 ──────────────────────────────────────────────────────────
    def upsert_requirements(self, reqs: list[Requirement]) -> dict:
        """명세서 내용을 반영한다. 파일에 없는 기존 요구사항은 지우지 않고 missing으로 알린다
        (완료 보고가 연결돼 있을 수 있어서). 확정된 조건이 있는 요구사항의 내용이 바뀌면
        조건을 다시 검토해야 하므로 review_needed로 알린다."""
        existing = {r["id"]: dict(r) for r in self.conn.execute("SELECT * FROM requirements")}
        confirmed = {r[0] for r in self.conn.execute(
            "SELECT DISTINCT req_id FROM criteria WHERE confirmed=1")}
        added, updated, unchanged, review = [], [], [], []
        with self.conn:
            for seq, req in enumerate(reqs, start=1):
                old = existing.get(req.id)
                values = [getattr(req, f) for f in REQ_FIELDS]
                if old is None:
                    self.conn.execute(
                        "INSERT INTO requirements(id, category, name, description, priority, seq,"
                        " created_at) VALUES (?,?,?,?,?,?,?)", (req.id, *values, seq, _now()))
                    added.append(req.id)
                    continue
                changed = [old[f] for f in REQ_FIELDS] != values
                self.conn.execute(
                    "UPDATE requirements SET category=?, name=?, description=?, priority=?, seq=?"
                    " WHERE id=?", (*values, seq, req.id))
                (updated if changed else unchanged).append(req.id)
                if changed and req.id in confirmed:
                    review.append(req.id)
            # 파일에 없는 기존 요구사항은 새 명세서 순서와 섞이지 않게 목록 맨 뒤로 보낸다.
            ids = {r.id for r in reqs}
            missing = sorted(set(existing) - ids, key=lambda i: (existing[i]["seq"], i))
            for n, rid in enumerate(missing, start=len(reqs) + 1):
                self.conn.execute("UPDATE requirements SET seq=? WHERE id=?", (n, rid))
        return {"added": added, "updated": updated, "unchanged": unchanged,
                "missing": missing, "review_needed": review,
                "total": len(self.list_requirements())}

    def list_requirements(self, category: str | None = None) -> list[dict]:
        """요구사항 목록 + 완료 조건 요약(개수·상태)."""
        sql = "SELECT id, category, name, priority FROM requirements"
        args: tuple = ()
        if category:
            sql, args = sql + " WHERE category=?", (category,)
        rows = [dict(r) for r in self.conn.execute(sql + " ORDER BY seq, id", args)]
        crit = self._criteria_by_req()
        for r in rows:
            items = crit.get(r["id"], [])
            r["criteria_count"] = len(items)
            r["criteria_state"] = criteria_state(items)
        return rows

    def get_requirement(self, req_id: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM requirements WHERE id=?", (req_id,)).fetchone()
        if row is None:
            return None
        req = {k: row[k] for k in ("id", "category", "name", "description", "priority")}
        req["criteria"] = self.list_criteria(req_id)
        req["criteria_state"] = criteria_state(req["criteria"])
        return req

    # ── 완료 조건 ─────────────────────────────────────────────────────────
    def _criteria_by_req(self) -> dict[str, list[dict]]:
        out: dict[str, list[dict]] = {}
        for c in self.conn.execute("SELECT * FROM criteria ORDER BY req_id, seq"):
            out.setdefault(c["req_id"], []).append(dict(c))
        return out

    def list_criteria(self, req_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT id, seq, text, origin, confirmed FROM criteria WHERE req_id=? ORDER BY seq",
            (req_id,))
        return [{**dict(r), "confirmed": bool(r["confirmed"])} for r in rows]

    def replace_criteria(self, req_id: str, items: list[dict], confirm: bool) -> list[dict]:
        """요구사항 하나의 조건 목록을 화면에서 편집한 상태로 맞춘다.

        items: [{"id"?, "text", "origin"?}] — id가 있으면 그 조건을 고치고, 없으면 새로 만들고,
        목록에서 빠진 기존 조건은 지운다. 완료 보고가 조건 id로 '무엇을 충족했는지' 기록하므로
        고친 조건의 id는 유지한다. AI 초안을 사람이 고치면 origin은 human이 된다.
        확정(confirm=True)하면 그 요구사항의 조건 전체가 진척 계산에 쓰인다."""
        if self.get_requirement(req_id) is None:
            raise KeyError(req_id)
        texts = [(i.get("text") or "").strip() for i in items]
        if any(not t for t in texts):
            raise ValueError("빈 완료 조건은 저장할 수 없습니다.")
        if confirm and not texts:
            raise ValueError("완료 조건이 하나 이상 있어야 확정할 수 있습니다.")
        old = {c["id"]: c for c in self.list_criteria(req_id)}
        keep = {i["id"] for i in items if i.get("id") in old}
        with self.conn:
            for cid in set(old) - keep:
                self.conn.execute("DELETE FROM criteria WHERE id=?", (cid,))
            for seq, (item, text) in enumerate(zip(items, texts), start=1):
                prev = old.get(item.get("id"))
                if prev is not None:
                    origin = prev["origin"] if prev["text"] == text else "human"
                    self.conn.execute(
                        "UPDATE criteria SET seq=?, text=?, origin=?, confirmed=? WHERE id=?",
                        (seq, text, origin, int(confirm), prev["id"]))
                else:
                    origin = item.get("origin") if item.get("origin") in ("ai", "human") else "human"
                    self.conn.execute(
                        "INSERT INTO criteria(req_id, seq, text, origin, confirmed, created_at)"
                        " VALUES (?,?,?,?,?,?)", (req_id, seq, text, origin, int(confirm), _now()))
        return self.list_criteria(req_id)

    def close(self) -> None:
        self.conn.close()
