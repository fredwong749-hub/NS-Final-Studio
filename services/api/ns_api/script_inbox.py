"""
剧本导入收件箱（项目方 2026-10-30：“你在画布点导入给我 link 和提醒我”）。

候选 = 等待项目方采纳的剧本稿（Qwen 写，系统只收发）：
  - data/staging_v3/*.md（v3 原稿、逐镜格式返修后的 v3.1、合并稿 merged/*.md）
  - Qwen 信箱 kind=script 交付物（projects/*/data/qwen/<id>/script.md、data/qwen/<id>/script.md）
对每个候选只做**格式**校验（tools/validate_qwen_script.py，按 sha256 缓存），不读不改内容。
导入只在项目方在画布勾选确认后执行：备份当前 data/import/script_v2.json → tools/import_script.py 原样导入
→ 记 data/import/import_log.jsonl；API 发现 script_v2.json 变化后自动换上新剧本。

接口（前缀 /api/script-inbox）：
  GET  /                 候选列表 + 缓存的校验摘要 + 当前已导入剧本
  POST /validate {path}  （重新）校验一个候选，返回摘要
  POST /import   {path, sha256, by:"owner", confirm:true, accept_blocking?, note?}
"""
from __future__ import annotations

from ns_api import run_paths as _RP   # K-OPS-F24：渲染根目录按当前剧（V1 已归档，不在网页显示）
import hashlib
import json
import re
import shutil
import subprocess
import sys
import threading
import time

from ns_api import clock as _clock   # L-212 #10：页面时间一律 JST
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

REPO = Path(__file__).resolve().parents[3]
DATA = REPO / "data"
IMPORT_JSON = DATA / "import" / "script_v2.json"
LOG = DATA / "import" / "import_log.jsonl"
CACHE = DATA / "import" / "script_inbox_cache.json"
# v3_changes.md = 改动说明（不是剧本）
SKIP_NAMES = ("v3_changes.md",)
MAINLINE_CFG = REPO / "config" / "script_mainline.json"


def mainline_paths() -> set[str]:
    """主线候选 = 现行导入来源（K-OPS-Q31，CLEANUP 11-01：从 data/import/script_v2.json 的 sources 自动推导，导入后不用人工改）
    ∪ 项目方在 config/script_mainline.json 指定的（项目设置页可改，仍然生效；推导不出来时就只剩它）"""
    try:
        cfg = set(json.loads(MAINLINE_CFG.read_text(encoding="utf-8")).get("mainline", []))
    except (OSError, ValueError):
        cfg = set()
    try:
        from ns_api import import_sources as IS  # noqa: PLC0415
        derived = set(IS.mainline(IS.IMPORT_JSON, REPO))
    except Exception:  # noqa: BLE001 - 推导失败回退配置
        derived = set()
    return derived | cfg

router = APIRouter(prefix="/api/script-inbox")
_lock = threading.Lock()


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _rel(p: Path) -> str:
    return p.resolve().relative_to(REPO).as_posix()


def candidates() -> list[Path]:
    pats = [DATA / "staging_input", DATA / "staging_v3", DATA / "staging_v3" / "merged"]  # staging_input = 剧本输入页草稿
    out = [p for d in pats if d.is_dir() for p in sorted(d.glob("*.md")) if p.name not in SKIP_NAMES]
    out += sorted(REPO.glob("projects/*/data/qwen/*/script.md")) + sorted(DATA.glob("qwen/*/script.md"))
    out += sorted(DATA.glob("script_chat/*/script.md"))  # T57 剧本创作对话框（fredw-c8）的定稿
    return out


def _allowed(path: str) -> Path:
    p = (REPO / path).resolve()
    if p not in [c.resolve() for c in candidates()]:
        raise HTTPException(404, f"不是导入候选：{path}")
    return p


