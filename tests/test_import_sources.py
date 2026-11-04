"""K-OPS-Q31：剧本全局头 / 主线从现行导入记录自动推导；data_parity 的 pending_redo（CLEANUP 2026-11-01）。"""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/api", "services/agent", "packages/schema", "services/recipes", "services/render_router", "services/post", "tools/qa"):
    sys.path.insert(0, str(ROOT / p))

from ns_api import import_sources as IS  # noqa: E402

HEAD = "# 剧\n\n**每条prompt统一前缀（角色锁）**\n\n```Plain Text\n【甲】占位\n```\n\n"


def _repo(tmp_path, files: dict, sources: list) -> Path:
    for rel, text in files.items():
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")
    imp = tmp_path / "data/import/script_v2.json"
    imp.parent.mkdir(parents=True, exist_ok=True)
    imp.write_text(json.dumps({"sources": sources, "episodes": []}, ensure_ascii=False), encoding="utf-8")
    return imp


def sha(tmp_path, rel):
    return hashlib.sha256((tmp_path / rel).read_bytes()).hexdigest()


def test_latest_matching_source_wins(tmp_path):
    files = {"a.md": HEAD + "## ep01《一》\n", "b.md": HEAD + "## ep01《一》\n## ep02《二》\n", "frag.md": "## ep02《二》\n"}
    imp = _repo(tmp_path, files, [])
    srcs = [{"path": "a.md", "sha256": sha(tmp_path, "a.md"), "episodes": [1]},
            {"path": "b.md", "sha256": sha(tmp_path, "b.md"), "episodes": [1, 2]},
            {"path": "frag.md", "sha256": sha(tmp_path, "frag.md"), "episodes": [2]},     # 单集片段：没有全局头
            {"path": "old_ref.md", "sha256": "x", "episodes": []}]                        # 参考来源（没导入集）
    imp.write_text(json.dumps({"sources": srcs}), encoding="utf-8")
    assert [s["path"] for s in IS.current_sources(imp, tmp_path)] == ["frag.md", "b.md", "a.md"]
    assert IS.header_source(imp, tmp_path) == "b.md"           # 最新一份带全局头的
    assert IS.mainline(imp, tmp_path) == ["b.md"]               # 覆盖集数最多


def test_sha_mismatch_or_missing_falls_back(tmp_path):
    imp = _repo(tmp_path, {"a.md": HEAD + "## ep01《一》\n"}, [])
    imp.write_text(json.dumps({"sources": [{"path": "a.md", "sha256": "0" * 64, "episodes": [1]},
                                           {"path": "gone.md", "episodes": [1]}]}), encoding="utf-8")
    assert IS.current_sources(imp, tmp_path) == []
    assert IS.header_source(imp, tmp_path) is None and IS.mainline(imp, tmp_path) == []
    assert IS.current_sources(tmp_path / "none.json", tmp_path) == []


def test_script_header_uses_derived_then_config(tmp_path, monkeypatch):
    from ns_api import script_chat as S
    files = {"cur.md": HEAD + "## ep01《一》\n", "cfg.md": "# 配置回退\n\n```Plain Text\n【乙】占位\n```\n\n## ep01《一》\n"}
    imp = _repo(tmp_path, files, [])
    imp.write_text(json.dumps({"sources": [{"path": "cur.md", "sha256": sha(tmp_path, "cur.md"), "episodes": [1]}]}), encoding="utf-8")
    monkeypatch.setattr(S, "PRODUCTION_SCRIPT", imp)
    monkeypatch.setattr(S, "REPO", tmp_path)
    cfg = {"header_sources": ["cfg.md"], "registry": {}}
    head, src = S.script_header(cfg)
    assert src == "cur.md" and "【甲】" in head
    head, src = S.script_header({**cfg, "header_sources_mode": "config"})
    assert src == "cfg.md" and "【乙】" in head
    monkeypatch.setattr(S, "PRODUCTION_SCRIPT", tmp_path / "none.json")
    assert S.script_header(cfg)[1] == "cfg.md"


def test_real_repo_header_is_current_import():
    hs = IS.header_source()
    if hs is None:
        return
    srcs = IS.current_sources()
    assert hs in [s["path"] for s in srcs]
    assert "为他而骚" not in hs   # 不再是 60 集旧稿


