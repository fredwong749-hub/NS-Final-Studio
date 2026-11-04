"""cut 七门 / 工人测试搬到 gpu33 跑（W45 SERVER-DEV，总调度 11-04 03:1x 派；配置 config/qa/remote_dev.json）。

项目方原话：“笔记本本来不适合做任务重的开发,gpu那2台服务器内存那么大,gpu 3090那么多卡,你不用,在这台笔记本做干嘛?”
笔记本只保留：改代码、推文件、读结果、git commit / tag / push（发版最后一步仍在笔记本：仓库和 sv 标签在这里）。

做法（笔记本 ↔ 服务器链路只有 ~170 KB/s，整棵树 ~390 MB 推不动 → 按 git blob sha 增量）：
  1. plan   ：笔记本发冻结树清单（ls-tree：mode / blob sha / 路径）→ 服务器在“上一份自己的快照”和 producer 仓库（只读）里
              按 blob sha 找现成文件 → 回报缺哪些
  2. build  ：笔记本只推缺的 blob（git cat-file，tar.gz）→ 服务器在独立目录拼出完整冻结树（自己的旧快照硬链、producer 仓库复制、
              推来的逐个核 sha），数据目录（笔记本 .gitignore 口径的 data/、assets …）按 system_version.build_snapshot 同口径从 producer
              仓库硬链进来（不带 pid / 锁 / 心跳文件）
  3. spawn  ：后台起闸门（system_version.gates 原样，在快照目录、用服务器 venv 跑；nice、CUDA_VISIBLE_DEVICES 置空）
  4. 轮询    ：每 poll_s 秒拉增量输出；完成后拉回 result.json（每门结果 + 耗时）与完整 pytest 输出（落笔记本 data/system_versions/）
服务器上只写 snap_root（cut 快照）与 work_root（venv / inbox / 工人临时副本）两个目录；不删任何东西（同名快照先改名 .old<ts>）。

  python tools/qa/remote_gates.py gates [--tree T | --worktree] [--sv ID] [--no-tests] [--host gpu33] [--report-json F]
  python tools/qa/remote_gates.py wait --job <服务器 job 目录>          # 断线后重新接上一个还在跑的远端任务
  system_version.py cut --on gpu33 …                                   # 发版走这条（release.json gates_on 为默认）
服务器内部入口：_op <plan|build|spawn> <inbox 目录>、_gates_run <job 目录>（笔记本不直接用）。
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.util
import io
import json
import os
import posixpath
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CFG_REL = "config/qa/remote_dev.json"
RUNNER_FILES = ("tools/qa/remote_gates.py", "tools/qa/system_version.py")
GATE_OF = {"syntax_guard.py": "syntax", "compile.py": "kb", "arch_scan.py": "arch", "regression_check.py": "vqa_regress",
           "decision_check.py": "decision", "decision_propagation.py": "propagation"}
SKIP_DATA = (".git", ".venv", ".pytest_cache", "nsfs_cut_snapshots")
LATEST = "_latest.json"
OV_PREFIX = "__overlay__/"
EVIDENCE_SRC = ("knowledge/rules/*.yaml", "config/owner_decisions.yaml", "data/vqa/regression/*.json")   # 后者 = VQA 回归集闸门的用例图


# ---------------------------------------------------------------- 通用
def load_cfg(root: Path | None = None) -> dict:
    """配置缺失 = 直接报错（失败关闭：不猜服务器路径）"""
    return json.loads(((root or ROOT) / CFG_REL).read_text(encoding="utf-8"))


def _mod(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


def load_sv():
    """同目录的 system_version.py（笔记本 = 仓库里的；服务器 = 随 runner 推过去的同一份）"""
    return sys.modules.get("ns_system_version_w45") or _mod(Path(__file__).with_name("system_version.py"), "ns_system_version_w45")


def check_dest(path: str, cfg: dict) -> str:
    """服务器上只许写 snap_root / work_root 之下（红线）；含 .. 一律拒绝"""
    p = posixpath.normpath(str(path))
    roots = [posixpath.normpath(cfg["snap_root"]), posixpath.normpath(cfg["work_root"])]
    if ".." in str(path).split("/") or not any(p.startswith(r + "/") for r in roots):
        raise ValueError(f"W45 只许写 {roots} 之下：{path}")
    return p


def atomic_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp{os.getpid()}")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def git_exe(repo: Path | None = None) -> str:
    """笔记本 WSL 里仓库在 /mnt/<盘>/：Linux git 每次都要重算 Windows git 写的 index（实测 git add -A 5 分钟）→ 改用 git.exe"""
    if os.name != "nt" and str(repo or ROOT).startswith("/mnt/") and shutil.which("git.exe"):
        return "git.exe"
    return "git"


def git_bytes(args: list[str], repo: Path | None = None, input: bytes | None = None, timeout: int = 900, env: dict | None = None) -> bytes:
    r = subprocess.run([git_exe(repo), *args], cwd=repo or ROOT, input=input, capture_output=True, timeout=timeout, env=env)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)[:80]} 失败：{r.stderr.decode('utf-8', 'replace')[-400:]}")
    return r.stdout


# ---------------------------------------------------------------- 笔记本：树清单 / 缺的 blob 打包
LFS_HDR = b"version https://git-lfs.github.com/spec/v1"
_LFS_SRC: dict[str, Path] = {}          # 真内容 blob sha → 笔记本上的文件（.git/lfs/objects 或工作树）
_LFS_PTR: dict[str, str] = {}           # 真内容 blob sha → 指针 blob sha（限速期“延后”用）


def tree_manifest(tree: str, repo: Path | None = None, lfs: bool = True, log=None) -> list[list[str]]:
    """[[mode, blob sha, 路径], …]；子模块（160000）照样列出（服务器只建空目录，和 git archive 一致）。
    Git LFS（*.png / *.wav / *.mp4 …）：git archive 会 smudge 成真内容，cat-file 只有指针 → 换成真内容的 blob sha（见 lfs_resolve）"""
    out, sizes = [], {}
    for e in git_bytes(["ls-tree", "-r", "-l", "-z", "--full-tree", tree], repo).split(b"\0"):
        if not e:
            continue
        meta, path = e.split(b"\t", 1)
        mode, _typ, sha, size = meta.decode().split()
        p = path.decode("utf-8")
        out.append([mode, sha, p])
        sizes[p] = int(size) if size.isdigit() else -1
    if lfs:
        bad = lfs_resolve(out, sizes, repo)
        if bad and log:
            log(f"[w45] ⚠ {len(bad)} 个 LFS 文件本机没有真内容（仍推指针）：{bad[:5]}")
    return out


def lfs_resolve(manifest: list, sizes: dict, repo: Path | None = None) -> list[str]:
    """LFS 指针 → 真内容：先 .git/lfs/objects/<oid>（按 oid 不可变，真内容的 blob sha 按 oid 缓存，只算一次），
    再工作树同路径文件（大小与 sha256 都对才用）。→ 解析不了的路径"""
    import re
    repo = repo or ROOT
    cand = [e for e in manifest if e[0] in ("100644", "100755") and 0 <= sizes.get(e[2], -1) <= 300]
    if not cand:
        return []
    blobs = cat_blobs(sorted({e[1] for e in cand}), repo)
    cp = repo / SHA_CACHE_REL
    cache = json.loads(cp.read_text(encoding="utf-8")) if cp.is_file() else {}
    n0, bad = len(cache), []
    for e in cand:
        data = blobs.get(e[1], b"")
        if not data.startswith(LFS_HDR):
            continue
        m = re.search(rb"oid sha256:([0-9a-f]{64})", data)
        z = re.search(rb"size (\d+)", data)
        if not m:
            bad.append(e[2])
            continue
        oid, size = m.group(1).decode(), int(z.group(1)) if z else -1
        src = repo / ".git/lfs/objects" / oid[:2] / oid[2:4] / oid
        if not src.is_file():
            wt = repo / e[2]
            src = wt if (wt.is_file() and wt.stat().st_size == size and hashlib.sha256(wt.read_bytes()).hexdigest() == oid) else None
        if src is None:
            bad.append(e[2])
            continue
        key = "lfs:" + oid
        if key not in cache:
            cache[key] = blob_sha_file(src)
        _LFS_PTR[cache[key]] = e[1]
        e[1] = cache[key]
        _LFS_SRC[e[1]] = src
    if len(cache) != n0:
        atomic_json(cp, cache)
    return bad


def cat_blobs(shas: list[str], repo: Path | None = None) -> dict[str, bytes]:
    if not shas:
        return {}
    raw = git_bytes(["cat-file", "--batch"], repo, input=("\n".join(shas) + "\n").encode(), timeout=1800)
    res, i = {}, 0
    while i < len(raw):
        nl = raw.index(b"\n", i)
        hdr = raw[i:nl].decode().split()
        if len(hdr) < 3:
            raise RuntimeError(f"git cat-file 缺对象：{hdr}")
        size = int(hdr[2])
        res[hdr[0]] = raw[nl + 1:nl + 1 + size]
        i = nl + 1 + size + 1
    return res


def blob_tar(entries: list[list[str]], repo: Path | None = None, overlay: dict | None = None) -> bytes:
    """缺的文件 → tar.gz（权限按 git mode；120000 = 软链）；overlay = {sha: 字节} 放在 __overlay__/<sha>"""
    blobs = cat_blobs(sorted({e[1] for e in entries if e[1] not in _LFS_SRC}), repo)
    blobs.update({e[1]: _LFS_SRC[e[1]].read_bytes() for e in entries if e[1] in _LFS_SRC})
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz", compresslevel=6) as tf:
        for sha, data in sorted((overlay or {}).items()):
            ti = tarfile.TarInfo(OV_PREFIX + sha)
            ti.size = len(data)
            tf.addfile(ti, io.BytesIO(data))
        for mode, sha, path in entries:
            data = blobs[sha]
            ti = tarfile.TarInfo(path)
            ti.mtime = int(time.time())
            if mode == "120000":
                ti.type, ti.linkname = tarfile.SYMTYPE, data.decode("utf-8")
                tf.addfile(ti)
                continue
            ti.size, ti.mode = len(data), 0o755 if mode == "100755" else 0o644
            tf.addfile(ti, io.BytesIO(data))
    return buf.getvalue()


def worktree_tree(repo: Path | None = None) -> str:
    """此刻工作树（.gitignore 口径，含未跟踪）写成一棵树：复制 .git/index 当临时 index（stat 缓存有效，不全量重算 hash），不动真 index"""
    repo = repo or ROOT
    gitdir = repo / ".git"
    fd, idx = tempfile.mkstemp(prefix="nsfs_w45_index_", dir=str(gitdir))   # 放 .git 里：git.exe 也能按 Windows 路径读
    os.close(fd)
    try:
        shutil.copyfile(gitdir / "index", idx)
        env = {**os.environ, "GIT_INDEX_FILE": idx}
        if git_exe(repo) == "git.exe":       # WSL → Windows 进程：WSLENV /p 把路径翻成 D:\…
            env["WSLENV"] = ":".join(x for x in (os.environ.get("WSLENV"), "GIT_INDEX_FILE/p") if x)
        git_bytes(["add", "-A"], repo, timeout=1800, env=env)
        return git_bytes(["write-tree"], repo, timeout=600, env=env).decode().strip()
    finally:
        Path(idx).unlink(missing_ok=True)       # 自己刚建的临时 index（不是项目文件）


def ignored_paths(repo: Path | None = None) -> list[str]:
    """同 system_version.ignored_paths（.gitignore 挡住的数据目录），走 git_exe（WSL 快）"""
    out = git_bytes(["status", "--ignored", "--porcelain=v1", "-z"], repo, timeout=900).decode("utf-8", "replace")
    return [e[3:].rstrip("/") for e in out.split("\0") if e.startswith("!! ")]


def overlay_refs(root: Path | None = None, extra: list[str] | None = None) -> list[str]:
    """闸门要核的笔记本数据：知识库规则 / owner_decisions 里引用的 data/、assets*/、apps/web/e2e/ 路径 + 配置 overlay_paths（例 data/sysarch/baseline.json）"""
    import re
    root = root or ROOT
    rx = re.compile(r"(?<![\w/])((?:data|assets|assets_v2|apps/web/e2e|docs|ops/logs)/[A-Za-z0-9_\-./]+)")   # 被 .gitignore 挡住的证据（已跟踪的在树里，放置时自动跳过）
    refs = set(extra or [])
    for pat in EVIDENCE_SRC:
        for f in sorted(root.glob(pat)):
            refs |= {m.rstrip(".,/") for m in rx.findall(f.read_text(encoding="utf-8"))}
    return sorted(r for r in refs if r)


def overlay_list(root: Path | None = None, extra: list[str] | None = None, big: int = 1_000_000) -> tuple[list, list[str]]:
    """→ ([[rel, blob sha, presence_only]], 目录)。只取笔记本上真实存在的；> big 字节的只要求“在”（服务器有就用服务器的）"""
    root = root or ROOT
    files, dirs = [], []
    tracked = set(git_bytes(["ls-files", "-z"], root).decode("utf-8", "replace").split("\0")) if (root / ".git").exists() else set()
    for rel in overlay_refs(root, extra):
        if rel in tracked:            # 已跟踪的在冻结树里，不重复推
            continue
        p = root / rel
        if p.is_file() and not p.is_symlink():
            files.append([rel, blob_sha_file(p), p.stat().st_size > big])
        elif p.is_dir():
            dirs.append(rel)
    return files, dirs


SHA_CACHE_REL = "data/qa/remote_gates/sha_cache.json"


def mirror_list(mcfg: dict, root: Path | None = None, cache: dict | None = None) -> list[list]:
    """B 方案镜像范围：roots 下非媒体、≤max_bytes、不在 skip_prefixes 的文件 + extra（文件或目录）。→ [[rel, sha, False]]。
    sha 按 (大小, mtime_ns) 缓存（cache 传入就就地更新），每次 cut 不用把 1 万个文件全读一遍"""
    root = root or ROOT
    skip = tuple(mcfg.get("skip_prefixes") or ())
    media = tuple(x.lower() for x in mcfg.get("media_exts") or ())
    cap = int(mcfg.get("max_bytes") or 1_000_000)
    cache = {} if cache is None else cache
    picked: dict[str, os.stat_result] = {}

    def walk(rel_dir: str, force: bool):
        base = root / rel_dir
        if base.is_file():
            picked[rel_dir] = base.stat()
            return
        for dp, dns, fns in os.walk(base):
            rd = Path(dp).relative_to(root).as_posix()
            if not force:
                dns[:] = [d for d in dns if not (rd + "/" + d + "/").startswith(skip) and not (rd + "/" + d).startswith(skip)
                          and d not in ("__pycache__", "node_modules")]
            for f in fns:
                rel = rd + "/" + f
                if not (Path(dp) / f).is_file():      # 坏链接 / 列出后被挪走的活文件
                    continue
                st = (Path(dp) / f).stat()
                if force or (not rel.startswith(skip) and not rel.lower().endswith(media) and st.st_size <= cap
                             and not live_pid_name(f)):
                    picked[rel] = st
    for r in mcfg.get("roots") or []:
        if (root / r).is_dir():
            walk(r, False)
    for r in mcfg.get("extra") or []:
        if (root / r).exists():
            walk(r, True)
    out = []
    for rel, st in sorted(picked.items()):
        if not (root / rel).is_file():
            continue
        c = cache.get(rel)
        if not (c and c[0] == st.st_size and c[1] == st.st_mtime_ns):
            c = cache[rel] = [st.st_size, st.st_mtime_ns, blob_sha_file(root / rel)]
        out.append([rel, c[2], False])
    return out


def live_pid_name(name: str) -> bool:
    import re
    return bool(re.search(r"(\.pid|\.pid\.json|\.lock|_pid\.json)$|^autoflow_resident\.json$|^api_restart\.json$", name, re.I))


def merged_overlay(cfg: dict, root: Path | None = None) -> tuple[list, list[str]]:
    """证据覆盖层（知识库 / 决策账本引用）+ B 方案镜像；同一路径以证据层为准（保留 presence_only 口径）。sha 缓存落 data/qa/remote_gates/"""
    root = root or ROOT
    files, dirs = overlay_list(root, cfg.get("overlay_paths"))
    m = cfg.get("mirror")
    if m:
        cp = root / SHA_CACHE_REL
        cache = json.loads(cp.read_text(encoding="utf-8")) if cp.is_file() else {}
        have = {f[0] for f in files}
        files += [e for e in mirror_list(m, root, cache) if e[0] not in have]
        atomic_json(cp, cache)
    return files, dirs


def wait_run_sync_tick(cfg: dict, host: str, seen: str | None, root: Path | None = None, sleep=time.sleep, clock=time.time) -> str | None:
    """等 run_sync 完成新的一拍（state 的 last:<host>.at 变了）再发下一批；最多 wait_tick_s（run_sync 没在跑就不等死）"""
    m = cfg.get("mirror") or {}
    p = (root or ROOT) / (m.get("run_sync_state") or "data/autopilot/run_sync.json")
    t0 = clock()

    def cur():
        return (json.loads(p.read_text(encoding="utf-8")).get(f"last:{host}") or {}).get("at") if p.is_file() else None
    while clock() - t0 < float(m.get("wait_tick_s") or 300):
        at = cur()
        if seen is not None and at != seen:
            return at
        if seen is None:
            seen = at
        sleep(5)
    return cur()


def throttle_of(cfg: dict, root: Path | None = None) -> dict | None:
    """限速段（总调度 11-04：ep01 出视频期间让路）；until_file 在笔记本出现 = 解除"""
    t = cfg.get("throttle")
    if not t or (t.get("until_file") and ((root or ROOT) / t["until_file"]).exists()):
        return None
    return t


def push_overlay(cfg: dict, host: str, ov_files: list, need: set, ov_root: Path | None, sh_fn=None, log=print, gate=None,
                 reader=None, what: str = "镜像", sleep_fn=time.sleep) -> dict:
    """要推的 blob 分批（压缩后 ≤ batch_mb）进服务器内容寻址库；每批前等 run_sync 一拍（gate 可替换，测试用）。
    现读现算 sha：活的日志两次读之间会变 → 以真正打包的字节为准，清单跟着改"""
    cap = float((cfg.get("mirror") or {}).get("batch_mb") or 6) * 1e6
    thr = throttle_of(cfg)
    if thr:
        cap = min(cap, float(thr.get("batch_mb") or 1) * 1e6)
    todo = [e for e in ov_files if e[1] in need]
    gate = gate or ((lambda seen: seen) if thr else (lambda seen: wait_run_sync_tick(cfg, host, seen)))   # 限速生效时由限速控链路，不再叠加等拍
    seen, sent, nbytes, batch, size = None, 0, 0, {}, 0

    def flush():
        nonlocal seen, sent, nbytes, batch, size
        if not batch:
            return None
        seen = gate(seen)
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz", compresslevel=6) as tf:
            for sha, data in batch.items():
                ti = tarfile.TarInfo(OV_PREFIX + sha)
                ti.size = len(data)
                tf.addfile(ti, io.BytesIO(data))
        blob = buf.getvalue()
        t_send = time.time()
        for k in range(3):            # 链路断（rc 255）：等下一拍 run_sync 再试这一批，3 次都不行才放弃（已推的批次留在库里，下次只补缺）
            r = call_op(cfg, host, "store", {"store": cfg["snap_root"] + "/_blobs"}, blob,
                        timeout=max(float(cfg.get("op_timeout_s") or 900), len(blob) / 50_000 + 300), sh_fn=sh_fn)
            if not r.get("error"):
                break
            log(f"[w45] {what}批次失败（第 {k + 1}/3 次）：{r['error'][:160]}")
            seen = gate(seen)
        if r.get("error"):
            return r
        sent += len(batch)
        nbytes += len(blob)
        if thr:                       # 限速：批后睡到平均 ≤ max_kbps
            pause = len(blob) / (float(thr.get("max_kbps") or 50) * 1000) - (time.time() - t_send)
            if pause > 0:
                sleep_fn(pause)
        log(f"[w45] {what}批次：{len(batch)} 个 blob，{len(blob) / 1e6:.2f} MB gz（累计 {sent}/{len(todo)}）")
        batch, size = {}, 0
        return None
    gone = []
    for ent in todo:
        if reader is not None:        # 树里的 blob（git 对象 / LFS 真内容）
            data = reader(ent)
        else:
            f = ov_root / ent[0]
            if not f.is_file():       # 活目录：列清单之后被别人挪走 / 改名（例 asset_jobs/_recheck）→ 这次不带
                gone.append(ent[0])
                continue
            data = f.read_bytes()
        ent[1] = hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()
        if ent[1] in batch:
            continue
        batch[ent[1]] = data
        size += len(zlib.compress(data, 1))   # 按压缩后字节计批（真正占链路的量）：文字压缩率高，按原始字节计会每拍只发 1 MB
        if size >= cap:
            err = flush()
            if err:
                return err
    err = flush()
    if gone:
        ov_files[:] = [e for e in ov_files if e[0] not in set(gone)]
        log(f"[w45] 镜像：{len(gone)} 个文件推送前已不在（跳过）：{gone[:5]}")
    return err or {"sent": sent, "bytes": nbytes, "gone": len(gone)}


def mirror_once(cfg: dict, host: str, sh_fn=None, log=print, gate=None, root: Path | None = None) -> dict:
    """只同步笔记本数据（不建快照）：问服务器缺哪些 sha → 分批推"""
    t0 = time.time()
    files, _dirs = merged_overlay(cfg, root)
    plan = call_op(cfg, host, "plan", {"manifest": [], "overlay": files, "store": cfg["snap_root"] + "/_blobs", "prod": cfg["prod_repo"]},
                   sh_fn=sh_fn)
    if plan.get("error"):
        return plan
    need = set(plan.get("overlay_missing") or [])
    log(f"[w45] 镜像：笔记本数据 {len(files)} 个，服务器缺 {len(need)} 个 blob")
    r = push_overlay(cfg, host, files, need, root or ROOT, sh_fn=sh_fn, log=log, gate=gate) if need else {"sent": 0, "bytes": 0}
    return {**r, "files": len(files), "missing": len(need), "s": round(time.time() - t0, 1)}


def mirror_lfs(cfg: dict, host: str, tree: str, sh_fn=None, log=print, repo: Path | None = None) -> dict:
    """补齐限速期延后的 LFS 真内容：树里服务器缺的文件（含 LFS 真内容）分批进内容寻址库（限速段仍生效）"""
    manifest = tree_manifest(tree, repo, log=log)
    plan = call_op(cfg, host, "plan", {"dest": "-", "manifest": manifest, "latest_roots": latest_roots(cfg), "prod": cfg["prod_repo"],
                                       "store": cfg["snap_root"] + "/_blobs"}, sh_fn=sh_fn)
    if plan.get("error"):
        return plan
    need = [e for e in manifest if e[2] in set(plan["missing"]) and e[0] not in ("120000", "160000")]
    log(f"[w45] LFS / 代码补齐：服务器缺 {len(need)} 个")
    small = cat_blobs(sorted({e[1] for e in need if e[1] not in _LFS_SRC}), repo)
    ents = [[e[2], e[1], False] for e in need]
    return push_overlay(cfg, host, ents, {e[1] for e in ents}, None, sh_fn=sh_fn, log=log, gate=lambda seen: seen, what="代码",
                        reader=lambda ent: _LFS_SRC[ent[1]].read_bytes() if ent[1] in _LFS_SRC else small[ent[1]]) if ents else {"sent": 0}


def expand_data_rels(rels: list[str], root: Path | None = None) -> list[str]:
    """被忽略的整目录（data/、assets …）展开到下一层：服务器只接笔记本上也有的子目录（服务器独有的旧隔离区等不带进来，D-CLN-09）"""
    root = root or ROOT
    out = []
    for rel in rels:
        p = root / rel
        if p.is_dir() and not p.is_symlink() and "/" not in rel.strip("/"):
            out += [f"{rel.strip('/')}/{c.name}" for c in sorted(p.iterdir())]
        else:
            out.append(rel)
    return out


# ---------------------------------------------------------------- 笔记本 → 服务器：一次调用
def runner_bundle(args: dict, payload: bytes | None = None, root: Path | None = None) -> bytes:
    root = root or ROOT
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for rel in RUNNER_FILES:
            tf.add(str(root / rel), arcname="runner/" + rel)
        for name, data in (("args.json", json.dumps(args, ensure_ascii=False).encode("utf-8")), ("payload.bin", payload)):
            if data is None:
                continue
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            tf.addfile(ti, io.BytesIO(data))
    return buf.getvalue()


def _rssh():
    return sys.modules.get("ns_rssh_w45") or _mod(ROOT / "tools/netfix/rssh.py", "ns_rssh_w45")


def remote_sh(host: str, cmd: str, data: bytes | None = None, timeout: float = 900) -> subprocess.CompletedProcess:
    """经 tools/netfix/rssh（常驻主连接，rc=255 退避重试）；Windows 与 WSL 都能用"""
    return _rssh().run_retry(host, cmd, input=data, timeout=timeout, tries=3)


def op_cmd(cfg: dict, op: str) -> str:
    w, py = shlex.quote(cfg["work_root"]), shlex.quote(cfg["remote_python"])
    return (f"set -e; mkdir -p {w}/inbox; T=$(mktemp -d {w}/inbox/{op}.XXXXXX); tar xzf - -C \"$T\"; "
            f"{py} \"$T/runner/tools/qa/remote_gates.py\" _op {op} \"$T\"")


def last_json(text: str) -> dict | None:
    for ln in reversed((text or "").strip().splitlines()):
        if ln.startswith("{"):
            return json.loads(ln)
    return None


def call_op(cfg: dict, host: str, op: str, args: dict, payload: bytes | None = None, timeout: float | None = None,
            sh_fn=None) -> dict:
    """服务器上跑一个 op（随身带 runner：remote_gates.py + system_version.py，~30 KB）；→ op 的 JSON 结果或 {"error": …}"""
    blob = runner_bundle(args, payload)
    res = (sh_fn or remote_sh)(host, op_cmd(cfg, op), blob, timeout or float(cfg.get("op_timeout_s") or 900))
    out = (res.stdout or b"").decode("utf-8", "replace")
    err = (res.stderr or b"").decode("utf-8", "replace")
    js = last_json(out) if res.returncode == 0 else None
    if js is None:
        return {"error": f"{host} op {op} rc={res.returncode}：{(err or out)[-600:]}"}
    return js


# ---------------------------------------------------------------- 服务器：plan / build / spawn
def blob_sha_file(p: Path) -> str:
    data = p.read_bytes()
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def cache_dirs(args: dict) -> list[str]:
    """候选来源（按序）：各 latest_root 下 _latest.json 指的上一份快照 → producer 仓库（只读，复制不硬链）"""
    out = []
    for r in args.get("latest_roots") or []:
        p = Path(r) / LATEST
        if p.is_file():
            d = json.loads(p.read_text(encoding="utf-8")).get("dir")
            if d and Path(d).is_dir() and d != args.get("dest"):
                out.append(d)
    out += [c for c in args.get("caches") or [] if Path(c).is_dir()]
    if args.get("prod") and Path(args["prod"]).is_dir():
        out.append(args["prod"])
    return out


def find_sources(manifest: list, caches: list[str], store: str | None = None) -> tuple[dict, list[str]]:
    """每个文件的现成来源：内容寻址库 store/<sha>（分批推来的）→ 各候选目录同路径（核 blob sha）"""
    src, missing = {}, []
    for mode, sha, path in manifest:
        if mode == "160000":
            continue
        if store and mode != "120000" and (Path(store) / sha).is_file() and blob_sha_file(Path(store) / sha) == sha:
            src[path] = str(Path(store) / sha)
            continue
        for c in caches if mode != "120000" else []:
            f = Path(c) / path
            if f.is_file() and not f.is_symlink() and blob_sha_file(f) == sha:
                src[path] = str(f)
                break
        else:
            missing.append(path)
    return src, missing


def overlay_missing(args: dict) -> list[str]:
    """笔记本独有数据（闸门要核的证据文件）：[[rel, sha, presence_only]]。presence_only（大文件）且 producer 仓库有同路径 = 用服务器的；
    否则看服务器内容寻址库 store/<sha>（核 sha）→ 没有就要推。→ 要推的 sha"""
    store, prod = Path(args.get("store") or "/nonexistent"), Path(args.get("prod") or "/nonexistent")
    out = []
    for rel, sha, presence in args.get("overlay") or []:
        if presence and (prod / rel).is_file():
            continue
        f = store / sha
        if not (f.is_file() and blob_sha_file(f) == sha):
            out.append(sha)
    return sorted(set(out))


def op_plan(args: dict) -> dict:
    caches = cache_dirs(args)
    src, missing = find_sources(args["manifest"], caches, args.get("store"))
    hits = {c: sum(1 for v in src.values() if v.startswith(c.rstrip("/") + "/")) for c in caches + [args.get("store") or "-"]}
    return {"missing": missing, "files": len(args["manifest"]), "hits": hits, "overlay_missing": overlay_missing(args)}


def place_overlay(dest: Path, args: dict) -> int:
    """在接数据之前放：store/<sha> 硬链到 dest/rel（之后 _hardlink_tree 遇到已存在的文件跳过 → 笔记本版本优先）"""
    store, prod, n = Path(args.get("store") or "/nonexistent"), Path(args.get("prod") or "/nonexistent"), 0
    for rel, sha, presence in args.get("overlay") or []:
        if presence and (prod / rel).is_file():
            continue
        dst = dest / rel
        if dst.exists():
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(store / sha, dst)
        except OSError:
            shutil.copy2(store / sha, dst)
        n += 1
    return n


def link_data(dest: Path, prod: Path, rels: list[str], sv) -> int:
    """数据按 build_snapshot 同口径：目录逐文件硬链（不带 pid / 锁 / 心跳），超大目录（JUNCTION_OK）软链，单文件硬链"""
    linked = 0
    for rel in rels:
        rel = rel.rstrip("/")
        if not rel or rel.startswith(SKIP_DATA) or "__pycache__" in rel or rel.endswith(".pyc") or rel.endswith("_selftest_take"):
            continue
        src, dst = prod / rel, dest / rel
        if not src.exists() or dst.is_symlink() or (dst.exists() and not (src.is_dir() and dst.is_dir())):
            continue
        if src.is_dir() and not rel.endswith(sv.JUNCTION_OK):
            linked += sv._hardlink_tree(src, dst)      # 目录已在（覆盖层先放的）→ 逐文件补，已存在的不动
        elif not sv.LIVE_PID_RE.search(src.name):
            sv._link(src, dst)
            linked += 1
    return linked


def store_blobs(tf: tarfile.TarFile, members: list, store: Path) -> int:
    """__overlay__/<sha> → store/<sha>（逐个核 sha，先写临时名再原子改名）"""
    if members:
        store.mkdir(parents=True, exist_ok=True)
    for m in members:
        sha = m.name[len(OV_PREFIX):]
        if len(sha) != 40 or not all(c in "0123456789abcdef" for c in sha):
            raise ValueError(f"覆盖层 blob 名不合法：{m.name}")
        tmp = store / f".{sha}.tmp{os.getpid()}"
        tmp.write_bytes(tf.extractfile(m).read())
        if blob_sha_file(tmp) != sha:
            raise ValueError(f"覆盖层 blob sha 不符：{sha}")
        os.replace(tmp, store / sha)
    return len(members)


def op_store(args: dict, payload: Path | None) -> dict:
    """镜像分批推送：只往内容寻址库写（不碰任何快照）"""
    if payload is None:
        return {"stored": 0}
    with tarfile.open(payload) as tf:
        mem = tf.getmembers()
        bad = [m.name for m in mem if not m.name.startswith(OV_PREFIX)]
        if bad:
            raise ValueError(f"store 包里有非 blob 条目：{bad[:5]}")
        return {"stored": store_blobs(tf, mem, Path(args["store"]))}


def op_build(args: dict, payload: Path | None, sv=None, own_roots: list[str] | None = None) -> dict:
    """拼冻结树 → dest（已存在先改名 .old<ts>，不删）；推来的逐个核 blob sha；缺一个就失败关闭"""
    t0 = time.time()
    dest = Path(args["dest"])
    if dest.exists():
        dest.rename(dest.with_name(dest.name + f".old{int(time.time())}"))
    dest.mkdir(parents=True)
    want = {p: (m, s) for m, s, p in args["manifest"]}
    ov_shas = {sha for _r, sha, _p in args.get("overlay") or []}
    got = set()
    if payload is not None:
        with tarfile.open(payload) as tf:
            mem = tf.getmembers()
            for m in mem:
                ok_ov = m.name.startswith(OV_PREFIX) and m.name[len(OV_PREFIX):] in ov_shas
                if not ok_ov and (m.name not in want or m.name.startswith("/") or ".." in m.name.split("/")):
                    raise ValueError(f"推来的包里有清单外的路径：{m.name}")
            store_blobs(tf, [m for m in mem if m.name.startswith(OV_PREFIX)], Path(args.get("store") or "/nonexistent"))
            tree_mem = [m for m in mem if not m.name.startswith(OV_PREFIX)]
            tf.extractall(dest, members=tree_mem, filter="tar") if hasattr(tarfile, "tar_filter") else tf.extractall(dest, members=tree_mem)
            got = {m.name for m in tree_mem}
    errors = [p for p in got if want[p][0] != "120000" and blob_sha_file(dest / p) != want[p][1]]
    caches = cache_dirs(args)
    src, missing = find_sources([[m, s, p] for p, (m, s) in want.items() if p not in got], caches, args.get("store"))
    errors += missing
    own = [os.path.normpath(r) + os.sep for r in (own_roots if own_roots is not None else args.get("latest_roots") or [])]
    n_link = n_copy = n_store = 0
    store_pre = os.path.normpath(args["store"]) + os.sep if args.get("store") else None
    for p, (mode, _sha) in want.items():
        dst = dest / p
        if mode == "160000":
            dst.mkdir(parents=True, exist_ok=True)
            continue
        if p in got or p not in src:
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        if any(os.path.normpath(src[p]).startswith(r) for r in own):
            try:
                os.link(src[p], dst)          # 自己的上一份快照 / 内容寻址库：硬链（不占空间）
                if store_pre and os.path.normpath(src[p]).startswith(store_pre):
                    n_store += 1
                else:
                    n_link += 1
                if mode == "100755":
                    dst.chmod(0o755)
                continue
            except OSError:
                pass                          # 跨盘等 → 复制
        shutil.copy2(src[p], dst)             # producer 仓库：只复制，不硬链（快照里的写不回生产代码）
        n_copy += 1
        if mode == "100755":
            dst.chmod(0o755)
    if errors:
        return {"error": f"拼树失败（{len(errors)} 个文件缺失或 sha 不符）：{sorted(errors)[:20]}", "dest": str(dest)}
    sv = sv or load_sv()
    n_ov = place_overlay(dest, args)
    linked = link_data(dest, Path(args["prod"]), args.get("data_rels") or [], sv) if args.get("prod") else 0
    for d in args.get("overlay_dirs") or []:
        (dest / d).mkdir(parents=True, exist_ok=True)       # 证据目录：笔记本有、服务器没有 → 至少目录在
    if args.get("latest_root"):
        atomic_json(Path(args["latest_root"]) / LATEST, {"dir": str(dest), "tree": args.get("tree"), "at": time.strftime("%F %T")})
    return {"dest": str(dest), "files": len(want), "pushed": len(got), "hardlinked": n_link, "copied": n_copy, "from_store": n_store, "linked": linked, "overlay": n_ov,
            "build_s": round(time.time() - t0, 1)}


SPAWN_SH = 'cd "$1"; shift; "$@" > "$J/out.log" 2>&1; echo $? > "$J/rc.tmp"; mv "$J/rc.tmp" "$J/rc"'


def job_env(dest: str, sv, extra: dict | None = None, py: str | None = None) -> dict:
    py = py or sys.executable
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", "NS_FREEZE_EXEMPT": "1", "CUDA_VISIBLE_DEVICES": "",
           "PYTHONPATH": os.pathsep.join(str(Path(dest) / x) for x in sv.PY_PATHS), "PY": py, "NS_REMOTE_DEV": "1",
           "PATH": str(Path(py).parent) + os.pathsep + os.environ.get("PATH", "")}
    env.update({k: str(v) for k, v in (extra or {}).items()})
    return env


def op_spawn(args: dict, runner_dir: Path, sv=None) -> dict:
    """后台起任务（新会话，ssh 断了也继续）：mode=gates → 本文件 _gates_run；mode=exec → args.argv。job 目录：out.log / rc / pid"""
    job = Path(args["job"])
    if job.exists():
        job.rename(job.with_name(job.name + f".old{int(time.time())}"))
    job.mkdir(parents=True)
    shutil.copytree(runner_dir, job / "runner")
    atomic_json(job / "job.json", args)
    sv = sv or load_sv()
    env = job_env(args["dest"], sv, args.get("env"))
    env["J"] = str(job)
    if args.get("mode") == "gates":
        argv = [sys.executable, "-u", str(job / "runner/tools/qa/remote_gates.py"), "_gates_run", str(job)]
    else:
        argv = [x.replace("{PY}", sys.executable) for x in args["argv"]]
    argv = ["nice", "-n", str(int(args.get("nice") or 10)), *argv]
    p = subprocess.Popen(["bash", "-c", SPAWN_SH, "_", args["dest"], *argv], env=env, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    (job / "pid").write_text(str(p.pid), encoding="utf-8")
    return {"job": str(job), "pid": p.pid}


def gate_key(cmd: list) -> str | None:
    c = [str(x) for x in cmd]
    if "-m" in c and "pytest" in c:
        return "pytest_collect" if "--collect-only" in c else "pytest"
    return GATE_OF.get(Path(c[1]).name) if len(c) > 1 else None


def run_gates_job(job: Path, sv=None) -> dict:
    """服务器后台：system_version.gates 原样在快照目录跑，逐命令计时（打桩 sv.sh / sv.run_watched，不改闸门本身）"""
    spec = json.loads((job / "job.json").read_text(encoding="utf-8"))
    ja = spec.get("job_args") or {}
    os.environ.update({"NS_FREEZE_EXEMPT": "1", "NS_CUT_PYTEST_N": str(ja.get("n", 24)), "CUDA_VISIBLE_DEVICES": ""})
    sv = sv or load_sv()
    dest = Path(spec["dest"])
    env = job_env(str(dest), sv, spec.get("env"))
    times: dict[str, float] = {}
    sh0, rw0 = sv.sh, sv.run_watched

    def _note(cmd, dt, code):
        k = gate_key(cmd) or "other"
        times[k] = round(times.get(k, 0) + dt, 1)
        print(f"[w45] {k:<14} {dt:7.1f}s  code {code}  {' '.join(map(str, cmd[1:3]))[:80]}", flush=True)

    def timed_sh(cmd, timeout=1800, cwd=sv.ROOT, env=None):
        t = time.time()
        r = sh0(cmd, timeout, cwd=cwd, env=env)
        _note(cmd, time.time() - t, r[0])
        return r

    def timed_rw(cmd, timeout, *a, **kw):
        t = time.time()
        r = rw0(cmd, timeout, *a, **kw)
        _note(cmd, time.time() - t, r[0])
        return r
    sv.sh, sv.run_watched = timed_sh, timed_rw
    t0 = time.time()
    try:
        rows = sv.gates(ja.get("changed") or [], bool(ja.get("run_tests", True)), root=dest, env=env, sv=ja.get("sv"),
                        log_dir=job / "logs")
        mt = sv.metrics(rows, dest, env) if ja.get("want_metrics") else None
    finally:
        sv.sh, sv.run_watched = sh0, rw0
    for r in rows:
        r["elapsed_s"] = times.get(r["id"])
        if r["id"] == "pytest":
            r["elapsed_s"] = round(times.get("pytest", 0), 1)
    res = {"ok_infra": True, "gates": rows, "metrics": mt, "timings": times, "total_s": round(time.time() - t0, 1),
           "host": os.uname().nodename if hasattr(os, "uname") else "", "nproc": os.cpu_count(), "dest": str(dest)}
    atomic_json(job / "result.json", res)
    print("[w45] 完成：" + "；".join(f"{'✅' if r['ok'] else '❌'} {r['id']} {r.get('elapsed_s')}s" for r in rows), flush=True)
    return res


def server_op(op: str, inbox: Path) -> dict:
    args = json.loads((inbox / "args.json").read_text(encoding="utf-8"))
    payload = inbox / "payload.bin"
    if op == "plan":
        return op_plan(args)
    if op == "build":
        return op_build(args, payload if payload.exists() else None)
    if op == "spawn":
        return op_spawn(args, inbox / "runner")
    if op == "store":
        return op_store(args, payload if payload.exists() else None)
    raise ValueError(f"未知 op：{op}")


# ---------------------------------------------------------------- 笔记本：编排
def poll_cmd(job: str, off: int) -> str:
    j = shlex.quote(job)
    return (f"J={j}; if [ -f $J/rc ]; then echo \"RC $(cat $J/rc)\"; elif kill -0 $(cat $J/pid 2>/dev/null || echo 0) 2>/dev/null; "
            f"then echo RUNNING; else echo DEAD; fi; echo \"SIZE $(stat -c %s $J/out.log 2>/dev/null || echo 0)\"; "
            f"tail -c +{int(off) + 1} $J/out.log 2>/dev/null | head -c 400000")


def parse_poll(raw: bytes) -> tuple[str, int | None, int, bytes]:
    """→ (RUNNING / DONE / DEAD, rc, 日志总长, 新输出)"""
    l1, rest = raw.split(b"\n", 1) if b"\n" in raw else (raw, b"")
    l2, new = rest.split(b"\n", 1) if b"\n" in rest else (rest, b"")
    s1 = l1.decode().strip()
    size = int(l2.decode().split()[1]) if l2.startswith(b"SIZE") else 0
    if s1.startswith("RC "):
        return "DONE", int(s1.split()[1]), size, new
    return ("RUNNING" if s1 == "RUNNING" else "DEAD"), None, size, new


def wait_job(cfg: dict, host: str, job: str, timeout: float, log=print, sh_fn=None, sleep=time.sleep, clock=time.time,
             max_conn_fail: int = 40) -> dict:
    """轮询到完成；连接层失败（rc 255 / 超时）连续 max_conn_fail 次才放弃（远端任务不受影响，可 `wait --job` 重新接上）"""
    sh_fn = sh_fn or remote_sh
    off, fails, t0 = 0, 0, clock()
    while True:
        res = sh_fn(host, poll_cmd(job, off), None, 120)
        if res.returncode != 0:
            fails += 1
            if fails >= max_conn_fail:
                return {"state": "lost", "job": job, "error": f"连续 {fails} 次轮询失败（rc {res.returncode}）"}
        else:
            fails = 0
            state, rc, size, new = parse_poll(res.stdout or b"")
            if new:
                log(new.decode("utf-8", "replace").rstrip("\n"))
                off += len(new)
            if state == "DONE" and off >= size:
                return {"state": "done", "rc": rc, "job": job}
            if state == "DEAD":
                return {"state": "dead", "job": job, "error": "远端任务进程不在、也没写 rc（被杀 / 机器重启）"}
            if state == "DONE":
                continue                      # 还有没拉完的输出
        if clock() - t0 > timeout:
            return {"state": "timeout", "job": job, "error": f"等了 {int(timeout)} s 仍未完成（远端仍在跑，可 wait --job 接上）"}
        sleep(float(cfg.get("poll_s") or 15))


def fetch(host: str, path: str, sh_fn=None, timeout: float = 600) -> bytes:
    res = (sh_fn or remote_sh)(host, f"gzip -c {shlex.quote(path)}", None, timeout)
    if res.returncode != 0:
        raise RuntimeError(f"拉回 {path} 失败 rc={res.returncode}：{(res.stderr or b'').decode('utf-8', 'replace')[-300:]}")
    return gzip.decompress(res.stdout)


def stage_tree(cfg: dict, host: str, tree: str, dest: str, latest_root: str, data_rels: list[str], sh_fn=None,
               log=print, repo: Path | None = None, overlay: tuple[list, list[str]] | None = None, ov_root: Path | None = None,
               ov_gate=None) -> dict:
    """plan → 只推缺的 blob → build。→ build 结果（含 dest / pushed / hardlinked / copied / linked）或 {"error"}"""
    check_dest(dest, cfg)
    check_dest(latest_root + "/x", cfg)
    t0 = time.time()
    manifest = tree_manifest(tree, repo, log=log)
    ov_files, ov_dirs = overlay or ([], [])
    base = {"dest": dest, "manifest": manifest, "latest_roots": latest_roots(cfg), "prod": cfg["prod_repo"],
            "overlay": ov_files, "store": cfg["snap_root"] + "/_blobs"}
    plan = call_op(cfg, host, "plan", base, sh_fn=sh_fn)
    if plan.get("error"):
        return plan
    miss = set(plan["missing"])
    deferred = defer_lfs(cfg, manifest, miss)
    if deferred:                  # 限速期：没人读的 LFS 先用指针（与 11-04 full2 首轮同口径，588 个测试照过），读到的（priority）推真内容
        log(f"[w45] 限速期延后 {len(deferred)} 个 LFS 真内容（先用指针；ep01 成片后 `remote_gates.py mirror --lfs` 补齐）")
        plan = call_op(cfg, host, "plan", {**base, "manifest": manifest}, sh_fn=sh_fn)
        if plan.get("error"):
            return plan
        miss = set(plan["missing"])
    ov_need = set(plan.get("overlay_missing") or [])
    n_ov = len([e for e in ov_files if e[1] in ov_need])
    if ov_need:                   # 笔记本数据：分批、每批等 run_sync 一拍（B 方案：冲刺期不抢链路）
        po = push_overlay(cfg, host, ov_files, ov_need, ov_root or repo or ROOT, sh_fn=sh_fn, log=log, gate=ov_gate)
        if po.get("error"):
            return po
    tree_need = [e for e in manifest if e[2] in miss and e[0] not in ("120000", "160000")]
    if tree_need:                 # 树里缺的文件（首次 / LFS 真内容可达几百 MB）：分批 ≤ batch_mb 进内容寻址库，单批断线重试；不等 run_sync 拍子（发版要及时）
        small = cat_blobs(sorted({e[1] for e in tree_need if e[1] not in _LFS_SRC}), repo)
        ents = [[e[2], e[1], False] for e in tree_need]
        po = push_overlay(cfg, host, ents, {e[1] for e in ents}, None, sh_fn=sh_fn, log=log, gate=lambda seen: seen, what="代码",
                          reader=lambda ent: _LFS_SRC[ent[1]].read_bytes() if ent[1] in _LFS_SRC else small[ent[1]])
        if po.get("error"):
            return po
    links = [e for e in manifest if e[2] in miss and e[0] == "120000"]
    payload = blob_tar(links, repo) if links else None
    log(f"[w45] 树 {tree[:10]}：{len(manifest)} 个文件，服务器已有 {len(manifest) - len(miss)}，要推 {len(miss)}"
        + (f"；笔记本数据（证据 + 镜像）{len(ov_files)} 个，已推 {n_ov}" if ov_files else "")
        + (f"（{len(payload) / 1e6:.2f} MB gz）" if payload else "") + f"；命中 {plan.get('hits')}")
    tmo = max(float(cfg.get("op_timeout_s") or 900), (len(payload) if payload else 0) / 50_000 + 300)
    b = call_op(cfg, host, "build", {**base, "data_rels": data_rels, "latest_root": latest_root, "tree": tree, "overlay_dirs": ov_dirs}, payload,
                timeout=tmo, sh_fn=sh_fn)
    if not b.get("error"):
        b["pushed"] = len(tree_need) + len(links)          # 本次从笔记本推的树文件数（经内容寻址库 + 软链走包）
        b["stage_s"] = round(time.time() - t0, 1)
        b["payload_bytes"] = len(payload) if payload else 0
        log(f"[w45] 快照就绪 {host}:{b['dest']}（推 {b['pushed']} / 硬链 {b['hardlinked']} / 复制 {b['copied']} / 数据 {b['linked']}；"
            f"{b['stage_s']} s）")
    return b


def latest_roots(cfg: dict) -> list[str]:
    """候选“上一份快照”：cut 快照、工人 _dev 副本（互为缓存，谁新谁先）"""
    return [cfg["snap_root"], cfg["snap_root"] + "/" + cfg.get("dev_dir", "_dev")]


def defer_lfs(cfg: dict, manifest: list, miss: set, root: Path | None = None) -> list[str]:
    """限速生效时：服务器缺真内容、又不在优先清单（mirror.extra + lfs_priority，定向测试实测会读的）的 LFS 文件 → 清单改回指针 sha。→ 改了的路径"""
    if not throttle_of(cfg, root):
        return []
    pri = set((cfg.get("mirror") or {}).get("extra") or []) | set(cfg.get("lfs_priority") or [])
    out = []
    for e in manifest:
        if e[2] in miss and e[1] in _LFS_PTR and e[2] not in pri:
            e[1] = _LFS_PTR[e[1]]
            out.append(e[2])
    return out


def remote_pytest_n(cfg: dict) -> int:
    v = os.environ.get("NS_CUT_REMOTE_PYTEST_N")
    return max(0, int(v)) if v not in (None, "") else int(cfg.get("pytest_n") or 24)


def remote_cut_gates(tree: str, sv_id: str, changed: list[str], run_tests: bool = True, want_metrics: bool = False,
                     host: str | None = None, sh_fn=None, log=print, sv=None, cfg: dict | None = None) -> dict:
    """cut 用：冻结树 → gpu33 快照 → 七门 → 结果（同 system_version.gates 的行结构，多 elapsed_s）。
    基础设施失败 → {"error"}（由 cut 决定退回本机还是失败关闭）；闸门红 ≠ error"""
    cfg = cfg or load_cfg()
    host = host or cfg["host"]
    sv = sv or load_sv()
    dest = check_dest(f"{cfg['snap_root']}/{sv_id}", cfg)
    job = dest + ".job"
    t0 = time.time()
    try:
        st = stage_tree(cfg, host, tree, dest, cfg["snap_root"], expand_data_rels(ignored_paths()), sh_fn=sh_fn, log=log,
                        overlay=merged_overlay(cfg))
        if st.get("error"):
            return st
        n = remote_pytest_n(cfg)
        sp = call_op(cfg, host, "spawn", {"job": job, "dest": dest, "mode": "gates", "nice": cfg.get("nice", 10),
                                          "job_args": {"sv": sv_id, "changed": changed, "run_tests": run_tests, "n": n,
                                                       "want_metrics": want_metrics}}, sh_fn=sh_fn)
        if sp.get("error"):
            return sp
        log(f"[w45] 闸门已在 {host} 后台起（job {job}，pid {sp['pid']}，pytest -n {n}）")
        w = wait_job(cfg, host, job, float(cfg.get("gates_timeout_s") or 7200), log=log, sh_fn=sh_fn)
        if w["state"] != "done" or w.get("rc"):
            return {"error": f"远端闸门任务 {w['state']} rc={w.get('rc')}：{w.get('error') or ''}（日志 {host}:{job}/out.log）", "job": job}
        res = json.loads(fetch(host, job + "/result.json", sh_fn))
    except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as e:
        return {"error": f"W45 远端闸门基础设施失败：{e!r}"[:800]}
    for r in res["gates"]:
        if r.get("log"):
            try:
                text = fetch(host, r["log"], sh_fn).decode("utf-8", "replace")
            except RuntimeError as e:
                r["log_fetch_error"] = repr(e)[:200]
                continue
            local = sv.write_pytest_log(text, sv_id)
            if local:
                r["detail"] = r["detail"].replace(r["log"], local)
                r["remote_log"], r["log"] = f"{host}:{r['log']}", local
    return {"gates": res["gates"], "metrics": res.get("metrics"), "timings": res.get("timings"), "gates_s": res.get("total_s"),
            "wall_s": round(time.time() - t0, 1), "host": host, "job": job,
            "snapshot": {"dir": f"{host}:{dest}", "files": st.get("files"), "linked": st.get("linked"), "pushed": st.get("pushed"),
                         "stage_s": st.get("stage_s"), "payload_bytes": st.get("payload_bytes")}}


def print_rows(rows: list[dict], log=print) -> None:
    for g in rows:
        log(f"  {'✅' if g['ok'] else '❌'} {g['id']:<12} {str(g.get('elapsed_s')):>7}s  {g['name']}：{g['detail'][:200]}")


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["_op"]:                         # 服务器内部
        print(json.dumps(server_op(argv[1], Path(argv[2])), ensure_ascii=False))
        return 0
    if argv[:1] == ["_gates_run"]:
        run_gates_job(Path(argv[1]))
        return 0
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass                                        # 非文本流（测试 / 重定向）：照常输出
    ap = argparse.ArgumentParser(description="W45：cut 七门在 gpu33 上跑")
    sp = ap.add_subparsers(dest="cmd", required=True)
    g = sp.add_parser("gates", help="冻结树（或此刻工作树）→ 服务器快照 → 七门；不提交、不打标签")
    g.add_argument("--tree")
    g.add_argument("--worktree", action="store_true", help="用此刻工作树（.gitignore 口径）")
    g.add_argument("--sv", default=None, help="快照目录名（默认 w45-<时间>）")
    g.add_argument("--no-tests", action="store_true")
    g.add_argument("--host", default=None)
    g.add_argument("--report-json", default=None)
    mi = sp.add_parser("mirror", help="B 方案：笔记本数据按 sha 增量推进服务器内容寻址库（分批、每批等 run_sync 一拍）；cut 前预热用")
    mi.add_argument("--host", default=None)
    mi.add_argument("--lfs", action="store_true", help="同时补齐此刻工作树里服务器缺的代码 / LFS 真内容（限速期延后的那些）")
    w = sp.add_parser("wait", help="重新接上远端任务（断线后）")
    w.add_argument("--job", required=True)
    w.add_argument("--host", default=None)
    a = ap.parse_args(argv)
    cfg = load_cfg()
    if a.cmd == "wait":
        r = wait_job(cfg, a.host or cfg["host"], check_dest(a.job, cfg), float(cfg.get("gates_timeout_s") or 7200))
        print(json.dumps(r, ensure_ascii=False))
        return 0 if r["state"] == "done" and not r.get("rc") else 1
    if a.cmd == "mirror":
        r = mirror_once(cfg, a.host or cfg["host"])
        if a.lfs and not r.get("error"):
            r["lfs"] = mirror_lfs(cfg, a.host or cfg["host"], worktree_tree())
        print(json.dumps(r, ensure_ascii=False))
        return 0 if not r.get("error") else 2
    tree = a.tree or (worktree_tree() if a.worktree else None)
    if not tree:
        ap.error("要 --tree 或 --worktree")
    changed = [x for x in git_bytes(["diff", "--name-only", "-z", "HEAD", tree]).decode("utf-8").split("\0") if x]
    sv_id = a.sv or time.strftime("w45-%Y%m%d-%H%M%S")
    out = remote_cut_gates(tree, sv_id, changed, run_tests=not a.no_tests, host=a.host, cfg=cfg)
    out.update(tree=tree, id=sv_id, changed=len(changed))
    if a.report_json:
        atomic_json(Path(a.report_json), out)
    if out.get("error"):
        print("❌ " + out["error"])
        return 2
    print_rows(out["gates"])
    print(json.dumps({k: out[k] for k in ("id", "tree", "changed", "host", "gates_s", "wall_s", "timings", "snapshot")}, ensure_ascii=False))
    return 0 if all(x["ok"] for x in out["gates"]) else 1


if __name__ == "__main__":
    sys.exit(main())
