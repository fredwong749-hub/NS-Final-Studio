"""线3 / G4 #9（11-08）：笔记本冒烟 Q10 人数检测打 count_host http://10.0.0.36:8893 → 笔记本不在机房内网（lan_proxy 只放行 10.0.0.33）
→ WinError 10060 → count untested → score_infra，首尾帧永远过不了 SOP 闸、视频 0 提交（A13 snap 证据）。
修：笔记本（无 OFFLINE_SELF）且本机隧道 127.0.0.1:18893（→ gpu36 127.0.0.1:8893，同一常驻检测服务）/health 通 → 用隧道；
隧道不在 → 原口径不变。服务器（有 OFFLINE_SELF）路由一字不变。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "services/agent"), str(ROOT / "packages/schema")]
from ns_agent.gen_contract import accept as GA  # noqa: E402


def test_laptop_uses_tunnel_when_up(tmp_path, monkeypatch):
    monkeypatch.delenv("OFFLINE_SELF", raising=False)
    seen = []
    assert GA.review_local_anomaly(tmp_path, probe=lambda u: seen.append(u) or True) == "http://127.0.0.1:18893"
    assert seen == ["http://127.0.0.1:18893"]
    assert GA.review_local_anomaly(tmp_path, probe=lambda u: False) is None          # 隧道不在 → 退回 count_host 原口径


def test_server_route_unchanged(tmp_path, monkeypatch):
    monkeypatch.setenv("OFFLINE_SELF", "gpu36")                                        # 无 lane_roles 配置 → 原样 None
    assert GA.review_local_anomaly(tmp_path, probe=lambda u: True) is None
