"""换场景底图（L-188 / L1：sk_white_cyc 换低调影棚版）——资产包清单里已有底图时的入口。

asset_jobs.register_pick 对“已有底图”的场景失败关闭（不重复登记），所以换底图走这里：
  - 复用 asset_jobs 的 manifest_path / _read_manifest / _write_manifest（清单 sha 防并发）/ _copy_in（sha 核对）/ push_files；
  - 旧底图 entry 整条挂到新 entry 的 replaced[]（历史保留），旧图文件不删；
  - 默认 dry-run（只打印计划，不拷贝、不写清单）；--apply 才写。

用法：
  .venv/Scripts/python.exe tools/pipeline/replace_scene_base.py --run series10_v2 --scene sk_white_cyc \
      --src data/ab/look_v2/plates/image_000_7afbc8bc_raw_post.png --name L1_s1104 --by 总调度 --note "L-188 ..."  [--apply] [--no-push]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "pipeline"))
import asset_jobs as AJ  # noqa: E402


def plan_replace(root: Path, run: str, scene: str, src_rel: str, name: str, by: str, note: str = "", apply: bool = False, push: bool = True) -> dict:
    src = root / src_rel
    if not src.is_file():
        raise AJ.RegisterError(f"源图不存在：{src_rel}")
    mp = AJ.manifest_path(root, run)
    d, sha0 = AJ._read_manifest(mp)
    old = ((d.get("scenes") or {}).get(scene) or {}).get("base") or {}
    sha_src = AJ._sha(src.read_bytes())
    dst = mp.parent / "scenes" / scene / f"{scene}_base_{AJ.safe_name(name)}{src.suffix.lower()}"
    rel = str(dst.relative_to(root)).replace("\\", "/")
    if old.get("sha256") == sha_src:
        raise AJ.RegisterError(f"{scene} 当前底图已经是这张（sha {sha_src[:12]}），不重复换")
    out = {"run": run, "scene": scene, "apply": apply, "manifest": str(mp.relative_to(root)).replace("\\", "/"), "manifest_sha_before": sha0[:12],
           "old": {"file": old.get("file"), "sha256": (old.get("sha256") or "")[:12], "picked_by": old.get("picked_by")},
           "new": {"src": src_rel, "file": rel, "sha256": sha_src[:12], "exists_already": dst.is_file()}}
    if not apply:
        return out
    rel = AJ._copy_in(root, src, dst)
    hist = [{k: v for k, v in old.items() if k != "replaced"}] if old.get("file") else []
    new = {"file": rel, "sha256": AJ._sha((root / rel).read_bytes()), "sha256_source": "computed_at_register",
           "source": f"{src_rel}（{note}）", "picked_by": by, "picked_at": AJ._now(), "route": "server_ok", "adult": False,
           "replaced": (old.get("replaced") or []) + hist}
    d.setdefault("scenes", {}).setdefault(scene, {})["base"] = new
    sha1 = AJ._write_manifest(mp, d, sha0)
    out["manifest_sha_after"] = sha1[:12]
    out["push"] = AJ.push_files(root, [out["manifest"], rel]) if (push and AJ.push_enabled(root)) else {"skipped": "push 关着或 --no-push"}
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--run", required=True)
    ap.add_argument("--scene", required=True)
    ap.add_argument("--src", required=True, help="相对仓库根的源图路径")
    ap.add_argument("--name", required=True, help="新文件名后缀：<scene>_base_<name>.png")
    ap.add_argument("--by", default="总调度")
    ap.add_argument("--note", default="")
    ap.add_argument("--apply", action="store_true", help="不给 = dry-run")
    ap.add_argument("--no-push", action="store_true")
    a = ap.parse_args(argv)
    try:
        r = plan_replace(ROOT, a.run, a.scene, a.src, a.name, a.by, a.note, apply=a.apply, push=not a.no_push)
    except AJ.RegisterError as e:
        print(json.dumps({"ok": False, "why": str(e)}, ensure_ascii=False))
        return 1
    print(json.dumps({"ok": True, **r}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
