"""W26 冒烟门自测：桩掉 GPU / 网络 / 子进程，只验证八门判定逻辑、隔离清目录、结构指纹、nsfs.smoke/1 schema 与退出码。
  .venv/Scripts/python.exe -m pytest eval -q
"""
from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
_sp = importlib.util.spec_from_file_location("smoke_under_test", HERE / "smoke.py")
S = importlib.util.module_from_spec(_sp)
_sp.loader.exec_module(S)


# ------------------------------------------------------------------ 每门“全好”的证据（桩）
def good_facts() -> dict:
    refs = {str(n): {"cast": ["祁念", "唐瑶"], "refs": ["a.png"], "face_files": ["f.png"], "missing_refs": [], "error": None}
            for n in (1, 2, 3)}
    rk = {f"{k}:ep01-S{n}": {"ok": True, "take": 1, "refs": ["f.png"], "why": ""} for n in (1, 2, 3) for k in ("first", "last")}
    have = {str(n): [f"x{n}"] for n in (1, 2, 3)}
    fp = {"files": {"a": "1"}, "sha": "abc"}
    return {
        "G1": {"api_status": 200, "procs": {k: True for k in S.PROCS}, "vqa_8870": True, "config_errors": [], "import_errors": []},
        "G2": {"validate_blocks": ["QW-E2", "QW-E3"], "import_rc": 0, "shots": 3, "assets_ready": True, "prompts": {"ok": True}},
        "G3": {"refs": refs, "render_refs": rk},
        "G4": {"rc": 0, "first": have, "last": have, "video": have, "oom": [], "timeouts": []},
        "G5": {"rc": 0, "mp4": "data/episodes/smoke_v2/ep01.mp4", "placeholders": 0},
        "G6": {"want": {"duration": 15, "width": 1080, "height": 1920, "fps": 24, "duration_tol_s": 2},
               "probe": {"duration": 15.8, "width": 1080, "height": 1920, "fps": 24.0}},
        "G7": {"residue_before": [], "first": fp, "second": dict(fp), "first_g2_ok": True, "second_g2_ok": True},
        "G8": {"owner_points": [], "queue_status": 200, "pipeline_complete": True},
    }


@pytest.mark.parametrize("gid", S.GATES)
def test_each_gate_passes_on_good_evidence(gid):
    ok, why = S.JUDGES[gid](good_facts()[gid])
    assert ok, why


BREAKS = [
    ("G1", lambda f: f.update(api_status=0), "8800"),
    ("G1", lambda f: f["procs"].update(tunnel_supervisor=False), "tunnel_supervisor"),
    ("G1", lambda f: f.update(vqa_8870=False), "8870"),
    ("G1", lambda f: f.update(config_errors=["config/x.json: ValueError"]), "配置"),
    ("G1", lambda f: f.update(import_errors=["ns_render.pipeline: ImportError"]), "import"),
    ("G2", lambda f: f.update(validate_blocks=["QW-E2", "QW-E9"]), "QW-E9"),
    ("G2", lambda f: f.update(import_rc=3, import_why="v1_leak"), "v1_leak"),
    ("G2", lambda f: f.update(shots=2), "镜数"),
    ("G2", lambda f: f.update(assets_ready=False, assets_why="5 个缺口"), "资产就绪"),
    ("G2", lambda f: f.update(prompts={"ok": False, "why": "镜2 preflight"}), "提示词"),
    ("G3", lambda f: f["refs"]["2"].update(error="AttributeError"), "镜2"),
    ("G3", lambda f: f["refs"]["1"].update(face_files=[]), "身份脸"),
    ("G3", lambda f: f["refs"]["3"].update(missing_refs=["gone.png"]), "gone.png"),
    ("G3", lambda f: f.update(render_refs=None), "G4 没出图"),
    ("G3", lambda f: f["render_refs"].update({"last:ep01-S3": {"ok": False, "why": "参考文件列表为空"}}), "last:ep01-S3"),
    ("G3", lambda f: f["render_refs"].pop("first:ep01-S2"), "first:ep01-S2"),
    ("G4", lambda f: f.update(skipped="前置没过"), "未执行"),
    ("G4", lambda f: f.update(rc=124, timeout_s=1500), "超时"),
    ("G4", lambda f: f["video"].update({"2": []}), "视频"),
    ("G4", lambda f: f.update(oom=["CUDA out of memory"]), "OOM"),
    ("G5", lambda f: f.update(rc=1, tail="boom"), "退出码"),
    ("G5", lambda f: f.update(mp4=None), "mp4"),
    ("G5", lambda f: f.update(placeholders=2), "占位"),
    ("G6", lambda f: f["probe"].update(duration=18.5), "时长"),
    ("G6", lambda f: f["probe"].update(width=720, height=1280), "分辨率"),
    ("G6", lambda f: f["probe"].update(fps=30.0), "帧率"),
    ("G6", lambda f: f.update(probe={}, err="no stream"), "ffprobe"),
    ("G7", lambda f: f.update(residue_before=["data/renders/smoke_v2"]), "残留"),
    ("G7", lambda f: f.update(second={"files": {"a": "2"}, "sha": "zzz"}), "不一致"),
    ("G7", lambda f: f.update(second_g2_ok=False), "残留"),
    ("G8", lambda f: f.update(owner_points=["owner_queue first:ep01-S1"]), "项目方"),
    ("G8", lambda f: f.update(queue_status=0), "owner_queue"),
    ("G8", lambda f: f.update(pipeline_complete=False), "流水线"),
]


