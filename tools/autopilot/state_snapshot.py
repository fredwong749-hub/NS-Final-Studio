"""决策 / 配置类数据文件的快照与恢复（DISTILL 11-02，总调度补派；规则 K-OPS-X06）。

data/ 不进 git，但里面有一批“像配置的文件”（配方选择、设定图选择、驳回、ready_episodes、交还记录、takes 当前指针……），
重建环境会丢、回滚代码时状态不跟着回。分类写在 config/policies/state_files.yaml（decision = 进快照；runtime = 不进）。

  python tools/autopilot/state_snapshot.py list                       # 分类清单 + 现存 / 大小
  python tools/autopilot/state_snapshot.py snapshot <sv>              # → data/system_versions/<sv>/state_snapshot.tar + manifest.json
  python tools/autopilot/state_snapshot.py restore <sv> [--apply]     # 校验 sha → 列出差异；--apply 先把现状备份到 <sv>/pre_restore_<时刻>/ 再恢复（不删文件）
  python tools/autopilot/state_snapshot.py init-run <run_id> [--apply]  # 新剧本：按 state_files.yaml 的 default（及 config/ 派生）生成初始文件；
                                                                        # 默认写到 data/autopilot/init_run/<run_id>/ 预览，--apply 才落到正式路径且只补缺、不覆盖
manifest 用 sha256 逐文件登记，与 FACTORY 本地库（docs/master/FRAMEWORK_REFRAME.md D2：library/objects/<前 2 位>/<sha256>）同一种寻址；
FACTORY 的 tools/factory/library.py 落地后，snapshot 同时 put 进本地库（不另建第二套内容库）。
system_version.py cut 时调用 snapshot(sv)（接入由 FACTORY 负责，它在改部署闸门）。
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import json
import sys
import tarfile
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SPEC = "config/policies/state_files.yaml"


def run_id(root: Path = ROOT) -> str:
    try:
        return json.loads((root / "config/pipeline/run.json").read_text(encoding="utf-8"))["run_id"]
    except (OSError, ValueError, KeyError):
        return "series10_v1"


def spec(root: Path = ROOT) -> dict:
    return yaml.safe_load((root / SPEC).read_text(encoding="utf-8")) or {}


def _expand(entry: dict, root: Path, run: str) -> list[str]:
    if entry.get("path"):
        rel = entry["path"].replace("{run}", run)
        return [rel] if (root / rel).exists() else []
    pat = entry["glob"].replace("{run}", run)
    return sorted(str(p.relative_to(root)).replace("\\", "/") for p in root.glob(pat) if p.is_file() and "_quarantine" not in str(p))


def decision_files(root: Path = ROOT, run: str | None = None) -> list[str]:
    run = run or run_id(root)
    out: list[str] = []
    for e in spec(root).get("decision") or []:
        out += [r for r in _expand(e, root, run) if r not in out]
    return out


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _library():
    p = ROOT / "tools/factory/library.py"
    if not p.exists():
        return None
    s = importlib.util.spec_from_file_location("ns_factory_library", p)
    m = importlib.util.module_from_spec(s)
    try:
        s.loader.exec_module(m)
    except Exception:  # noqa: BLE001
        return None
    return m if hasattr(m, "put") else None


def snapshot(sv: str, root: Path = ROOT, dest: Path | None = None) -> dict:
    run = run_id(root)
    files = decision_files(root, run)
    out = dest or (root / "data/system_versions" / sv)
    out.mkdir(parents=True, exist_ok=True)
    man = {"schema": "nsfs.state_snapshot/1", "sv": sv, "run_id": run, "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "spec": SPEC, "files": {}}
    lib = _library() if root == ROOT else None
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for rel in files:
            b = (root / rel).read_bytes()
            man["files"][rel] = {"sha256": sha256_bytes(b), "size": len(b)}
            ti = tarfile.TarInfo(rel)
            ti.size, ti.mtime = len(b), int((root / rel).stat().st_mtime)
            tf.addfile(ti, io.BytesIO(b))
            if lib:
                try:
                    lib.put(root / rel)
                except Exception:  # noqa: BLE001
                    pass
    tb = buf.getvalue()
    (out / "state_snapshot.tar").write_bytes(tb)
    man["tar_sha256"] = sha256_bytes(tb)
    man["library"] = "tools/factory/library.py" if lib else "（未落地，只有 tar + manifest）"
    (out / "manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
    return man


def restore(sv: str, root: Path = ROOT, apply: bool = False, src: Path | None = None) -> dict:
    d = src or (root / "data/system_versions" / sv)
    man = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    tb = (d / "state_snapshot.tar").read_bytes()
    if sha256_bytes(tb) != man.get("tar_sha256"):
        raise ValueError("state_snapshot.tar 的 sha 与 manifest 不符，拒绝恢复")
    changes, bad = [], []
    with tarfile.open(fileobj=io.BytesIO(tb)) as tf:
        blobs = {m.name: tf.extractfile(m).read() for m in tf.getmembers() if m.isfile()}
    for rel, meta in man["files"].items():
        b = blobs.get(rel)
        if b is None or sha256_bytes(b) != meta["sha256"]:
            bad.append(rel)
            continue
        cur = root / rel
        now_sha = sha256_bytes(cur.read_bytes()) if cur.exists() else None
        if now_sha != meta["sha256"]:
            changes.append({"file": rel, "now": now_sha, "snap": meta["sha256"]})
    if bad:
        raise ValueError(f"快照内文件 sha 不符：{bad[:5]}")
    res = {"sv": sv, "changes": changes, "applied": False}
    if apply and changes:
        bk = d / f"pre_restore_{time.strftime('%Y%m%d_%H%M%S')}"
        for c in changes:
            cur = root / c["file"]
            if cur.exists():
                (bk / c["file"]).parent.mkdir(parents=True, exist_ok=True)
                (bk / c["file"]).write_bytes(cur.read_bytes())
            cur.parent.mkdir(parents=True, exist_ok=True)
            cur.write_bytes(blobs[c["file"]])
        res.update(applied=True, backup=str(bk))
    return res


def _build_default(entry: dict, root: Path, run: str):
    dv = entry.get("default")
    if isinstance(dv, dict) and dv.get("from_config"):
        cfg = json.loads((root / dv["from_config"]).read_text(encoding="utf-8"))
        if dv.get("build") == "recipe_choice":
            allowed = ((cfg.get("pika_only") or {}).get("allowed") or [None])[0]
            return {"face_default": allowed, "ref_default": allowed, "noface_default": allowed,
                    "rule": "K-REN-301 / L-088（init-run 从 config/pipeline/video_policy.json 生成）", "decided_by": "config 默认"}
        return cfg
    return json.loads(json.dumps(dv).replace("{run}", run)) if dv is not None else None


def init_run(new_run: str, root: Path = ROOT, apply: bool = False) -> dict:
    """新剧本冷启动：只用 config/ 默认值，不读 series10 数据"""
    made, skipped = [], []
    stage = root / "data/autopilot/init_run" / new_run
    for e in spec(root).get("decision") or []:
        if not e.get("path"):
            continue
        val = _build_default(e, root, new_run)
        if val is None:
            skipped.append(e["path"])
            continue
        rel = e["path"].replace("{run}", new_run)
        txt = json.dumps(val, ensure_ascii=False, indent=1)
        if apply:
            p = root / rel
            if p.exists():
                skipped.append(rel + "（已存在，不覆盖）")
                continue
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(txt, encoding="utf-8")
        else:
            p = stage / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(txt, encoding="utf-8")
        made.append(rel)
    return {"run_id": new_run, "applied": apply, "made": made, "skipped": skipped, "preview_dir": None if apply else str(stage)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("list", "snapshot", "restore", "init-run"))
    ap.add_argument("arg", nargs="?")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "list":
        run = run_id()
        sp = spec()
        for kind in ("decision", "runtime"):
            print(f"## {kind}")
            for e in sp.get(kind) or []:
                fs = _expand(e, ROOT, run)
                size = sum((ROOT / f).stat().st_size for f in fs)
                print(f"  {e.get('path') or e.get('glob')}：{len(fs)} 个文件 {size / 1024:.0f} KB — {e.get('what') or e.get('why')}")
        return 0
    if not a.arg:
        ap.error("需要 <sv> 或 <run_id>")
    r = {"snapshot": lambda: snapshot(a.arg), "restore": lambda: restore(a.arg, apply=a.apply),
         "init-run": lambda: init_run(a.arg, apply=a.apply)}[a.cmd]()
    if a.cmd == "snapshot":
        r = {k: v for k, v in r.items() if k != "files"} | {"n_files": len(r["files"])}
    print(json.dumps(r, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
