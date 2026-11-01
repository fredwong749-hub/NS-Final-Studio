"""tools/ 同名脚本歧义守卫（ITERAUDIT 11-01，K-OPS-Q11）：两个 run.py 同在 sys.path 上 → 明确报错；只有一个 → 导入对的那个，
缓存里是另一个时先换掉。也核对真实仓库：tools/autopilot/run.py 与 tools/bakeoff/run.py 被识别为歧义名。"""
import sys

import pytest

import script_name_guard as SNG


def _two_runs(tmp_path):
    for d, mark in (("autopilot", "AUTOPILOT"), ("bakeoff", "BAKEOFF")):
        (tmp_path / d).mkdir()
        (tmp_path / d / "zz_run_probe.py").write_text(f"WHO = {mark!r}\n", encoding="utf-8")
    return {"zz_run_probe": [(tmp_path / "autopilot" / "zz_run_probe.py").resolve(),
                             (tmp_path / "bakeoff" / "zz_run_probe.py").resolve()]}


@pytest.fixture
def finder(tmp_path, monkeypatch):
    f = SNG._Finder(_two_runs(tmp_path))
    monkeypatch.setattr(sys, "meta_path", [f, *sys.meta_path])
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.delitem(sys.modules, "zz_run_probe", raising=False)
    yield f
    sys.modules.pop("zz_run_probe", None)


def test_repo_run_py_is_ambiguous():
    names = SNG.ambiguous()
    assert {p.parent.name for p in names["run"]} >= {"autopilot", "bakeoff"}


def test_both_dirs_on_path_raises_clear_error(finder, tmp_path):
    sys.path[:0] = [str(tmp_path / "bakeoff"), str(tmp_path / "autopilot")]
    with pytest.raises(SNG.AmbiguousScriptImport, match="有歧义"):
        __import__("zz_run_probe")


def test_single_dir_imports_that_one_and_replaces_stale_cache(finder, tmp_path):
    sys.path.insert(0, str(tmp_path / "bakeoff"))
    assert __import__("zz_run_probe").WHO == "BAKEOFF"
    sys.path.remove(str(tmp_path / "bakeoff"))
    sys.path.insert(0, str(tmp_path / "autopilot"))
    # 以前：缓存里还是 bakeoff 的 run → 拿错模块（收集错误 no attribute 'BASE'）
    SNG._state["finder"], old = finder, SNG._state.get("finder")
    try:
        assert SNG.evict_stale() == ["zz_run_probe"]
    finally:
        SNG._state["finder"] = old
    assert __import__("zz_run_probe").WHO == "AUTOPILOT"
