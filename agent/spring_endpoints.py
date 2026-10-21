"""Spring MVC 어노테이션에서 REST 엔드포인트 목록을 뽑는다.

springdoc처럼 OpenAPI 명세를 실행 중에 만드는 프로젝트는 저장소에 명세 파일이 없다. 그래서
컨트롤러 소스의 클래스 @RequestMapping(접두 경로)과 메서드 @GetMapping·@PostMapping 등을
조합해 'POST /api/orders/payment' 같은 엔드포인트를 만든다. 정식 파서가 아니라 어노테이션
문자열만 읽는 결정론 분석이다(상수로 만든 경로 등은 읽지 못한다 — 한계).
"""
import re
from dataclasses import dataclass

_MAPPING = re.compile(r"@(Get|Post|Put|Patch|Delete|Request)Mapping\b\s*(?:\(([^)]*)\))?")
_CLASS = re.compile(r"\b(class|interface)\s+(\w+)")
_STRINGS = re.compile(r'"([^"]*)"')
_PATH_KEY = re.compile(r"\b(?:value|path)\s*=\s*(\{[^}]*\}|\"[^\"]*\")")
_METHOD_KEY = re.compile(r"RequestMethod\.(GET|POST|PUT|PATCH|DELETE)")
_HANDLER = re.compile(r"\b(?:public|protected|private)?\s*[\w<>\[\],?\s]+?\s+(\w+)\s*\(")


@dataclass(frozen=True)
class Endpoint:
    method: str
    path: str
    handler: str     # Class.method
    line: int


def _paths(args: str | None) -> list[str]:
    if not args or not args.strip():
        return [""]
    args = args.strip()
    if args.startswith(("\"", "{")):                    # @GetMapping("/a") / @GetMapping({"/a","/b"})
        head = re.split(r",\s*\w+\s*=", args, maxsplit=1)[0]
        return _STRINGS.findall(head) or [""]
    m = _PATH_KEY.search(args)                           # @GetMapping(value = "/a", produces = ...)
    return _STRINGS.findall(m.group(1)) if m else [""]


def _join(prefix: str, path: str) -> str:
    joined = "/" + "/".join(p.strip("/") for p in (prefix, path) if p.strip("/"))
    return re.sub(r"/+", "/", joined)


def parse_controller(source: str) -> list[Endpoint]:
    """컨트롤러 소스 하나에서 엔드포인트를 뽑는다. @Controller·@RestController가 없으면 빈 목록."""
    if "@RestController" not in source and "@Controller" not in source:
        return []
    cls = _CLASS.search(source)
    if not cls:
        return []
    prefixes = [""]
    for m in _MAPPING.finditer(source[:cls.start()]):
        if m.group(1) == "Request":
            prefixes = _paths(m.group(2))
    out: list[Endpoint] = []
    for m in _MAPPING.finditer(source, cls.end()):
        kind, args = m.group(1), m.group(2)
        if kind == "Request":
            methods = _METHOD_KEY.findall(args or "") or ["GET"]
        else:
            methods = [kind.upper()]
        handler = _HANDLER.search(source, m.end())
        name = handler.group(1) if handler else "?"
        line = source[:m.start()].count("\n") + 1
        for prefix in prefixes:
            for path in _paths(args):
                for method in methods:
                    out.append(Endpoint(method, _join(prefix, path), f"{cls.group(2)}.{name}", line))
    return out
