# req-trace-agent

**공공 SI 개발 완료 보고 기반 요구사항 진척 관리 에이전트**

## 이 에이전트가 하는 일
1. 개발자가 개발을 끝낼 때마다 완료 보고를 쓴다. AI는 보고를 요구사항과 완료 조건에 매핑하고, 근거(파일·API·커밋·PR)가 Git 저장소에 실제로 있는지 확인한다.
2. 담당자가 확인한 내용만 저장된다.
3. 진척은 대시보드, 검수용 요구사항 추적표(엑셀), 채팅으로 본다.
4. 테스트 결과 보고서와 개발 명세서 같은 검수 산출물 초안을 자동으로 만든다.

> AI는 구현 여부를 **판정하지 않는다**. 사실의 출처는 개발자 보고이고, 상태(완료/부분완료/미착수)는 확정된 체크리스트 충족 여부로 **코드가 계산**한다. AI는 정리, 매핑, 요약, 서술만 맡고 모든 결과는 사람이 확인한 뒤 반영된다.

## 주요 기능
| 탭 | 기능 |
|---|---|
| 대시보드 | 전체·분류별·담당자별 진척률, 진척 추이(burn-up), 위험 신호(보고 없음, 부분완료 정체), 최근 보고, **검수용 엑셀 내보내기**(표지·요약 / 추적표 / 보고 이력, 기준일 지정) |
| 완료 보고 | 반정형 양식(요구사항 선택, 근거 행 입력, 자유 서술). AI 정리 결과 카드에서 요구사항·조건 체크, 근거 확인 결과를 보고 **확인/취소** |
| 요구사항 | 명세서 엑셀 업로드, 요구사항별 완료 조건 체크리스트(AI 초안 → 사람 확정), 연결된 보고 이력 |
| 채팅 | "SFR-018 남은 거 뭐야?", "보안 요구사항 진행률은?", "지난주 완료된 거", "그럼 품질은?" 같은 후속 질문, 채팅으로 완료 보고 입력 |
| 산출물 | **테스트 결과 보고서**(JUnit/JaCoCo XML), **개발 명세서**(테이블·인터페이스 정의서) 초안 → 섹션 수정 → 확정 → docx/xlsx 다운로드 |

## 구조
```
브라우저(web_chat.html, Vue 3) ── web_demo_server.py :8600 ──▶ server.py(FastAPI) :8100
                                                               │ SSE로 단계별 진행 표시
 ┌────────────────────────── LangGraph 그래프 4개 ─────────────────┴──────────────────┐
 │ criteria     select → draft → validate ⟲ → save                                   │
 │ intake       extract → candidates(RAG) → map → validate ⟲ → verify                │
 │              → confirm(interrupt, 사람 확인) → save                                 │
 │ chat         route → plan → research(MCP) → write → validate ⟲                    │
 │              (보고 입력이면 report → intake 그래프로 위임)                              │
 │ deliverable  collect(MCP) → build(코드) → write(AI) → validate ⟲ → save            │
 └──────────────────────────────────────────────────────────────────────────────────┘
          │ MCP(stdio)                       │ LLM                       │
 ┌────────┴──────────────────┐   ┌──────────┴──────────┐   SQLite 업무 DB
 │ trace 서버                 │   │ fast: qwen3:0.6b     │   (요구사항·조건·보고·산출물)
 │  진척·요구사항·보고 조회      │   │ quality: qwen3:8b    │
 │  search_requirements(RAG) │   │ (fake / openai 교체) │
 │ artifact 서버              │   └─────────────────────┘
 │  근거 확인(Git·GitHub PR)   │
 │  JUnit/JaCoCo 분석          │
 │  Java·DDL 소스 분석         │
 └───────────────────────────┘
```
⟲는 검증 실패 시 사유를 붙여 다시 작성하는 루프다. 상한을 넘으면 코드가 만든 대체 문장으로 끝낸다.

