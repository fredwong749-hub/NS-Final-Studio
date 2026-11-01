"""H3 FL2VA 提示词（SOP §9A）：构建器 ns_agent.h3_prompt、机检 ns_schema.h3_lint、导入 **H3提示词**、编译与画布 API。"""
import hashlib
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
# DIRECTOR 11-02（总调度批复 r2 第 1 条，K-REN-801）：不变量 = H3 正文只有项目方覆盖、或带规则号的编译层运镜规范化能改。
# EX1N = 编译层规范化后的 EX1（“tilts up at slow speed” → “tilts up with small amplitude”）；除此之外逐字不变（test_h3_norm_only_change）
from ns_agent import camera_norm as _CN  # noqa: E402
_CN.enabled = lambda: True
EX1N, EX1_NORM = _CN.normalize_video_prompt(EX1)
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
    assert frames_for_seconds(3) == 107 and frames_for_seconds(4) == 107 and frames_for_seconds(10) == 243 and frames_for_seconds(8) == 192
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
    # (S1)/(S2) 按首次开口；<d> 里只有 [Chinese] + 逐字原文；同一人复用编号。
    # FIX（CHAIN F6，官方 §4.4）：<d> 外不再放剧本括号里的中文舞台提示（“顾沉低声 (S1)”过不了 H3-A7）；
    # 没给人物表 VOICE 时只写 “(Sx) says:”；F7：画外台词的嘴唇句紧跟 </d>，官方句式 “while … lips remain completely closed.”
    assert " (S1) says: <d>[Chinese] 蓝头发，很大胆。</d>" in body and "顾沉低声" not in body
    assert " (S2) says: <d>[Chinese] 染了三年了……总经理。</d>" in body and "她小声" not in body
    assert ("(S1) says in an off-screen voiceover: <d>[Chinese] 进来。</d> while the on-screen character's lips "
            "remain completely closed.") in body
    v = H3.build(s, "电梯低鸣", names=("林晚", "顾沉"), voices={"顾沉": "The on-screen adult man with a low, calm voice"})
    assert "The on-screen adult man with a low, calm voice (S1) says: <d>[Chinese] 蓝头发，很大胆。</d>" in v.text
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
    # 项目方 2026-10-30：普通对话镜每镜只让一个人说话 → 双人对白镜 H3-D7 也 block（官方示例 2 是双人，本项目不通过）
    assert not lint_ok(r2) and failed_rules(r2) == ["H3-D7"]
    # 另：gpu3 启发式 H3-D8 认为 (S2) 没写语速（warn，不拦截）
    assert [r["rule_id"] for r in r2 if not r["ok"] and r["level"] == "warn"] == ["H3-D8"]
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
    # H3-S3（项目方 2026-10-30 配乐进 H3）：英文 1–3 句通过；中文 / 空 阻断；情绪词、超过 3 句警告
    mus = lambda v: lint_h3(EX1.replace("non_diegetic_music: N/A", f"non_diegetic_music: {v}"))  # noqa: E731
    assert "H3-S3" not in failed_rules(mus("Sparse piano notes at a slow tempo, fading out."))
    assert "H3-S3" in failed_rules(mus("慢速钢琴"), level="block")
    assert "H3-S3" in failed_rules(mus("Sad romantic piano."), level="warn")
    assert "H3-S3" in failed_rules(mus("Piano. Bass. Drums. Strings."), level="warn")
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
    assert c2.video_prompt == EX1N and c2.h3_prompt_source == "script" and c2.h3_missing == []


