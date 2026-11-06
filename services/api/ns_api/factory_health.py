"""生产健康条（UIRSI r42；总调度 11-02：总览加一条一屏看完的“生产健康条”）。

GET /api/factory/health   只读汇总，前端 8 s 轮询：
  · 5 条出图道（gpu33 卡 0/1/3、gpu36 卡 0/1）：复用 gpu_live（它已经每 4 / 12 s 读各道 ComfyUI /queue、/history，不另开连接）——
    状态（在出 / 空闲 / 连不上 / 坏卡）、利用率、排队数、最近一单耗时（history 最后一条 end - start）、同类中位耗时；
  · 2 张看图卡：笔记本 4080（本机 :8870）、gpu36（隧道 :8871，NETFIX 监管）各自 /health 的 loaded / queue（打分积压）/ served / last_error；
  · 两台服务器的阶段：data/netfix/net_status.json 的 dispatch_mode.phases（服务器自派 / 笔记本代派 / 交还中）；
  · producer 心跳：data/producer/heartbeat.json。
FACTORY 的 tools/factory/sync.py 若提供 health_status()（与本接口同结构、只读本机文件、不连机器）→ 整份用它；没有就用上面的拼法。
UIUX-LOOP-2 r6：原来钩子找的是 sync.status()——它对两台机器各跑一次 ssh（timeout 60 s × 4 次重试），返回的又不是本接口的结构，
结果一律被丢掉：每 8 s 一次轮询在请求线程里空等 ssh，隧道一抖 /api/factory/health 就 60 s+ 不回，线程池被占满后
/api/season、/api/candidates 也跟着 3–9 s。请求路径里不许连机器（gpu_live 的采集线程已经在读各道，这里只读内存 / 本机文件）。
文案全是大白话；端口等只进 tech 字段。
"""
from __future__ import annotations

import importlib.util
import json
import threading
import time

from ns_api import clock as _clock   # L-212 #10：页面时间一律 JST
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
_cache: dict = {"t": 0.0, "vqa": None, "thread": None}
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


_fs_mod: dict = {"mt": None, "fn": None}


def _factory_status() -> dict | None:
    """FACTORY 的 tools/factory/sync.py health_status()（与本接口同结构的 dict、只读本机文件）。没提供 → None（用本地拼法）。
    模块按文件改动时间只加载一次；不调 status()（那是 ssh 巡检，不是健康条的数据源）"""
    try:
        mt = FACTORY.stat().st_mtime
    except OSError:  # arch-ok: 没有 sync.py = FACTORY 没交付这个钩子，用本地拼法（接口里 source=live 写明）
        return None
    if _fs_mod["mt"] != mt:
        fn = None
        try:
            spec = importlib.util.spec_from_file_location("factory_sync", FACTORY)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)  # type: ignore[union-attr]
            fn = getattr(mod, "health_status", None)
        except Exception:  # noqa: BLE001 — FACTORY 那边加载出错就退回本地拼法
            fn = None
        _fs_mod.update(mt=mt, fn=fn if callable(fn) else None)
    fn = _fs_mod["fn"]
    if fn is None:
        return None
    try:
        out = fn()
        return out if isinstance(out, dict) and out.get("lanes") is not None else None
    except Exception:  # noqa: BLE001 — FACTORY 那边出错就退回本地拼法
        return None


def _vqa_probe_one(vid: str, label: str, url: str) -> dict:
    try:
        with urllib.request.urlopen(url + "/health", timeout=1.5) as r:
            h = json.loads(r.read())
    except Exception:  # noqa: BLE001
        h = None
    if h is None:
        return {"id": vid, "label": label, "state": "down", "queue": None, "served": None, "text": "没在运行", "tech": url}
    q = int(h.get("queue") or 0)
    err = h.get("last_error")
    state = "warn" if err and "memory" in str(err).lower() else ("busy" if q or h.get("last_job") else ("idle" if h.get("loaded") is not None else "down"))
    txt = (f"积压 {q} 张" if q else "没有积压") + (f" · 已打分 {h.get('served')}" if h.get("served") is not None else "")
    if state == "warn":
        txt += " · 最近一次显存不够"
    return {"id": vid, "label": label, "state": state, "queue": q, "served": h.get("served"), "loaded": h.get("loaded"),
            "text": txt, "tech": f"{url}；GPU {h.get('gpu')}；最近报错：{str(err)[:120] if err else '无'}"}


def _vqa_probe() -> list[dict]:
    """两张看图卡并行探（原来串行：都连不上时 1.5 s × 2 = 3 s 每次）"""
    from concurrent.futures import ThreadPoolExecutor  # noqa: PLC0415
    with ThreadPoolExecutor(max_workers=len(VQA)) as ex:
        return list(ex.map(lambda v: _vqa_probe_one(*v), VQA))


def _vqa_refresh() -> None:
    out = _vqa_probe()
    with _lock:
        _cache.update(t=time.time(), vqa=out, thread=None)


