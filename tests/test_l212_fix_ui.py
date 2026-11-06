"""L-212（W-FIX-UI 11-07）：SCAN_20261107 #9 / #10 / #14 / #15 / #16。全部临时目录 / 纯函数，不连服务器、不写真实数据。"""
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/api", "services/render_router", "services/agent"):
    sys.path.insert(0, str(ROOT / p))

from ns_api import clock  # noqa: E402
from ns_api import swr  # noqa: E402
from ns_api import v1_guard as VG  # noqa: E402
from ns_render import pipeline as P  # noqa: E402


def _load(rel, name):
    sp = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


KC = _load("tools/brain/kpi_core.py", "kpi_core_t")
T = _load("tools/brain/telemetry.py", "telemetry_l212_t")
A = _load("tools/qa/arch_scan.py", "arch_scan_l212_t")
NOW = 1_800_000_000.0


# ---------------------------------------------------------------- #9 KPI 同一口径
def test_clock_starts_at_later_of_dispatch_and_import():
    assert KC.clock_start(None, NOW) is None                       # 没派过单 = 没开始
    assert KC.clock_start(NOW - 3600, NOW - 600) == NOW - 600      # 重新导入 → 从导入算
    assert KC.clock_start(NOW - 600, NOW - 3600) == NOW - 600      # 导入在前 → 从首派算
    k = KC.episodes(NOW, {"1": NOW - 4493 * 60}, {"1": KC.merge_have(None, total=16, video=8)}, {"1": NOW - 30 * 60})
    assert k["1"]["elapsed_min"] == 30.0 and k["1"]["clock_from"] == "import" and k["1"]["state"] == "in_budget"
    w = KC.episodes(NOW, {"2": NOW - 90 * 60}, {}, {"_whole": NOW - 60 * 60})   # 整本导入对所有集生效
    assert w["2"]["elapsed_min"] == 60.0


def test_panel_and_brain_use_same_numbers(tmp_path):
    """ep02：gpu33 首帧 0、gpu36 首帧 14；本机登记表 11 → 大脑和面板都报 14（以前面板 11）"""
    from ns_api import episode_kpi as K
    probes = {h: {"log": {"first_dispatch": {"2": NOW - 600 * 60}},
                  "registry": {"episodes": {"2": {"have": {"t": 16, "f": f, "l": 6, "v": 0}, "asm": False}}}}
              for h, f in (("gpu33", 0), ("gpu36", 14))}
    imports = {"2": NOW - 200 * 60}
    brain = T.kpi(NOW, probes, imports=imports)
    snap = {"t": NOW - 30, "at": "x", "kpi": brain}
    reg = {"run": "r", "episodes": [{"ep": 2, "title": "二", "have": {"total": 16, "passed": {"first": 11, "last": 6, "video": 0}},
                                     "shots": [{"shot": "ep02-S1", "index": 1, "objects": {"first": {"status": "passed"}}}]}]}
    e = K.build(registry=reg, renders=tmp_path, snapshot=snap, local_starts={}, now=NOW, url=lambda r: r, vurl=lambda r: r,
                imports=imports)["episodes"][0]
    b = brain["2"]
    assert (e["first_done"], e["last_done"], e["video_done"], e["total"]) == (b["first_done"], b["last_done"], b["video_done"], b["total"]) == (14, 6, 0, 16)
    assert e["elapsed_min"] == b["elapsed_min"] == 200.0 and e["state"] == b["state"] == "over_budget" and e["clock_from"] == "import"
    # 快照过期 → 本机自算，仍是同一个函数（起点同样按导入重置）
    e2 = K.build(registry=reg, renders=tmp_path, snapshot=None, local_starts={"2": NOW - 600 * 60}, now=NOW, url=lambda r: r,
                 vurl=lambda r: r, imports=imports)["episodes"][0]
    assert e2["elapsed_min"] == 200.0 and e2["first_done"] == 11


