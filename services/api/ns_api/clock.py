"""时间口径（UIUX-LOOP-2 r6，11-06）：页面上的钟点一律 JST（项目方在东京）；存储不动，只在读接口转。

谁写的裸时间串（没有时区的 "YYYY-MM-DDTHH:MM:SS"）是什么时区——核过的事实，别再猜：
  · 两台出图机（gpu33 / gpu36）上的 producer / night / vidgen 都在 TZ=Asia/Tokyo 下跑
    （ops/offline/ensure_runs.sh、resident_restart.sh、tools/factory/sync.py ENV 都 export TZ=Asia/Tokyo）
    → 它们写进 takes.json 的 created_at、registry / log 的 ts 已经是 JST，原样显示就对
    （实测 11-06：ep01 S1 尾帧 #120 created_at 17:10:54 vs 本机文件 mtime 03:21（美东）= 差 14 h = JST − EST）。
  · 笔记本（系统时钟美东）上 time.strftime 写的裸串才是美东：frame_jobs 的任务表 created_at / started_at、
    frame_edit_queue 的修改记录 at、本机画布 / 工作台直出的版本。这些给页面前用 local_naive_to_jst 转。
浏览器也在这台笔记本上（本地时区美东）：Date.parse(裸串) 按美东算；给前端用来算“排了多久 / 预计几点”的时间串要带 +09:00
（with_offset=True），前端 fmtClock 再按 Asia/Tokyo 显示——两边都不靠系统时区。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))


def local_naive_to_jst(s: str | None, with_offset: bool = False) -> str | None:
    """笔记本本机 time.strftime 的裸时间串 → JST 串。with_offset=True 带 +09:00（给前端 Date.parse 用）；
    已经带时区的串（+09:00 / Z）按它自带的时区换算；转不了 = 原样（显示层不因一个坏串报错）"""
    if not s:
        return s
    try:
        d = datetime.fromisoformat(str(s))
    except (TypeError, ValueError):  # arch-ok: 显示层：不认识的时间串原样给（不是时间字段就别动）
        return s
    if d.tzinfo is None:
        d = d.astimezone()        # 本机时区（笔记本 = 美东）
    j = d.astimezone(JST)
    return j.strftime("%Y-%m-%dT%H:%M:%S") + ("+09:00" if with_offset else "")


def server_naive_jst(s: str | None, with_offset: bool = False) -> str | None:
    """出图机（TZ=Asia/Tokyo）写的裸串：已是 JST，不换算；只按需补 +09:00"""
    if not s:
        return s
    if with_offset and len(str(s)) == 19:
        return str(s) + "+09:00"
    return s


def jst_now_str(fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    return datetime.now(JST).strftime(fmt)


def epoch_jst(t: float | None, fmt: str = "%Y-%m-%dT%H:%M:%S") -> str | None:
    """epoch（time.time() / 文件 mtime）→ JST 串。页面上显示“现在 / 文件改动时刻”一律走这里（L-212 #10）；
    别用 time.strftime(fmt, time.localtime(t))——笔记本系统时钟是美东，页面会差 14 小时。非法值 → None"""
    if t is None or t == "":
        return None
    try:
        if float(t) < 0:
            return None
        return datetime.fromtimestamp(float(t), JST).strftime(fmt)
    except (OSError, OverflowError, ValueError, TypeError):  # arch-ok: 显示层：非法时间戳 = 不显示时间
        return None
