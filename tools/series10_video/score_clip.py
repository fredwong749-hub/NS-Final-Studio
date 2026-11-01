"""VIDEO10（2026-10-31）：单条视频原地打分（在出片的服务器上跑，不经笔记本链路；K-OPS-I05）。

指标（全部复用现有打分器，阈值同 LAB 闸门 tools/lab_ep02/lab_score.gate）：
- 运动：ns_render.motion_qc（mean / still / 定住 / 跳切 cut_s）
- 卡顿：tools/motion_judder（J4 / z）
- 硬切：tools/ep02_iter/cut_check.hist_cuts（HSV Bhattacharyya > 0.35 且帧差 > max(8, 6×中位)），并标出是否落在提示词分拍时间码 ±0.5 s
- 身份（按角色）：YuNet + SFace（ns_qc.face，同 review.py），每 6 帧，每个应在画露脸角色取“该帧与其参考最像的脸”的余弦，
  取中位数；参考 = 本镜 Ref2VA 用的脸部裁切（不按发色归人，K-REV-R01）
- 泛红：review.cheek_roi / face_colour，每 3 帧所有检出脸的 cheek_red 最大值、cheek_a95 起点→最大
- 印样：12 帧接触印样（lab_score.sheet）
闸门：mean ≥ 0.5、cheek_red ≤ 0.25、硬切 0、每个应在画角色 SFace ≥ 0.30（检出 ≥ 15% 采样帧；没检出 = 脸没出）；
      J4 > 1.3 记“4 帧一顿”但只作软项（合成时去抖，K-LOOP-004），不触发重出。

    python score_clip.py <video.mp4> <sheet.jpg> '<json: {"refs": {角色: 图路径}, "prompt": "...", "frames": n}>'
输出：stdout 最后一行 JSON
"""
from __future__ import annotations

import os as _os   # K-OPS-V13（VQAGATE 11-02 00:3x）：服务器打分 / 检测脚本限线程——96 核机上 onnxruntime / OpenMP 默认吃满全部核心（gpu33 7432% CPU）
for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    _os.environ[_k] = _os.environ.get("NS_SCORE_THREADS", "4")
NS_THREADS = int(_os.environ.get("NS_SCORE_THREADS", "4"))

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in ("tools", "tools/ep02_director", "tools/lab_ep02", "tools/ep02_iter", "services/render_router", "packages/qc"):
    sys.path.insert(0, str(ROOT / p))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

cv2.setNumThreads(NS_THREADS)
import cut_check as CC  # noqa: E402
import lab_score as LS  # noqa: E402
import motion_judder as MJ  # noqa: E402
import review as R  # noqa: E402
from ns_render import motion_qc as MQ  # noqa: E402

GATE = {"mean_min": 0.5, "J4_soft": 1.3, "cheek_red_max": 0.25, "cuts_max": 0, "sface_min": 0.30, "seen_min": 0.15}
# K-REN-122 景别档位（主脸框高 / 画面高；768×1344 竖构图）；允许差一档
BANDS = [0.45, 0.27, 0.17, 0.115, 0.095, 0.05]
SIZE_IDX = {"极近特写": 0, "大特写": 0, "特写": 1, "近景": 2, "中近景": 2, "中景": 3, "中全景": 4, "全身": 5, "全景": 5,
            "远景": 6, "大远景": 6}
SIZE_NAME = ["大特写", "特写", "近景/中近景", "中景", "中全景", "全景", "远景"]


def size_class(h):
    return next((i for i, b in enumerate(BANDS) if h >= b), len(BANDS))


STAMP = re.compile(r"At (\d{2}):(\d{2}(?:\.\d+)?)")


