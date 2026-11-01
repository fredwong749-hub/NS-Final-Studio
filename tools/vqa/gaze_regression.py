"""看镜头回归（L-102 / ITERATION_PROTOCOL §G1：判定落成本地模型 + 回归集，不靠人工目检）。
对 data/vqa/gate_calib/gaze_regression.json 每张图跑和生产同一套判定：本地看图整图 eye_contact → MediaPipe 高置信度旁证 →
拿不准带裁脸复判（contract.recheck_gaze_band）。和人工标签不一致的列出来，退出码 1。图片只进本地看图服务（K-REV-V01）。

    .venv/Scripts/python.exe tools/vqa/gaze_regression.py   → data/vqa/gate_calib/gaze_regression_result.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "services/agent"), str(ROOT / "packages/qc")]


def judge(path: Path, shot: str) -> dict:
    from ns_agent.vqa import client as VC
    from ns_agent.vqa import continuity as CT
    from ns_agent.vqa import contract as VQ
    prompt = (CT.shot_rec(shot) or {}).get("img_prompt") or ""
    v = VC.inspect_image(str(path), prompt, [])
    if v.get("error"):
        return {"error": v["error"]}
    faces = VQ.gaze_mp(path)
    VQ.merge_gaze(v, faces, prompt)
    VQ.recheck_gaze_band(v, faces, path, prompt)
    return {"eye_contact": "eye_contact" in (v.get("defects") or []), "evidence": (v.get("checks") or {}).get("eye_contact"),
            "gaze_mp": v.get("gaze_mp"), "gaze_recheck": v.get("gaze_recheck")}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    items = json.loads((ROOT / "data/vqa/gate_calib/gaze_regression.json").read_text(encoding="utf-8"))["items"]
    rows, bad = [], 0
    for it in items:
        p = ROOT / it["path"]
        if not p.exists():
            rows.append({**it, "result": "图不在"})
            continue
        r = judge(p, it["shot"])
        ok = None if "error" in r else (r["eye_contact"] == (it["label"] == "看镜头"))
        bad += ok is False
        rows.append({**it, **r, "ok": ok})
        print(it["path"].split("/")[-1], it["label"], "→", "看镜头" if r.get("eye_contact") else ("未测" if "error" in r else "不看"),
              "OK" if ok else ("未测" if ok is None else "不一致"), flush=True)
    (ROOT / "data/vqa/gate_calib/gaze_regression_result.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"看镜头回归：{len(rows)} 张，不一致 {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
