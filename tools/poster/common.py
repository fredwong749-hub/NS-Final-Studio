"""海报工具共用：run 清单来自数据（data/posters/<run>/content_zh.json 存在的 run），不在代码里写死 run 名；JSON / 文本一律先写临时文件再 os.replace。"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
POSTERS = ROOT / "data" / "posters"


def poster_runs() -> list[str]:
    """有中文文案的 run，按季排序（第 1 季 = 无 _sN 后缀的主线）"""
    runs = [p.parent.name for p in POSTERS.glob("*/content_zh.json")]
    return sorted(runs, key=lambda r: (season_of(r), r))


def season_of(run: str) -> int:
    m = re.search(r"_s(\d+)$", run)
    return int(m.group(1)) if m else 1


def run_of_season(season: int, runs: list[str] | None = None) -> str:
    return next(r for r in (runs or poster_runs()) if season_of(r) == season)


def write_text_atomic(p: Path, text: str) -> None:
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    t = p.with_suffix(p.suffix + ".tmp")
    t.write_text(text, encoding="utf-8")
    os.replace(t, p)


def write_json_atomic(p: Path, d) -> None:
    write_text_atomic(p, json.dumps(d, ensure_ascii=False, indent=1))
