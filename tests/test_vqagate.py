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


def test_vqa_min_window_opens_on_any_condition(monkeypatch):
    """最短看图窗口（总调度批：出图每满 6 张 / 最老请求等满 8 分钟 / 积压 ≥10，任一满足就开）"""
    import importlib.util
    import time as _t
    spec = importlib.util.spec_from_file_location("vqa_server_vqagate", ROOT / "tools/vqa/server.py")
    S = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(S)
    monkeypatch.setattr(S, "switch_log", lambda *a, **k: None)
    monkeypatch.setattr(S, "log", lambda *a, **k: None)
    monkeypatch.setattr(S, "WIN_N", 6)
    S._pending.clear()
    S._win.update(until=0.0, yields=5)
    assert not S.maybe_open_window()                   # 没积压：不开
    S._pending[1] = _t.time()
    assert not S.maybe_open_window()                   # 5 张、刚入队、积压 1：不开
    S._win["yields"] = 6
    assert S.maybe_open_window() and S.window_active() and S._win["yields"] == 0
    S._win.update(until=0.0)
    S._pending[1] = _t.time() - 500                    # 等了 500 s
    assert S.maybe_open_window()
    S._win.update(until=0.0)
    S._pending.clear()
    S._pending.update({i: _t.time() for i in range(10)})
    assert S.maybe_open_window() and S._win["until"] - _t.time() <= S.WIN_MAX_S + 1


def test_tunnel_requests_send_bytes_not_local_paths(monkeypatch, tmp_path):
    """隧道 8871 → gpu36：服务读不到本机路径，必须转成字节（20:xx gpu36 报 FileNotFoundError 的回归）"""
    from ns_agent.vqa import client as C
    from PIL import Image
    f = tmp_path / "a.png"
    Image.new("RGB", (64, 64)).save(f)
    sent = {}
    monkeypatch.setattr(C, "_local_up", lambda u: u.endswith(":8871"))
    monkeypatch.setattr(C, "_post_local", lambda u, body, t: sent.update(url=u, body=body) or {"text": "{}"})
    monkeypatch.setattr(C, "CACHE", tmp_path / "cache")
    C.generate({"system": "s", "text": "t", "images": [{"path": str(f), "max_pixels": 1000}]}, refresh=True)
    assert sent["url"].endswith(":8871") and "b64" in sent["body"]["images"][0] and "path" not in sent["body"]["images"][0]


def _pf_q1(sim, extra_detail=""):
    return {"ok": False, "blocking": ["Q1"], "reasons": ["Q1 x"],
            "items": [{"id": "Q1", "status": "fail", "detail": f"lin_wan {sim:.3f}（对 lin_wan）< 0.7" + extra_detail,
                       "evidence": {"sims": {"lin_wan": sim}, "strangers": [], "faces": 1}}]}


def _v(yaw, ident="ok"):
    return {"defects": [], "checks": {"identity_drift": {"s": ident, "e": ""}}, "key": "k",
            "gaze_mp": {"faces": [{"yaw_n": yaw, "pitch_n": 0.1, "eye_x": 0.3}], "hits": 0}}


def test_q1_yaw_relax_tiers(enf, monkeypatch):
    """Q1 按转角放宽（总调度 23:0x）：|yaw|<0.4 → 0.70；0.4–0.8 → 0.65；≥0.8 → 0.60；看图身份不是 ok → 回 0.70。
    11-02 K-REV-V18 修订后生产里已关（yaw_relax.enabled=false，由三段判定取代），这里显式打开只测函数本身"""
    from ns_agent import gen_contract as GC
    real = GC.cfg()
    q1c = {**real["image_thresholds"]["Q1_identity"]}
    q1c["yaw_relax"] = {**q1c["yaw_relax"], "enabled": True}
    monkeypatch.setattr(GC, "cfg", lambda: {**real, "image_thresholds": {**real["image_thresholds"], "Q1_identity": q1c}})
    pf = VQ.apply(_pf_q1(0.66), _v(0.6))
    assert pf["ok"] is True and next(i for i in pf["items"] if i["id"] == "Q1")["status"] == "pass"
    pf = VQ.apply(_pf_q1(0.66), _v(0.2))               # 正脸：仍要 0.70
    assert pf["ok"] is False
    pf = VQ.apply(_pf_q1(0.61), _v(0.9))               # 大侧脸：0.60
    assert pf["ok"] is True
    pf = VQ.apply(_pf_q1(0.61), _v(0.6))               # 0.4–0.8 档要 0.65
    assert pf["ok"] is False
    pf = VQ.apply(_pf_q1(0.66), _v(0.6, ident="unsure"))   # 看图身份拿不准 → 回 0.70
    assert pf["ok"] is False
    pf = VQ.apply(_pf_q1(0.66, "；画面里多了不该有的人"), _v(0.6))   # 还有别的不过原因 → 不放宽
    assert pf["ok"] is False


def test_multi_limb_needs_both_v6_and_vlm():
    """总调度 23:0x：多肢 = V6 手数规则命中 且 看图 extra_limbs defect；只有一方命中只记录"""
    import importlib.util
    spec = importlib.util.spec_from_file_location("s10v_score_clip_limb", ROOT / "tools/series10_video/score_clip.py")
    SC = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(SC)
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"score_clip 依赖不全：{e}")
    base = {"mean": 1.0, "cheek_red_max": 0.0, "cuts": [], "identity": {}}
    g = SC.gate({**base, "v6": {"status": "不通过"}, "vlm": {"defects": ["extra_limbs"]}}, {})
    assert "多肢" in g["fails"]
    g = SC.gate({**base, "v6": {"status": "不通过"}, "vlm": {"defects": []}}, {})
    assert "多肢" not in g["fails"] and any("多肢" in x for x in g["soft"])
    g = SC.gate({**base, "v6": {"status": "通过"}, "vlm": {"defects": ["extra_limbs"]}}, {})
    assert "多肢" not in g["fails"] and any("多肢" in x for x in g["soft"])


