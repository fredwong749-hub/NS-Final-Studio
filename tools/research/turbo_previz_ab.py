"""L-206 ②A 对照（给项目方看了再切）：ep01 S1–S4 首帧 turbo_previz（8 步 turbo + 摆位图深度 Fun ControlNet）vs 当前定稿首帧（takes.json active）。
作业 = 生产同一条编译路径（frame_job.build_first，当前 psm11 导入稿）+ job_patch{tier=turbo_previz, previz=自动摆位图}；只实验：scope=ab
（unified_frame.render_ab：不写 takes / 账本，图存 data/ab/<exp>/<shot>/）。对照 = 生产当前版（不重出）。身份 = 生产 Q1（ArcFace，gpu33 原地算）。

  dry    .venv/Scripts/python.exe -X utf8 tools/research/turbo_previz_ab.py dry                 # 离线：编作业 + 摆位图 + ComfyUI 图 + preflight，不碰 GPU
  run    .venv/Scripts/python.exe -X utf8 tools/research/turbo_previz_ab.py run --lane gpu36:0  # 只一条道、队列空才提交、顺序出，不抢占
  score  .venv/Scripts/python.exe -X utf8 tools/research/turbo_previz_ab.py score [--host gpu33]
  sheet  .venv/Scripts/python.exe -X utf8 tools/research/turbo_previz_ab.py sheet               # 并排 JPG + HTML（耗时 / Q1 身份分）
可选 --shots ep01-S1,ep01-S4 --seeds 2 --strength 0.55 --end 0.7 --exp turbo_previz（换控制参数时换实验名，如 turbo_previz_e0p8）。
"""
from __future__ import annotations

import argparse
import html
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in ("services/agent", "packages/schema", "services/render_router", "services/api", "tools/pipeline", "tools/autopilot",
           "tools/gen_contract", "tools/research", "tools/previz"):
    if str(ROOT / _p) not in sys.path:
        sys.path.insert(0, str(ROOT / _p))

RUN = "series10_v2"
SHOTS = ["ep01-S1", "ep01-S2", "ep01-S3", "ep01-S4"]
SEED_BASE = 20600            # 种子 = SEED_BASE + 镜号×10 + k（固定、可复现）
EXP = "turbo_previz"


def exp_dir(exp: str) -> Path:
    return ROOT / "data" / "ab" / exp


def seeds_for(shot: str, n: int) -> list[int]:
    k = int(shot.split("-S")[1])
    return [SEED_BASE + k * 10 + i for i in range(1, n + 1)]


def script():
    import runs as R
    from ns_schema.script import ScriptImport
    return ScriptImport.model_validate(json.loads(Path(R.script_path(RUN)).read_text(encoding="utf-8")))


def rows(exp: str) -> list[dict]:
    f = exp_dir(exp) / "takes.jsonl"
    allr = [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()] if f.exists() else []
    return list({(r["shot"], int(r["seed"])): r for r in allr}.values())


def patch_for(shot_id: str, shot, g, strength: float, end: float) -> dict:
    """job_patch：tier=turbo_previz + 本镜自动摆位图（frame_job.previz_inputs → auto_blocking.ensure_previz，按输入哈希缓存）"""
    from ns_agent import frame_job as FJ
    pv = FJ.previz_inputs(shot_id, shot=shot, g=g, stage="first")
    if not pv:
        raise SystemExit(f"{shot_id} 没有摆位图（config turbo_previz.auto.enabled 关了？）")
    pv.update(strength=strength, end_percent=end)
    tier, ov = FJ.first_frame_tier(RUN, force="turbo_previz")
    if tier != "turbo_previz":
        raise SystemExit("config/render_quality.json first_frame_tier.turbo_previz 不在")
    return {"previz": pv, "tier": tier, "tier_overrides": ov}


def q1_of(pf: dict | None) -> dict:
    """postflight → {status, sims{角色: 余弦}, faces, strangers}"""
    q1 = next((i for i in (pf or {}).get("items", []) if i.get("id") == "Q1"), {})
    ev = q1.get("evidence") or {}
    sims = ev.get("sims") or {x.get("ref") or x.get("character") or str(k): x.get("sim") for k, x in enumerate(ev.get("per_face") or [])}
    return {"status": q1.get("status"), "sims": {k: v for k, v in (sims or {}).items() if v is not None},
            "faces": ev.get("faces"), "strangers": len(ev.get("strangers") or [])}