def test_h3_only_changes_via_owner_override():
    from ns_render import pipeline as P
    from ns_schema.edits import H3PromptOverride
    s = _shot(h3_prompt=EX1)
    # 普通画布修改（环境声 / 旧 h3_body / 运镜）不进 H3，只进旧版拼接
    c = C.compile_shot(_ep(s), s, ScriptGlobals(), set(), soundscape="Soft rain taps on the glass.")
    assert c.video_prompt == EX1N and "Soft rain" in c.legacy_video_prompt
    out = P.apply_edit(c, ShotEdit(h3_body="whatever", camera="camera push in"))
    assert out.video_prompt == EX1N and out.legacy_video_prompt.startswith("camera push in")
    # 项目方覆盖（edits.json 嵌套格式 {text, by, at, base_sha, note}）：renderable 才替换；draft 只记录
    ov = H3.replace_field(EX1, "overall_soundscape", "Soft rain taps on the glass.")

    def edit(status):
        return ShotEdit(h3_prompt_override=H3PromptOverride(text=ov, at="t", note="好", status=status))
    c2 = P.apply_edit(C.compile_shot(_ep(s), s, ScriptGlobals(), set()), edit("renderable"))
    assert c2.video_prompt == ov and c2.h3_base_prompt == EX1N and c2.h3_override["note"] == "好"
    c3 = P.apply_edit(C.compile_shot(_ep(s), s, ScriptGlobals(), set()), edit("draft"))
    assert c3.video_prompt == EX1N and c3.h3_override["status"] == "draft"
    assert set(edit("draft").model_dump()["h3_prompt_override"]) >= {"text", "by", "at", "base_sha", "note"}


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
    assert sm2["h3_prompt_source"] == "script" and sm2["h3_prompt"] == EX1N and sm2["h3_lint_ok"]
    # gpu3 同步回来的 compiled.json h3_prompt 优先；takes.json 视频版本的 prompt / sha 一并给出
    g = data / "renders_gpu3" / "ep01" / "S1"
    g.mkdir(parents=True)
    (g / "compiled.json").write_text(json.dumps({"h3_prompt": EX2, "video_prompt": "旧版"}), encoding="utf-8")
    (g / "takes.json").write_text(json.dumps({"takes": [{"stage": "video", "n": 3, "prompt": EX2, "frames": 243,
                                                         "file": "x.mp4", "created_at": "2026"}],
                                              "active": {"video": 3}}), encoding="utf-8")
    sm3 = c.get("/api/shots/ep01-S1").json()["summary"]
    assert sm3["h3_prompt_source"] == "gpu3" and sm3["h3_prompt"] == EX2
    assert sm3["h3_edit_base"]["body"].startswith("[Shot 1] camera tilt up")   # 项目方修改的起点 = 笔记本草稿，不是 gpu3
    assert sm3["h3_take"]["n"] == 3 and len(sm3["h3_take"]["prompt_sha256"]) == 64
    assert "H3-D3" in sm3["h3_failed"]          # 与剧本台词（本镜无对白）不一致
    # 剧本缺台词以外都对 → 用项目方原话豁免 H3-D3
    # EX2 是官方双人示例：项目方 2026-10-30 起普通对话镜只许一人说话 → H3-D7 也 block，这里一并豁免
    assert "H3-D7" in sm3["h3_failed"]
    (g / "status.json").write_text(json.dumps({"audit": {"overrides": [
        {"rule_id": "H3-D3", "owner_quote": "这一镜按 gpu3 版本出", "by": "owner"},
        {"rule_id": "H3-D7", "owner_quote": "这一镜按 gpu3 版本出", "by": "owner"}]}}, ensure_ascii=False),
        encoding="utf-8")
    sm4 = c.get("/api/shots/ep01-S1").json()["summary"]
    assert sm4["h3_lint_ok"] and sm4["h3_overrides"] == ["H3-D3", "H3-D7"]


class FakeBridge:
    """假 gpu3 桥：按 docs/canvas.md §7.6 的契约回包；down=True 模拟隧道没开，stale=True 模拟 409"""

    def __init__(self):
        self.calls, self.down, self.stale, self.video_ok = [], False, False, False

    def __call__(self, method, url, body=None, timeout=None):
        from ns_api import gpu3_bridge as GB
        self.calls.append((method, url, body))
        if self.down:
            raise GB.BridgeError("gpu3 桥不可达（test）")
        if url.endswith("/h3_edit"):
            if body.get("by") != "owner":
                raise GB.BridgeError("gpu3 桥返回 403", 403)
            if self.stale:
                raise GB.BridgeError("gpu3 桥返回 409：stale base_sha", 409, {"detail": "stale base_sha"})
            return {"shot": "ep01-S2", "saved": {"text": body["text"], "sha256": hashlib.sha256(body["text"].encode()).hexdigest(),
                                                 "by": "owner", "at": "t", "base_sha": body["base_sha"]},
                    "lint": {"ok": True, "failed": [], "warnings": [], "frames": 243, "intimate": False, "results": []},
                    "rendered": False}
        if url.endswith("/override"):
            return {"shot": "ep01-S2", "request": body, "requests": [body]}
        if method == "GET":
            return {"video_gate": {"verdict": "pass" if self.video_ok else "fail", "prompt_sha": "a",
                                   "effective_sha256": "a" if self.video_ok else "b", "blocked": None,
                                   "video_ok": self.video_ok}}
        raise AssertionError(url)


