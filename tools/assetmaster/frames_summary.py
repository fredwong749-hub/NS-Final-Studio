"""frames_v2 收尾汇总：每集首 / 尾帧 通过 / 不合格 / 未决、双人镜 variant 胜出数、Q2/Q5 重打分救回数；--ledger 时追加 RSI_LEDGER 一节。

用法：.venv/Scripts/python.exe tools/assetmaster/frames_summary.py [--ledger]
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / "data/assetmaster/frames_v2/state.json"
OUT = ROOT / "data/assetmaster/frames_v2/summary.md"


def summarize() -> tuple[str, dict]:
    st = json.loads(STATE.read_text(encoding="utf-8"))
    eps = collections.defaultdict(lambda: collections.Counter())
    wins, tries = collections.Counter(), collections.Counter()
    for sid, v in st.items():
        if not sid.startswith("ep"):
            continue
        n = int(sid[2:4])
        for stage in ("image", "last"):
            r = v.get(stage) or {}
            fin = (r.get("final") or {}).get("status")
            key = {"通过": "通过", "不合格": "不合格", "阻断": "阻断", "不适用": "不适用"}.get(fin or "", "未决")
            if fin and fin.startswith("未出"):
                key = "未出（首帧不合格）"
            eps[n][f"{stage}:{key}"] += 1
            for a in r.get("attempts", []):
                if a.get("variant"):
                    tries[a["variant"]] += 1
            if fin == "通过":
                best = next((a for a in r.get("attempts", []) if a.get("file") == r["final"].get("file")), {})
                if best.get("variant"):
                    wins[best["variant"]] += 1
    rescued = st.get("_rescued") or []
    L = ["# frames_v2 汇总（" + time.strftime("%Y-%m-%d %H:%M") + "）", "",
         "| 集 | 首帧 通过 | 首帧 不合格 | 首帧 未决 | 尾帧 通过 | 尾帧 不合格 | 尾帧 未决/未出 |", "|---|---|---|---|---|---|---|"]
    tot = collections.Counter()
    for n in sorted(eps):
        c = eps[n]
        tot.update(c)
        L.append(f"| ep{n:02d} | {c['image:通过']} | {c['image:不合格']} | {c['image:未决'] + c['image:阻断']} | {c['last:通过']} "
                 f"| {c['last:不合格']} | {c['last:未决'] + c['last:未出（首帧不合格）'] + c['last:不适用']} |")
    L.append(f"| 合计 | {tot['image:通过']} | {tot['image:不合格']} | {tot['image:未决'] + tot['image:阻断']} | {tot['last:通过']} "
             f"| {tot['last:不合格']} | {tot['last:未决'] + tot['last:未出（首帧不合格）'] + tot['last:不适用']} |")
    L += ["", "双人镜 variant：" + "；".join(f"{k} 尝试 {tries[k]} 次、胜出 {wins[k]} 次" for k in sorted(tries)),
          f"Q2/Q5 重打分救回：{len(rescued)} 个（{', '.join(rescued[:20])}）"]
    md = "\n".join(L) + "\n"
    OUT.write_text(md, encoding="utf-8")
    return md, {"tot": dict(tot), "wins": dict(wins), "tries": dict(tries), "rescued": rescued}


def ledger(d: dict) -> None:
    t = d["tot"]
    row = (f"| AM6 | 双人镜参考板（两脸 + 两人设定图 / 单品 / 场景）能兼顾身份与服装 | frames_v2 run5 全量（frame_v9），"
           f"Q4 两次不过 → 第 3 次换“两脸 + 林晚造型图” | 首帧通过 {t.get('image:通过', 0)}、不合格 {t.get('image:不合格', 0)}；"
           f"尾帧通过 {t.get('last:通过', 0)}；variant 胜出 {d['wins']} / 尝试 {d['tries']}；Q2/Q5 重打分救回 {len(d['rescued'])} | "
           f"见数字（REFLOCK 阈值仍待 BAKEOFF 留出集验证） | K-AST-260、K-REN-132 | data/assetmaster/frames_v2/summary.md |")
    p = ROOT / "knowledge/RSI_LEDGER.md"
    s = p.read_text(encoding="utf-8")
    if "| AM6 |" not in s:
        p.write_text(s.rstrip("\n") + "\n" + row + "\n", encoding="utf-8")


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", action="store_true")
    a = ap.parse_args(argv)
    md, d = summarize()
    print(md)
    if a.ledger:
        ledger(d)
    return 0


if __name__ == "__main__":
    sys.exit(main())
