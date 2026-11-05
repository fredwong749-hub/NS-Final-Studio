"""阶段 2.1 提示词模板 v2（CODER-PT 11-05，PLAN_EP01_FINISH §4 2.1 / §8 ①–⑤ / §9）：
纯文本核心（ns_schema.prompt_v2）、按剧开关默认 v1、作业签名随模板变、词表 h3_official / 候选、真实 V2 数据（psm6）出图 + 视频两条路一致。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in ("packages/schema", "services/render_router", "services/agent", "services/recipes", "tools/autopilot", "tools", ""):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))

from ns_schema import prompt_v2 as PV  # noqa: E402
from ns_agent import prompt_template_v2 as PT2  # noqa: E402
import producer as PR  # noqa: E402

V2 = "series10_v2"
PSM6 = ROOT / "data/pipeline/runs/series10_v2/staging/P4_ep01.L2_psm6.md"
NAMES = ["卓琳", "祁念", "唐瑶"]


# ---------------------------------------------------------------- 核心：机位 / 焦点 / 否定 / 人物行 / 同框句
def test_parse_angle_variants():
    a = PV.parse_angle("侧 45°（A 区主机位，三人线的相机一侧）", NAMES)
    assert (a["azimuth"], a["height"]) == ("side45", "eye")
    assert PV.angle_en(a) == "from a 45-degree side angle at eye level"
    a = PV.parse_angle("过肩略俯（A 区过肩位）｜从祁念（右，前景）左肩与腰侧后方越肩拍卓琳（左偏中，蹲姿量尺，脸在焦点上）", NAMES)
    assert (a["azimuth"], a["height"], a["ots_from"], a["ots_to"]) == ("ots", "slightly_high", "祁念", "卓琳")
    assert "越过祁念的肩拍卓琳" in PV.angle_zh(a)
    a = PV.parse_angle("高机位从右前方俯拍（A 区高机位）", NAMES)
    assert (a["azimuth"], a["height"]) == ("front_right", "high")
    a = PV.parse_angle("机位在祁念右前 45°（环形灯一侧）、略低微仰", NAMES)
    assert (a["azimuth"], a["height"]) == ("front_right45", "slightly_low")


def test_focus_names_window_stops_at_next_person():
    field = "中景｜侧 45°｜三人前后错落：唐瑶前景侧身略虚、祁念与卓琳中景同在焦点上（卓琳在左侧半步之后），白幕前"
    sharp, soft = PV.focus_names(field, "", NAMES)
    assert set(sharp) == {"祁念", "卓琳"} and soft == ["唐瑶"]
    sharp, soft = PV.focus_names("中景｜过肩略俯｜从祁念（右，前景）左肩后方越肩拍卓琳（左偏中，蹲姿量尺，脸在焦点上）", "", ["卓琳", "祁念"])
    assert sharp == ["卓琳"]


def test_rewrite_negations_table_and_drop():
    t, negs = PV.rewrite_negations("白幕前，关着的环形灯架在右前景，没有正面补光，不是死白，没有多余的人")
    assert "熄灭的环形灯架" in t and "正面留在阴影里" in t and "保留灰阶渐变" in t
    assert "没有多余的人" not in t and negs == ["多余的人"]
    assert PV.rewrite_negations("无妆感，左手无名指一圈戒痕")[0] == "无妆感，左手无名指一圈戒痕"   # 不是否定句的词不动


def test_person_line_drops_identity_keeps_action_and_gaze():
    img = ("中景，侧 45° 机位，浅景深，影棚白幕前，卓琳站在画面左侧、比祁念靠后半步、脸在焦点上，卓琳穿酒红色西装套装、黑色丝质吊带衫，"
           "卓琳的黑色齐肩直发中分垂到肩头，卓琳哑光正红唇，卓琳的左手搭在透明亚克力椅的椅背上，卓琳的视线落在祁念和唐瑶并排的肩膀上，卓琳嘴唇张开；"
           "祁念站在画面中央、在焦点上，祁念穿黑色漆皮抹胸紧身短裙、黑色薄透丝袜，祁念裸妆、水光粉唇、灰绿色眼睛，祁念的右手搭在身侧白幕的弧面上，祁念嘴唇抿着；"
           "天花顶灯从上侧 45° 落在三个人的肩线上，另一侧黑旗压暗、没有正面补光")
    lead, per, tail = PV.person_segments(img, NAMES)
    assert lead[0] == "中景" and tail and "天花顶灯" in tail[0]
    line, negs = PV.person_line("卓琳", per["卓琳"], {"服装": "酒红色西装套装、黑色丝质吊带衫", "发": "黑色齐肩直发，中分", "妆": "哑光正红唇"}, "左", "中")
    assert line.startswith("卓琳（酒红色西装套装、黑色丝质吊带衫、黑色齐肩直发，中分、哑光正红唇），站在画面左侧")
    assert "穿酒红色" not in line and "齐肩直发中分垂到肩头" not in line and "哑光正红唇，" not in line.split("），", 1)[1]
    assert "卓琳的左手搭在透明亚克力椅的椅背上" in line and "卓琳的视线落在祁念和唐瑶并排的肩膀上" in line and line.endswith("嘴唇张开")
    assert "在画面左侧，站在" not in line        # 剧本已写画面左侧 → 不再加 cast 站位
    line2, _ = PV.person_line("祁念", per["祁念"], {}, "中", "中")
    assert line2.startswith("祁念，站在画面中央") and "裸妆" not in line2


def test_frame_count_sentence_by_faced_people():
    assert PV.frame_count_sentence(3).startswith("三人同框，三张脸都清晰入画")
    assert PV.frame_count_sentence(2).startswith("两人同框")
    assert PV.frame_count_sentence(1) == ""


def test_hidden_face_and_frame_sentence():
    """PS-MASTER 11-05 审 dump：过肩镜里只以肩 / 腰入画、只露、背影的人不算露脸"""
    assert PV.hidden_face("侧右｜站在白幕中央、在画面右侧前景以左肩和腰侧入画、略在焦外，右手搭白幕弧面") == (True, "左肩和腰侧")
    assert PV.hidden_face("侧右｜站在白幕左侧、脸在焦点上，左手搭椅背") == (False, "")
    assert PV.hidden_face("顾沉的背影在画面右侧远处，背对镜头") == (True, "背影")
    assert PV.hidden_face("只露出右手和软尺") == (True, "肩与背")
    assert PV.frame_sentence(["卓琳"], {"祁念": "左肩和腰侧"}) == "卓琳的脸清晰入画，祁念只以虚化的左肩和腰侧在前景"
    assert PV.frame_sentence(["卓琳", "祁念", "唐瑶"], {}) == PV.frame_count_sentence(3)
    s = PV.frame_sentence(["卓琳", "祁念"], {"顾沉": "背影"})
    assert s.startswith("两人同框") and "顾沉背对镜头的背影" in s
    assert PV.frame_sentence(["卓琳"], {}) == ""


def test_lighting_en_from_script_not_hardcoded():
    """AUDIT-RULES 11-05：L1 英文布光句按分镜 **灯光** 字段取动机光源 + 方向；模板默认句不许写死 ring light + front"""
    kv = PV.kv_field("动机光源=天花顶灯（上侧 45°）｜布光=主光天花顶灯从上侧 45° 冷白落三人肩线，另一侧黑旗负补光，人物比白幕亮一到两档，白幕落到中灰｜色温=4000K 冷白")
    s = PV.lighting_en_from(kv, "reality", "GENERIC")
    assert s.startswith("lit by the ceiling light as the motivated key from the upper side at 45 degrees, cool") and "negative fill" in s and "a stop or two brighter" in s
    kv2 = PV.kv_field("动机光源=环形灯架（右前方 45°）｜布光=主光环形灯从右前方 45° 亮起、暖金色高调，白幕明亮通透、向四周渐变｜色温=3200K 暖金")
    s2 = PV.lighting_en_from(kv2, "fantasy", "GENERIC")
    assert s2.startswith("lit by the ring light as the motivated key from the front right at 45 degrees, high-key warm golden") and "gradient" in s2
    assert PV.lighting_en_from({}, "fantasy", "GENERIC") == "GENERIC"
    assert PV.flat_light_hits(s2) == [] and PV.template_default_hits({"lighting_en": {"generic": {"fantasy": s2}}}) == []
    bad = {"lighting_en": {"fantasy": "lit by the warm ring light as the practical key from the front"}}
    assert PV.template_default_hits(bad)
    opt = PT2.options()
    assert PV.template_default_hits(opt) == [] and set(opt["lighting_en"]["generic"]) == {"fantasy", "reality"}
    assert "ring light" not in json.dumps(opt["lighting_en"]["generic"])


def test_lens_fallback_table_l192():
    """分镜没写 **镜头** → L-192 焦段表按镜头类型；写了照写"""
    assert PT2.lens_kind("中景", 2, False, None) == "two_shot" and PT2.lens_kind("中景", 1, True, None) == "ots_or_single_mcu"
    assert PT2.lens_kind("近景", 1, False, None) == "ots_or_single_mcu" and PT2.lens_kind("特写", 1, False, "face") == "closeup"
    assert PT2.lens_kind("中全景", 1, False, None) == "establishing" and PT2.lens_kind("特写", 1, False, "part") == "insert"
    sh = {"index": 1, "img_prompt": "中景，侧 45° 机位", "extras": [], "cast": []}
    L = PT2.lens_of(sh, n_faced=1, ots=True, subject=None, size="中景")
    assert (L["focal"], L["aperture"]) == ("85", "T1.4") and L["source"].startswith("L-192")
    assert PT2.lens_text(L) == ("85mm 镜头 T1.4", "85 mm lens at T1.4")
    Li = PT2.lens_of(sh, n_faced=1, ots=False, subject="part", size="特写")
    assert PT2.lens_text(Li)[0] == "100mm 微距镜头 T2"
    sh2 = {**sh, "extras": [{"label": "镜头", "text": "summicron_35_f2"}]}
    L2 = PT2.lens_of(sh2, n_faced=2, ots=True, subject=None, size="中景")
    assert L2["source"] == "script" and PT2.lens_text(L2)[0] == "35mm 镜头 f/2.8"


# ---------------------------------------------------------------- 核心：视频（官方写法）
def _vocab():
    from ns_agent import camera_norm as CN
    return {m["id"]: m for m in CN.vocab()["moves"]}


def test_camera_sentence_official_words_and_amp_shift():
    v = _vocab()
    she = ("she", "her", "her")
    assert PV.camera_sentence(v["push_in"], "small", None, she) == "The camera pushes in with small amplitude toward her face"
    assert PV.camera_sentence(v["push_in"], "large", "slow", she) == "The camera pushes in at slow speed toward her face"    # large → 中档不写幅度词
    assert PV.camera_sentence(v["push_in"], "medium", "normal", she) == "The camera pushes in with small amplitude toward her face"
    assert PV.camera_sentence(v["bolt_push_settle"], "medium", "fast", she) == \
        "The camera pushes in with large amplitude at fast speed within the first second, then holds a static shot for the rest of the shot"
    assert PV.camera_sentence(v["static"], None, None, she) == "The camera holds a static shot"
    assert PV.camera_sentence(None, None, None, she) == "The camera holds a static shot"
    # 横移 / 环绕候选：方向反写、不写幅度词；词表仍 disabled（L-129 不动）
    cand = PV.camera_sentence(v["truck"], "medium", "slow", she, direction="left", key="h3_official_candidate")
    assert cand == "The camera trucks right at slow speed, the studio background sliding to the left behind her"
    assert v["truck"]["enabled"] is False and v["arc"]["enabled"] is False and v["arc"].get("h3_official_candidate")


def test_vocab_l192_six_enabled_and_h3_official_present():
    """L-192（项目方 11-05）：白名单 6 种；truck / arc 仍 disabled 只留候选；6 种都有官方写法句"""
    v = _vocab()
    assert {k for k, m in v.items() if m.get("enabled")} == {"static", "push_in", "pull_out", "bolt_push_settle", "handheld_follow", "pedestal_up"}
    for k in ("static", "push_in", "pull_out", "pedestal_up", "bolt_push_settle", "handheld_follow", "truck", "arc"):
        assert v[k].get("h3_official"), k
    she = ("she", "her", "her")
    assert PV.camera_sentence(v["pull_out"], "small", "slow", she) == "The camera pulls out with small amplitude at slow speed, revealing more of the studio around her"
    assert PV.camera_sentence(v["pull_out"], "large", None, she) == "The camera pulls out, revealing more of the studio around her"
    assert PV.camera_sentence(v["pedestal_up"], "small", "slow", she) == "The camera pedestals up with small amplitude at slow speed, the floor dropping out of the bottom of the frame"
    assert PV.camera_sentence(v["handheld_follow"], None, None, she) == "The camera shakes slightly in a handheld tracking shot that follows her at shoulder height"


def test_l192_multi_person_whitelist():
    from ns_agent import camera_norm as CN
    # L-192 项目方原话“双人镜只用推 / 拉 / 固定 / 手持”；bolt 是否允许待项目方确认，未确认前不在多人白名单
    assert CN.multi_person_moves() == ["static", "push_in", "pull_out", "handheld_follow"]
    assert CN.multi_person_fallback("pedestal_up", 1, V2) == ("pedestal_up", None)
    mid, why = CN.multi_person_fallback("pedestal_up", 2, V2)
    assert mid == "push_in" and "L-192" in why
    assert CN.multi_person_fallback("bolt_push_settle", 3, V2)[0] == "push_in"
    assert CN.multi_person_fallback("arc", 2, V2)[0] == "push_in"
    assert CN.multi_person_fallback("static", 2, V2) == ("static", None) and CN.multi_person_fallback("pull_out", 2, V2) == ("pull_out", None)
    # v1 规范化路径同一规则（n_people 不给 = 旧行为不变）
    t = "The camera pedestals up with small amplitude as she turns."
    assert CN.normalize_video_prompt(t, "", V2)[0] == t
    new, ch = CN.normalize_video_prompt(t, "", V2, n_people=2)
    assert new.startswith("The camera pushes in with small amplitude as she turns") and ch[0]["move"] == "push_in" and "L-192" in ch[0]["why"]


def test_split_and_strip_camera_clauses():
    body = ("[Shot 1] Live-action, cinematic, shallow depth of field, a medium shot begins in the position, framing and lighting established by "
            "Picture 1, with a woman at the left. In the first two seconds, she is already mid-swing, her eyes on the shoulders, and the camera "
            "pushes in with small amplitude as the tape cracks straight and the on-screen woman (S1) says: <d>[Chinese] 站好。</d> her brow level. "
            "Then, around the third second, her lips close as the shot ends. They settle into the spacing established by Picture 2 at the end of the shot.")
    anchor, beats = PV.split_h3_body(body)
    assert anchor.endswith("with a woman at the left.") and beats.startswith("In the first two seconds")
    out, removed = PV.strip_camera_clauses(beats)
    assert removed == ["and the camera pushes in with small amplitude"]
    assert "her eyes on the shoulders as the tape cracks straight" in out and "<d>[Chinese] 站好。</d>" in out
    bolt = _vocab()["bolt_push_settle"]["template"]
    beats2 = ("In the first two seconds, her eyes still on the ring, and a robotic high-speed camera move: the camera whips in a fast, tight arc "
              "from her side to her front within the first second, then decelerates sharply and settles into a locked medium close-up, while she "
              "moves in super slow motion, hair drifting, as the ring light brightens, her chin lifting.")
    out2, removed2 = PV.strip_camera_clauses(beats2, [bolt])
    assert out2 == "In the first two seconds, her eyes still on the ring as the ring light brightens, her chin lifting." and len(removed2) == 1


def test_video_body_order_and_lint_clean():
    from ns_schema import h3_lint as L
    v = _vocab()
    h3 = ("[Shot 1] Live-action, cinematic, shallow depth of field, a medium shot from a side angle begins in the position, framing and lighting "
          "established by Picture 1, with a woman standing at the left, cool ceiling light from above. In the first two seconds, she is already "
          "mid-swing, and the camera pushes in with small amplitude as the tape cracks straight and the on-screen 35-year-old woman with a crisp "
          "bright alto voice, brisk pace (S1) says: <d>[Chinese] 站好。</d> her brow level. Then, around the third second, her lips close, the tape "
          "end turning between her nails as the shot ends. She settles into the medium-shot spacing established by Picture 2 at the end of the shot.")
    d = {"size": "中景", "angle_field": "侧 45°（A 区）", "comp_field": "",
         "chars": [{"name": "卓琳", "en": "a 35-year-old East Asian woman with sleek hair, thin lips", "look_en": "a wine-red tailored suit",
                    "x": "左", "depth": "中", "presence": "在画", "faced": True}],
         "h3_body": h3, "lighting_en": "lit by a cool ceiling key from the upper side at 45 degrees with negative fill on the other side",
         "constraint_en": "The face stays stable and sharp throughout", "move": v["push_in"], "move_id": "push_in", "amp": "small", "speed": None,
         "focus": "卓琳", "templates": [m["template"] for m in v.values() if m.get("template")]}
    body, rec = PV.video_body(d)
    sents = body.split(". ")
    assert sents[0].startswith("[Shot 1] Live-action, cinematic, shallow depth of field, a medium shot from a 45-degree side angle at eye level begins in "
                               "the position, framing and lighting established by Picture 1, with a 35-year-old East Asian woman in a wine-red tailored suit at frame left in the midground, lit by")
    assert sents[1] == "The camera pushes in with small amplitude toward her face"       # 运镜独立成句，紧跟构图句
    assert sents[2].startswith("The face stays stable") and "In the first two seconds" in sents[3]
    assert "cool ceiling light from above" not in body and rec["removed"] == ["and the camera pushes in with small amplitude"]
    text = f"{L.alignment_line(124)}\n\nintegrated_multimodal_description: {body}\n\noverall_soundscape: A tape measure snaps.\n\nnon_diegetic_music: N/A"
    res = L.lint_h3(text, 124, mode="fl2va", dialogue=["站好。"])
    assert not [r["rule_id"] for r in res if not r["ok"] and r.get("level") == "block"]
    hits = PV.flat_light_hits("bright ring light from the front flattening the shadows")
    assert "flattening the shadows" in hits and any("ring light from the front" in h for h in hits)
    assert PV.flat_light_hits("warm ring light from the front right at 45 degrees carving her cheekbones") == []   # 45° 侧前不算平光
    assert PV.flat_light_hits(body) == []


# ---------------------------------------------------------------- 开关默认关 / 签名
def test_switch_default_v1_for_all_runs(monkeypatch):
    monkeypatch.delenv("NS_PROMPT_TEMPLATE", raising=False)
    rs = json.loads((ROOT / "config/compile/run_style.json").read_text(encoding="utf-8"))
    assert rs["runs"][V2]["prompt_template"] == {k: v for k, v in rs["runs"]["smoke_v2"]["prompt_template"].items()}
    # 11-05 项目方“基于最新架构和规则重跑 ep01”→ series10_v2 / smoke_v2 开 v2；其余剧仍 v1
    for run in (V2, "smoke_v2"):
        assert PT2.image_on(run) and PT2.video_on(run), run
    for run in ("series10_v1", None):
        assert not PT2.image_on(run) and not PT2.video_on(run), run
    with PT2.force(image="v1"):
        assert not PT2.image_on(V2) and PT2.video_on(V2)
    assert PT2.image_on(V2)
    monkeypatch.setenv("NS_PROMPT_TEMPLATE", "v2")
    assert PT2.image_on(V2) and PT2.video_on("series10_v1")
    from ns_recipes import prompt_v2 as RPV2
    assert RPV2.on(V2)
    monkeypatch.delenv("NS_PROMPT_TEMPLATE")
    assert RPV2.on(V2) and not RPV2.on("series10_v1")


def test_job_sig_and_inputs_sig_change_with_template(monkeypatch, tmp_path):
    class Paths:
        run = tmp_path
        root = tmp_path

    def sig(job):
        monkeypatch.setattr(PR, "jl", lambda p, d=None: {"jobs": [job]})
        return PR.job_sig(Paths, "ep01-S1"), PR.shot_inputs_sig(Paths, "ep01-S1")
    base = {"shot": "ep01-S1", "prompt": "x", "compiler_inputs_sha": "a", "refs": []}
    s1, i1 = sig(base)
    s2, i2 = sig({**base, "prompt_template": "v2"})
    assert s1 != s2 and "template" not in i1 and i2["template"] == "v2"
    assert sig(dict(base))[0] == s1                       # v1 不加段，旧签名不变


# ---------------------------------------------------------------- 真实 V2 数据（psm6）：出图 + 视频两条路
@pytest.fixture(scope="module")
def psm6():
    from ns_agent import asset_refs as AR
    if not PSM6.is_file() or not AR.manifest_rel(V2) or not (ROOT / AR.manifest_rel(V2)).is_file():
        pytest.skip("psm6 / V2 资产包缺")
    import import_script as IS
    base = ROOT / "data/import/runs/series10_v2/script_v2.json"
    if not base.is_file():
        pytest.skip("series10_v2 导入稿缺")
    r = IS.merge_into(base, IS.import_script(PSM6, None), single_source=True)
    from ns_schema.script import ScriptImport
    s = ScriptImport.model_validate_json(r.model_dump_json())
    return s, next(e for e in s.episodes if e.number == 1)


def _shot(ep, n):
    return next(x for x in ep.shots if x.index == n)


def test_real_image_prompt_v2_vs_v1(psm6):
    s, e = psm6
    from ns_agent import frame_job as FJ
    from ns_agent.gen_contract import preflight as PF, style as ST
    # S4 过肩：祁念只以左肩和腰侧入画 → 不算露脸（PS-MASTER 11-05）；人数闸 people_range 仍按 cast 在画 / 局部 计，不受影响
    for n, count, extra_neg in ((1, "三人同框", "第四个人"), (4, "卓琳的脸清晰入画，祁念只以虚化的左肩和腰侧在前景", "第三个人")):
        sh = _shot(e, n)
        with PT2.force(image="v1"):
            v1 = FJ.build_first(V2, e, sh, s.globals)
        assert "prompt_template" not in v1 and "template=" not in v1["compiled_by"]
        with PT2.force(image="v2"):
            job = FJ.build_first(V2, e, sh, s.globals)
        p, pre = job["prompt"], job["asset_refs"]["slots"][-1]["line"]
        assert job["prompt_template"] == "v2" and "prompt_template_v2" in job["compiled_by"]
        assert p.startswith(v1["prompt"][:len(pre)]) or pre in p          # 参考槽标注原样在前
        body = p[p.find(pre) + len(pre):]
        assert body.startswith("中景（膝盖以上），")                            # ① 机位首句紧跟参考槽标注
        assert "35mm 镜头 f/2.8" in body and "（a medium shot " in body
        assert count in body and "两人同框" not in body.replace(count, "")   # ⑤ 按露脸人数
        assert "她这一镜" in p and "他这一镜" not in p                          # 参考板代词按性别（卓琳 / 祁念 / 唐瑶）
        from tools.vqa import accept as ACC
        assert ACC.people_range(job["cast"]) == ((3, 3) if n == 1 else (1, 2))   # 人数闸：不露脸的人计上限不计下限（psm6 S4 祁念只以肩腰入画）
        assert "【" not in body and "幻想段" not in body and "现实段" not in body   # ② 无角色锁块；③ 无双段原文
        assert "光线：" in body and "黑旗" in body and "4000K" in body        # ③ 一句布光（L1 句）
        assert "没有正面补光" not in body and "正面留在阴影里" in body         # ④ 否定 → 正向
        assert "看镜头" in job["negative"] and extra_neg in job["negative"]   # ④ 关键否定进负面词
        assert ST.image_suffix(V2, ST.segment_of(sh)[0]) in p and len(p) < len(v1["prompt"]) * 0.75
        req = {k: job.get(k) for k in ("model", "cast", "prompt", "refs", "asset_refs", "loras", "compiled_by", "route", "route_reasons")}
        req.update(kind="image", project=V2, framing_project=V2, shot_id=f"{V2}-ep01-S{n}")
        pf = PF.check(req)
        assert pf.ok, pf.reasons()
    sys.path.insert(0, str(ROOT / "tools/qa"))
    import l1_prompt_audit as A
    assert A.scan(p, "reality")[0] == []


def test_real_video_prompt_v2_two_paths_agree(psm6):
    s, e = psm6
    from ns_agent import compiler as C, camera_norm as CN
    from ns_agent.gen_contract import style as ST
    from ns_schema import h3_lint as L
    from ns_recipes.spec_import import specs_from_import
    from ns_recipes import prompt as RP, prompt_v2 as RPV2
    specs = {x.index: x for x in specs_from_import(s, 1, with_assets=False)}
    # S2 = bolt_push_settle（2 人在画；L-192 原话多人只 4 种，bolt 待项目方确认）→ 退回 push_in
    for n, cam in ((1, "The camera pushes in with small amplitude toward her face."),
                   (2, "The camera pushes in with small amplitude toward her face."),
                   (13, "The camera pushes in with small amplitude toward his face.")):
        sh = _shot(e, n)
        seg = ST.segment_of(sh)[0]
        with PT2.force(video="v1"):
            c1 = C.compile_shot(e, sh, s.globals, set(), image_style=ST.image_suffix(V2, seg), framing_project=V2)
        assert c1.h3_template == ""
        with PT2.force(video="v2"):
            c = C.compile_shot(e, sh, s.globals, set(), image_style=ST.image_suffix(V2, seg), framing_project=V2)
        assert c.h3_template == "v2" and len(c.h3_norm) == 1 and c.h3_norm[0]["rule"] == "K-REN-801"
        if n == 2:
            assert "L-192" in c.h3_norm[0]["why"] and c.h3_norm[0]["move"] == "push_in"
        assert CN.denormalize(c.video_prompt, c.h3_norm) == sh.h3_prompt.strip("\n")       # 倒回 = 剧本原文
        body = L.parse_h3(c.video_prompt)["fields"][L.FIELDS[0]]
        sents = body.split(". ")
        assert "established by Picture 1" in sents[0] and sents[1] + "." == cam                 # 运镜句紧跟构图句
        assert "In the first" in body and "as the shot ends" in body and body.endswith("at the end of the shot.")
        res = L.lint_h3(c.video_prompt, c.h3_frames, mode="fl2va", dialogue=[d.text for d in sh.dialogue if d.text])
        assert not [r["rule_id"] for r in res if not r["ok"] and r.get("level") == "block"]
        assert PV.flat_light_hits(c.video_prompt) == []
        RPV2._FORCE["video"] = "v2"
        try:
            b2 = RP.build_base(specs[n], {"prompt": {}}, "fl2va", specs[n].frames)
        finally:
            RPV2._FORCE.clear()
        assert b2["fields"][L.FIELDS[0]] == body                     # 生产路径（ns_recipes）与画布路径（compile_shot）同一句
        assert any("prompt_template v2" in x for x in b2["notes"])


# ---------------------------------------------------------------- PS-MASTER 11-05（psm7 复审）：光学行优先 / 背影主语归属 / 人数闸下限按露脸
PSM7 = ROOT / "data/pipeline/runs/series10_v2/staging/P4_ep01.L3_psm7.md"


def test_back_in_text_subject_by_clause():
    """“卓琳蹲在祁念左前、背对镜头”：背对的主语是卓琳（“在祁念左前”的祁念是宾语），不能记到祁念头上（psm7 S4 preflight I2）"""
    from ns_agent import asset_refs as AR
    img = "中近景，过肩略仰，祁念站在白幕中央、脸在焦点上，祁念的右手搭白幕弧面；卓琳蹲在祁念左前、背对镜头，只露右肩与后脑，卓琳的右手捏尺头"
    names = ["祁念", "卓琳"]
    assert AR.back_in_text("卓琳", img, names) and not AR.back_in_text("祁念", img, names)
    old = "顾沉的背影在画面右侧远处，背对镜头朝走廊暗处走；林晚站在前景"            # 没人名的小句沿用上一小句主语（K-REN-957 原例）
    assert AR.back_in_text("顾沉", old, ["林晚", "顾沉"]) and not AR.back_in_text("林晚", old, ["林晚", "顾沉"])
    assert not AR.back_in_text("林晚", "林晚看着顾沉的背影", ["林晚", "顾沉"]) and AR.back_in_text("顾沉", "林晚看着顾沉的背影", ["林晚", "顾沉"])
    assert AR.clause_subject("卓琳蹲在祁念左前、背对镜头", names) == "卓琳" and AR.clause_subject("背对镜头走开", names, "顾沉") == "顾沉"


def test_people_range_face_hidden_counts_upper_only():
    from tools.vqa import accept as ACC
    cast = [{"name": "祁念", "presence": "在画"}, {"name": "卓琳", "presence": "在画", "face_hidden": True, "hidden_part": "右肩与后脑"}]
    assert ACC.people_range(cast) == (1, 2)
    assert ACC.people_verdict(1, cast) is None and ACC.people_verdict(2, cast) is None and "多画了人" in ACC.people_verdict(3, cast)
    assert ACC.people_range([{"presence": "在画"}] * 3) == (3, 3)                                  # 没标 face_hidden 的口径不变


def test_lens_of_prefers_optics_line():
    """K-WRT-816：**光学** 行（焦段｜T｜高度=）> **镜头** id > lenses.yaml by_kind"""
    sh = {"index": 4, "img_prompt": "中近景，过肩略仰", "cast": [],
          "extras": [{"label": "镜头", "text": "arri_cine_50_t2"}, {"label": "光学", "text": "85mm｜T1.4｜高度=1.1m（卓琳蹲姿肩高，略仰拍祁念）"}]}
    L = PT2.lens_of(sh, n_faced=1, ots=True, size="中近景")
    assert L["source"] == "script 光学" and PT2.lens_text(L) == ("85mm 镜头 T1.4", "85 mm lens at T1.4") and "光斑" in L["dof_zh"]
    sh2 = {**sh, "extras": [{"label": "镜头", "text": "arri_cine_50_t2"}]}
    assert PT2.lens_text(PT2.lens_of(sh2, n_faced=1, ots=True, size="中近景"))[0] == "50mm 镜头 T2"
    sh3 = {**sh, "extras": [{"label": "光学", "text": "100mm｜T2"}]}
    assert PT2.lens_text(PT2.lens_of(sh3, size="大特写", subject="part"))[0] == "100mm 微距镜头 T2"     # 焦段 + T 对上登记档 → 带微距


@pytest.fixture(scope="module")
def psm7():
    from ns_agent import asset_refs as AR
    if not PSM7.is_file() or not AR.manifest_rel(V2) or not (ROOT / AR.manifest_rel(V2)).is_file():
        pytest.skip("psm7 / V2 资产包缺")
    import import_script as IS
    import runs as RN
    base = RN.import_path(V2, ROOT)
    if not base.is_file():
        pytest.skip("series10_v2 导入稿缺")
    r = IS.merge_into(base, IS.import_script(PSM7, None), single_source=True)
    from ns_schema.script import ScriptImport
    s = ScriptImport.model_validate_json(r.model_dump_json())
    return s, next(e for e in s.episodes if e.number == 1)


def test_real_psm7_s4_ots_hidden_lens_and_people(psm7):
    s, e = psm7
    from ns_agent import frame_job as FJ
    from ns_agent.gen_contract import preflight as PF
    from tools.vqa import accept as ACC
    s1, s4 = _shot(e, 1), _shot(e, 4)
    assert PT2.hidden_people(s1) == {} and PT2.hidden_people(s4) == {"卓琳": "右肩与后脑"}
    assert ACC.people_range(FJ.cast_of(s1)) == (3, 3) and ACC.people_range(FJ.cast_of(s4)) == (1, 2)
    with PT2.force(image="v2"):
        job = FJ.build_first(V2, e, s4, s.globals)
    p = job["prompt"]
    assert "祁念的脸清晰入画，卓琳只以虚化的右肩与后脑在前景" in p and "两人同框" not in p
    assert "85mm 镜头 T1.4" in p and "75mm" not in p and "f/2" not in p.split("电影剧照")[0]
    assert job["prompt_template_trace"]["lens"]["source"] == "script 光学"
    req = {k: job.get(k) for k in ("model", "cast", "prompt", "refs", "asset_refs", "loras", "compiled_by", "route", "route_reasons")}
    req.update(kind="image", project=V2, framing_project=V2, shot_id=f"{V2}-ep01-S4")
    pf = PF.check(req)
    assert pf.ok, pf.reasons()                                     # 背影归属修好后 I2 不再失败
    v1 = FJ.build_first(V2, e, s4, s.globals)                      # v1 路径同样受益（cast.face_hidden / 背影判定）
    assert any(c.get("face_hidden") for c in v1["cast"] if c["name"] == "卓琳")
