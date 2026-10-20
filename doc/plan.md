# 진행 계획

## 배경
- 공공 SI는 검수 때 요구사항별 완료 여부와 근거를 추적표로 제출해야 대금이 나온다.
- AI가 코드를 보고 구현 여부를 **판정**하는 방식은 틀렸을 때 치명적이다. 이전 시도에서 실측 판정 정확도는 0.5 수준이었다.
- 그래서 방향을 바꾼다. **사실의 출처는 개발자의 완료 보고**로 하고, AI는 그 보고를 **정리·매핑·요약·질의응답**하는 역할만 맡는다.
  - AI의 제안은 항상 사람이 확인한 뒤 저장된다(Human-in-the-loop).
  - 상태(완료/부분완료/미착수)는 LLM이 아니라 **코드가 체크리스트 충족 여부로 계산**한다.
- 사용자 흐름:
  1. 요구사항 명세서를 업로드한다.
  2. 개발자가 개발을 끝낼 때마다 폼에 자유롭게 입력한다. AI가 정리해서 제안하고 개발자가 확인한다.
  3. 대시보드에서 완료 현황을 본다.
  4. 채팅으로 현황을 묻는다.
  5. 검수 때 추적표 엑셀을 내보낸다.

## 작업 방식
- 기능 단위로 브랜치를 만들고 PR로 머지한다. PR 본문에는 배경 / 변경 사항 / 동작 방식 / 테스트 결과 / 한계를 적는다.
- PR마다 GitHub Actions가 fake 백엔드로 `pytest`를 돌린다(네트워크·Ollama 불필요).

## 최종 산출물: 검수·대금 청구용 엑셀 (핵심 기능)
대시보드와 채팅의 **"검수용 엑셀 내보내기"** 버튼, 또는 채팅의 "추적표 뽑아줘"로 생성한다. 공공 SI 검수 제출 형식을 따른다.

| 시트 | 내용 |
|---|---|
| 표지·요약 | 사업명, 기준일, 전체 진척률, 분류별·상태별 건수, 미완료 목록, 검수자·확인일 서명란 |
| 요구사항 추적표 | 요구사항ID, 분류, 요구사항명, 상세설명, 완료 조건(줄바꿈 목록), 충족 조건 수/전체, 상태(완료/부분완료/미착수), 완료일, 담당자, 구현 근거(파일·API·PR·테스트), 근거 확인 결과, 관련 보고 ID, 검수 확인(빈칸), 비고 |
| 완료 보고 이력 | 보고ID, 일시, 작성자, 요약, 연결된 요구사항·충족 조건 |

- **사람이 확인한 데이터만 들어간다.** 확정된 체크리스트와 확인된 보고만 반영하고, AI 제안 단계의 데이터는 제외한다.
- 상태별 색상, 필터, 틀 고정, 인쇄 영역을 설정한다. 기존 `rtm_excel.py`(openpyxl)를 확장한다.
- 기준일을 지정하면 그 시점 기준으로 내보낸다. 중간 검수와 최종 검수에 모두 쓸 수 있다.

## 화면 (Vue 3 CDN, 빌드 없음, 탭 4개)
| 탭 | 내용 |
|---|---|
| 대시보드 | **진척률 카드**(전체 % + 완료/부분/미착수 건수), **분류별 진척 막대**(SFR·SER·DAR·PER·QUR), **담당자별 현황**, **진척 추이 차트**(날짜별 누적 완료 건수, burn-up), 위험 신호(보고가 없는 요구사항, 부분완료로 N일 이상 머문 항목), 최근 보고 피드, 요구사항 표(상태·조건 진행도 필터), **검수용 엑셀 내보내기** 버튼. 차트는 Chart.js CDN |
| 완료 보고 | 이름 + 자유 서술 입력 → AI 정리 결과 카드(매핑된 요구사항, 충족 체크리스트, 근거, 확인 여부) → 수정 후 **확인** 또는 취소 |
| 요구사항 | 엑셀 업로드, 요구사항 목록, 요구사항별 완료 조건 체크리스트(AI 초안 → 사람이 수정·확정), 연결된 보고 이력 |
| 채팅 | "보안 요구사항 진행률은?", "SFR-005 남은 거 뭐야?", "이번 주 완료된 거 정리해줘" |

## 데이터 모델 (SQLite, `agent/store/`)
- `requirements(id, category, name, description, priority)`
- `criteria(id, req_id, text, origin[ai|human], confirmed)`: 완료 조건 체크리스트
- `reports(id, author, raw_text, summary, created_at)`
- `report_links(report_id, req_id, met_criteria[json], evidence[json], evidence_check[json])`
- **상태는 코드가 계산한다.**
  - 확정된 조건 전부 충족 → 완료
  - 일부 충족 → 부분완료
  - 없음 → 미착수
  - 체크리스트가 미확정이면 "조건 미확정"

## 에이전트 구성 (LangGraph, 원본 골격 유지: route → … → validate → finalize)
1. **요구사항 등록 에이전트** (업로드 시)
   - 엑셀/JSON 로드 → 요구사항별로 LLM이 완료 조건 2~4개 초안 작성 → 요구사항 탭에서 사람이 확정
   - 데모 시드는 미리 만든 체크리스트를 써서 LLM 없이 바로 쓸 수 있다.
