"""fredw-92/LB: LoRA training captions from the writer LLM (purpose lora_llm, config/llm_providers.json).

Claude does not author captions (REQUIREMENTS G2/G4/G5). This tool only sends each training scene's technical
metadata (Blender scene parameters, no prompt text) to the LLM configured for `lora_llm` and stores the reply
verbatim:
  <out>/<scene>.raw.json   full reply {content, reasoning, usage, model, provider, at, request}
  <out>/<scene>.txt        reply content as returned (outer whitespace stripped only)
Resumable: scenes that already have a .txt are skipped. Empty replies are recorded as .fail.json, no .txt.

  python tools/lb_llm_captions.py --meta data/lb/jewellery_meta/meta_all.json --concept lbrng9 \
      --out data/lb/captions_llm/lbrng9 [--limit 1]
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "services" / "api"))

from ns_api import llm_config as LC  # noqa: E402

# Task instruction only (format of the deliverable). It contains no descriptive caption text.
SYSTEM = (
    "You write captions for an image LoRA training dataset. The user message is the JSON metadata of one synthetic "
    "training image (a Blender render of a fictional adult body, later photorealised). Reply with exactly one caption "
    "line for that image. The caption must start with the trigger word given in the field `trigger`, followed by a "
    "comma. Describe what the metadata says is in the image (framing, pose, lighting, skin tone, and the jewellery "
    "with its exact count and placement from `counts`). Output only the caption line, no quotes, no explanations."
)
KEEP = ("concept", "variant", "pose", "framing", "lighting", "skin_tone", "counts", "all_pieces_visible", "res")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--meta", required=True)
    ap.add_argument("--concept", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    metas = json.loads(Path(a.meta).read_text(encoding="utf-8"))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    rv = LC.resolve("lora_llm")
    done = 0
    for scene, m in sorted(metas.items()):
        if m.get("concept") != a.concept or not m.get("all_pieces_visible"):
            continue
        if (out / f"{scene}.txt").exists():
            continue
        if a.limit and done >= a.limit:
            break
        req = {"trigger": a.concept, **{k: m[k] for k in KEEP if k in m}}
        user = json.dumps(req, ensure_ascii=False)
        try:
            r = LC.complete_text(rv, SYSTEM, user, max_tokens=400)
        except Exception as e:  # noqa: BLE001
            (out / f"{scene}.fail.json").write_text(json.dumps({"error": str(e)[:500], "request": req}, ensure_ascii=False))
            print(scene, "FAIL", str(e)[:200], flush=True)
            continue
        rec = {**r, "model": rv["model"], "provider": rv["id"], "purpose": "lora_llm",
               "at": datetime.datetime.now().isoformat(timespec="seconds"), "system": SYSTEM, "request": req}
        (out / f"{scene}.raw.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
        content = (r.get("content") or "").strip()
        if not content:
            (out / f"{scene}.fail.json").write_text(json.dumps({"error": "empty content", "request": req}))
            print(scene, "EMPTY", flush=True)
            continue
        (out / f"{scene}.txt").write_text(content + "\n", encoding="utf-8", newline="\n")
        done += 1
        print(scene, "ok", len(content), flush=True)
    print("done", done)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
