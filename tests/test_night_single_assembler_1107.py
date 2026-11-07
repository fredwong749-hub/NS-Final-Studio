"""逻辑纪律补丁 v3 §2c：assembled_n 单一递增者 = partition video 分区里该集的视频机；别的机只读，不起 finalize。
现场：partition video ep01=gpu36（gpu36 night_state assembled_n=75），gpu33 night_state 仍挂着 ep01（host=gpu33，计数空）→
gpu33 一旦合成会从 v1 起、和 gpu36 的版本号撞。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/series10_video"))
import night as N  # noqa: E402


def _st():
    return {"eps": {"1": {"status": "rendering", "host": "gpu33"}}}


def test_non_owner_does_not_finalize(monkeypatch):
    monkeypatch.setattr(N, "partition_hosts", lambda part=None: {"1": "gpu36"})
    monkeypatch.setattr(N, "log", lambda *a, **k: None)
    called = []
    monkeypatch.setattr(N, "finalize", lambda *a, **k: called.append(1))
    monkeypatch.setattr(N, "finalize_sync", lambda ctrl: True)
    assert N.start_finalize(1, "gpu33", _st(), {}) is False and not called


def test_owner_finalizes(monkeypatch):
    monkeypatch.setattr(N, "partition_hosts", lambda part=None: {"1": "gpu33"})
    monkeypatch.setattr(N, "log", lambda *a, **k: None)
    monkeypatch.setattr(N, "ep_sig", lambda ep, host: "S")
    called = []
    monkeypatch.setattr(N, "finalize", lambda *a, **k: called.append(1))
    monkeypatch.setattr(N, "finalize_sync", lambda ctrl: True)
    assert N.start_finalize(1, "gpu33", _st(), {}) is True and called
