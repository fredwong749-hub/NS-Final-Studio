"""MERGE-OPS-O（总调度 11-03，L-137：V2 并回 V1 运维）：
导入闸门 v1_leak 0 命中 + 触发词只取本剧登记（ISS-1103-024206-9974）；派单 / 改分区按剧（carryover 第 14 项）；
归因按剧读导入稿（第 8 项）；S2 豁免按剧 + 集（第 12 项）。"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / "tools", ROOT / "tools/netfix", ROOT / "tools/factory", ROOT / "tools/pipeline"):
    sys.path.insert(0, str(p))

import import_script as IS  # noqa: E402
from ns_schema.script import LoraTrigger, ScriptImport  # noqa: E402

V2 = "series10_v2"


def _result(triggers=("nprng2", "hh12clear"), shot_trig=("nprng2",), text="女主走进影棚"):
    """以 V2 现行导入稿为模板（只取第 1 集第 1 镜），换上测试用的触发词 / 镜头文字"""
    si = ScriptImport.model_validate_json((ROOT / f"data/import/runs/{V2}/script_v2.json").read_text(encoding="utf-8"))
    g = si.globals
    g.lora_triggers = [LoraTrigger(trigger=t, kind="image", description="道具") for t in triggers]
    g.scene_library, g.character_registry, g.character_locks, g.daily_outfit = [], [], [], ""
    g.motion_suffix = g.image_suffix = g.base_negative = ""
    ep = si.episodes[0]
    ep.shots = ep.shots[:1]
    sh = ep.shots[0]
    sh.img_triggers, sh.motion_triggers = list(shot_trig), []
    si.episodes = [ep]
    si.warnings, si.sources = [], []
    for k, v in sh.model_dump().items():           # 镜头里所有文字字段换成测试文字，避免模板里的内容影响断言
        if isinstance(v, str):
            setattr(sh, k, "")
    sh.img_prompt = text
    return si


# ---------------------------------------------------------------- ISS-1103-024206-9974
def test_scope_triggers_keeps_only_registered():
    r = _result()
    w = IS.scope_triggers(r, {"hh12clear"})
    assert [t.trigger for t in r.globals.lora_triggers] == ["hh12clear"] and w
    for ep in r.episodes:
        for s in ep.shots:
            assert "nprng2" not in s.img_triggers


def test_v2_registers_no_v1_triggers():
    """V2 没在 runs.json / 资产清单登记任何触发词 → V1 道具触发词一个都不留"""
    got = IS.run_triggers(V2)
    assert not got & {"nprng2", "lbrng9", "lbrng9_beads", "hh12clear", "hh12patent", "ptxcorset", "ptxharness", "ptxtrench", "lnwan01"}


def test_v1_gate_blocks_v1_content_and_passes_clean():
    bad = _result(text="林晚走进 sk_office_night")
    bad.globals.daily_outfit = "林晚 lnwan01"
    assert "旧剧内容" in IS.v1_gate(bad, V2)
    clean = _result(triggers=(), shot_trig=())
    assert IS.v1_gate(clean, V2) == ""
    assert IS.v1_gate(bad, "series10_v1") == ""                  # V1 自己不查


def test_import_main_refuses_on_v1_hit():
    src = (ROOT / "tools/import_script.py").read_text(encoding="utf-8")
    body = src.split("def main():")[1]
    assert body.index("scope_triggers(result, run_triggers(run))") < body.index("v1_gate(result, run)") < body.index("tmp.write_text")


# ---------------------------------------------------------------- 第 14 项：派单 / 改分区按剧
@pytest.fixture
def D(tmp_path, monkeypatch):
    import dispatch as D_
    runs = {"primary": V2, "legacy_unprefixed_run": "series10_v1",
            "runs": {"series10_v1": {"status": "archived"}, V2: {"status": "preparing"}, "series10_s2": {"status": "paused"}}}
    (tmp_path / "config/pipeline").mkdir(parents=True)
    (tmp_path / "config/pipeline/runs.json").write_text(json.dumps(runs), encoding="utf-8")
    part = {"images": {"gpu33": [1, 3], "gpu36": [2, 4], "laptop": []}, "video": {"gpu33": [1, 3], "gpu36": [2, 4]},
            "lanes": {"gpu33": ["gpu33:0"], "gpu36": ["gpu36:0"], "laptop": ["laptop:0"]}}
    monkeypatch.setattr(D_, "RUNS", tmp_path / "config/pipeline/runs.json")
    monkeypatch.setattr(D_, "ROOT", tmp_path)
    monkeypatch.setattr(D_, "OVERRIDE_STATE", tmp_path / "_none_state.json")
    monkeypatch.setattr(D_, "OVERRIDE", tmp_path / "_none_ov.json")
    monkeypatch.setattr(D_, "partition", lambda p=None: json.loads(json.dumps(part)))
    D_._runs_json = runs
    return D_


def test_v2_primary_is_not_excluded(D):
    assert D.legacy_run_id() == "series10_v1"
    assert D.paused_runs() == ["series10_s2", V2]                # V1（legacy 格）不进 runs/<run>/control.json
    D._runs_json["runs"][V2]["status"] = "producing"
    D.RUNS.write_text(json.dumps(D._runs_json), encoding="utf-8")
    assert [r for r, _p in D.extra_runs()] == [V2]               # 以前按“不是 primary”排除 → V2 没有 control


def test_v2_control_prepared_before_dispatch(D, tmp_path):
    f = D.pause_run_control(V2, host="gpu33")
    p = tmp_path / "data/producer/runs" / V2 / "control.json"
    c = json.loads(p.read_text(encoding="utf-8"))
    assert f and c["paused"] is True and c["reason_kind"] == "owner" and c["hold_lanes"] and c["only"] == [D.NONE]
    assert D.pause_run_control("nope_run") is None                            # 不给 host：没有文件不写（旧行为）


def test_laptop_run_control_released_when_producing(D, tmp_path):
    D.laptop_run_controls({}, write=True)
    p = tmp_path / "data/producer/runs" / V2 / "control.json"
    assert json.loads(p.read_text(encoding="utf-8"))["paused"] is True
    D._runs_json["runs"][V2]["status"] = "producing"
    D.RUNS.write_text(json.dumps(D._runs_json), encoding="utf-8")
    D.laptop_run_controls({}, write=True)
    c = json.loads(p.read_text(encoding="utf-8"))
    assert c["paused"] is False and c["paused_by"] is None
    c.update(paused=True, paused_by="项目方")                                  # 别人的暂停不动
    p.write_text(json.dumps(c), encoding="utf-8")
    D.laptop_run_controls({}, write=True)
    assert json.loads(p.read_text(encoding="utf-8"))["paused_by"] == "项目方"


def test_repart_counts_each_run_renders(tmp_path):
    import repart as RP
    (tmp_path / "config/pipeline").mkdir(parents=True)
    (tmp_path / "config/pipeline/runs.json").write_text(json.dumps({
        "primary": V2, "legacy_unprefixed_run": "series10_v1",
        "runs": {"series10_v1": {"status": "archived"}, V2: {"status": "producing"}}}), encoding="utf-8")
    (tmp_path / "tools/autopilot").mkdir(parents=True)
    (tmp_path / "tools/autopilot/runs.py").write_bytes((ROOT / "tools/autopilot/runs.py").read_bytes())
    rr = RP.renders_rels(ROOT)
    assert ("series10_v1", "data/renders") not in rr and all(rel.endswith(r) for r, rel in rr)   # V1 已归档不挡；其余按剧号目录
    assert "RD = sys.argv[3]" in RP.TAKES_PY and 'os.path.join(R, RD, "ep%02d" % e)' in RP.TAKES_PY
    old = {"images": {"gpu33": [1], "gpu36": [2]}, "video": {"gpu33": [1], "gpu36": [2]}}
    bad = {"images": {"gpu33": [1, 2], "gpu36": []}, "video": {"gpu33": [1, 2], "gpu36": []}}
    seen = []

    def run(h, cmd, **k):
        import types
        seen.append(cmd.split()[-1])
        rel = cmd.split()[-1]
        have = {"gpu33": [1], "gpu36": [2]} if rel.endswith(V2) else {"gpu33": [1, 2], "gpu36": [2]}   # 只有 V2 缺版本
        return types.SimpleNamespace(stdout=json.dumps(have[h]))
    probs = RP.check(old, bad, run=run, renders=[("series10_s2", "data/renders/series10_s2"), (V2, f"data/renders/{V2}")])
    assert probs and all(V2 in x for x in probs)                 # 只有 V2 的版本会被整集重做 → 拒绝，并标出是哪部剧
    assert f"data/renders/{V2}" in seen


# ---------------------------------------------------------------- 第 8 / 12 项
def test_attribute_bug_reads_run_import():
    import attribute_bug as AB
    assert AB.script_for(V2).as_posix().endswith(f"data/import/runs/{V2}/script_v2.json")
    assert AB.script_for("series10_v1").as_posix().endswith("data/import/script_v2.json")
    assert '"data" / "import" / "script_v2.json"' not in (ROOT / "tools/pipeline/attribute_bug.py").read_text(encoding="utf-8")


def test_s2_waiver_scoped_by_run():
    from ns_agent.state_timeline import waived
    w = json.loads((ROOT / "config/s2_waivers.json").read_text(encoding="utf-8"))["waivers"]
    assert all(x.get("run") for x in w)
    assert waived(ROOT, 2, "plate", run=V2) is None              # V2 ep02 不误用 V1 的豁免
    assert waived(ROOT, 2, "plate", run="series10_v1")


# ---------------------------------------------------------------- V2 画风用语放行（项目方 04:3x / L-145），V1 参数标记照拦
def _style_root(tmp_path, bible_body: str):
    import shutil
    (tmp_path / "config/compile").mkdir(parents=True)
    (tmp_path / "config/pipeline").mkdir(parents=True)
    (tmp_path / "tools/autopilot").mkdir(parents=True)
    shutil.copy(ROOT / "tools/autopilot/runs.py", tmp_path / "tools/autopilot/runs.py")
    (tmp_path / "config/pipeline/runs.json").write_text(json.dumps({"primary": V2, "legacy_unprefixed_run": "series10_v1",
                                                                    "runs": {V2: {"status": "preparing"}}}), encoding="utf-8")
    (tmp_path / "config/compile/run_style.json").write_text(json.dumps({
        "v1_style_phrases": ["徕卡", "Leica", "leica", "S★", "R0", "暖调通透"],
        "runs": {V2: {"bible": "config/compile/bible_v2.toml"}}}, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "config/compile/bible_v2.toml").write_text(bible_body, encoding="utf-8")
    shutil.copy(ROOT / "config/v1_guard.json", tmp_path / "config/v1_guard.json")
    return tmp_path


def _leak():
    import importlib.util
    sp = importlib.util.spec_from_file_location("v1_leak_t", ROOT / "tools/script_rsi/v1_leak.py")
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


def test_v2_bible_style_words_pass_v1_markers_still_hit(tmp_path):
    L = _leak()
    root = _style_root(tmp_path, '# 注释里的 R0 不算\n[look]\nstyle = "Leica 镜头风格，徕卡级锐利，ARRI 摄影机，Kodak 胶卷感"\n')
    v = L.vocab(root, current=V2)
    assert not {"徕卡", "Leica", "leica"} & set(v["style"])                   # 本剧 bible 正文写了 → 放行（大小写不敏感）
    assert {"S★", "R0", "暖调通透"} <= set(v["style"])                        # V1 参数标记照拦；注释不算放行依据
    hits = {h["word"] for h in L.scan("徕卡级锐利，ARRI 摄影机，Kodak 胶卷感；徕卡 S★：50mm", v)}
    assert hits == {"S★"}


def test_without_bible_style_words_still_blocked(tmp_path):
    L = _leak()
    root = _style_root(tmp_path, '# Leica 只写在注释里\n[look]\nno_text = "无字幕"\n')
    assert {"徕卡", "Leica"} <= set(L.vocab(root, current=V2)["style"])


def test_ep01_reimport_passes_gate():
    """第 1 集现行成稿（TIMELINE-O 03:00 重生集头后）按剧收口后过 v1_leak 闸门"""
    r = IS.import_script(ROOT / f"data/pipeline/runs/{V2}/P4_ep01.final.md", None)
    IS.scope_globals(r, *IS.run_registered(V2))
    IS.scope_triggers(r, IS.run_triggers(V2))
    assert IS.v1_gate(r, V2) == "" and not r.globals.lora_triggers


# ---------------------------------------------------------------- ISS-1103-044539-f93d：重导时底稿旧全局头不回流
def test_single_source_globals_no_backflow():
    base = _result(triggers=("nprng2",), shot_trig=())
    base.globals.motion_suffix, base.globals.image_suffix, base.globals.base_negative = "徕卡 S★ 暖调通透", "徕卡 R0", "旧负面"
    new = _result(triggers=(), shot_trig=())
    g = IS.merge_globals(base.globals, new.globals, {1}, single_source=True)
    assert (g.motion_suffix, g.image_suffix, g.base_negative) == ("", "", "") and not g.lora_triggers
    g_v1 = IS.merge_globals(base.globals, new.globals, {1})                  # V1 旧行为不变：新稿空 → 保留底稿
    assert g_v1.motion_suffix == "徕卡 S★ 暖调通透"


def test_ep01_reimport_with_merge_base_passes_gate(tmp_path):
    """producer import_staged_run 的真实路径：以现行 V2 导入稿为 --merge-base 重导第 1 集 → 过 v1_gate"""
    import shutil
    b = tmp_path / "base.json"
    shutil.copy(ROOT / f"data/import/runs/{V2}/script_v2.json", b)
    r = IS.merge_into(b, IS.import_script(ROOT / f"data/pipeline/runs/{V2}/P4_ep01.final.md", None), single_source=True)
    IS.scope_globals(r, *IS.run_registered(V2))
    IS.scope_triggers(r, IS.run_triggers(V2))
    assert IS.v1_gate(r, V2) == ""
    src = (ROOT / "tools/import_script.py").read_text(encoding="utf-8")
    assert "merge_into(args.merge_base, result, single_source=bool(run))" in src


def test_producer_logs_import_refusal_from_stdout():
    src = (ROOT / "tools/autopilot/producer.py").read_text(encoding="utf-8").split("def import_staged_run")[1].split("def imported_episodes")[0]
    assert 'r.stdout' in src and 'startswith("拒绝导入")' in src and "detail=detail" in src


def test_import_failed_retries_only_when_importer_changed(tmp_path):
    import importlib.util
    sp = importlib.util.spec_from_file_location("af_t", ROOT / "tools/script_rsi/autoflow.py")
    AF = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(AF)
    rd = tmp_path / V2
    rd.mkdir()
    st = {"run": V2, "episode": 1, "verdict": "import_failed"}
    (rd / "autoflow_ep01.json").write_text(json.dumps(st), encoding="utf-8")
    AF.next_episodes = lambda run_dir: []
    assert AF.pending_done(rd) == [1]                                         # 没记指纹（老状态）→ 重试一次
    st["import_fail_sig"] = AF.import_retry_sig(V2)
    (rd / "autoflow_ep01.json").write_text(json.dumps(st), encoding="utf-8")
    assert AF.pending_done(rd) == []                                          # 导入器没变 → 不空转
    assert b"\x00" not in (ROOT / "tools/script_rsi/autoflow.py").read_bytes()


# ---------------------------------------------------------------- L-188：非 V1 剧重导，新稿全剧场景表盖住旧场景定义
def test_single_source_scene_table_new_overrides_old():
    from ns_schema.script import SceneEntry
    base = _result(triggers=(), shot_trig=())
    base.globals.scene_library = [SceneEntry(scene_id="sk_a", name="A", light="环形灯正面高亮", fixtures="椅", defined_in=[None, 1])]
    new = _result(triggers=(), shot_trig=())
    new.globals.scene_library = [SceneEntry(scene_id="sk_a", name="A", light="顶灯上侧 45° 主光", fixtures="", defined_in=[None, 1])]
    g = IS.merge_globals(base.globals, new.globals, {1}, single_source=True)
    e = g.scene_library[0]
    assert e.light == "顶灯上侧 45° 主光" and e.fixtures == "椅"            # 新稿覆盖，新稿空格沿用
    assert any("场景表更新" in w for w in IS.registry_drift(base.globals, new.globals, {1}, single_source=True))
    g_v1 = IS.merge_globals(base.globals, new.globals, {1})                  # V1 / 默认口径不变：先登记为准
    assert g_v1.scene_library[0].light == "环形灯正面高亮"
