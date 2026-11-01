"""Postflight（出图后，自动质检）：docs/GEN_CONTRACT.md §2 Q1–Q7，全部量化；没测到的项 = untested（不算通过，不得冒充通过）。

数据来源：
- Q1 身份 / Q3 景别 / Q6 文字：出图机器上的 tools/series10_imggen/score_remote.py（insightface buffalo_l = tools/identity_metric.py
  同模型；rapidocr）。参考名用角色 id（lin_wan / gu_chen / chen_yu / ch_a_lan），本模块读它的输出（remote=items[id]，cross=输出的 cross）。
- Q5 坏手 / 多肢：tools/series10_imggen/hands_remote.py 的输出（hands=items[id]）。
- Q2 造型 / Q4 质感 / Q7 场景：本机算（measure_local）：CLIP ViT-L/14（本机 HF 缓存 openai/clip-vit-large-patch14，不新下模型）
  按单品所在区域滑窗取最高相似度 + HSV 颜色直方图；质感 = 脸部区域 Laplacian 方差、高频能量占比、饱和度 p95、皮肤镜面高光占比（“油”）。
阈值：config/gen_contract.json image_thresholds（K-REV-230、K-REV-231，带证据）。
"""
from __future__ import annotations

import re

import sys
import types
from functools import lru_cache
from pathlib import Path

import numpy as np

from . import ROOT, ContractResult, Item, cfg

TITLES = {"Q8": "林晚发色（相对身份参考与同帧肤色亮度）", "Q1": "身份余弦（ArcFace）", "Q1a": "逐人头发属性（发色 / 发长，对人物卡）", "Q2": "造型一致（服装 / 鞋 / 饰品区域相似度 + 颜色直方图）", "Q3": "景别符合度（脸高档位）",
          "Q4": "真人质感 / 油光", "Q5": "坏手 / 多肢 / 多人", "Q6": "文字 / 水印", "Q7": "场景一致",
          "G1": "演员看镜头（只记录，ACTING R11-2）"}


def gaze_item(image) -> tuple[str, str, dict]:
    """ACTING 11-01（项目方 R11-2“演员的眼睛不要看镜头”）：YuNet 五点头部朝向 + 眼球偏移估视线（packages/qc/ns_qc/gaze.py）。
    标定前只记录（status 恒为 na，evidence.would_fail）；ns_qc.gaze.BLOCK=True（总调度批准、标定分得开）后才判 fail。没检出脸 = 未测"""
    try:
        qc = str(ROOT / "packages" / "qc")
        if qc not in sys.path:
            sys.path.insert(0, qc)
        import cv2
        from ns_qc import gaze as GZ
        bgr = cv2.imread(str(image))
        if bgr is None:
            return "untested", "读不到图", {}
        r = GZ.image_gaze(bgr)
    except Exception as e:  # noqa: BLE001
        return "untested", f"视线检测出错：{e}"[:160], {}
    ev = {"gaze": r.get("status"), "faces": [{k: f.get(k) for k in ("iod", "yaw_n", "pitch_n", "iris_dx", "gaze_x", "status")}
                                             for f in r.get("faces") or []][:4], "provisional": GZ.PROVISIONAL}
    if r["status"] == "未测":
        return ("untested" if GZ.BLOCK else "na"), f"未测（{r.get('why')}）", ev
    bad = r["status"] == "疑似看镜头"
    if GZ.BLOCK:
        return ("fail" if bad else "pass"), r["status"], ev
    return "na", f"只记录（未标定，不阻断）：{r['status']}", {**ev, "would_fail": bad, "record_only": True}
SIZE_BAND = {"极近特写": 0, "大特写": 0, "特写": 1, "近景": 2, "中近景": 2, "中景": 3, "中全景": 4, "全身": 5, "全景": 5,
             "远景": 6, "大远景": 6}
NAME_ID = {"林晚": "lin_wan", "顾沉": "gu_chen", "陈宇": "chen_yu", "阿岚": "ch_a_lan"}
from .metrics import (ZONE_REGION, _clip, _ref_crop, embed, hist_corr, hs_hist, measure, region_match,  # noqa: E402,F401
                      texture, windows)


def q1a_item(image, boxes: dict, all_boxes: list, t1a: dict) -> tuple[str, str, dict]:
    """Q1a：每个在画角色那张脸的头发（分割 + 头顶连通域）对人物卡（Q1a_attr.cards）。→ (status, detail, evidence)
    分割不可用 → untested（q1a_mode=unavailable，producer 记 score_infra 只重打分；SENTINEL 探针读 q1a_mode），不静默放过"""
    cards = t1a.get("cards") or {}
    todo = {c: b for c, b in boxes.items() if c in cards and b}
    if not todo:
        return "na", "没有要核对头发的在画角色脸", {"q1a_mode": "na"}
    if not Path(str(image)).exists():
        # 只给了打分元数据、没有图像文件（单测 / 旧调用）：判不了，明写 no_image（生产 producer 一定传真实文件）
        return "na", "没有图像文件，头发属性未判", {"q1a_mode": "no_image"}
    from ..vqa import hair_attr as HA
    others = [b for b in all_boxes if b not in todo.values()]
    order = list(todo.values()) + others
    try:
        fs = HA.measure(image, order)
    except HA.Unavailable as e:
        return "untested", f"头发分割不可用：{e}", {"q1a_mode": "unavailable", "why": str(e)[:200]}
    bad, per = [], {}
    for (c, _b), f in zip(todo.items(), fs):
        per[c] = f
        bad += HA.judge(c, f, cards[c])
    ok_txt = "头发符合人物卡（" + "、".join(f"{cards[c].get('name', c)} 蓝 {f['hair_blue']:.2f} / 下长 {f['below']:.2f}" for c, f in per.items()) + "）"
    return ("fail" if bad else "pass"), ("；".join(bad) if bad else ok_txt), {"per_person": per, "q1a_mode": "seg", "boxes": todo}


