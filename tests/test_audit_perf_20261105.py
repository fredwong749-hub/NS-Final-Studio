"""AUDIT-PERF 11-05：热路径无效代码修复的回归
① producer.iso() 与 ts_epoch 同口径（无时区串 = +09:00），本机时钟是什么都成立（test_producer_b2 / w44 在美东时钟下红的根因）
② netfix.dispatch.held_lanes 的 until 无时区串也按 +09:00 读
③ 出图超时随预取深度放大（base35 每道 2 单 → 854 s 已贴近 900 s）
④ 驳回阶梯：skip_heavy_on 命中 → 不排重档
⑤ 共用验收 QB 跳过：只在 ok=False 且开关开时，QB 记 na、不翻结论
"""
import importlib.util
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(rel, name):
    sp = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


PR = _load("tools/autopilot/producer.py", "producer_audit_perf")
D = _load("tools/netfix/dispatch.py", "dispatch_audit_perf")


def test_iso_roundtrips_through_ts_epoch_regardless_of_local_clock():
    for t in (time.time(), 1793823334.0, 1700000000.0):
        s = PR.iso(t)
        assert PR.ts_epoch(s) == int(t) or abs(PR.ts_epoch(s) - t) < 1.0, (s, t)
    # 显式 +09:00：和无时区串指向同一刻
    s = PR.iso(1793823334.0)
    assert PR.ts_epoch(s + "+09:00") == PR.ts_epoch(s)


def test_held_lanes_until_naive_string_is_project_tz():
    now_t = time.time()
    part = {"retired_lanes": ["gpu36:2"],
            "_lent_lanes": {"gpu33:0": {"until": PR.iso(now_t + 3600)}, "gpu33:1": {"until": PR.iso(now_t - 3600)}}}
    held = D.held_lanes(part, now_t)
    assert "gpu33:0" in held and "gpu33:1" not in held and "gpu36:2" in held
    # 带时区串照旧
    part["_lent_lanes"]["gpu33:3"] = {"until": PR.iso(now_t + 60) + "+09:00"}
    assert "gpu33:3" in D.held_lanes(part, now_t)


def test_render_timeout_scales_with_prefetch_depth(monkeypatch):
    monkeypatch.delenv("NS_PRODUCER_RENDER_TIMEOUT_S", raising=False)
    monkeypatch.setattr(PR, "prefetch_depth", lambda: 2)
    assert PR.render_timeout_s() == 1800.0
    monkeypatch.setattr(PR, "prefetch_depth", lambda: 1)
    assert PR.render_timeout_s() == 900.0
    monkeypatch.setenv("NS_PRODUCER_RENDER_TIMEOUT_S", "1234")
    assert PR.render_timeout_s() == 1234.0
    monkeypatch.setenv("NS_PRODUCER_RENDER_TIMEOUT_S", "5")
    assert PR.render_timeout_s() == 60.0


def test_heavy_cannot_fix_only_when_switch_lists_last_blocking():
    led = {"redo_history": [{"ok": False, "blocking": ["Q9", "QB"]}, {"ok": False, "blocking": ["Q1", "Q9", "QB"]}]}
    assert PR.heavy_cannot_fix(led, {"skip_heavy_on": []}) is None            # 开关没开 = 原口径
    assert PR.heavy_cannot_fix(led, {}) is None
    assert PR.heavy_cannot_fix(led, {"skip_heavy_on": ["Q1"]}) == ["Q1"]
    led2 = {"redo_history": [{"ok": False, "blocking": ["Q1"]}, {"ok": False, "blocking": ["Q9", "QB"]}]}
    assert PR.heavy_cannot_fix(led2, {"skip_heavy_on": ["Q1"]}) is None       # 只看最后一次
    assert PR.heavy_cannot_fix({}, {"skip_heavy_on": ["Q1"]}) is None
    assert PR.redo_ladder_policy().get("skip_heavy_on") is not None            # 策略键存在（retry.yaml 单一来源）


def test_mark_qb_skipped_keeps_verdict_and_records_na():
    pf = {"ok": False, "blocking": ["Q1", "Q9"], "items": [{"id": "Q1", "status": "fail"}, {"id": "QB", "status": "fail"}]}
    out = PR.mark_qb_skipped(pf)
    assert out is pf and pf["ok"] is False and pf["blocking"] == ["Q1", "Q9"]
    qb = [i for i in pf["items"] if i["id"] == "QB"]
    assert len(qb) == 1 and qb[0]["status"] == "na" and qb[0]["blocking"] is False and "Q1" in qb[0]["detail"]
    assert pf["accept"]["status"] == "skipped"


def test_accept_skip_prefailed_switch_live_on(tmp_path):
    # PS-MASTER 11-05 按项目方“加速、任何无效的代码修复”开：已判不过的图不再做 QB 整张重看
    assert PR.accept_skip_prefailed(ROOT) is True
    cfg = json.loads((ROOT / "config/pipeline/producer.json").read_text(encoding="utf-8"))
    assert cfg["accept"].get("skip_prefailed") is True
