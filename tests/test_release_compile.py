"""封板 debug A 组（fredw-5c）：编译 / h3_prompt / frame_spec 的边界情况，补进单测。"""
from pathlib import Path

from ns_agent import bible as B
from ns_agent import compiler as C
from ns_agent import frame_spec as F
from ns_agent import h3_prompt as H
from ns_schema.h3_lint import frames_for_seconds
from ns_schema.script import CharacterLock, Episode, ScriptGlobals, Shot

FIX = Path(__file__).parent / "fixtures" / "t06_golden"
G = ScriptGlobals(image_suffix="85mm人像镜头f/1.2大光圈", character_locks=[CharacterLock(name="林晚", description="蓝发")])


def _shot(img, motion, idx=1, **kw):
    return Shot(episode=1, index=idx, img_prompt=img, img_triggers=[], motion_prompt=motion, motion_triggers=[],
                source_line=idx, **kw)


def test_boost_only_last_frame_keeps_first_frame_specs():
    """motion 没有可取的结束状态、只有导演加强时，尾帧照样生成并带首帧的规格词"""
    b = B.load_bible(root=FIX)
    patent = next(m.term for m in b.materials if "漆皮" in m.match)
    ep = Episode(number=1, title="t", source_line=1)
    s = _shot("极近特写，林晚穿黑色漆皮超短裙", "")
    c = C.compile_shot(ep, s, G, set(), bible=b, boost_last="尾帧加强")
    assert c.end_state == "" and c.last_prompt
    assert c.last_prompt.count("尾帧加强") == 1 and c.last_prompt.count(patent) == 1
    sp = F.build_spec(ep, s, G, available_triggers=None, bible=b, boost_last="尾帧加强")
    assert sp.model_prompt.qwen_last.count("尾帧加强") == 1


def test_script_na_music_not_replaced_by_episode_bgm():
    """owner_requirements §4 #4：剧本 **H3提示词** 明写 non_diegetic_music: N/A → 编译结果保持 N/A，不被本集 BGM 顶替"""
    b = B.load_bible(root=FIX)
    ep = Episode(number=1, title="t", source_line=1, music_bgm="Sparse piano, slow tempo, soft dynamics.")
    body = ("Live-action, cinematic, shallow depth of field, a medium shot begins in the position, framing and "
            "lighting established by Picture 1. She lifts her gaze slowly. She settles into the pose and "
            "composition established by Picture 2 at the end of the shot.")
    s = _shot("林晚站在窗边", "她抬眼——转身", duration=10, duration_source="script",
              h3_prompt=H.assemble(frames_for_seconds(10), body, "Quiet room tone.", "N/A"))
    c = C.compile_shot(ep, s, G, set(), bible=b)
    assert (c.video_music, c.video_music_source) == ("N/A", "script")
    s2 = _shot("林晚站在窗边", "她抬眼——转身", idx=2, duration=10, duration_source="script")
    c2 = C.compile_shot(ep, s2, G, set(), bible=b)
    assert c2.video_music_source in ("episode", "episode_invalid")


def test_red_episode_marks_every_shot_adult_by_default():
    b = B.load_bible(root=FIX)
    ep = Episode(number=1, title="t", source_line=1, high_intensity=True)
    shots = [_shot("林晚走进旋转门", "她抬眼——低头", idx=i) for i in (1, 2, 3)]
    assert all(C.compile_shot(ep, s, G, set(), bible=b).adult for s in shots)
    assert not C.compile_shot(Episode(number=2, title="t", source_line=1), shots[0], G, set(), bible=b).adult