def apply_bank(sims: dict, t1: dict) -> dict:
    """身份库 top-k（VQAGATE 11-02，L-098）：sims 里 "<cid>@bN" 是库帧的相似度，"<cid>" 是锚（L-086）。
    锚 ≥ 复核下限（三段线下限，默认 0.50）时，有效分 = 锚 + 库帧里前 k 个的平均；锚低于下限 → 有效分就是锚（库不帮忙，防带偏）。
    返回去掉 @bN 键、cid 键换成有效分的新 dict；原始锚分留在 "<cid>@anchor"（只记录，_merge_refs 不会拿它取高）"""
    k = int((t1.get("bank") or {}).get("k", 3))
    lo = float((t1.get("bank") or {}).get("anchor_min", 0.50))
    out = {key: v for key, v in sims.items() if "@b" not in key}
    for cid in [c for c in out if "@" not in c]:
        anchor = out.get(cid)
        bank = sorted((v for key, v in sims.items() if key.startswith(cid + "@b") and v is not None), reverse=True)
        if anchor is None or not bank:
            continue
        out[cid + "@anchor"] = anchor
        if anchor >= lo:
            top = sorted([anchor] + bank, reverse=True)[:k]
            out[cid] = round(float(sum(top) / len(top)), 4)
    return out


def _merge_refs(sims: dict) -> dict:
    """{"lin_wan": .8, "lin_wan@master": .85, "gu_chen": .1} → {"lin_wan": (.85, "lin_wan@master"), "gu_chen": (.1, "gu_chen")}"""
    out: dict = {}
    for k, v in sims.items():
        base = k.split("@", 1)[0]
        if base not in out or v > out[base][0]:
            out[base] = (v, k)
    return out


def band(h: float, bands) -> int:
    for i, b in enumerate(bands):
        if h >= b:
            return i
    return len(bands)


# ---------------------------------------------------------------- CLIP（本机）
# ---------------------------------------------------------------- 本机测量
def q2_rows(rec: dict) -> list[dict]:
    """要测的 Q2 行（与服务器版同一份选择逻辑）：本镜参考里的单品 / 设定图，去掉第二人与只记录不判的区域"""
    ro = (((cfg().get("image_thresholds") or {}).get("Q2_outfit") or {}).get("record_only_zones") or [])
    rows = []
    for s in rec.get("slots") or []:
        for m in s.get("members") or []:
            if m.get("role") not in ("item", "sheet") or not m.get("file") or m.get("secondary"):
                continue
            if m.get("role") == "item" and (m.get("zone") or "") in ro:
                continue                                  # K-REV-231：只记录不判的区域不算
            rows.append({"label": m.get("label"), "role": m["role"], "zone": m.get("zone"), "source": m.get("source"),
                         "file": m["file"], "ref": m["file"]})
    return rows


# 外层单品（总调度 11-01 P：ep01 S1–S3 林晚造型 A 没穿短款西装外套也过了 Q2——上身区单品只记录）。存在性探针，不比颜色。
OUTER_EN = (("西装裙", None), ("西装裤", None), ("西装外套", "blazer jacket"), ("西装", "suit jacket"), ("风衣", "long trench coat"),
            ("大衣", "overcoat"), ("皮衣", "leather jacket"), ("夹克", "jacket"), ("工装", "utility work jacket"),
            ("围裙", "apron"), ("开衫", "cardigan"), ("披肩", "shawl"), ("外套", "jacket"))


def outer_en(label: str) -> str | None:
    """外层单品（穿在别的衣服外面）的英文名；“西装裙 / 西装裤”不是外层"""
    return next((en for zh, en in OUTER_EN if zh in (label or "")), None)


def outer_rows(rec: dict, project: str = "series10_v1") -> list[dict]:
    """本镜要查“穿没穿”的外层单品：每个在画角色（含原文写到脸的局部角色）本镜造型里的外层服装，上身 / 全身区可见时。
    脸框按角色各自配（remote_score._FULL / metrics.outer_rows_with_faces）"""
    zones = set(rec.get("zones") or [])
    if not zones & {"upper", "body"}:
        return []
    try:
        from ns_agent import asset_refs as AR
        looks = AR.load_looks(project)
    except Exception:  # noqa: BLE001
        return []
    out = []
    for c in rec.get("characters") or []:
        cid = c.get("character")
        if not cid or not c.get("look") or not (c.get("presence", "在画") == "在画" or c.get("face_described")):
            continue
        L = (looks.get(cid) or {}).get(c["look"])
        for p in (L.parts if L else []):
            en = outer_en(p.label) if p.slot == "outfit" and not p.extra else None
            if en:
                probes = ((cfg().get("image_thresholds") or {}).get("Q2_outfit") or {}).get("outer_probes") or {}
                pr = probes.get(f"{cid}:{p.label}") or probes.get(p.label)
                out.append({"character": cid, "label": p.label, "en": en, "look": c["look"], **({"probe": pr} if pr else {})})
        # 发型锁（总调度 11-01：顾沉被画成长发 Q7-26/32/34/40/46，身份分照样过）——同一套“存在性”探针，裁头部
        for key, row in ((((cfg().get("image_thresholds") or {}).get("Q2_outfit") or {}).get("hair_probes") or {}).items()):
            if key.split(":")[0] == cid and isinstance(row, list):
                out.append({"character": cid, "label": key.split(":", 1)[1], "en": "hair", "look": c["look"], "probe": row,
                            "region": "head", "kind": "hair"})
    return out


def scene_file(rec: dict) -> str | None:
    return next((s["file"] for s in rec.get("slots") or [] if s.get("kind") == "scene"), None) or         next((d["file"] for d in rec.get("dropped") or [] if d.get("role") == "scene"), None)


