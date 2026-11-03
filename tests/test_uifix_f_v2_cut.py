"""UIFIX-F 11-03（总调度派）：V2 分镜页出现 V1 的“办公室夜 / 深夜写字楼办公区角落”，根因是 SOP 把 V1 状态表
（data/state_timeline.json，按 V1 剧本生成）的 scene_id 按同名镜号 ep01-S1 挂到了 V2 镜头上，再由前端拼中文；
“确认造型：卓琳”弹窗在身份脸还没选定时就开了入口。这里锁住后端规则：

1. SOP 的剧本按当前剧取（ns_agent.run_paths.script_json），不写死 V1 的 data/import/script_v2.json
2. 状态表属于别的剧本（script_sha 对不上）→ 它的 scene_id / 底板一律不用；本镜场景 id 第一来源是剧本 **场景**
3. “确认造型”动作带 asset_ready / asset_wait，口径 = tools/master/episode_ready.character_gaps（同一份代码）；
   身份脸没选定 → actionable=False，文案“X的形象还在出候选，选定后再确认造型”；算不出 → 失败关闭
4. 资产包剧（清单模式）不读 V1 的 data/scenes.json（scene_assets.scenes_json 为空）
"""
import importlib.util
import json
import types
from pathlib import Path

import pytest

from ns_api import scene_assets as SA
from ns_api import sop as SOP
from ns_schema.script import ScriptImport

REPO = Path(__file__).resolve().parents[1]
PINNED_SCRIPT = REPO / "tests" / "fixtures" / "t06_golden" / "data" / "import" / "script_v2.json"


@pytest.fixture()
def proj(tmp_path):
    """临时项目根（没有 runs.json → 剧本 = data/import/script_v2.json）：第 1 集，每镜剧本 **场景** = sk_white_cyc，最后一镜不写场景"""
    sc = ScriptImport.model_validate_json(PINNED_SCRIPT.read_text(encoding="utf-8")).model_copy(deep=True)
    sc.episodes = sc.episodes[:1]
    shots = sc.episodes[0].shots
    for s in shots:
        s.scene_id = "sk_white_cyc"
    shots[-1].scene_id = None
    (tmp_path / "data" / "import").mkdir(parents=True)
    (tmp_path / "data" / "import" / "script_v2.json").write_text(sc.model_dump_json(), encoding="utf-8")
    return tmp_path, sc


def write_timeline(root: Path, sc, *, foreign: bool, plate_status="candidate"):
    """V1 风格的状态表 / 场景表：每镜 scene_id=sk_office_night；foreign=True 时 source.script_sha 对不上当前剧本"""
    shots = [{"shot_id": s.id, "episode": 1, "index": s.index, "scene_id": "sk_office_night",
              "characters": {"lin_wan": {"present": True}}, "required_loras": [], "s2_ready": True, "s2_blockers": []}
             for s in sc.episodes[0].shots]
    src = {"script": "v3", **({"script_sha": "0" * 64} if foreign else {})}
    tl = {"format": "ns.state_timeline/1", "source": src, "provisional": False,
          "s1_gate": {"validator_errors": 0, "g3_accepted": True, "g3_ref": "好"},
          "episodes": {"1": {"look_confirmed": False, "characters": ["lin_wan"], "unconfirmed_characters": ["lin_wan"]}},
          "shots": shots}
    (root / "data" / "state_timeline.json").write_text(json.dumps(tl, ensure_ascii=False), encoding="utf-8")
    (root / "data" / "scenes.json").write_text(json.dumps({"provisional": False, "scenes": [
        {"scene_id": "sk_office_night", "place": "深夜写字楼办公区角落", "shots": [s["shot_id"] for s in shots],
         "plate": "assets/scenes/sk_office_night/plate.png", "plate_status": plate_status}]}, ensure_ascii=False), encoding="utf-8")


def inputs(root: Path) -> SOP.Inputs:
    return SOP.Inputs(root, root / "data" / "renders_gpu3")


def rows(sc):
    return [{"id": s.id, "episode": 1, "index": s.index} for s in sc.episodes[0].shots]


# ---------------------------------------------------------------- 1 + 2：场景 id 来源

def test_script_loaded_from_current_run_path(proj):
    root, sc = proj
    assert SOP.script_file(root) == root / "data" / "import" / "script_v2.json"
    inp = inputs(root)
    assert inp.script is not None and inp.script.episodes[0].shots[0].id == sc.episodes[0].shots[0].id


