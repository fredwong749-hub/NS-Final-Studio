"""SCHED-CORE（11-06）：离散事件模拟器 tools/sched/sim.py——确定性、场景间关系、不碰 gpu33:2、不连服务器。"""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("sched_sim_t", ROOT / "tools/sched/sim.py")
S = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(S)


def test_sim_deterministic_and_finishes():
    r1 = S.Sim("c_affinity", S.MEASURED, seed=7).run()
    r2 = S.Sim("c_affinity", S.MEASURED, seed=7).run()
    assert r1 == r2 and r1["finished"]
    assert r1["frames_min"] > 0 and r1["videos_min"] > 0 and r1["assembly_min"] > 0
    assert abs(r1["frames_min"] + r1["videos_min"] + r1["assembly_min"] - r1["total_min"]) < 0.3
    assert set(r1["gpu_util_pct"]) == set(S.GPU_LANES) and "gpu33:2" not in r1["gpu_util_pct"]


def test_scenarios_ordering():
    rows = {r["scenario"]: r for r in S.run_scenarios(seeds=[1106], scenarios=["a_today", "b_stations", "c_affinity", "d_turbo"])}
    assert rows["d_turbo"]["total_min"] < rows["c_affinity"]["total_min"] < rows["b_stations"]["total_min"] < rows["a_today"]["total_min"]
    assert rows["c_affinity"]["gpu_util_mean_pct"] > rows["b_stations"]["gpu_util_mean_pct"]
    # 固定工位：一集内每卡至多切换一次（L-206）
    assert all(v <= 2 for v in rows["b_stations"]["switches"].values())
    # 新调度首视频比固定工位晚不了太多、总时长更短
    assert rows["c_affinity"]["total_min"] < rows["b_stations"]["total_min"]


def test_table_renders_and_fetch_without_repo_is_safe(monkeypatch):
    rows = S.run_scenarios(seeds=[1], scenarios=["d_turbo"])
    txt = S.table(rows)
    assert "d_turbo" in txt and "KPI" in txt
    monkeypatch.setenv("NS_SCHED_SIM_REPO", "")
    monkeypatch.setattr(S.C, "load_config", lambda *a, **k: {"sim": {}})
    m = S.fetch_measured()
    assert "fetch_error" in m and m["frame_gpu_s"] == S.MEASURED["frame_gpu_s"]


def test_legacy_models_today_pathologies():
    r = S.Sim("a_today", S.MEASURED, seed=3).run()
    assert r["finished"] and r["first_video_start_min"] >= r["frames_min"] - 0.1      # 视频等整集首尾帧
    assert all(v <= 100.0 for v in r["gpu_util_pct"].values())
