"""E8 配乐取值回归（2026-10-30 总调度规则汇编查出）：剧本明确写 N/A = 不要配乐；只有缺字段才回退本集【BGM】，
且回退的 BGM 要过 H3-S3；中文配乐提示强度 0 / 静默 → N/A"""
from ns_agent.h3_prompt import resolve_music

BGM = "Sparse piano notes at a slow tempo, fading out."


def test_script_explicit_na_is_respected():
    assert resolve_music(None, "N/A", BGM) == ("N/A", "script")


def test_missing_field_falls_back_to_bgm():
    assert resolve_music(None, None, BGM) == (BGM, "episode")
    assert resolve_music(None, "", BGM) == (BGM, "episode")


def test_silent_cue_blocks_fallback():
    assert resolve_music(None, None, BGM, cue="落下，强度0，无需避让") == ("N/A", "cue_silent")
    assert resolve_music(None, None, BGM, cue="撤到静默") == ("N/A", "cue_silent")
    assert resolve_music("撤到静默：强度0", None, BGM) == ("N/A", "cue_silent")
    # 强度 0.5 / 10 不是 0
    assert resolve_music(None, None, BGM, cue="推高，强度 10")[1] == "episode"


def test_bgm_must_pass_h3_s3():
    assert resolve_music(None, None, "Sad romantic piano.") == ("N/A", "episode_invalid")
    assert resolve_music(None, None, "Piano. Bass. Drums. Strings.") == ("N/A", "episode_invalid")
    assert resolve_music(None, None, "慢速钢琴") == ("N/A", "episode_invalid")


def test_edit_and_script_priority():
    assert resolve_music("Low strings.", "N/A", BGM) == ("Low strings.", "edit")
    assert resolve_music("N/A", None, BGM) == ("N/A", "edit")
    assert resolve_music(None, "Soft guitar.", BGM) == ("Soft guitar.", "script")
