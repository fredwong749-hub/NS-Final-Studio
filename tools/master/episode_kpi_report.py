#!/usr/bin/env python
"""每集自动耗时报告（W-KPI 11-06，L-205：一集 ≤ 50 min；每一分钟超预算都归到 逻辑 / 代码 / GPU 调度 / 检测 之一）。

用法：
  .venv/Scripts/python.exe tools/master/episode_kpi_report.py --run series10_v2 --episode 1 [--fetch]
      [--anchor regen|import|first-dispatch] [--start 2026-11-06T14:53] [--until 2026-11-06T20:00] [--profile base|turbo]
      [--raw data/kpi/raw/<run>] [--no-docs] [--quiet]

数据源（只读；--fetch 经 tools/netfix/rssh.run_retry 拉到 data/kpi/raw/<run>/ 缓存，网络抖动按退避重试，拉不到用缓存）：
  gpu33 / gpu36：data/producer/runs/<run>/log.jsonl、<vid>/vidgen_<host>.log、<vid>/night.log、<vid>/state_<host>.json、
                 <vid>/night_state.json、data/vqa/route.jsonl、data/renders/<run>/epNN/S*/takes.json（只取 active / 版本数）
  笔记本：data/producer/runs/<run>/log.jsonl（导入事件）、data/pipeline/idle_watch/events.log、data/brain/decisions.jsonl
集的起点 = 该集最近一次“全集重出 / 导入”之后的第一次派单（--anchor，可用 --start 指定）；之前的尝试只作背景。
输出：data/kpi/<run>/epNN_kpi.json（全量）、data/kpi/<run>/latest.json（给大脑快照的短摘要）、docs/master/KPI_<run>_epNN.md（中文表）。
时间口径：全部 JST 朴素时间（服务器日志 TZ=Asia/Tokyo；epoch 一律按 +09:00 转）。
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JST = timezone(timedelta(hours=9))
CHECKLIST = ROOT / "docs/master/PIPELINE_CHECKLIST.md"
CATS = ("逻辑", "代码", "GPU 调度", "检测")
STAGES = ("import_probe", "first_frames", "last_frames", "videos", "assembly", "delivery")
STAGE_CN = {"import_probe": "导入 / 探针", "first_frames": "首帧", "last_frames": "尾帧", "videos": "视频",
            "assembly": "合成", "delivery": "拉回交付"}
# 清单读不到时的兜底预算（docs/master/PIPELINE_CHECKLIST.md 11-06 版，单位秒）
DEFAULT_BUDGET = {"import_probe": 150, "first_frames": {"turbo": 600, "base": 1200}, "last_frames": 480, "videos": 900,
                  "assembly": 480, "delivery": 180, "switch": 120, "episode": 3000,
                  "per_image": {"turbo": 120, "base": 660}, "score_image": 40, "per_video": 600, "score_video": 60}
SETTLE_EVS = {"passed", "master_approve", "redo_auto_approved", "review_adopt", "best_effort", "hard_cap_exhausted",
              "last_unavailable"}
VERDICT_EVS = {"passed", "content_fail", "redo_fail", "best_effort", "score_infra", "score_timeout", "redo_auto_approved",
               "rescore"}
UNSETTLE_EVS = {"dispatch", "regen", "master_reject", "last_void_reset", "best_effort_reset", "gaze_round", "last_requeued"}
NIGHT_END_EVS = ("RETRO", "BGM_LIB", "report", "director", "FINALIZE_DONE", "HARD_RULES", "assemble")


# ---------------------------------------------------------------- 时间工具
def pt(s: str) -> datetime:
    s = s.strip().replace(" ", "T")
    if len(s) == 16:
        s += ":00"
    d = datetime.fromisoformat(s)
    return d.replace(tzinfo=None) if d.tzinfo is None else d.astimezone(JST).replace(tzinfo=None)


def ep2dt(t: float) -> datetime:
    return datetime.fromtimestamp(float(t), tz=JST).replace(tzinfo=None)


def now_jst() -> datetime:
    return datetime.now(tz=JST).replace(tzinfo=None)


def fmt(d) -> str:
    return d.strftime("%m-%d %H:%M:%S") if isinstance(d, datetime) else "—"


def mins(sec) -> float:
    return round(float(sec) / 60.0, 1) if sec is not None else None


def _load(rel: str, name: str):
    sp = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


# ---------------------------------------------------------------- 预算（清单单一来源）
def parse_budget(text: str | None, profile: str = "base") -> dict:
    """从 PIPELINE_CHECKLIST.md 的清单表读“目标”列；读不到的项用 DEFAULT_BUDGET，并在 notes 里写明"""
    b = {k: (v[profile] if isinstance(v, dict) else v) for k, v in DEFAULT_BUDGET.items()}
    notes = []
    if not text:
        notes.append("清单读不到，预算全用默认表")
        b["notes"] = notes
        return b
    rows = {}
    for ln in text.splitlines():
        m = re.match(r"^\|\s*(\d+)\s*\|", ln)
        if not m:
            continue
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if len(cells) >= 6:
            rows[int(m.group(1))] = cells[5]
    rx = re.compile(r"≤\s*(\d+(?:\.\d+)?)\s*(min|s)")

    def secs_of(cell: str, idx: int = 0):
        ms = rx.findall(cell or "")
        if len(ms) <= idx:
            return None
        v, u = ms[idx]
        return float(v) * (60 if u == "min" else 1)

    def take(key, row, idx=0):
        v = secs_of(rows.get(row, ""), idx)
        if v is None:
            notes.append(f"{key}：清单第 {row} 行没读到“≤ N min”，用默认 {b[key]} s")
        else:
            b[key] = v

    ip = [secs_of(rows.get(r, "")) for r in (1, 2, 3)]
    if all(v is not None for v in ip):
        b["import_probe"] = sum(ip)
    else:
        notes.append(f"import_probe：清单第 1–3 行没读全，用默认 {b['import_probe']} s")
    # 第 4 行：每张 ≤ 2× 预计（turbo 60 s / base35 330 s）；整集 ≤ 10 min（8 步）/ ≤ 20 min（35 步）→ 第 1 个 ≤ 是 turbo，第 2 个是 base
    take("first_frames", 4, 0 if profile == "turbo" else 1)
    m4 = re.search(r"turbo\s*(\d+)\s*s\s*/\s*base\d*\s*(\d+)\s*s", rows.get(4, ""))
    if m4:
        b["per_image"] = 2 * float(m4.group(1) if profile == "turbo" else m4.group(2))
    take("last_frames", 5)
    take("score_image", 6)
    take("switch", 7)
    take("videos", 8)
    m8 = re.search(r"上限\s*(\d+)\s*min", rows.get(8, ""))
    if m8:
        b["per_video"] = float(m8.group(1)) * 60
    take("score_video", 9)
    take("assembly", 11)
    take("delivery", 12)
    m_ep = re.search(r"每集总预算\s*≤\s*(\d+)\s*min", text)
    if m_ep:
        b["episode"] = float(m_ep.group(1)) * 60
    b["profile"] = profile
    b["notes"] = notes
    return b


# ---------------------------------------------------------------- 拉取 / 读取
def source_jobs(run: str, ep: int, hosts=("gpu33", "gpu36")) -> list[tuple[str, str, str]]:
    """(主机, 远端相对路径或命令, 缓存文件名)。命令以 '!' 开头 = 整条 shell 命令（只读）"""
    jobs = []
    renders_rel = _load("tools/autopilot/runs.py", "runs_kpi").renders_dir(run, ROOT).relative_to(ROOT).as_posix()   # K-OPS-F24：渲染根目录只从 runs 取
    takes_glob = f"{renders_rel}/ep{ep:02d}/S*/takes.json"
    py_one = ("import json,sys;d=json.load(open(sys.argv[1]));print(json.dumps({'active':d.get('active'),'n':len(d.get('takes') or []),"
              "'stages':[[t.get('stage'),t.get('n')] for t in d.get('takes') or []]}))")
    for h in hosts:
        vid = f"data/pipeline/runs/{run}/video"
        jobs += [(h, f"data/producer/runs/{run}/log.jsonl", f"{h}__producer_log.jsonl"),
                 (h, f"{vid}/vidgen_{h}.log", f"{h}__vidgen.log"),
                 (h, f"{vid}/night.log", f"{h}__night.log"),
                 (h, f"{vid}/state_{h}.json", f"{h}__state.json"),
                 (h, f"{vid}/night_state.json", f"{h}__night_state.json"),
                 (h, "data/vqa/route.jsonl", f"{h}__route.jsonl"),
                 (h, f"!for f in {takes_glob}; do echo \"=== $f\"; python3 -c \"{py_one}\" \"$f\" 2>/dev/null; done",
                  f"{h}__takes_ep{ep:02d}.txt")]
    return jobs


def fetch(run: str, ep: int, raw: Path, hosts=("gpu33", "gpu36"), tries: int = 3, runner=None, log=print) -> dict:
    """只读拉日志到缓存（写 .part 再 os.replace）；连接层失败按 rssh.run_retry 退避重试，仍失败 → 用旧缓存。返回 {name: rc}"""
    raw.mkdir(parents=True, exist_ok=True)
    if runner is None:
        rssh = _load("tools/netfix/rssh.py", "rssh_kpi")
        hosts_mod = _load("tools/factory/hosts.py", "hosts_kpi")

        def runner(host, cmd):
            root = hosts_mod.server_root(host)
            return rssh.run_retry(host, f"cd {root} && {cmd}", timeout=120, tries=tries, backoff_s=10)
    res = {}
    for host, rel, name in source_jobs(run, ep, hosts):
        cmd = rel[1:] if rel.startswith("!") else f"cat {rel}"
        try:
            r = runner(host, cmd)
            rc, out = r.returncode, r.stdout or b""
        except Exception as e:  # noqa: BLE001  # arch-ok: 拉日志是旁路，任何一项失败只记、用缓存，不能让报告整体失败
            rc, out = 1, repr(e).encode()
        res[name] = rc
        if rc == 0:
            tmp = raw / (name + ".part")
            tmp.write_bytes(out)
            os.replace(tmp, raw / name)
        else:
            log(f"[fetch] {name} rc={rc}（用缓存：{'有' if (raw / name).exists() else '无'}）")
    meta = {"at": now_jst().isoformat(timespec="seconds"), "rc": res}
    tmp = raw / "_fetch.json.part"
    tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, raw / "_fetch.json")
    return res


def read_jsonl(path: Path) -> list[dict]:
    out = []
    if not path or not path.exists():
        return out
    for ln in path.read_text(encoding="utf-8", errors="replace").splitlines():
        ln = ln.strip()
        if ln.startswith("{"):
            try:
                out.append(json.loads(ln))
            except ValueError:  # arch-ok: 日志最后一行可能写了一半，坏行跳过
                pass
    return out


def read_json(path: Path):
    if not path or not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except ValueError:  # arch-ok: 状态文件写入中被截断 → 当没有，报告里写明来源缺失
        return None


def read_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8", errors="replace").splitlines() if path and path.exists() else []


def parse_takes_dump(text: str) -> dict:
    out, cur = {}, None
    for ln in text.splitlines():
        if ln.startswith("=== "):
            m = re.search(r"/(S\d+)/takes\.json", ln)
            cur = m.group(1) if m else None
        elif cur and ln.startswith("{"):
            try:
                out[cur] = json.loads(ln)
            except ValueError:  # arch-ok: 单个镜的账本坏行只影响该镜的版本计数
                pass
    return out


def load_sources(run: str, ep: int, raw: Path, hosts=("gpu33", "gpu36"), laptop: Path | None = None) -> dict:
    lap = laptop or ROOT
    src = {"hosts": list(hosts), "producer": {}, "vidgen": {}, "night": {}, "vstate": {}, "night_state": {}, "route": {},
           "takes": {}, "missing": []}
    for h in hosts:
        for key, name, rd in (("producer", f"{h}__producer_log.jsonl", read_jsonl), ("vidgen", f"{h}__vidgen.log", read_lines),
                              ("night", f"{h}__night.log", read_lines), ("vstate", f"{h}__state.json", read_json),
                              ("night_state", f"{h}__night_state.json", read_json), ("route", f"{h}__route.jsonl", read_jsonl)):
            p = raw / name
            if not p.exists():
                src["missing"].append(name)
            src[key][h] = rd(p)
        tp = raw / f"{h}__takes_ep{ep:02d}.txt"
        src["takes"][h] = parse_takes_dump(tp.read_text(encoding="utf-8", errors="replace")) if tp.exists() else {}
    src["laptop_producer"] = read_jsonl(lap / f"data/producer/runs/{run}/log.jsonl")
    src["idle"] = read_lines(lap / "data/pipeline/idle_watch/events.log")
    src["brain"] = read_jsonl(lap / "data/brain/decisions.jsonl")
    src["local_episodes"] = lap / "data/episodes" / run
    return src


# ---------------------------------------------------------------- 解析：出图机 producer
def merge_producer(src: dict, ep: int) -> list[dict]:
    """两台 + 笔记本的 producer 日志合并、去重、按时间排；只留本集（obj 带 epNN）和控制事件"""
    tag = f"ep{ep:02d}"
    seen, out = set(), []
    for host, rows in list(src["producer"].items()) + [("laptop", src.get("laptop_producer") or [])]:
        for r in rows:
            if "ts" not in r or not r.get("ev"):
                continue
            obj = str(r.get("obj") or "")
            ctl = r["ev"] in ("start", "pause", "resume", "imported_staged", "import_blocked", "lane_roles_phase", "lane_roles_active",
                              "review_scale", "script_reloaded")
            if obj and tag not in obj:
                continue
            if not obj and not ctl:
                continue
            if r["ev"] == "imported_staged" and tag not in str(r.get("path", "")) and ep not in (r.get("episodes") or []):
                continue
            key = (r["ts"], r["ev"], obj, str(r.get("lane")), str(r.get("take")), str(r.get("by")))
            if key in seen:
                continue
            seen.add(key)
            rr = dict(r)
            rr["_host"] = host
            rr["_ts"] = pt(r["ts"])
            out.append(rr)
    out.sort(key=lambda r: r["_ts"])
    return out


def shot_of(obj: str) -> str:
    return obj.split("-", 1)[-1] if "-" in obj else obj


def kind_of(obj: str) -> str:
    return obj.split(":", 1)[0] if ":" in obj else ""


def find_start(rows: list[dict], ep: int, anchor: str, regen_key: str = "全集") -> tuple[datetime | None, dict]:
    """集的起点：anchor=regen → 最近一次“全集重出”（regen / master_reject 带 regen_key）后的第一次派单；
    anchor=import → 最近一次 imported_staged 后的第一次派单；first-dispatch → 日志里第一次派单。返回 (起点, 说明)"""
    disp = [r for r in rows if r["ev"] == "dispatch"]
    info = {"anchor": anchor, "anchor_ts": None, "anchor_ev": None}
    if not disp:
        return None, info
    anc = None
    if anchor == "regen":
        cands = [r for r in rows if r["ev"] in ("regen", "master_reject") and regen_key in str(r.get("reason") or "")]
        anc = cands[-1] if cands else None
    elif anchor == "import":
        cands = [r for r in rows if r["ev"] == "imported_staged"]
        anc = cands[-1] if cands else None
    if anc is not None:
        info.update(anchor_ts=anc["_ts"], anchor_ev=f"{anc['ev']} {anc.get('reason') or anc.get('note') or ''}"[:120])
        after = [r for r in disp if r["_ts"] >= anc["_ts"]]
        if after:
            return after[0]["_ts"], info
        return anc["_ts"], info
    info["anchor_ev"] = "日志里第一次派单" if anchor == "first-dispatch" else f"没找到 {anchor} 锚点，退到第一次派单"
    return disp[0]["_ts"], info


BLOCK_EVS = {"sop_gate_block", "preflight_block", "adult_wait_owner", "hold", "waiting_asset", "import_blocked"}


def frame_attempts(rows: list[dict], start: datetime, until: datetime) -> dict:
    """按 obj（first:epNN-Sk / last:epNN-Sk）整理窗口内的尝试：派单 → 出图 → 结论；以及落定时间 / 状态。
    起点之前的事件只用来定“起点时已定下 / 未定”的状态（如起点前总调度已复核通过的首帧），不计尝试"""
    objs: dict[str, dict] = defaultdict(lambda: {"attempts": [], "events": [], "settled_at": None, "settled_by": None,
                                                 "adult": False, "fallback": None, "blocks": []})
    for r in rows:
        obj = str(r.get("obj") or "")
        if kind_of(obj) not in ("first", "last"):
            if r["ev"] == "adult_wait_owner" and obj:
                objs["first:" + obj.split(":")[-1]]["adult"] = True
            continue
        o = objs[obj]
        if r["ev"] == "adult_wait_owner":
            o["adult"] = True
            continue
        ts = r["_ts"]
        if ts > until:
            continue
        if ts < start:
            if r["ev"] in SETTLE_EVS:
                o["settled_at"], o["settled_by"] = ts, r["ev"] + "（起点前）"
                if r["ev"] == "last_unavailable":
                    o["fallback"] = r.get("fallback") or "i2va"
            elif r["ev"] in UNSETTLE_EVS:
                o["settled_at"], o["settled_by"] = None, None
            continue
        o["events"].append(r)
        if r["ev"] in BLOCK_EVS:
            o["blocks"].append({"ts": ts, "ev": r["ev"], "why": str(r.get("why") or r.get("reasons") or r.get("error") or "")[:120]})
        if r["ev"] == "dispatch":
            o["attempts"].append({"dispatch": ts, "lane": r.get("lane"), "attempt": r.get("attempt"), "rung": r.get("rung"),
                                  "redo": bool(r.get("redo")), "rendered": None, "render_s": None, "gpu_s": None, "take": None,
                                  "verdict": None, "verdict_at": None, "blocking": [], "why": None})
        elif r["ev"] == "rendered":
            a = next((a for a in reversed(o["attempts"]) if a["rendered"] is None), None)
            if a is None:
                a = {"dispatch": None, "lane": r.get("lane"), "attempt": None, "rung": None, "redo": False, "rendered": None,
                     "render_s": None, "gpu_s": None, "take": None, "verdict": None, "verdict_at": None, "blocking": [], "why": None}
                o["attempts"].append(a)
            a.update(rendered=ts, render_s=r.get("render_s") or r.get("secs"), gpu_s=r.get("gpu_s"), take=r.get("take"),
                     lane=r.get("lane") or a["lane"])
        elif r["ev"] in VERDICT_EVS:
            a = next((a for a in reversed(o["attempts"]) if a["rendered"] is not None and a["verdict"] is None), None)
            if a is None and o["attempts"]:
                a = o["attempts"][-1]
            if a is not None:
                a.update(verdict=r["ev"], verdict_at=ts, blocking=list(r.get("blocking") or []), why=(r.get("why") or r.get("error") or r.get("reason") or "")[:160])
                if r.get("contract_s") is not None:
                    a["contract_s"] = r.get("contract_s")
        if r["ev"] in SETTLE_EVS:
            o["settled_at"], o["settled_by"] = ts, r["ev"]
            if r["ev"] == "last_unavailable":
                o["fallback"] = r.get("fallback") or "i2va"
        elif r["ev"] in UNSETTLE_EVS and r["ev"] != "dispatch":
            o["settled_at"], o["settled_by"] = None, None
        elif r["ev"] == "dispatch" and o["settled_at"] is not None and ts > o["settled_at"]:
            o["settled_at"], o["settled_by"] = None, None
        if r["ev"] == "last_unavailable":
            o["fallback_ts"] = ts
    for o in objs.values():
        # 尾帧兜底（L-204 D8 i2va）：之后的重置 / 派单不撤销兜底，除非后来真的定下了一张尾帧
        if o.get("fallback") and o["settled_at"] is None and o.get("fallback_ts"):
            o["settled_at"], o["settled_by"] = o["fallback_ts"], "last_unavailable（兜底）"
    return dict(objs)


# ---------------------------------------------------------------- 解析：视频
def video_jobs(src: dict, ep: int) -> list[dict]:
    """state_<host>.json 的 renders（epoch，准）+ vidgen.log 的 SCORE / SHOT_PASS 时刻（只有时分秒，按 DONE 对齐日期）"""
    tag = f"ep{ep:02d}-"
    jobs = []
    for h, st in (src.get("vstate") or {}).items():
        shots = (st or {}).get("shots") or {}
        for sid, v in shots.items():
            if not sid.startswith(tag):
                continue
            for r in v.get("renders") or []:
                if not r.get("t_sub"):
                    continue
                jobs.append({"host": h, "shot": sid, "ver": r.get("variant"), "lane": r.get("lane"), "recipe": r.get("recipe"),
                             "submit": ep2dt(r["t_sub"]), "done": ep2dt(r["t_done"]) if r.get("t_done") else None,
                             "gpu_s": r.get("gpu_s"), "state": r.get("state"), "first_frame_take": r.get("first_frame_take"),
                             "verdict": ((r.get("score") or {}).get("verdict") if isinstance(r.get("score"), dict) else None),
                             "labels": list((r.get("score") or {}).get("labels") or []) if isinstance(r.get("score"), dict) else [],
                             "score_at": None, "chosen": v.get("chosen"), "shot_status": v.get("status")})
    # vidgen.log：SCORE / SHOT_PASS / SHOT_BEST_EFFORT 时刻
    by_key = {(j["shot"], j["ver"]): j for j in jobs}
    settles = {}
    rx = re.compile(r"^(\d\d):(\d\d):(\d\d) (\S+) (\S+)(?: (\S+))?(.*)$")
    for h, lines in (src.get("vidgen") or {}).items():
        parsed = []
        for ln in lines:
            m = rx.match(ln)
            if m:
                tod = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
                parsed.append((tod, m.group(4), m.group(5), m.group(6), m.group(7) or ""))
        # 日期对齐：DONE 行和 state 里同 (shot, ver) 的 t_done 比时分秒
        anchors = {}
        for i, (tod, op, shot, ver, _rest) in enumerate(parsed):
            j = by_key.get((shot, ver))
            if op == "DONE" and j and j["done"] and abs((j["done"].hour * 3600 + j["done"].minute * 60 + j["done"].second) - tod) <= 180:
                anchors[i] = j["done"].date()
        if not anchors:
            continue
        idxs = sorted(anchors)
        cur_i, cur_date, prev_tod = idxs[0], anchors[idxs[0]], parsed[idxs[0]][0]
        stamped = [None] * len(parsed)
        # 向后
        d, p = cur_date, prev_tod
        for i in range(cur_i, len(parsed)):
            if i in anchors:
                d, p = anchors[i], parsed[i][0]
            elif parsed[i][0] < p - 600:
                d += timedelta(days=1)
            p = parsed[i][0]
            stamped[i] = datetime.combine(d, datetime.min.time()) + timedelta(seconds=parsed[i][0])
        # 向前（锚点之前的行）
        d, p = cur_date, prev_tod
        for i in range(cur_i - 1, -1, -1):
            if parsed[i][0] > p + 600:
                d -= timedelta(days=1)
            p = parsed[i][0]
            stamped[i] = datetime.combine(d, datetime.min.time()) + timedelta(seconds=parsed[i][0])
        for i, (tod, op, shot, ver, rest) in enumerate(parsed):
            if not shot.startswith(tag) or stamped[i] is None:
                continue
            if op == "SCORE" and (shot, ver) in by_key and by_key[(shot, ver)]["score_at"] is None:
                by_key[(shot, ver)]["score_at"] = stamped[i]
                if by_key[(shot, ver)]["verdict"] is None:
                    tok = rest.split()[0] if rest.split() else None
                    by_key[(shot, ver)]["verdict"] = "pass" if tok == "PASS" else tok
            elif op in ("SHOT_PASS", "SHOT_BEST_EFFORT"):
                settles[shot] = {"at": stamped[i], "by": op, "ver": ver, "host": h}
            elif op == "START":
                settles.setdefault("_starts", []).append({"at": stamped[i], "host": h, "line": ln_strip(rest)})
    for j in jobs:
        s = settles.get(j["shot"])
        j["shot_settled_at"] = s["at"] if s else None
        j["shot_settled_by"] = s["by"] if s else None
    jobs.sort(key=lambda j: j["submit"])
    return jobs


def ln_strip(s: str) -> str:
    return " ".join(s.split())[:160]


# ---------------------------------------------------------------- 解析：night（合成）
def night_events(lines: list[str], ep: int, year: int) -> list[dict]:
    tag = f"ep{ep:02d}"
    rx = re.compile(r"^(\d\d)-(\d\d) (\d\d):(\d\d):(\d\d) (\S+)(?: (\S+))?(.*)$")
    out = []
    for ln in lines:
        m = rx.match(ln)
        if not m:
            continue
        ev, arg = m.group(6), m.group(7) or ""
        if arg != tag and ev not in ("RUN", "LANE_ROLES", "FINALIZE_SPAWN_ERR") and not (ev == "register_takes"):
            continue
        try:
            ts = datetime(year, int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5)))
        except ValueError:
            continue
        out.append({"ts": ts, "ev": ev, "arg": arg, "rest": ln_strip(m.group(8)), "line": ln[:240],
                    "full": m.group(8).strip() if ev == "EP_RESOLVED" else None})
    return out


def assembly_cycles(nev: list[dict], start: datetime, until: datetime) -> list[dict]:
    """每个 EP_RESOLVED 起一个合成周期，到下一个 EP_RESOLVED 前最后一个收尾事件（RETRO / report / director …）结束"""
    cycles = []
    for e in nev:
        if e["ts"] < start or e["ts"] > until:
            continue
        if e["ev"] == "EP_RESOLVED":
            resolved = {}
            try:
                import ast
                resolved = ast.literal_eval(e.get("full") or "{}") if (e.get("full") or "").startswith("{") else {}
            except (ValueError, SyntaxError):  # arch-ok: EP_RESOLVED 行被截断 / 格式变了 → 没有逐镜状态，只少“night 落定”这一路判断
                resolved = {}
            cycles.append({"start": e["ts"], "end": None, "end_ev": None, "steps": [], "errors": [], "reopen": None, "final": None,
                           "resolved": resolved if isinstance(resolved, dict) else {}})
        elif cycles:
            c = cycles[-1]
            if e["ev"] in NIGHT_END_EVS:
                c["end"], c["end_ev"] = e["ts"], e["ev"]
            if e["ev"] in ("proxies", "upscale", "assemble", "director", "report", "RETRO", "BGM_LIB", "register_takes", "HARD_RULES",
                           "PLACEHOLDER_SHOTS", "FINALIZE_BG", "FINALIZE_DONE"):
                c["steps"].append({"ts": e["ts"], "ev": e["ev"], "rest": e["rest"][:100]})
            if ("Error" in e["rest"] or "Traceback" in e["rest"] or e["ev"] in ("FINALIZE_NO_RESULT", "FINALIZE_CHILD_ERR")) and e["ev"] != "HARD_RULES":
                c["errors"].append({"ts": e["ts"], "ev": e["ev"], "rest": e["rest"][:160]})
            if e["ev"] == "director":
                m = re.search(r'"post":\s*"([^"]+)"', e["rest"])
                if m:
                    c["final"] = m.group(1)
            if e["ev"] == "REOPEN":
                c["reopen"] = e["ts"]
    return cycles


# ---------------------------------------------------------------- 解析：笔记本
def idle_lane_minutes(lines: list[str], start: datetime, until: datetime) -> dict:
    """idle_watch 每分钟一行：idle=[...] work=readyN/video{...}/assetsN → 每道“空闲且有活”的分钟数 + ACT 行"""
    rx = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\S* idle=(\[[^\]]*\]) work=ready(\d+)/video(\{[^}]*\})")
    per = Counter()
    acts = []
    for ln in lines:
        if not ln[:4].isdigit():
            continue
        try:
            ts = pt(ln[:19])
        except ValueError:
            continue
        if ts < start or ts > until:
            continue
        if " ACT " in ln:
            acts.append({"ts": ts, "text": ln_strip(ln[26:])[:200]})
            continue
        m = rx.match(ln)
        if not m:
            continue
        try:
            idle = json.loads(m.group(2).replace("'", '"'))
            ready = int(m.group(3))
            vid = json.loads(m.group(4).replace("'", '"'))
        except ValueError:  # arch-ok: 某一行格式变了只丢这一分钟的样本
            continue
        for lane in idle:
            host = lane.split(":")[0]
            if ready > 0 or int(vid.get(host, 0) or 0) > 0:
                per[lane] += 1
    return {"lane_minutes": dict(per), "acts": acts}


def brain_actions(rows: list[dict], start: datetime, until: datetime) -> list[dict]:
    out = []
    for r in rows:
        try:
            ts = ep2dt(r["t"]) if r.get("t") else pt(r["at"])
        except (KeyError, ValueError):
            continue
        if start <= ts <= until:
            out.append({"ts": ts, "kind": r.get("kind"), "by": r.get("by"), "dry": r.get("dry"), "result": str(r.get("result") or "")[:100]})
    return out


# ---------------------------------------------------------------- 汇总
def _clip(a: datetime, b: datetime, lo: datetime, hi: datetime) -> float:
    a, b = max(a, lo), min(b, hi)
    return max(0.0, (b - a).total_seconds())


def _union(ivs: list) -> list:
    out = []
    for s, e in sorted(iv for iv in ivs if iv[0] < iv[1]):
        if out and s <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


def _complement(u: list, lo: datetime, hi: datetime) -> list:
    out, cur = [], lo
    for s, e in u:
        if s > cur:
            out.append((cur, s))
        cur = max(cur, e)
    if cur < hi:
        out.append((cur, hi))
    return out


def _overlap_s(u: list, a: datetime, b: datetime) -> float:
    return sum(_clip(s, e, a, b) for s, e in u)


def _alloc(total_min: float, weights: dict) -> dict:
    """把超预算分钟按证据权重分到四类（最大余数法，和 = total）；没证据 → 逻辑（流程等待），并在 evidence 里写明"""
    total = int(round(total_min))
    if total <= 0:
        return {c: 0 for c in CATS}
    w = {c: max(0.0, float(weights.get(c, 0))) for c in CATS}
    if sum(w.values()) <= 0:
        return {c: (total if c == "逻辑" else 0) for c in CATS}
    raw = {c: total * w[c] / sum(w.values()) for c in CATS}
    out = {c: int(raw[c]) for c in CATS}
    rem = total - sum(out.values())
    for c in sorted(CATS, key=lambda c: raw[c] - out[c], reverse=True)[:rem]:
        out[c] += 1
    return out


def analyze(src: dict, run: str, ep: int, start: datetime | None, until: datetime, budget: dict, anchor_info: dict,
            rows: list[dict] | None = None) -> dict:
    rows = rows if rows is not None else merge_producer(src, ep)
    year = until.year
    res = {"run": run, "episode": ep, "generated_at": now_jst().isoformat(timespec="seconds"), "start": start, "until": until,
           "anchor": anchor_info, "budget": budget, "missing_sources": src.get("missing", [])}
    if start is None:
        res["error"] = "日志里没有本集派单，无法定起点"
        return res
    lanes = sorted({r.get("lane") for r in rows if r["ev"] == "dispatch" and r.get("lane")} |
                   set(next((r.get("lanes") for r in reversed(rows) if r["ev"] == "start" and r.get("lanes")), []) or []))
    objs = frame_attempts(rows, start, until)
    vjobs = video_jobs(src, ep)
    # ---- 镜头集合（非成人）
    shots_all = sorted({shot_of(o.split(":", 1)[1]) for o in objs} | {j["shot"].split("-", 1)[1] for j in vjobs}, key=lambda s: int(re.sub(r"\D", "", s) or 0))
    adult = {shot_of(o.split(":", 1)[1]) for o, v in objs.items() if v["adult"]}
    shots = [s for s in shots_all if s not in adult]
    # ---- 阶段
    stages: dict[str, dict] = {}
    ctx_imports = [r for r in rows if r["ev"] == "imported_staged" and r["_ts"] <= start]
    imp_ts = ctx_imports[-1]["_ts"] if ctx_imports else anchor_info.get("anchor_ts")
    stages["import_probe"] = {"start": imp_ts, "end": start, "status": "done" if imp_ts else "unknown",
                              "note": (f"导入 {fmt(imp_ts)}（{(ctx_imports[-1].get('note') or '')[:60]}）→ 第一次派单 {fmt(start)}" if ctx_imports
                                       else f"没有导入事件；锚点 {anchor_info.get('anchor_ev')}")}

    def settle_stage(kind: str, first_dispatch_after: datetime | None):
        ks = {o: v for o, v in objs.items() if kind_of(o) == kind and shot_of(o.split(":", 1)[1]) in shots}
        dis = [a["dispatch"] for v in ks.values() for a in v["attempts"] if a["dispatch"]]
        st = min(dis) if dis else None
        if first_dispatch_after and st and st < first_dispatch_after:
            st = first_dispatch_after
        settled = {o: v["settled_at"] for o, v in ks.items() if v["settled_at"]}
        pending = [o for o in ks if o not in settled] + [f"{kind}:ep{ep:02d}-{s}" for s in shots if f"{kind}:ep{ep:02d}-{s}" not in ks]
        done = bool(ks) and not pending
        end = max(settled.values()) if done else None
        return {"start": st, "end": end, "status": "done" if done else ("running" if st else "not_started"),
                "settled": len(settled), "total": len(shots), "pending": [shot_of(p.split(":", 1)[1]) for p in pending],
                "note": f"定下 {len(settled)}/{len(shots)}" + (f"；未定：{', '.join(shot_of(p.split(':', 1)[1]) for p in pending)}" if pending else "")}

    stages["first_frames"] = settle_stage("first", start)
    stages["last_frames"] = settle_stage("last", start)
    # night（合成）事件先读：视频“按 night 落定”也要用到。night 主机 = night_state 里本集有 final 的那台
    nhost = next((h for h, ns in (src.get("night_state") or {}).items() if ((ns or {}).get("eps") or {}).get(str(ep), {}).get("final")), None)
    nev = []
    for h, lines in (src.get("night") or {}).items():
        if nhost in (None, h):
            nev += night_events(lines, ep, year)
    nev.sort(key=lambda e: e["ts"])
    cycles = assembly_cycles(nev, start, until)
    last_cycle = cycles[-1] if cycles else None
    # 视频：窗口内提交的作业；镜落定 = SHOT_PASS / SHOT_BEST_EFFORT（vidgen）或 state 的 chosen；
    # 都没有但 night 最近一次 EP_RESOLVED 把该镜记为 done / best_effort（沿用起点前的片段）→ 也算定下，单独标“沿用旧片”
    vin = [j for j in vjobs if j["submit"] >= start and j["submit"] <= until]
    for j in vin:   # 截至之后才完成 / 打分的，按截至时刻看就是还在跑
        if j["done"] and j["done"] > until:
            j["done"], j["score_at"], j["verdict"], j["state"] = None, None, None, "running"
        elif j["score_at"] and j["score_at"] > until:
            j["score_at"], j["verdict"] = None, None
    vs_at, v_reused = {}, []
    for j in vin:
        s = j["shot"].split("-", 1)[1]
        if j["shot_settled_at"] and start <= j["shot_settled_at"] <= until:
            vs_at[s] = max(vs_at.get(s, j["shot_settled_at"]), j["shot_settled_at"])
        elif j["chosen"] and j["chosen"] == j["ver"] and j["done"] and (j["score_at"] or j["done"]) <= until:
            vs_at[s] = max(vs_at.get(s, j["score_at"] or j["done"]), j["score_at"] or j["done"])
    resolved = (last_cycle or {}).get("resolved") or {}
    for s in shots:
        if s not in vs_at and resolved.get(f"ep{ep:02d}-{s}") in ("done", "best_effort"):
            vs_at[s] = last_cycle["start"]
            v_reused.append(s)
    v_pending = [s for s in shots if s not in vs_at]
    stages["videos"] = {"start": vin[0]["submit"] if vin else None, "end": max(vs_at.values()) if vs_at and not v_pending else None,
                        "status": "done" if vs_at and not v_pending else ("running" if vin else "not_started"),
                        "settled": len(vs_at), "total": len(shots), "pending": v_pending, "reused": v_reused,
                        "note": f"定下 {len(vs_at)}/{len(shots)}，窗口内提交 {len(vin)} 段" + (f"；沿用起点前片段（night 落定）：{', '.join(v_reused)}" if v_reused else "")
                                + (f"；未定：{', '.join(v_pending)}" if v_pending else "")}
    ns_ep = (((src.get("night_state") or {}).get(nhost) or {}).get("eps") or {}).get(str(ep), {}) if nhost else {}
    stages["assembly"] = {"start": last_cycle["start"] if last_cycle else None,
                          "end": last_cycle["end"] if last_cycle else None,
                          "status": ("done" if last_cycle and last_cycle["end"] and last_cycle["end_ev"] in ("RETRO", "report", "BGM_LIB", "director", "FINALIZE_DONE")
                                     else ("running" if last_cycle else "not_started")),
                          "cycles": len(cycles), "host": nhost, "final": ns_ep.get("final"), "assembled_n": ns_ep.get("assembled_n"),
                          "note": f"night 主机 {nhost or '?'}；合成周期 {len(cycles)} 次（REOPEN 重开 {sum(1 for c in cycles if c['reopen'])}）；"
                                  f"最近成片 {os.path.basename(str(ns_ep.get('final') or '—'))} v{ns_ep.get('assembled_n') or '?'}"}
    # 拉回：本机 data/episodes/<run>/<final 文件名> 的 mtime
    deliv = {"start": stages["assembly"]["end"], "end": None, "status": "running" if stages["assembly"]["end"] else "not_started",
             "note": "成片还没拉回本机" if stages["assembly"]["end"] else "等合成"}
    final = ns_ep.get("final")
    if final and stages["assembly"]["end"]:
        lp = Path(src.get("local_episodes") or (ROOT / "data/episodes" / run)) / os.path.basename(str(final))
        if lp.exists() and lp.stat().st_size > 0:
            mt = ep2dt(lp.stat().st_mtime)
            if mt >= stages["assembly"]["end"]:
                deliv.update(end=mt, status="done", note=f"本机 {lp.name} {lp.stat().st_size // 1024 // 1024} MB，拉回完成 {fmt(mt)}")
            else:
                deliv["note"] = f"本机只有旧版 {lp.name}（{fmt(mt)}，早于本次合成）"
    stages["delivery"] = deliv
    for k, s in stages.items():
        st_, en = s.get("start"), s.get("end")
        eff_end = en or (until if st_ else None)
        s["actual_s"] = (eff_end - st_).total_seconds() if st_ and eff_end else None
        s["budget_s"] = budget.get(k)
        s["overrun_s"] = max(0.0, s["actual_s"] - s["budget_s"]) if s["actual_s"] is not None and s.get("budget_s") else 0.0
        s["open"] = bool(st_ and not en)
    res["stages"] = stages
    # ---- 整集
    ends = [s["end"] for s in stages.values() if s.get("end")]
    ep_end = stages["delivery"]["end"] or (stages["assembly"]["end"] if stages["videos"]["status"] == "done" and stages["assembly"]["status"] == "done" else None)
    elapsed = ((ep_end or until) - start).total_seconds()
    res["episode_status"] = "done" if ep_end else "running"
    res["episode_end"] = ep_end
    res["elapsed_s"] = elapsed
    res["episode_overrun_s"] = max(0.0, elapsed - budget["episode"])
    res["shots"], res["adult_shots"], res["lanes"] = shots, sorted(adult), lanes
    # ---- 每道 GPU 忙时（按作业类型；同道重叠的区间只算一次，所以利用率 ≤ 100%）
    hi = ep_end or until
    blank = lambda: {"first": 0.0, "last": 0.0, "video": 0.0, "gpu_s": 0.0, "n_first": 0, "n_last": 0, "n_video": 0, "_iv": []}  # noqa: E731
    busy = {ln: blank() for ln in lanes}
    for o, v in objs.items():
        k = kind_of(o)
        for a in v["attempts"]:
            if a["dispatch"] and a["rendered"] and a["lane"]:
                b = busy.setdefault(a["lane"], blank())
                b[k] += _clip(a["dispatch"], a["rendered"], start, hi)
                b["gpu_s"] += float(a["gpu_s"] or 0)
                b["n_" + k] += 1
                b["_iv"].append((max(a["dispatch"], start), min(a["rendered"], hi)))
    for j in vin:
        if j["done"] and j["lane"]:
            b = busy.setdefault(j["lane"], blank())
            b["video"] += _clip(j["submit"], j["done"], start, hi)
            b["gpu_s"] += float(j["gpu_s"] or 0)
            b["n_video"] += 1
            b["_iv"].append((max(j["submit"], start), min(j["done"], hi)))
    lane_free = {}
    for ln, b in busy.items():
        u = _union(b["_iv"])
        b["busy_s"] = sum((e - s).total_seconds() for s, e in u)
        b["util"] = round(100.0 * b["busy_s"] / max(1.0, elapsed), 1)
        lane_free[ln] = _complement(u, start, hi)
        del b["_iv"]
    res["lane_busy"] = busy
    any_free = _union([iv for ivs in lane_free.values() for iv in ivs])
    # ---- 每帧尝试 / 失败原因
    fails = Counter()
    per_frame = {}
    for o, v in sorted(objs.items()):
        k, sid = o.split(":", 1)
        s = shot_of(sid)
        if s not in shots:
            continue
        att = v["attempts"]
        vs = Counter(a["verdict"] for a in att if a["verdict"])
        for a in att:
            for bl in a["blocking"]:
                fails[bl] += 1
        rw = [a["render_s"] for a in att if a["render_s"]]
        cw = [(a["verdict_at"] - a["rendered"]).total_seconds() for a in att if a["verdict_at"] and a["rendered"]]
        per_frame[o] = {"shot": s, "kind": k, "dispatches": len([a for a in att if a["dispatch"]]), "rendered": len([a for a in att if a["rendered"]]),
                        "verdicts": dict(vs), "render_s_med": round(sorted(rw)[len(rw) // 2], 0) if rw else None,
                        "score_s_med": round(sorted(cw)[len(cw) // 2], 0) if cw else None,
                        "settled_by": v["settled_by"], "settled_at": v["settled_at"], "fallback": v["fallback"],
                        "lanes": sorted({a["lane"] for a in att if a["lane"]})}
    res["per_frame"] = per_frame
    res["fail_reasons"] = dict(fails.most_common())
    res["frames_summary"] = {"dispatches": sum(p["dispatches"] for p in per_frame.values()),
                             "rendered": sum(p["rendered"] for p in per_frame.values()),
                             "passed": sum(p["verdicts"].get("passed", 0) for p in per_frame.values()),
                             "content_fail": sum(p["verdicts"].get("content_fail", 0) + p["verdicts"].get("redo_fail", 0) for p in per_frame.values()),
                             "score_err": sum(p["verdicts"].get("score_infra", 0) + p["verdicts"].get("score_timeout", 0) for p in per_frame.values())}
    # ---- 视频段
    vsum = {"submitted": len(vin), "done": len([j for j in vin if j["done"]]), "pass": len([j for j in vin if j["verdict"] == "pass"]),
            "fail": len([j for j in vin if j["verdict"] not in (None, "pass")]),
            "gen_s_med": None, "score_s_med": None, "per_shot": {}}
    gs = sorted((j["done"] - j["submit"]).total_seconds() for j in vin if j["done"])
    ss = sorted((j["score_at"] - j["done"]).total_seconds() for j in vin if j["done"] and j["score_at"] and j["score_at"] >= j["done"])
    vsum["gen_s_med"] = round(gs[len(gs) // 2]) if gs else None
    vsum["score_s_med"] = round(ss[len(ss) // 2]) if ss else None
    for j in vin:
        s = j["shot"].split("-", 1)[1]
        d = vsum["per_shot"].setdefault(s, {"n": 0, "lanes": [], "verdicts": [], "settled_by": j["shot_settled_by"], "recipe": j["recipe"]})
        d["n"] += 1
        d["lanes"].append(j["lane"])
        d["verdicts"].append(j["verdict"] or j["state"])
    res["videos_summary"] = vsum
    # ---- 等待
    waits = {"ready_to_dispatch": [], "pair_to_submit": [], "settled_to_assembly": None, "score_waits": []}
    first_settle = {s: None for s in shots}
    for o, v in objs.items():
        if kind_of(o) == "first" and v["settled_at"]:
            first_settle[shot_of(o.split(":", 1)[1])] = v["settled_at"]
    for o, v in objs.items():
        k, sid = o.split(":", 1)
        s = shot_of(sid)
        if s not in shots:
            continue
        prev_ready = start if k == "first" else (first_settle.get(s) or start)
        for a in v["attempts"]:
            if not a["dispatch"]:
                continue
            w = (a["dispatch"] - prev_ready).total_seconds()
            if w >= 0:
                blk = [b for b in v["blocks"] if prev_ready <= b["ts"] <= a["dispatch"]]
                waits["ready_to_dispatch"].append({"obj": o, "wait_s": round(w), "ready": prev_ready, "dispatch": a["dispatch"], "lane": a["lane"],
                                                   "idle_s": round(_overlap_s(any_free, prev_ready, a["dispatch"])),
                                                   "blocked": (blk[-1]["ev"] + "：" + blk[-1]["why"][:80]) if blk else None})
            if a["verdict_at"]:
                prev_ready = a["verdict_at"]
                if a["rendered"]:
                    waits["score_waits"].append({"obj": o, "score_s": round((a["verdict_at"] - a["rendered"]).total_seconds()), "verdict": a["verdict"]})
    for s in shots:
        f = first_settle.get(s)
        lo = objs.get(f"last:ep{ep:02d}-{s}")
        l_at = lo["settled_at"] if lo else None
        if not f:
            continue
        pair = max(f, l_at) if l_at else f
        sub = next((j["submit"] for j in vin if j["shot"].endswith("-" + s) and j["submit"] >= pair), None)
        if sub:
            waits["pair_to_submit"].append({"shot": s, "pair_ready": pair, "submit": sub, "wait_s": round((sub - pair).total_seconds()),
                                            "idle_s": round(_overlap_s(any_free, pair, sub)),
                                            "note": "尾帧兜底（只用首帧）" if (lo and lo["fallback"]) else ("尾帧未定，按首帧定下算" if not l_at else "")})
    # 本集“空卡有活”：每道空闲区间 ∩ 本集有就绪帧 / 成对镜在等的区间（道·秒）
    ready_u = _union([(w["ready"], w["dispatch"]) for w in waits["ready_to_dispatch"]] + [(w["pair_ready"], w["submit"]) for w in waits["pair_to_submit"]])
    res["idle_with_work_s"] = {ln: round(sum(_overlap_s(ready_u, s_, e_) for s_, e_ in ivs)) for ln, ivs in lane_free.items()}
    if vs_at and cycles:
        last_settle = max(vs_at.values())
        nxt = next((c["start"] for c in cycles if c["start"] >= last_settle), None)
        waits["settled_to_assembly"] = {"last_settle": last_settle, "assembly_start": nxt, "wait_s": round((nxt - last_settle).total_seconds()) if nxt else None}
    res["waits"] = waits
    # ---- 空卡有活 / 大脑动作
    idle = idle_lane_minutes(src.get("idle") or [], start, until)
    res["idle_lanes"] = idle["lane_minutes"]
    res["idle_acts"] = idle["acts"]
    res["brain_actions"] = brain_actions(src.get("brain") or [], start, until)
    # ---- 重启 / 事故
    inc = []
    pauses = {}
    for r in rows:
        ts = r["_ts"]
        if ts < start or ts > until:
            continue
        if r["ev"] == "start":
            inc.append({"ts": ts, "kind": "producer_restart", "host": r["_host"], "text": f"producer 重启 pid {r.get('pid')} code {r.get('code_sha')}"})
        elif r["ev"] == "pause":
            pauses[(r["_host"], r.get("by"))] = r
            inc.append({"ts": ts, "kind": f"pause:{r.get('reason_kind') or r.get('by')}", "host": r["_host"], "text": f"暂停派单：{r.get('note') or ''}"[:120], "pause_s": None})
        elif r["ev"] == "resume":
            p = pauses.pop((r["_host"], r.get("by")), None)
            if p:
                for i in inc:
                    if i["kind"].startswith("pause:") and i["ts"] == p["_ts"] and i["host"] == r["_host"]:
                        i["pause_s"] = round((ts - p["_ts"]).total_seconds())
        elif r["ev"] in ("infra_error", "score_infra", "score_timeout", "vqa_gate_err", "accept_err", "canary_err", "hard_cap_exhausted",
                         "last_void_reset", "best_effort_reset", "gaze_round", "sop_gate_block", "regen", "master_reject", "retry",
                         "lane_roles_phase", "review_scale"):
            inc.append({"ts": ts, "kind": r["ev"], "host": r["_host"], "obj": r.get("obj"), "lane": r.get("lane"),
                        "text": str(r.get("error") or r.get("why") or r.get("reason") or r.get("note") or r.get("phase") or "")[:140],
                        "backoff_s": r.get("backoff_s"), "contract_s": r.get("contract_s")})
    for e in nev:
        if start <= e["ts"] <= until and e["ev"] in ("RUN", "REOPEN", "FINALIZE_SPAWN_ERR", "FINALIZE_NO_RESULT", "FINALIZE_CHILD_ERR") or \
           (start <= e["ts"] <= until and e["ev"] == "register_takes" and "Error" in e["rest"]):
            inc.append({"ts": e["ts"], "kind": "night_restart" if e["ev"] == "RUN" else e["ev"], "host": nhost, "text": e["rest"][:140]})
    inc.sort(key=lambda i: i["ts"])
    res["incidents"] = inc
    res["incident_counts"] = dict(Counter(i["kind"] for i in inc))
    res["cycles"] = cycles
    res["context_before_start"] = {"dispatches": len([r for r in rows if r["ev"] == "dispatch" and r["_ts"] < start and r["_ts"].date() == start.date()]),
                                   "rendered": len([r for r in rows if r["ev"] == "rendered" and r["_ts"] < start and r["_ts"].date() == start.date()]),
                                   "imports": [{"ts": r["_ts"], "note": (r.get("note") or "")[:80]} for r in rows if r["ev"] == "imported_staged" and r["_ts"].date() == start.date()]}
    res["attribution"] = attribute(res, objs, vin, cycles, inc, budget)
    res["takes"] = {h: {s: {"active": t.get("active"), "n": t.get("n")} for s, t in (tk or {}).items()} for h, tk in (src.get("takes") or {}).items()}
    return res


def attribute(res: dict, objs: dict, vin: list[dict], cycles: list[dict], inc: list[dict], budget: dict) -> dict:
    """每个阶段的超预算分钟 → 四类。证据权重（秒）：
    检测 = 契约没过后的重出（第 2 次起的出图墙钟）+ 打分超 40 s 的部分 + 打分超时 / 视频没过后重出
    代码 = infra_error 退避 + score_infra + 部署 / 重启暂停窗 + night 子步骤报错（每条按 60 s 记）
    GPU 调度 = 就绪→派单 > 30 s 的等待 + 成对→提交 > 60 s 的等待 + 空卡有活（道·分钟）
    逻辑 = 规则触发的作废 / 重置 / 阶梯（last_void_reset、best_effort_reset、gaze_round、regen、sop_gate_block 各按引发的出图墙钟或 120 s 记）
          + 全定→合成等待 + REOPEN 重合成周期"""
    start, until = res["start"], res["until"]
    stages = res["stages"] if "stages" in res else {}
    ev = {c: [] for c in CATS}   # (stage, seconds, text)

    def add(cat, stage, sec, text):
        if sec and sec > 0:
            ev[cat].append({"stage": stage, "s": round(float(sec)), "text": text[:160]})

    for o, v in objs.items():
        k = kind_of(o)
        stg = "first_frames" if k == "first" else "last_frames"
        prev_verdict = None
        for a in v["attempts"]:
            wall = (a["rendered"] - a["dispatch"]).total_seconds() if a["rendered"] and a["dispatch"] else 0
            if prev_verdict in ("content_fail", "redo_fail") and wall:
                add("检测", stg, wall, f"{o} 第 {a['attempt'] or '?'} 次重出（上一版契约没过：{','.join(a['blocking']) or prev_verdict}）{fmt(a['dispatch'])} 道 {a['lane']} {round(wall)} s")
            if a["verdict_at"] and a["rendered"]:
                sc = (a["verdict_at"] - a["rendered"]).total_seconds()
                if a["verdict"] in ("score_timeout", "score_infra"):
                    add("代码" if a["verdict"] == "score_infra" else "检测", stg, sc, f"{o} v{a['take']} {a['verdict']} 打分链 {round(sc)} s（{a['why'] or ''}）")
                elif sc > budget["score_image"]:
                    add("检测", stg, sc - budget["score_image"], f"{o} v{a['take']} 打分 {round(sc)} s > {budget['score_image']} s")
            if a["rung"] and ("换种子" in str(a["rung"]) or "D8" in str(a["rung"])) and a["redo"] and wall:
                add("逻辑", stg, wall, f"{o} 规则重出（{a['rung']}）{round(wall)} s")
            prev_verdict = a["verdict"] or prev_verdict
    for w in res["waits"]["ready_to_dispatch"]:
        stg = "first_frames" if w["obj"].startswith("first") else "last_frames"
        if w.get("blocked") and w["wait_s"] > 30:
            add("逻辑", stg, w["wait_s"], f"{w['obj']} 就绪 {fmt(w['ready'])} → 派单 {fmt(w['dispatch'])} 等 {w['wait_s']} s，期间被闸门挡：{w['blocked']}")
        elif w.get("idle_s", 0) > 30:
            add("GPU 调度", stg, w["idle_s"], f"{w['obj']} 就绪 {fmt(w['ready'])} → 派单 {fmt(w['dispatch'])}（{w['lane']}）等 {w['wait_s']} s，其中有空道 {w['idle_s']} s")
    for w in res["waits"]["pair_to_submit"]:
        if w.get("note") and w["wait_s"] > 60:
            add("逻辑", "videos", w["wait_s"], f"{w['shot']} 首帧定下 {fmt(w['pair_ready'])} → 视频提交 {fmt(w['submit'])} 等 {w['wait_s']} s（{w['note']}：等尾帧决策 / HOLD）")
        elif w.get("idle_s", 0) > 60:
            add("GPU 调度", "videos", w["idle_s"], f"{w['shot']} 首尾成对 {fmt(w['pair_ready'])} → 视频提交 {fmt(w['submit'])} 等 {w['wait_s']} s，其中有空道 {w['idle_s']} s")
    # 被规则作废的出图（last_void_reset / best_effort_reset / gaze_round 之前最近一张已出的图 → 白出）
    for i in inc:
        if i["kind"] in ("last_void_reset", "best_effort_reset", "gaze_round") and i.get("obj") in objs:
            o = objs[i["obj"]]
            a = next((a for a in reversed(o["attempts"]) if a["rendered"] and a["rendered"] <= i["ts"] and not a.get("_voided")), None)
            if a and a["dispatch"]:
                a["_voided"] = True
                add("逻辑", "last_frames" if i["obj"].startswith("last") else "first_frames", (a["rendered"] - a["dispatch"]).total_seconds(),
                    f"{i['obj']} v{a['take']} 出完被 {i['kind']} 作废（{i['text'][:70]}）{fmt(i['ts'])}")
    prev_fail = {}
    for j in vin:
        if j["done"]:
            wall = (j["done"] - j["submit"]).total_seconds()
            if prev_fail.get(j["shot"]):
                add("检测", "videos", wall, f"{j['shot']} {j['ver']} 重出（上一段 {prev_fail[j['shot']]}）{round(wall)} s")
            elif wall > budget["per_video"]:
                add("GPU 调度", "videos", wall - budget["per_video"], f"{j['shot']} {j['ver']} 单段 {round(wall)} s > 上限 {budget['per_video']} s（{j['lane']}）")
            if j["score_at"] and (j["score_at"] - j["done"]).total_seconds() > budget["score_video"]:
                add("检测", "videos", (j["score_at"] - j["done"]).total_seconds() - budget["score_video"], f"{j['shot']} {j['ver']} 视频打分 {round((j['score_at'] - j['done']).total_seconds())} s > {budget['score_video']} s")
        if j["verdict"] not in (None, "pass"):
            prev_fail[j["shot"]] = ",".join(j["labels"]) or str(j["verdict"])
    sa = res["waits"].get("settled_to_assembly")
    if sa and sa.get("wait_s"):
        add("逻辑", "assembly", sa["wait_s"], f"视频全定 {fmt(sa['last_settle'])} → 合成起 {fmt(sa['assembly_start'])} 等 {sa['wait_s']} s（HOLD / 轮询）")
    for c in cycles[:-1]:
        if c["end"]:
            add("逻辑", "assembly", (c["end"] - c["start"]).total_seconds(), f"合成周期 {fmt(c['start'])}→{fmt(c['end'])} 之后被 REOPEN（入选版本有变）重做")
    for c in cycles:
        for e in c["errors"]:
            add("代码", "assembly", 60, f"night {e['ev']} 报错 {fmt(e['ts'])}：{e['rest'][:90]}")
    for i in inc:
        stg = "videos" if res["stages"]["videos"]["start"] and i["ts"] >= res["stages"]["videos"]["start"] else "first_frames"
        if i["kind"].startswith("pause:") and i.get("pause_s"):
            add("代码", stg, i["pause_s"], f"{i['host']} 暂停派单 {i['pause_s']} s（{i['kind'][6:]}：{i['text'][:60]}）{fmt(i['ts'])}")
        elif i["kind"] == "infra_error":
            add("代码", stg, i.get("backoff_s") or 30, f"{i.get('obj')} {i.get('lane')} infra_error {i['text'][:70]} 退避 {i.get('backoff_s')} s {fmt(i['ts'])}")
        elif i["kind"] in ("regen", "master_reject", "retry", "hard_cap_exhausted"):
            add("逻辑", "last_frames" if str(i.get("obj", "")).startswith("last") else "first_frames", 120, f"{i.get('obj')} {i['kind']}：{i['text'][:80]} {fmt(i['ts'])}（按 120 s 记）")
        elif i["kind"] in ("night_restart", "producer_restart"):
            add("代码", stg, 30, f"{i['host']} {i['kind']} {fmt(i['ts'])}")
    per_stage = {}
    for name, s in res["stages"].items():
        ov = (s.get("overrun_s") or 0) / 60.0
        weights = {c: sum(e["s"] for e in ev[c] if e["stage"] == name) for c in CATS}
        if name == "import_probe":
            weights = {c: 0 for c in CATS}
            if ov > 0:
                weights["逻辑"] = 1
        per_stage[name] = {"overrun_min": round(ov, 1), "alloc_min": _alloc(ov, weights), "weights_s": weights,
                           "evidence": {c: sorted([e for e in ev[c] if e["stage"] == name], key=lambda e: -e["s"])[:8] for c in CATS}}
        if ov > 0 and sum(weights.values()) <= 0:
            per_stage[name]["evidence"]["逻辑"] = [{"stage": name, "s": 0, "text": "没有直接证据，按流程等待（逻辑）记"}]
    tot_ov = res["episode_overrun_s"] / 60.0
    tw = {c: sum(e["s"] for e in ev[c]) for c in CATS}
    total = {"overrun_min": round(tot_ov, 1), "alloc_min": _alloc(tot_ov, tw), "weights_s": tw,
             "top_evidence": {c: sorted(ev[c], key=lambda e: -e["s"])[:6] for c in CATS}}
    return {"per_stage": per_stage, "episode": total,
            "method": "超预算分钟按各类证据秒数的比例分配（最大余数法，和 = 超预算分钟）；证据秒数是并行道上的叠加，不等于墙钟"}


# ---------------------------------------------------------------- 输出
def _j(o):
    if isinstance(o, datetime):
        return o.isoformat(timespec="seconds")
    if isinstance(o, Path):
        return str(o)
    if isinstance(o, set):
        return sorted(o)
    return str(o)


def write_json(res: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=_j), encoding="utf-8")
    os.replace(tmp, path)


def summary(res: dict, md_path: Path | None, json_path: Path | None) -> dict:
    """给大脑快照的短摘要（data/kpi/<run>/latest.json）"""
    if res.get("error"):
        return {"run": res["run"], "episode": res["episode"], "generated_at": res["generated_at"], "error": res["error"]}
    at = res["attribution"]
    st = {k: {"actual_min": mins(s["actual_s"]), "budget_min": mins(s.get("budget_s")), "overrun_min": mins(s.get("overrun_s")),
              "status": s["status"], "open": s.get("open", False), "attribution_min": at["per_stage"][k]["alloc_min"]}
          for k, s in res["stages"].items()}
    top = []
    for c in CATS:
        for e in at["episode"]["top_evidence"][c][:2]:
            top.append(f"[{c}] {e['text']}")
    return {"run": res["run"], "episode": res["episode"], "generated_at": res["generated_at"], "start": _j(res["start"]),
            "until": _j(res["until"]), "status": res["episode_status"], "elapsed_min": mins(res["elapsed_s"]),
            "budget_min": mins(res["budget"]["episode"]), "overrun_min": mins(res["episode_overrun_s"]),
            "attribution_min": at["episode"]["alloc_min"], "stages": st,
            "frames": res["frames_summary"], "fail_reasons": dict(list(res["fail_reasons"].items())[:6]),
            "videos": {k: v for k, v in res["videos_summary"].items() if k != "per_shot"},
            "idle_lane_minutes": res["idle_lanes"], "idle_with_work_min": {k: round(v / 60) for k, v in res["idle_with_work_s"].items()},
            "lane_util_pct": {k: v["util"] for k, v in res["lane_busy"].items()},
            "incidents": res["incident_counts"], "top_evidence": top[:8],
            "md": str(md_path) if md_path else None, "json": str(json_path) if json_path else None}


def render_md(res: dict) -> str:
    run, ep = res["run"], res["episode"]
    L = [f"# KPI {run} ep{ep:02d}（L-205：一集 ≤ {mins(res['budget']['episode'])} min）", "",
         f"生成：{res['generated_at']}（JST）· 工具 tools/master/episode_kpi_report.py · 预算来源 docs/master/PIPELINE_CHECKLIST.md（{res['budget'].get('profile')} 档）"]
    if res.get("error"):
        L += ["", f"🔴 {res['error']}"]
        return "\n".join(L) + "\n"
    a = res["anchor"]
    status_cn = "✅ 已完成" if res["episode_status"] == "done" else "🟡 进行中（截至 until）"
    L += [f"起点：{fmt(res['start'])}（锚点 {a.get('anchor')}：{a.get('anchor_ev') or '—'} @ {fmt(a.get('anchor_ts'))}）· 截至：{fmt(res['until'])} · 状态：{status_cn}",
          f"**用时 {mins(res['elapsed_s'])} min / 预算 {mins(res['budget']['episode'])} min → 超 {mins(res['episode_overrun_s'])} min**；"
          f"归因（min）：" + "、".join(f"{c} {v}" for c, v in res["attribution"]["episode"]["alloc_min"].items()),
          f"镜头 {len(res['shots'])} 个（成人镜不计：{', '.join(res['adult_shots']) or '无'}）· 道 {len(res['lanes'])} 条", ""]
    if res["budget"].get("notes"):
        L += ["预算读取备注：" + "；".join(res["budget"]["notes"]), ""]
    L += ["## 1. 阶段耗时 vs 预算", "", "| 阶段 | 起 | 止 | 实际 min | 预算 min | 超 min | 状态 | 归因 逻辑/代码/GPU 调度/检测 | 备注 |", "|---|---|---|---|---|---|---|---|---|"]
    for k in STAGES:
        s = res["stages"][k]
        al = res["attribution"]["per_stage"][k]["alloc_min"]
        stt = {"done": "完成", "running": "进行中", "not_started": "未开始", "unknown": "不明"}.get(s["status"], s["status"])
        L.append(f"| {STAGE_CN[k]} | {fmt(s.get('start'))} | {fmt(s.get('end')) if s.get('end') else ('（截至 until）' if s.get('start') else '—')} | "
                 f"{mins(s['actual_s']) if s['actual_s'] is not None else '—'} | {mins(s.get('budget_s'))} | {mins(s.get('overrun_s'))} | {stt} | "
                 f"{al['逻辑']}/{al['代码']}/{al['GPU 调度']}/{al['检测']} | {s.get('note', '')} |")
    tot = res["attribution"]["episode"]
    L += ["", f"整集超预算 {tot['overrun_min']} min → 逻辑 {tot['alloc_min']['逻辑']} / 代码 {tot['alloc_min']['代码']} / GPU 调度 {tot['alloc_min']['GPU 调度']} / 检测 {tot['alloc_min']['检测']}"
          f"（证据权重秒：{', '.join(f'{c} {round(v)}' for c, v in tot['weights_s'].items())}）。{res['attribution']['method']}。", ""]
    L += ["## 2. 每道 GPU 忙时（按作业类型，窗口内；忙 s = 同道区间并集）", "",
          "| 道 | 首帧 s（张） | 尾帧 s（张） | 视频 s（段） | 忙 s | 纯 GPU s | 利用率 % | 空卡有活 min |", "|---|---|---|---|---|---|---|---|"]
    for ln, b in sorted(res["lane_busy"].items()):
        L.append(f"| {ln} | {round(b['first'])}（{b['n_first']}） | {round(b['last'])}（{b['n_last']}） | {round(b['video'])}（{b['n_video']}） | "
                 f"{round(b['busy_s'])} | {round(b['gpu_s'])} | {b['util']} | {round(res['idle_with_work_s'].get(ln, 0) / 60)} |")
    fs = res["frames_summary"]
    L += ["", "## 3. 每帧尝试与失败原因", "",
          f"派单 {fs['dispatches']} · 出图 {fs['rendered']} · 过 {fs['passed']} · 契约没过 {fs['content_fail']} · 打分故障 {fs['score_err']}；"
          f"失败原因：{', '.join(f'{k}×{v}' for k, v in res['fail_reasons'].items()) or '—'}", "",
          "| 帧 | 派单 | 出图 | 结论 | 出图中位 s | 打分中位 s | 定下 | 道 |", "|---|---|---|---|---|---|---|---|"]
    for o, p in sorted(res["per_frame"].items(), key=lambda kv: (int(re.sub(r"\D", "", kv[1]["shot"]) or 0), kv[1]["kind"])):
        vs = ", ".join(f"{k}×{v}" for k, v in p["verdicts"].items()) or "—"
        settled = f"{p['settled_by']} {fmt(p['settled_at'])}" if p["settled_at"] else ("兜底 " + p["fallback"] if p["fallback"] else "未定")
        L.append(f"| {o} | {p['dispatches']} | {p['rendered']} | {vs} | {p['render_s_med'] or '—'} | {p['score_s_med'] or '—'} | {settled} | {','.join(p['lanes'])} |")
    vs_ = res["videos_summary"]
    L += ["", "## 4. 视频段", "", f"窗口内提交 {vs_['submitted']} · 完成 {vs_['done']} · 过 {vs_['pass']} · 没过 {vs_['fail']} · 生成中位 {vs_['gen_s_med'] or '—'} s · 打分中位 {vs_['score_s_med'] or '—'} s", "",
          "| 镜 | 段数 | 道 | 结论 | 定下 | 配方 |", "|---|---|---|---|---|---|"]
    for s, d in sorted(vs_["per_shot"].items(), key=lambda kv: int(re.sub(r"\D", "", kv[0]) or 0)):
        L.append(f"| {s} | {d['n']} | {','.join(x or '?' for x in d['lanes'])} | {','.join(str(x) for x in d['verdicts'])} | {d['settled_by'] or '未定'} | {d['recipe'] or ''} |")
    w = res["waits"]
    rd = [x["wait_s"] for x in w["ready_to_dispatch"]]
    ps = [x["wait_s"] for x in w["pair_to_submit"]]
    sw = [x["score_s"] for x in w["score_waits"]]
    med = lambda xs: (sorted(xs)[len(xs) // 2] if xs else "—")  # noqa: E731
    rdi = sum(x.get("idle_s", 0) for x in w["ready_to_dispatch"])
    psi = sum(x.get("idle_s", 0) for x in w["pair_to_submit"])
    blocked_n = len([x for x in w["ready_to_dispatch"] if x.get("blocked")])
    L += ["", "## 5. 等待", "", "| 等待 | 次数 | 合计 s | 中位 s | 最大 s | 其中有空道 s | 被闸门挡 |", "|---|---|---|---|---|---|---|",
          f"| 就绪 → 派单 | {len(rd)} | {sum(rd)} | {med(rd)} | {max(rd) if rd else '—'} | {rdi} | {blocked_n} 次 |",
          f"| 首尾成对 → 视频提交 | {len(ps)} | {sum(ps)} | {med(ps)} | {max(ps) if ps else '—'} | {psi} | |",
          f"| 出图 → 打分结论 | {len(sw)} | {sum(sw)} | {med(sw)} | {max(sw) if sw else '—'} | | |"]
    sa = w.get("settled_to_assembly")
    L.append(f"| 视频全定 → 合成起 | {'1' if sa and sa.get('wait_s') is not None else '0'} | {sa['wait_s'] if sa and sa.get('wait_s') is not None else '—'} | | | | |")
    worst = sorted(w["ready_to_dispatch"], key=lambda x: -x["wait_s"])[:5]
    if worst:
        L += ["", "最长的就绪→派单：" + "；".join(f"{x['obj']} {x['wait_s']} s（{fmt(x['ready'])}→{fmt(x['dispatch'])} {x['lane']}，空道 {x.get('idle_s', 0)} s"
                                          f"{'，闸门：' + x['blocked'][:50] if x.get('blocked') else ''}）" for x in worst)]
    worst_v = sorted(w["pair_to_submit"], key=lambda x: -x["wait_s"])[:5]
    if worst_v:
        L += ["", "最长的成对→提交：" + "；".join(f"{x['shot']} {x['wait_s']} s（{fmt(x['pair_ready'])}→{fmt(x['submit'])}，空道 {x.get('idle_s', 0)} s{'，' + x['note'] if x.get('note') else ''}）" for x in worst_v)]
    L += ["", "## 6. 空卡有活", "",
          "本集口径（道空闲 ∩ 本集有帧 / 镜在等，道·分钟，日志推算）：" + ("、".join(f"{k} {round(v / 60)}" for k, v in sorted(res["idle_with_work_s"].items())) or "无"),
          "", "idle_watch 口径（道空闲且全剧有活，道·分钟，笔记本每分钟采样）：" + ("、".join(f"{k} {v}" for k, v in sorted(res["idle_lanes"].items())) or "无（或笔记本没有 idle_watch 记录）")]
    if res["idle_acts"]:
        L += ["", "idle_watch 动作：", *[f"- {fmt(x['ts'])} {x['text']}" for x in res["idle_acts"][:12]]]
    L += ["", "## 7. 重启 / 事故", "", "计数：" + ("、".join(f"{k} {v}" for k, v in sorted(res["incident_counts"].items())) or "无"), ""]
    for i in res["incidents"][:60]:
        extra = f" 暂停 {i['pause_s']} s" if i.get("pause_s") else ""
        L.append(f"- {fmt(i['ts'])} {i.get('host') or ''} {i['kind']} {i.get('obj') or ''} {i.get('lane') or ''} {i['text']}{extra}")
    if len(res["incidents"]) > 60:
        L.append(f"- …共 {len(res['incidents'])} 条，全量见 JSON")
    if res["brain_actions"]:
        L += ["", "大脑动作（decisions.jsonl）：", *[f"- {fmt(x['ts'])} {x['kind']} by {x['by']} {'dry' if x['dry'] else ''} {x['result']}" for x in res["brain_actions"][:10]]]
    L += ["", "## 8. 归因证据（每个超预算阶段）", ""]
    for k in STAGES:
        ps_ = res["attribution"]["per_stage"][k]
        if ps_["overrun_min"] <= 0:
            continue
        L.append(f"### {STAGE_CN[k]}：超 {ps_['overrun_min']} min → " + "、".join(f"{c} {v}" for c, v in ps_["alloc_min"].items()))
        for c in CATS:
            for e in ps_["evidence"][c][:5]:
                L.append(f"- [{c}] {e['s']} s · {e['text']}")
        L.append("")
    if res["cycles"]:
        L += ["## 9. 合成周期", "", "| 起（EP_RESOLVED） | 止 | 收尾事件 | 步骤 | 报错 | REOPEN |", "|---|---|---|---|---|---|"]
        for c in res["cycles"]:
            L.append(f"| {fmt(c['start'])} | {fmt(c['end'])} | {c['end_ev'] or '进行中'} | {len(c['steps'])} | {len(c['errors'])} | {fmt(c['reopen']) if c['reopen'] else ''} |")
        L.append("")
    cb = res["context_before_start"]
    L += ["## 10. 背景：起点之前同日的尝试（不计入 KPI）", "",
          f"派单 {cb['dispatches']} · 出图 {cb['rendered']}；导入：" + ("；".join(f"{fmt(x['ts'])} {x['note']}" for x in cb["imports"]) or "—"), "",
          "## 口径", "",
          "- 起点 = 最近一次“全集重出 / 导入”后的第一次派单（--anchor）；截至 = --until（默认现在）；进行中的阶段按截至时刻算实际用时。",
          "- 首帧 / 尾帧“定下”= passed / master_approve / redo_auto_approved / review_adopt / best_effort / hard_cap_exhausted / last_unavailable（兜底）；之后再派单 / 作废即回到未定。",
          "- 视频“定下”= vidgen SHOT_PASS / SHOT_BEST_EFFORT 或 state 里 chosen 的那段完成；合成周期 = night EP_RESOLVED → RETRO/report/director。",
          "- GPU 忙时 = 派单→出图 / 提交→完成 的墙钟（按道），利用率 = 忙时 ÷ 本集用时。",
          "- 归因：每个超预算阶段的分钟按四类证据秒数比例分配，证据是并行道上的叠加；没有证据的超预算记“逻辑”（流程等待）。",
          f"- 来源缺失：{', '.join(res['missing_sources']) or '无'}"]
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- 主流程
def run_report(run: str, ep: int, fetch_logs: bool = False, anchor: str = "regen", start: str | None = None, until: str | None = None,
               profile: str = "base", raw: Path | None = None, write_docs: bool = True, log=print, hosts=("gpu33", "gpu36"),
               checklist: Path | None = None, out_dir: Path | None = None, docs_dir: Path | None = None, laptop: Path | None = None) -> dict:
    raw = raw or (ROOT / "data/kpi/raw" / run)
    if fetch_logs:
        fetch(run, ep, raw, hosts=hosts, log=log)
    src = load_sources(run, ep, raw, hosts=hosts, laptop=laptop)
    cl = checklist or CHECKLIST
    budget = parse_budget(cl.read_text(encoding="utf-8") if cl.exists() else None, profile)
    rows = merge_producer(src, ep)
    until_dt = pt(until) if until else now_jst()
    if start:
        start_dt, info = pt(start), {"anchor": "manual", "anchor_ts": pt(start), "anchor_ev": "--start 指定"}
    else:
        start_dt, info = find_start([r for r in rows if r["_ts"] <= until_dt], ep, anchor)
    res = analyze(src, run, ep, start_dt, until_dt, budget, info, rows=rows)
    out_dir = out_dir or (ROOT / "data/kpi" / run)
    jp = out_dir / f"ep{ep:02d}_kpi.json"
    write_json(res, jp)
    mp = None
    if write_docs:
        mp = (docs_dir or (ROOT / "docs/master")) / f"KPI_{run}_ep{ep:02d}.md"
        mp.parent.mkdir(parents=True, exist_ok=True)
        tmp = mp.with_suffix(".md.part")
        tmp.write_text(render_md(res), encoding="utf-8")
        os.replace(tmp, mp)
    sm = summary(res, mp, jp)
    write_json(sm, out_dir / "latest.json")
    res["_paths"] = {"json": str(jp), "md": str(mp) if mp else None, "latest": str(out_dir / "latest.json")}
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--run", required=True)
    ap.add_argument("--episode", type=int, required=True)
    ap.add_argument("--fetch", action="store_true", help="先经 rssh 只读拉服务器日志到 data/kpi/raw/<run>/")
    ap.add_argument("--anchor", default="regen", choices=["regen", "import", "first-dispatch"])
    ap.add_argument("--start", help="手动指定起点（JST，如 2026-11-06T14:53）")
    ap.add_argument("--until", help="截至（JST），默认现在")
    ap.add_argument("--profile", default="base", choices=["base", "turbo"], help="首帧预算档：35 步 base / 8 步 turbo")
    ap.add_argument("--raw", help="缓存目录（默认 data/kpi/raw/<run>）")
    ap.add_argument("--no-docs", action="store_true", help="不写 docs/master/KPI_*.md")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):  # arch-ok: 非 tty / 旧解释器没有 reconfigure，照常输出
        pass
    log = (lambda *x: None) if a.quiet else print
    res = run_report(a.run, a.episode, fetch_logs=a.fetch, anchor=a.anchor, start=a.start, until=a.until, profile=a.profile,
                     raw=Path(a.raw) if a.raw else None, write_docs=not a.no_docs, log=log)
    if res.get("error"):
        log(f"🔴 {res['error']}")
        return 2
    sm = summary(res, None, None)
    log(f"ep{a.episode:02d} {sm['status']} 用时 {sm['elapsed_min']} / {sm['budget_min']} min，超 {sm['overrun_min']} min → {sm['attribution_min']}")
    for k, s in sm["stages"].items():
        log(f"  {STAGE_CN[k]:<6} {s['actual_min']!s:>7} / {s['budget_min']!s:>5} min  超 {s['overrun_min']!s:>5}  {s['status']}")
    log("写出：" + ", ".join(v for v in res["_paths"].values() if v))
    return 0


if __name__ == "__main__":
    sys.exit(main())