def test_v7_dialogue_windows_from_stamps():
    """V7 只在台词时段算（VIDEO-RCA r3）：从编译稿分拍取 “At mm:ss, … says: <d>…</d>” → [起点−0.5, min(下一拍, 起点+字数×0.3+0.6)+0.5]"""
    import importlib.util
    spec = importlib.util.spec_from_file_location("s10v_score_clip_v7", ROOT / "tools/series10_video/score_clip.py")
    SC = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(SC)
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"score_clip 依赖不全：{e}")
    p = ("At 00:02.000, his eyes drop to her heels. At 00:04.000, a man with a low voice (S1) says: <d>[Chinese] 第一天就加班。</d> "
         "his eyes lifting. At 00:06.000, the shot ends.")
    assert SC.dialogue_windows(p) == [[3.5, 6.5]]
    assert SC.dialogue_windows("no dialogue here") == []


def test_v7_masked_corr_ignores_noise_outside_window():
    import importlib.util
    import numpy as np
    spec = importlib.util.spec_from_file_location("s10v_v7", ROOT / "tools/series10_video/v7_lipsync.py")
    V = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(V)
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"v7_lipsync 依赖不全：{e}")
    n = 120
    rng = np.random.default_rng(0)
    mouth = np.zeros(n)
    audio = np.zeros(n)
    audio[:60] = np.sin(np.arange(60) / 3) + 1          # 台词外：脚步 / 配乐（嘴不动）
    mouth[60:100] = rng.random(40)
    audio[60:100] = mouth[60:100]                       # 台词时段：嘴和声同步
    m = V.window_mask([[60 / 24, 100 / 24]], n)
    assert V.best_corr_masked(mouth, audio, 3, m) > 0.9
    assert V.best_corr(mouth, audio, 3) < V.best_corr_masked(mouth, audio, 3, m)


def test_thread_guard_server_scripts_capped(tmp_path, monkeypatch):
    """K-OPS-V13：服务器打分脚本限线程（v7_lipsync 曾吃满 96 核）。现行脚本全过；缺标记块的会被查出"""
    import importlib.util
    spec = importlib.util.spec_from_file_location("thread_guard_t", ROOT / "tools/qa/thread_guard.py")
    TG = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(TG)
    assert all(not TG.check(ROOT / f) for f in TG.SERVER_SCRIPTS)
    monkeypatch.setattr(TG, "ROOT", tmp_path)
    bad = tmp_path / "x.py"
    bad.write_text("import json\nimport onnxruntime\n", encoding="utf-8")
    assert len(TG.check(bad)) == 2


def test_v7_asr_windows_from_tokens():
    """V7 台词时段用回听时间戳：有字 token 连成段（停顿 >0.8 s 切开），两头各留 0.3 s"""
    import importlib.util
    spec = importlib.util.spec_from_file_location("s10v_v7asr", ROOT / "tools/series10_video/v7_asr.py")
    A = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(A)
    w = A.windows_from_tokens(["第", "一", "天", "。", "好"], [1.54, 1.8, 2.1, 2.4, 4.0])
    assert w == [[1.24, 2.65], [3.7, 4.55]]


def test_vqa_gate_skips_vlm_when_contract_already_fails(monkeypatch, enf):
    """P0 吞吐：Q2–Q8 已不过的图不排队看图（反正要重出）；Q1 不算（转角放宽 / 后脑复核要看图）"""
    import producer as PR
    calls = []
    monkeypatch.setattr(VQ, "inspect_for", lambda *a, **k: calls.append(1) or {"defects": [], "checks": {}})
    pf = {"ok": False, "blocking": ["Q2"], "items": [{"id": "Q2", "status": "fail"}], "reasons": []}
    assert PR.vqa_gate("ep01-S1", "image", "renders/x.png", {"prompt": "p"}, pf) is None
    assert not calls and next(i for i in pf["items"] if i["id"] == "Q9")["status"] == "untested"
    pf = {"ok": False, "blocking": ["Q1"], "items": [{"id": "Q1", "status": "fail"}], "reasons": []}
    PR.vqa_gate("ep01-S1", "image", "renders/x.png", {"prompt": "p"}, pf)
    assert not calls                                       # Q1 不过、看图也救不回 → 不看
    pf = {"ok": False, "blocking": ["Q1"], "reasons": [], "items": [{"id": "Q1", "status": "fail",
          "detail": "lin_wan 0.66（对 lin_wan）< 0.7", "evidence": {"sims": {"lin_wan": 0.66}, "strangers": []}}]}
    PR.vqa_gate("ep01-S1", "image", "renders/x.png", {"prompt": "p"}, pf)
    assert calls                                           # 转角放宽可能救回 → 看


