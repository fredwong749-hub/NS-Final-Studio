"""DATAALIGN 2026-11-01（总调度 P2：重启后任何时刻 /api/episodes < 1.5 s）：上一份完好结果的磁盘快照。

启动预热（集摘要 + 80 镜按镜缓存 + 整份编码）在负载下要几秒到十几秒；预热没完成之前：
  · GET /api/episodes 直接返回磁盘快照（上次正常算出的整份字节，响应头 x-ns-snapshot = 快照时间），不排队等；
  · /api/episodes/summary 的缓存先装上快照（as_of=0 → 立即后台重算），不再冷等。
快照只在“剧本文件没变”（mtime + 大小一致）时用；预热一完成就换回现算结果。每次现算后后台写快照（30 s 内最多一次）。
只缓存展示数据，不参与任何判定。
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

_WRITE_EVERY_S = 30.0
_last_write: dict[str, float] = {}
_lock = threading.Lock()


def _dir(data_dir: Path) -> Path:
    return Path(data_dir) / "cache" / "api_snapshots"


def script_key(script_json: Path) -> list | None:
    try:
        st = os.stat(script_json)
        return [st.st_mtime_ns, st.st_size]
    except OSError:
        return None


def in_tests() -> bool:
    """pytest 正在跑测试：后台写快照的线程会活过测试结束、写到真实 data/（ITERAUDIT 真实数据写保护 11-01 抓到）→ 测试里不写"""
    return bool(os.environ.get("PYTEST_CURRENT_TEST")) or os.environ.get("NS_NO_API_SNAPSHOT") == "1"


def save(data_dir: Path, name: str, body: bytes, script_json: Path) -> None:
    """后台原子写快照（同名 30 s 内只写一次）；测试里不写（in_tests）"""
    if in_tests():
        return
    now = time.time()
    with _lock:
        if now - _last_write.get(name, 0) < _WRITE_EVERY_S:
            return
        _last_write[name] = now

    def run():
        try:
            d = _dir(data_dir)
            d.mkdir(parents=True, exist_ok=True)
            tmp = d / f"{name}.tmp"
            tmp.write_bytes(body)
            tmp.replace(d / f"{name}.json")
            (d / f"{name}.meta.json").write_text(json.dumps({"script": script_key(script_json), "at": now}), encoding="utf-8")
        except OSError:
            pass
    threading.Thread(target=run, name=f"snapshot-{name}", daemon=True).start()


def load(data_dir: Path, name: str, script_json: Path) -> tuple[bytes, float] | None:
    """剧本没变时返回 (字节, 快照时间)；否则 None"""
    d = _dir(data_dir)
    try:
        meta = json.loads((d / f"{name}.meta.json").read_text(encoding="utf-8"))
        if meta.get("script") != script_key(script_json):
            return None
        return (d / f"{name}.json").read_bytes(), float(meta.get("at") or 0)
    except (OSError, ValueError):
        return None
