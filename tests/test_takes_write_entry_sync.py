"""同步链路写 takes.json 只走 ns_render.pipeline.mutate_takes（SYSARCH #16 第 1 步，K-OPS-W29）。
- 两个进程同时往同一镜加版本（各 25 次），一条不丢、seq 单调到 50；
- merge_pull.merge_takes 写仓库内 takes.json 时走 mutate_takes（并发写入的版本不会被并回盖掉）；
- register_takes / resolve_dup_takes 源码里不再直接写 takes.json。全部临时目录。"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

WORKER = r"""
import sys, os
sys.path.insert(0, r"%s")
from ns_render import pipeline as P
tag = sys.argv[1]
for i in range(25):
    def fn(d, i=i):
        d.setdefault("takes", []).append({"stage": "image", "n": 1000 + len(d["takes"]), "file": f"renders/x/{tag}_{i}.png"})
    P.mutate_takes("ep01-S1", fn, op="t", by=tag)
"""


def test_two_processes_no_lost_takes(tmp_path):
    ren = tmp_path / "renders"
    (ren / "ep01" / "S1").mkdir(parents=True)
    env = {**os.environ, "NS_RENDERS_DIR": str(ren), "PYTHONUTF8": "1"}
    code = WORKER % str(ROOT / "services/render_router")
    ps = [subprocess.Popen([sys.executable, "-c", code, t], env=env, cwd=str(ROOT)) for t in ("A", "B")]
    assert all(p.wait(timeout=180) == 0 for p in ps)
    d = json.loads((ren / "ep01" / "S1" / "takes.json").read_text(encoding="utf-8"))
    files = {t["file"] for t in d["takes"]}
    assert len(files) == 50 and d["seq"] == 50 and d["last_op"]["seq"] == 50


def test_merge_takes_routes_through_mutate(monkeypatch, tmp_path):
    sys.path.insert(0, str(ROOT / "ops/offline"))
    sys.path.insert(0, str(ROOT / "services/render_router"))
    import merge_pull as MP
    from ns_render import pipeline as P
    monkeypatch.setattr(MP, "ROOT", tmp_path)
    monkeypatch.setattr(P, "RENDERS", tmp_path / "data" / "renders")
    monkeypatch.setattr(P, "DATA", tmp_path / "data")
    dst = tmp_path / "data/renders/ep01/S1/takes.json"
    dst.parent.mkdir(parents=True)
    dst.write_text(json.dumps({"seq": 4, "active": {"image": 1}, "takes": [{"stage": "image", "n": 1, "file": "a.png"}]}), encoding="utf-8")
    src = tmp_path / "pulled.json"
    src.write_text(json.dumps({"active": {"image": 1}, "takes": [{"stage": "image", "n": 1, "file": "b.png"}]}), encoding="utf-8")
    assert MP._sid_run_of(dst) == ("ep01-S1", None)
    MP.merge_takes(src, dst)
    d = json.loads(dst.read_text(encoding="utf-8"))
    assert d["seq"] == 5 and d["last_op"]["op"] == "merge_pull.merge_takes"
    assert {t["file"] for t in d["takes"]} == {"a.png", "b.png"} and d["active"]["image"] == 2      # 同号不同图换号，不覆盖


def test_no_direct_takes_writes_in_sync_chain():
    rt = (ROOT / "tools/pipeline/register_takes.py").read_text(encoding="utf-8")
    assert "_save_takes(" not in rt and "P.mutate_takes(" in rt
    rd = (ROOT / "ops/offline/resolve_dup_takes.py").read_text(encoding="utf-8")
    assert "P.mutate_takes(" in rd and "takes_cli.py replace" in rd and "MP.backup(rel)" not in rd


def test_a04_no_direct_takes_json_writes_anywhere():
    """A-04（V2_READINESS，FACTORY 21:3x）：takes.json 只经 ns_render.pipeline 的写入口落盘（mutate_takes / _save_takes → _commit_takes）。
    扫 services / tools / ops 的源码（不含测试）：直接对 takes.json（或指向它的变量）write_text / _write_json / os.replace / open(w) 的一律不许"""
    import ast
    def S(n, t):
        return ast.get_source_segment(t, n) or ""

    import re as _re
    _tj = _re.compile(r"""(?:^|[/"'\s])takes\.json""")         # 只认文件名正好是 takes.json（bad_takes.json 之类报告文件不算）

    def tk(e):
        e = e.lower()
        return bool(_tj.search(e)) or "takes_path(" in e
    allow = {("services/render_router/ns_render/pipeline.py", "_commit_takes")}
    bad = []
    for top in ("services", "tools", "ops"):
        for p in (ROOT / top).rglob("*.py"):
            if "_quarantine" in p.parts or "tests" in p.parts:
                continue
            t = p.read_text(encoding="utf-8", errors="replace")
            if "takes" not in t:
                continue
            try:
                tree = ast.parse(t)
            except SyntaxError:
                continue
            rel = p.relative_to(ROOT).as_posix()
            for fn in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
                if (rel, fn.name) in allow:
                    continue
                names = {x.id for n in ast.walk(fn) if isinstance(n, ast.Assign) and tk(S(n.value, t)) for x in n.targets if isinstance(x, ast.Name)}
                for n in ast.walk(fn):
                    if not isinstance(n, ast.Call):
                        continue
                    f = n.func
                    nm = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
                    tgt = None
                    if nm in ("write_text", "write_bytes") and isinstance(f, ast.Attribute):
                        tgt = f.value
                    elif nm in ("_write_json", "write_json", "js", "_js", "write_atomic", "_atomic_json", "atomic_write_json") and n.args:
                        tgt = n.args[0]
                    elif nm == "replace" and isinstance(f, ast.Attribute) and S(f.value, t) == "os" and len(n.args) == 2:
                        tgt = n.args[1]
                    if tgt is not None and (tk(S(tgt, t)) or (isinstance(tgt, ast.Name) and tgt.id in names)):
                        bad.append(f"{rel}:{n.lineno} {fn.name}")
    assert not bad, bad
