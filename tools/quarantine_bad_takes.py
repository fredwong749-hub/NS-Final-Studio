"""fredw-92/UXF1：找出坏图版本（ns_render.image_check：短边 < 256 px、文件 < 10 KB、尺寸与请求差 > 10 %），
挪进该镜 takes/_quarantine/（不删文件），版本上记 bad / quarantined；当前版本是坏图 → 退回定稿版（定稿版也坏 →
退回最新的好版本）。每一条动作记进 data/logs/quarantine_bad_takes.jsonl。

    .venv\\Scripts\\python.exe tools/quarantine_bad_takes.py            # 只列出（不改）
    .venv\\Scripts\\python.exe tools/quarantine_bad_takes.py --apply    # 执行
    .venv\\Scripts\\python.exe tools/quarantine_bad_takes.py --apply --shot ep02-S1
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

from ns_render import image_check as IC
from ns_render import pipeline as P

LOG = Path("logs") / "quarantine_bad_takes.jsonl"


def _log(row: dict) -> None:
    f = P.DATA / LOG
    f.parent.mkdir(parents=True, exist_ok=True)
    with f.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"at": P.now(), **row}, ensure_ascii=False) + "\n")


def _move(rel: str, qdir: Path) -> str:
    """data/ 下的 rel → takes/_quarantine/<名>；返回新的相对路径（文件不在就原样返回）"""
    src = P.DATA / rel
    if not src.is_file():
        return rel
    qdir.mkdir(parents=True, exist_ok=True)
    dst = qdir / src.name
    if dst.exists():
        dst = qdir / f"{src.stem}_{int(time.time())}{src.suffix}"
    shutil.move(str(src), str(dst))
    return dst.relative_to(P.DATA).as_posix()


def shots_with_takes(only: str | None):
    for f in sorted(P.RENDERS.glob("ep*/S*/takes.json")):
        sid = f"{f.parent.parent.name}-{f.parent.name}"
        if only and sid != only:
            continue
        yield sid


def scan(shot_id: str) -> list[dict]:
    data = P.load_takes(shot_id)
    out = []
    for t in data["takes"]:
        if t.get("quarantined"):
            continue
        why = IC.check_take({**t, "bad": None}, P.DATA)
        if why:
            out.append({"shot": shot_id, "stage": t["stage"], "n": t["n"], "file": t["file"], "why": why,
                        "active": (data.get("active") or {}).get(t["stage"]) == t["n"],
                        "locked": (data.get("locked") or {}).get(t["stage"]) == t["n"],
                        "job_id": t.get("job_id")})
    return out


def repair(shot_id: str, bad: list[dict]) -> None:
    qdir = P.shot_dir(shot_id) / "takes" / "_quarantine"
    with P.shot_lock(shot_id):
        data = P.load_takes(shot_id)
        for b in bad:
            t = next(x for x in data["takes"] if x["stage"] == b["stage"] and x["n"] == b["n"])
            old = {"file": t["file"], "raw_file": t.get("raw_file")}
            t["file"] = _move(t["file"], qdir)
            if t.get("raw_file"):
                t["raw_file"] = _move(t["raw_file"], qdir)
            t["bad"] = b["why"]
            t["quarantined"] = P.now()
            if t.get("locked") and (data.get("locked") or {}).get(b["stage"]) == b["n"]:
                data["locked"].pop(b["stage"], None)
                (data.get("locked_src") or {}).pop(b["stage"], None)
                t["locked"] = False
            _log({"shot": shot_id, "action": "quarantine", "stage": b["stage"], "n": b["n"], "why": b["why"],
                  "from": old, "to": {"file": t["file"], "raw_file": t.get("raw_file")}, "job_id": b.get("job_id")})
        P._save_takes(shot_id, data)
    # 当前版本是坏图 → 退回定稿版，定稿版没有 / 也坏 → 最新的好版本
    data = P.load_takes(shot_id)
    for stage in {b["stage"] for b in bad}:
        act = (data.get("active") or {}).get(stage)
        if act is not None and not any(b["stage"] == stage and b["n"] == act for b in bad):
            continue
        good = [t for t in data["takes"] if t["stage"] == stage and not P.bad_reason(t)]
        lk = (data.get("locked") or {}).get(stage)
        pick = next((t for t in good if t["n"] == lk), None) or (good[-1] if good else None)
        if pick is None:
            data["active"].pop(stage, None)
            P._save_takes(shot_id, data)
            _log({"shot": shot_id, "action": "clear_active", "stage": stage, "from": act})
            continue
        P.set_active(shot_id, stage, pick["n"])
        _log({"shot": shot_id, "action": "set_active", "stage": stage, "from": act, "to": pick["n"],
              "reason": "退回定稿版" if pick["n"] == lk else "退回最新的好版本"})


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--shot")
    a = ap.parse_args(argv)
    total = 0
    for sid in shots_with_takes(a.shot):
        bad = scan(sid)
        if not bad:
            continue
        total += len(bad)
        for b in bad:
            print(f"{sid} {b['stage']} v{b['n']}{' [当前]' if b['active'] else ''}{' [定稿]' if b['locked'] else ''}："
                  f"{b['why']}  {b['file']}")
        if a.apply:
            repair(sid, bad)
    print(f"共 {total} 个坏图版本" + ("（已隔离）" if a.apply and total else "（只列出，加 --apply 执行）" if total else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
