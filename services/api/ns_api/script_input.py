"""
剧本输入页后端（项目方 2026-10-30：“我新增一个页面,就是剧本输入页面”；fredw-25 起草，fredw-92 接手合入）。

项目方在画布里粘贴 / 上传剧本文本，存成草稿 data/staging_input/<名>.md。草稿自动成为剧本导入收件箱
（script_inbox）的候选，校验与导入走原流程（只做格式校验，项目方确认后导入）。系统不读不改剧本内容：
保存即原样写盘（只统一换行为 LF）。

接口：
  GET    /api/script-input                       草稿列表
  GET    /api/script-input/text?path=            读一个候选（草稿或收件箱候选）的原文
  POST   /api/script-input  {name, text, overwrite?}   保存草稿
  POST   /api/script-input/upload (multipart file)     上传 .md / .txt 存为草稿
  DELETE /api/script-input/{name}                删除草稿（移到 data/staging_input/.trash/，可找回）
"""
from __future__ import annotations

import os
import re
import shutil
import tempfile
import time
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from ns_api import script_inbox as SI

router = APIRouter(tags=["script-input"])

DRAFT_EXT = {".md", ".txt"}
MAX_SCRIPT_BYTES = 20 * 2**20


def drafts_dir() -> Path:
    return SI.DATA / "staging_input"


def _safe_name(name: str) -> str:
    stem = Path(name.strip()).stem if name.strip().lower().endswith(tuple(DRAFT_EXT)) else name.strip()
    stem = re.sub(r'[\\/:*?"<>|\s]+', "_", stem).strip("._")
    if not stem:
        raise HTTPException(422, "名称不能为空")
    return stem[:80] + ".md"


def _draft_info(p: Path) -> dict:
    sha = SI._sha(p)
    st = p.stat()
    return {"path": SI._rel(p), "name": p.name, "size": st.st_size, "sha256": sha,
            "mtime": time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime)),
            "validation": SI._load_cache().get(sha)}


def _write_draft(name: str, text: str, overwrite: bool) -> dict:
    data = text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")   # 封板修复：单独的 \r 也统一成 LF
    if not text.strip():
        raise HTTPException(422, "剧本是空的")
    if len(data) > MAX_SCRIPT_BYTES:
        raise HTTPException(413, "剧本超过 20 MB")
    d = drafts_dir()
    d.mkdir(parents=True, exist_ok=True)
    p = d / _safe_name(name)
    if p.exists() and not overwrite:
        raise HTTPException(409, f"已有同名草稿 {p.name}：勾选“覆盖”或换个名字")
    # 封板修复：唯一临时文件（并发同名保存曾因固定 .md.tmp 互踩 500）；不覆盖时用 os.link 原子落盘，
    # 检查与写入之间别人先存了同名 → 409，不会悄悄覆盖
    fd, tmp = tempfile.mkstemp(dir=d, prefix=p.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        if overwrite:
            os.replace(tmp, p)
        else:
            try:
                os.link(tmp, p)
            except FileExistsError:
                raise HTTPException(409, f"已有同名草稿 {p.name}：勾选“覆盖”或换个名字")
            except OSError:   # 文件系统不支持硬链接：退回 O_EXCL 独占创建
                try:
                    fd2 = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0))
                except FileExistsError:
                    raise HTTPException(409, f"已有同名草稿 {p.name}：勾选“覆盖”或换个名字")
                with os.fdopen(fd2, "wb") as f:
                    f.write(data)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    return _draft_info(p)


@router.get("/api/script-input")
def list_drafts():
    d = drafts_dir()
    items = [_draft_info(p) for p in sorted(d.glob("*.md"), key=lambda p: -p.stat().st_mtime)] if d.is_dir() else []
    return {"drafts": items, "dir": SI._rel(d) if d.is_dir() else "data/staging_input"}


@router.get("/api/script-input/text")
def read_text(path: str):
    p = SI._allowed(path)
    return {"path": SI._rel(p), "name": p.name, "text": p.read_text(encoding="utf-8", errors="replace"),
            "editable": p.parent.resolve() == drafts_dir().resolve(), "sha256": SI._sha(p)}


class DraftBody(BaseModel):
    name: str
    text: str
    overwrite: bool = False


@router.post("/api/script-input")
def save_draft(body: DraftBody):
    return _write_draft(body.name, body.text, body.overwrite)


@router.post("/api/script-input/upload")
async def upload_draft(file: UploadFile = File(...), overwrite: bool = Form(False)):
    name = file.filename or "script.md"
    if Path(name).suffix.lower() not in DRAFT_EXT:
        raise HTTPException(422, "只接受 .md / .txt")
    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = raw.decode("gb18030")
        except UnicodeDecodeError:
            raise HTTPException(422, "文件编码无法识别（请存为 UTF-8）")
    return _write_draft(name, text, overwrite)


@router.delete("/api/script-input/{name}")
def delete_draft(name: str):
    p = drafts_dir() / _safe_name(name)
    if not p.is_file():
        raise HTTPException(404, f"没有这个草稿：{name}")
    trash = drafts_dir() / ".trash"
    trash.mkdir(parents=True, exist_ok=True)
    dest = trash / f"{p.stem}.{time.strftime('%Y%m%d-%H%M%S')}.md"
    shutil.move(str(p), dest)
    return {"ok": True, "moved_to": SI._rel(dest)}
