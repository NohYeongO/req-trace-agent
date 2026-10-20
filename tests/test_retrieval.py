"""요구사항 검색(RAG) — 해시 임베더로 결정론 확인. 실모델(bge-m3) 수치는 PR 본문에 기록."""
from agent.config import DATA_DIR
from agent.retrieval import Glossary, HashEmbedder, RequirementSearch
from tools.seed_demo import seed_criteria


def test_search_finds_requirement_from_report_sentence(store, tmp_path):
    seed_criteria(store, force=False)
    s = RequirementSearch(store, HashEmbedder(), Glossary.load(DATA_DIR / "glossary" / "standard_terms.json"),
                          tmp_path / "idx")
    hits = s.search("수의사 관리 API 등록 조회 수정 삭제 끝냈습니다", top_k=3)
    assert hits[0]["req_id"] == "SFR-012"
    assert len({h["req_id"] for h in hits}) == len(hits)   # 요구사항 단위로 묶임


def test_index_rebuilds_only_when_content_changes(store, tmp_path):
    seed_criteria(store, force=False)
    s = RequirementSearch(store, HashEmbedder(), Glossary({}), tmp_path / "idx")
    first = s.index()
    assert s.index() is first                      # 내용이 같으면 재사용
    store.replace_criteria("SFR-001", [{"text": "보호자를 등록할 수 있다"}], confirm=True)
    assert s.index() is not first                  # 조건이 바뀌면 다시 임베딩
    assert len(list((tmp_path / "idx").glob("*.npy"))) == 2
