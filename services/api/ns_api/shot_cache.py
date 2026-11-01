"""DATAALIGN 2026-11-01（总调度 P1：GET /api/episodes 4–20 s）：镜头卡摘要按镜缓存，返回内容不变。

根因：/api/episodes 与集摘要后台重算（episodes_fast.SummaryCache，每次写入都 invalidate → 全量重算）每次都把 80 镜
的 _shot_summary 从头算一遍（编译提示词、H3 lint、旧造型解析、gpu3 链、数千次 stat）。出图进行中写入频繁时，
全量重算一轮接一轮地抢 GIL，/api/episodes 在负载下 20 s。

做法：每镜结果按“输入签名”缓存——
  · 本镜：渲染目录（目录 mtime + takes.json / edits.json / review.json）、gpu3 镜像目录（目录 + takes.json / status.json）；
  · 前后相邻镜的同样签名（尾帧 / 下一镜首帧 / 依赖过期跨镜）；
  · 本集 episode_edit.json；
  · 全局：剧本对象、data/looks/*、config/*、config/recipes/*、本剧运行目录 assets/*、资产版本账本、
    data/ 顶层状态文件（scenes / state_timeline / owner gates）。
签名变了 → 同步重算该镜；签名没变但超过 TTL（120 s）→ 先返回缓存，单个后台线程重算（兜住签名管不到的输入，
最多旧 TTL + 一次计算）。任务字段（job / job_stage / queue_pos，内存里的队列）每次现算，不进缓存。
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Callable

TTL_S = 120.0  # DATAALIGN 11-01：30 s 时每 30 s 后台把 80 镜全算一遍（约 3 s 纯 CPU），抢 GIL 造成请求 2–4 s 尖峰；签名管住了主要输入，TTL 只是兜底
BG_YIELD_S = 0.02   # 后台重算每算完一镜让出 20 ms，前台请求不被饿死
# 签名管不到的输入（内存里的视频任务状态、gpu3 审计等）最多旧 TTL；最早 5 s 时每次请求都触发后台全量重算、抢 GIL
JOB_KEYS = ("job", "job_stage", "queue_pos")


def _mt(p: Path):
    try:
        st = os.stat(p)
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


# 不影响镜头卡的文件（日志、知识库生成的提示词文档、备份）：不进签名。
# 11-01 04:11 重启后冷请求 4.2 s 的根因之一：compile.py 每次重生成 config/recipes/*.md、出图线不停写
# runs/<剧>/assets/first_frame_jobs.json → 全局签名一直在变 → 80 镜全部同步重算
_SIG_SKIP_EXT = (".md", ".jsonl", ".log", ".txt", ".bak")


def _sig_skip(name: str) -> bool:
    return name.endswith(_SIG_SKIP_EXT) or ".before" in name or name.startswith(".")


def _dir_sig(d: Path, only: tuple[str, ...] | None = None) -> tuple:
    """目录里每个文件的 (名字, mtime, 大小)（只看一层；跳过日志 / 文档 / 备份；only = 只看这些文件名）"""
    try:
        with os.scandir(d) as it:
            return tuple(sorted((e.name, e.stat().st_mtime_ns, e.stat().st_size) for e in it
                                if e.is_file() and (e.name in only if only else not _sig_skip(e.name))))
    except OSError:
        return ()


class ShotCache:
    def __init__(self, ttl_s: float = TTL_S):
        self.ttl_s = ttl_s
        self._lock = threading.Lock()
        self._items: dict[str, tuple] = {}     # shot_id → (sig, at, value)
        self._stale: dict[str, Callable[[], dict]] = {}
        self._bg = False
        self._inflight: dict[str, tuple] = {}   # shot_id → (sig, Event)：正在同步计算的镜头
        self.hits = self.misses = 0

    @staticmethod
    def shot_sig(render_dir: Path, gpu3_dir: Path | None) -> tuple:
        out = [_mt(render_dir)] + [_mt(render_dir / f) for f in ("takes.json", "edits.json", "review.json")]
        if gpu3_dir is not None:
            out += [_mt(gpu3_dir)] + [_mt(gpu3_dir / f) for f in ("takes.json", "status.json")]
        return tuple(out)

    @staticmethod
    def global_sig(dirs: list[Path], files: list[Path], extra: tuple = ()) -> tuple:
        return (extra, tuple(_dir_sig(d) for d in dirs), tuple(_mt(f) for f in files))

    def get(self, shot_id: str, sig, compute: Callable[[], dict], bg_compute: Callable[[], dict] | None = None) -> dict:
        """compute：本次请求同步算（可共用请求内上下文）；bg_compute：后台重算（须自带新上下文，默认 = compute）"""
        with self._lock:
            hit = self._items.get(shot_id)
        if hit is not None and hit[0] == sig:
            self.hits += 1
            if time.time() - hit[1] > self.ttl_s:
                with self._lock:
                    self._stale[shot_id] = (sig, bg_compute or compute)
            return hit[2]
        # 单飞（总调度 11-01 P1：重启后头几个 /api/episodes 10 / 18 / 6 s = 并发请求各算一遍）：
        # 同一镜同一签名只有一个线程在算，其余等它算完直接取
        while True:
            with self._lock:
                hit = self._items.get(shot_id)
                if hit is not None and hit[0] == sig:
                    self.hits += 1
                    return hit[2]
                fl = self._inflight.get(shot_id)
                if fl is None or fl[0] != sig:
                    ev = threading.Event()
                    self._inflight[shot_id] = (sig, ev)
                    break
            fl[1].wait(120)
            with self._lock:
                if self._inflight.get(shot_id) is fl:          # 算的那个线程挂了还没清：自己接手
                    self._inflight.pop(shot_id, None)
        self.misses += 1
        try:
            v = compute()
            with self._lock:
                self._items[shot_id] = (sig, time.time(), v)
                self._stale.pop(shot_id, None)
            return v
        finally:
            with self._lock:
                if self._inflight.get(shot_id, (None, None))[1] is ev:
                    self._inflight.pop(shot_id, None)
            ev.set()

    def kick(self):
        """把过了 TTL 的镜头放到一个后台线程里重算（单飞）"""
        with self._lock:
            if self._bg or not self._stale:
                return
            self._bg = True
        threading.Thread(target=self._run, name="shot-cache", daemon=True).start()

    def _run(self):
        try:
            while True:
                with self._lock:
                    if not self._stale:
                        return
                    sid, (sig, compute) = self._stale.popitem()
                try:
                    v = compute()
                except Exception:  # noqa: BLE001 — 后台重算失败：留旧值，下次请求再算
                    continue
                finally:
                    time.sleep(BG_YIELD_S)
                with self._lock:
                    cur = self._items.get(sid)
                    if cur is None or cur[0] == sig:
                        self._items[sid] = (sig, time.time(), v)
        finally:
            with self._lock:
                self._bg = False

    def dump(self, path: Path) -> int:
        """磁盘快照（pickle，原子替换）：重启后按签名复用，签名对不上的镜头照常重算（总调度 11-01 P1：重启后首屏 10–14 s）"""
        import pickle
        with self._lock:
            items = {k: (v[0], v[2]) for k, v in self._items.items()}
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(pickle.dumps(items, protocol=pickle.HIGHEST_PROTOCOL))
            tmp.replace(path)
        except OSError:
            return 0
        return len(items)

    def load(self, path: Path) -> int:
        """读回磁盘快照：条目时间记为 0（过 TTL → 用的时候后台再核一遍）；读不了就当没有"""
        import pickle
        try:
            items = pickle.loads(path.read_bytes())
        except Exception:  # noqa: BLE001
            return 0
        with self._lock:
            for k, (sig, v) in items.items():
                self._items.setdefault(k, (sig, 0.0, v))
        return len(items)

    def clear(self):
        with self._lock:
            self._items.clear()
            self._stale.clear()
