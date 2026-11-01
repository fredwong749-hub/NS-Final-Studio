"""VOX：变声只换台词时间段（段外样本不动）、默认关、没装 Seed-VC 时不拦合成。"""
import json
from pathlib import Path

import numpy as np

from ns_post import voice_convert as VC

ROOT = Path(__file__).resolve().parents[1]


def test_splice_only_touches_span():
    sr = 48000
    x = np.random.default_rng(0).uniform(-0.3, 0.3, (sr, 2)).astype(np.float32)
    conv = np.full(sr // 4, 0.5, dtype=np.float32)
    a, b = sr // 2, sr // 2 + sr // 4
    out = VC.splice(x, conv, a, b, xfade=int(0.04 * sr))
    assert out.shape == x.shape
    assert np.array_equal(out[:a], x[:a]) and np.array_equal(out[b:], x[b:])
    mid = (a + b) // 2
    assert np.allclose(out[mid], 0.5)
    assert np.allclose(out[a], x[a], atol=1e-6)          # 淡入起点 = 原样


def test_config_default_off():
    post = json.loads((ROOT / "config" / "render_quality.json").read_text(encoding="utf-8"))["post"]
    assert post["voice_conversion"]["enabled"] is False
    assert VC.config_hook(post) is None
    assert VC.config_hook({"voice_conversion": {"enabled": True, "speaker": "gu_chen", "reference": "x.wav"}})


def test_assembler_audio_no_spans_or_missing_reference(tmp_path, monkeypatch):
    assert VC.assembler_audio(tmp_path / "v.mp4", [], {"reference": "x"}, tmp_path) == (None, None)
    monkeypatch.setattr(VC, "available", lambda: True)
    conv, why = VC.assembler_audio(tmp_path / "v.mp4", [(1.0, 2.0)], {"reference": str(tmp_path / "nope.wav")},
                                   tmp_path)
    assert conv is None and "参考音色" in why