def test_pending_redo_rule():
    import data_parity as DP
    at = "2026-11-01T18:24:39"
    assert DP.pending_redo({}, at) == "无当前首帧"
    old = {"active": {"image": 2}, "takes": [{"stage": "image", "n": 2, "created_at": "2026-11-01T10:00:00"}]}
    new = {"active": {"image": 3}, "takes": [{"stage": "image", "n": 3, "created_at": "2026-11-01T19:00:00"}]}
    assert DP.pending_redo(old, at).startswith("当前首帧 #2")
    assert DP.pending_redo(new, at) is None                      # 新首帧设为当前 → 自动转回比对


def test_pending_overdue_and_alert(tmp_path):
    import time
    import data_parity as DP
    cfg = tmp_path / "dp.json"
    cfg.write_text('{"pending_redo_max_hours": 12}', encoding="utf-8")
    assert DP.pending_max_hours(cfg) == 12 and DP.pending_max_hours(tmp_path / "none.json") == 12
    at = "2026-11-01T06:00:00"
    t0 = time.mktime(time.strptime(at, "%Y-%m-%dT%H:%M:%S"))
    pend = {"ep01-S5": "x", "ep02-S6": "y"}
    assert DP.overdue_pending(pend, at, 12, now=t0 + 11 * 3600)[0] == []           # 未到 12 小时
    over, age = DP.overdue_pending(pend, at, 12, now=t0 + 13 * 3600)
    assert over == ["ep01-S5", "ep02-S6"] and age == 13.0
    al = tmp_path / "alerts.jsonl"
    assert DP.sync_pending_alert(over, age, 12, al) == "open"
    assert DP.sync_pending_alert(over, age, 12, al) is None                          # 已开着不重复写
    assert DP.sync_pending_alert([], 0, 12, al) == "closed"                           # 清零自动关
    rows = [json.loads(x) for x in al.read_text(encoding="utf-8").splitlines()]
    assert [r["state"] for r in rows] == ["open", "closed"]
    assert rows[0]["id"] == DP.PENDING_ALERT_ID and rows[0]["by"] == "data_parity" and rows[0]["shots"] == over
    assert {"ts", "t", "id", "state", "level", "msg", "by"} <= set(rows[0])        # 与 infra_watchdog 同格式


def _dp_root(tmp_path):
    """临时仓库：runs.json（v1 = legacy 不带前缀，v2 = 带前缀）+ runs.py 副本（for_root 按文件加载）"""
    import shutil
    (tmp_path / "config/pipeline").mkdir(parents=True)
    (tmp_path / "tools/autopilot").mkdir(parents=True)
    shutil.copy(Path(__file__).resolve().parents[1] / "tools/autopilot/runs.py", tmp_path / "tools/autopilot/runs.py")
    (tmp_path / "config/pipeline/runs.json").write_text(json.dumps({"primary": "v2", "legacy_unprefixed_run": "v1", "runs": {
        "v1": {"status": "archived"}, "v2": {"status": "producing"}}}), encoding="utf-8")
    return tmp_path


def test_data_parity_import_cutoffs_per_run(tmp_path):
    import data_parity as DP
    root = _dp_root(tmp_path)
    log, ev = tmp_path / "import_log.jsonl", tmp_path / "imports.jsonl"
    log.write_text("\n".join(json.dumps(r) for r in [
        {"at": "2026-11-01T23:21:50", "run": "v1", "episodes": [1], "rc": 0},
        {"at": "2026-11-02T14:28:49", "run": "v1", "path": "x_ep02_v3.md", "rc": 0},
        {"at": "2026-11-03T00:00:00", "run": "v1", "episodes": [3], "rc": 1}]), encoding="utf-8")       # rc!=0 不算
    ev.write_text("\n".join(json.dumps(r) for r in [
        {"at": "2026-11-03T04:50:46", "run_id": "v2", "episodes": [1]},
        {"at": "2026-11-04T15:33:57", "run_id": "v2", "episodes": [1]},
        {"at": "2026-11-03T13:44:48", "run_id": "v2", "episodes": [2]},
        {"at": "2026-11-09T00:00:00", "run_id": "other", "episodes": [1]}]), encoding="utf-8")
    assert DP.import_cutoffs("v1", log, ev, root) == ({1: "2026-11-01T23:21:50", 2: "2026-11-02T14:28:49"}, "", {})
    assert DP.import_cutoffs("v2", log, ev, root) == ({1: "2026-11-04T15:33:57", 2: "2026-11-03T13:44:48"}, "", {})       # 旧事件无镜级信息：按整集
    assert DP.last_import_at(log, tmp_path / "none.json", "v1", ev, root) == "2026-11-02T14:28:49"
    assert DP.last_import_at(log, tmp_path / "none.json", "v2", ev, root) == "2026-11-04T15:33:57"


