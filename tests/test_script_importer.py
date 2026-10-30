from pathlib import Path

import pytest

from ns_agent.importer.script_md import import_script

ROOT = Path(__file__).resolve().parent.parent
LIB = ROOT / "script play lib"

SCRIPT = """# 测试剧本

**每条prompt统一前缀（角色锁）**

```Plain Text
【林晚】22岁中国成年女性，蓝发
【顾沉】34岁成年男性CEO
```

**每条motion统一后缀**：`真人写实摄影，9:16竖屏`

**基础负面**：`动漫脸、水印`

**LoRA 触发词表**

```Plain Text
图像LoRA（说明）
  hh12clear     12cm透明细高跟
视频LoRA（说明）
  lnwan01       林晚
未训练完成的LoRA：渲染时自动去掉对应触发词。
```

## ep01《旋转门》🔴名场面

**剧情**：入职第一天。

**镜1｜img**：`hh12clear，清晨写字楼旋转门`

**motion**：`lnwan01，camera tilt up 缓慢上摇`

**sound**：`高跟鞋声`

**🎙（镜1尾入）**：*第一天实习。*

\\*\\*镜2｜img（核心镜）**：`电梯轿厢`

**motion**：`static camera`

**时长**：6秒

**sound**：`电梯低鸣`

**对白**：（顾沉低声）“蓝头发，很大胆。”／（她小声）“染了三年了。”

**对白屏幕上**：`她发：完了。`

**对白（无台词——只用眼神）**

**负面追加**：`变形的手部`

## ep17《酒会》

**镜1｜img**：`酒会`

**motion**：`static`

**sound**：`人声`

## 📋 自检表

**本批装饰连续性自查表**：不属于任何一集
"""

IMAGE_DOC = """### 数据B

```Plain Text
ep01-08:D0｜ep16-18:D3(17为D4礼服)｜
```

### 数据D

```JSON
[{"id":"REF-LW-01","desc":"林晚素颜","用途":"ep01-08"}]
```

### 数据E

```JSON
[
  {"trigger":"hh12clear","类型":"图像LoRA","文件":"wardrobe_heels_v1.safetensors","强度":"0.6-0.8"},
  {"trigger":"lnwan01","类型":"H3视频LoRA","文件":"lin_wan_h3_v1.safetensors","强度":"0.6-1.0"}
]
```
"""


@pytest.fixture
def result(tmp_path):
    script = tmp_path / "script.md"
    script.write_text(SCRIPT, encoding="utf-8")
    doc = tmp_path / "image.md"
    doc.write_text(IMAGE_DOC, encoding="utf-8")
    return import_script(script, doc)


def test_globals(result):
    g = result.globals
    assert [c.name for c in g.character_locks] == ["林晚", "顾沉"]
    assert g.motion_suffix == "真人写实摄影，9:16竖屏"
    assert g.base_negative == "动漫脸、水印"
    triggers = {t.trigger: t for t in g.lora_triggers}
    assert triggers["hh12clear"].kind == "image"
    assert triggers["hh12clear"].file == "wardrobe_heels_v1.safetensors"
    assert triggers["hh12clear"].strength == (0.6, 0.8)
    assert triggers["lnwan01"].kind == "video"
    assert g.references[0].id == "REF-LW-01"


def test_episode_and_shots(result):
    ep = result.episodes[0]
    assert (ep.number, ep.title, ep.high_intensity, ep.tag) == (1, "旋转门", True, "名场面")
    assert ep.synopsis == "入职第一天。"
    assert ep.negative_extra == "变形的手部"
    s1, s2 = ep.shots
    assert s1.id == "ep01-S1"
    assert s1.img_triggers == ["hh12clear"]
    assert s1.motion_triggers == ["lnwan01"]
    assert s1.voiceover.note == "镜1尾入" and s1.voiceover.text == "第一天实习。"


def test_escaped_shot_and_dialogue(result):
    s2 = result.episodes[0].shots[1]
    assert s2.index == 2 and s2.img_note == "核心镜" and s2.img_prompt == "电梯轿厢"
    assert [(d.speaker_note, d.text) for d in s2.dialogue] == [
        ("顾沉低声", "蓝头发，很大胆。"), ("她小声", "染了三年了。")]
    assert s2.extras[0].label == "对白屏幕上" and s2.extras[0].text == "她发：完了。"


def test_dialogue_without_separator_and_stacked_parens():
    from ns_agent.importer.script_md import _parse_dialogue
    got = _parse_dialogue("（顾沉）“方案错了。”／（她慌）“对不起——”（他）“不用急。”")
    assert [(d.speaker_note, d.text) for d in got] == [
        ("顾沉", "方案错了。"), ("她慌", "对不起——"), ("他", "不用急。")]
    got = _parse_dialogue("（接通）（她，很小声）“……睡不着。”")
    assert (got[0].speaker_note, got[0].stage, got[0].text) == ("她，很小声", "接通", "……睡不着。")
    assert _parse_dialogue("无台词")[0].text == "无台词"


def test_sound_blocks():
    from ns_agent.importer.script_md import _sound_blocks
    assert _sound_blocks("雨声，心跳；【亲密声】先A后B；【H3 audio】soft rain, heartbeat") == ("先A后B", "soft rain, heartbeat")
    assert _sound_blocks("高跟鞋声") == ("", "")
    assert _sound_blocks("x；【H3 audio】only h3") == ("", "only h3")


def test_music_blocks():
    from ns_agent.importer.script_md import _block, _sound_blocks
    line = "雨声；【亲密声】呼吸；【配乐】进入，强度1，压低；【H3 audio】soft rain"
    assert _sound_blocks(line) == ("呼吸", "soft rain")
    assert _block(line, "配乐") == "进入，强度1，压低"
    assert _block("低音提琴铺底，慢速；【BGM】slow cello and piano, 70 bpm", "BGM") == "slow cello and piano, 70 bpm"


def test_pose_trigger_tokens_are_leading_triggers():
    from ns_agent.importer.script_md import _leading_triggers
    assert _leading_triggers("hh12clear，pose_side_lying，卧室侧光", {"hh12clear"}) == ["hh12clear", "pose_side_lying"]
    assert _leading_triggers("卧室，pose_x", set()) == []   # 只认开头


def test_duration_line_and_default(result):
    s1, s2 = result.episodes[0].shots
    assert (s1.duration, s1.duration_source) == (10, "default")
    assert (s2.duration, s2.duration_source) == (6, "script")
    assert s2.sound == "电梯低鸣"  # 时长行不吞掉后面的字段


def test_decor_schedule_with_override(result):
    assert result.episodes[0].shots[0].decor_state == "D0"
    assert result.episodes[1].shots[0].decor_state == "D4"


def test_text_after_episode_section_is_not_attached(result):
    assert all(e.label != "本批装饰连续性自查表" for ep in result.episodes for e in ep.extras)


def test_validation_warns_on_short_episode(result):
    assert any("ep17 有 1 镜" in w for w in result.warnings)


@pytest.mark.skipif(not (LIB / "为他而骚 （剧本和镜头）v2.md").exists(), reason="需要原始剧本")
def test_full_script():
    r = import_script(LIB / "为他而骚 （剧本和镜头）v2.md", LIB / "为他而骚（image提示词） v2.md")
    assert len(r.episodes) == 60
    assert sum(len(e.shots) for e in r.episodes) == 360
    assert all(s.img_prompt and s.motion_prompt and s.sound for e in r.episodes for s in e.shots)
    assert all(s.decor_state for e in r.episodes for s in e.shots)