def test_back_of_head_recheck(monkeypatch, enf, tmp_path):
    """K-REV-V14：背影人物的后脑被认成认不出的脸 → 本地看图确认是后脑就不挡；是真脸照挡；cast 没有背影 / 局部人物不复核"""
    from PIL import Image
    from ns_agent.vqa import client as C
    img = tmp_path / "x.png"
    Image.new("RGB", (200, 300)).save(img)
    def pf(partial=True):
        return {"ok": False, "blocking": ["Q1"], "reasons": ["Q1 x"], "items": [{"id": "Q1", "status": "fail",
                "detail": "画面里多了不该有的人 / 认不出是谁：1 张脸不像本镜任何角色（脸高 0.12，最像 lin_wan 0.010；本镜可出现 lin_wan）",
                "evidence": {"stranger_boxes": [[50, 50, 100, 110]], "partial_cast": partial}}]}
    monkeypatch.setattr(C, "generate", lambda req, **k: {"text": '{"kind": "后脑或耳朵", "e": "只有头发和耳朵"}'})
    p = pf()
    assert VQ.recheck_strangers(p, img, tmp_path) and p["ok"] is True
    p = pf(partial=False)
    assert VQ.recheck_strangers(p, img, tmp_path) is None and p["ok"] is False
    monkeypatch.setattr(C, "generate", lambda req, **k: {"text": '{"kind": "侧脸", "e": "看得见眼睛"}'})
    p = pf()
    assert VQ.recheck_strangers(p, img, tmp_path) is None and p["ok"] is False


def test_identity_drift_per_person():
    """IMGFIX 11-02：identity_drift 逐人判——任何一个露脸的人“不像”就记缺陷（不只看主角）"""
    v = {"checks": {"identity_drift": {"s": "ok", "e": ""}}, "defects": [],
         "people": [{"who": "林晚", "pos": "左", "identity": "像"}, {"who": "顾沉", "pos": "右", "identity": "不像"}]}
    VQ.sanitize(v)
    assert "identity_drift" in v["defects"] and "顾沉" in v["checks"]["identity_drift"]["e"]
    v = {"checks": {}, "defects": [], "people": [{"who": "林晚", "identity": "像"}, {"who": "顾沉", "identity": "na"}]}
    VQ.sanitize(v)
    assert v["defects"] == []


def test_deploy_push_refuses_without_thread_guard(monkeypatch):
    """K-OPS-V13 硬检查：thread_guard 不过，deploy.push 不推"""
    import importlib.util
    spec = importlib.util.spec_from_file_location("s10v_deploy_tg", ROOT / "tools/series10_video/deploy.py")
    D = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(D)
    monkeypatch.setattr(D, "thread_guard_ok", lambda: False)
    monkeypatch.setattr(D, "ssh", lambda *a, **k: (_ for _ in ()).throw(AssertionError("不该连服务器")))
    assert D.push("gpu33") is False


def test_gaze_band_recheck_catches_near_miss(monkeypatch, enf, tmp_path):
    """L-102：s20261304 这类“差一点”（MediaPipe 0.065，线 0.05）由裁脸复判接住；回归集里登记了这张"""
    from PIL import Image
    from ns_agent.vqa import client as C
    reg = json.loads((ROOT / "data/vqa/gate_calib/gaze_regression.json").read_text(encoding="utf-8"))
    assert any("s20261304" in it["path"] and it["label"] == "看镜头" for it in reg["items"])
    enf["gate"]["gaze_mp"] = {"enabled": True, "A": 0.3, "T": 0.05, "P": 0.2, "down_max": 0.35, "blink_max": 0.6, "band": 2.0}
    img = tmp_path / "x.png"
    Image.new("RGB", (300, 400)).save(img)
    monkeypatch.setattr(VQ, "ROOT", tmp_path)
    face = {"yaw_n": 0.1, "eye_x": 0.035, "pitch_n": 0.1, "bs_y": 0.0, "blink": 0.0, "ybox": [100, 100, 60, 70]}
    monkeypatch.setattr(C, "generate", lambda req, **k: {"text": '{"gaze": "看镜头", "e": "瞳孔正对"}'})
    v = {"checks": {"eye_contact": {"s": "ok", "e": ""}}, "defects": []}
    VQ.recheck_gaze_band(v, [face], img, "中景")
    assert v["defects"] == ["eye_contact"]
    monkeypatch.setattr(C, "generate", lambda req, **k: {"text": '{"gaze": "看别处", "e": ""}'})
    v = {"checks": {}, "defects": []}
    VQ.recheck_gaze_band(v, [face], img, "中景")
    assert v["defects"] == []
    v = {"checks": {}, "defects": []}                      # 分数远离线（0.5）不复判
    VQ.recheck_gaze_band(v, [{**face, "eye_x": 0.5}], img, "中景")
    assert "gaze_recheck" not in v


def test_v7_window_rule_matches_owner_labels():
    """K-REV-V16：V7 台词段口径——幅度 ≥ win_amp_min 是前提，再“相关 ≥ 线 或 张嘴占比 ≥0.30”；对总调度标签 5/5"""
    import importlib.util
    spec = importlib.util.spec_from_file_location("s10v_v7_rule", ROOT / "tools/series10_video/v7_lipsync.py")
    V = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(V)
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"v7_lipsync 依赖不全：{e}")
    TH = V.TH
    lab = json.loads((ROOT / "data/vqa/gate_calib/v7_labels.json").read_text(encoding="utf-8"))["items"]
    for it in lab:
        ok = it["win_amp"] >= TH["win_amp_min"] and (it["corr"] >= TH["corr_min"] or it["win_open_frac"] >= TH["win_open_frac_min"])
        assert ok == (it["label"] == "过"), it["clip"]


def test_q1_needs_vlm_only_when_rescuable():
    def pf(sim, detail=None, ev=None):
        return {"ok": False, "blocking": ["Q1"], "items": [{"id": "Q1", "status": "fail",
                "detail": detail or f"lin_wan {sim}（对 lin_wan）< 0.7", "evidence": ev or {"sims": {"lin_wan": sim}, "strangers": []}}]}
    assert VQ.q1_needs_vlm(pf(0.66))                       # 转角放宽可能救回
    assert not VQ.q1_needs_vlm(pf(0.40))                   # 差太多：不看图
    assert VQ.q1_needs_vlm(pf(0, "画面里多了不该有的人 / 认不出是谁：1 张脸",
                              {"partial_cast": True, "stranger_boxes": [[1, 2, 3, 4]], "sims": {}}))


