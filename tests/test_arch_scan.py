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


def test_full_redo_run_dir_strict_on_server(monkeypatch, tmp_path):
    import sys
    sys.path.insert(0, str(ROOT / "tools/autopilot"))
    import full_redo as FR
    import runs as RUNS
    seen = {}
    monkeypatch.setattr(RUNS, "primary_run", lambda root=None, strict=False: seen.setdefault("strict", strict) and "r1" or "r1")
    monkeypatch.delenv("NS_FACTORY_HOST", raising=False)
    monkeypatch.delenv("OFFLINE_SELF", raising=False)
    assert FR.run_dir().name == "r1" and seen["strict"] is False
    seen.clear()
    monkeypatch.setenv("OFFLINE_SELF", "gpu33")
    FR.run_dir()
    assert seen["strict"] is True


def test_pipe_gate_e14_in_py_strings_not_docstrings():
    s = ('"""例：lock-status | head -2 && 改文件"""\n'
         'import subprocess\n'
         'subprocess.run("python tools/qa/system_version.py lock-status | head -2 && echo ok", shell=True, timeout=5)\n'
         'subprocess.run("set -o pipefail; pytest -q | tail -1", shell=True, timeout=5)\n')
    assert AS.scan_source("tools/x.py", s)["pipe_gate"] == 1
    assert AS.PIPE_GATE_RE.search("pytest -q tests | tail -3 && git commit")
    assert not AS.PIPE_GATE_RE.search("pytest -q tests && git commit")


def test_no_timeout_waiver_on_call_line():
    s = "import subprocess\nsubprocess.call(cmd)  # arch-ok: 包装任意命令，由外层 --timeout 管\n"
    assert AS.scan_source("tools/x.py", s)["no_timeout"] == 0


def test_scanner_not_flagged_by_netfix_ssh_regex():
    import re
    pat = re.compile(r"""\[\s*["'](ssh|scp)(\.exe)?["']|ssh\.exe["']""")
    assert not pat.search((ROOT / "tools/qa/arch_scan.py").read_text(encoding="utf-8"))


def test_tighten_only_lowers():
    base = {"per_file": {"a.py": {"no_timeout": 3, "hard_run": 2}, "b.py": {"def_ssh": 1}}, "untracked_imported": {"x.py": ["y"]}}
    cur = {"per_file": {"a.py": {"no_timeout": 1, "hard_run": 5}, "c.py": {"def_ssh": 1}}, "untracked_imported": {}}
    t = AS.tighten(base, cur)
    assert t["per_file"] == {"a.py": {"no_timeout": 1, "hard_run": 2}} and t["untracked_imported"] == {}


def test_mtime_run_guess_and_latest():
    s = ("ds = sorted(RUNS.iterdir(), key=lambda p: p.stat().st_mtime)\n"
         "def mt(p: str) -> float:\n    return 0.0\n"
         "f = max(d.glob('*.mp4'), key=lambda q: q.stat().st_mtime)\n"
         "g = max(d.glob('*.mp4'), key=lambda q: q.stat().st_mtime)  # arch-ok: 审片页展示新的在前\n")
    c = AS.scan_source("tools/x.py", s)
    assert c["mtime_run_guess"] == 2 and c["mtime_latest"] == 1


def test_ownership_alias_and_unknown_keys():
    own = {"owners": {"AUTOPILOT": ["a/**"], "AUTOPILOT_API": ["b.py"], "DEBUG_RSI": ["c.py"]}}
    f = AS.ownership_findings(own)
    assert f == ["别名 key：AUTOPILOT_API（应合进 AUTOPILOT）"]
    own = {"owners": {"AUTOPILOT": ["a/**"]}, "loops": ["AUTOPILOT"], "rule_owners": {"by_file": {"x.yaml": "INFRA"}}}
    assert AS.ownership_findings(own) == ["未知负责方 key：INFRA（不在已知 loop 里：ownership.yaml loops: 或 owners）"]
    own = {"owners": {"AUTOPILOT": ["a/**"]}, "rule_owners": {"by_id": {"K-1": "AUTOPILOT（ARCH）", "K-2": "SERIES"}}}
    assert AS.ownership_findings(own) == ["未知负责方 key：SERIES（不在已知 loop 里：ownership.yaml loops: 或 owners）"]
    assert AS.compare({"per_file": {}, "ownership_findings": ["x"]}, {"per_file": {}, "ownership_findings": ["x"]}) == []
    assert AS.compare({"per_file": {}, "ownership_findings": ["x"]}, {"per_file": {}}) == ["ownership: x"]


def test_real_ownership_has_no_alias_keys():
    assert not [x for x in AS.ownership_findings() if x.startswith("别名")]


def test_loops_registry_custodian_rules():
    own = {"owners": {"A": ["a"], "B": ["b"], "C": ["c"]},
           "loops": {"A": {"status": "active"}, "B": {"status": "inactive", "custodian": "A"},
                     "D": {"status": "inactive"}, "E": {"status": "inactive", "custodian": "B"}}}
    f = AS.ownership_findings(own)
    assert "loops 登记表：D 是 inactive 但没写 custodian" in f
    assert "loops 登记表：E 的代管方 B 不在岗" in f
    assert any("C（owners 里有、loops: 登记表里没有）" in x for x in f)
    assert not any(x.startswith("loops 登记表：B") for x in f)


