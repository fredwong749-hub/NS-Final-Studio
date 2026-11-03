"""契约阈值标定第二轮（总调度 11-01）：用总调度亲审认可的 IMGGEN 对照图作标定集。
  Q4（质感，脸框区域）：可接受 = v9 / v10 / v10L；不可接受 = v0（塑料、糊）
  Q2（造型）：穿对 = vR / v10（挂了造型参考）；穿错 = v0 / v3 / vN（只靠文字）
图：data/pipeline/runs/<legacy run>/images/imgfix/<镜>/<变体>（results.json 的 file = 最终交付图，S★ 为 post 后）。
脸框：最终图 scp 到 gpu33 原地 score_remote（tools/gen_contract/remote_score.py）。
输出：data/review_pages/asset_reflock/calibration_imgfix.json

    .venv/Scripts/python.exe tools/gen_contract/calibrate_imgfix.py [--q4] [--q2]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "autopilot"))
import runs as RUNS  # noqa: E402
_LEGACY = RUNS.legacy_run(ROOT)   # I-16：第一季专用历史工具（入口 gate_legacy_tool 要求显式 --run）
for p in ("services/agent", "packages/schema", "services/render_router", "tools/pipeline", "tools/prompt_v2", "tools/gen_contract"):
    sys.path.insert(0, str(ROOT / p))

FX = ROOT / ("data/pipeline/runs/" + _LEGACY + "/images/imgfix")
OUT = ROOT / "data/review_pages/asset_reflock/calibration_imgfix.json"
GOOD4, BAD4 = ("v9", "v10", "v10L"), ("v0",)
RIGHT2, WRONG2 = ("vR", "v10"), ("v0", "v3", "vN")


def jl(p, d=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return d


def main():
    RUNS.gate_legacy_tool(None, __file__)
    sys.stdout.reconfigure(encoding="utf-8")
    from PIL import Image
    from ns_agent.gen_contract import postflight as PO
    res = jl(FX / "results.json", {})
    out = jl(OUT, {}) or {}
    files = {k: ROOT / v["file"] for k, v in res.items() if v.get("file") and v["vid"] in GOOD4 + BAD4 + RIGHT2 + WRONG2
             and (ROOT / v["file"]).exists()}
    if "remote" not in out:
        # 出图机器上原地打分（K-OPS-122）：host_path = ComfyUI 原始输出（S★ 为 1.5× 出图），脸框按最终图尺寸换算
        import remote_score as RS
        m = RS.score("gpu33", {k: res[k]["host_path"] for k in files if res[k].get("host_path")})
        out["remote"] = {}
        for k, v in m["items"].items():
            fw = Image.open(files[k]).size[0]
            rw = (v.get("size") or [fw])[0]
            sc = fw / rw if rw else 1.0
            out["remote"][k] = {"scale": round(sc, 4), "faces": [{"bbox": [round(x * sc, 1) for x in f["bbox"]], "h_ratio": f["h_ratio"],
                                                                    "sims": f["sims"]} for f in v.get("faces", [])]}
        OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    if "--q4" in sys.argv or len(sys.argv) == 1:
        rows = []
        for k, f in files.items():
            vid = res[k]["vid"]
            if vid not in GOOD4 + BAD4:
                continue
            faces = (out["remote"].get(k) or {}).get("faces") or []
            t = PO.texture(Image.open(f).convert("RGB"), faces[0]["bbox"] if faces else None)
            rows.append({"key": k, "vid": vid, "label": "good" if vid in GOOD4 else "bad", **t})
            print("q4", k, t, flush=True)
        out["q4"] = rows
        OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    if "--q2" in sys.argv or len(sys.argv) == 1:
        import image_jobs as IJ
        from ns_agent import asset_refs as AR
        rows = []
        prod = IJ.production_globals()
        for k, f in files.items():
            vid, shot = res[k]["vid"], res[k]["shot"]
            if vid not in RIGHT2 + WRONG2:
                continue
            n = int(shot[2:4])
            __import__("os").environ.setdefault("NS_ALLOW_P4_SOURCE", "1")   # CLEANUP 11-01（K-OPS-Q24，总调度 r2：P4 旧来源迁到导入稿）：标定 / 对照实验复现当时 P4 稿出的图，属调研用途
            si, ep = IJ.load_episode(ROOT / f"data/pipeline/runs/{_LEGACY}/ep{n:02d}/P4_ep{n:02d}.md")
            s = next(x for x in ep.shots if f"ep{n:02d}-S{x.index}" == shot)
            sr, plan = AR.plan_for(_LEGACY, ep, s)
            loc = PO.measure_local(f, AR.record(sr, plan), None)
            for r in loc["Q2"]:
                rows.append({"key": k, "shot": shot, "vid": vid, "label": "right" if vid in RIGHT2 else "wrong",
                             "item": r["label"], "role": r["role"], "zone": r.get("zone"), "clip": r["clip"], "hist": r["hist"]})
                print("q2", k, r["label"], r["clip"], flush=True)
        out["q2"] = rows
        OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
