"""账户登录 + 审计（UIRSI 2026-10-31）。

项目方原话：“系统是在我 login 的，意味着我所做的所有行为都是我个人行为，所以你不需要每个东西都要打上一个字……要写入账户登录这个逻辑。”

- 本机账户：data/auth/users.json（密码 PBKDF2-SHA256 + 盐，不存明文）。第一次打开没有账户时，建的第一个账户就是项目方（role=owner）。
- 会话：登录后发 HttpOnly cookie `ns_session`（30 天），会话存 data/auth/sessions.json。
- 项目方闸门改成“从登录会话取身份”：AuthMiddleware 在写请求（非 GET）里——
    · 登录的项目方（role=owner）发 `by: "owner"` → 视为本人；原话字段（owner_quote / quote）没填就自动记“<账户> 登录点选”，不用再打字；
    · 没登录或不是项目方却声称 `by: "owner"` → 改成 `by: "unauthenticated"`，各闸门接口原有的检查会拒绝（403）。
  这样各模块的闸门检查不用逐个改，口径统一。
- 审计：每个写请求记一行 data/audit/<YYYYMMDD>.jsonl：时间、账户、角色、方法、路径、对象（请求体里的 id / key / path 等）、结果状态码；
  界面可看（GET /api/audit）。

接口：
  GET  /api/auth/me         {user: {name, role} | null, setup_needed}
  POST /api/auth/setup      {name, password}  只在还没有任何账户时可用：建项目方账户并登录
  POST /api/auth/login      {name, password}
  POST /api/auth/logout
  GET  /api/audit?limit=200 最近的操作记录（只给登录的项目方看）
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

REPO = Path(__file__).resolve().parents[3]
COOKIE = "ns_session"
SESSION_DAYS = 30
router = APIRouter(tags=["auth"])
_lock = threading.Lock()


def _dir() -> Path:
    d = REPO / "data" / "auth"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _read(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write(p: Path, obj) -> None:
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


def _users() -> list[dict]:
    return _read(_dir() / "users.json", {"users": []}).get("users", [])


def _hash(pw: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), bytes.fromhex(salt), 200_000).hex()


def _sessions() -> dict:
    return _read(_dir() / "sessions.json", {})


def viewer_token() -> str:
    """本机只读查看令牌（截图 / 走查脚本用，data/auth/viewer_token）：带请求头 x-ns-viewer-token 视为“查看者”，
    能打开界面、不能以项目方身份做任何决定（by=owner 会被拒）。文件只在本机，令牌不进前端代码。"""
    f = _dir() / "viewer_token"
    if not f.exists():
        f.write_text(secrets.token_urlsafe(24), encoding="utf-8")
    return f.read_text(encoding="utf-8").strip()


def user_of(request: Request) -> dict | None:
    vt = request.headers.get("x-ns-viewer-token")
    if vt and hmac.compare_digest(vt, viewer_token()):
        return {"name": "查看者（截图检查）", "role": "viewer"}
    tok = request.cookies.get(COOKIE)
    if not tok:
        return None
    s = _sessions().get(hashlib.sha256(tok.encode()).hexdigest())
    if not s or s.get("expires", 0) < time.time():
        return None
    return {"name": s["name"], "role": s["role"]}


def _login(resp: Response, u: dict) -> None:
    tok = secrets.token_urlsafe(32)
    with _lock:
        ss = {k: v for k, v in _sessions().items() if v.get("expires", 0) > time.time()}
        ss[hashlib.sha256(tok.encode()).hexdigest()] = {"name": u["name"], "role": u["role"], "created": time.time(),
                                                         "expires": time.time() + SESSION_DAYS * 86400}
        _write(_dir() / "sessions.json", ss)
    resp.set_cookie(COOKIE, tok, max_age=SESSION_DAYS * 86400, httponly=True, samesite="lax", path="/")


class Cred(BaseModel):
    name: str
    password: str


@router.get("/api/auth/me")
def me(request: Request):
    return {"user": user_of(request), "setup_needed": not _users()}


@router.post("/api/auth/setup")
def setup(body: Cred, response: Response):
    if not body.name.strip() or len(body.password) < 4:
        raise HTTPException(422, "名字不能空，密码至少 4 位")
    with _lock:
        if _users():
            raise HTTPException(409, "已经有账户了，请直接登录")
        salt = secrets.token_hex(16)
        u = {"name": body.name.strip(), "role": "owner", "salt": salt, "hash": _hash(body.password, salt), "created": time.time()}
        _write(_dir() / "users.json", {"users": [u]})
    _login(response, u)
    audit_line({"user": u["name"], "role": "owner", "method": "POST", "path": "/api/auth/setup", "status": 200})
    return {"user": {"name": u["name"], "role": "owner"}}


@router.post("/api/auth/login")
def login(body: Cred, response: Response):
    u = next((x for x in _users() if x["name"] == body.name.strip()), None)
    if not u or not hmac.compare_digest(u["hash"], _hash(body.password, u["salt"])):
        time.sleep(0.4)
        raise HTTPException(401, "账户或密码不对")
    _login(response, u)
    return {"user": {"name": u["name"], "role": u["role"]}}


@router.post("/api/auth/logout")
def logout(request: Request, response: Response):
    tok = request.cookies.get(COOKIE)
    if tok:
        with _lock:
            ss = _sessions()
            ss.pop(hashlib.sha256(tok.encode()).hexdigest(), None)
            _write(_dir() / "sessions.json", ss)
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


# ----------------------------------------------------------------------------- 审计
def _audit_dir() -> Path:
    d = REPO / "data" / "audit"
    d.mkdir(parents=True, exist_ok=True)
    return d


def audit_line(rec: dict) -> None:
    rec = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), **rec}
    try:
        with (_audit_dir() / f"{time.strftime('%Y%m%d')}.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass


@router.get("/api/audit")
def audit(request: Request, limit: int = 200):
    u = user_of(request)
    if not u or u["role"] not in ("owner", "viewer"):
        raise HTTPException(403, "只有登录的项目方能看操作记录")
    out: list[dict] = []
    for f in sorted(_audit_dir().glob("*.jsonl"), reverse=True):
        for ln in reversed(f.read_text(encoding="utf-8").splitlines()):
            try:
                out.append(json.loads(ln))
            except ValueError:
                continue
            if len(out) >= max(1, min(limit, 2000)):
                return {"items": out}
    return {"items": out}


# ----------------------------------------------------------------------------- 中间件：闸门身份 + 审计
OBJ_KEYS = ("id", "key", "rev", "path", "char", "run", "shot", "shot_id", "gate", "episode", "episodes", "stage", "n", "status", "asset_id", "look")
QUOTE_KEYS = ("owner_quote", "quote")
SKIP_AUDIT = ("/api/auth/me",)


class AuthMiddleware:
    """纯 ASGI 中间件：写请求按登录身份改写 by=owner 声明，并记审计。GET / HEAD 只透传。"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] in ("GET", "HEAD", "OPTIONS") or not scope["path"].startswith("/api/"):
            return await self.app(scope, receive, send)
        req = Request(scope)
        user = user_of(req)
        body = b""
        more = True
        while more:
            msg = await receive()
            body += msg.get("body", b"")
            more = msg.get("more_body", False)
        ctype = req.headers.get("content-type", "")
        obj_summary = {}
        claimed = False
        if body and "application/json" in ctype:
            try:
                data = json.loads(body)
            except ValueError:
                data = None
            if isinstance(data, dict):
                if data.get("by") == "owner":
                    claimed = True
                    if user and user["role"] == "owner":
                        for k in QUOTE_KEYS:
                            if k in data or k == "owner_quote":
                                if not str(data.get(k) or "").strip():
                                    data[k] = f"（{user['name']} 登录点选）"
                    else:
                        data["by"] = "unauthenticated"
                    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
                obj_summary = {k: data.get(k) for k in OBJ_KEYS if k in data}
        sent = False

        async def recv():
            nonlocal sent
            if sent:
                # 体已经给过了：之后交回原始 receive（流式响应靠它等客户端断开；不能立刻回 disconnect，否则 SSE 会被提前掐断）
                return await receive()
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}

        # 改写后的体长度变了：同步 content-length
        if body is not None:
            hdrs = [(k, v) for k, v in scope["headers"] if k.lower() != b"content-length"] + [(b"content-length", str(len(body)).encode())]
            scope = {**scope, "headers": hdrs}
        status = {"code": 0}

        async def snd(msg):
            if msg["type"] == "http.response.start":
                status["code"] = msg["status"]
            await send(msg)

        try:
            await self.app(scope, recv, snd)
        finally:
            if scope["path"] not in SKIP_AUDIT:
                audit_line({"user": user["name"] if user else None, "role": user["role"] if user else "agent/未登录",
                            "method": scope["method"], "path": scope["path"], "owner_claim": claimed,
                            "obj": obj_summary, "status": status["code"]})


def install(app) -> None:
    """app.py 里调用：挂路由 + 中间件（中间件在最外层，先于各路由的闸门检查）"""
    app.include_router(router)
    app.add_middleware(AuthMiddleware)
    os.environ.setdefault("NS_AUTH", "1")
    viewer_token()   # 启动时就生成本机查看令牌（截图脚本读这个文件）
