"""H3 FL2VA 提示词（SOP §9A）：构建器 ns_agent.h3_prompt、机检 ns_schema.h3_lint、导入 **H3提示词**、编译与画布 API。"""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ns_agent import compiler as C
from ns_agent import h3_prompt as H3
from ns_agent.importer.script_md import import_script
from ns_schema.edits import ShotEdit
from ns_schema.h3_lint import failed_rules, frames_for_seconds, lint_h3, lint_ok, parse_h3, sss
from ns_schema.script import DialogueLine, Episode, ScriptGlobals, Shot, Voiceover

FIX = Path(__file__).parent / "fixtures" / "h3"
EX1 = (FIX / "sop_9a2_example1.txt").read_text(encoding="utf-8").strip("\n")
EX2 = (FIX / "sop_9a2_example2.txt").read_text(encoding="utf-8").strip("\n")
LEGACY = (FIX / "ep01_S1_legacy_gpu3_video_prompt.txt").read_text(encoding="utf-8")


def _shot(**kw) -> Shot:
    base = dict(episode=1, index=1, source_line=1, motion_prompt="lnwan01，camera tilt up 缓慢上摇——她理了理刘海",
                motion_triggers=["lnwan01"], img_prompt="大堂", sound="高跟鞋声", duration=10)
    base.update(kw)
    return Shot(**base)


# ------------------------------------------------------------------ 帧数 / 对齐句

def test_frames_table_matches_sop_6():
    # SOP §6 对照表：秒（≤）→ 帧数
    table = {5.17: 124, 5.88: 141, 6.58: 158, 7.29: 175, 8.00: 192, 8.71: 209, 9.42: 226, 10.12: 243,
             10.83: 260, 11.54: 277, 12.25: 294, 12.96: 311, 13.67: 328, 14.38: 345, 15.08: 362}
    frames = list(table.values())
    for i, (sec, fr) in enumerate(table.items()):
        assert sss(fr) == f"{sec:.2f}"                      # 表里的“秒”= f"{帧数/24:.2f}"
        assert frames_for_seconds(fr / 24) == fr            # 恰好落在格点
        if i + 1 < len(frames):
            assert frames_for_seconds(fr / 24 + 0.01) == frames[i + 1]   # 超过一点就向上取下一格
    assert frames_for_seconds(3) == 124 and frames_for_seconds(10) == 243 and frames_for_seconds(8) == 192
    assert frames_for_seconds(15) == 362


# ------------------------------------------------------------------ 构建器

def test_builder_reproduces_sop_example_1_exactly():
    f = parse_h3(EX1)["fields"]
    body = f["integrated_multimodal_description"].removeprefix("[Shot 1] ")
    s = _shot(voiceover=Voiceover(note="镜1尾入", text="第一天实习。别出错，别被注意。"))
    d = H3.build(s, f["overall_soundscape"], body_en=body)
    assert d.text == EX1
    assert d.frames == 243 and d.missing == [] and d.source == "laptop"
    assert lint_ok(lint_h3(d.text, frames=d.frames, **H3.lint_inputs(s)))


def test_builder_fallback_keeps_structure_and_flags_a7():
    s = _shot(dialogue=[DialogueLine(speaker_note="顾沉低声", text="蓝头发，很大胆。"),
                        DialogueLine(speaker_note="她小声", text="染了三年了……总经理。"),
                        DialogueLine(speaker_note="顾沉，画外", text="进来。")],
              voiceover=Voiceover(note=None, text="他看我的方式，不像看一个实习生。"))
    d = H3.build(s, "电梯低鸣", names=("林晚", "顾沉"))
    p = parse_h3(d.text)
    assert p["layout_ok"] and p["align"].endswith("aligns with the 10.12-second mark of the target video.")
    body = p["fields"]["integrated_multimodal_description"]
    assert body.startswith("[Shot 1] camera tilt up") and "lnwan01" not in body
    # (S1)/(S2) 按首次开口；说话人说明在 <d> 外；<d> 里只有 [Chinese] + 逐字原文；同一人复用编号
    assert "顾沉低声 (S1) says: <d>[Chinese] 蓝头发，很大胆。</d>" in body
    assert "她小声 (S2) says: <d>[Chinese] 染了三年了……总经理。</d>" in body
    assert "(S1) says in an off-screen voiceover: <d>[Chinese] 进来。</d> The on-screen character's lips remain closed." in body
    assert "实习生" not in d.text                                    # 🎙 独白不进 H3（H3-D6）
    assert '"' not in d.text and "“" not in d.text                    # 不加引号
    assert p["fields"]["non_diegetic_music"] == "N/A" and d.missing == ["body", "soundscape"]
    res = {r["rule_id"]: r for r in lint_h3(d.text, frames=d.frames, **H3.lint_inputs(s))}
    assert not res["H3-A7"]["ok"] and "需要英文正文（剧本 v3 提供）" in res["H3-A7"]["detail"]
    for rid in ("H3-A1", "H3-A2", "H3-A3", "H3-D1", "H3-D2", "H3-D3", "H3-D4", "H3-D5", "H3-D6", "H3-S3", "P-B1"):
        assert res[rid]["ok"], res[rid]