def _load_cache() -> dict:
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def validate(p: Path) -> dict:
    """格式校验摘要（按 sha256 缓存）：blocking / warnings / 按规则计数 / 集数"""
    sha = _sha(p)
    with _lock:
        cache = _load_cache()
        if sha in cache:
            return cache[sha]
    r = subprocess.run([sys.executable, str(REPO / "tools" / "validate_qwen_script.py"), str(p), "--json"],
                       capture_output=True, cwd=REPO, timeout=900,
                       env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"})
    try:
        d = json.loads(r.stdout.decode("utf-8"))
        top = sorted(d.get("counts", {}).items(), key=lambda kv: -kv[1])
        summary = {"sha256": sha, "ok": d.get("blocking", 1) == 0, "blocking": d.get("blocking"),
                   "warnings": d.get("warnings"), "episodes": d.get("episodes_found"),
                   "top_rules": [{"rule": k, "count": v} for k, v in top[:12]],
                   "validated_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    except (ValueError, AttributeError):
        # 校验器自己出错（崩溃 / 超时外的异常输出）：不写缓存——否则同一文件永远拿到这条错误，“重新校验”也救不回（封板修复）
        return {"sha256": sha, "ok": False, "error": (r.stderr or b"").decode("utf-8", "replace")[-800:]
                or f"校验器退出码 {r.returncode}，没有输出"}
    with _lock:
        cache = _load_cache()
        cache[sha] = summary
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    return summary


def _current() -> dict | None:
    rows = []
    if LOG.exists():
        for x in LOG.read_text(encoding="utf-8").splitlines():
            try:                               # 封板修复：日志里一行坏 JSON（写到一半）曾让整个收件箱 GET 500
                rows.append(json.loads(x))
            except ValueError:
                continue
    last = rows[-1] if rows else None
    return {"path": _rel(IMPORT_JSON) if IMPORT_JSON.exists() else None,
            "mtime": _clock.epoch_jst(IMPORT_JSON.stat().st_mtime, "%Y-%m-%d %H:%M")
            if IMPORT_JSON.exists() else None,
            "last_import": last}


def _session_meta(p: Path) -> dict | None:
    """data/script_chat/<会话>/script.md → {id, title, episodes:[集号], created_at}；读不到 → None"""
    try:
        d = json.loads((p.parent / "session.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    eps = d.get("episodes") if isinstance(d, dict) else None
    nums = sorted({int(k) for k in (eps.keys() if isinstance(eps, dict) else []) if str(k).isdigit()})
    return {"id": d.get("id") or p.parent.name, "title": d.get("title") or None, "episodes": nums,
            "created_at": d.get("created_at")}


@router.get("")
@router.get("/")
def list_inbox():
    cache = _load_cache()
    items = []
    for p in candidates():
        sha = _sha(p)
        items.append({"path": _rel(p), "name": p.name, "size": p.stat().st_size, "sha256": sha,
                      "mtime": _clock.epoch_jst(p.stat().st_mtime, "%Y-%m-%d %H:%M"),
                      "source": "qwen-mailbox" if "/qwen/" in _rel(p)
                      else "script-chat" if "/script_chat/" in _rel(p)
                      else "input" if "/staging_input/" in _rel(p) else "staging",
                      "validation": cache.get(sha)})
        # fredw-92/UXF4（流程 d / 审查 #42）：剧本创作会话的稿都叫 script.md——附上会话标题 / 集号 / 创建时间（只读 session.json 元数据）
        if items[-1]["source"] == "script-chat":
            items[-1]["session"] = _session_meta(p)
    # 主线（config/script_mainline.json，项目方指定）排最前、标 mainline；同类按修改时间新→旧
    main_set = mainline_paths()
    for it in items:
        it["mainline"] = it["path"] in main_set
    main = sorted((x for x in items if x["mainline"]), key=lambda x: x["mtime"], reverse=True)
    return {"candidates": main + [x for x in items if not x["mainline"]], "current": _current()}


class PathBody(BaseModel):
    path: str


@router.post("/validate")
def post_validate(body: PathBody):
    return validate(_allowed(body.path))


@router.get("/download")
def download(path: str):
    """项目方：“qwen写完文章给我这里下载”——候选剧本原文件原样下载（中文文件名按 RFC 5987）"""
    from urllib.parse import quote
    from fastapi.responses import FileResponse
    p = _allowed(path)
    name = p.name if p.name != "script.md" else f"{p.parent.name}_script.md"
    return FileResponse(p, media_type="text/markdown; charset=utf-8",
                        headers={"Content-Disposition": f"attachment; filename=\"script.md\"; filename*=UTF-8''{quote(name)}"})


class ImportBody(BaseModel):
    path: str
    sha256: str
    by: str
    confirm: bool = False
    accept_blocking: bool = False
    note: str | None = None
    # merge（默认）= 只替换新稿里的集号，其余集保持；replace = 整份替换
    mode: str = "merge"
    # 合并的底稿（相对仓库根，例如 data/import/backups/script_v2.<时间>.json）；不给 = 导入前的当前剧本
    merge_base: str | None = None
    # 这份稿是第几版剧本（S1 按集要求 ≥ v3）；不给时：Qwen 剧本创作对话 / 信箱交付的 script.md 默认 v3，其余看文件名
    source_version: str | None = None
    # PRODUCER 系统身份（总调度 11-01：项目方选 A“导入剧本、推进阶段不再等你确认”）：by="PRODUCER" 时必须带 run 和令牌
    run: str | None = None
    token: str | None = None


def default_source_version(p: Path) -> str | None:
    """封板修复（debug_api P1）：画布导入没传 --source-version，文件名无 vN 的 Qwen script.md 会被当成 < v3"""
    rel = _rel(p)
    from ns_agent.state_timeline import VERSION_IN_NAME   # 封板修复 P2：“_rules_v2_”是规则标签，不是剧本版本
    if VERSION_IN_NAME.search(p.name):
        return None                                   # 文件名里有版本，导入工具自己读
    if "/script_chat/" in f"/{rel}" or "/qwen/" in f"/{rel}":
        return "v3"                                   # Qwen 按现行规则（rules_v2）写的稿
    return None


_import_lock = threading.Lock()

# ---- PRODUCER 系统身份（总调度 11-01 定：项目方选方案 A 授权“导入剧本、推进阶段不再等你确认”）
PRODUCER_BY = "PRODUCER"
PRODUCER_LABEL = "PRODUCER（项目方 11-01 选A授权）"
PRODUCER_TOKEN = DATA / "producer" / "import_token"        # 只有监督服务读写；关掉：data/producer/control.json auto_import=false


def _locked_takes() -> list[str]:
    """有项目方定稿（takes.json locked 非空）的镜头"""
    out = []
    rr = _RP.renders_root() if DATA == REPO / "data" else DATA / "renders"     # 测试 / 沙箱改了 DATA 就用它
    for tj in rr.glob("ep*/S*/takes.json"):
        try:
            d = json.loads(tj.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if any(v is not None for v in (d.get("locked") or {}).values()):
            out.append(f"{tj.parent.parent.name}-{tj.parent.name}")
    return out


def _producer_guard(body) -> None:
    """只给制作监督用：令牌对得上、开关开着、带 run；replace 会丢项目方定稿的工作 = 推翻旧决定，仍是项目方闸门"""
    try:
        ctrl = json.loads((DATA / "producer" / "control.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        ctrl = {}
    if ctrl.get("auto_import") is False:
        raise HTTPException(403, "自动导入已关闭（data/producer/control.json auto_import=false）")
    try:
        tok = PRODUCER_TOKEN.read_text(encoding="utf-8").strip()
    except OSError:
        tok = ""
    if not tok or body.token != tok or not body.run:
        raise HTTPException(403, "PRODUCER 系统身份只给制作监督服务用（令牌 / run 不对）")
    if body.accept_blocking:
        raise HTTPException(403, "PRODUCER 不能“仍然导入”：只在格式校验 0 阻断时导入")
    if body.mode == "replace":
        locked = _locked_takes()
        if locked and not ctrl.get("replace_gate_cleared"):
            raise HTTPException(409, f"整份替换会丢掉项目方已定稿的 {len(locked)} 镜（例 {', '.join(locked[:3])}）= 推翻旧决定，"
                                     "交项目方闸门")


@router.post("/import")
def post_import(body: ImportBody):
    if body.by == PRODUCER_BY:
        _producer_guard(body)
    elif body.by != "owner" or not body.confirm:
        raise HTTPException(403, "只有项目方在画布上勾选确认后才能导入")
    if body.mode not in ("merge", "replace"):
        raise HTTPException(422, "mode 只能是 merge（默认，只替换新稿里的集）或 replace（整份替换）")
    # 封板修复：两次导入同时进行会交错备份 / 回滚（第二次可能把第一次的结果“恢复”掉）→ 一次只导一个
    if not _import_lock.acquire(blocking=False):
        raise HTTPException(409, "另一个导入正在进行，请等它完成后再导入")
    try:
        return _do_import(body)
    finally:
        _import_lock.release()


def _do_import(body: ImportBody):
    p = _allowed(body.path)
    if _sha(p) != body.sha256:
        raise HTTPException(409, "文件在你确认之后又变了：请刷新列表再确认")
    v = validate(p)
    if not v.get("ok") and not body.accept_blocking:
        if v.get("error"):
            raise HTTPException(409, f"格式校验没跑成：{v['error'][-300:]}（可点“重新校验”，或勾选“仍然导入”）")
        raise HTTPException(409, f"还有 {v.get('blocking')} 个格式问题：需要再勾选“仍然导入”")
    if body.mode == "merge" and body.merge_base:     # 底稿不存在：导入前就说清楚（原来是子进程失败 → 500 + 回滚）
        mb = Path(body.merge_base)
        if not (mb if mb.is_absolute() else REPO / mb).is_file():
            raise HTTPException(422, f"合并底稿不存在：{body.merge_base}")
    ts = time.strftime("%Y%m%d-%H%M%S")
    backup = None
    if IMPORT_JSON.exists():
        bdir = IMPORT_JSON.parent / "backups"
        bdir.mkdir(parents=True, exist_ok=True)
        backup = bdir / f"script_v2.{ts}.json"
        k = 1
        while backup.exists():                      # 同一秒内两次导入：不覆盖上一份备份
            backup, k = bdir / f"script_v2.{ts}-{k}.json", k + 1
        shutil.copy2(IMPORT_JSON, backup)
    # 默认合并：只替换新稿里出现的集号，其余集保持当前导入（2026-10-30：单集导入曾让画布只剩 1 集）
    cmd = [sys.executable, str(REPO / "tools" / "import_script.py"), "--script", str(p)]
    sver = body.source_version or default_source_version(p)
    if sver:
        cmd += ["--source-version", sver]
    base = Path(body.merge_base) if body.merge_base else backup
    if body.mode == "merge" and base is not None:
        cmd += ["--merge-base", str(REPO / base) if not base.is_absolute() else str(base)]
    r = subprocess.run(cmd, capture_output=True, cwd=REPO, timeout=900,
                       env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"})
    out = (r.stdout or b"").decode("utf-8", "replace")[-2000:]
    err = (r.stderr or b"").decode("utf-8", "replace")[-2000:]
    if body.by == PRODUCER_BY and (not v.get("ok") or v.get("blocking")):
        raise HTTPException(409, f"PRODUCER 自动导入只在格式校验 0 阻断时进行：现在 {v.get('blocking')} 个阻断，交写作方返修")
    who = PRODUCER_LABEL if body.by == PRODUCER_BY else "owner"
    row = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "by": who, "run": body.run, "note": body.note, "path": _rel(p),
           "mode": body.mode, "merge_base": str(base) if body.mode == "merge" and base is not None else None,
           "sha256": body.sha256, "blocking": v.get("blocking"), "accept_blocking": body.accept_blocking,
           "backup": _rel(backup) if backup else None, "rc": r.returncode, "stdout": out[-500:]}
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    if body.by == PRODUCER_BY:
        try:
            from ns_api import auth as AU  # noqa: PLC0415
            AU.audit_line({"user": PRODUCER_LABEL, "role": "system/PRODUCER", "method": "POST", "path": "/api/script-inbox/import",
                           "owner_claim": False, "obj": {"run": body.run, "file": _rel(p), "mode": body.mode,
                                                         "validation": {"ok": v.get("ok"), "blocking": v.get("blocking")},
                                                         "backup": row["backup"], "rc": r.returncode},
                           "status": 200 if r.returncode == 0 else 500})
        except Exception:  # noqa: BLE001
            pass
    if r.returncode != 0:
        if backup:
            shutil.copy2(backup, IMPORT_JSON)
        raise HTTPException(500, f"导入失败（已恢复原剧本）：{err or out}")
    return {"ok": True, "stdout": out, "backup": row["backup"], "validation": v}
