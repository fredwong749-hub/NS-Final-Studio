"""成人镜“本人触发”入口（L-128 不变项 + L-210，项目方 11-07 01:1x 回“e”）。

L-128：成人镜只在项目方本人于界面上点了之后才出；系统 / agent 永不自动派。
L-210：点了之后可在 gpu33 / gpu36 出图（不限笔记本）。
以前 producer 只读 data/producer[/runs/<run>]/owner_triggers.json {"objects": [...]}，网页没有任何地方写它 → 项目方点不了。

POST /api/owner/adult-trigger {run?, objects: [...], episode?, note?}
  · 只认登录的项目方本人（auth.user_of → role=owner）；没登录 / 查看令牌 / agent 令牌 → 403，什么都不写。
  · objects 可写对象 id（first:ep02-S5 / last:… / video:…）或镜号（ep02-S5 = 这一镜首帧 + 尾帧 + 视频）；episode=N = 这一集全部成人镜。
    只收这部剧真的是成人镜的对象（剧本 adult=true，或出图前检查因成人画面资产卡住的镜）；别的一律 400，不写。
  · 先追加审计 data/pipeline/owner_adult_triggers.jsonl（谁、何时、哪部剧、哪些对象、备注），再原子写触发清单（临时文件 + os.replace）。
  · 触发清单写在 producer 读的位置（runs.producer_dir(run)/owner_triggers.json）；服务器上的 producer 读它自己机器上的那份——
    经现成的 resident_sync.push_control（控制小文件按对象合并推两台；control_files 已含每部在产剧的这份清单）送过去：
    resident 常驻每拍自动推，这里另起后台线程立刻推一次（NS_ADULT_TRIGGER_PUSH=off 关）。服务器副本不回拉（merge_pull SKIP_NAMES）。
GET /api/owner/adult-trigger?run=  按集列出成人镜：镜号、秒数、状态（waiting 等你点 / triggered 已点排队中 / rendering 正在出 / done 已出好）。
  只回文字：不回图、不回提示词、不回判定原因。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

REPO = Path(__file__).resolve().parents[3]
router = APIRouter(tags=["owner-adult-trigger"])
_lock = threading.Lock()
KINDS = ("first", "last", "video")
SID = re.compile(r"^ep(\d{2})-S(\d+)$")
DONE = ("passed", "best_effort")
STATE_WORD = {"waiting": "等你点", "triggered": "已点，排队中", "rendering": "正在出", "done": "已出好"}
ASSET_ADULT_MARK = "成人画面资产"        # producer.render 出图前检查因成人画面资产拦下时的错误原文（只用来认镜，不回给界面）


def audit_path(root: Path | None = None) -> Path:
    return Path(root or REPO) / "data" / "pipeline" / "owner_adult_triggers.jsonl"


# ------------------------------------------------------------------ 路径（转调 runs.py 唯一入口，测试可换）
def _runs_mod():
    from ns_api import run_paths as RP  # noqa: PLC0415
    return RP._runs()


def known_runs(root: Path | None = None) -> list[str]:
    m = _runs_mod()
    r = Path(root or REPO)
    out = [m.current_run(r)]
    try:
        out += [k for k in m.list_runs(r, status=None) if k not in out]
    except Exception:  # noqa: BLE001  # arch-ok: 剧目表读不到 = 只认当前剧
        pass
    return out


def producer_dir(run: str, root: Path | None = None) -> Path:
    return Path(_runs_mod().producer_dir(run, Path(root or REPO)))


def script_path(run: str, root: Path | None = None) -> Path:
    return Path(_runs_mod().script_path(run, Path(root or REPO)))


def triggers_path(run: str, root: Path | None = None) -> Path:
    return producer_dir(run, root) / "owner_triggers.json"


def _jl(p: Path, d):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):   # arch-ok: 读不到 = 默认值（触发清单读不到 = 一个都没触发，失败关闭）
        return d


def _atomic_json(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=p.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False, indent=1))
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


# ------------------------------------------------------------------ 读：哪些是成人镜、现在什么状态
def adult_shots(run: str, root: Path | None = None) -> dict[str, dict]:
    """{镜号: {ep, index, seconds}}：剧本 adult=true 的镜 + 登记表里因成人画面资产被出图前检查拦下的镜（与 producer 两道闸同口径）"""
    out: dict[str, dict] = {}
    sc = _jl(script_path(run, root), {}) or {}
    for E in sc.get("episodes") or []:
        for S in E.get("shots") or []:
            try:
                sid = f"ep{int(S.get('episode') or E.get('number')):02d}-S{int(S.get('index'))}"
            except (TypeError, ValueError):
                continue
            if S.get("adult"):
                out[sid] = {"ep": int(E.get("number") or 0), "index": int(S.get("index")), "seconds": S.get("duration")}
    reg = _jl(producer_dir(run, root) / "registry.json", {}) or {}
    for E in reg.get("episodes") or []:
        for S in E.get("shots") or []:
            sid = str(S.get("shot") or "")
            if sid in out or not SID.match(sid):
                continue
            if any(ASSET_ADULT_MARK in str((o or {}).get("last_error") or "") + str((o or {}).get("reason") or "")
                   for o in (S.get("objects") or {}).values()):
                m = SID.match(sid)
                out[sid] = {"ep": int(m.group(1)), "index": int(m.group(2)), "seconds": None}
    return out


def triggered(run: str, root: Path | None = None) -> set[str]:
    d = _jl(triggers_path(run, root), {})
    return set((d or {}).get("objects") or []) if isinstance(d, dict) else set()


def _reg_objects(run: str, root: Path | None = None) -> dict[str, dict]:
    reg = _jl(producer_dir(run, root) / "registry.json", {}) or {}
    out = {}
    for E in reg.get("episodes") or []:
        for S in E.get("shots") or []:
            out[str(S.get("shot") or "")] = S.get("objects") or {}
    return out


def shot_state(sid: str, trig: set[str], objs: dict) -> str:
    if not ({f"first:{sid}", f"last:{sid}"} & trig):
        return "waiting"
    st = {k: str((objs.get(k) or {}).get("status") or "") for k in KINDS}
    if "running" in st.values():
        return "rendering"
    frames_ok = st["first"] in DONE and (st["last"] in DONE or bool((objs.get("last") or {}).get("na")))
    if frames_ok and st["video"] in DONE:
        return "done"
    return "triggered"


def listing(run: str, root: Path | None = None) -> dict:
    shots = adult_shots(run, root)
    trig = triggered(run, root)
    objs = _reg_objects(run, root)
    eps: dict[int, list] = {}
    for sid, m in sorted(shots.items(), key=lambda kv: (kv[1]["ep"], kv[1]["index"])):
        s = shot_state(sid, trig, objs.get(sid) or {})
        eps.setdefault(m["ep"], []).append({"shot": sid, "index": m["index"], "seconds": m["seconds"], "state": s, "state_word": STATE_WORD[s]})
    out = []
    for ep, rows in sorted(eps.items()):
        n = {k: sum(1 for r in rows if r["state"] == k) for k in STATE_WORD}
        out.append({"ep": ep, "shots": rows, "counts": n, "waiting": n["waiting"]})
    return {"run": run, "episodes": out, "waiting": sum(e["waiting"] for e in out)}


# ------------------------------------------------------------------ 写
def expand(run: str, objects: list[str], episode: int | None, root: Path | None = None) -> tuple[list[str], list[str]]:
    """→ (要触发的对象 id, 不认的条目)。镜号 = 首帧 + 尾帧 + 视频；只收成人镜"""
    shots = adult_shots(run, root)
    want, bad = [], []
    if episode is not None:
        for sid, m in sorted(shots.items(), key=lambda kv: (kv[1]["ep"], kv[1]["index"])):
            if m["ep"] == int(episode):
                want += [f"{k}:{sid}" for k in KINDS]
    for raw in objects or []:
        x = str(raw or "").strip()
        kind, _, sid = x.partition(":") if ":" in x else ("", "", x)
        if not SID.match(sid) or sid not in shots or (kind and kind not in KINDS):
            bad.append(x)
            continue
        want += [f"{kind}:{sid}"] if kind else [f"{k}:{sid}" for k in KINDS]
    return list(dict.fromkeys(want)), bad


def apply(run: str, objs: list[str], by: str, note: str, root: Path | None = None, via: str = "web") -> dict:
    """先审计、再原子写触发清单（只加不减）。→ {added, total}"""
    with _lock:
        p = triggers_path(run, root)
        cur = _jl(p, {})
        cur = cur if isinstance(cur, dict) else {}
        have = list(cur.get("objects") or [])
        added = [o for o in objs if o not in have]
        at = _now()
        rec = {"at": at, "by": by, "run": run, "objects": objs, "added": added, "note": note, "via": via, "rule": "L-128/L-210",
               "status": "requested"}
        ap = audit_path(root)
        ap.parent.mkdir(parents=True, exist_ok=True)
        with ap.open("a", encoding="utf-8") as f:            # 审计先落盘：写清单失败也留得下“谁点了什么”
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        if added:
            items = dict(cur.get("items") or {})
            for o in added:
                items[o] = {"by": by, "at": at, "note": note}
            doc = {**cur, "objects": have + added, "items": items, "updated_at": at, "updated_by": by,
                   "_doc": "L-128 / L-210：只有项目方本人在网页点“出这一镜 / 出这一集的成人镜”才写；系统 / agent 不写。producer 只读 objects"}
            try:
                _atomic_json(p, doc)
            except BaseException as e:   # 复审 11-07：写清单失败要在审计里留失败标记，不能只剩一行“requested”像是成了
                with ap.open("a", encoding="utf-8") as f:
                    f.write(json.dumps({"at": _now(), "by": by, "run": run, "objects": objs, "status": "write_failed",
                                        "error": repr(e)[:200]}, ensure_ascii=False) + chr(10))
                raise
        return {"added": added, "total": len(have) + len(added)}


def _hosts(root: Path | None = None) -> list[str]:
    d = _jl(Path(root or REPO) / "config" / "factory" / "hosts.json", {}) or {}
    return [h for h, v in (d.get("hosts") or {}).items() if isinstance(v, dict) and v.get("ssh") and v.get("owner_controlled") is True]


def push_now(root: Path | None = None) -> None:
    """后台立刻经 resident_sync.push_control 推两台（常驻每拍也会推；这里只是不让项目方多等一拍）。失败只记日志，不影响已收下的触发"""
    if os.environ.get("NS_ADULT_TRIGGER_PUSH", "on").lower() in ("off", "0", "false"):
        return
    r = Path(root or REPO)

    def run():
        for h in _hosts(r):
            try:
                subprocess.run([sys.executable, str(r / "tools/autopilot/resident_sync.py"), "push_control", h], cwd=str(r),
                               capture_output=True, timeout=300, env={**os.environ, "PYTHONUTF8": "1"})
            except Exception:  # noqa: BLE001  # arch-ok: 立即推失败 = 等常驻下一拍推（触发清单已落盘）
                pass
    threading.Thread(target=run, name="adult_trigger_push", daemon=True).start()


# ------------------------------------------------------------------ 路由
class Trigger(BaseModel):
    run: str | None = None
    objects: list[str] = Field(default_factory=list)
    episode: int | None = None
    note: str = ""


def _run_of(run: str | None) -> str:
    rs = known_runs()
    r = (run or "").strip() or rs[0]
    if r not in rs:
        raise HTTPException(404, "没有这部剧")
    return r


@router.get("/api/owner/adult-trigger")
def get_adult(request: Request, run: str | None = None):
    from ns_api import auth  # noqa: PLC0415
    u = auth.user_of(request)
    out = listing(_run_of(run))
    out["can_trigger"] = bool(u and u.get("role") == "owner")
    return out


@router.post("/api/owner/adult-trigger")
def post_adult(body: Trigger, request: Request):
    from ns_api import auth  # noqa: PLC0415
    u = auth.user_of(request)
    if not u or u.get("role") != "owner":         # 登录即本人；查看令牌 / agent / 没登录一律不收（L-128：系统不自动派成人镜）
        raise HTTPException(403, "只有登录的项目方本人能点出成人镜")
    run = _run_of(body.run)
    objs, bad = expand(run, body.objects, body.episode)
    if bad:
        raise HTTPException(400, "这些不是这部剧的成人镜：" + "、".join(bad[:10]))
    if not objs:
        raise HTTPException(400, "没有可以出的成人镜")
    res = apply(run, objs, u["name"], (body.note or "").strip()[:500])
    if res["added"]:
        push_now()
    return {"ok": True, "run": run, **res, "listing": listing(run)}
