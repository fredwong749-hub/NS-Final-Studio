"""多剧并行的 run 登记表（WORKFLOW 11-02，总调度批准；docs/AUTOPILOT.md §0.1；规则 K-OPS-W17）。

config/pipeline/runs.json：{"primary": "series10_v1", "runs": {"<run_id>": {"priority": 0, "status": "producing", "episode": N?,
"created_at": ISO, "source": "import|flow-start"}}}。config/pipeline/run.json 保留为 primary 的指针（旧读法兼容）。
导入新剧本 = register_run 追加一条（priority 默认 10），不改 primary、不替换 series10。

路径约定（primary 一律保持旧路径，保证现有生产零变化）：
  导入稿      primary: data/import/script_v2.json              其它: data/import/runs/<run>/script_v2.json
  运行目录    data/pipeline/runs/<run>/（作业 assets/first_frame_jobs.json）
  ready       primary: data/autopilot/ready_episodes.json（并写 runs/<run>/ 一份）  其它: data/autopilot/runs/<run>/ready_episodes.json
  对象 id     primary: <kind>:<shot>（过渡期不加前缀）           其它: <run>/<kind>:<shot>
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "config/pipeline/runs.json"
RUN_PTR = ROOT / "config/pipeline/run.json"
DEFAULT_PRIMARY = "series10_v1"


def _jl(p: Path, d=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return d


def _js(p: Path, d) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    t = p.with_suffix(p.suffix + ".tmp")
    t.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(t, p)


class RunRegistryMissing(RuntimeError):
    """服务器侧（strict=True）读不到 / 读坏 runs.json：失败关闭，不静默回退 DEFAULT_PRIMARY（K-OPS-F09 / K-OPS-W17）"""


def registry(root: Path | None = None, strict: bool = False) -> dict:
    root = root or ROOT
    d = _jl(root / "config/pipeline/runs.json", None)
    if d and d.get("runs"):
        return d
    if strict:
        raise RunRegistryMissing(f"runs.json 缺失或无 runs：{root / 'config/pipeline/runs.json'}（strict：服务器侧不回退 {DEFAULT_PRIMARY}）")
    prim = (_jl(root / "config/pipeline/run.json", {}) or {}).get("run_id") or DEFAULT_PRIMARY
    return {"primary": prim, "runs": {prim: {"priority": 0, "status": "producing", "source": "import"}}}


def primary_run(root: Path | None = None, strict: bool = False) -> str:
    """strict=True：服务器侧 / 驱动服务器的工具用，runs.json 缺失、损坏或没写 primary 就 raise（失败关闭）"""
    p = registry(root, strict=strict).get("primary")
    if not p and strict:
        raise RunRegistryMissing("runs.json 没写 primary（strict）")
    return p or DEFAULT_PRIMARY


def list_runs(root: Path | None = None, status: str | None = "producing", strict: bool = False) -> list[str]:
    """按 priority 升序（数字小 = 优先）"""
    r = registry(root, strict=strict)
    items = [(v.get("priority", 10), k) for k, v in (r.get("runs") or {}).items() if status is None or v.get("status") == status]
    return [k for _p, k in sorted(items)]


def is_primary(run: str | None, root: Path | None = None) -> bool:
    return run is None or run == primary_run(root)


def import_path(run: str | None, root: Path | None = None) -> Path:
    root = root or ROOT
    return root / "data/import/script_v2.json" if is_primary(run, root) else root / "data/import/runs" / run / "script_v2.json"


def run_dir(run: str | None, root: Path | None = None) -> Path:
    root = root or ROOT
    return root / "data/pipeline/runs" / (run or primary_run(root))


def ready_paths(run: str | None, root: Path | None = None) -> list[Path]:
    root = root or ROOT
    r = run or primary_run(root)
    out = [root / "data/autopilot/runs" / r / "ready_episodes.json"]
    if is_primary(r, root):
        out.insert(0, root / "data/autopilot/ready_episodes.json")      # 旧路径（NETFIX dispatch / FACTORY 现读）
    return out


def obj_id(run: str | None, kind: str, shot: str, root: Path | None = None) -> str:
    """过渡期：primary 不加前缀（producer / dispatch 认前缀之前不影响现生产）；其它 run 一律 <run>/<kind>:<shot>"""
    return f"{kind}:{shot}" if is_primary(run, root) else f"{run}/{kind}:{shot}"


def register_run(run: str, source: str = "import", episode: int | None = None, priority: int = 10,
                 root: Path | None = None) -> dict:
    """导入新剧本 = 追加一条（已有就只补缺失字段）；不改 primary"""
    root = root or ROOT
    p = root / "config/pipeline/runs.json"
    d = registry(root)
    e = dict((d.get("runs") or {}).get(run) or {})
    e.setdefault("priority", priority)
    e.setdefault("status", "producing")
    e.setdefault("created_at", time.strftime("%Y-%m-%dT%H:%M:%S"))
    e.setdefault("source", source)
    if episode is not None:
        e["episode"] = episode
    d.setdefault("runs", {})[run] = e
    _js(p, d)
    return e
