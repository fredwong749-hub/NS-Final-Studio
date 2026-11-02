"""HARNESS-O：tools/master/episode_retro.py（集复盘门）+ tools/master/master_check.py（总调度巡检）。临时根目录夹具，不碰真实数据。"""
from __future__ import annotations

import importlib.util
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


ER = _load("episode_retro_t", "tools/master/episode_retro.py")
MC = _load("master_check_t", "tools/master/master_check.py")
SG = _load("sop_gate_t2", "tools/master/sop_gate.py")
RUN = "drama_x"


def _w(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def _root(tmp_path):
    r = tmp_path
    _w(r / "config/pipeline/runs.json", {"primary": RUN, "legacy_unprefixed_run": "old", "runs": {RUN: {"status": "preparing"}}})
    _w(r / "config/pipeline/sop_gate.json", {"enabled": True, "observe_stages": []})
    _w(r / f"data/import/runs/{RUN}/script_v2.json", {"episodes": [{"number": 1, "shots": [{"index": 1}]}, {"number": 2, "shots": [{"index": 1}]}]})
    for e in (1, 2):
        _w(r / f"data/pipeline/runs/{RUN}/P4_ep{e:02d}.md", "x")
        _w(r / f"data/pipeline/runs/{RUN}/autoflow_ep{e:02d}.json",
           {"started": "2026-11-03 01:00:00", "stages": [{"id": "gate", "status": "ok"}, {"id": "import", "status": "imported", "sha256": "s"}]})
        _w(r / f"data/pipeline/asset_jobs/{RUN}/_ready_ep{e:02d}.json", {"ready": True, "gaps": 0})
    iss = [{"id": "ISS-1", "event": "open", "time": "2026-11-03 01:10:00", "run": RUN, "episode": 1, "step": "8", "who": "A",
            "what": "缺脸", "blocking": True, "fix_hint": "补脸", "status": "open"},
           {"id": "ISS-2", "event": "open", "time": "2026-11-03 01:20:00", "run": RUN, "episode": 1, "step": "9", "who": "B",
            "what": "Q9 矛盾", "blocking": False, "fix_hint": "", "status": "open"},
           {"id": "ISS-2", "event": "close", "time": "2026-11-03 01:30:00", "sop_updated": True},
           {"id": "ISS-3", "event": "open", "time": "2026-11-03 01:20:00", "run": RUN, "episode": 2, "step": "3", "who": "C",
            "what": "别集", "blocking": False, "status": "open"}]
    _w(r / "data/pipeline/issues.jsonl", "\n".join(json.dumps(x, ensure_ascii=False) for x in iss) + "\n")
    return r


def _fake_collect(ep):
    return {"run": RUN, "episode": ep, "shots": 11, "model_calls": {"writer": {"calls": 10 - ep, "voided": 0}, "reviewer": {"calls": 2},
            "judges": {"calls": 3, "by_model": {}}, "vlm": {"calls": 5}}, "interventions": {"total": 5 - ep, "manual_cli": 0,
            "rejected_deliverables": 0, "requeue_after_fix": 0, "api_restarts": 0, "manual_lane_holds": 0, "issues": {"opened": 2, "blocking": 1}},
            "time": {"writing_p1": {"h": 1}, "writing_p2_to_import": {"h": 2}, "stage_a_assets": {"h": 1, "status": "done"},
                     "stage_b_golden": {"h": None, "status": "todo"}, "owner_wait_total_s": 60},
            "success": {"images": {"all": {"takes": 4, "passed": 2, "pass_rate": 0.5, "takes_per_pass": 2, "preflight_blocked_attempts": 0}}},
            "automation": {"ratio": 0.8, "by_actor": {}}, "gpu": {"overall": 0.4}, "quality": {"hollywood": {"mean": None}}, "nulls": []}


def test_generate_retro_and_gate(tmp_path):
    r = _root(tmp_path)
    ok, path = ER.generate(RUN, 1, root=r, collect=_fake_collect)
    text = Path(path).read_text(encoding="utf-8")
    assert ok and Path(path).name == "RETRO_ep01.md" and "retro_status: draft" in text
    assert "ISS-1" in text and "ISS-2" in text and "ISS-3" not in text           # 只列本集卡点
    assert "- [ ] ISS-1（A）：经验写进 PIPELINE_SOP_V2.md" in text               # 没写进 SOP 的进清单
    assert "ISS-2（B）：经验写进" not in text                                    # 已 sop_updated 的不再列
    assert SG.retro_state(RUN, 1, r) == "draft"
    assert not SG.judge(RUN, 2, "出图", shot=1, root=r)["ok"]                    # 复盘没 done → 第 2 集不能出图
    ok, msg = ER.mark_done(RUN, 1, root=r)
    assert not ok and "没勾" in msg                                              # 没勾完不许 done
    Path(path).write_text(text.replace("- [ ]", "- [x]"), encoding="utf-8")
    ok2, _ = ER.generate(RUN, 1, root=r, collect=_fake_collect)                 # 刷新保留已勾
    assert ok2 and "- [ ]" not in Path(path).read_text(encoding="utf-8")
    assert ER.mark_done(RUN, 1, root=r)[0] and SG.retro_state(RUN, 1, r) == "done"
    assert ER.generate(RUN, 1, root=r, collect=_fake_collect)[0] is False       # done 后不覆盖
    j = SG.judge(RUN, 2, "出图", shot=1, root=r)
    assert not any("复盘" in m for m in j["missing"])


def test_retro_compares_previous_episode(tmp_path):
    r = _root(tmp_path)
    ok, path = ER.generate(RUN, 2, root=r, collect=_fake_collect)
    text = Path(path).read_text(encoding="utf-8")
    assert ok and "| 指标 | 第1集 | 第2集 | 变化 |" in text and "✅ 变好" in text


def test_master_check_page(tmp_path):
    r = _root(tmp_path)
    _w(r / "config/pipeline/agent_dispatcher.json", {"enabled": True, "max_concurrent": 3})
    _w(r / "config/pipeline/asset_worker.json", {"max_parallel": 2, "render": True})
    _w(r / "data/factory/autoflow_resident.json", {"pid": 1, "t": time.time() - 10, "tick": 5})
    _w(r / "data/sentinel/gpu_samples.jsonl", "x\n" + json.dumps({"t": time.time(), "host": "gpu33", "smi": [[0, 90, 15000]]}) + "\n")
    _w(r / "data/state/netfix/partition.json", {"retired_lanes": ["gpu33:0"]})
    (r / "data/master/inbox/requests").mkdir(parents=True)
    s = MC.build(r, api=lambda: "HTTP 200")
    page = MC.render(s)
    lines = page.splitlines()
    assert len(lines) <= MC.MAX_LINES
    assert "drama_x ep01：提示词｜复盘 missing" in page and "drama_x ep02：提示词" in page
    assert "未关 2 条（阻断 1）" in page
    assert "agent_dispatcher.max_concurrent=3，要求 le 2" in page                # 开关和决策对不上
    assert "gpu33:0⛔ 90%" in page and "HTTP 200" in page and "待处理 0 条" in page


def test_master_check_caps_40_lines():
    big = {f"节{i}": [f"  行{j}" for j in range(20)] for i in range(7)}
    assert len(MC.render(big).splitlines()) <= 40
