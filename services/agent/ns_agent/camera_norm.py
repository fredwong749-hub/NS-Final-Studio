"""编译层运镜规范化 + 运镜词表读取（DIRECTOR；K-REN-801 / K-EDT-811 / L-107）。

单一事实来源：config/director/camera_moves.yaml（每种运镜的中文名、别名、Pika 提示句模板、适用景别 / 情绪、冲突、拆分、enabled + A/B 结果）。
本模块只依赖标准库 + PyYAML，ns_recipes / tools 都按文件路径载入。

规范化（K-REN-801，按词表 enabled 判定，不再写死）：视频提示词里的官方运镜句 “The camera …” →
  识别成词表里的运镜 → enabled 的按模板重写（只留小幅、去速度词，方向保留）；disabled / 词表外的 → 退回 fallback
  （环绕：本镜没有大动作且推近 enabled → 推近；其余 → 固定），每处改动记 {rule, from, to, move, why, vocab}。
句子后半（as … 动作）不动。开关：config/post/director.json camera_norm（默认开）。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
VOCAB = ROOT / "config" / "director" / "camera_moves.yaml"
BIG_ACTION = re.compile(r"站起|起身|走向|走到|走开|转身|推门|开门|关门|披上|脱下|抖开|蹲|跑|扑|拥抱|抱住|rises|stands up|walks|turns away|runs", re.I)
CAM = re.compile(r"The camera ([^.,;]*?)(?=( as |,|\.|;|$))")
# 英文运镜句 → 词表 id（顺序 = 优先级）
EN_MOVES = [
    (r"\bwhip[- ]pans?\b", "whip_pan"), (r"\bfocus (?:pulls?|racks?)\b|\brack focus\b", "focus_pull"),
    (r"\bslow motion\b", "slow_motion"), (r"\bforeground\b", "foreground_pass"),
    (r"\b(?:arcs?|orbits?|arc shot)\b", "arc"), (r"\b(?:pulls? out|dollies out|zooms? out)\b", "pull_out"),
    (r"\bzooms? in\b|\bcrash zoom\b", "zoom_in"), (r"\b(?:pushes|push|dollies) in\b", "push_in"),
    (r"\bpans?\b", "pan"), (r"\btilts? up\b", "tilt_up"), (r"\btilts? down\b", "tilt_down"),
    (r"\b(?:trucks?|tracks?|tracking)\b", "truck"), (r"\bpedestals? up\b|\bcranes? up\b", "pedestal_up"),
    (r"\bpedestals? down\b", "pedestal_down"), (r"\b(?:shakes?|handheld)\b", "handheld"), (r"\brolls?\b", "roll"),
    (r"\bholds? a static shot\b|\bstatic\b", "static"),
]
_cache: dict = {}


def vocab() -> dict:
    m = VOCAB.stat().st_mtime if VOCAB.exists() else 0
    if _cache.get("m") != m:
        import yaml
        d = yaml.safe_load(VOCAB.read_text(encoding="utf-8")) if VOCAB.exists() else {"moves": []}
        _cache.update(m=m, d=d, by={x["id"]: x for x in d.get("moves") or []})
    return _cache["d"]


def move(mid: str) -> dict | None:
    vocab()
    return _cache["by"].get(mid)


def enabled_ids() -> list[str]:
    return [m["id"] for m in vocab().get("moves") or [] if m.get("enabled")]


def is_enabled(mid: str | None) -> bool:
    m = move(mid) if mid else None
    return bool(m and m.get("enabled") and m.get("template"))


def match_zh(text: str) -> str | None:
    """剧本 motion 开头的运镜写法（中文 / 英文别名）→ 词表 id；最长别名优先"""
    t = (text or "").lower()
    best = None
    for m in vocab().get("moves") or []:
        for a in m.get("aliases") or []:
            if a.lower() in t and (best is None or len(a) > best[1]):
                best = (m["id"], len(a))
    return best[0] if best else None


def match_en(c: str) -> str | None:
    for rx, mid in EN_MOVES:
        if re.search(rx, c or "", re.I):
            return mid
    return None


def clause(mid: str, direction: str = "right") -> str:
    """词表模板 → “The camera …” 句（不含 as 之后）"""
    m = move(mid) if is_enabled(mid) else move("static")
    return ((m or {}).get("template") or "The camera holds a static shot").replace("{dir}", direction)


def fallback(mid: str | None, big_action: bool) -> tuple[str, str]:
    """disabled / 词表外 → (退回的 id, 原因)"""
    m = move(mid) if mid else None
    why = f"{mid}：" + ((m or {}).get("reason") or "词表外运镜") if mid else "没认出运镜"
    if mid == "arc" and not big_action and is_enabled("push_in"):
        return "push_in", why
    return "static", why


def enabled() -> bool:
    try:
        return bool(json.loads((ROOT / "config/post/director.json").read_text(encoding="utf-8")).get("camera_norm", True))
    except (OSError, ValueError):
        return True


def norm_clause_info(c: str, big_action: bool) -> tuple[str, str, str | None]:
    """→ (新句子不含 “The camera ” 前缀, 词表 id, 退回原因或 None)"""
    raw = c.strip()
    mid = match_en(raw)
    d = "left" if re.search(r"\bleft\b", raw, re.I) else "right"
    why = None
    if mid is None or not is_enabled(mid):
        mid, why = fallback(mid, big_action)
    return clause(mid, d)[len("The camera "):], mid, why


def norm_clause(c: str, big_action: bool) -> str:
    return norm_clause_info(c, big_action)[0]


def denormalize(text: str, changes: list[dict]) -> str:
    """把规范化改动倒回去（测试守“除带规则号的规范化外 H3 正文不许改”）"""
    for c in reversed(changes or []):
        text = text.replace(c["to"], c["from"], 1)
    return text


def normalize_video_prompt(text: str, motion_body: str = "") -> tuple[str, list[dict]]:
    """→ (规范化后的提示词, 改动记录 [{rule, from, to, move, why, vocab}])"""
    if not text or not enabled():
        return text, []
    big = bool(BIG_ACTION.search(motion_body or "") or BIG_ACTION.search(text))
    changes = []

    def sub(m):
        new, mid, why = norm_clause_info(m.group(1), big)
        if new != m.group(1).strip():
            changes.append({"rule": "K-REN-801", "from": "The camera " + m.group(1).strip(), "to": "The camera " + new,
                            "move": mid, "why": why or "按词表模板（小幅、去速度词）", "vocab": vocab().get("version")})
        return "The camera " + new
    return CAM.sub(sub, text), changes
