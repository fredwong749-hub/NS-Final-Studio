"""出图 preflight 的文件依赖（WORKFLOW 11-02，总调度 01:2x；规则 K-OPS-W13）：推送清单直接复用 preflight 的依赖收集，不另列一份。

producer 每一单都用 ns_agent.frame_job.build_first（唯一出图作业构建）得到作业，preflight（ns_agent.gen_contract.preflight，I1–I9）
检查的参考图就是作业里的 refs / asset_refs（身份脸、造型设定图及其去头裁切、景别单品 / 参考板、场景底图）。这里对现行导入稿的
每一镜调同一个 build_first，收集作业里出现的全部文件路径；裁切 / 参考板是由设定图现做的，所以把它们的来源（选定设定图、
单品图、场景目录的有效图）也带上（remote_preflight.asset_paths，服务器上缺裁切时 asset_refs 会按设定图重裁）。
W-REFS 11-06：再按 producer 重试阶梯每一档编一次（rung_deps），各档的派生参考图在笔记本生成、登记 sha、进推送清单。

    .venv/Scripts/python.exe tools/pipeline/preflight_deps.py            # 打印依赖数与按目录分布
    .venv/Scripts/python.exe tools/pipeline/preflight_deps.py --rungs series10_v2 --eps 2,3,4   # 只做阶梯派生图预生成
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


def preflight_deps(script=None, include_sources: bool = True, include_rungs: bool = True) -> dict:
    """→ {"files": 排序的仓库相对路径, "per_shot": {镜: [路径]}, "errors": {镜: 原因}, "rungs": rung_deps 摘要}。
    include_rungs（W-REFS 11-06）：再按 producer 重试阶梯每一档编一次（笔记本上顺手生成该档的派生参考图并登记 sha），
    这些图也进推送清单——服务器第 3 档“两张脸 + 参考板”等不再 DerivedRefMissing"""
    from ns_agent import frame_job as FJ
    from ns_render import pipeline as P
    from ns_render import unified_frame as UF
    sc = script or P.load_script()
    pj = UF.project_for(sc)
    files, per, errs, jobs = set(), {}, {}, {}
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
            jobs[sh.id] = j
    if include_sources:
        import remote_preflight as RP
        for paths in RP.asset_paths(ROOT).values():
            files |= {p.replace("\\\\", "/") for p in paths if not Path(p).is_absolute()}
    rs: dict = {}
    if include_rungs and pj:
        try:  # 复审 11-06：阶梯预建出任何错都不能拖垮推送（resident_sync.required_data → push）；退回只推默认档
            rs = rung_deps(sc, pj, jobs)
            files |= set(rs.get("files") or [])
        except Exception as e:  # noqa: BLE001  # arch-ok: 预建失败只记错误，默认档清单照推
            errs["_rungs"] = f"{type(e).__name__}: {e}"[:300]
            rs = {}
    files = {f for f in files if not f.startswith("data/cache/")}
    return {"files": sorted(files), "per_shot": per, "errors": errs,
            "rungs": {k: v for k, v in rs.items() if k != "files"}}


# ---------------------------------------------------------------------------------------------------------------------
# W-REFS 11-06：重试阶梯各档的派生参考图（refboards / refcrops）在笔记本预生成 + 进推送清单。
# 起因：gpu36 23:36 ep02-S13 第 3 次“退到 两张脸 + 参考板（B）”→ DerivedRefMissing board_1394f5efddbd.png——派生图只在笔记本生成、
# 按 sha 推（K-OPS-F23），而笔记本只编默认档，阶梯后几档的板从没生成过。这里对“过了导入闸门”的集、非成人镜，按
# producer.prebuild_rungs 列出的每一档调 producer.first_job_for_rung / last_job_for_rung（与服务器出图同一函数），生成的就是服务器会要的那张。
# 只在笔记本跑（服务器上直接返回空）；冻结 / 归档的剧不写（derived_writable）。按镜缓存：默认作业 + 相关代码没变、上次的文件都在且
# 派生图 sha 账本对得上 → 不重编（每轮 resident_sync 都调，命中时只读缓存）

RUNG_CODE = ("services/agent/ns_agent/asset_refs.py", "services/agent/ns_agent/frame_job.py",
             "tools/autopilot/producer.py", "tools/assetmaster/frames_v2.py", "tools/pipeline/preflight_deps.py")
DERIVED_PARTS = ("/refboards/", "/refcrops/")


def _rung_cache_path(run: str) -> Path:
    from ns_agent import asset_refs as AR
    base = Path(AR.DERIVED_OUT) if AR.DERIVED_OUT is not None else ROOT / "data" / "cache"
    return base / "rung_refs" / f"{run}.json"


def _code_sig() -> str:
    parts = []
    for f in RUNG_CODE:
        try:
            st = (ROOT / f).stat()
            parts.append(f"{f}:{st.st_size}:{st.st_mtime_ns}")
        except OSError:
            parts.append(f"{f}:-")
    return "|".join(parts)


def _shot_sig(job: dict, first_file: str | None, code: str) -> str:
    import hashlib
    blob = json.dumps({k: job.get(k) for k in ("prompt", "refs", "asset_refs", "last_prompt", "adult")}, ensure_ascii=False,
                      sort_keys=True, default=str)
    return hashlib.sha256(f"{blob}\n{first_file}\n{code}".encode("utf-8")).hexdigest()[:20]


def _files_ok(files: list[str]) -> bool:
    """缓存命中的前提：上次的文件都还在；派生图（refboards / refcrops）还要 sha 账本对得上"""
    from ns_agent import asset_refs as AR
    for f in files:
        p = ROOT / f
        if not p.is_file():
            return False
        if any(d in "/" + f for d in DERIVED_PARTS) and not AR.derived_sha_ok(p):
            return False
    return True


def _two_person(shot) -> bool:
    return sum(1 for c in shot.cast if getattr(c, "presence", None) == "在画") >= 2


def adult_shot(shot) -> bool:
    """成人镜判定：与 sop_gate 完全同一口径——导入稿每镜的 shot.adult（compile_preflight 逐镜 getattr(sh, "adult") /
    adult_shots_of 读 s.get("adult")；probe-prompts 记 pending_owner 的就是这些镜）。不看集、不看造型 / 资产标记"""
    return bool(shot.get("adult") if isinstance(shot, dict) else getattr(shot, "adult", False))


def shot_triggered(run: str, shot_id: str) -> bool:
    """L-216：这一镜是否已被项目方触发（读 sop_gate.triggered_adult_shots，与闸门同一口径）；读不到 = 没触发（fail-closed）"""
    m = re.match(r"ep(\d+)-S(\d+)", str(shot_id))
    if not m:
        return False
    try:
        sys.path.insert(0, str(ROOT / "tools" / "master"))
        import sop_gate as _SG
        return int(m.group(2)) in _SG.triggered_adult_shots(run, int(m.group(1)), ROOT)
    except Exception:  # noqa: BLE001  # arch-ok: 读不到触发清单 = 当作没触发，不预建
        return False


def _ep_no(shot_id: str) -> int | None:
    m = re.match(r"ep(\d+)-S(\d+)", str(shot_id))
    return int(m.group(1)) if m else None


def _passed_import_eps(run: str) -> set[int] | None:
    """过了导入闸门的集号；sop_gate 读不到 → None（不按集过滤，导入稿里的集都算）"""
    try:
        if str(ROOT / "tools" / "master") not in sys.path:
            sys.path.insert(0, str(ROOT / "tools" / "master"))
        import sop_gate as SG
        return {e for e in SG.episodes_of(run) if SG.check_import(ROOT, run, e).get("ok")}
    except Exception as e:  # noqa: BLE001  # arch-ok: 闸门读不到 = 不过滤（多生成几张板无害，少生成才会卡服务器）
        print(f"[preflight_deps.rung_deps] {run} 导入闸门读不到，不按集过滤：{e!r}"[:200], file=sys.stderr)
        return None


def rung_deps(sc, run: str, default_jobs: dict, *, episodes: set[int] | None = None, force: bool = False) -> dict:
    """→ {"files": 各档作业引用的文件（不含首帧成片）, "per_shot": {镜: [文件]}, "errors": {镜/首尾/档: 原因},
          "built": 现编的镜数, "cached": 缓存命中镜数, "skipped": 整体跳过的原因}。只在笔记本生成；episodes 给了就只做这些集"""
    from ns_agent import asset_refs as AR
    out: dict = {"files": [], "per_shot": {}, "errors": {}, "built": 0, "cached": 0, "skipped": None}
    if AR._on_server():
        out["skipped"] = "服务器上不生成派生参考图（K-OPS-F23）"
        return out
    if not AR.derived_writable(run):
        out["skipped"] = f"{run} 不在制作中（冻结 / 归档 / 暂停），不写派生图"
        return out
    if str(ROOT / "tools" / "autopilot") not in sys.path:
        sys.path.insert(0, str(ROOT / "tools" / "autopilot"))
    import producer as PR
    from ns_render import pipeline as P
    ok_eps = _passed_import_eps(run)
    cp = _rung_cache_path(run)
    try:
        cache = json.loads(cp.read_text(encoding="utf-8")) if cp.is_file() else {}
    except (OSError, ValueError):   # arch-ok: 缓存坏了 = 全部重编（只是慢一轮）
        cache = {}
    code = _code_sig()
    files: set[str] = set()
    changed = False
    for ep in sc.episodes:
        for sh in ep.shots:
            n = _ep_no(sh.id)
            if (episodes is not None and n not in episodes) or (ok_eps is not None and n not in ok_eps):
                continue
            j0 = default_jobs.get(sh.id)
            if j0 is None or (adult_shot(sh) and not shot_triggered(run, sh.id)):   # 未触发的成人镜不预生成；已触发的（L-216）照常预建；口径同 sop_gate
                continue
            try:
                ft = PR.active_take(P.load_takes(sh.id), "image")
            except Exception:  # noqa: BLE001  # arch-ok: 没有 takes = 用占位首帧路径（派生图与首帧文件无关）
                ft = None
            first_file = (f"data/{ft['file']}" if ft and ft.get("file")
                          else f"data/cache/rung_refs/{run}_first_placeholder.png")   # 派生图与首帧文件无关；占位不进推送清单
            sig = _shot_sig(j0, first_file, code)
            hit = cache.get(sh.id) or {}
            if not force and hit.get("sig") == sig and _files_ok(hit.get("files") or []):
                out["cached"] += 1
                out["per_shot"][sh.id] = hit["files"]
                files |= set(hit["files"])
                continue
            ps: set[str] = set()
            errs = 0
            tp = _two_person(sh)
            for kind in ("first", "last"):
                for rg in PR.prebuild_rungs(kind, tp):
                    r = dict(rg)
                    try:
                        fj = PR.first_job_for_rung(run, ep, sh, sc.globals, r, kind, run)
                        if kind == "last":
                            if not fj.get("last_prompt"):
                                continue
                            job = PR.last_job_for_rung(run, ep, sh, sc.globals, fj, first_file, r)
                        else:
                            job = fj
                        if r.get("rung_skip"):          # 笔记本上不该发生（这里能生成）；记下来给人看
                            raise RuntimeError("rung_skip：" + str(r["rung_skip"].get("error")))
                        ps |= job_paths(job)
                    except Exception as e:  # noqa: BLE001
                        errs += 1
                        out["errors"][f"{sh.id}/{kind}/{rg['name']}"] = f"{type(e).__name__}: {e}"[:200]
            ps = {f for f in ps if f != first_file and (ROOT / f).is_file()}
            out["per_shot"][sh.id] = sorted(ps)
            files |= ps
            out["built"] += 1
            if not errs:                                 # 有档编不出 → 不进缓存，下一轮再试
                cache[sh.id] = {"sig": sig, "files": sorted(ps)}
                changed = True
    if changed:
        try:
            cp.parent.mkdir(parents=True, exist_ok=True)
            tmp = cp.with_suffix(".tmp")
            tmp.write_text(json.dumps(cache, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
            tmp.replace(cp)
        except OSError as e:   # arch-ok: 缓存写不了 = 下一轮重编（只是慢）
            print(f"[preflight_deps.rung_deps] 缓存写不了：{e!r}"[:200], file=sys.stderr)
    out["files"] = sorted(files)
    return out


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--rungs", help="只做阶梯派生图预生成：剧名（如 series10_v2）")
    ap.add_argument("--eps", default="", help="集号，逗号分隔（默认：过了导入闸门的全部集）")
    ap.add_argument("--force", action="store_true", help="不看缓存，全部重编")
    a = ap.parse_args()
    if a.rungs:
        import os
        sys.path.insert(0, str(ROOT / "tools" / "autopilot"))
        import runs as RN
        os.environ.update(RN.run_env(a.rungs, ROOT))      # 与 tools/master/_w38_make_board.py 同：先定剧再导入 pipeline（takes 路径按剧）
        import image_jobs as IJ
        from ns_agent import frame_job as FJ
        from ns_render import unified_frame as UF
        sc = IJ.load_import(a.rungs)
        eps = {int(x) for x in a.eps.split(",") if x.strip()} or None
        pj = UF.project_for(sc)
        jobs = {sh.id: FJ.build_first(pj, ep, sh, sc.globals) for ep in sc.episodes for sh in ep.shots
                if eps is None or _ep_no(sh.id) in eps}
        r = rung_deps(sc, pj, jobs, episodes=eps, force=a.force)
        print(json.dumps({k: v for k, v in r.items() if k != "per_shot"}, ensure_ascii=False, indent=1)[:6000])
        sys.exit(0)
    r = preflight_deps()
    import collections
    print(len(r["per_shot"]), "镜；依赖", len(r["files"]), "个；构建出错", len(r["errors"]))
    print(collections.Counter("/".join(f.split("/")[:4]) for f in r["files"]).most_common(12))
    missing = [f for f in r["files"] if not (ROOT / f).is_file()]
    print("本地缺：", missing[:20])
    print("阶梯派生图：", json.dumps(r.get("rungs") or {}, ensure_ascii=False)[:600])
