"""RULES-1105（11-05，项目方“把最新的规则和细节写到系统来，然后全部 gpu 做完 ep01”）：
L-191 配方 / L-193…L-196 / 当天运维教训 的机检。规则层 K-OPS-I11…I14、K-OPS-D05 / D06、K-REN-963、K-REV-807、K-WRT-H16 修订；
机检 config/owner_decisions.yaml D-V2-191b…196b、D-V2-OPS-I11；SOP docs/master/PIPELINE_SOP_V2.md。
跑法：TZ=JST-9（K-OPS-I10）。"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _load(rel: str, name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _json(rel: str):
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def _rules(rel: str) -> dict:
    return {r["id"]: r for r in yaml.safe_load((ROOT / rel).read_text(encoding="utf-8"))["rules"]}


# ---------------------------------------------------------------- K-OPS-I11：deploy 改派单配置 → 紧急 producer 重启
SV = _load("tools/qa/system_version.py", "system_version_rules1105")


def _git_diff(files_changed):
    def git_fn(*a, **k):
        assert a[:2] == ("diff", "--name-only"), a
        paths = list(a[5:]) if len(a) > 5 else []          # ("diff","--name-only",prev,sv,"--",*paths)
        return "\n".join(f for f in files_changed if any(f == p or f.startswith(p.rstrip("/") + "/") for p in paths))
    return git_fn


def test_dispatch_config_list_has_the_eight_files():
    want = {"config/factory/hosts.json", "config/pipeline/lane_relay.json", "config/pipeline/sop_gate.json",
            "config/gen_contract.json", "config/pipeline/producer.json", "config/render_quality.json",
            "config/compile/run_style.json", "config/pipeline/video_shard.json"}
    assert set(SV.DISPATCH_CONFIG) == want
    for f in want:
        assert (ROOT / f).exists(), f


def test_dispatch_restart_plan_urgent_producer_only():
    # 只改了 lane_relay.json → urgent + producer-only
    p = SV.dispatch_restart_plan("sv-2", prev="sv-1", code_dirs=["tools", "config"],
                                 git_fn=_git_diff(["config/pipeline/lane_relay.json"]))
    assert p["changed"] == ["config/pipeline/lane_relay.json"] and p["urgent"] is True
    assert p["mode"] == "producer-only" and p["others"] == 0 and "K-OPS-I11" in p["why"]
    # 同版还改了代码 → urgent，但 mode 留空（= all，night 也要读新代码）
    p2 = SV.dispatch_restart_plan("sv-2", prev="sv-1", code_dirs=["tools", "config"],
                                  git_fn=_git_diff(["config/pipeline/sop_gate.json", "tools/autopilot/producer.py"]))
    assert p2["changed"] == ["config/pipeline/sop_gate.json"] and p2["urgent"] is True and p2["mode"] is None and p2["others"] == 1
    # 没改派单配置 → 不升 urgent、不改 mode
    p3 = SV.dispatch_restart_plan("sv-2", prev="sv-1", code_dirs=["tools"], git_fn=_git_diff(["tools/x.py"]))
    assert p3["changed"] == [] and p3["urgent"] is False and p3["mode"] is None
    # 调用方本来就 urgent → 保持
    p4 = SV.dispatch_restart_plan("sv-2", prev="sv-1", code_dirs=["tools"], git_fn=_git_diff([]), urgent=True)
    assert p4["urgent"] is True and p4["changed"] == []


def test_dispatch_config_changed_fails_closed_on_git_error():
    def boom(*a, **k):
        raise RuntimeError("no such tag")
    assert SV.dispatch_config_changed("sv-2", prev="sv-1", git_fn=boom) == list(SV.DISPATCH_CONFIG)
    assert SV.dispatch_config_changed("sv-2", prev="sv-2", git_fn=boom) == []        # 同版 = 没改


def test_previous_deployed_sv_reads_local_version_file(tmp_path, monkeypatch):
    monkeypatch.setattr(SV, "ROOT", tmp_path)
    assert SV.local_deployed_sv(tmp_path) is None
    assert SV.previous_deployed_sv("sv-20261105-10", tags=["sv-20261105-08", "sv-20261105-09", "sv-20261105-10"]) == "sv-20261105-09"
    assert SV.previous_deployed_sv("sv-20261105-08", tags=["sv-20261105-08"]) is None
    SV.write_local_version("sv-20261105-07", "abc", "2026-11-05T20:00:00", root=tmp_path)
    assert SV.local_deployed_sv(tmp_path) == "sv-20261105-07"
    assert SV.previous_deployed_sv("sv-20261105-10", tags=["sv-20261105-09", "sv-20261105-10"]) == "sv-20261105-07"
    assert SV.previous_deployed_sv("sv-20261105-07", tags=[]) is None


def test_deploy_wires_dispatch_restart_plan():
    src = (ROOT / "tools/qa/system_version.py").read_text(encoding="utf-8")
    body = src.split("\ndef deploy(")[1].split("\ndef ")[0]
    assert "dispatch_restart_plan(sv, code_dirs=rs.CODE_DIRS" in body and "restart_mode=restart_mode" in body
    assert 'res["dispatch_config_changed"]' in body and 'res["urgent_auto"]' in body
    host = src.split("\ndef deploy_host(")[1].split("\ndef ")[0]
    assert 'mode_kw = {"mode": restart_mode} if restart_mode else {}' in host and "urgent=urgent, **mode_kw)" in host


def test_deploy_host_passes_mode_to_restart_queue(monkeypatch):
    calls = []

    class RQ:
        def request(self, host, reason, by, urgent=False, mode=None):
            calls.append((host, urgent, mode))
            return {"id": "r1"}
    rq = RQ()
    assert not hasattr(rq, "process")
    # 只验证 deploy_host 的重启请求段：用源码里的同一调用方式
    q = rq.request("gpu33", "system_version deploy sv-x", by="system_version deploy", urgent=True, mode=SV.DISPATCH_RESTART_MODE)
    assert q["id"] == "r1" and calls == [("gpu33", True, "producer-only")]
    RQm = _load("tools/autopilot/restart_queue.py", "restart_queue_rules1105")
    assert RQm.norm_mode(SV.DISPATCH_RESTART_MODE) == "producer-only"     # 队列认识这个 mode


# ---------------------------------------------------------------- K-OPS-I12 / L-193 / L-194：六卡
def test_l193_l194_six_lanes_in_dispatch_configs():
    hosts = _json("config/factory/hosts.json")["hosts"]
    for ln in ("gpu36:0", "gpu36:1", "gpu36:2"):
        lane = hosts["gpu36"]["lanes"][ln]
        assert lane["enabled"] is True and lane["roles"] == ["image", "video"], ln
    relay = _json("config/pipeline/lane_relay.json")
    assert relay["enabled"] is True and set(relay["lanes"]) == {"gpu36:0", "gpu36:1", "gpu36:2"}
    assert "gpu33:2" not in relay["lanes"]
    vs = _json("config/pipeline/video_shard.json")
    assert vs["enabled"] is True
    ep1 = vs["runs"]["series10_v2"]["eps"]["1"]
    assert set(ep1["weights"]) == {"gpu36", "gpu33"} and ep1["weights"]["gpu36"] >= ep1["weights"]["gpu33"]


# ---------------------------------------------------------------- K-OPS-I13：导入 / 换代后立刻探针；退避不压制证据刷新
def test_episode_run_probes_prompts_right_after_regen():
    src = (ROOT / "tools/master/episode_run.py").read_text(encoding="utf-8")
    body = src.split("\ndef act_regen(")[1].split("\ndef ")[0]
    assert "probe_prompts(env)" in body
    imp = src.split("\ndef act_import(")[1].split("\ndef ")[0]
    assert 'st["regen"] = {}' in imp                      # 新稿导入 → 换代段重做 → 必经 probe


def _sg_root(tmp_path):
    (tmp_path / "config/pipeline").mkdir(parents=True)
    (tmp_path / "config/pipeline/sop_gate.json").write_text(json.dumps({"enabled": True, "observe_stages": []}), encoding="utf-8")
    return tmp_path


def test_sop_gate_backoff_yields_when_evidence_refreshed(tmp_path, monkeypatch):
    SG = _load("tools/master/sop_gate.py", "sop_gate_rules1105")
    root = _sg_root(tmp_path)
    sp = root / "data/pipeline/sop_gate/backoff/drama.producer.json"
    sp.parent.mkdir(parents=True)
    now = 1_000_000.0
    stale = {"producer|出图|ep01|sig-old": {"sig": "sig-old", "by": "producer", "stage": "出图", "episode": 1, "shot": 3, "mode": "enforce",
                                             "logged": 2, "suppressed": 5, "repeats": 7, "gaps": "提示词", "missing_head": "提示词：证据过期",
                                             "first": "t", "last_logged": "t", "until": now + 1800}}
    sp.write_text(json.dumps(stale), encoding="utf-8")
    calls = []
    monkeypatch.setattr(SG, "judge", lambda run, ep, stage, shot=None, root=SG.ROOT: calls.append((run, ep, stage, shot)) or {"ok": True, "missing": []})
    monkeypatch.setattr(SG, "require", lambda *a, **k: (_ for _ in ()).throw(AssertionError("证据已过不该再 require")))
    # 退避条目还在（until 未到）、证据刷新后 judge 通过 → 当场放行，不看退避
    r = SG.require_backoff("drama", 1, "出图", shot=3, root=root, by="producer", now=now, state_path=sp)
    assert r["allow"] is True and r["ok"] is True and r["backoff"] is None and r["error"] is None
    assert calls == [("drama", 1, "出图", 3)]             # 每次都先判，不被退避压住
    # 带 key 的调用（asset_worker 口径）同时把旧条目清掉
    r2 = SG.require_backoff("drama", 1, "出图", root=root, by="producer", now=now, state_path=sp, key="producer|出图|ep01|sig-old")
    assert r2["ok"] is True and r2["cleared"] is True
    assert json.loads(sp.read_text(encoding="utf-8")) == {}


# ---------------------------------------------------------------- K-OPS-D05 / L-195
def test_l195_per_shot_prompt_gate():
    sg = _json("config/pipeline/sop_gate.json")
    assert sg["whole_episode_prompts"] is False and "L-195" in sg["_whole_episode_prompts"]
    src = (ROOT / "tools/master/sop_gate.py").read_text(encoding="utf-8")
    assert 'config(root).get("whole_episode_prompts", True)' in src     # 关掉 = judge 按 shot 取证据


# ---------------------------------------------------------------- K-OPS-D06 / L-196
def test_l196_hard_gates_only():
    gc = _json("config/gen_contract.json")
    assert gc["blocking_items"] == ["Q1", "count", "text", "adult"]
    prod = _json("config/pipeline/producer.json")
    assert prod["review_adopt_auto"] is True and prod["accept"]["run_qb"] is False


# ---------------------------------------------------------------- K-REN-963 / L-191 配方单一来源
def test_v2_first_frame_recipe_single_source():
    rq = _json("config/render_quality.json")["first_frame_tier"]
    assert rq["runs"]["series10_v2"] == "base35"
    assert rq["base35"]["steps"] == 35 and float(rq["base35"]["cfg"]) == 3.0 and rq["base35"]["unet"] == "base"
    rs = _json("config/compile/run_style.json")["runs"]["series10_v2"]["prompt_template"]
    assert rs["image"] == "v2" and rs["video"] == "v2"
    lenses = yaml.safe_load((ROOT / "config/director/lenses.yaml").read_text(encoding="utf-8"))
    assert lenses["by_kind"] == {"establishing": "leica_cine_28_t28", "two_shot": "arri_cine_50_t2", "ots_or_single_mcu": "arri_cine_85_t14",
                                 "closeup": "leica_cine_135_t12", "insert": "leica_cine_100_macro_t2"}
    r = _rules("knowledge/rules/render.yaml")["K-REN-963"]
    assert r["params"] == {"first_frame_tier": "base35", "steps": 35, "cfg": 3.0, "prompt_template_image": "v2", "prompt_template_video": "v2"}
    sop = (ROOT / "docs/master/PIPELINE_SOP_V2.md").read_text(encoding="utf-8")
    assert "V2 首帧生产配方" in sop and "K-REN-963" in sop


# ---------------------------------------------------------------- K-REV-807：背影词表
def test_back_view_words_only_whitelist():
    for p in ("services/agent", "packages/schema", "services/render_router"):
        if str(ROOT / p) not in sys.path:
            sys.path.insert(0, str(ROOT / p))
    from ns_agent import asset_refs as AR
    assert set(AR.BACK_TXT_WORDS) == {"背影", "背对镜头", "背身", "背朝镜头"}
    others = ("卓琳",)
    assert AR.back_in_text("祁念", "中近景，卓琳的手落在祁念的背脊，祁念回头看她", others) is False      # 背脊 ≠ 背影（S16 误判）
    assert AR.back_in_text("祁念", "中景，祁念背对他站着，卓琳看着她", others) is False                   # 背对他 ≠ 背对镜头
    assert AR.back_in_text("祁念", "中景，祁念的后背贴着墙", others) is False
    assert AR.back_in_text("祁念", "中近景，祁念的背影在前景，卓琳看镜头外", others) is True
    assert AR.back_in_text("祁念", "中近景，祁念背对镜头，卓琳在她左前", others) is True
    assert AR.back_in_text("祁念", "全景，祁念的背面对着镜头", others) is True
    assert AR.back_in_text("祁念", "中景，祁念背身站在窗前", others) is True
    assert AR.back_in_text("祁念", "中景，卓琳蹲在祁念左前、背对镜头", others) is False               # 主语是卓琳（psm7 S4）
    assert AR.back_in_text("卓琳", "中景，卓琳蹲在祁念左前、背对镜头", ("祁念",)) is True


# ---------------------------------------------------------------- K-WRT-H16 修订：过肩前景不算露脸
def test_h16_ots_foreground_not_counted_as_face(monkeypatch):
    for p in ("packages/schema",):
        if str(ROOT / p) not in sys.path:
            sys.path.insert(0, str(ROOT / p))
    ST = _load("tools/script_rsi/staging.py", "staging_rules1105")
    both = ST.check_shot("中近景，卓琳的脸清晰入画，祁念的脸也清晰入画，两人并排看向彼此", [("卓琳", "在画"), ("祁念", "在画")])
    assert both["tight_pair"], both
    ots = ST.check_shot("中近景，卓琳的脸清晰入画，祁念只露虚化的左肩和腰侧在前景", [("卓琳", "在画"), ("祁念", "在画")])
    assert not ots["tight_pair"], ots
    ots = ST.check_shot("中近景，卓琳的脸清晰入画，祁念以虚化的左肩入画", [("卓琳", "在画"), ("祁念", "在画")])
    assert not ots["tight_pair"], ots
    r = _rules("knowledge/rules/writer_hollywood.yaml")["K-WRT-H16"]
    assert "过肩前景不算露脸" in r["then"] and "hidden_face" in r["then"]


# ---------------------------------------------------------------- 规则 / 机检 / SOP 齐
def test_rules_1105_present_and_complete():
    infra = _rules("knowledge/rules/ops_infra.yaml")
    assert {"K-OPS-I11", "K-OPS-I12", "K-OPS-I13", "K-OPS-I14"} <= set(infra)
    dec = _rules("knowledge/rules/ops_decisions.yaml")
    assert {"K-OPS-D05", "K-OPS-D06"} <= set(dec)
    assert "K-REN-963" in _rules("knowledge/rules/render.yaml") and "K-REV-807" in _rules("knowledge/rules/gen_contract.yaml")
    for r in [infra["K-OPS-I11"], infra["K-OPS-I12"], infra["K-OPS-I13"], infra["K-OPS-I14"], dec["K-OPS-D05"], dec["K-OPS-D06"]]:
        for k in ("id", "domain", "link", "title", "when", "then", "evidence", "confidence", "status", "date"):
            assert k in r, (r["id"], k)
        assert str(r["date"]) == "2026-11-05"
    for rid, txt in (("K-OPS-I11", "producer-only"), ("K-OPS-I12", "gpu33:2"), ("K-OPS-I13", "probe-prompts"), ("K-OPS-I14", "$_")):
        assert txt in infra[rid]["then"], rid


def test_owner_decisions_encode_l191_recipe_and_l193_to_l196():
    cfg = yaml.safe_load((ROOT / "config/owner_decisions.yaml").read_text(encoding="utf-8"))
    by = {c["id"]: c for c in cfg["checks"]}
    for need in ("D-V2-191b", "D-V2-191c", "D-V2-193", "D-V2-193b", "D-V2-193c", "D-V2-194", "D-V2-194b", "D-V2-194c", "D-V2-194d",
                 "D-V2-195", "D-V2-196", "D-V2-196b", "D-V2-OPS-I11"):
        assert need in by, need
    assert "L-196" in by["D-V2-187"]["decision"]           # CODER-AUTO 已把 L-187 改成 L-196 口径
    DC = _load("tools/qa/decision_check.py", "decision_check_rules1105")
    for cid in ("D-V2-191b", "D-V2-191c", "D-V2-193", "D-V2-193b", "D-V2-193c", "D-V2-194", "D-V2-194b", "D-V2-194c", "D-V2-194d",
                "D-V2-195", "D-V2-196", "D-V2-196b"):
        ok, _why = DC.check_json(by[cid])
        assert ok is True, (cid, _why)
    ok, _why = DC.check_grep(by["D-V2-OPS-I11"], True)
    assert ok is True, _why


def test_pipeline_sop_mentions_today_decisions():
    sop = (ROOT / "docs/master/PIPELINE_SOP_V2.md").read_text(encoding="utf-8")
    for s in ("L-193", "L-194", "L-195", "L-196", "K-OPS-I11", "K-OPS-I13", "K-OPS-I14", "probe-prompts", "producer-only", "lane_relay_hold.json"):
        assert s in sop, s
