"""成片“好莱坞观感分”（DIRECTOR loop，总调度 fredw-2b 派，2026-11-02；规则 K-REV-801–804）。

项目方 11-02 00:4x 原话：“我要全部系统化，出一个 Hollywood level 的、画面非常漂亮的短剧。”（docs/master/HOLLYWOOD_PLAN.md §1D）

只评技术和观感，不评剧本内容。四大项 15 小项，每小项 = 5 条可核对条件（个别 3–4 条），
小项分 = 5 × 通过条数 / 测到条数；没测到的条件记“未测”，不计入分母，测到比例单独给出（coverage）。
整集分（/50）= 15 小项平均 × 10，口径与写作分“50 over 50”一致。

数据来源（复用，不另起炉灶）：
- tools/ep02_director/review.py（DIR 审片：逐镜运动 / J4 / 脸色 / 身份 SFace / 嘴部同步 / 切点 / ebur128 响度）
- timeline.json（ns_post.assemble 产出：占位静帧、TTS 兜底、ASR 回听 CER、J/L-cut、BGM cue、room tone、音效层）
- 本工具自己的抽帧（2 fps，270×480）：曝光 / 高光溢出 / 死黑 / 对比、整帧 Laplacian、黑边、主脸位置
- ns_qc.gaze_mp（MediaPipe 虹膜，看镜头旁证）、tools/ep02_iter/cut_check.hist_cuts（镜内意外硬切）
- 本地看图模型（ns_agent.vqa，口径 B；可选 --vlm，走缓存；图片只进自家模型 K-REV-V01）

用法（项目 .venv）：
  python tools/director/film_score.py score <成片.mp4> [--timeline T] [--name ep01_v2] [--vlm] [--note 说明]
  python tools/director/film_score.py page                 # 重建本地页面 data/review_pages/film_score/index.html
  python tools/director/film_score.py lowest [--name X]    # RSI：全局最低小项（多集取平均）
输出：data/film_score/<name>.json（并复制为 data/film_score/epNN.json = 该集最新一次）
"""
from __future__ import annotations

import os as _os
for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):   # K-OPS-V13：限线程
    _os.environ[_k] = _os.environ.get("NS_SCORE_THREADS", "4")

import argparse
import html
import json
import re
import shutil
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
for p in ("tools", "tools/ep02_director", "tools/ep02_iter", "packages/qc", "services/agent"):
    sys.path.insert(0, str(ROOT / p))

import cv2  # noqa: E402

cv2.setNumThreads(int(_os.environ.get("NS_SCORE_THREADS", "4")))

OUT = ROOT / "data" / "film_score"
PAGE = ROOT / "data" / "review_pages" / "film_score"
SCHEMA = "nsfs.film_score/1"
RUBRIC_VERSION = "fs-v1-2026-11-02"

# ---- 阈值（来源见各条 src；改了同步 knowledge/rules/director.yaml K-REV-801–804）----
T = {
    "face_cy": (0.15, 0.55),        # 主脸中心 y / 画面高：竖屏主体在上 1/3–1/2（camera_language.md §2 K-WRT-107）
    "face_edge_margin": 0.01,       # 脸框离画框 <1% 视为被切
    "face_L": (45.0, 78.0),         # 主光落在脸上：脸内 L*（review.py colour.face_L，cv2 Lab 0–100）初值，待标定
    "clip_hi": 0.01,                # luma ≥250 像素占比 p95 ≤1%
    "crush_lo": {"day": 0.03, "night": 0.25},   # luma ≤5 像素占比 p95；夜景允许大块暗部（初值，待标定）
    "contrast_std": (38.0, 85.0),   # 灰度标准差（0–255）中位
    "scene_dE": 6.0,                # 同场相邻镜整帧平均色 ΔE76（rubric.md ⑦ 及格线）
    "face_dE": 6.0, "id_cos": 0.65, "cheek_drift": 6.0,
    "face_lap": 60.0,               # 脸内 Laplacian 方差中位（rubric.md ③ 参考线）
    "src_w": 1080,
    "asl": (2.0, 4.0), "max_cut": 4.5, "cut_cv": 0.25, "ep_len": (60.0, 120.0),
    "still_frac": 0.5, "frozen_tail": 0.5, "j4": 1.3, "j4_z": 3.0,
    "cut_dE_same_scene": 12.0, "audio_jump": 10.0, "room_floor": -60.0,
    "lufs": (-15.0, -13.0), "tp": -1.0, "lra": (4.0, 11.0), "shot_I_spread": 6.0,
    "cer": 0.15, "speech_over_bed_db": 2.0, "max_tempo": 1.2,
    "lip_corr": 0.3, "lip_lag": 0.12, "lip_good_frac": 0.7,
    "bgm_cover": 0.8, "bgm_duck_db": 9.0, "sfx_per_10s": 1.0,
}

ITEMS = {   # id → (大项, 名称)
    "P1": ("画面", "构图"), "P2": ("画面", "光线"), "P3": ("画面", "跨镜一致性"), "P4": ("画面", "清晰度"),
    "A1": ("表演", "视线"), "A2": ("表演", "表情与表演"), "A3": ("表演", "口型"),
    "E1": ("剪辑", "节奏"), "E2": ("剪辑", "连贯"), "E3": ("剪辑", "转场"), "E4": ("剪辑", "开头钩子"),
    "S1": ("声音", "对白清晰度"), "S2": ("声音", "响度"), "S3": ("声音", "配乐"), "S4": ("声音", "音效"),
}
CATS = ("画面", "表演", "剪辑", "声音")


def rel(p) -> str:
    try:
        return str(Path(p).resolve().relative_to(ROOT)).replace("\\", "/")
    except (ValueError, OSError):
        return str(p)


def C(cid: str, text: str, ok, value=None, src: str = "") -> dict:
    """一条可核对条件：ok = True / False / None（未测）"""
    if ok is not None:
        ok = bool(ok)
    if isinstance(value, float):
        value = round(value, 3)
    return {"id": cid, "text": text, "pass": ok, "value": value, "src": src}


def item_score(conds: list[dict]) -> dict:
    m = [c for c in conds if c["pass"] is not None]
    s = round(5.0 * sum(c["pass"] for c in m) / len(m), 2) if m else None
    return {"score": s, "measured": len(m), "total": len(conds), "conds": conds}


