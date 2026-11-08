"""P5 M2：旧前端 → 新 ns2 API 的桥（只转发，不加逻辑）。

浏览器同源请求 /ns2/<path> → 笔记本隧道 127.0.0.1:18900（config/netfix/tunnels.json gpu33-l0）→ gpu33 10.0.0.33:8900/<path>。
前端只经这里读唯一总览 /ns2/api/overview、定稿 /ns2/api/shots/{id}/review、看图 / 片 /ns2/files/<host>/…（支持 Range，视频可拖）。
回滚 = 前端 revert 调用点那一个 commit；本文件不被调用即无作用。
"""
from __future__ import annotations

import os
import urllib.error
import urllib.request

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response, StreamingResponse

NS2 = os.environ.get("NS2_API_LOCAL", "http://127.0.0.1:18900")
router = APIRouter()
PASS_REQ = ("content-type", "range", "accept")
PASS_RESP = ("content-type", "content-length", "content-range", "accept-ranges", "last-modified", "etag")


@router.api_route("/ns2/{path:path}", methods=["GET", "PUT", "POST", "HEAD"])
async def ns2(path: str, request: Request):
    if not (path.startswith("api/") or path.startswith("files/")):
        raise HTTPException(404)
    url = f"{NS2}/{path}" + (f"?{request.url.query}" if request.url.query else "")
    body = await request.body() if request.method in ("PUT", "POST") else None
    req = urllib.request.Request(url, data=body, method=request.method,
                                 headers={k: v for k, v in request.headers.items() if k.lower() in PASS_REQ})
    try:
        up = urllib.request.urlopen(req, timeout=60)
    except urllib.error.HTTPError as e:
        return Response(e.read(), status_code=e.code, media_type=e.headers.get("Content-Type"))
    except OSError as e:
        raise HTTPException(502, f"ns2 新 API 不通（隧道 18900 → gpu33:8900）：{e}")
    hdr = {k: v for k, v in up.headers.items() if k.lower() in PASS_RESP}
    if path.startswith("files/"):
        return StreamingResponse(iter(lambda: up.read(1 << 16), b""), status_code=up.status, headers=hdr)
    return Response(up.read(), status_code=up.status, headers=hdr)
