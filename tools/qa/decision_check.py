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


_PINNED_API = r"""
import json, os, sys
os.environ["NS_PRIMARY_RUN"] = sys.argv[1]
sys.path[:0] = ["services/api", "services/agent", "services/render_router", "packages/schema", "packages/qc", ""]
from fastapi.testclient import TestClient
from ns_api.app import app
out = {}
with TestClient(app) as cl:
    for u in sys.argv[2:]:
        r = cl.get(u)
        out[u] = r.json() if r.status_code == 200 else {"_status": r.status_code}
print("@@" + json.dumps(out, ensure_ascii=False))
"""
_PINNED_CACHE: dict = {}


def pinned_api(run: str, url: str):
    """K-OPS-F24（总调度 19:2x）：决定绑定某部剧（run: series10_v1）时，用钉住该剧的独立进程调接口（NS_PRIMARY_RUN），
    不随网页当前剧（primary）漂移——V1 冻结后它的断言照样要对。同一部剧的接口一次进程取全"""
    import subprocess
    if run not in _PINNED_CACHE:
        cfg = yaml.safe_load((ROOT / "config" / "owner_decisions.yaml").read_text(encoding="utf-8"))
        urls = sorted({c["url"] for c in cfg["checks"] if c.get("type") == "api" and c.get("run") == run})
        r = subprocess.run([sys.executable, "-X", "utf8", "-c", _PINNED_API, run, *urls], cwd=str(ROOT), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=600, env={**os.environ, "NS_DISABLE_BG": "1"})
        line = next((x for x in (r.stdout or "").splitlines() if x.startswith("@@")), None)
        if not line:
            raise RuntimeError(f"钉剧接口进程失败：{(r.stderr or '')[-300:]}")
        _PINNED_CACHE[run] = json.loads(line[2:])
    return _PINNED_CACHE[run][url]


def _current_primary() -> str | None:
    try:
        return json.loads((ROOT / "config" / "pipeline" / "runs.json").read_text(encoding="utf-8")).get("primary")
    except (OSError, ValueError):   # arch-ok: 读不到 = 按直连接口查（旧行为）
        return None


def check_api(c, use_api):
    if not use_api:
        return None, "跳过（--no-api）"
    try:
        if c.get("run") and c["run"] != _current_primary():
            data = pinned_api(c["run"], c["url"])
        else:
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


def check_cmd(c):
    """type: cmd（DISTILL 11-02，身份脸断言 K-OPS-X07）：{cmd: [脚本, 参数…]}，用本 venv 的 python 跑，退出码 0 = 符合"""
    import subprocess
    r = subprocess.run([sys.executable, "-X", "utf8", *c["cmd"]], cwd=str(ROOT), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=int(c.get("timeout", 300)))
    out = (r.stdout or r.stderr or "").strip().splitlines()
    return r.returncode == 0, ("；".join(out[:4]) or f"rc={r.returncode}")[:400]


def check_v2_isolation(c, use_api):
    """type: v2_isolation（L-125 / L-126，总调度 19:2x）：当前剧（V2）网页人物只来自 V2 资产清单 / V2 剧本人物登记，且不含任何 V1 人物"""
    if not use_api:
        return None, "跳过（--no-api）"
    try:
        with urllib.request.urlopen(API + c["url"], timeout=90) as r:
            data = json.loads(r.read().decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        return None, f"跳过（API 不可达：{e}）"
    got = {x.get(c.get("field", "id")) for x in _dig(data, c.get("list") or [])}
    man = json.loads((ROOT / c["manifest"]).read_text(encoding="utf-8"))
    allowed = set((man.get("characters") or {}).keys())
    sp = ROOT / c["script"]
    if sp.is_file():
        reg = (json.loads(sp.read_text(encoding="utf-8")).get("globals") or {}).get("character_registry") or []
        allowed |= {x.get("char_id") or x.get("id") for x in reg if isinstance(x, dict)}
    v1 = set(c.get("v1_cast") or [])
    leak, extra = sorted(map(str, got & v1)), sorted(map(str, got - allowed - v1))
    ok = not leak and not extra
    return ok, (f"V1 人物外露 {leak}" if leak else "") + (f" 清单外 {extra}" if extra else "") or f"只含 V2 人物 {sorted(map(str, got))}"


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
            elif t == "v2_isolation":
                ok, detail = check_v2_isolation(c, use_api)
            elif t in ("grep_absent", "grep_present"):
                ok, detail = check_grep(c, t == "grep_present")
            elif t in ("exists", "absent"):
                ok, detail = check_paths(c, t == "exists")
            elif t == "cmd":
                ok, detail = check_cmd(c)
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
