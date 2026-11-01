"""
画布加载提速（T60，fredw-25）：旧 GET /api/episodes 一次算全 360 镜（~1.2 s）、返回 ~8.8 MB。改成两段：

  GET /api/episodes/summary   集列表 + 每集摘要（镜头数、就绪数、时长合计）+ 每镜轻字段（集列表点阵、总览缩略图、
                              过滤、批量判断用）。后台缓存：有缓存直接返回；超过 TTL 返回旧值并在后台单飞重算。
  GET /api/episodes/{n}       单集完整数据（与旧接口里这一集逐字相同），现算，只算这一集。

旧 /api/episodes 原样保留（兼容）。缓存只是投影，不改任何字段含义。
"""
from __future__ import annotations

import threading
import time
from typing import Callable

# 每镜轻字段：EpisodeList（点阵/审核）、OverviewGrid（缩略图/人物）、matchFilter、批量判断、gpu3 等待签名要用的
LIGHT_SHOT_KEYS = (
    "id", "index", "review", "stale", "job", "job_stage", "queue_pos", "explicit_hold", "adult", "edited", "owner",
    "first_frame", "first_frame_take", "last_frame_target", "last_frame_take", "last_frame_source", "video",
    "img_summary", "duration", "latest_take", "takes_count", "frames_source", "gpu3", "next_shot", "prev_shot",
    "needs_review", "bad", "locked_take", "stale_global", "video_qc", "stale_deps",
)
LIGHT_CHAR_KEYS = ("character", "name", "face_url", "look_id", "look_label", "look_name", "d_state")
LIGHT_CHAR_OPT = ("cast_source", "presence")   # DATAALIGN：与出图同源的标记，有才带（资产中心按它判 series10 造型字母）
EPISODE_KEYS = ("number", "title", "high_intensity", "tag", "synopsis", "edit", "music", "audio_supported",
                "readiness", "explicit_hold_count")


def light_shot(s: dict) -> dict:
    out = {k: s[k] for k in LIGHT_SHOT_KEYS if k in s}
    exp = s.get("expression")
    if isinstance(exp, dict):
        out["expression"] = {"source": exp.get("source")}
    out["characters"] = [{**{k: c.get(k) for k in LIGHT_CHAR_KEYS}, **{k: c[k] for k in LIGHT_CHAR_OPT if k in c}}
                         for c in s.get("characters") or []]
    return out


def light_episode(ep: dict) -> dict:
    shots = ep.get("shots") or []
    out = {k: ep[k] for k in EPISODE_KEYS if k in ep}
    r = ep.get("readiness") or {}
    out["summary"] = {
        "shots": len(shots),
        "ready": r.get("ready"),
        "seconds": sum((s.get("duration") or {}).get("seconds") or 0 for s in shots),
        "first_frames": sum(1 for s in shots if s.get("first_frame")),
        "videos": sum(1 for s in shots if s.get("video")),
        "passed": sum(1 for s in shots if (s.get("review") or {}).get("state") == "passed"),
    }
    out["light"] = True
    out["shots"] = [light_shot(s) for s in shots]
    return out


