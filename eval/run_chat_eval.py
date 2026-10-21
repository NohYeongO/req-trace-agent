"""채팅 평가 — data/eval/chat_cases.json의 질문을 채팅 그래프에 넣고 답을 채점한다.

- 분류 정확도: 기대한 route로 갔는가
- 사실 재현율: must 항목 중 답에 들어간 비율(문항 평균), must_any 충족, forbid 위반
- 군더더기: 묻지 않은 정보(forbid)가 섞인 문항 수
- 완전 정답률: must·must_any를 모두 만족하고 forbid가 없는 문항 비율
- 부자연스러운 표현: 알려진 오류 패턴(외국어 문자, 어색한 어미, 머리말 노출, 화면에 그대로 보이는 **) 수
- 검증 반려 재작성 횟수, 대체 답변 비율, 평균 답변 길이, 평균 소요 시간
업무 DB는 임시 파일에 데모 시드를 넣어 쓰고, MCP 서버는 실제 subprocess로 띄운다.

실행: LLM_BACKEND=ollama FIXED_TODAY=2026-03-10 .venv/bin/python3 eval/run_chat_eval.py [--only id,id]
재채점: .venv/bin/python3 eval/run_chat_eval.py --rescore eval/results/chat-ollama-….json
"""
import argparse
import asyncio
import json
import re
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from agent.config import DATA_DIR, get_settings   # noqa: E402
from agent.deps import SupervisorDeps             # noqa: E402
from agent.graphs import build_chat_graph         # noqa: E402
from agent.llm import build_llms                  # noqa: E402
from agent.mcp_client import MCPClient            # noqa: E402
from agent.state import initial_state             # noqa: E402
from agent.store import ProjectStore              # noqa: E402
from tools.seed_demo import seed                  # noqa: E402

# 부자연스러운 표현: 외국어 문자, 어색한 어미, 내부 머리말 노출, 화면에 그대로 찍히는 마크다운 굵게(**)
UNNATURAL = re.compile(r"[À-ɏḀ-ỿ一-鿿぀-ヿ]|다음과 있습니다|\[질문 대상\]"
                       r"|^따르면|\bnull\b|None|\*\*", re.M)


def score(c: dict, route: str, answer: str) -> dict:
    must = c.get("must", [])
    hit = [m for m in must if m in answer]
    any_ok = not c.get("must_any") or any(m in answer for m in c["must_any"])
    forbid = [f for f in c.get("forbid", []) if f in answer]
    return {"route_ok": route == c["route"], "route": route,
            "recall": len(hit) / len(must) if must else 1.0, "missing": [m for m in must if m not in hit],
            "must_any_ok": any_ok, "forbid": forbid,
            "correct": route == c["route"] and len(hit) == len(must) and any_ok and not forbid,
            "unnatural": len(UNNATURAL.findall(answer)), "chars": len(answer)}


def summarize(rows: list[dict], backend: str, model: str) -> dict:
    n = len(rows)
    return {
        "backend": backend, "model": model, "cases": n,
        "route_accuracy": round(sum(r["route_ok"] for r in rows) / n, 3),
        "fact_recall": round(sum(r["recall"] for r in rows) / n, 3),
        "noise_cases": sum(bool(r["forbid"]) for r in rows),
        "correct_rate": round(sum(r["correct"] for r in rows) / n, 3),
        "unnatural_total": sum(r["unnatural"] for r in rows),
        "rewrites": sum(max(r.get("attempts", 1) - 1, 0) for r in rows),
        "fallback_rate": round(sum(r.get("fallback", False) for r in rows) / n, 3),
        "avg_chars": round(sum(r["chars"] for r in rows) / n),
        "avg_seconds": round(sum(r.get("seconds", 0) for r in rows) / n, 1),
    }


def load_cases() -> list[dict]:
    return json.loads((DATA_DIR / "eval" / "chat_cases.json").read_text(encoding="utf-8"))["cases"]


def rescore(path: Path) -> dict:
    """저장된 결과의 답을 현재 평가 세트 기준으로 다시 채점한다(평가 기준을 바꿨을 때 이전 결과와 비교용)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    cases = {c["id"]: c for c in load_cases()}
    rows = [{**r, **score(cases[r["id"]], r["route"], r["answer"])} for r in data["rows"] if r["id"] in cases]
    for r in rows:
        if not r["correct"]:
            print(f"✗ {r['id']:18} miss={r['missing']} forbid={r['forbid']}")
    s = summarize(rows, data["summary"]["backend"], data["summary"]["model"])
    print(json.dumps(s, ensure_ascii=False, indent=2))
    return s


async def ask(graph, q: str, thread: str, history: list[dict]) -> dict:
    return await graph.ainvoke(initial_state(q, thread, history, "평가"))


async def main(only: set[str] | None) -> dict:
    settings = get_settings()
    tmp = Path(tempfile.mkdtemp())
    store = ProjectStore(tmp / "chat.db")
    seed(store)
    fast, quality = build_llms(settings)
    mcp = MCPClient(env={"DB_PATH": str(store.path), "EMBEDDER": settings.embedder,
                         "FIXED_TODAY": settings.fixed_today, "INDEX_CACHE_DIR": str(tmp / "idx")})
    await mcp.start()
    try:
        return await _run_cases(mcp, store, fast, quality, settings, only)
    finally:
        await mcp.stop()   # 예외가 나도 MCP subprocess를 남기지 않는다(남으면 프로세스가 끝나지 않음)


async def _run_cases(mcp, store, fast, quality, settings, only) -> dict:
    deps = SupervisorDeps(fast_llm=fast, quality_llm=quality, mcp=mcp, store=store,
                          session_store=None, settings=settings)
    graph = build_chat_graph(deps)
    cases = [c for c in load_cases() if not only or c["id"] in only]

    rows, started = [], time.time()
    for i, c in enumerate(cases):
        history: list[dict] = []
        for h in c.get("history", []):
            prev = await ask(graph, h, f"h{i}", history)
            history += [{"role": "user", "content": h}, {"role": "assistant", "content": prev["final"]}]
        t0 = time.time()
        r = await ask(graph, c["q"], f"c{i}", history)
        answer = r["final"]
        row = {"id": c["id"], "q": c["q"], **score(c, r["route"], answer),
               "intent": (r.get("target") or {}).get("intent"), "attempts": r.get("attempts", 0),
               "fallback": r.get("used_fallback", False), "seconds": round(time.time() - t0, 1), "answer": answer}
        rows.append(row)
        mark = "✓" if row["correct"] else "✗"
        print(f"[{i + 1}/{len(cases)}] {mark} {c['id']:18} route={r['route']:7} recall={row['recall']:.2f} "
              f"miss={row['missing']} forbid={row['forbid']} ({row['seconds']}s)", flush=True)
    summary = {**summarize(rows, settings.llm_backend, quality.name), "elapsed": round(time.time() - started, 1)}
    out = ROOT / "eval" / "results" / "chat"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"chat-{settings.llm_backend}-{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"저장: {path.relative_to(ROOT)}")
    return summary


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--only", help="쉼표로 구분한 문항 id만 실행")
    p.add_argument("--rescore", type=Path, help="저장된 결과 파일을 현재 평가 세트로 다시 채점")
    a = p.parse_args()
    if a.rescore:
        rescore(a.rescore)
    else:
        asyncio.run(main(set(a.only.split(",")) if a.only else None))
