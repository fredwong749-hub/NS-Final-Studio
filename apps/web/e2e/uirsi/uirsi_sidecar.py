"""UIRSI 截图用只读旁路（端口 8803）：挂 story_runs（新建剧本）和 revisions（只读影响面）路由。
:8800 重启前新接口在线上是 404，截图时这些 GET 转到这里。observe / 账本写入关掉；中间件只放行 GET/HEAD 和
只读的 POST /api/revisions/impact(-shots)，其余一律 403（不会起写作线程、不花钱、不写盘）。不是 :8800，不影响渲染。
用法：.venv/Scripts/python.exe apps/web/e2e/uirsi/uirsi_sidecar.py
"""
import os

os.chdir(r"D:\NS-Final Studio")
from ns_agent import asset_revs as AR  # noqa: E402

AR.observe = lambda *a, **k: []
from fastapi import FastAPI, Request  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402

from ns_api import revisions, story_runs  # noqa: E402

app = FastAPI()
READONLY_POST = {"/api/revisions/impact", "/api/revisions/impact-shots"}


@app.middleware("http")
async def readonly(request: Request, call_next):
    if request.method not in ("GET", "HEAD") and request.url.path not in READONLY_POST:
        return JSONResponse({"detail": "只读旁路：不接受写请求"}, status_code=403)
    return await call_next(request)


for r in (revisions.router, story_runs.router):
    app.include_router(r)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8803, log_level="warning")
