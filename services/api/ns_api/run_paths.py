"""API 侧按剧取路径（AUDIT-M I-15，总调度 11-02 18:5x；规则 K-OPS-F24）：一律转调 tools/autopilot/runs.py 的唯一入口，
不许在 API 模块里写死 data/renders / data/import/script_v2.json / data/looks。不给 run = 当前 primary（现在是 series10_v2），
只有 legacy_unprefixed_run（series10_v1，已归档）走不带前缀的旧路径。"""
from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def _runs():
    from ns_agent import run_paths as _RPA     # OVERSIGHT-F P2：runs 加载器只此一处（services 侧）
    return _RPA.runs_module(REPO)


def renders_root(root: Path | None = None, run: str | None = None) -> Path:
    return _runs().renders_dir(run, Path(root) if root else REPO)


def script_path(root: Path | None = None, run: str | None = None) -> Path:
    return _runs().script_path(run, Path(root) if root else REPO)


def looks_dir(root: Path | None = None, run: str | None = None) -> Path:
    return _runs().looks_path(run, Path(root) if root else REPO)


def current_run(root: Path | None = None) -> str:
    return _runs().current_run(Path(root) if root else REPO)


def producer_dir(root: Path | None = None, run: str | None = None) -> Path:
    return _runs().producer_dir(run, Path(root) if root else REPO)


def producer_registry(root: Path | None = None, run: str | None = None) -> Path:
    """当前剧 producer 登记表（出图机写、resident_sync 同步回本机）：V2 = data/producer/runs/<run>/registry.json；legacy = data/producer/registry.json。
    UIUX-LOOP r1（11-06）：网页状态标签 / 修改队列以前读全局 data/producer/registry.json（11-03 之后没再更新），
    全剧总览把 ep01 每一镜都标成“已重置 / 驳回待重出 / 过期”；状态必须来自活的那份。"""
    return producer_dir(root, run) / "registry.json"


def v1_hidden(root: Path | None = None) -> bool:
    """L-125（项目方 18:4x：网页图片资产全部下架，只显示 V2）：当前 primary 不是 legacy 剧 → 网页不显示 V1 的图 / 资产 / 任务"""
    m = _runs()
    r = Path(root) if root else REPO
    return not m.is_legacy(None, r)


def manifest(root: Path | None = None) -> dict | None:
    """当前剧的资产包清单（没有 = None）；读坏 → {}（网页按“空”显示，不回退 V1 资产）"""
    import json
    p = _runs().asset_manifest(None, Path(root) if root else REPO)
    if not p:
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):   # arch-ok: 清单读坏 = 网页显示空，不退回 V1（资产包模式失败关闭）
        return {}


def manifest_character_ids(root: Path | None = None) -> list[str] | None:
    """资产包模式：网页人物列表只列清单里的角色；不是资产包模式 = None（旧行为）"""
    m = manifest(root)
    return None if m is None else sorted((m.get("characters") or {}).keys())


def manifest_scene_ids(root: Path | None = None) -> list[str] | None:
    m = manifest(root)
    return None if m is None else sorted((m.get("scenes") or {}).keys())


def renders_for_data(data_dir: Path | None) -> Path:
    """给定一个 data 目录：是真实仓库的 data → 当前剧的渲染根（K-OPS-F24）；测试 / 沙箱改过的 data 目录 → 它下面的 renders（旧行为）"""
    if data_dir is None or Path(data_dir).resolve() == (REPO / "data").resolve():
        return renders_root()
    return Path(data_dir) / "renders"


def episodes_dir(root: Path | None = None, run: str | None = None) -> Path:
    """整集成片目录（UIUX-LOOP-3 r12；K-OPS-F24 同口径）：V2 剧 = data/episodes/<run>/（装配器 tools/assemble_episode.py --run 的落点，
    night 合成的 ep01_vN.mp4 / _post.mp4 都在这）；只有 legacy 剧（series10_v1）用不带前缀的 data/episodes/。
    成片页 / 整集预览 / KPI 面板以前写死 data/episodes/ → V2 的 60 多版成片一版都列不出来、项目方看不到最新成片"""
    m = _runs()
    r = Path(root) if root else REPO
    run = run or m.current_run(r)
    base = r / "data" / "episodes"
    return base if m.is_legacy(run, r) else base / run


def episodes_for_data(data_dir: Path | None) -> Path:
    """同 renders_for_data：真实仓库的 data → 当前剧的成片目录；测试 / 沙箱 data → 它下面的 episodes（旧行为）"""
    if data_dir is None or Path(data_dir).resolve() == (REPO / "data").resolve():
        return episodes_dir()
    return Path(data_dir) / "episodes"
