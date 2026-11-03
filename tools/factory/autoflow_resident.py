"""剧本写作推进的常驻服务（总调度 11-02 19:4x：HOLLYWOOD 的 autoflow watch 挂在会话下，会话一结束就停 → 做成和 producer 一样的常驻）。

在笔记本上跑（写作包 / 写手产物都在笔记本）：
  - 单实例：data/factory/autoflow_resident.lock（O_EXCL 建，记 pid；锁主进程已死 = 陈旧、接管），第二份起不来；
  - 每 interval 秒读 config/pipeline/runs.json，只推进状态在 ADVANCE_STATUSES 的剧（paused / frozen / archived 一律不碰，K-OPS-F20）；
  - 推进 = 对 run_dir 里写手已交稿（.done）的集起 `autoflow.py run --source daemon`（与 HOLLYWOOD watch 同一实现，跨进程推进锁在 autoflow 里）；
  - 不写任何 control / 暂停字段（不清别人的暂停，A-09 ③ / K-OPS-F26）；
  - 每拍再调一次 tools/pipeline/asset_worker.tick（阶段 A 资产作业：缺口 → 作业 → 候选 → 待办通知；M-AUTOPIPE-01，AUTOPIPE-A 11-03）；
  - 每 30 分钟跑一轮看门狗 tools/master/watchdog.run（W19，L-163：总调度巡检规则写成代码；连续 3 轮出错登记 P0）；
  - 心跳 data/factory/autoflow_resident.json（pid / t / 在推进的剧 / 最近一次起的集），SENTINEL 按心跳年龄判掉线。
用法：.venv/Scripts/python.exe tools/factory/autoflow_resident.py [--interval 30] [--once]；拉起 / 重启：ops/restart_autoflow.ps1
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOCK = ROOT / "data/factory/autoflow_resident.lock"
HEARTBEAT = ROOT / "data/factory/autoflow_resident.json"
LIFELOG = ROOT / "ops/logs/autoflow_resident.life.log"     # 起停 / 每拍异常 / 退出原因（AUTOFIX-O 11-03：01:16 静默退出、日志全空，查不到原因）
# 写作推进只对“在做”的剧：preparing（V2 剧本写作阶段）/ active / producing；paused、frozen、archived 一律不碰
ADVANCE_STATUSES = ("preparing", "active", "producing")


def _drop_pyc(src: Path) -> None:
    """W12b（A12 第 27 轮 P1-1）：pyc 只校验秒级 mtime + size，同秒同 size 的改动会执行旧字节码 → 每次载入前先删缓存"""
    try:
        Path(importlib.util.cache_from_source(str(src))).unlink(missing_ok=True)
    except (OSError, NotImplementedError, ValueError):   # arch-ok: 删不掉 → 照常载入，下一拍再删
        pass


def _load(name: str, rel: str):
    _drop_pyc(ROOT / rel)
    sp = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True, timeout=30)
        return str(pid) in (r.stdout or "")
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def acquire_lock(lock: Path = LOCK) -> bool:
    """单实例：拿到锁 = True；别的活进程拿着 = False；锁主进程已死 = 接管"""
    lock.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(json.dumps({"pid": os.getpid(), "at": time.time()}))
            return True
        except FileExistsError:
            try:
                pid = int(json.loads(lock.read_text(encoding="utf-8")).get("pid") or 0)
            except (OSError, ValueError):   # arch-ok: 锁文件坏 = 当作陈旧，接管
                pid = 0
            if _pid_alive(pid):
                return False
            lock.unlink(missing_ok=True)
    return False


def release_lock(lock: Path = LOCK) -> None:
    try:
        if int(json.loads(lock.read_text(encoding="utf-8")).get("pid") or 0) == os.getpid():
            lock.unlink(missing_ok=True)
    except (OSError, ValueError):   # arch-ok: 锁已不在 / 坏了 = 没什么可放
        pass


def advance_runs(root: Path = ROOT) -> list[str]:
    """runs.json 里可推进的剧（状态在 ADVANCE_STATUSES）；登记表读不出 = 一部都不推（失败关闭）"""
    try:
        d = json.loads((root / "config/pipeline/runs.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):   # arch-ok: 读不出 = 不推进任何剧
        return []
    return sorted(r for r, v in (d.get("runs") or {}).items() if (v or {}).get("status") in ADVANCE_STATUSES)


def _write_hb(rec: dict) -> None:
    HEARTBEAT.parent.mkdir(parents=True, exist_ok=True)
    tmp = HEARTBEAT.with_suffix(".tmp")
    tmp.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, HEARTBEAT)


def tick(procs: dict, af=None, runs_mod=None, spawn=None) -> dict:
    """一拍：每部可推进的剧，写手已交稿的集起一个 autoflow run（同一集已在跑就跳过）。返回本拍记录"""
    af = af or _load("autoflow_for_resident", "tools/script_rsi/autoflow.py")
    if runs_mod is None:
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from tools.autopilot import runs as runs_mod    # OVERSIGHT-F P2：tools 侧 runs 唯一入口
    spawn = spawn or (lambda rd, ep: subprocess.Popen([sys.executable, str(ROOT / "tools/script_rsi/autoflow.py"), "run", "--run-dir", str(rd),
                                                       "--episode", str(ep), "--import", "dry", "--source", "daemon"], cwd=ROOT,
                                                      env={**os.environ, "PYTHONUTF8": "1"}))
    started = []
    runs = advance_runs()
    for run in runs:
        rd = runs_mod.run_dir(run, ROOT)
        if not rd.is_dir():
            continue
        for ep in af.pending_done(rd):
            key = (run, ep)
            p = procs.get(key)
            if p is not None and p.poll() is None:
                continue
            procs[key] = spawn(rd, ep)
            started.append(f"{run} ep{int(ep):02d}")
    return {"runs": runs, "started": started, "assets": asset_tick(runs), "dispatch": dispatch_tick(), "hollywood": hollywood_tick(runs),
            "watchdog": watchdog_tick()}


WATCHDOG_RETRY_S = 1800        # 看门狗一轮出错后隔多久再试（与正常间隔同；连续 WATCHDOG_FAIL_STREAK 轮出错 → 登记 P0）
WATCHDOG_FAIL_STREAK = 3
_WD = {"next": 0.0}            # 本进程内的下一轮时刻；重启后按 data/master/watchdog_last.json 的 t 续上（watchdog.due）


def watchdog_tick(wd=None, now: float | None = None) -> dict:
    """W19 WATCHDOG-CODE：到点（config/master/watchdog.json every_s，默认 30 分钟）跑一轮 tools/master/watchdog.run（每次重新加载）。
    没到点 = {}；跑了 = {ran, findings, registered, escalate}；载入 / 运行出错 = {error, phase}（同 asset_tick 口径，run_loop 计连续轮数）。
    规则自身的错误在 watchdog 内部记进 errors，不算本轮失败"""
    now = now or time.time()
    if now < _WD["next"]:
        return {}
    try:
        wd = wd or _load("watchdog_for_resident", "tools/master/watchdog.py")
    except BaseException as e:  # noqa: BLE001  载入失败：本轮不巡检（失败关闭），常驻不退
        if isinstance(e, (KeyboardInterrupt, SystemExit)):
            raise
        _WD["next"] = now + WATCHDOG_RETRY_S
        return {"error": repr(e)[:300], "phase": "load"}
    try:
        left = wd.due(now=now)
        if left > 0:
            _WD["next"] = now + min(left, WATCHDOG_RETRY_S)
            return {}
        _WD["next"] = now + WATCHDOG_RETRY_S
        r = wd.run(now=now)
        return {"ran": True, "findings": r.get("findings"), "registered": r.get("registered") or [], "escalate": len(r.get("escalate") or []),
                "rule_errors": len(r.get("errors") or [])}
    except Exception as e:  # noqa: BLE001  一轮出错只记，不退出常驻
        _WD["next"] = now + WATCHDOG_RETRY_S
        return {"error": repr(e)[:300], "phase": "run"}


def report_watchdog_stuck(err: dict, streak: int, runs: list[str], reporter=None) -> str | None:
    """看门狗连续出错 ≥ WATCHDOG_FAIL_STREAK 轮：登记一次 P0（who=resident，阻断）；写法同 report_asset_stuck"""
    try:
        rep = reporter or _load("report_issue_for_resident", "tools/master/report_issue.py").report
        rec = rep(run=(runs or ["-"])[0], episode=0, step="看门狗", who="resident", blocking=True,
                  what=f"P0 看门狗 tools/master/watchdog.py 连续 {streak} 轮出错（phase={err.get('phase')}），巡检规则没人跑：{str(err.get('error'))[:200]}",
                  fix_hint="手动跑 .venv/Scripts/python.exe tools/master/watchdog.py run --dry 看报错；修好后下一轮自动恢复（每轮重新加载）")
        return rec.get("id")
    except Exception as e:  # noqa: BLE001  登记失败不拖垮常驻
        life(f"登记看门狗卡点失败：{e!r}")
        return None


def hollywood_tick(runs: list[str] | None = None, ht=None) -> dict:
    """METRICS-F 11-03（总调度裁定 ISS-1103-023132-1c46 ①）：每拍调一次 tools/pipeline/hollywood_tick.tick——给已过检查的图打好莱坞质感分，
    独立于 asset_worker 主流程；只在本地看图服务空闲时打（低优先级，不挤占 Q9）；开关 config/pipeline/hollywood_score.json。出错只记"""
    try:
        ht = ht or _load("hollywood_tick_for_resident", "tools/pipeline/hollywood_tick.py")
        r = ht.tick(runs=runs)
        return {k: r.get(k) for k in ("scored", "failed", "pending", "skipped", "errors") if r.get(k)}
    except Exception as e:  # noqa: BLE001  打分一拍出错只记，不退出常驻
        return {"error": repr(e)[:300]}


def dispatch_tick(ad=None) -> dict:
    """EPCHAIN-O 11-03：每拍调一次派单器 tools/factory/agent_dispatcher.tick（每拍重新加载；开关 config/pipeline/agent_dispatcher.json，
    默认关 = 立即返回）。出错只记进本拍记录，不影响写作推进"""
    try:
        ad = ad or _load("agent_dispatcher_for_resident", "tools/factory/agent_dispatcher.py")
        return ad.tick()
    except Exception as e:  # noqa: BLE001  派单一拍出错只记，不退出常驻
        return {"error": repr(e)[:300]}


def asset_tick(runs: list[str] | None = None, aw=None) -> dict:
    """AUTOPIPE-A 11-03（M-AUTOPIPE-01 阶段 A）：每一拍调一次 tools/pipeline/asset_worker.tick（自带单实例锁；只处理 ADVANCE_STATUSES 的剧，
    与本服务同口径）。失败只记进本拍记录，不影响写作推进。
    W12：载入（含 asset_worker 按版本戳重载它声明的依赖 RELOAD_DEPS）失败记 phase=load，tick 本身出错记 phase=tick；
    连续出错由 run_loop 计数、≥ ASSET_FAIL_STREAK 拍登记 P0 卡点（失败关闭 + 可见）"""
    try:
        aw = aw or _load("asset_worker_for_resident", "tools/pipeline/asset_worker.py")
    except BaseException as e:  # noqa: BLE001  载入失败 = 本拍不派资产作业（失败关闭），常驻不退
        if isinstance(e, (KeyboardInterrupt, SystemExit)):
            raise
        return {"error": repr(e)[:300], "phase": "load"}
    try:
        r = aw.tick(runs={k: v for k, v in aw.active_runs(ROOT).items() if runs is None or k in runs})
        out = {k: r.get(k) for k in ("started", "meta", "failed", "generated", "golden_pending", "skipped", "config_error") if r.get(k)}
        if getattr(aw, "RELOADED_DEPS", None):
            out["reloaded_deps"] = list(aw.RELOADED_DEPS)
        return out
    except Exception as e:  # noqa: BLE001  资产作业一拍出错只记，不退出常驻
        return {"error": repr(e)[:300], "phase": "tick"}


ASSET_FAIL_STREAK = 3      # asset_tick 连续出错这么多拍 → 登记 P0 卡点 + 心跳 state（W12：04:56 起每拍 AttributeError、只有心跳年龄可看）
_STALE_CODE_ERRORS = ("AttributeError", "ImportError", "ModuleNotFoundError", "NameError", "SyntaxError")


def asset_fail_state(err: dict) -> str:
    """载入失败或典型“新旧代码对不上”的错 → reload_failed；其它 tick 内的错 → asset_failed"""
    e = str(err.get("error") or "")
    return "reload_failed" if err.get("phase") == "load" or e.startswith(_STALE_CODE_ERRORS) else "asset_failed"


def report_asset_stuck(err: dict, streak: int, runs: list[str], reporter=None) -> str | None:
    """登记一次卡点（who=resident，P0，阻断）；返回卡点 id。登记本身失败只记生命日志"""
    try:
        rep = reporter or _load("report_issue_for_resident", "tools/master/report_issue.py").report
        rec = rep(run=(runs or ["-"])[0], episode=0, step="资产线常驻", who="resident", blocking=True,
                  what=f"P0 资产 tick 连续 {streak} 拍出错（{asset_fail_state(err)}，phase={err.get('phase')}），"
                       f"待出图作业无人派：{str(err.get('error'))[:200]}",
                  fix_hint="看 ops/logs/autoflow_resident.life.log；代码修好后下一拍自动恢复（asset_worker 按版本戳重载依赖），"
                           "仍不恢复 → 总调度受控重启 ops/restart_autoflow.ps1")
        return rec.get("id")
    except Exception as e:  # noqa: BLE001  登记失败不拖垮常驻
        life(f"登记资产卡点失败：{e!r}")
        return None


def life(msg: str, path: Path | None = None) -> None:
    """起停 / 异常 / 退出原因写一行（失败不影响主循环）"""
    try:
        pth = path or LIFELOG
        pth.parent.mkdir(parents=True, exist_ok=True)
        with open(pth, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} pid={os.getpid()} {msg}\n")
    except OSError:   # arch-ok: 写不了生命日志不拖垮常驻
        pass


def _parent_info() -> str:
    """谁拉起的（父进程 pid + 命令行）：下次再被整棵进程树带走，看这一行就知道是哪个会话 / 脚本起的"""
    ppid = os.getppid()
    cmd = ""
    if os.name == "nt":
        try:
            r = subprocess.run(["powershell", "-NoProfile", "-Command",
                                f"(Get-CimInstance Win32_Process -Filter 'ProcessId={ppid}').CommandLine"],
                               capture_output=True, text=True, timeout=20)
            cmd = (r.stdout or "").strip()[:300]
        except (OSError, subprocess.SubprocessError):   # arch-ok: 查不到父进程命令行只少一行信息
            cmd = "?"
    return f"ppid={ppid} parent_cmd={cmd!r}"


def _install_signal_log() -> None:
    """能接到的终止信号（Ctrl+C / Ctrl+Break / SIGTERM）先写原因再退；taskkill /F、整棵进程树被带走接不到 → 只能靠“起”那一行的父进程信息"""
    import signal

    def h(signum, _frame):
        life(f"收到信号 {signum}，退出")
        raise SystemExit(128 + int(signum))
    for name in ("SIGTERM", "SIGBREAK", "SIGINT"):
        sig = getattr(signal, name, None)
        if sig is not None:
            try:
                signal.signal(sig, h)
            except (ValueError, OSError):   # arch-ok: 非主线程 / 平台不支持
                pass


def run_loop(interval: int, once: bool, tick_fn=None, sleep=time.sleep, max_ticks: int | None = None, reporter=None) -> int:
    """主循环：每拍任何异常（含 BaseException 里除退出信号外的）都记进心跳 + 生命日志后继续；退出前必写原因。
    asset_tick 连续出错 ≥ ASSET_FAIL_STREAK 拍：心跳 state=reload_failed / asset_failed + 登记一次 P0 卡点（同一段连续出错只登记一次）"""
    tick_fn = tick_fn or tick
    procs: dict = {}
    last: list = []
    n = 0
    streak = 0
    issue_id = None
    wd_streak, wd_issue = 0, None
    reason = "未知"
    try:
        while True:
            n += 1
            try:
                r = tick_fn(procs)
                last = r["started"] or last
                hb = {"pid": os.getpid(), "t": time.time(), "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "runs": r["runs"],
                      "last_started": last, "interval_s": interval, "by": "tools/factory/autoflow_resident.py", "tick": n}
                a = r.get("assets") or {}
                if a.get("error"):
                    streak += 1
                    hb.update(asset_error=a["error"], asset_error_phase=a.get("phase"), asset_error_streak=streak)
                    life(f"第 {n} 拍 asset_tick 出错（连续 {streak} 拍，已继续）：{a['error']}")
                    if streak >= ASSET_FAIL_STREAK:
                        hb["state"] = asset_fail_state(a)
                        if issue_id is None:
                            issue_id = report_asset_stuck(a, streak, r.get("runs") or [], reporter=reporter) or "登记失败"
                        hb["asset_issue"] = issue_id
                else:
                    if streak >= ASSET_FAIL_STREAK:
                        life(f"第 {n} 拍 asset_tick 恢复（此前连续 {streak} 拍出错，卡点 {issue_id}）")
                    streak, issue_id = 0, None
                    if a.get("reloaded_deps"):
                        hb["reloaded_deps"] = a["reloaded_deps"]       # A12 P2-3：心跳里看得到上拍重载了谁
                        life(f"第 {n} 拍 asset_worker 重载依赖：{a['reloaded_deps']}")
                w = r.get("watchdog") or {}
                if w.get("error"):
                    wd_streak += 1
                    hb.update(watchdog_error=w["error"], watchdog_error_streak=wd_streak)
                    life(f"第 {n} 拍看门狗出错（连续 {wd_streak} 轮，已继续）：{w['error']}")
                    if wd_streak >= WATCHDOG_FAIL_STREAK and wd_issue is None:
                        wd_issue = report_watchdog_stuck(w, wd_streak, r.get("runs") or [], reporter=reporter) or "登记失败"
                    if wd_issue:
                        hb["watchdog_issue"] = wd_issue
                elif w.get("ran"):
                    if wd_streak >= WATCHDOG_FAIL_STREAK:
                        life(f"第 {n} 拍看门狗恢复（此前连续 {wd_streak} 轮出错，卡点 {wd_issue}）")
                    wd_streak, wd_issue = 0, None
                    hb["watchdog"] = {"at": hb["at"], **{k: w.get(k) for k in ("findings", "registered", "escalate", "rule_errors")}}
                hb.setdefault("state", "ok")
                _write_hb(hb)
            except (KeyboardInterrupt, SystemExit):
                raise
            except BaseException as e:  # noqa: BLE001  一拍出错只记，不退出（常驻）
                import traceback
                life(f"第 {n} 拍异常（已继续）：{e!r}\n{traceback.format_exc()[-1500:]}")
                try:
                    _write_hb({"pid": os.getpid(), "t": time.time(), "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "error": repr(e)[:300], "tick": n})
                except OSError as e2:
                    life(f"写心跳失败：{e2!r}")
            if once or (max_ticks and n >= max_ticks):
                reason = "--once / 达到拍数，正常结束"
                return 0
            sleep(interval)
    except SystemExit as e:
        reason = f"SystemExit({e.code})"
        raise
    except KeyboardInterrupt:
        reason = "KeyboardInterrupt"
        raise
    except BaseException as e:  # noqa: BLE001  走到这里 = 循环外的异常：留下原因
        import traceback
        reason = f"主循环异常退出：{e!r}\n{traceback.format_exc()[-1500:]}"
        raise
    finally:
        life(f"退出：{reason}（共 {n} 拍）")


def detach(interval: int, popen=subprocess.Popen) -> int:
    """AUTOFIX-O 11-03：从 agent 会话 / 计划任务里拉起时，子进程默认挂在调用方的作业对象（进程树）下，会话或命令一结束就被整棵带走
    （taskkill /F 级，Python 接不到、锁不释放、日志全空——01:16:52 那次就是这样）。这里用 DETACHED_PROCESS + 新进程组 + 脱离作业对象起常驻"""
    logs = ROOT / "ops" / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-X", "utf8", str(ROOT / "tools" / "factory" / "autoflow_resident.py"), "--interval", str(interval)]
    kw = {"cwd": str(ROOT), "stdin": subprocess.DEVNULL, "close_fds": True, "env": {**os.environ, "PYTHONUTF8": "1"}}
    with open(logs / "autoflow_resident.out.log", "a", encoding="utf-8") as out, open(logs / "autoflow_resident.err.log", "a", encoding="utf-8") as err:
        kw.update(stdout=out, stderr=err)
        if os.name == "nt":
            base = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
            try:
                p = popen(cmd, creationflags=base | subprocess.CREATE_BREAKAWAY_FROM_JOB, **kw)
            except OSError:            # 作业对象不允许脱离：退一步只脱离控制台 / 进程组，并记一笔
                life("detach：作业对象不允许 CREATE_BREAKAWAY_FROM_JOB，只按 DETACHED_PROCESS 起（会话结束仍可能被带走）")
                p = popen(cmd, creationflags=base, **kw)
        else:
            p = popen(cmd, start_new_session=True, **kw)
    life(f"detach：已起常驻 pid={p.pid}")
    return p.pid


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=int, default=30)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--detach", action="store_true", help="脱离当前会话 / 作业对象起一份常驻后立即返回（ops/restart_autoflow.ps1 用）")
    a = ap.parse_args(argv)
    if a.detach:
        pid = detach(a.interval)
        print(f"autoflow_resident 已脱离会话启动 pid={pid}")
        return 0
    if not acquire_lock():
        print("autoflow_resident 已有一份在跑（data/factory/autoflow_resident.lock），本进程退出")
        life("已有一份在跑，本进程不启动")
        return 3
    life(f"启动 interval={a.interval} {_parent_info()}")
    _install_signal_log()
    try:
        return run_loop(a.interval, a.once)
    finally:
        release_lock()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
