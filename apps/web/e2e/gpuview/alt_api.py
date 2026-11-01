"""GPUVIEW 截图 / 核对用的只读小实例（:8801）：只挂 /api/gpu/* 与 /api/render-tasks，不挂任何会派活的路由。
:8800 还没重启时用它验证新接口（shoot.mjs 的 DA_ALT）。ns_api 自己的任务表从 :8800 的 /api/jobs、
/api/episodes/summary 读（render_tasks.SOURCE = "http"）。
用法：.venv/Scripts/python.exe apps/web/e2e/gpuview/alt_api.py [port]
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
for p in ("services/api", "services/agent", "services/render_router", "packages/ns_schema", "packages"):
    sys.path.insert(0, str(ROOT / p))
import uvicorn  # noqa: E402
from fastapi import FastAPI  # noqa: E402

from ns_api import gpu_live  # noqa: E402

app = FastAPI()
app.include_router(gpu_live.router)
try:
    from ns_api import render_tasks  # noqa: E402
    render_tasks.SOURCE = "http"
    app.include_router(render_tasks.router)
except ImportError as e:
    print("render_tasks 未加载：", e)
if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[1]) if len(sys.argv) > 1 else 8801, log_level="warning")
