"""只读审查（fredw-d9）发现的缺陷的回归测试：造型确认（H1/M3）、状态表过期（H2）、G4/G5 记录（M1/M2/L2）、
规范化哈希（M4）、并发写/重建（M5）、底板确认（L1）、快照版本（L3）、校色复用（L4）、TOML 报错（L5）、
S1 闸门无剧本（L6）、manifest 底板文件（L7）。全部在临时目录里跑，不碰真实 data/。"""
import hashlib
import importlib.util
import json
import os
import shutil
import threading
import time
from pathlib import Path

import pytest

from ns_agent import bible as B
from ns_agent import prompt_snapshot as PS
from ns_agent import state_timeline as T
from ns_agent.looks import DEFAULT_SCRIPT_JSON, LookStore
from ns_api import looks as api
from ns_api import sop as SOP
from ns_schema.looks import LookPatch, WardrobeItem
from ns_schema.script import ScriptImport

REPO = Path(__file__).resolve().parents[1]
FIX = Path(__file__).parent / "fixtures" / "t06_golden"
OWNER = {"owner_confirmed_at": "2026-10-30T12:00:00", "owner_confirmed_ref": "伪造的原话", "owner_confirmed_hash": "x"}

needs_script = pytest.mark.skipif(not DEFAULT_SCRIPT_JSON.exists(), reason="data/import/script_v2.json missing")


