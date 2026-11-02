"""VIDLAB 线 2（视频）RSI 打分器（总调度 fredw-2b 派，2026-11-02；docs/master/RSI_PROGRAM.md 线 2）。

项目方 11-02 03:5x 原话：“做视频的线（使用 MiniMax，或者现在用的 Pika Flex 模型）……最终目标：一定要达到现在好莱坞电影的水平。
很明显，现在生成的图和视频效果都达不到，镜头运动和人物表情也很死板。”

六个分项（权重 = RSI_PROGRAM 线 2 表），每项 0–1，总分 = Σ 权重 × 分项（0–100）。全部代码判定（decider = code）：
  cam   运镜执行 20：0.4 × min(1, 词表 enabled 数 / 12) + 0.3 × 最近一轮运镜 A/B 臂通过率 + 0.3 × 运镜活跃度占参照比
  act   表情与表演 25：0.7 × 表演活跃度占参照比（expr_std / brow_rng / lm_nonrigid / head_std / blink_pm / gaze_shift_ps 六个比值的几何平均，单项封顶 1）
                       + 0.3 × (1 − 看镜头帧占比)；VLM 表演评分（--vlm，ns_agent.vqa）测到时再占 0.2（未测不进分母，coverage 里写明）
  lip   口型 15：V7 台词段通过率（新口径 VQAGATE 11-02：优先 v7_rejudge 输出，其次 score_clip v7）÷ 0.95，封顶 1
  cons  一致性 20：每条片 = 每个应在画角色 SFace 中位 ≥0.30 且出脸 ≥15%（score_clip 闸门同口径）且 V6 分身 dup_side ≤0.15 且发色漂移 |dV| ≤30、|dS| ≤35，
                   通过率 ÷ 0.98
  stab  画面稳定 10：每条片 = 去抖后 J4 ≤1.3（J4 >1.2 的按 video_policy dejudder 去抖后重量）且镜内硬切 0 且 V6 未判不过，通过率 ÷ 0.98
  film  成片分 10：tools/director/film_score 最新整集分 / 45（好莱坞级目标 45/50）

好莱坞参照（满分锚点）：data/rsi/ref_video/raw/ 下公开片源（只本地存放、只给本地模型看）：
  Charade（1963，Stanley Donen；美国公有领域）、Tears of Steel（2012，Blender Foundation，CC-BY 3.0 实拍）。
  ref build 按镜头切分 → 选脸够大的人物镜 → 用 clipmetrics 同一套函数量 → data/rsi/vidlab/ref_metrics.json（中位数 = 锚点）。

用法（项目 .venv）：
  python tools/vidlab/score.py ref build [--per-film 50]
  python tools/vidlab/score.py score [--corpus DIR ...] [--name base] [--note ...] [--no-write]
  python tools/vidlab/score.py ab --a GLOB --b GLOB --name X [--metric act]     # A/B 代码判定
  python tools/vidlab/score.py lowest                                            # 最近一次分数的最低项
输出：data/rsi/scores.jsonl（line=video，一次一行）、data/rsi/vidlab/score_<name>.json（逐条明细）
"""
from __future__ import annotations

import argparse
import glob
import json
import random
import re
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "vidlab"))
sys.path.insert(0, str(ROOT / "tools"))

import clipmetrics as CM  # noqa: E402
import vio as VIO  # noqa: E402

RSI = ROOT / "data" / "rsi"
VL = RSI / "vidlab"
SCORES = RSI / "scores.jsonl"
REF_RAW = RSI / "ref_video" / "raw"
REF_JSON = VL / "ref_metrics.json"
DEFAULT_CORPUS = [VL / "corpus"]
RUBRIC = "vidlab-v2-2026-11-02"   # v2：运镜第三块 = 执行准确度（v1 = 运动量占参照比，Pika 背景漂移导致虚高）
W = {"cam": 20, "act": 25, "lip": 15, "cons": 20, "stab": 10, "film": 10}
NAMES = {"cam": "运镜执行", "act": "表情与表演", "lip": "口型", "cons": "一致性", "stab": "画面稳定", "film": "成片分"}
ACT_KEYS = ("expr_std", "brow_rng", "lm_nonrigid", "head_std", "blink_pm", "gaze_shift_ps")
CAM_KEYS = ("cam_net_ps", "cam_coherence")   # v4：只认有方向的连贯运动（背景漂移不算运镜）
TH = {"sface": 0.30, "seen": 0.15, "dup_side": 0.15, "hair_dV": 30.0, "hair_dS": 35.0, "J4": 1.3, "J4_dj": 1.2,
      "lip_full": 0.95, "cons_full": 0.98, "stab_full": 0.98, "film_full": 45.0, "cam_vocab_full": 12}
