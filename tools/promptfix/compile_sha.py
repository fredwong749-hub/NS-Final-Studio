"""PROMPTFIX 11-02（ALIGNMENT 第 2 步）：按镜编译首帧 / 尾帧作业，输出 compile_trace 的 sha（提示词、参考图、编译输入），
两台各跑一次比对（同一 sv 版本 → 每镜 sha 必须相同）。只读：不出图、不写 takes。

    python tools/promptfix/compile_sha.py --ep 1 [--out x.json]          # 本机
    python tools/promptfix/compile_sha.py --compare a.json b.json         # 两份对比 → 表
    python tools/promptfix/compile_sha.py --shots ep08-S5 ep07-S3 --show  # 打印提示词 + trace
    python tools/promptfix/compile_sha.py --run series10_v2 --golden ep01-S1 ep01-S4 ep01-S7 --out g.json
        # 金样镜（V2_PLAN §五）：指定剧编译 + trace 完整性 + preflight（I11 清单 / I12 本地专用 / I13 品牌）逐镜判定；
        # 两台各跑一次再 --compare（prompt_sha / refs_sha 必须一致）
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in ("packages/schema", "services/render_router", "services/agent", "packages/qc", ""):
    sys.path.insert(0, str(ROOT / p))



def _atomic_write(path, text: str) -> None:
    """先写临时文件再 os.replace（arch_scan nonatomic_json）"""
    import os
    import tempfile
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)

def _trace(job: dict | None) -> dict | None:
    """部署代码还没有 compile_trace（sv-13 及更早）时，按同一口径现算 prompt_sha / refs_sha"""
    if not job:
        return None
    import hashlib
    h = lambda b: hashlib.sha256(b).hexdigest()[:16]   # noqa: E731
    refs = []
    for f in job.get("refs") or []:
        q = Path(f) if Path(f).is_absolute() else ROOT / f
        refs.append(hashlib.sha256(q.read_bytes()).hexdigest()[:16] if q.is_file() else f)
    return {"prompt_sha": h((job.get("prompt") or "").encode("utf-8")), "refs_sha": h(json.dumps(refs).encode()), "legacy": True}


TRACE_REQUIRED = ("prompt_sha", "refs", "refs_sha", "blocking", "faces", "conflicts", "wardrobe_scope", "route", "rules")


def trace_problems(tr: dict | None) -> list[str]:
    """金样镜 trace 完整性：必填字段齐、每张参考都有内容 sha"""
    if not tr:
        return ["没有 compile_trace"]
    bad = [f"缺 {k}" for k in TRACE_REQUIRED if k not in tr]
    bad += [f"参考 {r.get('file')} 无 sha（文件不在）" for r in tr.get("refs") or []
            if not r.get("sha") and not str(r.get("file") or "").endswith("_first_frame_placeholder.png")]   # 尾帧图1 = 出图后的首帧
    return bad


def preflight_of(job: dict, lane: str = "gpu36:1") -> dict:
    from ns_agent.gen_contract import preflight as PF
    req = {k: job.get(k) for k in ("model", "cast", "prompt", "refs", "asset_refs", "loras", "compiled_by", "route", "route_reasons")}
    req.update(kind="image", project=job.get("framing_project"), framing_project=job.get("framing_project"),
               shot_id=job.get("shot"), lane=lane)
    r = PF.check(req)
    return {"ok": r.ok, "fail": [f"{i.id} {i.detail}"[:200] for i in r.items if i.status == "fail"]}


def _script_for(run: str | None):
    from ns_render import pipeline as P
    if not run:
        return P.load_script(), None
    import importlib.util
    sp = importlib.util.spec_from_file_location("runs_cs", ROOT / "tools" / "autopilot" / "runs.py")
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    from ns_schema.script import ScriptImport
    return ScriptImport.model_validate_json(Path(m.script_path(run, ROOT)).read_text(encoding="utf-8")), run


def compile_shots(sids: list[str] | None = None, ep: int | None = None, run: str | None = None, golden: bool = False) -> dict:
    import os
    from ns_agent import frame_job as FJ
    from ns_render import unified_frame as UF
    if run:
        os.environ["NS_RUN"] = run                       # run_paths / pipeline 同一剧（K-OPS-E15 run_env）
    s, _r = _script_for(run)
    project = run if (run and FJ.AR.project_cfg(run)) else UF.project_for(s)
    out = {}
    for e in s.episodes:
        if ep is not None and int(e.number) != ep:
            continue
        for sh in e.shots:
            sid = f"ep{int(e.number):02d}-S{sh.index}"
            if sids and sid not in sids:
                continue
            try:
                job = FJ.build_first(project, e, sh, s.globals)
                last = FJ.build_last(job, "data/renders/_first_frame_placeholder.png") if job.get("last_prompt") else None
                if golden:
                    ft = job.get("compile_trace")
                    out.setdefault("_golden", {})[sid] = {"trace_problems": trace_problems(ft) + [f"尾帧：{x}" for x in (
                        trace_problems((last or {}).get("compile_trace")) if last else [])],
                        "preflight": preflight_of(job)}
                out[sid] = {"first": job.get("compile_trace") or _trace(job), "last": (last or {}).get("compile_trace") or _trace(last),
                            "prompt": job["prompt"], "last_prompt": (last or {}).get("prompt"), "refs": job["refs"],
                            "last_refs": (last or {}).get("refs")}
            except Exception as ex:  # noqa: BLE001
                out[sid] = {"error": repr(ex)[:300]}
    return out


def compare(a: dict, b: dict) -> list[dict]:
    rows = []
    for sid in sorted((set(a) | set(b)) - {"_golden"}, key=lambda x: (x.split("-")[0], int(x.split("S")[-1]))):
        x, y = a.get(sid) or {}, b.get(sid) or {}
        def k(d, st, f):
            return ((d.get(st) or {}) if isinstance(d, dict) else {}).get(f)
        r = {"shot": sid}
        for st in ("first", "last"):
            for f in ("prompt_sha", "refs_sha"):
                r[f"{st}.{f}"] = (k(x, st, f), k(y, st, f), k(x, st, f) == k(y, st, f))
        r["same"] = all(v[2] and v[0] is not None for kk, v in r.items() if kk != "shot" and not kk.startswith("last.")) and all(
            v[2] for kk, v in r.items() if kk.startswith("last."))
        rows.append(r)
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ep", type=int)
    ap.add_argument("--shots", nargs="*")
    ap.add_argument("--out")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--compare", nargs=2)
    ap.add_argument("--run")
    ap.add_argument("--golden", nargs="*")
    a = ap.parse_args(argv)
    if a.compare:
        A, B = (json.loads(Path(f).read_text(encoding="utf-8")) for f in a.compare)
        rows = compare(A, B)
        print("| 镜 | 首帧 prompt_sha | 首帧 refs_sha | 尾帧 prompt_sha | 尾帧 refs_sha | 一致 |")
        print("|---|---|---|---|---|---|")
        for r in rows:
            c = lambda f: (r[f][0] or "-") + ("" if r[f][2] else " ≠ " + str(r[f][1]))   # noqa: E731
            print(f"| {r['shot']} | {c('first.prompt_sha')} | {c('first.refs_sha')} | {c('last.prompt_sha')} | {c('last.refs_sha')} | {'是' if r['same'] else '否'} |")
        print(f"\n{sum(r['same'] for r in rows)}/{len(rows)} 镜一致")
        return 0 if all(r["same"] for r in rows) else 1
    res = compile_shots(a.golden or a.shots, a.ep, run=a.run, golden=a.golden is not None)
    if a.golden is not None:
        g = res.get("_golden") or {}
        for sid, v in g.items():
            print(sid, "trace 完整" if not v["trace_problems"] else "trace 问题：" + "；".join(v["trace_problems"]),
                  "| preflight", "通过" if v["preflight"]["ok"] else "不过：" + "；".join(v["preflight"]["fail"]))
    if a.out:
        _atomic_write(a.out, json.dumps(res, ensure_ascii=False, indent=1))
    if a.show:
        for sid, r in res.items():
            print("=====", sid)
            print(json.dumps(r, ensure_ascii=False, indent=1))
    else:
        print(json.dumps({k: {"first": (v.get("first") or {}).get("prompt_sha"), "last": (v.get("last") or {}).get("prompt_sha"),
                              "err": v.get("error")} for k, v in res.items()}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
