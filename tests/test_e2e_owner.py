"""W-E2E（L-214）：项目方路径验收 tools/qa/e2e_owner.py。
  · 页面族：成人镜页面 vs 触发清单、待你看读取失败 / 给看没过的候选；复用 invariants 的检查（不重复实现）
  · 沙箱 POST：对真实配置跑一遍全过；再把 11-06/07 夜里真出过的集成 bug 注回去（修改清单不在推送列表、成人触发写错地方、
    资产推送关着、点过的卡又冒出来），验收必须报出来——这是这一层存在的意义"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sp = importlib.util.spec_from_file_location("e2e_owner_t", ROOT / "tools/qa/e2e_owner.py")
E = importlib.util.module_from_spec(sp)
sys.modules["e2e_owner_t"] = E
sp.loader.exec_module(E)


@pytest.fixture(autouse=True)
def _live_primary(monkeypatch):
    """conftest 把“真实仓库的主剧”钉成 series10_v1（防测试漂移）；这里验收的就是真实在产剧 → 钉回 runs.json 的 primary"""
    monkeypatch.setenv("NS_PRIMARY_RUN", json.loads((ROOT / "config/pipeline/runs.json").read_text(encoding="utf-8"))["primary"])


def _bad(res, prefix):
    return [r for r in res if r["id"].startswith(prefix) and not r["ok"]]


# ------------------------------------------------------------------ 页面族（纯函数）
def test_adult_view_vs_trigger_file():
    view = {"run": "r", "episodes": [{"ep": 2, "shots": [{"shot": "ep02-S1", "state": "triggered"}, {"shot": "ep02-S2", "state": "waiting"},
                                                         {"shot": "ep02-S3", "state": "done"}]}]}
    trig = {"objects": ["first:ep02-S2", "last:ep02-S2", "first:ep02-S3"]}
    res = E.check_adult_view(view, trig)
    ids = {r["id"] for r in res}
    assert ids == {"adult_view_ghost", "adult_view_stale"} and all(not r["ok"] for r in res)
    assert "ep02-S1" in next(r for r in res if r["id"] == "adult_view_ghost")["detail"]
    assert E.check_adult_view(view, {"objects": ["first:ep02-S1", "first:ep02-S3"]}) == []


def test_inbox_source_error_and_unpassed_candidate():
    res = E.check_inbox_extra({"status": "error", "source_errors": ["缺少必需来源 x"],
                               "items": [{"id": "pick:scene:a", "candidates": [{"key": "a", "contract_ok": True}, {"key": "b", "contract_ok": False}]}]})
    assert {r["id"] for r in res} == {"inbox_source", "inbox_unpassed"}
    assert "没过检查" in next(r for r in res if r["id"] == "inbox_unpassed")["line"]
    assert E.check_inbox_extra({"status": "ok", "items": []}) == []


def test_get_part_reuses_invariants_and_reports_down_api(monkeypatch, tmp_path):
    real_load = E._load
    calls = []

    def load(name, rel):
        m = real_load(name, rel)
        if rel.endswith("invariants.py"):
            def api_get(base, path, timeout=20):
                calls.append(path)
                return None, 0.01
            m.api_get = api_get
        return m
    monkeypatch.setattr(E, "_load", load)
    res = E.get_part(tmp_path, "http://127.0.0.1:1")
    assert [r["id"] for r in res] == ["api_down"] and not res[0]["ok"]
    assert set(calls) == set(E.PAGES)


def test_get_part_page_checks_come_from_invariants(monkeypatch, tmp_path):
    """视频页黑屏（文件没拉回）由 invariants.media_missing 报；e2e 原样转成一行中文"""
    real_load = E._load
    pages = {p: {} for p in E.PAGES}
    pages["/api/videos/overview"] = {"shots": [{"video": "/files/pipeline/runs/r/video/clips/ep01/x.mp4"}]}
    pages["/api/owner/inbox"] = {"items": [], "at": None}

    def load(name, rel):
        m = real_load(name, rel)
        if rel.endswith("invariants.py"):
            m.api_get = lambda base, path, timeout=20: (pages[path], 0.05)
        return m
    monkeypatch.setattr(E, "_load", load)
    res = E.get_part(tmp_path, "http://x")
    bad = _bad(res, "inv:media_missing")
    assert bad and "本机没有文件" in bad[0]["line"]
    assert next(r for r in res if r["id"] == "pages_open")["ok"]


# ------------------------------------------------------------------ 沙箱 POST：真实配置全过
def test_post_part_all_owner_paths_pass_on_real_config():
    res = E.post_part(ROOT)
    bad = [r for r in res if not r["ok"]]
    assert not bad, bad
    ids = {r["id"] for r in res}
    for k in ("pick:done", "pick:manifest", "pick:push", "pick:gone", "edit:push", "edit:text", "adult:file", "adult:consumer", "adult:push",
              "revise:job", "revise:gone"):
        assert k in ids


def test_post_part_writes_nothing_real():
    watch = [ROOT / "data/owner_queue/requests.json", ROOT / "data/owner_queue/pick_state.json",
             ROOT / "data/pipeline/owner_adult_triggers.jsonl", ROOT / "data/state/frame_edit_requests.json"]
    before = {p: (p.stat().st_mtime_ns if p.exists() else None) for p in watch}
    E.post_part(ROOT)
    assert {p: (p.stat().st_mtime_ns if p.exists() else None) for p in watch} == before


# ------------------------------------------------------------------ 把真出过的集成 bug 注回去，必须被抓到
def test_catches_v2_rejects_not_pushed(monkeypatch):
    """11-07 复审：V2“修改”写在 data/producer/runs/<run>/master_rejects.json，推送清单只有旧路径 → 服务器永远看不到"""
    real = E._control_files
    monkeypatch.setattr(E, "_control_files", lambda: [x for x in real() if not x.endswith("runs/" + E._load("r", "tools/autopilot/runs.py").primary_run(ROOT) + "/master_rejects.json")])
    res = E.post_part(ROOT, only={"edit"})
    bad = _bad(res, "edit:push")
    assert bad and "服务器 producer 永远看不到" in bad[0]["line"]


def test_catches_adult_trigger_written_where_producer_does_not_read(monkeypatch):
    class P:
        pd = ROOT / "data/producer"            # 旧单剧路径
    monkeypatch.setattr(E, "_producer_paths", lambda run: P)
    res = E.post_part(ROOT, only={"adult"})
    assert _bad(res, "adult:consumer")


def test_catches_asset_push_disabled(monkeypatch):
    real_init = E.Sandbox.__init__

    def init(self, real_root=ROOT):
        real_init(self, real_root)
        cfg = json.loads((self.dir / "config/pipeline/asset_worker.json").read_text(encoding="utf-8"))
        cfg["push"] = False
        self.write("config/pipeline/asset_worker.json", cfg)
    monkeypatch.setattr(E.Sandbox, "__init__", init)
    res = E.post_part(ROOT, only={"pick"})
    bad = _bad(res, "pick:push")
    assert bad and "不会推到服务器" in bad[0]["line"]


def test_catches_clicked_card_reappearing(monkeypatch):
    from ns_api import owner_pick as OP, owner_queue as OQ
    monkeypatch.setattr(OP, "hidden_ids", lambda root: set())        # 点过的不再藏 = 11-07 01:3x 项目方反复点卡
    monkeypatch.setattr(OQ, "_closed", lambda root, now: set())
    res = E.post_part(ROOT, only={"pick"})
    assert _bad(res, "pick:gone")


def test_scenario_crash_is_a_plain_failure(monkeypatch):
    def boom(sb):
        raise RuntimeError("坏了")
    monkeypatch.setattr(E, "SCENARIOS", (("pick", boom),))
    res = E.post_part(ROOT)
    assert res[0]["id"] == "pick:crash" and not res[0]["ok"] and "走不通" in res[0]["line"]


def test_main_exit_code_is_failure_count(monkeypatch, capsys):
    monkeypatch.setattr(E, "run", lambda parts, root, base, timeout: {"n": 3, "failed": 2, "secs": 0.1, "parts": ["get"],
                                                                     "results": [E.R("a", False, "甲不过", "get"), E.R("b", False, "乙不过", "get"),
                                                                                 E.R("c", True, "丙过", "get")]})
    assert E.main(["--part", "get"]) == 2
    out = capsys.readouterr().out
    assert "❌ 甲不过" in out and "✅ 丙过" in out
