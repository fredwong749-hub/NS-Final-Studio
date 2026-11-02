"""卡点登记（PIPELINE_SOP_V2.md 的配套工具）：任何 agent / 系统步骤卡住时调用一次。

  report_issue.py report --run series10_v2 --episode 1 --step 8 --who GOLDEN-S --what "大白话" --blocking yes --fix-hint "..."
  report_issue.py list [--all]
  report_issue.py close --id ISS-... --sop-updated yes|no

记录在 data/pipeline/issues.jsonl（只追加：open 一行，close 另追加一行事件；list 折叠成当前状态），
同时在 docs/master/V2_LIVE.md 第一行之后插一行“HH:MM ⚠ 卡点（who）：……”，总调度一眼看到。
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ISSUES = ROOT / "data" / "pipeline" / "issues.jsonl"
LIVE = ROOT / "docs" / "master" / "V2_LIVE.md"
SOP_HINT = "这条经验还没写进 PIPELINE_SOP_V2.md（写进对应步骤的“前置条件 / 卡过的地方”，再 close --sop-updated yes）"


def _append_line(path: Path, obj: dict) -> None:
    """单次 os.write 到 O_APPEND 句柄：多进程同时追加不会交错"""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)


def _insert_live(line: str, live: Path = LIVE) -> None:
    """在第一行之后插一行（tmp + os.replace 原子写）"""
    if not live.is_file():
        return
    text = live.read_text(encoding="utf-8")
    head, sep, rest = text.partition("\n")
    new = head + "\n" + line + "\n" + rest if sep else head + "\n" + line + "\n"
    tmp = live.with_name(live.name + f".tmp{os.getpid()}")
    tmp.write_text(new, encoding="utf-8")
    os.replace(tmp, live)


def report(run: str, episode: int, step: str, who: str, what: str, blocking: bool, fix_hint: str = "",
           issues: Path = ISSUES, live: Path | None = LIVE) -> dict:
    now = time.localtime()
    rec = {"id": f"ISS-{time.strftime('%m%d-%H%M%S', now)}-{secrets.token_hex(2)}", "event": "open",
           "time": time.strftime("%F %T", now), "run": run, "episode": episode, "step": str(step), "who": who,
           "what": what, "blocking": bool(blocking), "fix_hint": fix_hint, "status": "open"}
    _append_line(issues, rec)
    if live is not None:
        tail = f"（建议：{fix_hint}）" if fix_hint else ""
        _insert_live(f"{time.strftime('%H:%M', now)} ⚠ 卡点（{who}）：{run} 第{episode}集 步骤{step}"
                     f"{'【阻断】' if blocking else ''}：{what}{tail} [{rec['id']}]", live)
    return rec


def load(issues: Path = ISSUES) -> list[dict]:
    """折叠事件流 → 每个 id 的当前状态"""
    out: dict[str, dict] = {}
    if not issues.is_file():
        return []
    for ln in issues.read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        try:
            e = json.loads(ln)
        except ValueError:      # arch-ok: 追加写偶发坏行只跳过，不影响其余记录
            continue
        if e.get("event") == "close" and e.get("id") in out:
            out[e["id"]].update(status="closed", closed_at=e.get("time"), sop_updated=e.get("sop_updated"))
        elif e.get("event") == "open":
            out[e["id"]] = dict(e)
    return list(out.values())


def close(issue_id: str, sop_updated: bool, issues: Path = ISSUES) -> tuple[bool, str]:
    cur = {i["id"]: i for i in load(issues)}
    if issue_id not in cur:
        return False, f"没有这条：{issue_id}"
    _append_line(issues, {"id": issue_id, "event": "close", "time": time.strftime("%F %T"), "sop_updated": bool(sop_updated)})
    return True, ("已关闭。" if sop_updated else "已关闭。提示：" + SOP_HINT)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("report", help="登记一个卡点")
    r.add_argument("--run", required=True)
    r.add_argument("--episode", type=int, required=True)
    r.add_argument("--step", required=True, help="SOP 表里的步骤号或名字")
    r.add_argument("--who", required=True)
    r.add_argument("--what", required=True, help="大白话")
    r.add_argument("--blocking", choices=["yes", "no"], required=True)
    r.add_argument("--fix-hint", default="")
    ls = sub.add_parser("list", help="列出 open 的")
    ls.add_argument("--all", action="store_true")
    c = sub.add_parser("close", help="关闭一条")
    c.add_argument("--id", required=True)
    c.add_argument("--sop-updated", choices=["yes", "no"], required=True)
    a = ap.parse_args(argv)
    if a.cmd == "report":
        rec = report(a.run, a.episode, a.step, a.who, a.what, a.blocking == "yes", a.fix_hint)
        print(f"已登记 {rec['id']}，并写入 docs/master/V2_LIVE.md")
        return 0
    if a.cmd == "list":
        rows = [i for i in load() if a.all or i["status"] == "open"]
        for i in rows:
            print(f"{i['id']} [{i['status']}] {i['run']} 第{i['episode']}集 步骤{i['step']} {i['who']}"
                  f"{' 阻断' if i['blocking'] else ''}：{i['what']}")
        if not rows:
            print("没有 open 的卡点")
        return 0
    ok, msg = close(a.id, a.sop_updated == "yes")
    print(msg)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
