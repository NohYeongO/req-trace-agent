#!/usr/bin/env bash
#
# req-trace-agent — 저장된 데이터를 지우고 처음 상태로 되돌리는 스크립트.
#
# 실행 스크립트(run_agent_*.sh)는 채팅 이력만 비우고 업무 DB(요구사항·완료 조건·완료 보고)는
# 일부러 지우지 않는다. 명세서 업로드도 기존 요구사항을 지우지 않는다. 그래서 데모를 바꾸거나
# 처음부터 다시 하려면 이 스크립트로 명시적으로 초기화한다.
#
# 지우는 것: 업무 DB(+WAL), 채팅 이력 DB, 검색 임베딩 캐시, 공용 저장소 작업 사본
# 지우지 않는 것: output/의 엑셀 결과물, data/artifacts/(로컬 산출물 폴더 — --all일 때만)
# 업무 DB는 지우기 전에 output/backup/에 백업한다(--no-backup으로 끔).
#
# 사용:
#   bash sh/reset_data.sh             # 지울 목록을 보여주고 y/N 확인
#   bash sh/reset_data.sh --seed      # 초기화 후 데모 데이터(zerofive-store) 다시 넣기
#   bash sh/reset_data.sh --yes       # 확인 없이 진행(자동화용)
#   bash sh/reset_data.sh --all       # data/artifacts/까지 지움
#   bash sh/reset_data.sh --no-backup # 백업 없이 지움
#
set -euo pipefail
cd "$(dirname "$0")/.."
[ -x ".venv/bin/python3" ] && export PATH="$PWD/.venv/bin:$PATH"

YES=0; SEED=0; BACKUP=1; ALL=0
for arg in "$@"; do
    case "$arg" in
        --yes|-y) YES=1 ;;
        --seed) SEED=1 ;;
        --no-backup) BACKUP=0 ;;
        --all) ALL=1 ;;
        -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
        *) echo "알 수 없는 옵션: $arg (--help 참고)"; exit 2 ;;
    esac
done

# .env의 경로 설정을 따른다(없으면 기본값). 이미 환경변수로 준 값이 우선이다.
if [ -f .env ]; then
    while IFS='=' read -r key value; do
        case "$key" in
            DB_PATH|SESSION_DB_PATH|INDEX_CACHE_DIR|REPO_CACHE_DIR|OUTPUT_DIR)
                [ -z "${!key:-}" ] && export "$key"="$(echo "$value" | sed -e 's/[[:space:]]*#.*$//' -e 's/^"//' -e 's/"$//')" ;;
        esac
    done < <(grep -E '^(DB_PATH|SESSION_DB_PATH|INDEX_CACHE_DIR|REPO_CACHE_DIR|OUTPUT_DIR)=' .env || true)
fi
DB="${DB_PATH:-data/req_trace.db}"
SESSION_DB="${SESSION_DB_PATH:-session.db}"
INDEX_DIR="${INDEX_CACHE_DIR:-output/.index}"
REPO_DIR="${REPO_CACHE_DIR:-data/repos}"
OUT_DIR="${OUTPUT_DIR:-output}"

# 서버가 DB를 쓰는 중이면 지우지 않는다.
AGENT_PORT="${AGENT_PORT:-8100}"
if curl -s --max-time 2 "http://127.0.0.1:$AGENT_PORT/health" >/dev/null 2>&1; then
    echo "ERROR: 에이전트 서버($AGENT_PORT)가 실행 중입니다. 먼저 종료(Ctrl+C)한 뒤 다시 실행하세요."
    exit 1
fi

TARGETS=()
for p in "$DB" "$DB-wal" "$DB-shm" "$SESSION_DB" "$INDEX_DIR" "$REPO_DIR"; do
    [ -e "$p" ] && TARGETS+=("$p")
done
[ "$ALL" = "1" ] && [ -e data/artifacts ] && TARGETS+=("data/artifacts")

if [ "${#TARGETS[@]}" -eq 0 ]; then
    echo "지울 데이터가 없습니다(이미 처음 상태)."
else
    if [ -f "$DB" ]; then
        python3 - "$DB" <<'PY' || true
import sqlite3, sys
c = sqlite3.connect(sys.argv[1])
counts = {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("requirements", "criteria", "reports")}
print(f"현재 업무 DB: 요구사항 {counts['requirements']}건, 완료 조건 {counts['criteria']}개, 완료 보고 {counts['reports']}건")
PY
    fi
    echo "다음을 지웁니다:"
    for p in "${TARGETS[@]}"; do echo "  - $p ($(du -sh "$p" 2>/dev/null | cut -f1))"; done
    if [ "$YES" != "1" ]; then
        read -r -p "계속하시겠습니까? [y/N] " CONFIRM
        case "$CONFIRM" in [yY]|[yY][eE][sS]) ;; *) echo "중단합니다."; exit 1 ;; esac
    fi

    if [ "$BACKUP" = "1" ] && [ -f "$DB" ]; then
        mkdir -p "$OUT_DIR/backup"
        BACKUP_FILE="$OUT_DIR/backup/req_trace_$(date +%Y%m%d_%H%M%S).db"
        # sqlite 백업 API로 WAL에 남은 내용까지 한 파일로 복사한다.
        python3 -c "import sqlite3,sys; s=sqlite3.connect(sys.argv[1]); d=sqlite3.connect(sys.argv[2]); s.backup(d); d.close()" "$DB" "$BACKUP_FILE"
        echo "업무 DB 백업: $BACKUP_FILE"
    fi
    for p in "${TARGETS[@]}"; do rm -rf "$p"; done
    echo "초기화 완료."
fi

if [ "$SEED" = "1" ]; then
    echo "데모 데이터를 넣습니다..."
    python3 tools/seed_demo.py
fi
