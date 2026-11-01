"""生成契约（docs/GEN_CONTRACT.md）+ 资产参考锁定（ns_agent.asset_refs）测试。REFLOCK 2026-10-31。

项目方原话：“关于女主角鞋子的一致性也全部错了……你要在 image 里面让它知道，这个女孩要穿这个鞋子、穿这个衣服、戴这个饰品”。
"""
import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/agent", "packages/schema", "tools/pipeline"):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))

from ns_agent import asset_refs as AR  # noqa: E402
from ns_agent.gen_contract import ContractViolation, postflight, preflight  # noqa: E402
from ns_agent.gen_contract import preflight as PF  # noqa: E402
from ns_agent.gen_contract import style as ST  # noqa: E402

SCRIPT = ROOT / "data" / "import" / "script_v2.json"
PROJECT = "series10_v1"
need_data = pytest.mark.skipif(not SCRIPT.exists() or not AR.project_cfg(PROJECT), reason="series10 数据缺")


def _shot(ep_n, idx, img=None):
    d = json.loads(SCRIPT.read_text(encoding="utf-8"))
    ep = next(e for e in d["episodes"] if e["number"] == ep_n)
    s = next(s for s in ep["shots"] if s["index"] == idx)
    if img is not None:                       # 夹具镜：沿用这一镜的 cast / 造型行 / 镜号，img 换成固定原文（不依赖现行剧本写了什么）
        s = {**s, "img_prompt": img}
    return ep, s


# CODE-RSI 11-02（K-OPS-C02，AUDIT 00:23）：23:22 HOLLYWOOD 导入后剧本里已没有“林晚单人、造型 A、脚可见”的镜，
# 按性质选镜退回近景 → 鞋锁定 / 缺鞋 2 条红。改成夹具镜：ep01-S1（造型 A、林晚单人）+ 固定的全身 img
FULL_IMG = "全景，平视，林晚站在办公桌前，米白衬衫与深灰铅笔裙，透明12cm细高跟踩在地毯上，细银链贴在锁骨上，雾霾天蓝色及腰直发，齐刘海"


def _pick(pred, default):
    """CODE-RSI 11-01：按镜头性质选镜，不写死镜号——18:24 返修稿重排后 ep01-S3 变近景、ep01-S4 变单人，
    写死 (1, 3) / (1, 4) 的断言全部失去前提（K-OPS-C02）。找不到符合的镜就退回旧镜号（断言会如实报错）"""
    if not SCRIPT.exists():
        return default
    for ep in json.loads(SCRIPT.read_text(encoding="utf-8"))["episodes"]:
        for sh in ep["shots"]:
            if pred(sh):
                return ep["number"], sh["index"]
    return default


def _in_frame(sh):
    return [c["name"] for c in sh.get("cast") or [] if c.get("presence") == "在画" and not c.get("part")]


# 林晚造型 A（米白衬衫）单人、脚可见的全身 / 中全景镜：鞋必须由衣橱单品图锁定
FULL = (1, 1, FULL_IMG)                      # 夹具镜（见 _shot 上方说明）
# 林晚 + 顾沉两人都在画的镜：两张身份脸各占一槽
TWO = _pick(lambda sh: sorted(_in_frame(sh)) == sorted(["林晚", "顾沉"]), (1, 4))


def _req(ep_n, idx, img=None, model="qwen_image_2.1"):
    ep, s = _shot(ep_n, idx, img)
    sr, plan = AR.plan_for(PROJECT, ep, s, model)
    prompt = plan.prompt_prefix + "中全景构图，林晚站在办公桌前，" + ST.image_suffix()
    return {"kind": "image", "model": model, "project": PROJECT, "shot_id": sr.shot_id,
            "cast": [{"name": c["name"], "presence": c["presence"], "x": c.get("x") or "中"} for c in s["cast"]],
            "prompt": prompt, "refs": plan.files, "asset_refs": AR.record(sr, plan),
            "loras": [["krea2_film_texture_qwen21.safetensors", 0.5]],
            "compiled_by": "tools/pipeline/image_jobs.py → ns_agent.compiler.compile_shot"}, sr, plan


# ---------------------------------------------------------------- 解析器
def test_parse_parts_zones():
    parts = AR.parse_parts("服装=黑色漆皮束腰配黑色漆皮短裙，露出长腿｜鞋=12cm侧开透明细高跟｜饰品=九串铁珠、钻石水晶甲（5 厘米、镶满钻石）")
    z = {p.label: (p.slot, p.zone) for p in parts}
    assert z["黑色漆皮束腰"] == ("outfit", "upper") and z["黑色漆皮短裙"] == ("outfit", "lower")
    assert z["12cm侧开透明细高跟"] == ("shoes", "feet")
    assert z["钻石水晶甲（5 厘米、镶满钻石）"] == ("nails", "hand")          # 括号里的顿号不切
    assert AR.zone_of("outfit", "雾蓝针织长裙") == "body" and AR.zone_of("accessory", "细银链") == "neck"


def test_visible_zones_by_size():
    assert "feet" not in AR.visible_zones("特写，林晚抬眼看向镜头")[2]
    assert "feet" in AR.visible_zones("全景，林晚站在门口")[2]
    size, subj, zones = AR.visible_zones("大特写，透明细高跟的鞋跟踩在地毯上")
    assert subj == "part" and zones == {"feet"}


