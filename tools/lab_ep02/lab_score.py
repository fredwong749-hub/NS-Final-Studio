"""
LAB（2026-10-31）：ep02 配方对照打分。只测像素，不看内容。

每条视频：
- 运动质检（ns_render.motion_qc，同 take.qc.motion）：mean / still / 定住 / verdict
- 卡顿（tools/motion_judder.analyze）：J4、J4_z、节奏 px/帧、jerk、stall、下半身鬼影 p95
- 中途硬切：相邻帧 HSV 直方图 Bhattacharyya 距离 > 0.35 且 灰度帧差 > max(8, 6×中位数) → 一刀
- 脸部红色漂移（tools/ep02_director/review 的 YuNet + 蓝发判林晚）：每 3 帧测一次
  face_a = 脸内 Lab a* 中位数；cheek_a95；cheek_red = 脸颊 a*≥25 像素占比；frame_red = 整帧红块占比
  漂移 = 最大值 − 开头 0.5 s 中位数
- 接触印样：12 帧 + 帧号 / 秒 → <out>/<name>_sheet.jpg

用法：.venv/Scripts/python.exe tools/lab_ep02/lab_score.py <out_dir> name=path.mp4 [...]
输出 <out_dir>/scores.json（追加 / 覆盖同名）、scores.md
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "ep02_director"))
sys.path.insert(0, str(ROOT / "services" / "render_router"))
import motion_judder as MJ  # noqa: E402
import review as R  # noqa: E402
from ns_render import motion_qc as MQ  # noqa: E402

FACES = None


def cuts(path: Path) -> list[dict]:
    fr = R.decode(path, None, None, 96, 168, "bt709")
    hs = [cv2.calcHist([cv2.cvtColor(f, cv2.COLOR_RGB2HSV)], [0, 1], None, [24, 16], [0, 180, 0, 256]) for f in fr]
    hs = [cv2.normalize(h, h).flatten() for h in hs]
    g = fr.mean(axis=3)
    d = np.abs(np.diff(g, axis=0)).mean(axis=(1, 2))
    med = float(np.median(d)) + 1e-6
    out = []
    for t in range(1, len(fr)):
        bh = cv2.compareHist(hs[t - 1], hs[t], cv2.HISTCMP_BHATTACHARYYA)
        if bh > 0.35 and d[t - 1] > max(8.0, 6 * med):
            out.append({"frame": t, "t": round(t / 24, 2), "bhatt": round(float(bh), 3), "diff": round(float(d[t - 1]), 1)})
    return out


def red(path: Path, step: int = 3) -> dict:
    global FACES
    if FACES is None:
        FACES = R.Faces()
    fr = R.decode(path, None, None, 768, 1344, "bt709")
    rows = []
    for i in range(0, len(fr), step):
        f = fr[i]
        row = {"f": i, "frame_red": R.red_blobs(f)["red_frac"]}
        fs = [fc for fc in FACES.detect(f, small=True) if float(fc[3]) >= 30]
        lab = R.label_faces(f, fs)
        fc = lab["lin_wan"] if "lin_wan" in lab else lab.get("other")
        if fc is not None:
            row["who"] = "lin_wan" if "lin_wan" in lab else "other"
            roi, ck = R.face_roi(fc, f.shape), R.cheek_roi(fc, f.shape)
            if roi:
                c = R.face_colour(f, roi)
                row.update(face_a=c["a"], face_L=c["L"])
            if ck:
                c = R.face_colour(f, ck)
                row.update(cheek_a95=c["a_p95"], cheek_red=c["red_frac"])
            if row["who"] == "lin_wan" and i % 9 == 0 and "lin_wan" in FACES.refs:
                try:
                    row["sface"] = R.QF.cosine(FACES.embed(f, fc), FACES.refs["lin_wan"])
                except Exception:  # noqa: BLE001
                    pass
        rows.append(row)
    res = {"n": len(rows), "face_frames": sum("face_a" in r for r in rows),
           "who": max({r.get("who") for r in rows if r.get("who")} or {None},
                      key=lambda w: sum(r.get("who") == w for r in rows)),
           "frame_red_max": round(max(r["frame_red"] for r in rows), 4)}
    head = [r for r in rows if r["f"] < 12]
    for k in ("face_a", "cheek_a95", "cheek_red"):
        v = [r[k] for r in rows if k in r]
        h = [r[k] for r in head if k in r] or v[:3]
        if v:
            res[k + "_start"] = round(float(np.median(h)), 2)
            res[k + "_max"] = round(float(np.max(v)), 2)
            res[k + "_p90"] = round(float(np.percentile(v, 90)), 2)
            res[k + "_drift"] = round(float(np.max(v) - np.median(h)), 2)
    sf = [r["sface"] for r in rows if "sface" in r]
    if sf:
        res["sface_med"] = round(float(np.median(sf)), 3)
        res["sface_min"] = round(float(np.min(sf)), 3)
    res["series"] = [{k: (round(v, 3) if isinstance(v, float) else v) for k, v in r.items()} for r in rows]
    return res


def sheet(path: Path, out: Path, n: int = 12):
    fr = R.decode(path, None, None, 192, 336, "bt709")
    idx = np.linspace(0, len(fr) - 1, n).astype(int)
    tiles = []
    for i in idx:
        t = np.ascontiguousarray(fr[i][..., ::-1])
        cv2.putText(t, f"{i} {i/24:.1f}s", (4, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 255, 255), 1)
        tiles.append(t)
    rows = [np.hstack(tiles[k:k + 6]) for k in range(0, n, 6)]
    cv2.imwrite(str(out), np.vstack(rows), [cv2.IMWRITE_JPEG_QUALITY, 85])


GATE = {"mean_min": 0.5, "J4_max": 1.3, "cheek_red_max": 0.25, "cuts_max": 0, "sface_min": 0.30}
_ASR = None


def asr(path: Path) -> dict:
    """SenseVoice 回听：文本 + 第一个字的时间（开口时刻）"""
    global _ASR
    import subprocess
    import tempfile
    for p in ("services/post", "packages/schema"):
        sys.path.insert(0, str(ROOT / p))
    from ns_post.tts import SenseVoiceAsr, load_voice_config
    if _ASR is None:
        _ASR = SenseVoiceAsr(load_voice_config(), num_threads=4)
    with tempfile.TemporaryDirectory() as td:
        w = Path(td) / "a.wav"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(path), "-vn", "-ac", "1", "-ar", "16000", str(w)], check=True)
        r = _ASR.transcribe_detail([w])[0]
    ts = r.get("timestamps") or []
    return {"text": r.get("text"), "onset_s": round(float(ts[0]), 2) if ts else None,
            "end_s": round(float(ts[-1]), 2) if ts else None}


def gate(s: dict) -> dict:
    """LAB 建议门槛（lab_recipes.md）：mean ≥ 0.5、J4 ≤ 1.3、cheek_red ≤ 0.25、0 硬切、SFace ≥ 0.30（有脸时）"""
    r = s["red"]
    fails = []
    if (s.get("mean") or 0) < GATE["mean_min"]:
        fails.append("动作不足")
    if s["J4"] > GATE["J4_max"]:
        fails.append("4 帧一顿")
    if (r.get("cheek_red_max") or 0) > GATE["cheek_red_max"]:
        fails.append("脸部泛红")
    if len(s["cuts"]) > GATE["cuts_max"]:
        fails.append("镜内硬切")
    if r.get("sface_med") is not None and r["sface_med"] < GATE["sface_min"]:
        fails.append("身份偏离")
    return {"pass": not fails, "fails": fails}


def score(name: str, path: Path, out_dir: Path, with_asr: bool = False) -> dict:
    mq = MQ.video_motion(path)
    mm = mq.get("metrics") or {}
    jm, _ = MJ.analyze(path)
    c = cuts(path)
    r = red(path)
    sheet(path, out_dir / f"{name}_sheet.jpg")
    return {"name": name, "file": str(path.relative_to(ROOT)).replace("\\", "/") if path.is_relative_to(ROOT) else str(path),
            "verdict": mq.get("verdict"), "labels": mq.get("labels"),
            "mean": mm.get("mean_diff"), "qc_cut_s": mm.get("cut_s"), "first_last": mm.get("first_last_diff"), "still": mm.get("still_frac"), "tail_s": mm.get("frozen_tail_s"),
            "head_s": mm.get("frozen_head_s"),
            "J4": round(jm["J4"], 3), "J4_z": round(jm["J4_z"], 2), "pace": jm["pace_px_per_frame"],
            "jerk": jm["jerk"], "stall": jm["stall_frac"], "ghost_p95": jm["ghost_low_p95"],
            "cuts": c, "red": r, **({"asr": asr(path)} if with_asr else {})}


def md(scores: dict) -> str:
    L = ["| 名称 | 判定 | mean | 静止 | 尾定 s | J4 | z | 节奏 | jerk | 鬼影p95 | 硬切 | 脸 | face_a 起→max | cheek_a95 起→max | cheek_red max | 红块max | SFace中位 | LAB 闸门 |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for k, s in sorted(scores.items()):
        r = s["red"]
        L.append(f"| {k} | {s['verdict']} | {s['mean']} | {s['still']} | {s['tail_s']} | {s['J4']} | {s['J4_z']} | "
                 f"{s['pace']} | {s['jerk']} | {s['ghost_p95']} | {len(s['cuts'])}"
                 f"{(' @' + ','.join(str(c['t']) for c in s['cuts'])) if s['cuts'] else ''} | {r.get('who')} {r.get('face_frames')}/{r.get('n')} | "
                 f"{r.get('face_a_start')}→{r.get('face_a_max')} | {r.get('cheek_a95_start')}→{r.get('cheek_a95_max')} | "
                 f"{r.get('cheek_red_max')} | {r.get('frame_red_max')} | {r.get('sface_med')} | "
                 f"{'PASS' if (s.get('gate') or gate(s))['pass'] else '/'.join((s.get('gate') or gate(s))['fails'])} |")
    return "\n".join(L) + "\n"


def main(argv):
    sys.stdout.reconfigure(encoding="utf-8")
    out = Path(argv[0])
    out.mkdir(parents=True, exist_ok=True)
    sj = out / "scores.json"
    scores = json.loads(sj.read_text(encoding="utf-8")) if sj.exists() else {}
    for a in [x for x in argv[1:] if x != "--asr"]:
        name, p = a.split("=", 1)
        p = Path(p) if Path(p).is_absolute() else ROOT / p
        try:
            scores[name] = score(name, p, out, "--asr" in argv)
            scores[name]["gate"] = gate(scores[name])
            s = scores[name]
            print(name, s["verdict"], "mean", s["mean"], "J4", s["J4"], "cuts", len(s["cuts"]),
                  "cheek_a95", s["red"].get("cheek_a95_start"), "->", s["red"].get("cheek_a95_max"),
                  "red", s["red"].get("cheek_red_max"), "sface", s["red"].get("sface_med"),
                  "gate", "PASS" if s["gate"]["pass"] else "/".join(s["gate"]["fails"]),
                  ("asr " + str(s["asr"])) if s.get("asr") else "", flush=True)
        except Exception as e:  # noqa: BLE001
            print(name, "ERROR", e, flush=True)
        sj.write_text(json.dumps(scores, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "scores.md").write_text(md(scores), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1:])
