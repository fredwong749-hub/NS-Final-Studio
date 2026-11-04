"""集级指标（docs/master/METRICS_SPEC.md §B 的计算方，METRICS-F 11-03）。

  episode_metrics.py --run series10_v2 --episode 1 [--no-html]
  episode_metrics.py compare --run series10_v2 --a 1 --b 2

产物：data/pipeline/runs/<run>/metrics/epNN_summary.json
      data/review_pages/metrics/<run>_epNN.html（单集）/ <run>_ep0A_vs_ep0B.html（对比）

只读真实记录；拿不到的数写 null 并在 nulls[] 说明原因。好莱坞质感分不在这里跑：由 tools/pipeline/hollywood_tick.py
在本地看图服务空闲时自动打，写 metrics/hollywood_epNN.jsonl，这里只读（总调度 1c46 ①）。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = "nsfs.metrics.episode/1"
P1_THRESHOLD = 34
OK_STATUS = {"ok", "reused", "approved", "passed", "imported", "reimported", "dry_run_ok", "ready", "generated", "importable"}
MODEL_SUFFIX = ("fable", "opus", "sonnet", "haiku")
SYSTEM_LANE_ACTORS = ("ASSET-WORKER", "producer", "DEBUG-RSI（IMGFIX", "idle")
WRITER_MODEL_FALLBACK = {"model": "fable（claude_agent）", "model_source": "PIPELINE_SOP_V2 步骤 1 / L-109：包与 .done 不记录模型，按 SOP 标注，不是测得的"}
MANUAL_WORDS = ("手工", "手动", "人工", "补救", "补记", "接手", "临时")
HOLLYWOOD_KEYS = ("composition", "lighting", "texture", "performance", "consistency", "exposure", "depth", "grade", "ai_look")   # rubric 本体在 tools/pipeline/hollywood_tick.py


# ---------- 小工具 ----------
def ts(s) -> datetime | None:
    if not s or not isinstance(s, str):
        return None
    s = s.strip().replace("T", " ")[:19]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def iso(d: datetime | None) -> str | None:
    return d.strftime("%Y-%m-%dT%H:%M:%S") if d else None


def secs(a: datetime | None, b: datetime | None) -> int | None:
    return int((b - a).total_seconds()) if a and b else None


def span(a: datetime | None, b: datetime | None, **extra) -> dict:
    s = secs(a, b)
    return {"start": iso(a), "end": iso(b), "seconds": s, "h": round(s / 3600, 2) if s is not None else None, **extra}


def _runs(root: Path):
    """按剧取路径的唯一入口 tools/autopilot/runs.py：root 下有就用 root 的（夹具 / 快照），否则用本仓库的"""
    import importlib.util as _u
    p = Path(root) / "tools" / "autopilot" / "runs.py"
    if not p.is_file():
        p = ROOT / "tools" / "autopilot" / "runs.py"
    sp = _u.spec_from_file_location("runs_for_metrics", p)
    m = _u.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


def _atomic_write(p: Path, text: str) -> None:
    """tmp + os.replace（ARCH_MAP §6）：读者看不到写了一半的文件"""
    tmp = p.with_name(f"{p.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, p)


def jload(p: Path, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def jlines(p: Path) -> list[dict]:
    out = []
    if not p.is_file():
        return out
    for ln in p.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            d = json.loads(ln)
        except ValueError:      # arch-ok: 追加写偶发坏行只跳过
            continue
        if isinstance(d, dict):
            out.append(d)
    return out


def ratio(n, d) -> float | None:
    return round(n / d, 4) if d else None


def dmax(*ds):
    ds = [d for d in ds if d]
    return max(ds) if ds else None


def dmin(*ds):
    ds = [d for d in ds if d]
    return min(ds) if ds else None


def union_seconds(segments: list[dict]) -> int:
    """等待段并集时长（几个作业同时等项目方挑选只算一份时间）；没有 to 的段按 seconds 推 to"""
    iv = []
    for s in segments:
        a = ts(s.get("from"))
        b = ts(s.get("to")) or (a + __import__("datetime").timedelta(seconds=s.get("seconds") or 0) if a else None)
        if a and b and b >= a:
            iv.append((a, b))
    total, cur = 0, None
    for a, b in sorted(iv):
        if cur and a <= cur[1]:
            cur[1] = max(cur[1], b)
        else:
            if cur:
                total += secs(cur[0], cur[1])
            cur = [a, b]
    if cur:
        total += secs(cur[0], cur[1])
    return total


class Paths:
    """本 run 相关的所有路径（root 可换成测试夹具目录）"""

    def __init__(self, root: Path, run: str):
        self.root, self.run = Path(root), run

    @property
    def run_dir(self): return self.root / "data" / "pipeline" / "runs" / self.run
    @property
    def asset_jobs(self): return self.root / "data" / "pipeline" / "asset_jobs" / self.run
    @property
    def worker_json(self): return self.root / "data" / "pipeline" / "asset_jobs" / "worker.json"
    @property
    def ab_assets(self): return self.root / "data" / "ab" / "v2_assets" / self.run
    @property
    def ab_cast(self): return self.root / "data" / "ab" / "v2_cast" / "takes.jsonl"
    @property
    def ab_golden(self): return self.root / "data" / "ab" / "v2_golden" / "takes.jsonl"     # 旧金样账（只读历史，不再计入）
    @property
    def renders(self):
        """帧的唯一账本 takes.json 所在的渲染根（runs.renders_dir，PRODMERGE-O：episode_metrics 改读 takes.json）"""
        return Path(_runs(self.root).renders_dir(self.run, self.root))

    @property
    def script(self):
        """导入稿（runs.script_path，K-OPS-F24：不写死 script_v2.json 路径）"""
        return Path(_runs(self.root).script_path(self.run, self.root))
    @property
    def issues(self): return self.root / "data" / "pipeline" / "issues.jsonl"
    @property
    def lifecycle(self): return self.root / "data" / "ops" / "api_lifecycle.jsonl"
    @property
    def lane_loans(self): return self.root / "data" / "debug" / "lane_loans.jsonl"
    @property
    def partition(self): return self.root / "data" / "state" / "netfix" / "partition.json"
    @property
    def v2_live(self): return self.root / "docs" / "master" / "V2_LIVE.md"
    @property
    def metrics_dir(self): return self.run_dir / "metrics"
    @property
    def review_dir(self): return self.root / "data" / "review_pages" / "metrics"

    def summary(self, ep: int): return self.metrics_dir / f"ep{ep:02d}_summary.json"
    def hollywood(self, ep: int): return self.metrics_dir / f"hollywood_ep{ep:02d}.jsonl"
    def stage_jsonl(self, ep: int): return self.metrics_dir / f"ep{ep:02d}.jsonl"


class Nulls:
    def __init__(self):
        self.items: list[dict] = []

    def add(self, key: str, why: str):
        self.items.append({"key": key, "why": why})


# ---------- 写作链 ----------
def load_autoflow(P: Paths, ep: int) -> tuple[dict, list[dict]]:
    af = jload(P.run_dir / "autoflow.json", {}) or {}
    if int(af.get("episode") or -1) != ep:
        af = jload(P.run_dir / f"autoflow_ep{ep:02d}.json", {}) or {}
    log = [d for d in jlines(P.run_dir / "autoflow.log") if d.get("episode") in (ep, str(ep))]
    return af, log


def done_model(done: Path) -> str | None:
    """.done 第 2 行 `model: <id>`（METRICS_SPEC §A 定稿）；没有 → None"""
    if not done.is_file():
        return None
    for ln in done.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r"\s*model\s*[:=]\s*(\S+)", ln)
        if m:
            return m.group(1)
    return None


def writing_calls(P: Paths, ep: int, nulls: Nulls) -> dict:
    """writer_out / writer_out_void / _rejected_* 的交稿数；evaluate role from writer_tasks 包"""
    rd = P.run_dir
    out = {"writer": {"calls": 0, "voided": 0, "by_step": {}, "models": {}}, "reviewer": {"calls": 0, "by_step": {}, "models": {}}}
    tasks = {}
    for f in (rd / "writer_tasks").glob("*.json") if (rd / "writer_tasks").is_dir() else []:
        t = jload(f, {}) or {}
        tasks[f.stem] = t
    ep_tag = f"ep{ep:02d}"

    def belongs(stem: str, task: dict | None) -> bool:
        if task and task.get("episode") not in (None, "", ep, str(ep)):
            return False
        return (ep_tag in stem) or stem.startswith(("P1", "P0")) or (task or {}).get("episode") in (ep, str(ep))

    def role_of(stem: str, task: dict | None) -> str:
        if task and task.get("role"):
            return "reviewer" if task["role"] != "writer" else "writer"
        return "reviewer" if stem.startswith(("facts_", "factcheck_")) else "writer"

    wo = rd / "writer_out"
    if not wo.is_dir():
        nulls.add("model_calls.writer", "writer_out/ 不存在")
        return out
    for f in sorted(wo.iterdir()):
        if f.suffix == ".done" or not f.is_file():
            continue
        stem = f.stem if f.suffix == ".json" else f.name.rsplit(".", 1)[0]
        task = tasks.get(stem)
        if not belongs(stem, task):
            continue
        role = role_of(stem, task)
        step = re.sub(r"_a\d+(\.md)?$", "", stem)
        slot = out[role]
        slot["calls"] += 1
        slot["by_step"][step] = slot["by_step"].get(step, 0) + 1
        model = done_model(Path(str(f) + ".done"))
        key = model or "unknown"
        slot["models"][key] = slot["models"].get(key, 0) + 1
    void_n = 0
    vd = rd / "writer_out_void"
    if vd.is_dir():
        void_n += sum(1 for f in vd.iterdir() if f.suffix == ".json" and "void" in f.name)
    for d in rd.glob("_rejected_*"):
        void_n += sum(1 for f in d.glob("writer_out_*.json"))
    out["writer"]["voided"] = void_n
    out["writer"]["calls_total_with_voided"] = out["writer"]["calls"] + void_n
    if out["writer"]["models"].keys() <= {"unknown"}:
        out["writer"].update(WRITER_MODEL_FALLBACK)
        nulls.add("model_calls.writer.model", WRITER_MODEL_FALLBACK["model_source"])
    if out["reviewer"]["models"].keys() <= {"unknown"}:
        done_txt = ""
        for f in wo.glob("fact*.done"):
            done_txt = f.read_text(encoding="utf-8", errors="replace").strip()[:60]
        out["reviewer"].update({"model": None, "model_source": f".done 只写了“{done_txt}”，没有型号" if done_txt else ".done 没有型号"})
        nulls.add("model_calls.reviewer.model", out["reviewer"]["model_source"])
    return out


def judge_calls(P: Paths, nulls: Nulls) -> dict:
    st = jload(P.run_dir / "judge_p1" / "STATE.json", {}) or {}
    rounds = st.get("rounds") or []
    if not rounds:
        nulls.add("model_calls.judges", "judge_p1/STATE.json 没有 rounds")
        return {"calls": 0, "rounds": 0, "by_model": {}, "round_means": [], "passed_any": None, "threshold": P1_THRESHOLD}
    by_model, means, calls = {}, [], 0
    for r in rounds:
        res = r.get("result") or {}
        ids = res.get("judge_ids") or []
        calls += len(ids)
        for j in ids:
            m = next((s for s in MODEL_SUFFIX if s in str(j).lower()), "unknown")
            by_model[m] = by_model.get(m, 0) + 1
        means.append(res.get("mean"))
    return {"calls": calls, "rounds": len(rounds), "by_model": by_model, "round_means": means,
            "passed_any": any(r.get("passed") for r in rounds), "threshold": P1_THRESHOLD,
            "released_by_owner": bool(st.get("owner_direction")) and not any(r.get("passed") for r in rounds)}


def writing_success(af: dict, log: list[dict], judges: dict, gates: dict) -> dict:
    stages = {s.get("id"): s for s in af.get("stages") or []}
    hist = af.get("agent_history") or []

    def stage_fp(sid):
        s = stages.get(sid)
        if not s:
            return {"attempts": None, "first_pass": None, "status": None}
        att = s.get("attempt") if s.get("attempt") is not None else 1
        ok = str(s.get("status")) in OK_STATUS
        return {"attempts": att, "first_pass": bool(ok and att == 1), "status": s.get("status")}

    patch = [h for h in hist if str(h.get("step", "")).startswith("patch_") and h.get("accepted") is not None]
    patch_steps = sorted({h["step"] for h in patch})
    patch_ok = sum(1 for h in patch if h.get("accepted") is True)
    import_fails = sum(1 for d in log if d.get("verdict") == "import_failed")
    p1g = (gates.get("gates") or {}).get("P1") or {}
    return {
        "p1_judges": {"rounds": judges.get("rounds"), "round_means": judges.get("round_means"), "threshold": P1_THRESHOLD,
                      "passed_any": judges.get("passed_any"), "first_pass": (judges.get("rounds") == 1 and judges.get("passed_any")) if judges.get("rounds") else None,
                      "released_by_owner_below_threshold": bool(p1g.get("released_by_owner") or p1g.get("below_threshold"))},
        "P2": stage_fp("P2"), "P3": stage_fp("P3"), "P4": stage_fp("P4"),
        "patch_loop": {"attempts": len(patch_steps), "accepted": patch_ok, "first_pass": (len(patch_steps) == 1 and patch_ok == 1) if patch_steps else None},
        "factcheck": {"first_pass": (str(stages.get("factcheck", {}).get("status")) in OK_STATUS and not stages.get("factcheck", {}).get("deviations")) if "factcheck" in stages else None},
        "import": {"failed_attempts": import_fails, "first_pass": import_fails == 0 and str(stages.get("import", {}).get("status")) in OK_STATUS if "import" in stages else None},
    }


def writing_time(af: dict, log: list[dict], gates: dict, nulls: Nulls) -> dict:
    started = ts(af.get("started")) or dmin(*[ts(d.get("at")) for d in log])
    p1 = (gates.get("gates") or {}).get("P1") or {}
    p1_ok = ts(p1.get("at")) if p1.get("status") == "approved" else None
    imported = dmax(*[ts(d.get("at")) for d in log if d.get("verdict") in ("imported", "reimported")])
    if not started:
        nulls.add("time.writing_p1", "autoflow.json 没有 started，autoflow.log 为空")
    if not p1_ok:
        nulls.add("time.writing_p1.end", "owner_gates.json 里 P1 没有 approved")
    if not imported:
        nulls.add("time.writing_p2_to_import.end", "autoflow.log 没有 verdict=imported")
    # 项目方等待：owner_direction → 下一次 owner 动作（revise / approve）
    owner_acts = sorted(ts(h.get("at")) for h in (gates.get("history") or []) if h.get("action") in ("revise", "approve") and ts(h.get("at")))
    waits, waiting = [], None
    for d in sorted(log, key=lambda x: x.get("at") or ""):
        t = ts(d.get("at"))
        if d.get("verdict") == "owner_direction" and waiting is None and t:
            waiting = t
        if waiting and any(waiting <= a <= (t or a) for a in owner_acts):
            a = min(a for a in owner_acts if a >= waiting)
            waits.append({"from": iso(waiting), "to": iso(a), "seconds": secs(waiting, a)})
            waiting = None
    if waiting is not None and owner_acts and max(owner_acts) >= waiting:
        a = min(a for a in owner_acts if a >= waiting)
        waits.append({"from": iso(waiting), "to": iso(a), "seconds": secs(waiting, a)})
    return {"writing_p1": span(started, p1_ok), "writing_p2_to_import": span(p1_ok, imported),
            "owner_wait_writing": {"seconds": union_seconds(waits), "sum_s": sum(w["seconds"] for w in waits) if waits else 0, "segments": waits},
            "_started": started, "_imported": imported}


# ---------- 资产阶段 A / 金样阶段 B ----------
def load_jobs(P: Paths, ep: int) -> list[dict]:
    jobs = []
    if not P.asset_jobs.is_dir():
        return jobs
    for f in sorted(P.asset_jobs.glob("*.json")):
        if f.name.startswith("_"):
            continue
        j = jload(f, None)
        if not isinstance(j, dict) or j.get("schema", "").split("/")[0] != "nsfs.asset_job":
            continue
        eps = j.get("episodes") or [j.get("episode")]
        if ep in [int(e) for e in eps if str(e).isdigit()]:
            jobs.append(j)
    return jobs


def load_takes(P: Paths, ep: int, jobs: list[dict]) -> dict[str, list[dict]]:
    """按来源归集本集的出图候选：sheet（阶段 A 作业）/ cast_face / scene（CAST-S 候选，经作业 target 关联）/ golden（按 shot 前缀）"""
    src: dict[str, list[dict]] = {"cast_face": [], "scene": [], "sheet": [], "golden": []}
    targets = {("cast_face" if j.get("kind") == "face" else "scene"): set() for j in jobs}
    for j in jobs:
        if j.get("kind") == "face":
            targets.setdefault("cast_face", set()).add(str(j.get("target")).split(":")[0])
        elif j.get("kind") == "scene":
            targets.setdefault("scene", set()).add(str(j.get("target")).split(":")[0])
        elif j.get("kind") == "sheet":
            for r in jlines(P.ab_assets / str(j.get("id")) / "takes.jsonl"):
                src["sheet"].append(r)
    for r in jlines(P.ab_cast):
        cid = str(r.get("id"))
        if cid in targets.get("cast_face", set()):
            src["cast_face"].append(r)
        elif cid in targets.get("scene", set()):
            src["scene"].append(r)
    src["golden"] = frame_takes(P, ep)       # 键名沿用（下游指标口径不变），内容 = takes.json 首帧版本
    return src


def frame_takes(P: Paths, ep: int, stage: str = "image") -> list[dict]:
    """本集每镜 takes.json 里的首帧版本 → {at, shot, n, pass, vlm, source=takes.json}（PRODMERGE-O：帧只记这一本账）。
    pass = postflight.ok（共用验收 QB 已并进 postflight）；尽力 / 坏图算不过"""
    out = []
    base = P.renders / f"ep{ep:02d}"
    for tj in sorted(base.glob("S*/takes.json")):
        try:
            d = json.loads(tj.read_text(encoding="utf-8"))
        except (OSError, ValueError):   # arch-ok: 坏账本只跳过这一镜（指标里少一镜，nulls 会显示）
            continue
        for t in d.get("takes") or []:
            if t.get("stage") != stage:
                continue
            pf = t.get("postflight") or t.get("contract") or {}
            qb = (next((i for i in pf.get("items") or [] if i.get("id") == "QB"), None) or {}).get("evidence") or {}
            out.append({"at": t.get("created_at"), "shot": f"ep{ep:02d}-{tj.parent.name}", "n": t.get("n"),
                        "compile_trace": {"shot": f"ep{ep:02d}-{tj.parent.name}"}, "lane": (t.get("producer") or {}).get("lane") or t.get("gpu"),
                        "pass": bool(pf.get("ok")) and not t.get("bad"), "postflight": pf,
                        "anomaly": qb.get("anomaly") or {}, "vlm": qb.get("bundle") or {},
                        "seed": t.get("seed"), "source": "takes.json"})
    return out


def take_passed(r: dict) -> bool:
    return bool(r.get("passed") if "passed" in r else r.get("pass"))


def vlm_calls_of(r: dict) -> int:
    n = 0
    v = r.get("vlm")
    if isinstance(v, dict) and (v.get("text") or v.get("items")):
        n += 1
    q9 = next((i for i in ((r.get("postflight") or {}).get("items") or []) if i.get("id") == "Q9"), None)
    if q9 and q9.get("status") in ("pass", "fail"):
        n += 1
    for k in ("age", "ocr"):
        if isinstance(r.get(k), dict) and r[k].get("text"):
            n += 1
    return n


def quality_of(rows: list[dict]) -> dict:
    def item(r, iid):
        return next((i for i in ((r.get("postflight") or {}).get("items") or []) if i.get("id") == iid), None)

    def count(getter):
        c = {}
        for r in rows:
            s = getter(r)
            c[s] = c.get(s, 0) + 1
        return c

    q1 = count(lambda r: ((item(r, "Q1") or {}).get("status") or "missing"))
    sims = []
    for r in rows:
        for pf in (((item(r, "Q1") or {}).get("evidence") or {}).get("per_face") or []):
            if isinstance(pf.get("sim"), (int, float)):
                sims.append(float(pf["sim"]))
    q9 = count(lambda r: ((item(r, "Q9") or {}).get("status") or "missing"))
    an = count(lambda r: str((r.get("anomaly") or {}).get("status") or "missing"))
    an_reasons = sum(1 for r in rows if (r.get("anomaly") or {}).get("reasons"))
    ok_n = tot = 0
    for r in rows:
        v = r.get("vlm") or {}
        if v.get("items"):
            tot += len(v["items"])
            ok_n += sum(1 for i in v["items"] if i.get("ok"))
        elif v.get("text"):
            lines = [re.sub(r"^\s*\d+\s*[.、．)]\s*", "", ln).strip() for ln in v["text"].splitlines() if ln.strip() and not ln.strip().startswith("总结")]
            lines = [ln for ln in lines if ln.startswith(("符合", "不符合"))]
            tot += len(lines)
            ok_n += sum(1 for ln in lines if ln.startswith("符合"))
    n = len(rows)
    passed = sum(1 for r in rows if take_passed(r))
    return {"takes": n, "passed": passed, "contract_pass_rate": ratio(passed, n),
            "q1_identity": {"status": q1, "cos_mean": round(sum(sims) / len(sims), 4) if sims else None, "cos_n": len(sims)},
            "q9_review": {"status": q9, "untested_ratio": ratio(q9.get("untested", 0) + q9.get("missing", 0), n)},
            "anomaly": {"status": an, "with_reasons": an_reasons},
            "vlm_items": {"ok": ok_n, "total": tot, "pass_rate": ratio(ok_n, tot)}}


def images_success(src: dict[str, list[dict]], jobs: list[dict]) -> dict:
    out = {}
    blocked = {}
    for j in jobs:
        n = sum(1 for ln in (j.get("log") or []) if "preflight 不过" in ln and "没有候选过检" not in ln)
        blocked[j.get("kind")] = blocked.get(j.get("kind"), 0) + n
    for k, rows in src.items():
        n, p = len(rows), sum(1 for r in rows if take_passed(r))
        out[k] = {"takes": n, "passed": p, "pass_rate": ratio(p, n), "takes_per_pass": round(n / p, 2) if p else None,
                  "preflight_blocked_attempts": blocked.get(k if k != "cast_face" else "face", 0) if k in ("sheet", "cast_face", "scene") else 0}
    allrows = [r for rows in src.values() for r in rows]
    n, p = len(allrows), sum(1 for r in allrows if take_passed(r))
    out["all"] = {"takes": n, "passed": p, "pass_rate": ratio(p, n), "takes_per_pass": round(n / p, 2) if p else None,
                  "preflight_blocked_attempts": sum(blocked.values())}
    return out


def jobs_summary(jobs: list[dict]) -> dict:
    by_kind: dict[str, dict] = {}
    for j in jobs:
        k = by_kind.setdefault(j.get("kind") or "?", {"n": 0, "states": {}, "attempts": 0, "first_try_done": 0})
        k["n"] += 1
        k["states"][j.get("state") or "?"] = k["states"].get(j.get("state") or "?", 0) + 1
        k["attempts"] += int(j.get("attempts") or 0)
        requeued = any("重新排队" in ln for ln in (j.get("log") or []))
        if j.get("state") == "done" and int(j.get("attempts") or 0) <= 1 and not requeued:
            k["first_try_done"] += 1
    return {"n": len(jobs), "by_kind": by_kind, "all_done": bool(jobs) and all(j.get("state") == "done" for j in jobs)}


def stage_a_time(jobs: list[dict], window_end: datetime | None, nulls: Nulls) -> tuple[dict, dict]:
    if not jobs:
        nulls.add("time.stage_a_assets", "本集没有资产作业记录（asset_jobs/<run>/）")
        return span(None, None, status="no_jobs"), {"seconds": None, "segments": [], "open": 0}
    start = dmin(*[ts(j.get("created_at")) for j in jobs])
    done = all(j.get("state") == "done" for j in jobs)
    last = dmax(*[ts(j.get("updated_at")) for j in jobs])
    sp = span(start, last if done else None, status="done" if done else "in_progress")
    if not done:
        sp["elapsed_so_far_s"] = secs(start, window_end or last)
    segs, open_n = [], 0
    for j in jobs:
        logs = j.get("log") or []
        t_notify = next((ts(ln[:19]) for ln in logs if ("投待办通知" in ln or "接管已有的待办通知" in ln)), None)
        t_pick = next((ts(ln[:19]) for ln in logs if "项目方选定" in ln), None)
        if not t_notify:
            continue
        if t_pick:
            segs.append({"job": j.get("id"), "from": iso(t_notify), "to": iso(t_pick), "seconds": secs(t_notify, t_pick), "open": False})
        else:
            open_n += 1
            segs.append({"job": j.get("id"), "from": iso(t_notify), "to": None, "seconds": secs(t_notify, window_end or last), "open": True})
    return sp, {"seconds": union_seconds(segs), "sum_s": sum(s["seconds"] or 0 for s in segs), "segments": segs, "open": open_n,
                "note": "seconds = 等待段并集（并行挑选只算一份）；sum_s = 逐作业累加"}


def stage_b_time(golden: list[dict], worker: dict, nulls: Nulls) -> dict:
    g_on = ((worker or {}).get("config") or {}).get("golden")
    if not golden:
        nulls.add("time.stage_b_golden", "本集还没有首帧版本（data/renders/<剧>/epNN/S*/takes.json 里没有 image 版本）")
        return span(None, None, status="not_started", golden_switch=g_on)
    ats = [ts(r.get("at")) for r in golden]
    return span(dmin(*ats), dmax(*ats), status="done", trial=False, golden_switch=g_on, source="takes.json",
                note="首帧出图时长按 takes.json（producer 主干，PRODMERGE-O）")


# ---------- 横切：介入 / GPU ----------
def in_window(t: datetime | None, w0: datetime | None, w1: datetime | None) -> bool:
    return bool(t) and (w0 is None or t >= w0) and (w1 is None or t <= w1)


def interventions(P: Paths, ep: int, af: dict, log: list[dict], jobs: list[dict], w0, w1, nulls: Nulls) -> dict:
    det = {"manual_cli": [], "rejected_deliverables": [], "requeue_after_fix": [], "api_restarts": [], "manual_lane_holds": []}
    for d in log:
        if d.get("source") in ("cli", "escalate") and d.get("verdict"):
            det["manual_cli"].append({"at": d.get("at"), "who": d.get("source"), "what": str(d.get("note") or "")[:120]})
    for h in af.get("agent_history") or []:
        if h.get("accepted") is False:
            det["rejected_deliverables"].append({"step": h.get("step"), "what": str(h.get("note") or "")[:120]})
    for j in jobs:
        for ln in j.get("log") or []:
            if "重新排队" in ln:
                det["requeue_after_fix"].append({"at": ln[:19], "job": j.get("id"), "what": ln[20:140]})
    if P.lifecycle.is_file():
        for d in jlines(P.lifecycle):
            if d.get("event") == "started" and in_window(ts(d.get("at")), w0, w1):
                by = str(d.get("by") or "")
                if "pytest" in by or "-sim" in by:
                    continue
                det["api_restarts"].append({"at": d.get("at"), "who": by, "what": "手起 / 恢复 API"})
    else:
        nulls.add("interventions.api_restarts", "data/ops/api_lifecycle.jsonl 不存在")
    if P.lane_loans.is_file():
        for d in jlines(P.lane_loans):
            if d.get("ev") in ("hold", "lend") and in_window(ts(d.get("ts")), w0, w1):
                by = str(d.get("by") or "")
                if any(by.startswith(a) for a in SYSTEM_LANE_ACTORS):
                    continue
                det["manual_lane_holds"].append({"at": d.get("ts"), "who": by[:40], "what": f"{d.get('ev')} {d.get('lane')}：{(d.get('why') or d.get('to') or '')[:60]}"})
    else:
        nulls.add("interventions.manual_lane_holds", "data/debug/lane_loans.jsonl 不存在")
    iss = [d for d in jlines(P.issues) if d.get("event") == "open" and d.get("run") == P.run and d.get("episode") in (ep, str(ep))]
    closed = {d.get("id") for d in jlines(P.issues) if d.get("event") == "close"}
    issues = {"opened": len(iss), "blocking": sum(1 for d in iss if d.get("blocking")), "closed": sum(1 for d in iss if d.get("id") in closed),
              "by_who": {}}
    for d in iss:
        issues["by_who"][d.get("who") or "?"] = issues["by_who"].get(d.get("who") or "?", 0) + 1
    live_n = None
    if P.v2_live.is_file():
        live_n = sum(1 for ln in P.v2_live.read_text(encoding="utf-8", errors="replace").splitlines() if any(w in ln for w in MANUAL_WORDS))
    else:
        nulls.add("interventions.v2_live_mentions", "docs/master/V2_LIVE.md 不存在")
    counts = {k: len(v) for k, v in det.items()}
    by_who = {}
    for k in ("manual_lane_holds", "api_restarts", "manual_cli"):
        for r in det[k]:
            who = str(r.get("who") or "?").split("（")[0][:24]
            slot = by_who.setdefault(k, {})
            slot[who] = slot.get(who, 0) + 1
    return {**counts, "total": sum(counts.values()), "by_who": by_who, "issues": issues,
            "v2_live_mentions": {"lines": live_n, "note": "V2_LIVE 只有 HH:MM，不能按本集时间窗过滤，只作参考"}, "detail": det}


def gpu_util(P: Paths, w0: datetime | None, w1: datetime | None, nulls: Nulls) -> dict:
    part = jload(P.partition, {}) or {}
    lanes = [l for host in (part.get("lanes") or {}).values() for l in host]
    if not lanes:
        nulls.add("gpu.lanes", "partition.json 没有 lanes")
    if not (w0 and w1):
        nulls.add("gpu", "没有 GPU 时间窗（阶段 A / B 都没开始）")
        return {"lanes": lanes, "window": span(w0, w1), "per_lane": {}, "overall": None, "basis": "挂道 / 借道时长 ÷ 墙钟，不是 nvidia-smi 真实算力"}
    events = [d for d in jlines(P.lane_loans) if ts(d.get("ts"))]
    if not events:
        nulls.add("gpu.busy", "lane_loans.jsonl 为空或不存在")
    per: dict[str, list[tuple[datetime, datetime, str]]] = {l: [] for l in lanes}
    open_: dict[str, tuple[datetime, datetime | None, str]] = {}
    for d in sorted(events, key=lambda x: x.get("ts")):
        lane, ev, t = d.get("lane"), d.get("ev"), ts(d.get("ts"))
        if lane not in per:
            continue
        if ev in ("hold", "lend", "lane_loan_add"):
            if lane in open_:
                s, _, by = open_.pop(lane)
                per[lane].append((s, t, by))
            open_[lane] = (t, ts(d.get("expires_at") or d.get("until")), str(d.get("by") or d.get("to") or "?").split("（")[0][:24])
        elif ev in ("release", "idle_release", "lane_loan_remove") or (ev == "release_noop" and d.get("cleared")):
            if lane in open_:
                s, _, by = open_.pop(lane)
                per[lane].append((s, t, by))
    for lane, (s, exp, by) in open_.items():
        per[lane].append((s, dmin(exp, w1) or w1, by))
    win = secs(w0, w1) or 0
    out, total_busy = {}, 0
    for lane in lanes:
        iv = sorted((max(s, w0), min(e, w1), by) for s, e, by in per[lane] if e > w0 and s < w1)
        merged: list[list[datetime]] = []
        actors: dict[str, int] = {}
        for s, e, by in iv:
            actors[by] = actors.get(by, 0) + (secs(s, e) or 0)
            if merged and s <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], e)
            else:
                merged.append([s, e])
        busy = sum(secs(s, e) for s, e in merged)
        total_busy += busy
        out[lane] = {"busy_s": busy, "util": ratio(busy, win), "by_actor_s": actors}
    return {"lanes": lanes, "window": span(w0, w1), "window_s": win, "per_lane": out,
            "overall": ratio(total_busy, win * len(lanes)) if lanes else None,
            "basis": "挂道 / 借道时长（lane_loans.jsonl hold/lend→release）÷ 墙钟，不是 nvidia-smi 真实算力利用率"}


# ---------- 好莱坞质感分 ----------
def hollywood_rows(path) -> list[dict]:
    r"""读 hollywood_epNN.jsonl 并整理：production_first 只认 shot=S\d+，按 (shot, take) 去重取最后一行；
    source=reference_compare / 非 S\d+ 的正片行不计；其它来源（资产 / 金样）原样保留。不改写文件。"""
    out, last = [], {}
    for r in jlines(path):
        src = r.get("source")
        if src == "reference_compare":
            continue
        if src == "production_first":
            if not re.fullmatch(r"S\d+", str(r.get("shot"))):
                continue
            last[(r.get("shot"), r.get("take"))] = len(out)
        out.append(r)
    keep = set(last.values())
    return [r for i, r in enumerate(out) if r.get("source") != "production_first" or i in keep]


def hollywood_read(P: Paths, ep: int, nulls: Nulls) -> dict:
    """只读 metrics/hollywood_epNN.jsonl（由 tools/pipeline/hollywood_tick.py 在看图空闲时自动写；总调度 1c46 ①：这里不现场跑）"""
    allrows = hollywood_rows(P.hollywood(ep))
    rows = [r for r in allrows if isinstance(r.get("scores"), dict)]
    failed = sum(1 for r in allrows if not isinstance(r.get("scores"), dict))
    if not rows:
        nulls.add("quality.hollywood", "还没有分：metrics/hollywood_epNN.jsonl 不存在或没有打成的行（自动打分拍 hollywood_tick 只在本地看图空闲时跑，"
                  f"开关 config/pipeline/hollywood_score.json；失败行 {failed}）")
        return {"n": 0, "mean": None, "by_item": {}, "by_source": {}, "scale": "1-10", "calls": len(allrows), "failed_attempts": failed}
    by_item = {}
    for k in HOLLYWOOD_KEYS:      # 旧 5 项记录没有新 4 项：只对有该项的行取均值
        vs = [float(r["scores"][k]) for r in rows if k in r["scores"]]
        if vs:
            by_item[k] = round(sum(vs) / len(vs), 2)
    by_src: dict[str, list[float]] = {}
    for r in rows:
        by_src.setdefault(r.get("source") or "?", []).append(float(r.get("mean") or 0))
    return {"n": len(rows), "mean": round(sum(float(r.get("mean") or 0) for r in rows) / len(rows), 2), "by_item": by_item,
            "by_source": {k: round(sum(v) / len(v), 2) for k, v in by_src.items()}, "scale": "1-10", "calls": len(allrows),
            "failed_attempts": failed, "models": sorted({str(r.get("model")) for r in rows}),
            "source": "tools/pipeline/hollywood_tick.py（自动，低优先级，只在本地 VLM 空闲时）"}


# ---------- 自动化 ----------
def automation(af: dict, jobs: list[dict], inter: dict) -> dict:
    steps = []
    for s in af.get("stages") or []:
        actor = "owner" if s.get("decider") == "owner" else "system"
        steps.append({"step": f"writing:{s.get('id')}", "actor": actor, "status": s.get("status")})
    for j in jobs:
        actor = "agent" if j.get("adopted_from") else "system"
        steps.append({"step": f"asset:{j.get('id')}", "actor": actor, "status": j.get("state")})
        if j.get("kind") in ("face", "scene", "sheet"):
            picked = any("项目方选定" in ln for ln in (j.get("log") or []))
            steps.append({"step": f"pick:{j.get('id')}", "actor": "owner", "status": "picked" if picked else j.get("state")})
    for kind, rows in (inter.get("detail") or {}).items():
        for r in rows:
            who = str(r.get("who") or "")
            actor = "owner" if "项目方" in who else "agent"
            steps.append({"step": f"intervention:{kind}", "actor": actor, "status": (r.get("what") or "")[:60]})
    by = {}
    for s in steps:
        by[s["actor"]] = by.get(s["actor"], 0) + 1
    return {"total_steps": len(steps), "system_steps": by.get("system", 0), "ratio": ratio(by.get("system", 0), len(steps)), "by_actor": by, "steps": steps}


# ---------- PLAN §1.3 每集头条指标（W24 RETRO-AUTO）----------
PRODUCER_MANUAL_EV = ("master_approve", "approve", "uncap", "unwait", "reject")     # 总调度 / 人工对单个对象动手（producer.py 子命令落的事件）
PLAN_TARGETS = {"automation_ratio": (">=", 0.6), "interventions": ("<=", 20), "gpu_util": (">=", 0.4)}   # PLAN_V2_MASTER §1.3（ep02 起）


def _ep_of_obj(obj: str) -> int | None:
    m = re.search(r"ep(\d{2})", str(obj or ""))
    return int(m.group(1)) if m else None


def _ep_windows(P: Paths, ep: int) -> tuple[datetime | None, datetime | None]:
    """本集时间窗：autoflow_epNN.started → 下一集 autoflow started（没有就开放）。用来归属不带集号的记录（资产挑选等）"""
    a = ts((jload(P.run_dir / f"autoflow_ep{ep:02d}.json", {}) or {}).get("started"))
    b = ts((jload(P.run_dir / f"autoflow_ep{ep + 1:02d}.json", {}) or {}).get("started"))
    return a, b


def _belongs(rec_ep: int | None, at: datetime | None, ep: int, w: tuple) -> bool:
    if rec_ep is not None:
        return rec_ep == ep
    return bool(at and w[0] and at >= w[0] and (w[1] is None or at < w[1]))


def _median(xs: list[float]) -> float | None:
    xs = sorted(xs)
    if not xs:
        return None
    m = len(xs) // 2
    return round(xs[m] if len(xs) % 2 else (xs[m - 1] + xs[m]) / 2, 2)


def headline(root: Path, run: str, ep: int, nulls: Nulls | None = None) -> dict:
    """PLAN_V2_MASTER §1.3 的六项（结构化，RETRO 两集对比表读这里）：
      automation_ratio = 无人工介入的对象 / 全部对象（对象 = producer 首帧 / 尾帧 / 视频 obj + 项目方挑过的资产对象）
      interventions    = owner_queue/decisions.jsonl 本集条数 + producer 日志 master_approve/approve/uncap/unwait/reject 事件
      gpu_util         = producer 日志 rendered.gpu_s 合计 ÷（墙钟 × 用到的道数）；墙钟 = 本集第一条 dispatch → 最后一条 rendered
      hollywood_median = metrics/hollywood_epNN.jsonl 每行 mean 的中位数
      one_pass         = 首帧 / 尾帧 / 视频：第一版（take 最小的 adopt）就 ok 的对象比例
      issues           = issues.jsonl 本集卡点（不含 who=RETRO 的复盘跟进项）"""
    nulls = nulls or Nulls()
    P = Paths(root, run)
    w = _ep_windows(P, ep)
    plog = jlines(root / "data" / "producer" / "runs" / run / "log.jsonl")
    if not plog:
        nulls.add("headline.producer", f"data/producer/runs/{run}/log.jsonl 不存在或为空")
    objs: set[str] = set()
    manual: dict[str, list[str]] = {}
    adopts: dict[str, list[dict]] = {}
    gpu_s, lanes, t_first, t_last = 0.0, set(), None, None
    n_inter = 0
    for d in plog:
        obj = str(d.get("obj") or "")
        if _ep_of_obj(obj) != ep:
            continue
        at = ts(d.get("ts"))
        kind = obj.split(":")[0] if ":" in obj else ""
        if kind in ("first", "last", "video"):
            objs.add(obj)
        ev = d.get("ev")
        if ev in PRODUCER_MANUAL_EV:
            n_inter += 1
            objs.add(obj)
            manual.setdefault(obj, []).append(ev)
        elif ev == "adopt" and kind in ("first", "last", "video"):
            adopts.setdefault(obj, []).append(d)
        elif ev == "dispatch":
            t_first = dmin(t_first, at)
        elif ev == "rendered":
            gpu_s += float(d.get("gpu_s") or 0)
            if d.get("lane"):
                lanes.add(d["lane"])
            t_last = dmax(t_last, at)
    dec = [d for d in jlines(root / "data" / "owner_queue" / "decisions.jsonl")
           if ((d.get("applied") or {}).get("run") in (None, run))
           and _belongs(_ep_of_obj(d.get("id")), ts(d.get("at")), ep, w)]
    for d in dec:
        o = f"owner:{(d.get('applied') or {}).get('object') or d.get('id')}"
        objs.add(o)
        manual.setdefault(o, []).append(str(d.get("kind") or "decision"))
    n_inter += len(dec)
    one_pass = {}
    for kind in ("first", "last", "video"):
        rows = {o: sorted(v, key=lambda x: int(x.get("take") or 0)) for o, v in adopts.items() if o.startswith(kind + ":")}
        ok = sum(1 for v in rows.values() if v and v[0].get("ok") is True)
        one_pass[kind] = {"objects": len(rows), "one_pass": ok, "rate": ratio(ok, len(rows))}
        if not rows:
            nulls.add(f"headline.one_pass.{kind}", "producer 日志里本集没有这一类 adopt")
    wall = secs(t_first, t_last)
    gpu = {"gpu_s": round(gpu_s, 1), "wall_s": wall, "lanes": sorted(lanes),
           "ratio": ratio(gpu_s, (wall or 0) * max(1, len(lanes))) if wall else None,
           "basis": "producer 日志 rendered.gpu_s 合计 ÷（本集 dispatch→rendered 墙钟 × 用到的道数）"}
    if gpu["ratio"] is None:
        nulls.add("headline.gpu_util", "producer 日志里本集没有 dispatch→rendered 墙钟")
    hw = [float(r["mean"]) for r in hollywood_rows(P.hollywood(ep)) if isinstance(r.get("scores"), dict) and r.get("mean") is not None]
    iss = [d for d in jlines(P.issues) if d.get("event") == "open" and d.get("run") == run and d.get("episode") in (ep, str(ep))
           and d.get("who") != "RETRO"]
    closed = {d.get("id") for d in jlines(P.issues) if d.get("event") == "close"}
    n_obj = len(objs)
    out = {"automation_ratio": ratio(n_obj - len(manual), n_obj), "objects": n_obj, "manual_objects": len(manual),
           "interventions": n_inter, "interventions_detail": {"owner_decisions": len(dec), "producer_manual_events": n_inter - len(dec)},
           "gpu_util": gpu["ratio"], "gpu": gpu, "hollywood_median": _median(hw), "hollywood_n": len(hw),
           "one_pass": one_pass, "one_pass_first": one_pass["first"]["rate"], "one_pass_last": one_pass["last"]["rate"],
           "one_pass_video": one_pass["video"]["rate"],
           "issues": len(iss), "issues_open": sum(1 for d in iss if d.get("id") not in closed), "issues_closed": sum(1 for d in iss if d.get("id") in closed),
           "targets": {k: f"{op} {v}" for k, (op, v) in PLAN_TARGETS.items()}}
    return out


HEADLINE_ROWS = [   # (标签, headline 键, 方向)：RETRO“两集对比”逐项判 ≥（本集不能比上一集差）
    ("自动化率", "automation_ratio", "higher"),
    ("人工介入次数", "interventions", "lower"),
    ("GPU 占用", "gpu_util", "higher"),
    ("好莱坞分中位数", "hollywood_median", "higher"),
    ("首帧一次过率", "one_pass_first", "higher"),
    ("尾帧一次过率", "one_pass_last", "higher"),
    ("视频一次过率", "one_pass_video", "higher"),
    ("卡点数", "issues", "lower"),
]


def compare_headline(prev: dict | None, cur: dict) -> list[dict]:
    """逐项：ok = 本集不比上一集差（持平算过）；任一边是 null = n/a（不算过也不算退步，RETRO 里列出来）"""
    a, b = (prev or {}).get("headline") or {}, cur.get("headline") or {}
    rows = []
    for label, key, better in HEADLINE_ROWS:
        va, vb = a.get(key), b.get(key)
        if isinstance(va, (int, float)) and isinstance(vb, (int, float)):
            ok = vb >= va if better == "higher" else vb <= va
            verdict = "same" if vb == va else ("better" if ok else "worse")
        else:
            verdict = "n/a"
        tgt = PLAN_TARGETS.get(key)
        met = None
        if tgt and isinstance(vb, (int, float)):
            met = vb >= tgt[1] if tgt[0] == ">=" else vb <= tgt[1]
        rows.append({"label": label, "key": key, "a": va, "b": vb, "verdict": verdict,
                     "target": f"{tgt[0]} {tgt[1]}" if tgt else None, "target_met": met})
    return rows


# ---------- 汇总 ----------
def collect(root: Path, run: str, ep: int) -> dict:
    P = Paths(root, run)
    nulls = Nulls()
    af, log = load_autoflow(P, ep)
    if not af and not log:
        nulls.add("writing", f"autoflow.json / autoflow.log 里没有第 {ep} 集")
    if not P.stage_jsonl(ep).is_file():
        nulls.add("writing.stage_jsonl", "metrics/epNN.jsonl（METRICS_SPEC §A）未落盘，写作段按 autoflow.log / autoflow.json 反推")
    gates = jload(P.run_dir / "owner_gates.json", {}) or {}
    calls = writing_calls(P, ep, nulls)
    judges = judge_calls(P, nulls)
    jobs = load_jobs(P, ep)
    src = load_takes(P, ep, jobs)
    worker = jload(P.worker_json, {}) or {}
    wt = writing_time(af, log, gates, nulls)
    all_rows = [r for rows in src.values() for r in rows]
    w_end = dmax(wt["_imported"], *[ts(j.get("updated_at")) for j in jobs], *[ts(r.get("at")) for r in all_rows],
                 *[ts(d.get("at")) for d in log])
    w_start = wt["_started"]
    a_span, a_wait = stage_a_time(jobs, w_end, nulls)
    b_span = stage_b_time(src["golden"], worker, nulls)
    inter = interventions(P, ep, af, log, jobs, w_start, w_end, nulls)
    gpu_w0 = dmin(ts(a_span.get("start")), ts(b_span.get("start")))
    gpu = gpu_util(P, gpu_w0, w_end, nulls)
    quality = {k: quality_of(v) for k, v in src.items()}
    quality["all"] = quality_of(all_rows)
    quality["hollywood"] = hollywood_read(P, ep, nulls)
    vlm_calls = sum(vlm_calls_of(r) for r in all_rows)
    time_block = {k: v for k, v in wt.items() if not k.startswith("_")}
    time_block.update({"stage_a_assets": a_span, "stage_b_golden": b_span, "owner_wait_stage_a": a_wait,
                       "owner_wait_total_s": (wt["owner_wait_writing"]["seconds"] or 0) + (a_wait["seconds"] or 0),
                       "total_wall": span(w_start, w_end, note="窗尾 = 本集最后一条可见记录；阶段 A 未完成时不是终点")})
    summary = {
        "schema": SCHEMA, "run": run, "episode": ep, "generated_at": iso(datetime.now()),
        "shots": _shot_count(root, run, ep, nulls),
        "model_calls": {**calls, "judges": judges,
                        "vlm": {"calls": vlm_calls, "calls_estimated": True, "basis": "每条 take：逐条核对 1 + Q9 判了 1 + age 1 + ocr 1"},
                        "hollywood_vlm": {"calls": quality["hollywood"].get("calls", 0)},
                        "agent_calls_total": calls["writer"]["calls"] + calls["reviewer"]["calls"] + judges["calls"]},
        "interventions": inter,
        "time": time_block,
        "success": {"writing": writing_success(af, log, judges, gates), "images": images_success(src, jobs), "asset_jobs": jobs_summary(jobs)},
        "quality": quality,
        "automation": automation(af, jobs, inter),
        "gpu": gpu,
        "headline": headline(root, run, ep, nulls),
        "nulls": nulls.items,
    }
    return summary


def _shot_count(root: Path, run: str, ep: int, nulls: Nulls) -> int | None:
    doc = jload(Paths(root, run).script, {}) or {}
    for e in doc.get("episodes") or []:
        if int(e.get("number") or -1) == ep:
            return len(e.get("shots") or [])
    nulls.add("shots", "导入稿里没有本集")
    return None


# ---------- 对比 ----------
# (标签, 路径, 方向: lower = 越小越好, higher = 越大越好, None = 只看)
KEY_ROWS = [
    ("写手 agent 调用", "model_calls.writer.calls", "lower"),
    ("写手作废稿", "model_calls.writer.voided", "lower"),
    ("评审 agent 调用", "model_calls.reviewer.calls", "lower"),
    ("P1 评委调用", "model_calls.judges.calls", "lower"),
    ("agent 调用合计", "model_calls.agent_calls_total", "lower"),
    ("本地 VLM 调用（估）", "model_calls.vlm.calls", "lower"),
    ("人工 / agent 介入", "interventions.total", "lower"),
    ("  手工命令", "interventions.manual_cli", "lower"),
    ("  退稿", "interventions.rejected_deliverables", "lower"),
    ("  修后重排", "interventions.requeue_after_fix", "lower"),
    ("  手起 API", "interventions.api_restarts", "lower"),
    ("  手工挂道", "interventions.manual_lane_holds", "lower"),
    ("卡点登记", "interventions.issues.opened", "lower"),
    ("写作 P1 (h)", "time.writing_p1.h", "lower"),
    ("P2→导入 (h)", "time.writing_p2_to_import.h", "lower"),
    ("资产阶段 A (h)", "time.stage_a_assets.h", "lower"),
    ("金样阶段 B (h)", "time.stage_b_golden.h", "lower"),
    ("项目方等待 (s)", "time.owner_wait_total_s", "lower"),
    ("总墙钟 (h)", "time.total_wall.h", "lower"),
    ("P1 评审轮数", "success.writing.p1_judges.rounds", "lower"),
    ("导入失败次数", "success.writing.import.failed_attempts", "lower"),
    ("出图候选数", "success.images.all.takes", None),
    ("契约通过率", "success.images.all.pass_rate", "higher"),
    ("每张通过图耗出图", "success.images.all.takes_per_pass", "lower"),
    ("preflight 挡掉的尝试", "success.images.all.preflight_blocked_attempts", "lower"),
    ("Q1 身份余弦均值", "quality.all.q1_identity.cos_mean", "higher"),
    ("Q9 未判比例", "quality.all.q9_review.untested_ratio", "lower"),
    ("VLM 逐项通过率", "quality.all.vlm_items.pass_rate", "higher"),
    ("好莱坞质感分 (1-10)", "quality.hollywood.mean", "higher"),
    ("自动化比例", "automation.ratio", "higher"),
    ("GPU 占用率", "gpu.overall", "higher"),
]


def dig(d: dict, path: str):
    cur = d
    for k in path.split("."):
        if not isinstance(cur, dict) or k not in cur:
            return None
        cur = cur[k]
    return cur


def compare(a: dict, b: dict) -> list[dict]:
    rows = []
    for label, path, better in KEY_ROWS:
        va, vb = dig(a, path), dig(b, path)
        row = {"label": label, "path": path, "a": va, "b": vb, "delta": None, "delta_pct": None, "verdict": "n/a"}
        if isinstance(va, (int, float)) and isinstance(vb, (int, float)) and not isinstance(va, bool) and not isinstance(vb, bool):
            row["delta"] = round(vb - va, 4)
            row["delta_pct"] = round((vb - va) / va * 100, 1) if va else None
            if better and row["delta"] != 0:
                good = (row["delta"] < 0) if better == "lower" else (row["delta"] > 0)
                row["verdict"] = "better" if good else "worse"
            elif row["delta"] == 0:
                row["verdict"] = "same"
            else:
                row["verdict"] = "info"
        rows.append(row)
    return rows


# ---------- HTML ----------
CSS = """
:root{--bg:#fff;--fg:#1a1a1a;--mut:#666;--line:#e3e3e3;--good:#1b7f3b;--bad:#b3261e;--na:#999;--head:#f4f4f4}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#111;--fg:#eee;--mut:#aaa;--line:#333;--head:#1d1d1d;--good:#5fd38d;--bad:#ff7b72}}
body{background:var(--bg);color:var(--fg);font:14px/1.5 -apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;margin:0;padding:16px;max-width:1100px}
h1{font-size:20px;margin:0 0 4px}h2{font-size:15px;margin:22px 0 6px;border-bottom:1px solid var(--line);padding-bottom:3px}
.mut{color:var(--mut);font-size:12px}table{border-collapse:collapse;width:100%}th,td{border-bottom:1px solid var(--line);padding:4px 8px;text-align:left;vertical-align:top}
th{background:var(--head);font-weight:600}td.num{text-align:right;font-variant-numeric:tabular-nums}
.good{color:var(--good);font-weight:600}.bad{color:var(--bad);font-weight:600}.na{color:var(--na)}
details{margin:6px 0}summary{cursor:pointer;color:var(--mut)}pre{font-size:11px;white-space:pre-wrap;word-break:break-all;background:var(--head);padding:8px;border-radius:4px}
"""


def _fmt(v) -> str:
    if v is None:
        return "<span class=na>null</span>"
    if isinstance(v, bool):
        return "是" if v else "否"
    if isinstance(v, float):
        return f"{v:.3f}".rstrip("0").rstrip(".") if abs(v) < 1 else f"{v:.2f}"
    return str(v)


def _esc(s) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _nulls_html(s: dict) -> str:
    if not s.get("nulls"):
        return "<p class=mut>没有空缺。</p>"
    return "<ul class=mut>" + "".join(f"<li><b>{_esc(n['key'])}</b>：{_esc(n['why'])}</li>" for n in s["nulls"]) + "</ul>"


def _detail_html(s: dict) -> str:
    inter = s.get("interventions") or {}
    parts = []
    for k, rows in (inter.get("detail") or {}).items():
        if rows:
            parts.append(f"<h3 style='font-size:13px;margin:8px 0 2px'>{_esc(k)}（{len(rows)}）</h3><ul class=mut>" +
                         "".join(f"<li>{_esc(r.get('at') or r.get('step') or '')} {_esc(r.get('who') or r.get('job') or '')}：{_esc(r.get('what') or '')}</li>" for r in rows) + "</ul>")
    return "".join(parts) or "<p class=mut>无</p>"


def render_single(s: dict) -> str:
    rows = "".join(f"<tr><td>{_esc(l)}</td><td class=num>{_fmt(dig(s, p))}</td><td class=mut>{_esc(p)}</td></tr>" for l, p, _ in KEY_ROWS)
    title = f"{s['run']} ep{s['episode']:02d} 集级指标"
    return f"""<!doctype html><html lang=zh><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>{_esc(title)}</title><style>{CSS}</style></head>
<body><h1>{_esc(title)}</h1><p class=mut>生成 {_esc(s.get('generated_at'))} · 镜头数 {_fmt(s.get('shots'))} · 口径见 docs/master/METRICS_SPEC.md</p>
<h2>一览</h2><table><tr><th>指标</th><th>值</th><th>键</th></tr>{rows}</table>
<h2>人工 / agent 介入明细</h2>{_detail_html(s)}
<h2>空缺（null）与原因</h2>{_nulls_html(s)}
<details><summary>完整 JSON</summary><pre>{_esc(json.dumps({k: v for k, v in s.items() if k != 'automation'}, ensure_ascii=False, indent=1))}</pre></details>
</body></html>"""


def render_compare(a: dict, b: dict, rows: list[dict]) -> str:
    def cls(v):
        return {"better": "good", "worse": "bad", "same": "", "info": "", "n/a": "na"}.get(v, "")
    trs = "".join(
        f"<tr><td>{_esc(r['label'])}</td><td class=num>{_fmt(r['a'])}</td><td class=num>{_fmt(r['b'])}</td>"
        f"<td class='num {cls(r['verdict'])}'>{_fmt(r['delta'])}{'' if r['delta_pct'] is None else f' ({r['delta_pct']:+.1f}%)'}</td>"
        f"<td class={cls(r['verdict']) or 'mut'}>{ {'better': '更好', 'worse': '更差', 'same': '持平', 'info': '—', 'n/a': '不适用'}[r['verdict']] }</td></tr>"
        for r in rows)
    ea, eb = f"ep{a['episode']:02d}", f"ep{b['episode']:02d}"
    title = f"{a['run']} {ea} vs {eb}"
    return f"""<!doctype html><html lang=zh><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>{_esc(title)}</title><style>{CSS}</style></head>
<body><h1>{_esc(title)} 集级对比</h1><p class=mut>{ea} 生成 {_esc(a.get('generated_at'))} · {eb} 生成 {_esc(b.get('generated_at'))} · 方向：调用 / 时间 / 介入越少越好，通过率 / 质感 / 自动化越高越好 · 口径见 docs/master/METRICS_SPEC.md</p>
<table><tr><th>指标</th><th>{ea}</th><th>{eb}</th><th>差值</th><th>判定</th></tr>{trs}</table>
<h2>{ea} 空缺</h2>{_nulls_html(a)}<h2>{eb} 空缺</h2>{_nulls_html(b)}
<h2>{ea} 介入明细</h2>{_detail_html(a)}<h2>{eb} 介入明细</h2>{_detail_html(b)}
</body></html>"""


# ---------- 入口 ----------
def write_summary(root: Path, run: str, ep: int, summary: dict, html: bool = True) -> dict[str, Path]:
    P = Paths(root, run)
    P.metrics_dir.mkdir(parents=True, exist_ok=True)
    out = {"json": P.summary(ep)}
    _atomic_write(P.summary(ep), json.dumps(summary, ensure_ascii=False, indent=1))
    if html:
        P.review_dir.mkdir(parents=True, exist_ok=True)
        out["html"] = P.review_dir / f"{run}_ep{ep:02d}.html"
        _atomic_write(out["html"], render_single(summary))
    return out


def write_compare(root: Path, run: str, a: int, b: int) -> tuple[Path, list[dict]]:
    P = Paths(root, run)
    sa, sb = jload(P.summary(a)), jload(P.summary(b))
    missing = [e for e, s in ((a, sa), (b, sb)) if not s]
    if missing:
        raise FileNotFoundError("先算这些集的 summary：" + ", ".join(f"ep{e:02d}" for e in missing))
    rows = compare(sa, sb)
    P.review_dir.mkdir(parents=True, exist_ok=True)
    out = P.review_dir / f"{run}_ep{a:02d}_vs_ep{b:02d}.html"
    _atomic_write(out, render_compare(sa, sb, rows))
    _atomic_write(P.metrics_dir / f"compare_ep{a:02d}_ep{b:02d}.json", json.dumps(rows, ensure_ascii=False, indent=1))
    return out, rows


def _headline_line(h: dict) -> str:
    return (f"§1.3 头条：自动化率 {h.get('automation_ratio')}（{h.get('manual_objects')}/{h.get('objects')} 个对象有人工）；人工介入 {h.get('interventions')}；"
            f"GPU {h.get('gpu_util')}；好莱坞中位 {h.get('hollywood_median')}（n={h.get('hollywood_n')}）；一次过 首帧 {h.get('one_pass_first')} / "
            f"尾帧 {h.get('one_pass_last')} / 视频 {h.get('one_pass_video')}；卡点 {h.get('issues')}（未关 {h.get('issues_open')}）")


def brief(s: dict) -> str:
    mc, t, it, im = s["model_calls"], s["time"], s["interventions"], s["success"]["images"]["all"]
    return "\n".join([
        f"{s['run']} ep{s['episode']:02d}  镜头 {s.get('shots')}",
        f"agent 调用：写手 {mc['writer']['calls']}（作废 {mc['writer']['voided']}）/ 评审 {mc['reviewer']['calls']} / 评委 {mc['judges']['calls']} {mc['judges']['by_model']}；本地 VLM≈{mc['vlm']['calls']}",
        f"介入：{it['total']}（手工命令 {it['manual_cli']}，退稿 {it['rejected_deliverables']}，修后重排 {it['requeue_after_fix']}，手起 API {it['api_restarts']}，手工挂道 {it['manual_lane_holds']}）；卡点 {it['issues']['opened']}（阻断 {it['issues']['blocking']}）",
        f"时间：P1 {t['writing_p1']['h']}h，P2→导入 {t['writing_p2_to_import']['h']}h，阶段 A {t['stage_a_assets'].get('h')}h（{t['stage_a_assets'].get('status')}），阶段 B {t['stage_b_golden'].get('h')}h（{t['stage_b_golden'].get('status')}），项目方等待 {round(t['owner_wait_total_s'] / 60)}min",
        f"出图：{im['takes']} 张候选，通过 {im['passed']}（{im['pass_rate']}），每张通过图 {im['takes_per_pass']} 次；preflight 挡掉 {im['preflight_blocked_attempts']} 次",
        f"自动化 {s['automation']['ratio']}（{s['automation']['by_actor']}）；GPU 占用 {s['gpu']['overall']}；好莱坞分 {s['quality']['hollywood']['mean']}",
        *([_headline_line(s["headline"])] if s.get("headline") else []),
        f"空缺 {len(s['nulls'])} 项（见 nulls[]）",
    ])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", nargs="?", default="calc", choices=["calc", "compare"])
    ap.add_argument("--run", required=True)
    ap.add_argument("--episode", type=int)
    ap.add_argument("--a", type=int)
    ap.add_argument("--b", type=int)
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--no-html", action="store_true")
    a = ap.parse_args(argv)
    root = Path(a.root)
    if a.cmd == "compare":
        if a.a is None or a.b is None:
            ap.error("compare 需要 --a 和 --b")
        out, rows = write_compare(root, a.run, a.a, a.b)
        for r in rows:
            print(f"{r['label']:<18} {_fmt(r['a']):>10} -> {_fmt(r['b']):>10}  {r['verdict']}")
        print(f"对比页：{out}")
        return 0
    if a.episode is None:
        ap.error("计算需要 --episode")
    s = collect(root, a.run, a.episode)
    outs = write_summary(root, a.run, a.episode, s, html=not a.no_html)
    print(brief(s))
    for k, v in outs.items():
        print(f"{k}: {v}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