@pytest.fixture()
def bridge(monkeypatch):
    from ns_api import gpu3_bridge as GB
    fb = FakeBridge()
    monkeypatch.setattr(GB, "_call", fb)
    return fb


def test_api_owner_override(api, bridge, monkeypatch):
    from ns_api import app as app_mod
    from ns_render import pipeline as P
    c, data = api
    url = "/api/shots/ep01-S2/h3-override"
    soft = "Soft rain taps on the glass behind her."
    shown = c.get("/api/shots/ep01-S2").json()["summary"]["h3_prompt_sha256"]
    assert shown == hashlib.sha256(EX1N.encode("utf-8")).hexdigest()       # sha256(UTF-8 原文)
    # 只接受项目方本人 + 非空确认原话
    assert c.put(url, json={"soundscape": soft, "note": "好", "by": "agent"}).status_code == 403
    assert c.put(url, json={"soundscape": soft, "note": "  ", "by": "owner"}).status_code == 400
    assert P.load_edit("ep01-S2").h3_prompt_override is None and not bridge.calls
    # 边写边检（只读）
    lp = c.post("/api/shots/ep01-S2/h3-lint", json={"soundscape": soft}).json()
    assert lp["ok"] and parse_h3(lp["text"])["fields"]["overall_soundscape"] == soft
    assert all(r["rule_href"].startswith("/api/docs/rule_ids#") for r in lp["lint"])
    # 通过 lint → renderable，并按契约送到 gpu3（{text, by:"owner", base_sha}；note 不发）
    r = c.put(url, json={"soundscape": soft, "note": "环境声改成雨声", "by": "owner", "base_sha": shown})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "renderable" and r.json()["delivered"] is True
    m, u, b = bridge.calls[-1]
    assert m == "POST" and "/api/gpu3/projects/" in u and u.endswith("/shots/ep01-S2/h3_edit")
    assert set(b) == {"text", "by", "base_sha"} and b["by"] == "owner" and b["base_sha"] == shown
    e = P.load_edit("ep01-S2")
    ov = e.h3_prompt_override
    assert ov.status == "renderable" and ov.by == "owner" and ov.note == "环境声改成雨声" and ov.base_sha == shown
    assert ov.script_sha == hashlib.sha256(EX1.encode()).hexdigest() and ov.delivery.ok
    assert parse_h3(ov.text)["fields"]["overall_soundscape"] == soft and parse_h3(ov.text)["align"] == parse_h3(EX1)["align"]
    raw = json.loads((P.shot_dir("ep01-S2") / "edits.json").read_text(encoding="utf-8"))
    assert set(raw["h3_prompt_override"]) >= {"text", "by", "at", "base_sha", "note"}
    sm = c.get("/api/shots/ep01-S2").json()["summary"]
    assert sm["h3_prompt_source"] == "owner_edit" and sm["h3_prompt_source_label"] == "剧本＋画布修改"
    assert sm["h3_prompt"] == ov.text and sm["h3_lint_ok"] and not sm["h3_override_stale"]
    assert sm["h3_override"]["delivered"] and "text" not in sm["h3_override"]
    # 普通 PUT /edit 不能改也不会清掉覆盖 / 豁免请求
    body = {**e.model_dump(), "h3_prompt_override": {"text": "x", "at": "t", "note": "n"}, "note": "n"}
    assert c.put("/api/shots/ep01-S2/edit", json=body).status_code == 200
    assert P.load_edit("ep01-S2").h3_prompt_override.text == ov.text
    # 桥不可达 → 仍存本地，标「未送达」；重试成功后送达
    bridge.down = True
    r = c.put(url, json={"body": "她理了理刘海。", "note": "试一下", "by": "owner", "base_sha": shown})
    assert r.json()["status"] == "draft" and "H3-A7" in r.json()["failed"] and r.json()["delivered"] is False
    sm = c.get("/api/shots/ep01-S2").json()["summary"]
    assert "草稿" in sm["h3_prompt_source_label"] and not sm["h3_lint_ok"] and not sm["h3_override"]["delivered"]
    assert c.post("/api/shots/ep01-S2/gpu3-resend", json={"what": "h3_edit", "by": "agent"}).status_code == 403
    bridge.down = False
    assert c.post("/api/shots/ep01-S2/gpu3-resend", json={"what": "h3_edit", "by": "owner"}).json()["delivered"]
    # gpu3 侧已变 → 409 stale
    bridge.stale = True
    d = c.put(url, json={"soundscape": soft, "note": "再改", "by": "owner", "base_sha": "old"}).json()["delivery"]
    assert d["ok"] is False and d["code"] == 409
    bridge.stale = False
    # 剧本 **H3提示词** 更新 → stale + SOP「待你决定」
    sc = app_mod._script.model_copy(deep=True)
    sc.episodes[0].shots[1].h3_prompt = EX1.replace("slow speed", "fast speed")
    monkeypatch.setattr(app_mod, "_script", sc)
    sm = c.get("/api/shots/ep01-S2").json()["summary"]
    assert sm["h3_override_stale"] and "剧本已更新" in sm["h3_prompt_source_label"]
    from ns_api import sop as SOP
    acts = SOP.h3_override_actions([{"id": "ep01-S2", "episode": 1, "h3_override_stale": True}])
    assert acts[0]["title"] == "剧本 H3 提示词已更新，请重新确认画布修改" and acts[0]["shots"] == ["ep01-S2"]
    # 撤销（只在笔记本）
    r = c.put(url, json={"clear": True, "note": "撤销", "by": "owner"})
    assert r.status_code == 200 and "gpu3" in r.json()["warning"]
    assert P.load_edit("ep01-S2").h3_prompt_override is None