def test_real_ownership_registry_clean():
    assert AS.ownership_findings() == []


def test_def_ssh_thin_wrapper_over_rssh_not_counted():
    s = ("import rssh\n"
         "def ssh(host, cmd, timeout=600):\n    return rssh.run_retry(host, cmd, timeout=timeout)\n")
    assert AS.scan_source("tools/x.py", s)["def_ssh"] == 0
    s2 = ("import rssh, subprocess\n"
          "def ssh(host, cmd):\n    rssh.status()\n    return subprocess.run(['ssh', host, cmd], timeout=5)\n")
    assert AS.scan_source("tools/x.py", s2)["def_ssh"] == 1


def test_tests_only_gate_no_timeout():
    base = {"per_file": {}}
    cur = {"per_file": {"tests/test_x.py": {"nonatomic_json": 3, "hard_run": 2, "no_timeout": 1},
                        "services/canvas_api/tests/test_y.py": {"silent_read": 1}}}
    assert AS.compare(cur, base) == ["no_timeout: tests/test_x.py 0→1"]
    assert AS.is_test("tests/a.py") and AS.is_test("services/canvas_api/tests/b.py") and not AS.is_test("tools/a.py")


def test_imported_untracked_resolves_paths_not_stems():
    unt = {"tools/imglab/score.py", "tools/autopilot/runs.py", "services/api/ns_api/current_run.py"}
    # 相对导入 ns_render.score 不是 tools/imglab/score.py
    assert AS.imported_untracked("services/render_router/ns_render/pipeline.py", "from . import score as S\n", unt) == set()
    # 包内相对导入命中
    assert AS.imported_untracked("services/api/ns_api/live.py", "from .current_run import primary_run\n", unt) == {"services/api/ns_api/current_run.py"}
    # 绝对导入按包根解析
    assert AS.imported_untracked("tests/test_x.py", "from ns_api import current_run\n", unt) == {"services/api/ns_api/current_run.py"}
    # 裸名导入：源码里插了目标目录才算
    src = "import sys\nsys.path.insert(0, str(ROOT / 'tools/autopilot'))\nimport runs\n"
    assert AS.imported_untracked("services/canvas_api/ns_canvas/app.py", src, unt) == {"tools/autopilot/runs.py"}
    assert AS.imported_untracked("tools/other/x.py", "import score\n", unt) == set()


def test_def_ssh_wrapper_via_loader_not_counted():
    s = "def ssh(cmd, timeout=600):\n    return _rssh().run_retry('gpu36', cmd, timeout=timeout)\n"
    assert AS.scan_source("tools/x.py", s)["def_ssh"] == 0


def test_iter_gate_runs_a2_new_files():
    src = (ROOT / "tools/qa/iter_gate.py").read_text(encoding="utf-8")
    assert "def a2_new_files" in src and "self.a2_new_files()" in src and '"--new", "--owner"' in src


def test_new_files_owner_filter(monkeypatch):
    monkeypatch.setattr(AS, "git_lines", lambda *a: ["tools/imglab/a.py", "tools/vidlab/b.py", "tools/x/__pycache__/c.py", "docs/x.md"])
    monkeypatch.setattr(AS, "load_owner_fn", lambda: (lambda f: "IMGLAB" if f.startswith("tools/imglab/") else "VIDLAB"))
    assert AS.new_files() == ["tools/imglab/a.py", "tools/vidlab/b.py"]
    assert AS.new_files("IMGLAB") == ["tools/imglab/a.py"]


def test_knowledge_dup_ids_blocks(tmp_path):
    (tmp_path / "a.yaml").write_text("rules:\n  - id: K-OPS-S03\n    title: x\n", encoding="utf-8")
    (tmp_path / "b.yaml").write_text("rules:\n  - id: K-OPS-S03\n  - id: K-OPS-Y01\n", encoding="utf-8")
    f = AS.knowledge_dup_ids(tmp_path)
    assert f == ["规则 id 重复：K-OPS-S03（a.yaml 和 b.yaml）"]
    assert AS.compare({"per_file": {}, "knowledge_dup_ids": f, "partial": True}, {"per_file": {}}) == ["knowledge: " + f[0]]


def test_real_knowledge_has_no_dup_ids():
    assert AS.knowledge_dup_ids() == []


def test_iter_gate_runs_q2_vqa_regression_only_when_vqa_touched():
    src = (ROOT / "tools/qa/iter_gate.py").read_text(encoding="utf-8")
    assert "def q2_vqa_regression" in src and "self.q2_vqa_regression()" in src and "tools/vqa/regression_check.py" in src


def test_prompt_bypass_outside_compile_entry():
    s = ("job = {}\nprompt = 'a'\n"
         "prompt += '，柔光'\n"
         "job['prompt'] += '镜头'\n"
         "prompt = prompt + 'x'\n"
         "prompt.append('y')\n"
         "other = other + 'z'\n")
    assert AS.scan_source("tools/x.py", s)["prompt_bypass"] == 4
    assert AS.scan_source("services/agent/ns_agent/frame_job.py", s)["prompt_bypass"] == 0   # 唯一编译入口本身
    assert AS.scan_source("config/compile/plugins/imgfix_f1.py", s)["prompt_bypass"] == 0