def test_assembled_episode_not_over_budget(tmp_path):
    """ep01 已合成：面板以前因 best_effort 口径 / 起点不重置显示“超预算 4493 分钟”"""
    from ns_api import episode_kpi as K
    reg = {"run": "r", "episodes": [{"ep": 1, "title": "一", "have": {"total": 16, "passed": {"first": 15, "last": 14, "video": 14}},
                                     "objects": {"assembly": {"status": "passed"}}, "shots": []}]}
    e = K.build(registry=reg, renders=tmp_path, snapshot=None, local_starts={"1": NOW - 4493 * 60}, now=NOW, url=lambda r: r,
                vurl=lambda r: r)["episodes"][0]
    assert e["state"] == "assembled" and e["over_min"] is None


def test_import_epochs_mixed_tz(tmp_path):
    """imports.jsonl 裸串：按本机时区不晚于文件修改时间 → 本机；否则只能是 JST"""
    f = tmp_path / "data" / "autopilot" / "imports.jsonl"
    f.parent.mkdir(parents=True)
    mt = time.mktime((2026, 11, 6, 8, 15, 0, 0, 0, -1))             # 本机时区 11-06 08:15
    rows = [{"at": "2026-11-06T08:00:08", "run_id": "r", "episodes": [1]},                  # 本机
            {"at": "2026-11-06T14:49:28", "run_id": "r", "changed_shots": ["ep02-S3"]},      # 比文件新 → JST
            {"at": "2026-11-06T09:00:00", "run_id": "other", "episodes": [1]},
            {"at": "2026-11-06T07:00:00", "run_id": "r", "kind": "changed_shots_backfill", "changed_shots": ["ep01-S1"]}]
    f.write_text("\n".join(json.dumps(r) for r in rows) + "\nnot json\n", encoding="utf-8")
    os.utime(f, (mt, mt))
    out = KC.import_epochs(tmp_path, "r")
    assert set(out) == {"1", "2"}
    assert out["1"] == time.mktime((2026, 11, 6, 8, 0, 8, 0, 0, -1))
    assert clock.epoch_jst(out["2"]) == "2026-11-06T14:49:28"
    assert KC.import_epochs(tmp_path / "none", "r") == {}


# ---------------------------------------------------------------- #10 页面时间 JST
def test_epoch_jst_and_display_helpers():
    assert clock.epoch_jst(0) == "1970-01-01T09:00:00" and clock.epoch_jst(0, "%H:%M") == "09:00"
    assert clock.epoch_jst(None) is None and clock.epoch_jst(-5) is None and clock.epoch_jst("x") is None
    from ns_api import infra_status as IS
    assert IS._hm(3600) == "10:00:00" and IS._hm(-1) is None


def test_display_modules_have_no_naive_local_time():
    """页面直出时间的接口不再用本机时区（工厂健康 / GPU / 任务表 / 剧本列表 …）"""
    for f in ("factory_health", "infra_status", "gpu_live", "gpu_monitor", "render_tasks", "script_library", "live"):
        rel = f"services/api/ns_api/{f}.py"
        assert A.naive_time_count(rel, (ROOT / rel).read_text(encoding="utf-8").splitlines()) == 0, f


def test_arch_scan_naive_time_rule():
    src = ['x = time.strftime("%H:%M")', 'y = time.strftime("%H", time.gmtime())', "z = datetime.now()",
           "w = datetime.now(JST)", "v = datetime.fromtimestamp(t)", "u = datetime.fromtimestamp(t, JST)",
           's = time.strftime("%Y%m%d")  # arch-ok: 文件名戳', "# time.localtime(t)"]
    assert A.naive_time_count("services/api/ns_api/x.py", src) == 3
    assert A.naive_time_count("services/api/ns_api/clock.py", src) == 0
    assert A.naive_time_count("tools/brain/x.py", src) == 0
    assert "naive_time" in A.METRICS
    assert A.scan_source("services/api/ns_api/x.py", "\n".join(src))["naive_time"] == 3


