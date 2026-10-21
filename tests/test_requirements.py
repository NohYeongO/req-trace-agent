import io
import json

import pytest
from openpyxl import Workbook

from agent.config import DATA_DIR
from agent.requirements import REQ_ID_RE, load_requirements, load_requirements_file


def _xlsx(rows) -> bytes:
    wb = Workbook()
    for r in rows:
        wb.active.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_demo_files_have_32_requirements():
    xlsx = load_requirements_file(DATA_DIR / "requirements" / "zerofive_requirements.xlsx")
    js = load_requirements_file(DATA_DIR / "requirements" / "zerofive_requirements.json")
    assert len(xlsx.requirements) == len(js.requirements) == 32
    assert xlsx.requirements == js.requirements
    assert xlsx.warnings == []


def test_header_aliases_and_warnings():
    data = _xlsx([
        ["고유번호", "구분", "요구사항 명칭", "세부내용", "중요도"],
        ["SFR-001", "기능", "보호자 등록", "등록한다", "상"],
        [None, None, None, None, None],                 # 빈 행은 조용히 건너뜀
        ["기능-1", "기능", "잘못된 ID", "", ""],         # 형식 오류
        ["SFR-002", "기능", None, "", ""],              # 이름 없음
        ["SFR-001", "기능", "중복", "", ""],             # 중복
        ["SER-001", "보안", "접근통제", "역할별", 1],     # 숫자 셀도 문자열로
    ])
    r = load_requirements(data, "명세서.xlsx")
    assert [x.id for x in r.requirements] == ["SFR-001", "SER-001"]
    assert r.requirements[1].priority == "1"
    assert len(r.warnings) == 3
    assert r.warnings[0].startswith("엑셀 4행")   # 헤더 다음부터 엑셀 행 번호로 안내


def test_missing_required_columns():
    with pytest.raises(ValueError, match="요구사항명"):
        load_requirements(_xlsx([["번호", "내용"], ["SFR-001", "x"]]), "a.xlsx")


def test_json_list_and_unsupported_format():
    data = json.dumps([{"id": "QUR-001", "name": "오류 응답 표준화"}]).encode()
    assert load_requirements(data, "a.json").requirements[0].name == "오류 응답 표준화"
    with pytest.raises(ValueError, match="지원하지 않는"):
        load_requirements(b"x", "a.csv")


def test_req_id_regex_handles_korean_particles():
    assert REQ_ID_RE.findall("SFR-001이랑 SER-002, ABCD-1234는 아님") == ["SFR-001", "SER-002"]