def measure_local(image: str | Path, rec: dict, remote: dict | None = None) -> dict:
    from PIL import Image
    img = Image.open(image).convert("RGB")
    rows = q2_rows(rec)
    refs = {r["ref"]: Image.open(ROOT / r["file"]).convert("RGB") for r in rows}
    faces = sorted((remote or {}).get("faces") or [], key=lambda f: -((f.get("sims") or {}).get("lin_wan", -1)))   # 林晚的脸优先（Q8）
    sc = scene_file(rec)
    scene = Image.open(ROOT / sc).convert("RGB") if sc and (ROOT / sc).is_file() else None
    from .metrics import outer_rows_with_faces
    out = measure(img, rows, refs, faces[0].get("bbox") if faces else None, scene,
                  outer=outer_rows_with_faces(outer_rows(rec), (remote or {}).get("faces")))
    if out.get("Q7"):
        out["Q7"]["file"] = sc
    return out


# ---------------------------------------------------------------- 判定
def _vqa():
    """VQA（R11-4/5/10）的本地看图复核模块；没装就跳过（Q9 / V9 不出现）"""
    try:
        from ns_agent.vqa import contract as VQ
        TITLES.setdefault("Q9", VQ.TITLE)
        VTITLES.setdefault("V9", VQ.VTITLE)
        return VQ
    except Exception:  # noqa: BLE001
        return None


def band_lines(cid: str, h_ratio: float, t1: dict) -> tuple[float, float, str]:
    """K-REV-V18 修订（总调度 11-02 亲审 q1_band：20 张里 19 张是同一林晚，低分来自侧脸；0.70 单线退役）→ (通过线, 复核下限, 档名)。
    ≥ 通过线 = 过；复核下限 – 通过线 = 本地看图和 L-086 左右并排复核（同一人 + 画风 / 质感 + 清晰度三项全过才放行）；< 复核下限 = 直接不过。
    config Q1_identity.bands = {"default": [[脸高下限, 档名, 通过线, 复核下限], …], 角色: […]}，从大到小"""
    bands = (t1.get("bands") or {})
    rows = bands.get(cid) or bands.get("default") or [[0.10, "近中景及以上", 0.60, 0.50], [0.0, "小脸", 0.50, 0.40]]
    for h_min, name, need, lo in rows:
        if h_ratio >= h_min:
            return float(need), float(lo), name
    h_min, name, need, lo = rows[-1]
    return float(need), float(lo), name


def size_line(h_ratio: float, t1: dict) -> tuple[str, float | None]:
    """脸大小分档的身份线（特写最严）：config Q1_identity.size_tiers = [[脸高下限, 档名, 线], …] 从大到小"""
    for h_min, name, line in t1.get("size_tiers") or [[0.27, "特写", 0.55], [0.10, "近中景", 0.50], [0.04, "小脸", 0.40]]:
        if h_ratio >= h_min:
            return name, float(line)
    return "太小", None


def identity_unexpected(faces: list[dict], req: dict, t1: dict) -> tuple:
    """“不该露脸 / 没有在画角色”的镜头里出现的够大的脸：认得出是 cast 里的人且过分档线才过（K-REV-V18）。→ (status, detail, **evidence)"""
    allowed = {NAME_ID.get(c.get("name"), c.get("name")) for c in req.get("cast") or []}
    rows, bad, boxes = [], [], []
    for f in faces:
        sims = {k: v for k, v in _merge_refs({k2: v2 for k2, v2 in apply_bank(f.get("sims") or {}, t1).items()
                                              if not k2.endswith("@anchor")}).items()}
        best = max(sims, key=lambda c: sims[c][0]) if sims else None
        sim = sims[best][0] if best else None
        tier, line = size_line(float(f.get("h_ratio") or 0), t1)
        if line is None:
            continue
        ok = best in allowed and sim is not None and sim >= line
        rows.append({"best": best, "sim": None if sim is None else round(sim, 3), "tier": tier, "line": line, "h_ratio": f.get("h_ratio"), "ok": ok})
        if not ok:
            bad.append(f"脸高 {float(f.get('h_ratio') or 0):.2f}（{tier}，线 {line}）最像 {best} {0 if sim is None else sim:.3f}"
                       + ("" if best in allowed else "，不在本镜 cast 里"))
            boxes.append(f.get("bbox"))
    if not rows:
        return ("na", "局部 / 空镜：脸都太小，不判身份")
    if bad:
        return ("fail", "画面里多了不该有的人 / 认不出是谁：本镜 cast 写不露脸，但画面里出了脸且不像本人（" + "；".join(bad) + "）",
                {"faces": rows, "strangers": bad, "stranger_boxes": boxes,
                 "partial_cast": any(c.get("presence") in ("局部", "背影") for c in req.get("cast") or []), "unexpected_face": True})
    return ("pass", "cast 写不露脸，但露了的脸认得出是本人（" + "、".join(f"{r['best']} {r['sim']}（{r['tier']}）" for r in rows) + "）",
            {"faces": rows, "unexpected_face": True})


def _q9_item(VQ, v):
    """VQAGATE 11-01（项目方原话转阻断，config/vqa.json gate.enforce）：没有看图结果 = untested（不算通过）；
    blocking 项 defect = fail（VQ 给）。enforce 关掉时回到只记录：没有结果 = 不适用；未成年外观（HC-07）任何时候都不过"""
    st, d, ev = v
    enf = getattr(VQ, "enforced", lambda: False)() and (getattr(VQ, "gate_cfg", dict)() or {}).get("untested_blocks", True)
    if st == "untested" and not enf:
        st, d = "na", f"只记录（没有本地看图结果）：{d}"
    return st, d, ev


def _q9_live(VQ, image, req: dict) -> dict | None:
    """enforce 期笔记本路径（画布重出 / register_takes 等走 UF._postflight 的）：没有缓存判定 → 现场跑一次本地看图（带跨镜连贯参考）。
    只认 data/renders/epNN/SN/takes/ 下的图（镜号从路径取）；远端（gpu33 上的 remote_score）连不上本地服务 → None = untested"""
    try:
        import os
        if not VQ.enforced() or os.name != "nt" or os.environ.get("PYTEST_CURRENT_TEST"):
            # 只在笔记本跑（服务器上的 remote_score 没有本地服务，不能卡住打分）；测试里不连真服务
            return None
        p = Path(str(image)).resolve()
        parts = p.parts
        i = parts.index("renders")
        sid = f"{parts[i + 1]}-{parts[i + 2]}"
        kind = "last" if p.name.startswith("last") else "first"
        refs = VQ.ref_files(req.get("asset_refs") or {})
        return VQ.inspect_for(sid, kind, p, req.get("prompt") or "", refs, wait_s=900)
    except Exception:  # noqa: BLE001
        return None