@pytest.fixture
def look_a(monkeypatch):
    """夹具：林晚 ep01 钉死造型 A（临时登记），不受资产中心排期 / 逐镜切换 / 现行登记变化影响"""
    orig = AR.registry_looks
    monkeypatch.setattr(AR, "registry_looks", lambda project: {**orig(project), "ep01-S1": {"lin_wan": "A"}})
    monkeypatch.setattr(AR, "episode_look_override", lambda project, cid, ep_n: None)
    monkeypatch.setattr(AR, "shot_overrides", lambda project: ({}, {}))


@need_data
def test_full_shot_shoes_locked_by_wardrobe_image(look_a):
    """全身镜鞋可见：参考里必须有鞋的单品图（衣橱 LW-S01），且提示词写明“必须完全一致”"""
    ep, s = _shot(*FULL)                                           # 林晚造型 A 单人、脚可见（FULL）
    sr, plan = AR.plan_for(PROJECT, ep, s)
    feet = [r for r in sr.refs if r.zone == "feet"]
    assert feet and feet[0].item_id == "lw-shoes-lw-s01" and feet[0].source == "wardrobe"
    assert any("鞋" in lab for sl in plan.slots for lab in sl.labels)
    assert "必须与" in plan.prompt_prefix and "完全一致" in plan.prompt_prefix
    assert plan.slots[0].kind == "face" and len(plan.slots) <= 3


@need_data
def test_closeup_drops_shoes():
    ep, s = _shot(1, 1)                                           # ep01-S1 特写
    sr, _ = AR.plan_for(PROJECT, ep, s)
    assert not [r for r in sr.refs if r.zone == "feet"]
    assert any(r.role == "sheet" and "半身" in r.label for r in sr.refs)


@need_data
def test_two_person_primary_face_only_and_board_single_face():
    ep, s = _shot(*TWO)                                           # 顾沉 + 林晚（TWO）
    sr, plan = AR.plan_for(PROJECT, ep, s)
    # 11-01 起默认 both_faces：两张身份脸各占一槽（证据见 config/recipes/asset_refs.json two_person_note），绝不同槽
    assert sum(1 for sl in plan.slots if sl.kind == "face") == 2
    assert all(sl.faces <= 1 for sl in plan.slots)
    assert len(plan.slots) <= 3
    sr1, plan1 = AR.plan_for(PROJECT, ep, s, two_person="primary_face_only")
    assert sum(1 for sl in plan1.slots if sl.kind == "face") == 1


@need_data
def test_unregistered_look_blocks(monkeypatch):
    """剧本造型行对不上 P1 登记（例：旧 ep07 开场“米白衬衫解开到腰…”）→ 造型未登记，阻断"""
    ep, s = _shot(*FULL)
    ep = copy.deepcopy(ep)
    for r in ep["looks"]:
        if r["character"] == "林晚":
            r["slots"] = {**r["slots"], "服装": "米白衬衫解开到腰，下摆垂在胯侧，黑色漆皮短裙搭在臂弯", "鞋": "赤脚"}
    monkeypatch.setattr(AR, "registry_looks", lambda project: {})
    sr, _ = AR.plan_for(PROJECT, ep, s)
    assert sr.blocked and any(m["kind"] == "造型未登记" for m in sr.missing)


@need_data
def test_item_map_overrides_merge(tmp_path, monkeypatch):
    ov = tmp_path / "item_map_overrides.json"
    ov.write_text(json.dumps({PROJECT: {"lin_wan": {"B": {"黑色漆皮束腰": "lw-outfit-lw-o10", "钻石水晶甲": None, "_by": "t"}}}}),
                  encoding="utf-8")
    monkeypatch.setattr(AR, "OVERRIDES", ov)
    m = AR.item_map(PROJECT)["lin_wan"]["B"]
    assert m["黑色漆皮束腰"] == "lw-outfit-lw-o10" and "钻石水晶甲" not in m and "_by" not in m


# ---------------------------------------------------------------- preflight：四个必挡的场景
@need_data
def test_missing_shoe_asset_blocked(monkeypatch, look_a):
    """缺鞋资产图被阻断：鞋没有衣橱图、设定图也没有 → 资产缺图，I4 不通过，拒交"""
    monkeypatch.setattr(AR, "sheet_of", lambda project, cid, lid: None)
    monkeypatch.setattr(AR, "item_image", lambda iid: None)
    req, sr, plan = _req(*FULL)
    assert any(m["kind"] == "资产缺图" and "鞋" in m["detail"] for m in sr.missing)
    r = PF.check(req)
    assert not r.ok and "I4" in [i.id for i in r.blocking]
    with pytest.raises(ContractViolation):
        PF.enforce(req)


@need_data
def test_lin_wan_qi_blocked():
    """用 lin_wan_qi 被阻断（I8：已证伪 + 项目方去掉）；触发词 lnwan_qi 在图像提示词里也挡"""
    req, _, _ = _req(*FULL)
    ok = PF.check(req)
    assert "I8" not in [i.id for i in ok.blocking]
    bad = copy.deepcopy(req)
    bad["loras"].append(["lin_wan_qi_v1.safetensors", 0.6])
    assert "I8" in [i.id for i in PF.check(bad).blocking]
    bad2 = copy.deepcopy(req)
    bad2["prompt"] = "lnwan_qi，" + bad2["prompt"]
    assert "I8" in [i.id for i in PF.check(bad2).blocking]


def test_compiler_never_attaches_banned_lora():
    from ns_agent import compiler as C
    assert "lin_wan_qi_v1.safetensors" in C.banned_image_loras()
    assert all(e.get("file") != "lin_wan_qi_v1.safetensors" for es in C.auto_lora_triggers().values() for e in es)


