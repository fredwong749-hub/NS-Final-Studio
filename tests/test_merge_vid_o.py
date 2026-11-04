"""MERGE-VID-O（11-03，L-137：V2 并回 V1 视频链）。
ISS-1103-024206-3737 视频链按剧；ISS-1103-024206-4b21 看图闸门先于视频；ISS-1103-024206-0474 运镜按剧；
第 7 项 V2 集级 BGM 写入方（music_v2.json）；第 9 项 p4_adapter 传 run、V2 的 QW-T1 / QW-C1 判 block。
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in ("tools/series10_video", "tools/pipeline", "tools/bgm", "services/recipes", "packages/schema", "services/agent",
          "services/render_router", "services/api", "services/post", "packages/qc"):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))

import run_ctx as RC  # noqa: E402
from ns_recipes import compiler as C  # noqa: E402
from ns_recipes import registry as REG  # noqa: E402

V2 = "series10_v2"
V2_SRC = str(ROOT / "data/pipeline/runs/series10_v2/P4_ep01.final.md")
V1_SRC = "data/staging_v3/merged/x_series10_v1_ep01-10.md"


_BJ = {}


def _bj():
    """script_name_guard：build_jobs 同名脚本有两份，按文件载入（模块级缓存一份）"""
    if "m" not in _BJ:
        import importlib.util as u
        sp = u.spec_from_file_location("s10v_build_jobs_merge_vid", ROOT / "tools/series10_video/build_jobs.py")
        m = u.module_from_spec(sp)
        sp.loader.exec_module(m)
        _BJ["m"] = m
    return _BJ["m"]


# ---------------------------------------------------------------- 1. 视频链按剧（ISS-3737）
def test_run_ctx_resolves_and_fails_closed():
    assert RC.resolve(["--run", V2], server=False) == V2
    assert RC.resolve([f"--run={V2}"], server=False) == V2
    assert RC.vid_rel(V2) == "data/pipeline/runs/series10_v2/video"
    with pytest.raises(RC.VideoRunError):
        RC.resolve(["--run", "series10_nope"], server=False)        # 没登记
    with pytest.raises(RC.VideoRunError):
        RC.resolve([], server=True) if not __import__("os").environ.get("NS_RUN") else RC.resolve(["--run", "a/b"], server=True)
    assert RC.strip_run(["run", "gpu33", "--run", V2]) == ["run", "gpu33"]


def test_run_ctx_requires_video_policy_scope(monkeypatch):
    monkeypatch.setattr(RC, "scope_runs", lambda: ["series10_v1"])
    with pytest.raises(RC.VideoRunError, match="video_policy"):
        RC.resolve(["--run", V2], server=False)


def test_build_jobs_paths_per_run():
    B = _bj()
    try:
        B.set_run(V2)
        assert B.VID == ROOT / "data/pipeline/runs/series10_v2/video"
        assert ROOT / B.RENDERS == ROOT / "data/renders/series10_v2"
        assert B.VIDEO_HOLD == ROOT / "data/autopilot/runs/series10_v2/video_hold.json"
        assert B.HOST_OF_EP == {} and B.NAME2ID is None
        ids = B.name_ids()
        assert "林晚" not in ids and ids.get("祁念") == "lead_f"            # V2 人物表，不用 V1 人名
        specs = B.load_specs()
        assert specs and all(s.source.script_file and "series10_v2" in s.source.script_file for s in specs.values())
        ch = B.recipe_choice()                                               # V2 没有 recipe_choice.json → 按政策派生 Pika
        assert ch["face_default"] == ch["noface_default"] == ch["ref_default"] == "i2va_pika_flex" and ch["derived"]
        B.set_run("series10_v1")
        assert B.VID == ROOT / "data/pipeline/runs/series10_v1/video" and ROOT / B.RENDERS == ROOT / "data/renders"
        assert B.VIDEO_HOLD == ROOT / "data/autopilot/video_hold.json" and B.HOST_OF_EP[1] == "gpu33"
    finally:
        B.set_run("series10_v1")


def test_recipe_choice_fails_closed_without_policy(monkeypatch, tmp_path):
    B = _bj()
    try:
        B.set_run(V2)
        monkeypatch.setattr(B, "CHOICE", tmp_path / "none.json")
        monkeypatch.setattr(B.C, "video_policy", lambda: {"pika_only": {"enabled": True, "allowed": ["i2va_pika_flex"]},
                                                          "scope_runs": ["series10_v1"]})
        with pytest.raises(B.RecipeChoiceMissing):
            B.recipe_choice()
    finally:
        B.set_run("series10_v1")


def test_video_policy_scope_per_run(monkeypatch):
    reg = REG.load()
    v2 = SimpleNamespace(id="ep01-S8", source=SimpleNamespace(script_file=V2_SRC))
    v1 = SimpleNamespace(id="ep01-S1", source=SimpleNamespace(script_file=V1_SRC))
    old = SimpleNamespace(id="ep01-S1", source=SimpleNamespace(script_file="data/import/old_60ep.md"))
    assert C.policy_applies(v2) and C.policy_applies(v1) and not C.policy_applies(old)
    assert "不是 Pika" in C.hold_reason(reg, "i2va_pdd2", [], v2)            # V2 也只许 Pika（L-088 原样生效）
    assert C.hold_reason(reg, "i2va_pika_flex", [], v2) is None
    assert "泛红防护" in C.hold_reason(reg, "i2va_pika_flex", ["flush_risk"], v2)
    monkeypatch.setattr(C, "video_policy", lambda: {"scope_runs": ["series10_v1"], "pika_only": {"enabled": True}})
    with pytest.raises(C.PolicyMissing):                                    # 登记的剧却没有视频政策 → 失败关闭
        C.policy_applies(v2)
    monkeypatch.setattr(C, "video_policy", lambda: {})
    with pytest.raises(C.PolicyMissing):
        C.policy_applies(v1)


def test_vidgen_requires_run_and_policy_file_fails_closed(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("NS_RUN", "x")      # 先登记还原点：vidgen.set_run 会直接写 os.environ["NS_RUN"]
    monkeypatch.delenv("NS_RUN")
    import vidgen as VG
    assert VG.main(["run", "gpu33"]) == 2 and "必须显式指定剧" in capsys.readouterr().out
    monkeypatch.setattr(VG, "POLICY", tmp_path / "missing.json")
    assert "失败关闭" in VG.policy_hold({"recipe": "i2va_pika_flex"})
    VG.set_run(V2)
    assert VG.VID_REL == "data/pipeline/runs/series10_v2/video"


def test_deploy_and_night_follow_run(monkeypatch):
    monkeypatch.setenv("NS_RUN", V2)
    import deploy as DP
    import night as N
    DP, N = importlib.reload(DP), importlib.reload(N)
    try:
        assert DP.VID_REL == N.VID_REL == "data/pipeline/runs/series10_v2/video"
        assert DP.PID == "run/vidgen_series10_v2.pid" and N.EPS_OUT == ROOT / "data/episodes/series10_v2"
        assert N.partition_hosts({"video": {"gpu33": [1]}, "runs": {V2: {"video": {"gpu36": [1]}}}}) == {"1": "gpu36"}
        assert N.partition_hosts({"video": {"gpu33": [1, 3]}}) == {"1": "gpu33", "3": "gpu33"}
    finally:
        monkeypatch.setenv("NS_RUN", "series10_v1")
        importlib.reload(DP), importlib.reload(N)


# ---------------------------------------------------------------- 2. 看图闸门先于视频（ISS-4b21）
def test_vqa_video_requires_q9_on():
    d = json.loads((ROOT / "config/vqa.json").read_text(encoding="utf-8"))
    assert d["gate"]["video_requires_q9"] is True
    import yaml
    g = yaml.safe_load((ROOT / "config/policies/gates.yaml").read_text(encoding="utf-8"))
    assert g["items"]["video_requires_q9"]["value"] is True


def _take(tmp, sid, q9_status):
    ep, s = sid.split("-")
    d = tmp / "data" / "renders" / V2 / ep / s
    (d / "takes").mkdir(parents=True)
    from PIL import Image
    Image.new("RGB", (8, 8), (90, 90, 90)).save(d / "takes" / "image_001.png")
    items = [{"id": "Q1", "status": "pass"}, {"id": "Q10", "status": "pass", "evidence": {"count": {"defects": []}}}]
    if q9_status:
        items.append({"id": "Q9", "status": q9_status})
    (d / "takes.json").write_text(json.dumps({"active": {"image": 1}, "takes": [
        {"stage": "image", "n": 1, "file": f"renders/{V2}/{ep}/{s}/takes/image_001.png",
         "postflight": {"ok": True, "items": items}}]}), encoding="utf-8")


def test_frames_without_q9_pass_never_reach_video(monkeypatch, tmp_path):
    B = _bj()
    from ns_agent.vqa import contract as VQ
    real = json.loads((ROOT / "config/vqa.json").read_text(encoding="utf-8"))
    real["judge"]["enforce"] = real["gate"]["enforce"] = True
    monkeypatch.setattr(VQ, "cfg", lambda: real)                     # 用真配置（video_requires_q9 = true）
    try:
        B.set_run(V2)
        monkeypatch.setattr(B, "ROOT", tmp_path)
        monkeypatch.setattr(B, "VID", tmp_path / "vid")
        monkeypatch.setattr(B, "FRAMES_OK", tmp_path / "vid" / "frames_ok.json")
        _take(tmp_path, "ep01-S1", "pass")
        _take(tmp_path, "ep01-S2", "fail")
        _take(tmp_path, "ep01-S3", "untested")
        _take(tmp_path, "ep01-S4", None)                              # 没有看图结果 = 未通过
        got = B.passed_frames()
        assert set(got) == {"ep01-S1"}
        monkeypatch.setattr(B, "_vq", lambda: None)                   # 看图模块载不进来 → 一张都不放（失败关闭）
        assert B.passed_frames() == {}
    finally:
        B.set_run("series10_v1")


# ---------------------------------------------------------------- 3. 视频端运镜按剧（ISS-0474）
def test_video_run_of_spec():
    from ns_recipes import prompt as PR
    assert PR.video_run(SimpleNamespace(source=SimpleNamespace(script_file=V2_SRC))) == V2
    assert PR.video_run(SimpleNamespace(source=SimpleNamespace(script_file=V1_SRC))) == "series10_v1"


BOLT = "The camera follows her at shoulder height with a gentle natural sway"   # V2 专属运镜 handheld_follow（runs: [series10_v2]）


def test_build_base_keeps_v2_scoped_camera_move(monkeypatch):
    """prompt.py:215 传 run：V2 专属运镜（handheld_follow）原句保留；同一句不传 run 会被改回固定机位"""
    B = _bj()
    from ns_recipes import lint as LN
    from ns_recipes import prompt as PR
    sys.path.insert(0, str(ROOT / "services/agent"))
    from ns_agent import camera_norm as CN
    monkeypatch.setattr(LN, "missing_timeline", lambda *a, **k: None)     # 时间轴闸门归 TIMELINE-O，这里只验运镜
    try:
        B.set_run(V2)
        sp = B.load_specs()["ep01-S8"]
        # W13 CUTB-PREP 11-03：数据态陈旧（不是放宽）。ep01-S8 重导后原句改成句中小写 “…, and the camera pushes in with small amplitude …”，
        # 原来区分大小写的 replace 换不到 → BOLT 不在文本里。改成不分大小写换掉本镜的那句运镜（下一行仍断言换进去了）
        import re as _re
        sp.h3.text = _re.sub(r"(?i)the camera pushes in with small amplitude", BOLT, sp.h3.text, count=1)
        assert BOLT in sp.h3.text
        rc = REG.load().resolve("i2va_pika_flex")
        out = PR.build_base(sp, rc, "i2va", 145)
        assert BOLT in out["text"] and not any("K-REN-801" in n for n in out["notes"])
        txt, ch = CN.normalize_video_prompt(BOLT + ".", "", run=None)
        assert ch and BOLT not in txt                                      # 旧行为（run=None）：被改掉
    finally:
        B.set_run("series10_v1")


def test_compile_with_edits_passes_run(monkeypatch):
    from ns_render import pipeline as P
    seen = {}

    class Stop(Exception):
        pass

    def fake(*a, **k):
        seen.update(k)
        raise Stop
    monkeypatch.setattr(P, "compile_shot", fake)
    monkeypatch.setattr(P, "_legacy_and_primary", lambda: ("series10_v1", V2))
    script = SimpleNamespace(globals=None, episodes=[SimpleNamespace(number=1, shots=[SimpleNamespace(id="ep01-S8")])])
    with pytest.raises(Stop):
        P.compile_with_edits(script, "ep01-S8", set())
    assert seen.get("framing_project") == V2
    monkeypatch.setattr(P, "_legacy_and_primary", lambda: ("series10_v1", "series10_v1"))
    with pytest.raises(Stop):
        P.compile_with_edits(script, "ep01-S8", set())
    assert seen.get("framing_project") is None                             # V1 行为不变


# ---------------------------------------------------------------- 5. 写作校验传 run，V2 硬项 block（第 9 项）
def _gate():
    import p4_adapter as PA
    return PA._gate_module()


def _v2_src_7s(tmp_path) -> Path:
    """K-OPS-F24 夹具：真实 V2 第 1 集 P4 复制到 tmp，只把镜6 的时长改成 7 秒（返修稿修掉超长镜后测试不再跟着红）"""
    import re
    import pytest
    src = Path(V2_SRC)
    if not src.is_file():
        pytest.skip("没有 V2 第 1 集 P4")
    t = src.read_text(encoding="utf-8")
    a, b = t.find("**镜6｜"), t.find("**镜7｜")
    assert a >= 0 and b > a, "P4 里找不到镜6 / 镜7"
    blk, n = re.subn(r"\*\*时长\*\*：\s*[\d.]+\s*秒", "**时长**：7秒", t[a:b], count=1)
    assert n == 1, "镜6 没有时长行"
    out = tmp_path / "P4_ep01.final.md"
    out.write_text(t[:a] + blk + t[b:], encoding="utf-8")
    return out


def test_validate_v2_hard_rules_block_shot_over_6s(tmp_path):
    g = _gate()
    src = _v2_src_7s(tmp_path)
    rep2 = g.validate(src, 1, run=V2)
    hard = rep2["hard_blocks"]
    assert any(h["shot"] == "ep01-S6" and h["rule_id"] == "QW-T1" for h in hard)
    s6 = next(s for e in rep2["episodes"] for s in e["shots"] if s["id"] == "ep01-S6")
    assert any(i["rule_id"] == "QW-T1" and i["level"] == "block" for i in s6["issues"]) and not s6["ok"]
    rep1 = g.validate(src, 1, run="series10_v1")                          # legacy 口径：保持 warn
    assert rep1["hard_blocks"] == []
    assert not any(i["rule_id"] == "QW-T1" and i["level"] == "block" for e in rep1["episodes"]
                   for i in e["issues"] + [x for s in e["shots"] for x in s["issues"]])


def test_apply_hard_rules_upgrades_qw_c1():
    g = _gate()
    sh = SimpleNamespace(id="ep01-S2", index=2, duration=5)
    ep = SimpleNamespace(shots=[sh])
    ep_issues = [{"rule_id": "QW-T1", "level": "warn", "detail": "x"}]
    shot_iss = {"ep01-S2": [g._issue("QW-C1", "motion 的英文运镜不在运镜词表里")]}
    assert shot_iss["ep01-S2"][0]["level"] == "warn"
    hard = g._apply_hard_rules(ep, ep_issues, shot_iss)
    assert shot_iss["ep01-S2"][0]["level"] == "block" and hard[0]["rule_id"] == "QW-C1" and ep_issues == []
    assert g.hard_run(V2) and not g.hard_run("series10_v1") and not g.hard_run(None)


def test_p4_adapter_passes_current_run(monkeypatch, tmp_path):
    import p4_adapter as PA
    monkeypatch.setattr(PA, "TMP", tmp_path)
    from ns_api import script_chat as SC
    seen = {}
    real = PA._gate_module

    def gm():
        m = real()
        orig = m.validate

        def v(path, episode=None, *a, **k):
            seen["run"] = k.get("run")
            return orig(path, episode, *a, **k)
        m.validate = v
        return m
    monkeypatch.setattr(PA, "_gate_module", gm)
    (tmp_path / "src").mkdir()
    t = _v2_src_7s(tmp_path / "src").read_text(encoding="utf-8")                # 夹具：镜6 = 7 秒
    with SC.run_scope(V2):
        rep, _s, _sp, _raw = PA.check_p4(t[t.find("## ep"):], 1)
    assert seen["run"] == V2
    assert any(h["shot"] == "ep01-S6" and h["rule_id"] == "QW-T1" for h in rep.hard_blocks)
    assert any("[QW-T1]" in i.message and i.level == "block" for i in rep.issues)


# ---------------------------------------------------------------- 4. V2 集级 BGM 写入方（第 7 项）
def test_bgm_out_dir_per_run():
    import deliver as D
    assert D.out_dir(run="series10_v1") == ROOT / "data/music/series10"
    assert D.out_dir(run=V2) == ROOT / "data/music/series10_v2"


def test_library_plan_and_meta_pass_media_check(monkeypatch, tmp_path):
    import bgm_library as LB
    from ns_post import run_media as RM
    lib = RM.music_library(V2, ROOT)
    req = {"edit_sig": "abc", "duration_s": 12.0, "crossfade_s": 1.5,
           "shots": [{"index": 1, "start_s": 0.0, "dur_s": 4.0}, {"index": 2, "start_s": 4.0, "dur_s": 4.0},
                     {"index": 3, "start_s": 8.0, "dur_s": 4.0}]}
    shots = {1: {"extras": {"段落": "现实段"}}, 2: {"extras": {"段落": "幻想段"}}, 3: {}}
    pl = LB.plan(V2, 1, req, shots, lib)
    assert [s["segment"] for s in pl["spans"]] == ["reality", "fantasy", "reality"]
    assert pl["spans"][1]["track"] == "v2_bgm_C_fantasy" and pl["spans"][0]["track"] == "v2_bgm_A_reality"
    assert pl["library_track"] == "v2_bgm_A_reality" and pl["library_sha256"] == lib["v2_bgm_A_reality"]["sha256"]
    wav = tmp_path / "ep01.wav"
    wav.write_bytes(b"RIFF0000")
    js = LB.assembly_json(pl, wav, LB.D.load_cfg(), {})
    (tmp_path / "ep01.json").write_text(json.dumps(js), encoding="utf-8")
    assert RM.check_episode_music(V2, 1, tmp_path, root=ROOT) == {"checked": True, "track": "v2_bgm_A_reality"}
    assert js["shot_starts"] == [0.0, 4.0, 8.0] and js["cues"][1]["start_s"] == 4.0


def test_library_waits_for_edit_lock(monkeypatch, tmp_path):
    import bgm_library as LB
    from ns_post import run_media as RM
    monkeypatch.setattr(RM, "music_dir", lambda run, root=None: tmp_path / "music")
    monkeypatch.setattr(LB, "lock_dirs", lambda run: (tmp_path / "lock", tmp_path / "req"))
    st = LB.deliver_episode(V2, 1)
    assert st["status"] == "not_locked" and not (tmp_path / "music" / "ep01.wav").exists()
    with pytest.raises(LB.NotLibraryRun):
        LB.deliver_episode("series10_v1", 1)


# ---------------------------------------------------------------- 总调度裁定（11-03）：硬阻断不收稿 + 缩短镜长补丁
def _ag(name="autoflow_agent_mvo"):
    import importlib.util as u
    sp = u.spec_from_file_location(name, ROOT / "tools/script_rsi/autoflow_agent.py")
    m = u.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


def test_non_tl_blocking_rejects_hard_blocks():
    from ns_schema.upstream_common import Report
    AG = _ag()
    rep = Report("P4")
    rep.add("P4-GATE", "block", "[QW-T1] 镜6 时长 7 秒", "ep01-S6")
    assert AG.non_tl_blocking(rep) == 1
    rep.hard_blocks = [{"shot": "ep01-S6", "rule_id": "QW-T1"}]
    assert AG.non_tl_blocking(rep) == 99                                    # ≤6 放行不适用


def _dur_doc(d6="7", beat="0–3秒｜a；3–7秒｜b", lines="1=0.4–2.6秒；2=4.2–6.3秒", say="“甲。”／“乙。”", extra=""):
    blk = lambda n, d, b, ln, s: (f"**镜{n}｜img**：近景\n**分拍**：{b}\n**台词时段**：{ln}\n**时长**：{d}秒\n**对白**：{s}\n"
                                  f"integrated_multimodal_description: [Shot 1] x at 00:0{n}\n\n")
    return "## ep01｜T\n\n" + blk(5, "5", "0–5秒｜x", "无", "无") + blk(6, d6, beat, lines, say) + blk(7, "4", "0–4秒｜y", "无", "无") + extra


def test_duration_check_rules():
    AG = _ag()
    old = _dur_doc()
    good = _dur_doc("6", "0–3秒｜a；3–6秒｜b", "1=0.3–2.4秒；2=3.4–5.8秒")
    assert AG._shot_duration(old, 6) == 7.0 and AG.duration_check(old, good, 6) == ""
    assert "没有缩短" in AG.duration_check(old, _dur_doc("8"), 6)
    assert "仍超过上限" in AG.duration_check(old, _dur_doc("6.5"), 6)
    assert "以外的行" in AG.duration_check(old, good.replace("**对白**：“甲。”", "**对白**：“丙。”"), 6)   # 台词不许改
    assert "镜6以外" in AG.duration_check(old, good.replace("0–4秒｜y", "0–3秒｜y"), 6)
    assert "行数" in AG.duration_check(old, good + "多一行\n", 6)
    assert AG.duration_check(old, good, 9) == "找不到镜9"


def test_duration_patch_queues_then_packets(tmp_path):
    AG = _ag("autoflow_agent_mvo2")
    AF = AG.AF
    AG.live_note = lambda text: None
    rd = tmp_path / "dur1"
    rd.mkdir()
    r = AG.duration_patch(rd, 1, 6, 6, "V2 单镜 ≤6 秒。")
    assert r["queued"] and r["queue"][0]["shot"] == 6                       # 还没 final.md：排队
    (rd / "P4_ep01.final.md").write_text("头\n---\n\n" + _dur_doc(), encoding="utf-8")
    AG.RL.split_doc = lambda t: (t.split("---", 1)[0], [t.split("---", 1)[1].lstrip("\n")])
    import ns_api.script_chat as SC
    orig = SC.script_header
    SC.script_header = lambda registry=None, run=None: ("头", None)
    try:
        st = AF.Status(rd, 1, 0.0)
        out = AG._duration_from_queue(rd, 1, st)
    finally:
        SC.script_header = orig
    pk = json.loads((rd / "writer_tasks" / "patch_ep01_a1.json").read_text(encoding="utf-8"))
    assert out["from_s"] == 7.0 and pk["targets"] == ["dur#6"] and pk["duration_max"] == 6.0
    assert "cannot_fit" in pk["user"] and "镜数、镜号、台词" in pk["user"] and st.d["agent"]["duration_queue"] == []


def test_duration_cannot_fit_reports_issue(tmp_path, monkeypatch):
    AG = _ag("autoflow_agent_mvo3")
    seen = {}

    class RI:
        @staticmethod
        def report(run, ep, step, who, what, blocking, fix_hint=""):
            seen.update(run=run, step=step, what=what, blocking=blocking)
    monkeypatch.setattr(AG, "_load", lambda name, rel: RI if name == "report_issue" else None)
    note = AG.duration_cannot_fit(tmp_path / "series10_v2", 1, {"duration_shot": 6, "duration_max": 6.0}, "两句台词共 5.9 秒")
    assert "cannot_fit" in note and seen["blocking"] is True and seen["step"] == "6" and "镜6" in seen["what"]


def test_sop_step6_documents_duration_patch():
    t = (ROOT / "docs/master/PIPELINE_SOP_V2.md").read_text(encoding="utf-8")
    row = next(l for l in t.splitlines() if l.startswith("| 6 | 导入 |"))
    assert "duration_patch" in row and "cannot_fit" in row and "non_tl_blocking 返回 99" in row


# ---------------------------------------------------------------- W41（11-04，C-14）：跨剧版本不进视频
def test_foreign_run_takes_never_reach_video(monkeypatch, tmp_path):
    """V2 takes.json 的 active.image / active.last 指向 V1 前缀（renders/ep01/…）的版本 → passed_frames / passed_lasts 都不算"""
    B = _bj()
    from ns_agent.vqa import contract as VQ
    real = json.loads((ROOT / "config/vqa.json").read_text(encoding="utf-8"))
    real["judge"]["enforce"] = real["gate"]["enforce"] = True
    monkeypatch.setattr(VQ, "cfg", lambda: real)
    try:
        B.set_run(V2)
        monkeypatch.setattr(B, "ROOT", tmp_path)
        monkeypatch.setattr(B, "VID", tmp_path / "vid")
        monkeypatch.setattr(B, "FRAMES_OK", tmp_path / "vid" / "frames_ok.json")
        _take(tmp_path, "ep01-S1", "pass")                       # 本剧版本：照常
        _take(tmp_path, "ep01-S10", "pass")
        tj = tmp_path / "data/renders" / V2 / "ep01/S10/takes.json"
        d = json.loads(tj.read_text(encoding="utf-8"))
        v1 = tmp_path / "data/renders/ep01/S10/takes"
        v1.mkdir(parents=True)
        from PIL import Image
        Image.new("RGB", (8, 8)).save(v1 / "image_006.png")
        Image.new("RGB", (8, 8)).save(v1 / "last_002.png")
        pf = d["takes"][0]["postflight"]
        d["takes"] += [{"stage": "image", "n": 6, "file": "renders/ep01/S10/takes/image_006.png", "postflight": pf},
                       {"stage": "last", "n": 2, "file": "renders/ep01/S10/takes/last_002.png", "postflight": {"ok": True}}]
        d["active"] = {"image": 6, "last": 2}
        d["locked"] = {"last": 2}                                 # 定稿锁也不放行跨剧版本
        tj.write_text(json.dumps(d), encoding="utf-8")
        assert set(B.passed_frames()) == {"ep01-S1"}
        assert "跨剧" in B.ANOMALY_SKIPPED["ep01-S10"]
        assert B.passed_lasts() == {}
    finally:
        B.set_run("series10_v1")


def test_own_take_prefix_per_run():
    B = _bj()
    try:
        B.set_run(V2)
        assert B.own_take(f"renders/{V2}/ep01/S10/takes/last_001.png")
        assert not B.own_take("renders/ep01/S10/takes/last_002.png")
        assert not B.own_take("renders/series10_s2/ep01/S10/takes/x.png")
        B.set_run("series10_v1")
        assert B.own_take("renders/ep01/S10/takes/image_006.png")
        assert not B.own_take(f"renders/{V2}/ep01/S10/takes/last_001.png")   # V1 也不收 V2 的
    finally:
        B.set_run("series10_v1")


def test_l183_review_needed_first_frame_reaches_video(monkeypatch, tmp_path):
    """L-183：Q10 不过但按 Q1–Q9 全过取用（postflight.review_needed=true）的首帧进视频；同样 Q10 不过、没标 review_needed 的不进"""
    B = _bj()
    from ns_agent.vqa import contract as VQ
    real = json.loads((ROOT / "config/vqa.json").read_text(encoding="utf-8"))
    real["judge"]["enforce"] = real["gate"]["enforce"] = True
    monkeypatch.setattr(VQ, "cfg", lambda: real)
    try:
        B.set_run(V2)
        monkeypatch.setattr(B, "ROOT", tmp_path)
        monkeypatch.setattr(B, "VID", tmp_path / "vid")
        monkeypatch.setattr(B, "FRAMES_OK", tmp_path / "vid" / "frames_ok.json")
        for sid, rv in (("ep01-S4", True), ("ep01-S5", False)):
            _take(tmp_path, sid, "pass")
            tj = tmp_path / "data/renders" / V2 / "ep01" / sid.split("-")[1] / "takes.json"
            d = json.loads(tj.read_text(encoding="utf-8"))
            pf = d["takes"][0]["postflight"]
            for i in pf["items"]:
                if i["id"] == "Q10":
                    i["status"] = "fail"
            if rv:
                pf["review_needed"] = True
            tj.write_text(json.dumps(d), encoding="utf-8")
        got = B.passed_frames()
        assert "ep01-S4" in got and "ep01-S5" not in got
    finally:
        B.set_run("series10_v1")