def evaluate(image: str | Path, req: dict, *, remote: dict | None = None, cross: dict | None = None,
             hands: dict | None = None, local: dict | None = None, vlm: dict | None = None) -> ContractResult:
    th = (cfg().get("image_thresholds") or {})
    rec = req.get("asset_refs") or {}
    items: list[Item] = []

    def add(i, st, d="", **ev):
        items.append(Item(i, TITLES[i], st, d, ev))

    face_visible = rec.get("subject") not in ("part", "object")
    expect = [NAME_ID.get(c.get("name"), c.get("name")) for c in req.get("cast") or [] if c.get("presence") == "在画"]
    # K-AST-236：局部角色原文写到脸 / 头发（asset_refs 给他挂了身份脸）→ 画面里他的脸要过他自己的身份阈值（不只 recognize_floor）；
    # 只写到头发、脸可能不入画，所以不要求“必须出脸”
    described = {c["character"] for c in rec.get("characters") or [] if c.get("face_described")}
    # Q1
    t1 = th.get("Q1_identity") or {}
    big_unexpected = [f for f in (remote or {}).get("faces") or []
                      if (f.get("h_ratio") or 0) >= t1.get("min_face_ratio", 0.04)] if (not face_visible or not expect) else []
    if (not face_visible or not expect) and big_unexpected:
        # 人物一致性闸门（VQAGATE 11-02 P0，项目方 02:3x）：cast 写“局部 / 只露手 / 不露脸”或本镜没有在画角色，画面里却出了够大的脸
        # （ep02-S10：林晚判“只露双手”，没挂身份脸，Q1 原来直接“不适用”，换了人的脸照样过）→ 这张脸也必须认得出是 cast 里的谁：
        # 对每个角色的身份脸（score_remote 一直对 4 个主角都算）按脸大小分档比，像 cast 里的人且过线 = 过，否则拦
        _st, _d, *_ev = identity_unexpected(big_unexpected, req, t1)
        add("Q1", _st, _d, **(_ev[0] if _ev else {}))
    elif not face_visible or not expect:
        add("Q1", "na", "局部 / 空镜：不判身份")
    elif remote is None:
        add("Q1", "untested", "没有出图机器的人脸打分（score_remote）")
    else:
        # Q1 口径（总调度 11-01）：对本镜实际挂的身份参考算；参考名“<角色>@<版本>”（例 lin_wan@master = 项目方母版裁切）
        # 与“<角色>”（face_ref2va）都给时取较高者，报告写明对哪张
        faces = [{**f, "sims": _merge_refs({k: v for k, v in apply_bank(f.get("sims") or {}, t1).items() if not k.endswith("@anchor")}),
                  "anchor": {k[:-7]: v for k, v in apply_bank(f.get("sims") or {}, t1).items() if k.endswith("@anchor")}}
                 for f in remote.get("faces") or []]
        bad, got, via, used = [], {}, {}, set()
        q1_band = []                                  # K-REV-V18 修订：落在复核带的角色（交本地看图左右并排复核）
        q1_boxes = {}                                 # Q1a：每个在画角色认到的那张脸（ArcFace 最像的一张）
        refd = {k for f in faces for k in f["sims"]}
        for cid in expect:
            if faces and cid not in refd:                 # 没有身份脸参考的角色（路人）：不判，下面按“可抵一张认不出的脸”算
                continue
            cand = [(f["sims"].get(cid, (-1, "")), k) for k, f in enumerate(faces)]
            (best, ref), k_best = max(cand, default=((None, ""), None))
            got[cid], via[cid] = best, ref
            if best is None or best < 0:
                bad.append(f"{cid} 未出脸")
            else:
                used.add(k_best)
                q1_boxes[cid] = faces[k_best].get("bbox")
                h = float(faces[k_best].get("h_ratio") or 0)
                need, lo, tname = band_lines(cid, h, t1)
                if best < lo:
                    bad.append(f"{cid} {best:.3f}（对 {ref}）< {lo}（{tname}，直接不过）")
                elif best < need:
                    bad.append(f"{cid} {best:.3f}（对 {ref}）在复核带 {lo}–{need}（{tname}），待本地看图并排复核")
                    q1_band.append({"cid": cid, "sim": round(best, 3), "lo": lo, "need": need, "tier": tname,
                                 "bbox": faces[k_best].get("bbox"), "h_ratio": round(h, 3)})
                elif (faces[k_best].get("anchor") or {}).get(cid) is not None and faces[k_best]["anchor"][cid] < need:
                    # L-098 身份库 A/B（11-02）：top-k 把 03-S2 v14（脸圆发糊、亲审不合格，锚 0.573）抬到 0.611–0.650，
                    # 会绕开复核带的清晰度把关 → 锚自己没过线时仍进复核带，只是免本地看图（top-k 已证明是同一人），清晰度照查
                    a0 = faces[k_best]["anchor"][cid]
                    bad.append(f"{cid} 锚 {a0:.3f}（对 L-086）在复核带 {lo}–{need}（{tname}），身份库 top-k {best:.3f} 过线，待清晰度复核")
                    q1_band.append({"cid": cid, "sim": round(a0, 3), "topk": round(best, 3), "mode": "sharp_only", "lo": lo, "need": need,
                                    "tier": tname, "bbox": faces[k_best].get("bbox"), "h_ratio": round(h, 3)})
        # 总调度 11-01 P1（ep03-S6 林晚 + 一个不像顾沉的“外国脸”男人，Q1 只算了林晚）：画面里每一张（够大的）脸都要认得出是谁——
        # 必须像本镜 cast（在画 / 局部）里的某个角色；认不出 → 不过（“画面里多了不该有的人 / 认不出是谁”）。
        # cast 里没有身份脸参考的角色（路人等）每人可抵一张认不出的脸，只记录。
        allowed = {NAME_ID.get(c.get("name"), c.get("name")) for c in req.get("cast") or []
                   if c.get("presence") in ("在画", "局部")}
        with_ref = {k for f in faces for k in f["sims"]}
        no_ref = sorted(a for a in allowed if a not in with_ref)
        floor = t1.get("recognize_floor", 0.45)
        min_h = t1.get("min_face_ratio", 0.04)
        strangers, extra_ok, stranger_boxes = [], [], []
        for k, f in enumerate(faces):
            if k in used or (f.get("h_ratio") is not None and f["h_ratio"] < min_h):
                continue
            sims = {c: v[0] for c, v in f["sims"].items()}
            # 认出 = 像本镜 cast 里某个角色 ≥ recognize_floor（在画者另一张脸 = 镜像 / 重复人物，只记录待目检；“外国脸 / 陌生人”才挡）
            ok = [c for c in allowed if c in sims and sims[c] >= (t1.get(c, t1.get("default", 0.6)) if c in described and c not in got else floor)]
            if ok:
                me = max(ok, key=sims.get)
                pres = next((c.get("presence") for c in req.get("cast") or [] if NAME_ID.get(c.get("name"), c.get("name")) == me), None)
                if me in got and not rec.get("mirror"):
                    # 总调度 11-01 标注（Q7-36 / Q7-56）：同一角色两张脸、原文没写镜子 / 倒影 → 重复人物，不过
                    bad.append(f"同一角色出现两次：{me} 第二张脸 {sims[me]:.3f}（原文没写镜子 / 倒影）")
                elif pres == "局部" and me not in described and me not in got:
                    # 总调度 11-01（Q7-31 光膀子的男人）：cast 写“局部”（只出西装下摆 / 手）的人出了脸 → 不过
                    bad.append(f"局部角色出了脸：{me}（cast 写局部，原文也没写他的脸）{sims[me]:.3f}")
                else:
                    extra_ok.append(f"{me} {sims[me]:.3f}" + ("（同一角色第二张脸：原文写了镜子 / 倒影，待目检）" if me in got else ""))
                continue
            top = max(sims, key=sims.get) if sims else None
            strangers.append(f"脸高 {f.get('h_ratio', 0):.2f}" + (f"，最像 {top} {sims[top]:.3f}" if top else ""))
            stranger_boxes.append(f.get("bbox"))
        if len(strangers) > len(no_ref):
            bad.append(f"画面里多了不该有的人 / 认不出是谁：{len(strangers)} 张脸不像本镜任何角色（" + "；".join(strangers) +
                       f"；本镜可出现 {'、'.join(sorted(allowed)) or '无'}" + (f"，无参考可抵 {len(no_ref)} 张" if no_ref else "") + "）")
        for f in faces:
            sims = {k: v[0] for k, v in f["sims"].items()}
            if not sims:
                continue
            me = max(sims, key=sims.get)
            if me not in expect:
                continue
            for o, v in sims.items():
                if o == me:
                    continue
                cr = (cross or {}).get(f"{me}~{o}", (cross or {}).get(f"{o}~{me}", 0.0))
                lim = max(t1.get("other_floor", 0.4), cr + t1.get("other_margin", 0.05))
                if v >= lim and o not in allowed:
                    bad.append(f"{me} 的脸像 {o}（{v:.3f} ≥ {lim:.3f}）")
        add("Q1", "fail" if bad else "pass", "；".join(bad) if bad else
            "身份过线（" + "、".join(f"{c} {got[c]:.3f} 对 {via[c]}" for c in got) + "）" +
            (f"；其他脸：{'、'.join(extra_ok)}" if extra_ok else ""),
            sims=got, ref=via, faces=len(faces), strangers=strangers, others=extra_ok, stranger_boxes=stranger_boxes, review_band=q1_band,
            partial_cast=any(c.get("presence") in ("局部", "背影") for c in req.get("cast") or []), boxes=q1_boxes,
            q1_mode=(remote or {}).get("q1_mode"))
        # Q1a（VQAGATE 11-02 P0，ep06-S2 v6 顾沉长出林晚的蓝色长发）：逐人头发属性，确定性分割判；上线即阻断
        t1a = th.get("Q1a_attr") or {}
        if t1a.get("enabled"):
            st, d, ev = q1a_item(image, q1_boxes, [f.get("bbox") for f in faces if f.get("bbox")], t1a)
            add("Q1a", st, d, **ev)
    # Q2
    t2 = th.get("Q2_outfit") or {}
    q2 = (local or {}).get("Q2")
    # 外层单品存在性（不受 record_only_zones 影响）
    outer_bad, outer_note = [], []
    if local is not None:
        want_outer = outer_rows(rec)
        got = {(o.get("character", "lin_wan"), o.get("label")): o.get("p") for o in (local.get("outer") or [])}
        omin = t2.get("outer_min", 0.5)
        for o in want_outer:
            pv = got.get((o["character"], o["label"]))
            who = {"lin_wan": "林晚", "gu_chen": "顾沉", "chen_yu": "陈宇", "ch_a_lan": "阿岚"}.get(o["character"], o["character"])
            if pv is None:
                outer_note.append(f"{who}的{o['label']} 未测（没有{who}的脸框 / 旧打分）")
            else:
                key = f"{o['character']}:{o['label']}"
                block = not t2.get("outer_record_only") and key in (t2.get("outer_block_keys") or [])
                need = (t2.get("outer_min_by_key") or {}).get(key, omin)
                if pv < need:                                  # 只有校准过、能分开的单品才阻断（outer_block_keys），其余只记录
                    (outer_bad if block else outer_note).append(
                        f"{who}的{o['label']} 没穿（外层探针 {pv:.2f} < {need}）" + ("" if block else "，只记录（未校准）"))
    if q2 is None:
        add("Q2", "untested", "没有本机造型相似度测量")
    elif not q2:
        # 测过了、但没有要判的行（例：手部大特写——可见单品全在只记录区 hand / neck，或只有第二人的）→ 不适用。
        # 以前有槽位就记 untested，ep05-S3/S5、ep10-S1/S8 等手部特写因此每次都不过（11-01 PRODUCER 尽力清单）
        add("Q2", "na", "本镜没有要判的造型 / 单品（可见单品都在只记录区或属于第二人）" if rec.get("slots") else
            "本镜没有可比对的造型 / 单品参考")
    else:
        bad, review = [], []
        for r in q2:
            need = t2.get("clip_sheet", 0.7) if r["role"] == "sheet" else \
                (t2.get("clip_item_by_zone") or {}).get(r.get("zone") or "", t2.get("clip_item", 0.8))
            if r["role"] == "item" and (r.get("zone") or "") in (t2.get("record_only_zones") or []):
                r["pass"], r["record_only"] = True, True       # K-REV-231：该区域 CLIP 区分不开，只记录
                continue
            fband = t2.get("feet_band") if r.get("zone") == "feet" else None
            if fband:                                          # 总调度 11-01：鞋分三段——<下线挡；中间只记录“鞋待目检”；≥上线过
                emb = r.get("p_embellished")
                if emb is not None and emb > t2.get("embellished_max", 1.01):
                    r["pass"] = False
                    bad.append(f"{r['label']} 是加装饰款（水钻 / 脚踝带探针 {emb:.2f} > {t2.get('embellished_max')}）")
                elif r["clip"] < fband[0]:
                    r["pass"] = False
                    bad.append(f"{r['label']} clip {r['clip']:.3f} < {fband[0]}")
                elif r["clip"] < fband[1]:
                    r["pass"], r["review"] = True, "鞋待目检"
                    review.append(f"{r['label']} clip {r['clip']:.3f}（{fband[0]}–{fband[1]}，鞋待目检）")
                else:
                    r["pass"] = True
                continue
            ok = r["clip"] >= need and r["hist"] >= t2.get("hist", 0.0)
            r["pass"] = ok
            if not ok:
                bad.append(f"{r['label']} clip {r['clip']:.3f}/{need} hist {r['hist']:.2f}/{t2.get('hist')}")
        feet = [r for r in q2 if r.get("zone") == "feet"]
        if "feet" in (rec.get("zones") or []) and rec.get("primary") and not feet:
            bad.append("鞋可见但没有测鞋")
        if bad:
            add("Q2", "fail", "；".join(bad), rows=q2)
        elif review:
            add("Q2", "na", "只记录：" + "；".join(review), rows=q2, review="鞋待目检")
        else:
            add("Q2", "pass", f"{len(q2)} 项过线", rows=q2)
    if outer_bad or outer_note:                           # 外层单品存在性并进 Q2：没穿 → 不过（不管上身区单品是否只记录）
        it = next(i for i in items if i.id == "Q2")
        it.evidence["outer"] = (local or {}).get("outer")
        if outer_bad:
            keep = [it.detail] if it.detail and it.status != "pass" else []
            it.status = "fail"
            it.detail = "；".join(outer_bad + keep)
        if outer_note:
            it.detail = (it.detail + "；" if it.detail else "") + "；".join(outer_note)
    elif (local or {}).get("outer"):
        next(i for i in items if i.id == "Q2").evidence["outer"] = local["outer"]
    # Q3
    t3 = th.get("Q3_framing") or {}
    want = SIZE_BAND.get(rec.get("size") or "")
    close_part = rec.get("subject") in ("part", "object") and rec.get("size") in ("特写", "大特写", "极近特写")
    big = [f for f in (remote or {}).get("faces") or [] if (f.get("h_ratio") or 0) >= t1.get("min_face_ratio", 0.04)]
    any_described = any(c.get("face_described") for c in rec.get("characters") or [])
    if close_part and remote is not None and big and not any_described:
        # 总调度 11-01（ep05-S3/S5、ep10-S8 驳回）：局部 / 物件特写里出了脸 = 景别错了（模型拍成了带脸的人像），不享受局部豁免
        add("Q3", "fail", f"局部特写出了脸：{len(big)} 张脸（最大脸高 {max(f['h_ratio'] for f in big):.3f}），要的是只拍局部",
            faces=len(big))
    elif close_part and remote is None:
        add("Q3", "untested", "局部特写：没有人脸打分，无法确认画面里没出脸")
    elif not face_visible or want is None:
        add("Q3", "na", "局部特写 / 未写景别：不判（已确认没出脸）" if close_part else "局部特写 / 未写景别：不判")
    elif remote is None:
        add("Q3", "untested", "没有人脸打分")
    else:
        faces = remote.get("faces") or []
        if not faces:
            add("Q3", "fail", "没有检测到脸，无法判景别")
        else:
            got = band(faces[0]["h_ratio"], t3.get("bands", [0.45, 0.27, 0.17, 0.115, 0.095, 0.05]))
            ok = abs(got - want) <= int(t3.get("tolerance", 1))
            add("Q3", "pass" if ok else "fail", f"要 {rec.get('size')}（档 {want}），脸高 {faces[0]['h_ratio']:.3f} → 档 {got}",
                h_ratio=faces[0]["h_ratio"])
    # Q4
    t4 = th.get("Q4_texture") or {}
    q4 = (local or {}).get("Q4")
    if not q4 or q4.get("error"):
        add("Q4", "untested" if not face_visible or not q4 else "untested", (q4 or {}).get("error", "没有测质感"))
    else:
        bad = []
        if q4["lap_full"] < t4.get("lap_full_min", 0):
            bad.append(f"清晰度（整图 Laplacian，宽 768）{q4['lap_full']} < {t4['lap_full_min']}（塑料 / 糊）")
        if q4["sat_mean"] > t4.get("sat_mean_max", 1):
            bad.append(f"平均饱和度 {q4['sat_mean']} > {t4['sat_mean_max']}")
        if q4["specular"] > t4.get("specular_max", 1):
            bad.append(f"皮肤镜面高光（油光）{q4['specular']} > {t4['specular_max']}")
        add("Q4", "fail" if bad else "pass", "；".join(bad) if bad else "质感过线", **q4)
    # Q5
    if hands is None:
        add("Q5", "untested", "没有手 / 肢体检测（hands_remote）")
    else:
        fl = list(hands.get("flags") or [])
        t5 = th.get("Q5_hands") or {}
        if any(c.get("name") in (t5.get("long_nails") or []) and c.get("presence") in ("在画", "局部") for c in req.get("cast") or []):
            import re as _re
            keep = []
            for f in fl:                                  # 超长水晶甲：只有指长比超 3.0、且 ≤ 放宽线、没有指尖重合 → 不算可疑
                m = _re.search(r"指长比 \[([^\]]*)\]，指尖重合 (\d+)", f)
                if m and f.startswith("手型可疑") and int(m.group(2)) < 2:
                    rs = [float(x) for x in m.group(1).split(",") if x.strip()]
                    if rs and max(rs) <= t5.get("finger_ratio_max_long_nails", 3.0) and min(rs) >= 0.3:
                        continue
                keep.append(f)
            fl = keep
        ign = tuple((th.get("Q5_hands") or {}).get("record_only_flags") or ())   # 留出复核误报的规则只记录
        rec_only = [f for f in fl if ign and f.startswith(ign)]
        fl = [f for f in fl if f not in rec_only]
        det = "；".join(fl) if fl else "无可疑"
        if rec_only:
            det += "（只记录：" + "；".join(rec_only)[:120] + "）"
        add("Q5", "fail" if len(fl) > int((th.get("Q5_hands") or {}).get("max_flags", 0)) else "pass",
            det, hands=hands.get("hands"), poses=hands.get("poses"))
    # Q6
    if remote is None:
        add("Q6", "untested", "没有 OCR")
    else:
        t6 = th.get("Q6_text") or {}
        tx = remote.get("text") or []
        # 总调度 11-01 标注 4/4：只识别出纯数字 / 标点的框（“0002”“0.030”“888888888”）都不是多余文字——只记录
        ign = re.compile(t6.get("ignore_pattern") or r"^$")
        real = [t for t in tx if not ign.match(str(t.get("text") or "").strip())]
        noise = [t for t in tx if t not in real]
        det = "；".join(t["text"] for t in real) if real else "无文字"
        if noise:
            det += "（只记录：纯数字 / 标点 " + "、".join(str(t["text"]) for t in noise) + "）"
        add("Q6", "fail" if len(real) > int(t6.get("max_boxes", 0)) else "pass", det, boxes=len(real), ignored=len(noise))
    # Q7
    q7 = (local or {}).get("Q7")
    need = (th.get("Q7_scene") or {}).get("clip_min", 0.6)
    if q7 is None:
        add("Q7", "na" if not any(m.get("kind") == "场景缺图" for m in rec.get("missing") or []) else "fail", "本镜没有场景参考")
    else:
        add("Q7", "pass" if q7["clip"] >= need else "fail", f"场景相似度 {q7['clip']:.3f} / 线 {need}", **q7)
    # Q8 发色（总调度 11-01：ep01-S5 发色偏暗灰）——只挡明显过暗 / 过灰；项目方 10-30 定的“比参考图略深、带一点灰”不算不过
    t8 = th.get("Q8_hair") or {}
    lw_on = any(c.get("name") == "林晚" and c.get("presence") == "在画" for c in req.get("cast") or [])
    q8 = (local or {}).get("Q8") if local else None
    if not lw_on or not face_visible:
        add("Q8", "na", "林晚不在画 / 局部特写")
    elif remote is None or local is None:
        add("Q8", "na" if t8.get("record_only") else "untested", "没有脸框 / 本机测量")
    elif not q8 or q8.get("note") or not q8.get("hsv"):
        add("Q8", "na" if t8.get("record_only") else "untested", (q8 or {}).get("note") or "没检出林晚的脸或发丝")
    else:
        ref = t8.get("ref") or {"s": 96.0, "rel_v": 0.712}
        ds = q8["hsv"][1] - ref["s"]
        rv = (q8.get("rel_v") or 0) / ref["rel_v"]
        bad = []
        if ds < t8.get("ds_min", -40):
            bad.append(f"发色饱和度 {q8['hsv'][1]:.0f} 比身份参考 {ref['s']:.0f} 低 {-ds:.0f}（线 {-t8.get('ds_min', -40)}）")
        if rv < t8.get("rel_v_ratio_min", 0.55):
            bad.append(f"发色相对亮度（发 V / 肤 V）{q8.get('rel_v')} 只有身份参考的 {rv:.2f} 倍（线 {t8.get('rel_v_ratio_min', 0.55)}）")
        if t8.get("record_only"):                      # 总调度 11-01：只记录、不阻断、不触发重出
            add("Q8", "na", ("只记录（不阻断）：" + ("；".join(bad) if bad else "未越线") + f"；相对亮度 {rv:.2f}× 参考"),
                would_fail=bool(bad), ratio=round(rv, 3), **q8)
        else:
            add("Q8", "fail" if bad else "pass", "；".join(bad) if bad else f"发色 HSV {q8['hsv']}，相对亮度 {rv:.2f}× 参考", **q8)
    # Q9 本地看图复核（VQA 11-01，项目方定：gpu36 本地 Qwen3-VL-8B，不发外部 API；只记录，未成年外观除外）
    VQ = _vqa()
    if VQ is not None:
        v_ = vlm if vlm is not None else (VQ.cached_for(image) or _q9_live(VQ, image, req))
        st_, d_, ev_ = _q9_item(VQ, VQ.q9(v_))
        add("Q9", st_, d_, **ev_)
    # G1 看镜头（ACTING 11-01，只记录；局部 / 物件特写不判）
    if face_visible:
        st_, d_, ev_ = gaze_item(image)
        add("G1", st_, d_, **ev_)
    else:
        add("G1", "na", "局部 / 物件特写：不判视线")
    # 留出复核没过的项只记录不阻断（config image_thresholds.<项>.record_only；BAKEOFF 11-01 heldout_bakeoff.json）
    ro = {"Q2": "Q2_outfit", "Q4": "Q4_texture", "Q5": "Q5_hands", "Q7": "Q7_scene"}
    for it in items:
        key = ro.get(it.id)
        if key and (th.get(key) or {}).get("record_only") and it.status in ("fail", "untested"):
            it.evidence = {**(it.evidence or {}), "would_fail": it.status == "fail", "record_only": True}
            it.detail = f"只记录（不阻断，留出复核未过）：{it.detail}"
            it.status = "na"
    return ContractResult("postflight", str(image), items, cfg().get("version", ""))


