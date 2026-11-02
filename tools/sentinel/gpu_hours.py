"""GPU 24 小时时间分配（项目方 11-02 04:0x 要求，总调度派 SENTINEL；口径见 docs/master/SLO.md “GPU 24 小时”；规则 K-OPS-S09）。

每张生产出图卡（gpu33:0/1/3、gpu36:0/1）最近 24 小时按 10 s 一格归类，各项加起来 = 24 h：
  productive  真正在跑：生产任务（ns_tag.agent=PRODUCER）在执行，且产出被收下（producer 日志有 rendered 记这张 take，且没被回滚作废）
  idle_burn   空跑：卡被占着或在跑但没有有效产出——执行报错 / 中断、跑完没收下（孤儿）、产出被回滚作废（如 01:24–01:32 错脸 31 张）、
              派单后到取回之间卡没在执行（加载 / 传输 / 等结果，卡被这单占着）
  borrowed    借道实验：别的 loop（ns_tag.agent≠PRODUCER / 未标）占卡做 A/B、标定等——不是生产也不是空转，单列（总调度可并入）
  waiting     等待任务：有数据证明卡上没有任何执行、也没有派给它的单（pause / hold / 断连 / 服务停 / 没 ready 单）
  no_data     无数据：拿不到证据的时段（ComfyUI /history 覆盖不到、且日志里也没有这张卡的派单），不猜
VLM 卡（gpu36:2、笔记本 4080）没有 ComfyUI 历史，单列为 no_data，直到 SENTINEL 自己的 nvidia-smi 采样（data/sentinel/gpu_samples.jsonl）攒满 24 小时。
数据：服务器 ComfyUI /history（服务器本机压成区间再回传，经 rssh 常驻主连接，nice + timeout）、笔记本与两台服务器的 producer 日志（rendered / dispatch / master_reject）。
  .venv/Scripts/python.exe tools/sentinel/gpu_hours.py      → data/rsi/gpu_24h.json（SENTINEL 每小时刷新）
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools.sentinel import judges as J  # noqa: E402

OUT = ROOT / "data/rsi/gpu_24h.json"
LANES = {"gpu33:0": 8188, "gpu33:1": 8189, "gpu33:3": 8191, "gpu36:0": 8188, "gpu36:1": 8189}
VLM = ["gpu36:2", "laptop:4080"]
STEP = 10
BUCKETS = ("productive", "idle_burn", "borrowed", "waiting", "no_data")
ZH = {"productive": "真正在跑", "idle_burn": "空跑", "borrowed": "借道实验", "waiting": "等待任务", "no_data": "无数据"}
def _void_words() -> tuple:
    try:
        from tools.autopilot import policy
        return tuple(policy.load()["sentinel"]["GPU24_alloc"]["value"]["void_words"])
    except (KeyError, ImportError):  # arch-ok: 策略缺项时用同一份默认值（与 sentinel.yaml 一致）
        return ("身份脸用错", "覆盖配置缺失", "作废", "回滚", "孤儿", "重复", "全量重做")


VOID_WORDS = _void_words()


def server_root() -> str:
    """服务器仓库根：与 S6 同一来源（config/policies/sentinel.yaml S6_config_parity.server_root），不在代码里写死"""
    from tools.autopilot import policy
    return policy.load()["sentinel"]["S6_config_parity"]["value"]["server_root"]

# 服务器本机执行：读 ComfyUI /history 与 producer 日志，只回传压缩后的区间 / 事件（不传整张 prompt 图）
REMOTE = r'''
import json, os, sys, time, urllib.request
for k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[k] = "1"
since = float(sys.argv[1]); ports = [int(x) for x in sys.argv[2].split(",")]; root = sys.argv[3]
out = {"hist": {}, "log": [], "t": time.time()}
for p in ports:
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/history?max_items=4000" % p, timeout=40) as r:
            h = json.loads(r.read())
    except Exception as e:
        out["hist"][str(p)] = {"error": repr(e)[:120]}
        continue
    rows = []
    for pid, v in h.items():
        ms = {m[0]: m[1].get("timestamp") for m in (v.get("status") or {}).get("messages", []) if isinstance(m, list) and len(m) > 1 and isinstance(m[1], dict)}
        s = ms.get("execution_start")
        if not s:
            continue
        e = ms.get("execution_success") or ms.get("execution_error") or ms.get("execution_interrupted")
        ok = "execution_success" in ms
        pr = v.get("prompt") or []
        tag = (pr[3] if len(pr) > 3 and isinstance(pr[3], dict) else {}).get("ns_tag") or {}
        rows.append([s / 1000, (e / 1000) if e else None, ok, str(tag.get("agent") or ""), tag.get("episode"), tag.get("shot"), tag.get("kind")])
    out["hist"][str(p)] = {"n": len(h), "rows": [r for r in rows if (r[1] or time.time()) >= since]}
keep = ('"rendered"', '"dispatch"', '"master_reject"', '"infra_error"', '"stale_requeue"', '"pause"', '"resume"', '"score_backlog"')
pf = set()
try:
    for ln in open(os.path.join(root, "data/producer/log.jsonl"), encoding="utf-8", errors="replace"):
        if '"preflight_block"' in ln:
            i = ln.find('"t": ')
            try:
                tt = float(ln[i + 5:].split(",", 1)[0])
            except ValueError:
                continue
            if tt >= since:
                pf.add(int(tt // 60))
            continue
        if any(k in ln for k in keep):
            try:
                d = json.loads(ln)
            except ValueError:
                continue
            if d.get("t", 0) >= since:
                out["log"].append({k: d.get(k) for k in ("ts", "t", "ev", "obj", "lane", "take", "gpu_s", "render_s", "reason", "by", "note")})
except OSError as e:
    out["log_err"] = repr(e)[:120]
out["log"] += [{"t": m * 60, "ev": "pf_minute"} for m in sorted(pf)]
sys.stdout.write(json.dumps(out))
'''


def fetch(host: str, since: float) -> dict | None:
    from tools.netfix import rssh
    ports = ",".join(str(p) for ln, p in LANES.items() if ln.startswith(host))
    r = rssh.run(host, f"timeout 150 nice -n 19 python3 - {since} {ports} {server_root()}", input=REMOTE.encode(), timeout=180)
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout.decode("utf-8", "replace"))
    except ValueError:  # arch-ok: None = 该机本轮无数据（整机记 no_data，不猜）
        return None


def laptop_log(since: float) -> list[dict]:
    out, pf = [], set()
    keep = ('"rendered"', '"dispatch"', '"master_reject"', '"infra_error"', '"stale_requeue"', '"pause"', '"resume"', '"score_backlog"')
    with (ROOT / "data/producer/log.jsonl").open(encoding="utf-8", errors="replace") as f:
        for ln in f:
            if '"preflight_block"' in ln:
                try:
                    tt = float(json.loads(ln).get("t") or 0)
                except ValueError:  # arch-ok: 半行跳过
                    continue
                if tt >= since:
                    pf.add(int(tt // 60))
                continue
            if any(k in ln for k in keep):
                try:
                    d = json.loads(ln)
                except ValueError:  # arch-ok: 半行跳过
                    continue
                if d.get("t", 0) >= since:
                    out.append(d | {"src": "laptop"})
    return out + [{"t": m * 60, "ev": "pf_minute", "src": "laptop"} for m in sorted(pf)]


TUNNEL_LANE = {"gpu33-l0": "gpu33:0", "gpu33-l1": "gpu33:1", "gpu33-l3": "gpu33:3", "gpu36-l0": "gpu36:0", "gpu36-l1": "gpu36:1"}


def tunnel_down(since: float) -> dict[str, list]:
    """data/netfix/supervisor.log → 每条出图道隧道断开区间（PROBE fail / KILL / EXIT 起，UP 止）；只在笔记本经隧道派单时算“断连”"""
    import re
    out: dict[str, list] = {}
    cur: dict[str, float] = {}
    p = ROOT / "data/netfix/supervisor.log"
    if not p.exists():
        return out
    for ln in p.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r"(\S+) (PROBE fail|KILL|EXIT|UP) (\S+)", ln)
        if not m or m.group(3) not in TUNNEL_LANE:
            continue
        t = J.ts(m.group(1))
        if t is None or t < since - 3600:
            continue
        ln_ = TUNNEL_LANE[m.group(3)]
        if m.group(2) == "UP":
            if ln_ in cur:
                out.setdefault(ln_, []).append((cur.pop(ln_), t))
        else:
            cur.setdefault(ln_, t)
    for ln_, t in cur.items():
        out.setdefault(ln_, []).append((t, None))
    return out


WAIT_REASONS = ("service_down", "disconnect", "tz_suspect", "pause_master", "pause", "score_backlog", "hold", "no_jobs", "unknown")
MASTER_BY = ("总调度", "fredw-2b", "fredw")


def is_master(by) -> bool:
    """暂停是不是总调度本人下的：by 以“总调度 / fredw”开头才算（“NETFIX 切香港线路（总调度 00:5x）”是 NETFIX 下的，不算）"""
    return str(by or "").strip().startswith(MASTER_BY)
WAIT_ZH = {"service_down": "服务停", "disconnect": "断连", "tz_suspect": "时区存疑（只有 ts、没有 epoch t，K-OPS-E18）", "pause_master": "总调度暂停", "pause": "暂停（运维 / 各 loop）", "score_backlog": "打分积压闸顶满",
           "hold": "hold（让道）", "no_jobs": "队列没单（缺资产 / 缺稿，preflight 挡）", "unknown": "原因不明（无证据）"}
WAIT_OWNER = {"service_down": "DEBUG-RSI", "disconnect": "DEBUG-RSI", "tz_suspect": "DEBUG-RSI", "pause_master": "总调度", "pause": "DEBUG-RSI", "score_backlog": "DEBUG-RSI",
              "hold": "FACTORY", "no_jobs": "FACTORY", "unknown": "SENTINEL"}


def tz_suspect(e: dict) -> bool:
    """时区存疑：只有 ts 字符串、没有 epoch t 的事件（ts 可能是服务器 EST 写的，K-OPS-E18），无法确定发生时刻。
    有 epoch t 的事件一律以 t 为准——t 与时区无关；11-02 08:1x 核对：EST 写的 pause / resume 的 t 与东京时间一致（ts 差 14 小时是写 ts 的进程时区错，
    不是事件时刻错），所以不能把它们改判成“时区存疑”"""
    return e.get("t") is None and J.ts(e.get("ts")) is not None


def ctrl_intervals(t0: float, t1: float, path: Path | None = None) -> dict:
    """data/sentinel/control_history.jsonl → {src: {"pause": [(s,e)], "hold": {lane: [(s,e)]}}}；temp_holds 归到 "temp" 源。
    历史从 SENTINEL 开始记录起才有（08:0x），之前的时段仍按日志"""
    p = path or ROOT / "data/sentinel/control_history.jsonl"
    out: dict = {}
    if not p.exists():
        return out
    rows = []
    for ln in p.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            rows.append(json.loads(ln))
        except ValueError:  # arch-ok: 半行跳过
            continue
    rows.sort(key=lambda r: r.get("t") or 0)
    by_src: dict = {}
    for r in rows:
        by_src.setdefault(r.get("src"), []).append(r)
    for src, rs in by_src.items():
        o = out.setdefault("temp" if src == "temp_holds" else src, {"pause": [], "hold": {}, "from": rs[0]["t"]})
        for i, r in enumerate(rs):
            s, e = r["t"], (rs[i + 1]["t"] if i + 1 < len(rs) else t1)
            st = r.get("state") or {}
            if src == "temp_holds":
                for lane in st:
                    o["hold"].setdefault(lane, []).append((s, e))
                continue
            if st.get("paused"):
                o["pause"].append((s, e))
            for lane in st.get("hold_lanes") or []:
                o["hold"].setdefault(lane, []).append((s, e))
    return out


def wait_reasons(lane: str, t0: float, n: int, waiting_idx: list[int], events: list[dict], tunnels: dict, ctrl: dict | None = None) -> dict:
    """“等待任务”逐格归因（纯函数，10 s 一格）。owner = 这条道最近一次派单来自哪个 producer（笔记本 / 服务器），
    pause / 积压闸 / preflight 挡都按 owner 的事件算；优先级 服务停 > 断连 > pause > 积压闸 > 队列没单 > 原因不明。
    hold 没有历史记录（control.json 只存当前值）→ 恒为 0，相应时段落到“原因不明”，不猜"""
    tt = lambda i: t0 + i * STEP  # noqa: E731
    disp = sorted((e["t"], e.get("src", "laptop")) for e in events if e.get("ev") == "dispatch" and e.get("lane") == lane)
    owner = ["laptop"] * n
    j, cur = 0, (disp[0][1] if disp else "laptop")
    for i in range(n):
        while j < len(disp) and disp[j][0] <= tt(i):
            cur = disp[j][1]
            j += 1
        owner[i] = cur
    srcs = {e.get("src", "laptop") for e in events} | {"laptop"}
    paused = {s: [False] * n for s in srcs}
    backlog = {s: [False] * n for s in srcs}
    nojob = {s: [False] * n for s in srcs}

    def mark(arr, a, b):
        end = b if b is not None else t0 + n * STEP
        for i in range(max(0, int((a - t0) // STEP)), min(n, int((end - t0) // STEP) + 1)):
            arr[i] = True

    tzq = {s: [False] * n for s in srcs}
    mpause = {s: [False] * n for s in srcs}              # 总调度暂停（by 含 总调度 / fredw-2b）
    for s_ in srcs:
        ev = sorted((e for e in events if e.get("src", "laptop") == s_), key=lambda e: e["t"])
        p0, p0_tz, p0_m = None, False, False
        for e in ev:
            if e["ev"] == "pause":
                if p0 is None:
                    p0, p0_tz, p0_m = e["t"], tz_suspect(e), is_master(e.get("by"))
            elif p0 is not None and (e["ev"] == "resume" or (e["ev"] == "dispatch")):
                # 结束 = resume，或同一派单方又开始派单（有证据它已经在跑：dispatch.py 直接改 control.json 恢复时日志里没有 resume）
                mark(tzq[s_] if p0_tz else mpause[s_] if p0_m else paused[s_], p0, e["t"])
                p0 = None
            elif e["ev"] == "score_backlog":
                mark(backlog[s_], e["t"], e["t"] + 300)      # producer 每 300 s 记一次“积压闸顶满、先不派”
            elif e["ev"] == "pf_minute":
                mark(nojob[s_], e["t"], e["t"] + 60)
        if p0 is not None:
            mark(tzq[s_] if p0_tz else mpause[s_] if p0_m else paused[s_], p0, None)
    held = {s: [False] * n for s in srcs | {"temp"}}
    for src, o in (ctrl or {}).items():                     # SENTINEL control 历史（08:0x 起）：pause / hold 有据可查
        for a, b in o.get("hold", {}).get(lane, []):
            mark(held.setdefault(src, [False] * n), a, b)
        if src in paused:
            for a, b in o.get("pause", []):
                mark(paused[src], a, b)
                for i in range(max(0, int((a - t0) // STEP)), min(n, int((b - t0) // STEP) + 1)):
                    tzq[src][i] = False
    down = [False] * n
    ends = sorted(e["t"] for e in events if e.get("lane") == lane and e.get("ev") == "rendered")
    for e in events:
        if e.get("lane") == lane and e.get("ev") == "infra_error":
            nxt = next((x for x in ends if x > e["t"]), None)
            mark(down, e["t"], min(nxt or e["t"] + 1800, e["t"] + 1800))
    disc = [False] * n
    for a, b in tunnels.get(lane, []):
        mark(disc, a, b)
    out = {r: 0 for r in WAIT_REASONS}
    for i in waiting_idx:
        o = owner[i]
        r = ("service_down" if down[i] else "disconnect" if (disc[i] and o == "laptop") else "pause_master" if mpause[o][i] else "pause" if paused[o][i]
             else "tz_suspect" if tzq[o][i] else "hold" if (held["temp"][i] or held.get(o, [False] * n)[i]) else "score_backlog" if backlog[o][i] else "no_jobs" if nojob[o][i]
             else "unknown")
        out[r] += STEP
    return out



def _obj_key(ep, shot, kind) -> str | None:
    if ep is None or not shot:
        return None
    k = "last" if "last" in str(kind or "") else "first"
    return f"{k}:ep{int(ep):02d}-{shot}"


def classify(lane: str, t0: float, t1: float, hist: dict | None, events: list[dict], tunnels: dict | None = None, ctrl: dict | None = None) -> dict:
    """纯函数（可测）：→ {bucket: 秒, waiting_reasons: {原因: 秒}}"""
    n = int((t1 - t0) // STEP)
    cls = ["no_data"] * n
    pri = {b: i for i, b in enumerate(("no_data", "waiting", "borrowed", "idle_burn", "productive"))}

    def paint(s, e, b):
        a, z = max(0, int((s - t0) // STEP)), min(n, int(((e or t1) - t0) // STEP) + 1)
        for i in range(a, z):
            if pri[b] > pri[cls[i]]:
                cls[i] = b

    ev = [e for e in events if e.get("lane") == lane or e.get("ev") == "master_reject"]
    void = {(e.get("obj"), e.get("take")) for e in ev if e.get("ev") == "master_reject" and any(w in str(e.get("reason") or "") for w in VOID_WORDS)}
    rendered = [e for e in ev if e.get("ev") == "rendered" and e.get("lane") == lane]
    # 历史覆盖：/history 最早一条执行起点之后，“没有执行”是有证据的
    rows = (hist or {}).get("rows") or []
    cov0 = min((r[0] for r in rows), default=None) if rows else None
    # 注意：/history 为空不能证明“整段没执行”——ComfyUI 重启会清空历史（11-02 04:1x gpu33:1 / :3 实测），所以空历史 = 无证据（no_data）
    if cov0 is not None:
        paint(max(cov0, t0), t1, "waiting")
    # 派单 → 取回 / 报错：卡被这单占着（执行之外的部分 = 空跑）
    disp = sorted((e for e in ev if e.get("ev") == "dispatch" and e.get("lane") == lane), key=lambda e: e["t"])
    ends = sorted((e for e in ev if e.get("ev") in ("rendered", "infra_error") and e.get("lane") == lane), key=lambda e: e["t"])
    for d in disp:
        end = next((x["t"] for x in ends if x["t"] >= d["t"]), None)
        if end is not None and end - d["t"] < 1800:
            paint(d["t"], end, "idle_burn")
    # 执行区间
    taken = {}
    for r in rendered:
        k = (r.get("obj"), r.get("take"))
        taken.setdefault(r.get("obj"), []).append((r["t"], k in void))
    for s, e, ok, agent, ep, shot, kind in rows:
        e2 = e or t1
        if agent != "PRODUCER":
            paint(s, e2, "borrowed")
            continue
        if not ok:
            paint(s, e2, "idle_burn")
            continue
        cand = [(tt, vd) for tt, vd in taken.get(_obj_key(ep, shot, kind), []) if e2 - 5 <= tt <= e2 + 900]
        paint(s, e2, "productive" if cand and not cand[0][1] else "idle_burn")
    # 历史覆盖之前：只有日志里 rendered 的 gpu_s 能证明“在执行且收下”
    for r in rendered:
        gs = float(r.get("gpu_s") or r.get("render_s") or 0)
        if gs and (cov0 is None or r["t"] - gs < cov0):
            paint(r["t"] - gs, r["t"], "idle_burn" if (r.get("obj"), r.get("take")) in void else "productive")
    out = {b: 0 for b in BUCKETS}
    for c in cls:
        out[c] += STEP
    out["no_data"] += int((t1 - t0) - n * STEP)
    out["history_from"] = J.iso(cov0) if cov0 else None
    out["waiting_reasons"] = wait_reasons(lane, t0, n, [i for i, c in enumerate(cls) if c == "waiting"], events, tunnels or {}, ctrl)
    return out


HIST_DIR = ROOT / "data/sentinel/comfy_hist"


def merge_history(lane: str, hist: dict | None, t0: float, store: Path | None = None) -> dict | None:
    """把本次 /history 区间并进 data/sentinel/comfy_hist/<lane>.json（按执行起点去重，只留 24 小时内）；返回合并后的 {n, rows}。
    ComfyUI 重启后 /history 只剩重启之后的，存档补上重启之前的；ComfyUI 不通时也用存档（rows 没有新增）"""
    d = store or HIST_DIR
    p = d / f"{lane.replace(':', '_')}.json"
    old = []
    if p.exists():
        try:
            old = json.loads(p.read_text(encoding="utf-8")).get("rows") or []
        except ValueError:  # arch-ok: 存档坏了按空存档重建（本次 /history 仍然可用）
            old = []
    new = (hist or {}).get("rows") or [] if hist and "error" not in hist else []
    seen, rows = set(), []
    for r in sorted(old + new, key=lambda x: x[0]):
        k = round(r[0], 1)
        if k in seen or (r[1] or t0) < t0:
            continue
        seen.add(k)
        rows.append(r)
    d.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps({"lane": lane, "rows": rows}), encoding="utf-8")
    os.replace(tmp, p)
    if not rows and not (hist and "error" not in hist):
        return hist
    return {"n": len(rows), "rows": rows, "error": (hist or {}).get("error")} if rows else hist


def build(now: float | None = None, remote: dict | None = None, lap: list[dict] | None = None) -> dict:
    now = now or time.time()
    t0 = now - 86400
    remote_live = remote is None                       # 测试注入数据时不读写存档
    remote = remote if remote is not None else {h: fetch(h, t0) for h in ("gpu33", "gpu36")}
    lap = lap if lap is not None else laptop_log(t0)
    tun = tunnel_down(t0)
    ctrl = ctrl_intervals(t0, now) if remote_live else {}
    cards, errs = {}, {}
    for lane, port in LANES.items():
        h = lane.split(":")[0]
        rd = remote.get(h)
        if rd is None:
            errs[h] = "远程取数失败（主连接不在 / 超时）——该机只用笔记本日志"
        events = lap + [e | {"src": h} for e in ((rd or {}).get("log") or [])]
        hist = ((rd or {}).get("hist") or {}).get(str(port))
        if hist and "error" in hist:
            errs[lane] = f"/history 取不到：{hist['error']}（用存档）"
        hist = merge_history(lane, hist, t0) if remote_live else hist
        if hist and hist.get("error") is None:
            hist.pop("error", None)
        cards[lane] = classify(lane, t0, now, hist, events, tun, ctrl)
    for v in VLM:
        cards[v] = vlm_from_samples(v, t0, now)
    allev = lap + [e | {"src": h} for h, rd in remote.items() for e in ((rd or {}).get("log") or [])]
    try:
        from tools.autopilot import policy
        labels = policy.load()["sentinel"]["GPU24_alloc"]["value"].get("pause_labels") or []
    except (KeyError, ImportError):  # arch-ok: 没配显示名时按默认名（总调度暂停 / 暂停）
        labels = []
    segs = pause_segments(allev, t0, now, labels)
    runs_out = by_run(allev, t0)
    prod = [c for k, c in cards.items() if k in LANES]
    tot = {b: sum(c[b] for c in prod) for b in BUCKETS}
    wr = {r: sum(c["waiting_reasons"][r] for c in prod) for r in WAIT_REASONS}
    span = 86400 * len(prod)
    known = span - tot["no_data"]
    res = {"schema": "nsfs.gpu_24h/1", "at": J.iso(now), "window": [J.iso(t0), J.iso(now)], "step_s": STEP, "zh": ZH,
           "cards": {k: c | {"pct": {b: round(100 * c[b] / 86400, 1) for b in BUCKETS}} for k, c in cards.items()},
           "totals": tot | {"pct": {b: round(100 * tot[b] / span, 1) for b in BUCKETS},
                            "productive_pct_of_known": round(100 * tot["productive"] / known, 1) if known else None},
           "waiting_reasons": {"zh": WAIT_ZH, "owner": WAIT_OWNER, "seconds": wr,
                               "pct_of_waiting": {r: (round(100 * wr[r] / tot["waiting"], 1) if tot["waiting"] else 0) for r in WAIT_REASONS},
                               "note": "pause / hold：SENTINEL control 历史（data/sentinel/control_history.jsonl）开始记录之后有据可查，之前按日志；"
                                       "事件时刻以 epoch t 为准（与时区无关）；只有 ts 没有 t 的 pause 记“时区存疑”（K-OPS-E18）；"
                                       "pause 没有 resume 时，以同一派单方下一次派单为结束"},
           "pause_segments": segs,
           "by_run": runs_out,
           "errors": errs,
           "for_rsi_line5": {"productive_pct": round(100 * tot["productive"] / span, 1),
                             "note": "线 5“自运行”分项接这里：生产出图卡 24 小时“真正在跑”占比（含无数据时段在分母里，只升不虚高）"}}
    return res


def pause_segments(events: list[dict], t0: float, t1: float, labels: list | None = None) -> list[dict]:
    """各派单方的暂停段（窗口内）：谁暂停的、备注、起止、时长；labels（sentinel.yaml GPU24_alloc.pause_labels）给特定段起显示名，
    例：19:41–23:17 “总调度全局暂停（为 IMGFIX）”"""
    out = []
    for src in sorted({e.get("src", "laptop") for e in events}):
        ev = sorted((e for e in events if e.get("src", "laptop") == src and e.get("ev") in ("pause", "resume", "dispatch")), key=lambda e: e["t"])
        cur = None
        for e in ev:
            if e["ev"] == "pause" and cur is None:
                cur = e
            elif cur is not None and e["ev"] in ("resume", "dispatch"):
                out.append((src, cur, e["t"], e["ev"]))
                cur = None
        if cur is not None:
            out.append((src, cur, None, "窗口末仍暂停"))
    rows = []
    for src, p, end, how in out:
        s, e = max(p["t"], t0), min(end or t1, t1)
        if e - s < 60:
            continue
        by = str(p.get("by") or "")
        label = next((lb["label"] for lb in labels or [] if lb.get("by_match", "") in by and (not lb.get("start") or abs((J.ts(lb["start"]) or 0) - p["t"]) < 120)), None)
        rows.append({"src": src, "by": by, "label": label or ("总调度暂停" if is_master(by) else "暂停"),
                     "note": str(p.get("note") or "")[:80], "start": J.iso(s), "end": J.iso(e), "ended_by": how, "hours": round((e - s) / 3600, 2)})
    return sorted(rows, key=lambda r: -r["hours"])


def run_of(obj: str | None, primary: str) -> str:
    """对象 id → run：非主 run 带前缀 <run>/<kind>:<shot>（tools/autopilot/runs.obj_id）"""
    o = str(obj or "")
    return o.split("/", 1)[0] if "/" in o else primary


def by_run(events: list[dict], t0: float) -> dict:
    """24 小时内按 run 分开的出图量：rendered 次数、被收下（没被回滚作废）的次数、GPU 执行秒数、出过图的镜数"""
    from tools.autopilot import runs as RUNS
    prim = RUNS.primary_run()
    void = {(e.get("obj"), e.get("take")) for e in events if e.get("ev") == "master_reject" and any(w in str(e.get("reason") or "") for w in VOID_WORDS)}
    out: dict = {}
    seen = set()
    for e in events:
        if e.get("ev") != "rendered" or (e.get("t") or 0) < t0:
            continue
        k = (e.get("obj"), e.get("take"), e.get("lane"))
        if k in seen:                                        # 笔记本日志与服务器日志可能各记一次
            continue
        seen.add(k)
        r = out.setdefault(run_of(e.get("obj"), prim), {"renders": 0, "kept": 0, "gpu_h": 0.0, "shots": set()})
        r["renders"] += 1
        r["kept"] += 0 if (e.get("obj"), e.get("take")) in void else 1
        r["gpu_h"] += float(e.get("gpu_s") or 0) / 3600
        r["shots"].add(e.get("obj"))
    for r in out.values():
        r["gpu_h"] = round(r["gpu_h"], 2)
        r["shots"] = len(r["shots"])
    for run in RUNS.list_runs(status=None):
        out.setdefault(run, {"renders": 0, "kept": 0, "gpu_h": 0.0, "shots": 0})
    return out


VLM_SRC = {"gpu36:2": ("gpu36", 2), "laptop:4080": ("laptop", 0)}
VLM_BUSY_UTIL = 5          # nvidia-smi 利用率 ≥ 5% 视为在跑看图


def vlm_from_samples(card: str, t0: float, t1: float, path: Path | None = None) -> dict:
    """VLM 卡按 SENTINEL 的 nvidia-smi 采样算（data/sentinel/gpu_samples.jsonl，每拍一条）：采样点前后 45 s 内的格按利用率归
    “真正在跑 / 等待任务”，没有采样覆盖的格 = 无数据——采样攒满 24 小时后自动全覆盖（总调度 04:1x）。VLM 卡不区分空跑（没有产出登记可对）"""
    host, idx = VLM_SRC[card]
    n = int((t1 - t0) // STEP)
    cls = ["no_data"] * n
    p = path or ROOT / "data/sentinel/gpu_samples.jsonl"
    m = 0
    if p.exists():
        for ln in p.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                d = json.loads(ln)
            except ValueError:  # arch-ok: 半行跳过
                continue
            if d.get("host") != host or not (t0 - 45 <= d.get("t", 0) <= t1):
                continue
            u = next((x[1] for x in d.get("smi") or [] if x[0] == idx), None)
            if u is None or u < 0:
                continue
            m += 1
            b = "productive" if u >= VLM_BUSY_UTIL else "waiting"
            for i in range(max(0, int((d["t"] - 45 - t0) // STEP)), min(n, int((d["t"] + 45 - t0) // STEP) + 1)):
                if cls[i] == "no_data" or b == "productive":
                    cls[i] = b
    out = {b: 0 for b in BUCKETS}
    for c in cls:
        out[c] += STEP
    out["no_data"] += int((t1 - t0) - n * STEP)
    out["samples"] = m
    out["note"] = f"按 nvidia-smi 采样（{m} 个点，利用率 ≥ {VLM_BUSY_UTIL}% = 在跑）；没有采样的时段 = 无数据，攒满 24 小时自动全覆盖"
    out["waiting_reasons"] = {r: 0 for r in WAIT_REASONS}
    return out


def write(res: dict) -> Path:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, OUT)
    return OUT


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    r = build()
    write(r)
    for k, c in r["cards"].items():
        print(k, "  ".join(f"{ZH[b]} {c[b] / 3600:.1f}h({c['pct'][b]}%)" for b in BUCKETS), c.get("history_from") or "")
    print("合计", r["totals"]["pct"], "errors", r["errors"])
