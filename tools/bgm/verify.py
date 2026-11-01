"""交付文件复测（ffmpeg ebur128 + ffprobe）：每集 epNN.wav 的时长 / 采样率 / 位深 / 积分响度 / 真峰，与 epNN.json 的 sha256、候选对上没有。

    .venv/Scripts/python.exe tools/bgm/verify.py [--eps 1-10]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from deliver import ffmpeg, jload, load_cfg, out_dir  # noqa: E402
from report import parse_eps  # noqa: E402


def measure(wav: Path) -> dict:
    ff = ffmpeg()
    probe = Path(ff).with_name("ffprobe" + Path(ff).suffix)
    pr = json.loads(subprocess.run([str(probe), "-v", "error", "-show_entries",
                                    "stream=sample_rate,channels,bits_per_raw_sample:format=duration", "-of", "json", str(wav)],
                                   capture_output=True, text=True).stdout)
    r = subprocess.run([ff, "-hide_banner", "-nostats", "-i", str(wav), "-af", "ebur128=peak=true", "-f", "null", "-"],
                       capture_output=True, text=True)
    tail = r.stderr[r.stderr.rfind("Summary:"):]
    i = re.search(r"I:\s+(-?[\d.]+) LUFS", tail)
    pk = re.search(r"Peak:\s+(-?[\d.]+) dBFS", tail)
    st = (pr.get("streams") or [{}])[0]
    return {"duration_s": round(float(pr["format"]["duration"]), 2), "sr": int(st.get("sample_rate", 0)),
            "ch": st.get("channels"), "bits": st.get("bits_per_raw_sample"),
            "lufs": float(i.group(1)) if i else None, "true_peak": float(pk.group(1)) if pk else None}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--eps", default="1-10")
    a = ap.parse_args(argv)
    cfg = load_cfg()
    od = out_dir(cfg)
    rows = ["| 集 | 文件 | 候选 | 时长 s | 采样率 | 声道 | 位深 | 积分响度 LUFS | 真峰 dBTP | sha256 = json |", "|---|---|---|---|---|---|---|---|---|---|"]
    bad = 0
    for ep in parse_eps(a.eps):
        wav = od / f"ep{ep:02d}.wav"
        meta = jload(od / f"ep{ep:02d}.json", {}) or {}
        if not wav.is_file():
            rows.append(f"| ep{ep:02d} | 没有 | — | | | | | | | |")
            continue
        m = measure(wav)
        sha_ok = hashlib.sha256(wav.read_bytes()).hexdigest() == meta.get("sha256")
        ok = sha_ok and m["sr"] == 48000 and m["ch"] == 2 and m["true_peak"] is not None and m["true_peak"] <= cfg["output"]["true_peak_db"] + 0.05
        bad += not ok
        rows.append(f"| ep{ep:02d} | {wav.relative_to(od.parents[1]).as_posix()} | {meta.get('candidate')} | {m['duration_s']} | {m['sr']} | {m['ch']} | "
                    f"{m['bits']} | {m['lufs']} | {m['true_peak']} | {'是' if sha_ok else '**否**'} |")
    print("\n".join(rows))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
