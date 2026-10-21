#!/usr/bin/env bash
#
# req-trace-agent — Ollama 실모델로 에이전트를 "기동만" 해두는 스크립트.
#
# 서버를 켠 채로 떠 있게 두어 사용자가 직접 써볼 수 있게 한다:
#   - curl로 /chat, /chat/stream 호출해보기
#   - sh/run_frontend.sh를 추가로 띄워 브라우저 화면으로 써보기
#
# 종료하려면 이 터미널에서 Ctrl+C.
#
set -euo pipefail
cd "$(dirname "$0")/.."

# 이 머신은 plain python3/python이 alias로 다른 경로를 가리켜 venv를 무시하는
# 경우가 있어, 이 프로젝트 전용 .venv가 있으면 PATH 맨 앞에 명시적으로 꽂아둔다.
[ -x ".venv/bin/python3" ] && export PATH="$PWD/.venv/bin:$PATH"

FAST_MODEL="${OLLAMA_FAST_MODEL:-qwen3:0.6b}"
QUALITY_MODEL="${OLLAMA_QUALITY_MODEL:-qwen3:8b}"
EMBED_MODEL="${OLLAMA_EMBED_MODEL:-bge-m3}"   # 완료 보고 → 요구사항 검색(RAG) 임베딩

# ── 0) LangSmith 환경 ──────────────────────────────────────────────────
if [ ! -f .env ]; then
    echo "ERROR: .env가 없습니다 — .env.example을 복사해 .env로 만들고 본인 API 키를 채워주세요."
    echo "  cp .env.example .env"
    exit 1
fi
set -a; source .env; set +a
export LANGCHAIN_PROJECT="req-trace-agent-ollama"   # fake 모드와 프로젝트 분리
echo "LangSmith: project=$LANGCHAIN_PROJECT tracing=${LANGCHAIN_TRACING_V2:-}"
echo "모델: fast=$FAST_MODEL / quality=$QUALITY_MODEL / embed=$EMBED_MODEL"

# ── 1) Ollama 데몬 확인 (없으면 기동) ──────────────────────────────────
STARTED_OLLAMA=""
if ! curl -s --max-time 2 http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
    echo "ollama serve가 없어 백그라운드로 기동합니다..."
    nohup ollama serve > /tmp/req_trace_agent_ollama.log 2>&1 &
    STARTED_OLLAMA=$!
    for _ in $(seq 1 30); do
        curl -s --max-time 2 http://127.0.0.1:11434/api/tags >/dev/null 2>&1 && break
        sleep 0.5
    done
fi
curl -s --max-time 2 http://127.0.0.1:11434/api/tags >/dev/null 2>&1 \
    || { echo "ERROR: ollama serve 기동 실패"; exit 1; }

for m in "$FAST_MODEL" "$QUALITY_MODEL" "$EMBED_MODEL"; do
    # grep -q는 pipefail에서 SIGPIPE(141)를 유발하므로 전체를 읽는 형태로 검사
    ollama list | grep "^${m}" >/dev/null \
        || { echo "ERROR: 모델 $m 미설치 — bash sh/setup_ollama.sh 후 재실행"; exit 1; }
done

echo "모델 웜업 중 (최초 로드 수 초)..."
for m in "$FAST_MODEL" "$QUALITY_MODEL"; do
    curl -s http://127.0.0.1:11434/api/generate \
        -d "{\"model\":\"$m\",\"prompt\":\"hi\",\"stream\":false,\"options\":{\"num_predict\":1}}" >/dev/null
done

# ── 데모 산출물(근거 확인용) — 공용 저장소·로컬 폴더를 지정하지 않았고 아직 없으면 받아온다 ──
if [ -n "${ARTIFACT_REPO_URL:-}" ]; then
    echo "근거 확인: 공용 저장소 $ARTIFACT_REPO_URL (${ARTIFACT_BRANCH:-main})"
elif [ -z "${ARTIFACT_ROOT:-}" ] && [ ! -d data/artifacts/spring-petclinic-rest/src ]; then
    echo "데모 산출물(spring-petclinic-rest)이 없어 받아옵니다 (완료 보고 근거 확인용)..."
    bash sh/fetch_artifacts.sh || echo "⚠️  받기 실패 — 근거 확인은 '확인 불가'로 표시됩니다."
fi

# ── 2) 이전 실행 정리 ──────────────────────────────────────────────────
lsof -ti:8100 | xargs kill -9 2>/dev/null || true
rm -f session.db   # 채팅 이력만 초기화 — 업무 DB(data/req_trace.db)는 유지

cleanup() {
    echo
    echo "에이전트를 종료합니다..."
    lsof -ti:8100 | xargs kill -9 2>/dev/null || true
    [ -n "$STARTED_OLLAMA" ] && kill "$STARTED_OLLAMA" 2>/dev/null || true
}
trap cleanup EXIT

# ── 3) 서버 기동 (백그라운드로 띄운 뒤 준비될 때까지 대기) ─────────────
LLM_BACKEND=ollama python3 server.py &
SERVER_PID=$!
for _ in $(seq 1 40); do
    curl -s http://127.0.0.1:8100/health >/dev/null 2>&1 && break
    sleep 0.5
done

echo
curl -s http://127.0.0.1:8100/health | python3 -m json.tool --no-ensure-ascii

cat <<EOF

################################################################
 에이전트가 떠 있습니다 (http://127.0.0.1:8100, LLM_BACKEND=ollama)
################################################################

지금 바로 테스트해볼 수 있는 방법:

1) curl로 말 걸어보기
   curl -s -X POST localhost:8100/chat -H 'Content-Type: application/json' \\
     -d '{"message":"안녕, 너는 누구야?","thread_id":"t-test"}' \\
     | python3 -m json.tool --no-ensure-ascii

2) 실시간 진행 상황 보기 (스트리밍)
   curl -sN -G "localhost:8100/chat/stream" \\
     --data-urlencode "message=보안 요구사항 진행률 알려줘" \\
     --data-urlencode "thread_id=t-test-sse"

3) 브라우저 화면 (새 터미널에서)
   bash sh/run_frontend.sh
   → http://localhost:8600 접속

종료하려면 이 터미널에서 Ctrl+C.
EOF

wait "$SERVER_PID"
