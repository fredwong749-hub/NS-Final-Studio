"""
写实精修力度 A/B（项目方 2026-10-30：保留参考图的“感觉”，写实只作为质感）。只用非成人镜头，沙箱渲染。

    uv run python tools/ab_refine.py --out golden/quality_v2/owner_ab --shots ep01-S3 ep01-S6 ep03-S2

每镜：两段式首帧（项目方参考图脸部裁切作身份）→ 同一张原图分别做 无精修 / 现行精修 / 轻精修 / PureLens 轻精修，
出带分数的对比表与脸部放大对比表。
"""
import argparse
import json
import sys
import time
from pathlib import Path

from PIL import Image

from ns_render import pipeline as P
from ns_render.comfy_client import ComfyClient

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ab_quality import _lines, label, non_adult, sheet  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
VARIANTS = {
    "current": (0.30, [("krea2_film_texture_qwen21.safetensors", 0.5)], ""),
    "light": (0.22, [("krea2_film_texture_qwen21.safetensors", 0.35)], ""),
    "purelens_light": (0.22, [("purelens_qwen21.safetensors", 0.4)], "p3r4l4ns，"),
}


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="golden/quality_v2/owner_ab")
    ap.add_argument("--shots", nargs="*", default=["ep01-S3", "ep01-S6", "ep03-S2"])
    ap.add_argument("--variants", nargs="*", default=list(VARIANTS))
    args = ap.parse_args()
    out = (ROOT / args.out).resolve()
    P.DATA, P.RENDERS, P.QC_LOG = out / "work", out / "work" / "renders", out / "work" / "qc.jsonl"
    client = ComfyClient()
    script = P.load_script()
    shots = [s for s in args.shots if non_adult(script, s)]
    res = {}
    for sid in shots:   # 先全部 Turbo，再全部 Base，减少模型切换
        t0 = time.time()
        t = P.render_image(client, script, sid, candidates=2, rounds=1)
        res[sid] = {"base": {"file": str(P.DATA / t.file), "score": t.score, "secs": round(time.time() - t0, 1),
                             "n": t.n}}
        print(sid, "base", res[sid]["base"]["secs"], (t.score or {}).get("total"), flush=True)
    prefix0, den0, loras0 = P.REFINE_PREFIX, P.REFINE_DENOISE, P.REFINE_LORAS
    for v in args.variants:
        den, loras, trig = VARIANTS[v]
        P.REFINE_DENOISE, P.REFINE_LORAS, P.REFINE_PREFIX = den, loras, trig + prefix0
        P.REFINE_TOLERANCE = 9.0   # A/B：全部设为当前，方便取文件
        for sid in shots:
            P.set_active(sid, "image", res[sid]["base"]["n"])
            t0 = time.time()
            t = P.refine_image(client, script, sid)
            res[sid][v] = {"file": str(P.DATA / t.file), "score": t.score, "secs": round(time.time() - t0, 1)}
            print(sid, v, res[sid][v]["secs"], (t.score or {}).get("total"), flush=True)
    P.REFINE_DENOISE, P.REFINE_LORAS, P.REFINE_PREFIX = den0, loras0, prefix0
    (out / "results.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    cols = ["base", *args.variants]
    full, faces = [], []
    owner = Image.open(ROOT / "tools/char_assets/refs/lw_face_closeup_768.png")
    for sid in shots:
        full.append([label(Image.open(res[sid][c]["file"]), _lines(res[sid][c]["score"], res[sid][c]["secs"]))
                     for c in cols])
        row = []
        for c in cols:
            from ns_render.score import face_box
            f = Path(res[sid][c]["file"])
            im = Image.open(f).convert("RGB")
            box = face_box(f)
            if box:
                x, y, w, h = box
                m = int(0.6 * max(w, h))
                im = im.crop((max(0, x - m), max(0, y - m), min(im.width, x + w + m), min(im.height, y + h + m)))
            row.append(label(im, [c]))
        faces.append(row)
    sheet(full, ["无精修", *args.variants], out / "sheet_owner_refine.jpg", shots)
    sheet(faces + [[label(owner, ["项目方参考图"])] + [None] * (len(cols) - 1)],
          ["无精修", *args.variants], out / "sheet_owner_refine_faces.jpg", [*shots, "参考"])
    print("对比表：", out / "sheet_owner_refine.jpg", out / "sheet_owner_refine_faces.jpg")


if __name__ == "__main__":
    sys.exit(main())
