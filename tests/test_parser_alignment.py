"""T04：笔记本导入器与 gpu3 解析器（weita_render.parse_script）读同一剧本要得到同样的字段。

夹具全是占位文字（不是剧情）。期望值 = 2026-10-30 gpu3 解析器（打了 docs/parser_diff.md 的 T04 补丁）对同一夹具的输出。
设了环境变量 NS_GPU3_PARSER=<weita_render.py 本地副本> 时，另外用 tools/parser_diff.py 直接对比两边。
"""
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "packages" / "schema", ROOT / "services" / "agent", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from ns_agent.importer.script_md import _split_dialogue, _unwrap, import_script  # noqa: E402

FIXTURE = """# 剧本

**LoRA 触发词表**
```
图像LoRA
  trigaaa       占位A
视频LoRA
  trigvvv       占位V
```

---

## ep01《标题甲》🔴

**剧情**：占位剧情。

**配乐**：占位配乐说明；【BGM】Placeholder bgm prompt, 60 BPM.

**镜1｜img（备注甲）**：`trigaaa，占位画面\\.一 **加粗** 与 *斜体*`
**motion**：`trigvvv，static camera 占位动作——占位结束`
**时长**：8秒
**sound**：占位声音；【亲密声】占位亲密；【配乐】：占位cue；【H3 audio】Placeholder sound one.
**对白**：（甲，语气）“占位一。”／（停顿占位）／（乙）：“占位二。”／丙：“占位三。”／（丁）“占位\\\\四。／占位五。”
**🎙（独白说明）**：占位独白
**H3提示词**：
```text
Line one \\* kept.

overall_soundscape: Placeholder.
```

**镜2｜img**：占位画面二`——尾巴
**motion**：占位动作二
**时长**：10秒
**sound**：占位声音二；【配乐】占位cue二；【H3 audio】Placeholder two.
**对白**：—

---
"""


@pytest.fixture()
def script(tmp_path):
    p = tmp_path / "fixture.md"
    p.write_text(FIXTURE, encoding="utf-8", newline="\n")
    return p


def test_values_strip_markdown_like_gpu3():
    assert _unwrap("`占位\\.一 **加粗** 与 *斜体*`") == "占位.一 加粗 与 斜体"
    assert _unwrap("占位`——尾巴") == "占位——尾巴"            # 残缺的单边反引号
    assert _unwrap("占位\\\\四") == "占位\\四"                 # \\ = 一个反斜杠
    assert _unwrap("中文\\字") == "中文\\字"                   # 非 ASCII 标点不是转义


def test_unquoted_dialogue_segments_are_not_lines():
    lines, stage = _split_dialogue("（甲）“占位一。”／（停顿占位）／—")
    assert [(d.speaker_note, d.text) for d in lines] == [("甲", "占位一。")]
    assert stage == ["（停顿占位）", "—"]
    assert _split_dialogue("无台词") == ([], ["无台词"])


def test_fixture_fields(script):
    imp = import_script(script)
    (ep,) = imp.episodes
    assert ep.music_bgm == "Placeholder bgm prompt, 60 BPM."
    s1, s2 = ep.shots
    assert s1.img_triggers == ["trigaaa"] and s1.img_prompt == "trigaaa，占位画面.一 加粗 与 斜体"
    assert s1.motion_triggers == ["trigvvv"]
    assert (s1.duration, s1.duration_source) == (8, "script")
    assert (s1.sound_intimate, s1.music_cue, s1.sound_h3) == ("占位亲密", "占位cue", "Placeholder sound one.")
    assert [(d.speaker_note, d.text) for d in s1.dialogue] == [
        ("甲，语气", "占位一。"), ("乙", "占位二。"), ("丙", "占位三。"), ("丁", "占位\\四。／占位五。")]
    assert s1.dialogue_stage == ["（停顿占位）"]
    assert (s1.voiceover.note, s1.voiceover.text) == ("独白说明", "占位独白")
    assert s1.h3_prompt == "Line one \\* kept.\n\noverall_soundscape: Placeholder."   # 代码块逐字
    assert s2.img_prompt == "占位画面二——尾巴"
    assert s2.dialogue == [] and s2.dialogue_stage == ["—"]


def test_validator_still_flags_unquoted_segments(script):
    import validate_qwen_script as V
    rep = V.validate(script)
    s2 = next(s for s in rep["episodes"][0]["shots"] if s["id"].endswith("2"))
    assert any(i["rule_id"] == "S1-W4" for i in s2["issues"])


def test_diff_views_reports_field_and_gpu3_gaps():
    import parser_diff as PD
    shot = {f: "" for f in PD.SHOT_FIELDS}
    lap = {1: {"bgm": "x", "shots": {1: dict(shot, img="a"), 2: dict(shot)}}}
    gpu = {1: {"bgm": None, "shots": {1: dict(shot, img="b")}}}
    got = {(d["id"], d["field"]) for d in PD.diff_views(lap, gpu)}
    assert got == {("ep01", "bgm(gpu3 无字段)"), ("ep01", "shot_ids"), ("ep01s1", "img")}


@pytest.mark.skipif(not os.environ.get("NS_GPU3_PARSER"), reason="需要 NS_GPU3_PARSER=weita_render.py 本地副本")
def test_fixture_matches_gpu3_parser(script):
    import parser_diff as PD
    rep = PD.compare(script, PD.load_gpu3_parser(Path(os.environ["NS_GPU3_PARSER"])))
    assert rep["diffs"] == []
