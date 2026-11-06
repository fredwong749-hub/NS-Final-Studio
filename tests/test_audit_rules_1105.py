"""AUDIT-RULES 11-05（Fable 独立复审，项目方常令“每次做对的规则写到系统去”）：
① test_release_auto::test_run_watched_kills_stalled_tree 根因 —— .venv 转发器 + 进程表 JSON 控制字符 → 只杀根、子进程握着 stdout → unlink PermissionError；
② deploy 不在笔记本写 data/system_version.txt；③ TZ=JST-9 口径；④ 转发器父子 = 一份服务（K-OPS-I08）；⑤ 规则 / 决策表与 L-186…L-192 一致。
全部不碰真实 data/、不连网、不杀进程。"""
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def _load(rel, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


SV = _load("tools/qa/system_version.py", "ns_sv_audit1105")
PI = _load("tools/ops/proc_instances.py", "ns_proc_instances_t")


# ---------------------------------------------------------------- ① 僵死树：进程表 JSON 带控制字符 / 临时文件被占
@pytest.mark.skipif(os.name != "nt", reason="Windows CIM 进程表路径")
def test_ident_table_tolerates_control_chars_in_cmdline(monkeypatch):
    raw = ('[{"ProcessId":10,"ParentProcessId":1,"CommandLine":"\\"C:\\\\x.exe\\" a\tb\n","ExecutablePath":"C:\\\\x.exe","Born":638000000000000000},'
           '{"ProcessId":11,"ParentProcessId":10,"CommandLine":"python.exe -c pass","ExecutablePath":"C:\\\\p.exe","Born":638000000000000001}]')
    assert "\t" in raw and "\n" in raw                                   # 未转义的控制字符：默认 json.loads 会抛 ValueError

    class R:
        stdout = raw.encode("utf-8")
    monkeypatch.setattr(SV.subprocess, "run", lambda *a, **k: R())
    t = SV._ident_table()
    assert t is not None and set(t) == {10, 11} and t[11]["ppid"] == 10   # 表拿到了 → kill_plan 能连子进程一起杀


def test_unlink_tolerant_never_raises_and_records_leftover(tmp_path):
    class Locked:
        calls = 0

        def unlink(self, missing_ok=False):
            self.calls += 1
            raise PermissionError(32, "being used by another process")

        def __str__(self):
            return "C:/tmp/nsfs_watch_locked.out"
    info = {}
    p = Locked()
    assert SV._unlink_tolerant(p, info, tries=3, wait_s=0, sleep=lambda s: None) is False
    assert p.calls == 3 and info["tmp_left"].endswith("nsfs_watch_locked.out")
    real = tmp_path / "x.out"
    real.write_text("x")
    assert SV._unlink_tolerant(real, info) is True and not real.exists()


def test_run_watched_finally_uses_tolerant_unlink():
    src = (ROOT / "tools/qa/system_version.py").read_text(encoding="utf-8")
    body = src.split("def run_watched(")[1].split("\ndef ")[0]
    assert "_unlink_tolerant(Path(fn), info)" in body and "Path(fn).unlink(missing_ok=True)" not in body


def test_venv_python_is_a_launcher_pair_on_windows():
    """根因证据：.venv\\Scripts\\python.exe 起的子进程 pid ≠ Popen.pid（转发器再起基础解释器）。非 Windows 相等。"""
    pr = subprocess.Popen([sys.executable, "-c", "import os;print(os.getpid())"], stdout=subprocess.PIPE, text=True)
    out, _ = pr.communicate(timeout=60)
    child = int(out.strip())
    if os.name == "nt" and ".venv" in sys.executable.lower():
        assert child != pr.pid
    else:
        assert child == pr.pid


# ---------------------------------------------------------------- ② 本机 data/system_version.txt
def test_write_local_version_writes_same_schema_as_server(tmp_path):
    rel = SV.write_local_version("sv-20261105-04", "abc123", "2026-11-05T16:00:00", root=tmp_path)
    assert rel == "data/system_version.txt"
    d = json.loads((tmp_path / rel).read_text(encoding="utf-8"))
    assert d == {"id": "sv-20261105-04", "commit": "abc123", "at": "2026-11-05T16:00:00", "by": "tools/qa/system_version.py deploy"}
    assert not (tmp_path / "data/system_version.txt.tmp").exists()      # 原子写，不留临时文件


def test_deploy_calls_write_local_version_after_any_host_ok():
    src = (ROOT / "tools/qa/system_version.py").read_text(encoding="utf-8")
    body = src.split("\ndef deploy(")[1].split("\ndef ")[0]
    assert "write_local_version(sv, commit" in body and 'any(r.get("ok")' in body


# ---------------------------------------------------------------- ③ TZ=JST-9
def test_sv_env_defaults_tz_jst():
    assert SV.ENV["TZ"] == (os.environ.get("TZ") or "JST-9")
    assert SV.ENV["PYTHONUTF8"] == "1"


# ---------------------------------------------------------------- ④ 转发器父子 = 一份（K-OPS-I08）
def _tbl():
    V = r"D:\NS-Final Studio\.venv\Scripts\python.exe"
    B = r"C:\Users\u\AppData\Local\Programs\Python\Python312\python.exe"
    return [
        {"pid": 19180, "ppid": 51364, "exe": V, "cmd": f'"{V}" -u tools/autopilot/resident_sync.py loop ', "born": "t1"},
        {"pid": 25584, "ppid": 19180, "exe": B, "cmd": f'"{B}" -u tools/autopilot/resident_sync.py loop ', "born": "t2"},
        {"pid": 48428, "ppid": 41972, "exe": V, "cmd": f'"{V}" -u tools/monitor/server.py ', "born": "t1"},
        {"pid": 20812, "ppid": 48428, "exe": B, "cmd": f'"{B}" -u tools/monitor/server.py ', "born": "t2"},
        # :8800 链：看门狗转发器 → 看门狗 → uvicorn 转发器 → uvicorn
        {"pid": 14388, "ppid": 7400, "exe": V, "cmd": f'"{V}" "D:\\x\\tools\\factory\\api_watchdog.py" --by X -- -m uvicorn ns_api.app:app --port 8800', "born": "t1"},
        {"pid": 38644, "ppid": 14388, "exe": B, "cmd": f'"{B}" "D:\\x\\tools\\factory\\api_watchdog.py" --by X -- -m uvicorn ns_api.app:app --port 8800', "born": "t2"},
        {"pid": 8488, "ppid": 38644, "exe": V, "cmd": f'"{V}" -m uvicorn ns_api.app:app --port 8800 --host 127.0.0.1', "born": "t3"},
        {"pid": 43324, "ppid": 8488, "exe": B, "cmd": f'"{B}" -m uvicorn ns_api.app:app --port 8800 --host 127.0.0.1', "born": "t4"},
        {"pid": 999, "ppid": 1, "exe": B, "cmd": f'"{B}" -c pass', "born": "t0"},
    ]


def test_proc_instances_collapses_venv_launcher_pair():
    rs = PI.logical_instances(_tbl(), PI.DEFAULT_MATCHES["resident_sync"])
    assert len(rs) == 1 and rs[0]["pid"] == 19180 and rs[0]["worker_pid"] == 25584 and rs[0]["launcher_pair"]
    mon = PI.logical_instances(_tbl(), PI.DEFAULT_MATCHES["monitor8810"])
    assert [(x["pid"], x["worker_pid"]) for x in mon] == [(48428, 20812)]
    api = PI.logical_instances(_tbl(), PI.DEFAULT_MATCHES["api8800"])
    assert [(x["pid"], x["worker_pid"]) for x in api] == [(8488, 43324)]     # 看门狗那两层不算第二份


def test_proc_instances_still_reports_true_duplicates():
    V = r"D:\NS-Final Studio\.venv\Scripts\python.exe"
    B = r"C:\Python312\python.exe"
    t = _tbl() + [{"pid": 777, "ppid": 1, "exe": V, "cmd": f'"{V}" -u tools/autopilot/resident_sync.py loop', "born": "t9"},
                  {"pid": 778, "ppid": 777, "exe": B, "cmd": f'"{B}" -u tools/autopilot/resident_sync.py loop', "born": "t9"}]
    rs = PI.logical_instances(t, PI.DEFAULT_MATCHES["resident_sync"])
    assert sorted(x["pid"] for x in rs) == [777, 19180]                     # 真重复才是 2 份
    # 子进程不在 .venv 父之下（ppid 不对）= 各算一份，不合并
    t2 = [dict(_tbl()[0]), dict(_tbl()[1], ppid=1)]
    assert len(PI.logical_instances(t2, PI.DEFAULT_MATCHES["resident_sync"])) == 2


def test_proc_instances_is_read_only():
    src = (ROOT / "tools/ops/proc_instances.py").read_text(encoding="utf-8")
    for bad in ("taskkill", "Stop-Process", "os.kill(", ".kill()", ".terminate("):
        assert bad not in src


# ---------------------------------------------------------------- ⑤ 规则 / 决策表与 L-186…L-192 一致
def test_owner_decisions_encode_l187_to_l192():
    cfg = yaml.safe_load((ROOT / "config/owner_decisions.yaml").read_text(encoding="utf-8"))
    ids = {c["id"] for c in cfg["checks"]}
    for need in ("D-V2-187", "D-V2-188", "D-V2-188b", "D-V2-189", "D-V2-190", "D-V2-191", "D-V2-192a", "D-V2-192b", "D-V2-192c"):
        assert need in ids, need


def test_l187_auto_adopt_default_off_and_l191_base35():
    prod = json.loads((ROOT / "config/pipeline/producer.json").read_text(encoding="utf-8"))
    assert prod["review_adopt_auto"] is True   # L-196（项目方 11-05 “全自动”）修订 L-187 默认关
    rq = json.loads((ROOT / "config/render_quality.json").read_text(encoding="utf-8"))
    # L-206 ②（11-06）：runs[剧] 改成按集表——ep01 仍 base35（跑完作基线），ep02 起 turbo_previz；读法唯一入口 frame_job.tier_name
    if str(ROOT / "services/agent") not in sys.path:
        sys.path.insert(0, str(ROOT / "services/agent"))
    from ns_agent import frame_job as FJ
    runs_v = rq["first_frame_tier"]["runs"]["series10_v2"]
    assert FJ.tier_name(runs_v, 1) == "base35" and FJ.tier_name(runs_v, 2) == "turbo_previz" and rq["first_frame_tier"]["base35"]["steps"] == 35


def test_imggen_turbo8_rule_scoped_to_v1_after_l191():
    rules = yaml.safe_load((ROOT / "knowledge/rules/render_imggen_s10.yaml").read_text(encoding="utf-8"))["rules"]
    r = next(x for x in rules if x["id"] == "K-REN-124")
    assert "series10_v1" in r["when"] and "L-191" in r["when"] and "base35" in r["when"]


def test_camera_moves_whitelist_is_six_after_l192():
    cm = yaml.safe_load((ROOT / "config/director/camera_moves.yaml").read_text(encoding="utf-8"))
    enabled = {m["id"] for m in cm["moves"] if m.get("enabled")}
    assert {"static", "push_in", "pull_out", "bolt_push_settle", "handheld_follow", "pedestal_up"} <= enabled
    assert not ({"truck_left", "truck_right", "arc", "orbit_slowmo"} & enabled)
    assert set(cm["multi_person_moves"]) <= enabled and {"static", "push_in", "pull_out", "handheld_follow"} <= set(cm["multi_person_moves"])


def test_ops_infra_rules_i08_i10_present():
    rules = yaml.safe_load((ROOT / "knowledge/rules/ops_infra.yaml").read_text(encoding="utf-8"))["rules"]
    ids = {r["id"] for r in rules}
    assert {"K-OPS-I08", "K-OPS-I09", "K-OPS-I10"} <= ids
    for r in rules:
        for k in ("id", "domain", "link", "title", "when", "then", "evidence", "confidence", "status", "date"):
            assert k in r, (r["id"], k)
