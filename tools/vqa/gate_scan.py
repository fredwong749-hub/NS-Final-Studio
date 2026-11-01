"""VQAGATE 回扫（项目方 11-01 16:10 / 16:3x：“image 做出来后用本地图像模型检测是否达标……不对就叫系统重做”）。

不另造检测器：对每个镜的**当前首帧**（可加 --last 当前尾帧）跑现有本地看图复核（ns_agent.vqa.contract.inspect_for =
client.inspect_image + 跨镜连贯参考：同场上一镜当前首帧），结果并进版本的 postflight（Q9，contract.apply），
写回走 tools/gen_contract/rescore_takes.write_back（带 rescored.was_ok，PRODUCER reconcile_demoted 认“门槛变化”、
清次数重出），再交 auto_current.on_contract 决定撤不撤当前（唯一入口；项目方定稿不被挤掉）。

    .venv/Scripts/python.exe tools/vqa/gate_scan.py scan  [--eps 1,2] [--last]     # 只看图，结果 data/vqa/gate_scan/latest.json
    .venv/Scripts/python.exe tools/vqa/gate_scan.py apply [--eps 1,2]              # 按 config/vqa.json 现行 blocking 写回 + 撤当前
    .venv/Scripts/python.exe tools/vqa/gate_scan.py redo                           # G0：等总调度复核的替换版自动复核
图片只进 gpu36 本地模型（K-REV-V01）。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in ("services/agent", "services/render_router", "packages/schema", "tools/gen_contract", "tools/autopilot", "packages/qc"):
    sys.path.insert(0, str(ROOT / p))

OUT = ROOT / "data" / "vqa" / "gate_scan"


def shots(eps: set | None) -> list[str]:
    s = json.loads((ROOT / "data/import/script_v2.json").read_text(encoding="utf-8"))
    return [f"ep{e['number']:02d}-S{x['index']}" for e in s["episodes"] if not eps or e["number"] in eps for x in e["shots"]]


def active(sid: str, stage: str) -> tuple[dict | None, dict]:
    from ns_render import pipeline as P
    d = P.load_takes(sid)
    n = (d.get("active") or {}).get(stage)
    return next((t for t in d.get("takes") or [] if t.get("stage") == stage and t.get("n") == n), None), d


def refs_of(sid: str, t: dict) -> list[str]:
    from ns_agent.vqa import contract as VQ
    rs = [r for r in (t.get("refs") or []) if isinstance(r, str)]
    if rs:
        return [str(ROOT / r) if not Path(r).is_absolute() else r for r in rs]
    try:
        import rescore_takes as RT
        return VQ.ref_files(RT.current_rec(sid) or {})
    except Exception:  # noqa: BLE001
        return []


def scan(eps, with_last=False, resume=False) -> dict:
    from ns_agent.vqa import contract as VQ
    rows = []
    OUT.mkdir(parents=True, exist_ok=True)
    done = {}
    if resume and (OUT / "latest.json").exists():     # 断点续扫：同一版本已看成（没出错）的不重看
        done = {(r["shot"], r["stage"], r.get("take")): r for r in json.loads((OUT / "latest.json").read_text(encoding="utf-8"))["rows"]
                if r.get("take") and not r.get("error")}
    for sid in shots(eps):
        for stage in (("image", "last") if with_last else ("image",)):
            t, _d = active(sid, stage)
            if t and (sid, stage, t.get("n")) in done:
                rows.append(done[(sid, stage, t["n"])])
                continue
            if not t or not t.get("file"):
                rows.append({"shot": sid, "stage": stage, "take": None, "status": "无当前版本"})
                continue
            img = ROOT / "data" / t["file"]
            t0 = time.time()
            v = VQ.inspect_for(sid, "first" if stage == "image" else "last", img, t.get("prompt") or "", refs_of(sid, t), wait_s=1500)
            rows.append({"shot": sid, "stage": stage, "take": t["n"], "file": t["file"], "pf_ok": (t.get("postflight") or {}).get("ok"),
                         "error": v.get("error"), "defects": v.get("defects") or [], "unsure": v.get("unsure") or [],
                         "checks": v.get("checks") or {}, "continuity_ref": v.get("continuity_ref"), "key": v.get("key"),
                         "people": v.get("people"), "secs": round(time.time() - t0, 1)})
            print(sid, stage, f"v{t['n']}", v.get("error") or "", "defects=", ",".join(v.get("defects") or []), flush=True)
            (OUT / "latest.json").write_text(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "rows": rows}, ensure_ascii=False,
                                                        indent=1), encoding="utf-8")
    return {"rows": rows}


def apply(eps) -> dict:
    """按现行 blocking 把扫描结果并进当前版本 postflight；翻转（过→不过）的写 rescored.was_ok 并撤当前"""
    from ns_agent.vqa import client as VC
    from ns_agent.vqa import contract as VQ
    from ns_render import auto_current as AC
    import rescore_takes as RT
    rows = json.loads((OUT / "latest.json").read_text(encoding="utf-8"))["rows"]
    out = []
    for r in rows:
        if not r.get("take") or (eps and int(r["shot"][2:4]) not in eps):
            continue
        if r.get("error"):                     # 看图没跑成（隧道断 / 服务忙）= 基础设施，不写回、不撤当前；--resume 重扫
            out.append({**r, "applied": "跳过：看图没跑成，待重扫"})
            continue
        t, _d = active(r["shot"], r["stage"])
        if not t or t.get("n") != r["take"]:
            out.append({**r, "applied": "跳过：当前版本已换"})
            continue
        v = VQ.cached_for(ROOT / "data" / t["file"]) or {"error": r.get("error") or "没有判定"}
        if not v.get("error"):                # gaze_mp 旁证按现行阈值重算（同一套 Q9 eye_contact）
            VQ.refresh_gaze(v, ROOT / "data" / t["file"], t.get("prompt") or "")
            VQ.remember(ROOT / "data" / t["file"], v)
        old = dict(t.get("postflight") or {})
        pf = VQ.apply({"ok": old.get("ok"), "items": list(old.get("items") or []), "blocking": list(old.get("blocking") or []),
                       "reasons": list(old.get("reasons") or []), "measured_on": old.get("measured_on")}, v)
        if pf.get("ok") == old.get("ok") and any(i.get("id") == "Q9" for i in old.get("items") or []) \
                and next(i for i in old["items"] if i["id"] == "Q9").get("status") == next(i for i in pf["items"] if i["id"] == "Q9")["status"]:
            out.append({**r, "applied": "不变", "now_ok": pf.get("ok")})
            continue
        RT.write_back(r["shot"], r["stage"], t["n"], pf, "VQAGATE gate_scan：本地看图闸门（Q9）并进契约", plan="data/vqa/gate_scan/latest.json")
        cur = None
        try:
            cur = AC.on_contract(r["shot"], r["stage"], t["n"])
        except Exception as e:  # noqa: BLE001
            cur = f"on_contract 出错：{e}"
        out.append({**r, "applied": "写回", "was_ok": old.get("ok"), "now_ok": pf.get("ok"), "q9": pf["vqa_gate"]["status"],
                    "current": cur})
        print(r["shot"], r["stage"], f"v{t['n']}", "ok", old.get("ok"), "→", pf.get("ok"), pf["vqa_gate"]["status"], cur, flush=True)
    (OUT / "applied.json").write_text(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "rows": out}, ensure_ascii=False, indent=1),
                                      encoding="utf-8")
    _ = VC
    return {"rows": out}


def preview() -> dict:
    """拦截预览（不写回、不撤当前）：按现行 blocking 算每镜会不会被拦、拦什么 → data/vqa/gate_scan/preview.json / preview.md，
    交总调度亲审；审完再 apply（总调度 18:0x，AUDIT 建议不全自动放量）"""
    from ns_agent.vqa import contract as VQ
    rows = json.loads((OUT / "latest.json").read_text(encoding="utf-8"))["rows"]
    zh = {k: x.get("zh", k) for k, x in VQ._all_checks().items()}
    out = []
    for r in rows:
        if not r.get("take"):
            continue
        if r.get("error"):
            out.append({"shot": r["shot"], "take": r["take"], "result": "未看成"})
            continue
        f = ROOT / "data" / r["file"]
        v = VQ.cached_for(f) or {"error": "没有判定"}
        if not v.get("error"):
            VQ.refresh_gaze(v, f, "")
        st, d, ev = VQ.q9(v)
        blk = [x for x in ev.get("defects") or [] if (VQ._all_checks().get(x) or {}).get("blocking")]
        out.append({"shot": r["shot"], "take": r["take"], "file": r["file"], "result": "拦" if st == "fail" else ("过" if st in ("pass", "na") else st),
                    "blocking": blk, "evidence": {x: ((v.get("checks") or {}).get(x) or {}).get("e") for x in blk},
                    "record_only": [x for x in ev.get("defects") or [] if x not in blk]})
    n_blk = sum(1 for x in out if x["result"] == "拦")
    md = [f"# 看图闸门拦截预览（{time.strftime('%Y-%m-%d %H:%M')}，不写回；总调度亲审后跑 gate_scan apply）", "",
          f"共 {len(out)} 镜：拦 {n_blk}、过 {sum(1 for x in out if x['result'] == '过')}、未看成 {sum(1 for x in out if x['result'] == '未看成')}"
          "（出处 data/vqa/gate_scan/latest.json、data/vqa/verdicts/）", "", "| 镜 | 版本 | 结果 | 拦截项（证据） | 只记录 |", "|---|---|---|---|---|"]
    for x in out:
        ev_ = "；".join(f"{zh.get(k, k)}：{(e or '')[:60]}" for k, e in (x.get("evidence") or {}).items())
        md.append(f"| {x['shot']} | v{x['take']} | {x['result']} | {ev_} | {'、'.join(x.get('record_only') or [])} |")
    (OUT / "preview.json").write_text(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "rows": out}, ensure_ascii=False, indent=1),
                                      encoding="utf-8")
    (OUT / "preview.md").write_text(chr(10).join(md) + chr(10), encoding="utf-8")
    print("预览：拦", n_blk, "/", len(out), "→ data/vqa/gate_scan/preview.md")
    return {"rows": out}


def report() -> dict:
    """标定用：每项 defect / unsure 占比（全部扫描行），写 data/vqa/gate_scan/rates.json"""
    from collections import Counter
    from ns_agent.vqa import contract as VQ
    rows = [r for r in json.loads((OUT / "latest.json").read_text(encoding="utf-8"))["rows"] if r.get("take") and not r.get("error")]
    d, u = Counter(), Counter()
    for r in rows:
        v = VQ.cached_for(ROOT / "data" / r["file"]) or r
        d.update(v.get("defects") or [])
        u.update(v.get("unsure") or [])
    out = {"n": len(rows), "defect": {k: [n, round(n / max(1, len(rows)), 3)] for k, n in d.most_common()},
           "unsure": dict(u.most_common())}
    (OUT / "rates.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False))
    return out


def calib_gaze(limit: int | None = None) -> dict:
    """eye_contact 标定（看图模型 + gaze_mp 合并口径）：总调度标的 data/acting/gaze_labels.json（img:<首帧 jpg>#脸号 → 看镜头 / 没看镜头），
    按图汇总（任一张脸看镜头 = 正例），图 = video/inputs/<jpg>，提示词 = 剧本 img_prompt。→ data/vqa/gate_calib/gaze_vlm.json"""
    from ns_agent.vqa import client as VC
    from ns_agent.vqa import contract as VQ
    from ns_agent.vqa import continuity as CTY
    lab = json.loads((ROOT / "data/acting/gaze_labels.json").read_text(encoding="utf-8"))
    img = {}
    for k, v in lab.items():
        if not k.startswith("img:"):
            continue
        f = k[4:].split("#")[0]
        img[f] = img.get(f, False) or v == "看镜头"
    rows = []
    for i, (f, pos) in enumerate(sorted(img.items())):
        if limit and i >= limit:
            break
        p = ROOT / "data/pipeline/runs/series10_v1/video/inputs" / f
        if not p.exists():
            continue
        sid = f.split("_")[0]
        prompt = ((CTY.shot_rec(sid) or {}).get("img_prompt") or "")
        v = VC.inspect_image(str(p), prompt, [], wait_s=1500)
        if v.get("error"):
            rows.append({"img": f, "label": pos, "error": v["error"]})
            continue
        vlm_hit = "eye_contact" in (v.get("defects") or [])
        VQ.sanitize(v)
        san_hit = "eye_contact" in (v.get("defects") or [])
        VQ.merge_gaze(v, VQ.gaze_mp(p), prompt)
        rows.append({"img": f, "label": pos, "vlm": vlm_hit, "vlm_sanitized": san_hit, "merged": "eye_contact" in v["defects"],
                     "gaze_hits": (v.get("gaze_mp") or {}).get("hits")})
        print(rows[-1], flush=True)

    def score(key):
        ok = [r for r in rows if key in r]
        P_ = [r for r in ok if r["label"]]
        N_ = [r for r in ok if not r["label"]]
        return {"recall": f"{sum(r[key] for r in P_)}/{len(P_)}", "false_pos": f"{sum(r[key] for r in N_)}/{len(N_)}"}
    out = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "n": len(rows), "errors": sum(1 for r in rows if r.get("error")),
           "vlm": score("vlm"), "vlm_sanitized": score("vlm_sanitized"), "merged": score("merged"), "rows": rows}
    d = ROOT / "data/vqa/gate_calib"
    d.mkdir(parents=True, exist_ok=True)
    (d / "gaze_vlm.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print({k: out[k] for k in ("n", "errors", "vlm", "vlm_sanitized", "merged")})
    return out


def redo() -> list:
    """G0：账本里等总调度复核的替换版（redo_candidate）→ 本地看图闸门：过 = master_approve（by gate.auto_review_by）；
    不过 = 原因写进驳回记录 auto_reviews、清掉 redo_candidate（驳回计划接着重出）"""
    import producer as PR
    from ns_agent.vqa import contract as VQ
    from ns_render import pipeline as P
    paths = PR.Paths()
    L = PR.jl(paths.ledger, {}) or {}
    res = []
    for oid, r in L.items():
        n = (r or {}).get("redo_candidate") if isinstance(r, dict) else None
        if not n:
            continue
        kind, sid = oid.split(":", 1)
        stage = "image" if kind == "first" else "last"
        t = next((x for x in P.load_takes(sid).get("takes") or [] if x.get("stage") == stage and x.get("n") == n), None)
        if not t:
            continue
        v = VQ.inspect_for(sid, kind, ROOT / "data" / t["file"], t.get("prompt") or "", refs_of(sid, t), wait_s=1500)
        old = dict(t.get("postflight") or {})
        pf = VQ.apply({"ok": old.get("ok"), "items": list(old.get("items") or []), "blocking": list(old.get("blocking") or []),
                       "reasons": list(old.get("reasons") or [])}, v)
        if pf.get("ok") and PR.auto_review_redo(paths, oid, n, pf):
            res.append({"obj": oid, "take": n, "result": "自动换上", "unsure": v.get("unsure")})
        else:
            PR.note_auto_reject(paths, oid, n, pf)
            L2 = PR.jl(paths.ledger, {}) or {}
            L2.setdefault(oid, {})["redo_candidate"] = None
            PR.js(paths.ledger, L2)
            PR.log_event(paths, "redo_auto_rejected", obj=oid, take=n, why=PR.pf_reason(pf)[:200], by="VQAGATE", counted=False)
            res.append({"obj": oid, "take": n, "result": "自动驳回", "why": PR.pf_reason(pf)[:200]})
        print(res[-1], flush=True)
    return res


def main(argv):
    sys.stdout.reconfigure(encoding="utf-8")
    eps = None
    if "--eps" in argv:
        eps = {int(x) for x in argv[argv.index("--eps") + 1].split(",")}
    if argv and argv[0] == "scan":
        scan(eps, "--last" in argv, "--resume" in argv)
    elif argv and argv[0] == "apply":
        apply(eps)
    elif argv and argv[0] == "calib_gaze":
        calib_gaze(int(argv[argv.index("--limit") + 1]) if "--limit" in argv else None)
    elif argv and argv[0] == "preview":
        preview()
    elif argv and argv[0] == "report":
        report()
    elif argv and argv[0] == "redo":
        redo()
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
