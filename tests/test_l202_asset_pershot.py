"""L-202（项目方 11-06 08:0x 选 A“按镜判”）：资产就绪按镜判，取代 L-140 整集资产齐了才出图。
本镜用到的人物脸 / 造型 / 场景底图齐了就出首帧和视频，缺资产的镜单独等，补齐后自动放行。夹具全在临时根目录。"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


SG = _load("sop_gate_l202_t", "tools/master/sop_gate.py")
AJ = _load("asset_jobs_l202_t", "tools/pipeline/asset_jobs.py")
RUN = "drama_l202"
CFG = {"enabled": True, "observe_stages": [], "whole_episode_prompts": False, "whole_episode_assets": False,
       "promote": {"auto": False, "stage": "出图"}}


def _w(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def _root(tmp_path, *, cfg=None, shots=(1, 2, 3)):
    r = tmp_path
    _w(r / "config/pipeline/runs.json", {"primary": RUN, "legacy_unprefixed_run": "old_v1", "runs": {RUN: {"status": "preparing"}}})
    _w(r / "config/pipeline/sop_gate.json", cfg or CFG)
    _w(r / "data/import/runs" / RUN / "script_v2.json", {"episodes": [{"number": 1, "shots": [{"index": n} for n in shots]}]})
    _w(r / f"data/pipeline/runs/{RUN}/P4_ep01.md", "# P4\n")
    _w(r / f"data/pipeline/runs/{RUN}/autoflow_ep01.json",
       {"stages": [{"id": "gate", "status": "ok"}, {"id": "import", "status": "imported", "sha256": "abc"}]})
    _w(r / f"data/pipeline/runs/{RUN}/autoflow.json", {})
    return r


def _prompts(r, ok=(1, 2, 3)):
    _w(r / f"data/pipeline/sop_gate/{RUN}/ep01_prompts.json",
       {"fingerprint": SG.prompt_fingerprint(r, RUN, 1), "at": "t", "shots": {str(n): {"ok": True} for n in ok}})


def _ready(r, shot_gaps=None, **extra):
    d = {"ready": False, "gaps": 2, "at": "t", "created": [], "existing": [], "reopened": [], **extra}
    if shot_gaps is not None:
        d["shot_gaps"] = shot_gaps
    _w(r / f"data/pipeline/asset_jobs/{RUN}/_ready_ep01.json", d)


def _job(r, jid, kind, shots, state="pending"):
    _w(r / f"data/pipeline/asset_jobs/{RUN}/{jid}.json",
       {"id": jid, "run": RUN, "episode": 1, "kind": kind, "who": jid, "what": "缺", "shots": list(shots), "state": state})


# ---------------------------------------------------------------- 配置与决策登记
def test_l202_config_and_decision():
    sg = json.loads((ROOT / "config/pipeline/sop_gate.json").read_text(encoding="utf-8"))
    assert sg["whole_episode_assets"] is False and "L-202" in sg["_whole_episode_assets"]
    src = (ROOT / "tools/master/sop_gate.py").read_text(encoding="utf-8")
    assert 'config(root).get("whole_episode_assets", True)' in src
    od = (ROOT / "config/owner_decisions.yaml").read_text(encoding="utf-8")
    assert "id: D-V2-202" in od and "whole_episode_assets" in od


# ---------------------------------------------------------------- 按镜判：shot_gaps 来源
def test_shot_with_assets_passes_while_others_wait(tmp_path):
    r = _root(tmp_path)
    _prompts(r)
    _ready(r, shot_gaps={"1": ["[face] 黎岸：没有身份脸"], "3": ["[scene] sk_bar：没有底图"]})
    assert SG.require(RUN, 1, "出图", shot=2, root=r)["ok"]          # 镜 2 用到的资产齐 → 放行
    with pytest.raises(SG.SopGateError, match="镜1 等资产"):
        SG.require(RUN, 1, "出图", shot=1, root=r)
    with pytest.raises(SG.SopGateError, match="镜3 等资产"):
        SG.require(RUN, 1, "出图", shot=3, root=r)
    with pytest.raises(SG.SopGateError):                              # 不给镜号 = 仍按整集
        SG.require(RUN, 1, "出图", root=r)
    row = SG.check_assets(r, RUN, 1)
    assert row["bad"] == [1, 3] and row["ready_shots"] == [2] and "可放行" in row["why"]


def test_star_gap_blocks_every_shot(tmp_path):
    r = _root(tmp_path)
    _prompts(r)
    _ready(r, shot_gaps={"*": ["[script] -：导入稿读不出"]})
    for n in (1, 2, 3):
        assert not SG.check_assets(r, RUN, 1, shot=n)["ok"]


def test_whole_episode_assets_true_keeps_l140(tmp_path):
    r = _root(tmp_path, cfg={**CFG, "whole_episode_assets": True})
    _prompts(r)
    _ready(r, shot_gaps={"1": ["[face] 黎岸：没有身份脸"]})
    with pytest.raises(SG.SopGateError, match="资产就绪"):
        SG.require(RUN, 1, "出图", shot=2, root=r)
    assert SG.check_assets(r, RUN, 1, shot=2)["ok"]                   # 单查阶段仍可按镜看（与 L-140 提示词同款）


def test_all_ready_file_passes_unchanged(tmp_path):
    r = _root(tmp_path)
    _prompts(r)
    _w(r / f"data/pipeline/asset_jobs/{RUN}/_ready_ep01.json", {"ready": True, "gaps": 0, "at": "t"})
    assert SG.check_assets(r, RUN, 1, shot=1)["ok"] and SG.check_assets(r, RUN, 1)["ok"]


# ---------------------------------------------------------------- 旧 _ready 文件（没有 shot_gaps）→ 按作业文件推
def test_fallback_from_job_files(tmp_path):
    r = _root(tmp_path)
    _prompts(r)
    _job(r, "face-ch_a", "face", [1, 3])
    _job(r, "voice-ch_a", "voice", [1, 2, 3])                          # 音色不挡首帧
    _job(r, "sheet-ch_b-A", "sheet", [2], state="done")                # 已落地的作业不再挡（自动放行）
    _ready(r, existing=["face-ch_a", "voice-ch_a", "sheet-ch_b-A"])
    g = SG.asset_shot_gaps(r, RUN, 1)
    assert set(g) == {1, 3} and all("face-ch_a" in x for x in g[1])
    assert SG.require(RUN, 1, "出图", shot=2, root=r)["ok"]
    with pytest.raises(SG.SopGateError):
        SG.require(RUN, 1, "出图", shot=1, root=r)


def test_fallback_job_without_shots_or_unreadable_blocks_all(tmp_path):
    r = _root(tmp_path)
    _prompts(r)
    _job(r, "scene-sk_x", "scene", [])
    _ready(r, created=["scene-sk_x"])
    assert None in SG.asset_shot_gaps(r, RUN, 1) and not SG.check_assets(r, RUN, 1, shot=2)["ok"]
    _ready(r, created=["ghost-job"])                                   # 作业文件读不出 = 挡全部（失败关闭）
    assert not SG.check_assets(r, RUN, 1, shot=2)["ok"]


# ---------------------------------------------------------------- 资产补齐自动放行（_ready 重写即放行，不用人工）
def test_release_when_ready_rewritten(tmp_path):
    r = _root(tmp_path)
    _prompts(r)
    _ready(r, shot_gaps={"1": ["[face] 黎岸：没有身份脸"]})
    assert not SG.judge(RUN, 1, "出图", 1, root=r)["ok"]
    _ready(r, shot_gaps={})
    assert SG.judge(RUN, 1, "出图", 1, root=r)["ok"]


# ---------------------------------------------------------------- 退避 / 派单：缺资产的镜退避中不影响齐资产的镜
def test_backoff_blocked_shot_does_not_hold_ready_shot(tmp_path):
    r = _root(tmp_path)
    _prompts(r)
    _ready(r, shot_gaps={"1": ["[face] 黎岸：没有身份脸"]})
    sp = r / "backoff.json"
    b1 = SG.require_backoff(RUN, 1, "出图", shot=1, root=r, by="producer", now=1000.0, state_path=sp)
    assert b1["allow"] is False and b1["logged"] is True
    b1b = SG.require_backoff(RUN, 1, "出图", shot=1, root=r, by="producer", now=1001.0, state_path=sp)
    assert b1b["allow"] is False and b1b["backoff"]["suppressed"] == 1
    b2 = SG.require_backoff(RUN, 1, "出图", shot=2, root=r, by="producer", now=1002.0, state_path=sp)
    assert b2["allow"] is True and b2["ok"] is True


# ---------------------------------------------------------------- 视频 / 提升也按镜
def test_video_shots_ok_per_shot(tmp_path, monkeypatch):
    r = _root(tmp_path, shots=(1, 2))
    _prompts(r, ok=(1, 2))
    _ready(r, shot_gaps={"1": ["[face] 黎岸：没有身份脸"]})
    monkeypatch.setattr(SG, "_no_last", lambda *a, **k: True)
    for n in (1, 2):
        (r / "data/img").mkdir(parents=True, exist_ok=True)
        (r / f"data/img/s{n}.png").write_bytes(b"x")
        _w(r / f"data/renders/{RUN}/ep01/S{n}/takes.json",
           {"active": {"image": 1}, "takes": [{"stage": "image", "n": 1, "file": f"img/s{n}.png",
                                                "postflight": {"ok": True, "items": [{"id": "Q9", "status": "pass"}]}}]})
    assert SG.video_shots_ok(RUN, 1, r) == [2]


def test_promote_when_any_shot_can_enter(tmp_path):
    r = _root(tmp_path)
    _prompts(r, ok=(2,))
    _ready(r, shot_gaps={"1": ["[face] 黎岸：没有身份脸"], "3": ["[scene] sk_bar：没有底图"]})
    res = SG.promote_check(RUN, r)
    assert res["promote"] is True and res["episodes"] == [1] and "镜 2" in res["why"]
    _ready(r, shot_gaps={"*": ["[script] -：导入稿读不出"]})
    assert SG.promote_check(RUN, r)["promote"] is False


def test_promote_stays_whole_episode_when_both_flags_true(tmp_path):
    r = _root(tmp_path, cfg={**CFG, "whole_episode_prompts": True, "whole_episode_assets": True})
    _prompts(r)
    _ready(r, shot_gaps={"1": ["[face] 黎岸：没有身份脸"]})
    assert SG.promote_check(RUN, r)["promote"] is False


# ---------------------------------------------------------------- asset_jobs 写 shot_gaps
def test_asset_jobs_shot_gaps_from_episode_ready():
    res = {"gaps": [{"kind": "face", "who": "黎岸", "what": "没有身份脸", "shots": [1, 3]},
                    {"kind": "voice", "who": "黎岸", "what": "没选音色", "shots": [1, 2, 3]},
                    {"kind": "scene", "who": "sk_bar", "what": "没有底图", "shots": []}],
           "shots": [{"index": n} for n in (1, 2, 3)]}
    g = AJ.shot_gaps(res)
    assert set(g) == {"1", "3", "*"} and g["*"] == ["[scene] sk_bar：没有底图"] and len(g["1"]) == 1


def test_asset_jobs_generate_writes_shot_gaps(tmp_path):
    r = _root(tmp_path)
    res = {"ready": False, "gaps": [{"kind": "face", "who": "黎岸", "what": "没有身份脸", "shots": [1]}],
           "shots": [{"index": n} for n in (1, 2, 3)]}
    out = AJ.generate(RUN, 1, r, res=res)                              # 没有 P1 → error 分支也要带 shot_gaps
    d = json.loads((r / f"data/pipeline/asset_jobs/{RUN}/_ready_ep01.json").read_text(encoding="utf-8"))
    assert out["shot_gaps"] == {"1": ["[face] 黎岸：没有身份脸"]} and d["shot_gaps"] == out["shot_gaps"]
    _prompts(r)
    assert SG.check_assets(r, RUN, 1, shot=2)["ok"] and not SG.check_assets(r, RUN, 1, shot=1)["ok"]
