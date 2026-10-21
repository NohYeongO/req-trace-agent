-- 업무 DB 스키마. 상태(완료/부분완료/미착수)는 저장하지 않고 조회 시 코드가 계산한다 —
-- 저장된 사실(확정된 완료 조건, 확인된 완료 보고)만이 진척의 근거가 되게 하기 위함이다.

CREATE TABLE IF NOT EXISTS requirements (
    id          TEXT PRIMARY KEY,            -- 고유번호 (예: SFR-005)
    category    TEXT NOT NULL DEFAULT '',    -- 분류 (기능·보안·데이터·성능·품질 등)
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    priority    TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL
);

-- 요구사항별 완료 조건 체크리스트. AI 초안(origin='ai')은 사람이 확정(confirmed=1)해야
-- 진척 계산에 쓰인다.
CREATE TABLE IF NOT EXISTS criteria (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    req_id      TEXT NOT NULL REFERENCES requirements(id) ON DELETE CASCADE,
    seq         INTEGER NOT NULL,
    text        TEXT NOT NULL,
    origin      TEXT NOT NULL CHECK (origin IN ('ai', 'human')),
    confirmed   INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);

-- 개발자가 확인 버튼을 눌러 확정한 완료 보고만 저장한다(AI 제안 단계는 저장하지 않음).
CREATE TABLE IF NOT EXISTS reports (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    author      TEXT NOT NULL,
    raw_text    TEXT NOT NULL,
    summary     TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL
);

-- 보고 1건이 여러 요구사항에 걸칠 수 있다. 근거·근거 확인 결과는 JSON 문자열.
CREATE TABLE IF NOT EXISTS report_links (
    report_id      INTEGER NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
    req_id         TEXT NOT NULL REFERENCES requirements(id) ON DELETE CASCADE,
    met_criteria   TEXT NOT NULL DEFAULT '[]',
    evidence       TEXT NOT NULL DEFAULT '[]',
    evidence_check TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (report_id, req_id)
);

CREATE INDEX IF NOT EXISTS idx_criteria_req ON criteria(req_id);
CREATE INDEX IF NOT EXISTS idx_links_req ON report_links(req_id);

-- 검수 산출물(테스트 결과 보고서 등). 본문은 섹션 목록 JSON — 표는 코드가 계산한 값,
-- 서술은 AI 초안 또는 담당자가 고친 글. status: draft(검토 중) → confirmed(확정, 수정 불가).
CREATE TABLE IF NOT EXISTS deliverables (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_type     TEXT NOT NULL,
    title        TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'draft',
    source       TEXT NOT NULL DEFAULT '',
    content      TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    confirmed_at TEXT,
    confirmed_by TEXT
);
