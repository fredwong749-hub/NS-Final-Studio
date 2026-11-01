"""实时连接状态（UIRSI r38，总调度 11-01 派；项目方 22:1x 原话：“uiux加个实时连接状态”）。

GET /api/infra/status   只读汇总，前端 5–10 s 轮询一次。
  不在请求里 ssh：服务器那一侧只读已经写好的状态文件——
    · 跳板 / 6 条隧道 / 自动重连：tools/autopilot/infra_watchdog.py 每 30 s 写的 data/qa/infra_watchdog_state.json
      （fails 每条连续失败拍数、down、rebuilds 重建记录、_relay_down / _relay_t 跳板探测、open 开着的报警）；
    · 两台服务器常驻 night / producer 心跳：tools/autopilot/resident_sync.py health（每 5 分钟经跳板一次）写的
      data/autopilot/resident_sync.json 的 <host>.health；
  r39：NETFIX 隧道监管（tools/netfix/tunnel_supervisor.py）每拍写 data/netfix/net_status.json（跳板、每台 ssh 状态、每个端口、
    重连次数、服务器同步、派单模式 dispatch_mode）；它新鲜（90 s 内）时跳板 / 连接 / 重连 / 派单都以它为准，不新鲜才退回看门狗状态。
  笔记本本机的两样（本机道 laptop:0、本机看图服务）直接探本机 127.0.0.1（不经跳板，超时 1.5 s，结果缓存 5 s）。
  端口 → 卡的对应取 infra_watchdog.TUNNELS 与 config/render_endpoints.json，不另写一份。
返回里的 text 全是给项目方看的大白话（K-UI-037：不出现接口路径、端口号）；端口等只放在 tech 字段给“技术细节”用。
"""
from __future__ import annotations

import json
import threading
import time
import urllib.request
from pathlib import Path

from fastapi import APIRouter

router = APIRouter(tags=["infra-status"])
ROOT = Path(__file__).resolve().parents[3]
WD_STATE = ROOT / "data/qa/infra_watchdog_state.json"
RESIDENT = ROOT / "data/autopilot/resident_sync.json"
NETFIX = ROOT / "data/netfix/net_status.json"   # r39：NETFIX 隧道监管（K-OPS-N06）写的状态，新鲜时优先用它
NETFIX_STALE_S = 90                               # 与 net_status._doc 一致：t 超过 90 s 没更新 = 监管进程不在
ENDPOINTS = ROOT / "config/render_endpoints.json"
VQA_CFG = ROOT / "config/vqa.json"
TICK_S = 30                      # 与 infra_watchdog.TICK_S 一致（看门狗一拍）
WD_STALE_S = 150                 # 看门狗 5 拍没写状态 = 看门狗自己停了
REBUILD_FRESH_S = 150            # 最近 150 s 内重建过 = “正在重建”
NIGHT_STALE_MIN = 20             # 与 resident_sync 的 A-RESIDENT-NIGHT 同口径
# 端口 → (服务器, 卡号)；与 infra_watchdog.TUNNELS 同序（那边只记脚本 / 主机，卡号按 tunnel*.sh 的 -L 对应）
TUNNEL_CARDS = {18188: ("gpu33", "0"), 18189: ("gpu33", "1"), 18191: ("gpu33", "3"),
                18288: ("gpu36", "0"), 18289: ("gpu36", "1"), 18290: ("gpu36", "2")}
HOST_NAME = {"gpu33": "gpu33", "gpu36": "gpu36"}   # 与界面 cardName 同口径（“gpu33·卡0”）
_cache: dict = {"t": 0.0, "local": None}
_lock = threading.Lock()


def _jl(p: Path, d=None):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return d


def _ago(s: float | None) -> str:
    if s is None:
        return "不知道多久"
    s = max(0, int(s))
    if s < 60:
        return f"{s} 秒"
    if s < 3600:
        return f"{s // 60} 分钟"
    return f"{s // 3600} 小时 {s % 3600 // 60} 分钟"