def test_replace_field_only_touches_one_block():
    t = H3.replace_field(EX1, "overall_soundscape", "Soft rain taps on the glass.")
    p = parse_h3(t)
    assert p["layout_ok"] and p["fields"]["overall_soundscape"] == "Soft rain taps on the glass."
    assert p["fields"]["integrated_multimodal_description"] == parse_h3(EX1)["fields"]["integrated_multimodal_description"]
    assert p["align"] == parse_h3(EX1)["align"] and p["fields"]["non_diegetic_music"] == "N/A"


# ------------------------------------------------------------------ 机检

def test_lint_passes_sop_examples():
    r1 = lint_h3(EX1, frames=243, seconds=10, dialogue=[], monologue=["第一天实习。别出错，别被注意。"])
    assert lint_ok(r1) and all(r["ok"] for r in r1), [r for r in r1 if not r["ok"]]
    r2 = lint_h3(EX2, frames=243, seconds=10, dialogue=["蓝头发，很大胆。", "染了三年了……总经理。"])
    assert lint_ok(r2), [r for r in r2 if not r["ok"]]
    # 双人对白镜：H3-D7 只报 warn（待项目方定）；亲密镜则 block
    assert [r["rule_id"] for r in r2 if not r["ok"]] == ["H3-D7"]
    assert "H3-D7" in failed_rules(lint_h3(EX2, frames=243, intimate=True))
    for r in r1:
        assert set(r) >= {"rule_id", "sop_ref", "ok", "detail", "msg", "level"}


def test_lint_fails_legacy_ep01_s1_with_right_rules():
    res = lint_h3(LEGACY, frames=243, seconds=10)
    failed = set(failed_rules(res))
    assert {"H3-A1", "H3-A2", "H3-A3", "H3-A4", "H3-A5", "H3-A7", "H3-A8", "H3-S2", "H3-S3"} <= failed
    det = {r["rule_id"]: r["detail"] for r in res}
    assert "8K" in det["H3-A8"] and "f/1.4" in det["H3-A8"]            # 图像风格后缀
    assert "no" in det["H3-A5"] and "无" in det["H3-A5"]                # “No subtitles…”、“无字幕”


def test_lint_mechanical_rules():
    bad = EX1.replace("10.12-second", "10.00-second")
    assert "H3-A1" in failed_rules(lint_h3(bad, frames=243))
    assert "H3-A2" in failed_rules(lint_h3(EX1.replace("\n\nintegrated", "\nintegrated", 1)))
    assert "H3-A3" in failed_rules(lint_h3(EX1.replace("[Shot 1] ", "[Shot 1] (0-3s) ", 1)))
    assert "H3-A5" in failed_rules(lint_h3(EX1.replace("soft murmur", "soft murmur and without music")))
    assert "H3-A8" in failed_rules(lint_h3(EX1.replace("marble floor of", "marble floor, 85mm, Leica look, of")))
    assert "H3-D4" in failed_rules(lint_h3(EX2.replace("<d>[Chinese] 蓝头发，很大胆。</d>", "\"蓝头发，很大胆。\"")))
    assert "H3-D1" in failed_rules(lint_h3(EX2.replace("<d>[Chinese] 蓝头发", "<d>顾沉：蓝头发")))
    assert "H3-D2" in failed_rules(lint_h3(EX2.replace("(S1) says quietly", "says quietly")))
    assert "H3-D3" in failed_rules(lint_h3(EX2, dialogue=["蓝头发，很大胆！", "染了三年了……总经理。"]))
    assert "H3-S1" in failed_rules(lint_h3(EX1.replace("behind her.", "behind her. A. B. C. D.")))
    assert "H3-S3" in failed_rules(lint_h3(EX1.replace("non_diegetic_music: N/A", "non_diegetic_music: Slow piano.")))
    assert "P-B1" in failed_rules(lint_h3(EX1, frames=241), level="block")
    assert "P-B1" in failed_rules(lint_h3(EX1.replace("10.12", "8.71"), frames=209, seconds=8))   # 8 s → 192