@need_data
def test_old_soft_focus_suffix_blocked():
    """旧柔焦后缀被阻断（I7）：visual_bible fallback_suffix 的“奶油般柔焦虚化 / 浓郁饱和”"""
    req, _, _ = _req(*FULL)
    old = "专业电影镜头画面感，85mm人像镜头f/1.2大光圈，前景与背景奶油般柔焦虚化，浓郁饱和的暖色调电影调色，无字幕、无文字、无水印"
    bad = copy.deepcopy(req)
    bad["prompt"] = bad["prompt"].replace(ST.image_suffix(), old)
    r = PF.check(bad)
    assert "I7" in [i.id for i in r.blocking]
    assert "I7" not in [i.id for i in PF.check(req).blocking]
    assert ST.banned_hits("黑色漆皮像抹了油一样的高亮镜面") == []           # 漆皮光泽不算皮肤油光
    assert "油光" in ST.banned_hits("皮肤油光发亮")


@need_data
def test_two_faces_same_slot_blocked():
    """双人两脸同槽被阻断（I9）：把两人的脸拼进一块参考板"""
    req, sr, plan = _req(*TWO)
    bad = copy.deepcopy(req)
    bad["asset_refs"]["slots"][0]["faces"] = 2
    assert "I9" in [i.id for i in PF.check(bad).blocking]
    both = copy.deepcopy(req)                                     # 两张身份脸各占一槽（primary_face_only 模式下也挡）
    both["asset_refs"]["slots"].insert(1, {**both["asset_refs"]["slots"][0], "index": 2, "file": "x.png"})
    both["refs"].insert(1, "x.png")
    assert "I9" in [i.id for i in PF.check(both).blocking]


@need_data
def test_job_without_asset_refs_blocked():
    req, _, _ = _req(1, 1)
    req.pop("asset_refs")
    r = PF.check(req)
    assert {"I2", "I3", "I4", "I9"} <= {i.id for i in r.blocking}


@need_data
def test_unified_signature_callable():
    req, _, _ = _req(*FULL)
    d = preflight("image", req)
    assert isinstance(d, dict) and set(d) >= {"ok", "items", "blocking", "reasons"}
    v = postflight("video", {})
    assert v["ok"] is False


def test_postflight_untested_is_not_pass():
    """没有远端打分 / 本机测量 → Q 项 untested，结果不得为通过"""
    rec = {"size": "中全景", "subject": None, "zones": ["feet"], "primary": "lin_wan", "slots": [], "missing": []}
    r = postflight.evaluate("x.png", {"asset_refs": rec, "cast": [{"name": "林晚", "presence": "在画"}]})
    assert not r.ok and {"Q1", "Q3", "Q5", "Q6"} <= {i.id for i in r.blocking}


def test_postflight_identity_and_framing_judgement():
    rec = {"size": "特写", "subject": "face", "zones": ["face"], "primary": "lin_wan", "slots": [], "missing": []}
    req = {"asset_refs": rec, "cast": [{"name": "林晚", "presence": "在画"}]}
    good = {"faces": [{"h_ratio": 0.30, "bbox": [0, 0, 10, 10], "sims": {"lin_wan": 0.78, "gu_chen": 0.1}}], "text": []}
    r = postflight.evaluate("x.png", req, remote=good, hands={"flags": []}, local={"Q2": [], "Q4": None, "Q7": None})
    st = {i.id: i.status for i in r.items}
    assert st["Q1"] == "pass" and st["Q3"] == "pass" and st["Q5"] == "pass" and st["Q6"] == "pass"
    # K-REV-V18 修订（11-02，0.70 单线退役）：小脸档 ≥0.50 过、0.40–0.50 复核带、<0.40 直接不过 → 用 0.35 测“直接不过”
    weak = {"faces": [{"h_ratio": 0.09, "bbox": [0, 0, 10, 10], "sims": {"lin_wan": 0.35}}], "text": [{"text": "LOGO"}]}
    st = {i.id: i.status for i in postflight.evaluate("x.png", req, remote=weak, local={"Q2": [], "Q4": None, "Q7": None}).items}
    assert st["Q1"] == "fail" and st["Q3"] == "fail" and st["Q6"] == "fail"



def test_q1_every_face_must_be_recognised():
    """总调度 11-01 P1（ep03-S6）：林晚过线，但画面里另一张大脸谁都不像 → Q1 不过；像本镜局部角色（顾沉）→ 过"""
    rec = {"size": "近景", "subject": None, "zones": ["face"], "primary": "lin_wan", "slots": [], "missing": []}
    req = {"asset_refs": rec, "cast": [{"name": "林晚", "presence": "在画"}, {"name": "顾沉", "presence": "局部"}]}
    lw = {"h_ratio": 0.15, "bbox": [0, 0, 10, 10], "sims": {"lin_wan": 0.83, "gu_chen": 0.05}}
    loc = {"Q2": [], "Q4": None, "Q7": None}
    stranger = {"faces": [lw, {"h_ratio": 0.20, "bbox": [20, 0, 30, 10], "sims": {"lin_wan": 0.02, "gu_chen": 0.21}}], "text": []}
    q1 = next(i for i in postflight.evaluate("x.png", req, remote=stranger, local=loc).items if i.id == "Q1")
    assert q1.status == "fail" and "认不出是谁" in q1.detail
    him = {"faces": [lw, {"h_ratio": 0.20, "bbox": [20, 0, 30, 10], "sims": {"lin_wan": 0.02, "gu_chen": 0.66}}], "text": []}
    q1 = next(i for i in postflight.evaluate("x.png", req, remote=him, local=loc).items if i.id == "Q1")
    assert q1.status == "fail" and "局部角色出了脸" in q1.detail      # 11-01：cast 局部的人不该出脸
    req_d = {**req, "asset_refs": {**rec, "characters": [{"character": "gu_chen", "presence": "局部", "face_described": True}]}}
    q1 = next(i for i in postflight.evaluate("x.png", req_d, remote=him, local=loc).items if i.id == "Q1")
    assert q1.status == "pass", q1.detail                               # 原文写了他的脸 → 认得出就过
    tiny = {"faces": [lw, {"h_ratio": 0.02, "bbox": [20, 0, 21, 1], "sims": {"lin_wan": 0.0, "gu_chen": 0.1}}], "text": []}
    assert next(i for i in postflight.evaluate("x.png", req, remote=tiny, local=loc).items if i.id == "Q1").status == "pass"
    extra = {**req, "cast": req["cast"] + [{"name": "服务员", "presence": "在画"}]}     # 没有身份脸的路人可抵一张
    q1 = next(i for i in postflight.evaluate("x.png", extra, remote=stranger, local=loc).items if i.id == "Q1")
    assert "认不出是谁" not in q1.detail

