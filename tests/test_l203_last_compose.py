"""L-203（项目方 11-06 08:3x：“你所有的首尾帧都是一模一样的图片……现在全部都错了”）：
① 撤回 L-197 A / L-201 ②——series10_v2 video_mode = fl2va（任何集 / 任何镜都要尾帧；I2VA 代码路径保留，只是开关关）；
② 尾帧 compose：落幅（motion “——”之后）当新图编——同首帧模板 / 同参考槽逻辑，通过契约的首帧挂最后一张、弱指令只保一致性；
③ 尾帧 postflight FL 首尾帧比对硬项：太像 = 不过、换种子重出，不进 review_adopt / best_effort 采用。
全部 mock / 临时目录，不碰 GPU、不写真实数据。"""
import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/agent", "services/render_router", "packages/schema", "packages/qc", "tools/pipeline", "tools/autopilot", ""):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))

from ns_agent import frame_job as FJ  # noqa: E402
from ns_agent import video_mode as VM  # noqa: E402
from ns_agent.gen_contract import blocking as BL  # noqa: E402
from ns_agent.gen_contract import first_last as FL  # noqa: E402

SCRIPT = ROOT / "data/import/runs/series10_v2/script_v2.json"


# ---------------------------------------------------------------- ① 开关
def _cfg(monkeypatch, run_cfg):
    monkeypatch.setattr(VM, "_cfg", lambda root=None: {"runs": {"series10_v2": run_cfg}})
    monkeypatch.delenv("NS_VIDEO_MODE", raising=False)
    monkeypatch.delenv("NS_LAST_FRAME_MODE", raising=False)


def test_live_config_fl2va_and_compose():
    d = json.loads((ROOT / "config/compile/run_style.json").read_text(encoding="utf-8"))["runs"]["series10_v2"]
    assert d["video_mode"]["mode"] == "fl2va" and "L-203" in d["video_mode"]["_doc"] and not d["video_mode"].get("shots")
    assert d["last_frame_mode"] == "compose"
    for ep in (1, 2, 3):
        assert VM.no_last("series10_v2", ep, ROOT) is False
    assert VM.no_last("series10_v2", 1, ROOT, shot="ep01-S1") is False and VM.no_last("series10_v2", 1, ROOT, shot="ep01-S2") is False
    assert VM.last_frame_mode("series10_v2", ROOT) == "compose"


def test_last_frame_mode_reader(monkeypatch):
    _cfg(monkeypatch, {"last_frame_mode": "compose"})
    assert VM.last_frame_mode("series10_v2") == "compose"
    assert VM.last_frame_mode("series10_v1") == "edit" and VM.last_frame_mode(None) == "edit"
    _cfg(monkeypatch, {})
    assert VM.last_frame_mode("series10_v2") == "edit"                      # 不配 = 旧法
    _cfg(monkeypatch, {"last_frame_mode": "bogus"})
    assert VM.last_frame_mode("series10_v2") == "edit"
    _cfg(monkeypatch, {"last_frame_mode": "compose"})
    monkeypatch.setenv("NS_LAST_FRAME_MODE", "edit")
    assert VM.last_frame_mode("series10_v2") == "edit"                      # env 临时覆盖


def test_i2va_code_path_still_works_when_switched_back(monkeypatch):
    _cfg(monkeypatch, {"video_mode": {"mode": "i2va", "from_episode": 2, "shots": ["ep01-S1"]}})
    assert VM.no_last("series10_v2", 2) and VM.no_last("series10_v2", 1, shot="ep01-S1") and not VM.no_last("series10_v2", 1)


def test_sop_gate_requires_lasts_again(monkeypatch):
    from tools.master import sop_gate as G
    monkeypatch.setattr(G, "shot_frames", lambda *a, **k: {})
    r = G.check_lasts(ROOT, "series10_v2", 2)
    assert "I2VA" not in r["why"]                                           # ep02 也要尾帧（原来 L-197 从 ep02 起不要）


def test_producer_creates_last_objects_again():
    from tools.autopilot import producer as PR
    assert not PR._VM.no_last("series10_v2", 1, ROOT, shot="ep01-S1") and not PR._VM.no_last("series10_v2", 2, ROOT)


