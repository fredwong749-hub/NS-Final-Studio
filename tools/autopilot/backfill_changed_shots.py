"""给没有 changed_shots 的历史导入事件补记镜级变化（PS-MASTER 11-04 定的“按镜作废”口径）。

import_staged_run 每次导入前把旧导入稿备份到 data/import/runs/<run>/backups/script_v2.<YYYYmmdd-HHMMSS>.json；
事件 E 的“导入前稿” = 时间 ≤ E.at 且最近（10 分钟内）的备份；“导入后稿” = 时间 > E.at 的下一份备份（没有 = 现行导入稿）。
两稿逐镜比提示词指纹（import_events.shot_sigs），不同或新增的镜 = changed。
只追加事件（kind=changed_shots_backfill，orig_at 引用原事件时间），不改旧行；默认只打印，--apply 才写。
用法：python tools/autopilot/backfill_changed_shots.py --run series10_v2 [--apply]"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import import_events as IE  # noqa: E402
import runs as RN  # noqa: E402


def _ts(name: str) -> str | None:
    m = re.search(r"\.(\d{8})-(\d{6})\.json$", name)
    return f"{m.group(1)[:4]}-{m.group(1)[4:6]}-{m.group(1)[6:]}T{m.group(2)[:2]}:{m.group(2)[2:4]}:{m.group(2)[4:]}" if m else None


def plan(run: str, root: Path | None = None, events: Path | None = None, window_s: int = 600) -> tuple[list[dict], list[str]]:
    root = root or IE.ROOT
    cur = RN.import_path(run, root)
    bdir = cur.parent / "backups"
    backs = sorted((t, p) for p in bdir.glob("script_v2.*.json") if (t := _ts(p.name)))
    evs = IE.read_events(events)
    done = {e.get("orig_at") for e in evs if e.get("kind") == "changed_shots_backfill" and e.get("run_id") == run}
    out, skipped = [], []
    tm = lambda s: time.mktime(time.strptime(s[:19], "%Y-%m-%dT%H:%M:%S"))   # noqa: E731
    for e in evs:
        if e.get("run_id") != run or e.get("kind") or "changed_shots" in e or e.get("at") in done:
            continue
        before = [(t, p) for t, p in backs if t <= e["at"] and tm(e["at"]) - tm(t) <= window_s]
        if not before:
            skipped.append(f"{e['at']} eps={e.get('episodes')}：找不到导入前备份（{window_s}s 内）")
            continue
        old = before[-1][1]
        after = next((p for t, p in backs if t > e["at"]), cur)
        ch = IE.changed_shots(old, after)
        out.append({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "kind": "changed_shots_backfill", "run_id": run, "orig_at": e["at"],
                    "episodes": e.get("episodes"), "changed_shots": ch, "old_script": old.name, "new_script": after.name,
                    "by": "backfill_changed_shots.py", "note": "历史事件补记镜级变化（按镜作废口径）"})
    return out, skipped


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    rows, skipped = plan(a.run)
    for r in rows:
        print(r["orig_at"], r["episodes"], f"{len(r['changed_shots'])} 镜变", r["old_script"], "→", r["new_script"], r["changed_shots"][:20])
    for s in skipped:
        print("SKIP", s)
    if a.apply:
        with open(IE.EVENTS, "a", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"已追加 {len(rows)} 条补记事件 → {IE.EVENTS}")


if __name__ == "__main__":
    main()
