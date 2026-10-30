"""G1（2026-10-30）：尾帧与首帧用同一套规格词（触发词、材质 / 鞋跟 / 脚趾甲条目、特写 / 暗场 / 安全镜纠正器条目）。
编译器 last_prompt 与 frame_spec qwen_last 两条路径都要覆盖。"""
from pathlib import Path

from ns_agent import bible as B
from ns_agent import compiler as C
from ns_agent import frame_spec as F
from ns_schema.script import CharacterLock, Episode, ScriptGlobals, Shot

FIX = Path(__file__).parent / "fixtures" / "t06_golden"


def _shot(img: str, motion: str, img_triggers=("hh12clear",)):
    ep = Episode(number=1, title="t", source_line=1)
    s = Shot(episode=1, index=1, img_prompt=img, img_triggers=list(img_triggers),
             motion_prompt=motion, motion_triggers=[], source_line=1)
    g = ScriptGlobals(image_suffix="85mm人像镜头f/1.2大光圈",
                      character_locks=[CharacterLock(name="林晚", description="蓝发")])
    return ep, s, g


def _material_terms(b, text):
    return [m.term for m in b.materials if any(w in text for w in m.match)]


def test_compiler_last_prompt_carries_first_frame_specs():
    b = B.load_bible(root=FIX)
    ep, s, g = _shot("hh12clear，极近特写，夜晚，林晚穿黑色漆皮超短裙站在门口",
                     "她抬眼看向门外——转身走出门")
    c = C.compile_shot(ep, s, g, {t.file for t in g.lora_triggers}, bible=b)
    assert c.last_prompt
    for term in _material_terms(b, s.img_prompt):           # 漆皮句、6mm 鞋跟句
        assert term in c.image_prompt and term in c.last_prompt
    for term in C.corrector_terms(c.image_body, adult=c.adult, bible=b):   # 特写、暗场、安全镜
        assert term in c.image_prompt and term in c.last_prompt


def test_compiler_last_prompt_trigger_and_end_state_material():
    b = B.load_bible(root=FIX)
    ep, s, g = _shot("hh12clear，林晚坐在床边", "她慢慢起身——赤脚走向窗边")
    from ns_schema.script import LoraTrigger
    g.lora_triggers = [LoraTrigger(trigger="hh12clear", kind="image", description="透明高跟", file="hh12clear.safetensors")]
    c = C.compile_shot(ep, s, g, {"hh12clear.safetensors"}, bible=b)
    assert c.last_prompt.startswith("hh12clear，")
    toenail = next(m.term for m in b.materials if "赤脚" in m.match)
    assert toenail in c.last_prompt           # 结束状态里出现赤脚 → 尾帧补脚趾甲条目


def test_frame_spec_qwen_last_carries_first_frame_specs():
    b = B.load_bible(root=FIX)
    ep, s, g = _shot("hh12clear，极近特写，夜晚，林晚穿黑色漆皮超短裙站在门口",
                     "她抬眼看向门外——转身走出门")
    sp = F.build_spec(ep, s, g, available_triggers={"hh12clear"}, bible=b)
    q, ql = sp.model_prompt.qwen, sp.model_prompt.qwen_last
    assert ql and ql.startswith("hh12clear，")
    rules = [f.text for f in sp.facts if f.kind == "rule"]
    for r in rules:
        assert r in q and r in ql
    for term in C.corrector_terms(C._strip_triggers(s.img_prompt, s.img_triggers), adult=sp.adult, bible=b):
        if term in q:
            assert term in ql


def test_specs_not_repeated_when_writer_already_wrote_them():
    """项目方 2026-10-30：系统自动补规格词，但写作者在原文 / 结束状态里写过的同一条目不再追加"""
    b = B.load_bible(root=FIX)
    patent = next(m.term for m in b.materials if "漆皮" in m.match)
    closeup = next(r.term for r in b.shot_rules if "特写" in r.match)
    ep, s, g = _shot(f"hh12clear，极近特写，林晚穿黑色漆皮超短裙，{patent}，{closeup}",
                     f"她抬眼——转身，{patent}，{closeup}")
    c = C.compile_shot(ep, s, g, set(), bible=b)
    assert c.image_prompt.count(patent) == 1 and c.image_prompt.count(closeup) == 1
    assert c.last_prompt.count(patent) == 1 and c.last_prompt.count(closeup) == 1
    sp = F.build_spec(ep, s, g, available_triggers={"hh12clear"}, bible=b)
    for text in (sp.model_prompt.qwen, sp.model_prompt.qwen_last):
        assert text.count(closeup) <= 1


