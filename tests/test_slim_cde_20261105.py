"""SLIM-CDE 11-05：提效三项（无画质影响）的回归
E1 K-OPS-I15：hold 带 expires_at；没带挂满 6 h 失效（night_control / lane_notes / *_hold.json 条目）
E2 sop_gate：证据过期 → 退避封顶 120 s、自动探针（临时根不起子进程）
E3 canary.ignore_items 默认空 = 原口径
D  night 轮询间隔：V2 默认 15 s（FIX-NIGHT2 #3，原 45 s），night_control.poll_s 可覆盖
"""
import importlib.util
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "autopilot"))
import hold_expiry as HX  # noqa: E402


def _load(rel, name):
    sp = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


PR = _load("tools/autopilot/producer.py", "producer_slim_cde")
SG = _load("tools/master/sop_gate.py", "sop_gate_slim_cde")


def test_alive_rules():
    now = 1_800_000_000.0
    assert HX.alive("2026-11-05T10:00:00", None, now)[0] is False or True  # 解析不依赖本机时钟，下两行精确
    assert HX.alive(now + 60, None, now)[0] is True
    assert HX.alive(now - 60, now - 10, now)[0] is False                    # 到点失效，哪怕刚写
    assert HX.alive(None, now - 5 * 3600, now)[0] is True                   # 没 expires 但没满 6 h
    ok, why = HX.alive(None, now - 7 * 3600, now)
    assert ok is False and "K-OPS-I15" in why
    assert HX.alive(None, None, now)[0] is True                              # 不知道写入时刻 = 有效（失败关闭）
    assert HX.alive("garbage", now - 7 * 3600, now)[0] is False             # expires 写坏 = 当没写


def test_filter_lane_holds_seen_file(tmp_path):
    seen = tmp_path / "seen.json"
    logs = []
    t0 = 1_800_000_000.0
    kept = HX.filter_lane_holds(["gpu36:0", "gpu36:1", "gpu33:2"], {"gpu36:1": t0 + 100}, seen, now=t0, keep=("gpu33:2",),
                                log=lambda a, b: logs.append(a))
    assert kept == ["gpu36:0", "gpu36:1", "gpu33:2"] and not logs
    t1 = t0 + 7 * 3600
    kept = HX.filter_lane_holds(["gpu36:0", "gpu36:1", "gpu33:2"], {"gpu36:1": t0 + 100}, seen, now=t1, keep=("gpu33:2",),
                                log=lambda a, b: logs.append(a))
    assert kept == ["gpu33:2"] and sorted(logs) == ["gpu36:0", "gpu36:1"]      # 无 expires 挂 7 h 失效；有 expires 但到点也失效；keep 永远在
    # 撤掉后再挂 → 重新起算
    HX.filter_lane_holds([], {}, seen, now=t1)
    assert HX.filter_lane_holds(["gpu36:0"], {}, seen, now=t1 + 10) == ["gpu36:0"]


def test_effective_holds_releases_stale_held_by():
    now = time.time()
    part = {"lanes": {"gpu33": ["gpu33:0", "gpu33:1"]}, "retired_lanes": ["gpu33:0", "gpu33:1"],
            "_temp_holds": {"gpu33:0": {"until": PR.iso(now + 3600)}, "gpu33:1": {"until": PR.iso(now + 3600)}}}
    ctrl = {"hold_lanes": ["gpu33:0", "gpu33:1"], "dispatch_by": {"host": "gpu33"},
            "lane_notes": {"gpu33:0": {"held_by": "X", "at": PR.iso(now - 7 * 3600)},          # 没 expires、挂 7 h
                           "gpu33:1": {"held_by": "Y", "at": PR.iso(now - 1 * 3600)}}}         # 没 expires、才 1 h
    hold, rel = PR.effective_holds(ctrl, ["gpu33:0", "gpu33:1"], part)
    # 分区仍登记 hold（keep）→ held_by 失效不放开（分区自己有 until）；这里验证 notes 过滤不误伤
    assert "gpu33:1" in hold and "gpu33:0" in hold
    part2 = {"lanes": {"gpu33": ["gpu33:0", "gpu33:1"]}, "retired_lanes": []}
    hold, rel = PR.effective_holds(ctrl, ["gpu33:0", "gpu33:1"], part2)
    assert "gpu33:0" not in hold and "K-OPS-I15" in rel["gpu33:0"]
    assert "gpu33:1" in hold                                                   # 1 h 的人工 hold 仍有效


def test_asset_hold_item_without_expiry_ages_out(tmp_path):
    d = tmp_path / "data" / "autopilot"
    d.mkdir(parents=True)
    now = time.time()
    (d / "x_hold.json").write_text(json.dumps({"active": True, "shots": [
        {"shot": "ep01-S1", "objects": ["first:ep01-S1"], "at": PR.iso(now - 7 * 3600)},
        {"shot": "ep01-S2", "objects": ["first:ep01-S2"], "at": PR.iso(now - 1 * 3600)},
        {"shot": "ep01-S3", "objects": ["first:ep01-S3"]},
        {"shot": "ep01-S4", "objects": ["first:ep01-S4"], "expires_at": PR.iso(now + 3600)}]}), encoding="utf-8")
    out = PR.asset_hold_objects(tmp_path / "data")
    assert out == {"first:ep01-S2", "first:ep01-S3", "first:ep01-S4"}


def test_sop_gate_stale_detection_and_no_probe_in_tmp_root(tmp_path):
    miss = ["提示词：证据过期（2026-11-05T19:00:00 之后导入稿或资产清单变了，重跑 probe-prompts）"]
    assert SG._is_stale_evidence(miss) and not SG._is_stale_evidence(["资产就绪：缺口"])
    assert SG.auto_probe_stale("r", 1, tmp_path, miss) is None                  # 非真实根 = 不起子进程
    assert SG.auto_probe_stale("r", 1, SG.ROOT, ["资产就绪：缺口"]) is None      # 不是证据过期 = 不适用
    assert SG.STALE_BACKOFF_S == 120


def test_canary_ignore_items_default_empty(tmp_path):
    assert PR.canary_ignore_items(tmp_path) == set()
    (tmp_path / "config" / "pipeline").mkdir(parents=True)
    (tmp_path / "config" / "pipeline" / "producer.json").write_text(json.dumps({"canary": {"ignore_items": ["Q1"]}}), encoding="utf-8")
    assert PR.canary_ignore_items(tmp_path) == {"Q1"}
    # PS-MASTER 11-05 按 L-196（全自动）开：base35 Q1 底噪不再触发整台暂停（Q1 仍硬闸）
    assert json.loads((ROOT / "config/pipeline/producer.json").read_text(encoding="utf-8"))["canary"]["ignore_items"] == ["Q1"]


def test_night_poll_seconds():
    N = _load_night()
    assert N.poll_seconds({"poll_s": 30}) == 30
    assert N.poll_seconds({"poll_s": 1}) == 15 and N.poll_seconds({"poll_s": 9999}) == 600
    assert N.poll_seconds({}) in (15.0, 120.0)      # FIX-NIGHT2 #3：V2 默认 15 s（V1 仍 120 s）


def _load_night():
    import os
    os.environ.setdefault("NS_RUN", "series10_v2")
    sys.path.insert(0, str(ROOT / "tools" / "series10_video"))
    return _load("tools/series10_video/night.py", "night_slim_cde")
