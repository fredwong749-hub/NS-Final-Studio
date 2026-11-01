"""
V2（方案 A，2026-10-31 项目方“加快暴力实验”）：同一镜并行多 seed / 变体，填满本方案的道（每道排队 ≤2）。

和 iterate_loop 同一套编译（ns_recipes.compile_shot）、同一个提交器（ApiSubmitter，graph passthrough）、同一个审片
（review.py clips → reviewer.flatten）和同一个后处理（postproc：去抖 / 肤色限幅按配方 post）。不改 loop 状态，
产物记在 data/ab/v2_iter/fanout/manifest.json，每条带 plan_hash / seed / 配方 / 指标 / GPU 秒，给 planA 报告挑最好的一版。
不定稿，不写 review.json。

用法：
  python tools/ep02_iter/fanout.py add ep02-S2 --offsets 10,11 [--recipe two_person_ref2va] [--tag new]
  python tools/ep02_iter/fanout.py run --lanes 0,1,3 [--per-lane 2] [--poll 45]
  python tools/ep02_iter/fanout.py status
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT / "tools" / "iterate_loop", ROOT / "services" / "recipes", ROOT / "services" / "render_router"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import postproc  # noqa: E402
import reviewer as RV  # noqa: E402
import submitter as SB  # noqa: E402

DIR = ROOT / "data" / "ab" / "v2_iter" / "fanout"
MAN = DIR / "manifest.json"


def load() -> dict:
    return json.loads(MAN.read_text(encoding="utf-8")) if MAN.exists() else {"entries": []}


def save(m: dict) -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    tmp = MAN.with_suffix(".tmp")
    tmp.write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(MAN)


def compile_plan(sid: str, offset: int, recipe: str | None) -> dict:
    from ns_recipes import compiler as C, registry as R, selector as SEL, spec_import as SI
    from ns_render import pipeline as P
    ep = int(sid.split("-S")[0][2:])
    reg = R.load()
    spec = {s.id: s for s in SI.specs_from_import(P.load_script(), ep)}[sid]
    sel = SEL.select(spec, reg)
    plan = C.compile_shot(spec, reg, attempt=1, recipe_id=recipe or sel.recipe_id,
                          overrides={"seed.offset": offset}, selection=sel)
    (DIR / "plans").mkdir(parents=True, exist_ok=True)
    (DIR / "plans" / f"{plan['plan_hash'][:16]}.json").write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
    return plan


def cmd_add(a) -> None:
    m = load()
    for off in [int(x) for x in a.offsets.split(",") if x.strip()]:
        plan = compile_plan(a.shot, off, a.recipe)
        if plan["status"] != "ready":
            print(a.shot, off, "编译不过", plan["status"], plan.get("reason"))
            continue
        if any(e["plan_hash"] == plan["plan_hash"] for e in m["entries"]):
            print(a.shot, off, "已在清单")
            continue
        m["entries"].append({"shot": a.shot, "offset": off, "recipe": plan["recipe"]["id"], "seed": plan["seed"],
                             "plan_hash": plan["plan_hash"], "tag": a.tag, "state": "todo",
                             "long": plan["lane"]["long"], "only": plan["lane"].get("only")})
        print(a.shot, off, plan["recipe"]["id"], plan["seed"], plan["plan_hash"][:10])
    save(m)


def _plan(e: dict) -> dict:
    return json.loads((DIR / "plans" / f"{e['plan_hash'][:16]}.json").read_text(encoding="utf-8"))


def _recover_submit(sub, e: dict) -> dict | None:
    try:
        code, jobs = sub._req("GET", "/api/jobs")
    except SB.SubmitError:
        return None
    for j in jobs if isinstance(jobs, list) else []:
        if j.get("shot_id") == e["shot"] and (j.get("params") or {}).get("seed") == e["seed"]                 and j.get("state") in ("queued", "running", "done"):
            return {"state": "queued", "job_id": j["id"], "lane": j.get("gpu")}
    return None


def tick(m: dict, sub: SB.ApiSubmitter, la: SB.LaneAllocator, rev, post) -> bool:
    moved = False
    for e in m["entries"]:
        if e["state"] in ("queued", "running"):
            try:
                res = sub.poll(e["job"], _plan(e))
            except SB.SubmitError:
                continue
            if res["state"] == "done":
                e.update(state="rendered", take=res.get("take"), file=res.get("file"), local_path=res.get("local_path"),
                         job_info=res.get("job"))
                moved = True
            elif res["state"] in ("failed", "cancelled", "lost"):
                e.update(state=res["state"], error=str(res.get("error"))[:300])
                moved = True
            else:
                e["state"] = res["state"] if res["state"] in ("queued", "running") else e["state"]
    try:
        ext = sub.lane_load() or {}
    except Exception:  # noqa: BLE001
        return moved
    busy: dict = {}
    for e in m["entries"]:
        if e["state"] == "todo":
            lane = la.pick(bool(e.get("long")), busy, ext, e.get("only"))
            if lane is None:
                continue
            try:
                r = sub.submit(_plan(e), lane)
            except SB.SubmitError as ex:   # API 慢（上传参考图）超时：服务端可能已收下 → 按 seed 找回，找不到下次再交
                r = _recover_submit(sub, e) or {"state": "retry", "detail": str(ex)}
            if r["state"] == "retry":
                continue
            if r["state"] == "queued":
                e.update(state="queued", job=r["job_id"], lane=lane, submitted=time.strftime("%H:%M:%S"))
                ext[str(lane)] = ext.get(str(lane), 0) + 1
                busy[str(lane)] = busy.get(str(lane), 0) + 1
            else:
                e.update(state="error", error=json.dumps(r, ensure_ascii=False)[:300])
            moved = True
            save(m)
    for e in m["entries"]:
        if e["state"] == "rendered":
            plan = _plan(e)
            src = Path(e.get("local_path") or (ROOT / "data" / (e.get("file") or "")))
            try:
                out, steps = post.apply(e["shot"], f"fo{e['offset']}_{e['plan_hash'][:8]}", src, plan["post"])
                name = f"fanout_{e['shot']}_o{e['offset']}_{e['plan_hash'][:6]}"
                met = rev.clips(name, {e["shot"]: str(out)})[e["shot"]]
                e.update(state="reviewed", post_file=str(out), post_steps=steps, sheet=met.pop("_sheet", None),
                         flags=met.pop("_flags", []), metrics=met,
                         failures=RV.failures(met, plan["acceptance"]))
            except Exception as ex:  # noqa: BLE001
                e.update(state="review_error", error=str(ex)[:300])
            moved = True
            save(m)
    return moved


def cmd_run(a) -> None:
    lanes = [int(x) if x.strip().isdigit() else x.strip() for x in a.lanes.split(",") if x.strip()]
    la = SB.LaneAllocator(normal=lanes, long=[], per_lane=a.per_lane, lane_cap=a.per_lane)
    sub = SB.ApiSubmitter(graph_passthrough=True, timeout=180)
    rev, post = RV.ReviewPy(), postproc.PostRunner(DIR / "post")
    while True:
        m = load()
        tick(m, sub, la, rev, post)
        save(m)
        if all(e["state"] in ("reviewed", "failed", "cancelled", "lost", "error", "review_error") for e in m["entries"]):
            print("ALL_DONE", flush=True)
            break
        time.sleep(a.poll)


def cmd_status(_a) -> None:
    for e in load()["entries"]:
        mt = e.get("metrics") or {}
        print(e["shot"], e["offset"], e["recipe"], e["state"], e.get("lane"), e.get("take"),
              {k: mt.get(k) for k in ("still_frac", "cheek_red_max", "cheek_a_drift", "sface_ref_min", "J4")},
              [f["metric"] for f in e.get("failures") or []])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("add")
    p.add_argument("shot")
    p.add_argument("--offsets", default="10,11")
    p.add_argument("--recipe")
    p.add_argument("--tag", default="new")
    p = sp.add_parser("run")
    p.add_argument("--lanes", default="0,1,3")
    p.add_argument("--per-lane", type=int, default=2)
    p.add_argument("--poll", type=float, default=45)
    sp.add_parser("status")
    a = ap.parse_args(argv)
    {"add": cmd_add, "run": cmd_run, "status": cmd_status}[a.cmd](a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
