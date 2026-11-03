"""FIX：项目方 2026-10-31 两项决定——“改成正常节奏”、独白镜加嘴唇闭合“加”。"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in ("packages/schema", "services/agent", "services/render_router", "services/post"):
    sys.path.insert(0, str(ROOT / p))

from ns_agent import compiler as C  # noqa: E402
from ns_agent import h3_prompt as H3  # noqa: E402
from ns_schema.h3_lint import alignment_line  # noqa: E402
from ns_schema.script import CharacterLock, DialogueLine, Episode, ScriptGlobals, Shot, Voiceover  # noqa: E402

BODY = ("[Shot 1] Live-action, cinematic, shallow depth of field, a static close-up begins in the position, framing "
        "and lighting established by Picture 1, showing the young woman. She closes her eyes and breathes out. She "
        "settles into the pose established by Picture 2 at the end of the shot.")
PROMPT = (alignment_line(192) + "\n\nintegrated_multimodal_description: " + BODY +
          "\n\noverall_soundscape: Soft hum.\n\nnon_diegetic_music: N/A")


# ---------------- 正常节奏

def test_rules_say_normal_pace():
    rules = (ROOT / "config" / "script_chat_rules.md").read_text(encoding="utf-8")
    assert "正常或偏慢速度" not in rules and "动作量按正常速度在 N 秒内做完，并留出最后约 1 秒仍在进行的动作" in rules
    app = (ROOT / "config" / "script_chat_rules_appendix.md").read_text(encoding="utf-8") + (ROOT / "config" / "script_chat_runs" / "series10_v1_appendix.md").read_text(encoding="utf-8")   # HEADER-O：林晚声线移到 V1 专属附录
    prod = (ROOT / "docs" / "production_rules_v3.md").read_text(encoding="utf-8")
    assert "语速偏慢" not in app and "语速偏慢" not in prod and "自然语速" in app and "自然语速" in prod
    assert "中高音区" in app and "甜而带气声" in app            # 音色音区不动


def test_tts_speeds_are_normal():
    v = json.loads((ROOT / "config" / "voices.json").read_text(encoding="utf-8"))["characters"]
    assert v["lin_wan"]["speed"] == 1.0 and v["lin_wan"]["vo_speed"] == 1.0 and v["gu_chen"]["speed"] == 1.0
    assert "改成正常节奏" in v["lin_wan"]["speed_owner_decision"]


def test_lint_a11_text_synced():
    import importlib
    sys.path.insert(0, str(ROOT / "tools"))
    V = importlib.import_module("validate_qwen_script")
    assert "正常速度" in V.LINT_RULE_TEXT["H3-A11"]


# ---------------- 独白镜嘴唇闭合

def test_add_lips_closed_on_first_sentence_and_idempotent():
    out = H3.add_lips_closed(PROMPT)
    assert ("established by Picture 1, showing the young woman, while the on-screen character's lips remain "
            "completely closed. She closes") in out
    assert H3.add_lips_closed(out) == out
    from ns_render import h3_video as HV
    i2v = HV.i2v_prompt(out)[0]
    assert "lips remain completely closed" in i2v and "Picture 2" not in i2v


def _ep_shot(dialogue=(), vo=None, img="近景，林晚闭眼"):
    ep = Episode(number=2, title="t", source_line=1)
    s = Shot(episode=2, index=1, img_prompt=img, motion_prompt="x", source_line=1, duration=8,
             dialogue=list(dialogue), voiceover=vo, h3_prompt=PROMPT)
    return ep, s


def test_compiler_adds_lips_only_for_monologue_shots_with_people():
    g = ScriptGlobals(character_locks=[CharacterLock(name="林晚", description="蓝发")])
    ep, s = _ep_shot(vo=Voiceover(note=None, text="他看我的方式，不像看一个实习生。"))
    c = C.compile_shot(ep, s, g, set())
    assert c.h3_lips_closed_added and "lips remain completely closed" in c.video_prompt
    assert "实习生" not in c.video_prompt                       # 独白本身仍不进 H3
    ep, s = _ep_shot(dialogue=[DialogueLine(speaker_note="林晚", text="嗯。")],
                     vo=Voiceover(note=None, text="他看我的方式。"))
    assert not C.compile_shot(ep, s, g, set()).h3_lips_closed_added      # 有台词 → 不加
    ep, s = _ep_shot()
    assert not C.compile_shot(ep, s, g, set()).h3_lips_closed_added      # 无独白 → 不加
    ep, s = _ep_shot(vo=Voiceover(note=None, text="城市的夜。"), img="远景，空荡的街道")
    assert not C.compile_shot(ep, s, g, set()).h3_lips_closed_added      # 没人在画 → 不加