def _vqa(now: float) -> list[dict]:
    """看图卡健康：5 s 内直接用上次；过了 5 s 回上次的、后台线程去刷（stale-while-revalidate）；从没探过才同步探一次（并行，≤ 1.5 s）"""
    with _lock:
        cur, t, th = _cache["vqa"], _cache["t"], _cache.get("thread")
        if cur is not None and now - t < 5:
            return cur
        if cur is not None:
            if th is None or not th.is_alive():
                th = threading.Thread(target=_vqa_refresh, daemon=True, name="factory-vqa-probe")
                _cache["thread"] = th
                th.start()
            return cur
    out = _vqa_probe()
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
    producer = producer_of(now)
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
    return {"at": _clock.epoch_jst(now, "%H:%M:%S"), "lanes": lanes, "vqa": vq, "phases": phases,
            "producer": producer, "source": "live", "busy": busy, "total": len(lanes), "light": light}


HOSTS = ROOT / "config" / "factory" / "hosts.json"
CARD_WORD = {"busy": "出图中", "idle": "空闲", "down": "断开", "warn": "断开", "vlm": "看图卡"}


def heartbeat_age(now: float, t: float | None) -> tuple[float | None, float]:
    """心跳年龄（秒）+ 时钟差。心跳由服务器上的 producer 写、经同步到笔记本：服务器时钟比笔记本快时 now - t 会是负数
    （项目方看到“心跳 -97 秒前”）。负数按 0（刚刚）显示，差值记 clock_skew_s"""
    if t is None:
        return None, 0.0
    age = now - float(t)
    return (max(0.0, age), round(-age, 1) if age < 0 else 0.0)


def producer_of(now: float) -> dict:
    hb = _jl(HEARTBEAT, {}) or {}
    age, skew = heartbeat_age(now, hb.get("t"))
    word = "刚刚" if age is not None and age < 1 else (f"{_secs(age)}前" if age is not None else "")
    return {"state": "idle" if hb.get("paused") else ("down" if age is None or age > 600 else "busy"),
            "text": ("已暂停" if hb.get("paused") else "在跑") + (f" · 心跳 {word}" if age is not None else " · 没有心跳"),
            "inflight": hb.get("inflight"), "heartbeat_age_s": round(age, 1) if age is not None else None, "clock_skew_s": skew}


def cards_of(lanes: list[dict], vqa: list[dict], hosts: dict | None = None) -> dict:
    """显卡按 1–N 号一格一格（项目方 15:5x：“1、2、3…号显卡分别是什么情况”“坏卡隐藏……直接告诉我两张坏在底部”）：
    hosts.json 里每台机器的每张卡（出图道 + 看图卡），坏卡（broken_gpus / 读数判 faulty）不编号、只计数"""
    hosts = hosts if hosts is not None else ((_jl(HOSTS, {}) or {}).get("hosts") or {})
    by_lane = {x.get("id"): x for x in lanes}
    by_vqa = {x.get("id"): x for x in vqa}
    cards, broken = [], []
    for h, hv in hosts.items():
        bad = set(hv.get("broken_gpus") or [])
        gpus = {int(v.get("gpu")): (ln, v) for ln, v in (hv.get("lanes") or {}).items() if v.get("gpu") is not None}
        for g in sorted(set(gpus) | bad):
            ln, v = gpus.get(g, (f"{h}:{g}", {}))
            label = f"{h}·卡{g}"
            if g in bad or (by_lane.get(ln) or {}).get("state") == "faulty":
                broken.append({"host": h, "gpu": g, "label": label, "why": (v.get("note") or "坏卡（hosts.json broken_gpus）")[:80]})
                continue
            if "vlm" in (v.get("roles") or []):
                vq = by_vqa.get(h) or {}
                st = "vlm"
                text = "看图卡" + (" · 没在运行" if vq.get("state") == "down" else f" · {vq.get('text')}" if vq.get("text") else "")
                level = "warn" if vq.get("state") in ("down", "warn") else "ok"
            else:
                lane = by_lane.get(ln) or {}
                st = lane.get("state") or "down"
                text = CARD_WORD.get(st, st) + (f" · 利用率 {round(lane['util'])}%" if lane.get("util") is not None else "")
                level = "warn" if st in ("down", "warn") else "ok" if st == "busy" else "idle"
            cards.append({"lane": ln, "host": h, "gpu": g, "label": label, "state": st, "word": CARD_WORD.get(st, st), "text": text, "level": level})
    for i, c in enumerate(cards, 1):
        c["no"] = i
    return {"cards": cards, "broken": broken}


@router.get("/api/factory/health")
def factory_health():
    out = build()
    now = time.time()
    out["producer"] = {**(out.get("producer") or {}), **producer_of(now)}   # 心跳统一在这里算（修负数）
    out.update(cards_of(out.get("lanes") or [], out.get("vqa") or []))
    return out
