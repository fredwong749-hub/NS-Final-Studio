"""编排器每拍拆成三条互不阻塞的线（WORKFLOW 11-02 04:2x，总调度派；规则 K-OPS-W22 修订）。

起因：04:17:49 那一拍卡在 :8800 守护（api_restart_guard tick，上限 360 s）里，flow.tick 是串行的——
写作推进、line3 打分（上限 600 s）、:8800 守护任何一段跑得久，last_tick / status.json 就跟着停（04:16:55 → 04:20 仍未更新）。

拆法（实现在 flow.tick_part，DISTILL 11-02 并回为唯一实现；本文件只是命令行入口）：
  core   状态 + 覆盖率 + 写作交稿即推进；写 last_tick.json 与 status.json（并入另外两条线最近一次的结果）。每 60 s。
  line3  flow.line3_tick（看到 line3_dirty.json 就打分）；结果写 data/autopilot/flow/line3_tick.json。上一次没完就跳过。
  api    flow.api_restart_tick（:8800 空闲重启守护）；结果写 data/autopilot/flow/api_restart_tick.json。上一次没完就跳过。
resident_sync 为每条线各开一个线程、各自子进程跑，互不等待。
用法： python tools/autopilot/tick_parts.py core|line3|api [--dry-run]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import flow as FL  # noqa: E402


def run_part(part: str, root: Path = ROOT, apply: bool = True) -> dict:
    """拼装逻辑只有 flow.tick_part 一份（DISTILL 11-02 并回；本文件只做命令行入口，resident_sync 每条线一个线程调它）"""
    return FL.tick_part(part, root, apply)

def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print(__doc__)
        return 2
    print(json.dumps(run_part(argv[0], apply="--dry-run" not in argv), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
