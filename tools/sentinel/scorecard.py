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
def existing_scores() -> dict:
    out = {}
    d = _first_json(_run(["tools/imglab/score.py", "--no-write", "--json"], 300))
    out["image"] = d and {"score": d["score"], "parts": d.get("items") or d.get("parts") or {}, "lowest": d.get("lowest"), "src": "tools/imglab/score.py"}
    d = _first_json(_run(["tools/vidlab/score.py", "score", "--no-write"], 900))
    out["video"] = d and {"score": d["score"], "parts": d.get("items") or {}, "lowest": d.get("lowest"), "src": "tools/vidlab/score.py score"}
    d = _first_json(_run(["tools/script_rsi/line3_score.py", "--run-dir", "data/pipeline/runs/series10_s2", "--no-write"], 600))
    out["script"] = d and {"score": d["score"], "parts": d.get("parts") or {}, "lowest": d.get("lowest"), "src": "tools/script_rsi/line3_score.py"}
    try:
        from tools.rsi import system_score as SS
        d = SS.score(write=False)
        out["system"] = {"score": d.get("score"), "parts": d.get("parts") or d.get("items") or {}, "lowest": d.get("lowest"), "src": "tools/rsi/system_score.py"}
    except Exception as e:  # noqa: BLE001  # arch-ok: 记未测
        out["system"] = None
        out["_system_err"] = repr(e)[:120]
    for k in ("image", "video", "script", "system"):
        if out.get(k) and isinstance(out[k].get("parts"), dict):
            out[k]["parts"] = {pk: (pv.get("score") if isinstance(pv, dict) else pv) for pk, pv in out[k]["parts"].items()}
    return out


# ------------------------------------------------------------------ 新三项
def _combine(parts: dict, weights: dict, unmeasured: list[str], cap: float) -> dict:
    """parts = {分项: 0–1 或 None}；None = 未测按 0 计入（不能当满分）；有 unmeasured（SCORECARD 标准里还没法测的条目）时封顶 cap"""
    tot = sum(weights.values())
    s = sum(weights[k] * (parts.get(k) or 0.0) for k in weights) / tot * 100
    if unmeasured:
        s = min(s, cap)
    low = min(weights, key=lambda k: (parts.get(k) if parts.get(k) is not None else -1))
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
    st = jl("data/sentinel/state.json", {}) or {}
    waits = sum(len(v) for v in ((st.get("mem") or {}).get("waits") or {}).values())
    reg = jl("data/producer/registry.json", {}) or {}
    pending = sum(1 for E in reg.get("episodes") or [] for S in E.get("shots") or [] for o in (S.get("objects") or {}).values()
                  if o.get("status") in ("pending", "ready", "running"))
    stuck = _open_keys("S11:")
    eps = len((jl("data/autopilot/flow/status.json", {}) or {}).get("episodes") or []) or 10
    dup = _open_keys("S17:")
    # 项目方修改自动入队：反馈单建好后 30 分钟内离开 new（被自动分诊）
    fb_new_stale = []
    for p in sorted((ROOT / "data/feedback/items").glob("fb-*.json")):
        d = jl(p.relative_to(ROOT)) or {}
        if d.get("status") == "new" and time.time() - (J.ts(d.get("created_at")) or time.time()) > 1800:
            fb_new_stale.append(d.get("id"))
    n_fb = len(list((ROOT / "data/feedback/items").glob("fb-*.json"))) or 1
    parts = {"unattended": max(0.0, 1 - waits / max(1, pending)) if pending else (0.0 if waits else 1.0),
             "no_stuck": max(0.0, 1 - len(stuck) / eps),
             "no_dup": max(0.0, 1 - len(dup) / c["dup_zero_at"]),
             "auto_requeue": 1 - len(fb_new_stale) / n_fb}
    r = _combine(parts, c["workflow_weights"], c["workflow_unmeasured"], c["cap_when_unmeasured"])
    r.update(src="tools/sentinel/scorecard.py workflow_score",
             evidence={"waiting_human": waits, "pending_objs": pending, "stuck": stuck, "dup_render_tickets": dup, "feedback_new_over_30min": fb_new_stale})
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
    parts = {"productive": None if pk is None else min(1.0, pk / c["gpu_productive_target_pct"]),
             "rssh": None if n < 10 else min(1.0, (ok / n) / c["rssh_target"]),
             "deploy_stop": 1.0 if worst <= c["deploy_stop_max_s"] else max(0.0, c["deploy_stop_max_s"] / worst),
             "resident": 0.0 if _open_keys("S25:") else 1.0,
             "lend_expiry": 0.0 if _open_keys("S18:") else 1.0}
    r = _combine(parts, c["gpu_weights"], c["gpu_unmeasured"], c["cap_when_unmeasured"])
    r.update(src="tools/sentinel/scorecard.py gpu_score",
             evidence={"gpu24_pct": known, "productive_pct_of_known": pk, "rssh_ok_n": [ok, n], "deploy_pause_worst_s": round(worst),
                       "deploy_pause_segments": segs[:5], "s25_open": _open_keys("S25:"), "s18_open": _open_keys("S18:")})
    return r


# ------------------------------------------------------------------ 界面实测（后台子进程）
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
    try:
        r = subprocess.run(["node", str(ROOT / "apps/web/e2e/uirsi/topbar_check.mjs")], cwd=str(ROOT), capture_output=True, timeout=1500,
                           creationflags=NOWIN)
        lines = r.stdout.decode("utf-8", "replace").splitlines()
        ok = sum(1 for ln in lines if ln.startswith("✓"))
        badl = [ln for ln in lines if ln.startswith("✗")]
        res["topbar"] = {"ok": ok, "total": ok + len(badl), "bad": badl[:10]}
    except (OSError, subprocess.TimeoutExpired) as e:  # arch-ok: 记 topbar 未测
        res["topbar"] = {"error": repr(e)[:100]}
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
    sv = (jl("data/system_version.txt") or {}).get("id")
    now = time.time()
    if write:
        with SCORES.open("a", encoding="utf-8") as f:
            for line, r in res.items():
                if r and r.get("score") is not None:
                    f.write(json.dumps({"at": J.iso(now), "line": line, "score": r["score"], "parts": r.get("parts") or {}, "sv": sv,
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
