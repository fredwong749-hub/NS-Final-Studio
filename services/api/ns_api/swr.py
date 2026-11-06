"""接口结果缓存：先回旧值、后台重算（stale-while-revalidate；口径同 pipeline_status r13）。

L-212 慢接口（SCAN 11-07 #16）：/api/videos/overview 首次 6.0 s、/api/frames-index 6.2 s，页面每次轮询都现算。
  · 距上次算好 < fresh_s：直接回缓存
  · fresh_s ≤ 年龄 < stale_s：回缓存，同时后台重算一次（同一个键单飞）
  · 没有缓存 / 年龄 ≥ stale_s：同步重算（不给太旧的）
后台重算失败只记日志，旧值还在；过期超 stale_s 时下一次请求同步重算，错误照常抛给页面。
跑 pytest 时（PYTEST_CURRENT_TEST）默认不缓存：用例会换数据目录 / 打桩，跨用例复用旧结果会串（本模块自己的用例传 always=True）。
"""
from __future__ import annotations

import os
import sys
import threading
import time
from typing import Any, Callable, Hashable


class SWRCache:
    def __init__(self, name: str, fresh_s: float = 5.0, stale_s: float = 120.0, max_keys: int = 64, always: bool = False):
        self.name, self.fresh_s, self.stale_s, self.max_keys, self.always = name, fresh_s, stale_s, max_keys, always
        self._data: dict[Hashable, tuple[float, Any]] = {}
        self._busy: set[Hashable] = set()
        self._lock = threading.Lock()

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def _put(self, key: Hashable, val: Any) -> None:
        with self._lock:
            self._data[key] = (time.monotonic(), val)
            if len(self._data) > self.max_keys:   # 筛选参数组合有限；超了丢最旧的
                old = min(self._data, key=lambda k: self._data[k][0])
                self._data.pop(old, None)

    def _kick(self, key: Hashable, fn: Callable[[], Any]) -> bool:
        with self._lock:
            if key in self._busy:
                return False
            self._busy.add(key)

        def go():
            try:
                self._put(key, fn())
            except Exception as e:  # noqa: BLE001  # arch-ok: 后台刷新失败只记日志；旧值还在，过期超 stale_s 后同步重算并把错误抛给页面
                print(f"[swr:{self.name}] 后台刷新失败 {key!r}：{e!r}", file=sys.stderr)
            finally:
                with self._lock:
                    self._busy.discard(key)
        threading.Thread(target=go, daemon=True, name=f"swr-{self.name}").start()
        return True

    def get(self, key: Hashable, fn: Callable[[], Any]) -> Any:
        if not self.always and os.environ.get("PYTEST_CURRENT_TEST"):
            return fn()
        hit = self._data.get(key)
        age = time.monotonic() - hit[0] if hit else None
        if hit and age < self.fresh_s:
            return hit[1]
        if hit and age < self.stale_s:
            self._kick(key, fn)
            return hit[1]
        val = fn()
        self._put(key, val)
        return val
