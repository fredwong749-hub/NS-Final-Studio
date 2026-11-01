"""还原 data/_archive/<日期>/ 里归档的文件（2026-10-31 数据清洗用）。

MANIFEST.tsv 每行：原路径  归档路径  sha256  字节数（相对仓库根，制表符分隔，首行表头）。

用法（仓库根目录）：
  python tools/restore_archive.py --list                      # 列出归档清单
  python tools/restore_archive.py --all                       # 全部还原
  python tools/restore_archive.py --prefix previews/          # 只还原原路径以此开头的文件
  python tools/restore_archive.py --all --dry-run             # 只打印不移动
  --archive data/_archive/20261031                            # 指定归档目录（默认这个）
  python tools/restore_archive.py --archive data/_archive/20261031_r2 --all --records   # 第二轮：文件 + 记录一起还原

只移动不删除；原位置已有同名文件时跳过并报告（不覆盖）；还原前校验 sha256。
"""
import argparse, hashlib, shutil, sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive", default="data/_archive/20261031")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--prefix", action="append", default=[])
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--records", action="store_true", help="同时把 _records_backup 里的记录副本复制回原位（第二轮用）")
    a = ap.parse_args()
    man = REPO / a.archive / "MANIFEST.tsv"
    rows = [ln.split("\t")[:4] for ln in man.read_text(encoding="utf-8").splitlines()[1:] if ln.strip()]
    if a.records:
        # r2：被改过的记录（asset_*.json、manifest.json、takes.json）改前副本在 <archive>/_records_backup/<原路径>
        bk = REPO / a.archive / "_records_backup"
        n = 0
        for p in sorted(bk.rglob("*")) if bk.is_dir() else []:
            if p.is_file():
                dst = REPO / p.relative_to(bk)
                print(("将恢复记录: " if a.dry_run else "恢复记录: ") + dst.relative_to(REPO).as_posix())
                if not a.dry_run:
                    shutil.copy2(p, dst)
                n += 1
        print(f"记录 {n} 个" + ("（dry-run）" if a.dry_run else "（注意：会覆盖这些记录在清理之后的新改动）"))
        if not a.all and not a.prefix:
            return 0
    if a.list:
        for src, dst, sha, size in rows:
            print(f"{size:>12}  {src}")
        print(f"共 {len(rows)} 个文件")
        return 0
    if not a.all and not a.prefix:
        ap.error("需要 --all 或 --prefix")
    ok = skip = bad = 0
    for src, dst, sha, size in rows:
        if not a.all and not any(src.startswith(p) for p in a.prefix):
            continue
        s, d = REPO / dst, REPO / src
        if not s.exists():
            print("归档里没有（已还原？）:", dst); skip += 1; continue
        if d.exists():
            print("原位置已有文件，跳过:", src); skip += 1; continue
        if sha256(s) != sha:
            print("sha256 不符，跳过:", dst); bad += 1; continue
        if a.dry_run:
            print("将还原:", src); ok += 1; continue
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(s), str(d))
        ok += 1
    print(f"还原 {ok}，跳过 {skip}，校验失败 {bad}" + ("（dry-run）" if a.dry_run else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