VTITLES = {"V1": "身份（逐帧中位 / 检出占比）", "V2": "脸颊泛红", "V3": "J4 抖动", "V4": "动作量 / 静止", "V5": "镜内硬切",
           "V6": "多肢", "V7": "口型（有对白时）", "V8": "与首帧 / 造型一致"}


def evaluate_video(score: dict, req: dict | None = None) -> ContractResult:
    """视频 postflight（契约 §3）：读 VIDEO10 tools/series10_video/score_clip.py 的每片 JSON
    （video/scores/<镜>__<变体>.json）。阈值 config/gen_contract.json video_thresholds；没有检测器的项 = untested（不算通过）"""
    th = cfg().get("video_thresholds") or {}
    req = req or {}
    items: list[Item] = []

    def add(i, st, d="", **ev):
        items.append(Item(i, VTITLES[i], st, d, ev))

    ids = score.get("identity") or {}
    if not ids:
        add("V1", "untested", "没有身份打分")
    else:
        bad = []
        for n, v in ids.items():
            if v.get("sface_med") is None or v["sface_med"] < th.get("sface_med", 0.30):
                bad.append(f"{n} 中位 {v.get('sface_med')} < {th.get('sface_med', 0.30)}")
            if (v.get("seen") or 0) < th.get("seen", 0.15):
                bad.append(f"{n} 检出 {v.get('seen')} < {th.get('seen', 0.15)}")
        add("V1", "fail" if bad else "pass", "；".join(bad) if bad else "身份过线",
            **{n: {k: v.get(k) for k in ("sface_med", "sface_min", "sface_p10", "seen")} for n, v in ids.items()})
    cr = score.get("cheek_red_max")
    add("V2", "untested" if cr is None else ("pass" if cr <= th.get("cheek_red_max", 0.25) else "fail"),
        f"cheek_red_max {cr} / 线 {th.get('cheek_red_max', 0.25)}")
    j4 = score.get("J4")
    add("V3", "untested" if j4 is None else ("pass" if j4 <= th.get("J4_max", 1.3) else "fail"),
        f"J4 {j4}（z {score.get('J4_z')}）/ 线 {th.get('J4_max', 1.3)}")
    mean = score.get("mean")
    add("V4", "untested" if mean is None else ("pass" if mean >= th.get("motion_mean_min", 0.5) else "fail"),
        f"动作量 {mean} / 线 {th.get('motion_mean_min', 0.5)}；静止占比 {score.get('still')}；开头定 {score.get('head_s')} s、结尾定 {score.get('tail_s')} s")
    cuts = score.get("cuts")
    add("V5", "untested" if cuts is None else ("pass" if not cuts and not score.get("jump_cut_s") else "fail"),
        f"切点 {cuts}；跳切 {score.get('jump_cut_s')}")
    add("V6", "untested", "多肢检测器待接（人工看印样）")
    has_line = bool(req.get("dialogue")) or bool(score.get("has_dialogue"))
    add("V7", "untested" if has_line else "na", "口型检测待接（tools/ep02_director/review.py voice_env + xcorr）" if has_line else "无对白")
    add("V8", "untested", "与首帧 / 造型一致：待接（首帧 Q2 参考区域逐帧比对）")
    VQ = _vqa()
    if VQ is not None:
        st_, d_, ev_ = _q9_item(VQ, VQ.v9(score.get("vlm")))
        add("V9", st_, d_, **ev_)
    return ContractResult("postflight", str(req.get("shot_id") or score.get("shot") or "video"), items, cfg().get("version", ""))


