"""W-SCAN 11-07：tools/brain/invariants.py 系统自查 + telemetry.kpi 两台合并（全 fixture，不碰网络 / 服务器）。"""
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name, rel):
    sp = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(sp)
    sys.modules[name] = m
    sp.loader.exec_module(m)
    return m


INV = _load("brain_invariants_t", "tools/brain/invariants.py")
T = _load("brain_telemetry_inv_t", "tools/brain/telemetry.py")
NOW = 1_800_000_000.0


def host(f, l, v, att=(), vcounts=None, phase="frames", fails=(), ctrl=None, ctrl_files=None):
    return {"registry": {"episodes": {"2": {"have": {"t": 16, "f": f, "l": l, "v": v}}}, "attention": list(att)},
            "video": {"counts": vcounts or {}}, "lane_roles_state": {"2": {"phase": phase}, "_active": {"phase": "x"}},
            "log_fails": list(fails), "ctrl": ctrl or {}, "nctrl": {}, "ctrl_files": ctrl_files}


def snap(**kw):
    s = {"run": "run_t", "probe_errors": [],
         "kpi": {"2": {"first_done": 14, "last_done": 6}},
         "hosts": {"gpu33": host(0, 0, 0), "gpu36": host(14, 6, 0)},
         "lanes": {"gpu33:0": {"running": []}, "gpu36:2": {"running": ["VIDEO10:ep02-S16"]}},
         "idle_watch": {}, "assets": {}}
    s.update(kw)
    return s


def keys(vs):
    return {v["key"] for v in vs}


# ---------------------------------------------------------------- telemetry.kpi 修复
def _probe(f, l, v):
    return {"log": {"first_dispatch": {"2": NOW - 600}}, "registry": {"episodes": {"2": {"have": {"t": 16, "f": f, "l": l, "v": v}, "asm": False}}}}


def test_kpi_takes_per_field_max_across_hosts():
    """真数字：11-07 01:31 gpu33 ep02 首0尾0视频0、gpu36 首14尾6视频0 → 以前快照报 0/16"""
    k = T.kpi(NOW, {"gpu33": _probe(0, 0, 0), "gpu36": _probe(14, 6, 0)})["2"]
    assert (k["first_done"], k["last_done"], k["video_done"], k["total"]) == (14, 6, 0, 16)
    k = T.kpi(NOW, {"gpu33": _probe(15, 14, 10), "gpu36": _probe(15, 14, 14)})["2"]
    assert k["video_done"] == 14


# ---------------------------------------------------------------- 快照族
def test_snapshot_checks_flag_brain_kpi_and_host_disagreement():
    vs = INV.check_snapshot(snap(kpi={"2": {"first_done": 0, "last_done": 0}}), NOW)
    assert "kpi_brain:ep2" in keys(vs)
    assert {"host_disagree:ep2:f", "host_disagree:ep2:l"} <= keys(vs)
    assert "host_disagree:ep2:v" not in keys(vs)
    assert "kpi_brain:ep2" not in keys(INV.check_snapshot(snap(), NOW))


def test_phantom_running_and_phase_and_retry_loop():
    att = [{"obj": "video:ep01-S7", "st": "running", "where": "VIDEO10 gpu33"}]
    fails = [{"ts": "x", "ev": "content_fail", "obj": "last:ep01-S9", "why": "FL"}] * 3
    s = snap(hosts={"gpu33": host(0, 0, 0, att=att, vcounts={"pending": 5}, phase="videos", fails=fails), "gpu36": host(14, 6, 0)})
    ks = keys(INV.check_snapshot(s, NOW))
    assert "phantom_run:gpu33" in ks and "phase_disagree:ep2" in ks and "retry_loop:gpu33:content_fail:last:ep01-S9" in ks
    s["lanes"]["gpu33:0"]["running"] = ["VIDEO10:ep01-S7"]          # 真在跑 → 不报
    assert "phantom_run:gpu33" not in keys(INV.check_snapshot(s, NOW))


