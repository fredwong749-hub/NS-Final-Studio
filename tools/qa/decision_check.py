"""项目方决策机检（RECALL 2026-11-01）：跑 config/owner_decisions.yaml 里的全部断言，打印 ✅/❌ 表。

用法：.venv/Scripts/python.exe -X utf8 tools/qa/decision_check.py [--no-api] [--json OUT]
退出码：有 ❌ → 1，否则 0。API 默认 http://127.0.0.1:8800（环境变量 NS_API 可改）。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
API = os.environ.get("NS_API", "http://127.0.0.1:8800")


def _dig(obj, path):
    for k in path:
        if isinstance(obj, dict) and k in obj:
            obj = obj[k]
        else:
            raise KeyError("/".join(map(str, path)))
    return obj


def _files(paths, glob=None):
    for p in paths:
        q = ROOT / p
        if q.is_dir():
            yield from (x for x in q.rglob(glob or "*") if x.is_file())
        elif q.is_file():
            yield q


def check_json(c):
    try:
        v = _dig(json.loads((ROOT / c["file"]).read_text(encoding="utf-8")), c["path"])
    except KeyError as e:
        return False, f"缺键 {e}"
    op, want = c["op"], c.get("value")
    if op == "eq":
        return v == want, f"实测 {v!r}"
    if op == "in":
        return v in want, f"实测 {v!r}"
    if op == "not_in":
        return v not in want, f"实测 {v!r}"
    if op == "len_eq":
        return len(v) == want, f"实测 {len(v)}"
    if op == "contains":
        return want in v, f"{'含' if want in v else '不含'} {want}"
    if op == "empty":
        return not v, f"实测 {v!r}"
    if op == "names_eq":
        names = sorted(x.get("name") for x in v)
        return names == sorted(want), f"实测 {names}"
    keys = set(v)
    if op == "keys_subset":
        extra = sorted(keys - set(want))
        return not extra, f"多出 {extra}" if extra else f"{sorted(keys)}"
    if op == "keys_superset":
        miss = sorted(set(want) - keys)
        return not miss, f"缺 {miss}" if miss else "齐"
    raise ValueError(op)


def check_api(c, use_api):
    if not use_api:
        return None, "跳过（--no-api）"
    try:
        with urllib.request.urlopen(API + c["url"], timeout=90) as r:
            data = json.loads(r.read().decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        return None, f"跳过（API 不可达：{e}）"
    lst = _dig(data, c.get("list") or [])
    if c["op"] == "len_eq":
        return len(lst) == c["value"], f"实测 {len(lst)}"
    got = {x.get(c["field"]) for x in lst}
    if c["op"] == "subset":
        extra = sorted(map(str, got - set(c["value"])))
        return not extra, f"多出 {extra}" if extra else f"{sorted(map(str, got))}"
    if c["op"] == "superset":
        miss = sorted(set(c["value"]) - got)
        return not miss, f"缺 {miss}" if miss else "齐"
    raise ValueError(c["op"])


def check_grep(c, present: bool):
    rx = re.compile(c["pattern"])
    skip = re.compile(c["exclude_line"]) if c.get("exclude_line") else None
    hits = []
    for f in _files(c["paths"], c.get("glob")):
        try:
            for i, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if rx.search(line) and not (skip and skip.search(line)):
                    hits.append(f"{f.relative_to(ROOT).as_posix()}:{i}")
        except OSError:
            pass
    if present:
        return bool(hits), (hits[0] if hits else "没找到")
    return not hits, (f"{len(hits)} 处，如 {hits[:3]}" if hits else "无")


def check_paths(c, exists: bool):
    bad = [p for p in c["paths"] if (ROOT / p).exists() != exists]
    return not bad, (f"{'缺' if exists else '仍在'} {bad}" if bad else "符合")


def run(use_api=True):
    cfg = yaml.safe_load((ROOT / "config" / "owner_decisions.yaml").read_text(encoding="utf-8"))
    rows = []
    for c in cfg["checks"]:
        t = c["type"]
        try:
            if t == "json":
                ok, detail = check_json(c)
            elif t == "api":
                ok, detail = check_api(c, use_api)
            elif t in ("grep_absent", "grep_present"):
                ok, detail = check_grep(c, t == "grep_present")
            elif t in ("exists", "absent"):
                ok, detail = check_paths(c, t == "exists")
            else:
                ok, detail = False, f"未知类型 {t}"
        except Exception as e:  # noqa: BLE001
            ok, detail = False, f"检查出错：{e!r}"
        pu = c.get("pending_until")
        if ok is False and pu and not all((ROOT / p_).exists() for p_ in pu.get("paths") or []):
            # “待开”（VQAGATE 11-01，总调度：条件未满足的决定显示 ⏳ 不显示 ❌）：pending_until.paths 都存在 = 条件满足，之后仍不符才算 ❌
            ok, detail = "pending", f"待开：{pu.get('why') or '条件未满足'}（{detail}）"
        rows.append({"id": c["id"], "ok": ok, "title": c["title"], "decision": c.get("decision", ""), "detail": detail})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-api", action="store_true")
    ap.add_argument("--json")
    a = ap.parse_args()
    rows = run(not a.no_api)
    mark = {True: "✅", False: "❌", None: "⏭", "pending": "⏳"}
    print("| 结果 | id | 检查 | 实测 |\n|---|---|---|---|")
    for r in rows:
        print(f"| {mark[r['ok']]} | {r['id']} | {r['title']} | {str(r['detail'])[:160]} |")
    n_ok = sum(r["ok"] is True for r in rows)
    n_bad = sum(r["ok"] is False for r in rows)
    n_pend = sum(r["ok"] == "pending" for r in rows)
    print(f"\n合计 {len(rows)}：✅ {n_ok}  ❌ {n_bad}  ⏳ {n_pend}  ⏭ {len(rows) - n_ok - n_bad - n_pend}")
    try:   # K-OPS-D02 汇总（总调度 11-01：decision_check 末尾打印；明细 data/qa/decision_propagation/report.md）
        import importlib.util as _ilu
        _sp = _ilu.spec_from_file_location("ns_decision_propagation_dc", Path(__file__).resolve().parent / "decision_propagation.py")
        _dp = _ilu.module_from_spec(_sp)
        _sp.loader.exec_module(_dp)
        print(_dp.summary(_dp.run()))
    except Exception as e:  # noqa: BLE001
        print(f"决策全量同步：未测（{e!r}）"[:200])
    if a.json:
        Path(a.json).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    return 1 if n_bad else 0


if __name__ == "__main__":
    sys.exit(main())
