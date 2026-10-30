"""docs/research_adoption.md 里笔记本侧已落地的参数（不连 ComfyUI、不用 GPU、不调 ffmpeg）。

- H3 FL2VA 图：int8_convrot 底模、官方 v1.1 768p Turbo LoRA @1.0、MiniMaxH3SigmaShift 6/3（同时接采样与调度）、
  euler/simple 8 步、首尾帧同一种 center-crop、没有缓存类加速节点、帧数 17k+5 且 124–362。
- 配对规则：768p Turbo → 6/3，基模/544p → 12/3；w4a8 + LoRA 拒绝。
- 视频画布 768×1344（SOP P-B3）。
- 4K H.264 交付：CRF 17 + maxrate 60M / bufsize 120M / level 5.1（docs/upscale_4k.md）。
"""
import sys
from dataclasses import replace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "post"))

from ns_render import pipeline as P
from ns_render import workflows as W


def _by_class(wf: dict, cls: str) -> list[tuple[str, dict]]:
    return [(k, n) for k, n in wf.items() if n["class_type"] == cls]


def _graph(**kw):
    args = dict(prompt="p", first_frame="f.png", width=768, height=1344, frames=243, seed=1, prefix="x",
                last_frame="l.png")
    args.update(kw)
    return W.h3_fl2va(**args)


def test_h3_defaults_match_locked_sop_values():
    m = W.H3Model()
    assert m.unet == "minimax_h3_fl2va_pruned_int8_convrot.safetensors"
    assert m.loras == (("minimax_h3_fl2v_turbo_8step_v1.1_768p_comfyui_bf16.safetensors", 1.0),)
    assert (m.steps, m.sampler, m.scheduler, m.fps) == (8, "euler", "simple", 24)
    assert m.shift == (6.0, 3.0)
    assert m.audio_vae.endswith("fp32.safetensors")
    assert P.VIDEO_SIZE == (768, 1344)
    b = W.H3_BASE
    assert (b.loras, b.steps, b.shift, b.sampler) == ((), 20, (12.0, 3.0), "euler")


def test_shift_node_feeds_both_guider_and_scheduler():
    wf = _graph()
    [(sid, node)] = _by_class(wf, "MiniMaxH3SigmaShift")
    assert (node["inputs"]["shift_video"], node["inputs"]["shift_audio"]) == (6.0, 3.0)
    assert node["inputs"]["model"][0] in {k for k, _ in _by_class(wf, "LoraLoaderModelOnly")}
    assert wf["126"]["inputs"]["model"] == [sid, 0]      # BasicGuider
    assert wf["124"]["inputs"]["model"] == [sid, 0]      # BasicScheduler（sigma 从这里算）
    assert wf["124"]["inputs"]["steps"] == 8 and wf["124"]["inputs"]["scheduler"] == "simple"
    assert wf["123"]["inputs"]["sampler_name"] == "euler"


def test_base_preset_uses_12_3_without_lora():
    wf = _graph(m=W.H3_BASE)
    assert not _by_class(wf, "LoraLoaderModelOnly")
    [(_, node)] = _by_class(wf, "MiniMaxH3SigmaShift")
    assert (node["inputs"]["shift_video"], node["inputs"]["shift_audio"]) == (12.0, 3.0)
    assert node["inputs"]["model"] == ["127", 0]
    assert wf["124"]["inputs"]["steps"] == 20


def test_both_keyframes_get_the_same_centre_crop():
    wf = _graph()
    h3 = wf["131"]["inputs"]
    first, last = wf[h3["first_frame"][0]], wf[h3["last_frame"][0]]
    for node, load in ((first, "200"), (last, "201")):
        assert node["class_type"] == "ImageScale"
        assert node["inputs"] == {"image": [load, 0], "upscale_method": "lanczos", "width": 768, "height": 1344,
                                  "crop": "center"}
    off = _graph(m=replace(W.H3Model(), keyframe_crop=False))
    assert off["131"]["inputs"]["first_frame"] == ["200", 0] and off["131"]["inputs"]["last_frame"] == ["201", 0]


def test_no_lossy_accelerators_in_graph():
    classes = {n["class_type"] for n in _graph().values()}
    assert not classes & set(W.H3_BANNED_NODES)


@pytest.mark.parametrize("loras,shift", [
    ((("minimax_h3_fl2v_turbo_8step_v1.1_768p_comfyui_bf16.safetensors", 1.0),), (6.0, 3.0)),
    ((("minimax_h3_fl2v_turbo_8step_v1.0_768p_comfyui_bf16.safetensors", 1.0),), (6.0, 3.0)),
    ((("minimax_h3_fl2v_lightx2v_turbo_8step_v1.0_resized_avg_rank_24_bf16.safetensors", 1.0),), (12.0, 3.0)),
    ((), (12.0, 3.0)),
    ((("lnwan01_h3.safetensors", 0.8),), (12.0, 3.0)),
])
def test_lora_shift_pairing(loras, shift):
    assert W.expected_shift(loras) == shift


@pytest.mark.parametrize("bad,why", [
    (dict(shift=(12.0, 3.0)), "不配对"),                                   # 768p Turbo 配 12/3
    (dict(unet="minimax_h3_fl2va_pruned_w4a8_mixed.safetensors"), "w4a8"),
    (dict(steps=4), "步数"),
    (dict(sampler="euler_ancestral"), "ancestral"),
    (dict(loras=(("minimax_h3_fl2v_lightx2v_turbo_8step_v1.0_resized_avg_rank_24_bf16.safetensors", 1.0),)),
     "不配对"),                                                            # 544p Turbo 配 6/3（调研怀疑过的组合）
])
def test_invalid_h3_params_are_rejected_before_rendering(bad, why):
    with pytest.raises(ValueError, match=why):
        _graph(m=replace(W.H3Model(), **bad))


@pytest.mark.parametrize("frames", [242, 121, 379])
def test_frames_must_be_on_grid_and_in_range(frames):
    with pytest.raises(ValueError, match="帧数"):
        _graph(frames=frames)


def test_extra_identity_lora_keeps_turbo_shift():
    wf = _graph(loras=[("lnwan01_h3.safetensors", 0.8)])
    [(_, node)] = _by_class(wf, "MiniMaxH3SigmaShift")
    assert node["inputs"]["shift_video"] == 6.0


def test_4k_delivery_encode_settings(tmp_path):
    from ns_post import assemble as A
    calls = []

    class FF:
        def run(self, args):
            calls.append([str(a) for a in args])

    s = A.Settings()
    assert (s.crf_4k, s.maxrate_4k, s.bufsize_4k, s.level_4k) == (17, "60M", "120M", "5.1")
    src = {"kind": "black"}
    A.render_segment(FF(), src, 1.0, tmp_path / "a.mp4", s, uhd=True)
    A.render_segment(FF(), src, 1.0, tmp_path / "b.mp4", s, uhd=False)
    uhd, hd = calls
    assert uhd[uhd.index("-crf") + 1] == "17" and uhd[uhd.index("-maxrate") + 1] == "60M"
    assert uhd[uhd.index("-bufsize") + 1] == "120M" and uhd[uhd.index("-level:v") + 1] == "5.1"
    assert hd[hd.index("-crf") + 1] == str(s.crf) and "-maxrate" not in hd
