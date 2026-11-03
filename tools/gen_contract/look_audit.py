"""剧本 / 造型一致性审计（REFLOCK 2026-10-31，契约 I3 / I4；规则 K-AST-231）。

项目方原话：“整个剧本里面很多东西你都没有写好，错误很多。”本工具只做格式与登记核对，不评价内容：
  A. 每集造型行（**造型｜角色**，含“自镜N起”）→ 对上 P1 登记的哪套造型（服装 + 鞋逐字比对）；对不上 = 造型未登记 / 偏离
  B. P1 登记的“使用集”与实际使用是否一致
  C. 每镜 img 正文里写到的服装 / 鞋，是否和本镜造型冲突（写了同角色其它造型的部件、或鞋类相反：高跟 vs 球鞋 / 拖鞋）
  D. 同一场景内连续镜头换造型（一镜一换）
  E. 每套造型每个部件的资产图来源（衣橱产品图 / 仅设定图 / 缺图）
系统可确定修的（每镜每人的造型 id 登记、镜号）由系统写进 <run>/assets/shot_looks.json；内容层的问题列进
<run>/assets/look_revision_requests.json，交写作模型（abliteration，关推理）按登记改正，台词不动。

    .venv/Scripts/python.exe tools/gen_contract/look_audit.py [--source script_v2|p4] [--write]
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "autopilot"))
import runs as RUNS  # noqa: E402
_LEGACY = RUNS.legacy_run(ROOT)   # I-16：第一季专用历史工具（入口 gate_legacy_tool 要求显式 --run）
for p in ("services/agent", "packages/schema", "tools/pipeline"):
    sys.path.insert(0, str(ROOT / p))

from ns_agent import asset_refs as AR  # noqa: E402

P = _LEGACY
RUN = ROOT / ("data/pipeline/runs/" + _LEGACY)
HEELS = ("高跟", "细跟", "细高跟", "stiletto", "heel")
FLATS = ("球鞋", "帆布鞋", "拖鞋", "平底鞋", "短靴", "马丁靴", "皮鞋")
SERIES_EPS = set(range(1, 11))
PROP_VERBS = ("拎", "捧", "拿着", "拿起", "握着", "递", "挂在", "搭在臂弯", "抱着", "托着")


def episodes(source: str):
    if source == "p4":
        import os
        os.environ.setdefault("NS_ALLOW_P4_SOURCE", "1")   # CLEANUP 11-01（K-OPS-Q24，总调度 r2：P4 旧来源迁到导入稿）：--source p4 = 调研对照写作中间稿，显式放行
        import image_jobs as IJ
        out = []
        for n in range(1, 11):
            _si, ep = IJ.load_episode(RUN / f"ep{n:02d}" / f"P4_ep{n:02d}.md")
            out.append(ep)
        return out
    d = json.loads((ROOT / "data/import/script_v2.json").read_text(encoding="utf-8"))
    eps = {n for s in d.get("sources") or [] if "series10" in s.get("path", "") for n in s.get("episodes") or []} or SERIES_EPS
    return [e for e in d["episodes"] if e["number"] in eps]


def g(o, k, d=None):
    return AR.g(o, k, d)


def shoe_kind(t: str) -> str | None:
    if any(w in t for w in HEELS):
        return "heel"
    if any(w in t for w in FLATS):
        return "flat"
    return None


def audit(source: str = "script_v2") -> dict:
    looks = AR.load_looks(P)
    inv = AR.look_inventory(P)
    rows_out, shot_looks, issues = [], {}, []
    used: dict[str, set] = {}

    def issue(level, kind, where, detail, fix=None, layer="content"):
        issues.append({"level": level, "kind": kind, "where": where, "detail": detail, "fix": fix, "layer": layer})

    for ep in episodes(source):
        n = int(g(ep, "number"))
        # A. 造型行
        for r in AR.look_rows(ep):
            name = g(r, "character")
            cid = AR.NAME_ID.get(name, name)
            lid, sc, dev = AR.match_look(looks.get(cid) or {}, g(r, "slots"), g(r, "raw") or "")
            fs = g(r, "from_shot")
            where = f"ep{n:02d} 造型｜{name}" + (f"（自镜{fs}起）" if fs else "")
            rows_out.append({"ep": n, "character": name, "from_shot": fs, "look": lid, "score": round(sc, 2),
                             "deviation": dev, "slots": g(r, "slots")})
            if lid is None:
                issue("block", "造型未登记", where, f"服装“{(g(r, 'slots') or {}).get('服装')}”／鞋“{(g(r, 'slots') or {}).get('鞋')}”对不上 {name} 的 P1 三套造型（最高匹配 {sc:.2f}）",
                      fix=f"按 P1 登记改成 {name} 的某一套造型（A/B/C 原文），或由项目方新增登记")
            elif dev:
                issue("warn", "造型偏离", where, "；".join(dev), fix=f"按 P1 造型{lid} 原文改正造型行")
            if lid:
                used.setdefault(f"{cid}:{lid}", set()).add(n)
        # C / D. 逐镜
        prev = {}
        for s in g(ep, "shots") or []:
            idx = int(g(s, "index"))
            sid = f"ep{n:02d}-S{idx}"
            img = g(s, "img_prompt") or ""
            scene = g(s, "scene_id")
            on = AR.cast_on_screen(s)
            cur_looks = {}
            for name, _pr in on:
                cid = AR.NAME_ID.get(name, name)
                row = AR.look_for(ep, name, idx)
                lid = AR.match_look(looks.get(cid) or {}, g(row, "slots"))[0] if row is not None else None
                cur_looks[cid] = lid
                shot_looks.setdefault(sid, {})[cid] = {"look": lid, "how": "script_match" if lid else "unresolved"}
            for name, _pr in on:
                cid = AR.NAME_ID.get(name, name)
                lid = cur_looks.get(cid)
                if not lid:
                    continue
                L = looks[cid][lid]
                mine = {AR._short(p.label) for p in L.parts}
                others_now = {AR._short(p.label) for c2, l2 in cur_looks.items() if c2 != cid and l2
                              for p in looks[c2][l2].parts}
                for olid, OL in looks[cid].items():
                    if olid == lid:
                        continue
                    for p in OL.parts:
                        lab = AR._short(p.label)
                        if p.slot in ("outfit", "shoes") and len(lab) >= 3 and lab in img and lab not in mine \
                                and not any(lab in m or m in lab for m in mine) and lab not in others_now:
                            cl = next((c for c in re.split(r"[，,；;。]", img) if lab in c), "")
                            if any(v in cl for v in PROP_VERBS):
                                issue("info", "造型单品作道具", sid, f"“{cl.strip()}”——{lab} 是拿在手上的道具，不是本镜穿着（造型{lid}）",
                                      fix=None, layer="note")
                            else:
                                issue("block", "单品与造型冲突", sid, f"{name} 本镜是造型{lid}，正文却写了造型{olid}的“{lab}”（“{cl.strip()}”）",
                                      fix=f"二选一：本镜起改登记为造型{olid}（造型行加“自镜{idx}起”），或正文按造型{lid}改：{L.zh.split('｜')[0]}")
                want = shoe_kind(next((AR._short(p.label) for p in L.parts if p.slot == "shoes"), ""))
                clauses = [c for c in re.split(r"[，,；;。]", img) if name in c or len(on) == 1]
                got = {shoe_kind(c) for c in clauses} - {None}
                if want and got and want not in got:
                    issue("block", "鞋与造型冲突", sid, f"{name} 造型{lid} 的鞋是“{next(AR._short(p.label) for p in L.parts if p.slot == 'shoes')}”，正文写了{'高跟' if 'heel' in got else '平底 / 球鞋类'}",
                          fix="正文的鞋按造型登记改")
                pv = prev.get(cid)
                if pv and pv[1] == scene and pv[2] and lid != pv[2]:
                    issue("warn", "场内换装", f"{pv[0]}→{sid}", f"{name} 同一场景 {scene} 内从造型{pv[2]} 换成造型{lid}",
                          fix="确认剧情有换装交代；没有就统一为同一造型")
                prev[cid] = (sid, scene, lid)
    # B. 使用集
    for cid, lks in looks.items():
        for lid, L in lks.items():
            m = re.findall(r"ep(\d+)", L.use)
            reg = {int(x) for x in m}
            act = used.get(f"{cid}:{lid}", set())
            extra, unused = sorted(act - reg), sorted(reg - act)
            if extra or unused:
                issue("info", "使用集与登记不符", f"{AR.ID_NAME.get(cid, cid)} 造型{lid}",
                      f"登记 {sorted(reg)}，实际 {sorted(act)}" + (f"；多用于 {extra}" if extra else "") + (f"；登记了没用 {unused}" if unused else ""),
                      fix="P1 use 字段按实际更新（系统可改登记，不动剧本）", layer="registry")
    # E. 资产来源
    assets = []
    for lk in inv:
        for p in lk["parts"]:
            assets.append({"character": lk["name"], "look": lk["look"], "part": p["label"], "slot": p["slot"],
                           "status": p["status"], "item_id": p["item_id"], "item_file": p["item_file"]})
            if p["status"] == "missing":
                issue("block", "资产缺图", f"{lk['name']} 造型{lk['look']}", f"{p['label']} 没有任何图", layer="asset")
    return {"generated": time.strftime("%Y-%m-%d %H:%M:%S"), "source": source, "rule": "K-AST-231（REFLOCK）",
            "look_rows": rows_out, "issues": issues, "shot_looks": shot_looks, "assets": assets}


def revision_requests(rep: dict) -> list[dict]:
    """内容层（layer=content，block / warn）→ 写作模型修订请求（台词不动）"""
    out = []
    for i in rep["issues"]:
        if i["layer"] != "content" or i["level"] == "info":
            continue
        out.append({"where": i["where"], "kind": i["kind"], "problem": i["detail"], "fix": i["fix"],
                    "constraints": ["台词 / 旁白 / 🎙 一字不动", "只改造型行与 img / motion 正文里的服装、鞋、饰品描写",
                                    ("按 P1 登记原文（data/pipeline/runs/" + _LEGACY + "/P1_looks.json）"), "成年人与锁定外貌（HC-07）照旧"]})
    return out


def main():
    RUNS.gate_legacy_tool(None, __file__)
    sys.stdout.reconfigure(encoding="utf-8")
    src = sys.argv[sys.argv.index("--source") + 1] if "--source" in sys.argv else "script_v2"
    rep = audit(src)
    rep["p4_compare"] = None
    if src == "script_v2":
        p4 = audit("p4")
        diff = [{"shot": k, "script_v2": v, "p4": p4["shot_looks"].get(k)} for k, v in rep["shot_looks"].items()
                if p4["shot_looks"].get(k) and {c: x["look"] for c, x in v.items()} != {c: x["look"] for c, x in p4["shot_looks"][k].items()}]
        rep["p4_compare"] = {"differs": diff, "p4_issue_count": len(p4["issues"])}
    from collections import Counter
    print(json.dumps({"issues": Counter(f"{i['level']}:{i['kind']}" for i in rep["issues"]),
                      "p4_differs": len((rep.get("p4_compare") or {}).get("differs") or [])}, ensure_ascii=False, indent=1))
    if "--write" in sys.argv:
        (ROOT / "data/review_pages/asset_reflock").mkdir(parents=True, exist_ok=True)
        (ROOT / "data/review_pages/asset_reflock/look_audit.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
        reg = {"_doc": "每镜每人的造型 id（系统登记，REFLOCK look_audit 生成；ns_agent.asset_refs.resolve_shot 优先读这里）。"
                       "look=null = 剧本造型对不上 P1 登记，出图阻断，待写作模型按登记改正",
               "generated": rep["generated"], "source": src,
               "shots": {k: {c: x["look"] for c, x in v.items()} for k, v in rep["shot_looks"].items()}}
        try:                                              # 保留已做的系统登记修正（fixes），重写时重新套上
            old = json.loads((RUN / "assets" / "shot_looks.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            old = {}
        reg["fixes"] = old.get("fixes") or []
        reg["fixes_history"] = old.get("fixes_history") or []
        for k in ("overrides", "scene_overrides", "switch_log"):   # 画布“切换本镜参考”写的逐镜覆盖：审计重写时原样保留
            if old.get(k):
                reg[k] = old[k]
        for f in reg["fixes"]:
            reg["shots"].setdefault(f["shot"], {})[f["character"]] = f["to"]
        (RUN / "assets" / "shot_looks.json").write_text(json.dumps(reg, ensure_ascii=False, indent=1), encoding="utf-8")
        (RUN / "assets" / "look_revision_requests.json").write_text(json.dumps(
            {"generated": rep["generated"], "for": "写作模型（abliteration，关推理）", "requests": revision_requests(rep)},
            ensure_ascii=False, indent=1), encoding="utf-8")
        print("written")


if __name__ == "__main__":
    main()
