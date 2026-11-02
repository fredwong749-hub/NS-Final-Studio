"""IMGMASTER 分段编译（L-118，docs/imgmaster/DESIGN.md）：插件登记表失败关闭、槽位优先级、开关默认关、ep01 试编检查。纯 CPU，不出图。"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/agent", "packages/schema", "services/render_router", "tools/prompt_v2", "tools/pipeline", "tools/autopilot", "tools/imgmaster"):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))

from ns_agent import asset_refs as AR  # noqa: E402
from ns_agent import frame_job as FJ  # noqa: E402


def _yaml(tmp_path, rows):
    import yaml
    f = tmp_path / "plugins.yaml"
    f.write_text(yaml.safe_dump({"plugins": rows}, allow_unicode=True), encoding="utf-8")
    return f


RULES = {"K-OK": {"check": ["tests/x.py"]}, "K-NOCHECK": {"check": None}}
IMPL = {"a": lambda t, s, c: t}


def test_switch_default_off():
    assert FJ.imgmaster_enabled() is False


def test_real_registry_valid_and_matches_impl():
    rows = FJ.load_plugins()
    assert {r["id"] for r in rows if r["enabled"]} == set(FJ.PLUGIN_IMPL)
    assert all(r["segment"] in FJ.SEGMENTS for r in rows)


def test_registry_fails_closed(tmp_path):
    ok = {"id": "a", "segment": "action", "rule_id": "K-OK", "order": 1, "enabled": True}
    assert FJ.load_plugins(_yaml(tmp_path, [ok]), RULES, IMPL)
    for bad, why in (({**ok, "segment": "tail"}, "segment"), ({**ok, "rule_id": "K-NONE"}, "不存在"),
                     ({**ok, "rule_id": "K-NOCHECK"}, "check")):
        with pytest.raises(FJ.CompileError, match=why):
            FJ.load_plugins(_yaml(tmp_path, [bad]), RULES, IMPL)
    with pytest.raises(FJ.CompileError, match="没有 @plugin"):
        FJ.load_plugins(_yaml(tmp_path, [{**ok, "id": "zz"}]), RULES, IMPL)
    with pytest.raises(FJ.CompileError, match="没登记"):          # 代码里有、表里没有 = 未登记插件
        FJ.load_plugins(_yaml(tmp_path, []), RULES, IMPL)


def test_continuity_missing_or_bad_schema_refused(tmp_path):
    with pytest.raises(FJ.CompileError, match="不存在"):
        FJ.load_continuity(tmp_path / "nope.json")
    f = tmp_path / "c.json"
    f.write_text(json.dumps({"schema": "other"}), encoding="utf-8")
    with pytest.raises(FJ.CompileError, match="schema"):
        FJ.load_continuity(f)
    with pytest.raises(FJ.CompileError, match="缺"):
        FJ.scene_lock({"scenes": {"s": {"fixtures": ["a"], "key_light": "x"}}}, "s")


def test_side_conflict_same_axis_only():
    ref = FJ._sides("暖黄台灯从画面右后方逆光。走廊在画面右侧")
    assert FJ._side_conflicts("走廊方向在画面左侧", ref)
    assert not FJ._side_conflicts("台灯在后方", ref)            # 深度轴一致
    assert not FJ._side_conflicts("走廊暗处在画面右侧", ref)
    assert FJ._side_conflicts("视线朝画面左侧的走廊方向", ref)


def _ref(role, ch, f, prio, face=False, look="A"):
    return AR.Ref(role, ch, f, f, prio, has_face=face, look_id=look)


def _sr(refs, chars=("lin_wan",)):
    return AR.ShotRefs("t", "series10_v1", "近景", None, [], chars[0], [{"character": c, "name": c, "presence": "在画"} for c in chars],
                       refs, [], [], "sk")


def test_scene_slot_not_displaced_and_priority(monkeypatch):
    monkeypatch.setattr(AR, "make_board", lambda proj, tiles: "board_" + "+".join(f for f, _ in tiles))
    monkeypatch.setattr(AR, "_apply_sheet_gaps", lambda *a, **k: None)
    monkeypatch.setattr(AR, "_line", lambda *a, **k: "")
    refs = [_ref("face", "a", "fa", 1, True), _ref("face", "b", "fb", 2, True), _ref("sheet", "a", "sa", 10, True),
            _ref("item", "a", "ia", 12), _ref("scene", None, "SC", 30)]
    old = AR.plan_slots(_sr(refs, ("a", "b")))
    assert "SC" not in [s.file for s in old.slots]               # 旧：场景第一个被丢
    new = AR.plan_slots_v2(_sr(refs, ("a", "b")))
    assert [s.kind for s in new.slots] == ["face", "face", "scene"]
    assert {d["file"] for d in new.dropped} == {"sa", "ia"}      # 脸 > 场景 > 造型：造型走文字
    one = AR.plan_slots_v2(_sr([r for r in refs if r.character != "b"], ("a",)))
    assert [s.kind for s in one.slots][:2] == ["face", "scene"] and len(one.slots) == 3


def test_scene_look_refs_same_board_across_shots():
    a = _sr([_ref("face", "a", "fa", 1, True), _ref("sheet", "a", "sheet_half", 10, True), _ref("item", "a", "coat", 12)])
    b = _sr([_ref("face", "a", "fa", 1, True), _ref("sheet", "a", "sheet_full", 10, True), _ref("item", "a", "nails", 13)])
    c = _sr([_ref("face", "a", "fa", 1, True), _ref("sheet", "a", "sheet_half", 10, True)])
    for i, x in enumerate((a, b, c)):
        x.shot_id = f"s{i}"
    looks = AR.scene_look_refs([a, b, c])
    assert [r.file for r in looks["a"]] == ["sheet_half", "coat", "nails"]      # 设定图取最常用的一种；单品取并集


@pytest.fixture(scope="module")
def trial(tmp_path_factory):
    pytest.importorskip("pydantic")
    try:
        import trial_compile as T
        return T, T.run(1, "series10_v1", tmp_path_factory.mktemp("imgm"))
    except (FileNotFoundError, StopIteration, KeyError, ModuleNotFoundError) as e:
        pytest.skip(f"没有 ep01 数据：{e}")


def test_ep01_trial_checks(trial):
    T, res = trial
    cks = {c["id"]: c for c in T.checks(res)}
    assert len(res["rows"]) == 10
    for k in ("C1", "C2", "C3", "C4", "C5a"):
        assert cks[k]["ok"], (k, cks[k]["detail"])
    assert not FJ.imgmaster_enabled()


def test_ep01_trace_has_segments_and_rules(trial):
    _T, res = trial
    tr = res["rows"][0]["new"]["trace"]
    assert [s["name"] for s in tr["segments"]] == list(FJ.SEGMENTS)
    assert tr["continuity"]["sha256"] and tr["plugins_sha"] and tr["preamble"]["slots"]
    assert all(s["sources"] for s in tr["segments"])


def test_write_compile_trace(tmp_path):
    t = {"shot": "ep01-S1", "prompt_sha": "abc", "x": 1}
    r = FJ.write_compile_trace(t, tmp_path)
    assert Path(r["file"]).is_file() and len(r["sha"]) == 64


def test_eyeline_note_fills_missing_gaze():
    """D-SCR-07：正文没写视线 → 补固定落点句；写了（或背对）→ 不补；局部特写不补"""
    shot = {"img_prompt": "中景，林晚坐在桌前，双手放在键盘上", "cast": [{"name": "林晚", "presence": "在画"}], "extras": [
        {"label": "分拍1", "text": "视线=屏幕上的邮件｜动作=敲键盘"}]}
    sr = type("S", (), {"characters": [{"name": "林晚", "character": "lin_wan", "presence": "在画"}]})()
    note = FJ.eyeline_note(shot, sr, shot["img_prompt"])
    assert "林晚的视线落在屏幕上的邮件上" in note
    assert FJ.eyeline_note(shot, sr, "中景，林晚看着屏幕") == ""
    part = dict(shot, img_prompt="特写，手指悬在键盘上方")
    assert FJ.eyeline_note(part, sr, part["img_prompt"]) == ""


def test_all_plugins_enabled_no_legacy():
    rows = FJ.load_plugins()
    assert all(r["enabled"] for r in rows)
    assert {"eyeline", "garment_detail"} <= set(FJ.PLUGIN_IMPL)


def test_trace_marks_look_refs_via_text(trial):
    _T, res = trial
    two = next(r for r in res["rows"] if r["shot"].index == 7)["new"]["trace"]
    assert two["look_refs_via_text"] and "槽满走文字" in two["look_refs_via_text"][0]["why"]


def test_registered_scene_plate_equals_slot_file():
    """登记名的 sha 必须等于槽位送入文件的 sha（总调度 11-02：ep01 底图 = ar-9565919866）"""
    import hashlib
    cfg = json.loads((ROOT / "config/scene_aliases.json").read_text(encoding="utf-8"))["scenes"]["sk_office_night"]
    sent = AR.scene_ref("sk_office_night")
    assert sent == cfg["ref"] == "assets/scenes/sk_office_night/refs/ar-9565919866.png"
    assert hashlib.sha256((ROOT / sent).read_bytes()).hexdigest() == cfg["ref_sha256"]


def test_registered_scene_plate_sha_mismatch_refused(tmp_path, monkeypatch):
    f = tmp_path / "a.json"
    f.write_text(json.dumps({"scenes": {"s": {"ref": "config/scene_aliases.json", "ref_sha256": "0" * 64}}}), encoding="utf-8")
    monkeypatch.setattr(AR, "SCENE_ALIASES", f)
    with pytest.raises(ValueError, match="sha"):
        AR.registered_scene_ref("s")
