"""L-204 / FIX-PRE 11-06（REVIEW-PRE 出图前代码审计 B / D / E / F / G + ②A）：
① 过肩“越谁拍谁”按原文先后认（名字后带括注也认），尾帧沿用首帧的 ots_from / ots_to，被拍的主体永不记成不露脸；
② hidden_face 只认挂在身体部位上的写法（以侧脸入画 / 只露出一道金边 / 被手掌盖住 都不是不露脸）；
③ off_axis_gaze 多认 钉在 / 停在 / 投向 与无主语的“抬眼看向画面右前方”；
④ 尾帧 compose 作业派单前过生成契约 preflight，I9 认首帧连续性参考槽；
⑤ 局部（背影 / 过肩前景）的人只补部位内单品、不送整张设定图、不送脸；
⑥ 参考槽优先级：脸 > 主体造型 > 场景底板 > 第二人造型 > 单品；尾帧连续性槽让位造型而非底板。
全部纯函数 / mock，不碰 GPU、不写真实数据。"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in ("tools/autopilot", "services/render_router", "services/agent", "packages/schema", "services/recipes"):
    if str(ROOT / _p) not in sys.path:
        sys.path.insert(0, str(ROOT / _p))

from ns_schema import prompt_v2 as PV  # noqa: E402
from ns_agent import asset_refs as AR  # noqa: E402
from ns_agent import frame_job as FJ  # noqa: E402
from ns_agent import framing as FR  # noqa: E402
from ns_agent import prompt_template_v2 as PT2  # noqa: E402
from ns_agent.gen_contract import preflight as PF  # noqa: E402

# ep01-S12（P4_ep01.L3_psm9）原文节选：cast 顺序是被拍的祁念在前，原来退到 cast 顺序 → “越过祁念的肩拍江予白”
S12 = {
    "index": 12,
    "img_prompt": "中近景，过肩机位，从江予白左肩后方越过他的肩拍祁念，浅景深，祁念站在影棚白幕前的透明亚克力椅旁、在焦点上，"
                  "祁念的视线落在画面右侧江予白手里的相机包上；江予白在画面右侧前景环形灯架后的相机位、以侧后方的左肩和侧脸入画、"
                  "略在焦外，江予白低着头、视线落在包口的拉链上",
    "img_triggers": [],
    "motion_prompt": "camera pull out 中幅拉远，江予白把拉链一口气拉到头——中景，过肩、1.5 m 平视，镜头后拉一档，祁念到腰以上在画面左侧，"
                     "视线落在江予白肩上的相机包上，江予白的左肩与侧脸在右前景转向她、略在焦外",
    "extras": [
        {"label": "机位与景别", "text": "中近景｜过肩、平视（越江予白拍祁念，与镜13 成正反打对，同焦段同高度）｜起幅：从江予白（右，前景，"
                                     "低头看拉链）左肩后方越肩拍祁念（中，亚克力椅旁，脸在焦点上）；落幅：中景过肩（松一档），祁念腰以上在画左"},
        {"label": "运镜", "text": "拉远｜中幅｜起幅=中近景过肩 → 落幅=中景过肩（松一档），江予白的侧脸在右前景转向她，祁念到腰以上在画左"},
    ],
    "cast": [{"name": "祁念", "presence": "在画", "x": "中", "depth": "中", "part": None},
             {"name": "江予白", "presence": "在画", "x": "右", "depth": "前", "part": None}],
}
NAMES = ["祁念", "江予白"]


# ---------------------------------------------------------------- ① 过肩
@pytest.mark.parametrize("text, frm, to", [
    ("过肩、平视（越江予白拍祁念，与镜13 成正反打对）", "江予白", "祁念"),
    ("起幅：从江予白（右，前景，低头看拉链）左肩后方越肩拍祁念（中，亚克力椅旁）", "江予白", "祁念"),
    ("过肩机位，越过江予白的右肩略仰拍祁念", "江予白", "祁念"),
    ("从江予白的肩后方越过他的肩拍祁念", "江予白", "祁念"),
    ("过肩（越祁念拍江予白）；起幅：从江予白左肩后方越肩拍祁念", "祁念", "江予白"),     # 两处都写 → 按原文先后取第一处
])
def test_ots_pair_text_order(text, frm, to):
    a = PV.parse_angle(text, NAMES)
    assert a["azimuth"] == "ots"
    assert (a["ots_from"], a["ots_to"], a["ots_by"]) == (frm, to, "text")


def test_ots_pair_fallback_only_when_nothing_matches():
    a = PV.parse_angle("过肩机位，平视，两人同框", NAMES)
    assert a["azimuth"] == "ots" and a["ots_by"] in ("fallback", None)


def test_s12_hidden_people_keeps_subject_faced():
    hid = PT2.hidden_people(S12)
    assert "祁念" not in hid and "江予白" in hid


def test_s12_last_frame_keeps_first_frame_ots_pair():
    end = FJ.end_framing(S12)
    field = FJ.last_angle_field(S12, end)
    assert "越过江予白的肩拍祁念" in field and "越过祁念" not in field
    shot2 = FJ.compose_last_shot(S12, end)
    hid = PT2.hidden_people(shot2)
    assert "祁念" not in hid


# ---------------------------------------------------------------- ② hidden_face
@pytest.mark.parametrize("text", ["以侧脸入画", "以半边脸与肩入画", "耳环只露出一道金边", "台本被手掌盖住", "以相机包入画"])
def test_hidden_face_not_for_face_or_object(text):
    assert PV.hidden_face(text) == (False, "")


@pytest.mark.parametrize("text, part", [("只以右肩与后脑在左下入画", "右肩与后脑"), ("背对镜头", "背影"), ("只露出肩头", "肩与背")])
def test_hidden_face_body_parts(text, part):
    hid, got = PV.hidden_face(text)
    assert hid and part in got


# ---------------------------------------------------------------- ③ 视线不朝镜头
@pytest.mark.parametrize("text", ["她的视线钉在画面右前方的灯圈上", "视线停在画面左前方", "目光投向画面正前方", "祁念抬眼看向画面右前方"])
def test_off_axis_gaze_more_verbs(text):
    out = FR.off_axis_gaze(text)
    assert "前方" not in out and "与镜头方向错开" in out


def test_off_axis_gaze_leaves_hands_alone():
    assert FR.off_axis_gaze("右手停在画面右前方的桌沿") == "右手停在画面右前方的桌沿"


# ---------------------------------------------------------------- ④ 尾帧 preflight
def test_i9_accepts_continuity_slot():
    files = ["a_face.png", "b_sheet.png"]
    req = {"continuity_ref": {"file": "first.png", "n": 3}}
    assert PF._continuity_ok(req, files + ["first.png"], files, "")
    assert PF._continuity_ok({}, files + ["first.png"], files, "图3是本镜头首帧，只用来保持……")
    assert not PF._continuity_ok({}, files + ["first.png"], files, "")                  # 没有凭据
    assert not PF._continuity_ok(req, files + ["x.png", "first.png"], files, "")       # 多出来的不是连续性参考
    assert not PF._continuity_ok(req, ["b_sheet.png", "a_face.png", "first.png"], files, "")


def test_last_preflight_raises_on_contract_fail(monkeypatch):
    import producer as PR
    from ns_render import unified_frame as UF
    from ns_render.comfy_client import ComfyError

    class _Bad:
        ok = False

        def reasons(self):
            return ["I9 参考与规划不一致"]

    class _Good:
        ok = True

        def reasons(self):
            return []

    seen = []
    monkeypatch.setattr(UF, "_contract", lambda job: seen.append(job) or _Bad())
    with pytest.raises(ComfyError, match="preflight 不通过"):
        PR.last_preflight({"shot": "ep01-S4"}, "ep01-S4")
    monkeypatch.setattr(UF, "_contract", lambda job: _Good())
    assert PR.last_preflight({"shot": "ep01-S4"}, "ep01-S4") is None
    assert PR.PREFLIGHT_PAT.search("ep01-S4 尾帧生成契约 preflight 不通过，未提交：x")


def test_last_preflight_wired_once_before_double_face():
    src = (ROOT / "tools/autopilot/producer.py").read_text(encoding="utf-8")
    assert src.count("last_preflight(job, sid)") == 1
    i = src.index("job = last_job_for_rung(")              # W-REFS 11-06：尾帧作业构造挪进 last_job_for_rung（内部仍是 FJ.build_last）
    assert "FJ.build_last(first_job" in src[src.index("def last_job_for_rung"):]
    j = src.index("last_preflight(job, sid)")
    k = src.index('if rung.get("variant") == "double_face" and job.get("face_files"):')
    assert i < j < k


def test_unified_contract_passes_continuity_ref(monkeypatch):
    from ns_render import unified_frame as UF
    got = {}
    monkeypatch.setattr(PF, "check", lambda req: got.update(req) or "R")
    UF._contract({"shot": "ep01-S4", "continuity_ref": {"file": "f.png"}, "refs": ["f.png"]})
    assert got["continuity_ref"] == {"file": "f.png"}


# ---------------------------------------------------------------- ⑤ 局部人物
def _shot_partial(part):
    return {"index": 2, "img_prompt": "中景，祁念坐在亚克力椅上，唐瑶背对镜头只以右肩入画", "img_triggers": [],
            "cast": [{"name": "祁念", "presence": "在画", "part": None}, {"name": "唐瑶", "presence": "局部", "part": part}]}


@pytest.mark.parametrize("part", ["背影右肩", "后脑", "肩背", "左肩侧后"])
def test_back_part_words(part):
    assert AR.back_part(_shot_partial(part), "唐瑶")


def test_partial_items_scoped_note(monkeypatch):
    look = AR.Look("ch_tang_yao", "A", "", "", "", [
        AR.LookPart("outfit", "黑色西装外套", "upper"), AR.LookPart("accessory", "银色锁骨链", "neck"),
        AR.LookPart("nails", "红色长指甲", "hand"), AR.LookPart("shoes", "黑色高跟鞋", "feet")])
    monkeypatch.setattr(AR, "load_looks", lambda project: {"ch_tang_yao": {"A": look}})
    sr = type("SR", (), {"characters": [{"character": "ch_tang_yao", "look": "A", "name": "唐瑶", "presence": "局部",
                                         "back_view": True, "wardrobe_scope": ["neck"]}]})()
    shot = _shot_partial("背影右肩")
    ep = {"number": 1}
    assert FJ.outer_items("p", ep, shot, sr, body=shot["img_prompt"]) == []
    note = FJ.outer_items_note("p", ep, shot, sr, shot["img_prompt"])
    assert "要穿全" not in note and "必须入画" not in note
    assert note == "唐瑶露出的背影右肩上要有：银色锁骨链（只画这一部位的单品，不补整套造型）。"
    assert AR.PART_ITEMS_RE.fullmatch(note.rstrip("。"))
    res = AR.TEXT_NOTE_RES
    assert res.index(AR.PART_ITEMS_RE) == res.index(AR.OUTER_ITEMS_RE) + 1          # unified_stale 按拼接顺序认


# ---------------------------------------------------------------- ⑥ 槽位优先级
def _ref(role, ch, f, prio, face=False):
    return AR.Ref(role, ch, f, f"{ch} {role}", prio, None, role, has_face=face)


def test_slot_priority_scene_before_second_look():
    refs = [_ref("face", "a", "a_face.png", 0, True), _ref("sheet", "a", "a_sheet.png", 1),
            _ref("scene", None, "scene.png", AR.SCENE_SLOT_PRIO), _ref("sheet", "b", "b_sheet.png", 11),
            _ref("item", "b", "b_item.png", 12)]
    sr = AR.ShotRefs("ep01-S9", "p", "中景", None, ["upper"], "a", [], refs, [], [])
    plan = AR.plan_slots(sr, capacity=3)
    assert [s.kind for s in plan.slots] == ["face", "sheet", "scene"]
    assert {d["file"] for d in plan.dropped} >= {"b_sheet.png", "b_item.png"}


def test_continuity_slot_displaces_look_not_scene():
    refs = [_ref("face", "a", "a_face.png", 0, True), _ref("sheet", "a", "a_sheet.png", 1),
            _ref("scene", None, "scene.png", AR.SCENE_SLOT_PRIO)]
    sr = AR.ShotRefs("ep01-S9", "p", "中景", None, ["upper"], "a", [], refs, [], [])
    plan = AR.plan_slots(sr, capacity=3)
    cont = FJ.continuity_slot(plan, "qwen_image_2.1", "first.png", FJ.LAST_CONTINUITY_LINE)
    assert [s.kind for s in plan.slots] == ["face", "scene"]
    assert cont["replaced"]["kind"] == "sheet" and cont["n"] == 3


def test_single_turn_gaze_target_off_axis():
    shot = {"img_prompt": "近景，祁念的视线落在画面右前方环形灯架后的方向，嘴唇微张", "extras": []}
    t = AR.gaze_target(shot)
    assert "前方" not in t and t.startswith("画面右侧远处（与镜头方向错开）")
    line = AR.SINGLE_TURN_LEAD.format(name="祁念", target=t[:30])
    assert AR.SINGLE_TURN_RE.fullmatch(line)
