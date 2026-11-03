"""HARNESS-O：tools/master/sop_gate.py（SOP 阶段闸门）。夹具全在临时根目录，不读真实数据。"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("sop_gate_t", ROOT / "tools/master/sop_gate.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


SG = _load()
RUN = "drama_x"


def _w(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def _root(tmp_path, *, gate="ok", imp="imported", ready=True, shots=(1, 2), cfg=None, eps=(1,)):
    r = tmp_path
    _w(r / "config/pipeline/runs.json", {"primary": RUN, "legacy_unprefixed_run": "old_v1", "runs": {RUN: {"status": "preparing"}}})
    _w(r / "config/pipeline/sop_gate.json", cfg or {"enabled": True, "observe_stages": []})
    _w(r / "data/import/runs" / RUN / "script_v2.json",
       {"episodes": [{"number": e, "shots": [{"index": n} for n in shots]} for e in eps]})
    for e in eps:
        _w(r / f"data/pipeline/runs/{RUN}/P4_ep{e:02d}.md", "# P4\n")
        _w(r / f"data/pipeline/runs/{RUN}/autoflow_ep{e:02d}.json",
           {"stages": [{"id": "gate", "status": gate}, {"id": "import", "status": imp, "sha256": "abc"},
                       {"id": "code", "fails": 0 if gate == "ok" else 3, "detail": ["p4#TL-1 镜1 时间轴不全"]}],
            "next_action": "等写手交补丁"})
        if ready:
            _w(r / f"data/pipeline/asset_jobs/{RUN}/_ready_ep{e:02d}.json", {"ready": True, "gaps": 0, "at": "t"})
    _w(r / f"data/pipeline/runs/{RUN}/autoflow.json", {})
    return r


def _prompts(r, ep=1, ok=(1, 2), bad=()):
    ev = {"fingerprint": SG.prompt_fingerprint(r, RUN, ep), "at": "t",
          "shots": {**{str(n): {"ok": True} for n in ok}, **{str(n): {"ok": False, "why": "I3 没有设定图"} for n in bad}}}
    _w(r / f"data/pipeline/sop_gate/{RUN}/ep{ep:02d}_prompts.json", ev)


def _take(r, ep, n, *, q9="pass", last=False):
    d = r / f"data/renders/{RUN}/ep{ep:02d}/S{n}"
    (r / "data/img").mkdir(parents=True, exist_ok=True)
    (r / f"data/img/e{ep}s{n}.png").write_bytes(b"x")
    takes = [{"stage": "image", "n": 1, "file": f"img/e{ep}s{n}.png",
              "postflight": {"ok": True, "items": [{"id": "Q9", "status": q9}]}}]
    act = {"image": 1}
    if last:
        takes.append({"stage": "last", "n": 1, "file": f"img/e{ep}s{n}.png", "postflight": {"ok": True}})
        act["last"] = 1
    _w(d / "takes.json", {"active": act, "takes": takes})


def test_current_stage_prompt_when_import_and_assets_pass(tmp_path):
    """第 1 集真实形态（导入 + 资产都过、还没有提示词证据）→ 判在“提示词”"""
    r = _root(tmp_path)
    st = SG.status(RUN, r)[0]
    assert st["stage"] == "提示词" and st["passed"] == ["剧本", "导入闸门", "资产就绪"]


def test_reopened_import_is_not_passed(tmp_path):
    r = _root(tmp_path, gate="reopened", imp="reopened")
    st = SG.status(RUN, r)[0]
    assert st["stage"] == "导入闸门" and "reopened" in st["why"] and "等写手交补丁" in st["why"]


def test_require_raises_and_logs_violation(tmp_path):
    r = _root(tmp_path)
    with pytest.raises(SG.SopGateError, match="提示词"):
        SG.require(RUN, 1, "出图", shot=1, root=r)
    v = [json.loads(x) for x in (r / "data/pipeline/sop_gate/violations.jsonl").read_text(encoding="utf-8").splitlines()]
    assert v[-1]["stage"] == "出图" and v[-1]["mode"] == "enforce"


def test_require_passes_per_shot(tmp_path):
    # PRODMERGE-O：L-140 整集就绪才出图——默认 whole_episode_prompts=true 时镜 1 也要等全集提示词过；关掉才按镜
    r = _root(tmp_path, cfg={"enabled": True, "observe_stages": [], "whole_episode_prompts": False})
    _prompts(r, ok=(1,), bad=(2,))
    assert SG.require(RUN, 1, "出图", shot=1, root=r)["ok"]
    with pytest.raises(SG.SopGateError):
        SG.require(RUN, 1, "出图", shot=2, root=r)
    with pytest.raises(SG.SopGateError):          # 不给镜号 = 全集每镜都要过
        SG.require(RUN, 1, "出图", root=r)


def test_prompt_evidence_expires_when_import_changes(tmp_path):
    r = _root(tmp_path)
    _prompts(r)
    assert SG.check_prompts(r, RUN, 1)["ok"]
    af = r / f"data/pipeline/runs/{RUN}/autoflow_ep01.json"
    d = json.loads(af.read_text(encoding="utf-8"))
    d["stages"][1]["sha256"] = "new"
    af.write_text(json.dumps(d), encoding="utf-8")
    assert not SG.check_prompts(r, RUN, 1)["ok"] and "过期" in SG.check_prompts(r, RUN, 1)["why"]


def test_video_requires_q9_and_last(tmp_path):
    r = _root(tmp_path)
    _prompts(r)
    _take(r, 1, 1, q9="fail", last=True)
    _take(r, 1, 2, last=True)
    res = SG.judge(RUN, 1, "视频", root=r)
    assert not res["ok"] and any(m.startswith("出图检测") for m in res["missing"])
    _take(r, 1, 1, q9="pass", last=True)
    assert SG.judge(RUN, 1, "视频", root=r)["ok"]
    assert SG.status(RUN, r)[0]["stage"] == "视频"


def test_observe_mode_does_not_raise(tmp_path):
    r = _root(tmp_path, cfg={"enabled": True, "observe_stages": ["出图"]})
    res = SG.require(RUN, 1, "出图", shot=1, root=r)
    assert res["ok"] is False and res["mode"] == "observe"


def test_retro_blocks_next_episode_images_not_writing(tmp_path):
    r = _root(tmp_path, eps=(1, 2), cfg={"enabled": True, "observe_stages": ["出图"]})
    _prompts(r, ep=2)
    assert SG.judge(RUN, 2, "导入闸门", root=r)["ok"]          # 写作 / 导入不挡
    with pytest.raises(SG.SopGateError, match="复盘"):         # observe 也挡（retro_enforce）
        SG.require(RUN, 2, "出图", shot=1, root=r)
    _w(r / "docs/master/RETRO_ep01.md", "# 复盘\n<!-- retro_status: done -->\n")
    assert SG.require(RUN, 2, "出图", shot=1, root=r)["ok"]


def test_legacy_and_fixture_root_pass_through(tmp_path):
    r = _root(tmp_path)
    assert SG.judge("old_v1", 1, "视频", root=r)["ok"]
    bare = tmp_path / "bare"
    bare.mkdir()
    assert SG.config(bare)["enabled"] is False                 # 测试夹具根目录没有配置 = 不启用
    assert SG.config(ROOT)["enabled"] is True


def test_filter_helpers(tmp_path):
    r = _root(tmp_path, gate="reopened", imp="reopened")
    rec: dict = {}
    assert SG.filter_jobs(RUN, [{"id": "face-a", "episode": 1}], "资产就绪", rec, root=r) == []
    assert rec["sop_gate_blocked"] and "face-a" in rec["sop_gate_blocked"][0]

    class S:
        episode = 1
    assert SG.filter_video_specs(RUN, {"ep01-S1": S()}, root=r) == {}
    sp = {"x": S()}
    assert SG.filter_video_specs("old_v1", sp, root=r) is sp
    _w(r / f"data/pipeline/runs/{RUN}/video/hosts.json", {"1": "gpu33"})
    assert SG.video_dispatch_ok(f"data/pipeline/runs/{RUN}/video", root=r) is False
    assert SG.video_dispatch_ok("data/pipeline/runs/old_v1/video", root=r) is True


def test_probe_prompts_records_shots(tmp_path):
    r = _root(tmp_path)
    # PRODMERGE-O：探针 = build_first + preflight 逐镜结果（runner(run, ep, root, cfg) → rows），不再解析 golden_v2 输出
    rows = {"1": {"ok": True, "why": "", "prompt_sha": "p1"}, "2": {"ok": False, "why": "I3 造型没有设定图"}}
    ev = SG.probe_prompts(RUN, 1, root=r, runner=lambda run, ep, root, cfg: rows)
    assert ev["shots"]["1"]["ok"] and not ev["shots"]["2"]["ok"] and "I3" in ev["shots"]["2"]["why"]
    assert ev["probe"] == "build_first+preflight"
    assert SG.check_prompts(r, RUN, 1, shot=1)["ok"] and not SG.check_prompts(r, RUN, 1)["ok"]


def test_entry_points_have_gate_line():
    """接入点各一行闸门调用（不改原逻辑）"""
    hits = {"tools/autopilot/producer.py": "sop_gate_block(", "tools/pipeline/asset_worker.py": "sop.require_backoff(",   # ISS-1103-033742-73be / W8：按集 + 退避（sop_gate.require_backoff）
            "tools/series10_video/build_jobs.py": "filter_video_specs", "tools/series10_video/vidgen.py": "vidgen_guard",
            "tools/series10_video/night.py": "video_dispatch_ok"}
    for f, needle in hits.items():
        txt = (ROOT / f).read_text(encoding="utf-8")
        assert "HARNESS-O" in txt and needle in txt, f


# ---------------------------------------------------------------- W8 / A1-5、A1-6：require_backoff（asset_worker 与 producer 共用）
def _vio(r):
    p = r / "data/pipeline/sop_gate/violations.jsonl"
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


def test_missing_key_strips_counts_and_text():
    a = ["导入闸门：gate=reopened import=reopened；代码判定 6 项未过；等写手交 patch_ep01（第 14 次）"]
    b = ["导入闸门：gate=reopened import=reopened；等评审交 factcheck_ep01（第 2 次）"]
    assert SG.missing_key(a) == SG.missing_key(b) == ["导入闸门|gate=reopened,import=reopened"]
    assert SG.missing_key(["资产就绪：episode_ready 缺口 3 个"]) == SG.missing_key(["资产就绪：episode_ready 缺口 1 个"])
    assert SG.backoff_sig("出图", a, {"observe_stages": ["出图"]}) != SG.backoff_sig("出图", a, {"observe_stages": []})


def test_require_backoff_observe_producer_many_shots_one_line(tmp_path):
    """A1-5：producer 每拍对 11 镜 ×（首帧 + 尾帧）调 → 同一集同一缺口签名退避期内各阶段只写 1 条；observe 照样放行"""
    r = _root(tmp_path, cfg={"enabled": True, "observe_stages": ["出图", "尾帧"]}, shots=tuple(range(1, 12)))
    t0 = 1_000_000.0
    for tick in range(90):                                   # 30 分钟、每 20 s 一拍
        for n in range(1, 12):
            for st in ("出图", "尾帧"):
                res = SG.require_backoff(RUN, 1, st, shot=n, root=r, by="producer", now=t0 + 20 * tick)
                assert res["allow"] and res["mode"] == "observe"
    v = _vio(r)
    assert 2 <= len(v) <= 4 and {x["stage"] for x in v} == {"出图", "尾帧"} and all(x["by"] == "producer" for x in v)
    assert SG.backoff_path(RUN, "producer", r).is_file()


def test_require_backoff_enforce_blocks_while_suppressed_and_clears(tmp_path):
    r = _root(tmp_path)                                       # 提示词没证据 → 出图 enforce 挡
    t0 = 1_000_000.0
    a = SG.require_backoff(RUN, 1, "出图", shot=1, root=r, by="producer", now=t0)
    b = SG.require_backoff(RUN, 1, "出图", shot=2, root=r, by="producer", now=t0 + 20)
    assert not a["allow"] and a["logged"] and a["error"] and not b["allow"] and not b["logged"] and "退避中" in b["error"]
    assert len(_vio(r)) == 1 and _vio(r)[0]["mode"] == "enforce"
    _prompts(r)
    c = SG.require_backoff(RUN, 1, "出图", shot=1, root=r, by="producer", now=t0 + 40)
    assert c["allow"] and c["ok"] and len(_vio(r)) == 1
    d = SG.require_backoff(RUN, 1, "出图", shot=1, root=r, by="producer", now=t0 + 60 + SG.BACKOFF_S[0])
    assert d["ok"]


def test_l140_whole_episode_prompts_by_default(tmp_path):
    """L-140：默认配置下任何一镜进“出图”都要本集全部（非成人）镜提示词过"""
    r = _root(tmp_path)
    _prompts(r, ok=(1,), bad=(2,))
    with pytest.raises(SG.SopGateError):
        SG.require(RUN, 1, "出图", shot=1, root=r)
    assert SG.check_prompts(r, RUN, 1, shot=1)["ok"]          # 单查提示词阶段仍可按镜看
    _prompts(r, ok=(1, 2))
    assert SG.require(RUN, 1, "出图", shot=1, root=r)["ok"]
