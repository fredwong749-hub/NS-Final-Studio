"""重出某张资产（换种子）并放回 _s0 位置：uv run python tools/redo_asset.py items/outfit/O02_product [offset]"""
import json, subprocess, sys
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parent.parent
jid, off = sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 1
folder = ROOT / "assets/characters/lin_wan" / Path(jid).parent
stem = Path(jid).name
old = folder / f"{stem}_s0.png"
mp = folder / "manifest.json"
subprocess.run(["uv", "run", "python", "tools/gen_assets.py", "run", "--only", jid, "--seed-offset", str(off)] + sys.argv[3:],
               cwd=ROOT, check=True)
new = folder / f"{stem}_s{off}.png"
if not new.exists():
    sys.exit(f"redo failed: {new} missing")
m = json.loads(mp.read_text(encoding="utf-8"))
m = [e for e in m if e["file"] != old.name]
for e in m:
    if e["file"] == new.name:
        e["file"] = old.name
        e["note"] = f"redo (seed offset {off}) replacing a rejected s0"
old.unlink(missing_ok=True)
new.rename(old)
mp.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")
print("replaced", old)
