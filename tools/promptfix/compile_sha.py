"""PROMPTFIX 11-02（ALIGNMENT 第 2 步）：按镜编译首帧 / 尾帧作业，输出 compile_trace 的 sha（提示词、参考图、编译输入），
两台各跑一次比对（同一 sv 版本 → 每镜 sha 必须相同）。只读：不出图、不写 takes。

    python tools/promptfix/compile_sha.py --ep 1 [--out x.json]          # 本机
    python tools/promptfix/compile_sha.py --compare a.json b.json         # 两份对比 → 表
    python tools/promptfix/compile_sha.py --shots ep08-S5 ep07-S3 --show  # 打印提示词 + trace
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


def compile_shots(sids: list[str] | None = None, ep: int | None = None) -> dict:
    from ns_agent import frame_job as FJ
    from ns_render import pipeline as P
    from ns_render import unified_frame as UF
    s = P.load_script()
    project = UF.project_for(s)
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
                out[sid] = {"first": job.get("compile_trace") or _trace(job), "last": (last or {}).get("compile_trace") or _trace(last),
                            "prompt": job["prompt"], "last_prompt": (last or {}).get("prompt"), "refs": job["refs"],
                            "last_refs": (last or {}).get("refs")}
            except Exception as ex:  # noqa: BLE001
                out[sid] = {"error": repr(ex)[:300]}
    return out


def compare(a: dict, b: dict) -> list[dict]:
    rows = []
    for sid in sorted(set(a) | set(b), key=lambda x: (x.split("-")[0], int(x.split("S")[-1]))):
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
    res = compile_shots(a.shots, a.ep)
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