def test_identity_gate_unexpected_face_blocks_stranger():
    """K-REV-V18 人物一致性闸门：cast 写“局部 双手”，画面里却出了脸（ep02-S10 换人，ArcFace 对 L-086 0.24–0.26）→ Q1 拦；
    露了脸但认得出是本人（正例最低 0.669）→ 过；脸太小不判"""
    from ns_agent.gen_contract import postflight as PO
    rec = {"size": "特写", "subject": "part", "zones": [], "primary": None, "slots": [], "missing": [], "characters": []}
    req = {"asset_refs": rec, "cast": [{"name": "林晚", "presence": "局部"}]}
    loc = {"Q2": [], "Q4": None, "Q7": None}
    def q1(faces):
        r = PO.evaluate("x.png", req, remote={"faces": faces}, local=loc)
        return next(i for i in r.items if i.id == "Q1")
    bad = q1([{"h_ratio": 0.2, "bbox": [1, 2, 3, 4], "sims": {"lin_wan": 0.24, "gu_chen": 0.05}}])
    assert bad.status == "fail" and "不像" in bad.detail
    good = q1([{"h_ratio": 0.2, "sims": {"lin_wan": 0.70, "gu_chen": 0.05}}])
    assert good.status == "pass"
    tiny = q1([{"h_ratio": 0.02, "sims": {"lin_wan": 0.1}}])
    assert tiny.status == "na"
    assert q1([]).status == "na"


def test_q1_three_bands():
    """K-REV-V18 修订：≥0.60 过；0.50–0.60 复核带（Q1 不过 + review_band 证据，交本地看图并排复核）；<0.50 直接不过；小脸下移 0.10"""
    from ns_agent.gen_contract import postflight as PO
    rec = {"size": "近景", "subject": None, "zones": ["face"], "primary": "lin_wan", "slots": [], "missing": []}
    req = {"asset_refs": rec, "cast": [{"name": "林晚", "presence": "在画"}]}
    loc = {"Q2": [], "Q4": None, "Q7": None}
    def q1(sim, h=0.2):
        return next(i for i in PO.evaluate("x.png", req, remote={"faces": [{"h_ratio": h, "bbox": [0, 0, 9, 9], "sims": {"lin_wan": sim}}]},
                                           local=loc).items if i.id == "Q1")
    assert q1(0.62).status == "pass"
    b = q1(0.55)
    assert b.status == "fail" and b.evidence["review_band"][0]["cid"] == "lin_wan"
    c = q1(0.45)
    assert c.status == "fail" and not c.evidence["review_band"]
    assert q1(0.52, h=0.06).status == "pass"            # 小脸档 ≥0.50


def test_q1_band_review_fail_closed(monkeypatch, enf, tmp_path):
    """K-REV-V18 修订：复核带（0.50–0.60）看图没跑成 / 报错 / 有一项不是“是” → Q1 维持不过（fail-closed）；三项全是 → 改判过"""
    from PIL import Image
    from ns_agent.vqa import client as C
    img = tmp_path / "x.png"
    Image.new("RGB", (300, 400)).save(img)
    monkeypatch.setattr(VQ, "ROOT", tmp_path)
    monkeypatch.setattr(VQ, "BAND_CALIB", tmp_path / "band_sharp_auto.jsonl")   # 不写真实标定集
    (tmp_path / "data/assets/identity_refs/lin_wan").mkdir(parents=True)
    Image.new("RGB", (64, 64)).save(tmp_path / VQ.L086)

    def pf():
        return {"ok": False, "blocking": ["Q1"], "reasons": ["Q1 x"], "items": [{"id": "Q1", "status": "fail",
                "detail": "lin_wan 0.550（对 lin_wan）在复核带 0.5–0.6（近中景及以上），待本地看图并排复核",
                "evidence": {"review_band": [{"cid": "lin_wan", "sim": 0.55, "lo": 0.5, "need": 0.6, "bbox": [50, 50, 120, 140]}]}}]}
    monkeypatch.setattr(C, "generate", lambda req, **k: {"error": "服务没起"})
    p = pf()
    assert VQ.q1_band_review(p, img) is None and p["ok"] is False
    monkeypatch.setattr(C, "generate", lambda req, **k: (_ for _ in ()).throw(RuntimeError("连接断")))
    p = pf()
    assert VQ.q1_band_review(p, img) is None and p["ok"] is False
    monkeypatch.setattr(C, "generate", lambda req, **k: {"text": '{"same_person": "是", "style_ok": "否", "sharp": "是", "e": "发平"}'})
    p = pf()
    assert VQ.q1_band_review(p, img) is None and p["ok"] is False
    monkeypatch.setattr(C, "generate", lambda req, **k: {"text": '{"same_person": "是", "style_ok": "是", "sharp": "是", "e": ""}'})
    monkeypatch.setattr(VQ, "face_sharpness", lambda fp: 200.0)
    p = pf()
    assert VQ.q1_band_review(p, img) and p["ok"] is True
    monkeypatch.setattr(VQ, "face_sharpness", lambda fp: 23.9)     # 03-S2 v14：看图答“是”也拦（发糊）
    p = pf()
    assert VQ.q1_band_review(p, img) is None and p["ok"] is False