@need_data
def test_image_jobs_dry_rebuild_uses_asset_plan():
    import image_jobs as IJ
    r = IJ.rebuild_first_frame_jobs(ROOT / "data/pipeline/runs/series10_v1", write=False)
    j = next(x for x in r["data"]["jobs"] if x["shot"] == "ep01-S3")
    assert j["refs"] == [s["file"] for s in j["asset_refs"]["slots"]]
    assert __import__("ns_agent.asset_refs", fromlist=["x"]).SINGLE_TURN_RE.sub("", j["prompt"], count=1).startswith("图1是林晚的脸部参考")  # IMGFIX K-REN-704：单人朝向句在最前 and "lin_wan_qi_v1.safetensors" not in json.dumps(j["loras"])
    assert ST.preset_suffix() in j["prompt"] and not ST.banned_hits(j["prompt"])
    assert j["preflight"]["ok"], j["preflight"]


@need_data
@pytest.mark.real_data          # 参考板是按内容哈希的缓存，换了覆盖会现做一张（写 data/pipeline/runs/…/refboards）
def test_hub_extra_look_and_episode_override(tmp_path, monkeypatch):
    """资产中心“＋ 新造型”并入 P1 之后（id 重复以 P1 为准）；“排期：角色 × 集”整集覆盖本镜造型（在逐镜登记之上）"""
    hl = tmp_path / "hub_extra_looks.json"
    hl.write_text(json.dumps({PROJECT: {"lin_wan": [{"id": "D", "use": "测试", "zh": "服装=白色连衣裙｜鞋=白色平底鞋｜饰品=细银链"},
                                                     {"id": "A", "zh": "服装=不应覆盖"}]}}, ensure_ascii=False), encoding="utf-8")
    he = tmp_path / "hub_episode_looks.json"
    he.write_text(json.dumps({PROJECT: {"lin_wan": {"1": "B", "2": None}}}), encoding="utf-8")
    monkeypatch.setattr(AR, "HUB_LOOKS", hl)
    monkeypatch.setattr(AR, "HUB_EP_LOOKS", he)
    looks = AR.load_looks(PROJECT)["lin_wan"]
    assert "D" in looks and "米白衬衫" in looks["A"].zh
    ep, s = _shot(*FULL)
    sr, _ = AR.plan_for(PROJECT, ep, s)
    lw = next(c for c in sr.characters if c["character"] == "lin_wan")
    assert lw["look"] == "B" and lw["look_how"] == "hub_episode"
    ep2, s2 = _shot(2, 1)
    assert next(c for c in AR.plan_for(PROJECT, ep2, s2)[0].characters if c["character"] == "lin_wan")["look_how"] != "hub_episode"


FX = ROOT / "data/pipeline/runs/series10_v1/images/imgfix"


@pytest.mark.skipif(not (FX / "ep01-S5" / "v0.png").exists(), reason="imgfix 认可集不在本机")
def test_q4_threshold_on_approved_set():
    """K-REV-232 第二轮：总调度认可集 v10 判过、v0（塑料、糊）判不过——整图 Laplacian（宽 768）"""
    from PIL import Image
    th = json.loads((ROOT / "config/gen_contract.json").read_text(encoding="utf-8"))["image_thresholds"]["Q4_texture"]
    t_bad = postflight.texture(Image.open(FX / "ep01-S5" / "v0.png").convert("RGB"))
    good = json.loads((FX / "results.json").read_text(encoding="utf-8"))["ep01-S5/v10"]["file"]
    t_good = postflight.texture(Image.open(ROOT / good).convert("RGB"))
    assert t_bad["lap_full"] < th["lap_full_min"] <= t_good["lap_full"]


def test_locks_without_wardrobe_strips_clothing():
    """K-AST-232：角色锁里的服装分句在资产模式下去掉（顾沉“黑色高定衬衫”与造型 A 冲突）"""
    d, rm = AR.strip_wardrobe("34岁成年男性CEO，黑色高定衬衫，成熟克制英俊")
    assert d == "34岁成年男性CEO，成熟克制英俊" and rm == ["黑色高定衬衫"]


@need_data
def test_sheet_refs_are_headless():
    """K-AST-233：造型设定图进槽位一律去头（脸只由身份参考提供）；身份脸 = 项目方挑定的 A-s202 face_ref2va"""
    for key in ((1, 1), FULL, TWO):
        ep, s = _shot(*key)
        sr, plan = AR.plan_for(PROJECT, ep, s)
        for r in sr.refs:
            if r.role == "sheet":
                assert r.file.endswith("_nohead.png") and not r.has_face
        faces = [(r.character, r.file) for r in sr.refs if r.role == "face"]
        # K-AST-235：身份脸 = asset_refs.face_of（资产中心“设为当前身份脸”覆盖 > config faces），不写死文件名
        assert all(f == AR.face_of(PROJECT, c) for c, f in faces), faces


