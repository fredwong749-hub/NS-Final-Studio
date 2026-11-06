"""W-DETECT 11-06（PLAN_OVERNIGHT 第 3 线：ep01 首帧 77% / 尾帧 57% 不过的根因修复）：
① ns_qc.gaze.lineup_geo 排排站几何判（L-200；看图对 ep01 S1 / S14 / S15 合影式并排全漏）+ G1 不被看图“没报缺陷”否掉；
② Q9 eye_contact 与 YuNet 明显离轴矛盾 → 只记录（今天 15 张全是误报）；
③ Q10 人数硬项改读结构化 people（看图把站位不符写成 people_count 抬头）；
④ Q1 侧脸复核下限下移（直接不过 → 进复核带交看图）；
⑤ producer.last_consistent 不再对“已按新首帧重出中”的尾帧反复作废清零（S9 一天 26 版）；
⑥ 尾帧 FL 不过 → 下一次换构图（紧档 + 去首帧参考）而不是只换 seed。
全部 mock / 临时目录，不碰 GPU、不写真实数据。"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/agent", "services/render_router", "packages/schema", "packages/qc", "tools/pipeline", "tools/autopilot", ""):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))

from ns_qc import gaze as GZ  # noqa: E402
from ns_agent.gen_contract import blocking as BL  # noqa: E402
from ns_agent.gen_contract import postflight as PF  # noqa: E402

HARD = {"blocking_items": ["Q1", "count", "text", "adult", "gaze", "FL"]}
W, H = 768, 1344


def _row(cx, cy, h, iod_w, yaw, status="视线离轴", gx=0.9):
    """标定表（data/_offline_pull ep01 11-06，YuNet 实测）→ face_gaze 行：归一化脸心 / 脸高 → 像素框"""
    hp = h * H
    wp = hp * 0.75
    return {"box": [cx * W - wp / 2, cy * H - hp / 2, wp, hp], "iod": iod_w * wp, "yaw_n": yaw, "status": status, "gaze_x": gx}


# 11-06 标定集（亲看 + YuNet 特征）：1 = 排排站（项目方点名 S1 三人一排、S14 / S15 两人并排）；0 = 过肩 / 前后错落 / 单人
CALIB = {
    "S1 v3 三人一排": (1, [(0.773, 0.267, 0.098, 0.343, -0.529), (0.274, 0.25, 0.094, 0.398, 0.355), (0.529, 0.299, 0.084, 0.411, 0.309)]),
    "S14 v2 两人并排": (1, [(0.706, 0.284, 0.123, 0.269, 0.463), (0.318, 0.293, 0.104, 0.431, 0.221)]),
    "S15 v12 两人并排": (1, [(0.693, 0.355, 0.129, 0.393, -0.429), (0.325, 0.324, 0.124, 0.398, 0.313)]),
    "S14 v11 两人并排": (1, [(0.791, 0.3, 0.167, 0.347, 0.452), (0.44, 0.295, 0.142, 0.459, 0.143)]),
    "S1 v13 三人一排": (1, [(0.748, 0.346, 0.101, 0.322, 0.538), (0.492, 0.29, 0.078, 0.39, 0.4), (0.235, 0.273, 0.074, 0.366, 0.442)]),
    "S4 v25 过肩单脸": (0, [(0.55, 0.389, 0.123, 0.285, 0.596)]),
    "S5 v13 过肩单脸": (0, [(0.517, 0.371, 0.144, 0.27, 0.632)]),
    "S12 v13 过肩后脑未测": (0, [(0.874, 0.471, 0.197, 0.11, 0.729, "未测"), (0.325, 0.331, 0.139, 0.319, 0.431)]),
    "S7 v9 前后错落": (0, [(0.613, 0.299, 0.123, 0.368, 0.316), (0.254, 0.362, 0.069, 0.427, 0.181)]),
    "S9 v22 高机位前后": (0, [(0.487, 0.317, 0.116, 0.379, 0.267), (0.684, 0.117, 0.09, 0.448, 0.261)]),
    "S9 尾帧 v13": (0, [(0.459, 0.267, 0.094, 0.296, 0.448), (0.68, 0.115, 0.089, 0.426, 0.271)]),
    "S7 尾帧 v17": (0, [(0.547, 0.259, 0.135, 0.387, -0.376), (0.261, 0.346, 0.074, 0.445, 0.168)]),
    "S4 尾帧 v11 单脸": (0, [(0.528, 0.369, 0.129, 0.315, 0.632)]),
    "S5 v6 侧脸未测+正脸": (0, [(0.322, 0.32, 0.148, 0.14, 0.838, "未测"), (0.647, 0.288, 0.112, 0.395, 0.272)]),
    "S12 v11 男转头": (0, [(0.581, 0.32, 0.136, 0.303, -0.669), (0.31, 0.319, 0.104, 0.46, 0.106)]),
    "S4 v21 过肩侧脸前景": (0, [(0.188, 0.327, 0.174, 0.305, 0.511), (0.555, 0.314, 0.117, 0.415, 0.171)]),
    "S5 v5 前后错落": (0, [(0.644, 0.284, 0.128, 0.424, 0.148), (0.418, 0.414, 0.101, 0.25, 0.393)]),
    "S2 v17 单人": (0, [(0.468, 0.268, 0.141, 0.325, 0.439)]),
}


def test_lineup_geo_calibration_all_correct():
    for name, (lab, faces) in CALIB.items():
        rows = [_row(*f) for f in faces]
        r = GZ.lineup_geo(rows, W, H)
        assert r["lineup"] is bool(lab), f"{name}: 期望 {lab}，得到 {r}"
        if lab:
            assert r["n"] >= 2 and r["pairs"]
    assert GZ.lineup_geo([], W, H)["lineup"] is False
    assert GZ.lineup_geo([_row(0.5, 0.3, 0.1, 0.4, 0.1)], W, H)["lineup"] is False


def test_lineup_geo_thresholds_overridable():
    rows = [_row(*f) for f in CALIB["S15 v12 两人并排"][1]]
    assert GZ.lineup_geo(rows, W, H, {"size_ratio": 0.99})["lineup"] is False
    assert GZ.lineup_geo(rows, W, H)["thr"]["size_ratio"] == GZ.LINEUP["size_ratio"]


def test_image_gaze_reports_lineup_on_real_frame():
    """真图（笔记本 offline_pull 里的 S15 v12 当前首帧，项目方点名的两人并排）→ YuNet 几何判命中；没有模型 / 图不在就跳过"""
    import glob
    hits = glob.glob(str(ROOT / "data/_offline_pull/gpu33/*/data/renders/series10_v2/ep01/S15/takes/image_012_*_raw_post.png"))
    if not hits or GZ._models(ROOT) is None:
        pytest.skip("标定图 / YuNet 模型不在本机")
    import cv2
    r = GZ.image_gaze(cv2.imread(hits[0]), GZ._models(ROOT))
    assert r["lineup"]["lineup"] is True and r["lineup"]["n"] == 2


def test_gaze_item_lineup_fail_and_evidence(monkeypatch, tmp_path):
    monkeypatch.setattr(PF, "hard_set", lambda conf=None: {"gaze"})
    faces = [_row(*f) for f in CALIB["S15 v12 两人并排"][1]]
    monkeypatch.setattr(PF, "gaze_raw", lambda image: {"status": "视线离轴", "faces": faces, "measured": 2,
                                                       "lineup": GZ.lineup_geo(faces, W, H)})
    st, d, ev = PF.gaze_item(tmp_path / "x.png")
    assert st == "fail" and "排排站" in d and ev["lineup_geo"]["lineup"] is True and ev["lineup_geo"]["n"] == 2
    monkeypatch.setattr(PF, "gaze_raw", lambda image: {"status": "视线离轴", "faces": faces[:1], "measured": 1,
                                                       "lineup": GZ.lineup_geo(faces[:1], W, H)})
    st, d, ev = PF.gaze_item(tmp_path / "x.png")
    assert st == "pass" and ev["lineup_geo"]["lineup"] is False
    monkeypatch.setattr(PF, "gaze_raw", lambda image: {"status": "未测", "why": "读不到图", "faces": [], "error": "unreadable"})
    assert PF.gaze_item(tmp_path / "x.png")[0] == "untested"


def _pf(items):
    return {"ok": False, "items": items, "blocking": [i["id"] for i in items if i["status"] in ("fail", "untested")], "reasons": []}


def test_blocking_g1_lineup_hard_even_when_vqa_saw_nothing():
    pf = _pf([{"id": "G1", "status": "fail", "evidence": {"gaze": "视线离轴", "lineup_geo": {"lineup": True, "n": 2, "pairs": [[0, 1]]},
                                                           "faces": [{"gaze_x": 0.9, "status": "视线离轴"}]}},
              {"id": "Q9", "status": "pass", "evidence": {"defects": [], "model": "Qwen3-VL-8B-Instruct"}}])
    out = BL.apply(pf, HARD)
    assert out["ok"] is False and out["blocking"] == ["G1"]
    # 没有几何排排站、只是 YuNet 疑似看镜头、看图真看过没报 → 以看图为准（原口径不变）
    pf2 = _pf([{"id": "G1", "status": "fail", "evidence": {"gaze": "疑似看镜头", "lineup_geo": {"lineup": False, "n": 0, "pairs": []}}},
               {"id": "Q9", "status": "pass", "evidence": {"defects": [], "model": "Qwen3-VL-8B-Instruct"}}])
    out2 = BL.apply(pf2, HARD)
    assert out2["ok"] is True and out2["record_only_items"] == ["G1"]


def test_blocking_eye_contact_demoted_only_when_yunet_clearly_offaxis():
    q9 = {"id": "Q9", "status": "fail", "evidence": {"defects": ["eye_contact"], "model": "Qwen3-VL-8B-Instruct"}, "detail": "演员看镜头"}
    g1_off = {"id": "G1", "status": "pass", "evidence": {"gaze": "视线离轴", "faces": [{"gaze_x": 0.978, "status": "视线离轴"}]}}
    out = BL.apply(_pf([dict(q9, evidence=dict(q9["evidence"])), g1_off]), HARD)
    q9o = next(i for i in out["items"] if i["id"] == "Q9")
    assert out["ok"] is True and q9o["status"] == "na" and q9o["record_only"] and "eye_contact" in q9o["evidence"]["ignored_defects"]
    # 任一测得的脸接近轴心（0.1）→ 不矛盾，照挡
    g1_cam = {"id": "G1", "status": "pass", "evidence": {"gaze": "视线离轴", "faces": [{"gaze_x": 0.1, "status": "视线离轴"}, {"gaze_x": 1.2, "status": "视线离轴"}]}}
    out2 = BL.apply(_pf([dict(q9, evidence=dict(q9["evidence"])), g1_cam]), HARD)
    assert out2["ok"] is False and "Q9" in out2["blocking"]
    # 看图报了 lineup → 不降级
    q9l = dict(q9, evidence={"defects": ["eye_contact", "lineup"], "model": "x"})
    out3 = BL.apply(_pf([q9l, dict(g1_off)]), HARD)
    assert out3["ok"] is False and "Q9" in out3["blocking"]
    # 没有 G1 证据（脸太小 / 未测）→ 不降级
    out4 = BL.apply(_pf([dict(q9, evidence=dict(q9["evidence"]))]), HARD)
    assert out4["ok"] is False


def test_blocking_q10_people_structured_beats_header_string():
    base = {"status": "fail", "why": "people_count、positions、action不符：画面里有2人（祁念和唐瑶背影），但编译稿只写1人"}
    q10 = lambda prompt: _pf([{"id": "Q10", "status": "fail", "evidence": {"prompt": prompt, "identity": {"status": "pass"}, "count": {"status": "pass"}}}])  # noqa: E731
    assert BL.apply(q10({**base, "people": {"status": "pass", "visible": 2, "range": [1, 2]}}), HARD)["ok"] is True
    assert BL.apply(q10({**base, "people": {"status": "fail", "visible": 3, "range": [1, 2]}}), HARD)["ok"] is False
    assert BL.apply(q10(dict(base)), HARD)["ok"] is False          # 旧证据（没有 people）：字符串口径照旧
    assert BL._q10_prompt_people_bad({"prompt": {"status": "fail", "why": "positions不符：左右反了"}}) is False


def test_prompt_check_people_structured(monkeypatch):
    from tools.vqa import accept as AC
    from ns_agent.vqa import client as VC
    from ns_agent.vqa import continuity as CT
    from ns_agent.gen_contract import accept as GA
    from tools.vqa import anomaly as AN
    monkeypatch.setattr(CT, "shot_rec", lambda sid: {"x": 1})
    monkeypatch.setattr(GA, "shot_description", lambda rec, stage=None: "编译稿：祁念在中，唐瑶背影在右下角")
    monkeypatch.setattr(AC, "people_gate_on", lambda project=None: True)
    monkeypatch.setattr(AN, "shot_cast", lambda sid: [{"name": "祁念", "presence": "在画"}, {"name": "唐瑶", "presence": "局部"}])
    ans = {}
    monkeypatch.setattr(VC, "generate", lambda req, **kw: {"text": json.dumps(ans, ensure_ascii=False)})
    # ① 看图说 people_count 不符、可见 2 人、cast 区间 1–2 → 人数算过（只记录），其它项都符合 → pass
    ans.update({"people_count": "不符", "positions": "符合", "action": "符合", "scene": "符合", "e": "编译稿只写1人", "visible_people": 2})
    r = AC.prompt_check("ep01-S2", "x.png")
    assert r["status"] == "pass" and r["people"] == {"status": "pass", "visible": 2, "range": [1, 2], "why": None}
    assert "只记录" in r["checks"]["people_count_vlm"]
    # ② 同上但站位不符 → fail，why 不再带 people_count，people 仍 pass（blocking 不算人数硬项）
    ans.update({"positions": "不符"})
    r2 = AC.prompt_check("ep01-S2", "x.png")
    assert r2["status"] == "fail" and r2["why"].startswith("positions不符") and r2["people"]["status"] == "pass"
    assert BL._q10_prompt_people_bad({"prompt": r2}) is False
    # ③ 可见 3 人 > 上限 2 → 人数硬项
    ans.update({"positions": "符合", "visible_people": 3})
    r3 = AC.prompt_check("ep01-S2", "x.png")
    assert r3["status"] == "fail" and r3["people"]["status"] == "fail" and BL._q10_prompt_people_bad({"prompt": r3}) is True
    # ④ 看图没给整数、自由判不符 → 老口径（字符串）照挡
    ans.pop("visible_people")
    r4 = AC.prompt_check("ep01-S2", "x.png")
    assert r4["status"] == "fail" and "people" not in r4 and BL._q10_prompt_people_bad({"prompt": r4}) is True


def test_side_face_relax_lowers_review_floor_only(monkeypatch):
    t1 = {"side_face": {"enabled": True, "yaw_min": 0.4, "iod_w_max": 0.30, "lo_delta": -0.10}}
    monkeypatch.setattr(PF, "face_pose_for", lambda image, bbox, min_iou=0.3: {"yaw_n": 0.63, "iod_w": 0.31, "status": "视线离轴"})
    d, note = PF.side_face_relax("x.png", [0, 0, 10, 10], t1)
    assert d == -0.10 and "侧脸" in note
    monkeypatch.setattr(PF, "face_pose_for", lambda image, bbox, min_iou=0.3: {"yaw_n": 0.1, "iod_w": 0.42, "status": "视线离轴"})
    assert PF.side_face_relax("x.png", [0, 0, 10, 10], t1) == (0.0, None)
    monkeypatch.setattr(PF, "face_pose_for", lambda image, bbox, min_iou=0.3: None)          # 对不上 YuNet → 不放宽
    assert PF.side_face_relax("x.png", [0, 0, 10, 10], t1) == (0.0, None)
    assert PF.side_face_relax("x.png", [0, 0, 10, 10], {"side_face": {"enabled": False}}) == (0.0, None)


def test_face_pose_for_matches_by_iou(monkeypatch):
    rows = [{"box": [200, 220, 120, 150], "iod": 36.0, "yaw_n": 0.55, "status": "视线离轴"},
            {"box": [500, 90, 80, 120], "iod": 34.0, "yaw_n": 0.2, "status": "视线离轴"}]
    monkeypatch.setattr(PF, "gaze_raw", lambda image: {"status": "视线离轴", "faces": rows})
    p = PF.face_pose_for("x.png", [222.9, 226.0, 341.8, 378.9])
    assert p and p["yaw_n"] == 0.55 and p["iod_w"] == 0.3
    assert PF.face_pose_for("x.png", [0, 0, 20, 20]) is None


def test_live_config_side_face_and_prompt_wording():
    c = json.loads((ROOT / "config/gen_contract.json").read_text(encoding="utf-8"))
    sf = c["image_thresholds"]["Q1_identity"]["side_face"]
    assert sf["enabled"] is True and sf["lo_delta"] == -0.10 and sf["yaw_min"] == 0.4
    md = (ROOT / "config/prompts/vqa_inspect.md").read_text(encoding="utf-8")
    assert "同一纵深" in md and "视线不看镜头" in md and "过肩镜" in md


# ---------------------------------------------------------------- ⑤ producer：尾帧不再反复作废清零；⑥ FL 换构图阶梯
def test_last_consistent_counts_redo_instead_of_void_loop():
    import producer as PR
    fa = {"n": 22, "stage": "image", "file": "renders/ep01/S9/takes/image_022_x.png", "created_at": "2026-11-06T09:50:00"}
    la = {"n": 3, "stage": "last", "file": "renders/ep01/S9/takes/last_003_x.png", "created_at": "2026-11-06T10:10:00",
          "references": ["renders/ep01/S9/takes/image_012_old.png"], "from_first": 12}     # 配旧首帧 v12 出的（E13：stale）
    td = {"active": {"image": 22, "last": 3}, "takes": [fa, la]}
    fo = {"status": "passed"}
    lo = {"status": "passed", "attempts": 0}
    r0 = PR.last_consistent(td, fo, lo, {})
    assert r0["voided"] and r0["status"] == "ready" and r0["attempts"] == 0 and r0["stale_active_last"] == 3   # 首帧刚换：作废一次
    led = {"voided_at": "2026-11-06T14:00:00", "tries": 0, "final": "passed"}
    td["takes"] += [{"n": 10, "stage": "last", "file": "l10.png", "created_at": "2026-11-06T14:50:00", "references": [fa["file"]]},
                    {"n": 11, "stage": "last", "file": "l11.png", "created_at": "2026-11-06T15:30:00", "references": [fa["file"]]}]
    r1 = PR.last_consistent(td, fo, lo, led)
    assert not r1.get("voided") and r1["status"] == "ready" and r1["attempts"] == 2 and r1["redo_for_first"] == 22
    assert PR.last_tries_for(td, fa, la, since=led["voided_at"]) == 2 and PR.last_tries_for(td, fa, la, since="2026-11-06T16:00:00") == 0
    # 尾帧已配当前首帧（不 stale）→ 原样
    td2 = {"active": {"image": 22, "last": 11}, "takes": td["takes"]}
    assert PR.last_consistent(td2, fo, lo, led) is lo
    # 首帧没过 → 仍按原口径 pending 作废
    r2 = PR.last_consistent(td, {"status": "pending"}, lo, led)
    assert r2["voided"] and r2["status"] == "pending"


def test_fl_escalate_level_from_ledger_history():
    import producer as PR
    hist = [{"try": 1, "blocking": ["FL"]}, {"try": 2, "blocking": ["FL", "Q1"]}]
    fake = type("P", (), {"ledger": lambda self: {"last:ep01-S9": {"history": hist}}})()
    o = {"id": "last:ep01-S9", "kind": "last"}
    assert PR.Producer.fl_escalate_level(fake, o, 1) == 0
    assert PR.Producer.fl_escalate_level(fake, o, 2) == 2
    assert PR.Producer.fl_escalate_level(fake, {"id": "first:ep01-S9", "kind": "first"}, 2) == 0
    fake2 = type("P", (), {"ledger": lambda self: {"last:ep01-S9": {"history": [{"try": 1, "blocking": ["Q1"]}]}}})()
    assert PR.Producer.fl_escalate_level(fake2, o, 2) == 0
    fake3 = type("P", (), {"ledger": lambda self: {"last:ep01-S9": {"history": [{"try": 1, "blocking": ["FL"], "before_void": True}]}}})()
    assert PR.Producer.fl_escalate_level(fake3, o, 2) == 0


def test_vqa_gate_runs_vlm_when_only_g1_failed():
    import inspect
    import producer as PR
    src = inspect.getsource(PR.vqa_gate)
    assert 'if b not in ("Q9", "Q1", "G1")' in src


def test_tighten_last_shot_and_compose_fl_escalate():
    from ns_agent import frame_job as FJ
    assert FJ.tighten_size("中景", 1) == "近景" and FJ.tighten_size("中景", 2) == "中近景" and FJ.tighten_size("极近特写", 1) == "极近特写"
    assert FJ.tighten_size(None, 1) is None and FJ.tighten_size("中景", 0) == "中景"
    shot2 = {"img_prompt": "中景紧俯拍（上身到脚尖），祁念站直撑椅面", "motion_prompt": "中景紧俯拍（上身到脚尖），祁念站直撑椅面",
             "extras": [{"label": "机位与景别", "text": "中景｜机位在右前方、高机位俯拍｜落幅=两人同框"}, {"label": "构图", "text": "落幅=两人同框"}]}
    s3, end = FJ.tighten_last_shot(shot2, shot2["motion_prompt"], 1)
    assert end.startswith("近景紧俯拍") and FJ.TIGHTER_NOTE in end
    assert s3["img_prompt"].startswith("近景") and FJ.TIGHTER_NOTE in s3["img_prompt"]
    ang = next(e for e in s3["extras"] if e["label"] == "机位与景别")
    assert ang["text"].startswith("近景｜机位在右前方") and next(e for e in s3["extras"] if e["label"] == "构图")["text"] == "落幅=两人同框"


SCRIPT = ROOT / "data/import/runs/series10_v2/script_v2.json"


@pytest.mark.skipif(not SCRIPT.exists(), reason="series10_v2 导入稿不在")
def test_build_last_compose_fl_escalate_drops_first_frame_ref(monkeypatch):
    from ns_agent import frame_job as FJ
    from ns_render import pipeline as P
    from ns_schema import script as S
    monkeypatch.setenv("NS_LAST_FRAME_MODE", "compose")
    script = S.ScriptImport.model_validate(json.loads(SCRIPT.read_text(encoding="utf-8")))
    ep, shot = P.find_shot(script, "ep01-S9")
    first = FJ.build_first("series10_v2", ep, shot, script.globals)
    base = FJ.build_last(first, "data/x_first.png", project="series10_v2", ep=ep, shot=shot, g=script.globals)
    esc = FJ.build_last(first, "data/x_first.png", project="series10_v2", ep=ep, shot=shot, g=script.globals, plan_kw={"fl_escalate": 1})
    assert base["refs"][-1] == "data/x_first.png" and "data/x_first.png" not in esc["refs"]
    assert esc["fl_escalate"]["level"] == 1 and esc["first_frame_file"] == "data/x_first.png" and esc["last_frame_mode"] == "compose"
    assert FJ.TIGHTER_NOTE in esc["prompt"] and "本镜头首帧" not in esc["prompt"]
    size0, size1 = FJ.AR.FR.size_of(base["end_framing"]), FJ.AR.FR.size_of(esc["end_framing"])
    if size0:
        assert FJ.AR.FR.SIZES.index(size1) <= FJ.AR.FR.SIZES.index(size0)


# ---------------------------------------------------------------- 复审（PS-MASTER 11-06 20:xx）五项
def _s9_like_td(n_hist: int = 27):
    """S9 实况：首帧 v22（09:52）、旧尾帧 v3 当前（配 v12）、之后 27 版尾帧都配 v22 且都没过（历史垃圾）"""
    fa = {"n": 22, "stage": "image", "file": "renders/ep01/S9/takes/image_022_x.png", "created_at": "2026-11-06T09:52:00"}
    la = {"n": 3, "stage": "last", "file": "renders/ep01/S9/takes/last_003_x.png", "created_at": "2026-11-06T10:10:00",
          "references": ["renders/ep01/S9/takes/image_012_old.png"], "from_first": 12}
    hist = [{"n": 9 + i, "stage": "last", "file": f"l{9 + i}.png", "created_at": f"2026-11-06T{14 + i // 4:02d}:{(i % 4) * 15:02d}:00",
             "references": [fa["file"]]} for i in range(n_hist)]
    return {"active": {"image": 22, "last": 3}, "takes": [fa, la] + hist}, fa, la


def test_last_consistent_s9_history_reaches_terminal_within_3_new_tries():
    import producer as PR
    td, fa, la = _s9_like_td()
    fo, lo = {"status": "passed"}, {"status": "passed", "attempts": 0}
    # 拍 1：账本还没 voided_at → 历史 27 版不算，走作废一次（并带上要撤的过期当前尾帧）
    r0 = PR.last_consistent(td, fo, lo, {"tries": 1, "final": "passed"})
    assert r0["voided"] and r0["attempts"] == 0 and r0["stale_active_last"] == 3
    assert PR.last_tries_for(td, fa, la, since=None) == 0
    # void_reset 之后：voided_at = 现在；之后每出一版（配 v22）算一次；≤3 次到终态
    since = "2026-11-06T21:00:00"
    led = {"voided_at": since, "tries": 0, "final": "passed"}
    assert PR.last_tries_for(td, fa, la, since=since) == 0                     # 历史 27 版不算
    for k in (1, 2):
        td["takes"].append({"n": 40 + k, "stage": "last", "file": f"new{k}.png", "created_at": f"2026-11-06T21:{k:02d}:00", "references": [fa["file"]]})
        r = PR.last_consistent(td, fo, lo, led)
        assert r["status"] == "ready" and r["attempts"] == k and r["stale_active_last"] == 3 and not r.get("voided")
    td["takes"].append({"n": 43, "stage": "last", "file": "new3.png", "created_at": "2026-11-06T21:03:00", "references": [fa["file"]]})
    r3 = PR.last_consistent(td, fo, lo, led)
    assert r3["status"] == "best_effort" and r3["last_redo_exhausted"] and r3["attempts"] == 3 and r3["stale_active_last"] == 3
    # 当前尾帧被撤掉后（正常路径）：不再 stale，原样返回账本口径
    td["active"].pop("last")
    assert PR.last_consistent(td, fo, {"status": "ready", "attempts": 2}, led)["attempts"] == 2


class _FakeProducer:
    def __init__(self, ledger=None):
        self._led = ledger or {}
        self.updates, self.logs = [], []
        self.p = type("P", (), {"run_id": "series10_v2", "root": ROOT})()

    def ledger(self):
        return self._led

    def ep_closed_skip(self, *a, **k):          # S2.2：集关闭判定（测试里集都开着）
        return False

    def led_update(self, oid, **kw):
        self.updates.append((oid, kw))
        self._led.setdefault(oid, {}).update(kw)
        return self._led[oid]

    def logf(self, ev, **kw):
        self.logs.append((ev, kw))

    def two_person(self, sid):
        return True

    def clear_stale_last(self, o, why):
        import producer as PR
        return PR.Producer.clear_stale_last(self, o, why)


def test_void_reset_clears_stale_active_last(monkeypatch):
    import producer as PR
    from ns_render import pipeline as P
    cleared = []
    monkeypatch.setattr(P, "clear_active", lambda sid, stage, reason, actor=None: cleared.append((sid, stage, actor)))
    fp = _FakeProducer({"last:ep01-S9": {"tries": 3, "final": "passed", "history": [{"try": 1}]}})
    o = {"id": "last:ep01-S9", "shot": "ep01-S9", "kind": "last", "voided": True, "stale_active_last": 3, "reason": "首帧换过"}
    led = PR.Producer.void_reset(fp, o, fp.ledger()["last:ep01-S9"])
    assert led["tries"] == 0 and led["final"] is None and led["voided_at"]
    assert cleared == [("ep01-S9", "last", "producer.clear_stale_last")]
    assert any(ev == "stale_last_cleared" for ev, _ in fp.logs)
    # 没有过期当前尾帧（首帧没过的作废）→ 不撤
    cleared.clear()
    PR.Producer.void_reset(fp, {"id": "last:ep01-S9", "shot": "ep01-S9", "kind": "last", "voided": True}, {})
    assert cleared == []


def test_stale_last_sweep_lands_terminal_state(monkeypatch):
    import producer as PR
    from ns_render import pipeline as P
    cleared = []
    monkeypatch.setattr(P, "clear_active", lambda sid, stage, reason, actor=None: cleared.append(sid))
    fp = _FakeProducer({"last:ep01-S9": {"tries": 0, "final": "passed"}, "last:ep01-S4": {"tries": 1, "final": "passed"}})
    reg = {"episodes": [{"shots": [
        {"shot": "ep01-S9", "objects": {"last": {"id": "last:ep01-S9", "shot": "ep01-S9", "status": "best_effort", "attempts": 3,
                                                 "stale_active_last": 3, "last_redo_exhausted": True, "reason": "3 次用尽"}}},
        {"shot": "ep01-S4", "objects": {"last": {"id": "last:ep01-S4", "shot": "ep01-S4", "status": "ready", "attempts": 1,
                                                 "stale_active_last": 8, "reason": "继续"}}},
        {"shot": "ep01-S7", "objects": {"last": {"id": "last:ep01-S7", "shot": "ep01-S7", "status": "ready", "voided": True, "stale_active_last": 5}}},
        {"shot": "ep01-S2", "objects": {"last": {"id": "last:ep01-S2", "shot": "ep01-S2", "status": "passed"}}}]}]}
    out = PR.Producer.stale_last_sweep(fp, reg)
    assert out == ["last:ep01-S9", "last:ep01-S4"] and cleared == ["ep01-S9", "ep01-S4"]   # voided 的交 dispatch/void_reset
    l9, l4 = fp.ledger()["last:ep01-S9"], fp.ledger()["last:ep01-S4"]
    assert l9["final"] == "best_effort" and l9["redo_exhausted"] and l9["tries"] == 3        # 终态 → adopt / D8
    assert l4["final"] is None and l4["tries"] == 1                                          # 继续按账本计次


def test_build_first_previz_stage_explicit(monkeypatch):
    from ns_agent import frame_job as FJ
    from ns_render import pipeline as P
    from ns_schema import script as S
    if not SCRIPT.exists():
        pytest.skip("series10_v2 导入稿不在")
    script = S.ScriptImport.model_validate(json.loads(SCRIPT.read_text(encoding="utf-8")))
    ep, shot = P.find_shot(script, "ep01-S9")
    seen = []
    monkeypatch.setattr(FJ, "first_frame_tier", lambda project, force=None, episode=None: ("turbo_previz", {}))
    monkeypatch.setattr(FJ, "previz_or_none", lambda sid, shot, g, stage="first": (seen.append(stage) or ({"auto": {"stage": stage}}, "")))
    FJ.build_first("series10_v2", ep, shot, script.globals, frame_stage="last")
    FJ.build_first("series10_v2", ep, shot, script.globals, continuity_ref=("data/x.png", "图{n}是本镜头首帧"))
    FJ.build_first("series10_v2", ep, shot, script.globals)
    assert seen == ["last", "last", "first"]
    first = FJ.build_first("series10_v2", ep, shot, script.globals)
    monkeypatch.setenv("NS_LAST_FRAME_MODE", "compose")
    esc = FJ.build_last(first, "data/x_first.png", project="series10_v2", ep=ep, shot=shot, g=script.globals, plan_kw={"fl_escalate": 1})
    assert seen[-1] == "last" and esc.get("previz") and "previz_missing" not in esc      # 去掉首帧参考后尾帧摆位图照算


def test_lineup_recheck_caches_negative_and_persists(monkeypatch):
    import producer as PR
    from ns_agent.gen_contract import postflight as PF
    from ns_render import frame_edit as FE
    calls, annotated = [], []
    monkeypatch.setattr(PF, "gaze_raw", lambda image: (calls.append(image) or {"status": "视线离轴", "faces": [], "lineup": {"lineup": False, "n": 0, "pairs": []}}))
    monkeypatch.setattr(FE, "annotate", lambda sid, stage, n, **f: annotated.append((sid, stage, n, "lineup_geo" in f["postflight"]["items"][0]["evidence"])))
    fp = _FakeProducer()
    t = {"n": 3, "file": "renders/series10_v2/ep01/S1/takes/image_003.png"}
    pf = {"ok": True, "items": [{"id": "G1", "status": "na", "evidence": {"gaze": "视线离轴"}}]}
    assert PR.Producer.lineup_recheck(fp, "ep01-S1", t, pf) is False
    assert len(calls) == 1 and annotated == [("ep01-S1", "image", 3, True)]
    assert pf["items"][0]["evidence"]["lineup_geo"]["lineup"] is False
    assert PR.Producer.lineup_recheck(fp, "ep01-S1", t, pf) is False and len(calls) == 1      # 进程内 seen：不再跑 YuNet
    pf2 = {"ok": True, "items": [{"id": "G1", "status": "na", "evidence": {"gaze": "视线离轴", "lineup_geo": {"lineup": False}}}]}
    assert PR.Producer.lineup_recheck(fp, "ep01-S1", {"n": 4, "file": "x.png"}, pf2) is False and len(calls) == 1   # 落盘过的也不跑
    # 阳性：G1 改 fail、不落盘（交 gaze_regen_sweep 撤下并 annotate 改判）
    monkeypatch.setattr(PF, "gaze_raw", lambda image: {"status": "视线离轴", "faces": [], "lineup": {"lineup": True, "n": 2, "pairs": [[0, 1]]}})
    pf3 = {"ok": True, "items": [{"id": "G1", "status": "na", "evidence": {"gaze": "视线离轴"}}]}
    assert PR.Producer.lineup_recheck(fp, "ep01-S14", {"n": 2, "file": "y.png"}, pf3) is True
    assert pf3["items"][0]["status"] == "fail" and len(annotated) == 1


def test_vqa_lineup_record_only_geo_is_hard():
    import producer as PR
    q9 = {"id": "Q9", "status": "fail", "evidence": {"defects": ["lineup"], "model": "Qwen3-VL-8B-Instruct"}, "detail": "排排站"}
    out = BL.apply(_pf([dict(q9, evidence=dict(q9["evidence"]))]), HARD)
    assert out["ok"] is True and out["record_only_items"] == ["Q9"]
    assert PR.gaze_bad({"items": [dict(q9, evidence=dict(q9["evidence"]))]}) is False       # 看图 lineup 不算 never_adopt
    g1 = {"id": "G1", "status": "fail", "evidence": {"gaze": "视线离轴", "lineup_geo": {"lineup": True, "n": 2, "pairs": [[0, 1]]}}}
    assert BL.apply(_pf([g1, {"id": "Q9", "status": "pass", "evidence": {"defects": [], "model": "x"}}]), HARD)["ok"] is False
    assert PR.gaze_bad({"items": [g1]}) is True                                               # 几何排排站 = never_adopt


def test_eye_contact_not_demoted_when_faces_truncated():
    q9 = {"id": "Q9", "status": "fail", "evidence": {"defects": ["eye_contact"], "model": "x"}}
    faces = [{"gaze_x": 0.9, "status": "视线离轴"}] * 4
    g1 = {"id": "G1", "status": "pass", "evidence": {"gaze": "视线离轴", "faces": faces, "n_faces": 5}}
    assert BL.apply(_pf([dict(q9, evidence=dict(q9["evidence"])), g1]), HARD)["ok"] is False
    g1b = {"id": "G1", "status": "pass", "evidence": {"gaze": "视线离轴", "faces": faces, "n_faces": 4}}
    assert BL.apply(_pf([dict(q9, evidence=dict(q9["evidence"])), g1b]), HARD)["ok"] is True


def test_rung_fl_edit_mode_is_honest(monkeypatch):
    import producer as PR
    fp = _FakeProducer({"last:ep01-S9": {"history": [{"try": 1, "blocking": ["FL"]}]}})
    fp.seed_pick = lambda o, attempt, *a, **k: (123, None)
    fp.fl_escalate_level = lambda o, attempt: PR.Producer.fl_escalate_level(fp, o, attempt)
    o = {"id": "last:ep01-S9", "shot": "ep01-S9", "kind": "last"}
    monkeypatch.setattr(PR._VM, "last_frame_mode", lambda run, root=None: "compose")
    r = PR.Producer.rung(fp, o, 2)
    assert r["plan_kw"] == {"fl_escalate": 1} and "换构图" in r["name"]
    monkeypatch.setattr(PR._VM, "last_frame_mode", lambda run, root=None: "edit")
    r2 = PR.Producer.rung(fp, o, 2)
    assert r2["plan_kw"] == {} and "只换 seed" in r2["name"] and r2["variant"] == "fl_seed_only"


def test_deliver_survives_register_error(monkeypatch, tmp_path):
    import asset_worker as AW
    from tools.pipeline import asset_jobs as AJ
    job = {"id": "face-ch_li_an", "kind": "face", "run": "series10_v2", "spec": {"name": "黎岸"}, "pick_id": "pick-1", "log": []}
    jp = tmp_path / "job.json"
    (tmp_path / "review").mkdir()
    monkeypatch.setattr(AW.AJ, "delegate_active", lambda root: (True, "on"))
    monkeypatch.setattr(AW.AJ, "save_job", lambda root, j: jp)
    monkeypatch.setattr(AW.AJ, "load_job", lambda p: job)
    monkeypatch.setattr(AW.AJ, "log", lambda j, msg: j.setdefault("log", []).append(msg))
    monkeypatch.setattr(AW, "review_dir", lambda root, j: tmp_path / "review")
    posted = []
    monkeypatch.setattr(AW.AJ, "post_pick", lambda root, j, cands, title, detail, recommend=None, why="": posted.append((title, len(cands))) or "pick-1")

    def boom(root, j, cands, who, what, pusher=None):
        raise AW.AJ.RegisterError("黎岸 的身份脸已由项目方登记（清单 face 已有），不覆盖")   # 与 asset_worker 看到的同一个类
    assert AJ.RegisterError.__name__ == AW.AJ.RegisterError.__name__
    monkeypatch.setattr(AW.AJ, "auto_pick", boom)
    passed = [{"seed": 1200, "review_file": "r/a.png", "thumb": "r/a.jpg", "sha256": "x"}]
    out = AW.deliver(tmp_path, jp, job, passed)
    assert out["state"] == "awaiting_pick" and "已由项目方登记" in out["auto_pick_failed"]
    assert posted == [("挑 黎岸 的身份脸（1 选 1）", 1)] and any("代选登记被拒" in m for m in out["log"])
