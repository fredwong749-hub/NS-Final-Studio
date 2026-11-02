"""V1 / V2 分开显示（L-125 / L-126，NAVIA 20:1x）。

- V2（当前 primary）的页面只许出现 V2 目录下的文件：primary 不是 legacy_unprefixed_run 时，文件相对路径必须在 renders/<primary>/ 下，
  落在旧的不带前缀路径（V1）上的一律不给地址（返回 None），页面显示“没有”，不退回 V1 的图。
- V1 只在“Version 1 视频库”（GET /api/v1-library，只读）里出现。
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _data_root(data_dir=None) -> Path:
    return Path(data_dir if data_dir is not None else ROOT / "data").resolve()


def _runs_file(data_dir=None) -> Path:
    """被发放的 data 根旁边的 config/pipeline/runs.json（和 run_paths._ctx 同一个口径：沙箱 / 临时目录有自己的一份或没有）"""
    return _data_root(data_dir).parent / "config" / "pipeline" / "runs.json"


def _runs(data_dir=None) -> dict:
    return json.loads(_runs_file(data_dir).read_text(encoding="utf-8"))


def v2_prefix(data_dir=None) -> str | None:
    """当前 primary 不是 legacy（V1）时 = “renders/<primary>/”；否则 None（不限制）。
    这个 data 根旁边没有 runs.json（沙箱 / 临时目录）→ None；是仓库自己的 data 却读不到 → 抛出（fail-closed）。"""
    f = _runs_file(data_dir)
    if not f.exists() and _data_root(data_dir) != (ROOT / "data").resolve():
        return None
    d = _runs(data_dir)
    prim, leg = d.get("primary"), d.get("legacy_unprefixed_run")
    return None if not prim or prim == leg else f"renders/{prim}/"


def scoped(rel: str | None, prefix: str | None = ..., data_dir=None) -> str | None:
    """rel 属于当前剧才原样返回；属于别的剧（V1）→ None"""
    if not rel:
        return None
    pre = v2_prefix(data_dir) if prefix is ... else prefix
    r = rel.replace("\\", "/").lstrip("/")
    if r.startswith("data/"):
        r = r[5:]
    return rel if pre is None or r.lower().startswith(pre.lower()) else None


# ---------------------------------------------------------------- 统一拦截（文件发放层，不逐个接口接）
import posixpath as _posixpath
import re as _re
from urllib.parse import unquote as _unquote

_cache: dict = {}   # data 根 → (runs.json 修改时间, 前缀)


def _prefix_cached(data_dir=None) -> str | None:
    """v2_prefix 按（data 根, runs.json 修改时间）缓存；仓库 data 下读不到直接抛出（fail-closed，中间件里按拒绝处理）"""
    root = str(_data_root(data_dir))
    f = _runs_file(data_dir)
    mt = f.stat().st_mtime_ns if f.exists() else None
    hit = _cache.get(root)
    if hit is None or hit[0] != mt:
        hit = (mt, v2_prefix(data_dir))
        _cache[root] = hit
    return hit[1]


def deny(path: str, query: str = "", data_dir=None) -> bool:
    """当前剧是 V2 时：任何 GET 请求的路径或查询里出现 renders/<不是当前剧的目录>/… 就拒绝。
    覆盖 /files/…、/api/thumb?src=…、/api/assets/file?path=…、/api/looks/ref-image?path=…、/api/gpu3-media/… 以及以后新增的任何出口。
    V1 视频库走自己的只读路由 /v1-files/（不在这里放行任何 /files/ 下的 V1 路径）。"""
    if path.startswith(("/v1-files/", "/api/v1-library")):
        return False
    if path.startswith("/api/gpu3-media/"):
        rel = _unquote(path[len("/api/gpu3-media/"):])
        # gpu3-media 自己的安全检查（路径穿越 / 反斜杠 / 冒号 / 不在 renders_gpu3/ 下）排在最前面，回 400，不被这里改成 404
        if not rel.startswith("renders_gpu3/") or "\\" in rel or ":" in rel or any(x in ("..", ".") for x in rel.split("/")):
            return False
    try:
        pre = _prefix_cached(data_dir)
    except (OSError, ValueError):  # arch-ok: 读不到 runs.json 时按拒绝处理（fail-closed），不放过 V1 的文件
        return True
    if pre is None:
        return False
    cur = pre[len("renders/"):].lower()      # “series10_v2/”
    # 按“这个文件属于哪部剧”判断：renders/ 或 renders_gpu3/ 后面第一段必须是当前剧目录；不带剧前缀的（renders/ep01、renders_gpu3/ep01 = V1 legacy 布局，含 cache/gpu3_media/ 下的缓存）一律拒。前面是字母数字下划线点横线的（myrenders/）不算
    pat = _re.compile(r"(?<![A-Za-z0-9_.\-])renders(?:_gpu3)?/(?!" + _re.escape(cur) + r")[^/\s&?#]")
    return any(pat.search(t) for t in _variants(path + "?" + query))


def _variants(raw: str) -> list[str]:
    """同一个请求在文件系统眼里的所有写法：反复 URL 解码（%2F、%252F）、反斜杠当斜杠、多个斜杠合并、./ 和 ../ 先算掉、
    每段去掉末尾的点和空格（NTFS 认 renders./ 和 renders /）、去掉 ::$DATA、统一小写（NTFS 不分大小写）。
    原文和规范化后的都返回，任何一个命中就拒绝。"""
    t = raw
    for _ in range(4):
        u = _unquote(t)
        if u == t:
            break
        t = u
    t = t.replace("\\", "/").replace("::$data", "").replace("::$DATA", "")
    t = _re.sub(r"/+", "/", t)
    out = {t.lower()}
    segs = [x.rstrip(". ") if x not in (".", "..") else x for x in t.split("/")]
    n = _posixpath.normpath("/".join(segs))
    out.add(n.lower())
    out.add(_re.sub(r"/+", "/", n).lower())
    return list(out)


V1_VIDEO_RE = _re.compile(r"^renders/ep\d+/S\d+/takes/[^/]+\.(mp4|webm)$")

