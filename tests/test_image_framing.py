"""PROMPT（2026-10-31，K-REN-101）：出图提示词按景别只写看得见的造型部件，首句先写景别构图。
证据：方案 C 预览 S1（导演稿“手部特写起手”）把整套造型连鞋一起拼进提示词 → Qwen-Image 出成全身坐姿
（data/pipeline/runs/ep02_claude_director_v1/preview/_wrong_framing/S1_1_fullbody.png）。纯 CPU。"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in ("packages/schema", "services/agent", "services/render_router", "services/api", "tools"):
    sys.path.insert(0, str(ROOT / p))

from ns_agent import compiler as C  # noqa: E402
from ns_agent import framing as F  # noqa: E402
from ns_schema.script import CharacterLock, Episode, ScriptGlobals, Shot  # noqa: E402

G = ScriptGlobals(image_suffix="85mm人像镜头f/1.2大光圈",
                  character_locks=[CharacterLock(name="林晚", description="22岁中国成年女性，蓝发及腰、G罩杯、长腿")])
IMG_CU = "特写，低机位，林晚的双手停在键盘上方，黑色修身长袖上衣，黑色高亮镜面漆皮超短裙，12cm透明针形细跟高跟鞋，水晶甲映着屏幕蓝光"
IMG_WIDE = "全景，林晚坐在工位，黑色修身长袖上衣，黑色高亮镜面漆皮超短裙，12cm透明针形细跟高跟鞋"


def _shot(img):
    ep = Episode(number=2, title="t", source_line=1)
    return ep, Shot(episode=2, index=1, img_prompt=img, img_triggers=[], motion_prompt="lnwan01，她敲键盘——抬眼",
                    motion_triggers=["lnwan01"], source_line=1)


def test_size_and_visibility_rules():
    assert F.size_of("lnwan_qi，特写，手部") == "特写" and F.size_of("中近景，过肩") == "中近景"
    assert F.size_of("大特写，眼睛") == "大特写"
    assert not F.visible("12cm透明针形细跟高跟鞋", "特写") and not F.visible("黑色漆皮超短裙", "近景")
    assert F.visible("黑色漆皮超短裙", "中景") and not F.visible("透明高跟鞋", "中景")
    assert F.visible("透明高跟鞋", "全景") and F.visible("an elegant top", "近景")
    assert not F.visible("glossy black patent leather micro miniskirt", "特写")
    assert F.filter_parts("黑色上衣、黑色漆皮超短裙、12cm细跟", "近景") == "黑色上衣"
    assert F.lead("特写").startswith("特写") and F.lead(None) == ""


@pytest.fixture
def framing_on(monkeypatch):
    monkeypatch.setattr(F, "enabled", lambda *a, **k: True)


def test_closeup_prompt_drops_lower_body_and_leads_with_size(framing_on):
    ep, s = _shot(IMG_CU)
    c = C.compile_shot(ep, s, G, set())
    p = c.image_prompt
    assert "高跟" not in p and "超短裙" not in p and "长腿" not in p and "鞋跟直径" not in p
    assert "水晶甲" in p and "黑色修身长袖上衣" in p
    assert p.startswith("特写构图") and "漆皮" not in p


def test_wide_shot_keeps_full_outfit(framing_on):
    ep, s = _shot(IMG_WIDE)
    p = C.compile_shot(ep, s, G, set()).image_prompt
    assert "高跟鞋" in p and "超短裙" in p and "全景构图" in p


def test_switch_off_keeps_production_prompt_unchanged(monkeypatch):
    monkeypatch.setattr(F, "enabled", lambda *a, **k: False)
    ep, s = _shot(IMG_CU)
    p = C.compile_shot(ep, s, G, set()).image_prompt
    assert "高跟鞋" in p and "特写构图" not in p


def test_per_project_episode_switch(tmp_path, monkeypatch):
    import json
    cfg = tmp_path / "image_framing.json"
    cfg.write_text(json.dumps({"default": True, "per_project": {"__default__": {"off_episodes": [2], "keep_locked_shots": True}}}),
                   encoding="utf-8")
    monkeypatch.setattr(F, "CFG", cfg)
    repo = F.REPO
    assert F.enabled(2, 3, repo) is False                      # ep02 整集关（A/B 跑片中）
    shot = tmp_path / "data" / "renders" / "ep05" / "S1"
    shot.mkdir(parents=True)
    (shot / "takes.json").write_text(json.dumps({"locked": {"image": 3}}), encoding="utf-8")
    monkeypatch.setattr(F, "REPO", tmp_path)                    # 把 tmp 当成默认项目根
    assert F.enabled(5, 1, tmp_path) is False                   # 已定稿首帧的镜保持旧提示词
    assert F.enabled(5, 2, tmp_path) is True                    # 同集未定稿的镜开
    other = tmp_path / "projects" / "series10"
    other.mkdir(parents=True)
    assert F.enabled(1, 1, other) is True                       # 新剧默认开
    cfg.write_text(json.dumps({"enabled": False}), encoding="utf-8")
    assert F.enabled(1, 1, other) is False                      # 旧格式仍认


def test_repo_config_keeps_ep02_off():
    assert F.enabled(2, 1) is False


def test_lower_body_focus_is_not_filtered(framing_on):
    assert F.lower_focus("hh12clear，极近特写，林晚穿漆皮短裙站在门口")
    assert F.lower_focus("特写，脚踝与12cm透明细跟，地毯")
    assert not F.lower_focus("特写，低机位，林晚的双手停在键盘上方，12cm透明细跟")
    ep, s = _shot("特写，脚踝与12cm透明针形细跟高跟鞋踩在地毯上，黑色漆皮超短裙下摆")
    p = C.compile_shot(ep, s, G, set()).image_prompt
    assert "高跟鞋" in p and "特写构图" in p


def test_filter_keeps_label_head_and_drops_empty():
    assert F.filter_parts("【林晚造型】超短裙，12cm透明细高跟，素颜", "特写") == "【林晚造型】素颜"
    assert F.filter_parts("【林晚造型】超短裙，12cm透明细高跟", "特写") == ""


# ---- IMGGEN 第二轮（K-REN-123 / K-REV-122）：特写退成中景、双人镜第二人不出脸 ----
IMG_FACE_CU_HEELS = ("hh12clear，特写，低机位，林晚穿黑色漆皮束腰配黑色漆皮短裙，12cm侧开透明细高跟，雾霾天蓝色及腰直发，"
                     "四分之三侧身站定，视线越过镜头看向巷口，表情平静")
IMG_PART_CU = "特写，平视，小餐桌上一盏暖黄顶灯，林晚的手从画面右侧伸入，指尖按着一张白色续约单的纸角，自然的轻微不对称，眼睛为真实人眼大小"


def test_dropped_shoe_trigger_is_not_lower_focus():
    # hh12clear 的 LoRA 不可用、被编译器剥掉 → 不能再当“鞋是主体”的证据
    assert F.lower_focus("hh12clear，特写，脚踝与细跟") is True
    assert F.lower_focus("hh12clear，特写，脚踝与细跟", kept_triggers=[]) is True   # 触发词不算了，但首句写下半身仍按首句判
    assert F.lower_focus(IMG_FACE_CU_HEELS, kept_triggers=["lnwan_qi"]) is False
    assert F.lower_focus("特写，低机位，脚踝与细跟占满画面") is True     # 首个非机位分句就是下半身


def test_closeup_subject_and_lead():
    assert F.closeup_subject(IMG_FACE_CU_HEELS, "特写") == "face"
    assert F.closeup_subject(IMG_PART_CU, "特写") == "part"           # 通用质感句里的“眼睛”不算脸
    assert F.closeup_subject("中景，林晚看向窗外", "中景") is None
    assert "60%" in F.closeup_lead("特写", "face") and F.closeup_lead("特写", "face").startswith("特写构图")
    assert "画面里只有手" in F.closeup_lead("特写", "part", IMG_PART_CU)   # G22（CODE-RSI 11-01）：11:10 起正向句，旧句“只拍手”已取代
    assert F.strip_fullbody("四分之三侧身站定，视线看向巷口，侧身站在全身镜前") == "视线看向巷口"


def test_face_closeup_with_dropped_shoe_trigger_drops_heels_and_stance(framing_on):
    ep = Episode(number=8, title="t", source_line=1)
    s = Shot(episode=8, index=1, img_prompt=IMG_FACE_CU_HEELS, img_triggers=["hh12clear"], motion_prompt="她转身",
             motion_triggers=[], source_line=1)
    p = C.compile_shot(ep, s, G, set()).image_prompt
    assert "高跟" not in p and "短裙" not in p and "站定" not in p
    assert "60%" in p and "视线越过镜头" in p


def test_two_shot_asks_both_faces_toward_camera(framing_on):
    g2 = ScriptGlobals(image_suffix="85mm", character_locks=[CharacterLock(name="林晚", description="22岁中国成年女性"),
                                                              CharacterLock(name="顾沉", description="34岁成年男性")])
    ep = Episode(number=6, title="t", source_line=1)
    s = Shot(episode=6, index=4, img_prompt="近景，林晚抬眼看向顾沉，顾沉低头看她", img_triggers=[], motion_prompt="对视",
             motion_triggers=[], source_line=1)
    p = C.compile_shot(ep, s, g2, set()).image_prompt
    assert "两张脸都清晰入画" in p and "three-quarter" in p
    s1 = Shot(episode=6, index=5, img_prompt="近景，林晚抬眼看向窗外", img_triggers=[], motion_prompt="看",
              motion_triggers=[], source_line=1)
    assert "两张脸" not in C.compile_shot(ep, s1, g2, set()).image_prompt
