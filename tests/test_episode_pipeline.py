"""逐集流水线（K-OPS-W12，WORKFLOW，总调度 22:06）：认 CHANGELOG 的“HOLLYWOOD 导入 epNN”；作业对不上不派；
准备好的集才进 producer only；别的集导入不会让已准备的集重做（按集内容哈希）。全部打桩、写临时目录。"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/autopilot"))
import episode_pipeline as EP  # noqa: E402


def test_imported_eps_parse():
    txt = "- 21:30 HOLLYWOOD 导入 ep01\n- x\n- 21:50 HOLLYWOOD导入 ep02（重导）\n- 22:00 HOLLYWOOD 导入 ep01\n"
    assert EP.imported_eps(txt) == [1, 2]


def _setup(monkeypatch, tmp_path, mismatch=False, red=False):
    monkeypatch.setattr(EP, "ROOT", tmp_path)
    monkeypatch.setattr(EP, "OUT", tmp_path / "out")
    (tmp_path / "data/import").mkdir(parents=True)
    (tmp_path / "data/producer").mkdir(parents=True)
    (tmp_path / "data/import/script_v2.json").write_text(json.dumps(
        {"episodes": [{"number": 1, "shots": [{"index": 1}, {"index": 2}]}, {"number": 2, "shots": [{"index": 1}]}]}), encoding="utf-8")
    (tmp_path / "data/producer/control.json").write_text(json.dumps({"paused": False, "only": []}), encoding="utf-8")

    class IJ:
        @staticmethod
        def rebuild_first_frame_jobs(run, write=True):
            return {"ok": True}

        @staticmethod
        def jobs_vs_import(run):
            return {"ok": not mismatch, "missing": ["ep01-S2"] if mismatch else [], "extra": [], "stale_sha": []}
    monkeypatch.setattr(EP, "_image_jobs", lambda: IJ)
    import full_redo as FR
    calls = {}
    monkeypatch.setattr(FR, "make_plan", lambda: {})
    monkeypatch.setattr(FR, "apply", lambda eps=None, **k: calls.setdefault("apply", eps) or {"sent": 2})
    monkeypatch.setattr(FR, "reset_redo", lambda shots=None, by="": calls.setdefault("reset", shots) and {"changed": 0} or {"changed": 0})
    monkeypatch.setattr(FR, "import_sha_now", lambda: "sha1")
    monkeypatch.setattr(FR, "image_jobs_green", lambda: {"ok": not red, "tests": "red" if red else "ok"})
    monkeypatch.setattr(EP, "owner_of_ep", lambda ep: "laptop")          # 本测试不连服务器
    return calls


def test_prepare_sets_only_and_calls_redo(monkeypatch, tmp_path):
    calls = _setup(monkeypatch, tmp_path)
    kicks = []
    monkeypatch.setattr(EP, "kickoff", lambda st: kicks.append(1) or st.setdefault("kickoff", {"at": "x"}))
    st = {}
    rec = EP.prepare(1, st)
    assert rec["status"] == "prepared" and calls["apply"] == {1} and calls["reset"] == ["ep01-S1", "ep01-S2"]
    r = json.loads((tmp_path / "data/autopilot/ready_episodes.json").read_text(encoding="utf-8"))
    assert r["episodes"]["1"]["shots"] == ["ep01-S1", "ep01-S2"] and r["by"] == "WORKFLOW episode_pipeline"
    c = json.loads((tmp_path / "data/producer/control.json").read_text(encoding="utf-8"))
    assert c["only"] == []                                # NETFIX 接口：不再直接改 control.json 的 only（dispatch.py 算）
    EP.prepare(2, st)
    assert kicks == [1]                                   # 预先授权的一次性开工（重启 producer / 看图 / resume）只做一次


def test_prepare_refuses_on_jobs_mismatch(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, mismatch=True)
    st = {}
    assert EP.prepare(1, st)["status"] == "jobs_mismatch"
    c = json.loads((tmp_path / "data/producer/control.json").read_text(encoding="utf-8"))
    assert c["only"] == []


def test_hold_blocks_prepare(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    st = {"holds": {"1": {"note": "等造型换图"}}}
    assert EP.prepare(1, st)["status"] == "hold"


def test_ep_hash_ignores_other_episodes(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    h1 = EP.ep_hash(1)
    p = tmp_path / "data/import/script_v2.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    d["episodes"][1]["shots"].append({"index": 2})          # 只改 ep02
    p.write_text(json.dumps(d), encoding="utf-8")
    assert EP.ep_hash(1) == h1 and EP.ep_hash(2)


def test_prepare_refuses_when_image_jobs_red(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, red=True)
    st = {}
    assert EP.prepare(1, st)["status"] == "jobs_red"
    c = json.loads((tmp_path / "data/producer/control.json").read_text(encoding="utf-8"))
    assert c["only"] == []


def test_remote_merge_keeps_newer_server_objects(tmp_path):
    """NETFIX 接口：master_rejects 推到服务器按对象合并——笔记本 reset 过的对象要盖过去，服务器上更晚改过的对象不被旧值盖回"""
    import resident_sync as RS
    dst = tmp_path / "data/producer/master_rejects.json"
    dst.parent.mkdir(parents=True)
    dst.write_text(json.dumps({"first:ep01-S1": {"at": "2026-11-01T19:27:00", "wait": None},
                               "first:ep02-S1": {"at": "2026-11-01T23:00:00", "cleared": {"at": "2026-11-01T23:00:00"}}}), encoding="utf-8")
    src = tmp_path / "new.json"
    src.write_text(json.dumps({"first:ep01-S1": {"at": "2026-11-01T22:30:00", "wait": None, "plan": ["frame_v9"]},
                               "first:ep02-S1": {"at": "2026-11-01T19:27:00"},
                               "first:ep03-S1": {"at": "2026-11-01T22:30:00"}}), encoding="utf-8")
    code = RS.REMOTE_MERGE.replace("__R__", str(tmp_path).replace("\\", "/"))
    import sys as _s
    old = _s.argv
    _s.argv = ["m", "data/producer/master_rejects.json", str(src)]
    try:
        exec(compile(code, "remote_merge", "exec"), {})
    finally:
        _s.argv = old
    out = json.loads(dst.read_text(encoding="utf-8"))
    assert out["first:ep01-S1"].get("plan") == ["frame_v9"]          # 笔记本更晚 → 用笔记本的
    assert "cleared" in out["first:ep02-S1"]                          # 服务器更晚 → 不盖
    assert "first:ep03-S1" in out


def test_candidate_eps_from_events_and_import(monkeypatch, tmp_path):
    """总调度 02:0x：导入事件（imports.jsonl）触发；导入稿的集兜底；CHANGELOG 不再作为触发；事件按 run 区分（§0.1）"""
    _setup(monkeypatch, tmp_path)
    import import_events as IE
    monkeypatch.setattr(IE, "EVENTS", tmp_path / "imports.jsonl")
    monkeypatch.setattr(EP, "CHANGELOG", tmp_path / "CHANGELOG.md")
    (tmp_path / "CHANGELOG.md").write_text("- HOLLYWOOD 导入 ep07\n", encoding="utf-8")
    assert EP.candidate_eps() == [1, 2]                     # 只看到导入稿；CHANGELOG 的 ep07 不触发
    IE.append_import([5], by="PRODUCER import_staged", script=tmp_path / "data/import/script_v2.json")
    IE.append_import([3], by="PRODUCER import_staged", script=tmp_path / "data/import/script_v2.json", run_id="newshow_v1")
    assert EP.candidate_eps() == [5, 1, 2]                  # 别的 run 的事件不混进 primary
    ev = IE.read_events()
    assert ev[0]["run_id"] and ev[1]["run_id"] == "newshow_v1" and len(ev[0]["script_sha"]) == 64
    assert IE.episodes_imported(run_id="newshow_v1") == [3]


def test_run_dir_from_project_registry(monkeypatch, tmp_path):
    """DISTILL ①：运行目录按 asset_refs.json 里命中的项目取，不写死 series10_v1"""
    monkeypatch.setattr(EP, "ROOT", tmp_path)
    (tmp_path / "config/recipes").mkdir(parents=True)
    (tmp_path / "data/import").mkdir(parents=True)
    (tmp_path / "config/recipes/asset_refs.json").write_text(json.dumps({"projects": {
        "series10_v1": {"run_dir": "data/pipeline/runs/series10_v1"}, "newshow_v1": {"run_dir": "data/pipeline/runs/newshow_v1"}}}), encoding="utf-8")
    (tmp_path / "data/import/script_v2.json").write_text(json.dumps({"sources": [{"path": "data/staging_v3/merged/x_newshow_v1_ep01.md"}]}), encoding="utf-8")
    assert EP.run_dir() == tmp_path / "data/pipeline/runs/newshow_v1"
    (tmp_path / "config/pipeline").mkdir(parents=True)
    (tmp_path / "config/pipeline/run.json").write_text(json.dumps({"run_id": "show3_v2"}), encoding="utf-8")
    assert EP.run_dir() == tmp_path / "data/pipeline/runs/show3_v2"          # 配置优先


def test_second_run_prepares_separately_without_touching_primary(monkeypatch, tmp_path):
    """§0.1 多剧并行：新 run 的 ep01-S1 与 primary 的 ep01-S1 同名——作业 / ready 各在各的目录，ready 镜号带 run 前缀，primary 文件不动"""
    _setup(monkeypatch, tmp_path)
    import runs as RN
    monkeypatch.setattr(RN, "ROOT", tmp_path)
    (tmp_path / "config/pipeline").mkdir(parents=True)
    (tmp_path / "config/pipeline/runs.json").write_text(json.dumps({"primary": "series10_v1", "runs": {
        "series10_v1": {"priority": 0, "status": "producing"}, "newshow_v1": {"priority": 10, "status": "producing"}}}), encoding="utf-8")
    (tmp_path / "data/import/runs/newshow_v1").mkdir(parents=True)
    (tmp_path / "data/import/runs/newshow_v1/script_v2.json").write_text(json.dumps(
        {"episodes": [{"number": 1, "shots": [{"index": 1}, {"index": 2}, {"index": 3}]}]}), encoding="utf-8")
    seen = {}

    class IJ:
        @staticmethod
        def rebuild_first_frame_jobs(rd, project=None, write=True, run=None):
            seen["rebuild"] = (str(rd), run)
            return {}

        @staticmethod
        def jobs_vs_import(rd, run=None):
            return {"ok": True, "missing": [], "extra": [], "stale_sha": []}
    monkeypatch.setattr(EP, "_image_jobs", lambda: IJ)
    import import_events as IE
    monkeypatch.setattr(IE, "EVENTS", tmp_path / "imports.jsonl")
    primary_ready = tmp_path / "data/autopilot/ready_episodes.json"
    st = {}
    EP.watch_other_runs(st)
    assert seen["rebuild"][1] == "newshow_v1" and seen["rebuild"][0].endswith("newshow_v1")
    r = json.loads((tmp_path / "data/autopilot/runs/newshow_v1/ready_episodes.json").read_text(encoding="utf-8"))
    assert r["episodes"]["1"]["shots"] == ["newshow_v1/ep01-S1", "newshow_v1/ep01-S2", "newshow_v1/ep01-S3"]
    assert not primary_ready.exists()                                  # primary 的 ready 没被碰
    assert st["runs"]["newshow_v1"]["eps"]["1"]["status"] == "prepared" and "eps" not in {k for k in st if k != "runs"}
    assert RN.obj_id("newshow_v1", "first", "ep01-S1") == "newshow_v1/first:ep01-S1" and RN.obj_id("series10_v1", "first", "ep01-S1") == "first:ep01-S1"
