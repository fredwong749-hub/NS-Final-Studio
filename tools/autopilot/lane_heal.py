"""GPU 道卡死自愈（11-03 10:50 MASTER-WSL ASSIGN D；项目方 10:4x：“显卡生图卡住，也没有一个 logic 去修复”）。

每拍（producer.tick 每 60 s 调一次；也可 `lane_heal.py tick` 单跑）看每条 ComfyUI 道：
  ① 正在跑的那一单（queue_running 头）连续占道超过上限（按 ns_tag.kind 的预估 × factor，夹在 min_s–hard_cap_s）：
     - 是自己人的单（agent ∈ own_agents，如 PRODUCER）或没有标签的孤儿单 → 定向 interrupt + 出队（ComfyUI /interrupt 带 prompt_id，
       别人的单不受影响；不杀任何进程）。出图程序那边等结果的线程随即拿到失败，走它原有的失败分类 / 换道重排（租约释放后 derive 重新派到空闲道）；
     - 别人的单（VIDEO10 / BAKEOFF / 训练…）→ 只登记卡点，不动。
  ② 训练锁一直在、但这张卡上除常驻出图服务以外没有任何进程、占用率 0，持续 stale_lock_s → 判“过期锁”：默认只登记；
     stale_lock_action=reclaim 时把锁文件改名为 .released-stale-auto-<时间>（不删，可改回），道当拍收回。
  ③ 锁目录一直读不到（train_locks_cached → None，出图程序按“锁着”处理，界面显示“训练占用中”）持续 unknown_lock_s → 登记卡点（10:4x 截图的真实原因多半是这个）。
每次自愈 / 登记写一行 data/producer/lane_heal.jsonl（master_check ⑦ 读“卡死已自愈 N 次”），同一事件只登记一次 report_issue。
身份核对：按 prompt_id（ComfyUI 内唯一）+ 首次看到在跑的时间；不按道号猜。远端进程一律不杀（K-OPS-F30：只停自己记录的 pid）。
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CFG = ROOT / "config" / "autopilot" / "lane_heal.json"
STATE = ROOT / "data" / "producer" / "lane_heal_state.json"
LOG = ROOT / "data" / "producer" / "lane_heal.jsonl"

DEFAULT = {
    "enabled": True,
    "interrupt_own": True,
    "own_agents": ["PRODUCER"],
    "factor": 3.0,
    "min_s": 600,
    "hard_cap_s": 5400,
    "est_s": {"first_frame": 300, "last_frame": 300, "frame": 300, "edit": 300, "sheet": 400, "asset": 400, "video": 1500, "other": 900},
    "stale_lock_s": 1800,
    "stale_lock_action": "report",
    "unknown_lock_s": 900,
    "resident_cmd": ["ComfyUI", "clip_srv"],
}


def cfg() -> dict:
    try:
        return {**DEFAULT, **json.loads(CFG.read_text(encoding="utf-8"))}
    except (OSError, ValueError):   # arch-ok: 没有配置文件 = 用默认值（默认即文档里的值）
        return dict(DEFAULT)


def _jl(p: Path, d):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):   # arch-ok: 状态文件不存在 / 半写 = 从空状态起（只影响计时起点）
        return d


def _save(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def log(rec: dict) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"at": time.strftime("%F %T"), **rec}, ensure_ascii=False) + "\n")


def limit_s(kind: str | None, c: dict) -> float:
    est = (c.get("est_s") or {}).get(kind or "other") or (c.get("est_s") or {}).get("other") or 900
    return float(min(max(est * float(c["factor"]), c["min_s"]), c["hard_cap_s"]))


# ------------------------------------------------------------------ ComfyUI 读写（测试换掉这三个）
def comfy_queue(url: str) -> dict | None:
    try:
        with urllib.request.urlopen(url + "/queue", timeout=6) as r:
            return json.loads(r.read())
    except Exception:  # noqa: BLE001  # arch-ok: 道连不上不是卡死（探测另有登记），本拍跳过
        return None


def comfy_cancel(url: str, prompt_id: str) -> None:
    """定向：先出队再 interrupt(prompt_id)；ComfyUI 不是它在跑就不动（K-OPS-E03）"""
    for path, body in (("/queue", {"delete": [prompt_id]}), ("/interrupt", {"prompt_id": prompt_id})):
        req = urllib.request.Request(url + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=10).read()
        except Exception:  # noqa: BLE001  # arch-ok: 打断失败下一拍还会再看到、再试；结果写日志
            pass


def _report(what: str, hint: str) -> str | None:
    try:
        sp = importlib.util.spec_from_file_location("report_issue_lh", ROOT / "tools/master/report_issue.py")
        m = importlib.util.module_from_spec(sp)
        sp.loader.exec_module(m)  # type: ignore[union-attr]
        return m.report("ops", 0, "7", "lane_heal（GPU 道自愈）", what, False, fix_hint=hint, issues=m.ISSUES, live=m.LIVE)["id"]
    except Exception as e:  # noqa: BLE001  # arch-ok: 登记失败不挡自愈，原因进日志
        return f"登记失败：{e!r}"[:120]


def _running(q: dict) -> tuple[str, dict] | None:
    items = q.get("queue_running") or []
    if not items:
        return None
    it = items[0]
    pid = it[1] if len(it) > 1 else None
    ex = it[3] if len(it) > 3 and isinstance(it[3], dict) else {}
    tag = ex.get("ns_tag") if isinstance(ex.get("ns_tag"), dict) else {}
    return (str(pid), tag or {}) if pid else None


# ------------------------------------------------------------------ 一拍
def tick(lanes: dict, gpus: dict | None = None, locks: dict | None = None, now: float | None = None,
         queue_fn=comfy_queue, cancel_fn=comfy_cancel, report_fn=_report, reclaim_fn=None) -> list[dict]:
    """lanes = {道: ComfyUI url}；gpus = {道: {"procs": [命令行…], "util": %}}（没有就跳过 ②）；
    locks = {道: True/False/None}（None = 读不到）。→ 本拍动作列表"""
    c = cfg()
    if not c.get("enabled"):
        return []
    now = now or time.time()
    st = _jl(STATE, {"running": {}, "lock": {}, "unknown": {}, "reported": []})
    acts: list[dict] = []
    seen_run = {}
    for lane, url in sorted(lanes.items()):
        q = queue_fn(url)
        r = _running(q) if q else None
        if r:
            pid, tag = r
            prev = (st["running"].get(lane) or {})
            first = prev.get("since") if prev.get("prompt_id") == pid else now
            seen_run[lane] = {"prompt_id": pid, "since": first, "agent": tag.get("agent"), "kind": tag.get("kind")}
            age, lim = now - first, limit_s(tag.get("kind"), c)
            if age > lim:
                agent = tag.get("agent")
                mine = (not agent) or agent in (c.get("own_agents") or [])
                key = f"run:{lane}:{pid}"
                if mine and c.get("interrupt_own"):
                    cancel_fn(url, pid)
                    a = {"event": "healed", "lane": lane, "prompt_id": pid, "agent": agent or "无标签（孤儿）", "kind": tag.get("kind"),
                         "age_s": round(age), "limit_s": round(lim), "action": "interrupt+dequeue"}
                    seen_run.pop(lane, None)
                else:
                    a = {"event": "stuck_foreign", "lane": lane, "prompt_id": pid, "agent": agent, "kind": tag.get("kind"),
                         "age_s": round(age), "limit_s": round(lim), "action": "report"}
                if key not in st["reported"]:
                    a["issue"] = report_fn(
                        f"{lane} 上一单（{a['agent']} · {a.get('kind') or '?'}，{pid[:8]}）连续占道 {round(age / 60)} 分钟，超过上限 {round(lim / 60)} 分钟"
                        + ("：已定向打断并出队，出图程序会换道重排" if a["event"] == "healed" else "：不是出图程序的单，未动，请对应负责方处理"),
                        "自愈已处理" if a["event"] == "healed" else "联系该任务负责方；确认无用后在渲染任务中心取消")
                    st["reported"].append(key)
                log(a)
                acts.append(a)
        g = (gpus or {}).get(lane)
        lk = (locks or {}).get(lane)
        if lk is True and g is not None:
            busy = [p for p in g.get("procs") or [] if not any(k in p for k in c["resident_cmd"])]
            if not busy and float(g.get("util") or 0) == 0:
                since = st["lock"].setdefault(lane, now)
                if now - since > c["stale_lock_s"]:
                    key = f"lock:{lane}:{int(since)}"
                    act = c.get("stale_lock_action") == "reclaim" and reclaim_fn is not None
                    if act:
                        reclaim_fn(lane)
                        st["lock"].pop(lane, None)
                    a = {"event": "healed" if act else "stale_lock", "lane": lane, "age_s": round(now - since),
                         "action": "rename_lock" if act else "report"}
                    if key not in st["reported"]:
                        a["issue"] = report_fn(f"{lane} 训练锁还在，但这张卡 {round((now - since) / 60)} 分钟没有训练进程、占用 0%："
                                               + ("已把锁文件改名收回这条道" if act else "判为过期锁，道一直空着没派活"),
                                               "确认训练已结束后，把锁文件改名（.released-…）；或把 lane_heal.json stale_lock_action 设为 reclaim")
                        st["reported"].append(key)
                        log(a)
                        acts.append(a)
            else:
                st["lock"].pop(lane, None)
        elif lk is not True:
            st["lock"].pop(lane, None)
        if lk is None and locks is not None and lane in locks:
            since = st["unknown"].setdefault(lane, now)
            key = f"unknown:{lane}:{int(since)}"
            if now - since > c["unknown_lock_s"] and key not in st["reported"]:
                a = {"event": "lock_unknown", "lane": lane, "age_s": round(now - since), "action": "report",
                     "issue": report_fn(f"{lane} 的训练锁状态 {round((now - since) / 60)} 分钟读不到，出图程序按“锁着”处理、不往这张卡派活（界面会显示训练占用中）",
                                        "查 gpu33 远程命令通道（tools/netfix/rssh 超时归因）")}
                st["reported"].append(key)
                log(a)
                acts.append(a)
        else:
            st["unknown"].pop(lane, None)
    st["running"] = seen_run
    st["reported"] = st["reported"][-500:]
    _save(STATE, st)
    return acts


def healed_count(since_s: float = 86400, now: float | None = None) -> dict:
    """master_check ⑦：近 since_s 秒自愈次数 / 登记未处理次数"""
    now = now or time.time()
    out = {"healed": 0, "reported": 0, "last": None}
    try:
        lines = LOG.read_text(encoding="utf-8").splitlines()
    except OSError:   # arch-ok: 还没有日志 = 0 次
        return out
    for ln in lines:
        try:
            r = json.loads(ln)
            t = time.mktime(time.strptime(r["at"], "%Y-%m-%d %H:%M:%S"))
        except (ValueError, KeyError):   # arch-ok: 坏行跳过
            continue
        if now - t > since_s:
            continue
        out["healed" if r.get("event") == "healed" else "reported"] += 1
        out["last"] = r
    return out


def all_lanes() -> dict:
    """全部 ComfyUI 道（单一来源 ns_render.endpoints：gpu_ids + url_for_gpu；永不使用的 gpu33:2 不在里面）"""
    sys.path.insert(0, str(ROOT / "services" / "render_router"))
    from ns_render import endpoints as EP
    out = {}
    for g in EP.gpu_ids():
        try:
            out[EP.lane_name(g)] = EP.url_for_gpu(g)
        except Exception:  # noqa: BLE001  # arch-ok: 没配地址的道不看
            continue
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("tick", help="看一拍（只做 ①；② ③ 由出图程序带着锁 / 卡信息调用）")
    sub.add_parser("count", help="近 24 小时自愈次数")
    a = ap.parse_args(argv)
    if a.cmd == "tick":
        print(json.dumps(tick(all_lanes()), ensure_ascii=False, indent=1))
    else:
        print(json.dumps(healed_count(), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
