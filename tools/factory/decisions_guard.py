"""FACTORY K-OPS-F09：决策 / 覆盖文件缺失或损坏 → 拒派并报警（失败关闭）。ARCH_MAP #2（总调度 03:0x 定）。

起因：face_overrides 等覆盖文件读不到时各处静默回退（asset_refs、producer 的 *_hold.json、inbox expected_refs、run.json），
11-02 01:24 两台服务器因此用错身份脸出了 31 张图；config/pipeline/run.json 服务器上没有，producer 静默回退 series10_v1。
producer 每次派单前调 problems()：非空 → 这一拍一单不派，写报警事件 decision_files_block。

  REQUIRED      必须存在且能解析（缺 = 拒派）
  OPTIONAL      可以不存在（= 没有这层覆盖），存在就必须能解析（坏 = 拒派）
  HOLD_GLOB     data/autopilot/*_hold.json：存在就必须能解析（坏的 hold 不知道该挡谁 → 全部拒派）
  SERVER_ONLY   服务器工厂（OFFLINE_SELF / NS_FACTORY_HOST）额外必须有：期望 refs 表（K-OPS-F03）
"""
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(os.environ.get("NS_ROOT") or Path(__file__).resolve().parents[2]).resolve()

REQUIRED = ["config/scene_aliases.json", "config/recipes/asset_refs.json",
            "data/looks/face_overrides.json", "data/looks/item_map_overrides.json", "data/looks/hub_episode_looks.json",
            "data/looks/wardrobe.json", "data/assetmaster/look_extras.json", "data/assetmaster/sheet_item_checks.json",
            "data/pipeline/runs/{run}/assets/sheets_chosen.json"]
OPTIONAL = ["data/looks/hub_extra_looks.json", "data/looks/item_map_quarantine.json"]
HOLD_GLOB = "data/autopilot/*_hold.json"
SERVER_ONLY = ["data/factory/inbox/expected_refs.json"]


def is_server() -> bool:
    return bool(os.environ.get("NS_FACTORY_HOST") or os.environ.get("OFFLINE_SELF"))


def _bad_json(p: Path) -> str | None:
    try:
        json.loads(p.read_text(encoding="utf-8"))
        return None
    except (OSError, ValueError) as e:
        return f"{type(e).__name__}: {str(e)[:80]}"


def run_id(root: Path) -> str | None:
    """现行主剧：§10 起 run.json 在 data/state/pipeline/run.json（兼容期旧位置 config/pipeline/run.json 也认，读旧会留痕）"""
    import importlib.util
    try:
        spec = importlib.util.spec_from_file_location("ns_state_paths_dg", Path(__file__).resolve().parent / "state_paths.py")
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        v = (m.read_state("pipeline/run", root=root) or {}).get("run_id")
        return str(v).strip() or None
    except Exception:  # noqa: BLE001  读不到 = None，problems() 会报（失败关闭）
        return None


def _code_sv(root: Path) -> list[str]:
    import importlib.util
    try:
        spec = importlib.util.spec_from_file_location("ns_policy_dg", root / "tools/autopilot/policy.py")
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        pb = m.code_sv_problem(root)
    except Exception as e:  # noqa: BLE001  校验器自身出错也算问题（失败关闭）
        return [f"代码版本校验出错（K-OPS-X08）：{e!r}"[:200]]
    return [pb] if pb else []


def problems(root: Path | None = None, server: bool | None = None) -> list[str]:
    root = Path(root or ROOT)
    server = is_server() if server is None else server
    out = []
    run = run_id(root)
    if not run:
        out.append("run.json（data/state/pipeline/run.json，兼容期 config/pipeline/run.json）缺失或没有 run_id（不再静默回退 series10_v1）")
    # run 为空时上面已报问题；这里不拼默认路径（SYSARCH 02:4x：不再回退 series10_v1）
    req = [r.format(run=run) for r in REQUIRED if run or "{run}" not in r] + (SERVER_ONLY if server else [])
    for rel in req:
        p = root / rel
        if not p.is_file():
            out.append(f"缺必需的决策文件 {rel}")
        elif (why := _bad_json(p)):
            out.append(f"决策文件读不出 {rel}（{why}）")
    for rel in OPTIONAL:
        p = root / rel
        if p.is_file() and (why := _bad_json(p)):
            out.append(f"覆盖文件读不出 {rel}（{why}）")
    if server:              # K-OPS-X08（DISTILL policy.code_sv_problem）：本机代码版本低于 handback.min_code_sv / 读不到 → 拒派
        out += _code_sv(root)
    for p in sorted(root.glob(HOLD_GLOB)):
        if (why := _bad_json(p)):
            out.append(f"hold 文件读不出 {p.relative_to(root).as_posix()}（{why}；不知道该挡谁 → 全部拒派）")
    return out


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    pr = problems()
    print(json.dumps({"server": is_server(), "problems": pr}, ensure_ascii=False, indent=1))
    raise SystemExit(1 if pr else 0)