## 적용한 기술 요소
| 요소 | 적용 |
|---|---|
| **Multi-Agent** (LangGraph) | 목적별 그래프 4개. 채팅 그래프가 질문은 질의응답 노드로, 완료 보고는 보고 정리 에이전트(intake 그래프)로 위임한다. 노드마다 LLM(작성)과 코드(검증)의 역할을 나눴다 |
| **MCP** (fastmcp) | `trace` 서버(요구사항·진척·보고 조회, RAG 검색)와 `artifact` 서버(근거 확인, 테스트 결과 분석, 소스 명세 분석)를 별도 프로세스로 띄운다. 에이전트는 도구 이름으로 서버를 찾는다 |
| **RAG** | 요구사항과 완료 조건 문장을 bge-m3로 임베딩한다. 표준 용어 사전으로 질의를 확장해 보고와 관련된 후보 요구사항을 찾는다 |
| **Human-in-the-loop** | 보고 정리는 `interrupt()`와 체크포인터로 멈췄다가 확인 후 재개한다. 조건 초안과 산출물은 초안 → 검토 → 확정 순서다 |
| **의존성 주입** | `SupervisorDeps`(LLM 2종, MCP, 저장소, 설정)를 노드에 주입한다. fake LLM으로 바꿔 네트워크 없이 테스트한다 |
| **LangSmith** | 그래프별 트레이스 이름(`chat`, `report_intake`, `deliverable:*`)과 메타데이터, 노드·LLM·MCP 호출 단위 `@traceable` |
| **모듈화** | 산출물 레지스트리(문서 종류마다 수집·작성·검증·대체 함수 모듈), LLM 백엔드 공통화(`RemoteLLM`), 분석기 분리 |
| **단위 테스트** | pytest(fake 백엔드), GitHub Actions에서 PR마다 실행 |

## 평가 요약
자세한 내용은 [doc/evaluation.md](doc/evaluation.md)를 보면 된다.

| 항목 | 결과 (qwen3:8b) |
|---|---|
| 보고 → 요구사항 매핑 (11건) | 요구사항 정밀도 1.000 / 재현율 0.926, 조건 정밀도 0.979 / 재현율 0.939 |
| 채팅 정답률 (24문항) | 58.3% → **100%**, 평균 응답 6.9초 → **1.0초** |
| 산출물 초안 | AI 작업 17건 모두 1차 검증 통과, 서술 수치 경고 0건, 엔티티·DDL 불일치 10건 검출 |

## 실행
```bash
cp .env.example .env            # 사업명, 근거 확인 저장소(ARTIFACT_REPO_URL), LangSmith(선택)
sh/setup_venv.sh                # .venv와 의존성
sh/setup_ollama.sh              # qwen3:0.6b, qwen3:8b, bge-m3 받기
.venv/bin/python3 tools/seed_demo.py   # 데모 요구사항·조건·보고(zerofive-store)
sh/run_agent_ollma.sh           # 에이전트 :8100  (OpenAI는 sh/run_agent_openai.sh)
sh/run_frontend.sh              # 화면 http://localhost:8600
```
- 네트워크 없이 화면만 볼 때: `LLM_BACKEND=fake .venv/bin/python3 server.py`
- 데이터 초기화: `sh/reset_data.sh [--seed] [--all]`. 업무 DB는 자동 백업 후 지운다.
- 테스트: `.venv/bin/python3 -m pytest -q`
- 평가: `eval/run_intake_eval.py`, `eval/run_chat_eval.py`, `eval/run_deliverable_eval.py`

## 폴더
```
agent/
  graphs/        LangGraph 그래프 4개
  nodes/         그래프 노드(작성·검증·재시도)
  deliverables/  산출물 레지스트리, 테스트 결과 보고서, 개발 명세서, JUnit·Java·DDL 파서, docx·xlsx 출력
  retrieval/     임베딩, 색인, 용어 사전
  llm/           fake · ollama · openai 백엔드
  store/         SQLite 스키마와 저장소
  qa.py answers.py  채팅 질문 분석, 코드가 쓰는 답 본문, 검증
mcp_server.py           trace MCP 서버
mcp_server_artifact.py  artifact MCP 서버
server.py               FastAPI(SSE)
web_chat.html           화면
data/demo/              데모 완료 조건·보고·테스트 결과
eval/                   평가 스크립트와 결과
doc/                    계획, 평가, 한계
```

## 문서
- [진행 계획](doc/plan.md)
- [평가](doc/evaluation.md)
- [한계와 향후 개선](doc/limitations.md)
