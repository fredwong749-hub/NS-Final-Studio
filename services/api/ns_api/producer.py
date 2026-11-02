"""制作监督（PRODUCER）的接口：只读登记表 + 项目方暂停 / 继续 + 闸门一键确认（总调度 11-01，规则 K-OPS-A01）。

项目方原话：“自动执行对应制作,人类不应该点,坏了,系统自动做”。制作由常驻服务 tools/autopilot/producer.py 推进；
本路由不派活，只读它写的 data/producer/registry.json（与 GPUVIEW /api/render-tasks 同一份）和心跳。

  GET  /api/producer/status[?run=series10_v1][&ep=N]   登记表（每集 / 每镜 / 每个对象的状态、在等什么、在哪做、第几次、自修原因）
                                                       + heartbeat_age_s（>90 s 视为服务没在跑）+ 最近 30 条日志
  POST /api/producer/pause   {by?, note?}   项目方暂停（不再派新活；在跑的跑完）
  POST /api/producer/resume  {by?}
  POST /api/producer/gate    {id, by?}      项目方在闸门卡片上一键确认“已处理”（真正的处理在资产中心等原处点；这里只记已看）
"""
from __future__ import annotations

from ns_api import run_paths as _RP   # K-OPS-F24：按当前剧取路径（V1 已归档，不在网页显示）
import json
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

REPO = Path(__file__).resolve().parents[3]
def _pd() -> Path:
    """当前剧的 producer 目录（K-OPS-F24：legacy = data/producer，V2 = data/producer/runs/series10_v2）"""
    return _RP.producer_dir(REPO)


router = APIRouter(tags=["producer"])


def _jl(p: Path, d=None):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return d


def _js(p: Path, d) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".api.tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


def _log(ev: str, **kw) -> None:
    _pd().mkdir(parents=True, exist_ok=True)
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "t": round(time.time(), 2), "ev": ev, "src": "api", **kw}
    with (_pd() / "log.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _tail(n: int = 30) -> list[dict]:
    p = _pd() / "log.jsonl"
    try:
        with p.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 64 * 1024))
            lines = f.read().decode("utf-8", "replace").splitlines()[1:]
    except OSError:
        return []
    out = []
    for ln in lines[-n:]:
        try:
            d = json.loads(ln)
        except ValueError:
            continue
        d.pop("comfy_tag", None)
        d.pop("tb", None)
        out.append(d)
    return out


@router.get("/api/producer/status")
def status(run: str | None = None, ep: int | None = None):
    reg = _jl(_pd() / "registry.json", {}) or {}
    hb = _jl(_pd() / "heartbeat.json", {}) or {}
    age = round(time.time() - float(hb.get("t") or 0), 1) if hb.get("t") else None
    if run and reg.get("run") and reg["run"] != run:
        return {"run": run, "active": False, "note": f"制作监督现在管的是 {reg['run']}，不是这一季", "heartbeat_age_s": age}
    if ep is not None:
        reg = {**reg, "episodes": [e for e in reg.get("episodes") or [] if int(e.get("ep") or 0) == int(ep)]}
    ctrl = _jl(_pd() / "control.json", {}) or {}
    alive = age is not None and age < 90
    return {**reg, "active": bool(reg) and alive, "service_alive": alive, "heartbeat_age_s": age,
            "paused": bool(ctrl.get("paused")), "paused_by": ctrl.get("paused_by"), "log": _tail(30)}


class PauseBody(BaseModel):
    by: str = "owner"
    note: str = ""
    kind: str = "owner"          # K-OPS-E08：界面点的暂停 = 项目方显式暂停（不自动恢复，超 180 s 报警）；line_switch / restart / deploy = 运维暂停（≤180 s 到点恢复）
    expires_s: float = 0


@router.post("/api/producer/pause")
def pause(body: PauseBody | None = None):
    b = body or PauseBody()
    c = _jl(_pd() / "control.json", {}) or {}
    kind = b.kind if b.kind in ("line_switch", "restart", "deploy", "master", "owner") else "owner"
    ops = kind in ("line_switch", "restart", "deploy")
    exp = time.time() + (min(float(b.expires_s or 180), 180) if ops else float(b.expires_s or 180))
    c.update(paused=True, paused_by=b.by or "owner", paused_at=time.strftime("%Y-%m-%dT%H:%M:%S"), note=b.note or None,
             reason_kind=kind, expires_at=time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(exp)), overdue_alert_t=None)
    _js(_pd() / "control.json", c)
    _log("pause", by=b.by, note=b.note)
    return {"paused": True, "note": "已暂停：不再派新活，在跑的跑完"}


@router.post("/api/producer/resume")
def resume(body: PauseBody | None = None):
    b = body or PauseBody()
    c = _jl(_pd() / "control.json", {}) or {}
    c.update(paused=False, paused_by=None, paused_at=None, note=None, reason_kind=None, expires_at=None, overdue_alert_t=None)
    _js(_pd() / "control.json", c)
    _log("resume", by=b.by)
    return {"paused": False, "note": "已继续自动制作"}


class GateBody(BaseModel):
    id: str
    by: str = "owner"


@router.post("/api/producer/gate")
def gate_seen(body: GateBody):
    gates = _jl(_pd() / "gates.json", []) or []
    g = next((x for x in gates if x.get("id") == body.id), None)
    if g is None:
        raise HTTPException(404, f"没有这个闸门：{body.id}")
    g.update(status="seen", seen_by=body.by, seen_at=time.strftime("%Y-%m-%dT%H:%M:%S"))
    _js(_pd() / "gates.json", gates)
    _log("gate_seen", id=body.id, by=body.by)
    return g
