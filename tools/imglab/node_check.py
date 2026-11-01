"""ComfyUI 道的节点核对（给 restart_queue / DEBUG-RSI lent_lanes 用：重启后自动核对，齐了才解除挂道）。

必需节点清单是唯一来源 REQUIRED（P0 安装单 docs/research/imglab/install_plan.md；以后新装节点包在这里加）。
本机经隧道读 /object_info（端口取 config/render_endpoints.json 的道配置）。

    from node_check import check
    r = check("gpu36:0")      # → {"lane", "ok", "missing": [...], "error": None | str}
    命令行：.venv/Scripts/python.exe tools/imglab/node_check.py gpu36:0 gpu33:1 --json   退出码 0 = 全齐，1 = 有缺，2 = 连不上
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REQUIRED = ["ModelPatchLoader", "ZImageFunControlnet", "FaceDetailer", "DetailerForEach", "UltralyticsDetectorProvider",
            "InpaintCropImproved", "InpaintStitchImproved", "DWPreprocessor",
            "QwenImage21ReferenceStrength", "QwenImage21ReferenceStrengthMasked"]


def lane_url(lane: str) -> str:
    """config/render_endpoints.json：lanes.<道>.url；gpu33 的道在 gpus.<卡号>（历史结构）"""
    cfg = json.loads((ROOT / "config/render_endpoints.json").read_text(encoding="utf-8"))
    e = (cfg.get("lanes") or {}).get(lane)
    if isinstance(e, dict) and e.get("url"):
        return str(e["url"]).rstrip("/")
    host, _, idx = lane.partition(":")
    if host == "gpu33" and idx in (cfg.get("gpus") or {}):
        return str(cfg["gpus"][idx]).rstrip("/")
    raise KeyError(f"render_endpoints.json 里没有道 {lane}")


def check(lane: str, timeout: float = 60, required: list[str] | None = None) -> dict:
    need = required or REQUIRED
    try:
        url = lane_url(lane)
        info = json.loads(urllib.request.urlopen(url + "/object_info", timeout=timeout).read())
    except (OSError, ValueError, KeyError) as e:
        return {"lane": lane, "ok": False, "missing": need, "error": repr(e)[:200]}
    miss = [n for n in need if n not in info]
    return {"lane": lane, "ok": not miss, "missing": miss, "error": None}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("lanes", nargs="+")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    rs = [check(x) for x in a.lanes]
    print(json.dumps(rs, ensure_ascii=False, indent=1) if a.json else
          "\n".join(f"{r['lane']}: {'齐' if r['ok'] else '缺 ' + ','.join(r['missing'])}{'（' + r['error'] + '）' if r['error'] else ''}" for r in rs))
    if any(r["error"] for r in rs):
        return 2
    return 0 if all(r["ok"] for r in rs) else 1


if __name__ == "__main__":
    sys.exit(main())
