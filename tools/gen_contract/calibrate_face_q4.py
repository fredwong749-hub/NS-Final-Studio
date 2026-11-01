"""Q4 改量脸 + Q2 鞋“加装饰”探针的标定（总调度 11-01：整图 Laplacian 留出复核 AUC 0.41 作废）。
标签：总调度 11-01 亲标的留出集（data/review_pages/asset_reflock/heldout_bakeoff.json，BAKEOFF 整理；label 1 = 可接受 / 是那双鞋）。
度量：gpu33 上一次 ssh 算（tools/gen_contract/remote_score.full_score，metrics.face_texture / probe 与笔记本同一份代码）。
评估：每个候选指标的 AUC；单指标阈值 / 两指标逻辑回归都做留一交叉验证（LOO）报告留出 AUC 与判对率。
输出 data/review_pages/asset_reflock/q4_face_calibration.json

    .venv/Scripts/python.exe tools/gen_contract/calibrate_face_q4.py
"""
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
for p in ("services/agent", "services/render_router", "packages/schema", "tools/gen_contract"):
    sys.path.insert(0, str(ROOT / p))
import remote_score as RS  # noqa: E402

HB = ROOT / "data/review_pages/asset_reflock/heldout_bakeoff.json"
OUT = ROOT / "data/review_pages/asset_reflock/q4_face_calibration.json"
SHOE_REF = "assets/characters/lin_wan/items/shoes/S01_side45_s0.png"


def auc(y, s):
    y, s = np.asarray(y), np.asarray(s, float)
    pos, neg = s[y == 1], s[y == 0]
    if not len(pos) or not len(neg):
        return None
    return float(((pos[:, None] > neg[None, :]).sum() + 0.5 * (pos[:, None] == neg[None, :]).sum()) / (len(pos) * len(neg)))


def loo_threshold(y, s, higher_good=True):
    """留一：用其余样本选最佳阈值，判留出那张；返回留出判对率与留出分数列表（算 AUC 用 s 本身，阈值只影响判对率）"""
    y, s = np.asarray(y), np.asarray(s, float)
    if not higher_good:
        s = -s
    ok = 0
    for i in range(len(y)):
        m = np.ones(len(y), bool)
        m[i] = False
        cand = np.unique(s[m])
        best = max(cand, key=lambda t: ((s[m] >= t) == (y[m] == 1)).mean())
        ok += int((s[i] >= best) == (y[i] == 1))
    return ok / len(y)


def loo_logreg(y, X):
    from sklearn.linear_model import LogisticRegression
    y, X = np.asarray(y), np.asarray(X, float)
    X = (X - X.mean(0)) / (X.std(0) + 1e-9)
    pr = np.zeros(len(y))
    for i in range(len(y)):
        m = np.ones(len(y), bool)
        m[i] = False
        c = LogisticRegression(C=1.0, max_iter=1000).fit(X[m], y[m])
        pr[i] = c.predict_proba(X[i:i + 1])[0, 1]
    return auc(y, pr), float(((pr >= 0.5) == (y == 1)).mean())


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    hb = json.loads(HB.read_text(encoding="utf-8"))
    q4 = [r for r in hb["Q4"]["rows"] if r.get("label") in (0, 1)]
    q2 = [r for r in hb["Q2_shoe"]["rows"] if r.get("label") in (0, 1)]
    items = [{"id": "q4/" + r["code"], "file": str(ROOT / r["path"]), "post": None, "rows": [], "scene": None} for r in q4]
    items += [{"id": "q2/" + r["code"], "file": str(ROOT / r["path"]), "post": None, "scene": None,
               "rows": [{"label": "鞋", "role": "item", "zone": "feet", "source": "wardrobe", "file": SHOE_REF}]} for r in q2]
    m = RS.full_score("gpu33", items)
    loc = m.get("local") or {}
    out = {"n_q4": len(q4), "n_q2": len(q2), "clip_gpu": m.get("clip_gpu"), "rows_q4": [], "rows_q2": []}
    for r in q4:
        d = (loc.get("q4/" + r["code"]) or {}).get("Q4") or {}
        out["rows_q4"].append({**{k: r[k] for k in ("code", "path", "label")}, **{k: d.get(k) for k in
                               ("lap_full", "face_hf", "face_lap", "face_oil", "p_plastic", "face_px", "sat_mean")}})
    for r in q2:
        q = ((loc.get("q2/" + r["code"]) or {}).get("Q2") or [{}])[0]
        out["rows_q2"].append({**{k: r[k] for k in ("code", "path", "label")}, "clip": q.get("clip"), "p_embellished": q.get("p_embellished")})
    rows = [x for x in out["rows_q4"] if x.get("face_hf") is not None]
    y = [x["label"] for x in rows]
    res = {"n_with_face": len(rows), "no_face": [x["code"] for x in out["rows_q4"] if x.get("face_hf") is None]}
    for k, hg in (("face_hf", True), ("face_lap", True), ("face_oil", False), ("p_plastic", False), ("lap_full", True)):
        s = [x[k] for x in rows]
        a = auc(y, s if hg else [-v for v in s])
        res[k] = {"auc": None if a is None else round(a, 3), "loo_acc": round(loo_threshold(y, s, hg), 3)}
    try:
        a, acc = loo_logreg(y, [[x["face_hf"], x["p_plastic"]] for x in rows])
        res["logreg_face_hf+p_plastic"] = {"loo_auc": round(a, 3), "loo_acc": round(acc, 3)}
    except Exception as e:  # noqa: BLE001
        res["logreg_err"] = repr(e)[:200]
    out["q4_eval"] = res
    y2 = [x["label"] for x in out["rows_q2"]]
    out["q2_eval"] = {"clip_auc": auc(y2, [x["clip"] for x in out["rows_q2"]]),
                      "embellished_auc": auc(y2, [-x["p_embellished"] for x in out["rows_q2"]])}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"q4_eval": res, "q2_eval": out["q2_eval"]}, ensure_ascii=False, indent=1))
    for x in out["rows_q2"]:
        print("shoe", x["code"], x["label"], x["clip"], x["p_embellished"], Path(x["path"]).name)


if __name__ == "__main__":
    main()
