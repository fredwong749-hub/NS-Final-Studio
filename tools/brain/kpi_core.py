"""每集 KPI 的唯一口径（L-212 #9，11-07）：大脑 telemetry.kpi 和网页 KPI 面板 ns_api/episode_kpi 都只调这里。

  · 计时起点 = max(本集首次派单, 本集最近一次导入剧本)——重新导入 = 这一版剧本重新开始算 50 分钟（L-205），
    以前 ep01 起点停在 11-03 首派，面板显示“超预算 4493 分钟”。
    首派只知道“最早一次”，导入后真正的第一次派单时刻没有记录 → 用导入时刻代替（偏早不超过一次派单间隔）。
  · 首 / 尾 / 视频完成数 = 登记表 have.passed（两台逐字段取最大，W-SCAN 11-07），总镜 = have.total；
    best_effort 不算视频完成（面板以前自己逐镜数、把 best_effort 算进去，和大脑不一致）。
  · 导入时间：data/autopilot/imports.jsonl 的 at 是裸串，写的人可能是笔记本（系统时钟美东，time.strftime）
    也可能是带 TZ=JST-9 的会话 → 同一个文件里两种都有（实测 11-06 14:49:28 那行按美东算比文件修改时间还晚 = 只能是 JST）。
    规则：按本机时区算不晚于文件修改时间 → 本机时区；否则 → JST。写入格式不动（takes_ui / data_parity 按字符串比大小）。
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

JST = timezone(timedelta(hours=9))
BUDGET_MIN = 50   # L-205


def jst(t: float, fmt: str = "%m-%d %H:%M") -> str:
    return time.strftime(fmt, time.gmtime(t + 9 * 3600))


def clock_start(first_dispatch: float | None, import_t: float | None) -> float | None:
    """本集计时起点：没派过单 = 没开始；派过 = max(首派, 最近导入)"""
    if not first_dispatch:
        return None
    return max(float(first_dispatch), float(import_t or 0))


def naive_at_epoch(s: str, file_mtime: float | None = None) -> float | None:
    """imports.jsonl 的裸 at → epoch（规则见模块说明）；带时区的按自带时区"""
    try:
        d = datetime.fromisoformat(str(s)[:25])
    except (TypeError, ValueError):  # arch-ok: 坏行 = 没有导入时刻，起点按首派
        return None
    if d.tzinfo is not None:
        return d.timestamp()
    # 复审 11-07：不按读取方进程时区（大脑跑在 TZ=JST-9 下会读错 14 小时）；两种写入方时区（笔记本美东 / 服务器 JST）各算一个，
    # 取“不晚于文件修改时间”里最晚的那个（写入时刻不可能晚于文件 mtime）；没有 mtime 时按美东（imports.jsonl 主要由笔记本写）
    from datetime import timedelta, timezone as _tz
    east = d.replace(tzinfo=_tz(timedelta(hours=-5))).timestamp()
    jst = d.replace(tzinfo=JST).timestamp()
    if file_mtime is None:
        return east
    ok = [t for t in (east, jst) if t <= file_mtime + 60]
    return max(ok) if ok else min(east, jst)


def import_epochs(root: Path, run: str) -> dict[str, float]:
    """{集号: 本集最近一次导入的 epoch}（整本导入对所有集生效时记在 "_whole"）。没有文件 = {}"""
    f = Path(root) / "data" / "autopilot" / "imports.jsonl"
    try:
        mt = f.stat().st_mtime
        lines = f.read_text(encoding="utf-8").splitlines()
    except OSError:  # arch-ok: 没有导入记录 = 起点按首派（测试 / 沙箱根）
        return {}
    out: dict[str, float] = {}
    for ln in lines:
        try:
            r = json.loads(ln)
        except ValueError:  # arch-ok: 一行写坏跳过
            continue
        if r.get("run_id") != run or r.get("kind") == "changed_shots_backfill" or not r.get("at"):
            continue
        t = naive_at_epoch(r["at"], mt)
        if t is None:
            continue
        eps = [str(int(x)) for x in (r.get("episodes") or []) if str(x).isdigit()]
        eps += [str(int(k.split("-")[0][2:])) for k in (r.get("changed_shots") or []) if str(k).startswith("ep") and k.split("-")[0][2:].isdigit()]
        for ep in set(eps) or {"_whole"}:
            out[ep] = max(out.get(ep, 0.0), t)
    return out


def merge_have(cur: dict | None, total=0, first=0, last=0, video=0, assembled=False) -> dict:
    """两台登记表逐字段取最大"""
    c = cur or {"total": 0, "video_done": 0, "first_done": 0, "last_done": 0, "assembled": False}
    c.update(total=max(c["total"], int(total or 0)), video_done=max(c["video_done"], int(video or 0)),
             first_done=max(c["first_done"], int(first or 0)), last_done=max(c["last_done"], int(last or 0)),
             assembled=bool(c["assembled"] or assembled))
    return c


def have_from_registry_episode(E: dict) -> dict:
    """producer 登记表里一集（完整版：have:{total, passed:{first,last,video}}；大脑探针压缩版：have:{t,f,l,v}, asm）→ merge_have 的参数"""
    hv = E.get("have") or {}
    pz = hv.get("passed") or {}
    asm = E.get("asm")
    if asm is None:
        asm = ((E.get("objects") or {}).get("assembly") or {}).get("status") == "passed"
    return {"total": hv.get("t", hv.get("total")), "first": hv.get("f", pz.get("first")), "last": hv.get("l", pz.get("last")),
            "video": hv.get("v", pz.get("video")), "assembled": bool(asm)}


def episodes(now: float, starts: dict, have: dict, imports: dict | None = None, budget_min: int = BUDGET_MIN) -> dict:
    """纯函数：starts {ep: 首派 epoch}，have {ep: merge_have 结果}，imports {ep: 最近导入 epoch, "_whole": ...} → {ep: 记录}"""
    imports = imports or {}
    out = {}
    for ep in sorted(set(starts) | set(have), key=lambda x: int(x) if str(x).isdigit() else 0):
        ep = str(ep)
        h = have.get(ep) or {}
        imp = max(imports.get(ep, 0.0), imports.get("_whole", 0.0)) or None
        fd = starts.get(ep)
        t0 = clock_start(fd, imp)
        rec = {"start": jst(t0) if t0 else None, "start_t": t0, "first_dispatch_t": fd, "import_t": imp,
               "import_at": jst(imp) if imp else None, "clock_from": ("import" if t0 and imp and t0 == imp and imp != fd else "dispatch") if t0 else None,
               "elapsed_min": round((now - t0) / 60, 1) if t0 else None, "budget_min": budget_min, **h}
        if h.get("assembled"):
            rec["state"] = "assembled"
        elif t0 and h.get("total"):
            frac = h["video_done"] / h["total"]
            rec["done_frac"] = round(frac, 2)
            rec["eta_min"] = round(rec["elapsed_min"] / frac - rec["elapsed_min"], 1) if frac > 0 else None
            rec["state"] = "over_budget" if rec["elapsed_min"] > budget_min else "in_budget"
        else:
            rec["state"] = "not_started" if not t0 else "no_registry"
        out[ep] = rec
    return out