def _tool(name):
    spec = importlib.util.spec_from_file_location(name, REPO / "tools" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def proj(tmp_path):
    root = tmp_path / "proj"
    shutil.copytree(FIX / "config", root / "config")
    shutil.copytree(FIX / "data", root / "data")
    shutil.copytree(REPO / "data" / "looks", root / "data" / "looks", ignore=shutil.ignore_patterns("*.tmp", "*.bak*"))
    (root / "config" / "shot_ownership.json").write_text("{}", encoding="utf-8")
    return root


def _store(root: Path) -> LookStore:
    return LookStore(root / "data" / "looks", root / "data" / "import" / "script_v2.json")


@pytest.fixture
def store(proj) -> LookStore:
    return _store(proj)


def _plan(store, ep, char="lin_wan"):
    return store.schedule().episodes.get(str(ep), {}).get(char)


# ------------------------------------------------------------------ H1 造型确认只能由 CLI 写、内容变了作废

def test_h1_http_put_routes_strip_owner_confirmation(store):
    api.put_episode_look(3, "lin_wan", LookPatch(notes=["x"], **OWNER), store)
    p = _plan(store, 3)
    assert p.owner_confirmed_at is None and p.owner_confirmed_ref is None and p.owner_confirmed_hash is None
    api.put_episode_range("lin_wan", api.RangePatch(episodes="4-5", patch=LookPatch(**OWNER)), store)
    assert all(_plan(store, e).owner_confirmed_at is None for e in (4, 5))
    sched = store.schedule()
    eps = {k: dict(v) for k, v in sched.episodes.items()}
    eps["6"] = {**eps.get("6", {}), "lin_wan": LookPatch(**OWNER)}
    api.put_schedule(api.ScheduleReplace(episodes=eps), store)
    assert _plan(store, 6).owner_confirmed_at is None
    res = store.resolver()
    assert not any(res.episode_confirmed("lin_wan", e) for e in (3, 4, 5, 6))
    api.put_shot_override("ep03-S1", "lin_wan", LookPatch(**OWNER), store)
    assert store.schedule().shot_overrides["ep03-S1"]["lin_wan"].owner_confirmed_at is None


def test_h1_confirmation_bound_to_content(store):
    store.confirm_episodes("3", "lin_wan", "项目方：ep03 造型可以")
    assert store.resolver().episode_confirmed("lin_wan", 3)
    # 只改审核元数据（备注）→ 确认保留
    api.put_episode_look(3, "lin_wan", LookPatch(notes=["看过了"]), store)
    assert store.resolver().episode_confirmed("lin_wan", 3) and _plan(store, 3).owner_confirmed_ref
    # GET → PUT 原样回写整张表 → 确认保留
    api.put_schedule(api.ScheduleReplace(episodes=store.schedule().episodes), store)
    assert store.resolver().episode_confirmed("lin_wan", 3)
    # 改了解析内容 → _merge 清掉确认
    api.put_episode_look(3, "lin_wan", LookPatch(slots={"makeup": ["lw-makeup-heavy"]}), store)
    p = _plan(store, 3)
    assert p.owner_confirmed_at is None and not store.resolver().episode_confirmed("lin_wan", 3)


def test_h1_confirmation_voided_by_wardrobe_edit_and_needs_ref(store, proj):
    store.confirm_episodes("3", "lin_wan", "项目方 OK")
    res = store.resolver()
    item_id = next(i for sl in res.core("lin_wan", 3).slots.values() for i in sl.items)
    it = next(i for i in store.wardrobe().items if i.id == item_id)
    store.upsert_item(WardrobeItem(**{**it.model_dump(), "description": (it.description or "") + "（改过）"}))
    assert not store.resolver().episode_confirmed("lin_wan", 3)       # 集计划没动，但单品内容变了 → 哈希不符
    tl, _ = T.build(proj)
    assert not tl["episodes"]["3"]["look_confirmed"]
    # 有确认时间和哈希、但原话为空 → 不算确认
    store.confirm_episodes("3", "lin_wan", "项目方 OK")
    s = store.schedule()
    s.episodes["3"]["lin_wan"].owner_confirmed_ref = "  "
    store._write("schedule", s)
    assert not store.resolver().episode_confirmed("lin_wan", 3)
    tl, _ = T.build(proj)
    assert not tl["episodes"]["3"]["look_confirmed"]
    with pytest.raises(ValueError):
        store.confirm_episodes("3", "lin_wan", "")


# ------------------------------------------------------------------ M3 每个入镜角色都要确认

def test_m3_sop_requires_every_present_character(tmp_path):
    root = tmp_path / "p"
    (root / "data" / "looks").mkdir(parents=True)
    shots = [{"shot_id": "ep01-S1", "episode": 1, "index": 1, "scene_id": "sk",
              "characters": {"lin_wan": {"present": True}, "gu_chen": {"present": True}},
              "s2_ready": True, "s2_blockers": []}]
    tl = {"source": {"script": "v3"}, "provisional": False, "s1_gate": {"validator_errors": 0, "g3_accepted": True},
          "episodes": {"1": {"look_confirmed": True}}, "shots": shots}     # 旧表：说已确认
    (root / "data" / "state_timeline.json").write_text(json.dumps(tl), encoding="utf-8")
    (root / "data" / "looks" / "schedule.json").write_text(json.dumps({"episodes": {"1": {"lin_wan": {
        "owner_confirmed_at": "t", "owner_confirmed_ref": "可以"}}}}), encoding="utf-8")
    inp = SOP.Inputs(root, root / "data" / "renders_gpu3")
    assert SOP.episode_unconfirmed(inp) == {1: ["gu_chen"]}            # 没有计划 = 未确认
    b = next(x for x in SOP.s2_blockers(inp, shots[0], 1) if x["code"] == "look_unconfirmed:ep01")
    assert "gu_chen" in b["text"] and "confirm 1 gu_chen" in b["cli"]
    ev = SOP.evaluate(inp, [{"id": "ep01-S1", "episode": 1, "index": 1}], project_owner="laptop")
    acts = [a for a in ev["owner_actions"] if a["gate"] == "look"]
    assert [a["character"] for a in acts] == ["gu_chen"]


# ------------------------------------------------------------------ H2 状态表过期 + M4 规范化哈希

def _make_v3(root: Path):
    p = root / "data" / "import" / "script_v2.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    d["sources"][0]["path"] = d["sources"][0]["path"].replace("v2.md", "v3.md")
    p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")


def _inp(root):
    return SOP.Inputs(root, root / "data" / "renders_gpu3")


def test_h2_sop_detects_stale_timeline_and_m4_crlf(proj):
    _make_v3(proj)
    assert _tool("s1_gate").main(["--root", str(proj), "--validator-errors", "0", "--accept", "项目方 OK",
                                  "--no-rebuild"]) == 0
    T.write(proj)
    inp = _inp(proj)
    assert inp.stale == [] and SOP.s1_gate(inp)["passed"]
    # M4：同一份剧本换成 CRLF / 不同缩进 → 哈希与版本不变，S1 绑定仍有效
    p = proj / "data" / "import" / "script_v2.json"
    v0, sha0 = B.bible_version(proj), B.source_hashes(proj)["script"]
    d = json.loads(p.read_text(encoding="utf-8"))
    p.write_bytes(json.dumps(d, ensure_ascii=False, indent=4).replace("\n", "\r\n").encode("utf-8"))
    assert B.source_hashes(proj)["script"] == sha0 and B.bible_version(proj) == v0
    inp = _inp(proj)
    assert inp.stale == [] and SOP.s1_gate(inp)["passed"]
    # 剧本内容真的变了 → 状态表过期：S1/S2 都不算过，命令是重建
    d["episodes"][0]["shots"][0]["img_prompt"] += "（改）"
    p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    inp = _inp(proj)
    assert "script" in inp.stale
    s1 = SOP.s1_gate(inp)
    assert not s1["passed"] and not s1["g3_accepted"] and s1["blockers"][0]["code"] == "timeline_stale"
    assert s1["blockers"][0]["actor"] == "laptop" and s1["blockers"][0]["cli"] == SOP.CLI_TIMELINE
    row = inp.tl_shots["ep01-S1"]
    assert SOP.s2_blockers(inp, row, 1)[0]["code"] == "timeline_stale"
    T.write(proj)
    assert _inp(proj).stale == []


def test_h2_plate_change_marks_timeline_stale(proj):
    d = proj / "assets" / "scenes" / "sk_elevator"
    d.mkdir(parents=True)
    (d / "plate.png").write_bytes(b"png1")
    (d / "manifest.json").write_text(json.dumps({"plate": "plate.png"}), encoding="utf-8")
    T.write(proj)
    assert _inp(proj).stale == []
    (d / "plate.png").write_bytes(b"png2-different")
    assert "plate/sk_elevator" in _inp(proj).stale


def test_h2_wizard_import_triggers_rebuild(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from ns_api import app as app_mod
    from ns_api import project_ctx as PC
    from ns_orch import engine as E
    monkeypatch.setenv("NS_PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.setenv("NS_ORCH_BACKGROUND", "0")
    monkeypatch.setenv("NS_ORCH_SYNC", "1")
    E._live.clear()
    calls = []
    monkeypatch.setattr(T, "schedule_rebuild", lambda root=None, delay=None: calls.append(Path(root)))
    c = TestClient(app_mod.app)
    slug = c.post("/api/projects", json={"name": "雾港来信"}).json()["slug"]
    script = Path(__file__).parent / "fixtures" / "t42" / "雾港来信（剧本和镜头）.md"
    rep = c.post(f"/api/projects/{slug}/script", params={"kind": "script"},
                 files={"file": (script.name, script.read_bytes(), "text/markdown")}).json()
    assert rep["ok"]
    ctx = PC.get_project(slug)
    assert calls and calls[-1] == ctx.root
    assert b"\r\n" not in ctx.script_json.read_bytes()


def test_m4_written_json_uses_lf(store):
    store.confirm_episodes("3", "lin_wan", "项目方 OK")
    assert b"\r\n" not in (store.dir / "schedule.json").read_bytes()


# ------------------------------------------------------------------ M1 / M2 / L2 G4、G5 记录

def _write(p: Path, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def test_m1_g4_revoked_owner_record_is_authoritative(tmp_path):
    root = tmp_path / "p"
    orch = root / "data" / "orchestrator"
    _write(orch / "PIPELINE_LOCKED.json", {"locked_by": "看板", "locked_at": "t", "note": "样片可以"})
    assert SOP.g4_record(_inp(root))["source"].endswith("PIPELINE_LOCKED.json")
    _write(root / SOP.OWNER_GATES, {"g4": {"locked_at": "t", "ref": "锁", "revoked_at": "t2"}})
    assert SOP.g4_record(_inp(root)) is None                       # 撤销 → 不回退到看板记录
    (root / SOP.OWNER_GATES).unlink()
    _write(orch / "PIPELINE_LOCKED.json", {"locked_by": "看板", "locked_at": "t", "note": ""})
    assert SOP.g4_record(_inp(root)) is None                       # 看板记录没有项目方原话
    _write(orch / "state.json", {"episodes": {"1": {"steps": {"accept": {"status": "done", "decided_at": "t"}}}}})
    assert SOP.g5_record(_inp(root), 1) is None
    _write(orch / "state.json", {"episodes": {"1": {"steps": {"accept": {"status": "done", "decided_at": "t",
                                                                          "note": "发布吧"}}}}})
    assert SOP.g5_record(_inp(root), 1)["decision"] == "publish"


def test_m2_g5_rework_is_not_done(tmp_path):
    root = tmp_path / "p"
    (root / "data").mkdir(parents=True)
    inp = _inp(root)
    s1 = {"g3_accepted": True, "blockers": []}
    ep_states = {1: {"g5": {"decision": "rework", "ref": "返工"}, "final": "x.mp4"},
                 2: {"g5": {"decision": "publish", "ref": "好"}, "final": "y.mp4"}}
    g5 = next(g for g in SOP.gates(inp, s1, 1, ep_states) if g["id"] == "G5")
    assert g5["status"] == "blocked" and "1/2" in g5["detail"] and "ep1" in g5["detail"]
    assert [b["episode"] for b in g5["blockers"]] == [1]


def test_l2_owner_tool_g4_checks_and_g5_binds_final(tmp_path):
    tool = _tool("sop_owner")
    root = tmp_path / "p"
    g3 = root / "data" / "renders_gpu3"
    _write(root / "data" / "import" / "script_v2.json",
           {"episodes": [{"number": 1, "shots": [{"index": 1}, {"index": 2}]}, {"number": 2, "shots": [{"index": 1}]}]})
    vid = g3 / "ep01" / "S1" / "takes" / "video_001.mp4"
    vid.parent.mkdir(parents=True)
    vid.write_bytes(b"v1")
    _write(g3 / "ep01" / "S1" / "takes.json", {"takes": [{"stage": "video", "n": 1,
                                                          "file": "renders_gpu3/ep01/S1/takes/video_001.mp4"}],
                                               "active": {"video": 1}})
    good = hashlib.sha256(b"v1").hexdigest()
    qa = {"verdict": "pass", "shots": {"S1": {"verdict": "pass", "video_sha256": good}}}
    _write(g3 / "ep01" / "qa.json", qa)
    with pytest.raises(SystemExit, match="S2 不在"):
        tool.g4(root, g3, 1, "锁", False)                          # 缺一镜
    qa["shots"]["S2"] = {"verdict": "pass"}
    _write(g3 / "ep01" / "qa.json", qa)
    with pytest.raises(SystemExit, match="video_sha256"):
        tool.g4(root, g3, 1, "锁", False)
    qa["shots"]["S2"]["video_sha256"] = "abc"
    qa["shots"]["S1"]["video_sha256"] = "wrong"
    _write(g3 / "ep01" / "qa.json", qa)
    with pytest.raises(SystemExit, match="不一致"):
        tool.g4(root, g3, 1, "锁", False)                          # 当前采用的视频不是验收的那版
    qa["shots"]["S1"]["video_sha256"] = good
    _write(g3 / "ep01" / "qa.json", qa)
    _write(g3 / "ep02" / "qa.json", qa)
    with pytest.raises(SystemExit, match="样片集"):
        tool.g4(root, g3, 2, "锁", False)
    rec = tool.g4(root, g3, 1, "锁", False)
    assert rec["g4"]["video_sha256"] == {"S1": good, "S2": "abc"}
    # G5：发布记录成片 sha；换了 _final → SOP 视为未验收
    final = g3 / "ep01" / "ep01_final.mp4"
    final.write_bytes(b"final-1")
    rec = tool.g5(root, g3, 1, "发布", False)
    assert rec["g5"]["1"]["final_sha256"] == hashlib.sha256(b"final-1").hexdigest()
    assert SOP.g5_record(_inp(root), 1)["decision"] == "publish"
    final.write_bytes(b"final-2-rerendered")
    assert SOP.g5_record(_inp(root), 1) is None


# ------------------------------------------------------------------ M5 并发写 / 建的过程中输入变了

def test_m5_atomic_unique_tmp_and_concurrent_writes(tmp_path):
    p = tmp_path / "d" / "x.json"
    errs = []

    def w(i):
        try:
            for k in range(10):
                T._atomic(p, {"i": i, "k": k, "pad": "x" * 2000})
        except Exception as e:  # noqa: BLE001
            errs.append(e)
    ts = [threading.Thread(target=w, args=(i,)) for i in range(6)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not [e for e in errs if not isinstance(e, PermissionError)]   # Windows 上 replace 偶有占用
    assert json.loads(p.read_text(encoding="utf-8"))["pad"]
    assert not list(p.parent.glob("*.tmp"))


def test_m5_write_rebuilds_when_inputs_change_during_build(proj, monkeypatch):
    real, n = T.build, []

    def build(root=None, previous=None):
        out = real(root, previous)
        n.append(1)
        if len(n) == 1:            # 第一次建的时候有人改了剧本
            p = Path(root) / "data" / "import" / "script_v2.json"
            d = json.loads(p.read_text(encoding="utf-8"))
            d["episodes"][0]["shots"][0]["img_prompt"] += "（并发修改）"
            time.sleep(0.02)
            p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        return out
    monkeypatch.setattr(T, "build", build)
    tl, _ = T.write(proj)
    assert len(n) == 2
    assert T.read_timeline(proj)["source"]["script_sha"] == B.source_hashes(proj)["script"]
    assert not (proj / "data" / ".state_timeline.lock").exists()


def test_m5_stale_lock_is_broken(proj, monkeypatch):
    lock = proj / "data" / ".state_timeline.lock"
    lock.write_text("999999", encoding="utf-8")
    old = time.time() - T.LOCK_STALE_S - 10
    os.utime(lock, (old, old))
    T.write(proj)
    assert T.timeline_path(proj).exists() and not lock.exists()


# ------------------------------------------------------------------ L1 / L7 底板

def test_l1_plate_confirmation_requires_sha(proj):
    d = proj / "assets" / "scenes" / "sk_elevator"
    d.mkdir(parents=True)
    (d / "plate.png").write_bytes(b"png")
    (d / "manifest.json").write_text(json.dumps({"plate": "plate.png", "owner_confirmed_at": "t",
                                                 "owner_confirmed_ref": "可以"}), encoding="utf-8")
    assert T.plate_info(proj, "sk_elevator")["plate_status"] == "candidate"      # 没记 sha 不算确认
    (d / "manifest.json").write_text(json.dumps({"plate": "plate.png", "owner_confirmed_at": "t",
                                                 "owner_confirmed_ref": "可以",
                                                 "plate_sha256": hashlib.sha256(b"png").hexdigest()}),
                                     encoding="utf-8")
    assert T.plate_info(proj, "sk_elevator")["plate_status"] == "owner_confirmed"


def test_l7_inputs_watch_manifest_named_plate(proj):
    d = proj / "assets" / "scenes" / "sk_elevator"
    d.mkdir(parents=True)
    (d / "plate_v2.png").write_bytes(b"a")
    (d / "manifest.json").write_text(json.dumps({"plate": "plate_v2.png"}), encoding="utf-8")
    assert d / "plate_v2.png" in T.input_files(proj)
    before = T.shot_inputs_sha("ep01-S2", proj)
    time.sleep(0.02)
    (d / "plate_v2.png").write_bytes(b"bb-changed")
    assert T.shot_inputs_sha("ep01-S2", proj) != before


# ------------------------------------------------------------------ L3 快照版本 / bible_diff

def test_l3_snapshot_version_matches_compiled_inputs(proj, monkeypatch):
    real, n = PS.compile_all, []
    toml = proj / "config" / "visual_bible.toml"

    def compile_all(root=None, **kw):
        out = real(root, **kw)
        n.append(1)
        if len(n) == 1:            # 编译期间规则变了
            toml.write_text(toml.read_text(encoding="utf-8") + "\n# changed\n[zz_extra]\nx = 1\n", encoding="utf-8")
        return out
    v_before = B.bible_version(proj)
    monkeypatch.setattr(PS, "compile_all", compile_all)
    p = PS.save_snapshot(proj)
    assert len(n) == 2 and p.name == f"{B.bible_version(proj)}.json.gz" != f"{v_before}.json.gz"
    assert not list(p.parent.glob("*.tmp"))


def test_l3_bible_diff_handles_missing_current_snapshot(proj, monkeypatch, capsys):
    tool = _tool("bible_diff")
    monkeypatch.setattr(PS, "load_snapshot", lambda *a, **k: None)
    monkeypatch.setattr(PS, "compile_all", lambda root=None, **kw: {"ep01-S1": {"image_prompt": "x"}})
    assert tool.main(["--root", str(proj)]) == 0
    assert capsys.readouterr().out.strip() == B.bible_version(proj)


# ------------------------------------------------------------------ L4 校色复用绑定源 sha

def test_l4_cc_reuse_requires_source_sha(tmp_path, monkeypatch):
    import sys
    if str(REPO / "services" / "post") not in sys.path:
        sys.path.insert(0, str(REPO / "services" / "post"))
    from ns_post import colormatch as CM
    from ns_post.assemble import qa_gate
    clip = tmp_path / "S1.mp4"
    clip.write_bytes(b"clip-v1")
    out = CM.cc_path(clip)
    out.write_bytes(b"cc")
    s = CM.CcSettings()
    rep = {"settings": s.to_dict(), "source_mtime": clip.stat().st_mtime, "output": "x",
           "source_sha256": CM.file_sha256(clip)}
    out.with_suffix(".json").write_text(json.dumps(rep), encoding="utf-8")
    calls = []
    monkeypatch.setattr(CM, "correct_clip", lambda c, **kw: calls.append(c) or {"output": None})
    assert CM.ensure_cc(clip, s=s)[0] == out and not calls
    st = clip.stat()
    clip.write_bytes(b"clip-v2")                                   # 同大小、同 mtime 也要认出来
    os.utime(clip, ns=(st.st_atime_ns, st.st_mtime_ns))
    CM.ensure_cc(clip, s=s)
    assert calls == [clip]
    # 装配闸门：_cc 必须由 qa.json 验收的那版视频生成
    qa = tmp_path / "qa.json"
    sha = CM.file_sha256(clip)
    qa.write_text(json.dumps({"verdict": "pass", "shots": {"S1": {"verdict": "pass", "video_sha256": sha}}}),
                  encoding="utf-8")
    src = {"kind": "video", "path": str(clip), "path_cc": str(out), "color_match": {"path": {"source_sha256": "old"}}}
    ok, why = qa_gate(qa, [{"index": 1}], [src])
    assert not ok and any("_cc" in w for w in why)
    src["color_match"]["path"]["source_sha256"] = sha
    assert qa_gate(qa, [{"index": 1}], [src]) == (True, [])


# ------------------------------------------------------------------ L5 / L6

def test_l5_bad_toml_clear_error_and_datetime(proj):
    toml = proj / "config" / "visual_bible.toml"
    good = toml.read_text(encoding="utf-8")
    toml.write_text(good + "\n[broken\n", encoding="utf-8")
    with pytest.raises(ValueError, match="TOML"):
        B.bible_version(proj)
    toml.write_text(good + "\n[zz_meta]\nupdated = 2026-10-30T12:00:00\n", encoding="utf-8")
    assert len(B.bible_version(proj)) == B.VERSION_LEN


def test_l6_s1_gate_without_script_writes_nothing(tmp_path):
    root = tmp_path / "p"
    (root / "data" / "import").mkdir(parents=True)
    assert _tool("s1_gate").main(["--root", str(root), "--accept", "项目方 OK", "--no-rebuild"]) == 2
    assert not (root / T.S1_GATE).exists()
