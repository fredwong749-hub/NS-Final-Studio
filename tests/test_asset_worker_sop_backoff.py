"""ISS-1103-033742-73be（WATCHDOG 11-03）：asset_worker 每拍撞 sop_gate——导入闸门 reopened 期间 30 分钟 52 条一样的 observe 违规。

要求：进阶段前先读闸门状态（只读 judge），没过就退避（≥ 5 分钟，或闸门状态变化立即重判），违规按 (by, stage, missing) 去重计数。
临时根目录 + 真 sop_gate 判定，不碰真实数据。
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "pipeline"))
import asset_worker as AW  # noqa: E402

RUN = "drama_x"


def _load(name, rel):
    sp = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


SG = _load("sop_gate_t_backoff", "tools/master/sop_gate.py")


def _w(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def _root(r, *, gate="reopened", observe=True, fails=6):
    _w(r / "config/pipeline/runs.json", {"primary": RUN, "legacy_unprefixed_run": "old_v1", "runs": {RUN: {"status": "preparing"}}})
    _w(r / "config/pipeline/sop_gate.json", {"enabled": True, "observe_stages": ["资产就绪"] if observe else []})
    _w(r / f"data/import/runs/{RUN}/script_v2.json", {"episodes": [{"number": 1, "shots": [{"index": 1}]}]})
    _w(r / f"data/pipeline/runs/{RUN}/P4_ep01.md", "# P4\n")
    _w(r / f"data/pipeline/runs/{RUN}/autoflow_ep01.json",
       {"stages": [{"id": "gate", "status": gate}, {"id": "import", "status": "imported" if gate == "ok" else gate, "sha256": "a"},
                   {"id": "code", "fails": 0 if gate == "ok" else fails, "detail": ["p4#QW-T1 镜6 时长 7 秒"]}]})
    return r


def _viol(r):
    p = r / "data/pipeline/sop_gate/violations.jsonl"
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


JOBS = [{"id": "face-a", "episode": 1}, {"id": "scene-b", "episode": 1}]


def _tick(r, t):
    rec = {}
    return AW.sop_filter(r, RUN, list(JOBS), rec, now=t, sop=SG), rec


def test_observe_30_minutes_at_most_two_violations_and_jobs_still_pass(tmp_path):
    """事故现场：observe、闸门不变、每 30 s 一拍 × 60 拍（30 分钟）→ 违规 ≤ 2 条（原来 2 作业 × 60 拍 = 120 条）；observe 语义不变：照样放行"""
    r = _root(tmp_path)
    t0 = 1_000_000.0
    for i in range(60):
        out, rec = _tick(r, t0 + 30 * i)
        assert [j["id"] for j in out] == ["face-a", "scene-b"]
    v = _viol(r)
    assert len(v) <= 2 and all(x["by"] == "asset_worker" and x["mode"] == "observe" for x in v)
    st = json.loads((r / f"data/pipeline/asset_jobs/{RUN}/_sop_backoff.json").read_text(encoding="utf-8"))["ep01"]
    assert st["by"] == "asset_worker" and st["stage"] == "资产就绪" and st["repeats"] + st["suppressed"] == 60   # 去重计数：一拍不漏
    assert st["until"] - (t0 + 30 * 59) <= 1800


def test_backoff_at_least_5_minutes_and_ladder(tmp_path):
    r = _root(tmp_path)
    t0 = 1_000_000.0
    _tick(r, t0)
    _tick(r, t0 + 299)
    assert len(_viol(r)) == 1                                          # 5 分钟内不再写
    _, rec = _tick(r, t0 + AW.SOP_BACKOFF_S[0] + 1)
    assert len(_viol(r)) == 2 and rec["sop_gate_backoff"][0]["next_s"] == AW.SOP_BACKOFF_S[1]
    assert min(AW.SOP_BACKOFF_S) >= 300


def test_state_change_rejudges_immediately(tmp_path):
    """闸门状态变了（缺的东西变了 / 改 enforce / 过了）→ 不等退避，立刻按新状态处理"""
    r = _root(tmp_path)
    t0 = 1_000_000.0
    _tick(r, t0)
    _root(tmp_path, fails=2)                                           # 补丁进来：项数变了 = 同一缺口（A1-6 稳定键），不重写
    _tick(r, t0 + 30)
    assert len(_viol(r)) == 1
    _root(tmp_path, gate="pending", fails=2)                           # 闸门状态码变了（reopened → pending）= 新缺口，立刻重判
    _tick(r, t0 + 45)
    assert len(_viol(r)) == 2
    _root(tmp_path, fails=2, observe=False)                            # 总调度清空 observe_stages → enforce 立即生效
    out, rec = _tick(r, t0 + 60)
    assert out == [] and len(rec["sop_gate_blocked"]) == 2 and _viol(r)[-1]["mode"] == "enforce"
    out, rec = _tick(r, t0 + 90)                                       # enforce 退避中：照样挡、不写
    assert out == [] and len(_viol(r)) == 3 and "退避中" in rec["sop_gate_blocked"][0]
    _root(tmp_path, gate="ok", observe=False)                          # 导入闸门过了
    _w(r / f"data/pipeline/asset_jobs/{RUN}/_ready_ep01.json", {"ready": True, "gaps": 0})
    out, rec = _tick(r, t0 + 120)
    assert len(out) == 2 and rec.get("sop_gate_cleared") == [f"{RUN} ep01"] and len(_viol(r)) == 3


def test_per_episode_not_per_job(tmp_path):
    r = _root(tmp_path)
    many = [{"id": f"j{i}", "episode": 1} for i in range(7)]
    AW.sop_filter(r, RUN, many, {}, now=1.0, sop=SG)
    assert len(_viol(r)) == 1                                          # 7 个作业同一集 = 1 条，不是 7 条


def test_counter_in_missing_does_not_reset_backoff(tmp_path):
    """A1-6 事故：missing 里“（第 N 次）”/ next_action 文案每拍在变 → 原来签名一变就重写（22 分钟 7 条）。现在 30 分钟 ≤ 2 条"""
    r = _root(tmp_path)
    t0 = 1_000_000.0
    af = r / f"data/pipeline/runs/{RUN}/autoflow_ep01.json"
    for i in range(60):
        d = json.loads(af.read_text(encoding="utf-8"))
        d["next_action"] = ["等写手交 patch_ep01（第 %d 次）" % (i + 1), "已重开补丁预算，跑 autoflow run 继续",
                            "等评审交 factcheck_ep01（第 2 次）"][i % 3]
        d["stages"][2]["fails"] = 6 - i % 5
        _w(af, d)
        out, _ = _tick(r, t0 + 30 * i)
        assert len(out) == 2
    assert len(_viol(r)) <= 2
    st = json.loads((r / f"data/pipeline/asset_jobs/{RUN}/_sop_backoff.json").read_text(encoding="utf-8"))["ep01"]
    assert st["gaps"] == ["导入闸门|gate=reopened,import=reopened"] and st["repeats"] + st["suppressed"] == 60
