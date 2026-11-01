"""现行导入稿的来源文件（CLEANUP 2026-11-01，总调度按 G0 定：header_sources / 剧本主线不再写死路径）。

data/import/script_v2.json 的 sources 记着每次导入的来源 md 路径和 sha256。这里按导入顺序倒着找：
文件存在、sha256 与导入记录一致（= 就是导入进去的那份）、episodes 非空（真的导入过集）的来源，就是“现行导入来源”。
script_chat 的剧本全局头、剧本导入页的“主线”都从这里推导；推导不出来（没有导入稿 / 来源文件被改过或挪走）才回退到配置。
规则 K-OPS-Q31，测试 tests/test_import_sources.py。
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
IMPORT_JSON = REPO / "data" / "import" / "script_v2.json"
EP_HEAD_RE = re.compile(r"^## ep\d+", re.M)


def _rel(p: Path, root: Path) -> str:
    try:
        return p.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(p)


def current_sources(import_json: Path | None = None, root: Path | None = None) -> list[dict]:
    """现行导入来源（新 → 旧）：[{path: 仓库相对路径, sha256, episodes}]；只收 sha 一致、文件还在、导入过集的来源"""
    import_json = Path(import_json or IMPORT_JSON)
    root = Path(root or REPO)
    try:
        d = json.loads(import_json.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out, seen = [], set()
    for src in reversed(d.get("sources") or []):
        if not src.get("episodes"):
            continue
        raw = str(src.get("path") or "").replace("\\", "/")
        p = Path(raw)
        if not p.is_absolute():
            p = root / p
        if not p.is_file():
            continue
        if src.get("sha256") and hashlib.sha256(p.read_bytes()).hexdigest() != src["sha256"]:
            continue
        rel = _rel(p, root)
        if rel in seen:
            continue
        seen.add(rel)
        out.append({"path": rel, "sha256": src.get("sha256"), "episodes": list(src.get("episodes") or [])})
    return out


def header_source(import_json: Path | None = None, root: Path | None = None) -> str | None:
    """剧本全局头来源：最新一份带全局头（第一个 `## ep` 之前有内容）的现行导入来源；没有返回 None"""
    root = Path(root or REPO)
    for s in current_sources(import_json, root):
        p = Path(s["path"])
        p = p if p.is_absolute() else root / p
        text = p.read_text(encoding="utf-8")
        m = EP_HEAD_RE.search(text)
        head = text[: m.start()] if m else ""
        if "```" in head or "**全剧人物表**" in head:
            return s["path"]
    return None


def mainline(import_json: Path | None = None, root: Path | None = None) -> list[str]:
    """剧本主线候选 = 最新一份现行导入来源（覆盖集数最多者优先，同数取最新）"""
    srcs = current_sources(import_json, root)
    if not srcs:
        return []
    best = max(range(len(srcs)), key=lambda i: (len(srcs[i]["episodes"]), -i))
    return [srcs[best]["path"]]
