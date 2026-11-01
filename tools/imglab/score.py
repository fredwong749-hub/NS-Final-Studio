"""RSI 线 1（出图）代码化打分器（IMGLAB，docs/master/RSI_PROGRAM.md 线 1，L-112）。

只读生产版本记录（data/renders/epNN/SN/takes.json 里 stage=image 的 postflight，即生成契约逐项结果），不出图、不调模型。
分项与权重（RSI_PROGRAM 线 1 表）：
  identity 25   Q1 通过率（Q1 三段：pass 计 1，复核带计 0.5）；Q1x / Q1a 有记录时并入（同权平均）
  hands    15   Q5 坏手 / 多肢检出率 r（越低越好）：得分 = 1 − r / 0.20（r ≥ 20% 记 0；今晚目标 ≤10% = 半分以上）
  pose     15   Q3 景别档准确率（姿势模板匹配上线后并入）
  light    20   合成感 / 动机光一致 / VLM 融合题——SENTINEL composite 接口阈值未定 → 记 missing，partial=true，不计入总分分母
  gaze     10   G1 看镜头的脸占比 g：得分 = 1 − g / 0.20
  pass_speed 15 一半：每镜第一个版本一次过契约率 / 0.80；一半：出图耗时 p50（≤90 s 满分，≥240 s 记 0）
总分 = Σ 权重 × 分项得分 ÷ 已测权重和 × 100。写 data/rsi/scores.jsonl（line=image）。

    .venv/Scripts/python.exe tools/imglab/score.py                 # 最近 24 h 的版本
    .venv/Scripts/python.exe tools/imglab/score.py --since 2026-11-01T12:00 --no-write --json
"""
from __future__ import annotations

import argparse
import glob
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1].parent
WEIGHTS = {"identity": 25, "hands": 15, "pose": 15, "light": 20, "gaze": 10, "pass_speed": 15}
SCORES = ROOT / "data/rsi/scores.jsonl"


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def load_takes(since: str, renders: Path | None = None) -> list[dict]:
    out = []
    for p in sorted(glob.glob(str((renders or ROOT / "data/renders") / "ep*/S*/takes.json"))):
        try:
            d = json.loads(Path(p).read_text(encoding="utf-8"))
        except (OSError, ValueError):   # arch-ok: 写入中 / 坏的 takes.json 跳过这一镜，打分器只读、不阻断（次轮再读）
            continue
        shot = Path(p).parent.parent.name + "-" + Path(p).parent.name
        for t in d.get("takes") or []:
            if t.get("stage") != "image" or (t.get("created_at") or "") < since:
                continue
            out.append({**t, "_shot": shot})
    return out


def _items(t: dict) -> dict:
    return {i.get("id"): i for i in ((t.get("postflight") or {}).get("items") or [])}


