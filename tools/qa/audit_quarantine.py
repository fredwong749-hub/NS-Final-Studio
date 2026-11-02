"""AUDIT-M 旧数据隔离（总调度 fredw-2b 11-02 17:1x 批准：renders 里的候选类别全部批准，另加仓库根 *_take/ 目录、
11-01 23:20 之前的任务记录；_offline_pull / outbox 暂缓）。只移动、不删除，可还原。笔记本和服务器跑同一份脚本。

判据（执行时现场重判，不信预览快照）：
  留下：当前版 active、定稿 locked / locked_src、被留下的视频 / 尾帧引用的首帧、成片时间线引用的、项目方点过的
        （审计日志 role=owner 的 activate / lock / regen）、--keep-file 给的保留集（服务器用笔记本的保留集交叉核对）、
        通过契约的历史版、最近 --recent-h 小时内出的版本（可能还在打分）
  隔离：pre_reimport_old_script（11-01 23:20 剧本逐集重导之前）、bad_or_rejected_superseded、contract_fail_superseded、
        over_hard_cap（该阶段第 11 版起且没通过契约）、quarantined_record_file_still_present（记录已标隔离、文件还在）、
        orphan_file（takes/ 下没有任何记录引用的文件；和留下版本同号的不动）、orphan_shot_dir（剧本里没有的镜目录）、
        takes_tmp_residue（takes.json.* 残留，.lock 除外）
takes.json 只经 tools/pipeline/takes_cli.py（get → 局部加 quarantined → replace --expect-seq，冲突重试）；先标记、后移文件。

  python -X utf8 tools/qa/audit_quarantine.py plan  [--keep-file K.json] [--out PLAN.json]
  python -X utf8 tools/qa/audit_quarantine.py apply [--keep-file K.json] [--dry]
  python -X utf8 tools/qa/audit_quarantine.py keepset --out K.json          # 笔记本：导出保留集给服务器交叉核对
  python -X utf8 tools/qa/audit_quarantine.py extra --root-takes --jobs-before 2026-11-01T23:20 [--dry]   # 笔记本：仓库根脏目录 + 旧任务记录
  python -X utf8 tools/qa/audit_quarantine.py restore [--src data/...]     # 按 moves.jsonl 移回（不给 --src 就全部）+ 撤本工具加的标记
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(os.environ.get("NS_ROOT") or (Path(__file__).resolve().parents[2] if "__file__" in globals() else os.getcwd())).resolve()
DATA = ROOT / "data"
QREL = "data/_quarantine_20261102_audit"
QDIR = ROOT / QREL
BY = "AUDIT-M 11-02（旧数据隔离，总调度 17:1x 批准）"
REIMPORT = "2026-11-01T23:20"
HARD_CAP = 10
CATS = ("pre_reimport_old_script", "bad_or_rejected_superseded", "contract_fail_superseded", "over_hard_cap",
        "quarantined_record_file_still_present")
TZ = dt.timezone(dt.timedelta(hours=9))


def warn(msg: str) -> None:
    sys.stderr.write(f"[audit_quarantine] {msg}\n")


def atomic_json(p: Path, obj) -> None:
    tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=0), encoding="utf-8")
    os.replace(tmp, p)


def now_iso() -> str:
    return dt.datetime.now(TZ).isoformat(timespec="seconds")


def valid_shots() -> set:
    s = json.loads((DATA / "import/script_v2.json").read_text(encoding="utf-8"))
    out = set()
    for i, ep in enumerate(s["episodes"]):
        n = ep.get("number") or i + 1
        for j, sh in enumerate(ep["shots"]):
            out.add(f"ep{int(n):02d}-S{sh.get('index') or j + 1}")
    return out


def owner_touch() -> dict:
    out = collections.defaultdict(set)
    for f in glob.glob(str(DATA / "audit/*.jsonl")):
        for ln in open(f, encoding="utf-8", errors="replace"):
            if '"owner"' not in ln:
                continue
            try:
                d = json.loads(ln)
            except ValueError:
                if "/api/shots/" in ln:      # 可能是项目方点选记录读坏了：漏判会误隔离 → 整体中止（失败关闭）
                    raise RuntimeError(f"审计日志 {f} 有读不出的点选记录，中止隔离：{ln[:120]}")
                warn(f"审计日志 {f} 跳过一行无关的坏行")
                continue
            m = re.match(r"/api/shots/(ep\d+-S\d+)/takes/(image|last|video)/(\d+)/(activate|lock|regen)", d.get("path", ""))
            if d.get("role") == "owner" and m:
                out[m.group(1)].add((m.group(2), int(m.group(3))))
    return out


def assembly_refs() -> set:
    refs = set()
    for f in glob.glob(str(DATA / "episodes/**/*.json"), recursive=True):
        txt = open(f, encoding="utf-8", errors="replace").read()   # 读不到就抛错中止：漏掉成片引用会误隔离（失败关闭）
        refs.update(m.group(0) for m in re.finditer(r"renders/ep\d+/S\d+/takes/[^\"'\s]+", txt))
    return refs


def _ts(s) -> str:
    """created_at → +09:00 本地串。带时区的换算；不带时区的原样（服务器上其他进程写的是 EST 串，会偏早 14 小时）"""
    s = str(s or "")
    try:
        d = dt.datetime.fromisoformat(s)
        if d.tzinfo:
            return d.astimezone(TZ).strftime("%Y-%m-%dT%H:%M:%S")
    except ValueError:
        pass
    return s[:19]


REIMPORT_EPOCH = dt.datetime.fromisoformat(REIMPORT + ":00+09:00").timestamp()


def is_old(t: dict, p: Path) -> bool:
    """重导前的旧版：created_at 早于分界，且文件 mtime 也早于分界（两者都要满足——防服务器不带时区的 EST 串误判）"""
    if not p.is_file():
        return False                 # 文件不在 → 不判旧（保留，失败关闭）
    return _ts(t.get("created_at")) < REIMPORT and p.stat().st_mtime < REIMPORT_EPOCH


def keep_of(sid: str, d: dict, owner: dict, extra_keep: dict) -> tuple[set, set]:
    """→ (留下的 (stage, n)，留下的文件 rel)"""
    takes = d.get("takes") or []
    keep = {(st, int(n)) for st, n in (d.get("active") or {}).items() if n is not None}
    for st, v in (d.get("locked_src") or {}).items():
        if isinstance(v, dict) and v.get("n") is not None:
            keep.add((v.get("stage", st), int(v["n"])))
    for st, v in (d.get("locked") or {}).items():
        if isinstance(v, int):
            keep.add((st, v))
        elif isinstance(v, dict) and v.get("n") is not None:
            keep.add((st, int(v["n"])))
    keep |= owner.get(sid, set())
    ek = extra_keep.get(sid) or {}
    keep |= {(a, int(b)) for a, b in ek.get("n", [])}
    keep_files = set(ek.get("files", []))
    for t in takes:
        if t.get("locked"):
            keep.add((t["stage"], t["n"]))
        if t.get("file") in keep_files or Path(str(t.get("file") or "")).name in {Path(x).name for x in keep_files}:
            keep.add((t["stage"], t["n"]))
    for _ in range(2):
        for t in takes:
            if (t["stage"], t["n"]) not in keep:
                continue
            if t["stage"] == "video" and t.get("from_first"):
                keep.add(("image", int(t["from_first"])))
            for r in [t.get("reference")] + list(t.get("references") or []):
                if r and "/takes/" in str(r):
                    rr = str(r).replace("\\", "/").split("data/", 1)[-1]
                    for t2 in takes:
                        if t2.get("file") == rr:
                            keep.add((t2["stage"], t2["n"]))
    files = set()
    for t in takes:
        if (t["stage"], t["n"]) in keep:
            for k in ("file", "raw_file"):
                if t.get(k):
                    files.add(str(t[k]).replace("\\", "/"))
    return keep, files


def classify(extra_keep: dict, recent_h: float) -> dict:
    valid = valid_shots()
    owner = owner_touch()
    asm = assembly_refs()
    cutoff = time.time() - recent_h * 3600
    plan = {"takes": [], "orphans": [], "shot_dirs": [], "residue": [], "keep": collections.Counter()}
    for epd in sorted((DATA / "renders").glob("ep*")):
        for shd in sorted(epd.glob("S*")):
            sid = f"{epd.name}-{shd.name}"
            tj = shd / "takes.json"
            if sid not in valid:
                if not tj.exists() or not (json.loads(tj.read_text(encoding="utf-8")).get("takes")):
                    plan["shot_dirs"].append(shd.relative_to(ROOT).as_posix())
                continue
            for p in shd.glob("takes.json.*"):
                if not p.name.endswith(".lock") and p.stat().st_mtime < cutoff:
                    plan["residue"].append(p.relative_to(ROOT).as_posix())
            if not tj.exists():
                continue
            d = json.loads(tj.read_text(encoding="utf-8"))
            takes = d.get("takes") or []
            keep, keep_files = keep_of(sid, d, owner, extra_keep)
            per_stage = collections.Counter()
            refd = set()
            for t in takes:
                for k in ("file", "raw_file", "reference"):
                    if t.get(k):
                        refd.add(str(t[k]).replace("\\", "/").split("data/", 1)[-1])
                for r in t.get("references") or []:
                    refd.add(str(r).replace("\\", "/").split("data/", 1)[-1])
            for t in sorted(takes, key=lambda x: x["n"]):
                st, n = t["stage"], t["n"]
                per_stage[st] += 1
                f = str(t.get("file") or "")
                p = DATA / f
                exists = bool(f) and p.is_file()
                if (st, n) in keep or f in asm:
                    plan["keep"]["keep_rule"] += 1
                    continue
                if exists and p.stat().st_mtime > cutoff:
                    plan["keep"]["recent"] += 1
                    continue
                pf = t.get("postflight") or {}
                if t.get("quarantined"):
                    if not exists:
                        plan["keep"]["already_quarantined"] += 1
                        continue
                    cat = "quarantined_record_file_still_present"
                elif not exists:
                    plan["keep"]["record_no_file"] += 1
                    continue
                elif is_old(t, p):
                    cat = "pre_reimport_old_script"
                elif t.get("bad") or t.get("master_reject"):
                    cat = "bad_or_rejected_superseded"
                elif pf.get("ok") is False:
                    cat = "contract_fail_superseded"
                elif per_stage[st] > HARD_CAP and pf.get("ok") is not True:
                    cat = "over_hard_cap"
                else:
                    plan["keep"]["passing_or_pending"] += 1
                    continue
                files = [x for x in (f, t.get("raw_file")) if x and (DATA / x).is_file() and x not in keep_files]
                plan["takes"].append({"sid": sid, "stage": st, "n": n, "cat": cat, "files": ["data/" + x for x in files]})
            kept_n = {(st, n) for st, n in keep}
            td = shd / "takes"
            if td.is_dir():
                for p in td.iterdir():
                    rel = p.relative_to(DATA).as_posix()
                    if not p.is_file() or rel in refd or rel in keep_files or p.stat().st_mtime > cutoff:
                        continue
                    if rel in set((extra_keep.get(sid) or {}).get("refs") or []):
                        plan["keep"]["orphan_but_laptop_has_record"] += 1      # 服务器上没记录、笔记本有记录：不当孤儿
                        continue
                    m = re.match(r"(image|last|video|compose)_(\d+)", p.name)
                    if m and ({"compose": "image"}.get(m.group(1), m.group(1)), int(m.group(2))) in kept_n:
                        plan["keep"]["orphan_sibling_of_kept"] += 1
                        continue
                    plan["orphans"].append("data/" + rel)
    plan["keep"] = dict(plan["keep"])
    return plan


def size_of(p: Path) -> int:
    if p.is_file():
        return p.stat().st_size
    return sum(x.stat().st_size for x in p.rglob("*") if x.is_file())


def move(rel: str, cat: str, reason: str, dry: bool) -> int:
    src = ROOT / rel
    if not src.exists():
        return 0
    dst = QDIR / rel
    b = size_of(src)
    if dry:
        return b
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        dst = dst.with_name(dst.name + f".dup{int(time.time())}")
    shutil.move(str(src), str(dst))
    QDIR.mkdir(parents=True, exist_ok=True)
    with open(QDIR / "moves.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"at": now_iso(), "by": BY, "cat": cat, "src": rel, "dst": dst.relative_to(ROOT).as_posix(),
                             "bytes": b, "reason": reason}, ensure_ascii=False) + "\n")
    return b


def takes_cli(args: list, stdin: bytes | None = None) -> tuple[int, dict]:
    r = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "tools/pipeline/takes_cli.py"), *args], cwd=ROOT,
                       input=stdin, capture_output=True, timeout=300)
    lines = r.stdout.decode("utf-8", "replace").strip().splitlines()
    if not lines or not lines[-1].startswith("{"):
        warn(f"takes_cli {args[:3]} 没有 JSON 输出 rc={r.returncode}：{r.stderr.decode('utf-8', 'replace')[-200:]}")
        return 99, {}                # 调用方见 rc != 0 一律不动这一镜（失败关闭）
    return r.returncode, json.loads(lines[-1])


def mark_shot(sid: str, items: list, dry: bool) -> list:
    """一镜的待隔离版本局部加 quarantined（现场再核：已变成当前 / 定稿的跳过）。→ 实际标记成功的 items"""
    want = {(i["stage"], i["n"]): i for i in items}
    for _try in range(5):
        rc, out = takes_cli(["get", "--sid", sid])
        if rc != 0:
            return []
        seq, doc = out["seq"], out["doc"]
        keep, _ = keep_of(sid, doc, {}, {})
        done = []
        for t in doc.get("takes") or []:
            it = want.get((t["stage"], t["n"]))
            if not it or (t["stage"], t["n"]) in keep:
                continue
            if t.get("quarantined"):
                q = dict(t["quarantined"]) if isinstance(t["quarantined"], dict) else {"was": t["quarantined"]}
                q["audit_moved_to"] = {f: f"{QREL}/{f}" for f in it["files"]}
                q["audit_by"] = BY
                t["quarantined"] = q
            else:
                t["quarantined"] = {"at": now_iso(), "by": BY, "reason": it["cat"],
                                    "moved_to": {"file": f"{QREL}/{it['files'][0]}"} if it["files"] else {},
                                    "files": [f"{QREL}/{f}" for f in it["files"]], "was_active": False}
            done.append(it)
        if not done or dry:
            return done
        rc, res = takes_cli(["replace", "--sid", sid, "--op", "audit_quarantine", "--by", "AUDIT-M", "--expect-seq", str(seq)],
                            json.dumps(doc, ensure_ascii=False).encode("utf-8"))
        if rc == 0:
            return done
        if rc != 3:
            time.sleep(3)
        time.sleep(1)
    return []


def apply(extra_keep: dict, recent_h: float, dry: bool) -> dict:
    plan = classify(extra_keep, recent_h)
    stat = collections.Counter()
    byt = collections.Counter()
    by_sid = collections.defaultdict(list)
    for it in plan["takes"]:
        by_sid[it["sid"]].append(it)
    for sid, items in sorted(by_sid.items()):
        done = mark_shot(sid, items, dry)
        stat["mark_fail"] += len(items) - len(done)
        for it in done:
            stat[it["cat"]] += 1
            for f in it["files"]:
                byt[it["cat"]] += move(f, it["cat"], f"{sid} {it['stage']} v{it['n']}", dry)
    for rel in plan["orphans"]:
        stat["orphan_file"] += 1
        byt["orphan_file"] += move(rel, "orphan_file", "takes/ 下没有任何记录引用", dry)
    for rel in plan["shot_dirs"]:
        stat["orphan_shot_dir"] += 1
        byt["orphan_shot_dir"] += move(rel, "orphan_shot_dir", "现行剧本没有这一镜", dry)
    for rel in plan["residue"]:
        stat["takes_tmp_residue"] += 1
        byt["takes_tmp_residue"] += move(rel, "takes_tmp_residue", "takes.json 临时 / 备份残留", dry)
    if not dry:
        write_manifest()
    return {"dry": dry, "count": dict(stat), "MB": {k: round(v / 2**20, 1) for k, v in byt.items()},
            "total_MB": round(sum(byt.values()) / 2**20, 1), "keep": plan["keep"]}


def apply_items(items: list, dry: bool) -> dict:
    """指定版本隔离（例：总调度 17:3x gpu33 上 ep02/04/06 16:30 后重复出的版本，正本在 gpu36）。
    文件从本机 takes 记录现取；mark_shot 现场再核本机当前 / 定稿 / 被留下版本引用的一律跳过"""
    stat, byt = collections.Counter(), collections.Counter()
    by_sid = collections.defaultdict(list)
    for it in items:
        by_sid[it["sid"]].append(it)
    for sid, its in sorted(by_sid.items()):
        rc, out = takes_cli(["get", "--sid", sid])
        if rc != 0:
            stat["get_fail"] += len(its)
            continue
        recs = {(t["stage"], t["n"]): t for t in out["doc"].get("takes") or []}
        full = []
        for it in its:
            t = recs.get((it["stage"], int(it["n"])))
            if not t:
                stat["no_record"] += 1
                continue
            fs = [x for x in (t.get("file"), t.get("raw_file")) if x and (DATA / x).is_file()]
            full.append({**it, "n": int(it["n"]), "files": ["data/" + x for x in fs]})
        done = mark_shot(sid, full, dry)
        stat["skipped_now_kept"] += len(full) - len(done)
        for it in done:
            stat[it["cat"]] += 1
            for f in it["files"]:
                byt[it["cat"]] += move(f, it["cat"], f"{sid} {it['stage']} v{it['n']}", dry)
    if not dry:
        write_manifest()
    return {"dry": dry, "count": dict(stat), "MB": {k: round(v / 2**20, 1) for k, v in byt.items()}}


def extra(root_takes: bool, jobs_before: str | None, dry: bool) -> dict:
    stat = collections.Counter()
    byt = collections.Counter()
    if root_takes:
        for p in sorted(ROOT.glob("2026110*_take")):
            stat["root_take_dir"] += 1
            byt["root_take_dir"] += move(p.relative_to(ROOT).as_posix(), "root_take_dir",
                                         "merge_pull.main 把 puller 暂存写到仓库根（根因已修 A-11）", dry)
    if jobs_before:
        for f in sorted((DATA / "jobs/v1").glob("*.json")):
            raw = f.read_text(encoding="utf-8")
            if not raw.strip().startswith("{"):
                warn(f"任务记录 {f.name} 读不出，保留不动")
                continue
            j = json.loads(raw)
            if str(j.get("created_at") or "") < jobs_before and j.get("state") in ("done", "failed", "cancelled"):
                stat["old_job_record"] += 1
                byt["old_job_record"] += move(f.relative_to(ROOT).as_posix(), "old_job_record",
                                              f"渲染任务记录早于 {jobs_before}（剧本重导前）", dry)
    if not dry:
        write_manifest()
    return {"dry": dry, "count": dict(stat), "MB": {k: round(v / 2**20, 2) for k, v in byt.items()}}


def write_manifest() -> None:
    mv = QDIR / "moves.jsonl"
    if not mv.exists():
        return
    rows = [json.loads(x) for x in mv.read_text(encoding="utf-8").splitlines() if x.strip()]
    c = collections.Counter(r["cat"] for r in rows)
    b = collections.Counter()
    for r in rows:
        b[r["cat"]] += r.get("bytes", 0)
    lines = [f"# 隔离区 {QREL}（{BY}）", "",
             "只移动、不删除。还原：`python -X utf8 tools/qa/audit_quarantine.py restore [--src <原路径>]`（按 moves.jsonl 移回，并撤掉本工具加的 quarantined 标记）。",
             "删除只能由项目方本人下令，并先跑 tools/qa/purge_precheck.py。", "",
             "| 类别 | 项数 | 体积 MB |", "|---|---|---|"]
    lines += [f"| {k} | {c[k]} | {b[k] / 2**20:.1f} |" for k in sorted(c)]
    lines += ["", f"合计 {len(rows)} 项，{sum(b.values()) / 2**20:.1f} MB。逐项见 moves.jsonl。"]
    tmp = QDIR / "MANIFEST.md.tmp"
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(tmp, QDIR / "MANIFEST.md")


def restore(src: str | None) -> dict:
    mv = QDIR / "moves.jsonl"
    rows = [json.loads(x) for x in mv.read_text(encoding="utf-8").splitlines() if x.strip()] if mv.exists() else []
    back = 0
    sids = set()
    for r in rows:
        if src and r["src"] != src:
            continue
        d, s = ROOT / r["dst"], ROOT / r["src"]
        if d.exists() and not s.exists():
            s.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(d), str(s))
            back += 1
        m = re.search(r"renders/(ep\d+)/(S\d+)/", r["src"])
        if m:
            sids.add(f"{m.group(1)}-{m.group(2)}")
    unmarked = 0
    for sid in sorted(sids):
        rc, out = takes_cli(["get", "--sid", sid])
        if rc != 0:
            continue
        doc, hit = out["doc"], False
        for t in doc.get("takes") or []:
            q = t.get("quarantined")
            if not isinstance(q, dict):
                continue
            fs = list(q.get("files") or []) + list((q.get("audit_moved_to") or {}).values())
            if src and not any(x.endswith(src) for x in fs):
                continue
            if q.get("by") == BY:
                t["quarantined"] = None
                hit = True
                unmarked += 1
            elif q.get("audit_by") == BY:
                q.pop("audit_by", None)
                q.pop("audit_moved_to", None)
                hit = True
                unmarked += 1
        if hit:
            takes_cli(["replace", "--sid", sid, "--op", "audit_quarantine_restore", "--by", "AUDIT-M", "--expect-seq", str(out["seq"])],
                      json.dumps(doc, ensure_ascii=False).encode("utf-8"))
    return {"moved_back": back, "unmarked": unmarked}


def keepset() -> dict:
    owner = owner_touch()
    out = {}
    for tj in sorted((DATA / "renders").glob("ep*/S*/takes.json")):
        sid = "-".join(tj.parent.parts[-2:])
        d = json.loads(tj.read_text(encoding="utf-8"))
        keep, files = keep_of(sid, d, owner, {})
        refs = sorted({str(t.get(k)).replace("\\", "/") for t in d.get("takes") or [] for k in ("file", "raw_file") if t.get(k)})
        out[sid] = {"n": sorted([list(x) for x in keep]), "files": sorted(files), "refs": refs}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["plan", "apply", "keepset", "extra", "restore", "items"])
    ap.add_argument("--keep-file")
    ap.add_argument("--out")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--recent-h", type=float, default=2.0)
    ap.add_argument("--root-takes", action="store_true")
    ap.add_argument("--jobs-before")
    ap.add_argument("--src")
    ap.add_argument("--items", help="items：[{sid, stage, n, cat}] 指定版本隔离（现场再核：本机当前 / 定稿 / 被引用的跳过）")
    a = ap.parse_args()
    ek = json.loads(Path(a.keep_file).read_text(encoding="utf-8")) if a.keep_file else {}
    if a.cmd == "plan":
        p = classify(ek, a.recent_h)
        if a.out:
            atomic_json(Path(a.out), p)
        c = collections.Counter(i["cat"] for i in p["takes"])
        res = {"takes": dict(c), "orphan_file": len(p["orphans"]), "orphan_shot_dir": len(p["shot_dirs"]),
               "takes_tmp_residue": len(p["residue"]), "keep": p["keep"]}
    elif a.cmd == "apply":
        res = apply(ek, a.recent_h, a.dry)
    elif a.cmd == "keepset":
        res = keepset()
        atomic_json(Path(a.out), res)
        res = {"shots": len(res), "out": a.out}
    elif a.cmd == "extra":
        res = extra(a.root_takes, a.jobs_before, a.dry)
    elif a.cmd == "items":
        res = apply_items(json.loads(Path(a.items).read_text(encoding="utf-8")), a.dry)
    else:
        res = restore(a.src)
    sys.stdout.buffer.write((json.dumps(res, ensure_ascii=False) + "\n").encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
