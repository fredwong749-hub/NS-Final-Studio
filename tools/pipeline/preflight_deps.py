"""出图 preflight 的文件依赖（WORKFLOW 11-02，总调度 01:2x；规则 K-OPS-W13）：推送清单直接复用 preflight 的依赖收集，不另列一份。

producer 每一单都用 ns_agent.frame_job.build_first（唯一出图作业构建）得到作业，preflight（ns_agent.gen_contract.preflight，I1–I9）
检查的参考图就是作业里的 refs / asset_refs（身份脸、造型设定图及其去头裁切、景别单品 / 参考板、场景底图）。这里对现行导入稿的
每一镜调同一个 build_first，收集作业里出现的全部文件路径；裁切 / 参考板是由设定图现做的，所以把它们的来源（选定设定图、
单品图、场景目录的有效图）也带上（remote_preflight.asset_paths，服务器上缺裁切时 asset_refs 会按设定图重裁）。

    .venv/Scripts/python.exe tools/pipeline/preflight_deps.py            # 打印依赖数与按目录分布
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in ("services/agent", "services/render_router", "packages/schema", "services/api", "tools/pipeline"):
    if str(ROOT / _p) not in sys.path:
        sys.path.insert(0, str(ROOT / _p))

PATH_RE = re.compile(r"(?:data|assets)/[A-Za-z0-9_./-]+?\.(?:png|jpg|jpeg|webp)", re.I)   # 路径都是 ASCII；避免跨中文说明串误配


def job_paths(job: dict) -> set[str]:
    blob = json.dumps({k: job.get(k) for k in ("refs", "asset_refs", "reference", "references", "board")}, ensure_ascii=False)
    return {m.replace("\\\\", "/") for m in PATH_RE.findall(blob)}


def preflight_deps(script=None, include_sources: bool = True) -> dict:
    """→ {"files": 排序的仓库相对路径, "per_shot": {镜: [路径]}, "errors": {镜: 原因}}"""
    from ns_agent import frame_job as FJ
    from ns_render import pipeline as P
    from ns_render import unified_frame as UF
    sc = script or P.load_script()
    pj = UF.project_for(sc)
    files, per, errs = set(), {}, {}
    for ep in sc.episodes:
        for sh in ep.shots:
            try:
                j = FJ.build_first(pj, ep, sh, sc.globals)
            except Exception as e:  # noqa: BLE001
                errs[sh.id] = repr(e)[:200]
                continue
            ps = job_paths(j)
            per[sh.id] = sorted(ps)
            files |= ps
    if include_sources:
        import remote_preflight as RP
        for paths in RP.asset_paths(ROOT).values():
            files |= {p.replace("\\\\", "/") for p in paths if not Path(p).is_absolute()}
    files = {f for f in files if not f.startswith("data/cache/")}
    return {"files": sorted(files), "per_shot": per, "errors": errs}


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    r = preflight_deps()
    import collections
    print(len(r["per_shot"]), "镜；依赖", len(r["files"]), "个；构建出错", len(r["errors"]))
    print(collections.Counter("/".join(f.split("/")[:4]) for f in r["files"]).most_common(12))
    missing = [f for f in r["files"] if not (ROOT / f).is_file()]
    print("本地缺：", missing[:20])
