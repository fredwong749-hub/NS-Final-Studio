#!/usr/bin/env python3
"""K-WRT-V06：汇总本地看图复核里反复出现的缺陷 → data/vqa/recurring.json（给总调度 / 写作方 / 各 owner）。

读 data/vqa/verdicts/*.parsed.json（client 每次复核都存）+ data/vqa/script_feedback.jsonl（写作网关判出的剧本层问题）。
同一集同一检查项 ≥ THRESH 张不合格 → 一条“反复缺陷”，带去向：剧本 lint（已有就指向已有的）/ 出图链 owner。
只汇总文字，不发任何外部 API。
"""
from __future__ import annotations

import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VER = ROOT / "data" / "vqa" / "verdicts"
FB = ROOT / "data" / "vqa" / "script_feedback.jsonl"
OUT = ROOT / "data" / "vqa" / "recurring.json"
THRESH = 3
ROUTE = {   # 检查项 → (剧本侧 lint / 规则, 出图链 owner)
    "blank_expression": ("QW-A5（acting_lints）", "ACTING"),
    "eye_contact": ("K-REN-G01 / QW-A*（ACTING）", "ACTING"),
    "framing_mismatch": ("QW-CH6（validate_qwen_script）", "REFLOCK"),
    "outfit_mismatch": ("QW-W1 / QW-W4（writer_lints）", "REFLOCK"),
    "shoe_mismatch": ("VQ-W1（tools/vqa/script_lint.py）", "REFLOCK"),
    "hair_mismatch": ("—", "REFLOCK"), "identity_drift": ("—", "REFLOCK"), "extra_person": ("—", "REFLOCK"),
    "extra_limbs": ("—", "REFLOCK"), "hand_malformed": ("—", "REFLOCK"), "plastic_doll": ("—", "REFLOCK"),
    "text_watermark": ("—", "REFLOCK"), "wrong_scene": ("—", "REFLOCK"),
}


def main() -> dict:
    by: dict[tuple[str, str], list[str]] = defaultdict(list)
    for f in VER.glob("*.parsed.json"):
        try:
            v = json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            continue
        m = re.search(r"(ep\d+)", (v.get("subject") or "").replace("\\", "/"))
        ep = m.group(1) if m else "?"
        for d in v.get("defects") or []:
            by[(ep, d)].append(v.get("subject"))
    rows = [{"episode": ep, "check": c, "n": len(s), "examples": s[:5], "script_lint": ROUTE.get(c, ("—", "?"))[0],
             "owner": ROUTE.get(c, ("—", "?"))[1]} for (ep, c), s in sorted(by.items()) if len(s) >= THRESH]
    fb = [json.loads(x) for x in FB.read_text(encoding="utf-8").splitlines() if x.strip()] if FB.exists() else []
    out = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "threshold": THRESH, "recurring": rows, "script_feedback": fb[-50:]}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(rows)} 条反复缺陷，{len(fb)} 条剧本反馈 → {OUT.relative_to(ROOT)}")
    return out


if __name__ == "__main__":
    sys.exit(0 if main() is not None else 1)
