"""
把 Qwen 写好的剧本按集 + 全本复制到项目方下载目录（项目方 2026-10-30：“qwen写完文章给我这里下载”）。

  D:\\NS-Final Studio\\为他而骚短剧\\Qwen剧本\\为他而骚_ep01_qwen_rules_v1_20261030.md
  D:\\NS-Final Studio\\为他而骚短剧\\Qwen剧本\\为他而骚_全本_qwen_rules_v1_20261030.md

原文逐字复制（只按 `## epNN` 切集，全局头一并放进每集文件，不改任何文字）。由 qwen_repair_loop.py 每完成一集自动调用；
也可手动补导：python tools/export_qwen_script.py <script.md> --episodes 1-15 --rules-tag rules_v1
"""
from __future__ import annotations

import argparse
import re
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "为他而骚短剧" / "Qwen剧本"
TITLE = "为他而骚"


def split(text: str) -> tuple[str, dict[int, str]]:
    parts = re.split(r"(?m)^(?=## ep\d+)", text)
    head = parts[0] if parts and not re.match(r"## ep\d+", parts[0]) else ""
    eps = {int(m.group(1)): p for p in parts if (m := re.match(r"## ep(\d+)", p))}
    return head, eps


def export(src: Path, episodes: list[int], rules_tag: str = "rules_v1", out_dir: Path = OUT_DIR,
           full: bool = True, date: str | None = None) -> list[Path]:
    date = date or time.strftime("%Y%m%d")
    text = src.read_text(encoding="utf-8")
    head, eps = split(text)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for n in episodes:
        if n not in eps:
            continue
        p = out_dir / f"{TITLE}_ep{n:02d}_qwen_{rules_tag}_{date}.md"
        p.write_bytes((head + eps[n]).encode("utf-8"))
        written.append(p)
    if full:
        p = out_dir / f"{TITLE}_全本_qwen_{rules_tag}_{date}.md"
        p.write_bytes(text.encode("utf-8"))
        written.append(p)
    return written


def _eps(spec: str) -> list[int]:
    out = []
    for part in spec.split(","):
        a, _, b = part.partition("-")
        out += list(range(int(a), int(b or a) + 1))
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("script", type=Path)
    ap.add_argument("--episodes", default="1-60")
    ap.add_argument("--rules-tag", default="rules_v1")
    ap.add_argument("--no-full", action="store_true")
    a = ap.parse_args()
    for p in export(a.script, _eps(a.episodes), a.rules_tag, full=not a.no_full):
        print(p)
