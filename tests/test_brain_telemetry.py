"""BRAIN-FW：tools/brain/telemetry.py 快照——schema / 体积 / KPI / 道视图 / 摘要（全 fake，不碰网络 / 服务器）。"""
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


T = _load("brain_telemetry_t", "tools/brain/telemetry.py")
NOW = 1_800_000_000.0
LANES = {"gpu33:0": {"host": "gpu33", "gpu": 0, "comfy_port": 8188}, "gpu33:1": {"host": "gpu33", "gpu": 1, "comfy_port": 8189},
         "gpu33:3": {"host": "gpu33", "gpu": 3, "comfy_port": 8191}, "gpu36:0": {"host": "gpu36", "gpu": 0, "comfy_port": 8188},
         "gpu36:1": {"host": "gpu36", "gpu": 1, "comfy_port": 8189}, "gpu36:2": {"host": "gpu36", "gpu": 2, "comfy_port": 8190}}
LR = {"enabled": True, "from_episode": 2,
      "phases": {"frames": {"image": ["gpu33:0", "gpu33:1", "gpu36:0", "gpu36:1"], "review": ["gpu33:3"], "video": ["gpu36:2"]},
                 "videos": {"image": [], "review": ["gpu33:3"], "video": list(LANES)}}}


def registry(eps=(1, 2, 3, 4), n=16, status="passed"):
    E = {}
    att = []
    for ep in eps:
        shots = {}
        for i in range(1, n + 1):
            shots[f"S{i}"] = f"F:P/3 L:{'P' if status == 'passed' else 'R'}/2 V:{'P' if status == 'passed' else 'W'}"
        if status != "passed":
            att.append({"obj": f"last:ep{ep:02d}-S1", "st": "ready", "att": 2, "where": None, "wait_min": 14.2, "why": "等道（出图位满）" * 3})
        E[str(ep)] = {"headline": "首帧 16/16 · 尾帧 16/16 · 视频 16/16 · 已合成"[:100], "have": {"t": n, "f": n, "l": n, "v": n if status == "passed" else 3},
                      "asm": status == "passed", "obj_open": {} if status == "passed" else {"assembly": "pending"}, "shots": shots}
    return {"updated": "x", "paused": False, "counts": {"total": 64 * len(eps)}, "episodes": E, "attention": att, "attention_n": len(att),
            "stuck_objects": [], "lanes": {ln: {"free": True, "why": "", "q": 0} for ln in LANES}}


def probe(host, reg=None, util=80, running=("PRODUCER:first:ep02-S3",), first_dispatch=None):
    gpus = {str(i): {"util": util, "mem": 18000, "mem_total": 24564} for i in range(4)}
    qs = {str(i): {"running": list(running), "pending": 1, "model": ["qwen_image_fp8.safetensors"], "pending_labels": ["first:ep02-S4"]} for i in range(4)}
    return {"now": NOW, "host": host, "gpus": gpus, "queues": qs,
            "hb": {"t": NOW - 12, "paused": False, "inflight": 2, "scoring": 1, "started": "x", "pid": 1},
            "ctrl": {"paused": False, "only": [2], "hold_lanes": []}, "master_rejects_open": {"n": 1, "ids": ["first:ep02-S9"]},
            "registry": reg if reg is not None else registry(),
            "log": {"first_dispatch": first_dispatch or {"2": NOW - 40 * 60}, "last_dispatch_t": NOW - 60,
                    "fails": [{"ts": "11-06 17:00", "ev": "score_infra", "obj": "first:ep02-S3", "why": "no torch"}],
                    "ev_counts_tail": {"dispatch": 10, "score_infra": 3}},
            "nctrl": {"yield_s": 30, "hold_lanes": []}, "night_state_age_s": 40, "night_state": {"eps": {"2": {"status": "rendering", "host": host}}},
            "night_log_tail": ["11-06 17:00:00 DISPATCH gpu33 eps [2]"] * 8,
            "video": {"counts": {"done": 10, "rendering": 2}, "active": {"ep02-S1": "rendering n1 submitted@gpu36:2 h3"}, "active_n": 1},
            "finalize_procs": [], "procs": {"producer": 1, "night": 1, "vqa": 3}, "vqa": {"queue": 0, "loaded": True, "instances": 3},
            "lane_roles_state": {"2": {"phase": "frames", "since": "x"}}}


class FakeEnv(T.Env):
    def __init__(self, root, probes=None, assets=None, now=NOW):
        super().__init__(root)
        self.probes = probes if probes is not None else {"gpu33": probe("gpu33"), "gpu36": probe("gpu36")}
        self._assets, self._now = assets or [], now

    def now(self):
        return self._now

    def lanes(self):
        return dict(LANES)

    def primary_run(self):
        return "run_t"

    def probe_host(self, host, run, lanes, cfg):
        return self.probes.get(host)

    def asset_jobs(self, run):
        return self._assets

    def restart_pending(self):
        return [{"host": "gpu36", "mode": "night-only", "by": "IDLE-WATCH", "at": "x"}]

    def issues_open(self):
        return [{"id": "ISS-1", "who": "IDLE-WATCH", "what": "空卡有活", "status": "open"}]


