""":8800 事件循环 / 线程池看门狗（DATAALIGN 2026-11-01，总调度 P1：整体卡 15–17 s；笔记 docs/dataalign/STALL_NOTES.md）。

一个普通线程每 0.5 s 往事件循环里投一个回调（call_soon_threadsafe），回调里记下“执行时刻”和 anyio 线程池占用：
  · 回调迟迟不执行（> LAG_S）= 事件循环被同步代码堵住；
  · 线程池 borrowed_tokens ≥ total_tokens = 同步接口全部占满，新请求排队；
任一发生 → 写 data/qa/loop_lag.jsonl 一行（延迟、线程池占用、每个线程的调用栈摘要），同一次卡顿只抓一次全栈（--min-gap）。
平时每 60 s 记一行心跳（最大延迟、线程池最高占用），便于事后对照 UIMASTER 的慢窗口。只读：不改任何业务数据。
测试里（PYTEST_CURRENT_TEST）不启动。
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import traceback
from pathlib import Path

LAG_S = 1.5
PERIOD_S = 0.5
HEARTBEAT_S = 60.0
MIN_GAP_S = 20.0


def _stacks(limit: int = 12) -> list[dict]:
    names = {t.ident: t.name for t in threading.enumerate()}
    out = []
    for tid, frame in sys._current_frames().items():
        st = traceback.extract_stack(frame)[-limit:]
        out.append({"thread": names.get(tid, str(tid)),
                    "stack": [f"{Path(f.filename).name}:{f.lineno} {f.name}" for f in st]})
    return out


class Watchdog:
    def __init__(self, loop, log_path: Path):
        self.loop = loop
        self.log = Path(log_path)
        self.ack = time.time()
        self.borrowed = 0
        self.total = 0
        self.max_lag = 0.0
        self.max_borrowed = 0
        self.last_dump = 0.0
        self.last_beat = time.time()
        self.stop = False

    def _cb(self, sent: float):
        self.ack = time.time()
        lag = self.ack - sent
        self.max_lag = max(self.max_lag, lag)
        try:
            import anyio.to_thread
            lim = anyio.to_thread.current_default_thread_limiter()
            self.borrowed, self.total = int(lim.borrowed_tokens), int(lim.total_tokens)
            self.max_borrowed = max(self.max_borrowed, self.borrowed)
        except Exception:  # noqa: BLE001
            pass

    def _write(self, rec: dict):
        try:
            self.log.parent.mkdir(parents=True, exist_ok=True)
            with self.log.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def run(self):
        while not self.stop:
            sent = time.time()
            try:
                self.loop.call_soon_threadsafe(self._cb, sent)
            except RuntimeError:          # 循环已关
                return
            time.sleep(PERIOD_S)
            now = time.time()
            pending = now - sent if self.ack < sent else 0.0          # 投出去的回调还没执行了多久
            saturated = self.total and self.borrowed >= self.total
            if (pending > LAG_S or saturated) and now - self.last_dump > MIN_GAP_S:
                self.last_dump = now
                self._write({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "kind": "stall",
                             "loop_pending_s": round(pending, 2), "threadpool": [self.borrowed, self.total],
                             "threads": len(threading.enumerate()), "stacks": _stacks()})
            if now - self.last_beat > HEARTBEAT_S:
                self.last_beat = now
                self._write({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "kind": "beat", "max_lag_s": round(self.max_lag, 3),
                             "max_threadpool": [self.max_borrowed, self.total], "threads": len(threading.enumerate())})
                self.max_lag, self.max_borrowed = 0.0, 0


def start(log_path: Path) -> Watchdog | None:
    """在事件循环里调用（FastAPI startup）"""
    if os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("NS_NO_LOOP_WATCHDOG") == "1":
        return None
    import asyncio
    wd = Watchdog(asyncio.get_running_loop(), log_path)
    threading.Thread(target=wd.run, name="loop-watchdog", daemon=True).start()
    return wd