def test_audit_panel_override_requests_and_video_gate(api, bridge):
    from ns_render import pipeline as P
    c, data = api
    g = data / "renders_gpu3" / "ep01" / "S2"
    g.mkdir(parents=True)
    sha = hashlib.sha256(EX1.encode("utf-8")).hexdigest()
    (g / "status.json").write_text(json.dumps({"audit": {
        "verdict": "fail", "failures": [{"rule_id": "S1-W7", "sop_ref": "§6 #7", "detail": "x"}],
        "warnings": [], "not_checked": {"H3-A6": "待定"}, "overrides": [],
        "invalid_overrides": [{"rule_id": "H3-A1", "reason": "不可豁免"}], "prompt_sha": sha}}), encoding="utf-8")
    sm = c.get("/api/shots/ep01-S2").json()["summary"]
    au = sm["gpu3_audit"]
    assert au["verdict"] == "fail" and au["failures"][0]["rule_href"] == "/api/docs/rule_ids#S1-W7"
    assert au["failures"][0]["sop_href"] == "/api/docs/SOP_production#sec-6"
    assert au["not_checked"] == {"H3-A6": "待定"} and au["invalid_overrides"][0]["reason"] == "不可豁免"
    assert sm["video_gate"]["ok"] is False and sm["video_gate"]["audit_prompt_sha"] == sha
    # 出视频：以 gpu3 video_gate.video_ok 为准（服务端 409）
    r = c.post("/api/shots/ep01-S2/gpu3-rerender", json={"stage": "video"})
    assert r.status_code == 409 and "出视频闸门" in r.json()["detail"]
    assert c.get("/api/shots/ep01-S2/gpu3-state").json()["shot"]["video_gate"]["video_ok"] is False
    bridge.down = True
    assert c.post("/api/shots/ep01-S2/render", json={"stage": "video"}).status_code == 409
    assert c.get("/api/shots/ep01-S2/gpu3-state").json()["reachable"] is False
    bridge.down = False
    # 审计豁免请求：只接受项目方原话，存本地 + 按契约发到 gpu3（{rule_id, owner_quote, by}）
    u = "/api/shots/ep01-S2/audit-override"
    assert c.put(u, json={"rule_id": "S1-W7", "owner_quote": "可以", "by": "agent"}).status_code == 403
    # UIRSI 2026-10-31：身份来自登录会话；不是项目方（by≠owner）→ 403（以前测“缺原话 400”，现在登录即本人、不要原话）
    assert c.put(u, json={"rule_id": "S1-W7", "owner_quote": "", "by": "agent"}).status_code == 403
    r = c.put(u, json={"rule_id": "S1-W7", "owner_quote": "这一镜说话人描述按现状出", "by": "owner"})
    assert r.status_code == 200 and r.json()["delivered"]
    assert bridge.calls[-1][2] == {"rule_id": "S1-W7", "owner_quote": "这一镜说话人描述按现状出", "by": "owner"}
    reqs = P.load_edit("ep01-S2").audit_override_requests
    assert len(reqs) == 1 and reqs[0].by == "owner" and reqs[0].delivery.ok
    assert c.get("/api/shots/ep01-S2").json()["summary"]["audit_override_requests"][0]["rule_id"] == "S1-W7"
    assert not (g / "status.json").read_text(encoding="utf-8").count("这一镜")     # 从不写 gpu3 的 status.json


