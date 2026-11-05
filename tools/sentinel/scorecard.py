"""SCORECARD 七项自动计分（总调度 11-02 17:4x；docs/master/SCORECARD.md 附录 A；规则 K-OPS-S17）。

项目方原话（11-02 17:4x）：“无论是 UI、剧本、工作流、rendering 还是 GPU 管理、代码，全都要达到 100 分。没有达到 100 分，自动开始迭代。”

七项（SENTINEL 每 20 分钟写一行 / 项到 data/rsi/scores.jsonl，by = "SENTINEL scorecard"）：
  image   出图     沿用 tools/imglab/score.py（RSI_PROGRAM 线 1 公式）重算
  video   视频     沿用 tools/vidlab/score.py score（线 2）重算
  script  剧本     沿用 tools/script_rsi/line3_score.py（线 3，第二季）重算
  system  代码     沿用 tools/rsi/system_score.py（线 5）重算
  ui      UI       本文件 ui_score：顶栏（topbar_check）/ 无空白页 / 整洁（S9 同规则）/ 无技术词 / UI 反馈单
  workflow 工作流  本文件 workflow_score：无人值守 / 不卡段 / 不重复出图 / 反馈自动入队
  gpu     GPU 管理 本文件 gpu_score：真实运行率 / 命令通道成功率 / 部署停派时长 / 常驻服务 / 借道到期
新三项里 SCORECARD“100 分标准”中还不能代码测的条目列在 unmeasured；有未测条目时总分封顶 95（不能把没测当满分）。
不许靠改口径涨分：权重 / 线写在 config/policies/sentinel.yaml SC_scorecard，改动要总调度批准并在 SCORECARD.md 留痕。

  .venv/Scripts/python.exe tools/sentinel/scorecard.py once        # 立即算七项、写 scores.jsonl、打印
  .venv/Scripts/python.exe tools/sentinel/scorecard.py ui-measure  # 只跑界面实测（后台用；写 data/rsi/ui_measure.json）
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools.sentinel import judges as J  # noqa: E402

PY = str(ROOT / ".venv/Scripts/python.exe")
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)
UI_OUT = ROOT / "data/rsi/ui_measure.json"
SCORES = ROOT / "data/rsi/scores.jsonl"


def cfg() -> dict:
    from tools.autopilot import policy
    return policy.load()["sentinel"]["SC_scorecard"]["value"]


def jl(p, default=None):
    try:
        return json.loads((ROOT / p).read_text(encoding="utf-8"))
    except (OSError, ValueError):  # arch-ok: 调用方按 None 记“未测”
        return default


def _run(args: list[str], timeout: int) -> str | None:
    try:
        r = subprocess.run([PY, *args], cwd=str(ROOT), capture_output=True, timeout=timeout, creationflags=NOWIN,
                           env={**os.environ, "PYTHONIOENCODING": "utf-8", "OMP_NUM_THREADS": "2"})
        return r.stdout.decode("utf-8", "replace")
    except (OSError, subprocess.TimeoutExpired):  # arch-ok: None = 该项本轮未测（写 missing，不写分）
        return None


def _first_json(txt: str | None) -> dict | None:
    """输出里第一个完整 JSON 对象（单行或缩进多行都认）"""
    if not txt:
        return None
    dec = json.JSONDecoder()
    for i, ch in enumerate(txt):
        if ch == "{":
            try:
                obj, _ = dec.raw_decode(txt[i:])
                if isinstance(obj, dict) and "score" in obj:
                    return obj
            except ValueError:  # arch-ok: 不是 JSON 起点，继续找
                continue
    return None


# ------------------------------------------------------------------ 沿用的四项（重算）
def score_run() -> str:
    """计分对象 = 主 run（总调度 20:10：V1 已归档不计分，按 series10_v2 算）"""
    from tools.autopilot import runs as RUNS
    return RUNS.primary_run()


def stage_of(run: str) -> tuple[str, dict]:
    """run 当前走到哪一段（S1 剧本 → S2 资产 → S3 出图 → S4 视频 → S5 成片）。
    PRODMERGE-O 11-03（C-6）：非 legacy 剧读唯一阶段模型 tools/master/sop_gate.stage_view（stage_status.json 没有写入方，退役）；
    legacy 剧（V1 冻结）仍读旧 stage_status.json"""
    from tools.autopilot import runs as RUNS
    if not RUNS.is_legacy(run):
        from tools.master import sop_gate as SG
        v = SG.stage_view(run)
        return (v.get("legacy_stage") or "S1"), {"source": "sop_gate", "stage": v.get("stage"), "episodes": v.get("episodes")}
    st = jl((RUNS.run_dir(run) / "stage_status.json").relative_to(ROOT)) or {}
    order = ["S1", "S2", "S3", "S4", "S5"]
    cur = max((k for k in order if (st.get(k) or {}).get("state") in ("doing", "done")), key=order.index, default="S1")
    return cur, st


def p1_stage_score(run: str) -> dict | None:
    """剧本线 S1 阶段分（总调度 20:3x）：还没有分集稿时，用 P1 故事线最新一轮三评委均分折算百分制，注明“P1 阶段分”；有分集稿后切回线 3"""
    from tools.autopilot import runs as RUNS
    base = RUNS.run_dir(run) / "judge_p1"
    if not base.exists():
        return None
    best = None
    for d in [base] + [x for x in base.glob("r*") if x.is_dir()]:
        res = jl((d / "RESULT.json").relative_to(ROOT))
        if res and res.get("mean") is not None and (best is None or (res.get("at") or "") > (best[1].get("at") or "")):
            best = (d, res)
    if not best:
        return None
    d, res = best
    mx = float(res.get("max") or 40)
    items = res.get("item_mean") or {}
    low = min(items, key=items.get) if items else None
    return {"score": round(100 * float(res["mean"]) / mx, 1), "parts": {k: round(v / 5 * 100, 1) for k, v in items.items()}, "lowest": low,
            "stage_score": "P1 阶段分", "src": f"{(d / 'RESULT.json').relative_to(ROOT).as_posix()}（P1 阶段分：三评委均分 {res['mean']}/{int(mx)}，{res.get('at')}）",
            "evidence": {"round": "r1" if d == base else d.name, "totals": res.get("totals"), "sigma": res.get("sigma"), "judge_ids": res.get("judge_ids")}}


def structure_top(n: int = 5) -> dict:
    """代码线 structure 扣分来源：data/sysarch/scan_latest.json per_file 里按 system_score.STRUCT_ANCHOR 的 10 项求和，取前 n 个文件和前 n 个模块（前两级目录）"""
    from tools.rsi import system_score as SS
    scan = jl("data/sysarch/scan_latest.json") or {}
    keys = list(SS.STRUCT_ANCHOR)
    per = {f: sum(int(m.get(k, 0)) for k in keys) for f, m in (scan.get("per_file") or {}).items()}
    per = {f: v for f, v in per.items() if v and not f.startswith("tests/")}
    mods: dict = {}
    for f, v in per.items():
        m = "/".join(f.split("/")[:2])
        mods[m] = mods.get(m, 0) + v
    top_f = sorted(per.items(), key=lambda x: -x[1])[:n]
    top_m = sorted(mods.items(), key=lambda x: -x[1])[:n]
    detail = {f: {k: v for k, v in (scan["per_file"][f]).items() if k in keys and v} for f, _ in top_f}
    return {"scan_at": scan.get("at"), "total": sum(per.values()), "files": top_f, "modules": top_m, "file_detail": detail}


def current_sv() -> str | None:
    """真实线上版本。根因（11-05）：data/system_version.txt 是 deploy 在“被部署的服务器”上写的（= override system），
    笔记本（SENTINEL 跑的地方）从不被 deploy，文件停在 sv-20261102-04。真相源 = git sv-* 标签 / data/system_versions/index.json（入版即写），
    三处取字典序最大（sv-YYYYMMDD-NN 可排序）。"""
    cands = [(jl("data/system_version.txt") or {}).get("id")]
    cands += [v.get("id") for v in ((jl("data/system_versions/index.json") or {}).get("versions") or [])[-3:]]
    tags = _run(["git", "tag", "-l", "sv-*"], 30)
    cands += (tags or "").split()
    ok = [c for c in cands if isinstance(c, str) and c.startswith("sv-")]
    return max(ok) if ok else None


def stale_video(run: str, stage: str) -> dict:
    """本集还没有视频：报最近一次有分的视频线（标 stale），不再给 null；并附运镜执行基准（阶段 0.2b 36 臂，官方写法 Pika 白名单 6 种）"""
    last = None
    try:
        for ln in SCORES.read_text(encoding="utf-8").splitlines()[-4000:]:
            try:
                r = json.loads(ln)
            except ValueError:  # arch-ok: 账本里的坏行跳过（只找最近一条有分的视频记录）
                continue
            if r.get("line") == "video" and r.get("score") is not None and not (r.get("evidence") or {}).get("stale"):
                last = r
    except OSError:  # arch-ok: 没有历史 = 真没测过
        pass
    bench = cam_exec_bench()
    if not last:
        return {"score": None, "pending_stage": f"{run} 在 {stage}，还没有视频，也没有历史视频分", "src": "tools/vidlab/score.py", "evidence": {"cam_exec_bench": bench}}
    return {"score": last["score"], "parts": last.get("parts") or {}, "lowest": last.get("lowest"),
            "src": f"tools/vidlab/score.py（沿用 {last['at']} · {last.get('run') or '旧语料'} 的分，stale；{run} 在 {stage} 还没有视频）",
            "evidence": {"stale": True, "scored_at": last["at"], "scored_sv": last.get("sv"), "cam_exec_bench": bench}}


WHITELIST_MOVES = ("static", "push_in", "pull_out", "bolt_push_settle", "handheld_follow", "pedestal_up")


def cam_exec_bench() -> dict | None:
    """运镜执行基准：data/ab/adherence_video/results.json（运镜执行基准脚本（研究目录，不入发版）measure 同口径 score_move）里
    官方写法 × Pika × i2va 臂、白名单运镜的平均服从分（0–1）"""
    r = jl("data/ab/adherence_video/results.json") or {}
    xs = [v["adherence"]["score"] for k, v in r.items() if not k.startswith("_") and isinstance(v, dict) and v.get("adherence")
          and v.get("style") == "official" and v.get("base") == "pika" and v.get("mode") == "i2va" and v.get("move") in WHITELIST_MOVES]
    return {"mean": round(sum(xs) / len(xs), 2), "n": len(xs)} if xs else None


def existing_scores() -> dict:
    from tools.autopilot import runs as RUNS
    out = {}
    run = score_run()
    stage, _ = stage_of(run)
    order = ["S1", "S2", "S3", "S4", "S5"]
    # 出图：只算本 run 的版本（run 的 renders 目录）；还没到出图段 / 没有版本 = 阶段未到，不出分、不开单
    try:
        from tools.imglab import score as IS
        takes = IS.load_takes("2000-01-01T00:00:00", RUNS.renders_dir(run))
        d = IS.score(takes) if takes else None
    except Exception as e:  # noqa: BLE001  # arch-ok: 记未测
        d, out["_image_err"] = None, repr(e)[:120]
    if d and d.get("score") is not None:
        pic = (d.get("detail") or {}).get("picture") or {}
        parts = {**{k: v for k, v in (d.get("parts_pct") or {}).items()}, **{f"画面·{k}": v for k, v in (pic.get("parts_pct") or {}).items()}}
        out["image"] = {"score": d["score"], "parts": parts, "lowest": (min((pic.get("parts_pct") or {"-": 0}), key=(pic.get("parts_pct") or {"-": 0}).get) if pic else d.get("lowest")),
                        "src": f"tools/imglab/score.py v2（{run}；契约分 {d.get('contract_score')} × 0.35 + 画面指数 {pic.get('picture_index')} × 0.65）",
                        "unmeasured": pic.get("unmeasured"),
                        "evidence": {"contract_score": d.get("contract_score"), "picture_index": pic.get("picture_index"), "picture_n": pic.get("n"),
                                     "capped_by": pic.get("capped_by"), "per_shot": pic.get("per_shot")}}
    else:
        out["image"] = {"score": None, "pending_stage": f"{run} 在 {stage}，还没有出图版本", "src": "tools/imglab/score.py"}
    vdir = RUNS.run_dir(run) / "video"
    if order.index(stage) >= order.index("S4") and vdir.exists() and any(vdir.iterdir()):
        d = _first_json(_run(["tools/vidlab/score.py", "score", "--no-write", "--corpus", str(vdir)], 900))
        out["video"] = d and {"score": d["score"], "parts": d.get("items") or {}, "lowest": d.get("lowest"), "src": f"tools/vidlab/score.py score（{run}）"}
    else:
        out["video"] = stale_video(run, stage)
    d = _first_json(_run(["tools/script_rsi/line3_score.py", "--run-dir", str(RUNS.run_dir(run).relative_to(ROOT)), "--no-write"], 600))
    out["script"] = d and {"score": d["score"], "parts": d.get("parts") or {}, "lowest": d.get("lowest"), "src": f"tools/script_rsi/line3_score.py（{run}）"}
    if out["script"] and not any((v or 0) > 0 for v in (out["script"]["parts"] or {}).values()):
        # 线 3 按分集剧本打分；主 run 还在写故事线（没有分集稿）时各分项全 0 = 阶段未到，不是 0 分
        out["script"] = p1_stage_score(run) or {"score": None, "pending_stage": f"{run} 在 {stage}，还没有分集剧本，也没有 P1 评审结果", "src": out["script"]["src"]}
    try:
        from tools.rsi import system_score as SS
        d = SS.score(write=False)
        out["system"] = {"score": d.get("score"), "parts": d.get("parts") or d.get("items") or {}, "lowest": d.get("lowest"), "src": "tools/rsi/system_score.py",
                         "evidence": {"structure_top": structure_top()}}
    except Exception as e:  # noqa: BLE001  # arch-ok: 记未测
        out["system"] = None
        out["_system_err"] = repr(e)[:120]
    for k in ("image", "video", "script", "system"):
        if out.get(k) and out[k].get("score") is not None and isinstance(out[k].get("parts"), dict):
            out[k]["parts"] = {pk: (pv.get("score") if isinstance(pv, dict) else pv) for pk, pv in out[k]["parts"].items()}
        if out.get(k) and not out[k].get("lowest") and out[k].get("parts"):
            num = {pk: pv for pk, pv in out[k]["parts"].items() if isinstance(pv, (int, float))}
            out[k]["lowest"] = min(num, key=num.get) if num else None
    return out


# ------------------------------------------------------------------ 新三项
def _combine(parts: dict, weights: dict, unmeasured: list[str], cap: float) -> dict:
    """parts = {分项: 0–1 或 None}；None = 未测按 0 计入（不能当满分）；有 unmeasured（SCORECARD 标准里还没法测的条目）时封顶 cap"""
    tot = sum(weights.values())
    s = sum(weights[k] * (parts.get(k) or 0.0) for k in weights) / tot * 100
    if unmeasured:
        s = min(s, cap)
    low = min(weights, key=lambda k: (parts.get(k) if parts.get(k) is not None else -1))
    if unmeasured and all((parts.get(k) or 0) >= 1 for k in weights):
        low = "未测条目"                               # 实测分项都满分，差的是还测不了的标准（封顶 95 的原因）
    return {"score": round(s, 1), "parts": {k: (None if parts.get(k) is None else round(parts[k] * 100, 1)) for k in weights},
            "weights": weights, "lowest": low, "unmeasured": unmeasured, "capped": bool(unmeasured) and s >= cap}


def ui_score(c: dict) -> dict:
    m = jl("data/rsi/ui_measure.json") or {}
    age = time.time() - float(m.get("t") or 0)
    fresh = age <= c["ui_measure_max_age_s"]
    ev = {"ui_measure_at": m.get("at"), "fresh": fresh}
    parts = {"topbar": None, "no_blank": None, "clean": None, "no_jargon": None, "feedback": None}
    if fresh:
        tb = m.get("topbar") or {}
        if tb.get("total"):
            parts["topbar"] = tb["ok"] / tb["total"]
        pages = m.get("pages") or {}
        if pages:
            n = len(pages)
            parts["no_blank"] = sum(1 for p in pages.values() if not p.get("blank")) / n
            parts["clean"] = sum(1 for p in pages.values() if not p.get("color_capsules") and not p.get("contradictions") and not p.get("broken_imgs")) / n
            parts["no_jargon"] = sum(1 for p in pages.values() if not p.get("jargon")) / n
        ev.update(topbar_bad=tb.get("bad"), pages={k: {kk: v.get(kk) for kk in ("blank", "jargon", "n_color", "contradictions")} for k, v in pages.items()})
    fb = feedback_open("ui")
    parts["feedback"] = max(0.0, 1 - len(fb) / c["ui_feedback_zero_at"])
    ev["ui_feedback_open"] = fb
    r = _combine(parts, c["ui_weights"], c["ui_unmeasured"], c["cap_when_unmeasured"])
    r.update(src="tools/sentinel/scorecard.py ui_score", evidence=ev)
    return r


def feedback_open(prefix: str) -> list[str]:
    out = []
    for p in sorted((ROOT / "data/feedback/items").glob("fb-*.json")):
        d = jl(p.relative_to(ROOT)) or {}
        if str(d.get("category") or "").startswith(prefix) and d.get("status") not in ("closed", "done", "verified", "deferred"):
            out.append(f"{d.get('id')}:{d.get('status')}")
    return out


def _open_keys(prefix: str) -> list[str]:
    st = jl("data/sentinel/state.json", {}) or {}
    return [k for k in (st.get("open") or {}) if k.startswith(prefix)]


def workflow_score(c: dict) -> dict:
    """按主 run（V2）算：unattended = 写作推进常驻服务心跳正常且无人等人决定（S26 无单、S13 主 run 无单）；review_chain = P1 评审交齐后自动汇总（S27 无单）；
    no_dup = S17 无限重出；auto_requeue = 反馈单 30 分钟内被自动分诊"""
    run = score_run()
    s26, s27, dup = _open_keys("S26:"), _open_keys("S27:"), _open_keys("S17:")
    waits = [k for k in _open_keys("S13:wait:")]
    fb_new_stale = []
    for p in sorted((ROOT / "data/feedback/items").glob("fb-*.json")):
        d = jl(p.relative_to(ROOT)) or {}
        if d.get("status") == "new" and time.time() - (J.ts(d.get("created_at")) or time.time()) > 1800:
            fb_new_stale.append(d.get("id"))
    n_fb = len(list((ROOT / "data/feedback/items").glob("fb-*.json"))) or 1
    waits = []                                       # S13 现在只看 V1 producer 登记表（已归档），主 run 写作段没有等人对象；V2 进出图段后改按 run 拆
    s28 = _open_keys("S28:")
    parts = {"q10_detector": 0.0 if s28 else 1.0,
             "unattended": 0.0 if s26 else 1.0,
             "review_chain": 0.0 if s27 else 1.0,
             "no_dup": max(0.0, 1 - len(dup) / c["dup_zero_at"]),
             "auto_requeue": 1 - len(fb_new_stale) / n_fb}
    r = _combine(parts, c["workflow_weights"], c["workflow_unmeasured"], c["cap_when_unmeasured"])
    r.update(src=f"tools/sentinel/scorecard.py workflow_score（{run}）",
             evidence={"run": run, "s26_open": s26, "s27_open": s27, "s28_open": s28, "s13_wait_open": waits, "dup_render_tickets": dup, "feedback_new_over_30min": fb_new_stale})
    return r


def gpu_score(c: dict) -> dict:
    g = jl("data/rsi/gpu_24h.json") or {}
    known = (g.get("totals") or {}).get("pct", {})
    pk = (g.get("totals") or {}).get("productive_pct_of_known")
    st = jl("data/sentinel/state.json", {}) or {}
    rc = (st.get("mem") or {}).get("remote_calls") or {}
    ok, n = sum(v.get("ok", 0) for v in rc.values()), sum(v.get("n", 0) for v in rc.values())
    segs = [s for s in g.get("pause_segments") or [] if any(w in (s.get("by") or "") for w in c["deploy_pause_by"])]
    worst = max((s["hours"] * 3600 for s in segs), default=0.0)
    run = score_run()
    stage, _ = stage_of(run)
    expect = float((c.get("gpu_expected_by_stage") or {}).get(stage, 0.8))
    # 按“当前阶段应该有的占用”算（总调度 20:10）：写剧本段预期 0 → 不扣分；出图 / 视频段按目标占用比
    prod = 1.0 if expect <= 0 else (None if pk is None else min(1.0, (pk / 100) / expect))
    parts = {"productive": prod,
             "rssh": None if n < 10 else min(1.0, (ok / n) / c["rssh_target"]),
             "deploy_stop": 1.0 if worst <= c["deploy_stop_max_s"] else max(0.0, c["deploy_stop_max_s"] / worst),
             "resident": 0.0 if _open_keys("S25:") else 1.0,
             "lend_expiry": 0.0 if _open_keys("S18:") else 1.0,
             "q10_detector": 0.0 if _open_keys("S28:") else 1.0}
    r = _combine(parts, c["gpu_weights"], c["gpu_unmeasured"], c["cap_when_unmeasured"])
    r.update(src="tools/sentinel/scorecard.py gpu_score",
             evidence={"run": run, "stage": stage, "expected_occupancy": expect, "gpu24_pct": known, "productive_pct_of_known": pk, "rssh_ok_n": [ok, n], "deploy_pause_worst_s": round(worst),
                       "deploy_pause_segments": segs[:5], "s25_open": _open_keys("S25:"), "s18_open": _open_keys("S18:")})
    return r


# ------------------------------------------------------------------ 界面实测（后台子进程）
# 顶栏口径 v2（总调度 11-02 18:0x 批：NAVIA 按项目方要求把换集下拉移到页内范围条，顶栏不再放集号）：
#   顶栏 7 个一级入口（总览 / 剧本 / 资产 / 分镜 / 出图 / 视频 / 成片）都在、可点、互不重叠、页面无横向滚动；
#   出图 / 视频 / 成片 / 分镜四页的范围条（.v3-scope）里有换集下拉（“第 N 集 ▾”）
TOPBAR_JS = r'''
const vis = (e) => { if (!e) return false; const r = e.getBoundingClientRect(); const c = getComputedStyle(e); return r.width > 0 && r.height > 0 && c.visibility !== "hidden" && c.display !== "none"; };
const want = __LABELS__;
const steps = [...document.querySelectorAll(".v3-top .v3-step")].filter(vis);
const txt = (b) => (b.innerText || "").replace(/\s+/g, "");
const missing = want.filter((w) => !steps.some((b) => txt(b).includes(w) && !b.disabled));
const R = steps.map((e) => e.getBoundingClientRect());
let overlap = false;
for (let i = 0; i < R.length; i++) { if (R[i].left < -0.5 || R[i].right > innerWidth + 0.5) overlap = true; for (let j = i + 1; j < R.length; j++) { const a = R[i], b = R[j]; if (a.left < b.right - 1 && b.left < a.right - 1 && a.top < b.bottom - 1 && b.top < a.bottom - 1) overlap = true; } }
const hscroll = document.documentElement.scrollWidth > innerWidth + 1;
const scope = document.querySelector(".v3-scope");
const picker = !!scope && [...scope.querySelectorAll("button, span")].some((b) => vis(b) && /第\s*\d+\s*集/.test(b.textContent || ""));
return {missing, overlap, hscroll, picker};
'''


JARGON_JS = r'''
const T = (document.getElementById("root")?.innerText || "");
const W = __WORDS__;
const hit = W.filter((w) => new RegExp("(^|[^A-Za-z])" + w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "([^A-Za-z]|$)").test(T));
const blank = !document.getElementById("root") || T.replace(/\s+/g, "").length < 60 || !!document.querySelector("vite-error-overlay");
return {blank, jargon: hit};
'''


def ui_measure() -> dict:
    """顶栏：apps/web/e2e/uirsi/topbar_check.mjs（7 页 × 3 宽度）；每页 DOM：空白页 / 技术词（policy 词表）+ S9 同一套整洁规则（ui_rules.js）"""
    c = cfg()
    res = {"t": time.time(), "at": J.iso(time.time())}
    tex = "JSON.stringify((()=>{" + TOPBAR_JS.replace("__LABELS__", json.dumps(c["ui_topbar_labels"], ensure_ascii=False)) + "})())"
    ok, total, badl = 0, 0, []
    for page in c["ui_pages"]:
        for size in c["ui_topbar_sizes"]:
            total += 1
            try:
                out = subprocess.run(["node", str(ROOT / "apps/web/e2e/uirsi/probe.mjs"), page, tex, "12000", size], cwd=str(ROOT),
                                     capture_output=True, timeout=180, creationflags=NOWIN).stdout.decode("utf-8", "replace").strip().splitlines()
                d = json.loads(json.loads(out[-1]))
                why = (["缺入口 " + "、".join(d["missing"])] if d.get("missing") else []) + (["重叠"] if d.get("overlap") else []) + (["横向滚动"] if d.get("hscroll") else [])
            except (OSError, subprocess.TimeoutExpired, ValueError, IndexError, KeyError) as e:  # arch-ok: 探针失败记“不过”（不当正常）
                why = [f"探针失败 {type(e).__name__}"]
            ok += 0 if why else 1
            if why:
                badl.append(f"{page} {size}：{'、'.join(why)}")
    for page in c["ui_picker_pages"]:
        total += 1
        try:
            out = subprocess.run(["node", str(ROOT / "apps/web/e2e/uirsi/probe.mjs"), page, tex, "12000", "1440x900"], cwd=str(ROOT),
                                 capture_output=True, timeout=180, creationflags=NOWIN).stdout.decode("utf-8", "replace").strip().splitlines()
            d = json.loads(json.loads(out[-1]))
            good = bool(d.get("picker"))
        except (OSError, subprocess.TimeoutExpired, ValueError, IndexError) as e:  # arch-ok: 探针失败记“不过”
            good, d = False, {"error": type(e).__name__}
        ok += 1 if good else 0
        if not good:
            badl.append(f"{page} 范围条里没有换集下拉{'（' + d['error'] + '）' if d.get('error') else ''}")
    res["topbar"] = {"ok": ok, "total": total, "bad": badl[:20], "rule": "v2（总调度 18:0x 批）"}
    rules = (ROOT / "tools/sentinel/ui_rules.js").read_text(encoding="utf-8")
    rules = "\n".join(ln for ln in rules.splitlines() if not ln.startswith("//"))
    from tools.autopilot import policy
    s9 = policy.load()["sentinel"]["S9_ui_rules"]["value"]
    rules = rules.replace("__SAT__", str(s9["color_sat_min"])).replace("__DOT__", str(s9["dot_max_px"]))
    jg = JARGON_JS.replace("__WORDS__", json.dumps(c["ui_jargon_words"], ensure_ascii=False))
    expr = ("JSON.stringify((()=>{const A=(()=>{" + rules + "})();const B=(()=>{" + jg + "})();return Object.assign({},A,B);})())")
    pages = {}
    for page in c["ui_pages"]:
        try:
            out = subprocess.run(["node", str(ROOT / "apps/web/e2e/uirsi/probe.mjs"), page, expr, "12000", "1440x900"], cwd=str(ROOT),
                                 capture_output=True, timeout=180, creationflags=NOWIN).stdout.decode("utf-8", "replace").strip().splitlines()
            pages[page] = json.loads(json.loads(out[-1]))
        except (OSError, subprocess.TimeoutExpired, ValueError, IndexError) as e:  # arch-ok: 该页记“探针失败”（算不干净、算空白，不当正常）
            pages[page] = {"blank": True, "jargon": [], "error": repr(e)[:80], "color_capsules": [], "contradictions": ["探针失败"]}
    res["pages"] = pages
    UI_OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = UI_OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, UI_OUT)
    return res


def ensure_ui_measure(c: dict) -> None:
    """界面实测慢（顶栏 21 次无头打开 + 7 页），放后台子进程；上一份太旧、且没有在跑的就起一个"""
    lock = ROOT / "data/rsi/ui_measure.lock"
    m = jl("data/rsi/ui_measure.json") or {}
    if time.time() - float(m.get("t") or 0) < c["ui_measure_every_s"]:
        return
    if lock.exists() and time.time() - lock.stat().st_mtime < 1800:
        return
    lock.write_text(str(time.time()), encoding="utf-8")
    subprocess.Popen([PY, str(ROOT / "tools/sentinel/scorecard.py"), "ui-measure"], cwd=str(ROOT), creationflags=NOWIN,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ------------------------------------------------------------------ 汇总 + 写分
def compute(write: bool = True) -> dict:
    c = cfg()
    ex = existing_scores()
    res = {k: ex.get(k) for k in ("image", "video", "script", "system")}
    res["ui"] = ui_score(c)
    res["workflow"] = workflow_score(c)
    res["gpu"] = gpu_score(c)
    sv = current_sv()
    now = time.time()
    if write:
        with SCORES.open("a", encoding="utf-8") as f:
            for line, r in res.items():
                if r and (r.get("score") is not None or r.get("pending_stage")):
                    f.write(json.dumps({"at": J.iso(now), "line": line, "score": r.get("score"), "run": score_run(), "pending_stage": r.get("pending_stage"),
                                        "parts": r.get("parts") or {}, "sv": sv,
                                        "by": "SENTINEL scorecard", "src": r.get("src"), "lowest": r.get("lowest"),
                                        "unmeasured": r.get("unmeasured"), "evidence": r.get("evidence")}, ensure_ascii=False) + chr(10))
    return res


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    cmd = (argv or sys.argv[1:] or ["once"])[0]
    if cmd == "ui-measure":
        try:
            r = ui_measure()
        finally:
            (ROOT / "data/rsi/ui_measure.lock").unlink(missing_ok=True)
        print(json.dumps({"topbar": r.get("topbar"), "pages": {k: {kk: v.get(kk) for kk in ("blank", "jargon")} for k, v in (r.get("pages") or {}).items()}},
                         ensure_ascii=False, indent=1))
        return 0
    r = compute(write=cmd == "once")
    for k, v in r.items():
        print(k, None if not v else v.get("score"), (v or {}).get("lowest"), (v or {}).get("src"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
