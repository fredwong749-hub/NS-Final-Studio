"""W11（A-G1 第 22 轮 P1）：sop_gate.promote（runs.json preparing → producing 状态机）、整集预览目录按 run、master_check ④ 看 sop_gate.enabled。
临时根目录夹具，不碰真实数据；judge 用替身（闸门各阶段证据另有 test_sop_gate / test_episode_retro_master_check 覆盖）。"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


SG = _load("sop_gate_promote_t", "tools/master/sop_gate.py")
MC = _load("master_check_promote_t", "tools/master/master_check.py")
RUN = "drama_p"


def _w(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def _root(tmp_path, auto: bool) -> Path:
    r = tmp_path
    _w(r / "config/pipeline/runs.json", {"primary": RUN, "legacy_unprefixed_run": "old_run",
                                         "runs": {RUN: {"status": "preparing"}, "old_run": {"status": "archived"}}})
    _w(r / "config/pipeline/sop_gate.json", {"enabled": True, "observe_stages": [], "promote": {"auto": auto, "stage": "出图"}})
    _w(r / f"data/import/runs/{RUN}/script_v2.json", {"episodes": [{"number": 1, "shots": [{"index": 1}]}]})
    return r


def _producer_tick(root: Path) -> dict:
    """与 producer.maybe_promote 同一调用：apply = sop_gate.json promote.auto"""
    auto = bool((SG.config(root).get("promote") or {}).get("auto"))
    return SG.promote(RUN, root, by="producer.maybe_promote", apply=auto)


def _judge_ok(run, ep, stage, shot=None, root=None):
    return {"ok": True, "missing": [], "retro": None}


def test_promote_auto_false_only_reports(tmp_path, monkeypatch):
    r = _root(tmp_path, auto=False)
    before = (r / "config/pipeline/runs.json").read_bytes()
    monkeypatch.setattr(SG, "judge", _judge_ok)
    res = _producer_tick(r)
    assert res["promote"] is True and res["episodes"] == [1] and not res.get("applied")      # 判定可提升，但只报告
    assert (r / "config/pipeline/runs.json").read_bytes() == before                          # runs.json 一字不动
    assert not (r / "config/pipeline/run.json").exists()


def test_promote_auto_true_writes_runs_json_with_history(tmp_path, monkeypatch):
    r = _root(tmp_path, auto=True)
    monkeypatch.setattr(SG, "judge", _judge_ok)
    res = _producer_tick(r)
    assert res["promote"] is True and res.get("applied") is True
    reg = json.loads((r / "config/pipeline/runs.json").read_text(encoding="utf-8"))
    e = reg["runs"][RUN]
    assert e["status"] == "producing"
    h = e["status_history"][-1]
    assert (h["from"], h["to"], h["by"]) == ("preparing", "producing", "producer.maybe_promote") and "sop_gate.promote" in h["why"]
    assert json.loads((r / "config/pipeline/run.json").read_text(encoding="utf-8"))["run_id"] == RUN   # 派生指针同步
    again = _producer_tick(r)                                                                 # 已 producing：不再提升
    assert again["promote"] is False and "不是 preparing" in again["why"]


def test_promote_not_ready_never_writes(tmp_path, monkeypatch):
    r = _root(tmp_path, auto=True)
    before = (r / "config/pipeline/runs.json").read_bytes()
    monkeypatch.setattr(SG, "judge", lambda run, ep, stage, shot=None, root=None: {"ok": False, "missing": ["资产就绪：缺口 1"]})
    res = _producer_tick(r)
    assert res["promote"] is False and "缺口" in res["why"]
    assert (r / "config/pipeline/runs.json").read_bytes() == before


def test_preview_dir_follows_run(tmp_path):
    """sop_gate:308 原来写死 "series10"：现在按 run 交给 run_ctx.episodes_out（V2 剧 = data/episodes/<剧>）"""
    r = _root(tmp_path, auto=False)
    assert SG._episodes_rel(RUN) == Path("data/episodes") / RUN
    assert SG._episodes_rel("series10_v1") == Path("data/episodes/series10")   # V1 legacy 目录不变（run_ctx 或回退同一规则）
    assert not SG.check_preview(r, RUN, 1)["ok"]
    _w(r / f"data/episodes/{RUN}/ep01_preview.mp4", "x")
    _w(r / "data/episodes/series10/ep02_preview.mp4", "x")
    assert SG.check_preview(r, RUN, 1)["ok"] and not SG.check_preview(r, RUN, 2)["ok"]   # 不读 V1 目录


def test_master_check_flags_sop_gate_disabled(tmp_path):
    r = _root(tmp_path, auto=False)
    row = next(x for x in MC.switch_rows(r) if x["name"] == "sop_gate.enabled")
    assert row["ok"] and row["op"] == "eq"
    _w(r / "config/pipeline/sop_gate.json", {"enabled": False})
    row = next(x for x in MC.switch_rows(r) if x["name"] == "sop_gate.enabled")
    assert not row["ok"]
    assert any("sop_gate.enabled=False" in ln for ln in MC.sec_switches(r))
