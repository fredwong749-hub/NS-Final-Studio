"""画面指数 v2（L-189：确定性构图 / 焦段 / 虚化指标；不调模型）。RSI 线 1 的“项目方看得出来的那部分”。

项目方评图看：构图（过肩 / 前景 / 纵深层次 / 机位高度）、焦段观感（不要手机广角）、f/1.2 式光学虚化（背景有真实物体）。
五个分项（0–1，越大越像电影），权重 PI_W：
  dof      0.25  脸框锐度 / 四周背景锐度（dof_metrics.metrics 的 fbg_ratio，无脸框用 dof_ratio）；1× 记 0，4× 记满
  bg       0.20  背景亮度 + 空白：四周圈亮度 > 0.35 开始扣，> 0.65 扣完；亮且无纹理（白幕）额外重扣
  scale    0.15  焦段 / 景别代理：最大脸高 ÷ 要求景别档的脸高下限（Q3 “档 k”，bands 同 Q3）；全员脸太小 = 广角观感
  lineup   0.20  多人“一排站”惩罚：脸心纵向散布 ÷ 平均脸高 小 且 脸高相近（同一景深）→ 低分；单人记 1
  layers   0.20  纵深层次：有深度图用深度直方图占据档数；没有则用 12×8 格局部锐度相对脸的三档（锐 / 中 / 糊）占据数
没做：灭点 / 透视线焦段（需要几何模型）、机位高度（俯仰靠 VLM，本地 VLM 不做审美，L-189）——列在 UNMEASURED。
脸框来源：takes postflight Q1.evidence.per_face[].bbox（生产同口径，坐标 = 出图像素），没有则 OpenCV Haar 兜底。
"""
from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
PI_W = {"dof": 0.25, "bg": 0.20, "scale": 0.15, "lineup": 0.20, "layers": 0.20}
BANDS = [0.45, 0.27, 0.17, 0.115, 0.095, 0.05]          # 与 adherence_img_ab / Q3 同口径：档 k 的脸高下限
UNMEASURED = ["灭点 / 透视线焦段代理", "机位高度（俯 / 平 / 仰）", "前景遮挡物语义（过肩的肩）"]
OWNER_FILE = ROOT / "data/rsi/owner_spotcheck.json"
OWNER_CAP = 60.0


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def _gray(path: Path):
    for p in (ROOT, ROOT / "tools/pipeline"):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
    import cv2
    import look_metrics as LM
    img = LM._load(path)
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), img


def faces_from_take(take: dict) -> list[dict]:
    """[{bbox:[x0,y0,x1,y1], h_ratio}]，按脸高降序；取 postflight Q1 per_face"""
    pf = (take or {}).get("postflight") or {}
    out = []
    for it in pf.get("items") or []:
        if it.get("id") == "Q1":
            for f in (it.get("evidence") or {}).get("per_face") or []:
                if f.get("bbox") and (f.get("h_ratio") or 0) >= 0.04:
                    out.append({"bbox": [float(v) for v in f["bbox"]], "h_ratio": float(f["h_ratio"])})
    return sorted(out, key=lambda f: -f["h_ratio"])


def band_from_take(take: dict) -> int | None:
    for it in ((take or {}).get("postflight") or {}).get("items") or []:
        if it.get("id") == "Q3":
            m = re.search(r"要\s*\S*?（档\s*(\d)", it.get("detail") or "")
            if m:
                return int(m.group(1))
    return None


def detect_faces(img_bgr) -> list[dict]:
    import cv2
    g = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    c = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    H = g.shape[0]
    return sorted(({"bbox": [float(x), float(y), float(x + w), float(y + h)], "h_ratio": h / H}
                   for x, y, w, h in c.detectMultiScale(g, 1.1, 5, minSize=(int(H * .04),) * 2)), key=lambda f: -f["h_ratio"])


