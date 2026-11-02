"""takes.json 命令行入口（EDITOR_INTEGRATION 附录 A2；WORKFLOW 等别的进程 / 服务器脚本改 takes.json 一律走这里）。

内部只调 ns_render.pipeline.get_takes / mutate_takes（唯一写入口：跨进程锁、seq+1、last_op、op_id 防重放、备份）。

用法：
  python tools/pipeline/takes_cli.py get --sid ep01-S1 [--run series10_s2]
      → stdout 一行 JSON {"seq": n, "doc": {...}}
  python tools/pipeline/takes_cli.py replace --sid ep01-S1 --op merge_dup --by WORKFLOW [--op-id X] [--expect-seq n] [--run R] < new_doc.json
      → 用 stdin 的整份 doc 替换（seq / last_op / last_ops 由写入口管，stdin 里带的会被忽略）
      → stdout {"ok": true, "seq": n}
退出码：0 成功；2 参数 / 输入错；3 seq 冲突（TakesConflict，stdout {"ok": false, "code": "stale_base", "seq": 实际}）；4 拿不到锁
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in ("services/render_router", "packages/schema", "services/agent", "services/recipes"):
    if str(ROOT / _p) not in sys.path:
        sys.path.insert(0, str(ROOT / _p))

MANAGED = ("seq", "last_op", "last_ops")


def _out(obj) -> None:
    sys.stdout.buffer.write((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="takes_cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("get")
    g.add_argument("--sid", required=True)
    g.add_argument("--run")
    r = sub.add_parser("replace")
    r.add_argument("--sid", required=True)
    r.add_argument("--op", required=True)
    r.add_argument("--by", required=True)
    r.add_argument("--op-id")
    r.add_argument("--expect-seq", type=int)
    r.add_argument("--run")
    a = ap.parse_args(argv)

    from ns_render import pipeline as P

    if a.cmd == "get":
        seq, doc = P.get_takes(a.sid, a.run)
        _out({"seq": seq, "doc": doc})
        return 0

    try:
        new = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    except ValueError as e:
        _out({"ok": False, "code": "bad_input", "error": str(e)[:200]})
        return 2
    if not isinstance(new, dict) or not isinstance(new.get("takes"), list):
        _out({"ok": False, "code": "bad_input", "error": "stdin 要是整份 takes doc（含 takes 列表）"})
        return 2

    def fn(doc):
        keep = {k: doc[k] for k in MANAGED if k in doc}
        return {**{k: v for k, v in new.items() if k not in MANAGED}, **keep}

    try:
        d = P.mutate_takes(a.sid, fn, op=a.op, by=a.by, op_id=a.op_id, run=a.run, expect_seq=a.expect_seq)
    except P.TakesConflict as e:
        _out({"ok": False, "code": "stale_base", "seq": e.actual, "expect": e.expect})
        return 3
    except TimeoutError as e:
        _out({"ok": False, "code": "locked_by_other", "error": str(e)[:200]})
        return 4
    _out({"ok": True, "seq": d.get("seq")})
    return 0


if __name__ == "__main__":
    sys.exit(main())
