"""VIDEO10：在本机已有的片子上跑 V6 / V7 检测器，输出逐条数值（标定阈值用）。服务器上跑，nice 低优先级。

    python calibrate_v67.py <host>      → video/calib_v67_<host>.json + 打印表
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VID = ROOT / "data/pipeline/runs/series10_v1/video"
HAND_PY = "/root/work/fredw/venv_hand/bin/python"
IDM_PY = "/root/work/fredw/venv_idm/bin/python"


def meta_of(shot: dict) -> dict:
    return {"people": max(1, len(shot.get("visible") or [])), "dialogue": shot.get("dialogue") or [],
            "voiceover": shot.get("voiceover"), "refs": shot.get("score_refs") or {}, "visible": shot.get("visible") or []}


def run(py, script, clip, meta, env):
    r = subprocess.run(["nice", "-n", "15", py, str(ROOT / "tools/series10_video" / script), str(clip),
                        json.dumps(meta, ensure_ascii=False)], capture_output=True, text=True, timeout=1800, env=env)
    ln = [x for x in r.stdout.splitlines() if x.startswith("{")]
    return json.loads(ln[-1]) if ln else {"error": r.stderr[-300:]}


def main(host):
    env = dict(os.environ, PATH=("/root/claude-kimi-ns-studio-v1/env/ffmpeg/bin" if host == "gpu33" else "/root/work/fredw/tools_bin")
               + ":" + os.environ.get("PATH", ""), OMP_NUM_THREADS="4", PYTHONUTF8="1")
    shots = {}
    for jf in ("validate_jobs.json", "jobs.json"):
        p = VID / jf
        if p.exists():
            for s in json.loads(p.read_text(encoding="utf-8"))["shots"]:
                shots.setdefault(s["shot"], s)
    out = {}
    for clip in sorted((VID / "clips").rglob("*.mp4")):
        sid = clip.name.split("__")[0]
        sh = shots.get(sid)
        if not sh:
            continue
        m = meta_of(sh)
        v6 = run(HAND_PY, "v6_limbs.py", clip, m, env)
        v7 = run(IDM_PY, "v7_lipsync.py", clip, m, env)
        out[clip.name] = {**v6, **v7}
        a, b = v6.get("v6", {}), v7.get("v7", {})
        print(clip.name, "| V6", a.get("status"), a.get("why"), {k: a.get(k) for k in ("extra_hand_frac", "dup_side_frac", "flicker", "bad_finger_frac", "empty_frac")},
              "| V7", b.get("status"), b.get("mode"), {k: b.get(k) for k in ("corr", "open_frac", "seen", "aperture_med", "aperture_p90")},
              v6.get("error", "")[:120], v7.get("error", "")[:120], flush=True)
    (VID / f"calib_v67_{host}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1])