def test_build_jobs_fl2va_sends_last_frame(monkeypatch):
    """build_jobs：开关关 → 配方送 @last_frame（Picture 2 对齐句在）"""
    import build_jobs as B
    from ns_recipes import registry as R
    from ns_schema.shot_spec import IdentityRef
    B.set_run("series10_v2")
    specs = B.load_specs()
    if not specs:
        pytest.skip("no specs")
    reg = R.load()
    rid = B.recipe_choice()["face_default"]
    spec = next(iter(specs.values())).model_copy(deep=True)
    spec.keyframes = {"last": IdentityRef(path="last.png")}
    ff = {spec.id: {"file": "x.png", "created_at": "2026-11-05 00:00:00"}}
    B.LASTS_OF.clear()
    B.LASTS_OF.update({spec.id: {"file": "y.png", "created_at": "2026-11-05 01:00:00"}})
    monkeypatch.setattr(B, "RUN_ID", "series10_v2")
    monkeypatch.delenv("NS_VIDEO_MODE", raising=False)
    out = B.compile_variant(spec, reg, rid, 1, "v1", ff)
    assert out.get("status") == "ready", out.get("status")
    assert "Picture 2" in out["prompt"] and "y.png" in json.dumps(out.get("inputs") or {})


# ---------------------------------------------------------------- ② compose
class _Shot(dict):
    pass


def _shot(motion, extras=None, cast=("祁念",)):
    return {"index": 1, "episode": 1, "img_prompt": "中景，侧 45° 机位，祁念站着", "img_triggers": [], "motion_prompt": motion,
            "motion_triggers": [], "extras": extras or [], "cast": [{"name": n, "presence": "在画"} for n in cast]}


def test_end_framing_after_dash_and_fallbacks():
    s = _shot("camera push in 小幅推近，她抬眼——近景，祁念抬眼看向灯圈、嘴唇微张")
    assert FJ.end_framing(s) == "近景，祁念抬眼看向灯圈、嘴唇微张"
    s = _shot("推近，她抬眼看灯——像在问什么")                                  # 比喻段跳过 → 没有落幅
    assert FJ.end_framing(s) == ""
    s = _shot("推近，她抬眼看灯", [{"label": "运镜", "text": "推近｜小幅｜起幅=中景 → 落幅=近景略紧，眼睛居中｜动机=x"}])
    assert FJ.end_framing(s) == "近景略紧，眼睛居中"
    assert FJ.end_framing(_shot("推近，她抬眼看灯")) == ""


def test_last_angle_field_follows_end_framing():
    ex = [{"label": "机位与景别", "text": "中景｜侧 45°、平视略低（A 区主机位）｜三人错落"},
          {"label": "运镜", "text": "推近｜小幅｜起幅=中景 → 落幅=中景略紧，肩同框｜动机=x"}]
    s = _shot("推近——中景，侧 45° 机位，祁念抬眼", ex)
    a = FJ.last_angle_field(s, FJ.end_framing(s))
    assert a.startswith("中景｜侧 45° 机位、平视略低｜中景略紧")               # 落幅只写方位 → 高度沿用首帧
    s = _shot("急推——中近景，机位正面偏右、低机位微仰锁定，祁念下巴抬着", ex)
    a = FJ.last_angle_field(s, FJ.end_framing(s))
    assert a.split("｜")[0] == "中近景" and "正面偏右" in a and "平视略低" not in a   # 落幅写了机位 + 高度 → 全按落幅
    s = _shot("固定——近景，祁念的手指悬在卡上方", ex)
    a = FJ.last_angle_field(s, FJ.end_framing(s))
    assert a.startswith("近景｜侧 45°、平视略低")                               # 落幅没写机位 → 沿用首帧机位段


def test_compose_last_shot_rewrites_fields():
    ex = [{"label": "机位与景别", "text": "中景｜侧 45°、平视｜x"}, {"label": "构图", "text": "前景=a｜中景=b"},
          {"label": "分拍", "text": "0–2秒｜x｜视线=门"}, {"label": "表演节拍", "text": "y"}, {"label": "灯光", "text": "主光=顶灯"},
          {"label": "运镜", "text": "推近｜小幅｜起幅=中景 → 落幅=近景略紧，眼睛居中｜动机=x"}]
    s = _shot("推近——近景，祁念抬眼看向灯圈", ex)
    s2 = FJ.compose_last_shot(s, FJ.end_framing(s))
    labels = [e["label"] for e in s2["extras"]]
    assert "分拍" not in labels and "表演节拍" not in labels and "灯光" in labels
    assert s2["img_prompt"] == "近景，祁念抬眼看向灯圈" and s2["motion_prompt"] == "近景，祁念抬眼看向灯圈"
    assert next(e["text"] for e in s2["extras"] if e["label"] == "构图") == "落幅=近景略紧，眼睛居中"
    assert next(e["text"] for e in s2["extras"] if e["label"] == "机位与景别").startswith("近景｜侧 45°、平视｜近景略紧")


