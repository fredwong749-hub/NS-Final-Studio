"""L-088 全量重做脚本（K-OPS-W08，WORKFLOW）：前置闸门没全过绝不派单；G21 自动核“剧本导入后已重编作业”；
apply 逐镜记状态、已派的跳过（可续跑）。全部打桩，不连服务器、不写真实 data/。"""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/autopilot"))
for _p in ("services/render_router", "services/agent", "packages/schema", "services/api"):
    sys.path.insert(0, str(ROOT / _p))
import full_redo as FR  # noqa: E402


def _setup(monkeypatch, tmp_path, gates=()):
    monkeypatch.setattr(FR, "GATES", tmp_path / "gates.json")
    monkeypatch.setattr(FR, "STATE", tmp_path / "state.json")
    monkeypatch.setattr(FR, "PLAN", tmp_path / "plan.json")
    monkeypatch.setattr(FR, "ROOT", tmp_path)
    (tmp_path / "data/import").mkdir(parents=True)
    (tmp_path / "data/pipeline/runs/series10_v1/assets").mkdir(parents=True)
    (tmp_path / "data/import/script_v2.json").write_text("{}")
    (tmp_path / "data/pipeline/runs/series10_v1/assets/first_frame_jobs.json").write_text("{}")
    FR.js(FR.GATES, {g: {"ok": True, "by": "t"} for g in gates})
    monkeypatch.setattr(FR, "g21_check", lambda run_dir: {"ok": True})        # 真实核对见 tests/test_image_jobs_import.py
    monkeypatch.setattr(FR, "image_jobs_green", lambda: {"ok": True})      # AUDIT 22:13 前置检查（真实跑 pytest，这里打桩）
    FR.js(FR.PLAN, {"shots": [{"shot": "ep01-S3", "ep": 1, "host": "gpu33", "current_first": 4},
                              {"shot": "ep02-S1", "ep": 2, "host": "gpu36", "current_first": 6}]})


def test_apply_refuses_without_all_gates(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, gates=["G20", "G21", "W5", "PIKA_SMOKE"])      # 缺 SCRIPT
    r = FR.apply()
    assert r["ok"] is False and r["gates"]["SCRIPT"]["ok"] is False


def test_g21_auto_check_jobs_newer_than_script(monkeypatch, tmp_path):
    """K-OPS-Q24（RSI 11-01）：G21 不比修改时间，核对镜头集合 + 提示词来源 sha（作业比剧本新也可能是旧来源编的）"""
    _setup(monkeypatch, tmp_path, gates=FR.GATE_IDS)
    monkeypatch.setattr(FR, "g21_check", lambda run_dir: {"ok": False, "missing": ["ep01-S8"], "extra": [], "stale_sha": ["ep01-S1"]})
    st = FR.gates_status()["G21"]
    assert st["ok"] is False and "缺 1 镜" in st["auto"] and "sha 过期 1 条" in st["auto"] and not FR.gates_ok()
    monkeypatch.setattr(FR, "g21_check", lambda run_dir: {"ok": True})
    assert FR.gates_ok()


def test_apply_resumable(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, gates=FR.GATE_IDS)
    import resident_sync as RS
    calls = []
    monkeypatch.setattr(RS, "ssh", lambda host, cmd, **kw: calls.append((host, cmd)) or b"")
    assert FR.apply(executor="server")["sent"] == 2
    assert "'first:ep01-S3' '--n' '4'" in calls[0][1] and calls[0][0] == "gpu33"
    assert FR.apply(executor="server")["sent"] == 0                                                 # 已派的跳过
    st = json.loads(FR.STATE.read_text(encoding="utf-8"))
    assert set(st["done"]) == {"first:ep01-S3", "first:ep02-S1"}


