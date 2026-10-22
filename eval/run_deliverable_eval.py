"""산출물 초안 평가 — 테스트 결과 보고서(데모 결과 자료 2차수)와 개발 명세서를 산출물 그래프로 만들고
AI 작업이 검증을 몇 번 만에 통과했는지, 끝내 대체됐는지, 문서 서술의 수치가 결과 자료와 맞는지 본다.

- 작업: 서술 섹션(테스트 결과 보고서) 또는 이름 추정 묶음(개발 명세서) 하나
- 1차 통과율: 첫 작성에서 검증을 통과한 작업 비율
- 재작성 횟수·대체율: 검증 반려로 다시 쓴 횟수, 상한까지 틀려 코드 문장('미정')으로 대체한 비율
- 수치 경고: 저장된 문서의 서술 섹션에서 결과 자료에 없는 숫자·고유번호가 발견된 섹션 수(0이어야 함)
업무 DB는 임시 파일에 데모 데이터(요구사항·조건·완료 보고)를 넣어 쓰고, MCP 서버 2개는 실제 subprocess로 띄운다.

개발 명세서는 근거 확인 대상이 필요하다(.env 또는 실행 시 ARTIFACT_REPO_URL=https://github.com/NohYeongO/zerofive-store.git).
실행: LLM_BACKEND=ollama .venv/bin/python3 eval/run_deliverable_eval.py [--only test_report|dev_spec]
"""
import argparse
import asyncio
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from agent.artifacts import make_checker              # noqa: E402
from agent.config import get_settings                 # noqa: E402
from agent.deps import SupervisorDeps                 # noqa: E402
from agent.graphs import build_deliverable_graph      # noqa: E402
from agent.llm import build_llms                      # noqa: E402
from agent.mcp_client import MCPClient                # noqa: E402
from agent.qa import check_answer                     # noqa: E402
from agent.state import initial_deliverable_state     # noqa: E402
from agent.store import ProjectStore                  # noqa: E402
from tools.seed_demo import seed                      # noqa: E402

CASES = [("test_report", "demo:1차-2026-03-09"), ("test_report", "demo:2차-2026-03-10"), ("dev_spec", "repo")]


def _warnings(content: dict) -> int:
    return sum(1 for s in content["sections"]
               if s["kind"] == "ai" and check_answer(s.get("text") or "", content["facts"], ""))


async def main(only: str | None) -> dict:
    tmp = Path(tempfile.mkdtemp())
    settings = get_settings()
    store = ProjectStore(tmp / "eval.db")
    seed(store, force=False, reports=True, checker=make_checker(settings))
    fast, quality = build_llms(settings)
    mcp = MCPClient(env={"DB_PATH": str(store.path), "EMBEDDER": settings.embedder,
                         "UPLOAD_DIR": str(settings.upload_dir),
                         **({"ARTIFACT_ROOT": str(settings.artifact_root)} if settings.artifact_root else {})})
    await mcp.start()
    try:
        deps = SupervisorDeps(fast_llm=fast, quality_llm=quality, mcp=mcp, store=store,
                              session_store=None, settings=settings)
        graph = build_deliverable_graph(deps)
        rows = []
        for doc_type, source in CASES:
            if only and doc_type != only:
                continue
            t0 = time.time()
            state = await graph.ainvoke(initial_deliverable_state(source, doc_type))
            checks = [e for e in state["events"] if e["type"] == "SectionsValidated"]
            first = checks[0] if checks else {"problems": {}}
            built = next((e for e in state["events"] if e["type"] == "DocumentBuilt"), {})
            tasks = len(built.get("tasks", []))
            doc = store.get_deliverable(state["doc_id"]) if state.get("doc_id") else None
            row = {
                "doc_type": doc_type, "source": source, "error": state.get("error") or "",
                "tasks": tasks, "first_pass": tasks - len(first.get("problems", {})),
                "rewrites": sum(len(e["retry"]) for e in checks), "fallbacks": len(state.get("fallbacks", [])),
                "numeric_warnings": _warnings(doc["content"]) if doc else None,
                "notes": [s["note"] for s in (doc["content"]["sections"] if doc else []) if s.get("note")],
                "seconds": round(time.time() - t0, 1),
            }
            rows.append(row)
            print(f"{doc_type} {source}: 작업 {row['tasks']} · 1차 통과 {row['first_pass']} · 재작성 {row['rewrites']}"
                  f" · 대체 {row['fallbacks']} · 수치 경고 {row['numeric_warnings']} ({row['seconds']}s)", flush=True)
    finally:
        await mcp.stop()
    tasks = sum(r["tasks"] for r in rows)
    summary = {
        "backend": settings.llm_backend, "model": quality.name, "documents": len(rows), "tasks": tasks,
        "first_pass_rate": round(sum(r["first_pass"] for r in rows) / tasks, 3) if tasks else 1.0,
        "rewrites": sum(r["rewrites"] for r in rows),
        "fallback_rate": round(sum(r["fallbacks"] for r in rows) / tasks, 3) if tasks else 0.0,
        "numeric_warnings": sum(r["numeric_warnings"] or 0 for r in rows),
        "errors": sum(1 for r in rows if r["error"]),
    }
    out = ROOT / "eval" / "results" / "deliverables"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"deliverables-{settings.llm_backend}-{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"저장: {path.relative_to(ROOT)}")
    return summary


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--only", choices=["test_report", "dev_spec"])
    asyncio.run(main(p.parse_args().only))
