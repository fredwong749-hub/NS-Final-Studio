"""V2（ep02_iter 2026-10-31）：节奏收紧 pace_trims（项目方“节奏有点慢，慢溜溜的”）。"""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "post"))

from ns_post.assemble import EDIT_DEFAULTS, pace_trims, split_pieces  # noqa: E402


def test_dialogue_shot_keeps_lead_and_tail_pad():
    h, t = pace_trims(6.5, lines=[(1.4, 3.0), (3.4, 4.6)], lead_s=0.3, tail_pad_s=0.4)
    assert (h, t) == (1.1, 1.5)          # 第一句前留 0.3、最后一句后留 0.4


def test_voiceover_shot_untouched():
    assert pace_trims(12.0, lines=[], has_vo=True) == (0.0, 0.0)


def test_tts_dialogue_only_trims_tail():
    h, t = pace_trims(6.0, lines=[], tts_speech_s=2.0, lead_s=0.3, tail_pad_s=0.4)
    assert h == 0.0 and t == 3.3


def test_idle_shot_capped_at_most_motion_window():
    fps = 24
    d = np.full(8 * fps - 1, 0.2)
    d[4 * fps:7 * fps] = 3.0             # 4–7 s 动作最多
    h, t = pace_trims(8.0, lines=[], idle_max_s=4.0, diffs=d, fps=fps)
    assert abs((8.0 - h - t) - 4.0) < 1e-6 and 3.0 <= h <= 4.0


def test_min_keep_respected():
    h, t = pace_trims(2.0, lines=[(0.1, 0.2)], lead_s=0.0, tail_pad_s=0.0, min_keep_s=1.5)
    assert 2.0 - h - t >= 1.5 - 1e-6


def test_defaults_off_until_config():
    assert EDIT_DEFAULTS["pace_tighten"] is False and EDIT_DEFAULTS["jl_cut_s"] == 0.0


def test_split_at_4_5():
    p = split_pieces(9.0, max_s=4.5, min_piece_s=2.0, zoom=1.15)
    assert len(p) == 2 and p[1][2] == 1.15


def test_voiceover_drop_shots(tmp_path):
    import json
    from ns_post.assemble import Settings, voiceover_drop_shots
    cfg = tmp_path / "rq.json"
    cfg.write_text(json.dumps({"post": {"voiceover_drop": {"default": [], "per_episode": {"2": [8, "S11"]}}}}),
                   encoding="utf-8")
    assert voiceover_drop_shots(2, None, cfg) == {8, 11}          # 项目方 10-31：ep02 去掉 S8 / S11 独白
    assert voiceover_drop_shots(3, None, cfg) == set()
    assert voiceover_drop_shots(2, Settings(voiceover_drop=[]), cfg) == set()   # 显式空 = 不去
    assert 5 in voiceover_drop_shots(9, Settings(voiceover_drop="all"), cfg)
