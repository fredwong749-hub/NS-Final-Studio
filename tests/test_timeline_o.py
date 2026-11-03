"""TIMELINE-O 11-03（项目方：“MiniMax 的提示词，运动……是需要时间轴的”）：
V2 剧 / 新剧时间轴一律 strict；H3 分拍时间码与 **分拍** 对齐（RL-T8）；运镜按拍（SS-M8）；编译缺时间轴失败关闭；
导入关口按镜合成 [TL-<镜>]，补丁环只补时间轴；写手包按剧注入；成稿集头重生 + 不许有 V1 id。"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/recipes", "tools/pipeline", "tools/script_rsi"):
    sys.path.insert(0, str(ROOT / p))

from ns_api import script_chat as SC  # noqa: E402
from ns_recipes import lint as L  # noqa: E402
from ns_recipes import prompt as PR  # noqa: E402
from ns_recipes import spec_import as SI  # noqa: E402
import ns_schema.shot_spec as SS  # noqa: E402
from ns_schema.shot_spec import (Audio, Camera, Continuity, H3Text, IdentityRef, Motion, OnScreenCharacter,  # noqa: E402
                                 Scene, ShotSpec, Source, missing_fields)

V2_FILE = str(ROOT / "data" / "pipeline" / "runs" / "series10_v2" / "P4_ep01.final.md")
V1_FILE = str(ROOT / "data" / "pipeline" / "runs" / "series10_v1" / "P4_ep01.final.md")
BODY = ("[Shot 1] Live-action, cinematic, a close-up begins in the position, framing and lighting established by Picture 1, "
        "a young woman by a chair. In the first two seconds, she is already mid-reach, her eyes still on the card while her lips part. "
        "Then, around the third second, she lifts the card, her gaze toward the stand, her brows rising. "
        "Then, around the fifth second, her eyes stay on the stand and her lashes blink as her hand keeps lowering as the shot ends.")
T3, T5 = "Then, around the third second, ", "Then, around the fifth second, "
H3 = (PR.FL2VA_FMT.format(s="6.58") + "\n\nintegrated_multimodal_description: " + BODY
      + "\n\noverall_soundscape: A card ticks.\n\nnon_diegetic_music: N/A")
BEATS = ("0–2秒｜拿起卡｜视线=卡｜表情=嘴唇微张｜反应=—｜运镜=小幅推近；2–4秒｜举起｜视线=灯架｜表情=眉头抬起｜反应=—｜运镜=继续推近；"
         "4–6秒｜放下｜视线=灯架｜表情=眨眼｜反应=—｜运镜=继续推近")


def spec(script_file=V2_FILE, rules=None, beats=BEATS, h3=H3):
    ch = [OnScreenCharacter(id="lead_f", name="祁念", screen_x="中", facing="右", pose="站",
                            en_phrase="a young woman", identity_ref=IdentityRef(path="a.png", sha="1"))]
    return ShotSpec(id="ep01-S8", episode=1, index=8, duration_s=6.0, source=Source(script_file=script_file, rules_version=rules),
                    scene=Scene(id="sk_x"), camera=Camera(size="近景", move="push in"), characters_on_screen=ch,
                    motion=Motion(text="x——近景", beats=SI.parse_beats(beats), end_state="近景"),
                    audio=Audio(soundscape_en="Tick."), continuity=Continuity(link="换场", to_next="手放下"),
                    h3=H3Text(mode="fl2va", text=h3))


def test_v2_is_strict_even_without_stamp_v1_is_not():
    assert SS.rules_at_least(spec(rules=None), 2)                         # V2 / 新剧：没章也 strict
    assert SS.rules_at_least(spec(rules="rules_v2+sysimpl-v3"), 2)
    assert not SS.rules_at_least(spec(rules="rules_v2+sysimpl-v1"), 2)    # 明确盖了低版本章才放过
    assert not SS.rules_at_least(spec(V1_FILE, rules="rules_v2+sysimpl-v3"), 2)   # V1 冻结：仍按 timing_lint.json（warn）
    with SS.timeline_run("series10_v2"):                                   # 临时文件认不出剧：按当前剧
        assert SS.rules_at_least(spec(script_file="C:/tmp/p4-abc.md"), 2)
    assert not SS.rules_at_least(spec(script_file="C:/tmp/p4-abc.md"), 2)


def test_alignment_ok_and_mismatch():
    assert L.timeline_alignment(H3, spec()) == []
    bad = H3.replace(T5, "")
    assert "RL-T8" in {i["code"] for i in L.timeline_alignment(bad, spec(h3=bad))}           # 拍数不同
    off = H3.replace("fifth second", "seventh second")
    assert any("对不上" in i["message"] for i in L.timeline_alignment(off, spec(h3=off)))     # 拍起点差 2 秒
    rev = H3.replace("third second", "XX").replace("fifth second", "third second").replace("XX", "fifth second")
    assert any("严格递增" in i["message"] for i in L.timeline_alignment(rev, spec(h3=rev)))   # 拍序颠倒
    flat = H3.replace("In the first two seconds, ", "").replace(T3, "").replace(T5, "")
    assert L.timeline_alignment(flat, spec(h3=flat))[-1]["message"].startswith("缺时间轴")
    assert L.timeline_alignment(H3, spec(beats=""))[0]["message"].startswith("缺时间轴：剧本没有")


def test_l141_at_timecode_only_for_cuts():
    inshot = H3.replace(T3, "At 00:02.000, ").replace(T5, "At 00:04.000, ")       # 旧写法：镜内 At 时间码
    assert "RL-T9" in {i["code"] for i in L.timeline_alignment(inshot, spec(h3=inshot))}
    mark = H3.replace(T3, "At the 2-second mark, ")
    assert "RL-T9" in {i["code"] for i in L.timeline_alignment(mark, spec(h3=mark))}
    cut = H3.replace(" as the shot ends.", ". [Shot 2] At 00:05.000, the camera cuts to her hand as the shot ends.")
    assert "RL-T9" not in {i["code"] for i in L.timeline_alignment(cut, spec(h3=cut))}         # 切镜带 At：合格
    nocut = cut.replace("[Shot 2] At 00:05.000, ", "[Shot 2] ")
    assert any("切镜没写" in i["message"] for i in L.timeline_alignment(nocut, spec(h3=nocut)))
    dec = cut.replace(". [Shot 2] At 00:05.000,", ". [Shot 2] At 00:05.000, x. [Shot 3] At 00:04.000,")
    assert any("严格递增" in i["message"] for i in L.timeline_alignment(dec, spec(h3=dec)))
    assert L.in_shot_timecodes(cut) == []


def test_example_follows_beats():
    ex = L.nl_example(spec().motion.beats)
    assert ex.startswith("In the first two seconds") and "around the third second" in ex and "around the fifth second" in ex


def test_beat_camera_slot_required_under_strict():
    no_cam = BEATS.replace("｜运镜=继续推近", "")
    m = {(x.rule, x.severity) for x in missing_fields(spec(beats=no_cam))}
    assert ("SS-M8", "block") in m
    assert "SS-M8" not in {x.rule for x in missing_fields(spec(V1_FILE, rules="rules_v2+sysimpl-v3", beats=no_cam))}


def test_compiler_fails_closed_on_missing_timeline():
    flat = H3.replace("In the first two seconds, ", "").replace(T3, "").replace(T5, "")
    with pytest.raises(PR.NeedsWriter, match="缺时间轴"):
        PR.build_base(spec(h3=flat), {"prompt": {}}, "fl2va", 158)
    inshot = H3.replace(T3, "At 00:02.000, ").replace(T5, "At 00:04.000, ")
    with pytest.raises(PR.NeedsWriter, match="At 时间码"):                    # L-141：镜内 At 时间码也失败关闭
        PR.build_base(spec(h3=inshot), {"prompt": {}}, "fl2va", 158)
    out = PR.build_base(spec(), {"prompt": {}}, "fl2va", 158)                 # 对齐的稿照常编，拍序原样保留
    assert T3.strip() in out["text"] and T5.strip() in out["text"] and "At 00:" not in out["text"]
    PR.build_base(spec(V1_FILE, rules="rules_v2+sysimpl-v3", h3=flat), {"prompt": {}}, "fl2va", 158)   # V1 不变


def test_timeline_gate_returns_only_errors():
    assert L.timeline_gate(spec()) == []
    flat = H3.replace("In the first two seconds, ", "").replace(T3, "").replace(T5, "")
    codes = {i["code"] for i in L.timeline_gate(spec(h3=flat))}
    assert {"RL-T1", "RL-T8"} <= codes


def test_import_gate_on_real_v2_ep01_emits_one_tl_item_per_shot(tmp_path, monkeypatch):
    import p4_adapter as P4
    monkeypatch.setattr(P4, "TMP", tmp_path)          # 临时稿不写真实 data/
    f = Path(V2_FILE)
    if not f.exists():
        pytest.skip("没有 V2 第 1 集稿")
    # K-OPS-F24 夹具：真实稿复制一份、去掉每镜的 **分拍** / **表演节拍** 行 → 每镜都缺时间轴（返修稿修好后测试不跟着红）
    lines = f.read_text(encoding="utf-8").splitlines()
    txt = chr(10).join(x for x in lines if not x.startswith(("**分拍**", "**表演节拍**")))
    n_shots = sum(1 for x in lines if x.startswith("**镜") and "｜img**" in x)
    with SC.run_scope("series10_v2"):
        rep, *_ = P4.check_p4(txt[txt.find("## ep01"):], 1)
    tl = [i for i in rep.issues if i.level == "block" and (i.message or "").startswith("[TL-")]
    ids = [i.message.split("]")[0][1:] for i in tl]
    assert ids and len(ids) == len(set(ids)) == n_shots                       # 每镜一个 id（补丁环按镜计尝试次数）
    assert all(i.field.endswith(".timeline") for i in tl)


def test_writer_pack_injects_timeline_rules_per_run():
    assert SC.TIMELINE_BLOCK_HEAD in SC.timeline_block("series10_v2")
    tb = SC.timeline_block("series10_v2")
    assert "In the first <N> seconds," in tb and "Then, around the <序数> second," in tb and "运镜=" in tb
    assert "只用于切镜" in tb and "L-141" in tb
    assert SC.timeline_block("series10_v1") == ""
    with SC.run_scope("series10_v2"):
        sysp, parts = SC.build_system_prompt(SC.load_config(), None, appendix_budget=0)
    assert SC.TIMELINE_BLOCK_HEAD in sysp and any("时间轴" in p["name"] for p in parts)


def _agent():
    import importlib.util
    sp = importlib.util.spec_from_file_location("autoflow_agent_tl", ROOT / "tools/script_rsi/autoflow_agent.py")
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


DOC = ("**镜1｜img**：a\n**分拍**：0–2秒｜x\nintegrated_multimodal_description: [Shot 1] a\n**台词时段**：1=0–1秒\n"
       "**镜2｜img**：b\n**分拍**：0–2秒｜y\nintegrated_multimodal_description: [Shot 1] b\n")


def test_timeline_patch_may_only_touch_timeline_lines_of_target_shots():
    AG = _agent()
    ok = DOC.replace("[Shot 1] a", "[Shot 1] a. Then, around the third second, a2")
    assert AG.timeline_check(DOC, ok, ["p4#TL-1"]) == ""
    assert "以外的行" in AG.timeline_check(DOC, DOC.replace("1=0–1秒", "1=0–2秒"), ["p4#TL-1"])        # 台词时段不许动
    assert "镜1以外" in AG.timeline_check(DOC, DOC.replace("[Shot 1] b", "[Shot 1] b2"), ["p4#TL-1"])  # 别的镜不许动
    assert AG.timeline_check(DOC, DOC.replace("1=0–1秒", "x"), ["p4#SS-A1"]) == ""                     # 非时间轴补丁不管


def test_patch_user_adds_timeline_scope():
    import importlib.util
    sp = importlib.util.spec_from_file_location("autoflow_tl", ROOT / "tools/script_rsi/autoflow.py")
    AF = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(AF)
    import p4_adapter as P4
    doc = "## ep01《x》\n\n" + DOC
    u = AF.patch_user(1, "", doc, {"lines": []}, [("p4", {"id": "TL-1", "why": "ep01-S1.timeline：[TL-1] 镜1", "shots": [1]})])
    assert P4.TIMELINE_PATCH_SCOPE in u


def test_final_header_regen_quarantines_and_v1_ids_block(tmp_path, monkeypatch):
    AG = _agent()
    monkeypatch.setattr(AG, "ROOT", tmp_path)
    rd = tmp_path / "series10_v2"
    rd.mkdir()
    fp = rd / "P4_ep01.final.md"
    fp.write_text("# 旧集头 V1\n---\n\n## ep01\nbody\n", encoding="utf-8")
    monkeypatch.setattr(AG.H.RC, "_rel", lambda p: str(p))
    r = AG.regen_header(rd, fp, "# 新集头\n---\n\n", "## ep01\nbody\n")
    assert r and Path(r["backup"]).read_text(encoding="utf-8").startswith("# 旧集头 V1")    # 旧稿隔离备份
    assert fp.read_text(encoding="utf-8") == "# 新集头\n---\n\n## ep01\nbody\n"
    assert AG.regen_header(rd, fp, "# 新集头\n---\n\n", "## ep01\nbody\n") is None          # 已一致不再动
    fp.write_text("lnwan01 林晚\n", encoding="utf-8")
    assert "旧剧内容" in AG.final_v1_hits(rd, fp)


def test_void_request_writes_marker_and_quarantines(tmp_path, monkeypatch):
    AG = _agent()
    monkeypatch.setattr(AG, "ROOT", tmp_path)
    monkeypatch.setenv("NSFS_INBOX_DIR", str(tmp_path / "inbox"))
    rd = tmp_path / "series10_v2"
    (rd / "writer_tasks").mkdir(parents=True)
    (rd / "writer_tasks" / "P4_ep01_a3.json").write_text("{}", encoding="utf-8")
    (tmp_path / "inbox" / "requests").mkdir(parents=True)
    (tmp_path / "inbox" / "requests" / "series10_v2__P4_ep01_a3.json").write_text("{}", encoding="utf-8")
    r = AG.void_request(rd, "P4_ep01_a3", "误出")
    assert (tmp_path / "inbox" / "requests" / "series10_v2__P4_ep01_a3.void").exists()
    assert sorted(r["moved"]) == ["P4_ep01_a3.json", "series10_v2__P4_ep01_a3.json"]
    assert not (rd / "writer_tasks" / "P4_ep01_a3.json").exists()
    assert list((tmp_path / "data" / "_quarantine").rglob("P4_ep01_a3.json.*"))
