"""W33（C-14 / L-126）：列出某剧写进 V1 目录（data/renders/epNN/SNN/takes/）的版本文件 + 目标路径（data/renders/<run>/…）。

背景：W33 之前 ns_render 写版本时 rel 丢了剧名前缀，series10_v2 的版本文件落在 V1 目录。
归属判据：本剧 takes.json（data/renders/<run>/epNN/SNN/takes.json，不含 quarantined[]）里登记、
且 producer.foreign_reasons(origin / role) 判为本剧的版本 → 它引用的不带前缀的文件属于本剧。
V1 自己的 takes.json 也引用同一文件 → 标 shared_with_v1（迁移时不能搬，只能复制或留原处）。

  python tools/debug/migrate_renders_prefix.py --run series10_v2 --dry   # 只列，不动任何文件（缺省即 dry）
  python tools/debug/migrate_renders_prefix.py --run series10_v2 --apply # 搬（只搬不删，W34 总调度决定）

--apply（W34）：按 plan() 的 rows 逐个文件 move 到 data/renders/<run>/…（目标已存在 → 不覆盖，记冲突；
shared_with_v1 → 不搬，记冲突；源不在而目标在 → 视为上次已搬）；文件到位后改写本剧 takes.json 里引用它的
版本字段（takes[] 与 quarantined[]）为新 rel，原值写进 <字段>_legacy（file → file_legacy）；takes.json 走
ns_render.pipeline.mutate_takes（锁 + seq + .takes_bak 备份），改写前另抄一份进 manifest 目录。
清单写 data/quarantine/<run>/migrate_<ts>/manifest.json。幂等：重跑时已改写的 rel 带前缀，plan() 不再列出。
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "autopilot"))

_UNPREF = re.compile(r"^renders/(ep\d+/S\d+/.+)$")
FILE_KEYS = ("file", "raw_file", "last_frame", "mask_file", "thumb")


def _norm(f) -> str:
    s = str(f or "").replace("\\", "/").lstrip("/")
    return s[5:] if s.startswith("data/") else s


def take_files(t: dict) -> list[tuple[str, str]]:
    """版本里引用的文件（字段名, 相对 data/ 的路径）"""
    out = []
    for k in FILE_KEYS:
        v = t.get(k)
        if isinstance(v, str) and v:
            out.append((k, _norm(v)))
    return out


def v1_refs(data: Path, bad: list | None = None) -> set[str]:
    """V1 自己 takes.json（data/renders/epNN/SNN/takes.json，含 quarantined）引用的文件；读不了的记进 bad（不静默跳过）"""
    out: set[str] = set()
    for tj in data.glob("renders/ep*/S*/takes.json"):
        try:
            d = json.loads(tj.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            if bad is None:
                raise
            bad.append(f"{tj.relative_to(data).as_posix()}: {e}")
            d = {}
        for t in (d.get("takes") or []) + (d.get("quarantined") or []):
            out |= {f for _, f in take_files(t)}
    return out


def plan(run: str, root: Path = ROOT, producer_mod=None) -> dict:
    PR = producer_mod
    if PR is None:
        import producer as PR  # noqa: N813
    paths = PR.Paths(root=root, run_id=run)
    if paths.primary:
        raise SystemExit(f"{run} 是 legacy（V1）剧，本来就用不带前缀的路径，不迁移")
    roles = PR.run_role_ids(paths)
    v1_bad: list[str] = []
    v1 = v1_refs(paths.data, v1_bad)
    rows, skipped_foreign, seen = [], 0, set()
    for tj in sorted(paths.renders.glob("ep*/S*/takes.json")):
        d = json.loads(tj.read_text(encoding="utf-8"))
        sid = f"{tj.parent.parent.name}-{tj.parent.name}"
        for t in d.get("takes") or []:
            files = [(k, f) for k, f in take_files(t) if _UNPREF.match(f)]
            if not files:
                continue
            why = PR.foreign_reasons(paths, t, roles, {"origin", "role"})
            if why:
                skipped_foreign += 1
                continue
            o = (t.get("params") or {}).get("origin") or {}
            for k, f in files:
                if f in seen:
                    continue
                seen.add(f)
                dst = f"{paths.renders.relative_to(paths.data).as_posix()}/{_UNPREF.match(f).group(1)}"
                rows.append({"shot": sid, "takes_json": tj.relative_to(paths.data).as_posix(), "stage": t.get("stage"), "n": t.get("n"), "field": k, "src": f"data/{f}",
                             "dst": f"data/{dst}", "src_exists": (paths.data / f).is_file(),
                             "dst_exists": (paths.data / dst).exists(), "shared_with_v1": f in v1,
                             "origin": o.get("run") or t.get("workflow"), "created_at": t.get("created_at")})
    return {"run": run, "dry": True, "files": len(rows), "src_missing": sum(not r["src_exists"] for r in rows),
            "dst_conflict": sum(r["dst_exists"] for r in rows), "shared_with_v1": sum(r["shared_with_v1"] for r in rows),
            "takes_skipped_foreign": skipped_foreign,
            "v1_takes_unreadable": v1_bad, "rows": rows}


def _pipeline():
    for sub in ("services/render_router", "services/agent"):
        q = str(ROOT / sub)
        if q not in sys.path:
            sys.path.insert(0, q)
    from ns_render import pipeline as P
    return P


def apply(run: str, root: Path = ROOT, producer_mod=None, mutate=None, ts: str | None = None) -> dict:
    """真搬（只搬不删）。mutate(shot_id, fn, path=…, op=…, by=…) 缺省 = ns_render.pipeline.mutate_takes"""
    root = Path(root)
    pl = plan(run, root, producer_mod)
    data = root / "data"
    if mutate is None:
        mutate = _pipeline().mutate_takes
    ts = ts or time.strftime("%Y%m%d_%H%M%S")
    out_dir = data / "quarantine" / run / f"migrate_{ts}"
    moved, already, conflicts, errors = [], [], [], []
    ok: dict[str, str] = {}                       # 旧 rel（相对 data/） → 新 rel
    for r in pl["rows"]:
        src_rel, dst_rel = r["src"][5:], r["dst"][5:]
        src, dst = data / src_rel, data / dst_rel
        if r["shared_with_v1"]:
            conflicts.append({**r, "why": "shared_with_v1（V1 takes.json 也引用，不搬）"})
            continue
        s_in, d_in = src.is_file(), dst.exists()
        if s_in and d_in:
            conflicts.append({**r, "why": "目标已存在（不覆盖）"})
            continue
        if not s_in and not d_in:
            errors.append({**r, "why": "源和目标都不在"})
            continue
        if s_in:
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dst))
            except OSError as e:
                errors.append({**r, "why": f"move 失败：{e}"})
                continue
            moved.append(r)
        else:
            already.append(r)
        ok[src_rel] = dst_rel
    rewrites = []
    if ok:
        bak_dir = out_dir / "takes_before"
        shots = sorted({(r["shot"], r["takes_json"]) for r in pl["rows"] if r["src"][5:] in ok})
        for sid, tj_rel in shots:
            ep, sh = sid.split("-")
            tj = data / tj_rel
            try:
                bak = bak_dir / ep / sh / "takes.json"
                bak.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(tj, bak)
            except OSError as e:
                errors.append({"shot": sid, "why": f"takes.json 备份失败，不改写：{e}"})
                continue
            changed: list[dict] = []

            def fn(doc, _changed=changed):
                for bucket in ("takes", "quarantined"):
                    for t in doc.get(bucket) or []:
                        for k in FILE_KEYS:
                            v = t.get(k)
                            if not (isinstance(v, str) and v):
                                continue
                            new = ok.get(_norm(v))
                            if new is None:
                                continue
                            t.setdefault(f"{k}_legacy", v)
                            t[k] = new
                            _changed.append({"bucket": bucket, "stage": t.get("stage"), "n": t.get("n"), "field": k,
                                             "old": v, "new": new})
                return doc

            try:
                mutate(sid, fn, path=tj, op="migrate_renders_prefix", by="tools/debug/migrate_renders_prefix.py --apply")
            except Exception as e:  # noqa: BLE001  # arch-ok: 某一镜 takes.json 写不进（锁超时等）记进清单 errors，其余镜照常，重跑可补
                errors.append({"shot": sid, "why": f"takes.json 改写失败：{type(e).__name__}: {e}"})
                continue
            rewrites.append({"shot": sid, "takes_json": tj.relative_to(data).as_posix(), "changes": changed})
    res = {"run": run, "dry": False, "at": ts, "planned": pl["files"], "moved": len(moved), "already_moved": len(already),
           "conflicts": len(conflicts), "errors": len(errors),
           "takes_rewritten": sum(len(x["changes"]) for x in rewrites), "shots_rewritten": len(rewrites),
           "takes_skipped_foreign": pl["takes_skipped_foreign"], "v1_takes_unreadable": pl["v1_takes_unreadable"],
           "moved_rows": moved, "already_rows": already, "conflict_rows": conflicts, "error_rows": errors,
           "rewrites": rewrites}
    if pl["rows"]:
        out_dir.mkdir(parents=True, exist_ok=True)
        tmp = out_dir / "manifest.json.tmp"
        tmp.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(out_dir / "manifest.json")
        res["manifest"] = (out_dir / "manifest.json").relative_to(root).as_posix()
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--dry", action="store_true", help="只列（缺省即 dry）")
    ap.add_argument("--apply", action="store_true", help="真搬（只搬不删；目标已存在不覆盖）")
    ap.add_argument("--json", action="store_true", help="输出全部 rows")
    ap.add_argument("--show", type=int, default=5)
    a = ap.parse_args(argv)
    if a.apply and a.dry:
        print("--apply 和 --dry 只能给一个", file=sys.stderr)
        return 2
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    if a.apply:
        r = apply(a.run)
        print(json.dumps({k: v for k, v in r.items() if not k.endswith("_rows") and k != "rewrites"}, ensure_ascii=False, indent=1))
        return 1 if r["errors"] else 0
    r = plan(a.run)
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return 0
    print(json.dumps({k: v for k, v in r.items() if k != "rows"}, ensure_ascii=False, indent=1))
    for x in r["rows"][: a.show]:
        print(json.dumps(x, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
