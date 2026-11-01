"""IMGFIX（总调度 fredw-2b 派，11-01 19:4x）：出图两个系统性根因的对照实验台。

根因 1 外套缺失：现行造型 A 设定图（sheets_chosen = lin_wan_lookA_s101，10-31 v1 候选）上没有画短款西装外套，
          提示词却要求“服装必须与图2完全一致”，同时图3 参考板又要求外套 → 冲突，图2（真人 + 更强措辞）赢。
根因 2 单人看镜头：见 docs/video_rca/RCA_r1.md C1。

每臂只改一个因素（提示词句 / 参考槽），同 seed；出图走生产唯一出图路径 ns_render.unified_frame.build_graph
（frame_v9 = S★，参数不动），本机道 laptop:0；scope=ab：图只进 data/ab/imgfix/，不写 takes.json / 契约账本。
度量：gaze_mp（Q9 旁证，命中 = 高置信度正对镜头）、YuNet 视线、sface（对现行身份脸）、
     Q2 外套存在性（gen_contract 同一探针 outer_presence + config outer_probes，线 0.3）。

    .venv/Scripts/python.exe tools/imgfix/ab.py run ep01-S1,ep01-S2 --arms A0,P1,F2 --seeds job,job+100 [--tag r1]
    .venv/Scripts/python.exe tools/imgfix/ab.py page
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/localgpu"))
import identity_gaze_ab as IG  # noqa: E402

OUT = ROOT / "data/ab/imgfix"
LOG = OUT / "takes.jsonl"
FACE_LINE_OLD = "图1是林晚的脸部参考（只取脸和发型）"
SHEET_V2 = "data/pipeline/runs/series10_v1/images/refcrops/lin_wan_lookA_v2_s202_{panel}.png"


def _target(job: dict) -> str:
    """视线落点：只取剧本原文（出图正文里已有的“视线落在 / 朝 …”），不自己编"""
    p = job["prompt"]
    m = re.search(r"视线(?:落在|朝|看向|停在|转向)([^，。；]{1,20})", p)
    return (m.group(1).strip() if m else "画面里的人或物")


def arm_apply(job: dict, arm: str) -> dict:
    p, refs = job["prompt"], list(job["refs"])
    name = "林晚"
    t = _target(job)
    if arm in ("A0", "ACC", "ACC2", "ACC3", "ACC4", "ACC5", "K705"):        # ACC = 验收（朝向句在身份脸句后，作废）；ACC2 = 验收（朝向句在最前），都是重编后的生产作业原样
        pass
    elif arm == "P1":                       # “平视”（机位词）→ 明确是机位高度，不是人物眼睛平视前方
        p = re.sub(r"平视(?!机位)", "平视机位（镜头与眼睛同高）", p)
    elif arm in ("F2", "F2acc"):            # F2acc = 在重编后的生产作业（已含 K-REN-704 + K-AST-262）上再加 F2                       # 视线正向落点句放最前
        p = f"{name}的眼睛看着{t}，头和视线都朝向{t}，眼睛不看镜头。" + p
    elif arm == "T3":                       # 四分之三侧脸构图句放最前
        p = f"{name}四分之三侧脸，脸转向{t}一侧，脸和身体都不正对镜头。" + p
    elif arm == "T5":                       # 轻侧脸（约三十度）+ 落点，一句
        p = f"{name}的脸微微侧向{t}（约三十度），眼睛看着{t}，不看镜头。" + p
    elif arm == "M1":                       # 折中：生产终版里“四分之三侧脸”句换成“脸微侧”句（落点句不动）
        m = re.search(r"林晚四分之三侧脸，脸转向([^。]{1,40})一侧，脸和身体都不正对镜头。", p)
        if not m:
            raise SystemExit(f"{job['shot']} 没有 K-REN-704 朝向句")
        p = p.replace(m.group(0), f"林晚的脸微微侧向{m.group(1)}，不正对镜头。")
    elif arm == "R4":                       # 图1 只取身份
        p = p.replace(FACE_LINE_OLD, "图1是林晚的脸部参考（只取五官身份和发型，不取图1的视线、头部角度和朝向）")
    elif arm == "O1":                       # 造型图换成 ASSETMASTER 已通过单品一致性检查的 v2_s202（画了外套）
        m = re.search(r"lin_wan_lookA_s\d+_(\w+)\.png$", refs[1])
        if not m:
            raise SystemExit(f"{job['shot']} refs[1] 不是林晚造型 A 设定图裁切：{refs[1]}")
        refs[1] = SHEET_V2.format(panel=m.group(1))
    elif arm == "O2":                       # 设定图缺的外层单品让位给参考板（= asset_refs.SHEET_GAP_CLAUSE 生产原句，K-AST-262）
        from ns_agent import asset_refs as AR
        old = "（款式、颜色、材质、细节），背景与姿势不取。图3"
        new = "（款式、颜色、材质、细节），背景与姿势不取" + AR.SHEET_GAP_CLAUSE.format(n=2, items="短款西装外套", src="图3") + "。图3"
        if AR.SHEET_GAP_CLAUSE.format(n=2, items="短款西装外套", src="图3") in p:
            pass                            # 作业已按 K-AST-262 重编
        elif old not in p:
            raise SystemExit("图2 句不在提示词里")
        else:
            p = p.replace(old, new, 1)
    elif "+" in arm:                        # 组合：A+B
        j = job
        for a in arm.split("+"):
            j = arm_apply(j, a)
        return j
    else:
        raise SystemExit(f"未知臂 {arm}")
    return {**job, "prompt": p, "refs": refs}


def load_job(sid: str) -> dict:
    """同 IG.load_job，但不要求图1是林晚（多人镜 / 顾沉主镜，总调度 11-02 指定 ep02-S4 / S1 验证）。
    集级 intimate_ep 标记不挡：只出总调度点名的镜头，镜头本身不是亲密内容（电梯里按按钮 / 特写侧脸）"""
    jobs = json.loads(IG.JOBS.read_text(encoding="utf-8"))["jobs"]
    j = next(x for x in jobs if x["shot"] == sid)
    if j.get("intimate_ep") and sid not in ALLOW_INTIMATE_EP:
        raise SystemExit(f"{sid} 是亲密集镜头，不出")
    return j


ALLOW_INTIMATE_EP = {"ep02-S4", "ep02-S1"}


def lane_idle() -> bool:
    try:
        q = json.loads(urllib.request.urlopen(IG.URL + "/queue", timeout=10).read())
        # 本机道 19:4x 起归 IMGFIX（总调度派）；别的实验脚本跑完一张马上交下一张，“队列全空”永远等不到 →
        # 只要没有排队（pending）就交，排在正在跑的那张后面（对方的让道检查看到 pending 就会让）
        return not q["queue_pending"]
    except Exception:  # noqa: BLE001
        return False


def render(job: dict, tag: str, seed: int) -> dict:
    from ns_render import image_params as IP
    from ns_render import unified_frame as UF
    from ns_render.comfy_client import ComfyClient
    sid = job["shot"]
    d = OUT / sid
    d.mkdir(parents=True, exist_ok=True)
    client = ComfyClient(IG.URL)
    up = lambda p: client.upload_image(p, subfolder="ns_ab/imgfix")  # noqa: E731
    wf, eff, sent = UF.build_graph(job, seed, up, f"ns_ab/imgfix/{sid}_{tag}_s{seed}")
    t0 = time.time()
    entry, secs = client.run(wf, timeout_s=1800)
    item = next(f for f in client.output_files(entry) if f["filename"].endswith(".png"))
    raw = d / f"{sid}_{tag}_s{seed}_raw.png"
    client.download(item, raw)
    post = IP.post_file(raw, eff)
    return {"file": str(Path(post["path"]).relative_to(ROOT)).replace("\\", "/"),
            "comfy_s": round(secs, 1), "wall_s": round(time.time() - t0, 1), "prompt": sent, "refs": job["refs"]}


def outer_q2(img_path: Path) -> float | None:
    """Q2 外套存在性：与 gen_contract 同一探针（metrics.outer_presence + config outer_probes['短款西装外套']）"""
    import cv2
    from PIL import Image
    from ns_agent.gen_contract import metrics as GM
    from ns_agent.gen_contract.postflight import cfg
    from ns_qc import face as QF
    m = IG.face_models()
    bgr = cv2.imread(str(img_path))
    f = QF.largest(m.faces(bgr)) if m is not None else None
    if f is None:
        return None
    x, y, w, h = [float(v) for v in f[:4]]
    probes = ((cfg().get("image_thresholds") or {}).get("Q2_outfit") or {}).get("outer_probes") or {}
    pr = probes.get("lin_wan:短款西装外套") or probes.get("短款西装外套")
    v = GM.outer_presence(Image.open(img_path).convert("RGB"), (x, y, x + w, y + h), "blazer jacket", pr)
    return None if v is None else round(float(v), 3)


def run(shots: list[str], arms: list[str], seed_spec: str, tag: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    done = set()
    if LOG.exists():
        for ln in LOG.read_text(encoding="utf-8").splitlines():
            r = json.loads(ln)
            done.add((r["shot"], r["arm"], r["seed"]))
    for sid in shots:
        base = load_job(sid)
        for seed in IG.seeds_for(base, seed_spec):
            for arm in arms:
                if (sid, arm, seed) in done:
                    continue
                j = arm_apply(base, arm)
                while not lane_idle():
                    print("让道：本机道有任务", flush=True)
                    time.sleep(3)
                r = render(j, arm.replace("+", "_"), seed)
                met = IG.measure(ROOT / r["file"])
                met["q2_jacket"] = outer_q2(ROOT / r["file"])
                rec = {"scope": "ab", "experiment": "imgfix", "round": tag, "shot": sid, "arm": arm, "seed": seed, **r,
                       "metrics": met, "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
                with LOG.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                print(json.dumps({"shot": sid, "arm": arm, "seed": seed, "s": r["comfy_s"], "gaze_hit": met["gaze_mp_hit"],
                                  "gscore": met["gaze_mp_score"], "yunet": met["yunet_gaze"], "sface": met["sface_vs_face_A"],
                                  "q2": met["q2_jacket"]}, ensure_ascii=False), flush=True)


SIDE_REF = "data/ab/identity_gaze_ab/refs/lin_wan_face_side_A_s202.png"   # 同一张设定图 A-s202 侧视栏裁的侧脸（LOCALGPU）


def sface_side(img_path: Path) -> float | None:
    """同人侧脸参考的 sface（SFace 对正脸参考随头部转角下降；转开的脸另对同人侧脸参考量，取两者较大值作身份判断）"""
    import cv2
    from ns_qc import face as QF
    m = IG.face_models()
    ref, bgr = cv2.imread(str(ROOT / SIDE_REF)), cv2.imread(str(img_path))
    fr, fi = QF.largest(m.faces(ref)), QF.largest(m.faces(bgr))
    if fr is None or fi is None or float(fi[3]) < QF.MIN_FACE_PX:
        return None
    return round(QF.cosine(m.embed(ref, fr), m.embed(bgr, fi)), 3)


def backfill() -> None:
    rows = [json.loads(x) for x in LOG.read_text(encoding="utf-8").splitlines() if x.strip()]
    for r in rows:
        if "sface_side" not in r["metrics"]:
            r["metrics"]["sface_side"] = sface_side(ROOT / r["file"])
    LOG.write_text("".join(json.dumps(r, ensure_ascii=False) + chr(10) for r in rows), encoding="utf-8")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    a = sys.argv
    if a[1] == "run":
        if "--url" in a:                     # 服务器道（生产优先时实验改走服务器，scope=ab）
            IG.URL = a[a.index("--url") + 1]
        if "--jobs" in a:                    # 预览作业（未写回 first_frame_jobs.json，总调度 21:5x：导入新剧本后再统一重编）
            IG.JOBS = ROOT / a[a.index("--jobs") + 1]
        run(a[2].split(","), a[a.index("--arms") + 1].split(","), a[a.index("--seeds") + 1] if "--seeds" in a else "job",
            a[a.index("--tag") + 1] if "--tag" in a else "r1")
    elif a[1] == "backfill":
        backfill()
