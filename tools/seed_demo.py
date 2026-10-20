"""데모 데이터 시드 — 요구사항 29건, 담당자가 확정한 완료 조건, 개발자 3명의 완료 보고 19건.

LLM 없이 바로 화면(요구사항·완료 보고·이후 대시보드)을 확인하기 위한 도구다. 보고는 개발자가
확인을 마친 상태(data/demo/reports.json의 expected 매핑)로 넣고, 근거 실존 확인 결과도 함께
저장한다. 실제 사용 흐름(명세서 업로드 → AI 초안 → 확정, 보고 작성 → AI 정리 → 확인)은 화면에서 한다.

이미 확정된 조건이나 저장된 보고가 있으면 --force 없이는 건드리지 않는다. --force는 조건을
데모 값으로 다시 쓰고 보고를 모두 지운 뒤 다시 넣는다.

실행: .venv/bin/python3 tools/seed_demo.py [--force] [--no-reports]
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv   # noqa: E402

from agent.artifacts import ArtifactChecker              # noqa: E402
from agent.config import DATA_DIR, get_settings          # noqa: E402
from agent.evidence import extract_evidence              # noqa: E402
from agent.requirements import load_requirements_file    # noqa: E402
from agent.store import ProjectStore                     # noqa: E402

DEMO = DATA_DIR / "demo"


def seed_criteria(store: ProjectStore, force: bool) -> dict:
    loaded = load_requirements_file(DATA_DIR / "requirements" / "petclinic_requirements.json")
    diff = store.upsert_requirements(loaded.requirements)
    criteria = json.loads((DEMO / "criteria.json").read_text(encoding="utf-8"))["criteria"]
    confirmed, skipped = [], []
    for req_id, texts in criteria.items():
        if store.get_requirement(req_id)["criteria_state"] == "confirmed" and not force:
            skipped.append(req_id)
            continue
        store.replace_criteria(req_id, [{"text": t, "origin": "human"} for t in texts], confirm=True)
        confirmed.append(req_id)
    return {"requirements": diff, "criteria_confirmed": len(confirmed), "criteria_skipped": skipped}


def seed_reports(store: ProjectStore, checker: ArtifactChecker, force: bool) -> dict:
    if store.counts()["reports"] and not force:
        return {"reports_seeded": 0, "reports_skipped": "이미 보고가 있음(--force로 다시 넣기)"}
    with store.conn:
        store.conn.execute("DELETE FROM reports")
    data = json.loads((DEMO / "reports.json").read_text(encoding="utf-8"))["reports"]
    for rep in data:
        evidence = extract_evidence(rep["text"])
        checked = checker.check(evidence)
        links = []
        for exp in rep["expected"]:
            ids = [c["id"] for c in store.list_criteria(exp["req_id"])]
            links.append({"req_id": exp["req_id"], "met_criteria": [ids[n - 1] for n in exp["met"]],
                          "evidence": evidence, "evidence_check": checked})
        store.save_report(rep["author"], rep["text"], rep["text"].split(".")[0][:60], links,
                          created_at=rep["created_at"])
    return {"reports_seeded": len(data)}


def seed(store: ProjectStore, force: bool = False, reports: bool = True,
         artifact_root: Path | None = None) -> dict:
    result = seed_criteria(store, force)
    if reports:
        result.update(seed_reports(store, ArtifactChecker(artifact_root), force))
    return result


if __name__ == "__main__":
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="조건을 데모 값으로 다시 쓰고 보고를 다시 넣는다")
    parser.add_argument("--no-reports", action="store_true", help="완료 보고는 넣지 않는다")
    args = parser.parse_args()
    settings = get_settings()
    s = ProjectStore(settings.db_path)
    result = seed(s, args.force, not args.no_reports, settings.artifact_root)
    print(json.dumps({**result, "db": str(s.path), "counts": s.counts()}, ensure_ascii=False, indent=2))
    s.close()