def identity_and_red(path: Path, refs: dict) -> dict:
    faces = R.Faces()
    if not faces.ok:
        return {"error": faces.note}
    ref_emb = {}
    for name, p in refs.items():
        bgr = cv2.imread(str(ROOT / p) if not Path(p).is_absolute() else p)
        if bgr is None:
            continue
        f = R.QF.largest(faces.m.faces(bgr)) if R.QF else None
        if f is None:   # 裁切图太紧时放大再测
            big = cv2.copyMakeBorder(bgr, 80, 80, 80, 80, cv2.BORDER_CONSTANT, value=(128, 128, 128))
            f = R.QF.largest(faces.m.faces(big))
            if f is None:
                continue
            bgr = big
        ref_emb[name] = faces.m.embed(bgr, f)
    fr = R.decode(path, None, None, 768, 1344, "bt709")
    per = {n: [] for n in ref_emb}
    sampled = 0
    reds, a95 = [], []
    hfr = []
    for i in range(0, len(fr), 3):
        f = fr[i]
        fs = [fc for fc in faces.detect(f, small=True) if float(fc[3]) >= 30]
        best_red, best_a = None, None
        if fs:
            hfr.append(max(float(fc[3]) for fc in fs) / f.shape[0])
        for fc in fs:
            ck = R.cheek_roi(fc, f.shape)
            if ck:
                c = R.face_colour(f, ck)
                best_red = max(best_red or 0.0, c["red_frac"])
                best_a = max(best_a or 0.0, c["a_p95"])
        if best_red is not None:
            reds.append((i, best_red))
            a95.append((i, best_a))
        if i % 6 == 0:
            sampled += 1
            if fs and ref_emb:
                embs = [faces.embed(f, fc) for fc in fs]
                for n, re_ in ref_emb.items():
                    per[n].append(max(float(R.QF.cosine(e, re_)) for e in embs))
    ident = {}
    for n in refs:
        v = per.get(n)
        if n not in ref_emb:
            ident[n] = {"sface_med": None, "seen": None, "note": "参考图测不到脸"}
            continue
        seen = len(v) / max(1, sampled)
        good = [x for x in v if x >= 0.2]
        ident[n] = {"sface_med": round(float(np.median(v)), 3) if v else None,
                    "sface_p75": round(float(np.percentile(v, 75)), 3) if v else None,
                    "sface_p10": round(float(np.percentile(v, 10)), 3) if v else None,
                    "sface_min": round(float(min(v)), 3) if v else None,
                    "seen": round(seen, 3), "match_frac": round(len(good) / max(1, sampled), 3)}
    head = [r for i, r in reds if i < 12]
    head_a = [a for i, a in a95 if i < 12]
    fh = float(np.median(hfr)) if hfr else None
    return {"identity": ident, "sampled": sampled,
            "face_h_med": round(fh, 3) if fh is not None else None,
            "size_measured": SIZE_NAME[size_class(fh)] if fh is not None else None,
            "cheek_red_max": round(max((r for _, r in reds), default=0.0), 3),
            "cheek_red_start": round(float(np.median(head)), 3) if head else None,
            "cheek_a95_start": round(float(np.median(head_a)), 1) if head_a else None,
            "cheek_a95_max": round(max((a for _, a in a95), default=0.0), 1)}


