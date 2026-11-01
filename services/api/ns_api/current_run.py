"""当前剧（run）的唯一来源（WORKFLOW 11-02，总调度 P1 / UIAUDIT N1；规则 K-OPS-W20）。

界面和 API 里“当前是哪部剧”一律读 config/pipeline/runs.json 的 primary（tools/autopilot/runs.py）；
页面要切换剧目时传明确的 run / project 参数。不准按目录或文件修改时间猜（series10_s2 目录一出现，
人物中心按 mtime 猜成第二季，林晚人物页 404）。

- primary_run()：当前主剧 run_id；
- order_runs(names)：多部剧要列出或兜底遍历时的顺序 = primary 在前，其余按 runs.json 的 priority，再按名字；不看 mtime。
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def _runs():
    p = str(REPO / "tools" / "autopilot")
    if p not in sys.path:
        sys.path.insert(0, p)
    import runs as RUNS  # noqa: PLC0415
    return RUNS


def primary_run(root: Path | None = None) -> str:
    return _runs().primary_run(root or REPO)


def order_runs(names, root: Path | None = None) -> list:
    """names 可以是 run_id 字符串或 Path（取 .name）；返回同类型、按 primary → priority → 名字 排好的列表"""
    RUNS = _runs()
    reg = RUNS.registry(root or REPO)
    prim = reg.get("primary")
    pri = {k: (v or {}).get("priority", 10) for k, v in (reg.get("runs") or {}).items()}

    def key(x):
        n = x.name if isinstance(x, Path) else str(x)
        return (0 if n == prim else 1, pri.get(n, 99), n)
    return sorted(list(names), key=key)
