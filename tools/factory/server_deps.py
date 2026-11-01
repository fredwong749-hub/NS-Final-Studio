"""FACTORY：服务器运行依赖核对（config/deploy/server_deps.yaml）。在服务器上执行，退出码 0 = 齐，1 = 缺（打印缺什么）。
起因（11-02 04:0x VQAGATE）：offline venv 没装 mediapipe，看镜头确定性层 gaze_mp 在生产上一次都没生效，而且是静默失效。
  python tools/factory/server_deps.py [--repo <仓库根>]
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def problems(repo: Path = ROOT, spec: dict | None = None, spec_file: Path | None = None) -> list[str]:
    import yaml
    spec = spec or yaml.safe_load((spec_file or (ROOT / "config/deploy/server_deps.yaml")).read_text(encoding="utf-8")) or {}
    out = []
    for venv, req in (spec.get("venvs") or {}).items():
        py = Path(venv) / "bin" / "python"
        if not py.exists():
            out.append(f"缺解释器 {py}")
            continue
        code = ("import importlib,json,sys\nmods=json.loads(sys.argv[1]);bad=[]\n"
                "for m in mods:\n    try: importlib.import_module(m)\n    except Exception as e: bad.append(m+': '+type(e).__name__)\n"
                "print(json.dumps(bad))")
        r = subprocess.run([str(py), "-c", code, json.dumps(req.get("imports") or [])], capture_output=True, text=True, timeout=300,
                           env={"OMP_NUM_THREADS": "2", "PATH": "/usr/bin:/bin"})
        try:
            bad = json.loads((r.stdout.strip().splitlines() or ["[]"])[-1])
        except ValueError:
            bad = [f"import 检查本身失败：{r.stderr[-200:]}"]
        out += [f"{venv}: 不能 import {b}" for b in bad]
        for pkg, ver in (req.get("versions") or {}).items():
            r = subprocess.run([str(py), "-m", "pip", "show", pkg], capture_output=True, text=True, timeout=120)
            got = next((ln.split(":", 1)[1].strip() for ln in r.stdout.splitlines() if ln.startswith("Version:")), None)
            if got != str(ver):
                out.append(f"{venv}: {pkg} 版本 {got} ≠ {ver}")
    for rel, want in (spec.get("models") or {}).items():
        p = repo / rel
        if not p.is_file():
            out.append(f"缺模型文件 {rel}")
        elif sha256(p) != want:
            out.append(f"模型文件 sha 不符 {rel}")
    return out


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    repo = Path(sys.argv[sys.argv.index("--repo") + 1]) if "--repo" in sys.argv else ROOT
    pr = problems(repo)
    print(json.dumps({"problems": pr}, ensure_ascii=False))
    sys.exit(1 if pr else 0)
