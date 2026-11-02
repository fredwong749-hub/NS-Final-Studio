"""删除前反查（tools/qa/purge_precheck.py，K-OPS-Y06）。用临时目录造知识库，不碰真实文件。"""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def PP(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("purge_precheck_t", ROOT / "tools/qa/purge_precheck.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    monkeypatch.setattr(m, "ROOT", tmp_path)
    (tmp_path / "knowledge/rules").mkdir(parents=True)
    (tmp_path / "config").mkdir()
    (tmp_path / "knowledge/rules/a.yaml").write_text(
        "rules:\n  - id: K-X-1\n    evidence:\n      - {src: data/_quarantine_x/old/run.log, note: n}\n"
        "  - id: K-X-2\n    evidence:\n      - {src: docs/keep.md, note: n}\n", encoding="utf-8")
    (tmp_path / "config/owner_decisions.yaml").write_text("- id: D-1\n  check: data/_quarantine_y/sheet.json\n", encoding="utf-8")
    return m


def test_rule_evidence_under_deleted_dir_is_reported(PP):
    hits = PP.check(["data/_quarantine_x"])
    assert len(hits) == 1 and hits[0]["rule"] == "K-X-1" and hits[0]["ref"] == "data/_quarantine_x/old/run.log"
    assert "knowledge/archive/deleted_evidence.md" in hits[0]["fix"]


def test_owner_decisions_reference_is_reported(PP):
    hits = PP.check(["data/_quarantine_y/sheet.json"])
    assert len(hits) == 1 and hits[0]["file"] == "config/owner_decisions.yaml"


def test_clean_path_passes_and_emits_guarded_ps1(PP, tmp_path):
    assert PP.check(["data/_quarantine_z"]) == []
    assert PP.main(["data/_quarantine_z", "--emit-ps1", "ops/cleanup/del.ps1"]) == 0
    ps1 = (tmp_path / "ops/cleanup/del.ps1").read_text(encoding="utf-8-sig")
    assert ps1.index("purge_precheck.py") < ps1.index("Remove-Item") and "exit 1" in ps1


def test_referenced_path_refuses_to_emit_ps1(PP, tmp_path):
    assert PP.main(["data/_quarantine_x", "--emit-ps1", "ops/cleanup/del.ps1"]) == 1
    assert not (tmp_path / "ops/cleanup/del.ps1").exists()
