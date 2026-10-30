import os

# 测试里不在后台重建 data/state_timeline.json（需要时由测试自己打开）
os.environ.setdefault("NS_TIMELINE_AUTOBUILD", "0")


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _no_live_gpu3_bridge(monkeypatch):
    """测试一律不碰真实的 gpu3 桥（隧道 127.0.0.1:15180 可能开着）：默认按“不可达”处理，需要的测试自己换假桥"""
    try:
        from ns_api import gpu3_bridge as GB
    except Exception:  # noqa: BLE001
        return

    def _down(*a, **k):
        raise GB.BridgeError("gpu3 桥在测试里不可达（tests/conftest.py）")
    monkeypatch.setattr(GB, "_call", _down)


@pytest.fixture(autouse=True)
def _no_remote_index_writes(monkeypatch):
    """fredw-92/F1：测试里 ComfyClient.download 记 gpu3 输出名只记在内存，不写 data/cache/comfy_remote_outputs.json"""
    try:
        from ns_render import comfy_client as CC
    except Exception:  # noqa: BLE001
        return
    monkeypatch.setattr(CC, "remote_index", CC.RemoteIndex(None))


@pytest.fixture(autouse=True)
def _auto_final_off_by_default(monkeypatch):
    """fredw-92/VB：config/render_quality.json 的 auto_final_on_lock 由项目方 2026-10-31 改成 true（生产设置），
    测试按契约默认值 false 跑；显式传 path 的调用仍读那个文件（测这个开关本身时用）。"""
    from ns_render import final_tier as FT
    orig = FT.auto_final_on_lock
    monkeypatch.setattr(FT, "auto_final_on_lock", lambda path=None: orig(path) if path is not None else False)