def test_docs_served_with_anchors(api):
    c, _ = api
    r = c.get("/api/docs/rule_ids")
    assert r.status_code == 200 and 'id="H3-A1"' in r.text and 'id="P-B1"' in r.text
    s = c.get("/api/docs/SOP_production").text
    assert 'id="sec-9A.1"' in s and 'id="sec-6"' in s
    assert c.get("/api/docs/secrets").status_code == 404


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


def test_sop_s4_video_lora_warn_not_blocker(monkeypatch):
    """R-C4（总调度 2026-10-30）：视频 LoRA 未 accepted 只在 S4 warnings 提醒，不拦、passed 不变"""
    from ns_api import sop as SOP

    class Inp:
        tl_shots = {"ep01-S1": {"required_loras": [{"trigger": "lnwan01", "kind": "video", "registry_status": "training"},
                                                   {"trigger": "lnwan_qi", "kind": "image", "registry_status": "accepted"}]}}
        timeline = None

        def qa(self, n):
            return {"shots": {"S1": {"verdict": "pass"}}}

    monkeypatch.setattr(SOP, "s2_blockers", lambda inp, tl, ep: [])
    st = SOP.shot_status(Inp(), shot_id="ep01-S1", ep=1, index=1, s1={"blockers": []}, readiness=None,
                         frames_owner="gpu3", has_first=True, has_last=True, has_video=True, gpu3_status=None,
                         first_ep=1, g4_passed=True, h3_failed=[])
    s4 = st["stages"]["S4"]
    assert st["stage"] == "S5" and s4["passed"] and s4["blockers"] == []
    assert [w["trigger"] for w in s4["warnings"]] == ["lnwan01"]
    assert s4["warnings"][0]["text"] == "视频 LoRA lnwan01 未验收：视频照常出，accepted 后更好"


# ------------------------------------------------------------------ gpu3 合并的启发式规则（warn）

def _rule(res, rid):
    return next(r for r in res if r["rule_id"] == rid)


def test_extra_rules_present_as_warn_with_exact_ids():
    res = lint_h3(EX1, frames=243)
    for rid in ("H3-A6", "H3-A9", "H3-A10", "H3-D8", "H3-D9"):
        r = _rule(res, rid)
        assert r["level"] == "warn" and r["ok"], r          # 官方示例 1 全部通过
    assert lint_ok(lint_h3(EX1.replace("lifts one hand", "secretly hopes and lifts one hand"), frames=243))  # warn 不影响 pass


def test_extra_rule_a6_static_description():
    from ns_schema.h3_lint import lint_h3_extra
    bad = EX1.replace("The camera tilts up", "The room is bright. The walls are white. The camera tilts up")
    assert not _rule(lint_h3_extra(bad), "H3-A6")["ok"]
    assert _rule(lint_h3_extra(EX1), "H3-A6")["ok"]
    # 与首帧描述 3-gram 大量重合
    frame = "a pair of clear 12 cm needle heels stepping onto the reflective marble floor of an office lobby"
    assert not _rule(lint_h3_extra(EX1, frame_texts=[frame]), "H3-A6")["ok"]


