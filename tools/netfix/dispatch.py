"""谁派单（NETFIX 11-01，总调度 fredw-2b 派；规则 K-OPS-N04）。

出图从“笔记本 producer 经隧道派到服务器”改为“每台机器只派本机的出图道”：
  gpu33 / gpu36 各跑一个常驻 producer（服务器上 127.0.0.1:181xx/182xx 经 fwd.py 到本机 ComfyUI，不经跳板），笔记本 producer 只派 laptop:0。
每个 producer 的 control.json 由本模块按同一份规则算（唯一来源，不手写）：
  only       = config/netfix/partition.json images[本机] ∩ data/autopilot/ready_episodes.json（WORKFLOW episode_pipeline 写）的镜；
               交集为空 → ["__none__"]（一个都不派；producer 的 only 为空表示“全部”，所以不能留空）
  hold_lanes = 不属于本机的全部道（服务器上 laptop:0 的地址不通，也要挂住）
  paused     = 跟随笔记本 control.json 的全局暂停（paused_by 属于 global_pause_ignore_by 的不算）
跨机不重叠：分区按集互斥（check_partition 校验），所以两台不会派同一个对象；没有跨机共享锁，不做跨机接手（steal_plan 只出评估）。

用法：
  .venv/Scripts/python.exe tools/netfix/dispatch.py show                 每台机器会派什么
  .venv/Scripts/python.exe tools/netfix/dispatch.py check                分区自检（互斥 / 覆盖 10 集 / 道不重叠）
  .venv/Scripts/python.exe tools/netfix/dispatch.py apply-laptop [--dry] 写笔记本 control.json 的 only / hold_lanes（不动 paused）
  服务器上：<OFF>/venv/bin/python tools/netfix/dispatch.py server-control gpu33 --laptop-ctrl <json 文件> [--write]
            （resident_prep.py 调用；laptop-ctrl 是 resident_sync 推上去的笔记本 control.json 快照）
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PARTITION = ROOT / "config/netfix/partition.json"
READY = ROOT / "data/autopilot/ready_episodes.json"
CONTROL = ROOT / "data/producer/control.json"
NONE = "__none__"


def iso() -> str:
    """笔记本时区（UTC+9）的时间戳：服务器时区是 America/New_York，ts 字段统一按笔记本口径（同 start.sh 的 TZ=Asia/Tokyo）"""
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() + 9 * 3600))


def jl(p, d=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return d


def js(p: Path, d) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".netfix.tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def partition(p: Path = PARTITION) -> dict:
    return jl(p, {}) or {}


def check_partition(part: dict | None = None) -> list[str]:
    """[] = 通过。images / video 每集恰好一台；道不重叠；笔记本不出视频"""
    part = part or partition()
    errs = []
    for kind, want in (("images", range(1, 11)), ("video", range(1, 11))):
        seen: dict[int, str] = {}
        for h, eps in (part.get(kind) or {}).items():
            for e in eps:
                if e in seen:
                    errs.append(f"{kind}: ep{e:02d} 同时分给 {seen[e]} 和 {h}（会重复派单）")
                seen[e] = h
        miss = [e for e in want if e not in seen]
        if miss:
            errs.append(f"{kind}: 没分出去的集 {miss}")
    if "laptop" in (part.get("video") or {}):
        errs.append("video: 笔记本道 laptop:0 是 image_only，不能分视频")
    lanes: dict[str, str] = {}
    for h, ls in (part.get("lanes") or {}).items():
        for ln in ls:
            if ln in lanes:
                errs.append(f"lanes: {ln} 同时属于 {lanes[ln]} 和 {h}")
            lanes[ln] = h
    return errs


def ready_shots(ready: dict | None) -> dict[int, list[str]]:
    out = {}
    for ep, rec in ((ready or {}).get("episodes") or {}).items():
        try:
            out[int(ep)] = sorted(set((rec or {}).get("shots") or []))
        except (TypeError, ValueError):
            continue
    return out


def global_pause(laptop_ctrl: dict | None, part: dict | None = None) -> tuple[bool, str | None]:
    part = part or partition()
    c = laptop_ctrl or {}
    by = c.get("paused_by")
    if c.get("paused") and by not in set(part.get("global_pause_ignore_by") or []):
        return True, str(by)
    return False, None


def control_for(host: str, laptop_ctrl: dict | None, ready: dict | None, part: dict | None = None) -> dict:
    """本机 producer 的 control 字段（只这几个；control.json 其它字段读-改-写保留）"""
    part = part or partition()
    eps = sorted(set(part["images"].get(host) or []))
    rs = ready_shots(ready)
    ready_eps = [e for e in eps if e in rs]
    only = sorted({s for e in ready_eps for s in rs[e]}) or [NONE]
    hold = sorted({ln for h, ls in (part.get("lanes") or {}).items() if h != host for ln in ls})
    gp, by = global_pause(laptop_ctrl, part)
    fields = {"only": only, "hold_lanes": hold,
              "dispatch_by": {"by": "NETFIX dispatch.py", "at": iso(), "host": host,
                              "partition_eps": eps, "ready_eps": ready_eps,
                              "rule": "K-OPS-N04 only = 分区 ∩ 已准备好的集；hold = 别的机器的道；paused 跟随笔记本全局暂停"}}
    if host != "laptop":                     # 笔记本的 paused 就是全局开关本身，不改
        fields.update(paused=gp, paused_by=(f"GLOBAL:{by}" if gp else None),
                      note=(f"跟随笔记本全局暂停（{by}）" if gp else f"SERVER_RESIDENT {host}：只派 ep{eps} ∩ 已准备好的集 {ready_eps}"))
    return fields


def apply(ctrl_path: Path, fields: dict, dry: bool = False) -> dict:
    c = jl(ctrl_path, {}) or {}
    new = {**c, **fields}
    if not dry:
        js(ctrl_path, new)
    return new


SNAPSHOT = ROOT / "data/netfix/laptop_ctrl.json"


def snapshot_laptop() -> bool:
    """笔记本 control.json 的全局暂停快照（paused / paused_by / paused_at），变了才写；随 resident_sync 第一级推到服务器，
    resident_prep / server-control 据此决定服务器 producer 是否跟随暂停。监管进程每拍调用。返回是否改写"""
    c = jl(CONTROL, {}) or {}
    snap = {k: c.get(k) for k in ("paused", "paused_by", "paused_at", "note")}
    old = jl(SNAPSHOT, {}) or {}
    if {k: old.get(k) for k in snap} == snap:
        return False
    js(SNAPSHOT, {**snap, "at": iso(), "by": "NETFIX dispatch.snapshot_laptop"})
    return True


def steal_plan(states: dict[str, dict]) -> dict:
    """跨机接手评估（总调度 22:2x 问）。不执行，只说明为什么现在不做 / 什么条件下能做。
    states: {host: {"idle": bool, "unstarted_eps": [ep...]}}（由调用方从 health / attempts 算）"""
    return {"enabled": bool(partition().get("work_stealing")), "safe_now": False,
            "why": ("没有跨机共享锁：两台服务器互不访问、笔记本经跳板时通时断。安全做法只能是笔记本居中的两阶段交接："
                    "① 两台都连得上 ② 把整集从 A 的 only 撤掉、等 A 的 producer 下一拍确认（心跳 only 不含该集、租约里没有该集对象）"
                    " ③ 再把该集加进 B 的 only、partition 记一笔 ④ 并回按新归属收文件。任一步跳板断就停在“两边都不派”（安全侧）。"
                    "粒度只能是“整集且该集一个对象都还没开始”，否则并回会两边改同一集的文件。"),
            "candidates": {h: s.get("unstarted_eps") for h, s in states.items() if s.get("idle")}}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["show", "check", "apply-laptop", "server-control"])
    ap.add_argument("host", nargs="?")
    ap.add_argument("--laptop-ctrl")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args(argv)
    part = partition()
    if a.cmd == "check":
        errs = check_partition(part)
        print("OK" if not errs else "\n".join(errs))
        return 1 if errs else 0
    ready = jl(READY, {}) or {}
    if a.cmd == "show":
        lc = jl(CONTROL, {}) or {}
        for h in part["images"]:
            f = control_for(h, lc, ready, part)
            print(h, "paused" if f.get("paused") else "", "only", len(f["only"]) if f["only"] != [NONE] else 0, "镜",
                  "ready_eps", f["dispatch_by"]["ready_eps"], "hold", f["hold_lanes"])
        return 0
    if a.cmd == "apply-laptop":
        new = apply(CONTROL, control_for("laptop", jl(CONTROL, {}), ready, part), dry=a.dry)
        print(json.dumps({k: new.get(k) for k in ("paused", "paused_by", "hold_lanes")}, ensure_ascii=False), "only", len(new["only"]))
        return 0
    lc = jl(a.laptop_ctrl, {}) if a.laptop_ctrl else {}
    f = control_for(a.host, lc, ready, part)
    if a.write:
        apply(CONTROL, f)
    print(json.dumps(f, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