def base_take(shot_id: str) -> dict | None:
    """生产当前定稿首帧（takes.json active.image；没有 active 取最后一张）：文件 / 耗时 / 档 / Q1"""
    from ns_render import pipeline as P
    doc = P.load_takes(shot_id)
    tk = [t for t in doc.get("takes", []) if t.get("stage") == "image"]
    cur = (doc.get("active") or {}).get("image")
    pick = next((t for t in tk if t.get("n") == cur), None) or (tk[-1] if tk else None)
    if not pick:
        return None
    tier = ((pick.get("params") or {}).get("tier") or {}).get("id") or "preview"
    return {"n": pick.get("n"), "active": pick.get("n") == cur, "file": pick.get("file"), "seconds": pick.get("seconds"), "tier": tier,
            "q1": q1_of(pick.get("postflight")), "seed": pick.get("seed")}


def mean(xs: list) -> float | None:
    xs = [float(x) for x in xs if x is not None]
    return round(sum(xs) / len(xs), 3) if xs else None


# ---------------------------------------------------------------- dry（离线）
def dry(shots: list[str], strength: float, end: float, exp: str, seeds_n: int = 1) -> dict:
    """不碰 GPU：每镜 生产作业 → patch（摆位图，记耗时）→ ComfyUI 图（build_graph，核 ControlNet 节点 + 8 步）→ preflight → jobs.json + 摆位图联系表"""
    from ns_agent import frame_job as FJ
    from ns_agent.gen_contract import preflight as PF
    from ns_render import pipeline as P
    from ns_render import unified_frame as UF
    import auto_blocking as AB
    import runs as R
    sc = script()
    project = UF.project_for(sc)
    out = exp_dir(exp) / "dry"
    out.mkdir(parents=True, exist_ok=True)
    res = []
    for sid in shots:
        ep, shot = P.find_shot(sc, sid)
        t0 = time.time()
        job = FJ.build_first(project, ep, shot, sc.globals)
        t1 = time.time()
        patch = patch_for(sid, shot, sc.globals, strength, end)
        t2 = time.time()
        job2 = {**job, **patch}
        job2.pop("previz_missing", None)
        wf, eff, _sent = UF.build_graph(job2, seeds_for(sid, 1)[0], lambda p: Path(p).name, "dry")
        cn = wf.get("202") or {}
        ok_graph = cn.get("class_type") == "ZImageFunControlnet" and int(eff.get("steps") or 0) == 8 and eff.get("unet") == "turbo"
        req = {k: job2.get(k) for k in ("model", "cast", "prompt", "refs", "asset_refs", "loras", "compiled_by", "route", "route_reasons", "lane")}
        req.update(kind="image", project=job2.get("framing_project"), shot_id=sid)
        pf = PF.check(req)
        pv = patch["previz"]
        base = base_take(sid)
        spec_meta = {}
        try:
            spec_meta = json.loads((FJ._ROOT / pv["auto"]["dir"] / f"S{AB.shot_no(sid)}.json").read_text(encoding="utf-8")).get("meta") or {}
        except (OSError, ValueError, KeyError):   # arch-ok: 只是联系表标注，缺了不影响作业
            pass
        r = {"shot": sid, "seeds": seeds_for(sid, seeds_n), "compile_s": round(t1 - t0, 2), "previz_s": pv.get("auto", {}).get("seconds"),
             "previz_cached": pv.get("auto", {}).get("cached"), "previz_sha": pv["sha"], "control": pv["control"], "strength": pv["strength"],
             "end_percent": pv["end_percent"], "graph_ok": ok_graph, "steps": eff.get("steps"), "unet": eff.get("unet"),
             "preflight_ok": pf.ok, "preflight_reasons": pf.reasons(), "refs": job2["refs"], "face_files": job2.get("face_files"),
             "prompt_sha": job2["compile_trace"]["prompt_sha"], "size": spec_meta.get("size"), "focal_mm": spec_meta.get("focal_mm"),
             "angle": spec_meta.get("angle"), "base": base, "tier_now": job.get("tier") or "preview", "previz_dir": pv["auto"]["dir"],
             "patch_s": round(t2 - t1, 2)}
        res.append(r)
        print(f"{sid}: 摆位图 {r['previz_s']}s{'（缓存）' if r['previz_cached'] else ''} {spec_meta.get('size')} {spec_meta.get('focal_mm')}mm "
              f"{(spec_meta.get('angle') or {}).get('azimuth')} | 图 {'ok' if ok_graph else '不对'} steps={eff.get('steps')} | preflight "
              f"{'ok' if pf.ok else '不过：' + '；'.join(pf.reasons())} | 当前定稿 {base and base['tier']} n={base and base['n']} "
              f"{base and base['seconds']}s Q1={base and base['q1']['sims']}", flush=True)
    doc = {"exp": exp, "run": RUN, "shots": shots, "strength": strength, "end_percent": end, "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
           "script": Path(R.script_path(RUN)).resolve().relative_to(ROOT.resolve()).as_posix(), "items": res}
    tmp = out / "jobs.json.tmp"
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(out / "jobs.json")
    AB.contact_sheet([(f"{r['shot']} {r['focal_mm'] or ''}mm", FJ._ROOT / r["previz_dir"] / f"S{AB.shot_no(r['shot'])}_preview.png") for r in res],
                     out / "previz_sheet.jpg", cols=4, th=640)
    print("写", out / "jobs.json", "|", out / "previz_sheet.jpg")
    return doc


