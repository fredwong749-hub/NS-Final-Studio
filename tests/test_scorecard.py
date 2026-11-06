"""W-E2E（L-214）：“做完”记分卡 tools/qa/scorecard.py——口径用合成数据钉死（一次过、预览合成不算做完、空卡率、项目方报的 bug）。"""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sp = importlib.util.spec_from_file_location("scorecard_t", ROOT / "tools/qa/scorecard.py")
S = importlib.util.module_from_spec(sp)
sys.modules["scorecard_t"] = S
sp.loader.exec_module(S)

T0 = datetime(2026, 11, 7, 1, 0, tzinfo=S.JST).timestamp()


def _take(n, stage, minute, ok):
    return {"n": n, "stage": stage, "created_at": f"2026-11-07T01:{minute:02d}:00", "postflight": {"ok": ok}}


def test_frame_rates_first_pass_and_window():
    takes = {"ep02-S1": [_take(1, "image", 5, True), _take(1, "last", 9, False), _take(2, "last", 12, True)],
             "ep02-S2": [_take(1, "image", 6, False), _take(2, "image", 8, True)],
             "ep02-S3": [{"n": 1, "stage": "image", "created_at": "2026-11-06T23:00:00", "postflight": {"ok": True}}]}   # 导入前的旧版不算
    r = S.frame_rates(takes, "image", T0)
    assert r["shots"] == 2 and r["first_pass"] == 0.5 and r["takes"] == 3 and abs(r["pass"] - 2 / 3) < 1e-9
    last = S.frame_rates(takes, "last", T0)
    assert last["first_pass"] == 0.0 and last["pass"] == 0.5
    assert S.frame_rates({}, "image", T0)["first_pass"] is None


def test_video_rates():
    st = {"shots": {"ep02-S1": {"renders": [{"t_sub": T0 + 10, "score": {"verdict": "fail"}}, {"t_sub": T0 + 99, "score": {"verdict": "pass"}}]},
                    "ep02-S2": {"renders": [{"t_sub": T0 + 5, "score": {"verdict": "pass"}}, {"t_sub": T0 + 6}]},
                    "ep01-S1": {"renders": [{"t_sub": T0 + 5, "score": {"verdict": "pass"}}]}}}
    r = S.video_rates([st, None], 2, T0)
    assert r["shots"] == 2 and r["first_pass"] == 0.5 and r["renders"] == 3 and abs(r["pass"] - 2 / 3) < 1e-9


def test_minutes_preview_assembly_is_not_done():
    k = {"start_t": T0, "video_done": 14, "total": 16}
    m, how = S.minutes(k, T0 + 40 * 60, T0 + 300 * 60)
    assert m == 300.0 and "缺 2 镜" in how
    m, how = S.minutes({**k, "video_done": 16}, T0 + 40 * 60, T0 + 300 * 60)
    assert m == 40.0 and how == "到合成"
    assert S.minutes({}, None, T0)[0] is None


def test_owner_bugs_only_owner_reports_in_24h():
    now = datetime(2026, 11, 7, 4, 0, tzinfo=S.JST).timestamp()
    ch = "\n".join([
        "11-07 01:34 | PS-MASTER | 项目方怒（反复点卡、token 花费约 1000 美元）。止损",
        "11-07 01:35 | W-PICK | 待办点了没记录根治：项目方点了好几次没记录",
        "11-07 01:05 | PS-MASTER | L-210 记账：项目方 e 同意",
        "11-07 02:03 | IDLE-WATCH | 项目方 发现 空卡",
        "11-05 01:00 | PS-MASTER | 项目方怒 旧的",
        "随便一行"])
    got = S.owner_bugs(ch, now)
    assert len(got) == 2 and got[0].startswith("11-07 01:34") and "W-PICK" in got[1]


def test_snapshot_line_replaced_not_duplicated():
    md = "# 全局快照 x\n## 🔴 系统自查发现\n- a\n"
    once = S.put_snapshot_line(md, "## 记分卡（1）：x")
    twice = S.put_snapshot_line(once, "## 记分卡（2）：y")
    assert twice.splitlines()[:2] == ["# 全局快照 x", "## 记分卡（2）：y"] and twice.count("## 记分卡") == 1


def _w(p: Path, d):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(d if isinstance(d, str) else json.dumps(d, ensure_ascii=False), encoding="utf-8")


def test_compute_and_write_on_synthetic_root(tmp_path):
    r = tmp_path
    run = "demo_v2"
    _w(r / "config/pipeline/runs.json", {"primary": run, "legacy_unprefixed_run": "series10_v1", "runs": {run: {"status": "producing"}}})
    _w(r / "data/brain/snapshot.json", {"kpi": {"1": {"start_t": T0, "total": 2, "first_done": 2, "last_done": 2, "video_done": 2, "assembled": True},
                                                "2": {"start_t": T0, "total": 2, "first_done": 1, "last_done": 0, "video_done": 0}}})
    _w(r / f"data/renders/{run}/ep01/S1/takes.json", {"takes": [_take(1, "image", 5, True)]})
    _w(r / f"data/renders/{run}/ep01/S2/takes.json", {"takes": [_take(1, "image", 5, True)]})
    _w(r / f"data/renders/{run}/ep02/S1/takes.json", {"takes": [_take(1, "image", 5, False)]})
    mp4 = r / f"data/episodes/{run}/ep01_v1.mp4"
    _w(mp4, "x")
    import os
    os.utime(mp4, (T0 + 45 * 60, T0 + 45 * 60))
    _w(r / "data/sched/shadow/metrics.json", {"minutes": 100, "live_idle_lane_min": 30, "live_idle_with_work_lane_min": 6, "shadow_idle_lane_min": 12,
                                              "since": "x"})
    _w(r / "data/sched/shadow/last.json", {"row": {"lanes": {"a": {}, "b": {}, "c": {}}}})
    _w(r / "data/brain/snapshot.md", "# 全局快照\n## KPI\n")
    listing = {"episodes": [{"ep": 2, "waiting": 1, "counts": {"waiting": 1}}]}
    d = S.compute(r, run, now=T0 + 120 * 60, adult_listing=listing, open_items=[])
    e1, e2 = d["episodes"]
    assert e1["full_auto"] and e1["in_budget"] and e1["minutes"] == 45.0 and e1["first"]["first_pass"] == 1.0
    assert not e2["full_auto"] and "成人镜等项目方点" in e2["owner_needed"][0] and not e2["in_budget"]
    o = d["overall"]
    assert o["full_auto"] == "1/2" and o["in_budget"] == "1/2" and abs(o["first_pass"] - 2 / 3) < 1e-9
    assert abs(o["idle"]["pct"] - 0.1) < 1e-9 and o["idle"]["lanes"] == 3
    S.write(d, r)
    assert "## 每集" in (r / S.OUT_MD).read_text(encoding="utf-8")
    assert json.loads((r / S.OUT_JSON).read_text(encoding="utf-8"))["line"].startswith("## 记分卡")
    assert (r / S.SNAP_MD).read_text(encoding="utf-8").splitlines()[1].startswith("## 记分卡")