# ------------------------------------------------------------------ 导入 **H3提示词**

V3_SCRIPT = """# 测试剧本 v3

**每条motion统一后缀**：`真人写实摄影，9:16竖屏`

## ep01《旋转门》

**剧情**：入职第一天。

**镜1｜img**：`清晨写字楼旋转门`

**motion**：`camera tilt up 缓慢上摇——她理了理刘海`

**时长**：10秒

**H3提示词**：
""" + EX1 + """

**sound**：`高跟鞋声；【H3 audio】Crisp heel clicks echo off the marble floor.`

**镜2｜img**：`电梯`

**motion**：`static camera`

**H3提示词**：
```text
""" + EX2 + """
```
**sound**：`电梯低鸣`
"""


def test_importer_reads_h3_prompt_verbatim(tmp_path):
    p = tmp_path / "v3.md"
    p.write_text(V3_SCRIPT, encoding="utf-8")
    sc = import_script(p)
    s1, s2 = sc.episodes[0].shots
    assert s1.h3_prompt == EX1 and s2.h3_prompt == EX2           # 多行、空行、破折号逐字；代码块围栏去掉
    assert s1.sound.startswith("高跟鞋声") and s1.sound_h3 == "Crisp heel clicks echo off the marble floor."
    assert s1.duration == 10 and s2.sound == "电梯低鸣"
    assert not sc.episodes[0].extras                                # 不再落到本集 extras


# ------------------------------------------------------------------ 编译 / apply_edit

def _ep(s: Shot) -> Episode:
    return Episode(number=1, title="t", shots=[s], source_line=1)


def test_compiler_video_prompt_is_h3_without_style_or_negative():
    s = _shot()
    g = ScriptGlobals(motion_suffix="真人写实摄影，8K，9:16竖屏")
    c = C.compile_shot(_ep(s), s, g, set())
    assert c.video_prompt.startswith("How the reference pictures align") and c.h3_prompt_source == "laptop"
    assert "8K" not in c.video_prompt and "9:16" not in c.video_prompt and c.video_negative not in c.video_prompt
    assert "8K" in c.legacy_video_prompt and c.h3_frames == 243
    # 剧本带 **H3提示词** → 原样使用
    s2 = _shot(h3_prompt=EX1)
    c2 = C.compile_shot(_ep(s2), s2, g, set())
    assert c2.video_prompt == EX1 and c2.h3_prompt_source == "script" and c2.h3_missing == []


def test_apply_edit_h3_body_and_soundscape():
    from ns_render import pipeline as P
    s = _shot(h3_prompt=EX1)
    c = C.compile_shot(_ep(s), s, ScriptGlobals(), set(), soundscape="Soft rain taps on the glass.")
    assert parse_h3(c.video_prompt)["fields"]["overall_soundscape"] == "Soft rain taps on the glass."
    new_body = parse_h3(EX1)["fields"]["integrated_multimodal_description"].replace("slow speed", "fast speed")
    out = P.apply_edit(c, ShotEdit(h3_body=new_body, camera="camera push in"))
    f = parse_h3(out.video_prompt)
    assert f["layout_ok"] and "fast speed" in f["fields"]["integrated_multimodal_description"]
    assert f["align"] == parse_h3(EX1)["align"] and f["fields"]["non_diegetic_music"] == "N/A"
    assert "camera push in" not in out.video_prompt and out.legacy_video_prompt.startswith("camera push in")


# ------------------------------------------------------------------ API：来源优先级 + lint + SOP 阻塞

