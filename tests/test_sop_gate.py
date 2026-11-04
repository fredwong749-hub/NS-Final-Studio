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


# ------------------------------------------------------------------ W38：按集清单指纹（别集资产作业写清单不再作废本集证据）
def _manifest(r, chars=None, scenes=None, updated="t0"):
    _w(r / "assets_v2/manifest.json", {"schema": "nsfs.assets_manifest/1", "updated_at": updated,
                                       "characters": chars if chars is not None else {"lead_f": {"display_name": "祁念", "face": "a"},
                                                                                      "ch_b": {"display_name": "黎岸", "face": None}},
                                       "scenes": scenes if scenes is not None else {"sk_1": {"base": "s1"}}})


def _probe_keyed(r, keys=("characters/lead_f", "scenes/sk_1")):
    rows = {"1": {"ok": True, "manifest_keys": list(keys)}, "2": {"ok": True, "manifest_keys": []}}
    return SG.probe_prompts(RUN, 1, root=r, runner=lambda run, ep, root, cfg: rows)


def _bump(r, fn):
    p = r / "assets_v2/manifest.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    fn(d)
    p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")


def test_w38_other_episode_manifest_write_keeps_evidence(tmp_path):
    """ep02 的身份脸作业登记 ch_b + 刷 updated_at → 整文件 sha 变了，但 ep01 只用 lead_f / sk_1 → 证据仍有效"""
    r = _root(tmp_path)
    _manifest(r)
    ev = _probe_keyed(r)
    assert ev["manifest_keys"] == ["characters/lead_f", "scenes/sk_1"] and ev["fingerprint_scoped"]["manifest_sha"].startswith("k:")
    assert ev["fingerprint"] == ev["fingerprint_scoped"]            # 按集指纹（rev2 服务器读 fingerprint_scoped）
    assert SG.check_prompts(r, RUN, 1)["ok"]
    _bump(r, lambda d: (d["characters"]["ch_b"].update(face="new"), d.update(updated_at="t1")))
    assert SG.check_prompts(r, RUN, 1)["ok"]


def test_w38_used_entry_change_expires_evidence(tmp_path):
    r = _root(tmp_path)
    _manifest(r)
    _probe_keyed(r)
    _bump(r, lambda d: d["characters"]["lead_f"].update(face="b"))
    c = SG.check_prompts(r, RUN, 1)
    assert not c["ok"] and "过期" in c["why"]
    r2 = _root(tmp_path / "s")
    _manifest(r2)
    _probe_keyed(r2)
    _bump(r2, lambda d: d["scenes"]["sk_1"].update(base="s2"))
    assert not SG.check_prompts(r2, RUN, 1)["ok"]


def test_w38_used_entry_added_later_expires(tmp_path):
    """本集用到的条目当时清单里还没有（None）→ 之后补上 = 过期（重编译才知道新资产进没进参考）"""
    r = _root(tmp_path)
    _manifest(r, chars={"lead_f": {"display_name": "祁念"}})
    _probe_keyed(r, keys=("characters/lead_f", "characters/ch_b"))
    assert SG.check_prompts(r, RUN, 1)["ok"]
    _bump(r, lambda d: d["characters"].update(ch_b={"display_name": "黎岸"}))
    assert not SG.check_prompts(r, RUN, 1)["ok"]


def test_w38_rows_without_keys_fall_back_to_whole_file(tmp_path):
    """有一镜没带 manifest_keys（编译出错 / 旧探针）→ 不写按集指纹，只认整文件指纹（失败关闭）"""
    r = _root(tmp_path)
    _manifest(r)
    rows = {"1": {"ok": True, "manifest_keys": ["characters/lead_f"]}, "2": {"ok": False, "why": "编译出错"}}
    ev = SG.probe_prompts(RUN, 1, root=r, runner=lambda run, ep, root, cfg: rows)
    assert "manifest_keys" not in ev and "fingerprint_scoped" not in ev
    _bump(r, lambda d: d.update(updated_at="t9"))
    assert "过期" in SG.check_prompts(r, RUN, 1, shot=1)["why"]


def test_w38_manifest_keys_for_matches_id_name_and_path(tmp_path):
    r = _root(tmp_path)
    _manifest(r, chars={"lead_f": {"display_name": "祁念"}, "ch_b": {"display_name": "黎岸"}, "ch_c": {"display_name": "周旭"}},
              scenes={"sk_1": {}, "sk_2": {}})
    job = {"prompt": "祁念站在白幕前", "refs": ["assets_v2/scenes/sk_1/base.png"], "cast": [{"name": "黎岸"}], "asset_refs": {}}
    assert SG.manifest_keys_for(r, RUN, job) == ["characters/ch_b", "characters/lead_f", "scenes/sk_1"]


def test_w38_probe_evidence_idempotent_across_manifest_rewrites(tmp_path):
    """冒烟 G7：同一输入两遍证据（去掉 at）字节一致——别集条目 / updated_at 变了也一样（整文件 sha 不进证据）"""
    r = _root(tmp_path)
    _manifest(r)
    p = r / f"data/pipeline/sop_gate/{RUN}/ep01_prompts.json"
    _probe_keyed(r)
    a = json.loads(p.read_text(encoding="utf-8"))
    _bump(r, lambda d: (d.update(updated_at="t7"), d["characters"]["ch_b"].update(face="z")))
    _probe_keyed(r)
    b = json.loads(p.read_text(encoding="utf-8"))
    a.pop("at"), b.pop("at")
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_w38_rev2_server_compat(tmp_path):
    """已部署的 rev2 判法：fingerprint 对整文件 或 fingerprint_scoped 对按集——新证据在 rev2 下仍有效"""
    r = _root(tmp_path)
    _manifest(r)
    ev = _probe_keyed(r)
    _bump(r, lambda d: d.update(updated_at="t8"))
    keys = ev["manifest_keys"]
    rev2_fresh = ev["fingerprint"] == SG.prompt_fingerprint(r, RUN, 1) or ev["fingerprint_scoped"] == SG.prompt_fingerprint(r, RUN, 1, keys)
    assert rev2_fresh and SG.check_prompts(r, RUN, 1)["ok"]


