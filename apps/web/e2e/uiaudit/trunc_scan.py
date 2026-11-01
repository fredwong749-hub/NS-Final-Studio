"""UIAUDIT：离线并回后，找被截断的媒体 / JSON 文件（只读）。
判据：PNG/JPG 用 PIL 完整解码；MP4 查 moov 盒是否存在；JSON 能否解析。只扫 mtime 在 [since, now] 的文件。
用法：python trunc_scan.py 2026-11-01T11:00 out.json
"""
import sys, json, os, time, datetime, pathlib
from PIL import Image
ROOT = pathlib.Path(__file__).resolve().parents[4]
since = datetime.datetime.fromisoformat(sys.argv[1]).timestamp()
bad, n = [], 0
for base in ["data"]:
    for dp, dn, fn in os.walk(ROOT / base):
        if "_trash" in dp or "_archive" in dp or "cache" in dp.replace("\\", "/").split("/")[-1:]:
            continue
        for f in fn:
            p = pathlib.Path(dp) / f
            ext = p.suffix.lower()
            if ext not in (".png", ".jpg", ".jpeg", ".webp", ".mp4", ".json"):
                continue
            try:
                st = p.stat()
            except OSError:
                continue
            if st.st_mtime < since:
                continue
            n += 1
            why = None
            try:
                if ext in (".png", ".jpg", ".jpeg", ".webp"):
                    with Image.open(p) as im:
                        im.load()
                elif ext == ".mp4":
                    with open(p, "rb") as fh:
                        data = fh.read()
                    if b"moov" not in data:
                        why = "mp4 无 moov 盒"
                elif ext == ".json":
                    json.loads(p.read_text(encoding="utf-8"))
            except Exception as e:
                why = f"{type(e).__name__}: {str(e)[:80]}"
            if why:
                bad.append({"file": str(p.relative_to(ROOT)).replace("\\", "/"), "size": st.st_size, "size_mod512": st.st_size % 512,
                            "mtime": time.strftime("%m-%d %H:%M", time.localtime(st.st_mtime)), "why": why})
json.dump({"since": sys.argv[1], "scanned": n, "bad": bad}, open(sys.argv[2], "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"scanned={n} bad={len(bad)}")
for b in bad:
    print(f"  {b['mtime']} {b['size']:>9} mod512={b['size_mod512']:>3} {b['file']}  {b['why']}")