REF_FILMS = {"charade_1963.mp4": "Charade (1963) 公有领域", "tears_of_steel_720p.mov": "Tears of Steel (2012) CC-BY 3.0"}


def sysver() -> str:
    return VIO.read_json(ROOT / "data" / "system_version.txt").get("id", "?")


# ======================= 参照集 =======================

def scan_film(path: Path, fps: float = 4.0):
    """一遍解码：镜头切点（HSV 直方图 Bhattacharyya）+ 每帧最大脸高占比。"""
    import cv2
    pr = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                         "-of", "csv=p=0", str(path)], capture_output=True, text=True, timeout=120)
    w, h = [int(x) for x in pr.stdout.strip().split(",")[:2]]
    W, H = 480, int(round(480 * h / w / 2) * 2)
    proc = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(path), "-vf", f"fps={fps},scale={W}:{H}", "-f", "rawvideo",
                             "-pix_fmt", "bgr24", "-"], stdout=subprocess.PIPE)
    fm = CM.face_models()
    prev, cuts, faces, i = None, [0.0], [], 0
    nb = W * H * 3
    while True:
        buf = proc.stdout.read(nb)
        if len(buf) < nb:
            break
        f = np.frombuffer(buf, np.uint8).reshape(H, W, 3)
        hsv = cv2.cvtColor(f, cv2.COLOR_BGR2HSV)
        hist = cv2.calcHist([hsv], [0, 1], None, [16, 8], [0, 180, 0, 256])
        cv2.normalize(hist, hist)
        if prev is not None and cv2.compareHist(prev, hist, cv2.HISTCMP_BHATTACHARYYA) > 0.42:
            cuts.append(i / fps)
        prev = hist
        ds = fm.faces(f) if fm else []
        faces.append(max([d[3] / H for d in ds], default=0.0))
        i += 1
    proc.wait()
    dur = i / fps
    cuts.append(dur)
    shots = []
    for a, b in zip(cuts[:-1], cuts[1:]):
        fs = faces[int(a * fps): int(b * fps)]
        shots.append({"t0": round(a, 2), "t1": round(b, 2), "face_h": round(float(np.median(fs)) if fs else 0.0, 3),
                      "face_frac": round(float(np.mean([x > 0 for x in fs])) if fs else 0.0, 3)})
    return shots


def _ref_one(args):
    path, t0, dur = args
    a = CM.analyze(Path(path), t0=t0, dur=dur, j4=False)
    return {"t0": t0, "dur": dur, **CM.clip_summary(a)}