def test_w38_q9_record_only_na_counts_as_checked(tmp_path):
    """看图真看过、只报“只记录”缺陷（Q9 na + evidence.model）= 出图检测过；没看成的 na（无 model）/ untested / fail 不过"""
    assert SG._q9_pass({"items": [{"id": "Q9", "status": "na", "evidence": {"model": "Qwen3-VL-8B-Instruct", "record_only": True}}]})
    assert not SG._q9_pass({"items": [{"id": "Q9", "status": "na", "detail": "只记录（没有本地看图结果）", "evidence": {}}]})
    assert not SG._q9_pass({"items": [{"id": "Q9", "status": "untested"}]})
    assert not SG._q9_pass({"items": [{"id": "Q9", "status": "fail", "evidence": {"model": "m"}}]})
    assert not SG._q9_pass({"items": []})
    r = _root(tmp_path)
    _take(r, 1, 1, q9="na")
    d = r / f"data/renders/{RUN}/ep01/S1/takes.json"
    j = json.loads(d.read_text(encoding="utf-8"))
    j["takes"][0]["postflight"]["items"][0]["evidence"] = {"model": "m", "record_only": True}
    d.write_text(json.dumps(j), encoding="utf-8")
    assert SG.shot_frames(r, RUN, 1)[1]["checked"]


def test_w38_video_gate_per_shot(tmp_path):
    """项目方 11-04 04:3x“不等 11 镜齐”：镜 1 首尾帧齐、镜 2 没首帧 → 只编镜 1 的视频作业；night / vidgen 不因整集没齐全挡"""
    r = _root(tmp_path)
    _prompts(r)
    _take(r, 1, 1, last=True)
    specs = {"ep01-S1": {"episode": 1}, "ep01-S2": {"episode": 1}}
    assert SG.video_shots_ok(RUN, 1, r) == [1]
    assert list(SG.filter_video_specs(RUN, specs, r)) == ["ep01-S1"]
    vid = f"data/pipeline/runs/{RUN}/video"
    _w(r / vid / "hosts.json", {"1": "gpu36"})
    assert SG.video_dispatch_ok(vid, r)


def test_w38_vidgen_guard_one_ep_ready_does_not_abort(tmp_path):
    """gpu36 04:4x：控制文件 eps=[1,2]，ep01 镜 1 可进视频、ep02 不行 → vidgen 不退出；一集都不行才抛"""
    r = _root(tmp_path, eps=(1, 2))
    _prompts(r)
    _take(r, 1, 1, last=True)
    vid = r / f"data/pipeline/runs/{RUN}/video"
    _w(vid / "control_gpu36.json", {"eps": [1, 2]})
    SG.vidgen_guard(RUN, vid, r)
    _w(vid / "control_gpu36.json", {"eps": [2]})
    with pytest.raises(SG.SopGateError):
        SG.vidgen_guard(RUN, vid, r)


def test_l185_last_best_effort_does_not_block_video(tmp_path):
    """L-185：首帧已过检 + 尾帧尽力用尽（账本 best_effort）→ 本镜可进视频；尾帧没尽力（还在重出）仍挡"""
    r = _root(tmp_path, shots=(1,))
    _prompts(r, ok=(1,))
    _take(r, 1, 1)                                        # 只有首帧
    assert SG.video_shots_ok(RUN, 1, r) == []
    led = r / f"data/producer/runs/{RUN}/attempts.json"
    _w(led, {"last:ep01-S1": {"final": None, "tries": 2}})
    assert SG.video_shots_ok(RUN, 1, r) == []
    _w(led, {"last:ep01-S1": {"final": "best_effort", "tries": 3}})
    row = SG.shot_frames(r, RUN, 1)[1]
    assert row["last"] and row["last_best_effort"] and SG.video_shots_ok(RUN, 1, r) == [1]


def test_l185_last_exhausted_from_takes_without_ledger(tmp_path):
    """视频机（gpu36）没有 gpu33 的 producer 账本：takes.json 里 ≥3 版尾帧打过分且都没过 = 尽力用尽 → 可进视频；2 版不够"""
    r = _root(tmp_path, shots=(1,))
    _prompts(r, ok=(1,))
    _take(r, 1, 1)
    tj = r / f"data/renders/{RUN}/ep01/S1/takes.json"
    d = json.loads(tj.read_text(encoding="utf-8"))
    d["takes"] += [{"stage": "last", "n": k, "file": "img/e1s1.png", "postflight": {"ok": False}} for k in (1, 2)]
    tj.write_text(json.dumps(d), encoding="utf-8")
    assert SG.video_shots_ok(RUN, 1, r) == []
    d["takes"].append({"stage": "last", "n": 3, "file": "img/e1s1.png", "postflight": {"ok": False}})
    tj.write_text(json.dumps(d), encoding="utf-8")
    assert SG.video_shots_ok(RUN, 1, r) == [1]
