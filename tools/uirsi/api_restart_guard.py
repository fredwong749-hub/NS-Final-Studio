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
WEB = ROOT / "apps/web"


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


def tick(dry: bool = False) -> dict:
    now = time.time()
    act: dict = {"at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    try:
        act["dist"] = refresh_dist(dry)
    except Exception as e:  # noqa: BLE001 — dist 刷新失败不拦重启判断
        act["dist"] = {"error": repr(e)[:200]}
    files = changed_since_up()
    todo = RQ.pending(HOST)
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
    act["would_restart"] = [r.get("id") for r in todo]
    if dry:
        return act
    t0 = time.time()
    rec = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "host": HOST, "request_ids": [r["id"] for r in todo],
           "by": sorted({r.get("by") or "?" for r in todo}), "reasons": [r.get("reason") for r in todo][:20],
           "urgent_jump": bool(urgent and gap < MIN_GAP_S), "since_last_restart_min": round(gap / 60, 1)}
    try:
        p = subprocess.run(["pwsh", "-NoProfile", "-File", str(ROOT / "ops/restart_api.ps1")], capture_output=True, timeout=300,
                           cwd=str(ROOT))
        rec["restart_out"] = (p.stdout.decode("utf-8", "replace") + p.stderr.decode("utf-8", "replace")).strip()[-300:]
        rec["ok"] = p.returncode == 0 and bool(_marker().get("up_at"))
    except Exception as e:  # noqa: BLE001
        rec["ok"] = False
        rec["error"] = repr(e)[:300]
    rec["secs"] = round(time.time() - t0, 1)
    if rec["ok"]:
        RQ._append(RQ.DONE, rec)       # 失败不记 done：请求留着，下一拍再试
    act["restart"] = rec
    return act


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
