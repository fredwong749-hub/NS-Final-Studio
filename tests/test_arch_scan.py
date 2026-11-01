"""SYSARCH 11-02：结构退化扫描 + 棘轮（tools/qa/arch_scan.py；规则 K-OPS-S01）。纯函数测试，不读真实 data/。"""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("arch_scan_t", ROOT / "tools/qa/arch_scan.py")
AS = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(AS)


def test_no_timeout_counts_only_missing_timeout():
    src = ("import subprocess\n"
           "subprocess.run(['ls'])\n"
           "subprocess.run(['ls'], timeout=5)\n"
           "subprocess.check_output('x', shell=True)\n"
           "subprocess.run(['ls'], **kw)\n"
           "subprocess.Popen(['ls'])\n")
    assert AS.scan_source("tools/x.py", src)["no_timeout"] == 2


def test_direct_ssh_and_gate_files_exempt():
    src = "import subprocess\nsubprocess.run(['ssh', 'gpu33', 'ls'], timeout=3)\nsubprocess.Popen('scp a b')\n"
    assert AS.scan_source("tools/x.py", src)["direct_ssh"] == 2
    assert AS.scan_source("tools/netfix/rssh.py", src)["direct_ssh"] == 0


def test_def_ssh_parallel_impl():
    assert AS.scan_source("tools/x.py", "def ssh(h, c):\n    pass\ndef _ssh(h):\n    pass\ndef ssh_ok():\n    pass\n")["def_ssh"] == 2


def test_hard_run_allowlist():
    s = "RUN = 'series10_v1'\nP = 'data/pipeline/runs/series10_v1/x'\n"
    assert AS.scan_source("tools/x.py", s)["hard_run"] == 2
    assert AS.scan_source("tools/autopilot/runs.py", s)["hard_run"] == 0


def test_silent_read_fail_open():
    s = ("import json\n"
         "def a(p):\n    try:\n        return json.loads(p.read_text())\n    except (OSError, ValueError):\n        return {}\n"
         "def b(p):\n    try:\n        return json.loads(p.read_text())\n    except OSError as e:\n        raise RuntimeError(p) from e\n"
         "def c(p):\n    try:\n        x = 1\n    except Exception:\n        pass\n")
    assert AS.scan_source("tools/x.py", s)["silent_read"] == 1


def test_nonatomic_json_write():
    s = ("import json, os\n"
         "def bad(p, d):\n    p.write_text(json.dumps(d))\n"
         "def good(p, d):\n    t = p.with_suffix('.tmp')\n    t.write_text(json.dumps(d))\n    os.replace(t, p)\n"
         "def good2(p, d):\n    t = p.with_suffix('.tmp')\n    t.write_text(json.dumps(d))\n    t.replace(p)\n")
    assert AS.scan_source("tools/x.py", s)["nonatomic_json"] == 1


def test_import_names():
    assert {"tools", "autopilot", "policy", "os"} <= AS.import_names("import os\nfrom tools.autopilot import policy\n")


def test_ratchet_only_flags_regressions():
    base = {"per_file": {"a.py": {"no_timeout": 3}}, "untracked_imported": {"x.py": ["y.py"]}}
    better = {"per_file": {"a.py": {"no_timeout": 2}}, "untracked_imported": {}}
    worse = {"per_file": {"a.py": {"no_timeout": 4}, "b.py": {"def_ssh": 1}}, "untracked_imported": {"z.py": ["y.py"]}}
    assert AS.compare(better, base) == []
    bad = AS.compare(worse, base)
    assert len(bad) == 3 and any("b.py" in b for b in bad) and any("z.py" in b for b in bad)
    # 部分扫描（--files）不判未入版 import
    worse["partial"] = True
    assert len(AS.compare(worse, base)) == 2


def test_hard_run_ignores_comments_and_docstrings():
    s = '"""doc series10_v1"""\n# series10_v1\ndef f():\n    """series10_v1"""\n    return "runs/series10_v1"\n'
    assert AS.scan_source("tools/x.py", s)["hard_run"] == 1


def test_silent_read_waiver_needs_reason_marker():
    s = ("import json\n"
         "def a(p):\n    try:\n        return json.loads(p.read_text())\n"
         "    except OSError:  # arch-ok: 调用方把 None 当缺失并报警\n        return None\n")
    assert AS.scan_source("tools/x.py", s)["silent_read"] == 0


def test_partial_scan_skips_untracked_code_but_full_scan_flags_it():
    base = {"per_file": {}}
    cur = {"per_file": {"new.py": {"untracked_code": 1, "no_timeout": 1}}}
    assert len(AS.compare(cur, base)) == 2
    cur["partial"] = True
    assert AS.compare(cur, base) == ["no_timeout: new.py 0→1"]


def test_iter_gate_runs_a1():
    src = (ROOT / "tools/qa/iter_gate.py").read_text(encoding="utf-8")
    assert "def a1_arch" in src and "self.a1_arch()" in src and "arch_scan.py" in src


def test_repair_chain_prefix_uses_registered_runs():
    import sys
    sys.path.insert(0, str(ROOT / "tools/pipeline"))
    spec = importlib.util.spec_from_file_location("repair_chain_t", ROOT / "tools/pipeline/repair_chain.py")
    RC = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(RC)
    rec = [{"source": "x/漆皮之下·十日_series10_v1_qwA_ep01.md"}]
    assert RC.srcs_name_prefix(rec, ["series10_v1"]) == "漆皮之下·十日_series10_v1"
    assert RC.srcs_name_prefix([{"source": "新剧_series11_v1_ep01.md"}], ["series10_v1", "series11_v1"]) == "新剧_series11_v1"
    assert RC.srcs_name_prefix([{"source": "foo_bar.md"}], ["series10_v1"]) == "foo"


def test_parse_error_is_not_judged():
    assert AS.scan_source("tools/x.py", "def f(:\n") == {"parse_error": 1}
    assert AS.compare({"per_file": {"a.py": {"parse_error": 1}}}, {"per_file": {}}) == []
