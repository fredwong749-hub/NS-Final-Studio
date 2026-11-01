"""设定图入库检查（IMGFIX r6，总调度 fredw-2b 11-02，L-102 / ITERATION_PROTOCOL §G1：判据写成代码，不靠亲审）。

起因：林晚造型 A 设定图 v2_s202 正面栏左臂是米白衬衫袖、另一只是深灰西装袖（L-101 才修好），采用时没有任何检查拦下，
导致 front_nohead / back 参考把“缺一只袖子”带进首帧。设定图被采用前（人物中枢 set_sheet、ASSETMASTER choose）先过这里：

  IN1 左右对称：正面栏人物外框里，左右两条手臂带（关于人物中线镜像）逐行比颜色，平均 Lab ΔE76 ≤ arm_de_max，
      且“一边深一边浅”的行占比 ≤ arm_mismatch_max（深 = 最大通道 < 130；浅 = 亮度 > 165）
  IN3 鞋成对（只记录 warn，不挡）：正面栏脚部带连通块应为 2
  IN2 关键单品完整：本造型外层单品（outfit 槽、postflight.outer_en 认得的）在正面栏躯干上的存在性 —— 同契约 Q2 探针
      （metrics.outer_presence + config outer_probes），≥ outer_min（缺探针的单品记“未测”，不挡）
结果 ok=False 时 blocking 列出原因；参数在 config/gen_contract.json image_thresholds.sheet_intake（缺省值见 DEFAULTS）。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
DEFAULTS = {"arm_de_max": 18.0, "arm_mismatch_max": 0.25, "arm_band": [0.17, 0.47], "arm_width": 0.24, "outer_min": 0.3}


def _cfg() -> dict:
    try:
        from ns_agent.gen_contract.postflight import cfg
        return {**DEFAULTS, **(((cfg().get("image_thresholds") or {}).get("sheet_intake")) or {})}
    except Exception:  # noqa: BLE001
        return dict(DEFAULTS)


def _lab(a):
    a = a / 255.0
    a = np.where(a > 0.04045, ((a + 0.055) / 1.055) ** 2.4, a / 12.92)
    M = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]])
    xyz = a @ M.T / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)


def front_panel(sheet: str | Path):
    """→ (正面栏 PIL 图, 人物外框 (x0,y0,x1,y1) 正面栏像素)；版式 = asset_refs sheet_layout"""
    from PIL import Image
    from ns_agent import asset_refs as AR
    im = Image.open(ROOT / sheet if not Path(sheet).is_absolute() else sheet).convert("RGB")
    a, b = (AR._cfg().get("sheet_layout") or {}).get("front", [0.335, 0.556])
    W, H = im.size
    x0, x1 = int(a * W), int(b * W)
    bx0, by0, bx1, by1 = AR._person_box(im, x0 + 4, x1 - 4)
    return im.crop((x0, 0, x1, H)), (bx0 - x0, by0, bx1 - x0, by1)


def arm_symmetry(panel, box, c: dict | None = None) -> dict:
    """IN1：两条手臂带（人物外框最外侧 arm_width 宽、纵向 arm_band 段）逐行镜像比较"""
    c = c or _cfg()
    a = np.asarray(panel).astype(np.float32)
    x0, y0, x1, y1 = box
    h, w = y1 - y0, x1 - x0
    ys = range(y0 + int(c["arm_band"][0] * h), y0 + int(c["arm_band"][1] * h))
    aw = max(4, int(c["arm_width"] * w))
    des, mism, n = [], 0, 0
    for y in ys:
        L = a[y, x0:x0 + aw]
        R = a[y, x1 - aw:x1][::-1]
        lm = ~(L > 235).all(-1)                  # 去白背景
        rm = ~(R > 235).all(-1)
        if lm.sum() < 3 or rm.sum() < 3:
            continue
        lc, rc = L[lm].mean(0), R[rm].mean(0)
        des.append(float(np.linalg.norm(_lab(lc[None])[0] - _lab(rc[None])[0])))
        ld, rd = L[lm].max(-1).mean() < 130, R[rm].max(-1).mean() < 130
        ll, rl = L[lm].mean() > 165, R[rm].mean() > 165
        mism += int((ld and rl) or (rd and ll))
        n += 1
    if not n:
        return {"status": "untested", "detail": "正面栏没找到手臂带"}
    de, mr = float(np.mean(des)), mism / n
    ok = de <= c["arm_de_max"] and mr <= c["arm_mismatch_max"]
    return {"status": "pass" if ok else "fail", "deltaE": round(de, 2), "mismatch_rows": round(mr, 3), "rows": n,
            "detail": f"左右手臂带平均 ΔE {de:.1f}（线 {c['arm_de_max']}），一深一浅的行 {mr:.0%}（线 {c['arm_mismatch_max']:.0%}）"}


def outer_items(panel, cid: str, look_id: str, project: str, c: dict | None = None) -> list[dict]:
    """IN2：本造型外层单品在正面栏躯干上的存在性（契约 Q2 同一探针）"""
    c = c or _cfg()
    from ns_agent import asset_refs as AR
    from ns_agent.gen_contract import metrics as GM
    from ns_agent.gen_contract.postflight import cfg, outer_en
    L = (AR.load_looks(project).get(cid) or {}).get(look_id)
    if not L:
        return []
    probes = ((cfg().get("image_thresholds") or {}).get("Q2_outfit") or {}).get("outer_probes") or {}
    out = []
    face = _face_box(panel)
    for p in L.parts:
        en = outer_en(p.label) if p.slot == "outfit" and not p.extra else None
        if not en:
            continue
        pr = probes.get(f"{cid}:{p.label}") or probes.get(p.label)
        if not pr or face is None:
            out.append({"item": p.label, "status": "untested", "detail": "没有登记探针 / 正面栏没测到脸"})
            continue
        v = GM.outer_presence(panel, face, en, pr)
        st = "untested" if v is None else ("pass" if v >= c["outer_min"] else "fail")
        out.append({"item": p.label, "status": st, "score": None if v is None else round(float(v), 3),
                    "detail": f"{p.label} 存在性 {v if v is None else round(float(v), 3)}（线 {c['outer_min']}）"})
    return out


def _face_box(panel):
    try:
        import cv2
        import sys
        qc = str(ROOT / "packages/qc")
        if qc not in sys.path:
            sys.path.insert(0, qc)
        from ns_qc import face as QF
        from ns_qc import gaze as GZ
        m = GZ._models()
        bgr = cv2.cvtColor(np.asarray(panel), cv2.COLOR_RGB2BGR)
        big = cv2.resize(bgr, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        f = QF.largest(m.faces(big))
        if f is None:
            return None
        x, y, w, h = [float(v) / 2 for v in f[:4]]
        return (x, y, x + w, y + h)
    except Exception:  # noqa: BLE001
        return None


def feet_pair(panel, box) -> dict:
    """IN3 鞋成对（IMGFIX r7）：正面栏人物外框最下 7% 里，非白像素的连通块（面积 ≥ 外框面积的 0.05%）应正好 2 个（两只脚 / 鞋）；
    0 个 = 脚没画（栏被裁）→ untested；1 个 = 并脚或缺一只 → 记 warn（不挡，站姿并脚时也会是 1）；≥3 = 多出来的 → warn"""
    import cv2
    a = np.asarray(panel)
    x0, y0, x1, y1 = box
    h = y1 - y0
    band = a[y1 - int(0.07 * h):y1, x0:x1]
    m = (~(band > 235).all(-1)).astype(np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m, 8)
    big = [i for i in range(1, n) if stats[i, cv2.CC_STAT_AREA] >= 0.0005 * (x1 - x0) * h]
    k = len(big)
    st = "untested" if k == 0 else ("pass" if k == 2 else "warn")
    return {"status": st, "blobs": k, "detail": f"脚部带连通块 {k} 个（应为 2）"}


def check(sheet: str | Path, cid: str | None = None, look_id: str | None = None, project: str = "series10_v1") -> dict:
    c = _cfg()
    panel, box = front_panel(sheet)
    res = {"sheet": str(sheet), "IN1": arm_symmetry(panel, box, c)}
    res["IN2"] = outer_items(panel, cid, look_id, project, c) if cid and look_id else []
    res["IN3"] = feet_pair(panel, box)
    blocking = []
    if res["IN1"]["status"] == "fail":
        blocking.append("IN1 左右袖子不一致：" + res["IN1"]["detail"])
    blocking += ["IN2 关键单品缺失：" + x["detail"] for x in res["IN2"] if x["status"] == "fail"]
    res.update(ok=not blocking, blocking=blocking)
    return res
