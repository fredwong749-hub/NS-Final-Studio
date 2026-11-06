"""L-209 S2.3（W-S234）：分区只留一份 data/state/netfix/partition.json + 临时 hold 一律带到期（过期的所有读者都不认）。"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "netfix"))
import partition as PT  # noqa: E402


def _w(p: Path, obj) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return p


NOW = 1_800_000_000.0


def test_jst_roundtrip_independent_of_local_clock():
    assert PT.ts_epoch(PT.jst(NOW)) == NOW
    assert PT.ts_epoch("2026-11-07T05:00:00+09:00") == PT.ts_epoch("2026-11-07T05:00:00")


def test_alive_rules():
    assert PT.alive({"expires_at": PT.jst(NOW + 60)}, NOW)[0]
    assert not PT.alive({"expires_at": PT.jst(NOW - 60)}, NOW)[0]
    assert PT.alive({"until": PT.jst(NOW + 60)}, NOW)[0]
    # 没带到期：写入时刻起 2 h
    assert PT.alive({"at": PT.jst(NOW - 3600)}, NOW)[0]
    assert not PT.alive({"at": PT.jst(NOW - 3 * 3600)}, NOW)[0]
    # 什么都没带 = 不认
    ok, why = PT.alive({"by": "X"}, NOW)
    assert not ok and "必须带到期" in why


def test_live_drops_expired_and_their_retired_entry():
    part = {"retired_lanes": ["gpu33:1", "gpu36:2", "gpu33:0"],
            "_temp_holds": {"gpu33:1": {"by": "A", "expires_at": PT.jst(NOW - 1)}, "gpu33:0": {"by": "B", "expires_at": PT.jst(NOW + 600)}},
            "_lent_lanes": {}}
    out = PT.live(part, NOW)
    assert set(out["_temp_holds"]) == {"gpu33:0"}
    assert out["retired_lanes"] == ["gpu36:2", "gpu33:0"]
    assert "gpu33:1" in out["_dropped_holds"]
    assert part["_temp_holds"]["gpu33:1"]                       # 不改入参
    assert PT.held(out, NOW) == {"gpu36:2", "gpu33:0"}
    assert PT.held(part, NOW) == {"gpu36:2", "gpu33:0"}         # 原样分区算 held 同口径


def test_long_holds():
    part = {"_temp_holds": {"gpu36:1": {"by": "X", "expires_at": PT.jst(NOW + 5 * 3600)}, "gpu36:0": {"expires_at": PT.jst(NOW + 60)}}}
    assert set(PT.long_holds(part, NOW)) == {"gpu36:1"}


def test_load_reads_only_data_state(tmp_path):
    _w(tmp_path / "data/state/netfix/partition.json", {"images": {"gpu33": [1]}, "_temp_holds": {}})
    _w(tmp_path / "config/netfix/partition.json", {"images": {"gpu33": [9]}, "_doc": "弃用"})
    assert PT.load(tmp_path)["images"] == {"gpu33": [1]}
    assert PT.md5(tmp_path)


def test_dispatch_and_producer_and_asset_worker_agree_on_expiry():
    """dispatch.held_lanes / producer.partition_held / asset_worker._hold_expired 都走同一个到期口径"""
    sys.path.insert(0, str(ROOT / "tools" / "autopilot"))
    sys.path.insert(0, str(ROOT / "tools" / "pipeline"))
    import dispatch as D  # noqa: PLC0415
    part = {"retired_lanes": ["gpu33:1"], "_temp_holds": {"gpu33:1": {"by": "A", "at": PT.jst(NOW - 3 * 3600)},
                                                          "gpu36:0": {"by": "B", "expires_at": PT.jst(NOW + 60)}}}
    assert D.held_lanes(part, NOW) == {"gpu36:0"}
    import asset_worker as AW  # noqa: PLC0415
    assert AW._hold_expired({"expires_at": PT.jst(NOW - 60)}, NOW)
    assert not AW._hold_expired({"expires_at": PT.jst(NOW + 60)}, NOW)
    assert AW._hold_expired({"by": "x"}, NOW)                   # 没带到期 = 不认


def test_lanes_hold_writes_jst_expiry(tmp_path):
    sys.path.insert(0, str(ROOT / "tools" / "debug"))
    import lanes as LN  # noqa: PLC0415
    p = _w(tmp_path / "partition.json", {"retired_lanes": [], "_temp_holds": {}, "_lent_lanes": {}})
    t = time.time()
    LN.hold("gpu36:1", 15, "test", part=p, now=t, by="T")
    rec = json.loads(p.read_text(encoding="utf-8"))["_temp_holds"]["gpu36:1"]
    assert abs(PT.ts_epoch(rec["expires_at"]) - (t + 900)) < 2
    assert abs(PT.ts_epoch(rec["at"]) - t) < 2
    assert LN.sweep(part=p, now=t + 901) == ["gpu36:1"]


def test_no_reader_uses_legacy_copy():
    """S2.3：业务代码不再直接读 config/netfix/partition.json（state_paths 兼容读、freeze 豁免、注释 / 文档除外）"""
    bad = []
    for f in ["tools/autopilot/producer.py", "tools/autopilot/resident_sync.py", "tools/autopilot/episode_pipeline.py",
              "tools/autopilot/idle_watch.py", "tools/brain/telemetry.py", "tools/master/health_tick.py", "ops/offline/merge_pull.py"]:
        for i, ln in enumerate((ROOT / f).read_text(encoding="utf-8").splitlines(), 1):
            code = ln.split("#", 1)[0]
            if ('"config/netfix/partition.json"' in code or '"config" / "netfix" / "partition.json"' in code
                    or "config/netfix/partition.json\"" in code):
                bad.append(f"{f}:{i}")
    assert not bad, bad