def test_stuck_idle_hold_and_asset_failed():
    att = [{"obj": "first:ep02-S1", "st": "ready", "wait_min": 75, "why": "空闲道"}, {"obj": "first:ep02-S2", "st": "ready", "wait_min": 10}]
    s = snap(hosts={"gpu33": host(0, 0, 0, att=att, ctrl={"expires_at": "2020-01-01T00:00:00", "hold_lanes": ["gpu36:0"]}), "gpu36": host(14, 6, 0)},
             idle_watch={"idle_lanes": ["gpu36:0"], "has_work": True, "age_s": 30},
             assets={"failed": [{"id": "item-x", "err": "没有候选过检", "final": True}, {"id": "item-y", "err": "e", "final": False}]})
    ks = keys(INV.check_snapshot(s, NOW))
    assert {"stuck:gpu33:first:ep02-S1", "idle_work", "hold_expired:gpu33:ctrl", "asset_failed:item-x"} <= ks
    assert "stuck:gpu33:first:ep02-S2" not in ks and "asset_failed:item-y" not in ks


def test_ctrl_unpushed(tmp_path):
    pd = tmp_path / "data/producer/runs/run_t"
    pd.mkdir(parents=True)
    (pd / "owner_triggers.json").write_text("{}", encoding="utf-8")
    lm = (pd / "owner_triggers.json").stat().st_mtime
    s = snap(hosts={"gpu33": host(0, 0, 0, ctrl_files={"owner_triggers.json": None}), "gpu36": host(14, 6, 0, ctrl_files={"owner_triggers.json": lm})})
    assert keys(INV.check_ctrl_push(s, tmp_path, "run_t")) == {"ctrl_unpushed:gpu33:owner_triggers.json"}


# ---------------------------------------------------------------- 本机文件族
def _picks(tmp_path, st):
    d = tmp_path / "data/owner_queue"
    d.mkdir(parents=True, exist_ok=True)
    (d / "pick_state.json").write_text(json.dumps(st), encoding="utf-8")
    return d


def test_pick_stuck_and_failed_without_reason(tmp_path):
    old = INV.datetime.fromtimestamp(NOW - 3600).strftime("%Y-%m-%dT%H:%M:%S")
    new = INV.datetime.fromtimestamp(NOW - 60).strftime("%Y-%m-%dT%H:%M:%S")
    _picks(tmp_path, {"pick:scene:a": {"state": "processing", "updated": old}, "pick:scene:b": {"state": "accepted", "updated": new},
                      "pick:scene:c": {"state": "failed", "updated": old}, "pick:scene:d": {"state": "failed", "error": "选过别的", "updated": old},
                      "pick:scene:e": {"state": "done", "updated": old}})
    ks = keys(INV.check_picks(tmp_path, NOW))
    assert ks == {"pick_stuck:pick:scene:a", "pick_failed_noreason:pick:scene:c"}


def test_tmp_orphans(tmp_path):
    import os
    d = _picks(tmp_path, {})
    t = d / "pick_state.json.abc.tmp"
    t.write_text("x", encoding="utf-8")
    os.utime(t, (NOW - 3600, NOW - 3600))
    assert "tmp_orphan:data/owner_queue" in keys(INV.check_picks(tmp_path, NOW))


def test_api_logs_new_bytes_only_and_sticky(tmp_path):
    logs = tmp_path / "ops/logs"
    logs.mkdir(parents=True)
    out = logs / "api_8800.out.log"
    err = logs / "api_8800.err.log"
    out.write_text('INFO:     127.0.0.1:1 - "POST /api/owner/pick HTTP/1.1" 500 Internal Server Error\n'
                   + 'INFO:     127.0.0.1:1 - "GET /api/episodes/2/preview HTTP/1.1" 404 Not Found\n' * 201, encoding="utf-8")
    err.write_text("Traceback (most recent call last):\nPermissionError: [WinError 5] Access is denied: 'pick_state.json.x.tmp'\n"
                   "ConnectionResetError: [WinError 10054] closed\n", encoding="utf-8")
    st = {}
    ks = keys(INV.check_api_logs(tmp_path, st, NOW))
    assert ks == {"api_log:5xx:POST /api/owner/pick", "api_log:404poll:/api/episodes/2/preview", "api_log:exc:PermissionError"}
    assert keys(INV._scan_api_logs(tmp_path, st)) == set()            # 没新增字节 → 本拍扫描为空
    assert keys(INV.check_api_logs(tmp_path, st, NOW + 60)) == ks       # 30 分钟内持续报
    assert keys(INV.check_api_logs(tmp_path, st, NOW + 4000)) == set()  # 过了就清


