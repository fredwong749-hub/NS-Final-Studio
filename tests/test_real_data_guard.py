"""真实数据写保护自测（ITERAUDIT 2026-11-01，K-OPS-Q03）：证明守卫会跳闸，且不误伤临时目录。
写操作都打向一个不存在的真实路径 data/qa/_guard_probe/…；守卫在写之前就抛错，所以真实目录不会被创建。"""
import os
import threading
from pathlib import Path

import pytest

import real_data_guard as RDG

ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "data" / "qa" / "_guard_probe" / "x.json"


def test_guard_is_installed_for_the_session():
    assert RDG.active()


@pytest.mark.parametrize("write", [
    lambda: open(PROBE, "w"),
    lambda: PROBE.write_text("{}", encoding="utf-8"),
    lambda: os.replace(__file__, PROBE),
    lambda: PROBE.parent.mkdir(parents=True),
    lambda: os.open(str(PROBE), os.O_WRONLY | os.O_CREAT),
])
def test_guard_trips_on_real_data_write(write):
    with RDG.expect_violation() as caught:
        with pytest.raises(RDG.RealDataWriteError):
            write()
    assert caught and RDG.is_real(caught[0]["path"])
    assert not PROBE.parent.exists()


def test_guard_trips_in_background_thread_even_if_swallowed():
    """03:15 事故的形状：后台线程写真实数据、异常被吞——仍然记账"""
    def worker():
        try:
            PROBE.write_text("{}", encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
    with RDG.expect_violation() as caught:
        t = threading.Thread(target=worker, name="probe-postflight")
        t.start()
        t.join(5)
    assert [c["thread"] for c in caught] == ["probe-postflight"]


def test_tmp_writes_and_real_reads_still_work(tmp_path):
    f = tmp_path / "ok.json"
    f.write_text("{}", encoding="utf-8")
    os.replace(f, tmp_path / "ok2.json")
    assert (tmp_path / "ok2.json").read_text(encoding="utf-8") == "{}"
    assert (ROOT / "pyproject.toml").read_text(encoding="utf-8")


def test_data_roots_point_to_sandbox():
    from ns_render import pipeline as P
    assert not RDG.is_real(P.DATA) and not RDG.is_real(P.RENDERS)
