"""列出待处理的派人请求（只读；EPCHAIN-O 11-03）。

请求由 autoflow（tools/script_rsi/autoflow_agent.py packet() / judge_request()）写在 <inbox>/requests/<run>__<id>.json，一请求一文件，
格式 nsfs.dispatch_request/1（见 docs/master/PIPELINE_SOP_V2.md「派人请求」）。本命令只读这些请求文件和它们指向的包 / 产物是否存在，不写任何东西。

待处理 = 包还在（没被作废移走、status 不是 voided）且产物的 .done 还没建（评委请求：任一位评委的 .done 没建）。

    .venv/Scripts/python.exe tools/master/pending_requests.py              # 表格
    .venv/Scripts/python.exe tools/master/pending_requests.py --json       # JSON（给脚本用）
    .venv/Scripts/python.exe tools/master/pending_requests.py --run series10_v2 --all   # 含已交稿 / 已作废
inbox 目录默认 data/master/inbox；NSFS_INBOX_DIR 或 --inbox 可改（演练 / 测试）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _abs(p: str | None, root: Path | None = None) -> Path | None:
    if not p:
        return None
    q = Path(p)
    return q if q.is_absolute() else (root or ROOT) / q


def state_of(req: dict, root: Path | None = None) -> str:
    """pending / done / voided"""
    outs = req.get("outputs") or ([req["output"]] if req.get("output") else [])
    pks = req.get("packets") or ([req["packet"]] if req.get("packet") else [])
    for pk in pks:
        pp = _abs(pk, root)
        if pp is None or not pp.exists():
            return "voided"                       # 包被作废移进 writer_tasks_void/（或评审轮目录被归档）
        try:
            d = json.loads(pp.read_text(encoding="utf-8"))
            if isinstance(d, dict) and d.get("status") == "voided":
                return "voided"
        except (OSError, ValueError):             # arch-ok: 包读不出也按“还在”算，交总调度看
            pass
    if outs and all((_abs(o + ".done", root) or Path("")).exists() for o in outs):
        return "done"
    return "pending"


def list_requests(inbox: Path, run: str | None = None, include_all: bool = False, root: Path | None = None) -> list[dict]:
    """root = 请求里相对路径的基准（默认仓库根；派单器测试传临时根）"""
    out = []
    for f in sorted((inbox / "requests").glob("*.json")):
        try:
            r = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            out.append({"file": f.name, "state": "unreadable", "error": repr(e)[:120]})
            continue
        if run and r.get("run") != run:
            continue
        r["state"] = state_of(r, root)
        r["file"] = f.name
        if include_all or r["state"] == "pending":
            out.append(r)
    return sorted(out, key=lambda r: (str(r.get("run")), int(r.get("episode") or 0), str(r.get("at"))))


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(description="列出待处理的派人请求（只读）")
    ap.add_argument("--inbox", default=os.environ.get("NSFS_INBOX_DIR") or "data/master/inbox")
    ap.add_argument("--run", default=None)
    ap.add_argument("--all", action="store_true", help="含已交稿（done）/ 已作废（voided）")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    inbox = _abs(a.inbox)
    rows = list_requests(inbox, a.run, a.all)
    if a.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
        return 0
    if not rows:
        print(f"没有待处理的请求（{inbox / 'requests'}）")
        return 0
    for r in rows:
        model = "/".join(r.get("suggested_models") or []) or r.get("suggested_model")
        print(f"[{r.get('state')}] {r.get('run')} ep{int(r.get('episode') or 0):02d} {r.get('kind')} {r.get('step')} 第{r.get('attempt')}次 "
              f"模型={model} 包={r.get('packet')} 产物={r.get('output') or r.get('outputs')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