def test_gaze_regression_judge_exposes_defects(monkeypatch, tmp_path):
    """SENTINEL S8：judge 透出 defects / identity / missing_items / contract（Q1 / Q2 / Q9）"""
    import importlib.util
    spec = importlib.util.spec_from_file_location("gaze_reg_t", ROOT / "tools/vqa/gaze_regression.py")
    G = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(G)
    from ns_agent.vqa import client as C
    monkeypatch.setattr(C, "inspect_image", lambda *a, **k: {"defects": ["identity_drift", "outfit_mismatch"], "unsure": [],
        "checks": {"identity_drift": {"s": "defect", "e": "不像"}, "outfit_mismatch": {"s": "defect", "e": "缺外套"}},
        "people": [{"who": "林晚", "pos": "中", "identity": "不像"}]})
    monkeypatch.setattr(VQ, "gaze_mp", lambda p: None)
    r = G.judge(tmp_path / "x.png", "ep01-S1")
    assert "identity_drift" in r["defects"] and r["identity"]["per_person"][0]["identity"] == "不像"
    assert "outfit_mismatch" in r["missing_items"] and r["contract"] is None


def test_identity_bank_topk_with_anchor():
    """L-098 身份库 top-k：锚 ≥0.50 时有效分 = 锚 + 库帧前 k 平均（侧脸回升）；锚 <0.50 库不帮忙（S10 类反例照样拦）"""
    from ns_agent.gen_contract import postflight as PO
    t1 = {"bank": {"k": 3, "anchor_min": 0.50}}
    side = PO.apply_bank({"lin_wan": 0.56, "lin_wan@b0": 0.80, "lin_wan@b1": 0.74, "lin_wan@b2": 0.40, "gu_chen": 0.05}, t1)
    assert side["lin_wan"] == round((0.80 + 0.74 + 0.56) / 3, 4) and side["lin_wan@anchor"] == 0.56 and "lin_wan@b0" not in side
    neg = PO.apply_bank({"lin_wan": 0.25, "lin_wan@b0": 0.70, "lin_wan@b1": 0.66}, t1)
    assert neg["lin_wan"] == 0.25
    assert PO.apply_bank({"lin_wan": 0.7}, t1) == {"lin_wan": 0.7}


def test_q1_bank_topk_keeps_sharpness_check(monkeypatch, enf, tmp_path):
    """L-098 A/B（11-02）：03-S2 v14 锚 0.573、身份库 top-k 0.650 —— top-k 过线也不直接放行，进复核带 sharp_only：
    不调本地看图，确定性清晰度 ≥42.3 才过（23.9 拦）；S10 换人锚 0.24 库帧再像也不抬"""
    from PIL import Image
    from ns_agent.gen_contract import postflight as PO
    from ns_agent.vqa import client as C
    rec = {"size": "近景", "subject": None, "zones": ["face"], "primary": "lin_wan", "slots": [], "missing": []}
    req = {"asset_refs": rec, "cast": [{"name": "林晚", "presence": "在画"}]}
    loc = {"Q2": [], "Q4": None, "Q7": None}

    def q1(sims):
        return next(i for i in PO.evaluate("x.png", req, remote={"faces": [{"h_ratio": 0.2, "bbox": [50, 50, 120, 140], "sims": sims}]},
                                           local=loc).items if i.id == "Q1")
    it = q1({"lin_wan": 0.573, "lin_wan@b0": 0.70, "lin_wan@b1": 0.68})
    band = it.evidence["review_band"]
    assert it.status == "fail" and band[0]["mode"] == "sharp_only" and band[0]["sim"] == 0.573 and band[0]["topk"] >= 0.60
    assert q1({"lin_wan": 0.24, "lin_wan@b0": 0.9, "lin_wan@b1": 0.9}).evidence["review_band"] == []
    assert q1({"lin_wan": 0.65, "lin_wan@b0": 0.75}).status == "pass"
    img = tmp_path / "x.png"
    Image.new("RGB", (300, 400)).save(img)
    monkeypatch.setattr(VQ, "ROOT", tmp_path)
    monkeypatch.setattr(VQ, "BAND_CALIB", tmp_path / "band_sharp_auto.jsonl")   # 不写真实标定集
    monkeypatch.setattr(C, "generate", lambda req, **k: (_ for _ in ()).throw(AssertionError("sharp_only 不该调看图")))

    def pf():
        return {"ok": False, "blocking": ["Q1"], "reasons": ["Q1 x"],
                "items": [{"id": "Q1", "status": "fail", "detail": it.detail, "evidence": dict(it.evidence)}]}
    monkeypatch.setattr(VQ, "face_sharpness", lambda fp: 23.9)
    p = pf()
    assert VQ.q1_band_review(p, img) is None and p["ok"] is False
    monkeypatch.setattr(VQ, "face_sharpness", lambda fp: 120.0)
    p = pf()
    assert VQ.q1_band_review(p, img) and p["ok"] is True


