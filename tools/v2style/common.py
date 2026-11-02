"""STYLE-V2 工具公用：机器 / 路径配置（config/v2style.json）、V2 资产包取图（assets_v2/manifest.json，校验 sha256）、
远程命令（一律经 tools/netfix/rsh.py 常驻主连接，K-OPS-N07）、原子写 JSON。"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CFG_PATH = ROOT / "config" / "v2style.json"
MANIFEST = ROOT / "assets_v2" / "manifest.json"
RSH = [sys.executable, str(ROOT / "tools/netfix/rsh.py")]


def cfg() -> dict:
    return json.loads(CFG_PATH.read_text(encoding="utf-8"))


def asset(kind: str, cid: str = "lead_f", look: str | None = None) -> str:
    """V2 资产包里的文件（仓库相对路径），sha256 不符直接报错。kind = face | garment（garment 需 look，只许 server_ok 造型）"""
    m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    ch = m["characters"][cid]
    if kind == "face":
        it = ch["face"]
    elif kind == "garment":
        lk = ch["looks"][look]
        if lk.get("route") != "server_ok" or lk.get("adult"):
            raise SystemExit(f"{cid}/{look} 不是 server_ok 造型（只能本地生成），STYLE-V2 不用")
        it = next(iter(lk["items"].values()))
    else:
        raise KeyError(kind)
    got = hashlib.sha256((ROOT / it["file"]).read_bytes()).hexdigest()
    if got != it["sha256"]:
        raise SystemExit(f"资产 sha 不符：{it['file']} 清单 {it['sha256'][:12]} 实际 {got[:12]}")
    return it["file"]


def remote(host: str, cmd: str, stdin: bytes | None = None, timeout: int = 1800) -> subprocess.CompletedProcess:
    """远程命令：经 tools/netfix/rsh.py（不自开 ssh）"""
    return subprocess.run([*RSH, host, cmd], input=stdin, capture_output=True, timeout=timeout)


def save_json_atomic(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def load_json(path: Path, default):
    """读结果文件；不存在 = 默认值（新实验）；存在但坏了 = 报错（不静默当空）"""
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))
