"""
Qwen 信箱代理（画布 ↔ gpu3 上的 Qwen Docker）。

硬规则：内容（G1–G6）全归 Qwen。画布和 Qwen 只经信箱说话；本模块**不读、不改、不判断**内容——
任务文字原样转发，Qwen 的 result.output 原样存、原样返回。

上游（gpu3 127.0.0.1:8099，笔记本经隧道 127.0.0.1:18099；NS_QWEN_MAILBOX 可改）：
  POST /tasks {"from":"canvas","text":…,"meta":{…}} → 201 {"id"}
  GET  /tasks/<id> → {status: queued|running|done|failed, result:{output}}
  GET  /health

画布接口（本模块 router，前缀 /api/qwen）：
  （docs/qwen_comms.md 为准；meta.kind 必填：script|lora|blender|crawl|other，image_request 预留 → 501）
  POST /api/qwen/tasks         {text, meta:{kind, project, episode, shot, …}} → 201 {id, status, …本地记录}
  GET  /api/qwen/tasks/{id}/files          交付物清单（上游 /files/<id>/ 原样）
  GET  /api/qwen/tasks/{id}/files/{path}   交付物原样字节
  POST /api/qwen/tasks/{id}/script/fetch   kind=script：取回 script.md 原样落盘 + 跑 tools/validate_qwen_script.py
  POST /api/qwen/tasks/{id}/script/repair  校验不过：返修文字原样作为新 script 任务（meta.parent=id）
  POST /api/qwen/tasks/{id}/script/import  {confirm:true, by:"owner"} 项目方确认后 tools/import_script.py 导入
  GET  /api/qwen/tasks/{id}    上游最新状态（顺带更新本地索引）；隧道断 → 本地记录 + reachable:false
  GET  /api/qwen/tasks?shot=&project=&episode=&kind=&refresh=1&limit=50  本地索引（新→旧），未完成的顺带刷新
  GET  /api/qwen/health        {reachable, upstream, health|error, hint}（总是 200）
本地索引 data/qwen_tasks.jsonl：只追加，每行一个快照，同 id 以最后一行为准。
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ns_api import project_ctx as PJC

MAILBOX_URL = os.environ.get("NS_QWEN_MAILBOX", "http://127.0.0.1:18099").rstrip("/")
INDEX: Path | None = None          # 测试用：覆盖 data/qwen_tasks.jsonl
TIMEOUT_S = 5.0
TERMINAL = ("done", "failed", "cancelled")   # cancelled：本地取消（上游已删，再问只会 404 拖慢列表）
KINDS = ("script", "lora", "blender", "crawl", "image_request", "other")   # docs/qwen_comms.md §3 meta.kind
RESERVED_KINDS = ("image_request",)                                        # §6 Image Docker 未上线：只预留
HINT = ("Qwen 信箱不可达：请先开隧道 ssh -N -L 18099:127.0.0.1:8099 gpu33，"
        "并确认 gpu3 上 Qwen Docker 信箱（127.0.0.1:8099）在运行")

router = APIRouter(prefix="/api/qwen")
_lock = threading.Lock()


class MailboxError(Exception):
    def __init__(self, msg: str, code: int | None = None):
        super().__init__(msg)
        self.code = code


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def index_path() -> Path:
    return INDEX or (PJC.REPO / "data" / "qwen_tasks.jsonl")


# ---------------------------------------------------------------- 上游 HTTP

def _call(method: str, path: str, body: dict | None = None, timeout: float = TIMEOUT_S):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    r = urllib.request.Request(MAILBOX_URL + path, data=data, method=method,
                               headers={"Content-Type": "application/json; charset=utf-8"})
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode("utf-8", errors="replace")[:500]
        except Exception:  # noqa: BLE001
            detail = ""
        raise MailboxError(f"Qwen 信箱返回 {e.code}：{detail or e.reason}", e.code) from e
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise MailboxError(f"Qwen 信箱不可达（{MAILBOX_URL}）：{e}") from e


def _http_error(e: MailboxError) -> HTTPException:
    if e.code is None:
        return HTTPException(502, f"{e}。{HINT}")
    return HTTPException(e.code if 400 <= e.code < 500 else 502, str(e))


# ---------------------------------------------------------------- 本地索引

def _append(rec: dict) -> None:
    p = index_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with _lock, p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def load_index() -> dict[str, dict]:
    """id → 最新快照（按首次出现顺序）"""
    out: dict[str, dict] = {}
    p = index_path()
    if not p.exists():
        return out
    with _lock:
        lines = p.read_text(encoding="utf-8").splitlines()
    for ln in lines:
        try:
            rec = json.loads(ln)
        except ValueError:
            continue
        if isinstance(rec, dict) and rec.get("id"):
            out[str(rec["id"])] = {**out.get(str(rec["id"]), {}), **rec}
    return out


def _merge_upstream(rec: dict, up: dict) -> dict:
    """上游 GET /tasks/<id> → 本地快照；result 整个原样保存，output = result.output 原样"""
    if not isinstance(up, dict):   # 封板修复：上游返回非对象 JSON（列表 / 字符串）曾 AttributeError → 500；当作无变化
        return dict(rec)
    result = up.get("result")
    new = dict(rec)
    new.update({"status": up.get("status") or rec.get("status"), "updated_at": _now(), "upstream_ts": {
        k: up[k] for k in ("created_at", "started_at", "finished_at", "updated_at") if k in up}})
    if result is not None:
        new["result"] = result
        new["output"] = result.get("output") if isinstance(result, dict) else None
    if up.get("error") is not None:
        new["error"] = up.get("error")
    return new


def _refresh(rec: dict) -> dict:
    up = _call("GET", f"/tasks/{quote(rec['id'], safe='')}")
    new = _merge_upstream(rec, up)
    if any(new.get(k) != rec.get(k) for k in ("status", "result", "error")):
        _append(new)
    return new


# ---------------------------------------------------------------- 接口

class TaskBody(BaseModel):
    text: str
    meta: dict = Field(default_factory=dict)   # kind（必填）+ project / episode / shot …（原样转发）


def check_kind(meta: dict) -> None:
    kind = meta.get("kind")
    if kind not in KINDS:
        raise HTTPException(400, f"meta.kind 必填，只能是 {list(KINDS)}（docs/qwen_comms.md §3）")
    if kind in RESERVED_KINDS:
        raise HTTPException(501, f"meta.kind={kind} 已预留，尚未上线（docs/qwen_comms.md §6）")


@router.post("/tasks", status_code=201)
def create_task(body: TaskBody):
    if not body.text.strip():
        raise HTTPException(400, "任务文字为空")
    check_kind(body.meta)
    return submit(body.text, body.meta)


def submit(text: str, meta: dict) -> dict:
    """原样投递一条任务并记进本地索引"""
    try:
        up = _call("POST", "/tasks", {"from": "canvas", "text": text, "meta": meta})
    except MailboxError as e:
        raise _http_error(e)
    tid = (up or {}).get("id")
    if not tid:
        raise HTTPException(502, f"Qwen 信箱没有返回任务 id：{str(up)[:200]}")
    now = _now()
    rec = {"id": str(tid), "meta": meta, "text": text, "status": up.get("status") or "queued",
           "created_at": now, "updated_at": now, "output": None, "result": None}
    _append(rec)
    return rec


@router.get("/tasks/{task_id}")
def get_task(task_id: str):
    rec = load_index().get(task_id) or {"id": task_id, "meta": {}, "text": None, "status": None,
                                         "created_at": None, "untracked": True}
    try:
        return {**_refresh(rec), "reachable": True}
    except MailboxError as e:
        if e.code == 404:
            raise HTTPException(404, f"Qwen 信箱没有这个任务：{task_id}")
        if rec.get("untracked"):
            raise _http_error(e)
        return {**rec, "reachable": False, "error_upstream": str(e), "hint": HINT}


def _match(rec: dict, project, episode, shot, kind) -> bool:
    m = rec.get("meta") or {}
    return ((project is None or str(m.get("project")) == project)
            and (episode is None or str(m.get("episode")) == episode)
            and (shot is None or str(m.get("shot")) == shot)
            and (kind is None or str(m.get("kind")) == kind))


REFRESH_TTL_S = 5.0                # 列表顺带刷新：同一任务 5 s 内只问一次上游
_refreshed_at: dict[str, float] = {}
_last_reachable: list = [None]


@router.get("/tasks")
def list_tasks(shot: str | None = None, project: str | None = None, episode: str | None = None,
               kind: str | None = None, refresh: bool = True, limit: int = 50):
    """本地索引（新→旧）。refresh=1：未完成的任务顺带问上游（最多 10 个，隧道断即停，每个 ≤5 s）"""
    recs = [r for r in load_index().values() if _match(r, project, episode, shot, kind)]
    recs.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    recs = recs[:max(1, min(limit, 500))]
    reachable = None
    if refresh:
        # 封板修复 A-2：原来逐个串行问上游（10 个 × ~0.6 s ≈ 6–7 s）→ 并行；REFRESH_TTL_S 内问过的不再问
        now = time.monotonic()
        pending = [i for i, r in enumerate(recs) if r.get("status") not in TERMINAL
                   and now - _refreshed_at.get(str(r.get("id")), -1e9) > REFRESH_TTL_S][:10]
        if not pending and any(r.get("status") not in TERMINAL for r in recs):
            reachable = _last_reachable[0]
        if pending:
            from concurrent.futures import ThreadPoolExecutor

            def one(i):
                try:
                    return i, _refresh(recs[i]), None
                except MailboxError as e:
                    return i, None, e
            with ThreadPoolExecutor(len(pending)) as ex:
                results = list(ex.map(one, pending))
            for i, new, err in results:
                if new is not None:
                    recs[i] = new
                    reachable = True if reachable is None else reachable
                    _refreshed_at[str(new.get("id"))] = time.monotonic()
                elif err.code is None:
                    reachable = False
            _last_reachable[0] = reachable
    out = {"tasks": recs, "reachable": reachable}
    if reachable is False:
        out["hint"] = HINT
    return out


@router.get("/health")
def health():
    try:
        return {"reachable": True, "upstream": MAILBOX_URL, "health": _call("GET", "/health", timeout=3.0)}
    except MailboxError as e:
        return {"reachable": False, "upstream": MAILBOX_URL, "error": str(e), "hint": HINT}


# ---------------------------------------------------------------- 交付物（/files/<id>/…，原样）

def _open_raw(path: str, timeout: float = TIMEOUT_S):
    try:
        return urllib.request.urlopen(urllib.request.Request(MAILBOX_URL + path), timeout=timeout)
    except urllib.error.HTTPError as e:
        raise MailboxError(f"Qwen 信箱返回 {e.code}：{e.reason}", e.code) from e
    except (urllib.error.URLError, OSError) as e:
        raise MailboxError(f"Qwen 信箱不可达（{MAILBOX_URL}）：{e}") from e


def _files_path(task_id: str, rel: str = "") -> str:
    parts = [p for p in rel.replace("\\", "/").split("/") if p]
    if any(p in (".", "..") for p in parts):
        raise HTTPException(400, "路径不合法")
    return f"/files/{quote(task_id, safe='')}/" + "/".join(quote(p, safe="") for p in parts)


@router.get("/tasks/{task_id}/files")
def list_files(task_id: str):
    """交付物清单：上游 GET /files/<id>/ 的 JSON 原样"""
    try:
        return _call("GET", _files_path(task_id))
    except MailboxError as e:
        raise _http_error(e)


@router.get("/tasks/{task_id}/files/{rel:path}")
def get_file(task_id: str, rel: str):
    """交付物原样字节（流式转发，Content-Type 透传）"""
    try:
        r = _open_raw(_files_path(task_id, rel))
    except MailboxError as e:
        raise _http_error(e)
    keep = ("content-type", "content-length", "last-modified", "etag", "content-disposition")
    headers = {k: v for k, v in r.headers.items() if k.lower() in keep}

    def body():
        with r:
            while chunk := r.read(1 << 16):
                yield chunk
    return StreamingResponse(body(), status_code=r.status, headers=headers)


def fetch_bytes(task_id: str, rel: str) -> bytes:
    with _open_raw(_files_path(task_id, rel), timeout=30.0) as r:
        return r.read()


# ---------------------------------------------------------------- kind=script：取回 → 校验 →（返修）→ 项目方确认导入
# 全程不读、不改剧本文字：文件原样落盘；校验器 / 导入器是现成工具（子进程）；返修文字 = 校验器输出原样。

SCRIPT_FILE = "script.md"


def _ctx_for(rec: dict, project: str | None):
    slug = project or (rec.get("meta") or {}).get("project")
    if not slug:
        raise HTTPException(400, "不知道导入到哪个项目：任务 meta.project 为空，请在请求里带 project")
    try:
        return PJC.get_project(slug)
    except KeyError:
        raise HTTPException(404, f"没有这个项目：{slug}")


def _script_rec(task_id: str) -> dict:
    rec = load_index().get(task_id)
    if not rec:
        raise HTTPException(404, f"本地索引里没有这个任务：{task_id}")
    if (rec.get("meta") or {}).get("kind") != "script":
        raise HTTPException(409, "只有 kind=script 的任务有剧本交付物")
    return rec


def run_validator(path: Path, ctx) -> dict:
    """tools/validate_qwen_script.py --json（子进程）→ {ok, exit_code, blocking, warnings, repair_text, report}"""
    p = subprocess.run([sys.executable, str(PJC.REPO / "tools" / "validate_qwen_script.py"), str(path), "--json"],
                       cwd=PJC.REPO, env=ctx.env(), capture_output=True, timeout=120)
    out, err = p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")
    try:
        rep = json.loads(out) if out.strip() else None
    except ValueError:
        rep = None
    repairs: list[str] = []
    for ep in (rep or {}).get("episodes", []):
        repairs += [ep["repair"]] if ep.get("repair") else []
        repairs += [s["repair"] for s in ep.get("shots", []) if s.get("repair")]
    repair_text = "\n\n".join(repairs) if repairs else (err.strip() if p.returncode else "")
    return {"ok": p.returncode == 0, "exit_code": p.returncode,
            "blocking": (rep or {}).get("blocking"), "warnings": (rep or {}).get("warnings"),
            "episodes_found": (rep or {}).get("episodes_found", 0),
            "repair_text": repair_text, "report": rep, "stderr": err[-2000:] if p.returncode else ""}


class ScriptBody(BaseModel):
    project: str | None = None


@router.post("/tasks/{task_id}/script/fetch")
def script_fetch(task_id: str, body: ScriptBody | None = None):
    """取回 /files/<id>/script.md 原样落盘到 projects/<slug>/data/qwen/<id>/script.md，再跑校验器。不导入。"""
    rec = _script_rec(task_id)
    ctx = _ctx_for(rec, (body or ScriptBody()).project)
    try:
        data = fetch_bytes(task_id, SCRIPT_FILE)
    except MailboxError as e:
        raise _http_error(e)
    dest = ctx.data_dir / "qwen" / task_id / SCRIPT_FILE
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    v = run_validator(dest, ctx)
    info = {"project": ctx.slug, "path": ctx.rel(dest), "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data), "fetched_at": _now(), "validation": {k: v[k] for k in v if k != "report"}}
    _append({**rec, "script": info, "updated_at": _now()})
    return {**info, "report": v["report"]}


@router.post("/tasks/{task_id}/script/repair", status_code=201)
def script_repair(task_id: str):
    """校验不过：把校验器的返修文字原样作为新任务（kind=script，meta.parent=原任务 id）发回 Qwen"""
    rec = _script_rec(task_id)
    v = (rec.get("script") or {}).get("validation") or {}
    if not v:
        raise HTTPException(409, "还没取回并校验剧本（先 POST …/script/fetch）")
    if v.get("ok"):
        raise HTTPException(409, "校验已通过，不需要返修")
    if not v.get("repair_text"):
        raise HTTPException(409, "校验器没有给出返修文字")
    meta = {**(rec.get("meta") or {}), "kind": "script", "parent": task_id}
    new = submit(v["repair_text"], meta)
    _append({**rec, "repair_task": new["id"], "updated_at": _now()})
    return new


class ImportBody(BaseModel):
    confirm: bool = False            # 项目方在画布上点「导入」= True；agent 不得调用
    by: str = ""          # 封板修复 P1：不给默认值，必须显式 by=owner
    project: str | None = None


@router.post("/tasks/{task_id}/script/import")
def script_import(task_id: str, body: ImportBody):
    """项目方确认后导入：重新校验（必须通过、且文件与取回时同一 sha256）→ tools/import_script.py 原样导入到
    projects/<slug>/data/import/script_v2.json，并把项目的「剧本和镜头」指向这份文件。默认项目（为他而骚）不接受。"""
    if not body.confirm or body.by != "owner":
        raise HTTPException(403, "导入须由项目方在画布上确认（confirm=true, by=owner）")
    rec = _script_rec(task_id)
    info = rec.get("script") or {}
    if not info:
        raise HTTPException(409, "还没取回并校验剧本（先 POST …/script/fetch）")
    ctx = _ctx_for(rec, body.project or info.get("project"))
    if ctx.is_default:
        raise HTTPException(409, "默认项目《为他而骚》的剧本由现有流程维护，不从 Qwen 信箱导入")
    src = ctx.root / info["path"]
    if not src.is_file() or hashlib.sha256(src.read_bytes()).hexdigest() != info.get("sha256"):
        raise HTTPException(409, "本地剧本文件与取回时不一致，请重新取回")
    v = run_validator(src, ctx)
    if not v["ok"]:
        raise HTTPException(409, f"校验未通过（block {v['blocking']}），不能导入；请发回 Qwen 返修")
    from ns_api import wizard
    image_doc = wizard.script_files(ctx).get("image_doc")
    if image_doc is None:                    # 导入器要一个 image 文档路径：没有就给空文件（= 不合并）
        image_doc = ctx.data_dir / "qwen" / "_empty_image_doc.md"
        image_doc.parent.mkdir(parents=True, exist_ok=True)
        image_doc.write_text("", encoding="utf-8")
    p = subprocess.run([sys.executable, str(PJC.REPO / "tools" / "import_script.py"), "--script", str(src),
                        "--image-doc", str(image_doc), "-o", str(ctx.script_json)],
                       cwd=PJC.REPO, env=ctx.env(), capture_output=True, timeout=300)
    log = (p.stdout + p.stderr).decode("utf-8", "replace")
    if p.returncode != 0:
        raise HTTPException(500, f"导入失败（退出码 {p.returncode}）：{log[-800:]}")
    s = ctx.settings()
    s.setdefault("script_files", {})["script"] = info["path"]
    ctx.save_settings(s)
    imp = {"at": _now(), "by": body.by, "out": ctx.rel(ctx.script_json), "sha256": info["sha256"], "log": log[-2000:]}
    _append({**rec, "imported": imp, "updated_at": _now()})
    return {"ok": True, "project": ctx.slug, **imp}
