"""K-OPS-I15（SLIM-CDE 11-05）：任何 hold（night_control.json hold_lanes、producer lane_notes.held_by、*_hold.json 条目）
都必须带 expires_at；没带的，超过 6 小时（以“写入时刻”算）自动忽略并记一行日志——临时 hold 忘了撤 = 整台卡闲（11-05 21:1x 六卡全空的根因：
gpu36:0 基准 hold + W46 gpu36:1 hold 没人撤）。

纯函数、无副作用（日志由调用方给回调）；时间一律按 JST（+09:00）读无时区串，不依赖本机时区。
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

JST = timezone(timedelta(hours=9))
MAX_NO_EXPIRY_S = 6 * 3600


def ts_epoch(s) -> float | None:
    """“2026-11-05T19:10:52” / “…+09:00” / 数字（epoch）→ epoch；无时区串按 JST；认不出 = None"""
    if s is None or s == "":
        return None
    if isinstance(s, (int, float)):
        return float(s)
    try:
        d = datetime.fromisoformat(str(s).strip().replace(" ", "T").replace("Z", "+00:00"))
    except ValueError:
        return None
    return (d if d.tzinfo else d.replace(tzinfo=JST)).timestamp()


def alive(expires_at, since, now: float | None = None, max_age: float = MAX_NO_EXPIRY_S) -> tuple[bool, str]:
    """→ (还有效?, 原因)。有 expires_at：到点失效（写坏 = 当没写，走 6 h 兜底）；没有：写入时刻（since）超过 max_age 失效；
    since 也不知道 = 有效（失败关闭：不凭空放开）"""
    now = time.time() if now is None else now
    exp = ts_epoch(expires_at)
    if exp is not None:
        return (exp > now), ("" if exp > now else f"已过 expires_at {expires_at}")
    t0 = ts_epoch(since)
    if t0 is None:
        return True, ""
    age = now - t0
    if age > max_age:
        return False, f"没有 expires_at 且已挂 {age / 3600:.1f} h（>{max_age / 3600:.0f} h，K-OPS-I15）"
    return True, ""


def filter_lane_holds(holds, expires: dict | None, seen_path: Path | None, now: float | None = None,
                      keep=(), log=None, max_age: float = MAX_NO_EXPIRY_S) -> list:
    """lane 级 hold 列表过滤。expires = {lane: iso}（可空）；“写入时刻”取 seen_path（{lane: 首次看到的 epoch}）——
    写 hold 的人不用改写法，首次被本函数看到起算 6 h。keep 里的（坏卡 / 结构性 hold）永远保留。
    seen_path 写不了 = 不兜底（只认 expires）。log(lane, why) 每个被忽略的 hold 每次过滤调用一次（调用方自己去重）"""
    now = time.time() if now is None else now
    holds = [h for h in (holds or [])]
    expires = expires or {}
    seen: dict = {}
    if seen_path:
        try:
            seen = json.loads(Path(seen_path).read_text(encoding="utf-8")) or {}
        except (OSError, ValueError):
            seen = {}
    out, dirty = [], False
    for h in holds:
        if h in keep:
            out.append(h)
            continue
        if h not in seen:
            seen[h] = now
            dirty = True
        ok, why = alive(expires.get(h), seen.get(h), now, max_age)
        if ok:
            out.append(h)
        elif log:
            log(h, why)
    gone = [k for k in seen if k not in holds]      # 已经撤掉的 hold：清出记录，下次再挂重新起算
    for k in gone:
        seen.pop(k)
        dirty = True
    if dirty and seen_path:
        try:
            p = Path(seen_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(p.suffix + f".{os.getpid()}.tmp")
            tmp.write_text(json.dumps(seen, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, p)
        except OSError:
            pass
    return out
