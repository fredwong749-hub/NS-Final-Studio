"""逻辑纪律补丁 v3 §2e：assemble_series.sweep 熔断 + 合并状态拉取失败不拿旧副本算指纹。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import assemble_series as A  # noqa: E402


def _wire(tmp_path, monkeypatch, sigs, merged_fail=False):
    monkeypatch.setattr(A, "SWEEP_STATE", tmp_path / "sweep.json")
    monkeypatch.setattr(A, "BUILD_LOCK", tmp_path / "lock.json")
    man = tmp_path / "man.json"
    monkeypatch.setattr(A.RUNS, "renders_dir", lambda run, root: tmp_path)
    (tmp_path / "ep01/_final").mkdir(parents=True, exist_ok=True)
    it = iter(sigs)
    cur = {"sig": None}

    def merged_state(refresh):
        if merged_fail and refresh:
            raise OSError("pull failed")
        return {"m": 1}
    monkeypatch.setattr(A, "merged_state", merged_state)
    monkeypatch.setattr(A, "plan", lambda e, m, best_effort_video=True: [])
    monkeypatch.setattr(A, "signature", lambda rows: cur["sig"])
    built = []

    def build(e, preview=True):
        built.append(cur["sig"])
        A.write_json(tmp_path / "ep01/_final/preview_latest_manifest.json", {"signature": "built-" + str(len(built)), "built_at": 0})
    monkeypatch.setattr(A, "build", build)
    monkeypatch.setattr(A, "_alarm", lambda e, why: built.append("ALARM"), raising=False)
    return it, cur, built


def test_breaker_stops_flip_flop(tmp_path, monkeypatch):
    it, cur, built = _wire(tmp_path, monkeypatch, [])
    t = 1_000_000.0
    for i in range(12):                                   # 两台合并状态摇摆：指纹在 A / B 之间来回
        cur["sig"] = "A" if i % 2 == 0 else "B"
        A.sweep(now=t, eps=[1])
        t += 3600
    builds = [x for x in built if x != "ALARM"]
    assert len(builds) <= 4 and "ALARM" in built


def test_pull_failure_skips_fingerprint(tmp_path, monkeypatch):
    it, cur, built = _wire(tmp_path, monkeypatch, [], merged_fail=True)
    cur["sig"] = "A"
    assert A.sweep(now=1_000_000.0, eps=[1]) == [] and built == []
