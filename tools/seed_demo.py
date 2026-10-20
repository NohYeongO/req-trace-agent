"""데모 데이터 시드 — 요구사항 29건과 담당자가 확정한 완료 조건 체크리스트를 업무 DB에 넣는다.

LLM 없이 바로 화면을 확인하기 위한 도구다. 실제 사용 흐름(명세서 업로드 → AI 초안 → 담당자
확정)은 화면에서 한다. 이미 확정된 조건이 있는 요구사항은 --force 없이는 덮어쓰지 않는다.

실행: .venv/bin/python3 tools/seed_demo.py [--force]
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv   # noqa: E402

from agent.config import DATA_DIR, get_settings          # noqa: E402
from agent.requirements import load_requirements_file    # noqa: E402
from agent.store import ProjectStore                     # noqa: E402


def seed(store: ProjectStore, force: bool = False) -> dict:
    loaded = load_requirements_file(DATA_DIR / "requirements" / "petclinic_requirements.json")
    diff = store.upsert_requirements(loaded.requirements)
    criteria = json.loads((DATA_DIR / "demo" / "criteria.json").read_text(encoding="utf-8"))["criteria"]
    confirmed, skipped = [], []
    for req_id, texts in criteria.items():
        current = store.get_requirement(req_id)
        if current["criteria_state"] == "confirmed" and not force:
            skipped.append(req_id)
            continue
        store.replace_criteria(req_id, [{"text": t, "origin": "human"} for t in texts], confirm=True)
        confirmed.append(req_id)
    return {"requirements": diff, "criteria_confirmed": len(confirmed), "criteria_skipped": skipped}


if __name__ == "__main__":
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="이미 확정된 조건도 데모 값으로 덮어쓴다")
    args = parser.parse_args()
    s = ProjectStore(get_settings().db_path)
    result = seed(s, args.force)
    print(json.dumps({**result, "db": str(s.path), "counts": s.counts()}, ensure_ascii=False, indent=2))
    s.close()
