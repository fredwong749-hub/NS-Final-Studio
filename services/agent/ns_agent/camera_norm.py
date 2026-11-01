"""编译层运镜规范化（DIRECTOR，总调度 fredw-2b 11-02 定，L-098：运镜用词不交写作方重写，改在编译层确定性映射；规则 K-REN-801 / K-WRT-801）。

只改视频提示词里那一句官方运镜句（The camera …），映射到 Pika 稳定做得到的范围（config/prompts/hollywood_pika_reference.md P3 / P10 / P16；
docs/video_rca/RCA_r1.md C16 视频比首帧再远 ≥1 档 11/55）：
  pulls out / zooms out（拉远）          → holds a static shot（Pika 本来就往远退）
  arc shot（环绕）                        → 本镜有大动作 → static；否则 pushes in with small amplitude
  shake / handheld（晃动）                → holds a static shot
  with medium / large amplitude           → with small amplitude（推近只写小幅）
  slowly / at slow speed / gently（速度词）→ 去掉（项目方：节奏慢）
句子后半（as … 动作）不动。开关：config/post/director.json camera_norm（默认开）。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BIG_ACTION = re.compile(r"站起|起身|走向|走到|走开|转身|推门|开门|关门|披上|脱下|抖开|蹲|跑|扑|拥抱|抱住|rises|stands up|walks|turns away|runs", re.I)
CAM = re.compile(r"The camera ([^.,;]*?)(?=( as |,|\.|;|$))")


def enabled() -> bool:
    try:
        return bool(json.loads((ROOT / "config/post/director.json").read_text(encoding="utf-8")).get("camera_norm", True))
    except (OSError, ValueError):
        return True


def norm_clause(clause: str, big_action: bool) -> str:
    c = clause.strip()
    low = c.lower()
    if re.search(r"\b(pulls? out|zooms? out|dollies out)\b", low) or re.search(r"\b(shakes?|handheld)\b", low):
        return "holds a static shot"
    if re.search(r"\barc\b", low):
        return "holds a static shot" if big_action else "pushes in with small amplitude"
    c = re.sub(r"\bwith (medium|large) amplitude\b", "with small amplitude", c, flags=re.I)
    c = re.sub(r"\s*\b(at (slow|a slow) speed|slowly|gently|gradually)\b", "", c, flags=re.I)
    if re.search(r"\b(pushes in|trucks|pans|tilts|pedestals|tracks)\b", c, re.I) and "amplitude" not in c.lower():
        c += " with small amplitude"
    return re.sub(r"\s{2,}", " ", c).strip()


def denormalize(text: str, changes: list[dict]) -> str:
    """把规范化改动倒回去（测试守“除带规则号的规范化外 H3 正文不许改”）"""
    for c in reversed(changes or []):
        text = text.replace(c["to"], c["from"], 1)
    return text


def normalize_video_prompt(text: str, motion_body: str = "") -> tuple[str, list[dict]]:
    """→ (规范化后的提示词, 改动记录 [{from, to}])"""
    if not text or not enabled():
        return text, []
    big = bool(BIG_ACTION.search(motion_body or "") or BIG_ACTION.search(text))
    changes = []

    def sub(m):
        new = norm_clause(m.group(1), big)
        if new != m.group(1).strip():
            changes.append({"rule": "K-REN-801", "from": "The camera " + m.group(1).strip(), "to": "The camera " + new})
        return "The camera " + new
    return CAM.sub(sub, text), changes
