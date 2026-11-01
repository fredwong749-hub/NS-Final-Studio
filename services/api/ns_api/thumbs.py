"""缩略图（UIRSI r14，技术分：图片懒加载 + 缩略图）。

GET /api/thumb?src=/files/<data 下的路径>[&w=360]
→ 等比缩到宽 w（120–960，向上取到 120 的倍数）的 JPEG，缓存在 data/_cache/thumbs/（按源文件路径 + mtime + 宽度做键，源文件变了自动换）。
只读 data/ 下的图片；不改原图。列表、画布格子、设定图候选都用它，原图（1–2 MB PNG）只在点开大图时才取。
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

REPO = Path(__file__).resolve().parents[3]
router = APIRouter(tags=["thumbs"])
EXT = {".png", ".jpg", ".jpeg", ".webp"}


def _data() -> Path:
    return (REPO / "data").resolve()


def _cache() -> Path:
    d = REPO / "data" / "_cache" / "thumbs"
    d.mkdir(parents=True, exist_ok=True)
    return d


@router.get("/api/thumb")
def thumb(src: str, w: int = 360):
    if src.startswith("/api/assets/file?"):   # 资产图（assets/ 下）：/api/assets/file?path=<相对项目根>&v=…
        from urllib.parse import parse_qs, urlsplit
        rp = (parse_qs(urlsplit(src).query).get("path") or [""])[0]
        f = (REPO / rp).resolve()
        base = (REPO / "assets").resolve()
    else:
        rel = src.split("?", 1)[0]
        if not rel.startswith("/files/"):
            raise HTTPException(422, "src 要是 /files/… 或 /api/assets/file?path=… 路径")
        f = (_data() / rel[len("/files/"):]).resolve()
        base = _data()
    if base not in f.parents or f.suffix.lower() not in EXT or not f.is_file():
        raise HTTPException(404, "没有这张图")
    w = max(120, min(960, -(-w // 120) * 120))   # 向上取到 120 的倍数
    st = f.stat()
    key = hashlib.sha1(f"{f}|{st.st_mtime_ns}|{st.st_size}|{w}".encode()).hexdigest()[:20]
    out = _cache() / f"{key}.jpg"
    if not out.exists():
        from PIL import Image
        with Image.open(f) as im:
            im = im.convert("RGB")
            if im.width > w:
                im = im.resize((w, max(1, round(im.height * w / im.width))), Image.LANCZOS)
            tmp = out.with_suffix(".tmp")
            im.save(tmp, "JPEG", quality=82, optimize=True)
            tmp.replace(out)
    return FileResponse(out, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=604800"})