def test_q2_record_only_zones():
    """K-REV-231：手 / 颈 / 上身等区域的单品只记录不判；鞋、下装照判"""
    rec = {"size": "全景", "subject": None, "zones": ["feet", "hand"], "primary": "lin_wan", "slots": [{"kind": "x"}], "missing": []}
    rows = [{"label": "指甲", "role": "item", "zone": "hand", "clip": 0.5, "hist": 0},
            {"label": "鞋", "role": "item", "zone": "feet", "clip": 0.9, "hist": 0}]
    r = postflight.evaluate("x.png", {"asset_refs": rec, "cast": []}, local={"Q2": rows, "Q4": None, "Q7": None})
    assert next(i for i in r.items if i.id == "Q2").status == "pass"
    rows[1]["clip"] = 0.6
    r = postflight.evaluate("x.png", {"asset_refs": rec, "cast": []}, local={"Q2": rows, "Q4": None, "Q7": None})
    assert next(i for i in r.items if i.id == "Q2").status == "fail"


def test_q5_long_nail_relax():
    """林晚超长水晶甲：只有指长比偏高（≤4.6，无指尖重合）不算坏手；其它角色照判"""
    rec = {"subject": "face", "slots": []}
    fl = {"flags": ["手型可疑（第2只手：指长比 [4.44, 4.22]，指尖重合 0）"]}
    q = lambda cast: next(i for i in postflight.evaluate("x.png", {"asset_refs": rec, "cast": cast}, hands=fl,  # noqa: E731
                                                         local={"Q2": [], "Q4": None, "Q7": None}).items if i.id == "Q5").status
    assert q([{"name": "林晚", "presence": "在画"}]) == "pass"
    # 总调度 11-01 标注 contract_labels_r1：“手型可疑”13/13 误报 → 整条子规则只记录（不论角色）
    assert q([{"name": "顾沉", "presence": "在画"}]) == "pass"


def test_q8_record_only_does_not_block():
    """总调度 11-01：Q8 暂时只记录——越线也不阻断（na + would_fail），不触发重出"""
    rec = {"subject": "face", "slots": []}
    rem = {"faces": [{"h_ratio": 0.2, "bbox": [0, 0, 1, 1], "sims": {"lin_wan": 0.9}}], "text": []}
    r = postflight.evaluate("x.png", {"asset_refs": rec, "cast": [{"name": "林晚", "presence": "在画"}]}, remote=rem,
                            hands={"flags": []}, local={"Q2": [], "Q4": None, "Q7": None,
                                                        "Q8": {"n": 39253, "hsv": [107.0, 83.0, 56.0], "skin_v": 187.0, "rel_v": 0.299}})
    i = next(x for x in r.items if x.id == "Q8")
    assert i.status == "na" and i.evidence["would_fail"] is True and "Q8" not in [b.id for b in r.blocking]


def test_q8_hair_relative_luminance(monkeypatch):
    """K-REV-233（开阻断后的口径）：ep01-S5 v2 类（相对亮度 0.299）判不过；ep01-S1 v7 类（0.376，亲审签字）判过；没检出发丝 = 未测"""
    from ns_agent import gen_contract as GC
    c = GC.cfg()
    c["image_thresholds"]["Q8_hair"]["record_only"] = False
    monkeypatch.setattr(postflight, "cfg", lambda: c)
    rec = {"subject": "face", "slots": []}
    cast = [{"name": "林晚", "presence": "在画"}]
    rem = {"faces": [{"h_ratio": 0.2, "bbox": [0, 0, 1, 1], "sims": {"lin_wan": 0.9}}], "text": []}

    def q8(v):
        r = postflight.evaluate("x.png", {"asset_refs": rec, "cast": cast}, remote=rem, hands={"flags": []},
                                local={"Q2": [], "Q4": None, "Q7": None, "Q8": v})
        return next(i for i in r.items if i.id == "Q8").status
    assert q8({"n": 39253, "hsv": [107.0, 83.0, 56.0], "skin_v": 187.0, "rel_v": 0.299}) == "fail"
    assert q8({"n": 52774, "hsv": [104.0, 129.0, 64.0], "skin_v": 170.0, "rel_v": 0.376}) == "pass"
    assert q8({"n": 5, "note": "没检出足够的蓝色发丝"}) == "untested"


def _eval_local(local, cast=(), hands=None, subject=None):
    rec = {"size": "全景", "subject": subject, "zones": ["feet"], "primary": "lin_wan", "slots": [{"kind": "x"}], "missing": []}
    return {i.id: i for i in postflight.evaluate("x.png", {"asset_refs": rec, "cast": list(cast)}, hands=hands,
                                                 local={"Q2": [], "Q4": None, "Q7": None, **local}).items}


def test_q2_shoe_band_and_embellished_probe():
    """总调度 11-01 留出复核后：鞋 <0.70 挡；0.70–0.78 只记录“鞋待目检”；≥0.78 过；加装饰款（探针）挡"""
    row = lambda c, e=0.1: [{"label": "鞋", "role": "item", "zone": "feet", "clip": c, "hist": 0, "p_embellished": e}]  # noqa: E731
    assert _eval_local({"Q2": row(0.69)})["Q2"].status == "fail"
    q = _eval_local({"Q2": row(0.74)})["Q2"]
    assert q.status == "na" and q.evidence.get("review") == "鞋待目检"
    assert _eval_local({"Q2": row(0.80)})["Q2"].status == "pass"
    assert _eval_local({"Q2": row(0.80, 0.95)})["Q2"].status == "fail"


