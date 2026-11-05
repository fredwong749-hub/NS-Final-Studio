"""K-EDT-805（总调度 11-02 转 VQAGATE 查证，docs/vqa/GATE_CALIBRATION.md §10–11）：画内对白一旦被 TTS 兜底，
这一镜的口型和成片里的声音对不上——标“口型与成片声音不一致”，送回重出视频，不进定稿。

  python tools/director/lip_redo.py scan <timeline.json> …   → 列出要重出的镜，追加到 data/director/redo_requests.json
night 合成接线（CONSENT 待 VIDEO10 / WORKFLOW 落地）：finalize 合成完调 blocking(timeline)，非空 → 本集只出预览、不定稿，
并对返回的镜走现有“驳回 → 待重出”（producer.master_reject / full_redo 的同一条路径）。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REQ = ROOT / "data" / "director" / "redo_requests.json"
CFG = ROOT / "config" / "post" / "director.json"
REASON = "口型与成片声音不一致（画内对白 H3 原声回听不合格，TTS 兜底）"
CAP_DEFAULT = 1


def cap(cfg_path: Path | None = None) -> int:
    """每镜最多开几张口型重出单（config/post/director.json lip_redo_max_per_shot，默认 1；与 vidgen.lip_redo_cap 同一键）。
    VID-LOOP 11-06：每次重合成 timeline 版本号都变，以前每版都追加一张“新”单 → ep01-S1 51 张、作废重出 51 次"""
    try:
        return max(0, int(json.loads((cfg_path or CFG).read_text(encoding="utf-8")).get("lip_redo_max_per_shot", CAP_DEFAULT)))
    except (OSError, ValueError, TypeError):   # arch-ok: 配置读不到 = 默认上限 1
        return CAP_DEFAULT


def blocking(tl: dict) -> list[dict]:
    """→ [{shot, index, reason, fallback_reason}]：画内对白被 TTS 兜底的镜（旁白 / 画外音不算）"""
    ep = int(tl.get("episode") or 0)
    shots = {int(s["index"]): s for s in tl.get("shots") or []}
    dia = {int(x["shot"]) for x in tl.get("speech") or [] if x.get("kind") == "dialogue" and not x.get("off")}
    out = []
    for h in tl.get("h3_dialogue") or []:
        i = int(h.get("shot") or 0)
        if h.get("dialogue") == "tts_fallback" and i in dia:
            out.append({"shot": (shots.get(i) or {}).get("shot") or f"ep{ep:02d}-S{i}", "index": i, "reason": REASON,
                        "fallback_reason": h.get("fallback_reason"), "rule": "K-EDT-805",
                        "still": bool((shots.get(i) or {}).get("placeholder"))})
    return out


def record(tl_path: Path) -> list[dict]:
    tl = json.loads(tl_path.read_text(encoding="utf-8"))
    rows = blocking(tl)
    REQ.parent.mkdir(parents=True, exist_ok=True)
    cur = json.loads(REQ.read_text(encoding="utf-8")) if REQ.exists() else {"_doc": __doc__.strip().splitlines()[0], "requests": []}
    seen = {(r["shot"], r["timeline"]) for r in cur["requests"]}
    rel = str(tl_path.resolve().relative_to(ROOT)).replace("\\", "/") if tl_path.resolve().is_relative_to(ROOT) else str(tl_path)
    limit = cap()
    for r in rows:
        if (r["shot"], rel) in seen:
            continue
        prior = sum(1 for x in cur["requests"] if x.get("shot") == r["shot"])
        if prior >= limit:     # 已到上限：不再追加同一镜的单（vidgen 那边也不会再作废）；返回行里标 capped 给 finish / night 看
            r["capped"] = prior
            continue
        cur["requests"].append({**r, "timeline": rel, "at": time.strftime("%Y-%m-%d %H:%M:%S"), "status": "pending"})
    REQ.write_text(json.dumps(cur, ensure_ascii=False, indent=1), encoding="utf-8")
    return rows


if __name__ == "__main__":
    if len(sys.argv) < 3 or sys.argv[1] != "scan":
        raise SystemExit(__doc__)
    for p in sys.argv[2:]:
        rows = record(Path(p))
        print(p, "→", [(r["shot"], r["fallback_reason"]) for r in rows] or "无")
