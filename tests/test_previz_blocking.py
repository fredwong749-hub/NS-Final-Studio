import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "previz"))
import numpy as np
import blocking as B


def test_s4_specs_render_small():
    for n in ("V1_ots", "V2_insert", "V3_reverse"):
        spec = json.loads((ROOT / "data/previz/ep01-S4" / f"{n}.json").read_text(encoding="utf-8"))
        depth, ids, joints, names, ci = B.render(spec, 0.08)
        assert depth.shape == ids.shape and np.isfinite(depth).any()
        assert len(set(np.unique(ids)) - {0}) >= 1


def test_deterministic():
    spec = json.loads((ROOT / "data/previz/ep01-S4/V1_ots.json").read_text(encoding="utf-8"))
    a = B.render(spec, 0.06)[0]
    b = B.render(spec, 0.06)[0]
    assert np.array_equal(a, b)