def test_q4_record_only_and_q5_limb_rule_disabled():
    """Q4 整图质感留出 AUC 0.41 → 只记录；Q5“肢体比例可疑”7/7 误报 → 停用，“手型”照判"""
    q4 = _eval_local({"Q4": {"lap_full": 50.0, "sat_mean": 0.3, "specular": 0.0}})["Q4"]
    assert q4.status == "na" and q4.evidence.get("would_fail") is True
    cast = [{"name": "顾沉", "presence": "在画"}]
    assert _eval_local({}, cast, {"flags": ["肢体比例可疑（第1人 上臂 0.12/0.30）"]})["Q5"].status == "pass"
    assert _eval_local({}, cast, {"flags": ["手型可疑（第1只手：指长比 [5.2]，指尖重合 0）"]})["Q5"].status == "pass"   # 11-01 标注：只记录
    assert _eval_local({}, cast, {"flags": ["多手可疑（3 只手）"]})["Q5"].status == "fail"


@need_data
def test_ref2va_outfit_slot_registration():
    """VIDEO10 Ref2VA 造型槽（REFLOCK 11-01 审）：每个在画角色一张，路径须是已选定设定图或其 refcrops 裁切；手塞的图不认"""
    from ns_agent import asset_refs as AR
    sheet = AR.sheet_of(PROJECT, "lin_wan", "A")
    if not sheet:
        pytest.skip("没有林晚造型 A 的设定图")
    crop = AR.sheet_crop(PROJECT, sheet, "front_nohead")
    chosen = preflight.registered_sheet_files(PROJECT)
    assert preflight.look_file_registered({"path": crop, "sheet": sheet}, chosen)
    assert preflight.look_file_registered({"path": sheet}, chosen)
    assert not preflight.look_file_registered({"path": "data/tmp/whatever.png", "sheet": sheet}, chosen)
    assert not preflight.look_file_registered({"path": crop, "sheet": "data/not_chosen.png"}, chosen)


def test_q2_outer_item_presence_blocks(monkeypatch):
    """总调度 11-01：林晚造型 A 的短款西装外套没穿（外层探针 < outer_min）→ Q2 不过，不受上身区“只记录”影响。
    23:0x 起外套探针临时只记录（outer_record_only=true，敞开外套 / 长发盖住误判，VQAGATE 重新标定中）：这里按“恢复阻断后”的口径测，
    只记录口径另见 test_q2_outer_record_only_while_recalibrating"""
    from ns_agent.gen_contract import postflight as _PF
    real = _PF.cfg()
    th = {**real.get("image_thresholds", {}), "Q2_outfit": {**real["image_thresholds"]["Q2_outfit"], "outer_record_only": False}}
    monkeypatch.setattr(_PF, "cfg", lambda: {**real, "image_thresholds": th})
    rec = {"size": "中景", "subject": None, "zones": ["upper", "lower"], "primary": "lin_wan", "slots": [], "missing": [],
           "characters": [{"character": "lin_wan", "look": "A"}]}
    rows = postflight.outer_rows(rec)
    if not rows:
        pytest.skip("林晚造型 A 没登记外层单品")
    assert rows[0]["label"] == "短款西装外套" and rows[0].get("probe")
    req = {"asset_refs": rec, "cast": [{"name": "林晚", "presence": "在画"}]}

    def q2(p):
        loc = {"Q2": [], "Q4": None, "Q7": None, "outer": [{**rows[0], "p": p}]}
        return next(i for i in postflight.evaluate("x.png", req, local=loc).items if i.id == "Q2")
    assert q2(0.03).status == "fail" and "没穿" in q2(0.03).detail
    assert q2(0.80).status != "fail"
    assert "未测" in q2(None).detail


def test_q2_outer_record_only_while_recalibrating():
    """总调度 11-01 23:0x：外套探针重新标定期间只记录——低于线写进说明，不挡 Q2"""
    rec = {"size": "中景", "subject": None, "zones": ["upper", "lower"], "primary": "lin_wan", "slots": [], "missing": [],
           "characters": [{"character": "lin_wan", "look": "A"}]}
    rows = postflight.outer_rows(rec)
    if not rows:
        pytest.skip("林晚造型 A 没登记外层单品")
    if not postflight.cfg()["image_thresholds"]["Q2_outfit"].get("outer_record_only"):
        pytest.skip("外套探针已恢复阻断")
    req = {"asset_refs": rec, "cast": [{"name": "林晚", "presence": "在画"}]}
    loc = {"Q2": [], "Q4": None, "Q7": None, "outer": [{**rows[0], "p": 0.03}]}
    it = next(i for i in postflight.evaluate("x.png", req, local=loc).items if i.id == "Q2")
    assert it.status != "fail"


def test_q2_outer_per_character_faces_and_record_only():
    """外层单品查全部在画角色：每个角色配自己的脸框；只有校准过的（outer_block_keys）阻断，其余只记录"""
    from ns_agent.gen_contract import metrics as MM
    faces = [{"bbox": [0, 0, 10, 10], "sims": {"lin_wan": 0.9, "gu_chen": 0.1}},
             {"bbox": [50, 0, 60, 10], "sims": {"lin_wan": 0.05, "gu_chen": 0.8}}]
    rows = MM.outer_rows_with_faces([{"character": "gu_chen", "label": "深灰西装"}, {"character": "chen_yu", "label": "x"}], faces)
    assert rows[0]["face_bbox"] == [50, 0, 60, 10] and rows[1]["face_bbox"] is None
    rec = {"size": "中景", "subject": None, "zones": ["upper"], "primary": "lin_wan", "slots": [], "missing": [],
           "characters": [{"character": "gu_chen", "look": "A", "presence": "在画"}]}
    want = postflight.outer_rows(rec)
    if not want:
        pytest.skip("顾沉造型 A 没登记外层单品")
    req = {"asset_refs": rec, "cast": [{"name": "顾沉", "presence": "在画"}]}
    loc = {"Q2": [], "Q4": None, "Q7": None, "outer": [{**want[0], "p": 0.01}]}
    q2 = next(i for i in postflight.evaluate("x.png", req, local=loc).items if i.id == "Q2")
    assert q2.status != "fail" and "只记录" in q2.detail and "顾沉" in q2.detail


