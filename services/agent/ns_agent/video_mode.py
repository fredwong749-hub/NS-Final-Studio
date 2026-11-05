"""L-197 A（项目方 11-05）：砍尾帧——视频只用首帧（MiniMax H3 I2VA），不出尾帧、视频不等尾帧。

按剧开关：config/compile/run_style.json  runs.<run>.video_mode = {"mode": "i2va", "from_episode": N}
  - mode "i2va" 且 集号 >= from_episode（缺省 1）→ 该集“无尾帧”；其余（没配 / mode fl2va / 其它剧 / 更早的集）= 旧 FL2VA 路径，原样。
  - 默认不配 = 旧行为。ep01 已按 FL2VA 编出的作业不动：series10_v2 配 from_episode=2，只管 ep02 起的新作业。
唯一入口，producer / build_jobs / sop_gate / night 都调这里，不各自读配置。"""
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
_CFG = "config/compile/run_style.json"


def _cfg(root: Path | None = None) -> dict:
    try:
        return json.loads(((root or ROOT) / _CFG).read_text(encoding="utf-8"))
    except (OSError, ValueError):   # arch-ok: 读不到配置 = 开关关（旧 FL2VA 行为不变）
        return {}


def no_last(run: str | None, ep: int | None, root: Path | None = None, shot: str | None = None) -> bool:
    """本剧本集是否走 I2VA（不出尾帧、视频不等尾帧）。NS_VIDEO_MODE=fl2va 环境变量可一键强制关。
    L-201（项目方 11-06）：video_mode.shots = ["ep01-S1", ...] 逐镜改 I2VA（首尾帧差别不明显的镜头，运镜交给视频模型）；
    传了 shot 且在名单里 = True（不看 from_episode）"""
    if not run or os.environ.get("NS_VIDEO_MODE") == "fl2va":
        return False
    vm = (((_cfg(root).get("runs") or {}).get(run) or {}).get("video_mode")) or {}
    if not isinstance(vm, dict) or vm.get("mode") != "i2va":
        return False
    if shot and shot in set(map(str, vm.get("shots") or [])):
        return True
    try:
        return int(ep or 0) >= int(vm.get("from_episode") or 1)
    except (TypeError, ValueError):
        return False


def any_no_last(run: str | None, root: Path | None = None) -> bool:
    return no_last(run, 10**6, root)