def test_identity_bank_admission_and_eviction(monkeypatch, tmp_path):
    """L-098 入库条件：过契约 + 未驳回 + 单脸 + 对 L-086 ≥0.60；驳回后（takes.json 变新）下一次取库就出库"""
    import importlib.util
    import os
    import time
    spec = importlib.util.spec_from_file_location("ns_id_bank", ROOT / "tools/identity/bank.py")
    B = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(B)
    monkeypatch.setattr(B, "ROOT", tmp_path)
    monkeypatch.setattr(B, "BANK", tmp_path / "data/identity/bank.json")
    monkeypatch.setattr(B, "_yaw", lambda p: 0.1)
    d = tmp_path / "data/renders/ep01/S1"
    (d / "takes").mkdir(parents=True)

    def take(n, sim, ok=True, rej=False, nsims=1):
        (d / f"takes/i{n}.png").write_bytes(b"x")
        sims = {"lin_wan": sim, "gu_chen": 0.1} if nsims == 2 else {"lin_wan": sim}
        return {"stage": "image", "file": f"renders/ep01/S1/takes/i{n}.png", "master_reject": rej, "created_at": f"2026-11-02T0{n}",
                "postflight": {"ok": ok, "items": [{"id": "Q1", "status": "pass", "evidence": {"sims": sims, "faces": nsims}}]}}
    tk = [take(1, 0.8), take(2, 0.55), take(3, 0.9, ok=False), take(4, 0.9, rej=True), take(5, 0.9, nsims=2), take(6, 0.7)]
    (d / "takes.json").write_text(json.dumps({"takes": tk}), encoding="utf-8")
    assert sorted(B.bank_files("lin_wan")) == ["data/renders/ep01/S1/takes/i1.png", "data/renders/ep01/S1/takes/i6.png"]
    tk[0]["master_reject"] = True
    time.sleep(0.05)
    (d / "takes.json").write_text(json.dumps({"takes": tk}), encoding="utf-8")
    os.utime(d / "takes.json", (time.time() + 5, time.time() + 5))
    assert B.bank_files("lin_wan") == ["data/renders/ep01/S1/takes/i6.png"]


def test_q1a_hair_feats_crown_connectivity_and_judge():
    """K-REV-V19：只认与这张脸头顶相连的头发（旁边背对镜头的人的长发不算）；短发角色下巴以下有头发 = 长发不过；蓝色占比判发色"""
    import numpy as np
    from ns_agent.vqa import hair_attr as HA
    H, W = 400, 300
    rgb = np.zeros((H, W, 3), np.uint8)
    rgb[...] = (40, 40, 40)
    box = [100, 100, 160, 170]                      # 脸 60×70
    m = np.zeros((H, W), np.uint8)
    m[60:110, 95:165] = 1                           # 头顶短发
    m[0:400, 0:40] = 1                              # 左边旁人的长发（不连）
    rgb[0:400, 0:40] = (70, 110, 170)               # 蓝
    f = HA.hair_mask_feats(rgb, [box], 0, m, (0, 0))
    assert f["below"] == 0 and f["hair_blue"] == 0
    card = {"name": "顾沉", "hair_short": True, "below_max": 0.15, "blue_max": 0.45}
    assert HA.judge("gu_chen", f, card) == []
    m[110:330, 160:200] = 1                         # 连着头顶垂到肩下的长发
    rgb[60:330, 95:200] = (70, 110, 170)
    f2 = HA.hair_mask_feats(rgb, [box], 0, m, (0, 0))
    bad = HA.judge("gu_chen", f2, card)
    assert f2["below"] >= 0.15 and len(bad) == 2      # 长发 + 蓝发
    lw = {"name": "林晚", "blue_min": 0.20, "min_hair_px": 0.15}
    assert HA.judge("lin_wan", f2, lw) == [] and HA.judge("lin_wan", f, lw)   # 林晚黑发 → 发色不对


def test_q1a_item_unavailable_is_untested_not_silent(monkeypatch, tmp_path):
    """SYSARCH 11-02：分割不可用 → Q1a untested + q1a_mode=unavailable（producer 记 score_infra 只重打分），不静默放过"""
    from PIL import Image
    from ns_agent.gen_contract import postflight as PO
    from ns_agent.vqa import hair_attr as HA
    img = tmp_path / "x.png"
    Image.new("RGB", (64, 64)).save(img)

    def boom(*a, **k):
        raise HA.Unavailable("没有 mediapipe")
    monkeypatch.setattr(HA, "measure", boom)
    t1a = {"enabled": True, "cards": {"gu_chen": {"name": "顾沉", "hair_short": True}}}
    st, d, ev = PO.q1a_item(str(img), {"gu_chen": [1, 2, 3, 4]}, [[1, 2, 3, 4]], t1a)
    assert st == "untested" and ev["q1a_mode"] == "unavailable"
    assert PO.q1a_item(str(img), {}, [], t1a)[0] == "na"
    assert PO.q1a_item(str(tmp_path / "nope.png"), {"gu_chen": [1, 2, 3, 4]}, [], t1a)[2]["q1a_mode"] == "no_image"
    monkeypatch.setattr(HA, "measure", lambda img, boxes: [{"hair_px": 0.5, "hair_blue": 0.85, "below": 0.49}])
    st, d, ev = PO.q1a_item(str(img), {"gu_chen": [1, 2, 3, 4]}, [[1, 2, 3, 4]], t1a)
    assert st == "fail" and "长发" in d                 # ep06-S2 v6 实测值