def test_extra_rule_a9_abstract_words():
    assert not _rule(lint_h3(EX1.replace("lifts one hand", "feels nervous because she remembers him and lifts one hand")), "H3-A9")["ok"]
    assert _rule(lint_h3(EX1), "H3-A9")["ok"]


def test_extra_rule_a10_camera_moves():
    two = EX1.replace("The camera tilts up at slow speed", "The camera tilts up at slow speed and then pans left")
    assert not _rule(lint_h3(two), "H3-A10")["ok"]
    loose = EX1.replace("The camera tilts up at slow speed", "The camera slowly tilts up")
    assert not _rule(lint_h3(loose), "H3-A10")["ok"]
    assert _rule(lint_h3(EX1), "H3-A10")["ok"]


def test_extra_rule_d8_speaker_intro():
    bad = EX2.replace("The on-screen middle-aged man with a low, calm, unhurried voice (S1)", "He (S1)")
    assert not _rule(lint_h3(bad), "H3-D8")["ok"]
    ok = EX2.replace("The on-screen young woman with a soft, small, slightly nervous voice (S2)",
                     "The on-screen young woman with a soft, small, slightly nervous voice and a slow pace (S2)")
    assert _rule(lint_h3(ok), "H3-D8")["ok"]


def test_extra_rule_d9_cutoff_scenetrans():
    from ns_schema.h3_lint import lint_h3_extra
    line = "染了三年了……总经理。"
    assert not _rule(lint_h3_extra(EX2, cutoff=[line]), "H3-D9")["ok"]
    cut = EX2.replace(f"<d>[Chinese] {line}</d>", f"<d>[Chinese] {line}</d><cutoff>")
    assert _rule(lint_h3_extra(cut, cutoff=[line]), "H3-D9")["ok"]
    assert not _rule(lint_h3_extra(cut), "H3-D9")["ok"]          # 剧本没标却用了 <cutoff>
    assert _rule(lint_h3_extra(EX2), "H3-D9")["ok"]


def test_rule_explain_bridge_then_local(api, monkeypatch):
    from ns_api import gpu3_bridge as GB
    c, _ = api
    # 桥不可达（tests/conftest.py 默认）→ 本地 rule_ids.md + SOP 行
    r = c.get("/api/rules/H3-A5/explain").json()
    assert r["source"] == "local" and r["level"] == "block" and r["rule_href"] == "/api/docs/rule_ids#H3-A5"
    assert r["sop_lines"] and all("H3-A5" in x["text"] for x in r["sop_lines"])
    assert c.get("/api/rules/NOPE-X1/explain").status_code == 404
    assert c.get("/api/rules/bad id/explain").status_code == 404
    # 桥可达 → 原样透出 shot_audit --explain
    seen = []

    def fake(method, url, body=None, timeout=None):
        seen.append(url)
        return {"found": True, "rule_id": "H3-A5", "rule": "r", "check": "c", "level": "block", "sop_ref": "§9A.1 #8",
                "sop_lines": [], "example_pass": "p", "example_fail": "f", "rules_sha": "x", "cached": False}
    monkeypatch.setattr(GB, "_call", fake)
    r = c.get("/api/rules/H3-A5/explain").json()
    assert r["source"] == "gpu3" and r["example_fail"] == "f" and seen[-1].endswith("/api/gpu3/rules/H3-A5")
    assert r["sop_href"] == "/api/docs/SOP_production#sec-9A.1"


def test_h3_norm_only_change():
    """K-REN-801：编译后的 H3 正文 = 剧本原文 + 仅限 h3_norm 记录的规范化（每条带规则号）；倒回规范化必须逐字等于原文"""
    s = _shot(h3_prompt=EX1)
    c = C.compile_shot(_ep(s), s, ScriptGlobals(), set())
    assert c.h3_norm and all(x["rule"] == "K-REN-801" for x in c.h3_norm)
    assert _CN.denormalize(c.video_prompt, c.h3_norm) == EX1
    s2 = _shot(h3_prompt=EX2)
    c2 = C.compile_shot(_ep(s2), s2, ScriptGlobals(), set())
    assert _CN.denormalize(c2.video_prompt, c2.h3_norm) == EX2
