"""REVIEW-C 11-05：asset_worker 坏卡道单一来源（L-194：gpu36:2 已归 NS，只剩 gpu33:2 坏卡）。
坏卡读 config/factory/hosts.json hosts.<主机>.broken_gpus，代码 / 默认配置里不再写死 gpu36:2。"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _aw():
    spec = importlib.util.spec_from_file_location("asset_worker_review_c", ROOT / "tools/pipeline/asset_worker.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


HOSTS = {"schema": "nsfs.factory.hosts/1", "hosts": {
    "gpu33": {"broken_gpus": [2], "lanes": {f"gpu33:{i}": {"gpu": i, "roles": ["image", "video"], "enabled": True} for i in range(4)}},
    "gpu36": {"lanes": {f"gpu36:{i}": {"gpu": i, "roles": ["image", "video"], "enabled": True} for i in range(3)}},
    "laptop": {"lanes": {}},
}}


class FakeHosts:
    """假车道表模块：和 tools/factory/hosts.py 同接口（lanes / load）"""

    def __init__(self, d):
        self.d = d

    def load(self):
        return self.d

    def lanes(self, host=None, role=None, enabled=True, d=None):
        return {ln: rec for h in self.d["hosts"].values() for ln, rec in (h.get("lanes") or {}).items()
                if (role is None or role in rec.get("roles", [])) and rec.get("enabled")}


def test_broken_lanes_from_hosts_json_single_source():
    AW = _aw()
    assert AW.broken_lanes(d=HOSTS) == {"gpu33:2"}
    assert AW.broken_lanes(FakeHosts(HOSTS)) == {"gpu33:2"}
    d2 = json.loads(json.dumps(HOSTS))
    d2["hosts"]["gpu36"]["broken_gpus"] = [1]
    assert AW.broken_lanes(d=d2) == {"gpu33:2", "gpu36:1"}
    assert AW.broken_lanes(d={"hosts": {}}) == set()


def test_defaults_no_longer_hardcode_gpu36_2():
    AW = _aw()
    assert "gpu36:2" not in AW.DEFAULTS["exclude_lanes"]
    assert "gpu36:2" not in (AW.__doc__ or "")


def test_free_lanes_excludes_broken_only_and_keeps_gpu36_2():
    AW = _aw()
    probed = []

    def probe(lane):
        probed.append(lane)
        return {"ok": True, "busy": False}

    free = AW.free_lanes({"exclude_lanes": []}, set(), part={}, probe=probe, hosts_mod=FakeHosts(HOSTS))
    assert "gpu33:2" not in free and "gpu33:2" not in probed          # 坏卡连探都不探
    assert "gpu36:2" in free                                          # L-194：gpu36:2 归 NS 出图
    assert set(free) == {"gpu33:0", "gpu33:1", "gpu33:3", "gpu36:0", "gpu36:1", "gpu36:2"}
    # config exclude_lanes 仍叠加生效
    free2 = AW.free_lanes({"exclude_lanes": ["gpu36:1"]}, set(), part={}, probe=probe, hosts_mod=FakeHosts(HOSTS))
    assert "gpu36:1" not in free2 and "gpu33:2" not in free2


def test_real_hosts_json_marks_only_gpu33_2_broken():
    AW = _aw()
    assert AW.broken_lanes() == {"gpu33:2"}, "L-194：真实车道表只应有 gpu33:2 坏卡"
    cfg = json.loads((ROOT / "config/pipeline/asset_worker.json").read_text(encoding="utf-8"))
    assert "gpu36:2" not in cfg.get("exclude_lanes", []) and cfg.get("max_parallel") == 6        # L-197