def _root(tmp_path):
    (tmp_path / "config/pipeline").mkdir(parents=True)
    (tmp_path / "config/pipeline/lane_roles.json").write_text(json.dumps(LR), encoding="utf-8")
    (tmp_path / "data/pipeline/idle_watch").mkdir(parents=True)
    (tmp_path / "data/pipeline/idle_watch/status.json").write_text(json.dumps({"at": "x", "t": NOW - 30, "idle_lanes": ["gpu33:3"], "has_work": True,
                                                                               "actions": [{"kind": "night_once", "host": "gpu33", "result": "rc=0"}]}), encoding="utf-8")
    return tmp_path


def test_snapshot_schema_and_size(tmp_path):
    env = FakeEnv(_root(tmp_path), assets=[{"id": "a1", "state": "pending", "kind": "face"}, {"id": "a2", "state": "failed", "kind": "scene", "error": "boom", "final": False}])
    s = T.snapshot(env, T.load_cfg(tmp_path), save=True)
    assert s["schema"] == T.SCHEMA and s["run"] == "run_t" and s["hash"] and len(s["hash"]) == 12
    assert set(s["lanes"]) == set(LANES) and "gpu33:2" not in json.dumps(s)
    assert s["lanes"]["gpu33:0"]["running"] == ["PRODUCER:first:ep02-S3"] and s["lanes"]["gpu33:0"]["model"] == ["qwen_image_fp8.safetensors"]
    assert s["lanes"]["gpu33:0"]["roles"] == ["image"] and s["lanes"]["gpu33:3"]["roles"] == ["review"] and s["lanes"]["gpu36:2"]["roles"] == ["video"]
    assert s["hosts"]["gpu33"]["producer"]["hb_age_s"] == 12 and s["hosts"]["gpu33"]["master_rejects_open"]["n"] == 1
    assert s["assets"]["counts"] == {"pending": 1, "failed": 1} and s["assets"]["failed"][0]["err"] == "boom"
    assert s["idle_watch"]["idle_lanes"] == ["gpu33:3"] and s["restart_pending"][0].startswith("gpu36 night-only") and s["issues_open"][0]["id"] == "ISS-1"
    assert s["lane_roles"]["phases"] == {"2": "frames"}
    assert s["bytes"] < 15000, s["bytes"]
    assert (tmp_path / "data/brain/snapshot.json").is_file() and (tmp_path / "data/brain/snapshot.md").is_file()
    assert json.loads((tmp_path / "data/brain/snapshot.json").read_text(encoding="utf-8"))["hash"] == s["hash"]


def test_snapshot_compacts_big_registry_under_budget(tmp_path):
    big = registry(eps=range(1, 11), n=16, status="ready")        # 10 集 × 16 镜，两台各一份
    env = FakeEnv(_root(tmp_path), probes={"gpu33": probe("gpu33", reg=big), "gpu36": probe("gpu36", reg=big)})
    s = T.snapshot(env, T.load_cfg(tmp_path), save=False)
    assert s["bytes"] <= 15000 and s.get("truncated", 0) >= 1
    assert s["hosts"]["gpu33"]["registry"]["attention"]          # 裁剪后仍保留注意力列表（最多 8 条）


def test_kpi_timer_and_eta():
    reg = registry(eps=(2,), n=16, status="ready")
    reg["episodes"]["2"]["have"]["v"] = 4
    pr = {"gpu33": probe("gpu33", reg=reg, first_dispatch={"2": NOW - 60 * 60}), "gpu36": probe("gpu36", reg=reg, first_dispatch={"2": NOW - 30 * 60})}
    k = T.kpi(NOW, pr)
    assert k["2"]["elapsed_min"] == 60.0 and k["2"]["state"] == "over_budget" and k["2"]["budget_min"] == 50
    assert k["2"]["done_frac"] == 0.25 and k["2"]["eta_min"] == 180.0
    done = T.kpi(NOW, {"gpu33": probe("gpu33"), "gpu36": None})
    assert done["1"]["state"] == "assembled" and done["2"]["state"] == "assembled"


def test_probe_failure_is_reported_not_guessed(tmp_path):
    env = FakeEnv(_root(tmp_path), probes={"gpu33": probe("gpu33"), "gpu36": None})
    s = T.snapshot(env, T.load_cfg(tmp_path), save=False)
    assert s["probe_errors"] == ["gpu36"] and s["lanes"]["gpu36:0"]["probe"] is False and s["lanes"]["gpu36:0"].get("idle") is None
    assert s["hosts"]["gpu36"] == {"probe": None}
    md = T.summary_md(s)
    assert "探针失败" in md and "gpu36" in md


def test_idle_detection_and_summary(tmp_path):
    env = FakeEnv(_root(tmp_path), probes={"gpu33": probe("gpu33", util=0, running=()), "gpu36": probe("gpu36")})
    for q in env.probes["gpu33"]["queues"].values():
        q["pending"] = 0
    s = T.snapshot(env, T.load_cfg(tmp_path), save=False)
    assert s["lanes"]["gpu33:0"]["idle"] is True and s["lanes"]["gpu36:0"]["idle"] is False
    md = T.summary_md(s)
    assert "**空闲**" in md and "KPI" in md and "ep02" in md and "score_infra" in md and "空卡巡检" in md


def test_remote_probe_has_no_backslashes_and_placeholders_filled():
    assert chr(92) not in T.REMOTE_PROBE
    code = (T.REMOTE_PROBE.replace("__LANES__", "{}").replace("__RUN__", "r").replace("__HOST__", "gpu33").replace("__PD__", "pd")
            .replace("__NLOG__", "5").replace("__NFAIL__", "3").replace("__VQA_PORT__", "8870"))
    assert "__" not in code.replace("__file__", "")
    compile(code, "remote_probe", "exec")
