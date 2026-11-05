#!/usr/bin/env python
"""一集的分段计时瀑布图（PLAN_EP01_FINISH 阶段 0.1）。

用法：
  python tools/master/episode_timeline.py --run series10_v2 --episode 1 \
      --since 2026-11-04T18:04 --until 2026-11-04T22:53 \
      --since 2026-11-05T09:01 --until 2026-11-05T10:12 [--fetch]

--since/--until 可重复（成对），每对一个窗口。--fetch 时经 ssh 只读拉服务器日志到
data/metrics/timeline_cache/，否则读缓存。输出：
  data/metrics/<run>/ep<NN>_timeline.json 和 data/review_pages/metrics/ep<NN>_timeline.html（纯 SVG）。

时间全部是 JST 朴素时间。口径（读结果前必看）：
  * 机器在算 = 出图道 render 区间 + 视频道 SUBMIT→DONE + 后期（超分 / 合成 / 导演 / BGM）区间的并集；
    “检测在算”= 仅看图实例（route.jsonl）在忙而无生成在算。
  * 其余时间按优先级归类：部署重启 > 冻结暂停 > 代码错误 > 等人工 > 等检测 > 同步 > 无活。
  * 关键路径 = 从最后完成的段反向追：同镜或同道上最近结束的前驱，缺口归类为等待段。
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "metrics" / "timeline_cache"

WAIT_CLASSES = ["部署重启", "冻结暂停", "代码错误", "等人工", "等检测", "同步", "无活"]
VERDICT_EVS = {"passed", "content_fail", "redo_fail", "best_effort", "redo_auto_approved",
               "score_infra", "score_timeout"}
HUMAN_EVS = {"best_effort", "hard_cap", "master_reject", "uncap", "adult_wait_owner"}
POST_STAGES = [("EP_RESOLVED", "解析/代理"), ("proxies", "解析/代理"), ("upscale", "超分"),
               ("assemble", "合成"), ("director", "导演评分"), ("BGM_LIB", "报告/BGM")]

STAGE_COLOR = {
    "首帧等待": "#d9d9d9", "首帧准备": "#bcd7f5", "首帧出图": "#2f7ed8", "首帧检测": "#f5a623",
    "尾帧等待": "#d9d9d9", "尾帧准备": "#bcd7f5", "尾帧出图": "#5aa9e6", "尾帧检测": "#f8c471",
    "视频排队": "#d9d9d9", "视频生成": "#2e9d5b", "视频打分": "#9bd3ae",
    "解析/代理": "#8e6bbf", "超分": "#b08fd8", "合成": "#6a3d9a", "导演评分": "#9a7fc4", "报告/BGM": "#c9b8e4",
}
CLASS_COLOR = {"计算": "#2e9d5b", "检测在算": "#f5a623", "部署重启": "#c0392b", "冻结暂停": "#7f8c8d",
               "代码错误": "#e74c3c", "等人工": "#8e44ad", "等检测": "#f1c40f", "同步": "#16a085", "无活": "#ecf0f1"}


# ---------------------------------------------------------------- 时间工具
def pt(s: str) -> datetime:
    s = s.replace(" ", "T")
    if len(s) == 16:
        s += ":00"
    return datetime.fromisoformat(s)


def secs(a: datetime, b: datetime) -> float:
    return (b - a).total_seconds()


def hms(sec: float) -> str:
    sec = int(round(sec))
    return f"{sec // 3600}:{sec % 3600 // 60:02d}:{sec % 60:02d}" if sec >= 3600 else f"{sec // 60}:{sec % 60:02d}"


# ---------------------------------------------------------------- 拉取
def _load(rel: str, name: str):
    import importlib.util
    sp = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


def fetch(run: str) -> None:
    """只读：经统一远程接口 rssh.run_retry 拉服务器日志到缓存（写 .part 再改名）"""
    rssh = _load("tools/netfix/rssh.py", "rssh_tl")
    pp = _load("tools/master/partial_pull.py", "partial_pull_tl")
    CACHE.mkdir(parents=True, exist_ok=True)
    jobs = [("gpu33", f"data/producer/runs/{run}/log.jsonl", "producer_log.jsonl"),
            ("gpu33", "data/vqa/route.jsonl", "route.jsonl"),
            ("gpu36", f"data/pipeline/runs/{run}/video/vidgen_gpu36.log", "vidgen_gpu36.log"),
            ("gpu36", f"data/pipeline/runs/{run}/video/night.log", "night.log")]
    for host, rel, name in jobs:
        r = rssh.run_retry(host, f"cd {pp.remote_root(host)} && cat {rel}", timeout=180, tries=2)
        if r.returncode != 0:
            print(f"[fetch] {name} 失败 rc={r.returncode}：{(r.stderr or b'')[:200]!r}", file=sys.stderr)
            continue
        tmp = CACHE / (name + ".part")
        tmp.write_bytes(r.stdout)
        os.replace(tmp, CACHE / name)


# ---------------------------------------------------------------- 解析器
def read_jsonl(path: Path) -> list[dict]:
    out = []
    if not path.exists():
        return out
    for ln in path.read_text(encoding="utf-8", errors="replace").splitlines():
        ln = ln.strip()
        if ln.startswith("{"):
            try:
                out.append(json.loads(ln))
            except ValueError:  # arch-ok: 日志可能在写入中被截断，坏行跳过（只丢最后一行）
                pass
    return out


def parse_producer(rows: list[dict], episode: int) -> dict:
    """返回 {'segs': [...], 'events': [...(ts, ev, obj, d)]}。segs 含首/尾帧各阶段。"""
    tag = f"ep{episode:02d}-S"
    rows = sorted([r for r in rows if "ts" in r], key=lambda r: r["ts"])
    segs: list[dict] = []
    events: list[dict] = []
    last_verdict: dict[str, datetime] = {}
    disp: dict[str, dict] = {}
    pending: dict[str, dict] = {}
    for r in rows:
        ev, obj, ts = r.get("ev"), r.get("obj") or "", pt(r["ts"])
        if obj and tag not in obj and f"ep{episode:02d}" not in obj:
            continue  # 其它集的事件（如 adult_wait_owner）不计入本集
        events.append({"ts": ts, "ev": ev, "obj": obj, "d": r})
        if tag not in obj or ":" not in obj:
            continue
        kind, sid = obj.split(":", 1)  # first / last
        if kind not in ("first", "last"):
            continue
        shot = sid.replace(f"ep{episode:02d}-", "")
        pre = "首帧" if kind == "first" else "尾帧"
        if ev == "dispatch":
            disp[obj] = {"ts": ts, "lane": r.get("lane"), "attempt": r.get("attempt"), "redo": r.get("redo")}
        elif ev == "rendered":
            rs = float(r.get("render_s") or r.get("secs") or 0)
            start = ts - timedelta(seconds=rs)
            d = disp.get(obj)
            lane = r.get("lane") or (d or {}).get("lane")
            at = (d or {}).get("attempt")
            if d:
                prev = last_verdict.get(obj)
                wstart = prev if prev and prev < d["ts"] else None
                segs.append({"shot": shot, "stage": pre + "等待", "start": wstart, "end": d["ts"], "lane": None,
                             "attempt": at, "open_start": wstart is None})
                if d["ts"] < start:
                    segs.append({"shot": shot, "stage": pre + "准备", "start": d["ts"], "end": start, "lane": lane, "attempt": at})
            segs.append({"shot": shot, "stage": pre + "出图", "start": start, "end": ts, "lane": lane, "attempt": at,
                         "take": r.get("take"), "gpu_s": r.get("gpu_s")})
            pending[obj] = {"ts": ts, "take": r.get("take"), "attempt": at}
        elif ev in VERDICT_EVS:
            p = pending.pop(obj, None)
            last_verdict[obj] = ts
            if p:
                segs.append({"shot": shot, "stage": pre + "检测", "start": p["ts"], "end": ts, "lane": "检测",
                             "attempt": p["attempt"], "verdict": ev, "contract_s": r.get("contract_s")})
        elif ev == "master_approve":
            last_verdict[obj] = ts
    return {"segs": segs, "events": events}


def parse_route(rows: list[dict]) -> list[tuple[datetime, datetime, str]]:
    out = []
    for r in rows:
        try:
            end = pt(r["at"])
            ms = float(r.get("ms") or 0)
        except (KeyError, ValueError):
            continue
        if r.get("kind") == "ask" and ms < 1000:
            continue
        out.append((end - timedelta(milliseconds=ms), end, str(r.get("route"))))
    return out


def _date_rolling(lines: list[str], start_date: str, rx: re.Pattern):
    d = datetime.fromisoformat(start_date)
    prev = None
    for ln in lines:
        m = rx.match(ln)
        if not m:
            continue
        hh, mm, ss = int(m.group(1)), int(m.group(2)), int(m.group(3))
        tod = hh * 3600 + mm * 60 + ss
        if prev is not None and tod < prev - 600:
            d += timedelta(days=1)
        prev = tod
        yield d + timedelta(seconds=tod), ln[m.end():].strip()


def parse_video(lines: list[str], start_date: str) -> dict:
    """vidgen_gpu36.log（只有时分秒，按回绕推日期）。返回 jobs 与 pass 时间。"""
    rx = re.compile(r"^(\d\d):(\d\d):(\d\d) ")
    jobs: dict[tuple, dict] = {}
    for ts, rest in _date_rolling(lines, start_date, rx):
        p = rest.split()
        if len(p) < 3:
            continue
        op, shot, ver = p[0], p[1], p[2]
        key = (shot, ver)
        if op == "SUBMIT":
            jobs[key] = {"shot": shot, "ver": ver, "submit": ts, "lane": p[5] if len(p) > 5 else "?"}
        elif op == "DONE" and key in jobs:
            jobs[key]["done"] = ts
            m = re.search(r"([\d.]+)s\s*$", rest)
            jobs[key]["gen_s"] = float(m.group(1)) if m else None
            jobs[key]["lane"] = p[3] if len(p) > 3 else jobs[key]["lane"]
        elif op == "SCORE" and key in jobs:
            jobs[key]["score"] = ts
            jobs[key]["verdict"] = p[3] if len(p) > 3 else "?"
    return jobs


def parse_night(lines: list[str], start_date: str) -> list[dict]:
    d0 = datetime.fromisoformat(start_date)
    rx = re.compile(r"^(\d\d)-(\d\d) (\d\d):(\d\d):(\d\d) (\S+)(?: (\S+))?")
    out = []
    for ln in lines:
        m = rx.match(ln)
        if not m:
            continue
        mo, da, hh, mi, ss = (int(m.group(i)) for i in range(1, 6))
        ts = datetime(d0.year, mo, da, hh, mi, ss)
        out.append({"ts": ts, "ev": m.group(6), "arg": m.group(7), "line": ln[:200]})
    return out


def parse_channel(text: str, year: int) -> list[dict]:
    out = []
    for ln in text.splitlines():
        m = re.match(r"^(\d\d)-(\d\d) (\d\d):([0-9x])[0-9x]?\(JST\) \| (\S+) \| (\S+) \| (.*)", ln)
        if not m or m.group(5) != "PS-MASTER":
            continue
        mi = int(m.group(4)) * 10 + 5 if m.group(4) != "x" else 30
        try:
            ts = datetime(year, int(m.group(1)), int(m.group(2)), int(m.group(3)), min(mi, 59))
        except ValueError:
            continue
        out.append({"ts": ts, "kind": m.group(6), "text": m.group(7)[:90]})
    return out


# ---------------------------------------------------------------- 视频 / 后期段
def build_video_segs(jobs: dict, first_pass: dict[str, datetime]) -> list[dict]:
    segs = []
    for (shot, ver), j in jobs.items():
        if "done" not in j:
            continue
        s = shot.replace("ep01-", "").split("-")[-1] if "-S" in shot else shot
        s = "S" + shot.split("-S")[-1]
        fp = first_pass.get(s)
        if fp and fp < j["submit"] and ver == "v1":
            segs.append({"shot": s, "stage": "视频排队", "start": fp, "end": j["submit"], "lane": None, "attempt": ver})
        segs.append({"shot": s, "stage": "视频生成", "start": j["submit"], "end": j["done"], "lane": j["lane"], "attempt": ver})
        if "score" in j:
            segs.append({"shot": s, "stage": "视频打分", "start": j["done"], "end": j["score"], "lane": "检测", "attempt": ver,
                         "verdict": j.get("verdict")})
    return segs


def build_post_segs(night: list[dict], since: datetime, until: datetime) -> list[dict]:
    names = {n for n, _ in POST_STAGES} | {"REOPEN"}
    ev = [e for e in night if e["ev"] in names and since <= e["ts"] <= until + timedelta(minutes=2)]
    stage_of = dict(POST_STAGES)
    segs, anchor = [], None
    for e in ev:
        if e["ev"] in ("REOPEN", "EP_RESOLVED"):
            if anchor is None or e["ev"] == "REOPEN" or True:
                anchor = anchor if anchor and (e["ts"] - anchor).total_seconds() < 5 else e["ts"]
            if e["ev"] == "EP_RESOLVED":
                last = e["ts"]
            continue
        if anchor is None:
            continue
        cur = e["ts"]
        if cur > anchor:
            segs.append({"shot": "合成", "stage": stage_of[e["ev"]], "start": anchor, "end": cur, "lane": "gpu36:post", "attempt": None})
            anchor = cur
        if e["ev"] == "BGM_LIB":
            anchor = None
    return segs


# ---------------------------------------------------------------- 状态切片
def classify(window: tuple[datetime, datetime], segs: list[dict], route: list, events: list[dict],
             night: list[dict], imports: list[dict]) -> dict:
    t0, t1 = window
    n = int(secs(t0, t1))
    comp = bytearray(n)       # 生成在算
    det = bytearray(n)        # 检测在算
    cls = [None] * n

    def fill(arr, a, b, val=1):
        a = max(0, int(secs(t0, a)))
        b = min(n, int(secs(t0, b)) + 1)
        for i in range(a, b):
            arr[i] = val

    for s in segs:
        if s["stage"] in ("首帧出图", "尾帧出图", "视频生成") or s["lane"] == "gpu36:post":
            fill(comp, s["start"], s["end"])
    for a, b, _ in route:
        if b >= t0 and a <= t1:
            fill(det, a, b)

    # 各类等待区间
    pri = {k: bytearray(n) for k in WAIT_CLASSES}
    evs = events
    # 暂停 / 重启
    open_pause = None
    for e in evs:
        d = e["d"]
        if e["ev"] == "pause":
            exp = pt(d["expires_at"]) if d.get("expires_at") else None
            open_pause = (e["ts"], exp, d.get("reason_kind"))
            end = exp or t1
            nxt = next((x["ts"] for x in evs if x["ev"] == "resume" and x["ts"] > e["ts"]), None)
            if nxt and nxt < end:
                end = nxt
            fill(pri["部署重启" if d.get("reason_kind") == "restart" else "冻结暂停"], e["ts"], end)
        elif e["ev"] == "pause_shots":
            # 到期时间 expires_at；被后一条 pause_shots（如“解除”）取代则提前结束
            end = pt(d["expires_at"]) if d.get("expires_at") else t1
            nxt = next((x["ts"] for x in evs if x["ev"] == "pause_shots" and x["ts"] > e["ts"]), None)
            if nxt and nxt < end:
                end = nxt
            fill(pri["冻结暂停"], e["ts"], min(end, t1))
        elif e["ev"] == "runaway_hold":
            nxt = next((x["ts"] for x in evs if x["ev"] == "dispatch" and x["obj"] == e["obj"] and x["ts"] > e["ts"]), t1)
            fill(pri["冻结暂停"], e["ts"], nxt)
        elif e["ev"] in ("code_error", "content_error"):
            nxt = next((x["ts"] for x in evs if x["ev"] == "dispatch" and x["obj"] == e["obj"] and x["ts"] > e["ts"]), None)
            end = min(nxt, e["ts"] + timedelta(minutes=15)) if nxt else e["ts"] + timedelta(minutes=15)
            fill(pri["代码错误"], e["ts"], end)
        elif e["ev"] in HUMAN_EVS:
            nxt = next((x["ts"] for x in evs if x["ev"] == "dispatch" and x["obj"] == e["obj"] and x["ts"] > e["ts"]), None)
            fill(pri["等人工"], e["ts"], min(nxt or t1, e["ts"] + timedelta(minutes=30)))
        elif e["ev"] in ("score_backlog", "rescore_timeout", "rescore_busy", "score_timeout", "score_chain_down"):
            fill(pri["等检测"], e["ts"], e["ts"] + timedelta(seconds=60))
    for s in segs:
        if s["stage"] in ("首帧检测", "尾帧检测", "视频打分"):
            fill(pri["等检测"], s["start"], s["end"])
    fail_from = None
    for e in night:
        m = re.search(r"assemble \S+ (\d+)", e["line"])
        if e["ev"] == "assemble" and m and m.group(1) != "0":
            fail_from = fail_from or e["ts"]
        elif e["ev"] in ("REOPEN",) or (e["ev"] == "assemble" and m and m.group(1) == "0"):
            if fail_from:
                fill(pri["代码错误"], fail_from, e["ts"])
            fail_from = None
    if fail_from:
        fill(pri["代码错误"], fail_from, t1)
    for e in night:
        if e["ev"] == "push":
            fill(pri["同步"], e["ts"] - timedelta(seconds=20), e["ts"] + timedelta(seconds=20))
    for r in imports:
        try:
            ts = pt(r["at"])
        except (KeyError, ValueError):
            continue
        fill(pri["同步"], ts - timedelta(seconds=30), ts + timedelta(seconds=30))

    tot = {"计算": 0, "检测在算": 0, **{k: 0 for k in WAIT_CLASSES}}
    for i in range(n):
        if comp[i]:
            c = "计算"
        elif det[i]:
            c = "检测在算"
        else:
            c = "无活"
            for k in WAIT_CLASSES:
                if pri[k][i]:
                    c = k
                    break
        cls[i] = c
    # 无活段若紧接着出现“人工触发”（总调度驳回 / 导入 / 解除暂停），说明在等人工下令
    trig = [e["ts"] for e in events if (e["ev"] in ("master_reject", "uncap", "pause_shots", "master_approve")
            and "VQAGATE" not in str(e["d"].get("by")))] + [pt(r["at"]) for r in imports if r.get("at")]
    i = 0
    while i < n:
        if cls[i] != "无活":
            i += 1
            continue
        j = i
        while j < n and cls[j] == "无活":
            j += 1
        end = t0 + timedelta(seconds=j)
        if any(abs(secs(end, x)) <= 180 and x >= t0 + timedelta(seconds=i) for x in trig):
            for k in range(i, j):
                cls[k] = "等人工"
        i = j
    for c in cls:
        tot[c] += 1
    return {"cls": cls, "totals": tot, "n": n}


def class_of_interval(sl: dict, t0: datetime, a: datetime, b: datetime) -> str:
    """缺口主因：切片里占时最长的类别；“计算”→排队（别处在占用）。"""
    cnt: dict[str, int] = {}
    lo, hi = max(0, int(secs(t0, a))), min(sl["n"], int(secs(t0, b)))
    for i in range(lo, hi):
        cnt[sl["cls"][i]] = cnt.get(sl["cls"][i], 0) + 1
    if not cnt:
        return "无活"
    k = max(cnt, key=cnt.get)
    return {"计算": "排队(别处占用)", "检测在算": "等检测"}.get(k, k)


# ---------------------------------------------------------------- 关键路径
def critical_path(segs: list[dict], t0: datetime, sl: dict, tol: float = 90.0) -> list[dict]:
    real = [s for s in segs if s["stage"] not in ("首帧等待", "尾帧等待", "视频排队") and s["start"] and s["end"] > s["start"]]
    if not real:
        return []
    cur = max(real, key=lambda s: s["end"])
    path = [cur]
    while True:
        cand = []
        for s in real:
            if s is cur or s["end"] > cur["start"] + timedelta(seconds=5):
                continue
            same = (s["shot"] == cur["shot"]) or (s["lane"] and s["lane"] == cur["lane"] and s["lane"] not in ("检测",)) \
                or cur["shot"] == "合成"
            if cur["shot"] == "合成" and s["shot"] == "合成" and s["end"] > cur["start"]:
                continue
            if same:
                cand.append(s)
        if not cand:
            break
        nxt = max(cand, key=lambda s: s["end"])
        gap = secs(nxt["end"], cur["start"])
        if gap > 5:
            path.append({"shot": "-", "stage": "等待:" + class_of_interval(sl, t0, nxt["end"], cur["start"]),
                         "start": nxt["end"], "end": cur["start"], "lane": None, "wait": True})
        path.append(nxt)
        cur = nxt
    path.reverse()
    return path


# ---------------------------------------------------------------- 汇总
def lane_busy(segs: list[dict], t0: datetime, t1: datetime) -> dict:
    by: dict[str, list] = {}
    for s in segs:
        if s["stage"] in ("首帧出图", "尾帧出图", "视频生成") and s.get("lane"):
            by.setdefault(s["lane"], []).append((max(s["start"], t0), min(s["end"], t1)))
        elif s.get("lane") == "gpu36:post":
            by.setdefault("gpu36:post", []).append((max(s["start"], t0), min(s["end"], t1)))
    total = secs(t0, t1)
    out = {}
    for lane, iv in by.items():
        iv = sorted(x for x in iv if x[1] > x[0])
        busy, cur_a, cur_b = 0.0, None, None
        for a, b in iv:
            if cur_b is None or a > cur_b:
                if cur_b is not None:
                    busy += secs(cur_a, cur_b)
                cur_a, cur_b = a, b
            else:
                cur_b = max(cur_b, b)
        if cur_b is not None:
            busy += secs(cur_a, cur_b)
        out[lane] = {"busy_s": round(busy), "util": round(busy / total, 4) if total else 0, "intervals": [[a.isoformat(), b.isoformat()] for a, b in iv]}
    return out


def analyze(window, src, episode) -> dict:
    t0, t1 = window
    segs_all = src["prod"]["segs"]
    first_pass: dict[str, datetime] = {}
    for e in src["prod"]["events"]:
        if e["ev"] in ("passed", "redo_auto_approved", "master_approve") and e["obj"].startswith("first:"):
            first_pass[e["obj"].split("-")[-1]] = e["ts"]
    vsegs = build_video_segs(src["video"], first_pass)
    psegs = build_post_segs(src["night"], t0, t1)
    allsegs = []
    for s in segs_all + vsegs + psegs:
        if s["end"] < t0 or (s["start"] or s["end"]) > t1:
            continue
        s = dict(s)
        if s["start"] is None:
            s["start"] = t0
        s["start"] = max(s["start"], t0)
        s["end"] = min(s["end"], t1)
        if s["end"] > s["start"]:
            allsegs.append(s)
    sl = classify(window, allsegs, src["route"], src["prod"]["events"], src["night"], src["imports"])
    cp = critical_path(allsegs, t0, sl)
    tot = sl["totals"]
    n = sl["n"] or 1
    pct = {k: round(v / n * 100, 1) for k, v in tot.items()}
    cp_by = {}
    for s in cp:
        cp_by[s["stage"]] = cp_by.get(s["stage"], 0) + secs(s["start"], s["end"])
    top = sorted(cp, key=lambda s: -secs(s["start"], s["end"]))[:5]
    n_attempt = {}
    for s in allsegs:
        if s["stage"] in ("首帧出图", "尾帧出图"):
            n_attempt[s["shot"] + ("F" if s["stage"][0] == "首" else "L")] = n_attempt.get(s["shot"] + ("F" if s["stage"][0] == "首" else "L"), 0) + 1
    detect = [secs(s["start"], s["end"]) for s in allsegs if s["stage"] in ("首帧检测", "尾帧检测")]
    render = [secs(s["start"], s["end"]) for s in allsegs if s["stage"] in ("首帧出图", "尾帧出图")]
    med = lambda v: sorted(v)[len(v) // 2] if v else None  # noqa: E731
    human = [c for c in src["channel"] if t0 <= c["ts"] <= t1]
    return {
        "since": t0.isoformat(), "until": t1.isoformat(), "total_s": round(secs(t0, t1)),
        "seconds_by_class": tot, "percent_by_class": pct,
        "compute_pct": pct["计算"], "wait_pct": round(sum(pct[k] for k in WAIT_CLASSES), 1),
        "lanes": lane_busy(allsegs, t0, t1),
        "render_count": len(render), "render_median_s": med(render), "detect_count": len(detect), "detect_median_s": med(detect),
        "renders_per_frame": n_attempt,
        "critical_path": [{"shot": s["shot"], "stage": s["stage"], "lane": s.get("lane"), "start": s["start"].isoformat(),
                           "end": s["end"].isoformat(), "dur_s": round(secs(s["start"], s["end"]), 1)} for s in cp],
        "critical_path_by_stage_s": {k: round(v) for k, v in sorted(cp_by.items(), key=lambda kv: -kv[1])},
        "top5_critical": [{"shot": s["shot"], "stage": s["stage"], "dur_s": round(secs(s["start"], s["end"]), 1),
                           "start": s["start"].isoformat()} for s in top],
        "human_markers": [{"ts": c["ts"].isoformat(), "kind": c["kind"], "text": c["text"]} for c in human],
        "segments": [{"shot": s["shot"], "stage": s["stage"], "lane": s.get("lane"), "attempt": s.get("attempt"),
                      "start": s["start"].isoformat(), "end": s["end"].isoformat(), "verdict": s.get("verdict")} for s in allsegs],
        "class_runs": _runs(sl, t0),
    }


def _runs(sl: dict, t0: datetime) -> list[list]:
    runs, prev, st = [], None, 0
    for i, c in enumerate(sl["cls"] + [None]):
        if c != prev:
            if prev is not None:
                runs.append([st, i, prev])
            prev, st = c, i
    return runs


# ---------------------------------------------------------------- HTML / SVG
def render_html(result: dict, path: Path) -> None:
    W, LBL, RH = 1500, 110, 13
    parts = ["<!doctype html><meta charset=utf-8><title>%s 计时瀑布图</title>"
             "<style>body{font:13px sans-serif;margin:16px}svg{background:#fff;border:1px solid #ccc}"
             "table{border-collapse:collapse}td,th{border:1px solid #ccc;padding:2px 8px}.lg span{display:inline-block;margin-right:12px}"
             ".lg i{display:inline-block;width:12px;height:12px;vertical-align:middle;margin-right:3px}</style>" % html.escape(result["run"] + " ep%02d" % result["episode"])]
    parts.append("<h2>%s ep%02d 分段计时瀑布图</h2>" % (html.escape(result["run"]), result["episode"]))
    lg = "".join(f'<span><i style="background:{c}"></i>{html.escape(k)}</span>' for k, c in STAGE_COLOR.items())
    parts.append(f'<div class=lg>{lg}</div>')
    for w in result["windows"]:
        t0, t1 = pt(w["since"]), pt(w["until"])
        tot = max(1, w["total_s"])
        scale = (W - LBL - 10) / tot
        X = lambda ts: LBL + secs(t0, pt(ts)) * scale if isinstance(ts, str) else LBL + secs(t0, ts) * scale  # noqa: E731
        segs = w["segments"]
        shots = sorted({s["shot"] for s in segs if s["shot"] not in ("合成", "-")}, key=lambda x: int(re.sub(r"\D", "", x) or 0))
        rows = []
        for sh in shots:
            for pre, label in (("首帧", "首帧"), ("尾帧", "尾帧"), ("视频", "视频")):
                rows.append((f"{sh} {label}", lambda s, sh=sh, pre=pre: s["shot"] == sh and s["stage"].startswith(pre)))
        rows.append(("后期", lambda s: s["shot"] == "合成"))
        lanes = sorted(w["lanes"])
        H = 30 + (len(rows) + len(lanes) + 3) * RH + 30
        sv = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" font-size="10">']
        # 时间轴
        step = 600 if tot > 7200 else 300 if tot > 1800 else 60
        k = 0
        while k <= tot:
            x = LBL + k * scale
            sv.append(f'<line x1="{x:.1f}" y1="14" x2="{x:.1f}" y2="{H - 24}" stroke="#eee"/>')
            sv.append(f'<text x="{x:.1f}" y="10" fill="#666">{(t0 + timedelta(seconds=k)).strftime("%H:%M")}</text>')
            k += step
        y = 20
        # 各类别时间线
        sv.append(f'<text x="2" y="{y + 10}">状态</text>')
        for a, b, c in w["class_runs"]:
            sv.append(f'<rect x="{LBL + a * scale:.1f}" y="{y}" width="{max(0.5, (b - a) * scale):.1f}" height="{RH}" fill="{CLASS_COLOR.get(c, "#999")}"><title>{c} {hms(b - a)}</title></rect>')
        y += RH + 2
        for lane in lanes:
            sv.append(f'<text x="2" y="{y + 10}">{html.escape(lane)}</text>')
            for a, b in w["lanes"][lane]["intervals"]:
                sv.append(f'<rect x="{X(a):.1f}" y="{y}" width="{max(0.5, X(b) - X(a)):.1f}" height="{RH - 2}" fill="#2e9d5b"/>')
            y += RH
        y += 4
        for label, pred in rows:
            sv.append(f'<text x="2" y="{y + 10}">{html.escape(label)}</text>')
            for s in segs:
                if pred(s):
                    col = STAGE_COLOR.get(s["stage"], "#999")
                    d = secs(pt(s["start"]), pt(s["end"]))
                    sv.append(f'<rect x="{X(s["start"]):.1f}" y="{y}" width="{max(0.8, d * scale):.1f}" height="{RH - 2}" fill="{col}"><title>{html.escape(s["stage"])} 第{s.get("attempt") or ""}轮 {hms(d)} {html.escape(str(s.get("lane") or ""))} {html.escape(str(s.get("verdict") or ""))}</title></rect>')
            y += RH
        # 关键路径 / 人工
        y += 4
        sv.append(f'<text x="2" y="{y + 10}" fill="#c0392b">关键路径</text>')
        for s in w["critical_path"]:
            col = "#c0392b" if not s["stage"].startswith("等待") else "#f39c12"
            sv.append(f'<rect x="{X(s["start"]):.1f}" y="{y}" width="{max(0.8, X(s["end"]) - X(s["start"])):.1f}" height="{RH - 2}" fill="{col}"><title>{html.escape(s["shot"] + " " + s["stage"])} {hms(s["dur_s"])}</title></rect>')
        y += RH
        sv.append(f'<text x="2" y="{y + 10}" fill="#8e44ad">人工动作</text>')
        for m in w["human_markers"]:
            sv.append(f'<line x1="{X(m["ts"]):.1f}" y1="{y}" x2="{X(m["ts"]):.1f}" y2="{y + RH}" stroke="#8e44ad" stroke-width="2"><title>{html.escape(m["kind"] + " " + m["text"])}</title></line>')
        sv.append("</svg>")
        parts.append(f"<h3>{w['since']} → {w['until']}（{hms(w['total_s'])}）</h3>")
        cl = " ".join(f'<span style="background:{CLASS_COLOR.get(k, "#999")};padding:1px 6px;color:#000">{html.escape(k)} {v}%</span>' for k, v in w["percent_by_class"].items())
        parts.append(f"<p>{cl}</p>")
        parts.append("".join(sv))
        parts.append("<table><tr><th>关键路径最长 5 段</th><th>时长</th><th>起点</th></tr>" +
                     "".join(f"<tr><td>{html.escape(s['shot'] + ' ' + s['stage'])}</td><td>{hms(s['dur_s'])}</td><td>{s['start'][11:16]}</td></tr>" for s in w["top5_critical"]) + "</table>")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(parts), encoding="utf-8")


# ---------------------------------------------------------------- 主程序
def load_sources(run: str, episode: int, video_start: str) -> dict:
    prod = parse_producer(read_jsonl(CACHE / "producer_log.jsonl"), episode)
    route = parse_route(read_jsonl(CACHE / "route.jsonl"))
    vtxt = (CACHE / "vidgen_gpu36.log").read_text(encoding="utf-8", errors="replace").splitlines() if (CACHE / "vidgen_gpu36.log").exists() else []
    ntxt = (CACHE / "night.log").read_text(encoding="utf-8", errors="replace").splitlines() if (CACHE / "night.log").exists() else []
    ch = ROOT / "docs" / "master" / "CHANNEL.md"
    year = int(video_start[:4])
    return {
        "prod": prod, "route": route,
        "video": parse_video(vtxt, video_start),
        "night": parse_night(ntxt, video_start),
        "imports": read_jsonl(ROOT / "data" / "autopilot" / "imports.jsonl"),
        "channel": parse_channel(ch.read_text(encoding="utf-8", errors="replace"), year) if ch.exists() else [],
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", default="series10_v2")
    ap.add_argument("--episode", type=int, default=1)
    ap.add_argument("--since", action="append", required=True)
    ap.add_argument("--until", action="append", required=True)
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--video-start-date", default="2026-11-04", help="vidgen_gpu36.log 首行的日期（日志只有时分秒）")
    ap.add_argument("--out-json")
    ap.add_argument("--out-html")
    a = ap.parse_args(argv)
    if len(a.since) != len(a.until):
        ap.error("--since 与 --until 需成对")
    if a.fetch:
        fetch(a.run)
    src = load_sources(a.run, a.episode, a.video_start_date)
    wins = [analyze((pt(s), pt(u)), src, a.episode) for s, u in zip(a.since, a.until)]
    result = {"run": a.run, "episode": a.episode, "generated_at": datetime.now(timezone(timedelta(hours=9))).isoformat(timespec="seconds"), "windows": wins}
    ep = f"ep{a.episode:02d}"
    oj = Path(a.out_json) if a.out_json else ROOT / "data" / "metrics" / a.run / f"{ep}_timeline.json"
    oh = Path(a.out_html) if a.out_html else ROOT / "data" / "review_pages" / "metrics" / f"{ep}_timeline.html"
    oj.parent.mkdir(parents=True, exist_ok=True)
    tmp = oj.with_suffix(".json.part")
    tmp.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, oj)
    render_html(result, oh)
    for w in wins:
        print(f"== {w['since']} -> {w['until']}  总 {hms(w['total_s'])}")
        print("  占比%:", json.dumps(w["percent_by_class"], ensure_ascii=False))
        print("  道:", {k: f"{v['util'] * 100:.1f}%" for k, v in w["lanes"].items()})
        print("  出图 %d 次 中位 %ss；检测 %d 次 中位 %ss" % (w["render_count"], w["render_median_s"], w["detect_count"], w["detect_median_s"]))
        print("  关键路径按阶段(s):", w["critical_path_by_stage_s"])
        for s in w["top5_critical"]:
            print(f"   top: {s['shot']} {s['stage']} {hms(s['dur_s'])} @{s['start'][11:16]}")
    print(oj, oh)
    return 0


if __name__ == "__main__":
    sys.exit(main())