def test_review_flags_on_contact_sheet_caption():
    """总调度 11-01：只记录的项（未校准外层单品 / 鞋待目检 / 第二张脸）在印样标注里显示“待目检”"""
    from ns_agent.gen_contract import report as RPT
    pf = {"items": [{"id": "Q2", "status": "pass", "detail": "1 项过线；顾沉的深灰西装 没穿（外层探针 0.02 < 0.5），只记录（未校准）"},
                    {"id": "Q1", "status": "pass", "detail": "身份过线；其他脸：lin_wan 0.6（同一角色第二张脸：镜像 / 重复人物，待目检）"}]}
    cap = RPT.q4_caption(pf)
    assert cap.startswith("待目检：") and "顾沉的深灰西装" in cap and "第二张脸" in cap
    assert not RPT.review_flags({"items": [{"id": "Q2", "status": "pass", "detail": "2 项过线"}]})


def test_q2_empty_rows_is_na_not_untested():
    """手部大特写：有槽位但可见单品全在只记录区 → Q2 不适用（不是未测，不挡契约）"""
    rec = {"size": "大特写", "subject": "part", "zones": ["hand"], "primary": "lin_wan", "missing": [],
           "slots": [{"kind": "board", "members": [{"role": "item", "zone": "hand", "file": "x.png", "label": "指甲"}]}]}
    req = {"asset_refs": rec, "cast": [{"name": "林晚", "presence": "局部"}]}
    q2 = next(i for i in postflight.evaluate("x.png", req, local={"Q2": [], "Q4": None, "Q7": None}).items if i.id == "Q2")
    assert q2.status == "na"


def test_q3_part_closeup_with_face_fails():
    """总调度 11-01：手部大特写里检出了脸（够大）→ Q3 不过“局部特写出了脸”；没脸 → 不适用；没打分 → 未测"""
    rec = {"size": "大特写", "subject": "part", "zones": ["hand"], "primary": "lin_wan", "slots": [], "missing": [],
           "characters": [{"character": "lin_wan", "presence": "局部"}]}
    req = {"asset_refs": rec, "cast": [{"name": "林晚", "presence": "局部"}]}
    loc = {"Q2": [], "Q4": None, "Q7": None}

    def q3(remote):
        return next(i for i in postflight.evaluate("x.png", req, remote=remote, hands={"flags": []}, local=loc).items if i.id == "Q3")
    assert q3({"faces": [{"h_ratio": 0.14, "bbox": [0, 0, 1, 1], "sims": {"lin_wan": 0.8}}], "text": []}).status == "fail"
    assert q3({"faces": [], "text": []}).status == "na"
    assert q3({"faces": [{"h_ratio": 0.02, "bbox": [0, 0, 1, 1], "sims": {}}], "text": []}).status == "na"
    assert q3(None).status == "untested"


def test_part_closeup_prompt_has_no_face_cues():
    """局部特写的提示词：首句写局部 + 不出现脸；角色锁只留局部相关分句与成年句；不加“面部清晰对焦”"""
    from ns_agent import framing as FR
    assert "画面里只有手" in FR.closeup_lead("大特写", "part", "林晚的右手攥着纸") and "不" not in FR.closeup_lead("大特写", "part", "林晚的右手攥着纸")
    lk = FR.part_lock("【林晚】22岁中国成年女性，蓝发及腰，齐刘海，G罩杯，手指甲为5厘米超长透明水晶甲，镶满钻石饰品", "手")
    assert "蓝发" not in lk and "成年" in lk and "水晶甲" in lk and "钻石" in lk
    assert FR.part_lock("【阿岚】26岁成年女性，黑色齐耳短发", "手") == "【阿岚】26岁成年女性"


def test_labels_r1_record_only_q5_q6_q7():
    """总调度 11-01 标注 contract_labels_r1（76/76 ok）：Q7 只记录、Q5 手型只记录、Q6 纯数字只记录；Q1 照挡，印样标待目检"""
    from ns_agent.gen_contract import report as RPT
    rec = {"size": "中景", "subject": None, "zones": ["upper"], "primary": "lin_wan", "slots": [], "missing": []}
    req = {"asset_refs": rec, "cast": [{"name": "林晚", "presence": "在画"}]}
    remote = {"faces": [{"h_ratio": 0.12, "bbox": [0, 0, 1, 1], "sims": {"lin_wan": 0.5}}], "text": [{"text": "0002"}]}
    hands = {"flags": ["手型可疑（第1只手：指长比 [5.5, 8.6]）"], "hands": 1, "poses": 1}
    r = postflight.evaluate("x.png", req, remote=remote, hands=hands, local={"Q2": [], "Q4": None, "Q7": {"clip": 0.33}})
    st = {i.id: i.status for i in r.items}
    assert st["Q7"] == "na" and st["Q5"] == "pass" and st["Q6"] == "pass" and st["Q1"] == "fail"
    flags = RPT.review_flags(r.to_dict())
    assert "场景相似度低" in flags and "手型可疑" in flags and "画面里有数字" in flags
    remote2 = {**remote, "text": [{"text": "LOGO 2026"}]}
    assert next(i for i in postflight.evaluate("x.png", req, remote=remote2, hands=hands, local={"Q2": [], "Q4": None, "Q7": None}).items
                if i.id == "Q6").status == "fail"