def test_q1a_vlm_overrides_pass_and_tolerates_outage(monkeypatch, tmp_path):
    """K-REV-V19：确定性过、看图说顾沉是长发 → Q1a fail；看图没跑成 → 只记录不改判"""
    from ns_agent.vqa import hair_attr as HA
    def pf():
        return {"ok": True, "blocking": [], "reasons": [], "items": [{"id": "Q1a", "status": "pass", "detail": "",
                "evidence": {"boxes": {"gu_chen": [1, 2, 3, 4]}}}]}
    monkeypatch.setattr(HA, "vlm_ask", lambda img, box: {"gender": "男", "hair_color": "蓝", "hair_length": "长"})
    p = pf()
    assert VQ.q1a_vlm(p, "x.png") and p["ok"] is False and "Q1a" in p["blocking"]
    monkeypatch.setattr(HA, "vlm_ask", lambda img, box: None)
    p = pf()
    assert VQ.q1a_vlm(p, "x.png") is None and p["ok"] is True and p["items"][0]["evidence"]["vlm"]["gu_chen"] == {"vlm": "untested"}
    monkeypatch.setattr(VQ, "ROOT", tmp_path)

    def off():
        return {"ok": False, "blocking": ["Q1a"], "reasons": ["Q1a x"], "items": [{"id": "Q1a", "status": "untested", "detail": "",
                "evidence": {"q1a_mode": "unavailable", "boxes": {"gu_chen": [1, 2, 3, 4]}}}]}
    p = off()                                          # 分割不可用 + 看图也没跑成 → 维持 untested（fail-closed）
    assert VQ.q1a_vlm(p, "x.png") is None and p["ok"] is False
    monkeypatch.setattr(HA, "vlm_ask", lambda img, box: {"gender": "男", "hair_color": "黑", "hair_length": "短", "nails": "普通"})
    p = off()                                          # 看图逐人相符 → vlm_only 放行 + 报警
    assert VQ.q1a_vlm(p, "x.png") and p["ok"] is True and p["items"][0]["evidence"]["q1a_mode"] == "vlm_only"
    assert (tmp_path / "data/vqa/alerts.jsonl").exists()
    monkeypatch.setattr(HA, "vlm_ask", lambda img, box: {"gender": "男", "hair_color": "黑", "hair_length": "短", "nails": "长美甲"})
    p = off()                                          # 男性长美甲只记录（ep06-S8 看图把旁边林晚的手算给顾沉）
    assert VQ.q1a_vlm(p, "x.png") and p["ok"] is True
    monkeypatch.setattr(HA, "vlm_ask", lambda img, box: {"gender": "男", "hair_color": "蓝", "hair_length": "长", "nails": "长美甲"})
    p = off()                                          # ep06-S1 v8 实测回答：顾沉蓝色长发 → 拦（确定性分割漏了这张，缺口 0.4 脸宽）
    assert VQ.q1a_vlm(p, "x.png") and p["ok"] is False


def test_regression_check_broken_case_is_reported(monkeypatch, tmp_path):
    """DISTILL missed_defect_to_regression：坏的回归用例要显式记 broken（漏跑 = 假全过），整体退出 1"""
    import importlib.util
    spec = importlib.util.spec_from_file_location("ns_vqa_regcheck", ROOT / "tools/vqa/regression_check.py")
    RC = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(RC)
    (tmp_path / "bad.json").write_text("{坏", encoding="utf-8")
    monkeypatch.setattr(RC, "REG", tmp_path)
    assert RC.cases()[0]["kind"] == "broken"
    assert RC.main([]) == 1


def test_autosign_gate_sign_and_spot_revert(monkeypatch, tmp_path):
    """master_review 机签（总调度 11-02）：门槛没过 = manual 不签；切换后抽检有一条不一致 → 自动退回 manual + 报警"""
    import importlib.util
    spec = importlib.util.spec_from_file_location("ns_vqa_autosign", ROOT / "tools/vqa/autosign.py")
    A = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(A)
    for k in ("STATE", "SPOT", "SIGNED", "ALERTS"):
        monkeypatch.setattr(A, k, tmp_path / f"{k}.json")
    monkeypatch.setattr(A, "regression", lambda: {"ok": True, "pairs": [{"auto": "fail", "human": "fail"}] * 19})
    monkeypatch.setattr(A, "history_pairs", lambda root=None: [{"auto": "pass", "human": "fail", "file": "x", "why": "下装错"}])
    st = A.check()
    assert st["mode"] == "manual" and st["false_pass"] == 1        # 漏放 1 条就不能切
    monkeypatch.setattr(A, "history_pairs", lambda root=None: [{"auto": "pass", "human": "pass", "file": "x", "why": ""}])
    assert A.check()["mode"] == "auto"
    monkeypatch.setattr(A, "take_ok", lambda sid, stage, n: (True, f"renders/{sid}.png"))
    man = tmp_path / "m.json"
    man.write_text(json.dumps([{"sid": "ep01-S1", "stage": "image", "n": 1}]), encoding="utf-8")
    (tmp_path / "page").mkdir()
    assert A.sign(str(tmp_path / "page"), str(man)) == 0 and (tmp_path / "page/master_review_auto.md").exists()
    sid = A._rows(A.SPOT)[0]["id"]                                 # 第 1 条必抽
    assert A.spot(sid, "fail")["action"] == "revert"
    assert A.state()["mode"] == "manual" and A._rows(A.ALERTS)[0]["kind"] == "autosign_revert"
    assert A.check()["mode"] == "manual"                           # 退回过：要总调度确认才重新切


def test_canary_after_redo_pauses_on_shared_failure(monkeypatch, tmp_path):
    """canary_after_redo：换版后前 6 个不同镜头里同一阻断项 > 34% → 触发暂停；同镜重复不计；版本变了从头数"""
    from ns_agent.vqa import canary as CN
    monkeypatch.setattr(CN, "STATE", tmp_path / "s.json")
    monkeypatch.setattr(CN, "ALERTS", tmp_path / "a.jsonl")
    bad, ok = {"ok": False, "blocking": ["Q1a"]}, {"ok": True, "blocking": []}
    for i in range(5):
        assert CN.observe("ep05-S3", "image", bad, key="v1") is None      # 同镜重复只算 1 个样本
    hits = [CN.observe(f"ep01-S{i}", "image", bad if i < 2 else ok, key="v1") for i in range(5)]
    assert hits[-1] and hits[-1]["item"] == "Q1a" and hits[-1]["frac"] == 0.5 and (tmp_path / "a.jsonl").exists()
    assert CN.observe("ep02-S1", "image", bad, key="v1") is None           # 本版已判过
    for i in range(6):                                                     # 新版本：6 镜只 2 镜不过（33%）→ 不触发
        h = CN.observe(f"ep03-S{i}", "image", bad if i < 2 else ok, key="v2")
    assert h is None and CN._load()["decided"]["action"] == "ok"
    assert CN.observe("ep04-S1", "image", {"ok": False, "blocking": ["Q1"], "score_infra": True}, key="v3") is None


