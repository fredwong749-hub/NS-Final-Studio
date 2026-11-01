"""
审计规则说明：GET /api/gpu3/rules（全表，解析 docs/audit/rule_ids.md）和 /rules/{rule_id}
（子进程跑 gpu3 的 `ns-studio/scripts/shot_audit.py --explain <id> --json`，按 rule_id + 规则表 sha 缓存）。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import threading
from pathlib import Path

ID_RE = re.compile(r"^[A-Z][A-Z0-9]*-[A-Z]+\d+[a-z]?$")
ROW_RE = re.compile(r"^\|\s*([A-Z][A-Z0-9]*-[A-Z]+\d+[a-z]?)\s*\|")
_cache: dict[tuple[str, str], dict] = {}
_lock = threading.Lock()


class RuleError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


def table_sha(path: Path | None) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except (OSError, AttributeError):
        return ""


def split_row(line: str) -> list[str]:
    """markdown 表格行 → 单元格；反引号里的 | 不算分隔（如 `\b(no|not)\b`）。"""
    cells, cur, code = [], [], False
    body = line.strip()
    body = body[1:] if body.startswith("|") else body
    body = body[:-1] if body.endswith("|") and not body.endswith("\\|") else body
    for ch in body:
        if ch == "`":
            code = not code
        if ch == "|" and not code:
            cells.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    cells.append("".join(cur).strip())
    return cells


def parse_table(path: Path | None) -> dict:
    """rule_ids.md → {rules_sha, version, rules:[{rule_id, rule, check, level, sop_ref, section, retired}]}"""
    if not path or not path.exists():
        raise RuleError(503, f"规则表不可读：{path}")
    text = path.read_text(encoding="utf-8", errors="replace")
    version = (re.search(r"`(rule_ids/v\d+)`", text) or [None, None])[1]
    rules, section = [], None
    for ln in text.splitlines():
        if ln.startswith("## "):
            section = ln[3:].strip()
            continue
        m = ROW_RE.match(ln)
        if not m:
            continue
        cells = split_row(ln)
        cells += [""] * (5 - len(cells))
        rules.append({"rule_id": m.group(1), "rule": cells[1], "check": cells[2], "level": cells[3],
                      "sop_ref": cells[4], "section": section, "retired": "作废" in ln})
    return {"rules_sha": table_sha(path), "version": version, "count": len(rules), "rules": rules}


def explain(rule_id: str, *, table: Path | None, python: str | None, script: Path | None,
            cwd: Path | None = None, timeout: float = 15.0) -> dict:
    if not ID_RE.match(rule_id):
        raise RuleError(404, f"不是合法的 rule_id：{rule_id}")
    tab = parse_table(table)
    if rule_id not in {r["rule_id"] for r in tab["rules"]}:
        raise RuleError(404, f"rule_id {rule_id} 不在 docs/audit/rule_ids.md 里")
    key = (rule_id, tab["rules_sha"])
    with _lock:
        if key in _cache:
            return {**_cache[key], "cached": True}
    if not script or not script.exists() or not python:
        raise RuleError(503, f"shot_audit.py 不可用：{script}")
    try:
        # 封板修复：显式 utf-8（Windows 默认 cp1252 时子进程输出中文会崩 → 502）；Linux 上行为不变
        p = subprocess.run([python, str(script), "--explain", rule_id, "--json"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                           timeout=timeout, cwd=str(cwd or script.parent))
    except subprocess.TimeoutExpired:
        raise RuleError(504, f"shot_audit.py --explain {rule_id} 超过 {timeout:g}s")
    except OSError as e:
        raise RuleError(503, f"无法运行 shot_audit.py：{e}")
    try:
        data = json.loads(p.stdout)
    except ValueError:
        raise RuleError(502, f"shot_audit.py 输出不是 JSON（exit {p.returncode}）：{(p.stderr or p.stdout)[-300:]}")
    if not data.get("found"):
        raise RuleError(404, f"shot_audit.py 不认识 {rule_id}（规则表与代码不同步？）")
    out = {**data, "rules_sha": tab["rules_sha"], "retired": next(r["retired"] for r in tab["rules"] if r["rule_id"] == rule_id)}
    with _lock:
        _cache[key] = out
    return {**out, "cached": False}
