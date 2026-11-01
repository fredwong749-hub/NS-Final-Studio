"""K-OPS-Q30：隔离前必须先做引用检查（CLEANUP 2026-11-01）。"""
import json
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "qa"))

import quarantine_refcheck as RC  # noqa: E402
import quarantine_safe_move as QM  # noqa: E402


def test_code_reference_blocks():
    # config/script_chat.json 读 script play lib 的旧剧本做全局头 → 有引用
    r = RC.check("script play lib")
    assert r["referenced"]
    assert any("script_chat.json" in x or "visual_bible.toml" in x for x in r["code_refs"])


def test_knowledge_evidence_blocks():
    # K-OPS-311 的证据目录：知识库证据链算读取者（第一版漏查，compile --check 抓到）
    r = RC.check("data/_quarantine/prod_20261101_truncated_sheets")
    assert r["referenced"]
    assert any(x.startswith("knowledge") for x in r["code_refs"])


def test_unreferenced_is_clean(tmp_path):
    p = tmp_path / f"_probe_{uuid.uuid4().hex}.txt"   # 名字现场生成（不写真实数据目录，real_data_guard）
    p.write_text("probe", encoding="utf-8")
    assert not RC.check(p)["referenced"]


def test_terms_skip_generic_and_dates():
    t = RC.terms_for(ROOT / "data" / "_trash" / "2026-11-01")
    assert "2026-11-01" not in t
    assert "data/_trash/2026-11-01" in t


def test_safe_move_keeps_referenced_and_moves_clean(tmp_path, monkeypatch):
    q = tmp_path / "q"
    q.mkdir()
    rec_ref = QM.move_one({"src": "script play lib", "reason": "测试"}, q, dry=True)   # 真仓库、只演练
    assert rec_ref["status"] == "kept_referenced"
    root = tmp_path / "repo"
    (root / "data").mkdir(parents=True)
    probe = root / "data" / "old.txt"
    probe.write_text("probe", encoding="utf-8")
    monkeypatch.setattr(QM, "ROOT", root)
    monkeypatch.setattr(RC, "ROOT", root)
    q2 = root / "data" / "_quarantine_test"
    rec = QM.move_one({"src": "data/old.txt", "reason": "测试"}, q2, dry=False)
    assert rec["status"] == "moved" and not rec["code_refs"]
    assert (q2 / "data" / "old.txt").exists() and not probe.exists()


def test_cleanup_manifest_rows_all_checked():
    mv = ROOT / "data" / "_quarantine_20261101b" / "moves.jsonl"
    if not mv.exists():
        return
    rows = [json.loads(x) for x in mv.read_text(encoding="utf-8").splitlines() if x.strip()]
    for r in rows:
        if r.get("status") == "moved":
            # 每一项都带引用检查结果；有代码引用的必须写了 ref_override 理由
            assert "code_refs" in r
            assert not r["code_refs"] or r.get("ref_override"), r["src"]
