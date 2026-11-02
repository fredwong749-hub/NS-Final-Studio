"""FACTORY D4（第一部分）：派单前 refs 的 sha 校验（总调度 01:3x 批准；规则 K-OPS-F03）。

起因（11-02 01:24–01:32 实测）：服务器缺 data/looks/face_overrides.json，preflight 照样 0 挡，但林晚身份脸解析成旧的 ref2va，
两台 31 个 take 用错身份脸，事后才发现。根治：笔记本（资料全、决定在这里做）用 tools/factory/deps.py 算出每镜期望的 refs
（路径 + sha），写进目标状态 data/factory/inbox/expected_refs.json，随 inbox 推到服务器；服务器 producer 每次派单前把这单
实际要上传的 refs 逐个算 sha 和期望比对，不一致 → 拒派（不提交、不计次）+ 报警事件 refs_mismatch。

    python tools/factory/inbox.py build [--hosts gpu33,gpu36,laptop]   # 笔记本：生成 expected_refs.json
笔记本上没有期望表 = 不拦（返回 None）；服务器上期望表缺失由 decisions_guard 拒派（K-OPS-F09）；表里没有这镜 = 拒派。
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(os.environ.get("NS_ROOT") or Path(__file__).resolve().parents[2]).resolve()
EXPECTED = ROOT / "data/factory/inbox/expected_refs.json"
_SHA_CACHE: dict[tuple[str, float, int], str] = {}


def _sha(p: Path) -> str | None:
    try:
        st = p.stat()
    except OSError:
        return None
    k = (str(p), st.st_mtime_ns, st.st_size)
    fresh = time.time() - st.st_mtime < 5        # 刚写过的文件不走缓存（同秒同大小改写会撞键）
    if fresh or k not in _SHA_CACHE:
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for b in iter(lambda: f.read(1 << 20), b""):
                h.update(b)
        _SHA_CACHE[k] = h.hexdigest()
    return _SHA_CACHE[k]


def _rel(r: str, root: Path) -> str:
    p = Path(r)
    if p.is_absolute():
        try:
            return p.resolve().relative_to(root).as_posix()
        except ValueError:
            return str(r)
    return Path(r).as_posix()


def load_expected(path: Path | None = None) -> dict | None:
    try:
        return json.loads((path or EXPECTED).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def check_refs(sid: str, refs: list, expected: dict | None = None, root: Path | None = None,
               run: str | None = None) -> list[str] | None:
    """→ None = 无期望值（不拦）；[] = 一致；[问题…] = 不一致（拒派）。run = 非主剧时查 expected["runs"][run]
    （多剧并行：第二季镜号与第一季重名，必须按 run 分开，K-OPS-F03 / 总调度 09:2x）"""
    root = root or ROOT
    exp = expected if expected is not None else load_expected()
    if not exp:
        return None
    table = exp.get("shots") or {}
    if run and run != exp.get("primary", run):
        table = (exp.get("runs") or {}).get(run)
        if table is None:
            return [f"期望 refs 表里没有剧 {run}（先在笔记本 inbox.py build + sync push）"]
    want = table.get(sid)
    if want is None:        # K-OPS-F09：有期望表但这镜不在表里 = 目标状态没覆盖到 → 拒派（⤴ 取代“不在表里不拦”）
        return [f"期望 refs 表里没有 {run + ':' if run else ''}{sid}（先在笔记本 inbox.py build + sync push）"]
    got = [_rel(str(r), root) for r in refs or []]
    wl = [w["rel"] for w in want]
    wsha = {w["rel"]: w.get("sha") for w in want}
    closure = (exp.get("files") or {}) if not run or run == exp.get("primary", run) else ((exp.get("run_files") or {}).get(run) or {})
    probs = []
    # 自修阶梯的变体（只挂脸 / 两张脸 + 设定图 / 参考板 / 同脸双槽）会合法地改 refs 组合，所以不比整张清单，只核三件事
    # （11-02 12:2x 实测：按整张清单比，变体镜全被拦）：
    # ① 身份脸只能是这镜期望里的那几张（防 01:24 那种身份脸用错）；② 每个文件的 sha 与笔记本一致；③ 没登记过的文件只记不拦
    want_faces = {r for r in wl if "/identity_refs/" in r}
    for r in got:
        if "/identity_refs/" in r and r not in want_faces:
            probs.append(f"身份脸不对：{r} 不在本镜期望 {sorted(want_faces)}")
    for r in got:
        exp_sha = wsha.get(r) or closure.get(r)
        if exp_sha is None:
            continue
        s_ = _sha(root / r)
        if s_ is None:
            probs.append(f"缺文件 {r}")
        elif s_ != exp_sha:
            probs.append(f"sha 不一致 {r}：期望 {exp_sha[:12]}，实际 {s_[:12]}")
    return probs


def _runs(root: Path) -> tuple[str, list[str]]:
    """(主剧, 有导入稿的全部剧)——按 config/pipeline/runs.json（tools/autopilot/runs.py）"""
    import importlib.util
    spec = importlib.util.spec_from_file_location("ns_runs_ib", root / "tools/autopilot/runs.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    prim = m.primary_run(root)
    allr = [r for r in m.list_runs(root, status=None) if m.import_path(r, root).exists()]
    return prim, ([prim] + [r for r in allr if r != prim]) if prim else allr


def _dryrun_run(root: Path, run: str, primary: str, py: str) -> dict:
    """每部剧单独起一个进程跑 deps dryrun（非主剧要在 import ns_render 之前设 NS_SCRIPT_JSON / NS_RENDERS_DIR）"""
    import subprocess
    import tempfile
    env = dict(os.environ, NS_ROOT=str(root), PYTHONIOENCODING="utf-8", PYTHONUTF8="1",
               PYTHONPATH=os.pathsep.join(str(root / x) for x in ("packages/schema", "services/agent", "services/api",
                                                                    "services/render_router", "services/recipes")))
    env["NS_RUN_ID"] = run          # deps 的 project 回退值 = 本剧 run_id（与 producer 的 project_for(...) or run_id 同口径）
    if run != primary:
        env.update(NS_RENDERS_DIR=str(root / "data" / "renders" / run),
                   NS_SCRIPT_JSON=str(root / "data" / "import" / "runs" / run / "script_v2.json"))
    fd, out = tempfile.mkstemp(suffix=".json", prefix=f"expref_{run}_")
    os.close(fd)
    try:
        r = subprocess.run([py, str(root / "tools/factory/deps.py"), "dryrun", "--host", "all", "--all-eps", "--out", out],
                           cwd=root, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=3600)
        try:
            return json.loads(Path(out).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise RuntimeError(f"{run} dryrun 没出结果：{(r.stderr or r.stdout)[-400:]}")
    finally:
        Path(out).unlink(missing_ok=True)


def build(hosts: list[str] | None = None, root: Path | None = None, out_path: Path | None = None) -> dict:
    """期望 refs 表（路径 + sha），按剧分开：shots = 主剧，runs[<剧>] = 其它有导入稿的剧（第二季 series10_s2 等）。
    root = 用哪棵树建：deploy 时传 cut 冻结快照（代码 = 已部署的 tag，数据 = cut 时刻），平时缺省本仓库（K-OPS-F03 修订）"""
    root = Path(root or ROOT)
    py = sys.executable
    prim, runs = _runs(root)
    tables, blocked, counts, files_by_run = {}, {}, {}, {}
    for run in runs:
        res = _dryrun_run(root, run, prim, py)
        t = {}
        for sid, v in res["shots"].items():
            if not v.get("ok"):
                blocked[f"{run}:{sid}"] = v.get("reasons")
                continue
            t[sid] = [{"rel": _rel(r, root), "sha": _sha(root / _rel(r, root))} for r in v.get("refs") or []]
        tables[run] = t
        counts[run] = len(t)
        files_by_run[run] = {k: v for k, v in (res.get("files") or {}).items() if v}
    out = {"at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "by": "FACTORY tools/factory/inbox.py build（K-OPS-F03）",
           "built_from": str(root), "primary": prim, "shots": tables.get(prim, {}),
           "runs": {r: t for r, t in tables.items() if r != prim}, "counts": counts, "laptop_blocked": blocked,
           "files": files_by_run.get(prim, {}), "run_files": {r: f for r, f in files_by_run.items() if r != prim}}
    dest = out_path or (ROOT / "data/factory/inbox/expected_refs.json")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, dest)
    return out


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build"])
    ap.add_argument("--hosts", default="gpu33,gpu36,laptop")
    a = ap.parse_args()
    o = build()
    print(json.dumps({"counts": o["counts"], "laptop_blocked": len(o["laptop_blocked"]), "file": str(EXPECTED)}, ensure_ascii=False))
