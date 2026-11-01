"""FACTORY D2：本地库（内容寻址，docs/master/FRAMEWORK_REFRAME.md §2 D2；L-099b）。

  <库根>/objects/<sha256 前 2 位>/<sha256>      文件内容（只增不删；同 sha 只存一份）
库根默认 data/factory/library（data/ 不进 git）；环境变量 NS_LIBRARY 可改。笔记本、服务器、laptop:0 同一套布局。
  put(path) → sha        has(sha) → bool        path_of(sha) → Path | None        get(sha, dest) → dest
DISTILL state_snapshot.snapshot 会把每个快照文件 put 进来（K-OPS-X06）；之后 names.json（逻辑名 → sha）和缺 sha 补传在此之上做。
"""
from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path

ROOT = Path(os.environ.get("NS_ROOT") or Path(__file__).resolve().parents[2]).resolve()


def lib_root() -> Path:
    return Path(os.environ.get("NS_LIBRARY") or (ROOT / "data/factory/library"))


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def path_of(sha: str) -> Path | None:
    p = lib_root() / "objects" / sha[:2] / sha
    return p if p.is_file() else None


def has(sha: str) -> bool:
    return path_of(sha) is not None


def put(path, sha: str | None = None) -> str:
    """存入（已有同 sha 不重复写）；先写临时文件再原子改名，写到一半断了不会留下坏对象"""
    src = Path(path)
    sha = sha or sha256_file(src)
    if has(sha):
        return sha
    d = lib_root() / "objects" / sha[:2]
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / f".{sha}.part"
    shutil.copyfile(src, tmp)
    if sha256_file(tmp) != sha:
        tmp.replace(d / f".{sha}.bad")             # 源文件在复制期间被改：不入库，留痕
        raise ValueError(f"{src} 复制期间内容变了（sha 不符），未入库")
    os.replace(tmp, d / sha)
    return sha


def get(sha: str, dest) -> Path:
    p = path_of(sha)
    if p is None:
        raise FileNotFoundError(f"库里没有 {sha}")
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(p, dest)
    return dest
