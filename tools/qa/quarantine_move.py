"""RECALL 2026-11-01：把旧剧 / 预 series10 残留移进隔离区（只移动，不删除）。

用法：python -I -X utf8 tools/qa/quarantine_move.py PLAN.json
PLAN.json = [{"cat": "assets|loras|voices|renders|config|code", "src": "绝对路径", "reason": "..."}]
项目内路径 → data/_quarantine_20261101/<相对项目根的路径>；项目外路径（笔记本其他目录的 LoRA）→
data/_quarantine_20261101/loras/laptop/<盘符>/<原路径>。每一项追加一行到 data/_quarantine_20261101/moves.jsonl。
"""
import json, os, shutil, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import quarantine_refcheck as RC  # noqa: E402  ISS-1103-033325-9b07：系统代码守卫与 quarantine_safe_move 同一条规则

ROOT = Path(r"D:\NS-Final Studio")
Q = ROOT / "data" / "_quarantine_20261101"


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


def dest_for(src: Path) -> Path:
    try:
        rel = src.resolve().relative_to(ROOT)
        return Q / rel
    except ValueError:
        drive = src.drive.rstrip(":").lower() or "x"
        return Q / "loras" / "laptop" / drive / Path(*src.parts[1:])


def main():
    plan = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    Q.mkdir(parents=True, exist_ok=True)
    log = Q / "moves.jsonl"
    ok = fail = 0
    for it in plan:
        src = Path(it["src"])
        rec = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "cat": it["cat"], "src": str(src), "reason": it["reason"], "host": "laptop"}
        code = RC.protected_code(src, ROOT) if src.exists() else []
        if not src.exists():
            rec.update(status="missing")
            print("MISSING", src)
        elif code:
            rec.update(status="kept_code", code=code[:10])
            print("KEPT（系统代码不属于内容隔离）", src)
        else:
            dst = dest_for(src)
            rec["dst"] = str(dst)
            rec["bytes"] = size_of(src)
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                if dst.exists():
                    raise FileExistsError(str(dst))
                shutil.move(str(src), str(dst))
                rec["status"] = "moved"
                ok += 1
            except Exception as e:  # noqa: BLE001 - 记录失败继续
                rec.update(status="failed", error=repr(e))
                fail += 1
                print("FAILED", src, e)
        with log.open("a", encoding="utf-8") as w:
            w.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"moved={ok} failed={fail}")


if __name__ == "__main__":
    main()