def test_foreign_timeline_scene_from_script_only(proj):
    root, sc = proj
    write_timeline(root, sc, foreign=True)
    inp = inputs(root)
    assert "script" in inp.stale and inp.timeline_foreign
    first, last = sc.episodes[0].shots[0], sc.episodes[0].shots[-1]
    assert SOP.shot_scene(inp, first.id, inp.tl_shots[first.id]) == ("sk_white_cyc", "script")
    # 剧本没写场景的镜：状态表是别的剧本的 → 不拿它的 sk_office_night，宁可为空
    assert SOP.shot_scene(inp, last.id, inp.tl_shots[last.id]) == (None, None)
    ev = SOP.evaluate(inp, rows(sc), project_owner="gpu3")
    by = {s["id"]: s for s in ev["shots"]}
    assert by[first.id]["scene_id"] == "sk_white_cyc" and by[first.id]["scene_id_source"] == "script"
    assert by[last.id]["scene_id"] is None and by[last.id]["scene_id_source"] is None
    assert all(s["scene_id"] != "sk_office_night" for s in ev["shots"])


def test_own_timeline_fills_only_when_script_has_no_scene(proj):
    root, sc = proj
    write_timeline(root, sc, foreign=False)
    inp = inputs(root)
    assert not inp.timeline_foreign
    first, last = sc.episodes[0].shots[0], sc.episodes[0].shots[-1]
    assert SOP.shot_scene(inp, first.id, inp.tl_shots[first.id]) == ("sk_white_cyc", "script")
    assert SOP.shot_scene(inp, last.id, inp.tl_shots[last.id]) == ("sk_office_night", "timeline")


def test_timeline_foreign_flag():
    assert SOP.timeline_foreign(["script", "looks/looks.json"])
    assert SOP.timeline_foreign(["check_failed:KeyError"])
    assert not SOP.timeline_foreign(["looks/looks.json", "plate/sk_elevator"])
    assert not SOP.timeline_foreign([])


def test_foreign_scenes_json_plates_not_offered(proj):
    root, sc = proj
    write_timeline(root, sc, foreign=True)
    ev = SOP.evaluate(inputs(root), rows(sc), project_owner="gpu3")
    assert not [a for a in ev["owner_actions"] if a["gate"] == "plate"]
    write_timeline(root, sc, foreign=False)
    ev = SOP.evaluate(inputs(root), rows(sc), project_owner="gpu3")
    assert [a["scene_id"] for a in ev["owner_actions"] if a["gate"] == "plate"] == ["sk_office_night"]


# ---------------------------------------------------------------- 3：确认造型的资产前置

def _fake_er(gaps_fn):
    return types.SimpleNamespace(resolve_cid=lambda run, cid, name: cid, character_gaps=gaps_fn)


def test_look_asset_state_legacy_or_no_run_is_ready(proj):
    root, _ = proj
    assert SOP._current_run(root) is None                     # 临时根没有 runs.json
    assert SOP.look_asset_state(root, "lin_wan", "林晚", 1) == {"ready": True, "wait": None, "gaps": []}


def test_look_asset_state_face_missing(proj, monkeypatch):
    root, sc = proj
    monkeypatch.setattr(SOP, "_current_run", lambda r: "series10_v2")
    face_gap = [{"kind": "face", "who": "卓琳（ch_zhuo_lin）", "what": "没有身份脸", "cid": "ch_zhuo_lin", "name": "卓琳"},
                {"kind": "name", "who": "卓琳（ch_zhuo_lin）", "what": "清单里没有 display_name", "cid": "ch_zhuo_lin", "name": "卓琳"}]
    monkeypatch.setattr(SOP, "_episode_ready_module", lambda: _fake_er(lambda run, cid, name, ep, m=None: face_gap))
    st = SOP.look_asset_state(root, "卓琳", "卓琳", 1)
    assert st["ready"] is False and st["wait"] == "卓琳的形象还在出候选，选定后再确认造型" and len(st["gaps"]) == 2
    # 走完整评估：动作不可点、waiting_on 是这句话、asset_ready=False；标题 / 文案里没有命令行
    write_timeline(root, sc, foreign=True)
    ev = SOP.evaluate(inputs(root), rows(sc), project_owner="gpu3")
    look = next(a for a in ev["owner_actions"] if a["gate"] == "look")
    assert look["asset_ready"] is False and look["actionable"] is False
    assert look["asset_wait"].endswith("形象还在出候选，选定后再确认造型") and look["waiting_on"] == [look["asset_wait"]]


