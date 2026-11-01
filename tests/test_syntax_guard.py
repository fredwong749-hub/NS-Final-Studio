"""K-OPS-C01：全仓 Python 语法 / 导入守卫（tools/qa/syntax_guard.py，CODE-RSI 2026-11-01）。
起因：11-01 三次“别的 loop 把字符串写断 → 全部测试起不来”（unified_frame.py 16:55、pipeline.py 17:48）。"""
import ast
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("ns_syntax_guard_t", ROOT / "tools/qa/syntax_guard.py")
SG = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(SG)


def _codes(tmp_path, name, src: str | bytes):
    f = tmp_path / name
    f.write_bytes(src if isinstance(src, bytes) else src.encode("utf-8"))
    return [e["code"] for e in SG.check_file(str(f))["errors"]]


def test_detects_broken_string_and_syntax(tmp_path):
    assert _codes(tmp_path, "a.py", 'x = "写断的字符串\ny = 1\n') == ["E2"]
    assert _codes(tmp_path, "b.py", "def f(:\n  pass\n") == ["E2"]
    assert _codes(tmp_path, "c.py", b"x = 1\x00\n") == ["E2"]


def test_detects_invalid_escape_and_bad_utf8(tmp_path):
    assert _codes(tmp_path, "d.py", 'x = "a\\|b"\n') == ["E2"]
    assert _codes(tmp_path, "e.py", b'x = "\xc3\x28"\n') == ["E1"]


def test_detects_undefined_name_but_not_style(tmp_path):
    assert _codes(tmp_path, "f.py", "def f():\n    return undefined_thing\n") == ["E3"]
    assert _codes(tmp_path, "g.py", "import os\nx = 1\n") == []          # 未使用的导入不算
    assert _codes(tmp_path, "h.py", "﻿x = '中文'\n") == []            # BOM 允许


def test_project_import_resolution():
    pk = SG.package_roots()
    assert {"ns_agent", "ns_api", "ns_render", "ns_recipes", "ns_schema"} <= set(pk)

    def errs(src):
        return SG.check_imports(Path("x.py"), ast.parse(src), pk)
    assert errs("from ns_agent import frame_job\nimport ns_render.unified_frame\nimport json\n") == []
    assert errs("from ns_agent.frame_job_nope import x\n")[0]["code"] == "E4"
    assert errs("import ns_render.nope_mod\n")[0]["code"] == "E4"
    e = errs("from ns_render.unified_frame import definitely_not_a_name_xyz\n")
    assert e and "definitely_not_a_name_xyz" in e[0]["msg"]
    assert errs("from third_party_pkg.sub import anything\n") == []      # 非项目包不管


def test_whole_repo_is_clean():
    """全仓守卫本身（iter_gate Y1 同一份检查）：任何 loop 写断字符串 / 删掉被导入的名字，这里先红"""
    rep = SG.run()
    assert rep["files"] > 300
    assert rep["verdict"] == "PASS", "\n".join(f"{e['file']}:{e['line']} {e['code']} {e['msg']}" for e in rep["errors"][:20])


def test_iter_gate_runs_syntax_guard_as_y1(monkeypatch):
    """iter_gate 收轮必过 Y1：守卫退出 1 → Y1 不通过；CODE-RSI 别名映射到 ownership 条目 CODERSI"""
    import types
    spec = importlib.util.spec_from_file_location("ns_iter_gate_sg", ROOT / "tools/qa/iter_gate.py")
    IG = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(IG)
    g = IG.Gate(types.SimpleNamespace(loop="CODE-RSI", changed=["tools/qa/syntax_guard.py"], ui=False))
    assert g.loop == "CODERSI"
    calls = []
    monkeypatch.setattr(IG, "sh", lambda cmd, timeout=900: (calls.append(cmd) or (1, "x.py:1: E2 SyntaxError")))
    g.y1_syntax()
    assert g.rows[-1]["id"] == "Y1" and g.rows[-1]["status"] == "fail"
    assert any("syntax_guard.py" in c for c in calls[0])
    assert "self.y1_syntax()" in (ROOT / "tools/qa/iter_gate.py").read_text(encoding="utf-8")


def test_consent_glob_strips_trailing_note():
    """K-OPS-C06：CONSENT 行路径后直接跟“（只改 …）”说明时，glob 只取路径本身"""
    spec = importlib.util.spec_from_file_location("ns_iter_gate_sg2", ROOT / "tools/qa/iter_gate.py")
    IG = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(IG)
    c = IG.parse_consents("- CONSENT: ITERAUDIT -> CODERSI : tools/qa/iter_gate.py（只加 Y1） | by 总调度\n"
                          "- CONSENT: BAKEOFF -> RESEARCH : knowledge/rules/render_qwen21.yaml(only Q29) | x\n"
                          "- CONSENT: UIPIXEL -> UIRSI : apps/web/src/ds/live.css | y\n")
    assert [x["glob"] for x in c] == ["tools/qa/iter_gate.py", "knowledge/rules/render_qwen21.yaml", "apps/web/src/ds/live.css"]
    assert IG.consented("tools/qa/iter_gate.py", "ITERAUDIT", "CODERSI", c)
