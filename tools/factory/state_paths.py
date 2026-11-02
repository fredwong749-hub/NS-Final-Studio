"""FACTORY：运行期状态路径的唯一入口（ARCH_ROADMAP §10，总调度 11-02 12:3x 定；sv-10 兼容期、sv-11 删旧读）。
口径：程序运行中自动改写的 = 状态 → data/state/；人写的 = 配置 → 留 config/。

  state_path(name)            → 新位置 Path（data/state/<name>.json）
  read_state(name, default=…)  兼容期：先读新位置；新的不在 → 读旧位置并追加一行 data/state/legacy_reads.jsonl（不静默）；
                               都不在 / 读不出 → 有 default 返回 default，否则 raise StateError（失败关闭，同 K-OPS-F09）
  write_state(name, obj)       只写新位置，先写 .tmp 再 os.replace（原子）
  exists_any(name)             新或旧任一存在（decisions_guard 兼容期用）
事件格式（SENTINEL 探针 state_legacy_read 读）：{"at", "name", "old_path", "caller": "文件:行", "host"}
"""
from __future__ import annotations

import inspect
import json
import os
import socket
import time
from pathlib import Path

ROOT = Path(os.environ.get("NS_ROOT") or Path(__file__).resolve().parents[2]).resolve()
STATE_DIR = Path("data/state")
LEGACY_LOG = STATE_DIR / "legacy_reads.jsonl"
# 逻辑名 → 旧位置（相对仓库根）。新位置一律 data/state/<逻辑名>.json
LEGACY = {
    "netfix/partition": "config/netfix/partition.json",
    "netfix/override": "config/netfix/override.json",
    "pipeline/runs": "config/pipeline/runs.json",
    "pipeline/run": "config/pipeline/run.json",
}
_NO_DEFAULT = object()


class StateError(RuntimeError):
    """状态文件读不到 / 读不出（失败关闭）"""


def _root(root: Path | None) -> Path:
    return Path(root or ROOT)


def state_path(name: str, root: Path | None = None) -> Path:
    if name not in LEGACY:
        raise StateError(f"未登记的状态名 {name}（先登记进 tools/factory/state_paths.py LEGACY）")
    return _root(root) / STATE_DIR / f"{name}.json"


def legacy_path(name: str, root: Path | None = None) -> Path:
    return _root(root) / LEGACY[name]


def exists_any(name: str, root: Path | None = None) -> bool:
    return state_path(name, root).is_file() or legacy_path(name, root).is_file()


def _log_legacy(name: str, root: Path, depth: int = 2) -> None:
    try:
        fr = inspect.stack()[depth]
        caller = f"{Path(fr.filename).name}:{fr.lineno}"
    except Exception:  # noqa: BLE001
        caller = "?"
    rec = {"at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "name": name, "old_path": LEGACY[name], "caller": caller,
           "host": os.environ.get("NS_FACTORY_HOST") or os.environ.get("OFFLINE_SELF") or socket.gethostname()}
    p = root / LEGACY_LOG
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def read_state(name: str, default=_NO_DEFAULT, root: Path | None = None):
    r = _root(root)
    new, old = state_path(name, r), legacy_path(name, r)
    src = new if new.is_file() else (old if old.is_file() else None)
    if src is None:
        if default is not _NO_DEFAULT:
            return default
        raise StateError(f"状态 {name} 读不到（新 {new.relative_to(r)}、旧 {old.relative_to(r)} 都不在）")
    try:
        obj = json.loads(src.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        if default is not _NO_DEFAULT:
            return default
        raise StateError(f"状态 {name} 读不出：{src}（{e}）") from e
    if src == old:
        try:     # 留痕写失败（只读盘 / 测试禁写真实数据）不影响读结果（DEBUG-RSI 12:4x：否则 decisions_guard 误判 run.json 缺失 → 拒派）
            _log_legacy(name, r)
        except Exception:  # noqa: BLE001
            pass
    return obj


def write_state(name: str, obj, root: Path | None = None) -> Path:
    p = state_path(name, root)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, p)
    return p