def _hm(t: float | None) -> str | None:
    return time.strftime("%H:%M:%S", time.localtime(t)) if t else None


def _probe(url: str) -> tuple[bool, float | None]:
    t0 = time.time()
    try:
        with urllib.request.urlopen(url, timeout=1.5) as r:
            r.read(256)
        return True, round((time.time() - t0) * 1000)
    except Exception:  # noqa: BLE001
        return False, None


def _local(now: float) -> list[dict]:
    with _lock:
        if _cache["local"] is not None and now - _cache["t"] < 5:
            return _cache["local"]
    ep = _jl(ENDPOINTS, {}) or {}
    lane = (ep.get("lanes") or {}).get("laptop:0") or {}
    lane_url = lane.get("url") or "http://127.0.0.1:18388"
    vqa_port = (_jl(VQA_CFG, {}) or {}).get("port") or 8870
    ok1, ms1 = _probe(f"http://127.0.0.1:{vqa_port}/health")
    if lane.get("disabled"):                 # L-100（11-02）：笔记本 4080 专做看图，本机出图道停用 → 只显示“看图卡”，不报“离线”
        out = [{"id": "look", "label": "笔记本显卡：看图卡", "ok": ok1, "ms": ms1, "role": "vqa_only",
                "text": ("看图在线" if ok1 else "看图没在运行") + "（专用看图，不出图）", "tech": f"127.0.0.1:{vqa_port}"}]
        with _lock:
            _cache.update(t=now, local=out)
        return out
    ok0, ms0 = _probe(lane_url.rstrip("/") + "/system_stats")
    out = [
        {"id": "laptop:0", "label": "笔记本显卡出图", "ok": ok0, "ms": ms0, "hold": bool(lane.get("hold")),
         "text": ("在线" if ok0 else "没在运行") + ("（暂停派活）" if lane.get("hold") else ""),
         "tech": lane_url},
        {"id": "look", "label": "笔记本看图检查", "ok": ok1, "ms": ms1,
         "text": "在线" if ok1 else "没在运行", "tech": f"127.0.0.1:{vqa_port}"},
    ]
    with _lock:
        _cache.update(t=now, local=out)
    return out


PHASE_WORD = {"laptop": "由笔记本统一派图", "draining": "正在交还给服务器", "server": "服务器自己派图"}