def _hair_px(rgb: np.ndarray, face) -> np.ndarray:
    """头顶带 + 脸两侧各半个脸宽（同 review.blue_hair_share 的区域）里的蓝色发丝像素（OpenCV H 85–130、S ≥30、V ≥30）→ HSV 数组"""
    H, W = rgb.shape[:2]
    x, y, w, h = (int(v) for v in face[:4])
    boxes = [(max(0, x - w // 2), max(0, y - int(0.45 * h)), min(W, x + w + w // 2), max(1, y + int(0.05 * h))),
             (max(0, x - w // 2), max(0, y), max(0, x), min(H, y + h)),
             (min(W, x + w), max(0, y), min(W, x + w + w // 2), min(H, y + h))]
    px = []
    for x0, y0, x1, y1 in boxes:
        if x1 > x0 and y1 > y0:
            hsv = cv2.cvtColor(np.ascontiguousarray(rgb[y0:y1, x0:x1]), cv2.COLOR_RGB2HSV).reshape(-1, 3)
            px.append(hsv[(hsv[:, 0] >= 85) & (hsv[:, 0] <= 130) & (hsv[:, 1] >= 30) & (hsv[:, 2] >= 30)])
    return np.concatenate(px) if px else np.zeros((0, 3), np.uint8)


def hair_and_colour(path: Path, first_frame: str | None) -> dict:
    """总调度 11-01 亲审：ep01-S5 v1 发色比首帧明显更深、更灰蓝，且全片如此。
    指标（先记录、后标定阈值）：蓝色发丝像素的 H / S / V 中位数，首帧 vs 片子（开头 0.5 s、全片中位、结尾 0.5 s），
    以及整帧 Lab 均值差（首帧 vs 片子第 0 帧，看是不是整体偏色）。"""
    if not first_frame:
        return {}
    fp = ROOT / first_frame if not Path(first_frame).is_absolute() else Path(first_frame)
    img = cv2.imread(str(fp))
    if img is None:
        return {"hair_note": f"首帧读不到 {first_frame}"}
    img = cv2.cvtColor(cv2.resize(img, (768, 1344), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB)
    faces = R.Faces()
    fr = R.decode(path, None, None, 768, 1344, "bt709")

    def hair_stats(rgb):
        fs = [fc for fc in faces.detect(rgb, small=True) if float(fc[3]) >= 30]
        if not fs:
            return None
        best = max(fs, key=lambda f: R.blue_hair_share(rgb, f))
        px = _hair_px(rgb, best)
        if len(px) < 200:
            return None
        return np.median(px.astype(np.float32), axis=0)

    ref = hair_stats(img)
    # 同时记录相对林晚身份参考（项目方挑定的脸部裁切）的发色差：区分“视频改了颜色”和“首帧本身就偏了”
    idp = ROOT / "data/assets/identity_refs/lin_wan/lin_wan_face_ref2va.png"
    idimg = cv2.imread(str(idp))
    idh = hair_stats(cv2.cvtColor(idimg, cv2.COLOR_BGR2RGB)) if idimg is not None else None
    lab0 = R.lab_of(img).reshape(-1, 3).mean(0)
    labc = R.lab_of(fr[0]).reshape(-1, 3).mean(0)
    out = {"frame0_dLab": [round(float(x), 2) for x in (labc - lab0)], "frame0_dE": round(float(np.linalg.norm(labc - lab0)), 2)}
    if ref is None:
        out["hair_note"] = "首帧没有检出蓝色发丝（非林晚 / 背影 / 特写无头发）"
        return out
    rows = [(i, hair_stats(fr[i])) for i in range(0, len(fr), 6)]
    rows = [(i, h) for i, h in rows if h is not None]
    if not rows:
        out["hair_note"] = "片子里没检出蓝色发丝"
        return out
    allh = np.array([h for _, h in rows])
    head = np.array([h for i, h in rows if i < 12] or [rows[0][1]])
    tail = np.array([h for i, h in rows if i >= len(fr) - 12] or [rows[-1][1]])
    med = np.median(allh, axis=0)
    out.update({"hair_first_hsv": [round(float(x), 1) for x in ref], "hair_clip_hsv": [round(float(x), 1) for x in med],
                "hair_head_hsv": [round(float(x), 1) for x in np.median(head, 0)],
                "hair_tail_hsv": [round(float(x), 1) for x in np.median(tail, 0)],
                "hair_dH": round(float(med[0] - ref[0]), 1), "hair_dS": round(float(med[1] - ref[1]), 1),
                "hair_dV": round(float(med[2] - ref[2]), 1), "hair_frames": len(rows),
                **({"hair_idref_hsv": [round(float(x), 1) for x in idh],
                    "hair_first_vs_idref_dS": round(float(ref[1] - idh[1]), 1),
                    "hair_first_vs_idref_dV": round(float(ref[2] - idh[2]), 1)} if idh is not None else {})})
    return out


HAND_PY = "/root/work/fredw/venv_hand/bin/python"
IDM_PY = "/root/work/fredw/venv_idm/bin/python"


def shot_meta_for(path: Path) -> dict:
    """V6 / V7 需要的镜头信息（在画人数、对白、独白、说话人参考）：按文件名的镜号从 jobs.json / validate_jobs.json 取"""
    sid = path.name.split("__")[0]
    vid = ROOT / "data/pipeline/runs/series10_v1/video"
    for jf in ("jobs.json", "validate_jobs.json"):
        try:
            for sh in json.loads((vid / jf).read_text(encoding="utf-8"))["shots"]:
                if sh["shot"] == sid:
                    return {"people": max(1, len(sh.get("visible") or [])), "dialogue": sh.get("dialogue") or [],
                            "voiceover": sh.get("voiceover"), "refs": sh.get("score_refs") or {}, "visible": sh.get("visible") or []}
        except (OSError, ValueError, KeyError):
            continue
    return {}


SAYS = re.compile(r"At (\d{2}):(\d{2}(?:\.\d+)?),(?:(?!At \d{2}:)[^<])*?says:\s*<d>(?:\[[^\]]*\]\s*)?([^<]*)</d>")


def dialogue_windows(prompt: str, pad: float = 0.5, per_char: float = 0.3) -> list:
    """VQAGATE 11-02（VIDEO-RCA r3）：从编译稿的分拍时间码取台词时段——“At mm:ss.sss, … says: <d>…</d>”起点 −pad，
    到 min(下一拍时间码, 起点 + 字数 × per_char + 0.6) + pad。V7 只在这些时段算嘴部开合与声音的相关"""
    stamps = sorted(int(m.group(1)) * 60 + float(m.group(2)) for m in STAMP.finditer(prompt or ""))
    out = []
    for m in SAYS.finditer(prompt or ""):
        t = int(m.group(1)) * 60 + float(m.group(2))
        nxt = next((x for x in stamps if x > t + 1e-3), None)
        end = t + per_char * len(re.sub(r"\W", "", m.group(3))) + 0.6
        out.append([max(0.0, t - pad), (min(end, nxt) if nxt else end) + pad])
    return out


SPEECH_PY = "/root/work/fredw/speech/venv/bin/python"


def asr_windows(path: Path) -> list:
    """SenseVoice 回听拿台词实际时段（tools/series10_video/v7_asr.py）；跑不了 / 没听到字 → []"""
    import subprocess
    try:
        r = subprocess.run(["nice", "-n", "15", SPEECH_PY, str(ROOT / "tools/series10_video/v7_asr.py"), str(path)],
                           capture_output=True, text=True, timeout=600)
        ln = [x for x in r.stdout.splitlines() if x.startswith("{")]
        return (json.loads(ln[-1]).get("windows") or []) if ln else []
    except Exception:  # noqa: BLE001
        return []


def v67(path: Path, prompt: str = "") -> dict:
    """GEN_CONTRACT V6（v6_limbs.py，venv_hand）/ V7（v7_lipsync.py，venv_idm），低优先级子进程；跑不了记“未测”"""
    import subprocess
    m = shot_meta_for(path)
    # 台词时段：先用回听时间戳（SenseVoice，speech venv），没听到 / 跑不了才用分拍时间码兜底（总调度 11-02）
    if [d for d in m.get("dialogue") or [] if not d.get("off")]:
        aw = asr_windows(path)
        if aw:
            m["dialogue_windows"], m["window_source"] = aw, "asr"
    if prompt and not m.get("dialogue_windows"):
        m["dialogue_windows"], m["window_source"] = dialogue_windows(prompt), "stamps"
    out = {}
    for key, py, script in (("v6", HAND_PY, "v6_limbs.py"), ("v7", IDM_PY, "v7_lipsync.py")):
        try:
            r = subprocess.run(["nice", "-n", "15", py, str(ROOT / "tools/series10_video" / script), str(path),
                                json.dumps(m, ensure_ascii=False)], capture_output=True, text=True, timeout=1800)
            ln = [x for x in r.stdout.splitlines() if x.startswith("{")]
            out.update(json.loads(ln[-1]) if ln else {key: {"status": "未测", "why": "检测器出错：" + r.stderr[-200:]}})
        except Exception as e:  # noqa: BLE001
            out[key] = {"status": "未测", "why": f"检测器出错：{e}"[:200]}
    return out


def v9_vlm(path: Path, meta: dict) -> dict:
    """GEN_CONTRACT V9（VQA 11-01，R11-4/5）：本地看图模型（gpu36 Qwen3-VL-8B，127.0.0.1:8870 或 ssh gpu36 管道）复核抽帧。
    只记录，不进闸门；帧图不出自家机器（K-VQA-001）。连不上 / 忙 → {"error"}，记“未测”"""
    try:
        sys.path.insert(0, str(ROOT / "services/agent"))
        if _os.name != "nt":            # 服务器上：gpu36 本机 8870 不通时走 gpu36 内网入口（NETFIX K-OPS-N03，client._lan_url 要 VQA_LAN=1）
            _os.environ.setdefault("VQA_LAN", "1")
        from ns_agent.vqa import client as VC
        refs = [p for p in [meta.get("first_frame"), *((meta.get("refs") or {}).values())] if p]
        refs = [str(ROOT / p) if not Path(p).is_absolute() else p for p in refs]
        return VC.inspect_video(str(path), meta.get("prompt") or "", references=refs, wait_s=600)
    except Exception as e:  # noqa: BLE001
        return {"error": f"VQA 调用失败：{e}"[:300]}


def gate(s: dict, refs: dict) -> dict:
    fails, soft = [], []
    if (s.get("mean") or 0) < GATE["mean_min"]:
        fails.append("动作不足")
    if (s.get("cheek_red_max") or 0) > GATE["cheek_red_max"]:
        fails.append("脸部泛红")
    if len(s.get("cuts") or []) > GATE["cuts_max"]:
        fails.append("镜内硬切")
    low = []
    for n in refs:
        it = (s.get("identity") or {}).get(n) or {}
        if it.get("sface_med") is None or (it.get("seen") or 0) < GATE["seen_min"]:
            low.append(f"{n}没出脸")
        elif it["sface_med"] < GATE["sface_min"]:
            low.append(f"{n}{it['sface_med']}")
    if low:
        fails.append("身份偏离")
    want = SIZE_IDX.get(s.get("size_wanted") or "")
    if want is not None and s.get("face_h_med") is not None and abs(size_class(s["face_h_med"]) - want) >= 2:
        fails.append("景别不符")
    # 总调度 11-01 23:0x：多肢要 V6 手数规则命中 + 看图 extra_limbs = defect 两者都成立才判不过；只有一方命中只记录
    v6_hit = (s.get("v6") or {}).get("status") == "不通过"
    vlm_limb = "extra_limbs" in ((s.get("vlm") or {}).get("defects") or [])
    if v6_hit and vlm_limb:
        fails.append("多肢")
    elif v6_hit or vlm_limb:
        soft.append("多肢（只记录：" + ("V6 命中、看图没确认" if v6_hit else "看图命中、V6 没命中") + "）")
    if (s.get("v7") or {}).get("status") == "不通过":
        fails.append("口型不合")
    ac = s.get("acting") or {}
    for key, label in (("first_sec", "开头定格 / 看镜头"), ("camera_gaze", "看镜头"), ("caption", "疑似字幕")):
        v = ac.get(key) or {}
        hit = v.get("suspect") if key == "caption" else (v.get("status") or "").startswith("疑似")
        if hit:   # 只记录：标定前写进 soft，不进 fails（ACTING；BLOCK 由总调度批准后打开）
            (fails if ac.get("block") else soft).append(f"{label}（{v.get('status') or v.get('hits')}）")
    if (s.get("J4") or 0) > GATE["J4_soft"]:
        soft.append("4 帧一顿（合成去抖）")
    vf, vs = vlm_fails(s.get("vlm"))         # VQAGATE（D-VQA-01）：本地看图 V9 的 blocking 缺陷进 fails（enforce 关 = 只进 soft）
    fails += [x for x in vf if x not in fails]
    soft += vs
    return {"pass": not fails, "fails": fails, "identity_low": low, "soft": soft}


VLM_LABEL = {"eye_contact": "看镜头", "first_frame_stare": "看镜头", "posed_stiff": "摆拍", "blank_expression": "第二人无表情",
             "continuity_break": "跨镜不连贯", "hair_mismatch": "发色不符", "temporal_outfit": "片内换装", "outfit_mismatch": "服装不符",
             "extra_limbs": "多肢", "extra_person": "多人", "framing_mismatch": "景别不符", "underage_look": "未成年外观"}


def vlm_fails(v: dict | None) -> tuple[list, list]:
    """V9 判定 → (fails 标签, soft 标签)。blocking 名单 / enforce 都读 config/vqa.json（同出图 Q9 一套）；没看成 = 不加（记 vlm.error）"""
    if not v or v.get("error"):
        return [], []
    try:
        cfgp = ROOT / "config" / "vqa.json"
        c = json.loads(cfgp.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [], []
    allc = {**(c.get("checks") or {}), **(c.get("video_checks") or {})}
    enf = bool((c.get("gate") or {}).get("enforce")) and bool((c.get("judge") or {}).get("enforce"))
    f, so = [], []
    for d in v.get("defects") or []:
        lab = VLM_LABEL.get(d, d)
        blk = (allc.get(d) or {}).get("blocking") and (enf or d == "underage_look")
        if d == "first_frame_stare":
            blk = enf and (allc.get("eye_contact") or {}).get("blocking")
        if d == "extra_limbs":
            continue                       # 多肢在 gate() 里和 V6 一起判（两者都命中才拦）
        (f if blk else so).append(lab if blk else f"看图：{lab}")
    return list(dict.fromkeys(f)), list(dict.fromkeys(so))


def penalty(s: dict, g: dict) -> float:
    """挑“尽力”版本用：越小越好（只按测得的像素指标）"""
    p = 3.0 * len(g["fails"])
    p += max(0.0, 0.5 - (s.get("mean") or 0)) * 4
    p += max(0.0, (s.get("cheek_red_max") or 0) - 0.25) * 6
    p += 2.0 * len(s.get("cuts") or [])
    ids = [(it or {}).get("sface_med") or 0.0 for it in (s.get("identity") or {}).values()]
    if ids:
        p += max(0.0, 0.45 - min(ids)) * 5
    p += max(0.0, (s.get("J4") or 1.0) - 1.3) * 2
    return round(p, 3)


def main(argv):
    path, sheet_p, meta = Path(argv[0]), Path(argv[1]), json.loads(argv[2])
    refs = meta.get("refs") or {}
    mq = MQ.video_motion(path, MQ.thresholds(ROOT / "config" / "render_quality.json"))
    mm = mq.get("metrics") or {}
    jm, _ = MJ.analyze(path)
    hc = CC.hist_cuts(path, 24.0)
    stamps = [int(m.group(1)) * 60 + float(m.group(2)) for m in STAMP.finditer(meta.get("prompt") or "")]
    ir = identity_and_red(path, refs)
    try:
        hc_ = hair_and_colour(path, meta.get("first_frame"))
    except Exception as e:  # noqa: BLE001
        hc_ = {"hair_note": f"发色测量失败：{e}"[:200]}
    LS.sheet(path, sheet_p)
    try:   # ACTING 11-01（R11-2 / R11-8）：首秒定格 / 看镜头 / 字幕带——只记录（ns_qc.gaze.BLOCK=False，标定前不进 gate）
        from ns_qc import gaze as GZ
        acting = GZ.video_checks(path)
        acting.pop("gaze_samples", None)
    except Exception as e:  # noqa: BLE001
        acting = {"status": "未测", "why": f"视线 / 定格检测出错：{e}"[:200]}
    s = {"verdict": mq.get("verdict"), "labels": mq.get("labels"), "mean": mm.get("mean_diff"),
         "still": mm.get("still_frac"), "tail_s": mm.get("frozen_tail_s"), "head_s": mm.get("frozen_head_s"),
         "jump_cut_s": mm.get("cut_s"), "J4": round(jm["J4"], 3), "J4_z": round(jm["J4_z"], 2),
         "pace": jm["pace_px_per_frame"], "cuts": hc,
         "cuts_near_stamps": [c for c in hc if any(abs(c - t) <= 0.5 for t in stamps)], "stamps": stamps,
         "size_wanted": meta.get("size"), **ir, **hc_, **v67(path, meta.get("prompt") or ""), "acting": acting}
    s["vlm"] = v9_vlm(path, meta)          # VQAGATE：先看图，再算 gate（blocking 缺陷进 fails，D-VQA-01）
    g = gate(s, refs)
    s["gate"] = g
    s["penalty"] = penalty(s, g)
    print(json.dumps(s, ensure_ascii=False, default=float))


if __name__ == "__main__":
    main(sys.argv[1:])
