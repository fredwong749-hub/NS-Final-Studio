"""
静止镜头对照实验的汇总（fredw-92/QCV）：读 data/ab/static_fix/<镜>_<变体>.json → 每镜一张并排对照条（每行一个变体，
每行 6 帧：0%、20%…100%）+ 指标表 metrics.md / metrics.csv。只读视频，不改任何版本。
用法：.venv/Scripts/python.exe tools/ab_static_fix_report.py
"""
from __future__ import annotations

import csv
import json
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "ab" / "static_fix"
TW, TH = 180, 315
COLS = 6
ORDER = "BADCE"


def font(size):
    for f in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf"):
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            pass
    return ImageFont.load_default()


def frame_at(path: Path, t: float) -> Image.Image:
    r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{max(0.0, t):.3f}", "-i", str(path), "-frames:v", "1",
                        "-vf", f"scale={TW}:{TH}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True)
    if len(r.stdout) < TW * TH * 3:
        return Image.new("RGB", (TW, TH), (40, 40, 40))
    return Image.frombytes("RGB", (TW, TH), r.stdout[: TW * TH * 3])


def strip(shot: str, recs: list[dict]) -> Path:
    lab_w = 260
    im = Image.new("RGB", (lab_w + COLS * TW, len(recs) * TH), (20, 20, 20))
    d = ImageDraw.Draw(im)
    f1, f2 = font(20), font(15)
    for i, r in enumerate(recs):
        m = r["metrics"]
        dur = m.get("duration_s") or 1
        for c in range(COLS):
            t = dur * c / (COLS - 1) - (0.05 if c == COLS - 1 else 0)
            im.paste(frame_at(ROOT / r["file"], t), (lab_w + c * TW, i * TH))
        y = i * TH + 10
        d.text((10, y), f"{shot} 变体 {r['variant']}", fill=(255, 255, 255), font=f1)
        lines = [r["label"], f"平均帧差 {m['mean_diff']:.2f}", f"p90 {m['p90_diff']:.2f}",
                 f"静止帧 {m['still_frac'] * 100:.0f}%", f"结尾定住 {m['frozen_tail_s']:.1f}s",
                 f"首尾差 {m['first_last_diff']:.1f}", f"判定 {r['verdict']}"]
        for k, ln in enumerate(lines):
            d.text((10, y + 34 + k * 22), ln, fill=(255, 120, 120) if r["verdict"] == "fail" and k == 6 else (220, 220, 220),
                   font=f2)
    p = OUT / f"{shot}_strip.jpg"
    im.save(p, quality=88)
    return p


def main():
    from ns_render import motion_qc as MQ
    recs = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(OUT.glob("S*_?.json"))]
    for r in recs:     # 判定按当前阈值重算（config/render_quality.json motion_qc）
        j = MQ.judge(r["metrics"])
        r["verdict"], r["labels"] = j["verdict"], j["labels"]
    shots = sorted({r["shot"] for r in recs}, key=lambda s: int(s[1:]))
    rows = []
    for s in shots:
        rs = sorted([r for r in recs if r["shot"] == s], key=lambda r: ORDER.index(r["variant"]))
        strip(s, rs)
        b = next((r for r in rs if r["variant"] == "B"), None)
        for r in rs:
            m = r["metrics"]
            gain = round(m["mean_diff"] / b["metrics"]["mean_diff"], 2) if b and b["metrics"]["mean_diff"] else None
            rows.append({"shot": s, "variant": r["variant"], "label": r["label"], "seed": r["seed"],
                         "frames": r["frames"], "lane": r.get("lane"), "mean_diff": m["mean_diff"],
                         "p90_diff": m["p90_diff"], "still_frac": m["still_frac"],
                         "frozen_tail_s": m["frozen_tail_s"], "frozen_head_s": m["frozen_head_s"],
                         "first_last_diff": m["first_last_diff"], "x_vs_B": gain, "verdict": r["verdict"],
                         "labels": " ".join(r.get("labels") or []), "render_s": r.get("render_s"), "file": r["file"]})
    with (OUT / "metrics.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    md = ["| 镜 | 变体 | 做法 | 平均帧差 | ×B | p90 | 静止帧 | 结尾定住 | 开头定住 | 首尾差 | 判定 |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        md.append(f"| {r['shot']} | {r['variant']} | {r['label']} | {r['mean_diff']:.3f} | {r['x_vs_B'] or '—'} | "
                  f"{r['p90_diff']:.2f} | {r['still_frac'] * 100:.0f}% | {r['frozen_tail_s']:.1f}s | "
                  f"{r['frozen_head_s']:.1f}s | {r['first_last_diff']:.1f} | {r['verdict']} {r['labels']} |")
    (OUT / "metrics.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
