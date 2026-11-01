"""UIRSI r38 截图用只读旁路（端口 8804）：挂 infra_status（/api/infra/status）、gpu_live 的缩略图（/api/gpu/thumb）、r40 的 /api/candidates 与 /api/season（只读）。
:8800 重启前这两个改动在线上还没生效，截图时 shoot.mjs（SIDE_URL / SIDE_GET_RE 环境变量）把这两条 GET 转到这里。
只放行 GET/HEAD；不是 :8800，不影响渲染。用法：.venv/Scripts/python.exe apps/web/e2e/uirsi/infra_sidecar.py
"""
import os
import sys

os.chdir(r"D:\NS-Final Studio")
for p in ("services/api", "services/render_router", "services/agent"):
    sys.path.insert(0, p)
from fastapi import FastAPI, Request  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402

from ns_api import decision_locks, gpu_live, infra_status, season, takes_ui  # noqa: E402

app = FastAPI()


@app.middleware("http")
async def readonly(request: Request, call_next):
    if request.method not in ("GET", "HEAD"):
        return JSONResponse({"detail": "只读旁路：不接受写请求"}, status_code=403)
    return await call_next(request)


app.include_router(infra_status.router)
app.add_api_route("/api/gpu/thumb", gpu_live.gpu_thumb, methods=["GET"])
# r40：候选按剧本版本过滤（takes_ui.candidates）+ 总览（season）——只读 GET
app.add_api_route("/api/candidates", takes_ui.candidates, methods=["GET"])
app.include_router(season.router)
app.include_router(decision_locks.router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8804, log_level="warning")
