"""UX6 截图用只读旁路（端口 8802）：挂 revisions / revisions_p1 / cuts / asset_center_p1 路由。
observe、快照、账本写入全部关掉；中间件只放行 GET/HEAD 和只读的 POST /api/revisions/impact(-shots)，其余一律 403。
不是 :8800，不影响渲染。"""
import os
os.chdir(r"D:\NS-Final Studio")
from ns_agent import asset_revs as AR
from ns_agent import asset_revs_p1 as ARP
AR.observe = lambda *a, **k: []
ARP.snapshot = lambda *a, **k: None
ARP.snapshot_quiet = lambda *a, **k: None
# 演示账本（只在内存里，不写盘）：真实账本 data/assets/revisions.jsonl 要等 :8800 重启后才开始记，
# 为了截到“版本列表 + 回到这版”的样子，给定妆 / 预设各造一条“上一版”（标 by=observed），has_snapshot 只对这条演示版本为真
if os.environ.get("UX6_DEMO") == "1":
    _real_cur = AR.current_rev
    DEMO = {}
    def _demo_ledger(root=None):
        out = {}
        for k in ("identity:lin_wan", "preset:leica_sstar", "voice:lin_wan"):
            cur = _real_cur(k, root)
            if not cur:
                continue
            old = "demo" + cur[4:]
            DEMO[k] = old
            out[k] = [{"key": k, "rev": old, "seq": 1, "label": AR.label(k, root), "at": "2026-10-30T21:10:00", "by": "baseline"},
                      {"key": k, "rev": cur, "seq": 2, "prev": old, "label": AR.label(k, root), "at": "2026-10-31T18:40:00", "by": "observed"}]
        return out
    AR.read_ledger = _demo_ledger
    _real_has = ARP.has_snapshot
    ARP.has_snapshot = lambda key, rev, root=None: (rev is not None and rev.startswith("demo")) or _real_has(key, rev, root)
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from ns_api import revisions, revisions_p1, cuts, asset_center_p1

app = FastAPI()
READONLY_POST = {"/api/revisions/impact", "/api/revisions/impact-shots"}


@app.middleware("http")
async def readonly(request: Request, call_next):
    if request.method not in ("GET", "HEAD") and request.url.path not in READONLY_POST:
        return JSONResponse({"detail": "只读旁路：不接受写请求"}, status_code=403)
    return await call_next(request)


for r in (revisions.router, revisions_p1.router, cuts.router, asset_center_p1.router):
    app.include_router(r)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8802, log_level="warning")