def test_issue_backlog_counts_only_old_human_issues():
    old = INV.datetime.fromtimestamp(NOW - 7 * 3600, INV.JST).strftime("%Y-%m-%d %H:%M:%S+09:00")
    new = INV.datetime.fromtimestamp(NOW - 600, INV.JST).strftime("%Y-%m-%d %H:%M:%S+09:00")
    iss = [{"id": "A", "status": "open", "time": old, "who": "IDLE-WATCH"}, {"id": "B", "status": "open", "time": new, "who": "X"},
           {"id": "C", "status": "closed", "time": old}, {"id": "D", "status": "open", "time": old, "inv_key": "idle_work"}]
    vs = INV.check_issue_backlog(iss, NOW)
    assert len(vs) == 1 and "1 条" in vs[0]["title"]


# ---------------------------------------------------------------- 页面口径族
def test_pages_queue_shows_done_kpi_page_media_slow_tz(tmp_path):
    d = _picks(tmp_path, {"pick:scene:done1": {"state": "done"}, "pick:scene:open1": {"state": "failed", "error": "x"}})
    (d / "decisions.jsonl").write_text(json.dumps({"id": "pick:look:x", "applied": {"ok": 1}}) + "\n", encoding="utf-8")
    (tmp_path / "data/renders/r/ep01/S1/takes").mkdir(parents=True)
    (tmp_path / "data/renders/r/ep01/S1/takes/v1.mp4").write_bytes(b"x")
    at_wrong_tz = INV.datetime.fromtimestamp(NOW - 14 * 3600, INV.JST).strftime("%Y-%m-%dT%H:%M:%S")
    pages = {"/api/owner/inbox": {"at": at_wrong_tz, "items": [{"id": "pick:scene:done1", "title": "t"}, {"id": "pick:scene:open1"}, {"id": "pick:look:x"}]},
             "/api/episodes/kpi": {"episodes": [{"ep": 2, "first_done": 11, "last_done": 6}]},
             "/api/videos/overview": {"a": "/files/renders/r/ep01/S1/takes/v1.mp4?v=1", "b": "/files/renders/r/ep01/S2/takes/v9.mp4"}}
    ks = keys(INV.check_pages(pages, {"/api/owner/inbox": 2.4, "/api/episodes/kpi": 0.3}, tmp_path, snap(), NOW))
    assert {"queue_done:pick:scene:done1", "queue_done:pick:look:x", "kpi_page:ep2", "media_missing:/api/videos/overview",
            "slow_api:/api/owner/inbox", "api_tz:/api/owner/inbox"} <= ks
    assert "queue_done:pick:scene:open1" not in ks and "slow_api:/api/episodes/kpi" not in ks
    pages["/api/owner/inbox"]["at"] = INV.datetime.fromtimestamp(NOW, INV.JST).strftime("%Y-%m-%dT%H:%M:%S")
    assert "api_tz:/api/owner/inbox" not in keys(INV.check_pages(pages, {}, tmp_path, snap(), NOW))