def test_data_parity_imaging_episodes_per_run(tmp_path):
    import data_parity as DP
    root = _dp_root(tmp_path)
    assert DP.imaging_episodes("v1", root) is None                    # legacy：口径不变（不限）
    assert DP.imaging_episodes("v2", root) == set()                   # 没有 ready 清单 = 没有集进入出图
    p = tmp_path / "data/autopilot/runs/v2/ready_episodes.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({"episodes": {"1": {"shots": ["ep01-S1"]}}}), encoding="utf-8")
    assert DP.imaging_episodes("v2", root) == {1}                     # ep03 / ep04 未进 ready：不算过期待重做


def test_import_events_changed_shots_and_per_shot_cutoff(tmp_path):
    """V2 补丁式追加导入不作废未改镜；改了的镜作废；历史事件经 changed_shots_backfill 补记；无镜级信息的旧事件按整集"""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/autopilot"))
    import import_events as IE
    def sc(prompts):
        return {"episodes": [{"number": 1, "shots": [{"episode": 1, "index": i + 1, "img_prompt": p, "motion_prompt": "m", "cast_raw": "c"}
                                                     for i, p in enumerate(prompts)]}]}
    old, new = sc(["a", "b"]), sc(["a", "b2", "c"])
    assert IE.changed_shots(old, new) == ["ep01-S2", "ep01-S3"]          # 改了的 + 新增的
    assert IE.changed_shots(None, old) == ["ep01-S1", "ep01-S2"]
    ev = tmp_path / "imports.jsonl"
    rows = [{"at": "2026-11-03T00:00:00", "run_id": "v2", "episodes": [1]},                       # 历史事件：由补记提供
            {"kind": "changed_shots_backfill", "at": "2026-11-04T20:00:00", "run_id": "v2", "orig_at": "2026-11-03T00:00:00",
             "changed_shots": ["ep01-S1", "ep01-S2"]},
            {"at": "2026-11-04T15:33:57", "run_id": "v2", "episodes": [1], "changed_shots": ["ep01-S3"]},   # 补丁式追加
            {"at": "2026-11-04T16:00:00", "run_id": "v2", "episodes": [2]}]                       # 无镜级信息：整集
    ev.write_text(chr(10).join(json.dumps(r) for r in rows), encoding="utf-8")
    t = IE.cutoff_table("v2", ev)
    assert IE.shot_cutoff(t, 1, 1) == "2026-11-03T00:00:00"          # 未改镜：旧候选仍现行（作废线早于它们）
    assert IE.shot_cutoff(t, 1, 3) == "2026-11-04T15:33:57"          # 改 / 新增的镜作废
    assert IE.shot_cutoff(t, 2, 5) == "2026-11-04T16:00:00"          # 保守：整集
    assert IE.shot_cutoff(t, 3, 1) == ""
    # append_import 写 changed_shots（old_script 给了才写）
    s_old, s_new = tmp_path / "o.json", tmp_path / "n.json"
    s_old.write_text(json.dumps(old), encoding="utf-8")
    s_new.write_text(json.dumps(new), encoding="utf-8")
    rec = IE.append_import([1], by="t", run_id="v2", events=tmp_path / "e2.jsonl", script=s_new, old_script=s_old)
    assert rec["changed_shots"] == ["ep01-S2", "ep01-S3"]


def test_cast_ctx_registers_manifest_names_before_first_shot(monkeypatch):
    """ep01-S1 卓琳 重启后显示成名字（未解析成 ch_zhuo_lin）：CastCtx 一建就登记资产包角色名，不等 reg() / looks() 顺带登记"""
    from ns_api import shot_cast as SC
    from ns_agent import asset_refs as AR
    seen = []
    monkeypatch.setattr(SC, "project_for", lambda script: "proj_x")
    monkeypatch.setattr(AR, "register_manifest_names", lambda p: seen.append(p) or {})
    SC.CastCtx(object())
    assert seen == ["proj_x"]
