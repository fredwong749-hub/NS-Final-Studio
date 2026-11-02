"""DIRECTOR loop（2026-11-02）：成片评分 / 导演层 / 后期层 / 口型重出 的规则检查（K-REV-801–804、K-EDT-801–805、K-EDT-811–815、K-WRT-801–803）。
全部用合成夹具，不读会变的真实剧本 / 成片（K-OPS-C02）。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "director"))
sys.path.insert(0, str(ROOT / "services" / "post"))

import cut_plan as CP  # noqa: E402
import film_score as FS  # noqa: E402
import lip_redo as LR  # noqa: E402
import post_pass as PP  # noqa: E402


def _shot(i, link="接力", carry="动作｜手", cue="延续，强度1", motion="lnwan01，camera push in 小幅推近，她抬手", cast=None, dialogue=None,
          scene="sk_a", sound=""):
    return {"index": i, "link": link, "link_carry": carry, "music_cue": cue, "motion_prompt": motion, "scene_id": scene,
            "cast": cast or [{"name": "林晚", "presence": "在画", "x": "右"}], "dialogue": dialogue or [], "sound": sound,
            "img_prompt": "深夜写字楼", "scene_detail": ""}


# ---- K-REV-801 / 802：小项分 = 5 × 通过 / 测到；未测不进分母
def test_item_score_counts_only_measured():
    it = FS.item_score([FS.C("a", "x", True), FS.C("b", "y", False), FS.C("c", "z", None)])
    assert it["score"] == 2.5 and it["measured"] == 2 and it["total"] == 3
    assert FS.item_score([FS.C("a", "x", None)])["score"] is None


def test_rubric_has_15_items_in_4_categories():
    cats = {}
    for k, (c, _) in FS.ITEMS.items():
        cats.setdefault(c, []).append(k)
    assert set(cats) == set(FS.CATS)
    assert sorted(len(v) for v in cats.values()) == [3, 4, 4, 4]


def test_cut_list_uses_pieces():
    tl = {"shots": [{"start_s": 0, "duration_s": 4.5, "pieces": [[0, 3, 1], [3, 4.5, 1.15]]}, {"start_s": 4.5, "duration_s": 2.0}]}
    assert FS.cut_list(tl) == [3.0, 1.5, 2.0]
    assert FS.planned_cuts(tl) == [0.0, 3.0, 4.5]


# ---- K-EDT-805：画内对白 TTS 兜底 → 送回重出；旁白不算
def test_lip_redo_flags_onscreen_tts_fallback_only():
    tl = {"episode": 1, "shots": [{"index": 1, "shot": "ep01-S1"}, {"index": 2, "shot": "ep01-S2"}],
          "speech": [{"shot": 1, "kind": "voiceover"}, {"shot": 2, "kind": "dialogue"}],
          "h3_dialogue": [{"shot": 1, "dialogue": "tts_fallback"}, {"shot": 2, "dialogue": "tts_fallback", "fallback_reason": "cer"}]}
    rows = LR.blocking(tl)
    assert [r["shot"] for r in rows] == ["ep01-S2"] and rows[0]["rule"] == "K-EDT-805"


# ---- K-EDT-811：运镜在 Pika 范围内（一种、小幅、不拉远 / 环绕；大动作不叠运镜）
def test_camera_only_enabled_vocab_moves():   # K-EDT-811 / L-107：只从运镜词表 enabled 的选，decider=code
    CN = CP._cn()
    ep = {"number": 1, "shots": [_shot(1, motion="x，camera pull out 缓慢拉远，她坐着"),
                                 _shot(2, motion="x，camera arc shot 小幅度环绕，她站起走向门口"),
                                 _shot(3, cue="推到高点，强度3", motion="x，static shot，她看着他")]}
    for s in ep["shots"]:
        s["img_prompt"] = "lnwan01，中景，侧面机位"
    p = CP.plan_episode(ep)
    for s in p:
        assert CN.is_enabled(s["camera"]["move"]) and s["camera"]["decider"] == "code"
        assert "slow" not in s["camera"]["clause_en"].lower()
    assert p[1]["camera"]["move"] == "static"         # 大动作
    if CN.is_enabled("push_in"):
        assert p[2]["camera"]["move"] == "push_in"    # 高点：第一个 enabled 的高点运镜
    if not CN.is_enabled("pull_out"):
        assert any("disabled" in f for f in p[0]["flags"])


def test_vocab_schema():   # 词表每条必有字段；enabled 的必须有模板和 A/B 结果（baseline / pass）
    import yaml
    v = yaml.safe_load((ROOT / "config/director/camera_moves.yaml").read_text(encoding="utf-8"))
    ids = [m["id"] for m in v["moves"]]
    assert len(ids) == len(set(ids)) and "static" in ids
    for m in v["moves"]:
        assert {"zh", "en", "aliases", "enabled", "reason", "ab", "conflicts", "split"} <= set(m), m["id"]
        if m["enabled"]:
            assert m["template"] and m["template"].startswith("The camera") and m["ab"]["status"] in ("baseline", "pass"), m["id"]
            assert "slow" not in m["template"].lower()
        for c in m["conflicts"]:
            assert c in ids, (m["id"], c)


# ---- K-EDT-812 / 814：转场按衔接字段；J / L-cut
def test_transitions_and_jl():
    say = [{"speaker": "顾沉", "text": "x"}]
    ep = {"number": 1, "shots": [_shot(1), _shot(2, carry="视线｜门口"), _shot(3, dialogue=say),
                                 _shot(4, link="同场换机位", carry="无"), _shot(5, link="换场", scene="sk_b"),
                                 _shot(6, link="换场", scene="sk_c")]}
    ep["shots"][5]["scene_detail"] = "第二天清晨"
    p = CP.plan_episode(ep)
    assert [s["transition_in"]["type"] for s in p] == ["开场", "视线匹配切", "动作匹配切", "硬切", "声音先行", "叠化"]
    assert p[2]["j_cut_s"] == CP.J_CUT_S          # 这一镜开口
    assert p[3]["l_cut_s"] == CP.L_CUT_S          # 上一句尾音盖到反应镜
    assert p[4]["j_cut_s"] == CP.SOUND_LEAD_S


# ---- K-EDT-813：刀长随强度；第一镜 ≤3 s
def test_pace_by_intensity():
    ep = {"number": 1, "shots": [_shot(1, cue="强度3"), _shot(2, cue="强度3"), _shot(3, cue="强度1")]}
    p = CP.plan_episode(ep)
    assert p[0]["cut"]["target_s"][1] <= 3.0
    assert p[1]["cut"]["target_s"] == list(CP.PACE[3])
    assert p[2]["cut"]["target_s"][0] > p[1]["cut"]["target_s"][1] - 1e-9 or p[2]["cut"]["target_s"][0] >= 3.0


# ---- K-EDT-815：越轴提示
def test_axis_flip_flagged():
    a = [{"name": "林晚", "presence": "在画", "x": "左"}, {"name": "顾沉", "presence": "在画", "x": "右"}]
    b = [{"name": "林晚", "presence": "在画", "x": "右"}, {"name": "顾沉", "presence": "在画", "x": "左"}]
    p = CP.plan_episode({"number": 1, "shots": [_shot(1, cast=a), _shot(2, link="同场换机位", cast=b)]})
    assert any("越轴" in f for f in p[1]["flags"])
    assert p[0]["eyeline"]["林晚"] == "toward frame-right"


# ---- K-WRT-801–803：写作格式 lint（只查格式）
def test_writer_lint():
    ep = {"number": 1, "shots": [_shot(1, motion="x，camera push in 缓慢推近，y"), _shot(2, carry="无"), _shot(3, cue="延续")]}
    ids = [r["id"] for r in CP.lint_episode(ep)]
    assert ids.count("K-WRT-801") == 1 and ids.count("K-WRT-802") == 1 and "K-WRT-803" in ids


# ---- K-EDT-804：配乐强度跟剧本情绪节拍
def test_music_intensity_from_script():
    cues = [{"shot": 1, "action": "enter", "intensity": 2}, {"shot": 3, "action": "continue", "intensity": 2}]
    shots = [_shot(1, cue="进入，强度1"), _shot(2, cue="延续，强度1"), _shot(3, cue="渐强，强度2"), _shot(4, cue="推到高点，强度3")]
    m = CP.merge_music_intensity(cues, shots)
    assert [c["intensity"] for c in m] == [1, 2, 3]
    assert m[1]["action"] == "swell" and m[2]["action"] == "swell" and m[2]["shot"] == 4


# ---- K-EDT-802：音效按【声音】关键词挑素材、只用登记过许可证的素材
def test_sfx_plan_and_license(tmp_path, monkeypatch):
    if not PP.lib_files("footstep_concrete"):
        import pytest
        pytest.skip("data/sfx_lib 没有 Kenney 素材")
    tl = {"shots": [{"index": 1, "shot": "ep01-S1", "start_s": 0.0, "duration_s": 4.0},
                    {"index": 2, "shot": "ep01-S2", "start_s": 4.0, "duration_s": 4.0}]}
    ss = {1: _shot(1, sound="空调低鸣，皮鞋踏地声由远及近后停住；【配乐】延续"), 2: _shot(2, sound="衣料轻响，轻浅呼吸声，奇怪的嗡嗡")}
    ev, beds, um = PP.plan_sfx(ss, tl, lambda s: "sk_a")
    assert sum(1 for e in ev if "footstep" in Path(e["file"]).name) >= 3
    assert any("cloth" in Path(e["file"]).name for e in ev)
    assert beds and beds[0]["kind"] == "hvac" and beds[0]["end_s"] == 8.0
    assert any("嗡嗡" in u["text"] for u in um)
    monkeypatch.setattr(PP, "LICENSES", tmp_path / "LICENSES.json")
    reg = PP.register_licenses()
    assert all(v["commercial_ok"] for v in reg["packs"].values())


# ---- K-EDT-801：LUT 只定调，不改曝光（中灰偏移小）
def test_lut_is_subtle(tmp_path, monkeypatch):
    monkeypatch.setattr(PP, "LUT_DIR", tmp_path)
    for k in PP.LOOKS:
        p = PP.make_lut(k, n=9)
        rows = [list(map(float, ln.split())) for ln in p.read_text().splitlines() if ln[:1].isdigit()]
        a = np.array(rows).reshape(9, 9, 9, 3)
        assert abs(a[4, 4, 4].mean() - 0.5) < 0.03
        assert a.min() >= 0 and a.max() <= 1


# ---- K-EDT-816：合成落点（ns_post.director）——关时不改行为；开时刀长 / J-cut / 配乐强度按导演规格
def test_assemble_director_hooks(monkeypatch):
    from ns_post import director as D
    from ns_post.music import Cue
    monkeypatch.setenv("NS_DIRECTOR", "0")
    assert not D.enabled()
    assert D.shot_max_s({1: {"cut": {"target_s": [1.5, 2.5]}, "j_cut_s": 0.4}}, 1, 4.5) == 4.5
    monkeypatch.setenv("NS_DIRECTOR", "1")
    monkeypatch.setattr(D, "cfg", lambda: {"enabled": True, "music_min_intensity": 2})
    plan = {1: {"cut": {"target_s": [1.5, 2.5]}, "j_cut_s": 0.4}}
    assert D.shot_max_s(plan, 1, 4.5) == 2.0 and D.jcut_s(plan, 1, 0.3) == 0.4 and D.jcut_s(plan, 2, 0.3) == 0.3
    shots = [_shot(1, cue="强度1"), _shot(2, cue="强度1"), _shot(3, cue="推到高点，强度3"), _shot(4, cue="强度1")]
    cues = [Cue(shot=1, start_s=0.0, action="enter", intensity=2), Cue(shot=4, start_s=9.0, action="continue", intensity=2)]
    out, log = D.merge_cues(cues, shots, [0.0, 3.0, 6.0, 9.0])
    assert [(c.shot, c.intensity) for c in out] == [(1, 2), (3, 3), (4, 2)]   # 下限 2（整集统一 BGM 不压到 −10 dB），高点补 swell
    assert out[1].action == "swell" and out[1].source == "director"


def test_finish_disabled_is_noop(monkeypatch, capsys):
    import finish as F
    monkeypatch.setenv("NS_DIRECTOR", "0")
    assert F.main(["data/does_not_exist.mp4"]) == 0
    assert '"enabled": false' in capsys.readouterr().out


# ---- K-REN-801（待总调度定接线）：运镜句规范化映射
def test_camera_norm_mapping(monkeypatch):   # K-REN-801：按词表 enabled 判定（不写死）
    sys.path.insert(0, str(ROOT / "services" / "agent"))
    from ns_agent import camera_norm as CN
    monkeypatch.setattr(CN, "is_enabled", lambda mid: mid in ("static", "push_in"))
    f = lambda c, big=False: CN.norm_clause(c, big)   # noqa: E731
    assert f("pulls out with small amplitude") == "holds a static shot"
    assert f("performs an arc shot with small amplitude") == "pushes in with small amplitude"
    assert f("performs an arc shot with small amplitude", True) == "holds a static shot"
    assert f("pushes in slowly with medium amplitude") == "pushes in with small amplitude"
    assert f("tilts up at slow speed") == "holds a static shot"            # tilt_up 未通过 A/B → 固定
    monkeypatch.setattr(CN, "is_enabled", lambda mid: mid in ("static", "push_in", "tilt_up"))
    assert f("tilts up at slow speed") == "tilts up with small amplitude"  # 通过后按模板
    monkeypatch.setattr(CN, "enabled", lambda: True)
    t, ch = CN.normalize_video_prompt("x. The camera pulls out with small amplitude as she sits. y", "")
    assert "holds a static shot as she sits" in t and len(ch) == 1 and ch[0]["move"] == "static" and ch[0]["rule"] == "K-REN-801"


# ---- K-EDT-817：交付闸门（decider = code）
def test_delivery_gate():
    import finish as F
    ok = F.delivery_gate({"post": "x_post.mp4", "film_score": {"total_50": 28.5}, "film_score_post": {"total_50": 32.5}, "lip_redo": [], "errors": []})
    assert ok["deliver"] == "post" and ok["final_ok"] and ok["decider"] == "code"
    down = F.delivery_gate({"post": "x_post.mp4", "film_score": {"total_50": 30}, "film_score_post": {"total_50": 29}, "lip_redo": [], "errors": []})
    assert down["deliver"] == "raw"
    lip = F.delivery_gate({"post": "x_post.mp4", "film_score": {"total_50": 28}, "film_score_post": {"total_50": 30}, "lip_redo": [{"shot": "ep01-S6"}], "errors": []})
    assert lip["deliver"] == "post" and not lip["final_ok"] and "ep01-S6" in lip["why"][0]


def test_split_standup_is_action_match():   # K-WRT-704（VIDEO-RCA）拆镜后的衔接 = 动作匹配切
    p = CP.plan_episode({"number": 1, "shots": [_shot(1), _shot(2, carry="动作｜起身")]})
    assert p[1]["transition_in"]["type"] == "动作匹配切" and p[1]["transition_in"]["split"] == "K-WRT-704"


def test_recipe_prompt_records_camera_norm(monkeypatch):   # K-REN-801：Pika 作业提示词规范化 + notes 记来源
    sys.path[:0] = [str(ROOT / "services" / "recipes"), str(ROOT / "packages" / "schema")]
    from ns_recipes import prompt as PR
    monkeypatch.setattr(PR._camera_norm(), "enabled", lambda: True)
    body = "[Shot 1] Live-action, a medium shot begins. The camera pulls out with small amplitude as she sits. At 00:02.000, she looks up."

    class Spec:
        id = "t"
        h3 = type("H", (), {"text": "x"})()
        audio = type("A", (), {"soundscape_en": "rain"})()
    monkeypatch.setattr(PR, "split_fields", lambda t: ("", {"integrated_multimodal_description": body}))
    out = PR.build_base(Spec(), {"prompt": {}}, "fl2va", 97)
    assert "The camera holds a static shot as she sits" in out["fields"]["integrated_multimodal_description"]
    assert any(n.startswith("K-REN-801") for n in out["notes"])


def test_vidgen_consumes_lip_redo(tmp_path, monkeypatch):   # K-EDT-805：走首帧换版同一条作废路径，不计次，每条请求只用一次
    import threading
    sys.path.insert(0, str(ROOT / "tools" / "series10_video"))
    import vidgen as VG
    req = tmp_path / "redo.json"
    req.write_text(json.dumps({"requests": [{"shot": "ep01-S6", "timeline": "t.json", "at": "x", "status": "pending",
                                             "reason": LR.REASON}]}), encoding="utf-8")
    monkeypatch.setattr(VG, "LIP_REDO", req)
    monkeypatch.setattr(VG, "log", lambda *a, **k: None)
    ev = []
    R = type("R", (), {"lock": threading.Lock(), "host": "gpu33", "event": lambda self, k, **kw: ev.append(k)})()
    r = {"renders": [{"variant": "v1", "state": "scored"}], "status": "done", "chosen": "v1"}
    VG.Runner.check_lip_redo(R, "ep01-S6", r)
    assert r["status"] == "pending" and r["renders"] == [] and r["superseded"][0]["rule"] == "K-EDT-805" and ev == ["lip_redo"]
    r["renders"] = [{"variant": "v1", "state": "scored"}]
    r["status"] = "done"
    VG.Runner.check_lip_redo(R, "ep01-S6", r)          # 同一条请求不再用第二次
    assert r["status"] == "done"


def test_a3_v7_caliber_1102():   # 总调度 11-02 V7 口型口径：台词段相关 ≥ 线，或张嘴占比 ≥0.3 且开合幅度达标
    th = {"corr_min": 0.3, "open_thr": 0.035}
    assert FS.v7_pass({"mode": "sync", "corr": 0.41, "open_frac": 0.0, "aperture_p90": 0.01, "th": th}) is True
    assert FS.v7_pass({"mode": "sync", "corr": 0.12, "open_frac": 0.35, "aperture_p90": 0.05, "th": th}) is True
    assert FS.v7_pass({"mode": "sync", "corr": 0.12, "open_frac": 0.35, "aperture_p90": 0.02, "th": th}) is False
    assert FS.v7_pass({"mode": "sync", "corr": 0.12, "open_frac": 0.1, "aperture_p90": 0.05, "th": th}) is False
    assert FS.v7_pass({"status": "未测"}) is None and FS.v7_pass({"mode": "closed", "status": "通过"}) is None
    assert FS.v7_pass({"caliber": "v7-1102", "status": "不通过", "corr": 0.9, "th": th}) is False   # VQAGATE 新版输出优先


def test_camera_ab_judge_and_writeback(tmp_path):   # K-REV-806：A/B 判定（decider=code）与词表回写只动三行
    import camera_ab as CA
    good = {"score": {"mean": 0.9, "cuts": [], "identity": {"林晚": {"sface_med": 0.55, "sface_p10": 0.45}},
                      "v6": {"dup_side_frac": 0.0, "extra_hand_frac": 0.0, "people": 1}, "J4": 1.1, "J4_z": 1.0, "size_measured": "中景"}}
    assert CA.judge(good)["pass"] is True
    bad = json.loads(json.dumps(good))
    bad["score"]["v6"]["dup_side_frac"] = 0.4
    bad["score"]["size_measured"] = "全景"
    j = CA.judge(bad)
    assert j["pass"] is False and any(f.startswith("AB3") for f in j["fails"]) and any(f.startswith("AB5") for f in j["fails"])
    assert CA.judge({"score": {}})["pass"] is None
    txt = (ROOT / "config/director/camera_moves.yaml").read_text(encoding="utf-8")
    new = CA.set_move(txt, "arc", False, {"status": "fail"}, "Pika 环绕易分身")
    import yaml
    a = next(m for m in yaml.safe_load(new)["moves"] if m["id"] == "arc")
    assert a["enabled"] is False and a["ab"]["status"] == "fail" and a["reason"] == "Pika 环绕易分身"
    assert len(new.splitlines()) == len(txt.splitlines())


def test_ab_runner_single_lane_config(tmp_path):   # D9：A/B 执行器读配置的单道版本，借用名单外的道拒绝启动
    import ab_runner as AR
    import pytest
    c = {"lane": "gpu36:1", "port": 8189, "out": "/x/gpu1", "client_prefix": "director-", "dedicated": True, "borrowed_lanes": ["gpu36:1"]}
    p = tmp_path / "c.json"
    p.write_text(json.dumps(c), encoding="utf-8")
    assert AR.load_cfg(p)["port"] == 8189
    p.write_text(json.dumps({**c, "lane": "gpu36:0"}), encoding="utf-8")
    with pytest.raises(SystemExit):
        AR.load_cfg(p)
    sr = type("SR", (), {"PORT": 8190, "OUT": "", "LANES": [(8188, "a")], "CLIENT": "videorca-", "prod_ready": staticmethod(lambda: True)})()
    AR.configure(sr, c)
    assert sr.PORT == 8189 and sr.LANES == [] and sr.CLIENT == "director-" and sr.prod_ready() is False
    sr2 = type("SR", (), {"prod_ready": staticmethod(lambda: True)})()
    AR.configure(sr2, {**c, "dedicated": False})
    assert sr2.prod_ready() is True


# ---- K-EDT-818 / K-REN-802 / 803 / K-WRT-806：镜头语言 v2 编译（合成夹具）
def _v2_shot(img, size="中景", cast=None, dialogue=None, cue="强度1", h3=""):
    return {"index": 1, "img_prompt": f"lnwan01，{size}，平视，{img}", "music_cue": cue, "scene_id": "sk_x",
            "cast": cast or [{"name": "林晚", "presence": "在画", "x": "右", "depth": "中"}], "dialogue": dialogue or [],
            "motion_prompt": "x，static shot，她看着桌面——中景", "h3_prompt": h3}


def test_v2_lighting_motivated_source_and_lens():
    import shot_v2 as V
    home = V.image_clauses_zh(_v2_shot("暖黄顶灯从上方打来，小餐桌"))
    assert home["scheme"] == "home_dinner_warm" and home["key_side"] == "上方" and home["decider"] == "code"
    office = V.image_clauses_zh(_v2_shot("深夜写字楼，暖黄台灯从右侧逆光", size="近景"))
    assert office["scheme"] == "office_night_lamp" and "画面右侧" in office["lighting_zh"] and office["lens_id"] == "summilux_50_f14"
    peak = V.image_clauses_zh(_v2_shot("深夜写字楼，暖黄台灯从右侧逆光", cue="推到高点，强度3"))
    assert peak["scheme"] == "office_night_tense"
    assert "雾霾天蓝色发丝" in office["lighting_zh"]                       # 人物适配
    assert V.pick_lens(_v2_shot("x", size="特写"))["focal_mm"] == 75     # 按景别
    assert V.pick_lens(_v2_shot("x", size="特写"), "summicron_35_f2")["id"] == "summicron_35_f2"   # 剧本【镜头】覆盖


def test_v2_compile_order_constraints_and_speaker():
    import shot_v2 as V
    h3 = ("integrated_multimodal_description: [Shot 1] Live-action, a medium shot begins, featuring a 22-year-old Chinese woman "
          "with misty sky-blue hair, seated at a table in a small home kitchen, lit by a warm ceiling lamp, her eyes resting on the form. "
          "The camera holds a static shot as her finger rests on the paper. At 00:02.000, she looks up. At 00:04.000, she speaks.\n"
          "overall_soundscape: A fridge hums.")
    r = V.compile_v2(_v2_shot("暖黄顶灯从上方打来", dialogue=[{"speaker": "林晚", "text": "x"}], h3=h3), None)
    nos = [s[0] for s in r["segments"]]
    assert nos == ["①", "②", "③", "④", "⑤", "⑥", "⑦"]
    assert r["video"].endswith(V.SPEC["constraints_en"])
    assert "Shot on a Leica" in r["video"] and "clear, visible mouth movement" in r["video"]
    assert "⑤" not in "".join(s[0] for s in r["segments"] if s[2] in r["image"]) and "Lit by" in r["image"]


def test_camera_ab_ab6_exec_accuracy():   # AB6：VIDLAB 执行准确度 < 0.5 否决；没有指标不否决
    import camera_ab as CA
    good = {"score": {"mean": 0.9, "cuts": [], "identity": {"林晚": {"sface_med": 0.55, "sface_p10": 0.45}},
                      "v6": {"dup_side_frac": 0.0, "extra_hand_frac": 0.0, "people": 1}, "J4": 1.1, "J4_z": 1.0, "size_measured": "中景"}}
    assert CA.judge(good, cx=None)["pass"] is True
    j = CA.judge(good, cx={"move": "truck_right", "acc": 0.1, "rot_deg": 2.2})
    assert j["pass"] is False and j["fails"][0].startswith("AB6") and j["m"]["exec_acc"] == 0.1
    assert CA.judge(good, cx={"move": "push_in", "acc": 1.0})["pass"] is True
