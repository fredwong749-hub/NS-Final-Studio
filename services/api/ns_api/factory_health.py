"""生产健康条（UIRSI r42；总调度 11-02：总览加一条一屏看完的“生产健康条”）。

GET /api/factory/health   只读汇总，前端 8 s 轮询：
  · 5 条出图道（gpu33 卡 0/1/3、gpu36 卡 0/1）：复用 gpu_live（它已经每 4 / 12 s 读各道 ComfyUI /queue、/history，不另开连接）——
    状态（在出 / 空闲 / 连不上 / 坏卡）、利用率、排队数、最近一单耗时（history 最后一条 end - start）、同类中位耗时；
  · 2 张看图卡：笔记本 4080（本机 :8870）、gpu36（隧道 :8871，NETFIX 监管）各自 /health 的 loaded / queue（打分积压）/ served / last_error；
  · 两台服务器的阶段：data/netfix/net_status.json 的 dispatch_mode.phases（服务器自派 / 笔记本代派 / 交还中）；
  · producer 心跳：data/producer/heartbeat.json。
FACTORY 以后提供 tools/factory/sync.py status：_factory_status() 读到就整份用它（同样的字段），读不到才用上面的拼法。
文案全是大白话；端口等只进 tech 字段。
"""
from __future__ import annotations

import importlib.util
import json
import threading
import time
import urllib.request
from pathlib import Path

from fastapi import APIRouter

router = APIRouter(tags=["factory-health"])
ROOT = Path(__file__).resolve().parents[3]
NETFIX = ROOT / "data" / "netfix" / "net_status.json"
HEARTBEAT = ROOT / "data" / "producer" / "heartbeat.json"
FACTORY = ROOT / "tools" / "factory" / "sync.py"
LANES = ["gpu33:0", "gpu33:1", "gpu33:3", "gpu36:0", "gpu36:1"]
VQA = [("laptop", "笔记本看图卡", "http://127.0.0.1:8870"), ("gpu36", "gpu36 看图卡", "http://127.0.0.1:8871")]
PHASE = {"server": "服务器自派", "laptop": "笔记本代派", "draining": "交还中"}
RECENT_S = 60      # r43 K1：最近 60 s 出过东西也算在出
_cache: dict = {"t": 0.0, "vqa": None}
_lock = threading.Lock()


def _jl(p: Path, d=None):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return d


def _secs(s: float | None) -> str:
    if s is None:
        return "—"
    s = int(round(s))
    return f"{s} 秒" if s < 120 else f"{s // 60} 分 {s % 60} 秒"


def _factory_status() -> dict | None:
    """FACTORY 的 tools/factory/sync.py status（还没交付时返回 None）。约定：模块里有 status() → 与本接口同结构的 dict"""
    if not FACTORY.is_file():
        return None
    try:
        spec = importlib.util.spec_from_file_location("factory_sync", FACTORY)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        st = getattr(mod, "status", None)
        out = st() if callable(st) else None
        return out if isinstance(out, dict) and out.get("lanes") is not None else None
    except Exception:  # noqa: BLE001 — FACTORY 那边出错就退回本地拼法
        return None


def _vqa(now: float) -> list[dict]:
    with _lock:
        if _cache["vqa"] is not None and now - _cache["t"] < 5:
            return _cache["vqa"]
    out = []
    for vid, label, url in VQA:
        try:
            with urllib.request.urlopen(url + "/health", timeout=1.5) as r:
                h = json.loads(r.read())
        except Exception:  # noqa: BLE001
            h = None
        if h is None:
            out.append({"id": vid, "label": label, "state": "down", "queue": None, "served": None, "text": "没在运行", "tech": url})
            continue
        q = int(h.get("queue") or 0)
        err = h.get("last_error")
        state = "warn" if err and "memory" in str(err).lower() else ("busy" if q or h.get("last_job") else ("idle" if h.get("loaded") is not None else "down"))
        txt = (f"积压 {q} 张" if q else "没有积压") + (f" · 已打分 {h.get('served')}" if h.get("served") is not None else "")
        if state == "warn":
            txt += " · 最近一次显存不够"
        out.append({"id": vid, "label": label, "state": state, "queue": q, "served": h.get("served"), "loaded": h.get("loaded"),
                    "text": txt, "tech": f"{url}；GPU {h.get('gpu')}；最近报错：{str(err)[:120] if err else '无'}"})
    with _lock:
        _cache.update(t=now, vqa=out)
    return out


