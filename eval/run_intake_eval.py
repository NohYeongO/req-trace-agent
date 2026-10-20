"""완료 보고 매핑 평가 — 데모 보고 19건을 정리 그래프에 넣고, 확인 단계에 올라온 AI 제안을
담당자 정답(data/demo/reports.json의 expected)과 비교한다.

- 요구사항 단위: 정밀도(제안 중 맞은 비율)·재현율(정답 중 찾은 비율)
- 조건 단위: 정밀도·재현율 (충족 조건 id 기준)
- 완전 일치율: 요구사항과 조건이 정답과 정확히 같은 보고 비율
업무 DB는 임시 파일을 쓰고, MCP 서버 2개는 실제 subprocess로 띄운다.

실행: LLM_BACKEND=ollama .venv/bin/python3 eval/run_intake_eval.py [--limit N]
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

from agent.config import DATA_DIR, get_settings  # noqa: E402
from agent.deps import SupervisorDeps            # noqa: E402
from agent.graphs import build_intake_graph      # noqa: E402
from agent.llm import build_llms                 # noqa: E402
from agent.mcp_client import MCPClient           # noqa: E402
from agent.state import initial_intake_state     # noqa: E402
from agent.store import ProjectStore             # noqa: E402
from tools.seed_demo import seed_criteria        # noqa: E402


def _ratio(a: int, b: int) -> float:
    return round(a / b, 3) if b else 1.0


async def main(limit: int | None) -> dict:
    tmp = Path(tempfile.mkdtemp())
    settings = get_settings()
    store = ProjectStore(tmp / "eval.db")
    seed_criteria(store, force=False)
    fast, quality = build_llms(settings)
    mcp = MCPClient(env={"DB_PATH": str(store.path), "EMBEDDER": settings.embedder,
                         **({"ARTIFACT_ROOT": str(settings.artifact_root)} if settings.artifact_root else {})})
    await mcp.start()
    deps = SupervisorDeps(fast_llm=fast, quality_llm=quality, mcp=mcp, store=store,
                          session_store=None, settings=settings)
    graph = build_intake_graph(deps)
    reports = json.loads((DATA_DIR / "demo" / "reports.json").read_text(encoding="utf-8"))["reports"]
    reports = reports[:limit] if limit else reports

    seq_to_id = {r["id"]: [c["id"] for c in store.list_criteria(r["id"])] for r in store.list_requirements()}
    tp_r = fp_r = fn_r = tp_c = fp_c = fn_c = exact = retries = 0
    rows, started = [], time.time()
    for i, rep in enumerate(reports):
        t0 = time.time()
        cfg = {"configurable": {"thread_id": f"eval-{i}"}}
        await graph.ainvoke(initial_intake_state(rep["author"], rep["text"]), cfg)
        state = (await graph.aget_state(cfg)).values
        got = {l["req_id"]: set(l["met"]) for l in state["links"]}
        want = {e["req_id"]: {seq_to_id[e["req_id"]][n - 1] for n in e["met"]} for e in rep["expected"]}
        tp_r += len(got.keys() & want.keys()); fp_r += len(got.keys() - want.keys()); fn_r += len(want.keys() - got.keys())
        g_c = {(r, c) for r, cs in got.items() for c in cs}
        w_c = {(r, c) for r, cs in want.items() for c in cs}
        tp_c += len(g_c & w_c); fp_c += len(g_c - w_c); fn_c += len(w_c - g_c)
        exact += got == want
        retries += sum(1 for e in state["events"] if e["type"] == "MappingValidated" and e["retry"])
        rows.append({"date": rep["created_at"][:10], "want": {k: sorted(v) for k, v in want.items()},
                     "got": {k: sorted(v) for k, v in got.items()}, "exact": got == want,
                     "seconds": round(time.time() - t0, 1)})
        print(f"[{i + 1}/{len(reports)}] {'✓' if got == want else '✗'} want={rows[-1]['want']} got={rows[-1]['got']} ({rows[-1]['seconds']}s)", flush=True)
    await mcp.stop()
    summary = {
        "backend": settings.llm_backend, "model": quality.name, "embedder": settings.embedder,
        "reports": len(reports),
        "requirement_precision": _ratio(tp_r, tp_r + fp_r), "requirement_recall": _ratio(tp_r, tp_r + fn_r),
        "criteria_precision": _ratio(tp_c, tp_c + fp_c), "criteria_recall": _ratio(tp_c, tp_c + fn_c),
        "exact_match": _ratio(exact, len(reports)), "mapping_retries": retries,
        "avg_seconds": round((time.time() - started) / max(len(reports), 1), 1),
    }
    out = ROOT / "eval" / "results"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"intake-{settings.llm_backend}-{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"저장: {path.relative_to(ROOT)}")
    return summary


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int)
    asyncio.run(main(p.parse_args().limit))
