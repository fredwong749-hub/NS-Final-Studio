"""L-197 A：砍尾帧（视频只用首帧 I2VA）——按剧 / 集开关 ns_agent.video_mode；build_jobs 编 I2VA 提示词（无 Picture 2）；
sop_gate 尾帧阶段不挡视频；producer 尾帧对象 = 不适用。全部 mock，不碰 GPU / 真实数据写入。"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in ("tools/series10_video", "services/agent", "services/recipes", "services/render_router", "packages/schema", "tools/pipeline", ""):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))

from ns_agent import video_mode as VM  # noqa: E402


def _cfg(monkeypatch, vm):
    cfg = {"runs": {"series10_v2": ({"video_mode": vm} if vm else {})}}
    monkeypatch.setattr(VM, "_cfg", lambda root=None: cfg)
    monkeypatch.delenv("NS_VIDEO_MODE", raising=False)


def test_switch_scope(monkeypatch):
    _cfg(monkeypatch, {"mode": "i2va", "from_episode": 2})
    assert VM.no_last("series10_v2", 2) and VM.no_last("series10_v2", 5)
    assert not VM.no_last("series10_v2", 1)               # ep01 已按 FL2VA 编好的作业不动
    assert not VM.no_last("series10_v1", 2)               # 其它剧不变
    assert not VM.no_last(None, 2)
    monkeypatch.setenv("NS_VIDEO_MODE", "fl2va")
    assert not VM.no_last("series10_v2", 2)               # 一键强关
    _cfg(monkeypatch, None)
    assert not VM.no_last("series10_v2", 2)               # 不配 = 旧行为
    _cfg(monkeypatch, {"mode": "fl2va", "from_episode": 1})
    assert not VM.no_last("series10_v2", 2)


def test_real_config_fl2va_after_l203():
    """L-203（项目方 11-06）：撤回 L-197 A——线上配置 series10_v2 video_mode.mode = fl2va，任何集 / 任何镜都要尾帧；代码路径仍在（上面的 mock 测试）"""
    assert not VM.no_last("series10_v2", 2) and not VM.no_last("series10_v2", 1) and not VM.no_last("series10_v1", 3)
    assert not VM.no_last("series10_v2", 1, shot="ep01-S1") and not VM.no_last("series10_v2", 1, shot="ep01-S2")
    assert VM.last_frame_mode("series10_v2") == "compose"


def _specs():
    import build_jobs as B
    B.set_run("series10_v2")
    return B, B.load_specs()


def test_compile_ep01_shot_i2va_prompt(monkeypatch):
    """ep01 一镜按 I2VA 编：配方不送尾帧、提示词没有 Picture 2 / FL2VA 对齐句；关开关则仍是旧路径（带尾帧的镜）"""
    B, specs = _specs()
    from ns_recipes import registry as R
    reg = R.load()
    rid = B.recipe_choice()["face_default"]
    from ns_schema.shot_spec import IdentityRef
    spec = next(iter(specs.values())).model_copy(deep=True)
    spec.keyframes = {"last": IdentityRef(path="last.png")}     # 当前 ep01 spec 没有 last 关键帧：补一个，让 FL2VA 路径真的送尾帧
    ff = {spec.id: {"file": "x.png", "created_at": "2026-11-05 00:00:00"}}
    lf = {spec.id: {"file": "y.png", "created_at": "2026-11-05 01:00:00"}}
    B.LASTS_OF.clear()
    B.LASTS_OF.update(lf)
    monkeypatch.setattr(B, "RUN_ID", "series10_v2")
    # 开：ep01 也走 I2VA（测试把 from_episode 设 1）
    _cfg(monkeypatch, {"mode": "i2va", "from_episode": 1})
    on = B.compile_variant(spec, reg, rid, 1, "v1", ff)
    assert on.get("status") == "ready", on.get("status")
    assert "Picture 2" not in on["prompt"]
    assert not on["prompt"].startswith("How the reference pictures align") or "Picture 2" not in on["prompt"]
    assert "@last_frame" not in json.dumps(on.get("inputs") or {})
    # 关：旧路径（只有 spec 有 last 关键帧时才送尾帧）
    _cfg(monkeypatch, None)
    off = B.compile_variant(spec, reg, rid, 1, "v1", ff)
    assert off.get("status") == "ready", off.get("status")
    assert "Picture 2" in off["prompt"]                      # FL2VA 对齐句仍在（旧路径完好）
    assert "y.png" in json.dumps(off.get("inputs") or {})


def test_sop_gate_last_stage_not_blocking(monkeypatch, tmp_path):
    from tools.master import sop_gate as G
    _cfg(monkeypatch, {"mode": "i2va", "from_episode": 2})
    r = G.check_lasts(ROOT, "series10_v2", 2)
    assert r["ok"] and "I2VA" in r["why"]
    monkeypatch.setattr(G, "shot_frames", lambda *a, **k: {})
    r1 = G.check_lasts(ROOT, "series10_v2", 1)           # ep01 仍走旧口径（没有帧 = 不过）
    assert "I2VA" not in r1["why"]


def test_producer_last_object_na(monkeypatch):
    from tools.autopilot import producer as PR
    _cfg(monkeypatch, {"mode": "i2va", "from_episode": 2})
    assert PR._VM.no_last("series10_v2", 2)
    o = PR.obj("last", "ep02-S1", ep=2, shot="ep02-S1")
    lo = {**o, "status": "passed", "na": True, "i2va_no_last": True}
    td = {}
    # 尾帧 na 不被 last_consistent 作废；视频对象把它当通过
    assert PR.last_consistent(td, {"status": "ready"}, lo) is lo
