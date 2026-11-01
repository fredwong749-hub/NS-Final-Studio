"""VIDLAB 文件读写小工具（arch_scan：JSON 一律原子写；读坏了直接抛，不静默吞掉）。"""
from __future__ import annotations

import json
import os
from pathlib import Path


def write_json(p: Path, obj, indent: int | None = None) -> None:
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + f".tmp{os.getpid()}")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=indent, default=str), encoding="utf-8")
    os.replace(tmp, p)


def read_json(p: Path):
    """读不到 / 解析失败 → 抛 RuntimeError 并写明文件（调用方决定要不要跳过，不在这里吞）"""
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise RuntimeError(f"读 {p} 失败：{e}") from e
