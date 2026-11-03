"""派生参考图（refboards / refcrops）写出根跟随 DERIVED_OUT（总调度 11-03：测试不许写真实 images/refboards）。"""
from __future__ import annotations

import shutil
from pathlib import Path

from PIL import Image

from ns_agent import asset_refs as AR

ROOT = Path(__file__).resolve().parents[1]
BOARD_DIR = "data/pipeline/runs/fx_run/images/refboards"


def _tiles(tmp_path):
    out = []
    for n, c in enumerate(("red", "blue")):
        f = tmp_path / f"face_{n}.png"
        Image.new("RGB", (64, 64), c).save(f)
        out.append((str(f), f"人{n}"))
    return out


def test_sandbox_patches_derived_out():
    """conftest 沙盒把 DERIVED_OUT 指到 .pytest_sandbox 下：任何测试里编译出的新参考板都不进真实目录"""
    assert AR.DERIVED_OUT is not None
    assert ".pytest_sandbox" in Path(AR.DERIVED_OUT).as_posix()


def test_new_board_goes_to_derived_out(monkeypatch, tmp_path):
    out_root = tmp_path / "derived"
    monkeypatch.setattr(AR, "DERIVED_OUT", out_root)
    monkeypatch.setattr(AR, "project_cfg", lambda project: {"board_dir": BOARD_DIR})
    monkeypatch.setattr(AR, "_on_server", lambda: False)
    monkeypatch.setattr(AR, "derived_writable", lambda run: True)       # 假剧 fx_run 当作制作中
    got = Path(AR.make_board("fx_run", _tiles(tmp_path)))
    assert got.is_file() and out_root in got.parents
    assert not (ROOT / BOARD_DIR / got.name).exists()                    # 真实目录没写
    assert got.name in AR._derived_index(got.parent)                       # 账本也写在沙盒


def test_existing_real_board_reused_read_only(monkeypatch, tmp_path):
    """真实目录里已有同名图：只读复用，不补账本、不在沙盒另生成"""
    monkeypatch.setattr(AR, "project_cfg", lambda project: {"board_dir": BOARD_DIR})
    monkeypatch.setattr(AR, "_on_server", lambda: False)
    monkeypatch.setattr(AR, "derived_writable", lambda run: True)       # 假剧 fx_run 当作制作中
    tiles = _tiles(tmp_path)
    monkeypatch.setattr(AR, "DERIVED_OUT", tmp_path / "a")
    first = Path(AR.make_board("fx_run", tiles))
    fake_root = tmp_path / "root"
    real = fake_root / BOARD_DIR / first.name
    real.parent.mkdir(parents=True)
    shutil.copy2(first, real)
    monkeypatch.setattr(AR, "ROOT", fake_root)
    monkeypatch.setattr(AR, "DERIVED_OUT", tmp_path / "b")
    got = Path(AR.make_board("fx_run", tiles))
    got = got if got.is_absolute() else fake_root / got                     # rel() 相对（被换掉的）ROOT
    assert got.resolve() == real.resolve()
    assert not (tmp_path / "b").exists() and not (real.parent / AR.DERIVED_INDEX).exists()


def test_archived_run_still_refused_in_sandbox(monkeypatch, tmp_path):
    """写到沙盒也按逻辑目标判：已归档 / 冻结的剧照样拒绝生成新参考板"""
    import pytest
    monkeypatch.setattr(AR, "DERIVED_OUT", tmp_path / "derived")
    monkeypatch.setattr(AR, "project_cfg", lambda project: {"board_dir": BOARD_DIR})
    monkeypatch.setattr(AR, "_on_server", lambda: False)
    monkeypatch.setattr(AR, "derived_writable", lambda run: False)
    with pytest.raises(AR.DerivedWriteRefused):
        AR.make_board("fx_run", _tiles(tmp_path))


def test_production_default_writes_repo_dir(monkeypatch):
    monkeypatch.setattr(AR, "DERIVED_OUT", None)
    p, w = AR.derived_target(BOARD_DIR, "board_x.png")
    assert p == AR.ROOT / BOARD_DIR / "board_x.png" and w is True