# ---------------------------------------------------------------- 卡点同步：开 / 去重 / 更新 / 自动关 / 没跑的族不关
def test_sync_open_dedupe_update_autoclose(tmp_path):
    p = tmp_path / "issues.jsonl"
    st = {}
    v1 = [INV.V("idle_work", INV.RED, "有活但道空着", "gpu36:0"), INV.V("slow_api:/x", INV.YEL, "慢", "3 s")]
    r = INV.sync_issues(v1, {"idle_work", "slow_api"}, p, "run_t", NOW, st)
    assert r["opened"] == 2 and v1[0]["issue"].startswith("ISS-")
    r = INV.sync_issues([dict(x) for x in v1], {"idle_work", "slow_api"}, p, "run_t", NOW + 60, st)
    assert r == {"opened": 0, "updated": 0, "closed": 0}               # 去重：不重复开
    r = INV.sync_issues([INV.V("idle_work", INV.RED, "有活但道空着", "gpu36:0, gpu36:1")], {"idle_work"}, p, "run_t", NOW + 120, st)
    assert r == {"opened": 0, "updated": 1, "closed": 0}               # 证据变了 → update；slow_api 族本拍没跑 → 不关
    r = INV.sync_issues([], {"idle_work", "slow_api"}, p, "run_t", NOW + 180, st)
    assert r["closed"] == 2
    cur = {i["inv_key"]: i for i in INV.load_issues(p)}
    assert all(i["status"] == "closed" for i in cur.values()) and cur["idle_work"]["what"].endswith("gpu36:1")
    rec = json.loads(p.read_text(encoding="utf-8").splitlines()[0])
    assert rec["who"] == "SELF-CHECK" and rec["blocking"] is False   # 不进项目方待你看的只读告知
    ri = _load("report_issue_inv_t", "tools/master/report_issue.py")
    assert all(i["status"] == "closed" for i in ri.load(p))            # 老读者（report_issue.load）口径一致


# ---------------------------------------------------------------- 集成：telemetry.snapshot → snapshot.md 顶部
def test_snapshot_md_lists_self_check_on_top(tmp_path):
    tb = _load("brain_telemetry_test_mod", "tests/test_brain_telemetry.py")
    root = tb._root(tmp_path)
    p33 = tb.probe("gpu33", reg=tb.registry(eps=(2,), status="ready"))
    p36 = tb.probe("gpu36", reg=tb.registry(eps=(2,), status="ready"))
    p33["registry"]["episodes"]["2"]["have"].update(f=0, l=0)            # gpu33 首尾帧 0、gpu36 16 → 两台不一致
    env = tb.FakeEnv(root, probes={"gpu33": p33, "gpu36": p36})
    assert env.api_base is None                                         # 临时根不打本机 API
    s = T.snapshot(env, T.load_cfg(root), save=True)
    assert s["kpi"]["2"]["first_done"] == 16
    md = (root / "data/brain/snapshot.md").read_text(encoding="utf-8")
    assert md.splitlines()[1].startswith("## 🔴 系统自查发现")
    assert "host_disagree:ep2:f" in md and (root / "data/pipeline/issues.jsonl").is_file()


# ---------------------------------------------------------------- resident_sync：V2 当前版本视频也要拉回（视频页 14 个黑片的根因）
def test_remote_active_videos_covers_v2_layout(tmp_path, monkeypatch, capsys):
    src = (ROOT / "tools/autopilot/resident_sync.py").read_text(encoding="utf-8")
    code = src.split('REMOTE_ACTIVE_VIDEOS = r"""', 1)[1].split('"""', 1)[0]
    for rel in ("data/renders/ep01/S1", "data/renders/series10_v2/ep01/S13"):
        d = tmp_path / rel
        (d / "takes").mkdir(parents=True)
        f = rel.replace("data/", "") + "/takes/video_003.mp4"
        (tmp_path / "data" / f).write_bytes(b"xx")
        (d / "takes.json").write_text(json.dumps({"active": {"video": 3}, "takes": [{"n": 3, "stage": "video", "file": f}]}), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    exec(compile(code, "remote_active_videos", "exec"), {})
    got = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert set(got) == {"data/renders/ep01/S1/takes/video_003.mp4", "data/renders/series10_v2/ep01/S13/takes/video_003.mp4"}
