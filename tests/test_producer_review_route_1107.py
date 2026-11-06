"""11-07 PS-MASTER：producer 启动时套用 L-206 审图位路由（首尾帧看图也只去 gpu33:3）"""
import inspect
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "series10_video"))
sys.path.insert(0, str(ROOT / "tools" / "autopilot"))


def test_serve_applies_review_env():
    import producer as PR
    src = inspect.getsource(PR.serve)
    assert "apply_review_env()" in src and "review_route" in src


def test_review_env_on_gpu36_routes_to_review_lane():
    import lane_roles as LR
    cfg = {"enabled": True, "review": {"lane": "gpu33:3", "port_base": 8870, "lan_url": "http://10.0.0.33:8870"}}
    env = {"OFFLINE_SELF": "gpu36"}
    got = LR.apply_review_env(env, cfg)
    assert env["VQA_REVIEW_ONLY"] == "1" and env["VQA_LAN_URL"] == "http://10.0.0.33:8870" and got
    env2 = {"OFFLINE_SELF": "gpu33"}
    LR.apply_review_env(env2, cfg)
    assert env2["VQA_URL"] == "http://127.0.0.1:8870" and "VQA_REVIEW_ONLY" not in env2
    assert LR.apply_review_env({}, cfg) == {}          # 笔记本 / 测试：不改