# ---------------------------------------------------------------- 抽帧测量
def frame_pass(video: Path, shots: list[dict], faces, fdir: Path, fps_s: float = 2.0) -> dict:
    """2 fps 抽帧：每镜曝光 / 对比 / Lab 均色 / Laplacian / 黑边 / 主脸位置；每镜存首帧 + 中帧 jpg（看图模型、gaze 用）"""
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    step = max(1, int(round(fps / fps_s)))
    keep = {}
    for s in shots:
        a, b = int(round(s["start_s"] * fps)), int(round((s["start_s"] + s["duration_s"]) * fps)) - 1
        keep[max(0, a + 1)] = (s["shot"], "first")
        keep[(a + b) // 2] = (s["shot"], "mid")
        k = max(0, b - 2)
        keep.setdefault(k, (s["shot"], "last"))
    rows = []
    fdir.mkdir(parents=True, exist_ok=True)
    saved = {}
    i = 0
    while i < n:
        ok = cap.grab()
        if not ok:
            break
        if i % step == 0 or i in keep:
            ok, fr = cap.retrieve()
            if not ok:
                break
            t = i / fps
            if i in keep:
                sid, tag = keep[i]
                p = fdir / f"{sid}_{tag}.jpg"
                cv2.imwrite(str(p), fr, [cv2.IMWRITE_JPEG_QUALITY, 92])
                saved.setdefault(sid, {})[tag] = str(p)
            sm = cv2.resize(fr, (270, 480), interpolation=cv2.INTER_AREA)
            g = cv2.cvtColor(sm, cv2.COLOR_BGR2GRAY)
            lab = cv2.cvtColor(sm.astype(np.float32) / 255.0, cv2.COLOR_BGR2Lab)
            rowdark = (g.mean(1) < 16) & (g.std(1) < 4)     # 真黑边 = 整行又黑又平（夜景暗窗不算）
            bar = 0
            for arr in (rowdark, rowdark[::-1]):
                k = 0
                while k < len(arr) and arr[k]:
                    k += 1
                bar = max(bar, k / len(arr))
            mid = cv2.resize(fr, (360, 640), interpolation=cv2.INTER_AREA)
            fs = faces.detect(cv2.cvtColor(mid, cv2.COLOR_BGR2RGB)) if faces.ok else []
            face = None
            if fs is not None and len(fs):
                f = max(fs, key=lambda x: x[2] * x[3])
                x, y, w, h = [float(v) for v in f[:4]]
                face = {"cx": (x + w / 2) / 360, "cy": (y + h / 2) / 640, "h": h / 640,
                        "cut": x < 3.6 or y < 6.4 or x + w > 356.4 or y + h > 633.6}
            rows.append({"t": t, "L": float(lab[..., 0].mean()), "a": float(lab[..., 1].mean()),
                         "b": float(lab[..., 2].mean()), "std": float(g.std()),
                         "hi": float((g >= 250).mean()), "lo": float((g <= 5).mean()),
                         "lap": float(cv2.Laplacian(g, cv2.CV_64F).var()), "bar": bar, "face": face})
        i += 1
    cap.release()
    per = {}
    for s in shots:
        a, b = s["start_s"], s["start_s"] + s["duration_s"]
        rs = [r for r in rows if a <= r["t"] < b]
        if not rs:
            continue
        fc = [r["face"] for r in rs if r["face"]]
        per[s["shot"]] = {
            "n": len(rs), "L": float(np.median([r["L"] for r in rs])), "a": float(np.median([r["a"] for r in rs])),
            "b": float(np.median([r["b"] for r in rs])), "std": float(np.median([r["std"] for r in rs])),
            "hi_p95": float(np.percentile([r["hi"] for r in rs], 95)), "lo_p95": float(np.percentile([r["lo"] for r in rs], 95)),
            "lap": float(np.median([r["lap"] for r in rs])), "bar_max": float(max(r["bar"] for r in rs)),
            "face_frac": len(fc) / len(rs),
            "face_cy_ok": (sum(T["face_cy"][0] <= f["cy"] <= T["face_cy"][1] for f in fc) / len(fc)) if fc else None,
            "face_cut_frac": (sum(f["cut"] for f in fc) / len(fc)) if fc else None,
            "first_has_face": bool(rs[0]["face"]), "frames": saved.get(s["shot"], {})}
    return {"fps": fps, "per_shot": per, "n_samples": len(rows)}


def gaze_pass(per: dict) -> dict:
    try:
        from ns_agent.vqa import contract as VC
    except Exception as e:  # noqa: BLE001
        return {"error": f"gaze 不可用：{e}"}
    out = {}
    for sid, d in per.items():
        res = []
        for tag in ("first", "mid"):
            p = (d.get("frames") or {}).get(tag)
            if p:
                g = VC.gaze_mp(p)
                if g is None:
                    return {"error": "mediapipe 不可用"}
                res += [bool(x.get("camera_gaze")) for x in g]
        out[sid] = {"faces": len(res), "camera": sum(res)}
    return out


def speech_bed(video: Path, timeline: dict) -> dict:
    """对白 / 旁白时段 vs 非人声时段的 RMS 差（dB）：人声是否压在配乐 / 环境声之上（代理，混音里不分轨）"""
    import review as RV
    sr = 16000
    a = RV.audio_mono(video, sr)
    if a.size == 0:
        return {}
    win = sr // 10
    nw = a.size // win
    db = 20 * np.log10(np.sqrt((a[: nw * win].reshape(nw, win) ** 2).mean(1)) + 1e-9)
    sp = np.zeros(nw, bool)
    for x in timeline.get("speech") or []:
        sp[int(x["start_s"] * 10): int(np.ceil(x["end_s"] * 10))] = True
    if sp.sum() < 3 or (~sp).sum() < 3:
        return {"speech_db": None}
    s_db, b_db = float(np.median(db[sp])), float(np.median(db[~sp]))
    tail = float(np.mean(db[-10:])) if nw > 20 else None
    return {"speech_db": round(s_db, 1), "bed_db": round(b_db, 1), "diff_db": round(s_db - b_db, 1),
            "tail_1s_db": round(tail, 1) if tail is not None else None, "mean_db": round(float(np.mean(db)), 1)}


def inner_cuts(video: Path, fps: float, planned: list[float]) -> list[float]:
    import cut_check as CC
    hc = CC.hist_cuts(video, fps)
    return [t for t in hc if all(abs(t - p) > 0.25 for p in planned)]


# ---------------------------------------------------------------- 看图模型
VLM_PROMPT_NOTE = ("【成片评分抽查】以下是成片中一个镜头的若干帧（按时间顺序）。原文镜头描述附后，"
                   "只按清单判断画面缺陷，不评价剧情。")


def shot_prompt(sid: str, origin: str | None) -> str:
    pdir = ROOT / "data/pipeline/runs/series10_v1/video/prompts"
    m = re.search(r"\b(v\d+|s\d+|mot|alt|r\d+)\b", origin or "")
    cands = []
    if m:
        cands.append(pdir / f"{sid}.{m.group(1)}.txt")
    cands += sorted(pdir.glob(f"{sid}.*.txt"))
    for c in cands:
        if c.is_file():
            return c.read_text(encoding="utf-8")[:3000]
    try:
        from ns_agent.vqa import continuity as CO
        r = CO.shot_rec(sid) or {}
        return str(r.get("motion_prompt") or r.get("img_prompt") or "")
    except Exception:  # noqa: BLE001
        return ""


def vlm_pass(per: dict, tl_shots: dict, wait_s: float = 900) -> dict:
    from ns_agent.vqa import client as VC
    from ns_agent.vqa import rubric as VR
    out = {}
    for sid, d in per.items():
        if tl_shots.get(sid, {}).get("placeholder"):
            out[sid] = {"skipped": "占位静帧"}
            continue
        frames = [d["frames"][k] for k in ("first", "mid", "last") if d["frames"].get(k)]
        if not frames:
            continue
        req = VR.build_video_request(frames, VLM_PROMPT_NOTE + "\n" + shot_prompt(sid, tl_shots.get(sid, {}).get("origin")), None)
        v = VC._finish(req, VC.generate(req, wait_s=wait_s, label=f"film_score {sid}"), "video", sid)
        out[sid] = {"defects": v.get("defects") or [], "unsure": v.get("unsure") or [], "error": v.get("error"),
                    "checks": {k: c.get("s") for k, c in (v.get("checks") or {}).items()},
                    "evidence": {k: c.get("e") for k, c in (v.get("checks") or {}).items() if c.get("s") == "defect"},
                    "cached": v.get("cached"), "seconds": v.get("seconds")}
        print(f"[vlm] {sid} defects={out[sid]['defects']} err={out[sid]['error']}", flush=True)
    return out


def vlm_cond(vlm: dict | None, keys: tuple, cid: str, text: str) -> dict:
    if not vlm:
        return C(cid, text, None, "未测（没跑看图模型）", "ns_agent.vqa")
    rows = {k: v for k, v in vlm.items() if not v.get("skipped") and not v.get("error")}
    if not rows:
        return C(cid, text, None, "未测（看图模型无有效判定）", "ns_agent.vqa")
    bad = {sid: [k for k in keys if k in v["defects"]] for sid, v in rows.items()}
    bad = {k: v for k, v in bad.items() if v}
    return C(cid, text, not bad, bad or f"{len(rows)} 镜无缺陷", "ns_agent.vqa（口径 B）")


# ---------------------------------------------------------------- 打分
V7_OPEN_FRAC = 0.3     # 总调度 11-02 定 V7 口型口径（已通知 VQAGATE）：台词段相关 ≥ corr_min，或张嘴帧占比 ≥0.3 且开合幅度达标


def v7_pass(v7: dict | None) -> bool | None:
    """V7 口型按 11-02 口径判：VQAGATE 新版输出带 caliber 字段时直接用它的 status；旧输出按口径重算——
    相关 ≥ th.corr_min（有台词时段就是台词段相关），或 open_frac ≥ 0.3 且开合幅度（aperture_p90）≥ th.amp_min（缺省 th.open_thr）。
    人工标签（总调度）：S4ffb s102 过、S4calm s101 过、r18 三条不过。未测 / 闭嘴模式 → None"""
    if not v7 or v7.get("status") == "未测" or v7.get("mode") == "closed":
        return None
    if v7.get("caliber"):
        return v7.get("status") == "通过"
    th = v7.get("th") or {}
    if v7.get("corr") is not None and v7["corr"] >= float(th.get("corr_min", 0.3)):
        return True
    amp = v7.get("aperture_p90")
    return bool((v7.get("open_frac") or 0) >= V7_OPEN_FRAC and amp is not None
                and amp >= float(th.get("amp_min", th.get("open_thr", 0.035))))


def v7_for(tl_shot: dict) -> tuple[dict | None, str | None]:
    """成片里用的那一版视频的 V7 结果：origin 里的变体名 → data/pipeline/runs/series10_v1/video/scores/<镜>__<变体>.json"""
    sid = tl_shot.get("shot") or ""
    m = re.search(re.escape(sid) + r"\s+(\S+)", tl_shot.get("origin") or "")
    if not m:
        return None, None
    f = ROOT / "data/pipeline/runs/series10_v1/video/scores" / f"{sid}__{m.group(1)}.json"
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, rel(f)
    return d.get("v7") or (d.get("score") or {}).get("v7"), rel(f)


def cut_list(timeline: dict) -> list[float]:
    """实际刀长（含 assemble 拆刀 pieces）"""
    out = []
    for s in timeline["shots"]:
        ps = s.get("pieces") or []
        if len(ps) > 1:
            out += [float(p[1]) - float(p[0]) for p in ps]
        else:
            out.append(float(s["duration_s"]))
    return out


def planned_cuts(timeline: dict) -> list[float]:
    ts = []
    for s in timeline["shots"]:
        ts.append(float(s["start_s"]))
        for p in (s.get("pieces") or [])[1:]:
            ts.append(float(s["start_s"]) + float(p[0]))
    return ts


def scene_of(sid: str) -> str | None:
    try:
        from ns_agent.vqa import continuity as CO
        return (CO.shot_rec(sid) or {}).get("scene_id")
    except Exception:  # noqa: BLE001
        return None


def time_of_day(sid: str) -> str:
    """剧本 scene_id / 首帧提示词里有 夜 / night / 深夜 → night，否则 day（调色 LUT 选择同一口径，post_pass.py）"""
    try:
        from ns_agent.vqa import continuity as CO
        r = CO.shot_rec(sid) or {}
    except Exception:  # noqa: BLE001
        r = {}
    txt = f"{r.get('scene_id') or ''} {r.get('img_prompt') or ''}"
    return "night" if re.search(r"night|夜|深夜|夜晚|傍晚|dusk", txt, re.I) else "day"


def de76(x, y) -> float:
    return float(np.sqrt(sum((a - b) ** 2 for a, b in zip(x, y))))


def score_all(rep: dict, tl: dict, fp: dict, gz: dict, sb: dict, vlm: dict | None, inner: list[float]) -> dict:
    shots = rep["shots"]
    per = fp["per_shot"]
    tls = {s["shot"]: s for s in tl["shots"]}
    vid_shots = [s for s in shots if not tls.get(s["shot"], {}).get("placeholder")]
    items = {}
    RV = "review.py"

    # ---- P1 构图
    cy = [d["face_cy_ok"] for d in per.values() if d.get("face_cy_ok") is not None]
    cutf = [d["face_cut_frac"] for d in per.values() if d.get("face_cut_frac") is not None]
    scales = [s["scale"] for s in shots]
    diff_adj = [a != b for a, b in zip(scales, scales[1:])]
    bars = {k: d["bar_max"] for k, d in per.items() if d["bar_max"] > 0.02}
    items["P1"] = item_score([
        C("P1.1", "主脸中心落在画面上部 15–55% 的抽样帧 ≥80%（竖屏主体在上 1/3–1/2）", (np.mean(cy) >= 0.8) if cy else None,
          float(np.mean(cy)) if cy else "无脸", "抽帧 YuNet"),
        C("P1.2", "主脸被画框切到的抽样帧 ≤10%", (np.mean(cutf) <= 0.1) if cutf else None,
          float(np.mean(cutf)) if cutf else "无脸", "抽帧 YuNet"),
        C("P1.3", "相邻镜景别不同的切点 ≥70%（景别交替，rubric ⑤）", (np.mean(diff_adj) >= 0.7) if diff_adj else None,
          {"scales": scales, "diff_frac": round(float(np.mean(diff_adj)), 2) if diff_adj else None}, RV),
        C("P1.4", "无黑边 / 画框（上下黑带 ≤2% 画高）", not bars, bars or "无", "抽帧行均值"),
        vlm_cond(vlm, ("framing_mismatch", "collage_or_ref_leak"), "P1.5", "看图模型：无景别不符 / 拼图画框"),
    ])
    # ---- P2 光线
    fL = {s["shot"]: s["colour"].get("face_L") for s in vid_shots if s["colour"].get("face_L") is not None}
    tod = {k: time_of_day(k) for k in per}
    items["P2"] = item_score([
        C("P2.1", f"主光落在脸上：每镜脸内 L* 在 {T['face_L'][0]:.0f}–{T['face_L'][1]:.0f}（暗场也看得清脸，不过曝）",
          all(T["face_L"][0] <= v <= T["face_L"][1] for v in fL.values()) if fL else None, {k: round(v, 1) for k, v in fL.items()}, RV + " colour.face_L"),
        C("P2.2", "高光溢出（灰度 ≥250）p95 ≤1%", all(d["hi_p95"] <= T["clip_hi"] for d in per.values()),
          {k: round(d["hi_p95"], 4) for k, d in per.items() if d["hi_p95"] > T["clip_hi"]} or "全部 ≤1%", "抽帧"),
        C("P2.3", "死黑（灰度 ≤5）p95 ≤ 日景 3% / 夜景 25%（暗部有层次）",
          all(d["lo_p95"] <= T["crush_lo"][tod[k]] for k, d in per.items()),
          {k: f"{d['lo_p95']:.3f}（{tod[k]}）" for k, d in per.items() if d["lo_p95"] > T["crush_lo"][tod[k]]} or "全部达标", "抽帧 + 剧本时段"),
        C("P2.4", f"明暗反差（灰度标准差中位）在 {T['contrast_std'][0]}–{T['contrast_std'][1]}，有层次不发灰",
          all(T["contrast_std"][0] <= d["std"] <= T["contrast_std"][1] for d in per.values()),
          {k: round(d["std"], 1) for k, d in per.items()}, "抽帧"),
        vlm_cond(vlm, ("lighting_time",), "P2.5", "看图模型：时段 / 光线与原文不矛盾"),
    ])
    # ---- P3 跨镜一致
    pairs = []
    for a, b in zip(shots, shots[1:]):
        sa, sb_ = scene_of(a["shot"]), scene_of(b["shot"])
        if a["shot"] in per and b["shot"] in per and sa and sa == sb_:
            pa, pb = per[a["shot"]], per[b["shot"]]
            pairs.append((f"{a['shot']}→{b['shot']}", de76((pa["L"], pa["a"], pa["b"]), (pb["L"], pb["a"], pb["b"]))))
    xde = [v for d in (rep.get("cross") or {}).get("face_dE_to_char_median", {}).values() for v in d.values()]
    xid = {k: v for d in (rep.get("cross") or {}).get("identity_cos_to_char_mean", {}).values() for k, v in d.items()}
    drifts = {s["shot"]: s["colour"].get("cheek_a_max_drift") for s in shots if s["colour"].get("cheek_a_max_drift") is not None}
    items["P3"] = item_score([
        C("P3.1", f"同场相邻镜整帧平均色 ΔE76 ≤{T['scene_dE']}（同一场戏颜色一致）",
          all(v <= T["scene_dE"] for _, v in pairs) if pairs else None, {k: round(v, 1) for k, v in pairs} or "无同场相邻镜", "抽帧 Lab"),
        C("P3.2", f"同一角色跨镜脸部平均色 ΔE ≤{T['face_dE']}", (max(xde) <= T["face_dE"]) if xde else None,
          max(xde) if xde else "未测", RV + " cross"),
        C("P3.3", f"同一角色跨镜身份余弦（对本人全集平均脸）≥{T['id_cos']}", (min(xid.values()) >= T["id_cos"]) if xid else None,
          {k: v for k, v in xid.items() if v < T["id_cos"]} or (min(xid.values()) if xid else "未测"), RV + " SFace"),
        C("P3.4", f"镜内脸颊 a* 漂移 ≤{T['cheek_drift']}（无突然泛红 / 发绿）",
          all(abs(v) <= T["cheek_drift"] for v in drifts.values()) if drifts else None,
          {k: v for k, v in drifts.items() if abs(v) > T["cheek_drift"]} or "全部达标", RV),
        vlm_cond(vlm, ("continuity_break", "temporal_outfit", "temporal_identity"), "P3.5", "看图模型：无跨镜 / 片内服装发型身份跳变"),
    ])
    # ---- P4 清晰度
    ph = [s["shot"] for s in tl["shots"] if s.get("placeholder") or s.get("kind") == "still"]
    srcw = {s["shot"]: (2160 if s.get("file_4k") else (s.get("source_size") or [0])[0]) for s in tl["shots"] if not s.get("placeholder")}
    upsc = {s["shot"]: s.get("upscaled") for s in tl["shots"] if s.get("upscaled")}
    fl = {s["shot"]: s["identity"].get("face_sharp_lapvar_med") for s in vid_shots if s["identity"].get("face_sharp_lapvar_med")}
    laps = {k: d["lap"] for k, d in per.items() if k not in ph}
    medlap = float(np.median(list(laps.values()))) if laps else None
    items["P4"] = item_score([
        C("P4.1", "没有占位静帧 / 缺镜（每镜都是视频）", not ph, ph or "无", "timeline shots[].placeholder"),
        C("P4.2", f"源画面宽 ≥{T['src_w']}（原片或放大版，不是 540 代理）",
          all((w or 0) >= T["src_w"] or upsc.get(k) for k, w in srcw.items()) if srcw else None, {**srcw, **({"upscaled": upsc} if upsc else {})},
          "timeline source_size / upscaled"),
        C("P4.3", f"每镜脸内 Laplacian 方差中位 ≥{T['face_lap']:.0f}", all(v >= T["face_lap"] for v in fl.values()) if fl else None,
          {k: round(v, 1) for k, v in fl.items()}, RV),
        C("P4.4", "没有一镜整帧清晰度低于全集中位的 50%（无单镜发糊）",
          all(v >= 0.5 * medlap for v in laps.values()) if laps else None,
          {k: round(v, 1) for k, v in laps.items()}, "抽帧 Laplacian"),
        vlm_cond(vlm, ("low_resolution", "artifact", "face_artifact"), "P4.5", "看图模型：无低清 / 坏块 / 五官畸形"),
    ])
    # ---- A1 视线
    gzv = {k: v for k, v in (gz or {}).items() if isinstance(v, dict) and v.get("faces")}
    cam = {k: v["camera"] for k, v in gzv.items() if v["camera"]}
    items["A1"] = item_score([
        vlm_cond(vlm, ("eye_contact",), "A1.1", "看图模型：没有人看镜头（MASTER_PICTURE 已定：所有画面不看镜头）"),
        vlm_cond(vlm, ("first_frame_stare",), "A1.2", "看图模型：开头没有盯镜头停顿"),
        C("A1.3", "MediaPipe 虹膜：首帧 + 中帧所有脸都不是“疑似看镜头”", (not cam) if gzv else None,
          cam or (f"{sum(v['faces'] for v in gzv.values())} 张脸均离轴" if gzv else (gz or {}).get("error", "无脸")), "ns_qc.gaze_mp"),
    ])
    # ---- A2 表情与表演
    st = {s["shot"]: s["motion"]["still_frac"] for s in vid_shots}
    tails = {s["shot"]: s["motion"]["frozen_tail_s"] for s in vid_shots}
    items["A2"] = item_score([
        vlm_cond(vlm, ("blank_expression",), "A2.1", "看图模型：多人镜第二人有表情 / 有眼神"),
        vlm_cond(vlm, ("posed_stiff",), "A2.2", "看图模型：没有摆拍站桩"),
        vlm_cond(vlm, ("plastic_doll",), "A2.3", "看图模型：没有塑料 / 蜡像脸"),
        C("A2.4", f"静止占比 <{T['still_frac']:.0%} 的视频镜 ≥90%（人在演，不是幻灯片）",
          (np.mean([v < T["still_frac"] for v in st.values()]) >= 0.9) if st else None, {k: round(v, 2) for k, v in st.items()}, RV),
        C("A2.5", f"没有镜头结尾定住 ≥{T['frozen_tail']} s", all(v < T["frozen_tail"] for v in tails.values()) if tails else None,
          {k: v for k, v in tails.items() if v >= T["frozen_tail"]} or "无", RV),
    ])
    # ---- A3 口型（含总调度 11-02 规则 K-EDT-805：画内对白 TTS 兜底 = 口型与成片声音不一致）
    tts_fb = [f"S{h['shot']}（{h.get('fallback_reason')}）" for h in tl.get("h3_dialogue") or [] if h.get("dialogue") == "tts_fallback"]
    dia_shots = {x["shot"] for x in tl.get("speech") or [] if x.get("kind") == "dialogue"}
    dia_still = [s["shot"] for s in tl["shots"] if s["index"] in dia_shots and (s.get("placeholder") or s.get("kind") == "still")]
    syn = [x for s in shots for x in s["lip_sync"]]
    meas = [x for x in syn if "corr_best" in x]
    good = [x for x in meas if x["corr_best"] >= T["lip_corr"] and abs(x["best_lag_s"]) <= T["lip_lag"]]
    v7r, v7f = {}, {}
    for s_ in tl["shots"]:
        if s_["index"] in dia_shots and not (s_.get("placeholder") or s_.get("kind") == "still"):
            v, f = v7_for(s_)
            ok = v7_pass(v)
            if ok is not None:
                v7r[s_["shot"]], v7f[s_["shot"]] = ok, f
    items["A3"] = item_score([
        C("A3.1", "画内对白没有 TTS 兜底（兜底 = 口型与成片声音不一致，K-EDT-805 送回重出）", not tts_fb, tts_fb or "无",
          "timeline h3_dialogue[].dialogue"),
        C("A3.2", "对白镜都是视频（不是静帧配音）", not dia_still, dia_still or "无", "timeline shots + speech"),
        C("A3.3", "画内对白镜 V7 口型通过 ≥70%（口径 11-02：台词段相关 ≥0.30，或张嘴帧占比 ≥0.3 且开合幅度达标；没有 V7 时退回 DIR 嘴部相关代理）",
          (sum(v7r.values()) / len(v7r) >= T["lip_good_frac"]) if v7r else ((len(good) / len(meas) >= T["lip_good_frac"]) if meas else None),
          ({"v7": v7r, "files": v7f} if v7r else ({"proxy_good": len(good), "proxy_measured": len(meas)} if meas else "无可测句")),
          "scores/<镜>__<变体>.json v7（VQAGATE）" if v7r else RV + " lip_sync（代理）"),
        C("A3.4", "说话人的脸在对白期间入画（可测句 / 全部对白句 ≥70%）",
          (len(meas) / len(syn) >= 0.7) if syn else None, {"measured": len(meas), "lines": len(syn)} if syn else "无对白", RV),
    ])
    # ---- E1 节奏
    cuts = cut_list(tl)
    dur = float(tl.get("duration_s") or rep.get("duration_s") or sum(cuts))
    cv = float(np.std(cuts) / np.mean(cuts)) if cuts else 0
    items["E1"] = item_score([
        C("E1.1", f"集长 {T['ep_len'][0]:.0f}–{T['ep_len'][1]:.0f} s（项目方已定 D-SCR-08）", T["ep_len"][0] <= dur <= T["ep_len"][1], dur, "timeline duration_s"),
        C("E1.2", f"平均每刀 {T['asl'][0]}–{T['asl'][1]} s（竖屏短剧，rubric ⑤）", T["asl"][0] <= float(np.mean(cuts)) <= T["asl"][1],
          float(np.mean(cuts)), "timeline shots + pieces"),
        C("E1.3", f"最长单刀 ≤{T['max_cut']} s（post.edit_rules.max_shot_s）", max(cuts) <= T["max_cut"] + 0.05, max(cuts), "timeline"),
        C("E1.4", f"刀长变异系数 ≥{T['cut_cv']}（节奏随情绪有快有慢，不是一镜一个长度）", cv >= T["cut_cv"], cv, "timeline"),
        C("E1.5", "没有“画面定住等台词”的镜（静止占比 ≥50% 的镜 = 0）", all(v < T["still_frac"] for v in st.values()) and not ph,
          ({k: round(v, 2) for k, v in st.items() if v >= T["still_frac"]} or {}) | ({"占位静帧": ph} if ph else {}) or "无", RV),
    ])
    # ---- E2 连贯
    j4bad = {s["shot"]: (s["motion"]["J4"], s["motion"]["J4_z"]) for s in vid_shots
             if s["motion"]["J4"] > T["j4"] and s["motion"]["J4_z"] >= T["j4_z"]}
    cutsr = rep.get("cuts") or []
    flash = [c["cut"] for c in cutsr if c["flash_frame"] or c["black_frame"]]
    jar = [(c["cut"], c["picture_dE"]) for c in cutsr
           if scene_of(c["cut"].split("→")[0]) and scene_of(c["cut"].split("→")[0]) == scene_of(c["cut"].split("→")[1])
           and c["picture_dE"] > T["cut_dE_same_scene"]]
    items["E2"] = item_score([
        C("E2.1", "镜内没有意外硬切（直方图切点不在计划切点 ±0.25 s 内 = 0）", not inner, inner or "无", "cut_check.hist_cuts"),
        C("E2.2", f"去抖后没有明显 4 帧一顿（J4 >{T['j4']} 且 z ≥{T['j4_z']} 的视频镜 = 0）", not j4bad, j4bad or "无", RV + " J4"),
        C("E2.3", "切点没有闪帧 / 黑帧", not flash, flash or "无", RV + " cuts"),
        C("E2.4", "没有缺镜（占位静帧）", not ph, ph or "无", "timeline"),
        C("E2.5", f"同场切点画面 ΔE ≤{T['cut_dE_same_scene']}（同场接得上，不跳色）", not jar, jar or "无", RV + " cuts"),
    ])
    # ---- E3 转场
    jumps = [(c["cut"], c["audio_jump_db"]) for c in cutsr if abs(c["audio_jump_db"]) >= T["audio_jump"] or c["click"]]
    jl = [s["shot"] for s in tl["shots"][1:] if s.get("j_cut_s") or s.get("l_cut_s") or s.get("transition_in")]
    rt = tl.get("room_tone") or {}
    sc_change = [b["shot"] for a, b in zip(tl["shots"], tl["shots"][1:]) if scene_of(a["shot"]) != scene_of(b["shot"])]
    sc_ok = [s for s in sc_change if any(x["shot"] == s and (x.get("j_cut_s") or x.get("transition_in")) for x in tl["shots"])]
    items["E3"] = item_score([
        C("E3.1", f"切点前后电平跳变 <{T['audio_jump']:.0f} dB 且无爆音", not jumps, jumps or "无", RV + " cuts"),
        C("E3.2", "J-cut / L-cut / 设计过的转场占切点 ≥50%（声音带画面过刀）", (len(jl) / max(1, len(tl["shots"]) - 1)) >= 0.5,
          {"with_transition": jl, "cuts": len(tl["shots"]) - 1}, "timeline j_cut_s / l_cut_s / transition_in"),
        C("E3.3", "没有 ≥1 s 意外静音", not rep.get("silence"), rep.get("silence") or "无", RV),
        C("E3.4", f"没有低于 {T['room_floor']:.0f} dBFS 的数字静音窗（room tone）",
          (rt.get("min_window_dbfs_after") is not None and rt["min_window_dbfs_after"] >= T["room_floor"]) if rt else None,
          rt.get("min_window_dbfs_after", "未测"), "timeline room_tone"),
        C("E3.5", "换场切点都有声音先行 / 叠化（K-EDT-102）", (len(sc_ok) == len(sc_change)) if sc_change else None,
          {"scene_changes": sc_change, "with_transition": sc_ok} if sc_change else "本集无换场", "timeline + script scene_id"),
    ])
    # ---- E4 开头钩子
    hook = rep.get("hook") or {}
    s0 = shots[0]
    first_cut = min([c for c in planned_cuts(tl) if c > 0] or [dur])
    near = ("特写", "大特写", "近景")
    items["E4"] = item_score([
        C("E4.1", "前 3 s 内至少一刀", first_cut <= 3.0 + 0.05, first_cut, "timeline shots + pieces"),
        C("E4.2", "第一帧就有人物（首帧检出人脸）", per.get(s0["shot"], {}).get("first_has_face"), per.get(s0["shot"], {}).get("first_has_face"), "抽帧 YuNet"),
        C("E4.3", "第一镜有运动（节奏 ≥1 px/帧）", s0["motion"]["pace_px_per_frame"] >= 1.0, s0["motion"]["pace_px_per_frame"], RV),
        C("E4.4", "第一镜是近景或更近（钩子落在脸 / 细节上）", s0["scale"] in near, s0["scale"], RV + " 景别"),
        C("E4.5", "第一镜开头没有定住（frozen_head < 0.2 s）", s0["motion"]["frozen_head_s"] < 0.2, s0["motion"]["frozen_head_s"], RV),
    ])
    # ---- S1 对白清晰
    sp = tl.get("speech") or []
    cers = {x["key"]: ((x.get("h3_asr") or x.get("asr") or {}).get("cer")) for x in sp}
    cers = {k: v for k, v in cers.items() if v is not None}
    spans = sorted((x["start_s"], x["end_s"], x["key"]) for x in sp)
    ovl = [(a[2], b[2]) for a, b in zip(spans, spans[1:]) if b[0] < a[1] - 0.05]
    tempos = {x["key"]: x.get("tempo") for x in sp if (x.get("tempo") or 1) > T["max_tempo"]}
    items["S1"] = item_score([
        C("S1.1", f"每句回听 CER ≤{T['cer']}（ASR 听得出说了什么）", all(v <= T["cer"] for v in cers.values()) if cers else None,
          {k: v for k, v in cers.items() if v > T["cer"]} or (f"{len(cers)} 句达标" if cers else "无"), "timeline speech[].asr"),
        C("S1.2", f"人声时段比非人声时段响 ≥{T['speech_over_bed_db']} dB（人声压在配乐之上）",
          (sb["diff_db"] >= T["speech_over_bed_db"]) if sb.get("diff_db") is not None else None, sb.get("diff_db", "未测"), "成片音频 100 ms RMS"),
        C("S1.3", "人声不互相重叠", not ovl, ovl or "无", "timeline speech"),
        C("S1.4", f"没有被加速 >{T['max_tempo']}× 的句子", not tempos, tempos or "无", "timeline speech[].tempo"),
    ])
    # ---- S2 响度
    L = rep.get("loudness") or {}
    shotI = [s["loudness"].get("I_lufs") for s in shots if s["loudness"].get("I_lufs") is not None and s["loudness"]["I_lufs"] > -70]
    items["S2"] = item_score([
        C("S2.1", "整集 −14 ±1 LUFS", (T["lufs"][0] <= L["I_lufs"] <= T["lufs"][1]) if L.get("I_lufs") is not None else None, L.get("I_lufs"), RV + " ebur128"),
        C("S2.2", "真峰值 ≤ −1 dBTP", (L["true_peak_dbtp"] <= T["tp"]) if L.get("true_peak_dbtp") is not None else None, L.get("true_peak_dbtp"), RV),
        C("S2.3", "LRA 4–11 LU（有动态但不忽大忽小）", (T["lra"][0] <= L["LRA"] <= T["lra"][1]) if L.get("LRA") is not None else None, L.get("LRA"), RV),
        C("S2.4", f"逐镜响度差 ≤{T['shot_I_spread']} LU", (max(shotI) - min(shotI) <= T["shot_I_spread"]) if len(shotI) > 1 else None,
          round(max(shotI) - min(shotI), 1) if len(shotI) > 1 else "未测", RV),
        C("S2.5", f"切点电平跳变 <{T['audio_jump']:.0f} dB", not jumps, jumps or "无", RV + " cuts"),
    ])
    # ---- S3 配乐
    bgm = tl.get("bgm") or {}
    cues = bgm.get("cues") or []
    drop_t = min([c["start_s"] for c in cues if c.get("action") == "drop"] or [dur])
    enter_t = min([c["start_s"] for c in cues if c.get("action") == "enter"] or [dur])
    cover = max(0.0, min(dur, drop_t) - enter_t) / dur if bgm.get("used") and dur else 0.0
    ints = [c.get("intensity") for c in cues if c.get("intensity") is not None]
    duck = (tl.get("settings") or {}).get("bgm_duck_dialogue_db")
    tail = sb.get("tail_1s_db")
    items["S3"] = item_score([
        C("S3.1", "整集一条 BGM（项目方已定）", bool(bgm.get("used")), bgm.get("file"), "timeline bgm.used"),
        C("S3.2", f"BGM 覆盖 ≥{T['bgm_cover']:.0%} 时长", cover >= T["bgm_cover"], round(cover, 2), "timeline bgm.cues"),
        C("S3.3", f"对白段 BGM 压低 ≥{T['bgm_duck_db']:.0f} dB", (duck is not None and duck >= T["bgm_duck_db"] and bool(bgm.get("used"))),
          duck, "timeline settings.bgm_duck_dialogue_db（配置值，混音里分不出轨）"),
        C("S3.4", "配乐强度随情绪节拍变化（cue 强度至少 2 档，或有 swell / stinger）",
          (len(set(ints)) >= 2 or any(c.get("action") in ("swell", "stinger") for c in cues)) if cues else False,
          {"intensities": ints, "actions": [c.get("action") for c in cues]}, "timeline bgm.cues"),
        C("S3.5", "结尾收住（最后 1 s 比全片平均低 ≥6 dB，或有 drop cue）",
          (any(c.get("action") == "drop" for c in cues) or (tail is not None and sb.get("mean_db") is not None and tail <= sb["mean_db"] - 6)),
          {"tail_1s_db": tail, "mean_db": sb.get("mean_db")}, "成片音频 + cues"),
    ])
    # ---- S4 音效
    sfx = tl.get("sfx") or {}
    ev = sfx.get("events") or []
    beds = sfx.get("beds") or []
    stems = [st for s in tl["shots"] for st in (s.get("stems") or []) if st.get("role") in ("foley", "scene")]
    scenes_all = sorted({scene_of(s["shot"]) or "?" for s in tl["shots"]})
    bed_sc = sorted({b.get("scene") for b in beds})
    lic = sfx.get("licenses_ok")
    items["S4"] = item_score([
        C("S4.1", "有音效层（timeline.sfx 或 foley / scene 分轨）", bool(ev or beds or stems), {"events": len(ev), "beds": len(beds), "stems": len(stems)}, "timeline sfx"),
        C("S4.2", "每个场景都有环境声床", bool(beds) and set(scenes_all) <= set(bed_sc), {"scenes": scenes_all, "beds": bed_sc}, "timeline sfx.beds"),
        C("S4.3", f"动作音效（脚步 / 门 / 物件）≥{T['sfx_per_10s']:.0f} 个 / 10 s", (len(ev) / max(1.0, dur) * 10) >= T["sfx_per_10s"],
          round(len(ev) / max(1.0, dur) * 10, 2), "timeline sfx.events"),
        C("S4.4", f"没有低于 {T['room_floor']:.0f} dBFS 的数字静音", (rt.get("min_window_dbfs_after", -99) >= T["room_floor"]) if rt else None,
          rt.get("min_window_dbfs_after", "未测"), "timeline room_tone"),
        C("S4.5", "用到的音效文件全部有许可证登记（免费可商用）", lic if (ev or beds) else None, sfx.get("license_note") or "无音效", "data/sfx_lib/LICENSES.json"),
    ])

    for k, v in items.items():
        v["cat"], v["name"] = ITEMS[k]
    cats = {}
    for c in CATS:
        xs = [v["score"] for v in items.values() if v["cat"] == c and v["score"] is not None]
        cats[c] = round(float(np.mean(xs)), 2) if xs else None
    sc = [v["score"] for v in items.values() if v["score"] is not None]
    meas = sum(v["measured"] for v in items.values())
    tot = sum(v["total"] for v in items.values())
    return {"items": items, "cats": cats, "total_50": round(float(np.mean(sc)) * 10, 1) if sc else None,
            "coverage": round(meas / tot, 2), "lowest": sorted([(v["score"], k) for k, v in items.items() if v["score"] is not None])[:3]}


# ---------------------------------------------------------------- 主流程
def score(video: Path, timeline_path: Path, name: str, use_vlm: bool, note: str = "") -> dict:
    import review as RV
    tl = json.loads(timeline_path.read_text(encoding="utf-8"))
    t0 = time.time()
    items = []
    for s in tl["shots"]:
        spx = [x for x in tl.get("speech", []) if x.get("shot") == s["index"] and x.get("kind") == "dialogue"]
        items.append(RV.Shot(s["shot"], video, float(s["start_s"]), float(s["duration_s"]), s.get("file"), spx))
    rep = RV.review(f"film_{name}", items, video, "bt709", tl)
    faces = RV.Faces()
    fdir = OUT / "frames" / name
    fp = frame_pass(video, tl["shots"], faces, fdir)
    gz = gaze_pass(fp["per_shot"])
    sb = speech_bed(video, tl)
    inner = inner_cuts(video, fp["fps"], planned_cuts(tl))
    vlm = vlm_pass(fp["per_shot"], {s["shot"]: s for s in tl["shots"]}) if use_vlm else None
    res = score_all(rep, tl, fp, gz, sb, vlm, inner)
    m = re.match(r"(ep\d{2})", name)
    out = {"schema": SCHEMA, "rubric": RUBRIC_VERSION, "name": name, "episode": m.group(1) if m else None,
           "video": rel(video), "timeline": rel(timeline_path), "note": note, "at": time.strftime("%Y-%m-%d %H:%M:%S"),
           "system_version": (ROOT / "data/system_version.txt").read_text(encoding="utf-8").strip()
           if (ROOT / "data/system_version.txt").exists() else None,
           "vlm": bool(use_vlm), "seconds": round(time.time() - t0, 1),
           "review_dir": rel(ROOT / "data/ab/director" / f"film_{name}"), **res,
           "measures": {"frames": {k: {kk: vv for kk, vv in d.items() if kk != "frames"} for k, d in fp["per_shot"].items()},
                        "frame_files": {k: {t: rel(p) for t, p in d["frames"].items()} for k, d in fp["per_shot"].items()},
                        "gaze": gz, "speech_bed": sb, "inner_cuts": inner, "vlm": vlm,
                        "loudness": rep.get("loudness"), "hook": rep.get("hook"), "cuts": rep.get("cuts")}}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{name}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    if out["episode"]:
        shutil.copyfile(OUT / f"{name}.json", OUT / f"{out['episode']}.json")
    build_page()
    print(f"[film_score] {name}: {out['total_50']}/50 coverage {out['coverage']} cats {out['cats']} lowest {out['lowest']}")
    return out


def load_all() -> list[dict]:
    rows = []
    for p in sorted(OUT.glob("*.json")):
        if re.fullmatch(r"ep\d{2}", p.stem):
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if d.get("schema") == SCHEMA:
            rows.append(d)
    return sorted(rows, key=lambda d: d.get("at") or "")


def lowest(names: list[str] | None = None) -> list[tuple]:
    rows = [d for d in load_all() if not names or d["name"] in names]
    agg = {}
    for d in rows:
        for k, v in d["items"].items():
            if v["score"] is not None:
                agg.setdefault(k, []).append(v["score"])
    return sorted((round(float(np.mean(v)), 2), k, ITEMS[k][0] + "·" + ITEMS[k][1]) for k, v in agg.items())


def build_page() -> Path:
    rows = load_all()
    PAGE.mkdir(parents=True, exist_ok=True)
    e = html.escape
    css = ("body{font-family:system-ui,'Microsoft YaHei';margin:20px;background:#111;color:#ddd}table{border-collapse:collapse;margin:8px 0}"
           "td,th{border:1px solid #444;padding:4px 8px;font-size:13px;vertical-align:top}th{background:#222}"
           ".ok{color:#6c6}.bad{color:#e66}.na{color:#888}.bar{display:inline-block;height:10px;background:#4a8;vertical-align:middle}"
           "details{margin:6px 0}summary{cursor:pointer}img{height:150px;margin:2px}h2{margin-top:28px}code{color:#9cf}")
    out = [f"<html><head><meta charset='utf-8'><title>成片好莱坞观感分</title><style>{css}</style></head><body>",
           "<h1>成片“好莱坞观感分”</h1>",
           f"<p>评分口径 {RUBRIC_VERSION}：四大项 15 小项，每小项 5 条可核对条件，小项分 = 5 × 通过 / 测到；整集 /50 = 小项平均 × 10。"
           "只评技术和观感，不评剧本内容。工具 <code>tools/director/film_score.py</code>，规则 K-REV-801–804。</p>"]
    if rows:
        out.append("<h2>总表（A/B 对照：同一集多行即前后对比）</h2><table><tr><th>名称</th><th>时间</th><th>说明</th><th>/50</th><th>测到</th>"
                   + "".join(f"<th>{c}</th>" for c in CATS) + "".join(f"<th>{k}<br>{ITEMS[k][1]}</th>" for k in ITEMS) + "</tr>")
        for d in rows:
            out.append(f"<tr><td><a href='#{e(d['name'])}'>{e(d['name'])}</a></td><td>{e(d['at'])}</td><td>{e(d.get('note') or '')}</td>"
                       f"<td><b>{d['total_50']}</b></td><td>{d['coverage']:.0%}</td>"
                       + "".join(f"<td>{d['cats'].get(c)}</td>" for c in CATS)
                       + "".join(f"<td>{d['items'][k]['score'] if k in d['items'] else ''}</td>" for k in ITEMS) + "</tr>")
        out.append("</table>")
        lw = lowest()
        out.append("<p>全局最低小项（所有记录平均，RSI 下一轮先修）：" + "；".join(f"{k} {n} {s}" for s, k, n in lw[:4]) + "</p>")
    for d in reversed(rows):
        out.append(f"<h2 id='{e(d['name'])}'>{e(d['name'])} — {d['total_50']}/50（测到 {d['coverage']:.0%}，看图模型 {'有' if d['vlm'] else '未跑'}）</h2>")
        out.append(f"<p>成片 <code>{e(d['video'])}</code>；timeline <code>{e(d['timeline'])}</code>；DIR 审片明细 <code>{e(d['review_dir'])}/review.md</code>；"
                   f"系统版本 {e(str(d.get('system_version')))}</p>")
        for k, it in d["items"].items():
            sc = it["score"]
            w = int((sc or 0) * 30)
            out.append(f"<details><summary><b>{k} {e(it['cat'])}·{e(it['name'])}</b> {sc if sc is not None else '未测'} / 5 "
                       f"<span class='bar' style='width:{w}px'></span>（测到 {it['measured']}/{it['total']}）</summary><table>"
                       "<tr><th>条件</th><th>结果</th><th>测量值</th><th>出处</th></tr>")
            for c in it["conds"]:
                cls, lab = ("na", "未测") if c["pass"] is None else (("ok", "通过") if c["pass"] else ("bad", "不通过"))
                out.append(f"<tr><td>{c['id']} {e(c['text'])}</td><td class='{cls}'>{lab}</td>"
                           f"<td>{e(json.dumps(c['value'], ensure_ascii=False, default=str))[:600]}</td><td>{e(c['src'])}</td></tr>")
            out.append("</table></details>")
        ff = (d.get("measures") or {}).get("frame_files") or {}
        if ff:
            out.append("<details><summary>逐镜首 / 中 / 尾帧</summary>")
            for sid, fs in ff.items():
                out.append(f"<div>{e(sid)} " + "".join(f"<img src='../../../{e(p)}' title='{e(t)}'>" for t, p in fs.items()) + "</div>")
            out.append("</details>")
    out.append("</body></html>")
    p = PAGE / "index.html"
    p.write_text("\n".join(out), encoding="utf-8")
    return p


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("score")
    s.add_argument("video")
    s.add_argument("--timeline")
    s.add_argument("--name")
    s.add_argument("--vlm", action="store_true")
    s.add_argument("--note", default="")
    sub.add_parser("page")
    lo = sub.add_parser("lowest")
    lo.add_argument("--name", nargs="*")
    a = ap.parse_args(argv)
    if a.cmd == "score":
        v = Path(a.video)
        v = v if v.is_absolute() else ROOT / v
        tlp = Path(a.timeline) if a.timeline else v.with_suffix(".timeline.json")
        tlp = tlp if tlp.is_absolute() else ROOT / tlp
        score(v, tlp, a.name or v.stem, a.vlm, a.note)
    elif a.cmd == "page":
        print(build_page())
    else:
        for row in lowest(a.name):
            print(*row)


if __name__ == "__main__":
    main()