def score(takes: list[dict]) -> dict:
    measured = [t for t in takes if (t.get("postflight") or {}).get("items")]
    parts, detail, missing = {}, {}, {}
    # identity
    q1 = [_items(t).get("Q1") for t in measured]
    q1 = [x for x in q1 if x and x.get("status") in ("pass", "fail", "review")]
    if q1:
        val = sum(1.0 if x["status"] == "pass" else 0.5 if x["status"] == "review" else 0.0 for x in q1) / len(q1)
        extra = []
        for qid in ("Q1x", "Q1a"):
            xs = [_items(t).get(qid) for t in measured]
            xs = [x for x in xs if x and x.get("status") in ("pass", "fail")]
            if xs:
                extra.append(sum(x["status"] == "pass" for x in xs) / len(xs))
                detail[qid] = {"n": len(xs), "pass_rate": round(extra[-1], 3)}
        parts["identity"] = statistics.mean([val, *extra])
        detail["Q1"] = {"n": len(q1), "pass_rate": round(val, 3)}
    else:
        missing["identity"] = "没有 Q1 记录"
    # hands
    q5 = [_items(t).get("Q5") for t in measured]
    q5 = [x for x in q5 if x and x.get("status") in ("pass", "fail")]
    if q5:
        r = sum(x["status"] == "fail" for x in q5) / len(q5)
        parts["hands"] = _clamp(1 - r / 0.20)
        detail["Q5"] = {"n": len(q5), "defect_rate": round(r, 3)}
    else:
        missing["hands"] = "没有 Q5 记录"
    # pose
    q3 = [_items(t).get("Q3") for t in measured]
    q3 = [x for x in q3 if x and x.get("status") in ("pass", "fail")]
    if q3:
        parts["pose"] = sum(x["status"] == "pass" for x in q3) / len(q3)
        detail["Q3"] = {"n": len(q3), "pass_rate": round(parts["pose"], 3)}
    else:
        missing["pose"] = "没有 Q3 记录"
    # light（合成感接口未定）
    comp = [_items(t).get("C1") or _items(t).get("composite") for t in measured]
    comp = [x for x in comp if x and x.get("status") in ("pass", "fail")]
    if comp:
        parts["light"] = sum(x["status"] == "pass" for x in comp) / len(comp)
        detail["composite"] = {"n": len(comp), "pass_rate": round(parts["light"], 3)}
    else:
        missing["light"] = "合成感指标未接（SENTINEL composite 阈值未定）"
    # gaze
    faces, cam = 0, 0
    for t in measured:
        g = _items(t).get("G1") or {}
        for f in (g.get("evidence") or {}).get("faces") or []:
            faces += 1
            cam += 1 if "看镜头" in str(f.get("status") or "") else 0
    if faces:
        gr = cam / faces
        parts["gaze"] = _clamp(1 - gr / 0.20)
        detail["G1"] = {"faces": faces, "camera_rate": round(gr, 3)}
    else:
        missing["gaze"] = "没有 G1 记录"
    # pass + speed
    first = {}
    for t in sorted(measured, key=lambda t: (t["_shot"], t.get("n") or 0)):
        first.setdefault(t["_shot"], t)
    secs = [float(t["seconds"]) for t in takes if t.get("seconds")]
    if first:
        pr = sum(bool((t.get("postflight") or {}).get("ok")) for t in first.values()) / len(first)
        p50 = statistics.median(secs) if secs else None
        sp = _clamp((240 - p50) / (240 - 90)) if p50 is not None else 0.0
        parts["pass_speed"] = 0.5 * _clamp(pr / 0.80) + 0.5 * sp
        detail["pass_speed"] = {"shots": len(first), "first_pass_rate": round(pr, 3),
                                "render_p50_s": round(p50, 1) if p50 is not None else None, "n_timed": len(secs)}
    else:
        missing["pass_speed"] = "没有版本"
    wsum = sum(WEIGHTS[k] for k in parts)
    total = round(sum(WEIGHTS[k] * v for k, v in parts.items()) / wsum * 100, 2) if wsum else 0.0
    lowest = min(parts, key=lambda k: parts[k]) if parts else None
    return {"score": total, "parts": {k: round(v * WEIGHTS[k], 2) for k, v in parts.items()},
            "parts_pct": {k: round(v * 100, 1) for k, v in parts.items()}, "weights": WEIGHTS,
            "partial": bool(missing), "missing": missing, "detail": detail, "lowest": lowest,
            "n_takes": len(takes), "n_measured": len(measured)}


def _sv() -> str | None:
    try:
        r = subprocess.run(["git", "describe", "--tags", "--match", "sv-*", "--abbrev=0"], cwd=ROOT,
                           capture_output=True, text=True, timeout=20)
        return r.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):   # arch-ok: 没有 git 时版本号记空，不影响分数
        return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--since", default=None, help="ISO 时间；缺省 = 24 小时前")
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    since = a.since or time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - 86400))
    r = score(load_takes(since))
    rec = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "line": "image", "since": since, "version": _sv(), **r}
    if not a.no_write:
        SCORES.parent.mkdir(parents=True, exist_ok=True)
        with SCORES.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    if a.json:
        print(json.dumps(rec, ensure_ascii=False, indent=1))
    else:
        print(f"出图线 {rec['score']}（{'部分' if r['partial'] else '完整'}）最低分项 {r['lowest']}：{r['parts_pct']}；缺 {list(r['missing'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
