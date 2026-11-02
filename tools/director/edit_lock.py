"""剪辑锁定（DIRECTOR，总调度 13:1x 派，CONSISTENCY_PLAN §5；规则 K-EDT-821）。decider = code。

项目方 13:1x：按每个镜头配背景音乐，一集拼起来音乐断层、不连贯。→ 集级 BGM 只在“剪辑锁定”后按整集情绪曲线出。
“剪辑锁定”= 下面全部满足（逐条可判定，写进 data/director/edit_lock/epNN.json）：
  L1 每镜都是视频（没有占位静帧 / 缺镜）                 timeline.shots[].placeholder / missing / kind
  L2 合成闸门通过（没有缺镜、没有台词溢出）               timeline.gates.verdict == pass
  L3 没有待重出的口型镜（K-EDT-805）                     data/director/redo_requests.json 本集 status=pending
  L4 画内对白没有 TTS 兜底                               timeline.h3_dialogue[].dialogue != tts_fallback
  L5 剪辑签名连续两版不变（镜头顺序 + 每镜时长 + 每镜视频文件）——同一份剪辑合成两次结果一致才算定稿
锁定后：写 BGM 请求 data/director/bgm_requests/epNN.json（锁定时间轴、场景段、每镜情绪强度、场景切换处交叉淡化秒数），
BGM10（tools/bgm）按它出整集一条连续 BGM；时间轴变了（签名变）锁定自动失效，BGM 需重出。

  python tools/director/edit_lock.py <timeline.json> [--script S]
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOCKS = ROOT / "data" / "director" / "edit_lock"
BGM_REQ = ROOT / "data" / "director" / "bgm_requests"
REDO = ROOT / "data" / "director" / "redo_requests.json"
SCRIPT = ROOT / "data" / "import" / "script_v2.json"
XFADE_S = 1.5   # 场景切换处 BGM 交叉淡化（K-EDT-821）


def _atomic(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def signature(tl: dict) -> str:
    """剪辑签名：镜头顺序 + 每镜时长（到帧）+ 每镜视频文件名"""
    fps = float(tl.get("fps") or 24)
    rows = [(int(s["index"]), round(float(s["duration_s"]) * fps), Path(str(s.get("file") or "")).name) for s in tl.get("shots") or []]
    return hashlib.sha256(json.dumps(rows).encode()).hexdigest()[:16]


def pending_redo(ep: int) -> list[str]:
    try:
        reqs = json.loads(REDO.read_text(encoding="utf-8")).get("requests") or []
    except (OSError, ValueError):   # arch-ok: 没有重出单文件 = 没有待重出（L3 通过），不是失败开放
        return []
    return sorted({r["shot"] for r in reqs if r.get("status", "pending") == "pending" and str(r.get("shot", "")).startswith(f"ep{ep:02d}-")})


def check(tl: dict, prev_sig: str | None) -> dict:
    ep = int(tl.get("episode") or 0)
    shots = tl.get("shots") or []
    conds = []
    bad = [s["shot"] for s in shots if s.get("placeholder") or s.get("missing") or s.get("kind") != "video"]
    conds.append({"id": "L1", "text": "每镜都是视频（无占位静帧 / 缺镜）", "pass": not bad and bool(shots), "value": bad})
    g = tl.get("gates") or {}
    conds.append({"id": "L2", "text": "合成闸门通过", "pass": g.get("verdict") == "pass", "value": g.get("verdict")})
    pr = pending_redo(ep)
    conds.append({"id": "L3", "text": "没有待重出的口型镜（K-EDT-805）", "pass": not pr, "value": pr})
    fb = [h.get("shot") for h in tl.get("h3_dialogue") or [] if h.get("dialogue") == "tts_fallback"]
    conds.append({"id": "L4", "text": "画内对白没有 TTS 兜底", "pass": not fb, "value": fb})
    sig = signature(tl)
    conds.append({"id": "L5", "text": "剪辑签名连续两版不变", "pass": prev_sig == sig, "value": {"sig": sig, "prev": prev_sig}})
    return {"episode": ep, "locked": all(c["pass"] for c in conds), "sig": sig, "conds": conds, "decider": "code",
            "rule": "K-EDT-821"}


def _intensity(text) -> int | None:
    m = re.search(r"强度\s*([0-3])", str(text or ""))
    return int(m.group(1)) if m else None


def bgm_request(tl: dict, script_shots: dict, sig: str) -> dict:
    """锁定时间轴 → BGM 请求：每镜起点 / 时长 / 人声 / 情绪强度，场景段与交叉淡化"""
    shots, scenes = [], []
    voiced = {int(x["shot"]) for x in tl.get("speech") or []}
    for s in tl.get("shots") or []:
        rec = script_shots.get(int(s["index"])) or {}
        sc = rec.get("scene_id") or "?"
        shots.append({"index": int(s["index"]), "start_s": float(s["start_s"]), "dur_s": float(s["duration_s"]),
                      "voice": int(s["index"]) in voiced, "intensity": _intensity(rec.get("music_cue")), "music_cue": rec.get("music_cue") or "",
                      "scene_id": sc})
        if not scenes or scenes[-1]["scene_id"] != sc:
            scenes.append({"scene_id": sc, "start_s": float(s["start_s"]), "end_s": float(s["start_s"]) + float(s["duration_s"])})
        else:
            scenes[-1]["end_s"] = float(s["start_s"]) + float(s["duration_s"])
    return {"schema": "nsfs.bgm_request/1", "episode": int(tl["episode"]), "edit_sig": sig, "duration_s": float(tl.get("duration_s") or 0),
            "shots": shots, "scenes": scenes, "crossfade_s": XFADE_S if len(scenes) > 1 else 0.0,
            "rule": "K-EDT-821：整集一条连续 BGM，按 shots[].intensity 情绪曲线起伏，场景切换处交叉淡化；镜头级不配乐（K-EDT-820）",
            "at": time.strftime("%Y-%m-%d %H:%M:%S")}


def run(tl_path: Path, script: Path = SCRIPT) -> dict:
    tl = json.loads(tl_path.read_text(encoding="utf-8"))
    ep = int(tl.get("episode") or 0)
    lp = LOCKS / f"ep{ep:02d}.json"
    prev = json.loads(lp.read_text(encoding="utf-8")) if lp.exists() else {}
    r = check(tl, prev.get("last_sig"))
    hist = (prev.get("history") or [])[-19:] + [{"sig": r["sig"], "timeline": str(tl_path), "at": time.strftime("%Y-%m-%d %H:%M:%S"),
                                                 "locked": r["locked"]}]
    out = {**r, "last_sig": r["sig"], "timeline": str(tl_path), "history": hist}
    if r["locked"]:
        d = json.loads(script.read_text(encoding="utf-8"))
        e = next((x for x in d.get("episodes") or [] if int(x.get("number")) == ep), {})
        req = bgm_request(tl, {int(s["index"]): s for s in e.get("shots") or []}, r["sig"])
        _atomic(BGM_REQ / f"ep{ep:02d}.json", req)
        out["bgm_request"] = str(BGM_REQ / f"ep{ep:02d}.json")
    _atomic(lp, out)
    return out


def locked_timing(ep: int) -> dict | None:
    """BGM10 用：本集已锁定 → BGM 请求（锁定时间轴）；没锁定 → None"""
    p = BGM_REQ / f"ep{ep:02d}.json"
    lk = LOCKS / f"ep{ep:02d}.json"
    try:
        req, lock = json.loads(p.read_text(encoding="utf-8")), json.loads(lk.read_text(encoding="utf-8"))
    except (OSError, ValueError):   # arch-ok: 没有锁定记录 = 未锁定（调用方等锁定，不出 BGM）
        return None
    return req if lock.get("locked") and lock.get("sig") == req.get("edit_sig") else None


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    sp = Path(sys.argv[sys.argv.index("--script") + 1]) if "--script" in sys.argv else SCRIPT
    res = run(Path(sys.argv[1]), sp)
    print(json.dumps({k: res[k] for k in ("episode", "locked", "sig")} | {"fails": [c["id"] for c in res["conds"] if not c["pass"]]},
                     ensure_ascii=False))