def test_first_frame_spec_still_added_to_last_frame_when_only_in_img():
    b = B.load_bible(root=FIX)
    patent = next(m.term for m in b.materials if "漆皮" in m.match)
    ep, s, g = _shot(f"hh12clear，林晚穿黑色漆皮超短裙，{patent}", "她抬眼——转身走出门")
    c = C.compile_shot(ep, s, g, set(), bible=b)
    assert c.image_prompt.count(patent) == 1 and c.last_prompt.count(patent) == 1


def test_adult_red_episode_inherits_by_default_and_per_shot_switch(tmp_path):
    """项目方 2026-10-30 定“恢复整集判定”：默认集标题 🔴 → 每镜 adult；adult_overrides "per_shot": true 才逐镜"""
    import json
    import shutil
    ep = Episode(number=1, title="t", source_line=1, high_intensity=True)
    plain = Shot(episode=1, index=1, img_prompt="林晚站在旋转门前", motion_prompt="她抬眼", source_line=1)
    intimate = Shot(episode=1, index=2, img_prompt="林晚站在床边", motion_prompt="她抬眼", source_line=2,
                    sound_intimate="【亲密声】她轻声喘息")
    b = B.load_bible(root=FIX)
    assert not b.adult_per_shot()
    assert C.classify_adult(ep, plain, b) == ["整集🔴"] and C.classify_adult(ep, intimate, b) == ["整集🔴"]
    shutil.copytree(FIX / "config", tmp_path / "config")
    ov = tmp_path / "config" / "adult_overrides.json"
    ov.write_text(json.dumps({**json.loads(ov.read_text(encoding="utf-8")), "per_shot": True}), encoding="utf-8")
    b2 = B.load_bible(root=tmp_path)
    assert b2.adult_per_shot()
    assert C.classify_adult(ep, plain, b2) == [] and C.classify_adult(ep, intimate, b2) == ["亲密声"]


def _bible_with_identity_trigger(tmp_path):
    """临时项目：fixture 规则 + config/auto_lora_triggers.json（与导入器同一份配置）"""
    import json
    import shutil
    shutil.copytree(FIX / "config", tmp_path / "config")
    (tmp_path / "config" / "auto_lora_triggers.json").write_text(json.dumps({"characters": {"林晚": [
        {"trigger": "lnwan_qi", "kind": "image", "file": "lin_wan_qi_v1.safetensors", "strength": 1.0}]}}),
        encoding="utf-8")
    return B.load_bible(root=tmp_path)

def test_identity_trigger_auto_added_first_on_both_frames(tmp_path):
    """项目方 2026-10-30“系统自动补”：林晚入镜 → lnwan_qi 放在首帧 / 尾帧触发词最前，pose_* 仍在其它触发词之后"""
    b = _bible_with_identity_trigger(tmp_path)
    ep, s, g = _shot("hh12clear，pose_x，林晚站在门口", "她抬眼——转身走出门", img_triggers=("hh12clear", "pose_x"))
    c = C.compile_shot(ep, s, g, {"lin_wan_qi_v1.safetensors"}, bible=b)
    assert c.image_prompt.startswith("lnwan_qi，") and c.last_prompt.startswith("lnwan_qi，")
    assert c.image_loras[0] == ("lin_wan_qi_v1.safetensors", 1.0)
    sp = F.build_spec(ep, s, g, available_triggers=None, bible=b)
    q = sp.model_prompt.qwen
    assert q.startswith("lnwan_qi，hh12clear，pose_x") and sp.model_prompt.qwen_last.startswith("lnwan_qi，")
    # 本机没有 LoRA 文件：触发词照样保留（gpu3 按注册表加载），只是不进 image_loras
    c2 = C.compile_shot(ep, s, g, set(), bible=b)
    assert c2.image_prompt.startswith("lnwan_qi，") and c2.image_loras == []


def test_identity_trigger_not_added_without_character_or_twice(tmp_path):
    b = _bible_with_identity_trigger(tmp_path)
    ep, s, g = _shot("空荡的办公室走廊，夜晚", "镜头缓慢推进——灯熄灭", img_triggers=())
    assert "lnwan_qi" not in C.compile_shot(ep, s, g, set(), bible=b).image_prompt
    ep, s, g = _shot("lnwan_qi，林晚站在门口", "她抬眼——转身", img_triggers=("lnwan_qi",))
    c = C.compile_shot(ep, s, g, set(), bible=b)
    assert c.image_prompt.count("lnwan_qi") == 1
