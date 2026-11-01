"""链条契约校验（CHAINSPEC 2026-10-31）。

    .venv/Scripts/python.exe tools/pipeline/check_chain.py                 # 引用完整性：chain.yaml ↔ schema ↔ 规则 ↔ 校验器 ↔ knowledge
    .venv/Scripts/python.exe tools/pipeline/check_chain.py --artifact <文件> [--json]
        # 产物属于哪个节点、违反了哪条规则（规则所属连接 + 给写作模型的原话）；同目录有上一节点产物时一并查连接规则

完整性检查项：
  N1 节点 P0–P12 齐全；L1 每段连接的 from / to 是节点；R1 连接引用的规则在 rules 里、规则的 link 与引用它的连接一致；
  R2 上游规则的 check 在 validators 里；R3 schema 模块 RULE_IDS（代码实际产出的规则号）与 chain.yaml rules 双向一致；
  V1 python 校验器可导入、cli / file 校验器文件存在；F1 样例、模板、外部规则文件存在；
  K1 knowledge/rules 每条都有 link，且 link 都是 chain.yaml 的连接 id（不是就报给 ARCH）；D1 downstream 文件存在（缺 = warn）。
退出码：0 = 无 error；1 = 有 error。
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

from chainlib import ROOT, chain, knowledge_rules, links_of, rel, resolve_ref, rule_index

NODES = [f"P{i}" for i in range(13)]
SCHEMA_MODULES = ["ns_schema.storyline", "ns_schema.episode_outline", "ns_schema.screenplay"]


def integrity() -> list[dict]:
    out: list[dict] = []

    def err(code, msg, level="error"):
        out.append({"code": code, "level": level, "message": msg})

    c = chain()
    nodes, links, rules, vals = c.get("nodes") or {}, c.get("links") or {}, rule_index(), c.get("validators") or {}
    for n in NODES:
        if n not in nodes:
            err("N1", f"缺节点 {n}")
    for lid, lk in links.items():
        if lk.get("from") not in nodes:
            err("L1", f"{lid}.from={lk.get('from')} 不是节点")
        if lk.get("to") not in nodes and lid != "P11-RETRY":
            err("L1", f"{lid}.to={lk.get('to')} 不是节点")
        if lid != "P11-RETRY" and lid != f"{lk.get('from')}-{lk.get('to')}":
            err("L1", f"连接 id {lid} 与 from/to 不一致")
        for r in lk.get("rules") or []:
            if r.startswith("knowledge:"):
                if r.split(":", 1)[1] not in links:
                    err("R1", f"{lid} 引用 {r}：不是连接 id")
                continue
            if r not in rules:
                err("R1", f"{lid} 引用的规则 {r} 不在 rules")
            elif rules[r].get("link") != lid:
                err("R1", f"规则 {r}.link={rules[r].get('link')}，却挂在连接 {lid}")
        for v in lk.get("validators") or []:
            if v not in vals:
                err("V1", f"{lid} 的校验器 {v} 没登记")
        w = lk.get("writer") or {}
        if w.get("template") and not (ROOT / w["template"]).exists():
            err("F1", f"{lid} 模板不存在：{w['template']}")
        for f in lk.get("external_rules") or []:
            if not f.startswith("knowledge:") and not (ROOT / f).exists():
                err("F1", f"{lid} 外部规则文件不存在：{f}")
        if lk.get("on_fail") and lk["on_fail"] not in (c.get("fallback") or {}):
            err("L2", f"{lid}.on_fail={lk['on_fail']} 不在 fallback")
        if lk.get("gate") and lk["gate"] not in (c.get("gates") or {}):
            err("L3", f"{lid}.gate={lk['gate']} 不在 gates")
    listed = {r for lk in links.values() for r in lk.get("rules") or []}
    for rid, r in rules.items():
        if rid not in listed:
            err("R1", f"规则 {rid} 没挂在任何连接上")
        if r.get("check") not in vals:
            err("R2", f"规则 {rid} 的 check={r.get('check')} 没登记")
        for k in ("level", "writer_text", "evidence", "confidence"):
            if not r.get(k):
                err("R4", f"规则 {rid} 缺 {k}")
    implemented = set()
    for m in SCHEMA_MODULES:
        try:
            implemented |= set(resolve_ref(m + ":RULE_IDS"))
        except Exception as e:  # noqa: BLE001
            err("V1", f"{m} 导入失败：{e}")
    declared = {rid for rid, r in rules.items() if str(vals.get(r.get("check"), {}).get("ref", "")).startswith("ns_schema.")}
    for x in sorted(implemented - set(rules)):
        err("R3", f"代码产出规则号 {x}，chain.yaml rules 里没有")
    for x in sorted(declared - implemented):
        err("R3", f"chain.yaml 规则 {x} 指向 schema 校验器，但代码 RULE_IDS 里没有")
    for vid, v in vals.items():
        if v.get("kind") == "python":
            try:
                resolve_ref(v["ref"])
            except Exception as e:  # noqa: BLE001
                err("V1", f"校验器 {vid}（{v['ref']}）不能导入：{type(e).__name__}: {e}")
        elif v.get("path") and not (ROOT / v["path"]).exists():
            err("V1", f"校验器 {vid} 文件不存在：{v['path']}")
    for n, nd in nodes.items():
        ex = (nd.get("output") or {}).get("example")
        if ex and not (ROOT / ex).exists():
            err("F1", f"{n} 样例不存在：{ex}")
        for v in nd.get("validators") or []:
            if not v.startswith("knowledge:") and v not in vals:
                err("V1", f"{n} 的校验器 {v} 没登记")
    for r in knowledge_rules():
        ls = links_of(r)
        if not ls:
            err("K1", f"knowledge {r.get('id')}（{r['_file']}）没有 link 字段", "warn")
        for x in ls:
            if x not in links:
                err("K1", f"knowledge {r.get('id')}（{r['_file']}）link={x} 不是 chain.yaml 的连接")
    for k, v in (c.get("downstream") or {}).items():
        for p in ([v] if isinstance(v, str) else v):
            if not glob.glob(str(ROOT / p.rstrip("/"))):
                err("D1", f"downstream.{k} 不存在：{p}", "warn")
    return out


# ---------------------------------------------------------------------------- 产物归属
SCHEMA_NODE = {"nsfs.brief/1": "P0", "nsfs.storyline/1": "P1", "nsfs.episode_outline/1": "P2", "nsfs.screenplay/1": "P3",
               "nsfs.shot_spec/2": "P4"}


def node_of(path: Path, text: str) -> str | None:
    if path.suffix == ".json":
        try:
            d = json.loads(text)
        except ValueError:
            return None
        if isinstance(d, dict):
            if d.get("schema") in SCHEMA_NODE:
                return SCHEMA_NODE[d["schema"]]
            if "shots" in d and "fps" in d or path.name.endswith(".timeline.json"):
                return "P10"
            if path.name == "takes.json":
                return "P8"
        return None
    if path.suffix == ".md" and "## ep" in text:
        return "P4"
    if path.suffix in (".mp4", ".mov"):
        return "P8"
    return None


def _sibling(path: Path, pattern: str):
    hits = sorted(path.parent.glob(pattern))
    return hits[0] if hits else None


def check_artifact(path: Path) -> dict:
    from ns_schema import episode_outline as EO
    from ns_schema import screenplay as SPM
    from ns_schema import storyline as SL
    text = path.read_text(encoding="utf-8") if path.suffix in (".json", ".md", ".txt") else ""
    node = node_of(path, text)
    issues, linked = [], []
    if node == "P0":
        issues = SL.check_brief(text).issues
    elif node == "P1":
        rep = SL.check_storyline(text)
        issues = rep.issues
        b = _sibling(path, "P0_brief.json")
        if rep.obj is not None and b:
            br = SL.check_brief(b.read_text(encoding="utf-8"))
            if br.obj is not None:
                issues += SL.check_link_p0_p1(br.obj, rep.obj).issues
                linked.append(rel(b))
    elif node == "P2":
        rep = EO.check_outline(text)
        issues = rep.issues
        s = _sibling(path, "P1_storyline.json")
        if rep.obj is not None and s:
            sr = SL.check_storyline(s.read_text(encoding="utf-8"))
            if sr.obj is not None:
                issues += EO.check_link_p1_p2(sr.obj, rep.obj).issues
                linked.append(rel(s))
    elif node == "P3":
        s = _sibling(path, "P1_storyline.json")
        roster = None
        if s:
            sr = SL.check_storyline(s.read_text(encoding="utf-8"))
            roster = [c.name for c in sr.obj.characters] if sr.obj else None
        rep = SPM.check_screenplay(text, roster=roster)
        issues = rep.issues
        o = _sibling(path, f"P2_ep{rep.obj.episode:02d}_outline.json") if rep.obj is not None else None
        if rep.obj is not None and o:
            orp = EO.check_outline(o.read_text(encoding="utf-8"))
            if orp.obj is not None:
                issues += SPM.check_link_p2_p3(orp.obj, rep.obj).issues
                linked.append(rel(o))
    elif node == "P4" and path.suffix == ".md":
        import re
        from p4_adapter import check_p4
        m = re.search(r"^## ep(\d+)《", text, re.M)
        ep = int(m.group(1)) if m else 1
        body = text[m.start():] if m else text
        rep, shots, specs, _ = check_p4(body, ep)
        issues = rep.issues
        p3 = _sibling(path, f"P3_ep{ep:02d}_screenplay.json")
        if p3 and shots:
            spr = SPM.check_screenplay(p3.read_text(encoding="utf-8"))
            if spr.obj is not None:
                issues += SPM.check_link_p3_p4(spr.obj, shots).issues
                linked.append(rel(p3))
    elif node == "P4":
        from ns_schema.shot_spec import ShotSpec, missing_fields
        sp = ShotSpec.model_validate_json(text)
        issues = [type("I", (), {"rule": m.rule, "level": m.severity, "message": m.message, "field": m.field})()
                  for m in missing_fields(sp)]
    rules = rule_index()
    out = []
    for i in issues:
        rid = i.rule
        r = rules.get(rid) or {}
        out.append({"rule": rid, "level": i.level, "field": i.field, "message": i.message,
                    "link": r.get("link") or _link_for_external(rid, node), "writer_text": r.get("writer_text")})
    return {"artifact": rel(path), "node": node,
            "node_name": (chain()["nodes"].get(node) or {}).get("name") if node else None,
            "checked_with": linked, "blocking": sum(x["level"] == "block" for x in out),
            "warnings": sum(x["level"] != "block" for x in out), "issues": out,
            "note": None if node else "认不出节点：不是链条产物（P0–P4 JSON / 剧本分镜 md / Shot Spec JSON / timeline / takes）"}


def _link_for_external(rid: str, node: str | None) -> str | None:
    """现行规则号（QW-/H3-/SS-/RL-）都属于写作分镜这一段"""
    if node == "P4":
        return "P3-P4"
    return None


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="链条契约校验")
    ap.add_argument("--artifact")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if a.artifact:
        p = Path(a.artifact)
        p = p if p.is_absolute() else ROOT / p
        rep = check_artifact(p)
        if a.json:
            print(json.dumps(rep, ensure_ascii=False, indent=1))
        else:
            print(f"产物：{rep['artifact']}\n节点：{rep['node']} {rep['node_name'] or ''}  block {rep['blocking']} / warn {rep['warnings']}"
                  + (f"\n连同：{'、'.join(rep['checked_with'])}" if rep["checked_with"] else "") + (f"\n{rep['note']}" if rep["note"] else ""))
            for i in rep["issues"]:
                print(f"  [{i['level']}] {i['rule']}（连接 {i['link']}）{i['field']}：{i['message'][:200]}")
                if i.get("writer_text"):
                    print(f"        规则原话：{i['writer_text']}")
        return 0 if rep["node"] and rep["blocking"] == 0 else 1
    res = integrity()
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
    else:
        c = chain()
        print(f"chain.yaml {c.get('version')}：节点 {len(c['nodes'])}，连接 {len(c['links'])}，上游规则 {len(c['rules'])}，"
              f"校验器 {len(c['validators'])}，knowledge 规则 {len(knowledge_rules())}")
        for r in res:
            print(f"  [{r['level']}] {r['code']} {r['message']}")
        print("通过" if not any(r["level"] == "error" for r in res) else "有 error")
    return 0 if not any(r["level"] == "error" for r in res) else 1


if __name__ == "__main__":
    raise SystemExit(main())
