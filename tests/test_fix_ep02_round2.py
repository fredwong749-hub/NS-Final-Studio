"""FIX 第二轮：CHAIN F2–F7（H3 官方规范一致性）、开场第一刀 ≤3 s、出图身份 LoRA 按“在画”挂。纯 CPU。"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in ("packages/schema", "services/agent", "services/render_router", "services/api", "services/post"):
    sys.path.insert(0, str(ROOT / p))

from ns_schema import h3_lint as L  # noqa: E402

I2V = (L.I2V_ALIGN_LINE + "\n\nintegrated_multimodal_description: [Shot 1] Live-action, cinematic, shallow depth of "
       "field, a static close-up begins in the position, framing and lighting established by <Picture 1>, focusing "
       "on the young East Asian woman. The adult man (S1) says: <d>[Chinese] 方案第三页。</d> She swallows and looks "
       "down at the keyboard.\n\noverall_soundscape: The low hum of office electronics fills the room.\n\n"
       "non_diegetic_music: Sparse piano single notes with a slow tempo.")


# ---------------- F2：I2VA 模式

def test_i2va_mode_accepts_official_line_and_rejects_picture2():
    res = L.lint_h3(I2V, 158, mode="i2va")
    assert L.failed_rules(res) == [], [r for r in res if not r["ok"] and r["level"] == "block"]
    bad = I2V.replace("down at the keyboard.", "down, and settles into the pose established by Picture 2 at the end "
                                                "of the shot.")
    assert "H3-A4" in L.failed_rules(L.lint_h3(bad, 158, mode="i2va"))
    assert "H3-A1" in L.failed_rules(L.lint_h3(I2V, 158))          # 默认 FL2VA 模式不认 I2VA 指令行
    with pytest.raises(ValueError):
        L.lint_h3(I2V, 158, mode="t2v")


def test_ep02_latest_i2va_prompts_pass_blocks():
    from ns_render import h3_video as HV
    n = 0
    for i in range(1, 12):
        tj = ROOT / "data" / "renders" / "ep02" / f"S{i}" / "takes.json"
        if not tj.is_file():
            continue
        # 只看 FL2VA / I2VA 结构的版本（配方引擎出的 Ref2VA 版本里 <Picture 2> 是参考图，另有规则）
        # G24（CODE-RSI 11-01）：data/renders/ep02 现在是 series10 的 ep02；VIDEO10 登记的配方引擎片（workflow=video10，
        # 如 i2va_pdd2）开头也是 I2V 对齐句，但正文按 ns_recipes.lint 校验、不走 h3_video.submit_lint，不属于本测试范围
        v = [x for x in json.loads(tj.read_text(encoding="utf-8"))["takes"] if x["stage"] == "video"
             and x.get("workflow") != "video10"
             and (x.get("prompt") or "").startswith((L.ALIGN_PREFIX, L.I2V_ALIGN_LINE))]
        if not v or not v[-1].get("frames"):
            continue
        fr = v[-1]["frames"]
        p = HV.final_prompt(v[-1]["prompt"], fr, use_last=False)[0]
        assert "Picture 2" not in p and HV.submit_lint(p, fr, use_last=False)[0] == [], f"S{i}"
        n += 1
    if n == 0:
        pytest.skip("没有 ep02 数据")


# ---------------- F3：提交前 lint

def test_submit_lint_blocks_and_render_gate():
    from ns_render import h3_video as HV
    assert HV.submit_lint(I2V, 158, use_last=False) == ([], [])
    failed, why = HV.submit_lint(I2V.replace("keyboard.", "keyboard established by Picture 2."), 158, use_last=False)
    assert "H3-A4" in failed and why
    assert HV.submit_lint("自由文本，旧链路", 158, use_last=False) == ([], [])   # 不是 H3 结构：不查
    assert "owner_edit" in HV.LINT_EXEMPT_SOURCES
    e = HV.PromptLintBlocked(["H3-A4"], ["x"])
    assert "H3-A4" in str(e)


# ---------------- F4：可见文字引号放行，台词引号仍拦

def test_d4_visible_text_quotes_allowed():
    vis = I2V.replace("She swallows", 'A red neon sign reading "营业中" glows behind her. She swallows')
    res = {r["rule_id"]: r for r in L.lint_h3(vis, 158, mode="i2va")}
    assert res["H3-D4"]["ok"]
    for bad in (I2V.replace("<d>[Chinese] 方案第三页。</d>", '"<d>[Chinese] 方案第三页。</d>"'),
                I2V.replace("<d>[Chinese] 方案第三页。</d>", '<d>[Chinese] "方案第三页。"</d>'),
                I2V.replace("says: <d>[Chinese] 方案第三页。</d>", 'says quietly: "方案第三页。"')):
        assert not {r["rule_id"]: r for r in L.lint_h3(bad, 158, mode="i2va")}["H3-D4"]["ok"], bad


# ---------------- F5：配乐“作用”写法报 warn

def test_music_function_words_warn_only():
    m = I2V.replace("Sparse piano single notes with a slow tempo.",
                    "Sparse piano single notes with a slow tempo, providing a restrained background layer.")
    res = {r["rule_id"]: r for r in L.lint_h3(m, 158, mode="i2va")}
    assert not res["H3-S3"]["ok"] and res["H3-S3"]["level"] == "warn"
    from ns_agent import h3_prompt as H3
    assert H3.music_warnings("Sparse piano, providing a sustained background layer.")
    assert H3.music_warnings("Sparse piano single notes with a slow tempo.") == []
    assert H3.music_warnings("N/A") == []


# ---------------- F6 / F7：兜底构建器

def test_builder_no_chinese_stage_note_and_official_lips_sentence():
    from ns_agent import h3_prompt as H3
    d = [{"speaker_note": "她慌", "text": "对不起。"}, {"speaker_note": "顾沉，画外", "text": "进来。"}]
    out, ids, off = H3.dialogue_sentences(d, ("林晚", "顾沉"))
    assert out[0] == "(S1) says: <d>[Chinese] 对不起。</d>"
    assert out[1].endswith("</d> while the on-screen character's lips remain completely closed.")
    out, _, _ = H3.dialogue_sentences(d, ("林晚", "顾沉"), voices={"她": "The young woman with a soft voice"},
                                      on_screen_pronoun="her")
    assert out[0].startswith("The young woman with a soft voice (S1) says:")
    assert out[1].endswith("</d> while her lips remain completely closed.")
    out, _, _ = H3.dialogue_sentences(d[:1], (), voices={"她": "中文声线"})       # 中文 VOICE 不放 <d> 外
    assert out[0] == "(S1) says: <d>[Chinese] 对不起。</d>"


# ---------------- 开场第一刀 ≤3 s

def test_opening_first_cut():
    from ns_post import assemble as A
    ps = A.opening_pieces([(0.0, 8.0, 1.0)], first_cut_s=3.0, min_piece_s=1.0, zoom=1.15)
    assert ps == [(0.0, 3.0, 1.0), (3.0, 8.0, 1.15)]
    ps = A.opening_pieces([(0.0, 8.0, 1.0)], first_cut_s=3.0, min_piece_s=1.0, zoom=1.15, busy=[(2.0, 4.0)])
    assert ps[0] == (0.0, 2.0, 1.0)                          # 切点落在台词里 → 提前到句前
    ps = A.opening_pieces([(0.0, 4.0, 1.0), (4.0, 8.0, 1.15)], first_cut_s=3.0, min_piece_s=1.0, zoom=1.15)
    assert [p[:2] for p in ps] == [(0.0, 3.0), (3.0, 4.0), (4.0, 8.0)] and [p[2] for p in ps] == [1.0, 1.15, 1.0]
    assert A.opening_pieces([(0.0, 2.5, 1.0)], first_cut_s=3.0, min_piece_s=1.0, zoom=1.15) == [(0.0, 2.5, 1.0)]
    assert A.opening_pieces([(0.0, 3.5, 1.0)], first_cut_s=3.0, min_piece_s=1.0, zoom=1.15) == [(0.0, 3.5, 1.0)]
    s = A.resolve_settings(A.Settings(), 2)
    assert s.open_first_cut_s == 3.0 and s.open_min_piece_s == 1.0


# ---------------- 出图身份 LoRA 按“在画且不背对”挂

def test_image_identity_lora_follows_on_screen(monkeypatch):
    from ns_agent import compiler as C
    from ns_schema.script import CharacterLock, Episode, LoraTrigger, ScriptGlobals, Shot
    g = ScriptGlobals(character_locks=[CharacterLock(name="林晚", description="蓝发"),
                                       CharacterLock(name="陈宇", description="23岁")],
                      lora_triggers=[LoraTrigger(trigger="lnwan_qi", kind="image", description="林晚出图身份",
                                                 file="lin_wan_qi_v1.safetensors", strength=[0.8, 0.8])])
    monkeypatch.setattr(C, "banned_image_loras", lambda root=None: set())   # 机制测试；I8 禁用见 test_gen_contract
    monkeypatch.setattr(C, "auto_lora_triggers", lambda root=None: {"林晚": [
        {"trigger": "lnwan_qi", "kind": "image", "file": "lin_wan_qi_v1.safetensors", "strength": 0.8}]})
    ep = Episode(number=2, title="t", source_line=1)
    avail = {"lin_wan_qi_v1.safetensors"}

    def comp(img, trig=()):
        s = Shot(episode=2, index=1, img_prompt=img, img_triggers=list(trig), motion_prompt="x", source_line=1)
        return C.compile_shot(ep, s, g, avail)
    c = comp("近景，林晚抬眼")
    assert c.image_loras == [("lin_wan_qi_v1.safetensors", 0.8)] and c.image_prompt.startswith("lnwan_qi")
    c = comp("lnwan_qi，中景，陈宇站在玄关，林晚背对镜头站在厨房方向", ["lnwan_qi"])
    assert c.image_loras == [] and "lnwan_qi" not in c.image_prompt and "背对" in c.image_loras_dropped[0]
    c = comp("lnwan_qi，中景，陈宇站在玄关喝水", ["lnwan_qi"])
    assert c.image_loras == [] and "不在画" in c.image_loras_dropped[0]