2. **보고 정리 에이전트** (intake 그래프)
   - `extract`: LLM이 요약하고, 언급된 요구사항 ID와 근거 항목(파일, API, PR, 테스트)을 뽑는다.
   - `candidates`: 명시된 ID를 우선하고, 없으면 RAG(요구사항+조건 임베딩, bge-m3, 용어 사전 확장)로 상위 후보를 찾는다.
   - `map`: LLM이 보고 내용과 후보 조건을 대조해 충족 조건 ID를 고른다. 후보 목록 밖의 ID는 쓰지 못한다.
   - `verify`: 코드가 확인한다. 매핑 ID가 실존하는지, 근거로 적힌 파일과 API가 산출물에 존재하는지 본다. API는 OpenAPI 분석기로 확인한다. 결과는 "근거 확인됨/없음"으로 표시만 하고 판정하지 않는다.
   - `confirm`: `interrupt()`로 멈추고, 개발자가 수정·확인하면 `save`로 넘어간다.
3. **현황 질의응답 에이전트** (chat 그래프)
   - `route`: chat / status / summary로 분류
   - `plan`: 필요한 MCP Tool 호출 계획
   - `research`: 병렬로 Tool 호출
   - `write`: 수치와 요구사항 ID를 인용해 답변
   - `validate`: 답에 나온 숫자와 ID가 Tool 결과와 일치하는지 코드로 검증하고, 틀리면 재작성(최대 3회)
4. **요약 리포트 에이전트**: "이번 주 정리" → 기간별 보고와 상태 변화를 조회해 요약. RTM 엑셀 내보내기는 기존 `rtm_excel.py`를 재사용한다.

## MCP (서버 2개, 원본의 멀티 서버 탐색 구조 유지)
- `trace` 서버
  - Tool: `list_requirements(filter)`, `get_requirement(id)`, `get_progress(group_by)`, `search_requirements(query)`(RAG), `search_reports(query, since)`, `list_reports(since, author)`
  - Resource: `requirement://{id}`
  - Prompt: `intake_mapping_prompt`, `status_answer_prompt`
- `artifact` 서버: `verify_evidence(items)`. 파일이나 엔드포인트가 실존하는지만 확인한다. `ARTIFACT_ROOT`가 없으면 "확인 불가"로 표시한다.

## 재사용
- 강의 Base 코드: server.py의 lifespan 싱글턴과 SSE, web_demo_server 프록시, session_store, retry, deps 주입, mcp_client 멀티 서버 탐색, sh 스크립트
- 이전 시도(요구사항 추적 판정 에이전트)에서 옮겨 올 것:
  - `agent/llm/*`: RemoteLLM 공통화. 원본의 ollama/openai 중복 75%를 해소한다.
  - `agent/retrieval/{embedder,index,glossary,text}.py`
  - `agent/requirements.py`(엑셀 로더), `agent/rtm_excel.py`, `agent/analyzers/openapi.py`(근거 확인용)
  - `data/requirements/*`(29건), `data/glossary/standard_terms.json`, `sh/fetch_artifacts.sh`
  - tests 패턴(conftest, fake deps)

## PR 순서
| # | 브랜치 | 내용 |
|---|---|---|
| 0 | `main` | — | 샘플을 복사하고 이름을 req-trace-agent로 바꾼다(LangSmith 프로젝트, FastMCP 이름, 화면 제목, sh 로그 경로). 샘플 전용 파일(`make_student_zip.sh`, `doc/image_usecase*`, 매뉴얼 2종)을 삭제하고 `.gitignore`에 `*.pdf`를 추가한다. 이 상태에서도 원본 인시던트 에이전트는 동작한다. |
| 1 | `setting` | 인시던트 도메인(데이터·노드·프롬프트·v1)을 제거하고 뼈대를 잡는다. 패키지 구조 `agent/{nodes,llm,store,retrieval,graphs}`, `config.py`, `prompts.py`, LLM 공통화와 async 전환, SQLite 스키마, route→chat 최소 그래프, fake 백엔드, pytest와 CI, `.env.example`, README 골격, `doc/plan.md`. 화면은 탭 골격만 |
| 2 | `feat/requirements` | 업로드 API와 화면, 요구사항·조건 저장소, 조건 초안 생성 에이전트와 확정 UI, 데모 시드(`tools/seed_demo.py`: 29건 + 체크리스트) |
| 3 | `feat/report-intake` | 완료 보고 폼, intake 그래프(extract→candidates→map→verify→confirm→save), RAG, `artifact` MCP 서버, 상태 계산, 데모 보고 15~20건 시드(가상 개발자 3명) |
| 4 | `feat/dashboard-export` | 집계 API(진척률·분류별·담당자별·추이·위험 신호), 대시보드 탭(Chart.js), **검수용 엑셀 내보내기**(시트 3종, 기준일 지정) + 엑셀 내용 테스트 |
| 5 | `feat/chatbot` | 질의응답·요약 에이전트, `trace` MCP Tool 연결, 수치 검증 루프, 채팅 탭(SSE 진행 표시) |
| 6 | `docs/eval` | 평가: 보고→요구사항 매핑 정확도, 조건 매핑 정확도, 답변 수치 일치율(라벨 시드 기준). LangSmith 확인, README·한계·회귀 질의 문서 |

## 검증
- 각 PR: `pytest -q`(CI), fake 백엔드로 서버와 화면을 띄워 해당 기능을 수동 확인하고 PR 본문에 기록한다.
- PR 3: qwen3:8b로 "보호자 성으로 검색 API 만들었어요 GET /owners?lastName=" → SFR-005, 조건 1/2 충족 → 부분완료 제안 → 확인 후 대시보드 반영
- PR 4: 시드 데이터로 대시보드 수치와 엑셀 요약 시트 수치가 같은 집계 함수 결과와 일치하는지 테스트. 엑셀을 열어 시트 3종과 서식 확인
- PR 5: "보안 요구사항 진행률은?"에 대한 답의 숫자가 `get_progress` 결과와 일치하는지 확인
- PR 6: 평가 수치를 README에 기록
