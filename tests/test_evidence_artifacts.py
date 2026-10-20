"""근거 추출(정규식)과 산출물 실존 확인."""
from pathlib import Path

from agent.artifacts import ArtifactChecker
from agent.evidence import extract_evidence

FIX = Path(__file__).parent / "fixtures" / "mini_artifact"


def test_extract_evidence_handles_korean_particles_and_kinds():
    text = ("SFR-005 성 검색 API 끝냈어요. GET /owners?lastName=Davis로 조회되고 OwnerController.listOwners를 "
            "고쳤고 OwnerService.java에 반영. OwnerControllerTests의 testListOwnersByLastName 통과. PR #12, 커밋 a1b2c3d")
    got = [(e["type"], e["value"]) for e in extract_evidence(text)]
    assert got == [("api", "GET /owners"), ("file", "OwnerService.java"),
                   ("test", "OwnerControllerTests"), ("test", "testListOwnersByLastName"),
                   ("code", "OwnerController.listOwners"), ("pr", "#12"), ("commit", "a1b2c3d")]


def test_extract_evidence_ignores_plain_korean():
    assert extract_evidence("보호자 등록 기능을 마무리했습니다.") == []


def _check(*items):
    return [r["status"] for r in ArtifactChecker(FIX).check([{"type": t, "value": v} for t, v in items])]


def test_checker_finds_real_and_rejects_made_up_evidence():
    assert _check(("api", "POST /owners"), ("api", "DELETE /owners/7"), ("api", "DELETE /api/owners/{ownerId}"),
                  ("file", "OwnerController.java"), ("code", "OwnerController.listOwners"),
                  ("test", "testListOwnersByLastName"), ("code", "OwnerFields")) == ["found"] * 7
    assert _check(("api", "GET /owners/phone"),          # ownerId 자리에 단어 → 다른 엔드포인트
                  ("api", "PUT /owners/1"), ("file", "OwnerSearch.java"),
                  ("code", "OwnerController.searchByPhone"), ("test", "testSearchByPhone"),
                  ("test", "listOwners")) == ["not_found"] * 6   # 테스트가 아닌 메서드는 테스트로 인정 안 함


def test_checker_marks_external_and_missing_root_as_unchecked():
    assert _check(("pr", "#3"), ("commit", "abc1234")) == ["unchecked", "unchecked"]
    r = ArtifactChecker(None).check([{"type": "api", "value": "GET /owners"}])
    assert r[0]["status"] == "unchecked" and "ARTIFACT_ROOT" in r[0]["where"]