def _from_netfix(ns: dict, now: float) -> tuple[dict, list[dict], list[str], dict | None]:
    """NETFIX net_status.json → 跳板 / 6 条连接 / 自动重连 / 派单模式（大白话；端口只进 tech）"""
    r = ns.get("relay") or {}
    up = bool(r.get("up"))
    ds = float(r["down_since_t"]) if (not up and r.get("down_since_t")) else None
    relay = {"ok": up, "checked_at": _hm(r.get("checked_t")), "last_ok_at": _hm(r.get("last_ok_t")),
             "down_s": round(now - ds) if ds else None}
    relay["text"] = "通" if up else f"不通，已断 {_ago(relay['down_s'])}"
    hosts = ns.get("hosts") or {}
    # AUDIT 00:23 P1：NETFIX 00:0x 起按道分连接，hosts 的键是“gpu33-l0 … gpu36-l2”（server 字段 = 所属服务器），
    # 不再是主机名——按端口找它所在的那条连接（旧格式按主机名的也照样找得到）
    by_port: dict[str, tuple[str, dict]] = {}
    for hk, hv in hosts.items():
        for pk in (hv.get("ports") or {}):
            by_port[str(pk)] = (hk, hv)
    tunnels, reconnect = [], []
    for port, (host, card) in TUNNEL_CARDS.items():
        hk, h = by_port.get(str(port), (host, hosts.get(host) or {}))
        st = h.get("state") or "stopped"
        pp = (h.get("ports") or {}).get(str(port)) or {}
        busy = pp.get("why") == "busy"          # 连接通，只是卡在忙、探测超时（NETFIX 记 why=busy）：不算断
        ok = bool(pp.get("ok")) or (busy and st == "up")
        name = f"{HOST_NAME[host]}·卡{card}"
        since = float(h.get("since_t") or 0) or None
        down_s = 0 if ok else (round(now - since) if since and st != "up" else None)
        rebuilding = (not ok) and st in ("connecting", "backoff")
        if ok:
            text = "通（卡在忙）" if busy else "通"
        elif st == "relay_down" or not up:
            text = "断了（跳板断了，等跳板恢复后自动重连）"
        elif st == "up" and pp.get("why") == "remote_down":
            text = "连接通着，但这张卡的出图程序没响应"
        elif st == "connecting":
            text = (f"断了约 {_ago(down_s)}，" if down_s else "断了，") + "正在自动重连"
        elif st == "backoff":
            nt = float(h.get("next_try_t") or 0)
            text = (f"断了约 {_ago(down_s)}，" if down_s else "断了，") + (f"{_ago(nt - now)}后自动再连" if nt > now else "马上自动再连")
        elif st == "stopped":
            text = "断了，自动重连没在运行"
        else:
            text = "暂时不通，正在查"
        tunnels.append({"port": port, "host": host, "card": card, "name": name, "lane": f"{host}:{card}", "ok": ok,
                        "fails": 0 if ok else 1, "down_s": down_s or 0, "rebuilding": rebuilding,
                        "last_rebuild_at": _hm((h.get("last_restart") or {}).get("t")), "alert": False, "text": text,
                        "tech": f"本机 {port} → {host}:{pp.get('remote', '?')}（{pp.get('why', '?')}）；连接 {hk} 状态 {st}，重连 {h.get('restarts', 0)} 次"})
    port_name = {str(p): f"{HOST_NAME[hh]}·卡{cc}" for p, (hh, cc) in TUNNEL_CARDS.items()}
    bad_ports = {str(x["port"]) for x in tunnels if not x["ok"]}
    for hk, h in hosts.items():
        st = h.get("state")
        names = [port_name[str(p)] for p in (h.get("ports") or {}) if str(p) in port_name]
        # UIAUDIT P1-3（UIRSI r43）：只为“我们 6 条出图连接里真断了的”写重连行，跟连接表同一口径——
        # 端口通着就不写“正在重连”；命令通道（*-cmd*）不给项目方看；主连接 base 写“主连接”，不漏内部名
        if "cmd" in hk:
            continue
        if hk == "base":
            if st in ("connecting", "backoff", "queued", "wait_base") and bad_ports:
                reconnect.append("正在重连主连接（各条出图连接都走它）")
            continue
        if not any(str(p) in bad_ports for p in (h.get("ports") or {})):
            continue
        who = "、".join(names) or HOST_NAME.get(h.get("server") or hk, h.get("server") or hk)
        if st in ("queued", "wait_base"):
            reconnect.append(f"{who} 的连接在排队，等主连接通了再连")
        elif st == "connecting":
            reconnect.append(f"正在重连 {who} 的连接（已重连 {h.get('restarts', 0)} 次）")
        elif st == "backoff":
            nt = float(h.get("next_try_t") or 0)
            reconnect.append(f"{who} 的连接{_ago(nt - now) + '后' if nt > now else '马上'}再试一次")
        elif st == "stopped":
            reconnect.append(f"{who} 的连接没人在管（自动重连没在运行）")
    if not up:
        reconnect.insert(0, "跳板断了：先等跳板恢复，再自动重连各条连接（这时不反复重连，免得加重跳板负担）")
    dm = ns.get("dispatch_mode") or {}
    dispatch = None
    if dm:
        ph = dm.get("phases") or {}
        if dm.get("override_active"):
            lap = [HOST_NAME.get(k, k) for k, v in ph.items() if v == "laptop"]
            drn = [HOST_NAME.get(k, k) for k, v in ph.items() if v == "draining"]
            srv = [HOST_NAME.get(k, k) for k, v in ph.items() if v == "server"]
            parts = []
            if lap:
                parts.append(f"现在由笔记本统一派图（服务器资产补推中），{' / '.join(lap)} 推完后自动交还")
            if drn:
                parts.append(f"{' / '.join(drn)} 正在交还给服务器自己派")
            if srv:
                parts.append(f"{' / '.join(srv)} 已由服务器自己派图")
            text = "；".join(parts) or "临时由笔记本派图"
        else:
            text = "两台服务器各自派图（正常模式）"
        dispatch = {"override": bool(dm.get("override_active")), "phases": {k: PHASE_WORD.get(v, v) for k, v in ph.items()}, "text": text}
    return relay, tunnels, reconnect, dispatch


