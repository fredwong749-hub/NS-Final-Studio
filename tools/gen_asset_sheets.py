"""每个类别一张拼图 → golden/assets/sheets/<category>.jpg；并打印各目录的数量。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import gen_assets as G

ROOT = G.ROOT
B = G.BASE
CATS = {
    "plates": (B / "plates", lambda p: p.name == "master.png" or (p.stem.startswith(("id_", "body_")) and "superseded" not in p.stem), 6),
    "expressions": (B / "expressions", None, 6),
    "outfit_products": (B / "items/outfit", lambda p: "_worn" not in p.stem, 6),
    "outfit_worn": (B / "items/outfit", lambda p: "_worn" in p.stem, 6),
    "shoes": (B / "items/shoes", None, 5),
    "nails": (B / "items/nails", None, 6),
    "hair": (B / "items/hair", None, 6),
    "makeup": (B / "items/makeup", lambda p: p.stem.startswith("L"), 5),
    "accessory": (B / "items/accessory", None, 4),
    "tattoo": (B / "items/tattoo", None, 4),
    "looks": (B / "looks", None, 6),
}
counts = {}
for name, (folder, flt, cols) in CATS.items():
    files = sorted(p for p in folder.glob("*.png") if flt is None or flt(p))
    counts[name] = len(files)
    if files:
        print(G.sheet(folder, G.SHEETS / f"{name}.jpg", files, cols=cols, cell=320, title=f"lin_wan · {name} ({len(files)})"))
men = sorted((ROOT / "assets/characters").glob("*/candidates/*.png"))
counts["male_candidates"] = len(men)
if men:
    print(G.sheet(None, G.SHEETS / "male_candidates.jpg", men, cols=7, cell=260, title=f"male lead candidates ({len(men)})"))
print(counts)
