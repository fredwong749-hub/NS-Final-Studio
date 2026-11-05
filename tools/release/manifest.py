"""发版交付清单 + 文件租约（RSI release 线 72）。

问题：并行工人改重叠文件，清单先拼、别人的伴随文件后到，或未跟踪的伴随文件漏掉 → cut I 拆成 3 刀。
做法：①工人交 data/system_versions/deliverables/<worker>-<date>.json（交付清单）；
      ②manifest-check 核对存在 / 钉 blob / 查伴随缺口 / 查重叠 / 查别人的租约；
      ③cut --manifests 用 HEAD + 钉住的 blob 拼树（复用 system_version.build_tree_from_list）；
      ④租约 data/system_versions/leases.json：建议性，不锁文件系统。
本模块不依赖 system_version（避免循环），路径都带 root 参数便于测试。
"""
from __future__ import annotations

import ast
import fnmatch
import json
import os
import re
import subprocess
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JST = timezone(timedelta(hours=9))
DATA_NOT_IN_TREE = ("data/",)
DELIV_REL = "data/system_versions/deliverables"
PINS_REL = "data/system_versions/pins"
LEASE_REL = "data/system_versions/leases.json"
CODE_EXT = (".py", ".json", ".yaml", ".yml", ".sh", ".ps1", ".md", ".txt", ".toml")
DEFAULT_TTL_H = 6.0


def _git(root: Path, *a: str) -> str:
    r = subprocess.run(["git", *a], cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=300)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(a)[:60]} 失败：{(r.stdout + r.stderr)[-300:]}")
    return r.stdout


def _norm(p: str) -> str:
    p = p.replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p


def now_iso(ts: float | None = None) -> str:
    return datetime.fromtimestamp(ts if ts is not None else time.time(), JST).isoformat(timespec="seconds")


# ------------------------------------------------------------ 交付清单
def manifest_path(root: Path, mid: str) -> Path:
    return root / DELIV_REL / f"{mid}.json"


def load_manifest(root: Path, mid: str) -> dict:
    p = manifest_path(root, mid)
    if not p.exists():
        raise FileNotFoundError(f"没有交付清单 {mid}（{DELIV_REL}/{mid}.json）")
    m = json.loads(p.read_text(encoding="utf-8-sig"))
    m["id"] = mid
    for k in ("files", "tests", "deletes"):
        m[k] = [_norm(x) for x in m.get(k) or []]
    m["depends_on"] = list(m.get("depends_on") or [])
    return m


def all_paths(m: dict) -> list[str]:
    return list(dict.fromkeys([*m["files"], *m["tests"]]))


def blob_of(root: Path, rel: str, write: bool = False) -> str:
    return _git(root, "hash-object", *(["-w"] if write else []), "--", rel).strip()


def untracked_files(root: Path) -> list[str]:
    out = _git(root, "ls-files", "--others", "--exclude-standard")
    return [ln.strip() for ln in out.splitlines() if ln.strip().endswith(CODE_EXT)]


def _py_imports(text: str) -> set[str]:
    mods: set[str] = set()
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):  # arch-ok: 语法坏的文件抽不出 import；语法由 syntax_guard 闸门管
        return mods
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            mods.update(a.name for a in n.names)
        elif isinstance(n, ast.ImportFrom) and n.module:
            mods.add(n.module)
            mods.update(f"{n.module}.{a.name}" for a in n.names)
    return mods


def _dotted_suffixes(rel: str) -> set[str]:
    """packages/schema/ns_schema/prompt_v2.py -> {prompt_v2, ns_schema.prompt_v2, schema.ns_schema.prompt_v2, ...}"""
    parts = rel[:-3].split("/")
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return {".".join(parts[i:]) for i in range(len(parts))}


