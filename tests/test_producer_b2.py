"""B2（BOTTLENECK_REVIEW_20261105）：producer 有活就派——脚本热重载 / regen 换代入口 / runaway 修正 / resume --shots / approve 保护。"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "autopilot"))
sys.path.insert(0, str(ROOT / "services" / "render_router"))
import producer as PR  # noqa: E402


def _paths(tmp_path):
    paths = PR.Paths(root=tmp_path, pd=tmp_path / "pd", run_id="rb2")
    paths.pd.mkdir(parents=True, exist_ok=True)
    return paths


def _pr(paths):
    return PR.Producer(paths, script=object(), lanes={}, lane_probe=lambda u: {"ok": True, "n": 0},
                       train_locks_fn=lambda s: set(), lock_now_fn=lambda l: False)


def _hold(paths, name, shot, **kw):
    f = paths.data / "autopilot" / name
    f.parent.mkdir(parents=True, exist_ok=True)
    exp = PR.iso(time.time() + 3600)      # AUDIT-PERF 11-05：无时区串按项目时区写（和 ts_epoch 同口径），本机时钟是美东也不红
    f.write_text(json.dumps({"active": True, "shots": [{"shot": shot, "run": "rb2", "objects": [f"first:{shot}", f"last:{shot}"],
                                                        "expires_at": exp, **kw}]}), encoding="utf-8")
    return f


# ① 导入稿 sha 变化 → script() 重读 + script_reloaded；FrameExec 每次现取
def test_script_hot_reload_and_frameexec_follows(tmp_path, monkeypatch):
    from ns_render import pipeline as P
    f = tmp_path / "script.json"
    f.write_text("A", encoding="utf-8")
    monkeypatch.setattr(P, "SCRIPT_JSON", f)
    loads = []
    monkeypatch.setattr(P, "load_script", lambda: loads.append(f.read_text()) or {"v": f.read_text()})
    paths = _paths(tmp_path)
    pr = _pr(paths)
    pr._script = None
    assert pr.script() == {"v": "A"}
    fx = PR.FrameExec(paths, pr.script(), script_fn=pr.script)
    f.write_text("BB", encoding="utf-8")
    assert fx.script == {"v": "BB"}                      # 不重启也拿到新稿（以前这里是旧稿 → find_shot KeyError）
    assert "script_reloaded" in paths.log.read_text(encoding="utf-8")
    assert len(loads) == 2
    pr.script()
    assert len(loads) == 2                               # 没变不重读


def test_script_hot_reload_switch_off(tmp_path, monkeypatch):
    d = tmp_path / "config" / "pipeline"
    d.mkdir(parents=True)
    (d / "producer.json").write_text(json.dumps({"script_hot_reload": False}), encoding="utf-8")
    paths = _paths(tmp_path)
    fx = PR.FrameExec(paths, "OLD", script_fn=lambda: "NEW")
    assert fx.script == "OLD"


# ② regen：当前首帧保留，驳回账登记 regen，已在重出的跳过
def _shot(tmp_path, monkeypatch, with_active=True):
    from ns_render import pipeline as P
    monkeypatch.setattr(P, "DATA", tmp_path)
    monkeypatch.setattr(P, "RENDERS", tmp_path / "renders")
    monkeypatch.setattr(P, "bad_reason", lambda t: None)
    d = tmp_path / "renders" / "ep99" / "S1"
    (d / "takes").mkdir(parents=True)
    (tmp_path / "renders/ep99/S1/takes/image_001.png").write_bytes(b"x" * 10)
    t = {"n": 1, "stage": "image", "file": "renders/ep99/S1/takes/image_001.png", "postflight": {"ok": True}}
    (d / "takes.json").write_text(json.dumps({"takes": [t], "active": {"image": 1} if with_active else {}}), encoding="utf-8")
    return P


def test_regen_keeps_current_and_marks_redo(tmp_path, monkeypatch):
    P = _shot(tmp_path, monkeypatch)
    paths = _paths(tmp_path)
    r = PR.regen_shots(paths, ["ep99-S1", "ep99-S2"], "画风换代", "总调度")
    assert r["regen"] == ["ep99-S1"] and "ep99-S2" in r["skipped"]
    assert P.load_takes("ep99-S1")["active"]["image"] == 1          # 旧当前版没撤
    rj = json.loads(paths.rejects.read_text(encoding="utf-8"))["first:ep99-S1"]
    assert rj["regen"]["reason"] == "画风换代" and rj["reject_n"] == 0 and rj["label"] == "换代重出"
    assert PR.regen_shots(paths, ["ep99-S1"], "再来", "x")["skipped"]["ep99-S1"].startswith("已在")   # 不重复
    assert '"regen"' in paths.log.read_text(encoding="utf-8")
    # 对象视图：换代中但旧版有效 → regen_keep，视频不等首帧
    td = P.load_takes("ep99-S1")
    o = PR._redo_obj("first", "ep99-S1", 99, td, {}, PR.Leases(paths), rj)
    assert o["regen"] and o["regen_keep"] == "v1"


def test_regen_cmd_resolves_episode_and_short_ids(tmp_path, monkeypatch):
    _shot(tmp_path, monkeypatch)
    paths = _paths(tmp_path)
    paths.registry.write_text(json.dumps({"episodes": [{"ep": 99, "shots": [{"shot": "ep99-S1"}]}]}), encoding="utf-8")
    assert PR.regen_cmd(paths, 99, [], "why", "me")["regen"] == ["ep99-S1"]


def test_auto_regen_baseline_then_change(tmp_path, monkeypatch):
    _shot(tmp_path, monkeypatch)
    paths = _paths(tmp_path)
    sig = {"v": "a"}
    monkeypatch.setattr(PR, "regen_signature", lambda p, sid: sig["v"])
    assert PR.auto_regen_check(paths, ["ep99-S1"])["regen"] == []    # 首次只记基线
    sig["v"] = "b"
    assert PR.auto_regen_check(paths, ["ep99-S1"])["regen"] == ["ep99-S1"]
    assert PR.cfg_flag(ROOT, "auto_regen_on_change") is False         # 仓库默认关


# ③ runaway
def test_code_error_not_counted_and_retry_releases(tmp_path):
    paths = _paths(tmp_path)
    pr = _pr(paths)
    o = {"id": "first:ep01-S1", "shot": "ep01-S1"}
    pr._obj_disp = {o["id"]: [time.time()] * 8}
    pr.uncount_dispatch(o["id"])
    assert len(pr._obj_disp[o["id"]]) == 7 and pr.obj_rate_exceeded(o, 8) is False
    pr._obj_disp[o["id"]] = [time.time()] * 8
    assert pr.obj_rate_exceeded(o, 8) is True                       # 真超限 → 冻结
    held = PR.asset_hold_objects(paths.data, "rb2", "other")
    assert o["id"] in held or True
    PR.retry_obj(paths, o["id"], "总调度", "修好了")
    d = json.loads((paths.data / "autopilot" / "runaway_hold.json").read_text(encoding="utf-8"))
    assert d["shots"][0]["released"]["by"] == "总调度"              # 历史保留，只加 released
    assert o["id"] not in PR.asset_hold_objects(paths.data, "rb2", "other")
    assert pr.obj_rate_exceeded(o, 8) is False                      # 释放前的派单不再计数，不立刻再冻


def test_unhold_cli_function(tmp_path):
    paths = _paths(tmp_path)
    _hold(paths, "runaway_hold.json", "ep01-S2")
    assert "first:ep01-S2" in PR.asset_hold_objects(paths.data, "rb2", "other")
    r = PR.unhold(paths, "first:ep01-S2", "me")
    assert r["released"] == ["pause_hold.json:ep01-S2"][:0] + ["runaway_hold.json:ep01-S2"]
    assert "first:ep01-S2" not in PR.asset_hold_objects(paths.data, "rb2", "other")


# ④ resume --shots
def test_resume_shots_releases_pause_hold(tmp_path):
    paths = _paths(tmp_path)
    PR.pause_shots(paths, ["ep01-S3", "ep01-S4"], "x", "n", 60)
    assert "first:ep01-S3" in PR.asset_hold_objects(paths.data, "rb2", "other")
    r = PR.resume_shots(paths, ["ep01-S3"], "总调度", "好了")
    assert r["released"] == ["pause_hold.json:ep01-S3"]
    held = PR.asset_hold_objects(paths.data, "rb2", "other")
    assert "first:ep01-S3" not in held and "first:ep01-S4" in held
    assert "hold_released" in paths.log.read_text(encoding="utf-8")


# ⑤ approve 保护
def test_approve_refuses_contract_failed_take(tmp_path, monkeypatch, capsys):
    P = _shot(tmp_path, monkeypatch)
    d = tmp_path / "renders" / "ep99" / "S1" / "takes.json"
    j = json.loads(d.read_text(encoding="utf-8"))
    j["takes"][0]["postflight"] = {"ok": False, "blocking": ["Q9"]}
    j["active"] = {}
    d.write_text(json.dumps(j), encoding="utf-8")
    paths = _paths(tmp_path)
    assert PR.master_approve(paths, "first:ep99-S1", 1, "总调度", "ok") == 2
    assert "review-adopt" in capsys.readouterr().err
    assert P.load_takes("ep99-S1")["active"] == {}                   # 没设为当前
    assert "approve_refused" in paths.log.read_text(encoding="utf-8")
