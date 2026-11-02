"""FACTORY D3：依赖闭包 = preflight 自己算（docs/master/FRAMEWORK_REFRAME.md §2 D3；L-099b；规则 K-OPS-F02）。

起因（11-02 01:13 实测）：assets_ready 按人工清单（resident_sync.required_data）判“资产齐”，漏了 assets/scenes，gpu36 交还后
每单都被 preflight I5 挡下。改为：在一台机器上对一批镜跑与 producer 完全相同的“编译作业 + preflight”（FJ.build_first →
UF._contract，不提交），用 Python 审计钩子记下这期间实际打开 / 列目录的仓库文件 + 作业 refs，得到依赖闭包 need={rel: sha}。
  - 在笔记本（资料全）上跑 → need.json：服务器缺什么一目了然，sync push 只补缺 sha 的文件
  - 在服务器上跑 → preflight 挡单数；挡 0 才能写 assets_ready.<host>.preflight_dryrun_ok=true（总调度 01:2x 交还条件）
只读：不提交、不写 takes / 账本（审计钩子只记录）。NS_ROOT 可指向另一份仓库（例：服务器开发树里的本工具去读生产副本的代码和数据）。

  python tools/factory/deps.py dryrun --host gpu36 [--eps 2,4] [--shots ep02-S1,...] [--out need.json] [--write-ready]
  python tools/factory/deps.py diff need.json          # 本机对照 need：缺的 / sha 不同的
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(os.environ.get("NS_ROOT") or Path(__file__).resolve().parents[2]).resolve()
for _p in ("services/render_router", "services/agent", "packages/schema", "tools/pipeline", "tools/gen_contract", "services/api",
           "services/recipes"):
    if str(ROOT / _p) not in sys.path:
        sys.path.insert(0, str(ROOT / _p))

TRACK_TOP = ("assets/", "data/", "config/", "knowledge/")
SKIP_PREFIX = ("data/producer/", "data/_quarantine", "data/_offline_pull", "data/cache/", "data/qa/", "data/factory/")


def partition_eps(host: str) -> list[int]:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import state_paths as SP                 # §10：运行期状态走 data/state/（兼容期读旧会留痕）
    part = SP.read_state("netfix/partition", root=ROOT)
    return sorted(int(x) for x in (part.get("images") or {}).get(host) or [])


def rel_of(p) -> str | None:
    """仓库内的相对路径（posix）；仓库外 / 不跟踪的目录 → None"""
    try:
        q = Path(os.fsdecode(p))
        q = (q if q.is_absolute() else Path.cwd() / q).resolve()
        r = q.relative_to(ROOT).as_posix()
    except (ValueError, OSError, TypeError):
        return None
    if not r.startswith(TRACK_TOP) or r.startswith(SKIP_PREFIX):
        return None
    return r


class Recorder:
    """sys.addaudithook 只能加不能删：用一个全局开关控制是否记录"""

    def __init__(self):
        self.on = False
        self.files: set[str] = set()
        self.dirs: set[str] = set()
        sys.addaudithook(self._hook)

    def _hook(self, ev, args):
        if not self.on:
            return
        if ev == "open" and args and isinstance(args[0], (str, bytes, os.PathLike)):
            r = rel_of(args[0])
            if r:
                self.files.add(r)
        elif ev in ("os.listdir", "os.scandir") and args:
            r = rel_of(args[0] if args[0] is not None else ".")
            if r:
                self.dirs.add(r)


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def shots_for(script, eps: list[int], only: set[str] | None):
    from ns_render import pipeline as P
    out = []
    for ep in getattr(script, "episodes", None) or []:
        n = int(getattr(ep, "index", None) or getattr(ep, "number", None) or 0)
        for sh in getattr(ep, "shots", None) or []:
            sid = getattr(sh, "id", None)
            if not sid:
                continue
            try:
                n2 = int(str(sid).split("-")[0][2:])
            except ValueError:
                n2 = n
            if (only and sid in only) or (not only and n2 in eps):
                out.append(sid)
    if not out:          # 剧本对象结构不认识时退回 find_shot 逐个试
        for e in eps:
            for i in range(1, 21):
                sid = f"ep{e:02d}-S{i}"
                if only and sid not in only:
                    continue
                try:
                    P.find_shot(script, sid)
                    out.append(sid)
                except Exception:  # noqa: BLE001
                    pass
    return out


def dryrun(eps: list[int], only: set[str] | None = None, rec: Recorder | None = None) -> dict:
    """→ {"shots": {sid: {"ok", "reasons", "refs"}}, "files": {rel: sha|None}, "blocked": n, "missing": [rel]}"""
    from ns_agent import frame_job as FJ
    from ns_render import pipeline as P
    from ns_render import unified_frame as UF
    rec = rec or Recorder()
    script = P.load_script()
    project = UF.project_for(script) or os.environ.get("NS_RUN_ID") or "series10_v1"   # 与 producer 同口径：project_for 认不出 → 用本剧 run_id（第二季）
    res: dict = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "root": str(ROOT), "project": project, "eps": eps, "shots": {}}
    need: set[str] = set()
    for sid in shots_for(script, eps, only):
        rec.files, rec.dirs = set(), set()
        rec.on = True
        try:
            ep, shot = P.find_shot(script, sid)
            job = FJ.build_first(project, ep, shot, script.globals)
            pf = UF._contract(job)
            refs = [str(r) for r in job.get("refs") or []]
            res["shots"][sid] = {"ok": bool(pf.ok), "reasons": list(pf.reasons()) if not pf.ok else [], "refs": refs}
        except Exception as e:  # noqa: BLE001
            res["shots"][sid] = {"ok": False, "reasons": [f"dryrun 异常：{e!r}"[:300]], "trace": traceback.format_exc()[-800:]}
            refs = []
        finally:
            rec.on = False
        need |= rec.files
        # 按“目录里最新一张”解析的资产（asset_refs.scene_ref：rglob + stat，审计钩子看不到 open）——列过的 assets/ 目录里的图全算依赖
        for dr in rec.dirs:
            if dr.startswith("assets/") and (ROOT / dr).is_dir():
                need |= {f"{dr}/{c.name}" for c in (ROOT / dr).iterdir() if c.is_file()}
        for r in refs:
            rr = rel_of(ROOT / r if not Path(r).is_absolute() else r)
            if rr:
                need.add(rr)
    files, missing = {}, []
    for r in sorted(need):
        p = ROOT / r
        if p.is_file():
            files[r] = sha256_file(p)
        else:
            files[r] = None
            missing.append(r)
    res.update(files=files, missing=missing, blocked=sum(1 for v in res["shots"].values() if not v["ok"]),
               total=len(res["shots"]))
    return res


def diff(need: dict) -> dict:
    """本机对照别处算出的 need：absent（没有）/ changed（sha 不同）"""
    absent, changed = [], []
    for r, sha in (need.get("files") or {}).items():
        if sha is None:
            continue
        p = ROOT / r
        if not p.is_file():
            absent.append(r)
        elif sha256_file(p) != sha:
            changed.append(r)
    return {"absent": absent, "changed": changed, "checked": len(need.get("files") or {})}


def write_ready(host: str, res: dict, path: Path | None = None) -> dict:
    """K-OPS-F02：只有 dryrun 挡 0（且至少跑了 1 镜）才写 preflight_dryrun_ok=true；否则写 false + 原因摘要"""
    path = path or (ROOT / "data/autopilot/assets_ready.json")
    try:
        cur = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cur = {}
    ok = res["total"] > 0 and res["blocked"] == 0
    rec = dict(cur.get(host) or {})
    rec.update(preflight_dryrun_ok=ok, preflight_dryrun_at=res["at"], preflight_dryrun_shots=res["total"],
               preflight_dryrun_blocked=res["blocked"], preflight_dryrun_by="FACTORY tools/factory/deps.py")
    if not ok:
        rec["preflight_dryrun_reasons"] = sorted({r[:60] for v in res["shots"].values() for r in v.get("reasons") or []})[:20]
    else:
        rec.pop("preflight_dryrun_reasons", None)
    cur[host] = rec
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cur, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)
    return rec


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("dryrun")
    d.add_argument("--host", required=True)
    d.add_argument("--eps", default="")
    d.add_argument("--shots", default="")
    d.add_argument("--out", default="")
    d.add_argument("--write-ready", action="store_true")
    d.add_argument("--all-eps", action="store_true", help="导入稿里的全部集（期望 refs 表用；非主剧由环境变量 NS_SCRIPT_JSON / NS_RENDERS_DIR 指向它的导入稿）")
    f = sub.add_parser("diff")
    f.add_argument("need")
    a = ap.parse_args(argv)
    if a.cmd == "dryrun":
        eps = list(range(1, 100)) if a.all_eps else ([int(x) for x in a.eps.split(",") if x] or partition_eps(a.host))
        only = {x for x in a.shots.split(",") if x} or None
        res = dryrun(eps, only)
        res["host"] = a.host
        if a.out:
            Path(a.out).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        reasons = {}
        for v in res["shots"].values():
            for r in v.get("reasons") or []:
                reasons[r[:50]] = reasons.get(r[:50], 0) + 1
        print(json.dumps({"host": a.host, "eps": eps, "total": res["total"], "blocked": res["blocked"], "files": len(res["files"]),
                          "missing": res["missing"][:30], "reasons": reasons}, ensure_ascii=False, indent=1))
        if a.write_ready:
            print("assets_ready:", json.dumps(write_ready(a.host, res), ensure_ascii=False))
        return 0 if res["blocked"] == 0 and res["total"] > 0 else 2
    print(json.dumps(diff(json.loads(Path(a.need).read_text(encoding="utf-8"))), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
