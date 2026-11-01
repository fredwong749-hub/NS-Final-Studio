"""SYSARCH 线 5 打分器（tools/rsi/system_score.py；K-OPS-Y01）。全部用临时目录假数据，不读真实 data/。"""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("system_score_t", ROOT / "tools/rsi/system_score.py")
SS = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(SS)


def _w(p: Path, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def _fixture(tmp: Path):
    _w(tmp / "data/autopilot/coverage.json", {"deciders_now": {"claude": 4}, "decision_points": 50})
    _w(tmp / "data/sentinel/state.json", {"probes": {"S1": {"n": 10, "violated": 5}, "S2": {"n": 10, "violated": 0},
                                                     "S9": {"n": 5, "violated": 5, "error": "boom"}}})
    _w(tmp / "data/system_versions/last_cut.json", {"id": "sv-20261102-02", "at_iso": "2026-11-02T02:00:00", "ok": True})
    _w(tmp / "data/system_versions/index.json", {"versions": [{"id": "sv-20261102-01"}, {"id": "sv-20261102-02"}]})
    _w(tmp / "data/system_versions/deploy_sv-20261102-01_1.json", {"id": "sv-20261102-01", "hosts": {"a": {"ok": True}, "b": {"ok": True}}})
    _w(tmp / "data/system_versions/deploy_sv-20261102-02_1.json", {"id": "sv-20261102-02", "hosts": {"a": {"ok": True}, "b": {"ok": False}}})
    half = {k: v // 2 for k, v in SS.STRUCT_ANCHOR.items()}
    _w(tmp / "data/sysarch/scan_latest.json", {"totals": {**half, "pipe_gate": 999}, "at": "x"})
    _w(tmp / "knowledge/generated/index.json", {"rules": [{"id": "A", "date": "2026-11-02", "check": ["t"]},
                                                          {"id": "B", "date": "2026-11-02", "check": []},
                                                          {"id": "C", "date": "2026-11-01"}]})


def test_parts_and_weights(tmp_path):
    _fixture(tmp_path)
    r = SS.score(root=tmp_path, out=tmp_path / "data/rsi", write=True, day="2026-11-02")
    p = r["parts"]
    assert p["no_claude"] == 50.0                              # 4 / 8
    assert p["self_run"] == round((0.75 + 0.5) / 2 * 100, 1)   # 报错的探针 S9 不算样本
    assert p["release"] == 100.0                                # 一次通过 + 落后 1 版（02 只有一台成功 → 最新全量部署 01）
    assert 49 <= p["structure"] <= 51                           # 后加的检查项（pipe_gate）不算进锚点比较
    assert p["rule_coverage"] == 50.0 and r["detail"]["rule_coverage"]["missing_check"] == ["B"]
    assert not r["partial"] and r["line"] == "system"
    assert (tmp_path / "data/rsi/scores.jsonl").read_text(encoding="utf-8").count('"line": "system"') == 1


def test_missing_source_is_null_not_zero(tmp_path):
    _fixture(tmp_path)
    (tmp_path / "data/sentinel/state.json").unlink()
    r = SS.score(root=tmp_path, out=tmp_path / "data/rsi", write=False, day="2026-11-02")
    assert r["parts"]["self_run"] is None and "self_run" in r["missing"] and r["partial"]
    assert r["score"] is not None


def test_first_attempt_failure_counts(tmp_path):
    _fixture(tmp_path)
    (tmp_path / "data/rsi").mkdir(parents=True)
    (tmp_path / "data/rsi/cut_seen.jsonl").write_text(
        json.dumps({"id": "sv-20261102-02", "at": "2026-11-02T01:00:00", "ok": False}) + "\n", encoding="utf-8")
    r = SS.score(root=tmp_path, out=tmp_path / "data/rsi", write=False, day="2026-11-02")
    assert r["detail"]["release"]["first_pass_rate"] == 0.0


def test_gpu_from_sentinel_24h(tmp_path):
    _fixture(tmp_path)
    _w(tmp_path / "data/rsi/gpu_24h.json", {"for_rsi_line5": {"productive_pct": 40.0}})
    r = SS.score(root=tmp_path, out=tmp_path / "data/rsi", write=False, day="2026-11-02")
    d = r["detail"]["self_run"]
    assert d["gpu_src"] == "gpu_24h.productive_pct" and d["gpu_score"] == 0.5
    assert r["parts"]["self_run"] == round((0.75 + 0.5) / 2 * 100, 1)
