"""补登记：唯一出图路径（workflow=frame_v9_unified）版本缺 params.post / 交付尺寸的，按文件实际尺寸补上并重判坏图（不改“当前”）。
REFLOCK 11-01：take 7 被误判“坏图：768×1344 与请求的 1152×2016 不符”的存量修复。"""
import glob
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in ("services/render_router", "services/agent", "packages/schema"):
    sys.path.insert(0, str(ROOT / p))
from PIL import Image  # noqa: E402
from ns_render import image_check as IC, pipeline as P  # noqa: E402


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    out = []
    for f in glob.glob(str(P.RENDERS / "**" / "takes.json"), recursive=True):
        sid = "-".join(Path(f).parent.parts[-2:])
        with P.shot_lock(sid):
            d = json.load(open(f, encoding="utf-8"))
            ch = False
            for t in d["takes"]:
                if t.get("workflow") != "frame_v9_unified" or (t.get("params") or {}).get("post"):
                    continue
                before = IC.check_take(t, P.DATA)
                fw, fh = Image.open(P.DATA / t["file"]).size
                raw = P.DATA / (t.get("raw_file") or t["file"])
                rw, rh = Image.open(raw).size if raw.exists() else (fw, fh)
                params = dict(t.get("params") or {})
                params["post"] = {"file": t["file"], "from": t.get("raw_file"), "size": [fw, fh], "rendered_size": [rw, rh],
                                  "steps": [f"lanczos {rw}×{rh} → {fw}×{fh}", "USM radius 1.2 percent 60 threshold 2"],
                                  "repaired_by": "tools/gen_contract/backfill_v9_params.py"}
                eff = dict(params.get("effective") or {})
                eff.update(width=fw, height=fh, rendered_size=[rw, rh], render_scale=round(rw / fw, 3))
                params["effective"] = eff
                params["preset"] = params.get("preset") or "frame_v9"
                t["params"] = params
                t["bad"] = IC.check_take(t, P.DATA)
                ch = True
                out.append((sid, t["stage"], t["n"], before, t["bad"]))
            if ch:
                P._save_takes(sid, d)
    for x in out:
        print(x)
    print("补登记", len(out))


if __name__ == "__main__":
    main()
