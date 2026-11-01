"""推送前检查：本地模拟一次 resident_sync push（CODE-RSI 2026-11-01，规则 K-OPS-C03，knowledge/rules/ops_code_rsi.yaml）。

项目方 11-01 18:1x：“一旦 OK，你就把代码 push 到最新版本”。推送走 tools/autopilot/resident_sync.py push / recover（WORKFLOW），
断网期间只做过单元测试。这里用一个临时目录当“服务器”，**原样调用** resident_sync 的清单计算（local_manifest / diff_push /
wanted / required_data）和打包（batches / tar_bytes），按服务器端同样的方式“先解到临时目录再搬进 repo”，然后核对：

  P0 前置      tools/qa/syntax_guard.py 全仓通过（写断的代码不许推）
  P1 打包      每一批 tar 能完整读出；每个成员大小 = 本地文件大小；成员内容 = 本地文件当前内容（不同 = 打包时正被改写，记 changed）
  P2 解码      推过去的每个文件能完整解码：.py 编译 / .json / .jsonl 每行 / .yaml / 图片 PIL load / mp4 有 moov（0 字节只许 .py/.md/.txt 等）
  P3 最新      代码目录（resident_sync.CODE_DIRS）里每个本地文件在“服务器”上都有，且字节相同；第二轮清单差异 = 0
  P4 不该推的  模型权重（.safetensors/.ckpt/.pt/.pth/.onnx/.gguf/.bin ≥ 5 MB）、单文件 ≥ 100 MB、.git / node_modules / .venv /
               data/_quarantine / data/review_pages / data/ab / data/cache 一律不许出现；data 里的成品视频 / 音频单列（提示）
用法：
  .venv/Scripts/python.exe tools/qa/push_check.py                 # 代码 + 数据（服务器副本按“全新空目录”最坏情况，冻结时刻默认 6 小时前）
  .venv/Scripts/python.exe tools/qa/push_check.py --code-only
  .venv/Scripts/python.exe tools/qa/push_check.py --freeze 1793500000 --keep
退出码 0 = 可推；1 = 有问题；结果写 data/qa/push_check/last.json（--dry 不写）。不连服务器、不改源文件。
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data/qa/push_check"
PY = str(ROOT / ".venv/Scripts/python.exe") if (ROOT / ".venv/Scripts/python.exe").exists() else sys.executable
WEIGHT_EXT = (".safetensors", ".ckpt", ".pt", ".pth", ".onnx", ".gguf", ".bin", ".engine", ".trt")
FORBID_PARTS = {".git", "node_modules", ".venv", "__pycache__"}
FORBID_PREFIX = ("data/_quarantine", "data/review_pages/", "data/ab/", "data/cache/", "data/_offline_pull")
PRODUCT_EXT = (".mp4", ".mov", ".wav", ".mp3", ".flac")
EMPTY_OK = (".py", ".md", ".txt", ".gitkeep", ".keep", ".jsonl", ".log", ".err", ".out", ".lock", ".typed", ".pid")
IMG_EXT = (".png", ".jpg", ".jpeg", ".webp")


def load_rs():
    spec = importlib.util.spec_from_file_location("ns_resident_sync_pushcheck", ROOT / "tools/autopilot/resident_sync.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def sim_manifest(repo: Path, dirs: list[str]) -> dict[str, tuple[int, float]]:
    """服务器端 `find <dirs> -type f -printf '%p\\t%s\\t%T@'` 的等价物"""
    out = {}
    for d in dirs:
        base = repo / d
        if not base.exists():
            continue
        for dp, _dn, fn in os.walk(base):
            for f in fn:
                p = Path(dp) / f
                st = p.stat()
                out[p.relative_to(repo).as_posix()] = (st.st_size, st.st_mtime)
    return out


def apply_batch(blob: bytes, off: Path, repo: Path) -> list[str]:
    """服务器端：T=$(mktemp -d OFF/.push.XXXX); tar xf - -C $T; cp -a $T/. REPO/; rm -rf $T"""
    t = Path(tempfile.mkdtemp(prefix=".push.", dir=off))
    try:
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:") as tf:
            names = [m.name for m in tf.getmembers() if m.isfile()]
            tf.extractall(t, filter="data")
        shutil.copytree(t, repo, dirs_exist_ok=True)   # copy2 保留修改时间，等价 cp -a
    finally:
        shutil.rmtree(t, ignore_errors=True)
    return names


def decode_problem(p: Path, rel: str) -> str | None:
    n = p.stat().st_size
    suf = p.suffix.lower()
    if n == 0:
        return None if rel.endswith(EMPTY_OK) or p.name.startswith(".") else "0 字节"
    try:
        if suf == ".py":
            compile(p.read_bytes().decode("utf-8-sig"), rel, "exec", dont_inherit=True)
        elif suf == ".json":
            json.loads(p.read_text(encoding="utf-8-sig"))
        elif suf == ".jsonl":
            lines = p.read_text(encoding="utf-8").splitlines()
            for i, ln in enumerate(lines):
                if ln.strip():
                    try:
                        json.loads(ln)
                    except ValueError:
                        return f"jsonl 第 {i + 1}/{len(lines)} 行解析不了" + ("（末行 = 写一半）" if i == len(lines) - 1 else "")
        elif suf in (".yaml", ".yml"):
            import yaml
            yaml.safe_load(p.read_text(encoding="utf-8"))
        elif suf in IMG_EXT:
            from PIL import Image
            with Image.open(p) as im:
                im.load()
        elif suf in (".mp4", ".mov"):
            if b"moov" not in p.read_bytes():
                return "mp4 无 moov 盒（没写完 / 传一半）"
    except Exception as e:  # noqa: BLE001
        return f"读不全：{type(e).__name__}: {str(e)[:100]}"
    return None


def forbidden(rel: str, size: int) -> str | None:
    parts = rel.split("/")
    if any(x in FORBID_PARTS for x in parts):
        return "目录不该推（.git / node_modules / .venv / __pycache__）"
    if rel.startswith(FORBID_PREFIX):
        return "data 下不该推的目录（隔离区 / 审片页 / A/B / 缓存）"
    if rel.lower().endswith(WEIGHT_EXT) and size >= 5 * 1024 * 1024:
        return f"模型权重 {size / 1e6:.1f} MB"
    if size >= 100 * 1024 * 1024:
        return f"单文件 {size / 1e6:.1f} MB"
    return None


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def run(code_only: bool = False, freeze: float | None = None, server: Path | None = None, keep: bool = False,
        rs=None, skip_guard: bool = False, tier: int = 2) -> dict:
    t0 = time.time()
    rs = rs or load_rs()
    src = Path(rs.ROOT)   # 源仓库（测试里可换成临时仓库）
    rep: dict = {"schema": "nsfs.push_check/1", "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "code_only": code_only,
                 "problems": [], "changed_during_pack": [], "products": [], "stats": {}}

    def bad(kind, rel, why):
        rep["problems"].append({"kind": kind, "file": rel, "why": why})

    # P0 前置：写断的代码不许推
    if not skip_guard:
        r = subprocess.run([PY, str(ROOT / "tools/qa/syntax_guard.py"), "--dry"], capture_output=True, timeout=600)
        tail = r.stdout.decode("utf-8", "replace").strip().splitlines()[-3:]
        rep["syntax_guard"] = {"rc": r.returncode, "tail": tail}
        if r.returncode != 0:
            bad("P0", "tools/qa/syntax_guard.py", " ⏎ ".join(tail))

    # 直接驱动真实的 resident_sync.push()：只把 ssh 换成本地“服务器”（临时目录），目录 / 分层 / 过滤 / 打包全用它自己的代码，
    # 改了 push 逻辑这里自动跟上（之前抄一份 rem_dirs，WORKFLOW 一改就过期）
    import inspect
    import re as _re
    has_tier = hasattr(rs, "tier_of")
    rep["tier"] = tier if has_tier else None
    own_tmp = server is None
    base = Path(tempfile.mkdtemp(prefix="nsfs_push_sim_")) if own_tmp else Path(server)
    off, repo = base, base / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    freeze = time.time() - 6 * 3600 if freeze is None else freeze
    sent: dict[str, int] = {}
    packed_at: dict[str, float] = {}
    rounds: list[int] = []
    finds = {"n": 0}

    def fake_ssh(host, cmd, data=None, timeout=900, tries=5):
        if "FREEZE_TS" in cmd:
            return str(freeze).encode()
        m = _re.search(r"find (.+?) -type f", cmd)
        if m and "-printf" in cmd:
            finds["n"] += 1
            rounds.append(0)
            man = sim_manifest(repo, m.group(1).split())
            return "".join(f"{k}\t{v[0]}\t{v[1]}\n" for k, v in man.items()).encode()
        if "tar xf -" in cmd and data is not None:
            t_pack = time.time()
            try:
                with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as tf:
                    for mm in tf.getmembers():
                        if not mm.isfile():
                            continue
                        packed_at.setdefault(mm.name, t_pack)   # 记第一次打包时刻：之后被改过 = 打包后别的 loop 又改（下一次 push 会补），不算不收敛
                        got = tf.extractfile(mm).read()
                        f = src / mm.name
                        if f.exists() and got != f.read_bytes():
                            rep["changed_during_pack"].append(mm.name)
            except (tarfile.TarError, OSError, EOFError) as e:
                bad("P1", "batch", f"tar 读不出：{type(e).__name__}: {e}")
                raise RuntimeError("tar 坏了") from e
            names = apply_batch(data, off, repo)
            for n in names:
                sent[n] = sent.get(n, 0) + 1
            if rounds:
                rounds[-1] += len(names)
            return b"ok"
        raise RuntimeError(f"push_check 没模拟的远端命令：{cmd[:120]}")

    saved = {k: getattr(rs, k) for k in ("ssh", "STATE", "LOG") if hasattr(rs, k)}
    rs.ssh, rs.STATE, rs.LOG = fake_ssh, base / "resident_sync_state.json", base / "resident_sync.log"
    if code_only or not hasattr(rs, "required_data"):
        saved.setdefault("required_data", getattr(rs, "required_data", None))
        rs.required_data = lambda: set()
    kw = {}
    sig = inspect.signature(rs.push).parameters
    if "tier" in sig:
        kw["tier"] = tier
    if "yes" in sig:
        kw["yes"] = True
    if "gate" in sig:
        kw["gate"] = False          # 本身就是闸门，不递归
    if hasattr(rs, "push_dirs"):     # 与 push 同一份目录计算（resident_sync.push_dirs）
        d, rd = rs.push_dirs(code_only, tier) if has_tier else rs.push_dirs(code_only)
        rep["dirs"], rep["remote_dirs"] = d, rd
    try:
        try:
            rs.push("sim", code_only, **kw)
        except RuntimeError as e:
            bad("P1", "push", str(e)[:200])
        rep["stats"]["rounds"] = [x for x in rounds]
        rep["stats"]["files_sent"] = len(sent)
        rep["stats"]["resent"] = sorted(k for k, v in sent.items() if v > 1)[:50]
        # 收敛：同一份本地状态再推一次，应当 0 个文件（不收敛 = 远端清单漏目录 / 文件一直在变）
        before = dict(sent)
        rounds.clear()
        try:
            rs.push("sim", code_only, **kw)
        except RuntimeError as e:
            bad("P1", "push#2", str(e)[:200])
        again = sorted(k for k in sent if sent[k] != before.get(k, 0))
        rep["stats"]["second_push"] = len(again)
        for f in again[:50]:
            if (src / f).exists() and (src / f).stat().st_mtime >= packed_at.get(f, 0) - 5:
                rep.setdefault("changed_after_pack", []).append(f)
                continue
            bad("P3", f, "再推一次仍要发（清单不收敛：远端清单没列这个目录，或文件一直在变）")
        # P2 解码 + P4 不该推的
        files = sorted(sent)

        def one(rel):
            p = repo / rel
            return rel, p.stat().st_size, decode_problem(p, rel)
        with ThreadPoolExecutor(max_workers=min(16, os.cpu_count() or 4)) as ex:
            res = list(ex.map(one, files))
        by_top: dict[str, list] = {}
        for rel, size, why in res:
            if why:
                bad("P2", rel, why)
            fb = forbidden(rel, size)
            if fb:
                bad("P4", rel, fb)
            if rel.startswith("data/") and rel.lower().endswith(PRODUCT_EXT):
                rep["products"].append({"file": rel, "mb": round(size / 1e6, 2)})
            top = "/".join(rel.split("/")[:2])
            t = by_top.setdefault(top, [0, 0])
            t[0] += 1
            t[1] += size
        rep["stats"]["by_top"] = {k: {"files": v[0], "mb": round(v[1] / 1e6, 2)} for k, v in
                                  sorted(by_top.items(), key=lambda kv: -kv[1][1])}
        rep["stats"]["total_mb"] = round(sum(v[1] for v in by_top.values()) / 1e6, 2)

        # P3 最新：代码目录每个本地文件都在、字节相同（打包时正被改写的单列，不算错）
        code_loc = {k: v for k, v in rs.local_manifest(rs.CODE_DIRS).items()
                    if not has_tier or rs.tier_of(k, v[0]) <= tier}
        miss, diff = [], []
        for rel in code_loc:
            q = repo / rel
            if not q.exists():
                miss.append(rel)
            elif q.stat().st_size != (src / rel).stat().st_size or sha(q) != sha(src / rel):
                diff.append(rel)
        for rel in miss[:50]:
            bad("P3", rel, "代码文件没推到")
        for rel in diff[:50]:
            if rel in rep["changed_during_pack"]:
                continue
            if (src / rel).stat().st_mtime >= packed_at.get(rel, 0) - 1:   # 打包之后别的 loop 又改了：下一次 push 会补
                rep.setdefault("changed_after_pack", []).append(rel)
                continue
            bad("P3", rel, "服务器副本和本地不同（不是最新）")
        rep["stats"]["code_files"] = len(code_loc)
        rep["stats"]["code_mb"] = round(sum(v[0] for v in code_loc.values()) / 1e6, 2)
        rep["stats"]["products_mb"] = round(sum(x["mb"] for x in rep["products"]), 2)
        rep["freeze"] = freeze
        if hasattr(rs, "estimate"):   # 跳板实测带宽下的预计耗时（resident_sync.LINK_KBPS）
            rep["stats"]["eta_min"] = rs.estimate(files, {f: ((repo / f).stat().st_size, 0) for f in files})["eta_min"]
    finally:
        for k, v in saved.items():
            setattr(rs, k, v)
        if own_tmp and not keep:
            shutil.rmtree(base, ignore_errors=True)
        elif keep:
            rep["server_dir"] = str(base)
    rep["seconds"] = round(time.time() - t0, 1)
    rep["verdict"] = "FAIL" if rep["problems"] else "PASS"
    return rep


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="推送前检查：本地模拟 resident_sync push（K-OPS-C03）")
    ap.add_argument("--code-only", action="store_true")
    ap.add_argument("--tier", type=int, default=2, help="同 resident_sync push --tier1（1）/ 默认（2）")
    ap.add_argument("--freeze", type=float, help="服务器副本冻结时刻（epoch 秒），默认 6 小时前")
    ap.add_argument("--server", help="模拟服务器目录（默认临时空目录 = 全新服务器最坏情况）")
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args(argv)
    rep = run(a.code_only, a.freeze, Path(a.server) if a.server else None, a.keep, tier=a.tier)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    if not a.dry:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "last.json.tmp").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(OUT / "last.json.tmp", OUT / "last.json")
    for p in rep["problems"][:60]:
        print(f"[{p['kind']}] {p['file']}：{p['why']}")
    s = rep["stats"]
    print(f"push_check {rep['verdict']}：推 {s.get('files_sent')} 个文件 {s.get('total_mb')} MB（代码 {s.get('code_files')} 个 "
          f"{s.get('code_mb')} MB），轮次差异 {s.get('rounds')}，打包时正被改写 {len(rep['changed_during_pack'])}，"
          f"data 成品 {len(rep['products'])} 个 {s.get('products_mb')} MB，tier {rep.get('tier')}，按跳板带宽预计 {s.get('eta_min')} 分钟，{rep['seconds']} 秒")
    return 0 if rep["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