# ---------------------------------------------------------------- run（一条道）
def run(lane: str, shots: list[str], seeds_n: int, exp: str, strength: float, end: float, idle_s: float = 20, wait_max: float = 3600) -> None:
    import look_v2_ab as L
    from ns_agent import comfy_tag as CT
    from ns_api import jobs as J
    from ns_render import endpoints as EP
    from ns_render import pipeline as P
    from ns_render import unified_frame as UF
    sc = script()
    have = {(r["shot"], int(r["seed"])) for r in rows(exp)}
    todo = [(sid, s) for sid in shots for s in seeds_for(sid, seeds_n) if (sid, s) not in have]
    print("待出", len(todo), "道", lane, flush=True)
    client = J._make_client(lane)
    host = EP.server_of(lane)
    for sid, s in todo:
        if not L.wait_idle(lane, idle_s, wait_max):
            print("道一直不空，停", flush=True)
            return
        ep_s, sh_s = sid.split("-")
        _ep, shot = P.find_shot(sc, sid)
        tag = CT.make("TURBO-PREVIZ", "bakeoff", episode=int(ep_s[2:]), shot=sh_s, label=f"实验 {exp}")
        try:
            rec = UF.render_ab(client, sc, sid, experiment=exp, tier="turbo_previz", seed=s, tag=tag, postflight=False, host=host,
                               job_patch=patch_for(sid, shot, sc.globals, strength, end))
            print(sid, s, lane, rec["file"], rec["seconds"], "s", flush=True)
        except Exception as e:  # noqa: BLE001
            print(sid, s, lane, "失败", type(e).__name__, str(e)[:300], flush=True)
            time.sleep(30)