def test_continuity_slot_appends_or_replaces_lowest_non_face():
    from ns_agent.asset_refs import Slot, SlotPlan
    mk = lambda i, kind, ch: Slot(i, kind, f"{kind}{i}.png", ch, [kind], [], line=f"图{i}是{kind}。")   # noqa: E731
    plan = SlotPlan("ep01-S1", "qwen_image_2.1", 3, [mk(1, "face", "lead_f"), mk(2, "board", "lead_f")], [], "头。图1是face。图2是board。", False, [], [])
    c = FJ.continuity_slot(plan, "qwen_image_2.1", "data/first.png", FJ.LAST_CONTINUITY_LINE)
    assert c["n"] == 3 and c["replaced"] is None and plan.prompt_prefix == "头。图1是face。图2是board。"
    assert c["line"].startswith("图3是本镜头首帧，只用来保持人物服装、发型、场景陈设与光线一致；构图、机位、景别按下面的结束画面重新构图")
    plan = SlotPlan("ep01-S4", "qwen_image_2.1", 3, [mk(1, "face", "lead_f"), mk(2, "board", "lead_f"), mk(3, "face", "ch_zhuo_lin")], [],
                    "图1是face。图2是board。图3是face。", False, [], [])
    c = FJ.continuity_slot(plan, "qwen_image_2.1", "data/first.png", FJ.LAST_CONTINUITY_LINE)
    assert c["n"] == 3 and c["replaced"]["kind"] == "board"                 # 槽满：最后一个非脸槽让位，脸一张不丢
    assert [s.kind for s in plan.slots] == ["face", "face"] and plan.prompt_prefix == "图1是face。图2是face。"
    assert plan.dropped and "L-203" in plan.dropped[0]["why"] and "的服装、鞋、饰品以本镜头首帧为准" in c["line"]


def _script():
    import ns_schema.script as S
    return S.ScriptImport.model_validate(json.loads(SCRIPT.read_text(encoding="utf-8")))