def build(now: float | None = None, wd: dict | None = None, res: dict | None = None, local: list | None = None, ns: dict | None = None) -> dict:
    """纯函数（测试注入 wd / res / local）：看门狗状态 + 常驻健康 + 本机探测 → 给界面的汇总"""
    now = time.time() if now is None else now
    wd = (_jl(WD_STATE, {}) or {}) if wd is None else wd
    res = (_jl(RESIDENT, {}) or {}) if res is None else res
    local = _local(now) if local is None else local
    ns = (_jl(NETFIX, {}) or {}) if ns is None else ns
    ns_ok = bool(ns.get("t")) and now - float(ns["t"]) < NETFIX_STALE_S
    wd_t = float(wd.get("t") or 0) or None
    wd_age = now - wd_t if wd_t else None
    wd_ok = wd_age is not None and wd_age < WD_STALE_S
    opened = wd.get("open") or {}

    # 跳板
    relay_down = bool(wd.get("_relay_down"))
    relay_checked = float(wd.get("_relay_t") or 0) or None
    ra = opened.get("A-RELAY")
    down_since = float(ra["t"]) if relay_down and ra and ra.get("t") else None
    relay = {"ok": not relay_down, "checked_at": _hm(relay_checked),
             "last_ok_at": _hm(relay_checked if not relay_down else down_since),
             "down_s": round(now - down_since) if down_since else None}
    relay["text"] = ("通" if not relay_down else f"不通，已断 {_ago(relay['down_s'])}") if relay_checked else "还没测过"

    # 隧道 + 自动重连
    fails = wd.get("fails") or {}
    rebuilds = wd.get("rebuilds") or []
    last_rb: dict[int, float] = {}
    for r in rebuilds:
        last_rb[int(r.get("port") or 0)] = max(last_rb.get(int(r.get("port") or 0), 0), float(r.get("t") or 0))
    tunnels, reconnect = [], []
    for port, (host, card) in TUNNEL_CARDS.items():
        f = int(fails.get(str(port)) or 0)
        ok = f == 0
        rb = last_rb.get(port)
        rebuilding = (not ok) and rb is not None and now - rb < REBUILD_FRESH_S
        name = f"{HOST_NAME[host]}·卡{card}"
        if ok:
            text = "通"
        elif relay_down:
            text = f"断了约 {_ago(f * TICK_S)}（跳板断了，等跳板恢复后自动重连）"
        elif rebuilding:
            text = f"断了约 {_ago(f * TICK_S)}，正在自动重连"
        else:
            text = f"断了约 {_ago(f * TICK_S)}，自动重连会在 2 分钟内再试"
        tunnels.append({"port": port, "host": host, "card": card, "name": name, "lane": f"{host}:{card}", "ok": ok,
                        "fails": f, "down_s": f * TICK_S if f else 0, "rebuilding": rebuilding,
                        "last_rebuild_at": _hm(rb), "alert": f"A-TUNNEL-{port}" in opened, "text": text,
                        "tech": f"本机 {port} → {host}"})
        if rebuilding:
            reconnect.append(f"正在重连{name}的连接（{_hm(rb)} 起）")
    if relay_down and any(not t["ok"] for t in tunnels):
        reconnect.insert(0, "跳板断了：先等跳板恢复，再自动重连各条连接（这时不反复重连，免得加重跳板负担）")
    if not wd_ok:
        reconnect.insert(0, f"自动重连的看门狗{_ago(wd_age)}没报到，可能没在运行" if wd_age is not None else "自动重连的看门狗没有记录，可能没在运行")

    dispatch = None
    if ns_ok:
        relay, tunnels, reconnect, dispatch = _from_netfix(ns, now)
        relay_down = not relay["ok"]
        if not wd_ok:     # 监管进程在跑，看门狗只做探测 / 报警，没报到不算“自动重连没人管”
            reconnect = [r for r in reconnect if "看门狗" not in r]

    # 两台服务器常驻 night / producer
    servers = {}
    for host in ("gpu33", "gpu36"):
        h = (res.get(host) or {}).get("health") or {}
        at = h.get("at")
        try:
            at_t = time.mktime(time.strptime(at, "%Y-%m-%d %H:%M:%S")) if at else None
        except ValueError:
            at_t = None
        chk_age = now - at_t if at_t else None
        nage = h.get("night_state_age_min")
        night_age_now = (float(nage) * 60 + (chk_age or 0)) if nage is not None else None
        night_ok = night_age_now is not None and night_age_now < NIGHT_STALE_MIN * 60
        hb_at = (at_t - float(nage) * 60) if (at_t and nage is not None) else None
        servers[host] = {
            "name": HOST_NAME[host], "night_ok": night_ok, "night_heartbeat_at": _hm(hb_at),
            "night_age_s": round(night_age_now) if night_age_now is not None else None,
            "checked_at": _hm(at_t), "checked_age_s": round(chk_age) if chk_age is not None else None,
            "idle_min": h.get("idle_min"), "dispatchable": h.get("dispatchable"),
            "text": ("常驻在跑" if night_ok else ("常驻可能停了" if night_age_now is not None else "没有记录"))
                    + (f"，最近心跳 {_ago(night_age_now)}前" if night_age_now is not None else "")
                    + (f"（{_ago(chk_age)}前查的；跳板断着，查不到最新）" if relay_down and chk_age is not None else ""),
        }
        nsv = (ns.get("servers") or {}).get(host) if ns_ok else None
        if nsv and nsv.get("sync_age_min") is not None:
            servers[host]["sync_age_min"] = nsv["sync_age_min"]
            servers[host]["text"] += f"；最后一次同步 {_ago(float(nsv['sync_age_min']) * 60)}前"

    bad_t = [t for t in tunnels if not t["ok"]]
    if relay_down:
        level, summary = "bad", f"跳板断了 {_ago(relay['down_s'])}：笔记本连不上两台服务器（服务器上的常驻照常跑）"
    elif len(bad_t) == len(tunnels):
        level, summary = "bad", "到两台服务器的连接全断了，正在自动重连"
    elif bad_t:
        level, summary = "warn", f"{len(bad_t)} 条连接断了（{'、'.join(t['name'] for t in bad_t)}），正在自动重连"
    else:
        level, summary = "ok", "全部连接正常"
    if not wd_ok and not ns_ok and level == "ok":
        level, summary = "warn", "连接看起来正常，但自动重连的看门狗没报到"
    return {"at": _hm(now), "level": level, "summary": summary,
            "watchdog": {"ok": wd_ok, "at": _hm(wd_t), "age_s": round(wd_age) if wd_age is not None else None},
            "relay": relay, "tunnels": tunnels, "servers": servers, "local": local, "reconnect": reconnect,
            "dispatch": dispatch, "source": "netfix" if ns_ok else "watchdog",
            "alerts": [{"id": a.get("id"), "level": a.get("level"), "since": a.get("ts")} for a in opened.values()]}


@router.get("/api/infra/status")
def infra_status():
    return build()
