"""按剧取路径（AUDIT-M I-14，PROMPTFIX 11-02 19:0x；L-125 / L-126 V2 完全切割）。

ns_agent 的编译 / 造型 / 时间线 / 快照模块不许再写死 data/import/script_v2.json、data/looks、data/renders——
一律经这里转到 FACTORY 的唯一入口 tools/autopilot/runs.py（script_path / looks_path / renders_dir / asset_manifest）。
- root 下没有 config/pipeline/runs.json（沙箱 / 测试临时目录）→ 旧路径（行为不变）；
- 剧 = 环境变量 NS_RUN（多剧并行 run_env，K-OPS-E15）或 runs.json 的 primary；
- NS_SCRIPT_JSON 环境变量仍优先（与 ns_render.pipeline.SCRIPT_JSON 同一口径）；
- 失败关闭：非 legacy 剧解析出的路径落在 V1 的旧位置（data/import/script_v2.json、data/looks、data/renders 根）→ raise。
"""
from __future__ import annotations

import importlib.util
import os
from functools import lru_cache
from pathlib import Path


class V1PathError(RuntimeError):
    """V2（非 legacy 剧）读到了 V1 的旧路径"""


@lru_cache(maxsize=8)
def _runs_mod(root: str):
    p = Path(root) / "tools" / "autopilot" / "runs.py"
    if not p.is_file():
        return None
    sp = importlib.util.spec_from_file_location(f"runs_for_ns_agent_{abs(hash(root))}", p)
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


def runs_module(root=None):
    """services 侧加载 tools/autopilot/runs.py 的唯一入口（OVERSIGHT-F P2：副本收口）；root 默认本仓库；没有 runs.py → None"""
    return _runs_mod(str(Path(root) if root else Path(__file__).resolve().parents[3]))


def _ctx(root) -> tuple:
    root = Path(root)
    if not (root / "config" / "pipeline" / "runs.json").is_file():
        return root, None, None, True
    m = _runs_mod(str(root))
    if m is None:
        return root, None, None, True
    run = m.current_run(root) if hasattr(m, "current_run") else (os.environ.get("NS_RUN") or m.primary_run(root))   # OVERSIGHT-F P2 统一认法
    return root, m, run, bool(m.is_legacy(run, root))


def _guard(root: Path, p: Path, legacy: bool, legacy_paths: tuple) -> Path:
    if not legacy and any(p.resolve() == (root / x).resolve() for x in legacy_paths):
        raise V1PathError(f"非 V1 剧解析到了 V1 路径 {p}（L-126 完全切割）")
    return p


def current_run(root) -> str | None:
    return _ctx(root)[2]


def script_json(root) -> Path:
    env = os.environ.get("NS_SCRIPT_JSON")
    if env:
        return Path(env)
    root, m, run, legacy = _ctx(root)
    if m is None:
        return root / "data" / "import" / "script_v2.json"
    return _guard(root, Path(m.script_path(run, root)), legacy, ("data/import/script_v2.json",))


def looks_dir(root) -> Path:
    root, m, run, legacy = _ctx(root)
    if m is None:
        return root / "data" / "looks"
    return _guard(root, Path(m.looks_path(run, root)), legacy, ("data/looks",))


def renders_dir(root) -> Path:
    env = os.environ.get("NS_RENDERS_DIR")
    if env:
        return Path(env)
    root, m, run, legacy = _ctx(root)
    if m is None:
        return root / "data" / "renders"
    return _guard(root, Path(m.renders_dir(run, root)), legacy, ("data/renders",))


def asset_manifest(root) -> Path | None:
    root, m, run, _legacy = _ctx(root)
    return Path(m.asset_manifest(run, root)) if m is not None and m.asset_manifest(run, root) else None
