"""Pull character-asset renders from gpu3, deliver selected ones into assets/characters/<id>/..., keep manifest.json.

    python collect.py pull stage1                      # gpu3 out/stage1 -> tools/char_assets/pulled/stage1
    python collect.py sheet stage1 previews/assets/x.jpg [prefix...]   # review contact sheet of pulled images
    python collect.py deliver stage1 <job_id> <dest> <kind> [--item <wardrobe id>] [--default] [--note ...]
          dest is relative to assets/characters/, e.g. lin_wan/plates/LW-ID-F.png
    python collect.py reject stage1 <job_id> <reason>  # recorded in pulled/<stage>/_rejected.json (never delivered)

manifest.json (one per character dir; a JSON list like fredw-d9's items/makeup/manifest.json; "file" is relative
to the manifest's directory):
  {"file": "plates/LW-ID-F.png", "kind": "identity/plate", "design": "LW-ID-F", "name": "正脸底片",
   "wardrobe_item": null, "default": false, "prompt": ..., "seed": ..., "model": ..., "vae": ..., "loras": [...],
   "workflow": "qwen_edit", "sampler": {...}, "references": [...], "sha256": ..., "source_job": ...,
   "created_at": ..., "gpu": 1, "seconds": 93.1, "notes": [...]}
Kinds: identity/master identity/plate identity/expression identity/candidate item/<outfit|shoes|nails|hair> look
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).parent
PULLED = HERE / "pulled"
CHARS = ROOT / "assets" / "characters"
G_OUT = "/root/claude-kimi-ns-studio-v1/nsfs_assets/out"
G_REFS = "/root/claude-kimi-ns-studio-v1/nsfs_assets/refs/"
REFS_MAP = HERE / "refs_map.json"   # gpu3 ref file name -> project-relative source path


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def pull(stage: str):
    d = PULLED / stage
    d.mkdir(parents=True, exist_ok=True)
    subprocess.run(["scp", "-q", "-o", "BatchMode=yes", f"gpu33:{G_OUT}/{stage}/*", str(d)], check=False)
    print(len(list(d.glob("*.png"))), "png in", d)


def font(sz):
    for f in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/arial.ttf"):
        try:
            return ImageFont.truetype(f, sz)
        except OSError:
            pass
    return ImageFont.load_default()


def sheet(files: list[Path], out: Path, cell=360, cols=6, labels: list[str] | None = None):
    rows = (len(files) + cols - 1) // cols
    s = Image.new("RGB", (cols * cell, rows * (cell + 28)), "white")
    dr, ft = ImageDraw.Draw(s), font(16)
    for k, f in enumerate(files):
        im = Image.open(f).convert("RGB")
        im.thumbnail((cell, cell))
        x, y = (k % cols) * cell, (k // cols) * (cell + 28)
        s.paste(im, (x + (cell - im.width) // 2, y))
        dr.text((x + 4, y + cell + 4), (labels[k] if labels else f.stem)[:40], fill="black", font=ft)
    out.parent.mkdir(parents=True, exist_ok=True)
    s.save(out, quality=90)
    print(out)


def ref_paths(refs: list[str]) -> list[str]:
    m = json.loads(REFS_MAP.read_text(encoding="utf-8")) if REFS_MAP.exists() else {}
    return [m.get(Path(r).name, r) for r in refs]


def deliver(stage, job_id, dest, kind, item=None, default=False, notes=(), design=None, name=None):
    src = PULLED / stage / f"{job_id}.png"
    job = json.loads((PULLED / stage / f"{job_id}.json").read_text(encoding="utf-8"))
    out = CHARS / dest
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(src.read_bytes())
    char = dest.split("/")[0]
    mpath = CHARS / char / "manifest.json"
    man = json.loads(mpath.read_text(encoding="utf-8")) if mpath.exists() else []
    rel = out.relative_to(CHARS / char).as_posix()       # relative to the manifest's dir (same as items/makeup)
    t2i = "refs" not in job
    entry = {
        "file": rel, "kind": kind, "design": design or out.stem, "name": name or out.stem,
        "wardrobe_item": item, "default": default,
        "prompt": job["prompt"], "negative": job.get("negative") if t2i else None, "seed": job["seed"],
        "model": job.get("unet", "qwen_image_2.1_int8_convrot.safetensors"),
        "workflow": "qwen_t2i" if t2i else "qwen_edit",
        "vae": job.get("vae", "texture_fix_vae_for_qwen_image_2.1_bf16.safetensors"),
        "text_encoder": "qwen3vl_8b_int8_convrot.safetensors", "loras": job.get("loras", []),
        "sampler": {"steps": job.get("steps", 25), "cfg": job.get("cfg", 1.0), "sampler": job.get("sampler", "euler"),
                    "scheduler": job.get("scheduler", "simple"), "resolution": job.get("resolution", 0),
                    "latent": "empty" if t2i else job.get("latent", "empty"),
                    "size": [job.get("w"), job.get("h")] if job.get("w") else "follows image_1"},
        "references": ref_paths(job.get("refs", [])),
        "sha256": sha256(out), "source_job": f"gpu3:{G_OUT}/{stage}/{job_id}.png",
        "created_at": job.get("_at"), "gpu": job.get("_gpu"), "seconds": job.get("_seconds"),
        "provenance": "generated", "notes": list(notes),
    }
    if default and item:  # one default per wardrobe item
        for e in man:
            if e.get("wardrobe_item") == item and e["kind"] == kind:
                e["default"] = False
    man = [e for e in man if e["file"] != rel] + [entry]
    man.sort(key=lambda e: (e["kind"], e["file"]))
    mpath.write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
    print("delivered", rel)


def reject(stage, job_id, reason):
    p = PULLED / stage / "_rejected.json"
    d = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    d[job_id] = reason
    p.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[0] == "pull":
        pull(a[1])
    elif a[0] == "sheet":
        fs = sorted((PULLED / a[1]).glob("*.png"))
        if a[3:]:
            fs = [f for f in fs if any(f.stem.startswith(p) for p in a[3:])]
        sheet(fs, ROOT / a[2])
    elif a[0] == "deliver":
        kw = {"item": None, "default": False, "notes": [], "design": None, "name": None}
        rest = a[5:]
        while rest:
            k = rest.pop(0)
            if k == "--item":
                kw["item"] = rest.pop(0)
            elif k == "--default":
                kw["default"] = True
            elif k in ("--design", "--name"):
                kw[k[2:]] = rest.pop(0)
            elif k == "--note":
                kw["notes"].append(rest.pop(0))
        deliver(a[1], a[2], a[3], a[4], **kw)
    elif a[0] == "reject":
        reject(a[1], a[2], " ".join(a[3:]))
