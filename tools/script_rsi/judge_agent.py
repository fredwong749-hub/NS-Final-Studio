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
BSL = chr(92)
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


def _rel(p: Path) -> str:
    """仓库内 → 相对路径（正斜杠）；仓库外（测试临时目录）→ 绝对路径"""
    try:
        return str(Path(p).resolve().relative_to(ROOT.resolve())).replace(BSL, "/")
    except ValueError:
        return str(Path(p).resolve()).replace(BSL, "/")


def _abs(s: str) -> Path:
    q = Path(s)
    return q if q.is_absolute() else ROOT / q


# ---- 盲评（总调度 11-02：v2 / v3 对比，包里不写版本，用随机编号，对照表另存，collect 时还原）
def _doc_chunk(path: Path) -> tuple[str, str, int]:
    import re as _re
    _L3, R5 = _modules()
    pre, chunks = R5.RL.split_doc(path.read_text(encoding="utf-8"))
    return pre, chunks[0], int(_re.search(r"ep(\d+)", path.name).group(1))


def _key_dir(out: Path) -> Path:
    """对照表不放在评审包目录下：<out 的上级>/_keys/<out 名>/（评审只读自己的 judge_k 目录）"""
    return out.parent / "_keys" / out.name


def blind_pack(sources: dict, eps: list, judges: int, out: Path, seed=None) -> dict:
    """sources = {版本标签: 快照目录（含 P4_epNN.final.md）}。每个评审 judge_k 拿到 len(sources) × len(eps) 份，随机编号、顺序打乱；
    对照表写 out/_key/KEY.json（评审不读这个目录）。返回 {judge_k: [包路径…]}"""
    import random
    import secrets
    rng = random.Random(seed if seed is not None else secrets.randbits(64))
    _L3, R5 = _modules()
    system = R5.judge_system_r6()
    items = [f"{d}#{i}" for d, i, _t in R5.judge_items_r6()]
    key = {"created_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "sources": {k: _rel(v) for k, v in sources.items()}, "packets": {}}
    made, used = {}, set()
    for j in range(1, judges + 1):
        docs = [(tag, ep) for tag in sources for ep in eps]
        rng.shuffle(docs)
        made[f"judge_{j}"] = []
        for order, (tag, ep) in enumerate(docs, 1):
            bid = None
            while bid is None or bid in used:
                bid = f"B{rng.randrange(10 ** 5, 10 ** 6)}"
            used.add(bid)
            doc = Path(sources[tag]) / f"P4_ep{ep:02d}.final.md"
            pre, chunk, _ep = _doc_chunk(doc)
            op = out / f"judge_{j}" / "out" / f"{bid}.json"
            pk = {"schema": "nsfs.judge_task/1", "mode": "blind", "judge_slot": f"judge_{j}", "blind_id": bid, "order": order,
                  "role": "judge", "judge_md": "config/prompts/hollywood_judge.md", "items": items, "system": system,
                  "user": R5.H.judge_user(ep, pre, chunk, None),
                  "rules": ("你是独立评审：不是写手，也不是 HOLLYWOOD；只读自己这个 judge 目录里的包，不要打开别的目录，不要猜这份稿是哪一版。每份单独作答，按 order 顺序做。"
                            "只判 items 里的条目；met=true 必须附镜头块里逐字可找到的原文证据。只输出一个 ```json（hollywood_judge.md §六 + §七 v3 四条），"
                            "顶层写 judge_id（你的评审 agent 名）和 blind_id。"),
                  "output": {"path": _rel(op), "done_marker": _rel(op) + ".done"},
                  "created_at": key["created_at"], "status": "open"}
            pp = out / f"judge_{j}" / f"{order:02d}_{bid}.json"
            _write_json(pp, pk)
            made[f"judge_{j}"].append(_rel(pp))
            key["packets"][bid] = {"judge_slot": f"judge_{j}", "version": tag, "episode": ep, "doc": _rel(doc),
                                   "base_sha": _sha(chunk), "output": _rel(op)}
    _write_json(_key_dir(out) / "KEY.json", key)
    return made


def blind_collect(out: Path) -> dict:
    """按对照表还原：每个（版本, 集）收各评审的 50 分制总分 → σ / 均值 / 是否不同评审；v3 四条多数。结果写 out/_key/RESULT.json"""
    _L3, R5 = _modules()
    RC6, H, RL = R5.RC6, R5.H, R5.RL
    key = json.loads((_key_dir(out) / "KEY.json").read_text(encoding="utf-8"))
    llm_items = [(d, i) for d, i, _t in R5.judge_items_r6()]
    code_cache, groups, problems = {}, {}, []
    for bid, k in key["packets"].items():
        op = _abs(k["output"])
        if not (op.exists() and Path(str(op) + ".done").exists()):
            problems.append(f"{k['judge_slot']} {bid} 还没交")
            continue
        pre, chunk, ep = _doc_chunk(_abs(k["doc"]))
        if _sha(chunk) != k["base_sha"]:
            problems.append(f"{bid} 稿变了，作废")
            continue
        if k["doc"] not in code_cache:
            wd = _key_dir(out) / "work" / k["version"] / f"ep{ep:02d}"
            wd.mkdir(parents=True, exist_ok=True)
            obj = H.episode_obj(pre, chunk, ep, wd)
            shots = sorted(obj.shots, key=lambda q: q.index)
            blocks = [RL.block_text(chunk, n) for n in range(len(shots))]
            code_cache[k["doc"]] = RC6.code_checks(chunk, shots, blocks, RL.block_text(chunk, "head"), H.lint(chunk, ep)["codes"])
        raw = op.read_text(encoding="utf-8")
        judged, err = R5.parse_evidence(raw, chunk)
        if judged is None:
            problems.append(f"{bid} 不是 §六 的 JSON：{err}")
            continue
        raw_d, _e = H._json_block(raw)
        v3 = {str(x.get("id")): bool(x.get("met")) and bool(str(x.get("evidence") or "").strip())
              for x in (raw_d or {}).get("v3") or [] if isinstance(x, dict)}
        groups.setdefault(f"{k['version']}|ep{k['episode']:02d}", []).append(
            {"blind_id": bid, "judge_slot": k["judge_slot"], "judge_id": str((raw_d or {}).get("judge_id") or "").strip(),
             "total": rep_total(code_cache[k["doc"]], judged, llm_items, RC6.DIMS), "v3": v3})
    res = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "groups": {}, "problems": problems}
    for name, g in sorted(groups.items()):
        st = stability([x["total"] for x in g])
        ids = [x["judge_id"] for x in g]
        single = any(not x for x in ids) or len(set(ids)) < len(ids)
        res["groups"][name] = {**st, "stable": st["stable"] and not single, "single_judge": single, "judge_ids": ids,
                               "v3_majority": {it: sum(x["v3"].get(it, False) for x in g) * 2 > len(g) for it in V3_ITEMS}}
    _write_json(_key_dir(out) / "RESULT.json", res)
    return res


