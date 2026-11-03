"""笔记本 :8800 ns_api 的守护重启（UIRSI r44，DISTILL 覆盖率 G1：把“:8800 空闲才重启”这个 claude 判断点改成代码）。
调用方：DISTILL 编排器 run.py tick 每拍用子进程调 `api_restart_guard.py tick`（decider=code，结果写 status.json global.api_restart），不另起常驻进程（总调度 r44 定）。

接 WORKFLOW 的重启队列（tools/autopilot/restart_queue.py，K-OPS-W16）：
  · 谁要重启 :8800，都只 restart_queue.request("laptop-api", 原因, by=…) 追加一条请求，不再直接跑 ops/restart_api.ps1；
  · 本守护每拍（默认 60 s）tick()：
      1) 后端改动合入检测：services/api/** 与 services/{render_router,agent}/** 里 .py 的最新 mtime 晚于上次 up_at（data/qa/api_restart.json）
         → 自动 request("laptop-api", "后端改动合入：<文件…>", by="API_GUARD")，同一批改动只排一次（已有待办就不重复排）；
      2) 有待办 → 检查空闲：GET /api/jobs 没有 queued / running，且 /api/script-autoflow 等无在途子进程（_procs 由 jobs 口径覆盖不到的，跳过）；
         距上次重启 ≥ MIN_GAP_S（10 分钟，紧急请求不受限、审计写明插队）；
         → 跑 ops/restart_api.ps1（不带 -Force，它自己再查一次 /api/jobs），等 /api/season 200；
         → 结果按 restart_queue 同格式追加 data/autopilot/restart_done.jsonl（request_ids / by / reasons / urgent_jump / ok / secs）；
         失败或忙 → 请求留着，下一拍再试。
命令行：
  .venv/Scripts/python.exe tools/uirsi/api_restart_guard.py tick [--dry]     # 跑一拍（--dry 只打印会做什么）
  .venv/Scripts/python.exe tools/uirsi/api_restart_guard.py loop [--every 60]     # 只在没有编排器时手动用
另：:8800 挂的 apps/web/dist 比 apps/web/src 旧时（防止有人从 :8800 打开看到旧界面，总调度 r45），每拍先 vite build 刷新 dist，
    结果写在返回的 dist 字段里（K-UI-050）。
  .venv/Scripts/python.exe tools/uirsi/api_restart_guard.py request --by X --reason "..." [--urgent]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "autopilot"))
import restart_queue as RQ  # noqa: E402

HOST = "laptop-api"
API = "http://127.0.0.1:8800"
MARKER = ROOT / "data/qa/api_restart.json"
MIN_GAP_S = 600
WATCH = [ROOT / "services/api", ROOT / "services/render_router", ROOT / "services/agent", ROOT / "packages"]
# 重启前编译闸门（总调度 11-02 12:0x，K-UI-054）：ns_api 启动会 import 这些目录；任何一个 .py 编译不过就不重启、开工单，
# 不能把 :8800 重启成起不来的状态（11:55 owner_queue.py 改到一半时被自动重启，API 停了 10 分钟）
COMPILE_DIRS = [ROOT / "services/api", ROOT / "services/render_router", ROOT / "services/agent"]
ALERTS = ROOT / "data/qa/alerts.jsonl"
WEB = ROOT / "apps/web"
# 总调度 22:0x 止血开关：文件不存在或 enabled 不是 true → 守护不自动执行重启（只排队、只告警）。打开由总调度写 {"enabled": true, "by": "..."}
AUTO_SWITCH = ROOT / "data/ops/api_guard_auto.json"


def auto_enabled() -> bool:
    try:
        return json.loads(AUTO_SWITCH.read_text(encoding="utf-8-sig")).get("enabled") is True
    except (OSError, ValueError, AttributeError):   # arch-ok: 读不到开关 = 关（宁可不自动重启）
        return False


def _newest(d: Path, exts: tuple[str, ...]) -> float:
    t = 0.0
    for p in d.rglob("*"):
        if p.suffix in exts and "node_modules" not in p.parts:
            try:
                t = max(t, p.stat().st_mtime)
            except OSError:  # arch-ok: 单个文件 stat 失败跳过，不影响最新时间判断
                pass
    return t


def dist_stale() -> tuple[bool, float, float]:
    """(dist 是否比 src 旧, src 最新 mtime, dist/index.html mtime)"""
    src = max(_newest(WEB / "src", (".ts", ".tsx", ".css")), (WEB / "index.html").stat().st_mtime if (WEB / "index.html").exists() else 0.0)
    try:
        dist = (WEB / "dist" / "index.html").stat().st_mtime
    except OSError:  # arch-ok: dist 不存在 = 0，按“dist 比 src 旧”处理（会触发刷新）
        dist = 0.0
    return src > dist + 2, src, dist


def refresh_dist(dry: bool = False) -> dict:
    stale, src, dist = dist_stale()
    out = {"stale": stale, "src_at": time.strftime("%m-%d %H:%M", time.localtime(src)) if src else None,
           "dist_at": time.strftime("%m-%d %H:%M", time.localtime(dist)) if dist else None}
    if not stale or dry:
        return out
    t0 = time.time()
    npx = "npx.cmd" if sys.platform == "win32" else "npx"
    try:
        p = subprocess.run([npx, "vite", "build", "--emptyOutDir"], cwd=str(WEB), capture_output=True, timeout=240)
        out.update(built=p.returncode == 0, secs=round(time.time() - t0, 1),
                   tail=(p.stdout.decode("utf-8", "replace") + p.stderr.decode("utf-8", "replace")).strip()[-200:])
    except Exception as e:  # noqa: BLE001
        out.update(built=False, error=repr(e)[:200])
    return out


def _get(path: str, timeout: float = 10):
    with urllib.request.urlopen(API + path, timeout=timeout) as r:  # noqa: S310 — 本机
        return json.loads(r.read().decode("utf-8"))


def _marker() -> dict:
    try:
        return json.loads(MARKER.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):  # arch-ok: 标记文件读不到 = 不知道上次启动时间：changed_since_up 返回空、不自动排重启（宁可不重启）
        return {}


def _ts(s: str | None) -> float:
    try:
        return time.mktime(time.strptime((s or "")[:19], "%Y-%m-%dT%H:%M:%S"))
    except ValueError:  # arch-ok: 时间格式坏 = 0，同上按未知处理
        return 0.0


def changed_since_up() -> list[str]:
    """上次 :8800 起来之后改过的后端 .py（相对路径，最多 20 个）"""
    up = _ts(_marker().get("up_at"))
    if not up:
        return []
    out = []
    for d in WATCH:
        for p in d.rglob("*.py"):
            if "__pycache__" in p.parts or ".venv" in p.parts:
                continue
            try:
                if p.stat().st_mtime > up + 2:
                    out.append(p.relative_to(ROOT).as_posix())
            except OSError:  # arch-ok: 单个文件 stat 失败跳过
                pass
    return sorted(out)[:20]


def busy() -> int | None:
    """/api/jobs 里 queued / running 的数量；读不到返回 None（按“不确定”处理：不重启）"""
    try:
        r = _get("/api/jobs")
    except Exception:  # noqa: BLE001
        return None
    jobs = r.get("jobs", r) if isinstance(r, dict) else r
    return sum(1 for j in jobs or [] if isinstance(j, dict) and j.get("state") in ("queued", "running"))


def _last_restart() -> float:
    done = [d for d in RQ._lines(RQ.DONE) if d.get("host") == HOST and d.get("ok")]
    t = max((_ts(d.get("at")) for d in done), default=0.0)
    return max(t, _ts(_marker().get("up_at")))


def compile_gate() -> list[str]:
    """COMPILE_DIRS 下全部 .py 用 compile() 过一遍（不写 __pycache__）；返回编译不过的“文件:行 原因”"""
    bad = []
    for d in COMPILE_DIRS:
        for f in sorted(d.rglob("*.py")):
            if any(x in f.parts for x in ("__pycache__", "_quarantine", ".venv", "node_modules")):
                continue
            try:
                compile(f.read_bytes(), str(f), "exec")
            except (SyntaxError, ValueError) as e:
                rel = f.relative_to(ROOT) if f.is_relative_to(ROOT) else f
                bad.append(f"{rel}:{getattr(e, 'lineno', '?')} {getattr(e, 'msg', e)}"[:200])
    return bad


def _compile_alert(bad: list[str]) -> None:
    """开工单：data/qa/alerts.jsonl（同一组错误只记一次）"""
    key = "|".join(bad)[:400]
    if any(r.get("id") == "API-COMPILE" and r.get("key") == key for r in RQ._lines(ALERTS)):
        return
    RQ._append(ALERTS, {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "id": "API-COMPILE", "key": key, "owner_loop": "UIRSI", "severity": "P1",
                        "title": f":8800 重启前编译不过 {len(bad)} 个文件，已暂缓重启（API 继续跑旧代码）", "files": bad[:10]})


def tick(dry: bool = False) -> dict:
    now = time.time()
    act: dict = {"at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    try:
        act["dist"] = refresh_dist(dry)
    except Exception as e:  # noqa: BLE001 — dist 刷新失败不拦重启判断
        act["dist"] = {"error": repr(e)[:200]}
    rv = revive_check(dry)          # 22:0x：API 不在先处理（告警 / 补起一次），不再把“读不到 /api/jobs”当成“不重启”就静默
    if rv is not None:
        act["api_down"] = rv
        return act
    files = changed_since_up()
    todo = covered_filter(RQ.pending(HOST))
    if files and not todo:
        reason = "后端改动合入：" + "、".join(files[:6]) + (f" 等 {len(files)} 个" if len(files) > 6 else "")
        act["requested"] = reason
        if not dry:
            RQ.request(HOST, reason, by="API_GUARD")
        todo = RQ.pending(HOST) if not dry else [{"id": "dry", "reason": reason, "by": "API_GUARD"}]
    if not todo:
        act["skip"] = "没有待办"
        return act
    urgent = [r for r in todo if r.get("urgent")]
    gap = now - _last_restart()
    if gap < MIN_GAP_S and not urgent:
        act["skip"] = f"距上次重启 {gap / 60:.1f} 分钟（< {MIN_GAP_S // 60}），到点合并执行"
        return act
    b = busy()
    if b is None or b > 0:
        act["skip"] = "读不到 /api/jobs，不重启" if b is None else f"/api/jobs 还有 {b} 个在排 / 在跑，等空闲"
        return act
    bad = compile_gate()
    if bad:
        act["skip"] = f"编译不过 {len(bad)} 个文件，不重启（API 继续跑旧代码，已开工单 API-COMPILE）：" + "；".join(bad[:3])
        act["compile_fail"] = bad
        if not dry:
            _compile_alert(bad)
        return act
    act["would_restart"] = [r.get("id") for r in todo]
    if dry:
        return act
    if not auto_enabled():   # 总调度 22:0x 止血：今晚三次自动重启把 :8800 弄挂；开关打开前只排队、不执行“杀旧起新”
        act["skip"] = f"自动重启已停用（止血，开关 data/ops/{AUTO_SWITCH.name}）；待办 {len(todo)} 条留在队列，等人工或开关打开"
        return act
    rec = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "host": HOST, "request_ids": [r["id"] for r in todo],
           "by": sorted({r.get("by") or "?" for r in todo}), "reasons": [r.get("reason") for r in todo][:20],
           "urgent_jump": bool(urgent and gap < MIN_GAP_S), "since_last_restart_min": round(gap / 60, 1)}
    rec.update(run_restart_ps1(by="API_GUARD"))
    if rec["ok"]:
        RQ._append(RQ.DONE, rec)       # 失败不记 done：请求留着；失败已由 restart_api.ps1 写 restart_failed + 开告警
    act["restart"] = rec
    return act


# ---------------------------------------------------------------- 22:0x 总调度：结果以 restart_events 为准 + 挂了告警 / 补起一次
EVENTS = ROOT / "data/ops/restart_events.jsonl"
PS1_LOG = ROOT / "ops/logs/api_restart_guard_ps1.log"
# restart_api.ps1 最长：/api/jobs 10 + 预检 60+30 + 端口 240（RESTARTFIX-O：90→240）+ 起来 180 + 进程快照 / 停树 ≈ 20 → ≈ 540 s；
# vite build 240 + 本值 < flow.api_restart_tick（900）< resident_sync AUTOFLOW_PARTS["api"]（960）——外层先超时会 taskkill /T 把正在跑的 ps1 一起杀掉
# （看门狗经 api_watchdog.py --detach 起，已不在这棵树里）；test_restartfix_o_timeout_chain 核这条链
PS1_TIMEOUT_S = 600
PS1_WORST_S = 10 + 60 + 30 + 240 + 180 + 20


def _events_from(offset: int) -> list[dict]:
    try:
        with open(EVENTS, "rb") as f:
            f.seek(offset)
            raw = f.read().decode("utf-8-sig", "replace")
    except OSError:   # arch-ok: 事件文件读不到 = 没有事件（revive_check 按“没有可补起的故障”处理，宁可不补）
        return []
    out = []
    for ln in raw.splitlines():
        ln = ln.strip().lstrip("﻿")
        if ln:
            try:
                out.append(json.loads(ln))
            except ValueError:   # arch-ok: 坏行跳过
                pass
    return out


def outcome(events: list[dict]) -> dict:
    """本次 restart_api.ps1 的结局（只看它跑之后新写的事件）：restart_done 且 up_at 有值 = 成功；restart_failed = 失败（带 stage / old_kept）；
    都没有 = 没跑完（被杀 / 超时）——不再拿管道 EOF / 退出码当准（19:24 后多次“已成功却记失败”，请求一直挂着反复重启）"""
    for e in reversed(events):
        if e.get("event") == "restart_done":
            return {"ok": bool(e.get("up_at")), "up_at": e.get("up_at"), "stage": None if e.get("up_at") else "not_up"}
        if e.get("event") == "restart_failed":
            return {"ok": False, "stage": e.get("stage"), "why": e.get("why"), "old_kept": e.get("old_kept")}
        if e.get("event") == "restart_skipped":      # RESTARTFIX-S：lock_busy（别人在重启，没动）/ already_healthy（补起时 API 已被拉起，没动）
            return {"ok": e.get("stage") == "already_healthy", "stage": e.get("stage"), "why": e.get("why")}
    return {"ok": False, "stage": "unfinished"}


def run_restart_ps1(by: str, force: bool = False, runner=None) -> dict:
    """跑 ops/restart_api.ps1：输出写文件（不接管道——新起的 API 会继承 pwsh 的句柄，接管道就一直等不到 EOF，
    20:07 / 21:45 两拍就是这样卡满 360 s、明明起来了却记失败，tests/test_restart_api_ps1.py 复现过）；结局读 restart_events"""
    runner = runner or subprocess.run
    t0 = time.time()
    try:
        off = EVENTS.stat().st_size
    except OSError:
        off = 0
    cmd = ["pwsh", "-NoProfile", "-File", str(ROOT / "ops/restart_api.ps1"), "-By", by] + (["-Force", "-Revive"] if force else [])   # force 只有补起用：-Revive 让脚本停旧进程之前再测一次，已健康就不动
    res: dict = {}
    try:
        PS1_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(PS1_LOG, "ab") as f:
            p = runner(cmd, stdin=subprocess.DEVNULL, stdout=f, stderr=subprocess.STDOUT, timeout=PS1_TIMEOUT_S, cwd=str(ROOT))
        res["rc"] = getattr(p, "returncode", None)
    except subprocess.TimeoutExpired:
        res["rc"] = "timeout"
    except Exception as e:  # noqa: BLE001
        res["rc"] = "error"
        res["error"] = repr(e)[:300]
    evs = _events_from(off)
    res.update(outcome(evs))
    if res["stage"] == "unfinished":
        # RESTARTFIX-O P2-4：脚本被超时杀 / 中途死掉——看它是否已走到停旧（stopping_old / port_residual）；
        # 走到了 = 旧进程已停、新的未必起来 → 补写 restart_failed(old_kept=false)，让下一拍 revive_check 能补起；没走到 = 旧进程还在
        stopped = any(e.get("event") in ("stopping_old", "old_stopped", "port_residual") for e in evs)
        res["old_kept"] = not stopped
        RQ._append(EVENTS, {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "event": "restart_failed",
                            "stage": "ps1_unfinished_after_stop" if stopped else "ps1_unfinished_before_stop",
                            "why": f"restart_api.ps1 没跑完（rc={res['rc']}）", "old_kept": not stopped, "by": "api_restart_guard"})
        _alert("A-API-RESTART-FAIL", "crit", f":8800 重启脚本没跑完（rc={res['rc']}，{'已停旧进程' if stopped else '还没停旧进程'}），没有 restart_done / restart_failed，请人工核对 API 状态")
    res["secs"] = round(time.time() - t0, 1)
    return res


def _alert(aid: str, level: str, msg: str, dedupe_s: int = 1800) -> None:
    """data/qa/alerts.jsonl（infra_watchdog 同格式）；同 id 同消息 dedupe_s 内只记一次"""
    now = time.time()
    for r in reversed(RQ._lines(ALERTS)[-200:]):
        if r.get("id") == aid and r.get("msg") == msg and now - float(r.get("t") or 0) < dedupe_s:
            return
    RQ._append(ALERTS, {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "t": now, "id": aid, "state": "open", "level": level,
                        "msg": msg, "by": "api_restart_guard"})


API_UP_TIMEOUT_S = 25      # ISS-1103-014614-9db2(5)：/api/season 首算最多等 SEASON_FIRST_WAIT_S（20 s），5 s 会把刚起、正在首算的 API 误报 A-API-DOWN


def api_up(get=None) -> bool:
    get = get or _get
    for i in range(2):
        try:
            get("/api/season", timeout=API_UP_TIMEOUT_S)
            return True
        except Exception:  # noqa: BLE001 — 连不上 / 超时 / 非 200 都算不在
            if i == 0:
                time.sleep(3)
    return False


def covered_filter(todo: list[dict], up_at: float | None = None) -> list[dict]:
    """请求之后已经有一次成功启动（标记文件 up_at，手动重启也算）→ 这条请求已被满足，不再触发重启。
    （20:14 / 20:26 的请求在 21:15、21:34、22:02 的手动重启后仍算“待办”，自动开关一开会再白杀一次）"""
    up = _ts(_marker().get("up_at")) if up_at is None else up_at
    return [r for r in todo if not (up and float(r.get("t") or _ts(r.get("at"))) < up)]


REVIVE_WINDOW_S = 1800


def revive_check(dry: bool = False, up=None, events=None, now: float | None = None) -> dict | None:
    """:8800 不在时：开告警 A-API-DOWN；若是守护自己的重启弄挂的（30 分钟内最后一条重启结局是 restart_failed 且 old_kept=false），
    且这之后没补起过，且开关打开 → 补起一次（-Force：旧进程本来就不在，脚本里先验新代码、等端口再起）。返回 None = API 在"""
    if (up or api_up)():
        return None
    now = now or time.time()
    r: dict = {"api": "down"}
    _alert("A-API-DOWN", "crit", ":8800 连不上（/api/season 两次失败）") if not dry else None
    evs = events if events is not None else _events_from(0)[-300:]
    last_fail = next((e for e in reversed(evs) if e.get("event") in ("restart_failed", "restart_done")), None)
    # P1-1（OVERSIGHT 第 16 轮）：窗口内出现过任何一次 revive_attempt 就不再补（补起自己失败会写新的 restart_failed，不能只看最后一条）
    # RESTARTFIX-O P2-3：补起什么都没做（lock_busy = 别人在重启 / 停旧之前就被杀）会写 revive_released，把这次额度还回来
    inwin = lambda kind: sum(1 for e in evs if e.get("event") == kind and now - _ts(e.get("at")) < REVIVE_WINDOW_S)
    revived = inwin("revive_attempt") > inwin("revive_released")
    eligible = bool(not revived and last_fail and last_fail.get("event") == "restart_failed" and last_fail.get("old_kept") is False
                    and now - _ts(last_fail.get("at")) < REVIVE_WINDOW_S)
    r["revive_eligible"] = eligible
    if not eligible:
        r["skip"] = "不补起：不是守护重启弄挂的 / 已补起过 / 超过 30 分钟——等人工"
        return r
    if dry or not auto_enabled():
        r["skip"] = "可补起，但" + ("dry" if dry else "自动开关关着") + "——等人工"
        return r
    RQ._append(EVENTS, {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "event": "revive_attempt", "by": "API_GUARD"})
    r["revive"] = run_restart_ps1(by="API_GUARD（补起）", force=True)
    if r["revive"].get("stage") in REVIVE_VOID_STAGES:
        RQ._append(EVENTS, {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "event": "revive_released", "stage": r["revive"].get("stage"), "by": "API_GUARD"})
    return r


REVIVE_VOID_STAGES = ("lock_busy", "ps1_unfinished_before_stop")      # 补起没碰任何进程：不消耗额度


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["tick", "loop", "request"])
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--every", type=int, default=60)
    ap.add_argument("--by", default="")
    ap.add_argument("--reason", nargs="*", default=[])
    ap.add_argument("--urgent", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "request":
        if not a.by:
            print("用法：request --by <谁> --reason <原因> [--urgent]")
            return 2
        print(json.dumps(RQ.request(HOST, " ".join(a.reason), a.by, a.urgent), ensure_ascii=False))
        return 0
    if a.cmd == "tick":
        print(json.dumps(tick(a.dry), ensure_ascii=False, indent=1))
        return 0
    while True:
        try:
            print(json.dumps(tick(a.dry), ensure_ascii=False), flush=True)
        except Exception as e:  # noqa: BLE001
            print(json.dumps({"error": repr(e)[:300]}, ensure_ascii=False), flush=True)
        time.sleep(max(15, a.every))


if __name__ == "__main__":
    sys.exit(main())
