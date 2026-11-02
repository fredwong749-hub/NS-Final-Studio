"""判断类条目的独立评审（总调度 11-02：测试期用另一个独立的 Claude agent 当评审，和写手、和 HOLLYWOOD 都分开；
按 config/prompts/hollywood_judge.md 打分，同一稿评 3 次看 σ ≤ 1）。

  pack     出评审任务包：<run>/judge_tasks/judge_epNN_rK.json（K = 1..reps，同一稿同一请求各一份，评审 agent 每份独立作答，不看别的份）
  collect  收评审产物 <run>/judge_out/judge_epNN_rK.json（+ .done）→ 逐份按 r6 口径算 50 分制总分（代码条目 rubric_code 判、
           判断条目取这一份评审的判定；met=true 的证据须在镜头块里逐字找得到，hollywood_r5.parse_evidence）→ 3 份 σ（总体标准差）≤ 1 才算稳定；
           判断条目按多数合成一份分数。结果写 <run>/judge_out/judge_epNN.result.json；--write-score 时稳定的结果追加到 data/rsi/scores.jsonl（line=script_judge）。
任务包格式见 docs/hollywood/judge_agent_interface.md。评审 agent 由总调度派；HOLLYWOOD 不自己作答。
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TASKS, OUTS = "judge_tasks", "judge_out"
SIGMA_MAX = 1.0
MIN_REPS = 3
V3_ITEMS = ("stakes", "opposition", "subtext_contrast", "open5s")      # hollywood_judge.md §七


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _sha(t: str) -> str:
    return hashlib.sha256(t.encode("utf-8")).hexdigest()[:16]


def _write_json(p: Path, d) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


def _modules():
    L3 = _load("line3_score", "tools/script_rsi/line3_score.py")
    R5 = _load("hollywood_r5", "tools/script_rsi/hollywood_r5.py")
    return L3, R5


def pack(run_dir: Path, ep: int, reps: int = MIN_REPS) -> list[str]:
    L3, R5 = _modules()
    got = L3.best_chunk(run_dir, ep)
    if got is None:
        raise FileNotFoundError(f"{run_dir.name} 第 {ep} 集没有稿")
    pre, chunk = got
    system, user = R5.judge_system_r6(), R5.H.judge_user(ep, pre, chunk, None)
    items = [f"{d}#{i}" for d, i, _t in R5.judge_items_r6()]
    out = []
    for k in range(1, reps + 1):
        op = run_dir / OUTS / f"judge_ep{ep:02d}_r{k}.json"
        pk = {"schema": "nsfs.judge_task/1", "run": run_dir.name, "episode": ep, "rep": k, "reps": reps, "role": "judge",
              "base_sha": _sha(chunk), "judge_md": "config/prompts/hollywood_judge.md", "items": items,
              "system": system, "user": user,
              "rules": ("你是独立评审：不是写手，也不是 HOLLYWOOD。每份任务包单独作答，不看别的 rep 的产物，不看写手的自检。"
                        "只判 items 里列出的条目；每条 met=true 必须附镜头块里逐字可找到的原文证据，找不到就判 false。"
                        "只输出一个 ```json（格式按 hollywood_judge.md §六：{\"items\": {\"<维度>\": [{\"id\": 1, \"met\": true, \"evidence\": \"原文\", \"why\": \"…\"}]}}），"
                        "另加 §七 的 \"v3\" 四条（stakes / opposition / subtext_contrast / open5s）和顶层 \"judge_id\"（你的评审 agent 名；3 份须来自 3 个不同评审）。"),
              "output": {"path": str(op.relative_to(ROOT)).replace("\\", "/"), "done_marker": str(op.relative_to(ROOT)).replace("\\", "/") + ".done"},
              "collect_cmd": f".venv/Scripts/python.exe tools/script_rsi/judge_agent.py collect --run-dir {str(run_dir.relative_to(ROOT)).replace(chr(92), '/')} --episode {ep}",
              "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "status": "open"}
        p = run_dir / TASKS / f"judge_ep{ep:02d}_r{k}.json"
        _write_json(p, pk)
        out.append(str(p.relative_to(ROOT)).replace("\\", "/"))
    return out


def rep_total(code: dict, judged: dict, llm_items: list[tuple[str, int]], dims) -> int:
    """一份评审的 50 分制总分：每维 5 条，条目满足 = 代码条目过（若有）且判断条目这一份判 met（若有）；每维至少 1 分（同 score_r6）"""
    tot = 0
    for d in dims:
        m = 0
        for i in range(1, 6):
            ok = True
            if (d, i) in llm_items:
                ok &= bool(judged.get(d, {}).get(i, {}).get("met"))
            if i in code.get(d, {}):
                ok &= bool(code[d][i][0])
            m += ok
        tot += max(1, m)
    return tot


def stability(totals: list[int]) -> dict:
    n = len(totals)
    sigma = round(statistics.pstdev(totals), 3) if n >= 2 else None
    return {"n": n, "totals": totals, "sigma": sigma, "mean": round(statistics.mean(totals), 2) if totals else None,
            "stable": n >= MIN_REPS and sigma is not None and sigma <= SIGMA_MAX}


def collect(run_dir: Path, ep: int, write_score: bool = False) -> dict:
    L3, R5 = _modules()
    pre, chunk = L3.best_chunk(run_dir, ep)
    RC6, H, RL = R5.RC6, R5.H, R5.RL
    wd = run_dir / f"work_ep{ep:02d}"
    wd.mkdir(exist_ok=True)
    obj = H.episode_obj(pre, chunk, ep, wd)
    shots = sorted(obj.shots, key=lambda s: s.index)
    blocks = [RL.block_text(chunk, k) for k in range(len(shots))]
    code = RC6.code_checks(chunk, shots, blocks, RL.block_text(chunk, "head"), H.lint(chunk, ep)["codes"])
    llm_items = [(d, i) for d, i, _t in R5.judge_items_r6()]
    reps, problems = [], []
    for p in sorted((run_dir / TASKS).glob(f"judge_ep{ep:02d}_r*.json")):
        pk = json.loads(p.read_text(encoding="utf-8"))
        op = ROOT / pk["output"]["path"]
        if not (op.exists() and Path(str(op) + ".done").exists()):
            problems.append(f"r{pk['rep']} 还没交")
            continue
        if pk.get("base_sha") != _sha(chunk):
            problems.append(f"r{pk['rep']} 出包后稿变了，作废（重新 pack）")
            continue
        judged, err = R5.parse_evidence(op.read_text(encoding="utf-8"), chunk)
        if judged is None:
            problems.append(f"r{pk['rep']} 不是 §六 的 JSON：{err}")
            continue
        raw_d, _e = R5.H._json_block(op.read_text(encoding="utf-8"))
        v3 = {str(x.get("id")): bool(x.get("met")) and bool(str(x.get("evidence") or "").strip())
              for x in (raw_d or {}).get("v3") or [] if isinstance(x, dict)}
        reps.append({"rep": pk["rep"], "total": rep_total(code, judged, llm_items, RC6.DIMS), "judged": judged,
                     "judge_id": str((raw_d or {}).get("judge_id") or "").strip(), "v3": v3})
    st = stability([r["total"] for r in reps])
    ids = [r["judge_id"] for r in reps]
    single = len(reps) >= 2 and (any(not x for x in ids) or len(set(ids)) < len(ids))     # 总调度 11-02：同一个评审做 3 份，σ≈0 不能证明尺子稳定
    if single:
        st["stable"] = False
    majority = {f"{d}#{i}": sum(bool(r["judged"].get(d, {}).get(i, {}).get("met")) for r in reps) * 2 > len(reps)
                for d, i in llm_items} if reps else {}
    res = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "run": run_dir.name, "episode": ep, "base_sha": _sha(chunk), **st,
           "per_rep": [{"rep": r["rep"], "total": r["total"]} for r in reps], "llm_majority": majority,
           "code_failed": [f"{d}#{i}" for d in RC6.DIMS for i, v in code[d].items() if not v[0]], "problems": problems,
           "judge_ids": ids, "single_judge": single,
           "v3_majority": {k: sum(r["v3"].get(k, False) for r in reps) * 2 > len(reps) for k in V3_ITEMS} if reps else {},
           "verdict": ("single_judge（3 份不是 3 个不同评审，σ 未验证，不作正式分）" if single else
                       "stable" if st["stable"] else ("waiting" if len(reps) < MIN_REPS else "unstable（σ > 1：评审口径不稳，这一稿的判断分不采用）"))}
    _write_json(run_dir / OUTS / f"judge_ep{ep:02d}.result.json", res)
    if write_score and st["stable"]:
        rec = {"at": res["at"], "line": "script_judge", "run": run_dir.name, "episode": ep, "score50": st["mean"], "sigma": st["sigma"],
               "reps": st["n"], "base_sha": res["base_sha"], "note": "独立 Claude 评审 agent，hollywood_judge.md r6 口径，3 次 σ ≤ 1"}
        with open(ROOT / "data" / "rsi" / "scores.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return res


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("pack", "collect"):
        s = sub.add_parser(name)
        s.add_argument("--run-dir", required=True)
        s.add_argument("--episodes", default="1")
        if name == "pack":
            s.add_argument("--reps", type=int, default=MIN_REPS)
        else:
            s.add_argument("--write-score", action="store_true")
    a = ap.parse_args(argv)
    run_dir = Path(a.run_dir) if Path(a.run_dir).is_absolute() else ROOT / a.run_dir
    L3, _R5 = _modules()
    eps = sorted(L3.H.RL.parse_episodes(a.episodes))
    for ep in eps:
        if a.cmd == "pack":
            print(json.dumps({"episode": ep, "packets": pack(run_dir, ep, a.reps)}, ensure_ascii=False))
        else:
            r = collect(run_dir, ep, a.write_score)
            print(json.dumps({k: r[k] for k in ("episode", "n", "totals", "sigma", "mean", "verdict", "problems")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