def test_q1_duplicate_face_and_partial_face():
    """总调度 11-01 标注：同一角色两张脸且原文没写镜子 → 不过；写了镜子 → 待目检；cast 局部的人出了脸 → 不过"""
    base = {"size": "近景", "subject": None, "zones": ["upper"], "primary": "lin_wan", "slots": [], "missing": []}
    lw = {"h_ratio": 0.15, "bbox": [0, 0, 1, 1], "sims": {"lin_wan": 0.85, "gu_chen": 0.05}}
    lw2 = {"h_ratio": 0.12, "bbox": [5, 0, 6, 1], "sims": {"lin_wan": 0.62, "gu_chen": 0.05}}
    gu = {"h_ratio": 0.14, "bbox": [9, 0, 10, 1], "sims": {"lin_wan": 0.02, "gu_chen": 0.7}}
    loc = {"Q2": [], "Q4": None, "Q7": None}

    def q1(rec, cast, faces):
        r = postflight.evaluate("x.png", {"asset_refs": rec, "cast": cast}, remote={"faces": faces, "text": []}, local=loc)
        return next(i for i in r.items if i.id == "Q1")
    lin = [{"name": "林晚", "presence": "在画"}]
    assert q1(base, lin, [lw, lw2]).status == "fail"
    assert q1({**base, "mirror": True}, lin, [lw, lw2]).status == "pass"
    part = lin + [{"name": "顾沉", "presence": "局部"}]
    assert "局部角色出了脸" in q1(base, part, [lw, gu]).detail
    desc = {**base, "characters": [{"character": "gu_chen", "presence": "局部", "face_described": True}]}
    assert q1(desc, part, [lw, gu]).status == "pass"


def test_bakeoff_scope_imgtag_and_suffix_variant():
    """BAKEOFF R11-12 A/B 放行（只限 scope=bakeoff）：I6 认 <imageN>是；I7 声明 suffix_variant 可换后缀；生产照旧"""
    import re as _re
    line = "图1是林晚的脸部参考（只取脸和发型）。"
    rec = {"slots": [{"kind": "face", "index": 1, "line": line, "file": "a.png"}], "missing": [], "characters": []}
    p_img = _re.sub(r"图(\d+)", r"<image\1>", line) + "中景构图（膝盖以上），林晚站在窗边"
    base = {"kind": "image", "prompt": p_img, "refs": ["a.png"], "asset_refs": rec, "compiled_by": "ns_agent.compiler",
            "cast": [{"name": "林晚", "presence": "在画"}], "loras": []}
    i = lambda r, k: next(x for x in preflight.check(r).items if x.id == k)   # noqa: E731
    assert i(base, "I6").status == "fail"
    assert i({**base, "scope": "bakeoff"}, "I6").status == "pass"
    assert i({**base, "scope": "bakeoff"}, "I7").status == "fail"
    assert i({**base, "scope": "bakeoff", "suffix_variant": "qa_suffix"}, "I7").status == "pass"


def test_q9_vqa_record_only_and_hc07(monkeypatch):
    """VQA Q9：enforce 关（旧口径）时没看图结果 → 不适用（不挡）；有缺陷 → 只记录；未成年外观 → 不过。
    项目方 11-01 16:10 转阻断（MASTER_PICTURE L-080 / D-VQA-01，config/vqa.json gate.enforce=true）后：没看图结果 = untested（挡），
    blocking 项 defect = fail——见 test_q9_vqa_enforced_blocks 与 tests/test_vqagate.py"""
    from ns_agent.gen_contract import postflight as PO
    VQ = PO._vqa()
    if VQ is None:
        pytest.skip("ns_agent.vqa 不在")
    monkeypatch.setattr(VQ, "enforced", lambda: False)
    rec = {"size": "中景", "subject": None, "zones": [], "primary": None, "slots": [], "missing": []}
    r = PO.evaluate("nowhere.png", {"asset_refs": rec, "cast": []}, vlm=None, local={"Q2": [], "Q4": None, "Q7": None})
    q9 = next((i for i in r.items if i.id == "Q9"), None)
    assert q9 is not None and q9.status == "na" and "Q9" not in [i.id for i in r.blocking]



def test_q9_vqa_enforced_blocks(monkeypatch):
    """项目方 11-01 16:10“一旦发现不对，叫系统重写做”（L-080 / D-VQA-01）：enforce 期没看图结果 = untested，挡契约"""
    from ns_agent.gen_contract import postflight as PO
    VQ = PO._vqa()
    if VQ is None:
        pytest.skip("ns_agent.vqa 不在")
    monkeypatch.setattr(VQ, "enforced", lambda: True)
    monkeypatch.setattr(PO, "_q9_live", lambda *a, **k: None)      # 不连真服务
    rec = {"size": "中景", "subject": None, "zones": [], "primary": None, "slots": [], "missing": []}
    r = PO.evaluate("nowhere.png", {"asset_refs": rec, "cast": []}, vlm=None, local={"Q2": [], "Q4": None, "Q7": None})
    q9 = next((i for i in r.items if i.id == "Q9"), None)
    assert q9 is not None and q9.status == "untested" and "Q9" in [i.id for i in r.blocking]