def test_look_asset_state_schedule_and_name(proj, monkeypatch):
    root, _ = proj
    monkeypatch.setattr(SOP, "_current_run", lambda r: "series10_v2")
    monkeypatch.setattr(SOP, "_episode_ready_module", lambda: _fake_er(
        lambda run, cid, name, ep, m=None: [{"kind": "schedule", "who": "x", "what": "没排期", "cid": cid, "name": name}]))
    assert SOP.look_asset_state(root, "lead_f", "祁念", 1)["wait"] == "祁念本集的造型排期还没做，排好后再确认造型"
    monkeypatch.setattr(SOP, "_episode_ready_module", lambda: _fake_er(
        lambda run, cid, name, ep, m=None: [{"kind": "name", "who": "x", "what": "没名字", "cid": cid, "name": name}]))
    assert SOP.look_asset_state(root, "lead_f", "祁念", 1)["wait"] == "祁念还没登记进资产清单，登记后再确认造型"
    monkeypatch.setattr(SOP, "_episode_ready_module", lambda: _fake_er(lambda run, cid, name, ep, m=None: []))
    assert SOP.look_asset_state(root, "lead_f", "祁念", 1)["ready"] is True


def test_look_asset_state_fails_closed(proj, monkeypatch):
    root, _ = proj
    monkeypatch.setattr(SOP, "_current_run", lambda r: "series10_v2")

    def boom(*a, **k):
        raise RuntimeError("manifest broken")
    monkeypatch.setattr(SOP, "_episode_ready_module", lambda: _fake_er(boom))
    st = SOP.look_asset_state(root, "卓琳", "卓琳", 1)
    assert st["ready"] is False and "读不出来" in st["wait"]


def _episode_ready():
    spec = importlib.util.spec_from_file_location("er_under_test", REPO / "tools" / "master" / "episode_ready.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_episode_ready_character_gaps_same_rule(monkeypatch):
    """SOP 用的 character_gaps 就是开工前检查的那一份：身份脸 / display_name / 本集排期"""
    from ns_agent import asset_refs as AR
    er = _episode_ready()
    faces = {"lead_f": "assets_v2/characters/lead_f/face/x.png"}
    monkeypatch.setattr(AR, "face_of", lambda run, cid: faces.get(cid))
    monkeypatch.setattr(AR, "episode_look_override", lambda run, cid, ep: None)
    mchars = {"lead_f": {"display_name": "祁念", "looks": {"O4": {}}}}
    kinds = {g["kind"] for g in er.character_gaps("series10_v2", "ch_zhuo_lin", "卓琳", 1, mchars)}
    assert kinds == {"face", "name"}
    kinds = {g["kind"] for g in er.character_gaps("series10_v2", "lead_f", "祁念", 1, mchars)}
    assert kinds == {"schedule"}
    monkeypatch.setattr(AR, "episode_look_override", lambda run, cid, ep: "O4")
    assert er.character_gaps("series10_v2", "lead_f", "祁念", 1, mchars) == []
    g = er.character_gaps("series10_v2", "ch_tang_yao", "唐瑶", 1, mchars)[0]
    assert g["cid"] == "ch_tang_yao" and g["name"] == "唐瑶" and g["who"] == "唐瑶（ch_tang_yao）"


# ---------------------------------------------------------------- 4：资产包剧不读 V1 的 scenes.json

def test_scene_assets_ignores_v1_scenes_json_in_manifest_mode(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "scenes.json").write_text(json.dumps({"scenes": [
        {"scene_id": "sk_office_night", "place": "深夜写字楼办公区角落"}]}), encoding="utf-8")
    monkeypatch.setattr(SA, "root", lambda: tmp_path)
    monkeypatch.setattr(SA._RP, "manifest_scene_ids", lambda root=None: [])        # 资产包模式（清单里还没有场景）
    assert SA.scenes_json() == {}
    monkeypatch.setattr(SA._RP, "manifest_scene_ids", lambda root=None: None)      # 旧模式照旧
    assert list(SA.scenes_json()) == ["sk_office_night"]
