"""阈值改口径后的重打分（总调度 11-01：Q4 改只记录、Q5“肢体比例可疑”停用、Q8 只记录、鞋分三段）。
只重打分、不重出、不计入内容尝试：扫 data/renders/**/takes.json，挑出 postflight 不过、且 blocking 全在 {Q4, Q5, Q8}（可加 Q2）里的
首帧 / 尾帧版本，用 gpu33 一次 ssh 重算（remote_score.postflight_full），写回版本顶层 postflight 与 contract.postflight，
再交 auto_current.on_contract 决定是否设为当前（唯一入口，项目方定稿不被挤掉）。

    .venv/Scripts/python.exe tools/gen_contract/rescore_takes.py [--codes Q4,Q5,Q8 | --active-passed | --keys …]   # 只打分，出计划
    .venv/Scripts/python.exe tools/gen_contract/rescore_takes.py --apply data/qa/rescore_plans/<计划>.json      # 审过翻转清单再写
"""
import argparse
import glob
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in ("services/agent", "services/render_router", "packages/schema", "tools/gen_contract"):
    sys.path.insert(0, str(ROOT / p))


def candidates(codes: set) -> list[tuple[str, dict]]:
    from ns_render import pipeline as P
    out = []
    for f in glob.glob(str(P.RENDERS / "ep*" / "S*" / "takes.json")):
        sid = "-".join(Path(f).parent.parts[-2:])
        try:
            d = json.loads(Path(f).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for t in d.get("takes") or []:
            if t.get("stage") not in ("image", "last"):
                continue
            pf = t.get("postflight") or (t.get("contract") or {}).get("postflight") or {}
            blk = set(pf.get("blocking") or [])
            if pf.get("ok") is False and blk and blk <= codes and (P.DATA / t["file"]).exists():
                out.append((sid, t))
    return out


_SCRIPT = {}


def current_rec(sid: str, project: str | None = None) -> dict | None:
    if project is None:                          # I-16：不写剧名，按本进程的剧（NS_RUN → primary）
        import sys as _s
        if str(ROOT) not in _s.path:
            _s.path.insert(0, str(ROOT))
        from tools.autopilot import runs as _RN
        project = _RN.current_run()
    from ns_agent import asset_refs as AR
    from ns_render import pipeline as P
    if "s" not in _SCRIPT:
        try:
            _SCRIPT["s"] = json.loads((P.DATA / "import" / "script_v2.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
    n, idx = int(sid[2:4]), int(sid.split("-S")[1])
    ep = next((e for e in _SCRIPT["s"]["episodes"] if e["number"] == n), None)
    sh = next((x for x in (ep or {}).get("shots", []) if x["index"] == idx), None)
    if sh is None:
        return None
    sr, plan = AR.plan_for(project, ep, sh)
    return {**AR.record(sr, plan), "rec_from": "current plan_for（版本没记参考规划）"}


def active_passed() -> list[tuple[str, dict]]:
    """总调度 11-01 P1：Q1 改成“每张脸都要认得出”后，当前（active）且已通过的首帧 / 尾帧全部重打分"""
    from ns_render import pipeline as P
    out = []
    for f in glob.glob(str(P.RENDERS / "ep*" / "S*" / "takes.json")):
        sid = "-".join(Path(f).parent.parts[-2:])
        try:
            d = json.loads(Path(f).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        act = d.get("active") or {}
        for t in d.get("takes") or []:
            if t.get("stage") in ("image", "last") and act.get(t["stage"]) == t.get("n")                     and (t.get("postflight") or {}).get("ok") is True and (P.DATA / t["file"]).exists():
                out.append((sid, t))
    return out


PLAN_DIR_REL = Path("qa") / "rescore_plans"


def _key(sid, t) -> str:
    return f"{sid}|{t['stage']}|{t['n']}"


def _take_sig(t: dict) -> str:
    """版本当前的 postflight 指纹：计划生成后版本被别人改过（又打过分 / 换了文件）→ 拒绝写回"""
    import hashlib
    pf = t.get("postflight") or {}
    return hashlib.sha256(json.dumps([t.get("file"), pf.get("ok"), pf.get("ts")], ensure_ascii=False).encode()).hexdigest()[:16]


def history_entry(old: dict, pf: dict, why: str, plan: str | None) -> dict:
    return {"by": "tools/gen_contract/rescore_takes.py", "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "why": why,
            "was_ok": old.get("ok"), "was_blocking": old.get("blocking"), "now_ok": pf.get("ok"),
            "now_blocking": pf.get("blocking"), "plan": plan}


def write_back(sid: str, stage: str, n: int, pf: dict, why: str, plan: str | None = None, P=None) -> dict:
    """写回一个版本：新 postflight + 追加 rescore_history（DATAALIGN 11-01：以前每次覆盖 rescored，04:49 之前“曾通过”的记录丢了）"""
    if P is None:
        from ns_render import pipeline as P
    out: dict = {}

    def fn(d):                                   # A-04：takes.json 只经 mutate_takes 写
        t = next(x for x in d["takes"] if x["stage"] == stage and x["n"] == n)
        old = t.get("postflight") or {}
        hist = list(old.get("rescore_history") or [])
        if not hist and old.get("rescored"):                   # 旧格式的单条记录并进历史，不丢
            hist.append(old["rescored"])
        ent = history_entry(old, pf, why, plan)
        hist.append(ent)
        t["postflight"] = {"ok": pf["ok"], "items": pf["items"], "blocking": pf.get("blocking"), "reasons": pf.get("reasons", []),
                           "ts": P.now(), "measured_on": pf.get("measured_on"), "rescored": ent, "rescore_history": hist}
        c = dict(t.get("contract") or {})
        c["postflight"] = {**pf, "status": "done"}
        t["contract"] = c
        out["ent"] = ent
        return d
    P.mutate_takes(sid, fn, op="rescore", by="tools/gen_contract/rescore_takes.py")
    return out["ent"]


def flips(plan: dict) -> list[dict]:
    return [r for r in plan["rows"] if r["was_ok"] != r["pf"]["ok"]]


def main(argv=None):
    """两步走（DATAALIGN 11-01：04:49 第一遍把同一角色的镜像脸当成“多了一个人”，直接写回挤掉了 4 个当前版本）：
      1) 不带 --apply：只打分，结果存成计划 data/qa/rescore_plans/<时间>.json，打印翻转清单，什么都不写；
      2) 看过翻转清单后 --apply <计划文件>：按计划写回（版本在此期间被改过的跳过），追加 rescore_history，再交 auto_current。"""
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="只列候选，不打分")
    ap.add_argument("--dry", action="store_true", help="兼容旧用法：等同 --list")
    ap.add_argument("--codes", default="Q4,Q5,Q8")
    ap.add_argument("--active-passed", action="store_true", help="重打当前已通过的版本（Q1 全脸识别上线后）")
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--keys", default="", help="只重打这些版本：ep02-S7|image|2,ep02-S7|last|1")
    ap.add_argument("--why", default="", help="写进 rescore_history 的原因")
    ap.add_argument("--apply", default="", help="按已审过的计划文件写回")
    a = ap.parse_args(argv)
    from ns_render import pipeline as P
    if a.apply:
        return apply_plan(Path(a.apply), P)
    import remote_score as RS
    from ns_render import unified_frame as UF
    if a.keys:
        want = {tuple(k.split("|")) for k in a.keys.split(",") if k}
        cands = []
        for sid, stage, n in sorted(want):
            d = json.loads((P.shot_dir(sid) / "takes.json").read_text(encoding="utf-8"))
            cands += [(sid, t) for t in d["takes"] if t["stage"] == stage and t["n"] == int(n)]
    else:
        cands = active_passed() if a.active_passed else candidates(set(a.codes.split(",")))
    print("候选", len(cands), [(s, t["stage"], t["n"]) for s, t in cands])
    if a.list or a.dry or not cands:
        return None
    jobs, before = [], {}
    for sid, t in cands:
        ctx = UF._ctx_for(sid, t)
        rec = (t.get("contract") or {}).get("asset_refs") or {}
        if not rec.get("characters"):                 # 老版本没记参考规划：按现行剧本 + 资产规划补（与出图同一个 plan_for）
            rec = current_rec(sid) or rec
        jobs.append({"id": _key(sid, t), "file": str(P.DATA / t["file"]), "post": None,
                     "request": {"cast": ctx.get("cast"), "asset_refs": rec}})
        before[_key(sid, t)] = {"was_ok": (t.get("postflight") or {}).get("ok"), "sig": _take_sig(t)}
    res, failed = {}, []
    part = P.DATA / PLAN_DIR_REL / f"partial_{time.strftime('%Y%m%d_%H%M%S')}.json"
    for i in range(0, len(jobs), a.batch):                     # 分批：每批一次 ssh（上传慢，单批别超 900 s）
        chunk = jobs[i:i + a.batch]
        for attempt in range(3):                               # 跳板 ssh 偶发 Connection reset：重试 3 次，仍失败就记下跳过，不丢前面的结果
            try:
                res.update(RS.postflight_full("gpu33", chunk, label=f"重打分 {i // a.batch + 1}"))
                break
            except Exception as e:  # noqa: BLE001
                print(f"批 {i // a.batch + 1} 第 {attempt + 1} 次失败：{str(e)[:120]}", flush=True)
                time.sleep(20 * (attempt + 1))
        else:
            failed += [j["id"] for j in chunk]
        part.parent.mkdir(parents=True, exist_ok=True)
        part.write_text(json.dumps({"done": list(res), "failed": failed}, ensure_ascii=False), encoding="utf-8")
    if failed:
        print("打分失败（未进计划）：", ",".join(failed), flush=True)
    why = (a.why or ("Q1 全脸识别（总调度 11-01 P1）" if a.active_passed else "门槛改口径（总调度 11-01）")) + "，只重打分不重出、不计尝试"
    plan = {"made_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "why": why,
            "rows": [{"key": k, **before[k], "pf": pf} for k, pf in res.items()]}
    d = P.DATA / PLAN_DIR_REL
    d.mkdir(parents=True, exist_ok=True)
    out = d / f"rescore_{time.strftime('%Y%m%d_%H%M%S')}.json"
    out.write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
    fl = flips(plan)
    print(f"计划 {out}（{len(plan['rows'])} 个版本，翻转 {len(fl)} 个；未写回，看过后 --apply {out}）")
    for r in fl:
        q1 = next((i for i in r["pf"]["items"] if i["id"] == "Q1"), {})
        print("  翻转", r["key"], r["was_ok"], "→", r["pf"]["ok"], r["pf"].get("blocking"), "Q1:", q1.get("detail"))
    return out


def apply_plan(path: Path, P) -> list[str]:
    from ns_render import auto_current as AC
    plan = json.loads(Path(path).read_text(encoding="utf-8"))
    done = []
    for r in plan["rows"]:
        sid, stage, n = r["key"].split("|")
        n = int(n)
        d = json.loads((P.shot_dir(sid) / "takes.json").read_text(encoding="utf-8"))
        t = next((x for x in d["takes"] if x["stage"] == stage and x["n"] == n), None)
        if t is None or _take_sig(t) != r["sig"]:
            print("跳过（计划之后版本被改过）", r["key"], flush=True)
            continue
        write_back(sid, stage, n, r["pf"], plan["why"], str(path), P)
        AC.on_contract(sid, stage, n)
        done.append(r["key"])
        print(r["key"], "写回 ok", r["pf"]["ok"], "（原", r["was_ok"], "）", flush=True)
    return done


if __name__ == "__main__":
    main()