# ---------------------------------------------------------------- score（Q1 身份等）
def score(exp: str, host: str = "gpu33") -> list[dict]:
    import remote_score as RS
    from ns_render import unified_frame as UF
    recs = rows(exp)
    sc = script()
    project = UF.project_for(sc)
    cf = exp_dir(exp) / "scores.json"
    cache = json.loads(cf.read_text(encoding="utf-8")) if cf.exists() else {}
    need = [r for r in recs if r["file"] not in cache]
    jobs = []
    for r in need:
        job = UF._job_for(sc, r["shot"], project, None)
        jobs.append({"id": r["id"], "file": str(ROOT / "data" / r["file"]), "post": None,
                     "request": {"cast": job.get("cast"), "asset_refs": job.get("asset_refs")}})
    for i in range(0, len(jobs), 12):
        got = RS.postflight_full(host, jobs[i:i + 12], label=f"{exp} postflight")
        for r, j in zip(need[i:i + 12], jobs[i:i + 12]):
            cache[r["file"]] = got.get(j["id"])
        tmp = cf.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        tmp.replace(cf)
    summ = []
    for r in sorted(recs, key=lambda x: (x["shot"], x["seed"])):
        q1 = q1_of(cache.get(r["file"]))
        summ.append({"shot": r["shot"], "seed": r["seed"], "q1": q1["status"], "sims": q1["sims"], "mean_sim": mean(list(q1["sims"].values())),
                     "faces": q1["faces"], "strangers": q1["strangers"], "sec": r["seconds"], "file": r["file"]})
    tmp = exp_dir(exp) / "summary.json.tmp"
    tmp.write_text(json.dumps(summ, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(exp_dir(exp) / "summary.json")
    print(json.dumps(summ, ensure_ascii=False, indent=1))
    return summ


# ---------------------------------------------------------------- sheet（并排）
def _label_base(b: dict | None) -> str:
    if not b:
        return "当前定稿：无"
    q = b["q1"]
    sims = " ".join(f"{k}={v:.2f}" for k, v in q["sims"].items()) if q["sims"] else "Q1 未测"
    return f"当前定稿 n={b['n']} {b['tier']} {b['seconds'] or '?'}s | {sims}"


def _label_tp(r: dict, s: dict | None) -> str:
    sims = (" ".join(f"{k}={v:.2f}" for k, v in s["sims"].items()) if s and s.get("sims") else "Q1 未测")
    return f"turbo_previz seed{r['seed']} {r['seconds']}s | {sims}"


def sheet(exp: str, shots: list[str]) -> Path:
    from PIL import Image, ImageDraw
    import auto_blocking as AB
    from ns_agent import frame_job as FJ
    out = exp_dir(exp)
    out.mkdir(parents=True, exist_ok=True)
    byk = {(r["shot"], int(r["seed"])): r for r in rows(exp)}
    sf = out / "summary.json"
    summ = {(x["shot"], int(x["seed"])): x for x in json.loads(sf.read_text(encoding="utf-8"))} if sf.exists() else {}
    dj = out / "dry" / "jobs.json"
    dry_items = {x["shot"]: x for x in json.loads(dj.read_text(encoding="utf-8")).get("items", [])} if dj.exists() else {}
    H = 960
    rows_img, html_rows = [], []
    for sid in shots:
        n = AB.shot_no(sid)
        base = base_take(sid)
        cells = []
        d = dry_items.get(sid)
        if d:
            cells.append((f"{sid} 摆位图 {d.get('focal_mm') or ''}mm {(d.get('angle') or {}).get('azimuth') or ''} {d.get('previz_s')}s",
                          FJ._ROOT / d["previz_dir"] / f"S{n}_preview.png"))
        if base and base.get("file"):
            cells.append((_label_base(base), ROOT / "data" / base["file"]))
        tps = sorted((k for k in byk if k[0] == sid), key=lambda k: k[1])
        for k in tps:
            cells.append((_label_tp(byk[k], summ.get(k)), ROOT / "data" / byk[k]["file"]))
        ims = []
        for lab, p in cells:
            if p.exists():
                im = Image.open(p).convert("RGB")
                ims.append((lab, im.resize((int(im.width * H / im.height), H))))
        if not ims:
            continue
        row = Image.new("RGB", (sum(i.width for _, i in ims) + 8 * len(ims), H + 26), (24, 24, 28))
        dr = ImageDraw.Draw(row)
        x = 0
        for lab, i in ims:
            dr.text((x + 4, 6), lab, fill=(230, 230, 230))
            row.paste(i, (x, 26))
            x += i.width + 8
        rows_img.append(row)
        tp_mean = mean([summ[k]["mean_sim"] for k in tps if k in summ and summ[k].get("mean_sim") is not None])
        html_rows.append({"shot": sid, "cells": [(lab, p) for lab, p in cells if p.exists()], "base": base,
                          "tp_sec": mean([byk[k]["seconds"] for k in tps]), "tp_q1": tp_mean,
                          "base_q1": mean(list(base["q1"]["sims"].values())) if base else None})
    if not rows_img:
        raise SystemExit("没有可拼的图（先 dry / run）")
    W = max(r.width for r in rows_img)
    big = Image.new("RGB", (W, sum(r.height for r in rows_img) + 6 * len(rows_img)), (24, 24, 28))
    y = 0
    for r in rows_img:
        big.paste(r, (0, y))
        y += r.height + 6
    dst = out / f"sheet_{shots[0].split('-')[0]}_{'-'.join(s.split('-')[1] for s in shots)}.jpg"
    big.save(dst, quality=88)
    _write_html(dst.with_suffix(".html"), html_rows, exp)
    print(dst, "|", dst.with_suffix(".html"))
    return dst


def _write_html(dst: Path, rows_: list[dict], exp: str) -> None:
    """本地打开的审片页：每镜一行（摆位图 | 当前定稿 | turbo_previz ×种子），下面一张耗时 / 身份表"""
    def rel(p: Path) -> str:
        try:
            return Path(p).resolve().relative_to(dst.parent.resolve()).as_posix()
        except ValueError:
            return ("../../.." / Path(p).resolve().relative_to(ROOT.resolve())).as_posix()
    parts = [f"<!doctype html><meta charset='utf-8'><title>L-206 ②A 对照 {html.escape(exp)}</title>",
             "<style>body{background:#18181c;color:#ddd;font:14px system-ui;margin:16px}.row{display:flex;gap:8px;margin-bottom:14px}"
             ".c{max-width:32vw}.c img{width:100%;height:auto;display:block}.c div{font-size:12px;color:#bbb;padding:3px 0}"
             "table{border-collapse:collapse;margin-top:16px}td,th{border:1px solid #444;padding:4px 10px}</style>",
             f"<h2>L-206 ②A：turbo 8 步 + 摆位图 vs 当前定稿首帧（ep01 S1–S4，实验 {html.escape(exp)}）</h2>",
             "<p>左→右：摆位图（自动从分镜算的深度 / 站位预览）｜当前定稿首帧（takes.json active，档 / 秒 / Q1 身份余弦）｜turbo_previz 各种子（秒 / Q1）。</p>"]
    for r in rows_:
        parts.append("<div class='row'>")
        for lab, p in r["cells"]:
            parts.append(f"<div class='c'><div>{html.escape(lab)}</div><img src='{html.escape(rel(p))}'></div>")
        parts.append("</div>")
    parts.append("<table><tr><th>镜</th><th>当前定稿档</th><th>定稿秒</th><th>定稿 Q1 均值</th><th>turbo_previz 秒（均）</th><th>turbo_previz Q1 均值</th></tr>")
    for r in rows_:
        b = r["base"] or {}
        parts.append(f"<tr><td>{r['shot']}</td><td>{html.escape(str(b.get('tier') or '-'))}</td><td>{b.get('seconds') or '-'}</td>"
                     f"<td>{r['base_q1'] if r['base_q1'] is not None else '-'}</td><td>{r['tp_sec'] if r['tp_sec'] is not None else '-'}</td>"
                     f"<td>{r['tp_q1'] if r['tp_q1'] is not None else '-'}</td></tr>")
    parts.append("</table>")
    dst.write_text("\n".join(parts), encoding="utf-8")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["dry", "run", "score", "sheet"])
    ap.add_argument("--lane", default=None, help="run：只用这一条道（如 gpu36:0）")
    ap.add_argument("--host", default="gpu33", help="score：打分机器（CLIP / ArcFace 权重在 gpu33）")
    ap.add_argument("--shots", default=",".join(SHOTS))
    ap.add_argument("--seeds", type=int, default=2, help="每镜种子数")
    ap.add_argument("--exp", default=EXP)
    ap.add_argument("--strength", type=float, default=0.55)
    ap.add_argument("--end", type=float, default=0.7)
    a = ap.parse_args(argv)
    shots = [x.strip() for x in a.shots.split(",") if x.strip()]
    if a.cmd == "dry":
        dry(shots, a.strength, a.end, a.exp, a.seeds)
    elif a.cmd == "run":
        if not a.lane or ":" not in a.lane:
            raise SystemExit("run 要 --lane gpuNN:k（只一条道）")
        run(a.lane, shots, a.seeds, a.exp, a.strength, a.end)
    elif a.cmd == "score":
        score(a.exp, a.host)
    else:
        sheet(a.exp, shots)


if __name__ == "__main__":
    main()
