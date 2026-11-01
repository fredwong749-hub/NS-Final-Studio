"""LOCALGPU（11-01，总调度 fredw-2b 派）：笔记本本机出图道 laptop:0（knowledge K-OPS-L01）。

① 本机道参数必须和 leica_sstar 完全一致：道记录不许带出图参数，生产预设 frame_v9 与 leica_sstar 出图参数逐项相同；
② image_only：任何视频选道（pick_lane / resolve_lane / long_lanes / max_frames）都不派到这条道；
③ hold=true：道就绪但不自动派（jobs.lanes ok=False、producer 按 hold_lanes），等总调度开派；
④ producer 出图道表并入 render_endpoints 的 image_only 道。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from ns_api import jobs as J
from ns_render import endpoints as EP

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "localgpu"))
import check_lane as CL  # noqa: E402

LAPTOP = {"url": "http://127.0.0.1:18388", "image_only": True, "concurrency": 1, "hold": True, "preset_lock": "leica_sstar"}
CFG = {"image": {"url": "http://127.0.0.1:18188", "gpu": 0}, "video": {"url": "http://127.0.0.1:18191", "gpu": 3},
       "gpus": {"0": "http://127.0.0.1:18188", "3": "http://127.0.0.1:18191"},
       "lanes": {"gpu36:0": "http://127.0.0.1:18288", "laptop:0": LAPTOP}}


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    p = tmp_path / "render_endpoints.json"
    p.write_text(json.dumps(CFG), encoding="utf-8")
    monkeypatch.setattr(EP, "CONFIG", p)
    for k in ("NS_COMFY_URL", "NS_COMFY_URL_GPU0", "NS_COMFY_URL_GPU3", "NS_COMFY_URL_LAPTOP_0"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(J, "_jobs", {})
    monkeypatch.setattr(J, "reachable_fn", lambda url: {"reachable": True, "running": 0, "pending": 0})
    monkeypatch.setattr(J, "train_lock_fn", lambda server: set())
    monkeypatch.setattr(J, "_train_cache", {})
    yield p
    J._jobs.clear()


def _set(p: Path, **laptop):
    c = json.loads(p.read_text(encoding="utf-8"))
    c["lanes"]["laptop:0"] = {**c["lanes"]["laptop:0"], **laptop}
    p.write_text(json.dumps(c), encoding="utf-8")


# ---------------------------------------------------------------- ① 参数与 leica_sstar 一致（真实配置）
def test_real_config_lane_params_equal_leica_sstar():
    assert CL.check_config() == []
    real = json.loads((ROOT / "config/render_endpoints.json").read_text(encoding="utf-8"))
    lane = real["lanes"]["laptop:0"]
    assert lane["image_only"] is True and lane["concurrency"] == 1 and lane["preset_lock"] == "leica_sstar"
    assert lane["url"] == "http://127.0.0.1:18388"


def test_lane_record_with_param_override_is_rejected(tmp_path):
    c = json.loads((ROOT / "config/render_endpoints.json").read_text(encoding="utf-8"))
    c["lanes"]["laptop:0"] = {**c["lanes"]["laptop:0"], "loras": [{"name": "krea2_film_texture_qwen21.safetensors", "strength": 0.8}]}
    p = tmp_path / "re.json"
    p.write_text(json.dumps(c), encoding="utf-8")
    errs = CL.check_config(cfg_path=p)
    assert errs and "出图参数" in errs[0]


def test_production_preset_drift_from_leica_sstar_is_caught(tmp_path):
    rq = json.loads((ROOT / "config/render_quality.json").read_text(encoding="utf-8"))
    prod = rq.get("frame_redo_preset") or "frame_v9"
    for x in rq["image_presets"]:
        if x["id"] == prod:
            x["params"] = {**x["params"], "render_scale": 1.0}
    p = tmp_path / "rq.json"
    p.write_text(json.dumps(rq, ensure_ascii=False), encoding="utf-8")
    errs = CL.check_config(rq_path=p)
    assert any("render_scale" in e for e in errs)


def test_required_files_match_owner_confirmed_sstar():
    f = CL.required_files("leica_sstar")
    assert f == {"unet": "qwen_image_2.1_turbo_int8_convrot.safetensors", "clip": "qwen3vl_8b_int8_convrot.safetensors",
                 "vae": "texture_fix_vae_for_qwen_image_2.1_bf16.safetensors", "loras": ["krea2_film_texture_qwen21.safetensors"]}
    assert set(CL.EXPECTED_SHA256) >= {"diffusion_models/" + f["unet"], "text_encoders/" + f["clip"], "vae/" + f["vae"],
                                       "loras/" + f["loras"][0]}


def test_build_graph_has_no_lane_input():
    """同一作业在任何道上出的图完全相同：build_graph 不收道 / 地址参数（参数只来自预设）"""
    import inspect
    from ns_render import unified_frame as UF
    params = set(inspect.signature(UF.build_graph).parameters)
    assert params == {"job", "seed", "upload", "prefix", "size", "overrides"}


# ---------------------------------------------------------------- ② image_only
def test_image_only_lane_never_gets_video(cfg):
    _set(cfg, hold=False)
    assert EP.image_only("laptop:0") and not EP.image_only("gpu36:0") and not EP.image_only(0)
    assert EP.max_frames("laptop:0") == 0
    assert "laptop:0" not in EP.long_lanes(121)
    lanes = J.lanes()
    lp = next(ln for ln in lanes if ln["gpu"] == "laptop:0")
    assert lp["image_only"] is True and lp["ok"] is True
    only_laptop = [lp]
    assert J.pick_lane("video", 121, only_laptop) == EP.default_gpu("video")     # 没有可接视频的道 → 默认视频道，不派笔记本
    with pytest.raises(ValueError):
        J.resolve_lane("laptop:0", "video", 121)
    assert J.resolve_lane("laptop:0", "image") == "laptop:0"


def test_image_only_lane_can_take_images_when_open(cfg):
    _set(cfg, hold=False)
    lanes = [ln for ln in J.lanes() if ln["gpu"] == "laptop:0"]
    assert J.pick_lane("image", None, lanes) == "laptop:0"


# ---------------------------------------------------------------- ③ hold
def test_held_lane_is_not_auto_dispatched(cfg):
    assert EP.held("laptop:0") and not EP.held("gpu36:0")
    lp = next(ln for ln in J.lanes() if ln["gpu"] == "laptop:0")
    assert lp["ok"] is False and lp["hold"] is True and "待开派" in lp["status_text"]
    assert J.pick_lane("image", None, [lp]) == EP.default_gpu("image")
    assert J.resolve_lane("laptop:0", "image") == "laptop:0"          # 手动指定仍可用（单张验证 / 总调度点名）


# ---------------------------------------------------------------- ④ producer
def test_yield_peer_raises_when_peer_does_not_yield(cfg, monkeypatch):
    """轮流用卡：看图服务在但超时没让出 → 不提交（11-01 18:52 超时照交，两边挤进共享显存慢到不动）"""
    from ns_render import comfy_client as CC
    _set(cfg, yield_url="http://127.0.0.1:1/yield", yield_timeout_s=1)

    def slow(*a, **k):
        raise TimeoutError("timed out")
    monkeypatch.setattr(CC.urllib.request, "urlopen", slow)
    with pytest.raises(CC.ComfyUnavailable):
        CC.ComfyClient("http://127.0.0.1:18388")._yield_peer()


def test_yield_peer_passes_when_peer_not_running(cfg, monkeypatch):
    import urllib.error
    from ns_render import comfy_client as CC
    _set(cfg, yield_url="http://127.0.0.1:1/yield")

    def refused(*a, **k):
        raise urllib.error.URLError(ConnectionRefusedError(10061, "refused"))
    monkeypatch.setattr(CC.urllib.request, "urlopen", refused)
    CC.ComfyClient("http://127.0.0.1:18388")._yield_peer()          # 看图服务没起 = 没占卡 → 照常提交
    CC.ComfyClient("http://127.0.0.1:18188")._yield_peer()          # 没配 yield_url 的道不受影响


def test_real_lane_has_yield_url():
    real = json.loads((ROOT / "config/render_endpoints.json").read_text(encoding="utf-8"))
    assert real["lanes"]["laptop:0"]["yield_url"].endswith("/yield")


def test_producer_lane_table_includes_image_only_lanes(cfg, monkeypatch):
    sys.path.insert(0, str(ROOT / "tools" / "autopilot"))
    import producer as PR
    assert PR.render_image_only_lanes() == {"laptop:0": "http://127.0.0.1:18388"}
    assert PR.lane_held("laptop:0") is True
    lanes = {**PR.IMAGE_LANES, **PR.render_image_only_lanes()}
    assert "laptop:0" in lanes and "gpu36:2" not in lanes


def test_producer_probe_treats_render_hold_as_hold(cfg, tmp_path):
    sys.path.insert(0, str(ROOT / "tools" / "autopilot"))
    import producer as PR
    paths = PR.Paths(root=tmp_path, pd=tmp_path / "producer")
    pr = PR.Producer(paths, script=object(), frames=None, video=object(),
                     lanes={"gpu33:0": "fake://a", "laptop:0": "http://127.0.0.1:18388"},
                     lane_probe=lambda url: {"ok": True, "n": 0, "agents": []},
                     train_locks_fn=lambda srv: set(), lock_now_fn=lambda lane: False)
    st = pr.probe_lanes({"hold_lanes": []})
    assert st["gpu33:0"]["free"] is True
    assert st["laptop:0"]["free"] is False and "等总调度开派" in st["laptop:0"]["why"]
    _set(cfg, hold=False)
    assert pr.probe_lanes({"hold_lanes": []})["laptop:0"]["free"] is True
