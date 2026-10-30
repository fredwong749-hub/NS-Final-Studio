"""tools/validate_qwen_script.py：合成占位剧本（格式占位，不是剧情文本）"""
import importlib.util
from pathlib import Path

import pytest

from ns_schema.h3_lint import alignment_line, frames_for_seconds

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("validate_qwen_script", ROOT / "tools" / "validate_qwen_script.py")
V = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(V)

SOUNDSCAPE = "Placeholder room tone hums steadily. Placeholder footsteps tap twice on the floor."
LINE = "占位台词一。"


def h3(seconds=10, music="N/A", d_block=f"<d>[Chinese] {LINE}</d>", align_seconds=None):
    align = alignment_line(frames_for_seconds(align_seconds or seconds))
    body = ("[Shot 1] Live-action, cinematic, shallow depth of field, a medium shot begins in the position, framing "
            "and lighting established by Picture 1. The on-screen young woman with a soft voice, speaking at a slow "
            f"pace (S1) says: {d_block} The subject settles into the pose and composition established by Picture 2 "
            "at the end of the shot.")
    return (f"{align}\n\nintegrated_multimodal_description: {body}\n\noverall_soundscape: {SOUNDSCAPE}"
            f"\n\nnon_diegetic_music: {music}")


def shot(i, seconds=10, music="N/A", dialogue=f"（林晚）“{LINE}”", h3_text=None, with_h3=True, with_dur=True):
    parts = [f"**镜{i}｜img**：`中景，占位画面{i}`",
             f"**motion**：`lnwan01，camera push in 缓慢推近，占位动作，眼神占位——占位结束状态`"]
    if with_dur:
        parts.append(f"**时长**：{seconds}秒")
    parts.append(f"**sound**：占位声音；【配乐】延续，强度1；【H3 audio】{SOUNDSCAPE}")
    if dialogue:
        parts.append(f"**对白**：{dialogue}")
    if with_h3:
        parts.append("**H3提示词**：\n```text\n" + (h3_text or h3(seconds, music)) + "\n```")
    return "\n\n".join(parts)


def episode(shots=None):
    shots = shots or [shot(i) for i in range(1, 7)]
    head = ("## ep01《占位标题》\n\n**剧情**：占位剧情。\n\n"
            "**配乐**：占位配乐说明；【BGM】Placeholder BGM prompt with soft piano.\n\n")
    return head + "\n\n".join(shots) + "\n\n---\n"


def run(tmp_path, text, **kw):
    p = tmp_path / "ep.md"
    p.write_text(text, encoding="utf-8")
    return V.validate(p, **kw)


def ids(rep, shot_id=None):
    out = []
    for ep in rep["episodes"]:
        if shot_id is None:
            out += [i["rule_id"] for i in ep["issues"] if i["level"] == "block"]
        for s in ep["shots"]:
            if shot_id in (None, s["id"]):
                out += [i["rule_id"] for i in s["issues"] if i["level"] == "block"]
    return out


def test_pass(tmp_path):
    rep = run(tmp_path, episode())
    assert rep["episodes_found"] == 1
    assert rep["blocking"] == 0, ids(rep)
    assert all(s["ok"] and not s["repair"] for s in rep["episodes"][0]["shots"])


def test_cli_exit_codes(tmp_path):
    p = tmp_path / "ok.md"
    p.write_text(episode(), encoding="utf-8")
    assert V.main([str(p), "--json"]) == 0
    bad = tmp_path / "bad.md"
    bad.write_text(episode([shot(1, with_h3=False)] + [shot(i) for i in range(2, 7)]), encoding="utf-8")
    assert V.main([str(bad)]) == 1
    empty = tmp_path / "empty.md"
    empty.write_text("# nothing\n", encoding="utf-8")
    assert V.main([str(empty)]) == 2


def test_missing_fields(tmp_path):
    shots = [shot(1, with_dur=False), shot(2, with_h3=False)] + [shot(i) for i in range(3, 7)]
    rep = run(tmp_path, episode(shots))
    assert "S1-W2" in ids(rep, "ep01-S1")
    assert "S1-W7" in ids(rep, "ep01-S2")
    assert ids(rep, "ep01-S3") == []


def test_missing_bgm_and_cue(tmp_path):
    text = episode().replace("**配乐**：占位配乐说明；【BGM】Placeholder BGM prompt with soft piano.\n\n", "")
    text = text.replace("【配乐】延续，强度1；", "", 1)
    rep = run(tmp_path, text)
    head = [i["rule_id"] for i in rep["episodes"][0]["issues"]]
    assert "R-C1" in head
    assert "R-C1" in ids(rep, "ep01-S1")


def test_bad_dialogue_format(tmp_path):
    shots = [shot(1, h3_text=h3(d_block=f"<d>{LINE}</d>")),           # 缺 [Chinese]
             shot(2, dialogue=f"“{LINE}”")]                            # 剧本台词缺（说话人）
    shots += [shot(i) for i in range(3, 7)]
    rep = run(tmp_path, episode(shots))
    assert "H3-D1" in ids(rep, "ep01-S1")
    assert "S1-W4" in ids(rep, "ep01-S2")


def test_dialogue_not_verbatim(tmp_path):
    shots = [shot(1, dialogue="（林晚）“占位台词二。”")] + [shot(i) for i in range(2, 7)]
    rep = run(tmp_path, episode(shots))
    assert "H3-D3" in ids(rep, "ep01-S1")


def test_bad_frame_count(tmp_path):
    # 时长 8 秒（192 帧 → 8.00）但对齐句写成 10 秒（10.12）
    shots = [shot(1, seconds=8, h3_text=h3(seconds=8, align_seconds=10))] + [shot(i) for i in range(2, 7)]
    rep = run(tmp_path, episode(shots))
    s1 = rep["episodes"][0]["shots"][0]
    assert s1["frames"] == 192
    assert "H3-A1" in ids(rep, "ep01-S1")


@pytest.mark.parametrize("music,ok", [
    ("N/A", True),
    ("Sparse placeholder piano notes at a slow tempo. Low strings gradually increase in volume.", True),
    ("A romantic placeholder piano melody at a slow tempo.", False),          # 抽象情绪词
    ("占位钢琴。", False),                                                    # 中文
    ("Piano at a slow tempo. Strings enter. Drums enter. Volume fades.", False),   # 4 句
    ("", False),
])
def test_music_rule(tmp_path, music, ok):
    shots = [shot(1, music=music)] + [shot(i) for i in range(2, 7)]
    rep = run(tmp_path, episode(shots))
    got = ids(rep, "ep01-S1")
    assert ("H3-S3" not in got) is ok, got
    if ok:
        assert got == []


def test_repair_request_is_format_only(tmp_path):
    shots = [shot(1, seconds=8, h3_text=h3(seconds=8, align_seconds=10))] + [shot(i) for i in range(2, 7)]
    rep = run(tmp_path, episode(shots))
    text = rep["episodes"][0]["shots"][0]["repair"]
    assert "[H3-A1|block]" in text and "只修正格式" in text and "镜1" in text
    assert rep["episodes"][0]["shots"][1]["repair"] == ""


def test_trigger_in_h3(tmp_path):
    bad = h3().replace("a medium shot", "lnwan01 in a medium shot")
    shots = [shot(1, h3_text=bad)] + [shot(i) for i in range(2, 7)]
    rep = run(tmp_path, episode(shots))
    assert "H3-D4" in ids(rep, "ep01-S1")
