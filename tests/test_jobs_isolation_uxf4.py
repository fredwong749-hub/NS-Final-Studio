"""fredw-92/UXF4：测试提交的任务记录 / 整集出片状态永远不落到真实 data/jobs（conftest._jobs_persist_isolated）。
根因：test_drain_cancels_queued 曾把 queued 的 ep02-S1 frame 任务写进真实 data/jobs/v1，API 重启后变成“失败：API 重启中断”。"""
from __future__ import annotations

import queue

from ns_api import episode_produce as EPR
from ns_api import jobs as J
from ns_render import pipeline as P


def test_submit_without_patched_data_never_writes_real_dir(monkeypatch):
    real = (P.ROOT / "data" / "jobs" / "v1").resolve()
    assert J.jobs_dir().resolve() != real
    q: "queue.Queue[str]" = queue.Queue()
    monkeypatch.setattr(J, "_lane", lambda gpu: q)
    job = J.submit("frame", "ep02-S1", 0, lambda c, j: {})
    try:
        assert (J.jobs_dir() / f"{job['id']}.json").is_file()
        assert not (real / f"{job['id']}.json").exists()
    finally:
        assert J.drain(timeout_s=1) == []


def test_episode_produce_dir_isolated():
    real = (P.ROOT / "data" / "jobs" / "episodes").resolve()
    assert EPR.Producer().dir().resolve() != real
    assert EPR.PRODUCER.dir().resolve() != real


def test_patched_data_still_followed(tmp_path, monkeypatch):
    """测试自己换了 P.DATA 的：任务记录跟着它走（老测试按 P.DATA/jobs/v1 断言）"""
    monkeypatch.setattr(P, "DATA", tmp_path / "d")
    assert J.jobs_dir() == tmp_path / "d" / "jobs" / "v1"
