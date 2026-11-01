"""VQAGATE（项目方 11-01 16:10 / 16:3x）：本地看图闸门并进契约 Q9、视频只派闸门通过的首帧、跨镜连贯参考、驳回替换版自动复核。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/agent", "services/render_router", "packages/schema", "tools/autopilot"):
    sys.path.insert(0, str(ROOT / p))

from ns_agent.vqa import continuity as CT  # noqa: E402
from ns_agent.vqa import contract as VQ  # noqa: E402
from ns_agent.vqa import rubric  # noqa: E402

REAL = json.loads((ROOT / "config/vqa.json").read_text(encoding="utf-8"))


def _cfg(enforce=True, blocking=("eye_contact", "continuity_break"), video_q9=True):
    c = json.loads(json.dumps(REAL))
    c["judge"]["enforce"] = enforce
    c["gate"]["enforce"] = enforce
    c["gate"]["video_requires_q9"] = video_q9
    for k, v in c["checks"].items():
        v["blocking"] = k in blocking or k == "underage_look"
    return c


@pytest.fixture
def enf(monkeypatch):
    c = _cfg()
    monkeypatch.setattr(VQ, "cfg", lambda: c)
    return c


def _pf():
    return {"ok": True, "items": [{"id": "Q1", "status": "pass"}], "blocking": [], "reasons": []}


def test_config_has_gate_and_new_checks():
    assert REAL["judge"]["enforce"] is True and REAL["gate"]["enforce"] is True     # D-VQA-01 项目方原话转阻断
    for k in ("continuity_break", "posed_stiff"):
        assert k in REAL["checks"] and REAL["checks"][k]["contract"] == "Q9"
    txt = (ROOT / "config/prompts/vqa_inspect.md").read_text(encoding="utf-8")
    assert '"continuity_break"' in txt and "{continuity}" not in txt and "posed_stiff" in txt


def test_blocking_defect_fails_q9(enf):
    pf = VQ.apply(_pf(), {"defects": ["eye_contact"], "checks": {"eye_contact": {"s": "defect", "e": "正对镜头"}}, "key": "k"})
    q9 = next(i for i in pf["items"] if i["id"] == "Q9")
    assert q9["status"] == "fail" and pf["ok"] is False and "Q9" in pf["blocking"]


def test_unsure_and_nonblocking_only_recorded(enf):
    pf = VQ.apply(_pf(), {"defects": ["plastic_doll"], "unsure": ["eye_contact"],
                          "checks": {"plastic_doll": {"s": "defect", "e": "x"}, "eye_contact": {"s": "unsure", "e": ""}}})
    assert pf["ok"] is True and VQ.q9_passed(pf)


def test_no_verdict_is_untested_and_blocks(enf):
    pf = VQ.apply(_pf(), {"error": "服务忙"})
    assert pf["ok"] is False and next(i for i in pf["items"] if i["id"] == "Q9")["status"] == "untested"
    assert not VQ.q9_passed(pf)
    assert not VQ.q9_passed(_pf())                     # 没有 Q9 项 = 没看图 = 不派视频


def test_enforce_off_back_to_record_only(monkeypatch):
    c = _cfg(enforce=False)
    monkeypatch.setattr(VQ, "cfg", lambda: c)
    pf = VQ.apply(_pf(), {"defects": ["eye_contact"], "checks": {"eye_contact": {"s": "defect", "e": ""}}})
    assert pf["ok"] is True and VQ.q9_passed(_pf())
    pf = VQ.apply(_pf(), {"defects": ["underage_look"], "checks": {"underage_look": {"s": "defect", "e": ""}}})
    assert pf["ok"] is False                           # HC-07 任何时候都拦


def test_continuity_prev_same_scene():
    assert CT.prev_same_scene("ep01-S1") is None
    assert CT.prev_same_scene("ep01-S2") == "ep01-S1"     # 同一场 sk_office_night


def test_request_carries_continuity_ref(tmp_path):
    a, b = tmp_path / "prev.png", tmp_path / "me.png"
    a.write_bytes(b"x")
    b.write_bytes(b"y")
    req = rubric.build_image_request(str(b), "中景，林晚坐着", [], extra_refs=[(str(a), CT.LABEL)],
                                     spec={"continuity": "对照上一镜首帧（ep01-S1）"})
    assert "上一镜首帧" in req["images"][0]["label"] and "跨镜连贯：对照上一镜首帧" in req["text"]


def test_build_jobs_requires_q9(monkeypatch, enf):
    import importlib.util
    for d in ("tools/series10_video", "tools/pipeline"):
        monkeypatch.syspath_prepend(str(ROOT / d))
    # tools/ 下有两个 build_jobs.py（K-OPS-Q11 script_name_guard）：按文件路径以唯一模块名加载
    spec = importlib.util.spec_from_file_location("s10v_build_jobs_vqagate", ROOT / "tools/series10_video/build_jobs.py")
    B = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(B)
    monkeypatch.setattr(B, "_vq", lambda: VQ)
    assert B._q9_ok({"items": [{"id": "Q9", "status": "pass"}]})
    assert not B._q9_ok({"items": [{"id": "Q1", "status": "pass"}]})
    assert not B._q9_ok({"items": [{"id": "Q9", "status": "fail"}]})


def test_auto_review_redo(monkeypatch, enf):
    import producer as PR
    called = []
    monkeypatch.setattr(PR, "master_approve", lambda paths, oid, n, by, note="": called.append((oid, n, by)) or 0)
    bad = VQ.apply(_pf(), {"defects": ["continuity_break"], "checks": {"continuity_break": {"s": "defect", "e": "发色变黑"}}})
    assert PR.auto_review_redo(None, "first:ep05-S3", 4, bad) is False and not called
    good = VQ.apply(_pf(), {"defects": [], "checks": {}})
    assert PR.auto_review_redo(None, "first:ep05-S3", 5, good) is True
    assert called and called[0][2] == REAL["gate"]["auto_review_by"]


def test_truncated_output_salvaged():
    """K-REV-V10：输出被 max_new_tokens 截断（ep01 首扫 3/7）→ 按项抢救，不当“没缺陷”，也不整张判失败"""
    txt = '{"people_count": 1, "checks": {"eye_contact": {"s": "defect", "e": "正对镜头"}, "hair_mismatch": {"s": "ok", "e": ""}, "continuity_break": {"s":'
    v = rubric.parse(txt)
    assert v["ok_parse"] and v["salvaged"] and v["defects"] == ["eye_contact"] and "continuity_break" not in v["checks"]


def test_gaze_mp_high_confidence_adds_eye_contact(enf):
    enf["gate"]["gaze_mp"] = {"enabled": True, "A": 0.3, "T": 0.05, "P": 0.12}
    v = {"checks": {"eye_contact": {"s": "ok", "e": ""}}, "defects": []}
    VQ.merge_gaze(v, [{"yaw_n": 0.06, "pitch_n": 0.1, "eye_x": -0.007, "gaze_x": 0.05}], "中景，林晚看向顾沉")
    assert v["defects"] == ["eye_contact"] and "gaze_mp" in v["checks"]["eye_contact"]["e"]
    v = {"checks": {}, "defects": []}
    VQ.merge_gaze(v, [{"yaw_n": 0.06, "pitch_n": 0.1, "eye_x": -0.007, "gaze_x": 0.05}], "近景，林晚直视镜头")
    assert v["defects"] == []                          # 原文写了看镜头：不算
    v = {"checks": {}, "defects": []}
    VQ.merge_gaze(v, [{"yaw_n": 0.4, "pitch_n": 0.1, "eye_x": 0.2, "gaze_x": 0.6}], "中景")
    assert v["defects"] == []                          # 离轴


def test_template_backward_compatible_with_old_rubric():
    """16:24 事故：模板加了 {continuity} 占位符，运行中的旧 rubric 进程 .format() 不传它 → KeyError，看图整个被跳过。
    模板只能用旧占位符；跨镜连贯一行由 rubric 拼进去"""
    sec = rubric.sections("vqa_inspect.md")
    old_args = dict(refs="", spec="", cast="", size="", items="", scene="", camera_ok="")
    sec["user"].format(**old_args)                     # 旧代码的调用方式不能抛
    req = rubric.build_image_request("nowhere.png", "中景", [])
    assert "跨镜连贯：" in req["text"]


def test_auto_current_requires_q9(monkeypatch, enf):
    """撤下看图不过的当前版时，不能退回到从没看过图的旧版（否则系统不重出）"""
    from ns_render import auto_current as AC
    monkeypatch.setenv("VQA_GATE_IN_TESTS", "1")
    monkeypatch.setattr(AC.P, "bad_reason", lambda t: None)
    old = {"stage": "image", "n": 1, "postflight": {"ok": True, "items": [{"id": "Q1", "status": "pass"}]}}
    bad = {"stage": "image", "n": 2, "postflight": {"ok": False, "items": [{"id": "Q9", "status": "fail"}]}}
    data = {"takes": [old, bad], "active": {"image": 2}}
    assert not AC.passes(old)
    assert AC.decide(data, "image", 2)[0] == "clear"
    good = {"stage": "image", "n": 3, "postflight": {"ok": True, "items": [{"id": "Q9", "status": "pass"}]}}
    assert AC.passes(good)


def test_contradictory_eye_contact_downgraded(enf):
    v = {"checks": {"eye_contact": {"s": "defect", "e": "两人均未看镜头，原文不允许看镜头"}}, "defects": ["eye_contact"],
         "people": [{"gaze": "看画面右"}, {"gaze": "看林晚"}]}
    VQ.sanitize(v)
    assert v["defects"] == [] and "eye_contact" in v["unsure"]
    v = {"checks": {"eye_contact": {"s": "defect", "e": "顾沉直视镜头"}}, "defects": ["eye_contact"], "people": [{"gaze": "看镜头"}]}
    VQ.sanitize(v)
    assert v["defects"] == ["eye_contact"]


def test_score_clip_vlm_fails_follow_config():
    """视频层：V9 的 blocking 缺陷进 score_clip gate.fails（带中文标签），非 blocking 只进 soft；没看成不加"""
    import importlib.util
    spec = importlib.util.spec_from_file_location("s10v_score_clip_vqagate", ROOT / "tools/series10_video/score_clip.py")
    SC = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(SC)
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"score_clip 依赖不全：{e}")
    f, s = SC.vlm_fails({"defects": ["eye_contact", "plastic_doll", "continuity_break"]})
    assert "看镜头" in f and "跨镜不连贯" in f and "看图：plastic_doll" in s
    assert SC.vlm_fails({"error": "服务忙"}) == ([], [])


def test_decision_check_pending_until(tmp_path, monkeypatch):
    """D-VQA-02：条件文件不在时不符记 ⏳ 待开（不算 ❌）；条件满足后仍不符才 ❌"""
    import importlib.util
    spec = importlib.util.spec_from_file_location("dc_vqagate", ROOT / "tools/qa/decision_check.py")
    DC = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(DC)
    (tmp_path / "config").mkdir()
    (tmp_path / "c.json").write_text('{"gate": {"video_requires_q9": false}}', encoding="utf-8")
    (tmp_path / "config/owner_decisions.yaml").write_text(
        "checks:\n  - id: X\n    title: t\n    type: json\n    file: c.json\n    path: [gate, video_requires_q9]\n    op: eq\n    value: true\n"
        "    pending_until: {paths: [done.json], why: 等扫完}\n", encoding="utf-8")
    monkeypatch.setattr(DC, "ROOT", tmp_path)
    assert DC.run(False)[0]["ok"] == "pending"
    (tmp_path / "done.json").write_text("{}", encoding="utf-8")
    assert DC.run(False)[0]["ok"] is False


def test_limb_contradiction_downgraded_and_real_extra_hand_kept(enf):
    v = {"checks": {"extra_limbs": {"s": "defect", "e": "双手各5指，但左手小指被遮挡"}}, "defects": ["extra_limbs"]}
    VQ.sanitize(v)
    assert v["defects"] == []
    v = {"checks": {"extra_limbs": {"s": "defect", "e": "第 3 帧林晚肩上多出一只手，共 3 只手"}}, "defects": ["extra_limbs"]}
    VQ.sanitize(v)
    assert v["defects"] == ["extra_limbs"]


def test_v6_thresholds_not_empty_and_loaded():
    """K-REV-Q05 / K-REV-V12：V6 阈值写在 config/gen_contract.json，不许留空；v6_limbs 读它（多手 = 手数 > 2×人数）"""
    import importlib.util
    v6 = json.loads((ROOT / "config/gen_contract.json").read_text(encoding="utf-8"))["video_thresholds"]["V6"]
    assert v6["hands_max_per_person"] == 2 and all(v is not None for k, v in v6.items() if k != "src")
    spec = importlib.util.spec_from_file_location("v6_limbs_vqagate", ROOT / "tools/series10_video/v6_limbs.py")
    M = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(M)
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"v6_limbs 依赖不全：{e}")
    assert M.TH["bad_finger_frac"] == v6["bad_finger_frac"] and M.TH["hands_max_per_person"] == 2


def test_gaze_mp_downcast_excluded(enf):
    """ep04-S2：林晚垂眼看碗（bs_y 0.598），虹膜几何像正视 → 不算看镜头；闭眼同理"""
    enf["gate"]["gaze_mp"] = {"enabled": True, "A": 0.3, "T": 0.05, "P": 0.12, "down_max": 0.35, "blink_max": 0.6}
    v = {"checks": {}, "defects": []}
    VQ.merge_gaze(v, [{"yaw_n": 0.009, "pitch_n": 0.11, "eye_x": -0.037, "bs_y": 0.598, "gaze_x": -0.03}], "中景")
    assert v["defects"] == []
    v = {"checks": {}, "defects": []}
    VQ.merge_gaze(v, [{"yaw_n": 0.0, "pitch_n": 0.1, "eye_x": 0.0, "bs_y": 0.0, "blink": 0.9, "gaze_x": 0}], "中景")
    assert v["defects"] == []
    v = {"checks": {}, "defects": []}
    VQ.merge_gaze(v, [{"yaw_n": 0.0, "pitch_n": 0.1, "eye_x": 0.0, "bs_y": 0.05, "blink": 0.1, "gaze_x": 0}], "中景")
    assert v["defects"] == ["eye_contact"]


def test_refresh_gaze_restores_vlm_verdict(enf, monkeypatch):
    """阈值改了以后，旧判定里 gaze_mp 记的 eye_contact 要按新阈值重算（ep04-S2 垂眼误报）"""
    enf["gate"]["gaze_mp"] = {"enabled": True, "A": 0.3, "T": 0.05, "P": 0.12, "down_max": 0.35}
    monkeypatch.setattr(VQ, "gaze_mp", lambda img: [{"yaw_n": 0.009, "pitch_n": 0.11, "eye_x": -0.037, "bs_y": 0.598, "gaze_x": 0}])
    v = {"checks": {"eye_contact": {"s": "defect", "e": "gaze_mp 虹膜测得 1 张脸正对镜头（…）；看图模型原判 ok"}},
         "defects": ["eye_contact"], "gaze_mp": {"hits": 1}}
    VQ.refresh_gaze(v, "x.png", "中景")
    assert v["defects"] == [] and v["checks"]["eye_contact"]["s"] == "ok"