# ---- P1 故事线三评委（总调度 11-02 19:3x：P1 先过三评委盲评再交项目方；口径 config/prompts/hollywood_p1_judge.md）
P1_ITEMS = ("act3", "arc", "men", "hooks", "av", "theme", "assets", "craft")


def p1_pack(run_dir: Path, judges: int = 3, out: Path | None = None) -> list[str]:
    """每个评审一份同样的包（P1 故事线 + 造型表 + 口径），目录 judge_p1/judge_k/；评审互不相见"""
    md = (ROOT / "config" / "prompts" / "hollywood_p1_judge.md").read_text(encoding="utf-8")
    sl = (run_dir / "P1_storyline.json").read_text(encoding="utf-8")
    lk = (run_dir / "P1_looks.json").read_text(encoding="utf-8") if (run_dir / "P1_looks.json").exists() else "（没有造型表）"
    out = out or (run_dir / "judge_p1")
    made = []
    for j in range(1, judges + 1):
        op = out / f"judge_{j}" / "out" / "p1_review.json"
        pk = {"schema": "nsfs.judge_task/1", "mode": "p1", "judge_slot": f"judge_{j}", "role": "judge", "judge_md": "config/prompts/hollywood_p1_judge.md",
              "base_sha": _sha(sl), "system": md, "user": "【P1 故事线】\n" + sl + "\n\n【造型表】\n" + lk,
              "rules": "独立作答：只读自己这个 judge 目录的包，不看别的评审，不看写手的自检。顶层写 judge_id。",
              "output": {"path": _rel(op), "done_marker": _rel(op) + ".done"}, "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "status": "open"}
        pp = out / f"judge_{j}" / "p1_review_task.json"
        _write_json(pp, pk)
        made.append(_rel(pp))
    return made


def p1_collect(run_dir: Path, out: Path | None = None) -> dict:
    """收三家：每家 8 条 1–5 分（满分 40）→ 各家总分、σ、逐条均分与分歧（逐条极差 ≥2 的列出来），3 个 judge_id 互不相同才算有效"""
    out = out or (run_dir / "judge_p1")
    sl = (run_dir / "P1_storyline.json").read_text(encoding="utf-8")
    reps, problems = [], []
    for pp in sorted(out.glob("judge_*/p1_review_task.json")):
        pk = json.loads(pp.read_text(encoding="utf-8"))
        op = _abs(pk["output"]["path"])
        if not (op.exists() and Path(str(op) + ".done").exists()):
            problems.append(f"{pk['judge_slot']} 还没交")
            continue
        if pk.get("base_sha") != _sha(sl):
            problems.append(f"{pk['judge_slot']} 出包后故事线变了，作废")
            continue
        _L3, R5 = _modules()
        d, err = R5.H._json_block(op.read_text(encoding="utf-8"))
        if d is None:
            problems.append(f"{pk['judge_slot']} 不是 JSON：{err}")
            continue
        sc = {str(x.get("id")): max(1, min(5, int(x.get("score") or 1))) if str(x.get("evidence") or "").strip() else 1
              for x in d.get("items") or [] if isinstance(x, dict)}
        if set(sc) != set(P1_ITEMS):
            problems.append(f"{pk['judge_slot']} 条目不全：缺 {sorted(set(P1_ITEMS) - set(sc))}")
            continue
        reps.append({"judge_slot": pk["judge_slot"], "judge_id": str(d.get("judge_id") or "").strip(), "scores": sc,
                     "total": sum(sc.values()), "top_fixes": d.get("top_fixes") or []})
    st = stability([r["total"] for r in reps])
    ids = [r["judge_id"] for r in reps]
    single = any(not x for x in ids) or len(set(ids)) < len(ids)
    per_item = {it: [r["scores"][it] for r in reps] for it in P1_ITEMS} if reps else {}
    res = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "run": run_dir.name, "base_sha": _sha(sl), **st, "max": 40,
           "stable": st["stable"] and not single, "single_judge": single, "judge_ids": ids,
           "item_mean": {k: round(sum(v) / len(v), 2) for k, v in per_item.items()},
           "item_split": {k: v for k, v in per_item.items() if v and max(v) - min(v) >= 2},
           "top_fixes": [f for r in reps for f in r["top_fixes"]][:12], "problems": problems}
    _write_json(out / "RESULT.json", res)
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
    bp = sub.add_parser("blind-pack", help="盲评出包：--source v2=<快照目录> --source v3=<快照目录>")
    bp.add_argument("--source", action="append", required=True)
    bp.add_argument("--episodes", default="1-3")
    bp.add_argument("--judges", type=int, default=3)
    bp.add_argument("--out", required=True)
    bc = sub.add_parser("blind-collect")
    bc.add_argument("--out", required=True)
    pp_ = sub.add_parser("p1-pack", help="P1 故事线三评委出包（每家一份，互不相见）")
    pp_.add_argument("--run-dir", required=True)
    pp_.add_argument("--judges", type=int, default=3)
    pc_ = sub.add_parser("p1-collect")
    pc_.add_argument("--run-dir", required=True)
    a = ap.parse_args(argv)
    if a.cmd in ("p1-pack", "p1-collect"):
        rd = _abs(a.run_dir)
        if a.cmd == "p1-pack":
            print(json.dumps({"packets": p1_pack(rd, a.judges)}, ensure_ascii=False, indent=1))
        else:
            r = p1_collect(rd)
            print(json.dumps({k: r[k] for k in ("n", "totals", "sigma", "mean", "stable", "single_judge", "item_mean", "item_split", "problems")},
                             ensure_ascii=False, indent=1))
        return 0
    if a.cmd in ("blind-pack", "blind-collect"):
        outd = _abs(a.out)
        if a.cmd == "blind-pack":
            L3, _R5 = _modules()
            srcs = {x.split("=", 1)[0]: _abs(x.split("=", 1)[1]) for x in a.source}
            made = blind_pack(srcs, sorted(L3.H.RL.parse_episodes(a.episodes)), a.judges, outd)
            print(json.dumps({k: len(v) for k, v in made.items()}, ensure_ascii=False))
        else:
            r = blind_collect(outd)
            print(json.dumps({k: {x: v[x] for x in ("n", "totals", "sigma", "mean", "stable", "single_judge")} for k, v in r["groups"].items()},
                             ensure_ascii=False, indent=1))
            if r["problems"]:
                print("问题：", r["problems"][:12])
        return 0
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
