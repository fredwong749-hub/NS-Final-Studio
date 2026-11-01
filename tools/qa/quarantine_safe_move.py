"""先查引用、再移进隔离区（K-OPS-Q30；CLEANUP 2026-11-01，项目方 18:3x：“把旧的东西全部移出”）。只移动，不删除。

    .venv/Scripts/python.exe -X utf8 tools/qa/quarantine_safe_move.py PLAN.json [--qdir data/_quarantine_20261101b] [--dry]
    .venv/Scripts/python.exe -X utf8 tools/qa/quarantine_safe_move.py --manifest [--qdir ...]      # 只重写 MANIFEST.md
    .venv/Scripts/python.exe -X utf8 tools/qa/quarantine_safe_move.py --restore SRC [--qdir ...]   # 把一项移回原处

PLAN.json = [{"cat": "...", "src": "相对项目根或绝对路径", "reason": "为什么算旧",
              "ref_override": "可选：有引用但引用方不是读取者时写明理由（例：只有 README 里一句“不要用”）"}]
每一项先跑 tools/qa/quarantine_refcheck.check()：生产代码 / 测试 / 前端 / 配置 / 运维有引用、又没写 ref_override 的 → 不移（status=kept_referenced）。
目标路径 = <qdir>/<相对项目根的原路径>；每项追加一行到 <qdir>/moves.jsonl（含引用检查结果），MANIFEST.md 由它生成。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import quarantine_refcheck as RC  # noqa: E402

DEFAULT_Q = "data/_quarantine_20261101b"


def size_of(p: Path) -> int:
    if p.is_file():
        return p.stat().st_size
    total = 0
    for dp, _, fs in os.walk(p):
        for f in fs:
            try:
                total += (Path(dp) / f).stat().st_size
            except OSError:
                pass
    return total


def human(n: float) -> str:
    for u in ("B", "K", "M", "G"):
        if n < 1024:
            return f"{n:.0f}{u}" if u == "B" else f"{n:.1f}{u}"
        n /= 1024
    return f"{n:.1f}T"


def move_one(it: dict, q: Path, dry: bool = False) -> dict:
    src = Path(it["src"])
    if not src.is_absolute():
        src = ROOT / src
    rel = src.resolve().relative_to(ROOT).as_posix()
    rec = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "cat": it.get("cat", "misc"), "src": rel, "reason": it["reason"], "host": "laptop"}
    if not src.exists():
        rec["status"] = "missing"
        return rec
    rc = RC.check(src)
    rec["code_refs"] = rc["code_refs"][:10]
    rec["doc_ref_count"] = rc["doc_ref_count"]
    if rc["referenced"] and not it.get("ref_override"):
        rec["status"] = "kept_referenced"
        return rec
    if it.get("ref_override"):
        rec["ref_override"] = it["ref_override"]
    dst = q / rel
    rec["dst"] = dst.relative_to(ROOT).as_posix()
    rec["bytes"] = size_of(src)
    if dry:
        rec["status"] = "would_move"
        return rec
    try:
        if dst.exists():
            raise FileExistsError(str(dst))
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        rec["status"] = "moved"
    except Exception as e:  # noqa: BLE001 - 记录失败继续
        rec.update(status="failed", error=repr(e))
    return rec


def restore(rel: str, q: Path) -> str:
    rel = Path(rel).as_posix()
    dst, src = ROOT / rel, q / rel
    if dst.exists():
        return f"原处已有同名文件，未恢复：{rel}"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    with (q / "moves.jsonl").open("a", encoding="utf-8") as w:
        w.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "src": rel, "status": "restored"}, ensure_ascii=False) + "\n")
    return f"已恢复 {rel}"


def manifest(q: Path) -> Path:
    rows = [json.loads(ln) for ln in (q / "moves.jsonl").read_text(encoding="utf-8").splitlines() if ln.strip()]
    restored = {r["src"] for r in rows if r.get("status") == "restored"}
    moved = [r for r in rows if r.get("status") == "moved" and r["src"] not in restored]
    moved_src = {r["src"] for r in moved}
    kept = [r for r in rows if r.get("status") == "kept_referenced" and r["src"] not in moved_src]
    qrel = q.relative_to(ROOT).as_posix()
    out = [f"# 隔离区清单（{qrel}）", "",
           "> CLEANUP 2026-11-01（总调度 fredw-2b 派）。项目方 11-01 18:3x：“把旧的东西全部移出，因为我很怕你的记忆里面混入太多旧的素材了。”"
           "旧决定 L-079：“先隔离，验证后你删”——只移动、不删除；最终删除只能由项目方本人运行 `ops/cleanup/delete_quarantine_20261101b.ps1`。",
           "> 每一项移动前都跑了引用检查 `tools/qa/quarantine_refcheck.py`（K-OPS-Q30）：生产代码 / 测试 / 前端 / 配置 / 运维有引用的不移。",
           f"> 恢复一项：`.venv/Scripts/python.exe -X utf8 tools/qa/quarantine_safe_move.py --restore <原路径>`（或手工把 `{qrel}/<原路径>` 移回 `<原路径>`）。", "",
           "| # | 类别 | 原路径 | 大小 | 原因 | 引用检查 |", "|---|---|---|---|---|---|"]
    tot, cnt = defaultdict(int), defaultdict(int)
    for i, r in enumerate(moved, 1):
        b = int(r.get("bytes") or 0)
        tot[r["cat"]] += b
        cnt[r["cat"]] += 1
        refs = "无代码引用" if not r.get("code_refs") else f"仅非读取引用：{r.get('ref_override', '')}"
        refs += f"；文档提及 {r.get('doc_ref_count', 0)} 处"
        out.append(f"| {i} | {r['cat']} | `{r['src']}` | {human(b)} | {r['reason']} | {refs} |")
    out += ["", "## 汇总", "", "| 类别 | 项数 | 大小 |", "|---|---|---|"]
    for c in sorted(cnt):
        out.append(f"| {c} | {cnt[c]} | {human(tot[c])} |")
    out.append(f"| **合计** | {sum(cnt.values())} | **{human(sum(tot.values()))}** |")
    if kept:
        out += ["", "## 有引用、没有移动的候选", "", "| 原路径 | 原因 | 引用方（前 2 条） |", "|---|---|---|"]
        seen = set()
        for r in kept:
            if r["src"] in seen:
                continue
            seen.add(r["src"])
            refs = "；".join(x[:90].replace("|", "/") for x in (r.get("code_refs") or [])[:2])
            out.append(f"| `{r['src']}` | {r['reason']} | {refs} |")
    if restored:
        out += ["", "## 已恢复（验证后移回原处）", ""] + [f"- `{s}`" for s in sorted(restored)]
    p = q / "MANIFEST.md"
    p.write_text("\n".join(out) + "\n", encoding="utf-8")
    return p


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("plan", nargs="?")
    ap.add_argument("--qdir", default=DEFAULT_Q)
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--manifest", action="store_true")
    ap.add_argument("--restore")
    a = ap.parse_args(argv)
    q = ROOT / a.qdir
    q.mkdir(parents=True, exist_ok=True)
    if a.restore:
        print(restore(a.restore, q))
        manifest(q)
        return 0
    if a.plan:
        plan = json.loads(Path(a.plan).read_text(encoding="utf-8"))
        n = defaultdict(int)
        for it in plan:
            rec = move_one(it, q, a.dry)
            n[rec["status"]] += 1
            print(rec["status"], rec["src"], human(rec.get("bytes") or 0), (rec.get("code_refs") or [""])[0][:100])
            if not a.dry:
                with (q / "moves.jsonl").open("a", encoding="utf-8") as w:
                    w.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(dict(n))
    if not a.dry and (q / "moves.jsonl").exists():
        print("MANIFEST", manifest(q))
    return 0


if __name__ == "__main__":
    sys.exit(main())
