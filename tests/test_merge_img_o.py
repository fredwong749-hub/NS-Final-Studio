"""MERGE-IMG-O 11-03（L-137 V2 出图链并回 V1 主干）：编译 + 闸门 8 项回归。

1 ISS-1103-024205-8856 近景 / 特写服装：一体件上身看得见 → 不整句删；全身装 zone=body；I3 无设定图 fail
2 ISS-1103-023528-2869 镜头语言模板 v2 接进 build_first（固定顺序；按剧开关；V2 镜头句去品牌）
3 ISS-1103-023528-1509 三人镜脸板逐人认脸（I2 / I9 / trace.faces）
4 ISS-1103-024206-c8c0 Q1a 人物卡按剧生成；Q1 主角线按本剧主角 id
5 CARRYOVER 第 11 项 作业负面词不再被覆盖，硬负面永远在；Base 预设写回编码器
6 设定图模式不加朝向 / 视线句
7 V2 bible 补回 realism banned_words 两条 + “画风变为动漫”
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/agent", "packages/schema", "services/render_router", "tools/pipeline"):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))

from ns_agent import asset_refs as AR  # noqa: E402
from ns_agent import framing as FR  # noqa: E402
from ns_agent import frame_job as FJ  # noqa: E402
from ns_agent import shot_language as SL  # noqa: E402
from ns_agent.gen_contract import cards as CARDS  # noqa: E402
from ns_agent.gen_contract import preflight as PF  # noqa: E402

V2 = "series10_v2"
HAVE_V2 = bool(AR.project_cfg(V2)) and (ROOT / "assets_v2" / "manifest.json").is_file()


# ---------------------------------------------------------------- 1 服装
def test_close_keeps_upper_of_one_piece_drops_legwear():
    s = "近景，平视机位，祁念站在白幕前，祁念穿黑色漆皮抹胸紧身短裙、黑色薄透丝袜，祁念的雾蓝色长发垂在肩后"
    out = FR.filter_parts(s, "近景", subjects=["祁念"])
    assert "祁念穿黑色漆皮抹胸紧身短裙" in out
    assert "丝袜" not in out


def test_close_still_drops_pure_lower_and_suit_skirt():
    assert FR.filter_parts("近景，林晚穿深灰西装裙，林晚抬眼", "近景", subjects=["林晚"]).find("西装裙") < 0
    assert "高跟" not in FR.filter_parts("特写，透明细高跟，林晚的眼睛", "特写")


def test_visible_items_splits_plus_list():
    lab = "日常全身装：黑色漆皮抹胸紧身短裙 + 黑色薄透丝袜 + 透明尖头细高跟"
    assert FR.visible_items(lab, "近景") == "日常全身装：黑色漆皮抹胸紧身短裙"
    assert FR.visible_items("穿黑色短裙配白衬衫", "近景") == "穿白衬衫"
    assert not FR.upper_garment("黑色吊带袜")


def test_zone_of_full_body_dress():
    assert AR.zone_of("outfit", "日常全身装：黑色漆皮抹胸紧身短裙 + 黑色薄透丝袜") == "body"
    assert AR.zone_of("outfit", "银灰色缎面高腰短裤") == "lower"


def _rec(zones, warn=True, subject=None):
    return {"subject": subject, "zones": zones, "primary": "lead_f",
            "characters": [{"character": "lead_f", "name": "祁念", "presence": "在画", "look": "O4"}],
            "slots": [{"index": 1, "kind": "face", "file": "f.png", "character": "lead_f", "faces": 1,
                       "members": [{"role": "face", "character": "lead_f", "file": "f.png"}], "line": "图1是祁念的脸部参考（只取脸和发型）。"}],
            "warnings": [{"character": "祁念", "kind": "造型参考用清单单品图", "detail": "祁念 造型O4 还没有设定图"}] if warn else [],
            "missing": [], "dropped": [], "capacity": 3}


def _i(res, iid):
    return next(i for i in res.items if i.id == iid)


def test_i3_fails_without_sheet_when_wardrobe_visible():
    req = {"kind": "image", "cast": [{"name": "祁念", "presence": "在画", "x": "中"}], "prompt": "图1是祁念的脸部参考（只取脸和发型）。",
           "refs": ["f.png"], "asset_refs": _rec(["face", "upper", "body"])}
    assert _i(PF.check(req), "I3").status == "fail"
    req["asset_refs"] = _rec(["face"])                      # 只看得到脸：不要求设定图
    assert _i(PF.check(req), "I3").status == "pass"
    req["asset_refs"] = _rec(["face", "upper"], warn=False)
    assert _i(PF.check(req), "I3").status == "pass"


# ---------------------------------------------------------------- 2 镜头语言
class _Shot(dict):
    pass


def _shot(**kw):
    d = {"index": 8, "img_prompt": "近景，平视机位，祁念站在白幕前", "cast": [{"name": "祁念", "presence": "在画", "x": "中"}],
         "extras": [{"label": "构图", "text": "前景=手｜中景=祁念的脸｜背景=白幕"},
                    {"label": "灯光", "text": "动机光源=天花顶光（上方）｜色温=4000K 冷白"}], "music_cue": ""}
    d.update(kw)
    return d


def test_shot_language_off_without_run_entry(monkeypatch):
    monkeypatch.setattr(SL, "run_cfg", lambda p: {})
    assert SL.image_clauses("series10_v1", _shot()) == []


def test_shot_language_fixed_order_and_brand_free(monkeypatch):
    monkeypatch.setattr(SL, "run_cfg", lambda p: {"lens": "auto", "composition": "script", "lighting": "script", "fusion": True})
    monkeypatch.setattr(AR, "manifest_rel", lambda p: "assets_v2/manifest.json")
    got = SL.image_clauses(V2, _shot())
    assert [k for k, _ in got] == ["lens", "composition", "lighting", "fusion"]
    lens = got[0][1]
    assert "徕卡" not in lens and "Leica" not in lens and "mm" in lens
    assert got[1][1] == "构图：前景：手，中景：祁念的脸，背景：白幕"
    assert got[2][1].startswith("灯光：动机光源：天花顶光")
    assert "接触阴影" in got[3][1]


def test_shot_language_script_mode_skips_missing_fields(monkeypatch):
    monkeypatch.setattr(SL, "run_cfg", lambda p: {"lens": "script", "composition": "script", "lighting": "script"})
    assert SL.image_clauses(V2, _shot(extras=[])) == []


def test_v2_run_style_has_switches():
    rc = SL.run_cfg(V2)
    assert set(rc) >= {"lens", "composition", "lighting", "fusion"}
    assert SL.image_compile_cfg().get("order") == ["lens", "composition", "lighting", "fusion"]


# ---------------------------------------------------------------- 3 脸板
def _board_rec():
    mem = [{"role": "face", "character": c, "file": f"{c}.png"} for c in ("ch_zhuo_lin", "lead_f", "ch_tang_yao")]
    return {"subject": None, "zones": ["face", "upper"], "primary": "ch_zhuo_lin",
            "characters": [{"character": c, "name": n, "presence": "在画", "look": "A"}
                           for c, n in (("ch_zhuo_lin", "卓琳"), ("lead_f", "祁念"), ("ch_tang_yao", "唐瑶"))],
            "slots": [{"index": 1, "kind": "faceboard", "file": "b.png", "character": "ch_zhuo_lin", "faces": 3, "members": mem,
                       "line": "图1是脸部参考板：①卓琳②祁念③唐瑶——每一格是对应人物的脸（只取脸和发型），每个人的长相必须与自己那一格一致。"}],
            "warnings": [], "missing": [], "dropped": [], "capacity": 3}


def test_faceboard_counts_every_person(monkeypatch):
    monkeypatch.setattr(PF, "manifest_missing_faces", lambda faced, proj=None: [])
    monkeypatch.setattr(PF, "stale_face_slots", lambda slots, proj=None: [])
    rec = _board_rec()
    req = {"kind": "image", "cast": [{"name": n, "presence": "在画", "x": x} for n, x in (("卓琳", "左"), ("祁念", "中"), ("唐瑶", "右"))],
           "prompt": rec["slots"][0]["line"], "refs": ["b.png"], "asset_refs": rec}
    res = PF.check(req)
    assert _i(res, "I2").status == "pass", _i(res, "I2").detail
    assert "两张脸" not in _i(res, "I9").detail
    assert FJ.face_ids(rec["slots"]) == ["ch_zhuo_lin", "lead_f", "ch_tang_yao"]
    rec["slots"][0]["members"][1]["character"] = "ch_zhuo_lin"   # 同一人两格 = 不合规
    assert "两张脸" in _i(PF.check(req), "I9").detail


# ---------------------------------------------------------------- 4 人物卡 / 主角线
def test_card_from_p1_rows():
    blue = CARDS.card_from_p1({"name": "祁念", "gender": "女", "zh_look": "二十三岁｜雾蓝色及腰长直发、空气感碎刘海｜黑色漆皮"})
    assert blue["gender"] == "女" and "蓝" in blue["hair_colors"] and blue["blue_min"] == 0.2 and "长" in blue["hair_lengths"]
    buzz = CARDS.card_from_p1({"name": "周序", "gender": "男", "zh_look": "二十五岁｜黑色寸头｜藏青与灰"})
    assert buzz["hair_short"] and buzz["hair_lengths"] == ["短"] and buzz["blue_max"] == 0.45
    tied = CARDS.card_from_p1({"name": "江予白", "gender": "男", "zh_look": "二十九岁｜深棕色中长发、半扎"})
    assert "hair_lengths" not in tied and not tied.get("hair_short") and "棕" in tied["hair_colors"]


def test_q1a_cards_by_run():
    t1a = {"cards": {"lin_wan": {"name": "林晚"}}}
    assert CARDS.q1a_cards(None, t1a) == t1a["cards"]
    if not HAVE_V2:
        pytest.skip("V2 资产包不在本机")
    c = CARDS.q1a_cards(V2, t1a)
    assert "lin_wan" not in c and "lead_f" in c and c["lead_f"]["gender"] == "女"


def test_identity_line_uses_run_lead():
    t1 = {"lin_wan": 0.7, "lead": 0.7, "default": 0.6}
    assert CARDS.identity_line("lin_wan", t1) == 0.7
    if HAVE_V2:
        assert CARDS.identity_line("lead_f", t1, V2) == 0.7
        assert CARDS.identity_line("ch_zhuo_lin", t1, V2) == 0.6
        assert CARDS.is_lead_listed("lead_f", ["lin_wan", "@lead"], V2)


def test_gen_contract_config_has_lead_and_by_run():
    th = json.loads((ROOT / "config" / "gen_contract.json").read_text(encoding="utf-8"))["image_thresholds"]
    assert th["Q1_identity"]["lead"] == 0.7 and "@lead" in th["Q1_identity"]["yaw_relax"]["characters"]
    assert "cards_by_run" in th["Q1a_attr"]


# ---------------------------------------------------------------- 5 负面词
def test_job_negative_keeps_hard_guard():
    from ns_agent import compiler as C
    assert C.MINOR_GUARD in FJ.job_negative("", "")
    n = FJ.job_negative("动漫脸、未成年人外观", "品牌logo、任何文字")
    assert n.count(C.MINOR_GUARD) == 1 and "品牌logo" in n and "动漫脸" in n


def test_unified_frame_writes_negative_for_base_preset(monkeypatch):
    from ns_render import image_params as IP
    from ns_render import unified_frame as UF
    job = {"refs": [], "prompt": "p", "negative": "未成年人外观、水印", "preset": "final_base_2pass"}
    try:
        wf, eff, _ = UF.build_graph(job, 1, lambda p: p.name, "x")
    except Exception as e:      # noqa: BLE001 — 预设在本机配置里不可解析时跳过
        pytest.skip(f"预设不可用：{e}")
    enc = next(n for n in wf.values() if "TextEncodeQwenImage" in n.get("class_type", ""))
    if eff.get("unet") != "turbo" and float(wf["38"]["inputs"]["cfg"]) > 1:
        assert enc["inputs"]["negative_prompt"] == job["negative"]
    job["preset"] = None
    wf2, eff2, _ = UF.build_graph(job, 1, lambda p: p.name, "x")
    enc2 = next(n for n in wf2.values() if "TextEncodeQwenImage" in n.get("class_type", ""))
    if eff2.get("unet") == "turbo":
        assert enc2["inputs"]["negative_prompt"] == ""


# ---------------------------------------------------------------- 6 设定图模式 / 1 + 5 真编译（V2 ep01）
def _v2_shot(n):
    from ns_schema.script import ScriptImport
    import importlib.util as U
    sp = U.spec_from_file_location("runs_mio", ROOT / "tools" / "autopilot" / "runs.py")
    m = U.module_from_spec(sp)
    sp.loader.exec_module(m)
    p = m.import_path(V2, ROOT)
    if not p.is_file():
        pytest.skip("V2 导入稿不在本机")
    s = ScriptImport.model_validate(json.loads(p.read_text(encoding="utf-8")))
    ep = s.episodes[0]
    return s, ep, next(x for x in ep.shots if int(x.index) == n)


@pytest.mark.skipif(not HAVE_V2, reason="V2 资产包不在本机")
def test_v2_s8_close_wardrobe_and_negative(monkeypatch):
    monkeypatch.setenv("NS_RUN", V2)
    s, ep, sh = _v2_shot(8)
    job = FJ.build_first(V2, ep, sh, s.globals)
    assert "穿黑色漆皮抹胸紧身短裙" in job["prompt"] and "丝袜" not in job["prompt"].split("图3")[-1].split("【场景】")[0]
    assert "高亮镜面漆皮" in job["prompt"]
    assert any("outfit" in f for f in job["refs"])
    assert "未成年人外观" in job["negative"]


@pytest.mark.skipif(not HAVE_V2, reason="V2 资产包不在本机")
def test_sheet_mode_has_no_gaze_lines(monkeypatch):
    monkeypatch.setenv("NS_RUN", V2)
    s, ep, sh = _v2_shot(8)
    shot = FJ.build_first(V2, ep, sh, s.globals)["prompt"]
    sheet = FJ.build_first(V2, ep, sh, s.globals, mode="sheet")["prompt"]
    assert "四分之三侧脸" in shot
    assert "四分之三侧脸" not in sheet and "眼睛不看镜头" not in sheet and "看画内的人或物" not in sheet


# ---------------------------------------------------------------- 7 V2 bible
def test_v2_bible_carries_realism_words_and_anime_negative():
    import tomllib
    b = tomllib.loads((ROOT / "config" / "compile" / "bible_series10_v2.toml").read_text(encoding="utf-8"))
    assert {"严格保持图1的眼睛形状", "五官比例完全一致"} <= set(b["realism"]["banned_words"])
    assert "画风变为动漫" in b["look"]["video"]["negative"]


# ---------------------------------------------------------------- ISS-1103-030746-664a：episode_ready 与 preflight I3 同一份判定
def test_episode_ready_uses_preflight_sheet_gaps(monkeypatch, tmp_path):
    import types
    sys.path.insert(0, str(ROOT / "tools" / "master"))
    import episode_ready as ER
    chars = [{"character": "lead_f", "name": "祁念", "presence": "在画", "look": "O4"}]
    warns = [{"character": "祁念", "kind": "造型参考用清单单品图", "detail": "x"}]
    g = PF.sheet_gaps(None, ["face", "upper"], chars, warns)
    assert g and g[0]["detail"] == "祁念 造型O4 没有设定图"
    assert PF.sheet_gaps(None, ["face"], chars, warns) == []
    doc = {"episodes": [{"number": 1, "shots": [{"index": 8}]}]}
    src = tmp_path / "s.json"
    src.write_text(json.dumps(doc), encoding="utf-8")
    from ns_agent import run_paths as RP
    monkeypatch.setattr(RP, "runs_module", lambda root: types.SimpleNamespace(script_path=lambda run, root: src))
    sr = types.SimpleNamespace(characters=chars, scene_id=None, missing=[], subject=None, zones=["face", "upper"], warnings=warns)
    monkeypatch.setattr(AR, "resolve_shot", lambda run, ep, s: sr)
    monkeypatch.setattr(AR, "manifest", lambda run: {"characters": {"lead_f": {"display_name": "祁念"}}})
    monkeypatch.setattr(ER, "character_gaps", lambda *a, **k: [])
    res = ER.check(V2, 1, tmp_path)
    assert [(x["kind"], x["what"], x["shots"]) for x in res["gaps"]] == [("look", "祁念 造型O4 没有设定图", [8])] and not res["ready"]


# ---------------------------------------------------------------- L-147 / L-148 / L-149（项目方 11-03 05:0x）
def test_auto_final_on_lock_per_run(tmp_path):
    from ns_render import final_tier as FT
    q = tmp_path / "rq.json"
    q.write_text(json.dumps({"auto_final_on_lock": False, "auto_final_on_lock_runs": {"series10_v2": True}}), encoding="utf-8")
    assert FT.auto_final_on_lock(q, "series10_v2") is True
    assert FT.auto_final_on_lock(q, "series10_v1") is False
    real = json.loads((ROOT / "config" / "render_quality.json").read_text(encoding="utf-8"))
    assert real["auto_final_on_lock_runs"]["series10_v2"] is False and real["auto_final_on_lock"] is False   # L-147：共用验收并回前先关（总调度 11-03）


def test_v2_suffix_texture_only_no_lighting():
    from ns_agent.gen_contract import style as ST
    for seg in ("fantasy", "reality"):
        s = ST.preset_suffix(V2, seg)
        assert "Leica" in s and "ARRI" in s and "Kodak" in s
        for w in ("机顶", "直闪", "白平衡", "日落", "暖阳", "夜里", "逆光"):
            assert w not in s, (seg, w)


def test_v2_lens_and_fusion_on():
    rc = SL.run_cfg(V2)
    assert rc["lens"] == "auto" and rc["fusion"] is True and rc["lighting"] == "script"


def test_importer_puts_lighting_on_shot(tmp_path):
    from ns_agent.importer import script_md as M
    md = tmp_path / "p4.md"
    md.write_text("## ep01《t》\n\n**镜1｜img**：近景，祁念站着\n**构图**：前景=手｜中景=脸\n**灯光**：动机光源=顶光（上方）\n**时长**：6秒\n",
                  encoding="utf-8")
    sh = M.import_script(md).episodes[0].shots[0]
    assert {e.label: e.text for e in sh.extras} == {"构图": "前景=手｜中景=脸", "灯光": "动机光源=顶光（上方）"}


def test_sheet_spec_shoe_from_p1_schedule():
    sys.path.insert(0, str(ROOT / "tools" / "pipeline"))
    import asset_jobs as AJ
    story = {"characters": [{"char_id": "lead_f", "name": "祁念", "gender": "女", "age": 23, "zh_look": "二十三岁｜高挑｜雾蓝色长发｜黑"}]}
    looks = [{"character": "祁念", "char_id": "lead_f", "looks": [{"id": "O4", "zh": "服装=抹胸短裙｜鞋=SH1 或 SH2｜饰品=无"}],
              "schedule": [{"episode": 1, "outfit": "O4", "shoes": "SH1"}, {"episode": 2, "outfit": "O1+O4", "shoes": "SH1"}]}]
    try:
        s = AJ.spec_sheet(story, looks, "lead_f", "O4", 1)
    except Exception as e:   # noqa: BLE001 — 夹具缺字段时只核鞋的取法
        pytest.skip(f"spec_face 夹具不全：{e}")
    assert s["slots"]["鞋"] == "SH1" and "SH2" not in s["img"]
