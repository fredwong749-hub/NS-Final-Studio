"""一集在跑时的“清单独占”旗标（PIPELINE_CHECKLIST 规则 1）：data/pipeline/episode_lock.json {run, ep, by, at, until}。
episode_run 每拍刷新（until = now + ttl）；它停了旗标到点自失效，不会把卡永远锁住。
asset_worker 派 render 前、任何 A/B / 研究工具提交 GPU 道前都调 active(root)，有旗标就不提交（清单外的任务等这一集结束）。
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def path(root: Path = ROOT) -> Path:
    return Path(root) / "data" / "pipeline" / "episode_lock.json"


def active(root: Path = ROOT, now: float | None = None) -> dict | None:
    """有效旗标（未到期）→ dict；没有 / 到期 / 坏文件 → None（坏文件按“没锁”处理：宁可不挡也别永久卡住资产线）"""
    try:
        d = json.loads(path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):  # arch-ok: 旗标缺 / 坏 = 无锁
        return None
    return d if float(d.get("until") or 0) > (now if now is not None else time.time()) else None


def write(root: Path, run: str, ep: int, ttl_s: float = 600, by: str = "episode_run", now: float | None = None) -> dict:
    t = now if now is not None else time.time()
    d = {"run": run, "ep": int(ep), "by": by, "at": t, "until": t + float(ttl_s)}
    p = path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.part")
    tmp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)
    return d


def clear(root: Path, run: str, ep: int) -> bool:
    """只清自己这集的旗标（别集的不动）；不删文件，写成已到期（until=0），留痕"""
    p = path(root)
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):  # arch-ok: 没有旗标 = 已清
        return False
    if d.get("run") != run or int(d.get("ep") or -1) != int(ep):
        return False
    d.update(until=0, released_at=time.time())
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)
    return True
