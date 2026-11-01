"""
V2（方案 A）：从 loop（data/iterate_loop/ep02_v2）和 fanout（data/ab/v2_iter/fanout）的已审版本里，按机器指标给每镜挑一版，
写 --sources-from 用的时间线 + 选择报告（planA_report.md 的数据源）。不定稿；剪辑导演的覆盖写在 director/verdicts.json
（"pick": "<来源 id>" 或 "reject": [来源 id…]）。

打分（越小越好）：每条未过的验收项按超出比例计分；静止 / 泛红 / 身份 权重 2，其他 1。没有任何新版本的镜用后备（v1 / LAB 版本）。
用法：python tools/ep02_iter/planA_sources.py [--fallback data/episodes/ep02_v1.timeline.json]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / "data/iterate_loop/ep02_v2"
FO = ROOT / "data/ab/v2_iter/fanout"
OUT = ROOT / "data/ab/v2_iter/planA"
W = {"still_frac": 2, "cheek_red_max": 2, "cheek_a_drift": 1, "sface_ref_min": 2, "sface_self_min": 1,
     "frozen_tail_s": 1, "frozen_head_s": 1, "J4": 1, "red_blob_max": 1, "lipsync_corr": 1, "dark_run_s": 1}


def score(fails: list[dict]) -> float:
    s = 0.0
    for f in fails or []:
        v, t = f.get("value"), f.get("threshold")
        if v is None or not t:
            s += W.get(f["metric"], 1)
            continue
        over = (v - t) / t if f["metric"] not in ("sface_ref_min", "sface_self_min", "lipsync_corr") else (t - v) / t
        s += W.get(f["metric"], 1) * (1 + max(0.0, over))
    return round(s, 3)


def candidates() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    plans = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in (RUN / "plans").glob("*.json")}
    takes: dict[str, list[dict]] = {}
    for tj in (ROOT / "data/renders/ep02").glob("S*/takes.json"):
        for t in json.loads(tj.read_text(encoding="utf-8")).get("takes") or []:
            if t.get("stage") == "video" and ((t.get("params") or {}).get("recipe") or {}).get("plan_hash"):
                takes.setdefault(f"ep02-{tj.parent.name}", []).append(t)
    for rf in sorted((RUN / "results").glob("*/*.json")):
        r = json.loads(rf.read_text(encoding="utf-8"))
        if "metrics" not in r:
            continue
        sid = rf.parent.name
        # 视频源 = 计划哈希相同的那版；只改后处理的结果（哈希对不上）= 结果时间之前最近一版（post_only_of 之前写的结果没有这项）
        tk = [t for t in takes.get(sid, []) if t["params"]["recipe"]["plan_hash"] in (r["plan_hash"], r.get("post_only_of"))]
        if not tk:
            tk = sorted([t for t in takes.get(sid, []) if (t.get("created_at") or "") <= (r.get("at") or "~")],
                        key=lambda t: t.get("created_at") or "")[-1:]
        src_take = tk[-1] if tk else None
        review = r.get("review")
        post = next(iter(sorted((RUN / "post").glob(f"{sid}_*{r['plan_hash'][:8]}*.mp4"), key=lambda p: -len(p.name))), None)
        pl = plans.get(r["plan_hash"][:16]) or {}
        out.setdefault(sid, []).append({"id": f"loop:{rf.stem}:{r['plan_hash'][:8]}", "file": str(post) if post else None,
                                        "metrics": r["metrics"], "failures": r.get("failures"),
                                        "group": ("new" if "At 00:" in (src_take or {}).get("prompt", "") else "old") if src_take
                                        else ("new" if "At 00:" in (pl.get("prompt") or {}).get("text", "") else "old"),
                                        "take": (src_take or {}).get("n"),
                                        "recipe": (pl.get("recipe") or {}).get("id"), "review": review,
                                        "post_only_of": r.get("post_only_of")})
    if (FO / "manifest.json").exists():
        for e in json.loads((FO / "manifest.json").read_text(encoding="utf-8"))["entries"]:
            if e.get("state") != "reviewed":
                continue
            out.setdefault(e["shot"], []).append({"id": f"fanout:o{e['offset']}:{e['plan_hash'][:8]}", "file": e.get("post_file"),
                                                  "metrics": e.get("metrics"), "failures": e.get("failures"),
                                                  "group": "new", "recipe": e["recipe"], "take": e.get("take"),
                                                  "sheet": e.get("sheet")})
    for sid, cs in out.items():
        for c in cs:
            c["score"] = score(c["failures"])
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fallback", default=str(ROOT / "data/episodes/ep02_v1.timeline.json"))
    a = ap.parse_args()
    vd_p = RUN / "director" / "verdicts.json"
    vd = json.loads(vd_p.read_text(encoding="utf-8")) if vd_p.exists() else {}
    fb = {s["index"]: s for s in json.loads(Path(a.fallback).read_text(encoding="utf-8"))["shots"]}
    cands = candidates()
    shots, report = [], []
    for idx in sorted(fb):
        sid = f"ep02-S{idx}"
        cs = [c for c in cands.get(sid, []) if c.get("file") and Path(c["file"]).exists()
              and c["id"] not in ((vd.get(sid) or {}).get("reject") or [])]
        pick = (vd.get(sid) or {}).get("pick")
        chosen = next((c for c in cs if c["id"] == pick), None) if pick else None
        if chosen is None and cs:
            chosen = min(cs, key=lambda c: (c["score"], c["group"] != "new"))
        if chosen:
            f = Path(chosen["file"])
            rel = str(f.relative_to(ROOT)).replace("\\", "/")
            shots.append({"shot": sid, "index": idx, "kind": "video", "file": rel, "origin": "planA"})
            report.append({"shot": sid, "pick": chosen["id"], "group": chosen["group"], "recipe": chosen.get("recipe"),
                           "score": chosen["score"], "metrics": chosen["metrics"],
                           "failures": [x["metric"] for x in chosen.get("failures") or []],
                           "n_candidates": len(cs), "all": [(c["id"], c["score"], c["group"]) for c in cs]})
        else:
            s = fb[idx]
            shots.append({"shot": sid, "index": idx, "kind": "video", "file": s["file"], "origin": "fallback_v1"})
            report.append({"shot": sid, "pick": "fallback:" + s["file"], "group": "v1", "n_candidates": 0})
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "sources.timeline.json").write_text(json.dumps({"episode": 2, "shots": shots}, ensure_ascii=False, indent=1),
                                               encoding="utf-8")
    (OUT / "selection.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    for r in report:
        print(r["shot"], r["pick"], r.get("group"), r.get("score"), r.get("failures"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