@pytest.fixture()
def api(tmp_path, monkeypatch):
    from ns_api import app as app_mod
    from ns_api import readiness as RD
    from ns_render import pipeline as P
    from ns_schema.script import ScriptImport
    data = tmp_path / "data"
    (data / "renders").mkdir(parents=True)
    (data / "renders_gpu3").mkdir()
    s1 = _shot(index=1, h3_prompt=None)
    s2 = _shot(index=2, h3_prompt=EX1)
    sc = ScriptImport(sources=[], globals=ScriptGlobals(), episodes=[
        Episode(number=1, title="t", shots=[s1, s2], source_line=1)])
    monkeypatch.setattr(P, "DATA", data)
    monkeypatch.setattr(P, "RENDERS", data / "renders")
    monkeypatch.setattr(RD, "GPU3_ROOT", data / "renders_gpu3")
    monkeypatch.setattr(app_mod, "_script", sc)
    return TestClient(app_mod.app), data


def test_api_h3_sources_and_lint(api):
    c, data = api
    r = c.get("/api/shots/ep01-S1")
    assert r.status_code == 200, r.text
    d = r.json()
    sm = d["summary"]
    assert sm["h3_prompt_source"] == "laptop" and sm["h3_prompt_source_label"].startswith("笔记本草稿")
    assert sm["video_prompt"] == sm["h3_prompt"] == d["compiled"]["video_prompt"]
    assert "video_negative" not in d["compiled"] and d["compiled"]["legacy_video_prompt"]
    assert "H3-A7" in sm["h3_failed"] and not sm["h3_lint_ok"]
    assert {x["rule_id"] for x in sm["h3_lint"]} >= {"H3-A1", "H3-A2", "H3-S3", "P-B1"}
    assert sm["h3_blocks"]["music"] == "N/A"
    # 剧本 **H3提示词**
    sm2 = c.get("/api/shots/ep01-S2").json()["summary"]
    assert sm2["h3_prompt_source"] == "script" and sm2["h3_prompt"] == EX1 and sm2["h3_lint_ok"]
    # gpu3 同步回来的 compiled.json h3_prompt 优先；takes.json 视频版本的 prompt / sha 一并给出
    g = data / "renders_gpu3" / "ep01" / "S1"
    g.mkdir(parents=True)
    (g / "compiled.json").write_text(json.dumps({"h3_prompt": EX2, "video_prompt": "旧版"}), encoding="utf-8")
    (g / "takes.json").write_text(json.dumps({"takes": [{"stage": "video", "n": 3, "prompt": EX2, "frames": 243,
                                                         "file": "x.mp4", "created_at": "2026"}],
                                              "active": {"video": 3}}), encoding="utf-8")
    sm3 = c.get("/api/shots/ep01-S1").json()["summary"]
    assert sm3["h3_prompt_source"] == "gpu3" and sm3["h3_prompt"] == EX2 and not sm3["h3_editable"]
    assert sm3["h3_take"]["n"] == 3 and len(sm3["h3_take"]["prompt_sha256"]) == 64
    assert "H3-D3" in sm3["h3_failed"]          # 与剧本台词（本镜无对白）不一致
    # 剧本缺台词以外都对 → 用项目方原话豁免 H3-D3
    (g / "status.json").write_text(json.dumps({"audit": {"overrides": [
        {"rule_id": "H3-D3", "owner_quote": "这一镜按 gpu3 版本出", "by": "owner"}]}}, ensure_ascii=False),
        encoding="utf-8")
    sm4 = c.get("/api/shots/ep01-S1").json()["summary"]
    assert sm4["h3_lint_ok"] and sm4["h3_overrides"] == ["H3-D3"]


def test_sop_s4_blocker_for_failed_h3(monkeypatch):
    from ns_api import sop as SOP

    class Inp:
        tl_shots: dict = {}
        timeline = None

        def qa(self, n):
            return {"shots": {"S1": {"verdict": "pass"}}}

    s1 = {"blockers": []}
    kw = dict(shot_id="ep01-S1", ep=1, index=1, s1=s1, readiness=None, frames_owner="gpu3", has_first=True,
              has_last=True, has_video=True, gpu3_status=None, first_ep=1, g4_passed=True)
    monkeypatch.setattr(SOP, "s2_blockers", lambda inp, tl, ep: [])   # 本测试只看 S4
    st = SOP.shot_status(Inp(), **kw, h3_failed=["H3-A7", "H3-A4"], h3_source="laptop")
    b = st["stages"]["S4"]["blockers"]
    assert st["stage"] == "S4" and b[0]["code"] == "h3_lint" and b[0]["rule_ids"] == ["H3-A7", "H3-A4"]
    assert b[0]["text"].startswith("H3 提示词未通过 §9A")
    assert SOP.shot_status(Inp(), **kw, h3_failed=[])["stage"] == "S5"
