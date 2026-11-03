"""RSI 线 3：提纲 → 镜头剧本 → 分镜 的打分器（HOLLYWOOD 牵头，总调度 L-112；总纲 docs/master/RSI_PROGRAM.md §线 3）。

纯代码、0 花费：复用 rubric_code（27 条代码判定 + v2 镜头块 / 灯光）、validate_qwen_script、imglab/orphan_check 的判定函数、
autoflow 状态。每轮把一行写进 data/rsi/scores.jsonl（line=script），分数 0–100：

  剧本分（35）   新尺子：测试期只用代码判定（L-109：判断条目缓），= 35 × 代码判定满足数 / 27；判断条目恢复后改为 35 × 新尺子 / 50
  镜头块（20）   = 20 × 镜头块合格镜数 / 总镜数；合格 = v2 必填五段齐、顺序对 + 【灯光】合规 + **镜头** 写了就必须在 lenses.yaml 里
  可拍性（20）   = 20 × 可拍镜数 / 总镜数；可拍 = 编译后 0 孤儿描述（K-REN-901）+ 0 特写双人露脸冲突（K-REN-902）；整集 validate 有阻断 → 本项 0
  结构（15）     = 15 × 结构项通过数 / 6：镜1 钩子（hook5s#1 / #4）、结尾钩子（endhook#3 / #5）、镜数 10–20（turns#1）、时长 60–120 秒
  自动化（10）   = 10 × 无人干预到“可导入”的集数 / 目标集数（第二季 10）
整季分 = 各集分平均（自动化项按整季算一次）。

    .venv/Scripts/python.exe tools/script_rsi/line3_score.py --run-dir data/pipeline/runs/series10_s2 [--episodes 1-10] [--no-write]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "tools" / "pipeline", ROOT / "tools" / "autopilot", ROOT / "tools" / "imglab", ROOT / "packages" / "schema",
           ROOT / "services" / "agent", ROOT / "services" / "api", ROOT / "services" / "recipes", ROOT / "services" / "render_router",
           ROOT / "tools" / "prompt_v2"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


AF = _load("autoflow", "tools/script_rsi/autoflow.py")
H, RL, RC6 = AF.H, AF.RL, AF.R5.RC6
SCORES = ROOT / "data" / "rsi" / "scores.jsonl"
WEIGHTS = {"script": 35, "shot_block": 20, "shootable": 20, "structure": 15, "automation": 10}
TARGET_EPISODES = 10


def lens_names() -> set[str]:
    import yaml
    p = ROOT / "config" / "director" / "lenses.yaml"
    if not p.exists():
        return set()
    d = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return {str(x.get(k, "")).strip() for x in d.get("lenses") or [] for k in ("id", "zh") if x.get(k)}


def best_chunk(run_dir: Path, ep: int) -> tuple[str, str] | None:
    """这一集现在最好的稿：final > P4；→ (前言, 一集正文)"""
    from ns_api import script_chat as SC
    for name in (f"P4_ep{ep:02d}.final.md", f"P4_ep{ep:02d}.md"):
        p = run_dir / name
        if p.exists():
            t = p.read_text(encoding="utf-8")
            if name.endswith(".final.md"):
                pre, ch = RL.split_doc(t)
                return pre, ch[0]
            body = t[t.find("## ep"):] if "## ep" in t else t
            header, _ = SC.script_header(registry={}, run=SC.run_for_dir(run_dir))
            return header + "\n---\n\n", body.rstrip() + "\n\n---\n"
    return None


def shootable(ep_obj, shots, chunk_pre: str, chunk: str) -> list[bool]:
    """逐镜：编译后 0 孤儿 + 0 特写双人露脸——单一来源 tools/script_rsi/shootable.py（导入闸门同一判法，K-WRT-H13）"""
    SH = _load("shootable", "tools/script_rsi/shootable.py")
    rows = {r["shot"]: r["ok"] for r in SH.shootable_rows(chunk_pre + chunk)}
    return [rows.get(s.index, False) for s in shots]


def score_episode(run_dir: Path, ep: int, lenses: set[str]) -> dict | None:
    got = best_chunk(run_dir, ep)
    if got is None:
        return None
    pre, chunk = got
    wd = run_dir / f"work_ep{ep:02d}"
    wd.mkdir(exist_ok=True)
    obj = H.episode_obj(pre, chunk, ep, wd)
    shots = sorted(obj.shots, key=lambda s: s.index)
    blocks = [RL.block_text(chunk, k) for k in range(len(shots))]
    cc = RC6.code_checks(chunk, shots, blocks, RL.block_text(chunk, "head"), H.lint(chunk, ep)["codes"])
    met = sum(ok for d in RC6.DIMS for ok, _ in cc[d].values())
    # 镜头块：逐镜判（v2_checks 按镜拆开调用）
    sb_ok = []
    for s, b in zip(shots, blocks):
        v = RC6.v2_checks([s], [b], pre + RL.block_text(chunk, "head"))
        lens_line = next((ln.split("：", 1)[1].strip() for ln in b.split("\n") if ln.startswith("**镜头**：")), "")
        lens_ok = (not lens_line) or (not lenses) or any(x in lens_line for x in lenses)
        sb_ok.append(v[1][0] and v[2][0] and lens_ok)
    # 可拍性
    v = AF.FR.validate_json(Path(_tmp_write(run_dir, ep, pre + chunk)))
    sh_ok = shootable(obj, shots, pre, chunk) if not v.get("blocking") else [False] * len(shots)
    total = sum(int(s.duration or 0) for s in shots)
    struct = [cc["hook5s"][1][0], cc["hook5s"][4][0], cc["endhook"][3][0], cc["endhook"][5][0], cc["turns"][1][0], 60 <= total <= 120]
    n = max(1, len(shots))
    parts = {"script": round(WEIGHTS["script"] * met / 27, 2),
             "shot_block": round(WEIGHTS["shot_block"] * sum(sb_ok) / n, 2),
             "shootable": round(WEIGHTS["shootable"] * sum(sh_ok) / n, 2),
             "structure": round(WEIGHTS["structure"] * sum(struct) / len(struct), 2)}
    NC = _load("narrative_code", "tools/script_rsi/narrative_code.py")       # 叙事质量 N01–N07：剧本分 = 代码判定 70% + 叙事 30%（N05 整季判，在 main 里合）
    nar = NC.episode_checks(shots, blocks)
    return {"episode": ep, "parts": parts, "code_met": met, "base_sha": __import__("hashlib").sha256(chunk.encode("utf-8")).hexdigest()[:16], "shots": len(shots), "seconds": total,
            "narrative": {k: {"ok": v["ok"], "value": v["value"], "detail": v["detail"][:160]} for k, v in nar.items()},
            "shot_block_bad": [s.index for s, ok in zip(shots, sb_ok) if not ok],
            "unshootable": [s.index for s, ok in zip(shots, sh_ok) if not ok], "validate_blocking": v.get("blocking"),
            "structure_fail": [k for k, ok in zip(["hook5s#1", "hook5s#4", "endhook#3", "endhook#5", "turns#1", "时长60–120"], struct) if not ok]}


NARR_KEYS = ["N01", "N02", "N03", "N04", "N05", "N06", "N07"]
SCRIPT_MIX = {"code": 0.7, "narrative": 0.3}     # 总调度 11-02：叙事 7 条计入总分（代码判定 70%、叙事 30%）


def apply_narrative(eps: list[dict], n05_repeats: list[int], judge: dict | None = None) -> None:
    """把叙事 7 条合进每集剧本分：N05 按整季判（本集落在相邻 3 集重复里 = 不过），其余按本集"""
    for e in eps:
        ok = {k: bool(e["narrative"][k]["ok"]) for k in NARR_KEYS if k != "N05"}
        ok["N05"] = e["episode"] not in n05_repeats
        e["narrative_pass"] = sum(ok.values())
        e["narrative_fail"] = [k for k in NARR_KEYS if not ok[k]]
        j = (judge or {}).get((e["episode"], e.get("base_sha")))
        if j is not None:      # 总调度 11-02：有正式判断分（3 个独立评审、同一稿 sha）→ 代码 27 条换成新尺子 50 分制（已含代码条目）
            e["judge50"] = j
            base = j / 50
        else:
            base = e["code_met"] / 27
        e["parts"]["script"] = round(WEIGHTS["script"] * (SCRIPT_MIX["code"] * base
                                                          + SCRIPT_MIX["narrative"] * e["narrative_pass"] / len(NARR_KEYS)), 2)


def official_judge(run: str) -> dict:
    """scores.jsonl 里 line=script_judge、official=true 的记录 → {(集, 稿 sha): 50 分制均值}（同一集同一 sha 取最新一条）"""
    out = {}
    if not SCORES.exists():
        return out
    for n, ln in enumerate(SCORES.read_text(encoding="utf-8").splitlines(), 1):
        if not ln.strip():
            continue
        try:
            d = json.loads(ln)
        except ValueError as ex:          # 坏行不吞：报出来，判断分照常从其余行取
            print(f"[line3_score] scores.jsonl 第 {n} 行不是 JSON（{ex}），跳过", file=sys.stderr)
            continue
        if d.get("line") == "script_judge" and d.get("official") and d.get("run") == run and d.get("base_sha"):
            out[(int(d["episode"]), d["base_sha"])] = float(d["score50"])
    return out


def _tmp_write(run_dir: Path, ep: int, text: str) -> str:
    p = run_dir / f"work_ep{ep:02d}" / "line3_score.md"
    p.write_text(text, encoding="utf-8")
    return str(p)


def automation(run_dir: Path) -> tuple[float, list[int]]:
    """无人干预到“可导入”：autoflow_epNN.json verdict=importable 且没有人工标记（agent_history 里没有 manual）"""
    ok = []
    for f in sorted(run_dir.glob("autoflow_ep*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        if d.get("verdict") in ("importable", "imported") and not any("manual" in json.dumps(h, ensure_ascii=False) for h in d.get("agent_history") or []):
            ok.append(int(d.get("episode")))
    return round(WEIGHTS["automation"] * len(ok) / TARGET_EPISODES, 2), ok


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--episodes", default="1-10")
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--ref", default="", help="好莱坞参照锚点：给这批参照稿打分，记录带 ref 字段（不计自动化，不参与线 3 轨迹）")
    a = ap.parse_args(argv)
    run_dir = Path(a.run_dir) if Path(a.run_dir).is_absolute() else ROOT / a.run_dir
    lenses = lens_names()
    eps = [score_episode(run_dir, e, lenses) for e in sorted(H.RL.parse_episodes(a.episodes))]
    eps = [e for e in eps if e]
    auto, auto_eps = automation(run_dir)
    keys = ["script", "shot_block", "shootable", "structure"]
    try:
        import subprocess
        sv = subprocess.run(["git", "describe", "--tags", "--abbrev=0"], cwd=ROOT, capture_output=True, text=True, timeout=20).stdout.strip()
    except Exception as e:  # noqa: BLE001  版本号拿不到不影响打分，记下原因
        sv = f"unknown（{e!r}）"[:80]
    NC = _load("narrative_code", "tools/script_rsi/narrative_code.py")
    n05 = NC.season_endings({e["episode"]: e["narrative"]["N05"]["value"] for e in eps})
    apply_narrative(eps, n05["repeats_at"], official_judge(run_dir.name))
    avg = {k: round(sum(e["parts"][k] for e in eps) / len(eps), 2) if eps else 0.0 for k in keys}
    avg["automation"] = auto
    score = round(sum(avg.values()), 2)
    low = min(((k, avg[k] / WEIGHTS[k]) for k in WEIGHTS), key=lambda t: t[1])[0]
    nar_keys = ["N01", "N02", "N03", "N04", "N06", "N07"]
    narrative = {k: f"{sum(1 for e in eps if e['narrative'][k]['ok'])}/{len(eps)}" for k in nar_keys}
    narrative["N05"] = "ok" if n05["ok"] else f"相邻 3 集结尾类型重复：第 {n05['repeats_at']} 集"
    rec_narr = {"summary": narrative, "endings": n05["types"]}
    rec = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "line": "script", "score": score, "parts": avg, "weights": WEIGHTS,
           "narrative": rec_narr,
           "version": sv, "run": run_dir.name, "episodes": eps, "automation_eps": auto_eps, "lowest": low,
           "note": ("剧本分 = 35 ×（0.7 × 代码判定 27 条通过率 + 0.3 × 叙事 7 条通过率）（总调度 11-02 定）；"
                    "100 = 全部代码可判条目通过，不代表判断条目（人物弧、情感、台词好坏）已评，判断条目测试期缓（L-109）")}
    if a.ref:      # 参照锚点：同一套指标给参照打分，作为满分锚点（RSI_PROGRAM 共同规则）
        rec["ref"] = a.ref
        rec["score_no_automation"] = round(score - avg["automation"], 2)
    if not a.no_write:
        SCORES.parent.mkdir(parents=True, exist_ok=True)
        with open(SCORES, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(json.dumps({k: rec[k] for k in ("score", "parts", "lowest", "automation_eps", "narrative")}, ensure_ascii=False))
    for e in eps:
        print(f"  ep{e['episode']:02d} {e['parts']}  镜头块不合格 {e['shot_block_bad']}  不可拍 {e['unshootable']}  结构 {e['structure_fail']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
