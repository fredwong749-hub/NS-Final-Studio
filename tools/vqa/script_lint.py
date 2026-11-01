"""VQA 回写给写作方的剧本机检（K-WRT-V06）。与 tools/qa/writer_lints.py 同签名：check_shot(sh, ep, img, size, fields=None, level=)。

看图模型反复报、且根子在剧本原文的缺陷，已有 lint 的直接复用（不重复造）：
  blank_expression → QW-A5（tools/qa/acting_lints.py）  eye_contact → K-REN-G01 / QW-A*（ACTING）
  framing_mismatch（局部特写露脸）→ QW-CH6（validate_qwen_script）  outfit_mismatch → QW-W1 / QW-W4（writer_lints）
本文件只补还没有 lint 的一条：
  VQ-W1  景别看得见脚（全景 / 中全景 / 远景）时，每个在画角色本镜造型里的鞋要写进 img（写品名：款式 + 颜色）。
         根因：R11-4“不同的镜头鞋子就错了”——img 没写鞋，出图模型只靠参考图，鞋最容易漂。
接线：tools/validate_qwen_script.py 在 WL / AL 之后加一行 out.extend(VQL.check_shot(...))（ITERAUDIT 的文件，已请总调度转达）。
"""
from __future__ import annotations

import importlib.util as _ilu
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = _ilu.spec_from_file_location("ns_writer_lints_vq", ROOT / "tools" / "qa" / "writer_lints.py")
WL = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(WL)

RULES: dict[str, tuple[str, str]] = {
    "VQ-W1": ("warn", "景别看得见脚（全景 / 中全景 / 远景）时，每个在画角色的鞋要写进 img（款式 + 颜色，如“12cm 透明侧开细高跟”），不能只靠参考图"),
}
FEET_SIZES = ("全景", "中全景", "远景", "大全景")
SHOE_WORDS = re.compile(r"鞋|高跟|靴|凉拖|拖鞋|赤脚|光脚|赤足|裸足|袜")


def check_shot(sh, ep, img: str, size: str | None, fields: dict | None = None, level: str | None = None) -> list[dict]:
    out: list[dict] = []
    if size not in FEET_SIZES:
        return out
    on = [c.name for c in (sh.cast or []) if c.presence == "在画"]
    for name in on:
        slots = WL.look_slots_at(ep.looks or [], name, sh.index)
        shoe = slots.get("鞋") or slots.get("鞋子") or ""
        if not shoe.strip():
            continue
        if not SHOE_WORDS.search(img or ""):
            out.append({"rule_id": "VQ-W1", "level": level or WL.WRITER_LINT_LEVEL, "field": "img",
                        "detail": f"{size}看得见脚，{name} 本镜造型的鞋「{shoe.strip()[:20]}」没写进 img", "rule": RULES["VQ-W1"][1]})
    return out