def test_master_reject_demotes_passed_ledger(monkeypatch, tmp_path):
    """CLEANUP D-LEDGER（11-01 19:2x）：驳回即撤下当前后，账本 attempts.json 不能还留 final=passed（等下一拍 producer 才改，中间窗口
    data_parity 会报“PRODUCER 不会重出”）→ master_reject 同步改成待重出"""
    import contextlib
    import producer as PR
    from ns_render import frame_edit as FE
    from ns_render import pipeline as P
    paths = PR.Paths(root=tmp_path, pd=tmp_path / "producer")
    paths.pd.mkdir(parents=True)
    PR.js(paths.ledger, {"first:ep05-S8": {"final": "passed", "tries": 1, "history": [{"take": 2, "ok": True}]}})
    monkeypatch.setattr(FE, "annotate", lambda *a, **k: None)
    monkeypatch.setattr(P, "shot_lock", lambda sid: contextlib.nullcontext())
    monkeypatch.setattr(P, "load_takes", lambda sid: {"takes": [], "active": {"image": 2}})
    monkeypatch.setattr(P, "_save_takes", lambda sid, d: None)
    monkeypatch.setattr(P, "clear_active", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(PR, "log_event", lambda *a, **k: None)
    PR.master_reject(paths, "first:ep05-S8", 2, "L-088 全量重做", ["frame_v9", "frame_v9"], None, "WORKFLOW-L088")
    led = PR.jl(paths.ledger)["first:ep05-S8"]
    assert led["final"] is None and led.get("demoted_at") and led["redo_tries"] == 0


def test_reset_redo_restores_counts_keeps_history(monkeypatch, tmp_path):
    """总调度 19:41：IMGFIX 修根因期间白出的驳回重出不占次数"""
    monkeypatch.setattr(FR, "ROOT", tmp_path)
    (tmp_path / "data/producer").mkdir(parents=True)
    FR.js(tmp_path / "data/producer/master_rejects.json",
          {"first:ep01-S1": {"reason": "L-088 全量重做（R0）"}, "first:ep02-S1": {"reason": "别的驳回"}})
    FR.js(tmp_path / "data/producer/attempts.json",
          {"first:ep01-S1": {"redo_tries": 1, "redo_history": [{"try": 1, "at": "2026-11-01T19:35:00"}]},
           "first:ep02-S1": {"redo_tries": 2}})
    assert FR.reset_redo(dry=True)["changed"] == 1
    r = FR.reset_redo(since="2026-11-01T19:20:00")
    L = FR.jl(tmp_path / "data/producer/attempts.json")
    assert r["changed"] == 1 and L["first:ep01-S1"]["redo_tries"] == 0 and len(L["first:ep01-S1"]["redo_history"]) == 2
    assert L["first:ep02-S1"]["redo_tries"] == 2                     # 非 L-088 的不动


def test_apply_refuses_when_image_jobs_red(monkeypatch, tmp_path):
    """AUDIT 22:13：作业清单与编译器不一致（test_image_jobs 红）→ 不派、不 resume"""
    _setup(monkeypatch, tmp_path, gates=FR.GATE_IDS)
    monkeypatch.setattr(FR, "image_jobs_green", lambda: {"ok": False, "tests": "2 failed"})
    r = FR.apply()
    assert r["ok"] is False and r["image_jobs"]["ok"] is False


def test_cli_reason_with_spaces_not_split(monkeypatch, tmp_path, capsys):
    """DEBUG_r1 #12：Start-Process / 未加引号的调用把带空格的原因拆成多个参数 → argparse 报错。现在多词原因拼回一句"""
    monkeypatch.setattr(FR, "ROOT", tmp_path)
    (tmp_path / "data/pipeline/runs/series10_v1/assets").mkdir(parents=True)
    (tmp_path / "data/pipeline/runs/series10_v1/assets/first_frame_jobs.json").write_text('{"jobs": []}', encoding="utf-8")
    rc = FR.main(["reject-old-jobs", "--shots", "ep01-S1", "--since", "2099-01-01", "--reason", "局部出场人物去外貌", "/", "脸部词（IMGFIX", "00:3x）",
                  "--note", "a", "b", "--dry"])
    assert rc == 0 and '"rejected": []' in capsys.readouterr().out


def test_restart_guarded_skips_without_resident_changes(monkeypatch, tmp_path):
    """DEBUG_r1：只在常驻实际加载的文件变了才重启；30 分钟内最多一次"""
    import resident_sync as RS
    monkeypatch.setattr(RS, "STATE", tmp_path / "st.json")
    monkeypatch.setattr(RS, "log", lambda *a: None)
    calls = []
    monkeypatch.setattr(RS, "ssh", lambda *a, **k: calls.append(a) or b"{}")
    monkeypatch.setattr(RS, "restart", lambda h, mode=None: calls.append(("restart", h)) or "ok")
    monkeypatch.setattr(RS, "local_manifest", lambda dirs: {"tests/test_x.py": (1, 9e9), "docs/a.md": (1, 9e9)})
    assert RS.restart_guarded("gpu33") is None and not calls                 # 只改了测试 / 文档 → 不重启
    monkeypatch.setattr(RS, "local_manifest", lambda dirs: {"tools/autopilot/producer.py": (1, 9e9)})
    assert RS.restart_guarded("gpu33") == "ok"
    assert RS.restart_guarded("gpu33") is None                               # 30 分钟内第二次 → 跳过
    assert RS.AUTO_CODE_PUSH is False                                        # loop 不再自己推代码 / 重启