@pytest.mark.skipif(not SCRIPT.exists(), reason="series10_v2 导入稿不在")
def test_compose_on_real_ep01_s1_s2(monkeypatch):
    """真导入稿 ep01-S1 / S2：尾帧 = 落幅重新构图，首帧挂最后一张 + 弱指令；参考槽同首帧逻辑；不再带 bible last_frame_keep；种子不在作业里（producer 种子流）"""
    from ns_render import pipeline as P
    monkeypatch.setenv("NS_LAST_FRAME_MODE", "compose")
    script = _script()
    for sid in ("ep01-S1", "ep01-S2"):
        ep, shot = P.find_shot(script, sid)
        first = FJ.build_first("series10_v2", ep, shot, script.globals)
        last = FJ.build_last(first, "data/x_first.png", project="series10_v2", ep=ep, shot=shot, g=script.globals)
        assert last["id"] == sid + ":last" and last["stage"] == "last" and last["last_frame_mode"] == "compose"
        assert last["refs"][-1] == "data/x_first.png" and last["first_frame_file"] == "data/x_first.png"
        assert len(last["refs"]) <= 3 and "seed" not in last
        n = len(last["refs"])
        assert f"图{n}是本镜头首帧，只用来保持人物服装、发型、场景陈设与光线一致；构图、机位、景别按下面的结束画面重新构图" in last["prompt"]
        assert "保持图1的人物身份" not in last["prompt"] and "图1是本镜头的首帧画面" not in last["prompt"]
        assert last["end_framing"] and last["end_framing"] in shot.motion_prompt
        assert last["prompt"] != first["prompt"] and last["compile_trace"]["refs"][-1]["file"] == "data/x_first.png"
        assert last["preset"] == first["preset"] and last["negative"]
        assert "previz" not in last
    ep, shot = P.find_shot(script, "ep01-S2")
    first = FJ.build_first("series10_v2", ep, shot, script.globals)
    last = FJ.build_last(first, "data/x_first.png", project="series10_v2", ep=ep, shot=shot, g=script.globals)
    assert "中近景" in last["prompt"][:len(last["prompt"]) // 2] and "正面" in last["prompt"]     # S2 落幅：中近景正面偏右


@pytest.mark.skipif(not SCRIPT.exists(), reason="series10_v2 导入稿不在")
def test_edit_mode_unchanged_and_fallbacks(monkeypatch):
    from ns_render import pipeline as P
    script = _script()
    ep, shot = P.find_shot(script, "ep01-S1")
    first = FJ.build_first("series10_v2", ep, shot, script.globals)
    monkeypatch.setenv("NS_LAST_FRAME_MODE", "edit")
    last = FJ.build_last(first, "data/x_first.png", project="series10_v2", ep=ep, shot=shot, g=script.globals)
    assert last["last_frame_mode"] == "edit" and last["refs"][0] == "data/x_first.png" and last["first_frame_file"] == "data/x_first.png"
    assert first.get("last_prompt") and first["last_prompt"] in last["prompt"]
    monkeypatch.setenv("NS_LAST_FRAME_MODE", "compose")
    last2 = FJ.build_last(first, "data/x_first.png")                       # 旧入口没给 ep / shot / g → 退回旧法并记原因
    assert last2["last_frame_mode"] == "edit_fallback" and last2["refs"][0] == "data/x_first.png"
    shot3 = shot.model_copy(update={"motion_prompt": "推近，她抬眼看灯", "extras": [e for e in shot.extras if e.label != "运镜"]})
    last3 = FJ.build_last(first, "data/x_first.png", project="series10_v2", ep=ep, shot=shot3, g=script.globals)
    assert last3["last_frame_mode"] == "edit_fallback" and "落幅" in last3["last_frame_mode_why"]


# ---------------------------------------------------------------- ③ FL 首尾帧比对
def _png(path: Path, arr):
    from PIL import Image
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(arr.astype(np.uint8)).save(path)


def _gradient(h=224, w=128, shift=0, noise=0):
    y, x = np.mgrid[0:h, 0:w]
    base = ((x + shift) * 255 / w + y * 60 / h) % 255
    img = np.stack([base, base * 0.8, base * 0.6], -1)
    if noise:
        rng = np.random.default_rng(1)
        img = np.clip(img + rng.normal(0, noise, img.shape), 0, 255)
    return img


def test_fl_item_pass_fail_untested(tmp_path):
    a, b = tmp_path / "first.png", tmp_path / "last.png"
    _png(a, _gradient())
    _png(b, _gradient(noise=3))                                            # 几乎同一张
    it = FL.item(a, b)
    assert it["id"] == "FL" and it["status"] == "fail" and it["evidence"]["too_similar"] and it["blocking"] is True
    c = tmp_path / "other.png"
    rng = np.random.default_rng(7)
    _png(c, rng.integers(0, 255, (224, 128, 3)))                           # 完全不同的画面
    it2 = FL.item(a, c)
    assert it2["status"] == "pass" and it2["evidence"]["struct"] < 0.8 and it2["evidence"]["ssim"] < 0.85
    assert FL.item(None, c)["status"] == "untested"
    assert FL.item(tmp_path / "missing.png", c)["status"] == "untested"


def test_fl_thresholds_from_config():
    d = json.loads((ROOT / "config/gen_contract.json").read_text(encoding="utf-8"))
    assert "FL" in d["blocking_items"] and d["first_last"]["struct_max"] == 0.80 and d["first_last"]["ssim_max"] == 0.85
    assert FL.conf({})["struct_max"] == 0.80 and FL.conf({"first_last": {"struct_max": 0.5}})["struct_max"] == 0.5


def test_fl_apply_blocks_and_policy_keeps_it_hard(tmp_path):
    a, b = tmp_path / "f.png", tmp_path / "l.png"
    _png(a, _gradient())
    _png(b, _gradient(noise=2))
    pf = {"ok": True, "blocking": [], "reasons": [], "items": [{"id": "Q1", "status": "pass"}, {"id": "Q2", "status": "fail", "detail": "x"}]}
    pf = FL.apply(pf, a, b)
    assert pf["ok"] is False and "FL" in pf["blocking"] and any(r.startswith("FL") for r in pf["reasons"])
    conf = {"blocking_items": ["Q1", "count", "text", "adult", "gaze", "FL"]}
    pf = BL.apply(pf, conf)
    assert pf["blocking"] == ["FL"] and pf["ok"] is False                   # Q2 只记录；FL 硬项留着
    assert FL.too_similar(pf)
    # 不在名单里 = 只记录（旧口径可退）
    pf2 = FL.apply({"ok": True, "blocking": [], "reasons": [], "items": [{"id": "Q1", "status": "pass"}]}, a, b)
    pf2 = BL.apply(pf2, {"blocking_items": ["Q1", "count", "text", "adult", "gaze"]})
    assert pf2["ok"] is True and pf2["blocking"] == [] and not FL.too_similar(pf2)
    # 首帧阶段没有 FL 项：策略对首帧 postflight 无影响
    pf3 = BL.apply({"ok": True, "blocking": [], "reasons": [], "items": [{"id": "Q1", "status": "pass"}]}, conf)
    assert pf3["ok"] is True and not any(i["id"] == "FL" for i in pf3["items"])


def test_fl_pass_does_not_touch_ok(tmp_path):
    a, c = tmp_path / "f.png", tmp_path / "o.png"
    _png(a, _gradient())
    _png(c, np.random.default_rng(3).integers(0, 255, (224, 128, 3)))
    pf = FL.apply({"ok": True, "blocking": [], "reasons": [], "items": []}, a, c)
    assert pf["ok"] is True and pf["blocking"] == [] and pf["items"][-1]["status"] == "pass"


def test_producer_never_adopts_too_similar_last(tmp_path):
    from tools.autopilot import producer as PR
    bad = {"ok": False, "blocking": ["FL"], "items": [{"id": "Q1", "status": "pass"}, {"id": "Q9", "status": "pass", "evidence": {"model": "x", "defects": []}},
                                                      {"id": "FL", "status": "fail"}]}
    good = {"ok": True, "blocking": [], "items": [{"id": "Q1", "status": "pass", "evidence": {"value": 0.9}},
                                                   {"id": "Q9", "status": "pass", "evidence": {"model": "x", "defects": []}}, {"id": "FL", "status": "pass"}]}
    assert PR.fl_bad(bad) and not PR.fl_bad(good) and PR.never_adopt(bad) and not PR.never_adopt(good)
    assert PR.safe_take(bad) is False
    td = {"takes": [{"stage": "last", "n": 1, "file": "a.png", "postflight": bad}, {"stage": "last", "n": 2, "file": "b.png", "postflight": good}]}
    assert PR.review_pick(td, "last") == 2 and PR.review_pick_relaxed(td, "last") == 2
    td2 = {"takes": [{"stage": "last", "n": 1, "file": "a.png", "postflight": bad}]}
    assert PR.review_pick(td2, "last") is None and PR.review_pick_relaxed(td2, "last") is None


def test_producer_first_last_check_reads_job_first_frame(tmp_path, monkeypatch):
    from tools.autopilot import producer as PR
    from ns_render import pipeline as P
    data = tmp_path / "data"
    _png(tmp_path / "first.png", _gradient())
    _png(data / "renders/x/last.png", _gradient(noise=2))
    monkeypatch.setattr(P, "DATA", data)
    paths = PR.Paths(root=tmp_path)
    pf = PR.first_last_check(paths, {"ok": True, "blocking": [], "reasons": [], "items": []}, {"first_frame_file": "first.png"}, "renders/x/last.png")
    assert pf["ok"] is False and "FL" in pf["blocking"]
    pf = PR.first_last_check(paths, {"ok": True, "blocking": [], "reasons": [], "items": []}, {}, "renders/x/last.png")
    assert pf["ok"] is False and pf["items"][-1]["status"] == "untested"   # 没有首帧文件 = 失败关闭


def test_calibration_pairs_distribution_documented():
    """校准数字写进了配置说明（可追溯）"""
    d = json.loads((ROOT / "config/gen_contract.json").read_text(encoding="utf-8"))
    assert "111" in d["_first_last"] and "0.858" in d["_first_last"]
