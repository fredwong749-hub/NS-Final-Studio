"""RSI（fredw-2b 派 11-01）给“没有自动检查”的旧规则补的检查——只读源码 / 配置，不 import 重模块、不写数据。
对应规则的 owner 在自己 yaml 的 check: 里引用本文件后，删掉 enforced: false（见 docs/rsi/UNCHECKED_AUDIT.md）。"""
import ast
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _const(path: str, name: str):
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            return node.value
    raise AssertionError(f"{path} 没有 {name}")


def _regex(path: str, name: str) -> re.Pattern:
    v = _const(path, name)
    assert isinstance(v, ast.Call) and v.func.attr == "compile"
    flags = re.I if any(getattr(a, "attr", "") in ("I", "IGNORECASE") for a in v.args[1:]) else 0
    return re.compile(ast.literal_eval(v.args[0]), flags)


# K-REN-122（首帧景别档位）/ K-REV-301（视频景别）：两处档位必须同一组数字 = 规则原文
RULE_BANDS = [0.45, 0.27, 0.17, 0.115, 0.095, 0.05]


def test_size_bands_match_rule_in_image_and_video_qc():
    for p in ("tools/series10_imggen/imggen.py", "tools/series10_video/score_clip.py"):
        assert ast.literal_eval(_const(p, "BANDS")) == RULE_BANDS, p


def test_video_size_mismatch_is_two_bands():
    """K-REV-301：与剧本差 ≥2 档才判不符（defect_hunt DH-V12 同口径）"""
    src = (ROOT / "tools/qa/defect_hunt.py").read_text(encoding="utf-8")
    assert re.search(r'SIZE_RANK\.get\(v\["size_wanted"\], 0\) - SIZE_RANK\.get\(v\["size_measured"\], 0\)\) > 1', src)


# K-PRM-302：视频侧不挂身份 / 出图 LoRA；系统风格句不带奶油柔焦 / f/1.x / 浓郁饱和 / 油光
def test_video_bad_lora_and_style_regex_cover_rule_words():
    lora = _regex("tools/series10_video/build_jobs.py", "BAD_LORA_RE")
    style = _regex("tools/series10_video/build_jobs.py", "BAD_STYLE_RE")
    for n in ("lin_wan_qi_v1.safetensors", "lnwan01", "x_qi_y", "some_identity_lora"):
        assert lora.search(n), n
    for w in ("creamy soft focus", "f/1.4", "richly saturated", "oily skin", "greasy", "奶油", "油光", "浓郁饱和"):
        assert style.search(w), w


def test_recipe_style_leads_are_clean():
    style = _regex("tools/series10_video/build_jobs.py", "BAD_STYLE_RE")
    seen = 0
    for f in sorted((ROOT / "services/recipes/recipes").glob("*.yaml")):
        d = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        sl = ((d.get("prompt") or {}) if isinstance(d, dict) else {}).get("style_lead")
        if sl:
            seen += 1
            assert not style.search(sl), f"{f.name}: {sl}"
    assert seen >= 1


# K-EDT-018：音色 HNR 做窗自相关校正（Boersma），低音男声不被系统性低估
def test_hnr_corrected_reads_clean_low_voice_high(tmp_path):
    import importlib.util as ilu
    import sys
    import wave

    import numpy as np
    sys.path.insert(0, str(ROOT / "data" / "review_pages" / "narrator_pick" / "_tools"))
    sys.path.insert(0, str(ROOT / "services" / "post"))
    spec = ilu.spec_from_file_location("ns_voice10_rsi", ROOT / "tools" / "voice10" / "voice10.py")
    V = ilu.module_from_spec(spec)
    spec.loader.exec_module(V)
    sr, f0 = 24000, 110.0                      # 规则原文：f0 110 Hz 的干净男声旧算法只读到 2.4 dB
    t = np.arange(int(1.5 * sr)) / sr
    rng = np.random.default_rng(0)
    clean = sum(np.sin(2 * np.pi * f0 * k * t) / k for k in range(1, 8)) * 0.3
    noisy = clean + rng.normal(0, 0.12, t.size)

    def _w(name, x):
        p = tmp_path / name
        with wave.open(str(p), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
            w.writeframes((np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes())
        return p
    h_clean, h_noisy = V.hnr_corrected(_w("clean.wav", clean)), V.hnr_corrected(_w("noisy.wav", noisy))
    assert h_clean > 10 and h_clean > h_noisy + 3, (h_clean, h_noisy)
