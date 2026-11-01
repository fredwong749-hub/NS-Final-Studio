"""人物一致性闸门（VQAGATE 11-02 P0，项目方 02:3x：“女孩的脸就不一样了……写一个本地的图像模型来识别一致性的问题”）。

复用已有的 ArcFace（insightface buffalo_l：RetinaFace det_10g 检测 + 对齐 + w600k_r50 特征，服务器 venv_idm，和契约 Q1 同一模型），
不另造检测器。每个角色一个身份库（L-086 身份脸 + 已通过帧），画面里每张“足够大的脸”取对每个角色身份库的 top-k 平均余弦：
- 认得出（像 cast 里某人 ≥ 该景别档的线）→ 记是谁；
- cast 写“局部 / 不露脸 / 只露手”的人，画面里却露了脸 → 一样比身份库，不像就拦；
- 认不出 → “陌生脸”，拦（背影后脑的误检交 contract.recheck_strangers 的本地看图复核排除）；
- 临界区（线 − margin 到线）交本地看图“左右并排是否同一人”复核（contract 侧做）。
限线程（K-OPS-V13）。常驻用法：python id_gate.py serve（127.0.0.1:8890，加载一次）；单次：python id_gate.py score <img> '<json req>'。
"""
from __future__ import annotations

import os as _os   # K-OPS-V13
for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    _os.environ[_k] = _os.environ.get("NS_SCORE_THREADS", "4")
NS_THREADS = int(_os.environ.get("NS_SCORE_THREADS", "4"))

import json  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402

MODEL_ROOT = _os.environ.get("IDM_ROOT", "/root/work/fredw/idm_models")
_APP = None
_BANK_CACHE: dict = {}


def _cap_onnxruntime():
    import onnxruntime as ort
    if getattr(ort, "_ns_capped", False):
        return
    _orig = ort.InferenceSession.__init__

    def _init(self, path_or_bytes, sess_options=None, *a, **kw):
        if sess_options is None:
            sess_options = ort.SessionOptions()
            sess_options.intra_op_num_threads = NS_THREADS
            sess_options.inter_op_num_threads = 1
        return _orig(self, path_or_bytes, sess_options, *a, **kw)
    ort.InferenceSession.__init__ = _init
    ort._ns_capped = True


def app():
    global _APP
    if _APP is None:
        _cap_onnxruntime()
        import cv2
        cv2.setNumThreads(NS_THREADS)
        from insightface.app import FaceAnalysis
        a = FaceAnalysis(name="buffalo_l", root=MODEL_ROOT, allowed_modules=["detection", "recognition"],
                         providers=["CPUExecutionProvider"])
        a.prepare(ctx_id=-1, det_size=(640, 640))
        _APP = a
    return _APP


def faces(path: str) -> list[dict]:
    import cv2
    bgr = cv2.imread(str(path))
    if bgr is None:
        return []
    H = bgr.shape[0]
    out = []
    for f in app().get(bgr):
        x1, y1, x2, y2 = [float(v) for v in f.bbox]
        out.append({"bbox": [x1, y1, x2, y2], "h_ratio": (y2 - y1) / H, "det": float(f.det_score),
                    "emb": [float(v) for v in f.normed_embedding]})
    if not out:           # 裁切图 / 身份脸太紧：加边再测
        big = cv2.copyMakeBorder(bgr, 120, 120, 120, 120, cv2.BORDER_CONSTANT, value=(128, 128, 128))
        for f in app().get(big):
            x1, y1, x2, y2 = [float(v) for v in f.bbox]
            out.append({"bbox": [x1 - 120, y1 - 120, x2 - 120, y2 - 120], "h_ratio": (y2 - y1) / H, "det": float(f.det_score),
                        "emb": [float(v) for v in f.normed_embedding]})
    return out


def bank(files: list[str]) -> np.ndarray:
    key = tuple(files)
    if key not in _BANK_CACHE:
        embs = []
        for f in files:
            fs = faces(f)
            if fs:
                embs.append(max(fs, key=lambda x: x["h_ratio"])["emb"])
        _BANK_CACHE[key] = np.array(embs, np.float32) if embs else np.zeros((0, 512), np.float32)
    return _BANK_CACHE[key]


def topk_sim(emb, B: np.ndarray, k: int = 3) -> float | None:
    if not len(B):
        return None
    s = np.sort(B @ np.asarray(emb, np.float32))[::-1]
    return float(np.mean(s[:min(k, len(s))]))


def tier(h_ratio: float, th: dict) -> tuple[str, float]:
    """景别 / 脸大小分档（特写最严）：th = {"tiers": [[h_min, 名, 线], ...]} 从大到小"""
    for h_min, name, line in th["tiers"]:
        if h_ratio >= h_min:
            return name, float(line)
    return "太小", None


def score(path: str, req: dict) -> dict:
    """req = {"banks": {角色: [身份库图…]}, "cast": [{"id", "presence"}], "th": {...}} → 每张脸是谁、像不像、是否拦"""
    th = req["th"]
    B = {c: bank(fs) for c, fs in req["banks"].items()}
    allowed = {c["id"] for c in req.get("cast") or []}
    out, bad = [], []
    for f in faces(path):
        name, line = tier(f["h_ratio"], th)
        if line is None:
            continue
        sims = {c: topk_sim(f["emb"], b, th.get("k", 3)) for c, b in B.items()}
        sims = {c: round(s, 3) for c, s in sims.items() if s is not None}
        best = max(sims, key=sims.get) if sims else None
        row = {"bbox": [round(v, 1) for v in f["bbox"]], "h_ratio": round(f["h_ratio"], 3), "tier": name, "line": line, "sims": sims,
               "best": best, "best_sim": sims.get(best) if best else None}
        if best is None or sims[best] < line:
            near = best is not None and sims[best] >= line - th.get("margin", 0.08)
            row["verdict"] = "临界" if near else "陌生脸"
            if best in allowed and near:
                row["verdict"] = "临界"
            bad.append(row)
        elif best not in allowed:
            row["verdict"] = "不该出现的人"
            bad.append(row)
        else:
            row["verdict"] = "认出"
        out.append(row)
    return {"faces": out, "blocking": [r for r in bad if r["verdict"] != "临界"], "borderline": [r for r in bad if r["verdict"] == "临界"]}


def main(argv):
    if argv and argv[0] == "score":
        print(json.dumps(score(argv[1], json.loads(argv[2])), ensure_ascii=False))
    elif argv and argv[0] == "embed":           # 标定用：每张图所有脸的特征
        for p in argv[1:]:
            print(json.dumps({"path": p, "faces": faces(p)}, ensure_ascii=False), flush=True)
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