class SummaryCache:
    """全量集数据的后台缓存（stale-while-revalidate）。build() = 旧 /api/episodes 的全量计算。"""

    def __init__(self, build: Callable[[], list[dict]], ttl_s: float = 15.0):
        self._build = build
        self.ttl_s = ttl_s
        self._lock = threading.Lock()
        self._data: list[dict] | None = None
        self._at = 0.0
        self._refreshing = False
        self._gen = 0             # 封板修复：invalidate() 递增；重算开始后代数变了 → 结果作废，不刷新 _at
        self.last_build_s: float | None = None

    def _run(self):
        t = time.perf_counter()
        rerun = False
        try:
            with self._lock:
                gen = self._gen
            data = [light_episode(e) for e in self._build()]
            with self._lock:
                if gen == self._gen:
                    self._data, self._at = data, time.time()
                elif self._data is None:
                    self._data, self._at = data, 0.0   # 冷启动：先给旧值（_at=0 → 下次请求立即再算）
                    rerun = True
                else:
                    rerun = True                        # 算的过程中有写入 / 换剧本：丢掉，重算
            self.last_build_s = round(time.perf_counter() - t, 3)
        finally:
            with self._lock:
                self._refreshing = False
        if rerun:
            self._kick()

    def _kick(self):
        with self._lock:
            if self._refreshing:
                return
            self._refreshing = True
        threading.Thread(target=self._run, name="episodes-summary", daemon=True).start()

    def warm(self):
        """服务启动后预热（后台）"""
        self._kick()

    def invalidate(self):
        """已知写入后调用：下一次请求返回旧值并立即后台重算"""
        with self._lock:
            self._at = 0.0
            self._gen += 1

    def refresh_now(self, timeout_s: float = 60.0) -> None:
        """DATAALIGN（D-COUNT 滞后）：已知输入变了（takes.json 等）→ 同步重算到最新一代再返回；并发调用者共用同一次重算。
        build() 走按镜缓存，只有变了的镜头真算，通常 0.1–0.3 s"""
        self.invalidate()
        t0 = time.time()
        while time.time() - t0 < timeout_s:
            with self._lock:
                if self._at > 0:                 # invalidate 之后已有一代按新输入算完
                    return
                busy = self._refreshing
                if not busy:
                    self._refreshing = True
            if not busy:
                self._run()
            else:
                time.sleep(0.02)

    def get(self) -> tuple[list[dict], float]:
        with self._lock:
            data, at = self._data, self._at
        if data is None:
            # 冷启动：同步算一次（之后都走缓存）；并发请求等同一份结果
            with self._lock:
                busy = self._refreshing
                if not busy:
                    self._refreshing = True
            if busy:
                while True:
                    time.sleep(0.05)
                    with self._lock:
                        if self._data is not None or not self._refreshing:
                            break
            else:
                self._run()
            with self._lock:
                data, at = self._data, self._at
            if data is None:
                raise RuntimeError("集摘要计算失败")
        elif time.time() - at > self.ttl_s:
            self._kick()
        return data, at


class KeyedCache:
    """封板修复 A-2（慢接口）：按参数缓存整份返回值（返回内容不变，只是复用）。
    sig = 输入签名（剧本 / 状态表等文件 mtime）：变了 → 同步重算；没变但超过 ttl_s → 先返回旧值、后台单飞重算。
    sig 管不到的输入（gpu3 镜像、帧文件）最多旧 ttl_s + 一次计算的时间。"""

    def __init__(self, ttl_s: float = 10.0, max_items: int = 64):
        self.ttl_s, self.max_items = ttl_s, max_items
        self._lock = threading.Lock()
        self._items: dict = {}          # args → (sig, at, value)
        self._busy: set = set()

    def _store(self, args, sig, value):
        with self._lock:
            if len(self._items) >= self.max_items and args not in self._items:
                self._items.pop(next(iter(self._items)))
            self._items[args] = (sig, time.time(), value)

    def _bg(self, args, sig, compute):
        try:
            self._store(args, sig, compute())
        except Exception:  # noqa: BLE001 — 后台刷新失败：保留旧值，下次请求再算
            pass
        finally:
            with self._lock:
                self._busy.discard(args)

    def get(self, args, sig, compute: Callable[[], object]):
        with self._lock:
            hit = self._items.get(args)
        if hit is not None and hit[0] == sig:
            if time.time() - hit[1] > self.ttl_s:
                with self._lock:
                    kick = args not in self._busy
                    self._busy.add(args)
                if kick:
                    threading.Thread(target=self._bg, args=(args, sig, compute), daemon=True,
                                     name="keyed-cache").start()
            return hit[2]
        value = compute()
        self._store(args, sig, value)
        return value

    def clear(self):
        with self._lock:
            self._items.clear()
