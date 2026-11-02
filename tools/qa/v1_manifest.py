"""V1 视频库冻结清单（总调度 fredw-2b 11-02 18:4x；项目方 18:2x：停止渲染，现有成果打包成 Version 1，V2 从头重做，L-125）。

原地整树冻结：不搬、不删、不改 takes.json，只写 data/library/v1/MANIFEST.json。
每个版本打标签：
  good：current（当前版 / 定稿 / 被留下版本引用 / 成片引用 / 项目方点过 / --keep-file 保留集）| passed（通过契约的历史版）
  bad ：pre_reimport_old_script / bad_or_rejected_superseded / contract_fail_superseded / over_hard_cap / quarantined
  unknown：契约结果缺失或还在打分
每镜写“V1 正本版本”（canon）：定稿 locked_src / locked 优先，其次 active；--w27 给的判定表（K-OPS-W27，ep02/04/06 两台重复出图）覆盖：
  canon 记成判定采用的那台的文件（use=gpu36 / gpu33；④ 两台都没过则记 none）。孤儿文件（takes/ 下没有记录引用）列为 bad/orphan_file。
判据和 tools/qa/audit_quarantine.py 共用（keep_of / is_old），服务器用笔记本保留集交叉核对。

  python -X utf8 tools/qa/v1_manifest.py [--keep-file K.json] [--w27 dup_decisions.json] [--host laptop|gpu33|gpu36] [--dry]
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(os.environ.get("NS_ROOT") or (Path(__file__).resolve().parents[2] if "__file__" in globals() else os.getcwd())).resolve()
sys.path.insert(0, str(ROOT / "tools/qa"))
os.environ.setdefault("NS_ROOT", str(ROOT))
import audit_quarantine as AQ  # noqa: E402

DATA = ROOT / "data"
OUT = DATA / "library/v1/MANIFEST.json"


def label_take(t: dict, keep: set, asm: set, per_stage_idx: int) -> tuple[str, str]:
    st, n = t["stage"], t["n"]
    f = str(t.get("file") or "")
    p = DATA / f
    pf = t.get("postflight") or ((t.get("contract") or {}).get("postflight")) or {}
    if (st, n) in keep or f in asm:
        return "good", "current"
    if t.get("quarantined"):
        return "bad", "quarantined"
    if f and p.is_file() and AQ.is_old(t, p):
        return "bad", "pre_reimport_old_script"
    if t.get("bad") or t.get("master_reject"):
        return "bad", "bad_or_rejected_superseded"
    if pf.get("ok") is False:
        return "bad", "contract_fail_superseded"
    if per_stage_idx > AQ.HARD_CAP and pf.get("ok") is not True:
        return "bad", "over_hard_cap"
    if pf.get("ok") is True:
        return "good", "passed"
    return "unknown", "no_contract_result"


def canon_of(d: dict) -> dict:
    out = {}
    for st in ("image", "last", "video"):
        n = None
        v = (d.get("locked_src") or {}).get(st)
        if isinstance(v, dict) and v.get("n") is not None:
            n, src = int(v["n"]), "locked_src"
        elif isinstance((d.get("locked") or {}).get(st), int):
            n, src = d["locked"][st], "locked"
        elif (d.get("active") or {}).get(st) is not None:
            n, src = int(d["active"][st]), "active"
        if n is None:
            continue
        t = next((x for x in d.get("takes") or [] if x.get("stage") == st and x.get("n") == n), None)
        out[st] = {"n": n, "file": (t or {}).get("file"), "source": src,
                   "exists": bool(t and t.get("file") and (DATA / t["file"]).is_file())}
    return out


def build(host: str, extra_keep: dict, w27: list, run: str) -> dict:
    valid = AQ.valid_shots()
    owner = AQ.owner_touch()
    asm = AQ.assembly_refs()
    w = collections.defaultdict(dict)
    for x in w27 or []:
        w[x["shot"]][x["stage"]] = x
    shots, tot = {}, collections.Counter()
    for epd in sorted((DATA / "renders").glob("ep*")):
        for shd in sorted(epd.glob("S*")):
            sid = f"{epd.name}-{shd.name}"
            tj = shd / "takes.json"
            if sid not in valid:
                shots[sid] = {"in_script": False, "label": "bad", "why": "orphan_shot_dir（现行剧本没有这一镜）"}
                tot["orphan_shot_dir"] += 1
                continue
            if not tj.exists():
                shots[sid] = {"in_script": True, "takes": [], "canon": {}}
                continue
            d = json.loads(tj.read_text(encoding="utf-8"))
            keep, keep_files = AQ.keep_of(sid, d, owner, extra_keep)
            per = collections.Counter()
            rows, refd = [], set()
            for t in sorted(d.get("takes") or [], key=lambda x: x["n"]):
                per[t["stage"]] += 1
                lab, why = label_take(t, keep, asm, per[t["stage"]])
                tot[f"{lab}:{why}"] += 1
                f = t.get("file")
                rows.append({"stage": t["stage"], "n": t["n"], "file": f, "raw_file": t.get("raw_file"),
                             "exists": bool(f and (DATA / f).is_file()), "label": lab, "why": why,
                             "created_at": t.get("created_at"), "lane": (t.get("producer") or {}).get("lane")})
                for k in ("file", "raw_file", "reference"):
                    if t.get(k):
                        refd.add(str(t[k]).replace("\\", "/").split("data/", 1)[-1])
                for r in t.get("references") or []:
                    refd.add(str(r).replace("\\", "/").split("data/", 1)[-1])
            orphans = []
            td = shd / "takes"
            if td.is_dir():
                for p in sorted(td.iterdir()):
                    rel = p.relative_to(DATA).as_posix()
                    if p.is_file() and rel not in refd and rel not in keep_files:
                        orphans.append(rel)
            tot["bad:orphan_file"] += len(orphans)
            canon = canon_of(d)
            for st, x in w.get(sid, {}).items():
                use = x.get("use")
                f = x.get("file36") if use == "gpu36" else x.get("file33") if use == "gpu33" else None
                canon[st] = {"n": x.get("n36") if use == "gpu36" else x.get("n33") if use == "gpu33" else None,
                             "file": f, "source": f"K-OPS-W27 规则{x.get('rule')} use={use}",
                             "host_numbering": use, "exists": bool(f and (DATA / f).is_file()),
                             "local_active_differs": (canon.get(st) or {}).get("file") not in (None, f)}
                tot["w27_override"] += 1
            shots[sid] = {"in_script": True, "canon": canon, "takes": rows, "orphan_files": orphans,
                          "seq": d.get("seq")}
    return {"version": "V1", "run": run, "frozen_at": AQ.now_iso(), "host": host, "root": str(ROOT),
            "by": "AUDIT-M（总调度 18:4x：原地整树冻结，不搬不删不改 takes.json）",
            "rule": "good = current（当前 / 定稿 / 被引用 / 成片引用 / 项目方点过 / 笔记本保留集）| passed（过契约）；"
                    "bad = 旧剧本 / 驳回 / 契约没过 / 超上限 / 已隔离 / 孤儿；unknown = 没有契约结果。"
                    "canon = 定稿 > 当前；ep02/04/06 以 K-OPS-W27 判定表为准（冻结时以本清单为准，不改 takes.json）",
            "cross_checked_with_laptop_keepset": bool(extra_keep), "w27_rows": len(w27 or []),
            "totals": dict(tot), "shots": shots}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep-file")
    ap.add_argument("--w27")
    ap.add_argument("--host", default="laptop")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--run", help="冻结的 run；默认读 config/pipeline/runs.json 的 primary")
    a = ap.parse_args()
    ek = json.loads(Path(a.keep_file).read_text(encoding="utf-8")) if a.keep_file else {}
    w27 = json.loads(Path(a.w27).read_text(encoding="utf-8")) if a.w27 else []
    run = a.run or json.loads((ROOT / "config/pipeline/runs.json").read_text(encoding="utf-8"))["primary"]
    m = build(a.host, ek, w27, run)
    if not a.dry:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        AQ.atomic_json(OUT, m)
    canon_n = sum(len(v.get("canon") or {}) for v in m["shots"].values())
    missing = sum(1 for v in m["shots"].values() for c in (v.get("canon") or {}).values() if not c.get("exists"))
    print(json.dumps({"host": a.host, "out": None if a.dry else str(OUT), "shots": len(m["shots"]), "canon": canon_n,
                      "canon_file_missing_here": missing, "totals": m["totals"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