@pytest.mark.parametrize("gid,breaker,word", BREAKS)
def test_each_failure_is_caught_with_reason(gid, breaker, word):
    f = good_facts()[gid]
    breaker(f)
    ok, why = S.JUDGES[gid](f)
    assert not ok
    assert word in why


def test_g6_duration_tolerance_edges():
    f = good_facts()["G6"]
    f["probe"]["duration"] = 17.0          # 15 + 2 = 边界内
    assert S.judge_g6(f)[0]
    f["probe"]["duration"] = 17.01
    assert not S.judge_g6(f)[0]


# ------------------------------------------------------------------ 隔离清目录 / 模板 / 指纹（临时目录）
def _mk(root: Path, rel: str, text: str = "x") -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def test_quarantine_moves_not_deletes(tmp_path):
    _mk(tmp_path, "data/renders/smoke_v2/ep01/S1/takes.json", "{}")
    _mk(tmp_path, "data/pipeline/runs/smoke_v2/P4_ep01.md", "old")
    moved = S.quarantine_smoke(tmp_path, "T1")
    assert set(moved) == {"data/renders/smoke_v2", "data/pipeline/runs/smoke_v2"}
    assert not any((tmp_path / d).exists() for d in S.SMOKE_DIRS)
    q = tmp_path / "data/quarantine/smoke_v2/T1"
    assert (q / "data__renders__smoke_v2/ep01/S1/takes.json").is_file()          # 文件还在（只隔离）
    assert (q / "data__pipeline__runs__smoke_v2/P4_ep01.md").read_text(encoding="utf-8") == "old"


def test_seed_from_template_is_clean(tmp_path):
    smoke = tmp_path / "eval/smoke"
    _mk(smoke, "template/pipeline_run/P1_storyline.json", "{}")
    _mk(smoke, "template/pipeline_run/looks/looks.json", "{}")
    _mk(smoke, "P4_smoke.md", "# fixture")
    files = S.seed_from_template(tmp_path, smoke)
    assert "data/pipeline/runs/smoke_v2/P4_ep01.md" in files
    assert (tmp_path / "data/pipeline/runs/smoke_v2/looks/looks.json").is_file()


