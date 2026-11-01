"""把 SERIES 作业清单（设定图 / 首帧）直接提交到 ComfyUI（SERIES 2026-10-31）。

作业文件：data/pipeline/runs/<run>/assets/{char_sheet_jobs,first_frame_jobs}.json
每条作业：{"id", "graph": <ComfyUI API prompt>, "out": <仓库相对路径 .png>, "priority", "status", …}
graph 里 LoadImage 的 image 写成 "@upload:<仓库相对路径>"：本工具先上传（JPEG q95，与 tools/ab/char_sheet_qi21.py 同法）再替换成服务器文件名。
只出图到 out，不改定妆、不改 config；已存在的 out 跳过（断点续跑）；每次串行一张。

    .venv/Scripts/python.exe tools/pipeline/submit_jobs.py --jobs data/pipeline/runs/series10_v1/assets/char_sheet_jobs.json \
        --url http://127.0.0.1:18188 [--only ch_a_lan] [--priority P1] [--status ready] [--limit N] [--dry-run]
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "ab"))


def _api(url, path, data=None, ctype="application/json", timeout=600):
    req = urllib.request.Request(url + path, data=data, headers={"Content-Type": ctype} if data else {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def placeholders(graph: dict) -> list[str]:
    return sorted({v[len("@upload:"):] for n in graph.values() for v in (n.get("inputs") or {}).values()
                   if isinstance(v, str) and v.startswith("@upload:")})


def resolve(graph: dict, names: dict[str, str]) -> dict:
    g = copy.deepcopy(graph)
    for n in g.values():
        for k, v in list((n.get("inputs") or {}).items()):
            if isinstance(v, str) and v.startswith("@upload:"):
                n["inputs"][k] = names[v[len("@upload:"):]]
    return g


def compile_mismatch(run_dir: Path, jobs: list[dict]) -> list[str]:
    """首帧作业提示词 ≠ 系统编译器输出的作业 id（tools/pipeline/image_jobs.frame_prompt）"""
    sys.path.insert(0, str(ROOT / "tools" / "pipeline"))
    import image_jobs as IJ
    bible, bad = IJ.load_bible(), []
    si = IJ.load_import()          # K-OPS-Q24：提示词来源 = 导入稿 data/import/script_v2.json（不再读 P4 稿）
    g, eps = si.globals, {e.number: e for e in si.episodes}
    for j in jobs:
        n = int(j["ep"])
        ep = eps.get(n)
        shot = next((s for s in ep.shots if s.id == j["shot"]), None) if ep else None
        want = IJ.frame_prompt(ep, shot, g, list(j.get("refs") or []), j.get("framing_project") or run_dir.name, bible)[0]             if shot else None
        gp = next((x["inputs"]["prompt"] for x in j["graph"].values() if x.get("class_type") == "TextEncodeQwenImage21"), None)
        if want is None or gp != want:
            bad.append(j["id"])
    return bad


def select(jobs: list[dict], only: str = "", priority: str = "", status: str = "") -> list[dict]:
    out = []
    for j in jobs:
        if only and not any(j["id"].startswith(x) for x in only.split(",")):
            continue
        if priority and not str(j.get("priority", "")).startswith(priority):
            continue
        if status and not str(j.get("status", "")).startswith(status):
            continue
        out.append(j)
    return sorted(out, key=lambda j: (str(j.get("priority", "Z")), j["id"]))


def _ns_tag(j: dict, idx: int | None = None, total: int | None = None) -> dict:
    """GPU 面板标签（K-OPS-G01，extra_data.ns_tag）：首帧作业带集/镜，设定图作业带造型"""
    sp = str(ROOT / "services" / "agent")
    if sp not in sys.path:
        sys.path.append(sp)
    from ns_agent import comfy_tag as CT
    frame = bool(j.get("shot"))
    sh = str(j.get("shot") or "")
    return CT.make("SERIES", "first_frame" if frame else "sheet", episode=int(j["ep"]) if j.get("ep") is not None else None,
                   shot=sh.rsplit("-", 1)[-1] if sh else None, obj=None if frame else (j.get("look") or j["id"]),
                   idx=idx, total=total, job=j["id"])


def run_one(url: str, j: dict, cache: dict, idx: int | None = None, total: int | None = None) -> float:
    import char_sheet_qi21 as CS
    for p in placeholders(j["graph"]):
        if p not in cache:
            cache[p] = CS.upload(url, ROOT / p)
    g = resolve(j["graph"], cache)
    body = {"prompt": g, "client_id": "series-" + j["id"]}
    try:   # 打标签出错也照常提交（不带标签）
        body["extra_data"] = {"ns_tag": _ns_tag(j, idx, total)}
    except Exception:  # noqa: BLE001
        body.pop("extra_data", None)
    pid = json.loads(_api(url, "/prompt", json.dumps(body).encode()))["prompt_id"]
    t0 = time.time()
    while True:
        time.sleep(5)
        h = json.loads(_api(url, f"/history/{pid}"))
        if pid in h:
            st = h[pid].get("status", {})
            if st.get("status_str") == "error":
                raise RuntimeError(json.dumps(st)[:800])
            for node in h[pid]["outputs"].values():
                for im in node.get("images", []):
                    dest = ROOT / j["out"]
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(_api(url, f"/view?filename={im['filename']}&subfolder={im['subfolder']}&type={im['type']}"))
                    dest.with_suffix(".json").write_text(json.dumps({**{k: v for k, v in j.items() if k != "graph"}, "prompt_id": pid,
                                                                     "lane": url, "render_s": round(time.time() - t0, 1)},
                                                                    ensure_ascii=False, indent=1), encoding="utf-8")
                    return time.time() - t0
        if time.time() - t0 > 3600:
            raise TimeoutError(pid)


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", required=True)
    ap.add_argument("--url", default="http://127.0.0.1:18188")
    ap.add_argument("--only", default="")
    ap.add_argument("--priority", default="")
    ap.add_argument("--status", default="")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-compile-check", action="store_true", help="跳过“提示词 = 编译器输出”检查（只在排查时用）")
    a = ap.parse_args(argv)
    d = json.loads((ROOT / a.jobs).read_text(encoding="utf-8"))
    jobs = select(d["jobs"] if isinstance(d, dict) else d, a.only, a.priority, a.status)
    jobs = [j for j in jobs if not (ROOT / j["out"]).exists()]
    if a.limit:
        jobs = jobs[: a.limit]
    if isinstance(d, dict) and d.get("kind") == "first_frame" and not a.no_compile_check:
        # K-REN-103：首帧作业的提示词必须等于系统编译器输出（tools/pipeline/image_jobs.py）；不一致就拒交，先重建作业
        bad = compile_mismatch((ROOT / a.jobs).parent.parent, jobs)
        if bad:
            print(f"拒绝提交：{len(bad)} 条首帧作业的提示词不是系统编译器输出（{bad[:5]}…）。"
                  f"先跑 .venv/Scripts/python.exe tools/pipeline/image_jobs.py {(ROOT / a.jobs).parent.parent.relative_to(ROOT)}",
                  flush=True)
            return 2
    if isinstance(d, dict) and d.get("kind") == "first_frame":
        # 生成契约 preflight（docs/GEN_CONTRACT.md I1–I10，ns_agent.gen_contract）：不过就拒交，没有绕过开关
        sys.path.insert(0, str(ROOT / "tools" / "pipeline"))
        sys.path.insert(0, str(ROOT / "services" / "agent"))
        import image_jobs as IJ
        from ns_agent.gen_contract import preflight as PF
        refused = [(j["id"], PF.check(IJ.contract_request(j))) for j in jobs]
        refused = [(i, r) for i, r in refused if not r.ok]
        if refused:
            for i, r in refused[:10]:
                print(f"拒绝提交 {i}：" + "；".join(r.reasons()), flush=True)
            print(f"共 {len(refused)} 条不过生成契约 preflight，已全部拒交（先补资产 / 重建作业：tools/pipeline/image_jobs.py）", flush=True)
            jobs = [j for j in jobs if j["id"] not in {i for i, _ in refused}]
    print(f"{len(jobs)} 条待出", flush=True)
    cache: dict = {}
    for i, j in enumerate(jobs, 1):
        if a.dry_run:
            print(j["id"], j.get("priority", ""), j["out"], placeholders(j["graph"]))
            continue
        s = run_one(a.url, j, cache, i, len(jobs))
        print(time.strftime("%H:%M:%S"), "done", j["id"], f"{s:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
