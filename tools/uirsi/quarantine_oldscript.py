"""旧剧本版本隔离（UIRSI r41；项目方 11-02 00:5x：“旧版本的东西就隔离开吧,然后在我的网页里面尽量给我看最新的”）。

判定沿用 r40：ns_api.takes_ui.script_version(take, ep) == "old"（带现行剧本 sha 的按 sha；否则出图时间早于本集最后一次导入）。
  mark   给这些版本在 takes.json 里局部追加 quarantined = {at, by, reason, moved_to: {字段: 新位置}}（其余字段、历史记录一律不动；
         写前把整份 takes.json 备份到 <qdir>/_takes_backup/<原相对路径>）；同时生成移动计划 <qdir>/plan_oldscript.json
  restore-mark  从备份把 takes.json 的 quarantined 字段撤掉（只撤本工具加的，按 by 字段认）
文件移动只走 tools/qa/quarantine_safe_move.py（K-OPS-Q30：引用检查、保持原相对路径、moves.jsonl + MANIFEST、--restore 一键恢复）。

    .venv/Scripts/python.exe -X utf8 tools/uirsi/quarantine_oldscript.py mark [--dry]
    .venv/Scripts/python.exe -X utf8 tools/qa/quarantine_safe_move.py data/_quarantine_20261102_oldscript/plan_oldscript.json --qdir data/_quarantine_20261102_oldscript
    .venv/Scripts/python.exe -X utf8 tools/uirsi/quarantine_oldscript.py restore-mark      # 撤标记（文件用 safe_move --restore 移回）
    .venv/Scripts/python.exe -X utf8 tools/uirsi/quarantine_oldscript.py restore-all       # 一键恢复：文件逐项 safe_move --restore 移回 + 撤标记
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in ("services/api", "services/render_router", "services/agent"):
    sys.path.insert(0, str(ROOT / p))
from ns_api import takes_ui as T  # noqa: E402

QDIR = ROOT / "data" / "_quarantine_20261102_oldscript"
BY = "UIRSI r41（旧剧本版本隔离）"
REASON = "旧剧本版本：剧本 11-01 23:2x 逐集重导（镜头可能重新编号）之前出的；项目方 11-02 00:5x：“旧版本的东西就隔离开吧”"
REF_OVERRIDE = ("引用方只有：测试临时夹具同名文件（tests 里 tmp_path 生成的 image_00N_pipeline.png 等）、e2e 扫描输出、历史记录"
                "（旧剧本成片 timeline、jobs/v1 历史、edits 记录、vqa 判定、rescore 计划、api 快照缓存）——都不是生产读取者；"
                "takes.json 里该版已标 quarantined 并记新位置（moved_to）")


def _wjson(p: Path, d) -> None:
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def mark(dry: bool = False) -> dict:
    plan, stats = [], {"takes": 0, "files": 0, "active_old": 0, "shots": 0}
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    for tj in sorted((ROOT / "data" / "renders").glob("ep*/S*/takes.json")):
        ep = int(re.search(r"ep(\d{2})", str(tj)).group(1))
        d = json.loads(tj.read_text(encoding="utf-8"))
        act = d.get("active") or {}
        changed = False
        for t in d.get("takes") or []:
            if t.get("quarantined") or T.script_version(t, ep) != "old":
                continue
            # 文件已在隔离区（上次标记被别的进程整份重写 takes.json 时冲掉了）也照样记 moved_to，补回标记
            moved = {k: f"data/_quarantine_20261102_oldscript/data/{v}" for k, v in t.items()
                     if isinstance(v, str) and v.startswith("renders/")
                     and ((ROOT / "data" / v).is_file() or (QDIR / "data" / v).is_file())}
            t["quarantined"] = {"at": now, "by": BY, "reason": REASON, "moved_to": moved,
                                "was_active": act.get(t.get("stage")) == t.get("n")}
            stats["takes"] += 1
            stats["active_old"] += int(act.get(t.get("stage")) == t.get("n"))
            for k, v in t.items():
                if isinstance(v, str) and v.startswith("renders/") and (ROOT / "data" / v).is_file():
                    plan.append({"cat": "old_script_take", "src": f"data/{v}", "reason": REASON, "ref_override": REF_OVERRIDE})
            changed = True
        if changed:
            stats["shots"] += 1
            if not dry:
                bk = QDIR / "_takes_backup" / tj.relative_to(ROOT)
                bk.parent.mkdir(parents=True, exist_ok=True)
                if not bk.exists():
                    shutil.copy2(tj, bk)
                # 写前再读一遍：只把本工具的 quarantined 字段并进最新内容（别的进程刚加的版本不丢）
                cur = json.loads(tj.read_text(encoding="utf-8"))
                q = {(t["stage"], t["n"]): t["quarantined"] for t in d["takes"] if isinstance(t.get("quarantined"), dict) and t["quarantined"].get("by") == BY}
                for t in cur.get("takes") or []:
                    if (t.get("stage"), t.get("n")) in q and not t.get("quarantined"):
                        t["quarantined"] = q[(t["stage"], t["n"])]
                _wjson(tj, cur)
    stats["files"] = len(plan)
    if not dry:
        QDIR.mkdir(parents=True, exist_ok=True)
        (QDIR / "plan_oldscript.json").write_text(json.dumps(plan, ensure_ascii=False, indent=0), encoding="utf-8")
    return stats


def restore_mark() -> int:
    n = 0
    for tj in sorted((ROOT / "data" / "renders").glob("ep*/S*/takes.json")):
        d = json.loads(tj.read_text(encoding="utf-8"))
        hit = False
        for t in d.get("takes") or []:
            q = t.get("quarantined")
            if isinstance(q, dict) and q.get("by") == BY:
                t["quarantined"] = None
                hit = True
                n += 1
        if hit:
            _wjson(tj, d)
    return n


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "mark"
    if cmd == "mark":
        print(json.dumps(mark("--dry" in sys.argv), ensure_ascii=False))
    elif cmd == "restore-all":
        import subprocess
        mv = QDIR / "moves.jsonl"
        srcs = [json.loads(ln).get("src") for ln in mv.read_text(encoding="utf-8").splitlines() if ln.strip()] if mv.exists() else []
        ok = 0
        for s in dict.fromkeys(x for x in srcs if x):
            r = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "tools/qa/quarantine_safe_move.py"), "--restore", s, "--qdir", str(QDIR.relative_to(ROOT))], cwd=ROOT)
            ok += r.returncode == 0
        print(f"移回 {ok}/{len(set(srcs))} 个文件；撤掉 {restore_mark()} 个版本的隔离标记")
    elif cmd == "restore-mark":
        print(f"撤掉 {restore_mark()} 个版本的隔离标记")
    else:
        print(__doc__)
