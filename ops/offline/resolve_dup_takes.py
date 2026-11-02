"""两台重复出图的逐镜合并判定（WORKFLOW 11-02，总调度 12:4x 定规则；DEBUG-RSI 派；规则 K-OPS-W27）。

起因：08:09 ep08/09 从 gpu36 搬到 gpu33（两台 takes 不同步），gpu33 把第一季 ep08/09 重做了一遍（90 张，
清单 gpu33:data/_quarantine/dup_s1_ep0809_gpu33.json，rows = {obj, take, ts}）。两台的 take 编号各自从自己的 takes.json 往上数，
同一个 n 在两台是不同的图（例：ep08-S3 image #5 在 gpu33 是 aa798660、在 gpu36 是 967c7411），不能按编号直接并。

逐镜、逐阶段（first→image / last→last）判定，不一刀切、不删任何文件：
  ① 有项目方定稿锁（takes.json locked 里该阶段有值）→ 以锁定版本为准；
  ② 其余按现行契约（postflight.ok is True 且未隔离）：只有一台的版本过 → 用那一台；
  ③ 两台都过 → 以 gpu36 为准（原分区机、已在用），gpu33 那份进隔离区；
  ④ 两台都没过 → 都保留，走正常重出。
候选版本：gpu36 = 它 takes.json 里该阶段的 active；gpu33 = 它该阶段的 active（且在重复清单里），否则清单里该阶段最后一条。

本模块只做判定（纯函数 decide / plan），执行（写 takes.json、搬文件）另走 apply，先出判定表给 DEBUG-RSI / 总调度。
用法： python ops/offline/resolve_dup_takes.py plan <snapshot.json> [--out decisions.json]
  snapshot = {"dup": {rows}, "gpu33": {shot: takes}, "gpu36": {shot: takes}, "laptop": {shot: takes}}
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

STAGE_OF = {"first": "image", "last": "last"}
PRIMARY = "gpu36"        # ③ 两台都过时以它为准
OTHER = "gpu33"


def _take(doc: dict, stage: str, n) -> dict | None:
    if n is None:
        return None
    return next((t for t in (doc or {}).get("takes") or [] if t.get("stage") == stage and t.get("n") == n), None)


def passes(t: dict | None) -> bool:
    return bool(t) and (t.get("postflight") or {}).get("ok") is True and not t.get("quarantined")


def locked_n(doc: dict, stage: str):
    lk = (doc or {}).get("locked")
    if isinstance(lk, dict):
        v = lk.get(stage)
        return v.get("n") if isinstance(v, dict) else v
    return None


def decide(stage: str, d36: dict, d33: dict, dup_ns: list[int], laptop: dict | None = None) -> dict:
    """一个镜的一个阶段 → {rule, use, n36, n33, ok36, ok33, quarantine_33: [n...]}"""
    n36 = ((d36 or {}).get("active") or {}).get(stage)
    a33 = ((d33 or {}).get("active") or {}).get(stage)
    n33 = a33 if a33 in dup_ns else (dup_ns[-1] if dup_ns else None)
    t36, t33 = _take(d36, stage, n36), _take(d33, stage, n33)
    ok36, ok33 = passes(t36), passes(t33)
    base = {"stage": stage, "n36": n36, "n33": n33, "ok36": ok36, "ok33": ok33,
            "file36": (t36 or {}).get("file"), "file33": (t33 or {}).get("file")}
    for host, doc in (("gpu36", d36), ("laptop", laptop), ("gpu33", d33)):
        ln = locked_n(doc, stage)
        if ln is not None:
            use = "gpu33" if host == "gpu33" else "gpu36"
            return {**base, "rule": "①", "use": use, "locked_by": host, "locked_n": ln,
                    "quarantine_33": [] if use == "gpu33" else list(dup_ns)}
    if ok36 and not ok33:
        return {**base, "rule": "②", "use": "gpu36", "quarantine_33": list(dup_ns)}
    if ok33 and not ok36:
        return {**base, "rule": "②", "use": "gpu33", "quarantine_33": []}     # 用 gpu33 的：它其余没过的尝试是正常历史，不额外隔离
    if ok33 and ok36:
        return {**base, "rule": "③", "use": "gpu36", "quarantine_33": list(dup_ns)}
    return {**base, "rule": "④", "use": "both", "quarantine_33": []}


def plan(snapshot: dict) -> list[dict]:
    by = {}
    for r in snapshot["dup"]["rows"]:
        kind, sid = r["obj"].split(":", 1)
        by.setdefault((sid, STAGE_OF[kind]), []).append(int(r["take"]))
    out = []
    for (sid, stage), ns in sorted(by.items()):
        dec = decide(stage, snapshot["gpu36"].get(sid) or {}, snapshot["gpu33"].get(sid) or {}, sorted(set(ns)),
                     (snapshot.get("laptop") or {}).get(sid))
        out.append({"shot": sid, **dec, "dup_takes_33": sorted(set(ns))})
    return out


def merged_doc(d33: dict, d36: dict, decs: list[dict], by: str, at: str) -> tuple[dict, dict]:
    """以 gpu33（现分区机、producer 在跑、它的编号不动）为底，并入 gpu36 的版本（同文件认同一版本，同号不同图换新号），
    再按判定设 active、给 gpu33 的落选重复版本打隔离标记（不删文件）。返回 (合并后, {stage: {gpu36 原号: 新号}})"""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import merge_pull as MP
    d36_noactive = {**(d36 or {}), "active": {}, "locked": (d36 or {}).get("locked") or {}}
    out, _a, _u, remap = MP.merge_takes_docs(d36_noactive, d33 or {"takes": []})
    act = dict(out.get("active") or {})
    for dec in decs:
        st = dec["stage"]
        if dec["use"] == "gpu36" and dec["n36"] is not None:
            act[st] = remap.get((st, dec["n36"]), dec["n36"])
        elif dec["use"] == "gpu33" and dec["n33"] is not None:
            act[st] = dec["n33"]
        q = set(dec.get("quarantine_33") or [])
        for t in out["takes"]:
            if t.get("stage") == st and t.get("n") in q and not (t.get("origin") or {}).get("merged_from") and not t.get("renumbered") \
                    and not t.get("quarantined"):
                t["quarantined"] = {"at": at, "by": by, "reason": f"两台重复出图合并 规则{dec['rule']}：采用 gpu36 #{dec['n36']}（gpu33 这份进隔离区，文件保留）"}
    out["active"] = act
    out.setdefault("restore_log", []).append({"at": at, "by": by, "what": "K-OPS-W27 两台重复出图逐镜合并",
                                              "decisions": [{k: d[k] for k in ("stage", "rule", "use", "n36", "n33")} for d in decs]})
    return out, {st: n for (st, _o), n in remap.items()}


def fold_local_quarantine(doc: dict, laptop: dict) -> dict:
    """笔记本上的隔离标记（UIRSI 等处置，LOCAL_STICKY）按 (stage, 文件) 带进合并结果；active 指向被隔离的版本就撤掉该阶段指针"""
    marks = {(t.get("stage"), t.get("file")): t["quarantined"] for t in (laptop or {}).get("takes") or [] if t.get("quarantined") and t.get("file")}
    for t in doc.get("takes") or []:
        q = marks.get((t.get("stage"), t.get("file")))
        if q and not t.get("quarantined"):
            t["quarantined"] = q
    qn = {(t.get("stage"), t.get("n")) for t in doc.get("takes") or [] if t.get("quarantined")}
    doc["active"] = {st: n for st, n in (doc.get("active") or {}).items() if (st, n) not in qn}
    return doc


def files_needed(doc: dict, stages=("image", "last")) -> set[str]:
    """只补当前版本（active）的图：gpu33 → 笔记本下行实测约 56 KB/s（13:1x，6.9 MB 用 123 s），整批历史版本拉不动；
    其余版本的文件留在各自机器上（不删），以后按需拉"""
    act = doc.get("active") or {}
    return {"data/" + t["file"].lstrip("/") for t in doc.get("takes") or []
            if t.get("stage") in stages and t.get("file") and act.get(t.get("stage")) == t.get("n")}


def apply(snapshot_fn, decisions: list[dict], by: str = "WORKFLOW dup-merge", dry: bool = False) -> dict:
    """执行：逐镜按判定合并 → 写 gpu33 / gpu36 / 笔记本三份 takes.json，补齐各处缺的图（经笔记本中转，不删任何文件）。
    snapshot_fn() 现取两台最新 takes（执行前重取，判定也按最新的重算）"""
    import shlex
    import time
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools/autopilot"))
    import resident_sync as RS
    ROOT = RS.ROOT
    at = time.strftime("%Y-%m-%dT%H:%M:%S")
    snap = snapshot_fn()
    decs_now = plan(snap)
    by_shot: dict = {}
    for d in decs_now:
        by_shot.setdefault(d["shot"], []).append(d)
    report, docs = [], {}
    for sid, decs in sorted(by_shot.items()):
        doc, _rm = merged_doc(snap["gpu33"].get(sid) or {}, snap["gpu36"].get(sid) or {}, decs, by, at)
        ep_, s_ = sid.split("-")
        lp = ROOT / f"data/renders/{ep_}/{s_}/takes.json"
        doc = fold_local_quarantine(doc, json.loads(lp.read_text(encoding="utf-8")) if lp.exists() else {})
        docs[sid] = doc
        for d in decs:
            report.append({"shot": sid, "stage": d["stage"], "rule": d["rule"], "use": d["use"],
                           "active_now": doc["active"].get(d["stage"])})
    if dry:
        return {"dry": True, "report": report}
    # 文件：gpu36 → 笔记本 → gpu33；gpu33 → 笔记本 → gpu36（只补缺的）
    lst_code = "import os,sys,json;print(json.dumps([p for p in sys.stdin.read().splitlines() if p and os.path.isfile(p)]))"
    need = sorted(set().union(*[files_needed(d) for d in docs.values()]))
    have = {}
    for h in ("gpu33", "gpu36"):
        raw = RS.ssh(h, f"cd {RS.R} && python3 -c {shlex.quote(lst_code)}", data="\n".join(need).encode(), timeout=300, tries=2).decode()
        have[h] = set(json.loads([x for x in raw.splitlines() if x.startswith("[")][-1]))
    moved = {"to_laptop": 0, "to_gpu33": 0, "to_gpu36": 0}
    import io, tarfile
    for src in ("gpu36", "gpu33"):
        get = [p for p in need if p in have[src] and (not (ROOT / p).is_file())]
        for i in range(0, len(get), 2):            # 小批（12:55 / 13:16 大包 tar 断连 rc=255，gpu33 下行约 56 KB/s）；已落地的下次跳过
            blob = RS.ssh(src, f"cd {RS.R} && tar cf - -T -", data="\n".join(get[i:i + 2]).encode(), timeout=600, tries=4)
            with tarfile.open(fileobj=io.BytesIO(blob)) as tf:
                for m in tf.getmembers():
                    if m.isfile() and ".." not in m.name and not (ROOT / m.name).exists():
                        (ROOT / m.name).parent.mkdir(parents=True, exist_ok=True)
                        (ROOT / m.name).write_bytes(tf.extractfile(m).read())
                        moved["to_laptop"] += 1
    for dst in ("gpu33", "gpu36"):
        put = [p for p in need if p not in have[dst] and (ROOT / p).is_file()]
        if put:
            buf = io.BytesIO()
            with tarfile.open(fileobj=buf, mode="w") as tf:
                for p in put:
                    tf.add(str(ROOT / p), arcname=p)
            RS.ssh(dst, f"cd {RS.R} && tar xf - --skip-old-files && echo ok", data=buf.getvalue(), timeout=1800, tries=2)
            moved[f"to_{dst}"] += len(put)
    # takes.json：三处写同一份（服务器原子写 + 旧版备份；笔记本走 merge_pull 的备份）
    for sid, doc in docs.items():
        ep, s = sid.split("-")
        rel = f"data/renders/{ep}/{s}/takes.json"
        body = json.dumps(doc, ensure_ascii=False, indent=1).encode()
        for h in ("gpu33", "gpu36"):
            exp = int(((snap.get(h) or {}).get(sid) or {}).get("seq") or 0)
            out = RS.ssh(h, f"cd {RS.R} && if [ -f tools/pipeline/takes_cli.py ]; then {RS.PY[h]} tools/pipeline/takes_cli.py replace "
                            f"--sid {sid} --op resolve_dup_takes --by WORKFLOW --op-id dupmerge:{sid}:{at} --expect-seq {exp}; echo rc=$?; "
                            f"else mkdir -p $(dirname {rel}) && [ -f {rel} ] && cp {rel} {rel}.before_dupmerge_{at.replace(':', '')}; "
                            f"cat > {rel}.new && mv {rel}.new {rel} && echo rc=0; fi", data=body, timeout=120, tries=2).decode("utf-8", "replace")
            if "rc=3" in out:
                raise RuntimeError(f"{h} {sid} takes.json 在判定之后被改过（stale_base）：{out[-200:]}；重跑 apply")
        sys.path.insert(0, str(ROOT / "services/render_router"))
        from ns_render import pipeline as P      # K-OPS-W29：笔记本这份也只经 mutate_takes 写
        P.mutate_takes(sid, lambda _cur, _doc=doc: {k: v for k, v in _doc.items() if k not in ("seq", "last_op", "last_ops")},
                       op="resolve_dup_takes", by="WORKFLOW", op_id=f"dupmerge:{sid}:{at}")
    return {"dry": False, "report": report, "files": moved, "shots": len(docs)}


def live_snapshot() -> dict:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools/autopilot"))
    import resident_sync as RS
    dup = json.loads(RS.ssh("gpu33", f"cat {RS.R}/data/_quarantine/dup_s1_ep0809_gpu33.json", timeout=60, tries=2))
    shots = sorted({r["obj"].split(":", 1)[1] for r in dup["rows"]})
    code = "import json,sys\nout={}\nfor sid in sys.argv[1].split(','):\n    ep,s=sid.split('-')\n    try:\n        out[sid]=json.load(open(f'data/renders/{ep}/{s}/takes.json',encoding='utf-8'))\n    except Exception as e:\n        out[sid]={}\nprint(json.dumps(out,ensure_ascii=False))\n"
    res = {}
    for h in ("gpu33", "gpu36"):
        raw = RS.ssh(h, f"cd {RS.R} && python3 - {','.join(shots)}", data=code.encode(), timeout=300, tries=2).decode("utf-8", "replace")
        res[h] = json.loads([x for x in raw.splitlines() if x.startswith("{")][-1])
    return {"dup": dup, "gpu33": res["gpu33"], "gpu36": res["gpu36"], "laptop": {}}


def run_apply(dry: bool = False) -> dict:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools/autopilot"))
    import resident_sync as RS
    snap = live_snapshot()
    shots = sorted({r["obj"].split(":", 1)[1] for r in snap["dup"]["rows"]})
    if not dry:                                  # 执行期间先按镜暂停 gpu33 第一季 producer（K-OPS-E19），15 分钟后自动失效
        RS.ssh("gpu33", f"cd {RS.R} && {RS.PY['gpu33']} tools/autopilot/producer.py pause --shots {','.join(shots)} --minutes 15 "
                        f"--by WORKFLOW_DUP_MERGE --note 两台重复出图逐镜合并中", timeout=120, tries=2)
    return apply(lambda: snap if dry else live_snapshot(), [], dry=dry)


def main(argv=None) -> int:
    a = list(sys.argv[1:] if argv is None else argv)
    if a and a[0] == "apply":                 # apply [--dry]：现取两台 takes → 重算判定 → 合并写回 + 补图（先暂停这批镜）
        print(json.dumps(run_apply(dry="--dry" in a), ensure_ascii=False, indent=1))
        return 0
    if len(a) < 2 or a[0] != "plan":
        print(__doc__)
        return 2
    snap = json.loads(Path(a[1]).read_text(encoding="utf-8"))
    res = plan(snap)
    if "--out" in a:
        import os
        outp = Path(a[a.index("--out") + 1])
        tmp = outp.with_name(outp.name + ".tmp")
        tmp.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, outp)
    from collections import Counter
    print(json.dumps({"rows": len(res), "rule": Counter(r["rule"] for r in res), "use": Counter(r["use"] for r in res)}, ensure_ascii=False))
    for r in res:
        print(f"{r['shot']:9s} {r['stage']:5s} {r['rule']} use={r['use']:5s} 36#{r['n36']}:{'过' if r['ok36'] else '不过'}  33#{r['n33']}:{'过' if r['ok33'] else '不过'}  隔离33={r['quarantine_33']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
