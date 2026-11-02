"""多剧并行的 run 登记表（WORKFLOW 11-02，总调度批准；docs/AUTOPILOT.md §0.1；规则 K-OPS-W17）。

config/pipeline/runs.json：{"primary": "series10_v1", "runs": {"<run_id>": {"priority": 0, "status": "producing", "episode": N?,
"created_at": ISO, "source": "import|flow-start"}}}。config/pipeline/run.json 保留为 primary 的指针（旧读法兼容）。
导入新剧本 = register_run 追加一条（priority 默认 10），不改 primary、不替换 series10。

路径约定（K-OPS-F24：只有 legacy_unprefixed_run 那部剧用不带前缀的旧路径；primary 切到别的剧也一律带前缀）：
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
    """strict=True：服务器侧 / 驱动服务器的工具用，runs.json 缺失、损坏或没写 primary 就 raise（失败关闭）。
    环境变量 NS_PRIMARY_RUN = 进程级显式钉剧（总调度 19:1x：读“真实当前剧”的测试一律钉到固定剧，不随 primary 切换漂移）"""
    pin = os.environ.get("NS_PRIMARY_RUN")
    if pin and (root is None or Path(root).resolve() == ROOT.resolve()):   # 只钉真实仓库；测试的临时目录照读自己的登记表
        return pin
    p = registry(root, strict=strict).get("primary")
    if not p and strict:
        raise RunRegistryMissing("runs.json 没写 primary（strict）")
    return p or DEFAULT_PRIMARY


def legacy_run(root: Path | None = None) -> str:
    """K-OPS-F24（总调度 11-02 18:4x，NETFIX 提醒）：只有这部剧（runs.json legacy_unprefixed_run，= series10_v1）用不带 run 前缀的旧路径
    （data/renders/epNN、data/import/script_v2.json、data/autopilot/ready_episodes.json、对象 id 无前缀）。primary 可以切到别的剧，
    别的剧一律 data/renders/<run>/ 等带前缀路径——V2 当上 primary 也不会写进 V1 的目录"""
    reg = registry(root)
    v = reg.get("legacy_unprefixed_run")
    if v:
        return v
    if (root or ROOT).joinpath("config/pipeline/runs.json").is_file():
        # 总调度 19:1x：剧名不写进代码；登记表在、却没写 legacy_unprefixed_run → 失败关闭（不能猜旧路径属于哪部剧）
        raise RunRegistryMissing("runs.json 没写 legacy_unprefixed_run（K-OPS-F24：哪部剧用不带前缀的旧路径必须登记）")
    return reg.get("primary")          # 没有登记表（沙箱 / 测试目录）= 旧行为：主剧就是旧路径那部


def is_legacy(run: str | None, root: Path | None = None) -> bool:
    return (run or primary_run(root)) == legacy_run(root)


def current_run(root: Path | None = None) -> str:
    """本进程在做的剧（OVERSIGHT-F P2：两种环境变量统一认法）：NS_RUN（多剧并行进程，producer.run_env 设）优先，
    否则 primary_run（真实仓库可被 NS_PRIMARY_RUN 钉住，测试用）"""
    v = os.environ.get("NS_RUN")
    if v and (root is None or Path(root).resolve() == ROOT.resolve()):
        return v
    return primary_run(root)


def list_runs(root: Path | None = None, status: str | None = "producing", strict: bool = False) -> list[str]:
    """按 priority 升序（数字小 = 优先）"""
    r = registry(root, strict=strict)
    items = [(v.get("priority", 10), k) for k, v in (r.get("runs") or {}).items() if status is None or v.get("status") == status]
    return [k for _p, k in sorted(items)]


def is_primary(run: str | None, root: Path | None = None) -> bool:
    return run is None or run == primary_run(root)


def import_path(run: str | None, root: Path | None = None) -> Path:
    root = root or ROOT
    r = run or primary_run(root)
    return root / "data/import/script_v2.json" if is_legacy(r, root) else root / "data/import/runs" / r / "script_v2.json"


def run_dir(run: str | None, root: Path | None = None) -> Path:
    root = root or ROOT
    return root / "data/pipeline/runs" / (run or primary_run(root))


# ---------------------------------------------------------------- 按剧取路径的唯一入口（AUDIT-M I-14 / I-15，总调度 11-02 18:5x）
# 编译 / 验收 / 合成 / API 一律调这几个函数，不许写死 data/import/script_v2.json、data/looks、data/renders 根目录（arch_scan hard_import_path）。
# 规则 K-OPS-F24：只有 legacy_unprefixed_run（series10_v1）用不带前缀的旧路径；不给 run = 当前 primary
def script_path(run: str | None = None, root: Path | None = None) -> Path:
    """导入稿（剧本）"""
    return import_path(run or current_run(root), root)


def renders_dir(run: str | None = None, root: Path | None = None) -> Path:
    """渲染根目录（epNN/SK/takes.json、版本图、_final 成片都在下面）"""
    root = root or ROOT
    r = run or current_run(root)
    return root / "data/renders" if is_legacy(r, root) else root / "data/renders" / r


def looks_path(run: str | None = None, root: Path | None = None) -> Path:
    """造型 / 身份脸覆盖 / 衣橱等“造型数据”目录：legacy = data/looks；其它剧 = data/pipeline/runs/<run>/looks（不读 V1 的 data/looks）"""
    root = root or ROOT
    r = run or current_run(root)
    return root / "data/looks" if is_legacy(r, root) else root / "data/pipeline/runs" / r / "looks"


def producer_dir(run: str | None = None, root: Path | None = None) -> Path:
    """producer 的账本 / registry / 心跳 / control 目录：legacy = data/producer；其它剧 = data/producer/runs/<run>"""
    root = root or ROOT
    r = run or current_run(root)
    return root / "data/producer" if is_legacy(r, root) else root / "data/producer/runs" / r


def asset_manifest(run: str | None = None, root: Path | None = None) -> Path | None:
    """资产包清单（runs.json 该剧的 assets_manifest；legacy / 没登记 = None，走旧资产来源）"""
    root = root or ROOT
    r = run or current_run(root)
    v = ((registry(root).get("runs") or {}).get(r) or {}).get("assets_manifest")
    return root / v if v else None


def ready_paths(run: str | None, root: Path | None = None) -> list[Path]:
    root = root or ROOT
    r = run or primary_run(root)
    out = [root / "data/autopilot/runs" / r / "ready_episodes.json"]
    if is_legacy(r, root):
        out.insert(0, root / "data/autopilot/ready_episodes.json")      # 旧路径（NETFIX dispatch / FACTORY 现读）
    return out


def obj_id(run: str | None, kind: str, shot: str, root: Path | None = None) -> str:
    """过渡期：primary 不加前缀（producer / dispatch 认前缀之前不影响现生产）；其它 run 一律 <run>/<kind>:<shot>"""
    r = run or primary_run(root)
    return f"{kind}:{shot}" if is_legacy(r, root) else f"{r}/{kind}:{shot}"


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