def companion_gaps(root: Path, files: list[str], covered: set[str], untracked: list[str] | None = None) -> list[dict]:
    """files 里的文本引用了“未跟踪、且不在任何交付清单里”的文件 = 伴随缺口。
    引用 = python import（点路径后缀匹配）/ 文本里出现完整仓库相对路径 / 引号里的文件名。"""
    unt = [u for u in (untracked if untracked is not None else untracked_files(root)) if u not in covered]
    if not unt:
        return []
    suf = {u: _dotted_suffixes(u) for u in unt if u.endswith(".py")}
    # 已跟踪的同名模块能解析这个 import（例：备份目录里的 remote_score.py 不算缺口）
    tracked_suf: set[str] = set()
    for t in _git(root, "ls-files", "*.py").splitlines():
        tracked_suf |= _dotted_suffixes(t.strip())
    gaps: dict[tuple[str, str], str] = {}
    for rel in files:
        p = root / rel
        if not p.is_file() or not rel.endswith(CODE_EXT):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:  # arch-ok: 读不到 = 本文件没有可核对的引用，文件存在性已在上面单独判错
            continue
        imps = _py_imports(text) if rel.endswith(".py") else set()
        for u in unt:
            if u == rel:
                continue
            why = None
            if u in suf and any(i in suf[u] and i not in tracked_suf and ("." in i or i == Path(u).stem) for i in imps):
                why = "import"
            elif u in text:
                why = "路径引用"
            elif re.search(r"[\"']" + re.escape(os.path.basename(u)) + r"[\"']", text):
                why = "文件名引用"
            if why:
                gaps[(rel, u)] = why
    return [{"file": a, "needs": b, "why": w} for (a, b), w in gaps.items()]


def load_pin(root: Path, mid: str) -> dict | None:
    pp = root / PINS_REL / f"{mid}.json"
    if not pp.exists():
        return None
    d = json.loads(pp.read_text(encoding="utf-8-sig"))      # 坏 pin 直接抛（不能当“没 pin”而静默重钉）
    if not isinstance(d.get("blobs"), dict):
        raise ValueError(f"pin 文件 {mid} 缺 blobs")
    return d


def _blob_exists(root: Path, b: str) -> bool:
    return subprocess.run(["git", "cat-file", "-e", b], cwd=root, capture_output=True, timeout=60).returncode == 0


