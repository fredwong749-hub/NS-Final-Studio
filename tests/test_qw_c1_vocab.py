"""QW-C1 运镜词表单一来源（总调度 11-02 21:5x）：validate_qwen_script 只认 config/director/camera_moves.yaml 里 enabled、
且对本剧可用（runs）的运镜，不另存词表；漂移检查。"""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in ("packages/schema", "services/agent", "services/api", "tools"):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))

import validate_qwen_script as V  # noqa: E402


def _cn():
    sp = importlib.util.spec_from_file_location("cn_t", ROOT / "services/agent/ns_agent/camera_norm.py")
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


def test_v2_vocab_accepts_run_scoped_moves():
    assert V.motion_move("bolt_push_settle，她从走廊尽头走来——中景", "series10_v2") == "bolt_push_settle"
    assert V.motion_move("handheld_follow，她走向窗边——中全景", "series10_v2") == "handheld_follow"
    assert V.motion_move("camera push in 缓慢推近，她抬眼——近景", "series10_v2") == "push_in"
    assert V.motion_move("orbit_slowmo，她转身——中景", "series10_v2") is None          # L-129 未选
    assert V.motion_move("bolt_push_settle，她走来——中景", "series10_v1") is None       # 别的剧不可用


def test_no_drift_vocab_equals_enabled_moves_for_run():
    CN = _cn()
    for run in ("series10_v2", "series10_v1"):
        want = {m["id"] for m in CN.vocab()["moves"] if CN.is_enabled(m["id"], run)}
        assert set(V.camera_vocab(run).values()) == want, run
    src = (ROOT / "tools/validate_qwen_script.py").read_text(encoding="utf-8")
    assert "OFFICIAL_MOVES" not in src                                              # 旧的第二份词表已删
    assert set(V.MOVE_TYPE) <= {m["id"] for m in CN.vocab()["moves"]}               # 类型映射只映射词表里的 id


def test_run_of_path():
    assert V.run_of_path(ROOT / "data/import/runs/series10_v2/script_v2.json") == "series10_v2"
    assert V.run_of_path(ROOT / "data/import/script_v2.json") == "series10_v1"
