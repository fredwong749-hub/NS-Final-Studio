"""#6（11-08）：冒烟剧尾帧出图方式必须与生产剧一致——冒烟验的是生产路径。
A12 证据：smoke_v2 未配 last_frame_mode → edit 旧法 → 尾帧 preflight I6/I9 连挂 3 次 → I2VA 兜底，G4 永远缺尾帧。"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_smoke_last_frame_mode_matches_production():
    runs = json.loads((ROOT / "config/compile/run_style.json").read_text(encoding="utf-8"))["runs"]
    prod = (runs.get("series10_v2") or {}).get("last_frame_mode")
    assert prod, "生产剧没配 last_frame_mode"
    assert (runs.get("smoke_v2") or {}).get("last_frame_mode") == prod