def run(kind: str, payload: dict) -> dict:
    """统一签名（EDITDEL / VIDEO10 等调用）：
    image：payload = {"image", "request", "remote", "cross", "hands", "local"?}；local 不给时本机现算 Q2 / Q4 / Q7。
    video：payload = {"score": score_clip.py 的 JSON（或 "score_file": 路径）, "request"?}。→ ContractResult.to_dict()"""
    if kind != "image":
        sc = payload.get("score")
        if sc is None and payload.get("score_file"):
            import json
            p = Path(payload["score_file"])
            sc = json.loads((p if p.is_absolute() else ROOT / p).read_text(encoding="utf-8"))
        r = evaluate_video(sc or {}, payload.get("request"))
        d = r.to_dict()
        d["reasons"] = r.reasons()
        return d
    req = payload.get("request") or {}
    local = payload.get("local")
    if local is None:
        local = measure_local(payload["image"], req.get("asset_refs") or {}, payload.get("remote"))
    r = evaluate(payload["image"], req, remote=payload.get("remote"), cross=payload.get("cross"),
                 hands=payload.get("hands"), local=local, vlm=payload.get("vlm"))
    d = r.to_dict()
    d["reasons"] = r.reasons()
    d["local"] = local
    return d


class _Callable(types.ModuleType):
    def __call__(self, kind: str, payload: dict) -> dict:
        return run(kind, payload)


sys.modules[__name__].__class__ = _Callable
