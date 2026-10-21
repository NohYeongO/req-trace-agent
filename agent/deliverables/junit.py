"""테스트 결과 파일 해석 — JUnit XML(Gradle·Maven surefire)과 JaCoCo XML.

폴더 아래의 XML을 모두 읽어 루트 태그로 종류를 가린다(testsuite·testsuites = JUnit, report = JaCoCo).
모듈 이름은 결과 폴더 바로 아래 폴더 이름(멀티 모듈 빌드에서 모듈별로 모은 경우)으로 한다.
system-out·system-err(로그)는 읽지 않는다 — 크고, 경로·호스트 같은 환경 정보가 섞여 있다.
"""
import re
import xml.etree.ElementTree as ET
from pathlib import Path

PASSED, FAILED, ERROR, SKIPPED = "통과", "실패", "오류", "건너뜀"


def _outer(classname: str) -> str:
    """'com.x.CartAppServiceTest$AddItem' → 'CartAppServiceTest' (중첩 클래스는 바깥 클래스로 묶는다)"""
    return classname.rsplit(".", 1)[-1].split("$", 1)[0]


def _first_line(text: str | None, limit: int = 300) -> str:
    text = (text or "").strip()
    return text.splitlines()[0][:limit] if text else ""


def _causes(detail: str | None) -> list[str]:
    """스택 트레이스의 'Caused by: X: 메시지' 줄들 — 실패의 근본 원인을 묶는 데 쓴다."""
    return [m.group(1).strip()[:200] for m in re.finditer(r"Caused by:\s*([^\n]+)", detail or "")]


def _module(path: Path, root: Path) -> str:
    rel = path.relative_to(root).parts
    return rel[0] if len(rel) > 1 else "(전체)"


def parse_junit(path: Path, root: Path) -> list[dict]:
    tree = ET.parse(path).getroot()
    suites = [tree] if tree.tag == "testsuite" else tree.findall(".//testsuite")
    cases = []
    for suite in suites:
        for tc in suite.findall("testcase"):
            status, node = PASSED, None
            for tag, st in (("failure", FAILED), ("error", ERROR), ("skipped", SKIPPED)):
                node = tc.find(tag)
                if node is not None:
                    status = st
                    break
            detail = (node.text or "") if node is not None else ""
            cases.append({
                "module": _module(path, root), "classname": tc.get("classname", ""),
                "class": _outer(tc.get("classname", "")), "name": tc.get("name", ""),
                "time": float(tc.get("time") or 0), "status": status,
                "type": node.get("type", "") if node is not None else "",
                "message": _first_line(node.get("message") if node is not None else ""),
                "causes": _causes(detail), "timestamp": suite.get("timestamp", ""),
            })
    return cases


def parse_jacoco(path: Path) -> dict:
    tree = ET.parse(path).getroot()
    counters = {c.get("type"): (int(c.get("covered")), int(c.get("missed"))) for c in tree.findall("counter")}

    def rate(kind):
        cov, mis = counters.get(kind, (0, 0))
        return {"covered": cov, "missed": mis, "rate": round(100 * cov / (cov + mis), 1) if cov + mis else None}

    return {"module": tree.get("name", ""), "line": rate("LINE"), "branch": rate("BRANCH"),
            "method": rate("METHOD"), "class": rate("CLASS")}


def read_results(root: Path) -> dict:
    """결과 폴더 전체를 읽어 테스트 케이스 목록과 커버리지를 돌려준다."""
    cases, coverage, skipped_files = [], [], []
    for p in sorted(root.rglob("*.xml")):
        try:
            tag = ET.parse(p).getroot().tag
        except ET.ParseError:
            skipped_files.append(p.name)
            continue
        if tag in ("testsuite", "testsuites"):
            cases += parse_junit(p, root)
        elif tag == "report":
            coverage.append(parse_jacoco(p))
    return {"cases": cases, "coverage": coverage, "unreadable": skipped_files}


def summarize(cases: list[dict]) -> dict:
    """총·통과·실패·오류·건너뜀 건수와 통과율(실행한 것 기준)."""
    count = {s: sum(c["status"] == s for c in cases) for s in (PASSED, FAILED, ERROR, SKIPPED)}
    ran = len(cases) - count[SKIPPED]
    return {"total": len(cases), **count, "pass_rate": round(100 * count[PASSED] / ran, 1) if ran else None,
            "time": round(sum(c["time"] for c in cases), 3)}


def total_coverage(coverage: list[dict]) -> dict | None:
    """모듈별 JaCoCo를 합친 전체 라인·분기 커버리지."""
    if not coverage:
        return None
    out = {}
    for kind in ("line", "branch"):
        cov = sum(c[kind]["covered"] for c in coverage)
        mis = sum(c[kind]["missed"] for c in coverage)
        out[kind] = {"covered": cov, "missed": mis, "rate": round(100 * cov / (cov + mis), 1) if cov + mis else None}
    return out