def _lap_cells(g: np.ndarray, rows: int = 8, cols: int = 12) -> np.ndarray:
    import cv2
    lap = cv2.Laplacian(cv2.GaussianBlur(g, (3, 3), 0).astype(np.float32), cv2.CV_32F)
    h, w = lap.shape
    out = np.zeros((rows, cols), np.float32)
    for r in range(rows):
        for c in range(cols):
            out[r, c] = lap[r * h // rows:(r + 1) * h // rows, c * w // cols:(c + 1) * w // cols].var()
    return out


def measure(path: Path, faces: list[dict] | None = None, band: int | None = None, depth: np.ndarray | None = None) -> dict:
    """返回 {parts: {分项: 0–1}, raw: {...}, index: 0–100}。faces 的 bbox 是出图原始像素"""
    import cv2
    from PIL import Image
    g, img = _gray(Path(path))
    h, w = g.shape
    if faces is None:
        faces = detect_faces(img)
        for f in faces:      # detect_faces 在缩放后坐标；换算到“原图”不必要，直接以 g 坐标 + 比例 1
            pass
        sc_orig = 1.0
    else:
        W0, H0 = Image.open(path).size
        sc_orig = h / H0     # 原图像素 → g 像素
    boxes = [[v * sc_orig for v in f["bbox"]] for f in faces]
    raw: dict = {"faces": len(faces)}
    from tools.imglab import dof_metrics as LS      # dof_ratio / fbg_ratio / bg_lum（不再 import research 脚本）
    W0, H0 = Image.open(path).size
    fb = None
    if boxes:
        s_back = H0 / h
        fb = [int(boxes[0][0] * s_back), int(boxes[0][1] * s_back), int((boxes[0][2] - boxes[0][0]) * s_back), int((boxes[0][3] - boxes[0][1]) * s_back)]
    m = LS.metrics(Path(path), fb)
    r = m.get("fbg_ratio") if m.get("fbg_ratio") is not None else m.get("dof_ratio")
    raw.update({"dof_ratio": m.get("dof_ratio"), "fbg_ratio": m.get("fbg_ratio"), "bg_lum": m.get("bg_lum")})
    dof = _clamp(math.log(max(r or 1.0, 1e-3)) / math.log(4.0))
    ring = np.ones((h, w), bool)
    ring[int(h * .2):int(h * .8), int(w * .2):int(w * .8)] = False
    ring_std = float((g[ring] / 255.0).std())
    bl = float(m.get("bg_lum") or 0.0)
    blank = 0.6 + 0.4 * (1 - _clamp(ring_std / 0.15))
    bg = 1.0 - _clamp((bl - 0.35) / 0.30) * blank
    raw["ring_std"] = round(ring_std, 3)
    hmax = faces[0]["h_ratio"] if faces else 0.0
    lo = BANDS[band] if band is not None and 0 <= band < len(BANDS) else 0.12
    scale = _clamp(hmax / lo) if faces else 0.5
    raw.update({"face_h_max": round(hmax, 3), "band": band, "band_lo": lo})
    big = [f for f in faces if f["h_ratio"] >= 0.04]
    if len(big) >= 2:
        hs = np.array([f["bbox"][3] - f["bbox"][1] for f in big])
        cy = np.array([(f["bbox"][1] + f["bbox"][3]) / 2 for f in big])
        spread = float((cy.max() - cy.min()) / hs.mean())
        cv = float(hs.std() / hs.mean())
        lineup = 1.0 - (1 - _clamp(spread / 1.0)) * (1 - _clamp(cv / 0.5))
        raw.update({"lineup_spread_y": round(spread, 2), "lineup_size_cv": round(cv, 2)})
    else:
        lineup = 1.0
    if depth is not None:
        d = np.asarray(depth, np.float32)
        d = (d - d.min()) / max(float(np.ptp(d)), 1e-6)
        hist, _ = np.histogram(d, bins=4, range=(0, 1))
        occ = int((hist / d.size >= 0.10).sum())
        layers = _clamp((occ - 1) / 3.0)
        raw["layers_src"] = "depth"
    else:
        cells = _lap_cells(g)
        fs = float(max(np.percentile(cells, 75), 1e-3))
        if boxes:
            x0, y0, x1, y1 = [int(v) for v in boxes[0]]
            gg = g[max(0, y0):max(1, y1), max(0, x0):max(1, x1)]
            if gg.size > 16:
                fs = float(cv2.Laplacian(cv2.GaussianBlur(gg, (3, 3), 0).astype(np.float32), cv2.CV_32F).var())
        q = cells / max(fs, 1e-3)
        n = q.size
        tiers = [(q >= 0.5).sum() / n, ((q >= 0.08) & (q < 0.5)).sum() / n, (q < 0.08).sum() / n]
        layers = sum(min(t / 0.20, 1.0) for t in tiers) / 3.0     # 三档各占 ≥20% 记满；缺一档（无虚化层 / 无锐层）就掉分
        raw["layers_src"] = "sharpness_tiers"
        raw["tiers"] = [round(float(t), 2) for t in tiers]
    layers = float(layers)
    parts = {"dof": dof, "bg": bg, "scale": scale, "lineup": lineup, "layers": layers}
    idx = 100 * sum(PI_W[k] * parts[k] for k in PI_W)
    return {"parts": {k: round(v, 3) for k, v in parts.items()}, "raw": raw, "index": round(idx, 1)}


def load_owner() -> dict:
    try:
        return json.loads(OWNER_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):   # arch-ok: 没有抽检记录 = 不封顶
        return {}


def owner_cap(owner: dict | None) -> float | None:
    """owner = {"verdict": "不合格|合格", "at": ISO, "version": sv, "note": ...}（最新一条抽检）。
    “不合格”封顶 60；被更晚的“合格”抽检（写进同一文件覆盖）解除"""
    return OWNER_CAP if owner and owner.get("verdict") == "不合格" else None


def combine(contract: float | None, pic: float | None, owner: dict | None = None) -> tuple[float | None, dict]:
    """出图线总分：0.35 × 契约分（缺陷类）+ 0.65 × 画面指数；项目方“不合格”封顶 60"""
    info: dict = {"contract": contract, "picture_index": pic}
    if pic is None:
        s = contract
    else:
        s = pic if contract is None else 0.35 * contract + 0.65 * pic
    cap = owner_cap(owner)
    if s is not None and cap is not None and s > cap:
        info["capped_by"] = f"项目方抽检不合格（{(owner or {}).get('at')} {(owner or {}).get('version') or ''}）：{(owner or {}).get('note') or ''}"
        s = cap
    return (round(s, 1) if s is not None else None), info