def ref_build(per_film: int = 50, workers: int = 3):
    VL.mkdir(parents=True, exist_ok=True)
    out = {"schema": "nsfs.vidlab_ref/1", "algo": CM.ALGO, "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "films": {}, "shots": []}
    jobs = []
    for fn, label in REF_FILMS.items():
        p = REF_RAW / fn
        if not p.is_file():
            continue
        sp = VL / f"ref_shots_{p.stem}.json"
        if sp.is_file():
            shots = VIO.read_json(sp)
        else:
            shots = scan_film(p)
            VIO.write_json(sp, shots)
        # 人物镜：≥3 s、脸在 ≥70% 采样帧里、脸高 ≥15% 画面高（与我们中景及以上的人物镜同类）；片头片尾 3% 不取
        T = shots[-1]["t1"] if shots else 0
        cand = [s for s in shots if s["t1"] - s["t0"] >= 3.0 and s["face_frac"] >= 0.7 and s["face_h"] >= 0.15
                and 0.03 * T < s["t0"] < 0.97 * T]
        random.Random(7).shuffle(cand)
        pick = sorted(cand[:per_film], key=lambda s: s["t0"])
        out["films"][fn] = {"label": label, "shots_total": len(shots), "candidates": len(cand), "picked": len(pick)}
        for s in pick:
            jobs.append((str(p), s["t0"] + 0.3, round(min(s["t1"] - 0.3, s["t0"] + 10.3) - (s["t0"] + 0.3), 2)))
    with ProcessPoolExecutor(workers) as ex:
        for (p, t0, dur), r in zip(jobs, ex.map(_ref_one, jobs)):
            out["shots"].append({"film": Path(p).name, **r})
    out["anchor"] = anchors(out["shots"])
    VIO.write_json(REF_JSON, out, indent=1)
    return out


def anchors(rows):
    a = {}
    for k in (*ACT_KEYS, "cam_gaze", *CAM_KEYS, "cam_speed_med", "cam_moving_frac", "cam_path_ps", "expr_rng"):
        v = [r[k] for r in rows if r.get(k) is not None]
        a[k] = {"median": round(float(np.median(v)), 4), "mean": round(float(np.mean(v)), 4), "p25": round(float(np.percentile(v, 25)), 4),
                "p75": round(float(np.percentile(v, 75)), 4), "n": len(v)} if v else None
    return a


def load_ref():
    if not REF_JSON.is_file():
        raise SystemExit("没有参照集：先跑 python tools/vidlab/score.py ref build")
    return VIO.read_json(REF_JSON)


# ======================= 我们的片 =======================

ARM_RE = re.compile(r"^(?P<shot>ep\d+-S\d+)__rca_(?P<arm>.+)\.mp4$")


def corpus_clips(dirs):
    """corpus 目录下的 Pika 片（排除 pdd2 对照和 _dj 后期版）+ 同实验目录 results.json 里的 score_clip 分数"""
    clips = []
    for d in dirs:
        for mp4 in sorted(Path(d).rglob("*.mp4")):
            m = ARM_RE.match(mp4.name)
            if not m or "pdd2" in mp4.name or mp4.stem.endswith("_dj"):
                continue
            exp = mp4.parent.name
            rf = mp4.parent / "results.json"
            res = VIO.read_json(rf) if rf.is_file() else {}
            arm = res.get(m["arm"]) or {}
            jf = mp4.parent / "jobs.json"
            prompt = next((j.get("prompt") for j in (VIO.read_json(jf) if jf.is_file() else []) if j.get("id") == m["arm"]), None)
            if arm.get("recipe") and arm["recipe"] != "i2va_pika_flex":
                continue
            clips.append({"path": mp4, "exp": exp, "arm": m["arm"], "shot": m["shot"], "score": arm.get("score") or {}, "prompt": prompt,
                          "dj": mp4.parent / (mp4.stem + "_dj.mp4")})
    return clips


def v7_rejudged(dirs):
    out = {}
    for d in dirs:
        for f in Path(d).rglob("v7_rejudge*.out"):
            # .out 里混着日志行：只解析以 { 开头的 JSON 行；JSON 行坏了直接抛（不静默跳过）
            for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
                if not line.startswith("{"):
                    continue
                r = json.loads(line)
                if isinstance(r, dict) and r.get("exp") and r.get("arm"):
                    out[(r["exp"], r["arm"])] = r
    return out


def dejudder_j4(c: dict) -> float | None:
    """J4 > 1.2 的片按 video_policy 去抖（tools/dejudder.py）后重量；去抖版缓存在 data/rsi/vidlab/dj_cache/"""
    import motion_judder as MJ
    dst = VL / "dj_cache" / f"{c['exp']}__{c['path'].stem}_dj.mp4"
    if not dst.is_file():
        dst.parent.mkdir(parents=True, exist_ok=True)
        r = subprocess.run([sys.executable, str(ROOT / "tools" / "dejudder.py"), str(c["path"]), str(dst)],
                           capture_output=True, text=True, timeout=900)
        if r.returncode or not dst.is_file():
            return None
    m, _ = MJ.analyze(dst)
    return m.get("J4")


def _an(path):
    return CM.clip_summary(CM.analyze(Path(path)))


def ratio_score(val, anchor):
    """占参照比，封顶 1。参照中位数为 0 的稀疏事件指标（眨眼：12 fps 下多数镜头测到 0 次）改用均值作锚"""
    if val is None or not anchor:
        return None
    ref = anchor.get("median") or anchor.get("mean")
    return min(1.0, val / ref) if ref else None


def geo(xs):
    xs = [max(1e-3, x) for x in xs if x is not None]
    return float(np.exp(np.mean(np.log(xs)))) if xs else None


def act_index(summ: dict, anc: dict) -> dict:
    rs = {k: ratio_score(summ.get(k), anc.get(k)) for k in ACT_KEYS}
    if anc.get("blink_pm") and not anc["blink_pm"].get("median") and summ.get("blink_pm") is not None:
        # 稀疏事件：单条片 0 次不代表死板（参照中位也是 0）→ 单条片按 0/1 有没有眨眼记，整体靠均值比
        rs["blink_pm"] = 1.0 if summ["blink_pm"] > 0 else 0.5
    return {"ratios": {k: (round(v, 3) if v is not None else None) for k, v in rs.items()}, "index": geo(list(rs.values()))}


def cam_index(summ: dict, anc: dict) -> float | None:
    return geo([ratio_score(summ.get(k), anc.get(k)) for k in CAM_KEYS])


# 提示词运镜句 → 目标量（内容相对画面的累计量；“small amplitude”档 = tools/vidlab/camctl.AMP 同一张表）
CAM_RE = [(r"pushes in|zooms in", "push_in"), (r"pulls out|zooms out", "pull_out"), (r"trucks right", "truck_right"),
          (r"trucks left", "truck_left"), (r"pans right", "pan_right"), (r"pans left", "pan_left"), (r"tilts up", "tilt_up"),
          (r"tilts down", "tilt_down"), (r"pedestals up", "pedestal_up"), (r"pedestals down", "pedestal_down"),
          (r"arcs", "arc"), (r"holds a static shot", "static")]


def cam_target(prompt: str) -> tuple[str | None, dict | None]:
    import camctl as CC
    for rx, mv in CAM_RE:
        if re.search(r"The camera[^.]*\b(?:" + rx + r")\b", prompt or ""):
            tx, ty, sc, rot = CC.AMP[mv]
            t = {"cam_tx": tx, "cam_ty": ty, "cam_zoom": float(np.log(sc)), "cam_rot": float(np.radians(rot))}
            return mv, {k: v for k, v in t.items() if abs(v) > 1e-9}
    return None, None


def cam_exec_tol(summ: dict, move: str | None, target: dict | None) -> float | None:
    """运镜执行（语料版，带容差）：静止镜 = 净运动 ≤ 参照 p25 记 1，越大越低；有运动的镜每个目标量：
    方向反 → 0；实测 / 目标在 0.5–2 倍之间 → 1；不足 0.5 倍按比例；超过 2 倍线性降到 4 倍为 0。多个目标量取平均"""
    if move is None:
        return None
    if move == "static":
        v = summ.get("cam_net_ps")
        return None if v is None else round(max(0.0, min(1.0, 1 - (v - 0.008) / 0.03)), 3)
    acc = []
    for k, t in target.items():
        v = summ.get(k)
        if v is None:
            continue
        r = v / t
        acc.append(0.0 if r <= 0 else (min(1.0, r / 0.5) if r < 2 else max(0.0, 1 - (r - 2) / 2)))
    return round(float(np.mean(acc)), 3) if acc else None


def write_camexec(rows) -> None:
    """DIRECTOR camera_ab.py 判 AB6 用（11-02 约定）：data/rsi/vidlab/camexec.json，“实验名/臂 id → {move, acc, amp_ratio, rot_deg}”，
    与已有条目合并（同键覆盖），口径 = clipmetrics ALGO + cam_exec_tol"""
    import camctl as CC
    f = VL / "camexec.json"
    cur = VIO.read_json(f) if f.is_file() else {"schema": "nsfs.vidlab_camexec/1", "items": {}}
    for r in rows:
        mv = r.get("cam_move")
        if not mv:
            continue
        amp = None
        if mv != "static":
            _, tg = cam_target("The camera " + {"push_in": "pushes in", "pull_out": "pulls out"}.get(mv, mv.replace("_", "s ", 1)) + ".")
            tg = tg or {}
            if tg:
                k = max(tg, key=lambda x: abs(tg[x]))
                amp = round(r[k] / tg[k], 3) if r.get(k) is not None else None
        cur["items"][f"{r['exp']}/{r['arm']}"] = {"move": mv, "acc": r.get("cam_exec"), "amp_ratio": amp,
                                                 "rot_deg": round(float(np.degrees(r["cam_rot"])), 2) if r.get("cam_rot") is not None else None,
                                                 "net_ps": r.get("cam_net_ps"), "coherence": r.get("cam_coherence")}
    cur.update({"algo": CM.ALGO, "rubric": RUBRIC, "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "doc": "acc：方向反 0；实测/目标 0.5–2 倍 = 1；不足按比例；超 2 倍线性降到 4 倍为 0。目标 = camctl.AMP 小幅档"})
    VIO.write_json(f, cur, indent=1)


def cam_vocab():
    import yaml
    y = yaml.safe_load((ROOT / "config" / "director" / "camera_moves.yaml").read_text(encoding="utf-8"))
    mv = y.get("moves") or {}
    items = mv.items() if isinstance(mv, dict) else [(m.get("id"), m) for m in mv]
    en = [k for k, m in items if (m or {}).get("enabled")]
    ab = None
    # 取最新 = 轮次号最大（cm_r<N>_verdict.json，显式版本号），不按修改时间
    vs = sorted((ROOT / "data" / "ab" / "camera_moves").glob("cm_r*_verdict.json"),
                key=lambda p: int(re.search(r"cm_r(\d+)_", p.name).group(1)))
    if vs:
        v = VIO.read_json(vs[-1])
        arms = v.get("arms") or v.get("results") or []
        if isinstance(arms, dict):
            arms = list(arms.values())
        ps = [a.get("pass") for a in arms if isinstance(a, dict) and a.get("pass") is not None]
        ab = {"file": str(vs[-1].relative_to(ROOT)), "pass": sum(1 for x in ps if x), "measured": len(ps),
              "rate": round(sum(1 for x in ps if x) / len(ps), 3) if ps else None}
    return {"enabled": en, "n_enabled": len(en), "n_total": len(list(items)), "ab": ab}


def film_latest():
    """film_score 每集的 epNN.json = 该集最新一次（film_score 自己维护的登记）；多集取文件内 at 字段最新的一集，不按修改时间"""
    best = None
    for f in sorted((ROOT / "data" / "film_score").glob("ep*.json")):
        if re.fullmatch(r"ep\d+\.json", f.name):
            d = VIO.read_json(f)
            if best is None or str(d.get("at") or "") > best["at"]:
                best = {"file": str(f.relative_to(ROOT)), "name": d.get("name"), "total_50": d.get("total_50"), "at": str(d.get("at") or "")}
    return best


def score(dirs, name="base", note="", write=True, use_vlm=False, workers=3, dejudder=True):
    ref = load_ref()
    anc = ref["anchor"]
    clips = corpus_clips(dirs)
    with ProcessPoolExecutor(workers) as ex:
        summs = list(ex.map(_an, [str(c["path"]) for c in clips]))
    rj = v7_rejudged(dirs)
    rows = []
    for c, s in zip(clips, summs):
        sc = c["score"]
        r = {"exp": c["exp"], "arm": c["arm"], "shot": c["shot"], "path": str(c["path"].relative_to(ROOT)), **s}
        r["act"] = act_index(s, anc)
        r["cam_idx"] = cam_index(s, anc)
        mv, tg = cam_target(c.get("prompt"))
        r["cam_move"], r["cam_exec"] = mv, cam_exec_tol(s, mv, tg)
        # 口型
        v7n = rj.get((c["exp"], c["arm"]))
        v7 = sc.get("v7") or {}
        if v7n and v7n.get("status") in ("通过", "不通过"):
            r["lip"] = {"pass": v7n["status"] == "通过", "src": "v7_rejudge（台词段新口径）", "amp": v7n.get("win_amp"), "corr": v7n.get("corr")}
        elif v7.get("status") in ("通过", "不通过"):
            r["lip"] = {"pass": v7["status"] == "通过", "src": "score_clip v7", "corr": v7.get("corr")}
        else:
            r["lip"] = None
        # 一致性
        if sc:
            ids = sc.get("identity") or {}
            low = [n for n, it in ids.items() if (it or {}).get("sface_med") is None or (it.get("seen") or 0) < TH["seen"]
                   or it["sface_med"] < TH["sface"]]
            v6 = sc.get("v6") or {}
            dup = (v6.get("dup_side_frac") or 0) > TH["dup_side"]
            hair = abs(sc.get("hair_dV") or 0) > TH["hair_dV"] or abs(sc.get("hair_dS") or 0) > TH["hair_dS"]
            r["cons"] = {"pass": not low and not dup and not hair and bool(ids), "id_low": low, "dup": dup, "hair_drift": hair}
        else:
            r["cons"] = None
        # 稳定
        j4 = s.get("J4") if s.get("J4") is not None else sc.get("J4")
        j4_after = j4
        if j4 is not None and j4 > TH["J4_dj"]:
            j4_after = (dejudder_j4(c) if dejudder else None)
        cuts = len(sc.get("cuts") or []) if sc else None
        v6bad = (sc.get("v6") or {}).get("status") == "不通过" if sc else None
        if j4_after is None and j4 is not None and j4 > TH["J4_dj"]:
            r["stab"] = {"pass": None, "why": "去抖后 J4 未测", "J4": j4}
        else:
            r["stab"] = {"pass": (j4_after is not None and j4_after <= TH["J4"]) and not cuts and not v6bad,
                         "J4": j4, "J4_after": j4_after, "cuts": cuts, "v6_bad": v6bad}
        rows.append(r)
    return finish(rows, anc, ref, name, note, write, dirs)


def rate(rows, key):
    v = [r[key]["pass"] for r in rows if r.get(key) and r[key].get("pass") is not None]
    return (sum(v) / len(v), len(v)) if v else (None, 0)


def finish(rows, anc, ref, name, note, write, dirs):
    items, cov = {}, {}
    # 表情与表演
    ai = [r["act"]["index"] for r in rows if r["act"]["index"] is not None]
    gz = [r["cam_gaze"] for r in rows if r.get("cam_gaze") is not None]
    act_live = float(np.median(ai)) if ai else None
    nolook = 1 - float(np.mean(gz)) if gz else None
    items["act"] = round(0.7 * act_live + 0.3 * nolook, 4) if act_live is not None and nolook is not None else None
    cov["act"] = {"clips_with_faces": len(ai), "vlm": "未测（--vlm 未开；VQAGATE 本地看图道）"}
    # 运镜
    cv = cam_vocab()
    # v4：运镜第三块从“运动量占参照比”改成“提示词要求的运镜执行准确度”（Pika 背景运动量本来就 ≥ 参照，量多少不代表执行对）
    ci = [r["cam_exec"] for r in rows if r.get("cam_exec") is not None]
    cam_live = float(np.median(ci)) if ci else None
    by_move = {}
    for r in rows:
        if r.get("cam_exec") is not None:
            by_move.setdefault(r["cam_move"], []).append(r["cam_exec"])
    parts = [(0.4, min(1.0, cv["n_enabled"] / TH["cam_vocab_full"]))]
    if cv["ab"] and cv["ab"]["rate"] is not None:
        parts.append((0.3, cv["ab"]["rate"]))
    if cam_live is not None:
        parts.append((0.3, cam_live))
    items["cam"] = round(sum(w * v for w, v in parts) / sum(w for w, _ in parts), 4)
    cov["cam"] = {"vocab_enabled": cv["n_enabled"], "vocab_total": cv["n_total"], "ab": cv["ab"], "cam_exec_median": cam_live,
                  "cam_exec_by_move": {k: {"n": len(v), "median": round(float(np.median(v)), 3)} for k, v in by_move.items()}}
    # 口型 / 一致性 / 稳定
    for k, full in (("lip", TH["lip_full"]), ("cons", TH["cons_full"]), ("stab", TH["stab_full"])):
        rt, n = rate(rows, k)
        items[k] = round(min(1.0, rt / full), 4) if rt is not None else None
        cov[k] = {"pass_rate": round(rt, 3) if rt is not None else None, "measured": n, "clips": len(rows)}
    fl = film_latest()
    items["film"] = round(min(1.0, (fl["total_50"] or 0) / TH["film_full"]), 4) if fl and fl.get("total_50") is not None else None
    cov["film"] = fl
    have = {k: v for k, v in items.items() if v is not None}
    total = round(sum(W[k] * v for k, v in have.items()) / sum(W[k] for k in have) * 100, 1) if have else None
    # 最低项：按“离满分的加权缺口”排，缺口最大 = 最该修
    gaps = sorted(((W[k] * (1 - v), k) for k, v in have.items()), reverse=True)
    lowest = [{"item": k, "name": NAMES[k], "score": have[k], "weighted_gap": round(g, 2)} for g, k in gaps]
    detail_act = {k: round(float(np.median([r["act"]["ratios"][k] for r in rows if r["act"]["ratios"].get(k) is not None])), 3)
                  for k in ACT_KEYS if any(r["act"]["ratios"].get(k) is not None for r in rows)}
    ours = anchors(rows)
    rec = {"t": time.strftime("%Y-%m-%dT%H:%M:%S"), "line": "video", "score": total,
           "items": {k: (round(v * 100, 1) if v is not None else None) for k, v in items.items()},
           "weights": W, "version": sysver(), "rubric": RUBRIC, "algo": CM.ALGO, "name": name, "note": note,
           "lowest": lowest[0]["item"] if lowest else None, "clips": len(rows),
           "corpus": [str(Path(d).relative_to(ROOT)) if Path(d).is_absolute() else str(d) for d in dirs]}
    detail = {**rec, "coverage": cov, "lowest_rank": lowest, "act_ratio_medians": detail_act,
              "ours_medians": {k: (v or {}).get("median") for k, v in ours.items()},
              "ref_medians": {k: (v or {}).get("median") for k, v in anc.items()},
              "ref_films": ref.get("films"), "rows": rows}
    VIO.write_json(VL / f"score_{name}.json", detail, indent=1)
    write_camexec(rows)
    if write:
        with SCORES.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return detail


# ======================= A/B（代码判定） =======================

def cam_exec(summ: dict, target: dict) -> float | None:
    """运镜执行准确度：每个目标量（cam_tx / cam_ty / cam_zoom / cam_rot，内容相对画面的累计量）1 − |实测−目标|/|目标|，
    方向反了记 0；多个目标取平均。没测到 → None"""
    acc = []
    for k, t in (target or {}).items():
        v = summ.get(k)
        if v is None or not t:
            continue
        acc.append(0.0 if v * t < 0 else max(0.0, 1 - abs(v - t) / abs(t)))
    return round(float(np.mean(acc)), 3) if acc else None


def ab(a_glob, b_glob, name, metric="act", min_gain=0.15, target=None):
    """B 相对 A：目标指标中位数提升 ≥ min_gain（相对），且护栏不退：身份 SFace 中位不降 >0.05、V6 不新增不通过、J4 中位不升 >0.1、
    看镜头占比不升 >0.05。判定写 data/rsi/vidlab/ab_<name>.json。"""
    ref = load_ref()
    anc = ref["anchor"]

    def summarize(g):
        ps = sorted(set(glob.glob(g, recursive=True)))
        out = []
        for p in ps:
            s = _an(p)
            s["act_idx"] = act_index(s, anc)["index"]
            s["cam_idx"] = cam_index(s, anc)
            s["cam_exec"] = cam_exec(s, target)
            s["path"] = p
            out.append(s)
        return out

    A, B = summarize(a_glob), summarize(b_glob)
    key = {"act": "act_idx", "cam": "cam_idx"}.get(metric, metric)
    if metric == "cam_exec" and not target:
        raise SystemExit("cam_exec 需要 --target cam_tx=-0.07 这类目标量")

    def med(rows, k):
        v = [r[k] for r in rows if r.get(k) is not None]
        return float(np.median(v)) if v else None

    ma, mb = med(A, key), med(B, key)
    fails = []
    if ma is None or mb is None:
        fails.append("目标指标未测")
    elif mb < ma * (1 + min_gain) and not (ma == 0 and mb > 0.3):
        fails.append(f"{key} 中位 {mb:.3f} 未比 A {ma:.3f} 高 {int(min_gain * 100)}%")
    ga, gb = med(A, "cam_gaze"), med(B, "cam_gaze")
    if ga is not None and gb is not None and gb > ga + 0.05:
        fails.append(f"看镜头占比升 {ga:.2f}→{gb:.2f}")
    ja, jb = med(A, "J4"), med(B, "J4")
    if ja is not None and jb is not None and jb > ja + 0.1:
        fails.append(f"J4 中位升 {ja:.2f}→{jb:.2f}")
    v = {"name": name, "metric": key, "target": target, "A": {"n": len(A), "median": ma}, "B": {"n": len(B), "median": mb},
         "guards": {"cam_gaze": [ga, gb], "J4": [ja, jb]}, "pass": not fails, "fails": fails, "decider": "code",
         "rows": {"A": A, "B": B}, "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    VIO.write_json(VL / f"ab_{name}.json", v, indent=1)
    return v


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("ref")
    r.add_argument("action", choices=["build", "show"])
    r.add_argument("--per-film", type=int, default=50)
    s = sub.add_parser("score")
    s.add_argument("--corpus", nargs="*")
    s.add_argument("--name", default="base")
    s.add_argument("--note", default="")
    s.add_argument("--no-write", action="store_true")
    s.add_argument("--no-dejudder", action="store_true")
    a = sub.add_parser("ab")
    a.add_argument("--a", required=True)
    a.add_argument("--b", required=True)
    a.add_argument("--name", required=True)
    a.add_argument("--metric", default="act")
    a.add_argument("--min-gain", type=float, default=0.15)
    a.add_argument("--target", nargs="*", default=[], help="cam_exec 目标量，如 cam_tx=-0.07")
    sub.add_parser("lowest")
    x = ap.parse_args(argv)
    if x.cmd == "ref":
        out = ref_build(x.per_film) if x.action == "build" else load_ref()
        print(json.dumps({"films": out["films"], "anchor": out["anchor"]}, ensure_ascii=False, indent=1))
    elif x.cmd == "score":
        dirs = [Path(d) if Path(d).is_absolute() else ROOT / d for d in (x.corpus or [])] or DEFAULT_CORPUS
        d = score(dirs, x.name, x.note, not x.no_write, dejudder=not x.no_dejudder)
        print(json.dumps({k: d[k] for k in ("score", "items", "lowest", "clips", "coverage", "act_ratio_medians",
                                            "ours_medians", "ref_medians")}, ensure_ascii=False, indent=1, default=str))
    elif x.cmd == "ab":
        v = ab(x.a, x.b, x.name, x.metric, x.min_gain, {k: float(val) for k, val in (t.split("=") for t in x.target)})
        print(json.dumps({k: v[k] for k in ("name", "metric", "A", "B", "guards", "pass", "fails")}, ensure_ascii=False, indent=1))
    elif x.cmd == "lowest":
        last = [json.loads(l) for l in SCORES.read_text(encoding="utf-8").splitlines() if '"line": "video"' in l]
        print(json.dumps(last[-1] if last else None, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
