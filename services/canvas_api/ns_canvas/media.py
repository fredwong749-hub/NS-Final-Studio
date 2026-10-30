"""媒体：带 Range 的文件响应、ffmpeg 抽尾帧、缩略图（都缓存在 state/cache）。"""
from __future__ import annotations

import hashlib
import mimetypes
import re
import subprocess
import threading
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, Response, StreamingResponse

_locks: dict[str, threading.Lock] = {}
_glock = threading.Lock()


def _lock_for(key: str) -> threading.Lock:
    with _glock:
        return _locks.setdefault(key, threading.Lock())


def file_response(path: Path, request: Request):
    if not path.is_file():
        raise HTTPException(404, "文件不存在")
    size = path.stat().st_size
    ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    rng = request.headers.get("range")
    headers = {"Accept-Ranges": "bytes", "Cache-Control": "no-cache"}
    if not rng:
        return FileResponse(path, media_type=ctype, headers=headers)
    m = re.match(r"bytes=(\d*)-(\d*)", rng)
    if not m:
        raise HTTPException(416)
    a, b = m.groups()
    if a == "":
        start, end = max(0, size - int(b)), size - 1
    else:
        start, end = int(a), int(b) if b else size - 1
    end = min(end, size - 1)
    if start > end or start >= size:
        return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})

    def body(chunk=1 << 16):
        with path.open("rb") as f:
            f.seek(start)
            left = end - start + 1
            while left > 0:
                data = f.read(min(chunk, left))
                if not data:
                    break
                left -= len(data)
                yield data

    headers.update({"Content-Range": f"bytes {start}-{end}/{size}", "Content-Length": str(end - start + 1)})
    return StreamingResponse(body(), status_code=206, media_type=ctype, headers=headers)


def _key(src: Path, extra: str) -> str:
    st = src.stat()
    return hashlib.sha1(f"{src}|{st.st_mtime_ns}|{st.st_size}|{extra}".encode()).hexdigest()[:20]


def extract_last_frame(ffmpeg: str, video: Path, cache_dir: Path) -> Path | None:
    """视频最后一帧 → PNG。先试 -sseof，太短的视频退回整段解码。"""
    if not video.is_file():
        return None
    out = cache_dir / "last" / f"{_key(video, 'last')}.png"
    if out.exists():
        return out
    with _lock_for(str(out)):
        if out.exists():
            return out
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(".tmp.png")
        for pre in (["-sseof", "-1"], []):
            cmd = [ffmpeg, "-v", "error", "-y", *pre, "-i", str(video), "-an", "-update", "1", "-q:v", "1", str(tmp)]
            try:
                subprocess.run(cmd, check=True, timeout=120, capture_output=True)
            except (subprocess.SubprocessError, OSError):
                continue
            if tmp.exists() and tmp.stat().st_size > 0:
                tmp.replace(out)
                return out
        return None


def thumbnail(ffmpeg: str, src: Path, cache_dir: Path, width: int) -> Path | None:
    if not src.is_file():
        return None
    width = max(64, min(int(width), 1080))
    out = cache_dir / "thumb" / f"{_key(src, str(width))}.jpg"
    if out.exists():
        return out
    with _lock_for(str(out)):
        if out.exists():
            return out
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(".tmp.jpg")
        cmd = [ffmpeg, "-v", "error", "-y", "-i", str(src), "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "4", str(tmp)]
        try:
            subprocess.run(cmd, check=True, timeout=60, capture_output=True)
        except (subprocess.SubprocessError, OSError):
            return None
        if tmp.exists():
            tmp.replace(out)
            return out
    return None
