"""
S2 一次性豁免（项目方本人运行）：只对指定的一集、指定的一项要求（目前只有 plate = 场景底图须 owner_confirmed）。
全局规则不变，其他集照旧要求。写 config/s2_waivers.json 并重建状态时间线。

    python tools/s2_waiver.py --episode 2 --skip plate --quote "项目方原话" --scope "ep02 本次端到端测试渲染"
    python tools/s2_waiver.py --episode 2 --revoke          # 撤销

只记录项目方本人的决定：必须有原话；Claude / agent 会话不代为运行。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "config" / "s2_waivers.json"
SKIPPABLE = ("plate",)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--episode", type=int, required=True)
    ap.add_argument("--skip", action="append", choices=SKIPPABLE, default=[])
    ap.add_argument("--quote", default="", help="项目方原话（必填，撤销除外）")
    ap.add_argument("--scope", default="", help="有效范围，例如“ep02 本次端到端测试渲染”")
    ap.add_argument("--revoke", action="store_true")
    a = ap.parse_args()
    if a.episode < 1:
        ap.error("--episode 必须 ≥ 1")
    data = json.loads(CFG.read_text(encoding="utf-8")) if CFG.exists() else {"waivers": []}
    if not isinstance(data, dict) or not isinstance(data.get("waivers"), list):   # 封板修复：缺 waivers 键曾 KeyError
        data = {**(data if isinstance(data, dict) else {}), "waivers": []}
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    if a.revoke:
        n = 0
        for w in data["waivers"]:
            if w.get("episode") == a.episode and not w.get("revoked"):
                w["revoked"], w["revoked_at"] = True, now
                n += 1
        print(f"撤销 ep{a.episode:02d} 的豁免 {n} 条")
    else:
        if not a.quote.strip() or not a.skip:
            ap.error("需要 --skip 和项目方原话 --quote")
        data["waivers"].append({"episode": a.episode, "skip": a.skip, "owner_quote": a.quote.strip(),
                                "scope": a.scope.strip() or f"ep{a.episode:02d}", "by": "owner", "at": now,
                                "revoked": False})
        print(f"ep{a.episode:02d} 豁免 {a.skip}：{a.quote.strip()}")
    tmp = CFG.with_name(CFG.name + ".tmp")             # 封板修复 P2：原子写
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    os.replace(tmp, CFG)
    sys.path[:0] = [str(ROOT / "services" / "agent"), str(ROOT / "packages" / "schema")]
    from ns_agent import state_timeline as T
    T.write(ROOT)
    print(f"时间线已重建 -> {T.timeline_path(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
