"""K-OPS-V01：系统版本工具（tools/qa/system_version.py，CODE-RSI r3）。不提交、不推送，只测纯函数与闸门判定。"""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("ns_system_version_t", ROOT / "tools/qa/system_version.py")
SV = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(SV)


def test_next_id_increments_per_day():
    assert SV.next_id("20261101", []) == "sv-20261101-01"
    assert SV.next_id("20261101", ["sv-20261101-01", "sv-20261101-02", "sv-20261031-07"]) == "sv-20261101-03"
    assert SV.next_id("20261102", ["sv-20261101-09"]) == "sv-20261102-01"


def test_pick_tests_includes_smoke_and_related():
    t = SV.pick_tests(["tools/qa/syntax_guard.py", "tests/test_push_check.py", "docs/x.md"])
    assert "tests/test_syntax_guard.py" in t and "tests/test_push_check.py" in t
    assert all((ROOT / x).exists() for x in t)


def test_gate_blocks_on_decision_cross(monkeypatch):
    outs = {"syntax_guard.py": (0, "syntax_guard PASS"), "compile.py": (0, "OK"),
            "decision_check.py": (0, "合计 62：✅ 60  ❌ 1  ⏳ 1  ⏭ 0"), "decision_propagation.py": (0, "ok")}

    def fake(cmd, timeout=1800, cwd=None):
        return next((v for k, v in outs.items() if any(k in c for c in cmd)), (0, ""))
    monkeypatch.setattr(SV, "sh", fake)
    rows = {r["id"]: r for r in SV.gates([], run_tests=False)}
    assert not rows["decision"]["ok"] and rows["syntax"]["ok"]
    outs["decision_check.py"] = (0, "合计 62：✅ 61  ❌ 0  ⏳ 1  ⏭ 0")     # ⏳ 可以
    assert {r["id"]: r for r in SV.gates([], run_tests=False)}["decision"]["ok"]


def test_flat_config_keys():
    assert SV._flat({"a": {"b": 1, "c": {"d": 2}}, "e": []}) == {"a.b": 1, "a.c.d": 2, "e": []}


def test_iter_gate_warns_when_changes_not_in_a_version(monkeypatch):
    import types
    spec = importlib.util.spec_from_file_location("ns_iter_gate_sv", ROOT / "tools/qa/iter_gate.py")
    IG = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(IG)
    g = IG.Gate(types.SimpleNamespace(loop="CODE-RSI", changed=["tools/qa/system_version.py"], ui=False))
    monkeypatch.setattr(IG, "sh", lambda cmd, timeout=900: (0, " M tools/qa/system_version.py\n"))
    g.v2_version()
    assert g.rows[-1]["id"] == "V2" and g.rows[-1]["status"] == "warn" and not g.rows[-1]["required"]
    monkeypatch.setattr(IG, "sh", lambda cmd, timeout=900: (0, ""))
    g.v2_version()
    assert g.rows[-1]["status"] == "pass"


def test_push_secret_scan_patterns():
    key = '"api' + '_key": "' + "abcdefghijklmnopqrstu" + '"'          # 拼出来，免得本文件自己被密钥扫描命中
    for bad in (key, "sk-" + "a" * 30, "ghp_" + "b" * 36, "-----BEGIN " + "PRIVATE KEY-----"):
        assert SV.PUSH_SECRET_RE.search(bad), bad
    for ok in ('"api_key": ""', "token budget 4096", "sk-short"):
        assert not SV.PUSH_SECRET_RE.search(ok), ok
