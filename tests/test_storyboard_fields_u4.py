"""fredw-92/U4：镜头摘要带出剧本分镜字段原文（storyboard），集数据带出配乐整行 / 【BGM】原文。只读、逐字。"""
from ns_api import app as app_mod
from ns_api import episodes_fast as EF
from ns_schema.script import CastEntry, DialogueLine, Shot


def _shot(**kw) -> Shot:
    base = dict(episode=2, index=3, img_prompt="画面原文", motion_prompt="lnwan01，推近，她抬头——停在窗边",
                sound="空调声；【配乐】延续，强度1；【H3 audio】AC hum.", sound_h3="AC hum.", music_cue="延续，强度1",
                h3_prompt="A\n\nintegrated_multimodal_description: B", dialogue=[DialogueLine(text="嗯", speaker_note="顾沉")],
                duration=6, duration_source="script", source_line=1)
    base.update(kw)
    return Shot(**base)


def test_storyboard_is_verbatim():
    sb = app_mod._storyboard(_shot(scene_id="office_night", scene_detail="台灯亮着", sound_intimate="",
                                   cast=[CastEntry(name="林晚", presence="在画", raw="林晚（在画｜中｜前）")],
                                   cast_raw="林晚（在画｜中｜前）", link="接力", link_carry="外套在手"))
    assert sb["img_prompt"] == "画面原文"
    assert sb["motion_prompt"] == "lnwan01，推近，她抬头——停在窗边"
    assert sb["end_state"] == "停在窗边" and sb["end_state_source"] == "motion"
    assert sb["scene_id"] == "office_night" and sb["scene_detail"] == "台灯亮着"
    assert sb["sound_h3"] == "AC hum." and sb["music_cue"] == "延续，强度1" and sb["sound_intimate"] == ""
    assert sb["h3_prompt"].startswith("A\n\n")
    assert sb["duration"] == 6 and sb["duration_source"] == "script"
    assert sb["cast_raw"] == "林晚（在画｜中｜前）" and sb["cast"][0]["name"] == "林晚"
    assert sb["link"] == "接力" and sb["link_carry"] == "外套在手"


def test_storyboard_old_draft_gaps_stay_empty():
    sb = app_mod._storyboard(_shot(motion_prompt="她抬头", sound="", sound_h3="", music_cue="", h3_prompt=None,
                                   duration=10, duration_source="default"))
    assert sb["end_state"] is None and sb["end_state_source"] is None
    assert sb["scene_id"] is None and sb["cast"] is None and sb["link"] is None
    assert sb["h3_prompt"] is None and sb["sound_h3"] == "" and sb["duration_source"] == "default"


def test_light_summary_drops_storyboard():
    s = {"id": "ep01-S1", "index": 1, "storyboard": {"img_prompt": "长"}, "duration": {"seconds": 8}}
    assert "storyboard" not in EF.light_shot(s)