def _lanes(now: float) -> list[dict]:
    from ns_api import gpu_live as G  # noqa: PLC0415
    snap = G.snapshot()
    hist = G.lanes_cache()
    cards = {c.get("lane"): c for c in snap.get("cards") or [] if c.get("lane")}
    out = []
    for lane in LANES:
        c = cards.get(lane) or {}
        h = (hist.get(lane) or {}).get("history") or []
        done = [x for x in h if x.get("start") and x.get("end") and x.get("ok")]
        last_s = (done[-1]["end"] - done[-1]["start"]) if done else None
        med = None
        if done:
            ds = sorted(x["end"] - x["start"] for x in done[-12:])
            med = ds[len(ds) // 2]
        if c.get("faulty"):
            state, word = "faulty", "坏卡"
        elif c.get("state") == "offline" or (c.get("link") and c["link"].get("offline")):
            state, word = "down", "连不上"
        elif c.get("state") in ("busy", "external") or (done and now - float(done[-1]["end"]) < RECENT_S) or (c.get("hw") or {}).get("util", 0) and (c.get("hw") or {}).get("util", 0) > 30:
            # r43（OVERVIEW_REDESIGN K1）：两单之间的上传 / 后处理 / 看图也是在干活——ComfyUI 正在跑、最近 60 s 出过东西、或卡利用率 > 30% 都算在出
            r0 = (c.get("running") or [{}])[0] if c.get("running") else {}
            ag = ((r0.get("tag") or {}).get("agent") or "") if isinstance(r0, dict) else ""
            # K2：能对上我们自己的登记（ns_tag agent）就写“出图”；对不上才写“其他任务”
            state, word = "busy", ("出图" if (not r0 or ag) else "其他任务")
        elif c.get("link"):
            state, word = "warn", "暂时连不上"     # 读数断了、也看不出在干活
        elif not c:
            state, word = "down", "没有读数"
        else:
            state, word = "idle", "空闲"
        q = c.get("queue_len") or 0
        util = (c.get("hw") or {}).get("util")
        out.append({"id": lane, "label": lane.replace(":", "·卡"), "state": state, "util": util, "queue": q,
                    "last_s": round(last_s, 1) if last_s is not None else None, "median_s": round(med, 1) if med is not None else None,
                    "text": f"{word}" + (f" · 利用率 {round(util)}%" if util is not None else "") + f" · 每单 {_secs(last_s)}" + (f" · 排队 {q}" if q else ""),
                    "tech": f"同类中位 {_secs(med)}；最近 12 单"})
    return out


def build(now: float | None = None) -> dict:
    now = time.time() if now is None else now
    fs = _factory_status()
    if fs:
        return {**fs, "source": "factory"}
    ns = _jl(NETFIX, {}) or {}
    ph = ((ns.get("dispatch_mode") or {}).get("phases") or {}) if ns.get("t") and now - float(ns["t"]) < 90 else {}
    phases = [{"id": h, "label": h, "phase": ph.get(h), "text": PHASE.get(ph.get(h), "不知道（连接状态没更新）")} for h in ("gpu33", "gpu36")]
    hb = _jl(HEARTBEAT, {}) or {}
    hb_age = now - float(hb["t"]) if hb.get("t") else None
    producer = {"state": "idle" if hb.get("paused") else ("down" if hb_age is None or hb_age > 600 else "busy"),
                "text": ("已暂停" if hb.get("paused") else "在跑") + (f" · 心跳 {_secs(hb_age)}前" if hb_age is not None else " · 没有心跳"),
                "inflight": hb.get("inflight")}
    try:
        lanes = _lanes(now)
    except Exception as e:  # noqa: BLE001
        lanes = [{"id": x, "label": x.replace(":", "·卡"), "state": "down", "text": "读不到", "tech": str(e)[:120]} for x in LANES]
    vq = _vqa(now)
    busy = sum(1 for x in lanes if x.get("state") == "busy")
    down = sum(1 for x in lanes if x.get("state") == "down")
    warn = sum(1 for x in lanes if x.get("state") == "warn")
    bad_vqa = [x for x in vq if x.get("state") in ("down", "warn")]
    # 生产灯（OVERVIEW_REDESIGN §4.1）：平时安静；有道连不上 / 看图卡停了或显存不够 → 黄“生产偏慢”；全部道都停 / producer 没心跳 → 红“生产停了”
    if (down == len(lanes) and lanes) or producer["state"] == "down":
        light = {"level": "bad", "text": "生产停了"}
    elif down or warn or bad_vqa:
        light = {"level": "warn", "text": "生产偏慢"}
    else:
        light = {"level": "ok", "text": "生产正常"}
    return {"at": time.strftime("%H:%M:%S", time.localtime(now)), "lanes": lanes, "vqa": vq, "phases": phases,
            "producer": producer, "source": "live", "busy": busy, "total": len(lanes), "light": light}


@router.get("/api/factory/health")
def factory_health():
    return build()
