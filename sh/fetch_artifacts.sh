#!/usr/bin/env bash
#
# req-trace-agent — 데모 산출물(spring-petclinic-rest)을 핀 커밋으로 받아오는 스크립트.
#
# 완료 보고의 근거(파일·API·테스트)가 실제로 있는지 확인할 때 쓰는 데모 산출물이다.
# 데모 완료 보고(data/demo/reports.json)는 이 커밋의 실제 파일·API·테스트 이름으로 썼다.
# 본인 프로젝트를 쓰려면 이 스크립트 대신 .env의 ARTIFACT_ROOT에 로컬 경로를 지정한다 —
# 그 산출물은 이 저장소에 복사하지 않는다(data/artifacts/는 gitignore).
#
set -euo pipefail
cd "$(dirname "$0")/.."

REPO_URL="https://github.com/spring-petclinic/spring-petclinic-rest.git"
COMMIT="afc8fc1d3b8ec8de69414482b3bd70a1da78cb95"
DEST="data/artifacts/spring-petclinic-rest"

if [ -d "$DEST/.git" ] && [ "$(git -C "$DEST" rev-parse HEAD)" = "$COMMIT" ]; then
    echo "이미 받아져 있습니다: $DEST @ ${COMMIT:0:7}"
    exit 0
fi

rm -rf "$DEST"
mkdir -p "$DEST"
git -C "$DEST" init -q
git -C "$DEST" remote add origin "$REPO_URL"
git -C "$DEST" fetch -q --depth 1 origin "$COMMIT"
git -C "$DEST" checkout -q FETCH_HEAD
echo "산출물 준비 완료: $DEST @ ${COMMIT:0:7}"
