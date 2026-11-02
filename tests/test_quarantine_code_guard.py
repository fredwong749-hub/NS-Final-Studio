"""ISS-1103-033325-9b07（SYSAUDIT-F 11-03）：tools/ tests/ 下的 .py 是系统代码，不属于“内容隔离”。

golden_worker.py 和 test_golden_pipeline.py 被移进 data/_quarantine_20261103_golden_o/ 后，阶段 B 没有执行器。守卫：
① quarantine_refcheck.protected_code：tools/ tests/ 的 .py（含目录里的）一律视为有引用；
② quarantine_safe_move / quarantine_move：status=kept_code，ref_override 也不放行；
③ quarantined_code：已经躺在 data/_quarantine*/tools|tests 里的 .py 查得出来（手工 mv 也能抓）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "qa"))
import quarantine_refcheck as RC  # noqa: E402
import quarantine_safe_move as SM  # noqa: E402


def _w(p: Path, text="x = 1\n") -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def test_protected_code_paths(tmp_path):
    _w(tmp_path / "tools/pipeline/golden_worker.py")
    _w(tmp_path / "tests/test_golden_pipeline.py")
    _w(tmp_path / "tools/pipeline/notes.md", "doc")
    _w(tmp_path / "data/pipeline/asset_jobs/r/golden-ep01-S01.json", "{}")
    assert RC.protected_code(tmp_path / "tools/pipeline/golden_worker.py", tmp_path) == ["tools/pipeline/golden_worker.py"]
    assert RC.protected_code("tests/test_golden_pipeline.py", tmp_path) == ["tests/test_golden_pipeline.py"]
    assert RC.protected_code(tmp_path / "tools/pipeline", tmp_path) == ["tools/pipeline/golden_worker.py"]   # 整个目录也挡
    assert RC.protected_code(tmp_path / "tools/pipeline/notes.md", tmp_path) == []            # 非 .py 照旧走引用检查
    assert RC.protected_code(tmp_path / "data/pipeline/asset_jobs/r/golden-ep01-S01.json", tmp_path) == []   # 内容照旧可隔离


def test_safe_move_refuses_code_even_with_ref_override(tmp_path, monkeypatch):
    monkeypatch.setattr(SM, "ROOT", tmp_path)
    monkeypatch.setattr(RC, "ROOT", tmp_path)
    src = _w(tmp_path / "tools/pipeline/golden_worker.py")
    q = tmp_path / "data/_quarantine_x"
    rec = SM.move_one({"src": "tools/pipeline/golden_worker.py", "reason": "回退", "ref_override": "没人读"}, q)
    assert rec["status"] == "kept_code" and src.exists() and not (q / "tools/pipeline/golden_worker.py").exists()
    _w(tmp_path / "tests/test_golden_pipeline.py")
    rec = SM.move_one({"src": "tests", "reason": "旧"}, q, dry=True)
    assert rec["status"] == "kept_code"


def test_legacy_quarantine_move_refuses_code(tmp_path, monkeypatch):
    import importlib.util
    sp = importlib.util.spec_from_file_location("quarantine_move_t", ROOT / "tools/qa/quarantine_move.py")
    QM = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(QM)
    monkeypatch.setattr(QM, "ROOT", tmp_path)
    monkeypatch.setattr(QM, "Q", tmp_path / "data/_quarantine_y")
    src = _w(tmp_path / "tests/test_golden_pipeline.py")
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps([{"cat": "code", "src": str(src), "reason": "旧"}]), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["quarantine_move.py", str(plan)])
    QM.main()
    assert src.exists()
    rows = [json.loads(x) for x in (tmp_path / "data/_quarantine_y/moves.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rows[0]["status"] == "kept_code"


def test_refcheck_cli_marks_code_referenced(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(RC, "ROOT", tmp_path)
    monkeypatch.setattr(RC, "rg", lambda terms, dirs: [])          # 没有任何文本引用也算有引用
    _w(tmp_path / "tools/pipeline/golden_worker.py")
    assert RC.main([str(tmp_path / "tools/pipeline/golden_worker.py")]) == 1
    assert "REFERENCED" in capsys.readouterr().out


def test_scan_finds_code_already_in_quarantine(tmp_path, monkeypatch):
    _w(tmp_path / "data/_quarantine_20261103_golden_o/tools/pipeline/golden_worker.py")
    _w(tmp_path / "data/_quarantine_20261103_golden_o/tests/test_golden_pipeline.py")
    _w(tmp_path / "data/_quarantine_20261103_golden_o/data/pipeline/asset_jobs/r/golden-ep01-S01.json", "{}")
    _w(tmp_path / "data/_quarantine_20261101b/data/old/script.py")                 # data 下的 .py 是内容（旧脚本产物），不报
    assert RC.quarantined_code(tmp_path) == ["data/_quarantine_20261103_golden_o/tests/test_golden_pipeline.py",
                                             "data/_quarantine_20261103_golden_o/tools/pipeline/golden_worker.py"]


# ---------------------------------------------------------------- 例外：显式退役清单 <qdir>/RETIRED.json（总调度 11-03 选 C）
def test_explicit_retire_moves_and_records(tmp_path, monkeypatch):
    monkeypatch.setattr(SM, "ROOT", tmp_path)
    monkeypatch.setattr(RC, "ROOT", tmp_path)
    src = _w(tmp_path / "tools/pipeline/golden_worker.py")
    q = tmp_path / "data/_quarantine_x"
    bad = SM.move_one({"src": "tools/pipeline/golden_worker.py", "reason": "x", "retire": {"reason": "并回 producer"}}, q)
    assert bad["status"] == "kept_code" and src.exists()                     # 没写 by（谁定的）不算显式退役
    rec = SM.move_one({"src": "tools/pipeline/golden_worker.py", "reason": "并回",
                       "retire": {"reason": "L-151 并回 producer", "by": "总调度", "decision": "L-151"}}, q)
    assert rec["status"] == "moved" and not src.exists() and (q / "tools/pipeline/golden_worker.py").exists()
    assert set(RC.retired_list(q)) == {"tools/pipeline/golden_worker.py"}
    assert RC.quarantined_code(tmp_path) == []                                # 登记过的不再报误隔离


def test_scan_respects_retired_list_and_retire_existing_cli(tmp_path, monkeypatch):
    q = tmp_path / "data/_quarantine_20261103_golden_o"
    _w(q / "tools/pipeline/golden_worker.py")
    _w(q / "tests/test_golden_pipeline.py")
    assert len(RC.quarantined_code(tmp_path)) == 2
    monkeypatch.setattr(SM, "ROOT", tmp_path)
    qd = "data/_quarantine_20261103_golden_o"
    assert SM.main(["--qdir", qd, "--retire-existing", "tools/pipeline/golden_worker.py", "--reason", "L-151", "--by", "总调度"]) == 0
    assert RC.quarantined_code(tmp_path) == [f"{qd}/tests/test_golden_pipeline.py"]
    assert SM.main(["--qdir", qd, "--retire-existing", "tools/nope.py", "--reason", "r", "--by", "b"]) == 1
    import pytest
    with pytest.raises(ValueError):
        RC.record_retired(q, "tests/test_golden_pipeline.py", "", "总调度")
