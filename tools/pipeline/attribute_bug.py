"""审片发现 / bug → 归因到链条的某段连接 → 已有规则 or 缺规则 → 规则草案进 knowledge/inbox/（CHAINSPEC 2026-10-31，RSI）。

    .venv/Scripts/python.exe tools/pipeline/attribute_bug.py "镜头切换生硬" ["眼神表情生硬" …] [--episode 2] [--write] [--json]
    .venv/Scripts/python.exe tools/pipeline/attribute_bug.py --v1-demo --episode 2 --write     # 项目方 2026-10-31 的 v1 五条

步骤（确定性，不调用 LLM）：
1. 症状匹配：config/pipeline/attribution.yaml 的关键词 → 候选连接（按排查顺序）+ 相关规则号；
2. 规则查找：每个规则号在 chain.yaml rules / knowledge/rules/*.yaml / 现行规则文件与校验代码里找，记下所属连接、状态、出处；
3. 产物对照（--episode）：把生产剧本 data/import/script_v2.json 这一集转成 Shot Spec，用现行校验器数这些规则号的违规次数
   ——“产物违反现行规则” = 规则有、产物是旧规则写的 / 规则没执行；违规 0 而 bug 仍在 = 规则不够或不在这段；
4. 结论：每个候选连接标 已有规则（附违规数）/ 缺规则；首要连接 = 第一个“有违规”的连接，否则第一个“缺规则”的连接；
5. --write：按 knowledge/schema.yaml 的条目格式写草案 knowledge/inbox/<日期>_<症状>.yaml（status: 待确认，link = 首要连接），
   由总调度 / ARCH 确认后移进 knowledge/rules/。草案只讲格式与系统做法，不写剧情、不评价内容。
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import yaml

from chainlib import ROOT, chain, knowledge_rules, links_of, rule_index

ATTR = ROOT / "config" / "pipeline" / "attribution.yaml"
INBOX = ROOT / "knowledge" / "inbox"
EXTERNAL_SOURCES = ["config/script_chat_rules.md", "packages/schema/ns_schema/shot_spec.py", "services/recipes/ns_recipes/lint.py",
                    "tools/validate_qwen_script.py", "packages/schema/ns_schema/h3_lint.py"]
EXTERNAL_LINK = {"SS-": "P3-P4", "QW-": "P3-P4", "S1-": "P3-P4", "IMG-": "P3-P4", "H3-": "P4-P7", "RL-T": "P4-P7", "RL-": "P4-P7"}
DOMAIN_ABBR = {"render": "REN", "prompt": "PRM", "writer": "WRT", "edit": "EDT", "review": "REV", "loop": "LOOP", "asset": "AST", "ops": "OPS"}
V1_BUGS = ["镜头切换生硬", "眼神表情生硬", "提示词时间轴差", "节奏慢", "旁白声音老"]   # 项目方 2026-10-31 对 ep02 v1 的原话要点


def load_attr() -> dict:
    return yaml.safe_load(ATTR.read_text(encoding="utf-8"))


def match(text: str, attr: dict) -> list[tuple[int, dict]]:
    scored = []
    for s in attr["symptoms"]:
        hits = [k for k in s["keywords"] if k.lower() in text.lower()]
        if hits:
            scored.append((len(hits) + sum(len(h) for h in hits) / 10, s))
    return sorted(scored, key=lambda x: -x[0])


def _grep_external(rid: str) -> str | None:
    for f in EXTERNAL_SOURCES:
        p = ROOT / f
        if p.exists() and re.search(rf"(?<![A-Za-z0-9-]){re.escape(rid)}(?![0-9])", p.read_text(encoding="utf-8")):
            return f
    return None


def find_rule(rid: str) -> dict:
    cr = rule_index().get(rid)
    if cr:
        return {"id": rid, "where": "config/pipeline/chain.yaml", "links": [cr["link"]], "status": "确认", "level": cr.get("level"),
                "text": cr.get("writer_text")}
    for k in knowledge_rules():
        if k.get("id") == rid:
            return {"id": rid, "where": k["_file"], "links": links_of(k), "status": k.get("status"), "text": k.get("title")}
    f = _grep_external(rid)
    if f:
        link = next((v for p, v in sorted(EXTERNAL_LINK.items(), key=lambda x: -len(x[0])) if rid.startswith(p)), None)
        return {"id": rid, "where": f, "links": [link] if link else [], "status": "现行", "text": None}
    return {"id": rid, "where": None, "links": [], "status": "找不到", "text": None}


_SPEC_CACHE: dict = {}


def violations(episode: int | None) -> collections.Counter:
    """生产剧本这一集按现行校验器数违规（SS-* / RL-T*）"""
    if not episode:
        return collections.Counter()
    if episode in _SPEC_CACHE:
        return _SPEC_CACHE[episode]
    from ns_recipes.lint import timeline_for_spec
    from ns_recipes.spec_import import specs_from_import
    from ns_schema.script import ScriptImport
    from ns_schema.shot_spec import check_sequence, missing_fields
    c: collections.Counter = collections.Counter()
    try:
        si = ScriptImport.model_validate_json((ROOT / "data" / "import" / "script_v2.json").read_text(encoding="utf-8"))
        specs = specs_from_import(si, episode)
        for s in specs:
            for m in missing_fields(s):
                c[m.rule] += 1
            for i in timeline_for_spec(s.h3.text or "", s, s.frames, strict=True):
                c[i["code"]] += 1
        for m in check_sequence(specs):
            c[m.rule] += 1
        c["_shots"] = len(specs)
    except Exception as e:  # noqa: BLE001
        c["_error:" + type(e).__name__] = 1
    _SPEC_CACHE[episode] = c
    return c


def attribute(bug: str, episode: int | None = None) -> dict:
    attr = load_attr()
    ms = match(bug, attr)
    if not ms:
        return {"bug": bug, "symptom": None, "primary_link": None, "verdict": "待人工归因（关键词都没命中）", "links": [],
                "note": attr["fallback"]["note"]}
    sym = ms[0][1]
    rules = [find_rule(r) for r in sym.get("rules") or []]
    viol = violations(episode)
    links = []
    for cand in sym["links"]:
        lk = cand["link"]
        own = set(cand.get("rules") or [])      # 归因表里明确挂在这段的规则号（现行规则号默认归属可能是相邻段）
        rs = [r for r in rules if lk in r["links"] or r["id"] in own]
        rs += [find_rule(x) for x in own if x not in {r["id"] for r in rules}]
        rs += [{"id": k["id"], "where": k["_file"], "links": links_of(k), "status": k.get("status"), "text": k.get("title")}
               for k in knowledge_rules() if lk in links_of(k) and any(w in (k.get("title") or "") for w in sym["keywords"])
               and k["id"] not in {r["id"] for r in rs}]
        v = {r["id"]: viol.get(r["id"], 0) for r in rs if viol.get(r["id"])}
        state = ("已有规则，产物违反" if v else "已有规则") if rs else "缺规则"
        links.append({"link": lk, "why": cand["why"], "state": state, "rules": rs, "violations": v})
    primary = next((x for x in links if x["violations"]), None) or next((x for x in links if x["state"] == "缺规则"), None) or links[0]
    if primary["violations"]:
        verdict = (f"归因 {primary['link']}：现行规则已覆盖（{', '.join(primary['violations'])}），但这一集产物是旧规则写的 / 规则没执行"
                   f"（违规 {sum(primary['violations'].values())} 次 / {viol.get('_shots', '?')} 镜）→ 按现行规则重写该段，并把规则从提示升为闸门")
    elif primary["state"] == "缺规则":
        verdict = f"归因 {primary['link']}：这一段没有对应规则（缺规则）→ 草案进 knowledge/inbox/"
    else:
        verdict = f"归因 {primary['link']}：有规则、产物不违反 → 规则本身不够（阈值 / 写法），需要加强"
    return {"bug": bug, "symptom": sym["id"], "symptom_name": sym["name"], "primary_link": primary["link"], "verdict": verdict,
            "links": links, "owner_quote": sym.get("owner_quote"), "draft": sym.get("draft")}


def _next_id(abbr: str) -> str:
    used = {k.get("id") for k in knowledge_rules()}
    for f in INBOX.glob("*.yaml"):
        used |= {r.get("id") for r in (yaml.safe_load(f.read_text(encoding="utf-8")) or {}).get("rules") or []}
    n = 1
    while f"K-{abbr}-I{n:02d}" in used:
        n += 1
    return f"K-{abbr}-I{n:02d}"


def write_draft(res: dict, episode: int | None) -> Path | None:
    d = res.get("draft")
    if not res.get("primary_link"):
        d = d or {"domain": "review", "title": f"待归因：{res['bug']}", "when": "审片发现", "then": "总调度指定连接后补规则"}
    if not d:
        return None
    INBOX.mkdir(parents=True, exist_ok=True)
    prim = next((x for x in res["links"] if x["link"] == res["primary_link"]), None)
    ev = [{"src": "config/pipeline/attribution.yaml", "note": f"症状 {res.get('symptom')}；项目方 v1 审片：{res['bug']}"}]
    if res.get("owner_quote") and "writer_requests" in res["owner_quote"]:
        ev.append({"src": "docs/ep02_iter/writer_requests.md", "quote": res["owner_quote"][:30]})
    if prim and prim["violations"]:
        ev.append({"src": "data/import/script_v2.json", "note": f"ep{episode:02d} 现行校验违规 {prim['violations']}（tools/pipeline/attribute_bug.py）"})
    entry = {"id": _next_id(DOMAIN_ABBR.get(d.get("domain", "review"), "REV")), "domain": d.get("domain", "review"),
             "link": [x["link"] for x in res["links"][:2]] if res["links"] else None,
             "title": d["title"], "when": d["when"], "then": d["then"],
             **({"writer_text": d["writer_text"]} if d.get("writer_text") else {}),
             **({"director_text": d["director_text"]} if d.get("director_text") else {}),
             "evidence": ev, "confidence": "medium" if prim and prim["violations"] else "low", "status": "待确认",
             "date": time.strftime("%Y-%m-%d"),
             "attribution": {"bug": res["bug"], "primary_link": res["primary_link"], "verdict": res["verdict"],
                             "existing_rules": [r["id"] for x in res["links"] for r in x["rules"]]}}
    if entry["link"] and res["primary_link"] in entry["link"]:
        entry["link"].remove(res["primary_link"])
        entry["link"].insert(0, res["primary_link"])
    p = INBOX / f"{time.strftime('%Y-%m-%d')}_{res.get('symptom') or 'unattributed'}.yaml"
    head = ("# 规则草案（tools/pipeline/attribute_bug.py 生成，CHAINSPEC）。status 待确认：总调度 / ARCH 确认后移到 knowledge/rules/ 并改 status。\n"
            "# attribution 字段是归因记录，移入正式规则时可删。\n")
    p.write_text(head + yaml.safe_dump({"rules": [entry]}, allow_unicode=True, sort_keys=False, width=200), encoding="utf-8")
    return p


def render(res: dict) -> str:
    out = [f"■ {res['bug']}  →  {res.get('symptom_name') or '未匹配'}", f"  结论：{res['verdict']}"]
    for x in res["links"]:
        mark = "★" if x["link"] == res["primary_link"] else " "
        rs = "、".join(f"{r['id']}({r['status']})" for r in x["rules"]) or "—"
        vs = ("；违规 " + "、".join(f"{k}×{v}" for k, v in x["violations"].items())) if x["violations"] else ""
        out.append(f"  {mark} {x['link']:<9} {x['state']:<10} 规则：{rs}{vs}\n               {x['why']}")
    if res.get("draft_path"):
        out.append(f"  草案：{res['draft_path']}")
    return "\n".join(out)


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="bug → 连接归因 → 规则草案")
    ap.add_argument("bugs", nargs="*")
    ap.add_argument("--v1-demo", action="store_true", help="项目方 2026-10-31 的 v1 五条")
    ap.add_argument("--episode", type=int)
    ap.add_argument("--write", action="store_true", help="草案写进 knowledge/inbox/")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    bugs = (V1_BUGS if a.v1_demo else []) + a.bugs
    res = []
    for b in bugs:
        r = attribute(b, a.episode)
        if a.write:
            p = write_draft(r, a.episode)
            r["draft_path"] = p.relative_to(ROOT).as_posix() if p else None
        res.append(r)
    if a.write and (ROOT / "tools" / "knowledge" / "compile.py").exists():
        cp = subprocess.run([sys.executable, str(ROOT / "tools" / "knowledge" / "compile.py"), "--inbox", "--check"],
                            capture_output=True, cwd=ROOT, env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"})
        tail = (cp.stdout or b"").decode("utf-8", "replace").strip().splitlines()
        inbox_line = [ln for ln in tail if ln.startswith("inbox")]
        for r in res:
            r["inbox_check"] = inbox_line[-1] if inbox_line else None
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    else:
        print("\n\n".join(render(r) for r in res))
        if res and res[0].get("inbox_check"):
            print("\n" + res[0]["inbox_check"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
