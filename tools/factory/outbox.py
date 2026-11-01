"""FACTORY D7：outbox 写端（服务器本机；格式与 NETFIX puller 11-02 01:5x 约定；规则 K-OPS-F05）。

  <outbox>/<YYYYmmddTHHMMSS>_<seq6>_<对象 id，冒号换成 _>_<事件>/
      files/<仓库相对路径>      快照副本（不引用仓库活文件）
      manifest.json            {"id", "host", "obj", "event", "created"(带时区 ISO), "files": [{"rel", "sha256", "size", "prio"}]}
      .done                    最后写（空文件）；puller 只认带 .done 的目录
  prio：0 状态 / json（takes.json、契约、看图判定、attempts）；1 缩略图（512px JPEG，rel = 原图 rel + ".thumb.jpg"）；
        2 全尺寸首尾帧；3 视频 / 成片（按需拉）
  ack：puller 并回后在目录里建 .acked；本端按“不删文件”只归档到 <outbox>/_acked/<日期>/（archive_acked），不删除。
事件写在出图 / 打分完成的同一进程里，写失败只记日志、不影响生产（D5：回传和生产解耦）。
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import shutil
import threading
from pathlib import Path

ROOT = Path(os.environ.get("NS_ROOT") or Path(__file__).resolve().parents[2]).resolve()
DEFAULT_DIR = Path(os.environ.get("NS_OUTBOX") or "/root/work/fredw/offline_20261101/outbox")
EVENTS = ("take", "score", "vqa", "takes", "video", "assembly", "log")
TZ = dt.timezone(dt.timedelta(hours=9))          # 日志统一写带时区的 ISO（服务器系统时钟与笔记本差 14 小时，总调度 01:3x）
_LOCK = threading.Lock()


def now_iso() -> str:
    return dt.datetime.now(TZ).isoformat(timespec="seconds")


def prio_of(rel: str) -> int:
    r = rel.lower()
    if r.endswith(".thumb.jpg"):
        return 1
    if r.endswith((".json", ".jsonl", ".txt")):
        return 0
    if r.endswith((".png", ".jpg", ".jpeg", ".webp")):
        return 2
    return 3


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _next_seq(box: Path) -> int:
    f = box / ".seq"
    try:
        n = int(f.read_text().strip() or 0) + 1
    except (OSError, ValueError):
        n = 1
    tmp = box / ".seq.tmp"
    tmp.write_text(str(n))
    os.replace(tmp, f)
    return n


def thumb(src: Path, dst: Path, size: int = 512) -> bool:
    try:
        from PIL import Image
        im = Image.open(src).convert("RGB")
        im.thumbnail((size, size))
        dst.parent.mkdir(parents=True, exist_ok=True)
        im.save(dst, "JPEG", quality=85)
        return True
    except Exception:  # noqa: BLE001
        return False


def write(obj: str, event: str, rels: list[str], host: str | None = None, box: Path | None = None,
          root: Path | None = None, thumbs: bool = True, extra: dict | None = None) -> Path:
    """→ 写好的结果目录。rels = 仓库相对路径（快照复制）；图片自动加 512px 缩略图（prio 1）。.done 最后写"""
    if event not in EVENTS:
        raise ValueError(f"未知事件 {event}（{EVENTS}）")
    box = Path(box or DEFAULT_DIR)
    root = Path(root or ROOT)
    host = host or os.environ.get("NS_FACTORY_HOST") or os.environ.get("OFFLINE_SELF") or "unknown"
    box.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        seq = _next_seq(box)
    stamp = dt.datetime.now(TZ).strftime("%Y%m%dT%H%M%S")
    name = f"{stamp}_{seq:06d}_{obj.replace(':', '_').replace('/', '_')}_{event}"
    d = box / (name + ".part")
    files = []
    for rel in rels:
        src = root / rel
        if not src.is_file():
            continue
        dst = d / "files" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        files.append({"rel": rel, "sha256": _sha(dst), "size": dst.stat().st_size, "prio": prio_of(rel)})
        if thumbs and prio_of(rel) == 2:
            trel = rel + ".thumb.jpg"
            if thumb(dst, d / "files" / trel):
                tp = d / "files" / trel
                files.append({"rel": trel, "sha256": _sha(tp), "size": tp.stat().st_size, "prio": 1})
    man = {"id": name, "host": host, "obj": obj, "event": event, "created": now_iso(), "files": files, **(extra or {})}
    d.mkdir(parents=True, exist_ok=True)
    (d / "manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
    final = box / name
    os.replace(d, final)                       # 目录名去掉 .part 后才算出现（puller 只看最终名 + .done）
    (final / ".done").write_bytes(b"")
    return final


def archive_acked(box: Path | None = None, keep_hours: float = 24) -> int:
    """puller 建了 .acked 且超过 keep_hours 的目录 → 移到 _acked/<日期>/（不删）"""
    box = Path(box or DEFAULT_DIR)
    n = 0
    cutoff = dt.datetime.now().timestamp() - keep_hours * 3600
    for d in sorted(box.iterdir()) if box.is_dir() else []:
        a = d / ".acked"
        if d.is_dir() and not d.name.startswith("_") and a.exists() and a.stat().st_mtime < cutoff:
            dest = box / "_acked" / d.name[:8]
            dest.mkdir(parents=True, exist_ok=True)
            shutil.move(str(d), str(dest / d.name))
            n += 1
    return n