def test_fingerprint_ignores_timestamps_but_sees_content(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    for root, at, stamp in ((a, "2026-11-03T10:00:00", "20261103-100000"), (b, "2026-11-03T11:11:11", "20261103-111111")):
        _mk(root, "data/import/runs/smoke_v2/script_v2.json", json.dumps({"at": at, "episodes": [{"number": 1}]}))
        _mk(root, f"data/import/runs/smoke_v2/backups/script_v2.{stamp}.json", json.dumps({"x": 1, "created_at": at}))
    fa, fb = S.tree_fingerprint(a, S.STRUCT_DIRS), S.tree_fingerprint(b, S.STRUCT_DIRS)
    assert fa["sha"] == fb["sha"] and len(fa["files"]) == 2
    _mk(b, "data/import/runs/smoke_v2/script_v2.json", json.dumps({"at": "z", "episodes": [{"number": 2}]}))
    assert S.tree_fingerprint(b, S.STRUCT_DIRS)["sha"] != fa["sha"]


T0 = 1793692000.0          # 桩里的 G4 窗口起点（epoch）


def _iso(t: float) -> str:
    from datetime import datetime
    return datetime.fromtimestamp(t).strftime("%Y-%m-%dT%H:%M:%S")


def _stub_render_tree(root: Path, *, t: float = T0 + 60, lane: str = "gpu33:1") -> None:
    """本次窗口 producer 自己出的 3 镜首/尾帧 + 视频：log ev=rendered（带 t / take / lane）+ takes.json（producer.lane、references）"""
    log = [{"t": t, "ev": "rendered", "obj": f"smoke_v2/{k}:ep01-S{n}", "lane": lane, "take": 1}
           for n in (1, 2, 3) for k in ("first", "last")]
    _mk(root, "data/producer/runs/smoke_v2/log.jsonl", "\n".join(json.dumps(x) for x in log) + "\n")
    _mk(root, "assets_v2/characters/lead_f/face/lead_f_face_v1.png")
    _mk(root, "data/pipeline/runs/smoke_v2/images/refboards/board.png")
    vid = root / "data/pipeline/runs/smoke_v2/video/clips/ep01"
    for n in (1, 2, 3):
        i, l = f"renders/smoke_v2/ep01/S{n}/takes/image_001.png", f"renders/smoke_v2/ep01/S{n}/takes/last_001.png"
        _mk(root, "data/" + i)
        _mk(root, "data/" + l)
        prod = {"attempt": 1, "rung": "base", "lane": lane}
        takes = {"takes": [
            {"n": 1, "stage": "image", "file": i, "created_at": _iso(t), "producer": prod,
             "references": ["assets_v2/characters/lead_f/face/lead_f_face_v1.png", "data/pipeline/runs/smoke_v2/images/refboards/board.png"]},
            {"n": 1, "stage": "last", "file": l, "created_at": _iso(t), "producer": prod,
             "references": [f"data/{i} (image v1)", "assets_v2/characters/lead_f/face/lead_f_face_v1.png"]}]}
        _mk(root, f"data/renders/smoke_v2/ep01/S{n}/takes.json", json.dumps(takes))
        _mk(vid, f"ep01-S{n}__h3.mp4")


FACES = {str(n): ["assets_v2/characters/lead_f/face/lead_f_face_v1.png"] for n in (1, 2, 3)}


def test_render_refs_and_outputs_from_stub_tree(tmp_path):
    assert S.render_refs(tmp_path) is None                              # 没出图 = None（G3 判失败）
    _stub_render_tree(tmp_path)
    rr = S.render_refs(tmp_path, faces=FACES, t0=T0)
    assert len(rr) == 6 and all(r["ok"] for r in rr.values()), rr
    assert rr["last:ep01-S2"]["refs"][0] == "data/renders/smoke_v2/ep01/S2/takes/image_001.png"   # “ (image v1)” 后缀去掉
    assert S.judge_g3({"refs": good_facts()["G3"]["refs"], "render_refs": rr})[0]
    out = S.scan_g4_outputs(tmp_path, t0=T0)
    assert all(out[k][str(n)] for k in ("first", "last", "video") for n in (1, 2, 3)) and out["excluded_count"] == 0
    assert S.judge_g4({"rc": 0, **out})[0]
    _mk(tmp_path, "data/producer/runs/smoke_v2/log.jsonl", '{"ev": "video_err", "error": "CUDA out of memory"}\n')
    assert S.scan_g4_outputs(tmp_path)["oom"]


def test_g3_needs_refs_nonempty_existing_and_identity_face(tmp_path):
    _stub_render_tree(tmp_path)
    p = tmp_path / "data/renders/smoke_v2/ep01/S1/takes.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    d["takes"][0]["references"] = []                                  # S1 首帧：参考列表空
    d["takes"][1]["references"] = ["assets_v2/gone.png"]            # S1 尾帧：参考文件不存在
    p.write_text(json.dumps(d), encoding="utf-8")
    rr = S.render_refs(tmp_path, faces=FACES, t0=T0)
    assert not rr["first:ep01-S1"]["ok"] and "为空" in rr["first:ep01-S1"]["why"]
    assert not rr["last:ep01-S1"]["ok"] and "gone.png" in rr["last:ep01-S1"]["why"]
    other = {"2": ["assets_v2/characters/ch_tang_yao/face/x.png"]}  # 编译侧解析的身份脸没进 S2 出图参考
    assert "身份脸" in S.render_refs(tmp_path, faces=other, t0=T0)["first:ep01-S2"]["why"]
    ok, why = S.judge_g3({"refs": good_facts()["G3"]["refs"], "render_refs": rr})
    assert not ok and "first:ep01-S1" in why and "last:ep01-S1" in why


def test_g3_refs_from_asset_refs_slots(tmp_path):
    """takes 没有 references、只有 refs / asset_refs.slots[].file 也算（任务 W32-1：take.asset_refs / refs）"""
    _stub_render_tree(tmp_path)
    p = tmp_path / "data/renders/smoke_v2/ep01/S3/takes.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    d["takes"][0].pop("references")
    d["takes"][0]["asset_refs"] = {"slots": [{"index": 1, "kind": "face", "file": "assets_v2/characters/lead_f/face/lead_f_face_v1.png"}]}
    d["takes"][1].pop("references")
    d["takes"][1]["refs"] = ["assets_v2/characters/lead_f/face/lead_f_face_v1.png"]
    p.write_text(json.dumps(d), encoding="utf-8")
    rr = S.render_refs(tmp_path, faces=FACES, t0=T0)
    assert rr["first:ep01-S3"]["ok"] and rr["last:ep01-S3"]["ok"], rr


def test_g3_g4_exclude_adopted_v1_and_old_window(tmp_path):
    """W26b 复现：adopt 把 V1 旧图（data/renders/ep01/…）登记进 smoke_v2 takes → G4 不算、G3 不算"""
    _stub_render_tree(tmp_path)
    p = tmp_path / "data/renders/smoke_v2/ep01/S1/takes.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    _mk(tmp_path, "data/renders/ep01/S1/takes/image_002_pipeline_ff3ef653.png")
    d["takes"] = [  # 只剩 adopt 来的 V1 版本 + 一个窗口外的旧版本
        {"n": 2, "stage": "image", "file": "renders/ep01/S1/takes/image_002_pipeline_ff3ef653.png", "created_at": _iso(T0 + 10),
         "references": ["assets_v2/characters/lead_f/face/lead_f_face_v1.png"],
         "params": {"origin": {"adopted_by": "PRODUCER", "lane": "gpu33:1"}}},
        {"n": 3, "stage": "image", "file": "renders/smoke_v2/ep01/S1/takes/image_001.png", "created_at": _iso(T0 + 10),
         "references": ["assets_v2/characters/lead_f/face/lead_f_face_v1.png"]},                       # producer.lane 空
        {"n": 4, "stage": "last", "file": "renders/smoke_v2/ep01/S1/takes/last_001.png", "created_at": _iso(T0 - 3600),
         "producer": {"lane": "gpu33:1"}, "references": ["assets_v2/characters/lead_f/face/lead_f_face_v1.png"]},  # 窗口外
        {"n": 5, "stage": "last", "file": "renders/smoke_v2/ep01/S1/takes/last_001.png", "created_at": _iso(T0 + 10),
         "producer": {"lane": "gpu33:1"}, "references": ["assets_v2/characters/lead_f/face/lead_f_face_v1.png"]},  # log 里是 adopt
    ]
    p.write_text(json.dumps(d), encoding="utf-8")
    log = tmp_path / "data/producer/runs/smoke_v2/log.jsonl"
    extra = [{"t": T0 + 5, "ev": "adopt", "obj": "last:ep01-S1", "take": 5, "ok": True},
             {"t": T0 + 6, "ev": "rendered", "obj": "last:ep01-S1", "take": 5, "lane": "gpu33:1"},
             {"t": T0 - 3600, "ev": "rendered", "obj": "first:ep01-S1", "take": 3, "lane": "gpu33:1"}]   # 窗口外的 rendered
    log.write_text("".join(json.dumps(x) + "\n" for x in extra), encoding="utf-8")
    out = S.scan_g4_outputs(tmp_path, t0=T0)
    assert out["first"]["1"] == [] and out["last"]["1"] == []
    ex = " ".join(out["excluded"])
    assert "不在 data/renders/smoke_v2/" in ex and "adopt" in ex and "早于 t0" in ex and "producer.lane" in ex
    ok, why = S.judge_g4({"rc": 0, **out})
    assert not ok and "首帧 缺镜 ['1'" in why and "不算" in why
    rr = S.render_refs(tmp_path, faces=FACES, t0=T0)
    assert not rr["first:ep01-S1"]["ok"] and "本次窗口没有" in rr["first:ep01-S1"]["why"]
    assert not rr["last:ep01-S1"]["ok"] and "adopt" in rr["last:ep01-S1"]["why"]


def test_g4_video_clip_outside_window_not_counted(tmp_path):
    import os
    _stub_render_tree(tmp_path)
    clip = tmp_path / "data/pipeline/runs/smoke_v2/video/clips/ep01/ep01-S2__h3.mp4"
    os.utime(clip, (T0 - 3600, T0 - 3600))
    out = S.scan_g4_outputs(tmp_path, t0=T0)
    assert out["video"]["2"] == [] and out["video"]["1"]
    assert "视频 缺镜 ['2']" in S.judge_g4({"rc": 0, **out})[1]


# ------------------------------------------------------------------ W32-3：:8800 探测 30 s × 重试 2 次（G1 / G8）
def test_http_retry_until_200(monkeypatch):
    calls = []
    seq = iter([(0, None, "TimeoutError: timed out"), (0, None, "TimeoutError: timed out"), (200, {"ok": 1}, "")])
    monkeypatch.setattr(S, "http_json", lambda url, timeout=10.0: (calls.append(timeout), next(seq))[1])
    monkeypatch.setattr(S.time, "sleep", lambda s: None)
    st, d, err, n = S.http_json_retry("http://127.0.0.1:8800/x")
    assert (st, n) == (200, 3) and calls == [30.0, 30.0, 30.0]
    assert S.API_TIMEOUT_S == 30.0 and S.API_RETRIES == 2


def test_http_retry_gives_up_after_three(monkeypatch):
    calls = []
    monkeypatch.setattr(S, "http_json", lambda url, timeout=10.0: (calls.append(url), (0, None, "URLError: refused"))[1])
    monkeypatch.setattr(S.time, "sleep", lambda s: None)
    assert S.http_json_retry("http://127.0.0.1:8800/x")[3] == 3 and len(calls) == 3


def test_g1_g8_probe_8800_with_retry(monkeypatch, tmp_path):
    seen = []
    def fake(url, timeout=10.0):
        seen.append((url.split("?")[0].rsplit(":", 1)[-1], timeout))
        if ":8800" in url and sum(1 for u, _ in seen if u.startswith("8800")) < 3:
            return 0, None, "TimeoutError: timed out"        # 冷启动：前两次超时
        return 200, {"items": []}, ""
    monkeypatch.setattr(S, "http_json", fake)
    monkeypatch.setattr(S.time, "sleep", lambda s: None)
    monkeypatch.setattr(S, "sh", lambda cmd, timeout, env=None: (0, "autoflow_resident.py tunnel_supervisor.py SMOKE_IMPORT_BAD []"))
    monkeypatch.setattr(S, "ROOT", tmp_path)
    f1 = S.collect_g1()
    assert f1["api_status"] == 200 and f1["api_attempts"] == 3 and S.judge_g1(f1)[0]
    assert [t for u, t in seen if u.startswith("8800")] == [30.0, 30.0, 30.0]
    seen.clear()
    monkeypatch.setattr(S, "sop_gate_mod", lambda: type("SG", (), {"stage_view": staticmethod(lambda run, root: {"episodes": []})}))
    pts, st, err = S.owner_points(tmp_path)
    assert st == 200 and pts == [] and len(seen) == 3
    f = {**good_facts()["G1"], "api_status": 0, "api_err": "TimeoutError", "api_attempts": 3, "api_timeout_s": 30.0}
    assert "试 3 次 × 30s" in S.judge_g1(f)[1]


# ------------------------------------------------------------------ 主流程（全部采集桩掉）+ schema + 退出码
def _stub_collectors(monkeypatch, facts: dict, tmp_path: Path):
    monkeypatch.setattr(S, "collect_g1", lambda: facts["G1"])
    monkeypatch.setattr(S, "collect_g2", lambda: dict(facts["G2"], shot_seconds=[4, 5, 6]))
    monkeypatch.setattr(S, "collect_g3_compile", lambda: {"refs": facts["G3"]["refs"]})
    monkeypatch.setattr(S, "render_refs", lambda root=None, faces=None, t0=None: facts["G3"]["render_refs"])
    monkeypatch.setattr(S, "collect_g4", lambda ok, why: facts["G4"] if ok else {"skipped": why})
    monkeypatch.setattr(S, "collect_g5", lambda ok, why: facts["G5"] if ok else {"skipped": why})
    monkeypatch.setattr(S, "collect_g6", lambda g5, secs: facts["G6"] if g5.get("mp4") else {"skipped": "no mp4"})
    monkeypatch.setattr(S, "quarantine_smoke", lambda root, stamp, dirs=None: [])
    monkeypatch.setattr(S, "seed_from_template", lambda root, smoke=None: [])
    monkeypatch.setattr(S, "tree_fingerprint", lambda root, dirs: {"files": {"a": "1"}, "sha": "abc"})
    monkeypatch.setattr(S, "owner_points", lambda root=None: (facts["G8"]["owner_points"], facts["G8"]["queue_status"], ""))
    monkeypatch.setattr(S, "code_sha", lambda: "deadbee")
    monkeypatch.setattr(S, "ROOT", tmp_path)        # 残留检查看临时根（空）


def test_run_all_eight_of_eight_schema(monkeypatch, tmp_path):
    _stub_collectors(monkeypatch, good_facts(), tmp_path)
    d = S.run_all("20261103-0000")
    assert S.validate_result(d) == []
    assert [g["id"] for g in d["gates"]] == S.GATES
    assert d["score"] == 1.0 and d["passed"] == 8 and d["schema"] == "nsfs.smoke/1"
    p = S.write_result(d, tmp_path / "results")
    back = json.loads(p.read_text(encoding="utf-8"))
    assert p.name == "20261103-0000.json" and back["code_sha"] == "deadbee" and back["run_id"] == "smoke_v2"
    assert "通过" in S.table(d)


def test_run_all_cascade_and_exit_code(monkeypatch, tmp_path):
    facts = good_facts()
    facts["G2"]["assets_ready"] = False                  # G2 坏 → G4/G5/G6 未执行、G8 无法证明
    facts["G3"]["render_refs"] = None
    _stub_collectors(monkeypatch, facts, tmp_path)
    monkeypatch.setattr(S, "write_result", lambda d, out_dir=None: tmp_path / "r.json")
    monkeypatch.setattr(S, "run_all", (lambda real: (lambda stamp: real(stamp)))(S.run_all))
    rc = S.main(["run"])
    assert rc == 6                                        # G2 G3 G4 G5 G6 G8 失败；G1 G7 过


def test_validate_result_rejects_bad_shapes():
    d = {"schema": "nsfs.smoke/1", "gates": [{"id": "G1", "ok": True, "secs": 1, "evidence": {}}], "score": 1.0,
         "total_secs": 1, "run_id": "smoke_v2", "code_sha": "x", "notes": []}
    bad = S.validate_result(d)
    assert any("gates" in b for b in bad) and any("score" in b for b in bad)
    with pytest.raises(ValueError):
        S.write_result({**d, "stamp": "x"}, Path("."))


# ------------------------------------------------------------------ W26b R2：本剧级配置 / 夹具与 series10_v2 对齐
REPO = HERE.parent


def _ar():
    import sys
    p = str(REPO / "services" / "agent")
    if p not in sys.path:
        sys.path.insert(0, p)
    from ns_agent import asset_refs as AR
    return AR


def test_seed_schedule_only_touches_smoke_key_and_is_idempotent(tmp_path):
    smoke = tmp_path / "eval/smoke"
    _mk(smoke, "template/hub_episode_looks.json", json.dumps({"_doc": "x", "smoke_v2": {"lead_f": {"1": "O4"}}}))
    other = {"series10_v2": {"lead_f": {"1": "O4", "_by": "ASSET-WORKER", "_at": "t"}}}
    _mk(tmp_path, S.HUB_EP_LOOKS_REL, json.dumps(other))
    assert S.seed_schedule(tmp_path, smoke) is True
    d = json.loads((tmp_path / S.HUB_EP_LOOKS_REL).read_text(encoding="utf-8"))
    assert d["series10_v2"] == other["series10_v2"] and d["smoke_v2"] == {"lead_f": {"1": "O4"}} and "_doc" not in d
    assert S.seed_schedule(tmp_path, smoke) is False                  # 已一致不写（G7 幂等）
    d["smoke_v2"] = {"lead_f": {"1": "O1"}}                          # 残留的旧条目 → 整键换回模板
    (tmp_path / S.HUB_EP_LOOKS_REL).write_text(json.dumps(d), encoding="utf-8")
    assert S.seed_schedule(tmp_path, smoke) is True
    assert json.loads((tmp_path / S.HUB_EP_LOOKS_REL).read_text(encoding="utf-8"))["smoke_v2"]["lead_f"]["1"] == "O4"


def test_seed_schedule_never_overwrites_unreadable_file(tmp_path):
    smoke = tmp_path / "eval/smoke"
    _mk(smoke, "template/hub_episode_looks.json", json.dumps({"smoke_v2": {"lead_f": {"1": "O4"}}}))
    _mk(tmp_path, S.HUB_EP_LOOKS_REL, "{坏")
    assert S.seed_schedule(tmp_path, smoke) is False
    assert (tmp_path / S.HUB_EP_LOOKS_REL).read_text(encoding="utf-8") == "{坏"
    assert S.seed_schedule(tmp_path, tmp_path / "nope") is False      # 没模板 = 不写


def test_seed_from_template_carries_schedule(tmp_path):
    smoke = tmp_path / "eval/smoke"
    _mk(smoke, "template/pipeline_run/P1_storyline.json", "{}")
    _mk(smoke, "template/hub_episode_looks.json", json.dumps({"smoke_v2": {"ch_tang_yao": {"1": "A"}}}))
    _mk(smoke, "P4_smoke.md", "# fixture")
    files = S.seed_from_template(tmp_path, smoke)
    assert S.HUB_EP_LOOKS_REL in files
    assert json.loads((tmp_path / S.HUB_EP_LOOKS_REL).read_text(encoding="utf-8")) == {"smoke_v2": {"ch_tang_yao": {"1": "A"}}}


def test_schedule_path_is_asset_refs_source():
    AR = _ar()
    assert Path(AR.HUB_EP_LOOKS).resolve() == (REPO / S.HUB_EP_LOOKS_REL).resolve()


def _fixture_look_rows() -> dict:
    rows = {}
    for ln in (HERE / "smoke/P4_smoke.md").read_text(encoding="utf-8").splitlines():
        m = re.match(r"\*\*造型｜(\S+?)\*\*：(.*)", ln)
        if m:
            rows[m.group(1)] = dict(seg.split("=", 1) for seg in m.group(2).split("｜") if "=" in seg)
    return rows


def test_fixture_looks_match_p1_registry_and_schedule():
    """夹具迁就规则：P4_smoke.md 造型行按 asset_refs.match_look（剧本造型行 → P1 造型）要能对上，且与模板排期同一造型 id"""
    from types import SimpleNamespace
    AR = _ar()
    p1 = json.loads((HERE / "smoke/template/pipeline_run/P1_looks.json").read_text(encoding="utf-8"))
    sched = json.loads((HERE / "smoke/template/hub_episode_looks.json").read_text(encoding="utf-8"))["smoke_v2"]
    rows = _fixture_look_rows()
    assert set(rows) == {"祁念", "唐瑶"}
    for c in p1:
        if c["name"] not in rows:
            continue
        looks = {lk["id"]: SimpleNamespace(zh=lk["zh"]) for lk in c["looks"]}
        lid, score, _ = AR.match_look(looks, rows[c["name"]])
        assert score >= 0.6, (c["name"], score)
        assert lid == sched[c["char_id"]][str(S.EP)], (c["name"], lid)
        assert lid in looks


def test_run_style_smoke_aligned_with_series10_v2():
    rs = json.loads((REPO / "config/compile/run_style.json").read_text(encoding="utf-8"))["runs"]
    strip = lambda e: {k: ({kk: vv for kk, vv in v.items() if not kk.startswith("_")} if isinstance(v, dict) else v)
                       for k, v in e.items() if k != "decision" and not k.startswith("_")}
    assert "smoke_v2" in rs, "smoke_v2 资产包模式，没有 run_style 条目 → StyleMissing（L-126）"
    assert strip(rs["smoke_v2"]) == strip(rs["series10_v2"])
    assert (REPO / rs["smoke_v2"]["bible"]).is_file()