def manifest_check(ids: list[str], root: Path | None = None, pin: bool = True, worker: str | None = None,
                   untracked: list[str] | None = None, repin: bool | list[str] = False, by: str | None = None) -> dict:
    """pin 语义（cut K 后）：已有 pin 文件的清单默认只校验、不改 pin（别人的检查不能静默重钉已交付清单）；
    pin 只在 ①首次（无 pin 文件）②repin=True（作者显式 --repin）时写，并记 pinned_by / pinned_at。
    已有 pin 时拼树用 pin 里的 blob；工作树文件与 pin 不同只给 warning，清单新增路径不在 pin 里 = error（要作者 --repin）。
    返回 {ok, errors, warnings, pins:{id:{path:blob}}, gaps, lease_hits}；errors 非空 = 不能拼树"""
    root = root or ROOT
    errors: list[str] = []
    warns: list[str] = []
    mans: dict[str, dict] = {}
    for mid in ids:
        try:
            mans[mid] = load_manifest(root, mid)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{mid}：{e}")
    pins: dict[str, dict[str, str]] = {}
    owner: dict[str, tuple[str, str]] = {}
    for mid, m in mans.items():
        pins[mid] = {}
        do_repin = repin is True or (bool(repin) and mid in repin)      # repin=True 全部；列表 = 只重钉这些 id
        try:
            old = None if do_repin else load_pin(root, mid)
        except (ValueError, OSError) as e:
            errors.append(f"{mid}：pin 文件坏了（{e}）；作者 --repin")
            continue
        old_b = (old or {}).get("blobs") or {}
        for rel in all_paths(m):
            if not (root / rel).is_file():
                errors.append(f"{mid}：文件不存在 {rel}")
                continue
            if old is not None:
                if rel not in old_b:
                    errors.append(f"{mid}：清单新增路径 {rel} 不在已有 pin 里（清单作者用 manifest-check --repin 重钉）")
                    continue
                b = old_b[rel]
                if not _blob_exists(root, b):
                    errors.append(f"{mid}：pin 的 blob {b[:7]}（{rel}）不在 git 库里（--repin）")
                    continue
                if blob_of(root, rel) != b:
                    warns.append(f"{mid}：{rel} 工作树已变，按 pin（{b[:7]}）拼树；要纳入新改动由作者 --repin")
            else:
                b = blob_of(root, rel, write=pin)
            pins[mid][rel] = b
            if rel in owner and owner[rel][1] != b:
                errors.append(f"重叠：{rel} 同时在 {owner[rel][0]} 与 {mid}，期望 blob 不同"
                              f"（{owner[rel][1][:7]} vs {b[:7]}）——要约定谁最后改")
            elif rel in owner:
                warns.append(f"{rel} 同时在 {owner[rel][0]} 与 {mid}（blob 相同，无冲突）")
            owner.setdefault(rel, (mid, b))
        for dep in m["depends_on"]:
            if dep not in mans and not manifest_path(root, dep).exists():
                errors.append(f"{mid}：depends_on {dep} 没有这份交付清单")
            elif dep not in mans:
                warns.append(f"{mid}：depends_on {dep} 不在本次 ids 里（要一起发或已入版）")
        for dl in m["deletes"]:
            if (root / dl).exists():
                errors.append(f"{mid}：deletes 的 {dl} 仍在工作树")
    covered = set(owner)
    gaps = []
    for mid, m in mans.items():
        for g in companion_gaps(root, [p for p in all_paths(m) if p in pins[mid]], covered, untracked):
            g["manifest"] = mid
            gaps.append(g)
            errors.append(f"伴随缺口：{mid} 的 {g['file']} {g['why']}了未跟踪、不在任何清单里的 {g['needs']}")
    leases = leases_active(root)
    lease_hits = []
    for mid, m in mans.items():
        w = worker or m.get("worker")
        for rel in all_paths(m):
            for ls in leases:
                if ls["worker"] != w and any(path_match(rel, pat) for pat in ls["paths"]):
                    lease_hits.append({"manifest": mid, "file": rel, "lease_worker": ls["worker"]})
                    warns.append(f"租约：{mid} 的 {rel} 被 {ls['worker']} 租着（到 {ls['expires']}），确认对方已交付")
                    break
    if pin and not errors:
        for mid, d in pins.items():
            pp = root / PINS_REL / f"{mid}.json"
            if pp.exists() and not (repin is True or (bool(repin) and mid in repin)):
                continue
            pp.parent.mkdir(parents=True, exist_ok=True)
            tmp = pp.with_suffix(".tmp")
            tmp.write_text(json.dumps({"schema": "nsfs.deliverable_pin/1", "id": mid, "pinned_at": now_iso(),
                                       "pinned_by": by or mans[mid].get("worker") or "?", "blobs": d},
                                      ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, pp)
    return {"ok": not errors, "errors": errors, "warnings": warns, "gaps": gaps, "lease_hits": lease_hits,
            "pins": pins, "manifests": list(mans)}


def build_list_text(ids: list[str], root: Path | None = None) -> tuple[str, dict]:
    """manifest-check（钉 blob）-> 清单文本（path@blob + 删除项）；有 error 就抛"""
    root = root or ROOT
    missing = [m for m in ids if load_pin(root, m) is None]
    if missing:        # REVIEW-C：发版时不许现场钉当前工作树——必须交付时已 manifest-check 钉过
        raise RuntimeError("交付清单缺 pin 文件（先跑 manifest-check 交付时钉住，发版不现场钉工作树）：" + "、".join(missing))
    rep = manifest_check(ids, root, pin=True)
    if rep["errors"]:
        raise RuntimeError("交付清单检查不过：" + "；".join(rep["errors"][:6]))
    lines = [f"# 由交付清单生成：{' '.join(ids)}（{now_iso()}）"]
    seen: set[str] = set()
    for mid in ids:
        for rel, b in rep["pins"][mid].items():
            if rel.startswith(DATA_NOT_IN_TREE):      # data/ 不进发版树：进树会让快照不链接数据目录（cut K 第 1 次失败根因）
                rep["warnings"].append(f"{rel}：data/ 路径不进发版树（数据文件由部署另行同步）")
                continue
            if rel not in seen:
                lines.append(f"{rel}@{b}")
                seen.add(rel)
        for dl in load_manifest(root, mid)["deletes"]:
            if dl not in seen:
                lines.append(dl)
                seen.add(dl)
    return "\n".join(lines) + "\n", rep


def build_tree_from_manifests(ids: list[str], build_tree_from_list, base: str = "HEAD", repo: Path | None = None) -> dict:
    """build_tree_from_list 由调用方传入（system_version 的那份），本模块不 import 它"""
    repo = repo or ROOT
    text, rep = build_list_text(ids, repo)
    fd, tmp = tempfile.mkstemp(prefix="nsfs_manifest_list_", suffix=".txt")
    os.close(fd)
    try:
        Path(tmp).write_text(text, encoding="utf-8")
        out = build_tree_from_list(Path(tmp), base, repo=repo)
    finally:
        Path(tmp).unlink(missing_ok=True)
    out["manifests"] = ids
    out["warnings"] = rep["warnings"]
    return out


# ------------------------------------------------------------ 租约（建议性）
def path_match(path: str, pat: str) -> bool:
    path, pat = _norm(path), _norm(pat)
    if path == pat or fnmatch.fnmatch(path, pat):
        return True
    return pat.endswith("/") and path.startswith(pat)


def _overlap(a: str, b: str) -> bool:
    return path_match(a, b) or path_match(b, a)


def _read_leases(root: Path) -> list[dict]:
    p = root / LEASE_REL
    if not p.exists():
        return []
    try:
        d = json.loads(p.read_text(encoding="utf-8-sig"))
    except Exception:  # noqa: BLE001  # arch-ok: 租约是建议性的，坏文件 = 当没有租约（不挡发版）
        return []
    return list(d.get("leases") or []) if isinstance(d, dict) else []


def _write_leases(root: Path, leases: list[dict]) -> None:
    p = root / LEASE_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps({"schema": "nsfs.leases/1", "note": "建议性文件租约；过期自动失效；lease take / release / list",
                               "leases": leases}, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def _alive(ls: dict, now: float) -> bool:
    try:
        return datetime.fromisoformat(ls["expires"]).timestamp() > now
    except Exception:  # noqa: BLE001
        return False


def leases_active(root: Path | None = None, now: float | None = None) -> list[dict]:
    now = now if now is not None else time.time()
    return [x for x in _read_leases(root or ROOT) if _alive(x, now)]


def lease_take(worker: str, paths: list[str], root: Path | None = None, ttl_h: float = DEFAULT_TTL_H,
               now: float | None = None) -> dict:
    """同一 worker 再租 = 合并 + 续期。别人的租约与本次路径重叠 -> 仍记下，但返回 conflicts（建议性）"""
    root = root or ROOT
    now = now if now is not None else time.time()
    paths = [_norm(p) for p in paths]
    live = leases_active(root, now)
    conflicts = [{"path": p, "worker": x["worker"], "pattern": q, "expires": x["expires"]}
                 for p in paths for x in live if x["worker"] != worker for q in x["paths"] if _overlap(p, q)]
    mine = next((x for x in live if x["worker"] == worker), None)
    others = [x for x in live if x is not mine]
    rec = {"worker": worker, "paths": list(dict.fromkeys([*(mine["paths"] if mine else []), *paths])),
           "taken": (mine or {}).get("taken") or now_iso(now), "expires": now_iso(now + ttl_h * 3600)}
    _write_leases(root, [*others, rec])
    return {"lease": rec, "conflicts": conflicts}


def lease_release(worker: str, paths: list[str] | None = None, root: Path | None = None, now: float | None = None) -> dict:
    root = root or ROOT
    live = leases_active(root, now)
    out, released = [], []
    norm = [_norm(p) for p in paths or []]
    for x in live:
        if x["worker"] != worker:
            out.append(x)
        elif not norm:
            released.extend(x["paths"])
        else:
            keep = [q for q in x["paths"] if q not in norm]
            released.extend(q for q in x["paths"] if q in norm)
            if keep:
                out.append({**x, "paths": keep})
    _write_leases(root, out)
    return {"worker": worker, "released": released}
