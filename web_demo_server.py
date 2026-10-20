"""web_demo_server.py — 브라우저 화면(web_chat.html) + 백엔드 프록시(:8600).

web_chat.html 한 장을 같은 출처(origin)로 띄우고, 그 밖의 모든 요청을 백엔드(server.py,
:8100)로 그대로 중계한다. 브라우저의 CORS 제약 없이 에이전트를 쓰기 위한 얇은 레이어다.
SSE(text/event-stream) 응답은 버퍼링 없이 흘려보낸다. server.py가 먼저 떠 있어야 한다.

실행:
    python3 web_demo_server.py        # http://localhost:8600
"""
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from starlette.background import BackgroundTask

BACKEND = "http://127.0.0.1:8100"
HERE = Path(__file__).parent
# hop-by-hop 헤더와 길이 헤더는 프록시가 다시 계산하게 둔다.
_DROP_HEADERS = {"host", "content-length", "connection", "transfer-encoding", "content-encoding"}

app = FastAPI()
client = httpx.AsyncClient(base_url=BACKEND, timeout=None)


@app.get("/")
async def index():
    return FileResponse(HERE / "web_chat.html")


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def proxy(path: str, request: Request):
    headers = {k: v for k, v in request.headers.items() if k.lower() not in _DROP_HEADERS}
    try:
        upstream = await client.send(
            client.build_request(request.method, f"/{path}", params=request.query_params,
                                 headers=headers, content=await request.body()),
            stream=True)
    except httpx.ConnectError:
        return JSONResponse({"detail": "백엔드(8100)에 연결할 수 없습니다. server.py가 떠 있는지 확인하세요."},
                            status_code=502)
    out_headers = {k: v for k, v in upstream.headers.items() if k.lower() not in _DROP_HEADERS}
    if upstream.headers.get("content-type", "").startswith("text/event-stream"):
        return StreamingResponse(upstream.aiter_raw(), status_code=upstream.status_code,
                                 headers=out_headers, background=BackgroundTask(upstream.aclose))
    body = await upstream.aread()
    await upstream.aclose()
    return Response(body, status_code=upstream.status_code, headers=out_headers)


if __name__ == "__main__":
    print("브라우저에서 http://localhost:8600 을 열어보세요 (server.py가 8100에 떠 있어야 합니다)")
    uvicorn.run(app, host="0.0.0.0", port=8600)