# ---------------------------------------------------------------- #14 runs.json 读竞争
def test_runs_read_retries_then_falls_back(tmp_path, monkeypatch):
    d = tmp_path / "data"
    f = tmp_path / "config" / "pipeline" / "runs.json"
    f.parent.mkdir(parents=True)
    f.write_text(json.dumps({"primary": "v2", "legacy_unprefixed_run": "v1"}), encoding="utf-8")
    VG._runs_last.clear()
    assert VG._runs(d)["primary"] == "v2"
    real = Path.read_text
    calls = {"n": 0}

    def flaky(self, *a, **k):
        if self == f:
            calls["n"] += 1
            if calls["n"] < 3:
                raise PermissionError(13, "正被替换")
        return real(self, *a, **k)
    monkeypatch.setattr(Path, "read_text", flaky)
    assert VG._runs(d, wait_s=0)["primary"] == "v2" and calls["n"] == 3      # 前两次被拒，第三次读到

    def deny(self, *a, **k):
        if self == f:
            raise PermissionError(13, "正被替换")
        return real(self, *a, **k)
    monkeypatch.setattr(Path, "read_text", deny)
    assert VG._runs(d, wait_s=0)["primary"] == "v2"                            # 一直被拒 → 上一份
    VG._runs_last.clear()
    try:
        VG._runs(d, wait_s=0)
        raise AssertionError("从没读成功过应抛出（fail-closed）")
    except PermissionError:
        pass


# ---------------------------------------------------------------- #15 没预览 = 200
def test_preview_missing_is_200_with_state(tmp_path, monkeypatch):
    from ns_api import ep_preview as EP
    monkeypatch.setattr(P, "ROOT", tmp_path)
    monkeypatch.setattr(P, "DATA", tmp_path / "data")
    monkeypatch.setattr(P, "RENDERS", tmp_path / "data" / "renders")
    (tmp_path / "data").mkdir()
    app = FastAPI()
    app.include_router(EP.router)
    r = TestClient(app).get("/api/episodes/7/preview")
    assert r.status_code == 200
    d = r.json()
    assert d["url"] is None and d["state"] == "none" and d["building"] is False and d["shots"] == [] and d["word"]
    st = tmp_path / "data" / "state" / "preview_sweep.json"
    st.parent.mkdir(parents=True)
    st.write_text(json.dumps({"eps": {"7": {"building": True, "eta_s": 120}}}), encoding="utf-8")
    d = TestClient(app).get("/api/episodes/7/preview").json()
    assert d["state"] == "building" and d["url"] is None and d["eta_s"] == 120


def test_frontend_handles_state_none():
    src = (ROOT / "apps/web/src/v3/pages/FilmOverview.tsx").read_text(encoding="utf-8")
    assert 'pv.state === "none"' in src


# ---------------------------------------------------------------- #16 慢接口：先回旧值、后台刷
def test_swr_cache_serves_stale_and_refreshes():
    c = swr.SWRCache("t", fresh_s=0.05, stale_s=5.0, always=True)
    n = {"v": 0}

    def slow():
        n["v"] += 1
        time.sleep(0.05)
        return n["v"]
    assert c.get("k", slow) == 1                       # 冷：同步算
    assert c.get("k", slow) == 1 and n["v"] == 1       # 新鲜：直接回
    time.sleep(0.08)
    t0 = time.time()
    assert c.get("k", slow) == 1                       # 过期：先回旧值（不等）
    assert time.time() - t0 < 0.04
    for _ in range(50):
        if c._data["k"][1] == 2:
            break
        time.sleep(0.02)
    assert c.get("k", slow) == 2                       # 后台刷好了
    c2 = swr.SWRCache("t2", always=False)              # pytest 里默认不缓存（用例换数据目录不串）
    assert c2.get("k", slow) == 3 and c2.get("k", slow) == 4


def test_routes_use_swr():
    from ns_api import frames_index as FI
    from ns_api import video_index as VI
    assert isinstance(FI._SWR, swr.SWRCache) and isinstance(VI._SWR, swr.SWRCache)
    assert FI._SWR.stale_s <= 300 and VI._SWR.stale_s <= 300