def test_vram_budget_static_blocks_overcommit():
    """总调度 11-02（S3 根因）：同卡常驻峰值和 > 0.9×显存（24576 → 22118 MiB）→ 部署前拦。2×7400 过；4 实例拦；3 实例 + CLIP 2.5 GB（13:17 OOM 组合）拦"""
    import importlib.util
    spec = importlib.util.spec_from_file_location("ns_vqa_vram", ROOT / "tools/vqa/vram_budget.py")
    V = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(V)
    b = {"gpu36:2": {"total_mib": 24576, "residents": [{"count_from": "model.instances", "peak_mib": 7400}]}}
    assert V.static_check({"model": {"instances": 2, "vram_budget": b}}) == []
    assert V.static_check({"model": {"instances": 4, "vram_budget": b}})
    b["gpu36:2"]["residents"].append({"name": "clip", "count": 1, "peak_mib": 2500})
    assert V.static_check({"model": {"instances": 3, "vram_budget": b}})     # 11-02 13:17 的 OOM 组合


def test_autosign_history_skips_quarantined_and_logs_false_reject(monkeypatch, tmp_path):
    """总调度 11-02：机签历史样本只取现行剧本（图已隔离的旧剧本不比）；判过但机器拦了的记误拦样本"""
    import importlib.util
    spec = importlib.util.spec_from_file_location("ns_vqa_autosign2", ROOT / "tools/vqa/autosign.py")
    A = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(A)
    d = tmp_path / "data/renders/ep01/S1"
    d.mkdir(parents=True)
    (d / "a.png").write_bytes(b"x")
    rj = {"by": "总调度", "reason": "下装错"}
    tk = [{"stage": "image", "file": "renders/ep01/S1/a.png", "postflight": {"ok": False}, "master_reject": rj},
          {"stage": "image", "file": "renders/ep01/S1/gone.png", "postflight": {"ok": True}, "master_reject": rj}]
    (d / "takes.json").write_text(json.dumps({"takes": tk}), encoding="utf-8")
    h = A.history_pairs(tmp_path)
    assert len(h) == 1 and h[0]["file"].endswith("a.png")              # 已隔离的那张（漏放）不计
    monkeypatch.setattr(A, "FALSE_REJECT", tmp_path / "fr.jsonl")
    A.false_reject("renders/x.png", "总调度判过")
    assert A._rows(tmp_path / "fr.jsonl")[0]["human"] == "pass"


def test_gaze_primary_switch(monkeypatch, enf):
    """总调度 11-02：gaze_mp 主判（开关 gate.gaze_mp.primary）——每张脸都明显没看镜头且脸数够 → VLM defect 降 ok；关着不动；脸数不够不动"""
    enf["gate"]["gaze_mp"] = {"enabled": True, "A": 0.3, "T": 0.05, "P": 0.2, "band": 2.0, "primary": False}
    away = {"yaw_n": 1.3, "eye_x": 0.7, "pitch_n": 0.05, "bs_y": 0.0, "blink": 0.0}

    def v(n_people=1):
        return {"checks": {"eye_contact": {"s": "defect", "e": "男左眼正对镜头"}}, "defects": ["eye_contact"],
                "people": [{"who": "x"}] * n_people}
    x = v(); VQ.merge_gaze(x, [away], "")
    assert x["defects"] == ["eye_contact"]                       # 开关关着：现行
    enf["gate"]["gaze_mp"]["primary"] = True
    x = v(); VQ.merge_gaze(x, [away], "")
    assert x["defects"] == [] and x["checks"]["eye_contact"]["s"] == "ok"
    x = v(2); VQ.merge_gaze(x, [away], "")
    assert x["defects"] == ["eye_contact"]                       # 看图数到 2 人、gaze_mp 只测到 1 张 → 不降
    near = {**away, "yaw_n": 0.0, "eye_x": 0.08}                 # 带内（0.05–0.1）→ 不降，交复判
    x = v(); VQ.merge_gaze(x, [near], "")
    assert x["defects"] == ["eye_contact"]


def test_hair_primary_switch(enf):
    """总调度 11-02：发色 Q1a 分割主判（开关 gate.hair_primary）——Q1a seg pass → VLM hair_mismatch 降 unsure；Q1a fail / vlm_only / 关着不动"""
    def pf(st="pass", mode="seg"):
        return {"items": [{"id": "Q1a", "status": st, "evidence": {"q1a_mode": mode}}]}

    def v():
        return {"checks": {"hair_mismatch": {"s": "defect", "e": "发色偏灰"}}, "defects": ["hair_mismatch"], "unsure": []}
    x = v()
    assert VQ.hair_primary(pf(), x) is False and x["defects"] == ["hair_mismatch"]   # 关着
    enf["gate"]["hair_primary"] = True
    x = v()
    assert VQ.hair_primary(pf(), x) and x["defects"] == [] and "hair_mismatch" in x["unsure"]
    for p_ in (pf("fail"), pf("pass", "vlm_only")):
        x = v()
        assert VQ.hair_primary(p_, x) is False and x["defects"] == ["hair_mismatch"]
