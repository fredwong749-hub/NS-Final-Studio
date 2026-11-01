"""知识库编译器（ARCH 2026-10-31）：knowledge/ = 系统 memory 的单一事实来源。

做三件事：
1. 校验 knowledge/rules/*.yaml 每条规则（格式、id 唯一、link 在链条契约里、证据文件存在、loop / 提示词条目字段齐全）。
2. 一致性检查：targets 里 kind=recipe 的值必须等于配方（services/recipes）解析后的值；kind=render_quality 对照
   config/render_quality.json（只读）；covered_by=script_chat_rules 的标签必须出现在写作模型加载的 config/script_chat_rules.md。
3. 生成下游文件（文件头标“自动生成，勿手改”）：
   - tools/iterate_loop/rules.yaml        ← domain=loop 条目 + knowledge/settings.yaml
   - config/recipes/writer_knowledge.md   ← writer_text（写作模型 system_parts，带版本号）
   - config/recipes/director_system_prompt.md ← director_text + rubric（审片模型）
   - knowledge/generated/index.json       ← 全部条目 + 版本

用法：
  .venv/Scripts/python.exe tools/knowledge/compile.py            # 校验 + 生成
  .venv/Scripts/python.exe tools/knowledge/compile.py --check    # 只校验；生成物和仓库里的不一致也算失败（CI / 测试用）
  .venv/Scripts/python.exe tools/knowledge/compile.py --inbox    # 另外校验 knowledge/inbox/ 的草案（允许 status 待确认）
加一条新规则：在 knowledge/rules/<域>.yaml 末尾加一条（格式见 knowledge/schema.yaml），跑一次本脚本。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
KB = ROOT / "knowledge"
sys.path.insert(0, str(ROOT / "services" / "recipes"))

DOMAINS = {"render": "REN", "prompt": "PRM", "writer": "WRT", "edit": "EDT", "review": "REV", "loop": "LOOP",
           "asset": "AST", "ops": "OPS",
           "ui": "UI"}   # UIRSI 2026-10-31：界面规则（knowledge/rules/ui.yaml），不进写作 / 审片提示词
STATUSES = {"确认", "建议", "待验", "待许可登记", "项目方闸门"}
INBOX_STATUSES = STATUSES | {"待确认"}
CONFIDENCE = {"high", "medium", "low"}
REQUIRED = ("id", "domain", "link", "title", "when", "then", "evidence", "confidence", "status", "date")
ID_RE = re.compile(r"^K-(REN|PRM|WRT|EDT|REV|LOOP|AST|OPS|UI)-[A-Z]?\d{2,3}$")
GEN_HEADER = "自动生成，勿手改：改 knowledge/ 后运行 tools/knowledge/compile.py"
WRITER_SECTIONS = ("镜头字段", "分拍与动作", "时长与节奏", "身份锚点", "H3 正文", "声音")
DIRECTOR_SECTIONS = ("判定标准", "打分")


# ---------------------------------------------------------------------------------------------- 读取
def load_yaml(p: Path):
    return json.loads(json.dumps(yaml.safe_load(p.read_text(encoding="utf-8")) or {}, ensure_ascii=False, default=str))


def load_rules(directory: Path) -> list[dict]:
    out = []
    for p in sorted(directory.glob("*.yaml")):
        for e in load_yaml(p).get("rules") or []:
            e["_file"] = str(p.relative_to(ROOT)).replace("\\", "/")
            out.append(e)
    return out


def connections(root: Path = ROOT) -> set[str]:
    chain = root / "config" / "pipeline" / "chain.yaml"
    if chain.exists():
        d = load_yaml(chain)
        links = d.get("links") or d.get("connections") or {}
        ids = set(links) if isinstance(links, dict) else {x.get("id") for x in links if isinstance(x, dict)}
        if ids:
            return {i for i in ids if i}
    return set((load_yaml(root / "knowledge" / "links.yaml").get("connections") or {}))


def as_list(v) -> list:
    return v if isinstance(v, list) else ([] if v is None else [v])


def get_path(d, path: str):
    cur = d
    for k in path.split("."):
        if not isinstance(cur, dict) or k not in cur:
            return KeyError
        cur = cur[k]
    return cur


def same(a, b) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool) and not isinstance(b, bool):
        return abs(float(a) - float(b)) < 1e-9
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    return a == b


# ---------------------------------------------------------------------------------------------- 校验
def validate(rules: list[dict], *, inbox: bool = False, root: Path = ROOT) -> list[str]:
    errs, seen = [], {}
    conns = connections(root)
    statuses = INBOX_STATUSES if inbox else STATUSES
    for e in rules:
        rid = e.get("id", "?")
        where = f"{rid}（{e.get('_file')}）"
        for k in REQUIRED:
            if e.get(k) in (None, "", []):
                errs.append(f"{where}: 缺字段 {k}")
        if rid in seen:
            errs.append(f"{where}: id 与 {seen[rid]} 重复")
        seen[rid] = e.get("_file")
        if not ID_RE.match(str(rid)):
            errs.append(f"{where}: id 格式应为 K-<域>-<编号>")
        dom = e.get("domain")
        if dom not in DOMAINS:
            errs.append(f"{where}: domain {dom!r} 不在 {sorted(DOMAINS)}")
        elif not str(rid).startswith(f"K-{DOMAINS[dom]}-"):
            errs.append(f"{where}: id 前缀与 domain {dom} 不符")
        for ln in as_list(e.get("link")):
            if ln not in conns:
                errs.append(f"{where}: link {ln!r} 不在链条连接表里")
        if e.get("status") not in statuses:
            errs.append(f"{where}: status {e.get('status')!r} 不在 {sorted(statuses)}")
        if e.get("confidence") not in CONFIDENCE:
            errs.append(f"{where}: confidence 应为 high/medium/low")
        for ev in as_list(e.get("evidence")):
            src = str((ev or {}).get("src") or "")
            path = re.split(r"\s|§", src, 1)[0]
            if not path or not (root / path).exists():
                errs.append(f"{where}: 证据文件不存在 {path!r}")
        kinds = [t.get("kind") for t in as_list(e.get("targets"))]
        if dom == "loop" or "loop_rule" in kinds:
            lp = e.get("loop") or {}
            if not lp.get("rule_id") or not lp.get("ladder") or not (lp.get("when") or lp.get("spec_rules")):
                errs.append(f"{where}: loop 条目要有 loop.rule_id / when 或 spec_rules / ladder")
        if "writer_prompt" in kinds and not e.get("covered_by"):
            if not e.get("writer_text"):
                errs.append(f"{where}: writer_prompt 目标要有 writer_text")
            sec = next((t.get("section") for t in as_list(e.get("targets")) if t.get("kind") == "writer_prompt"), None)
            if sec not in WRITER_SECTIONS:
                errs.append(f"{where}: writer_prompt section {sec!r} 不在 {WRITER_SECTIONS}")
        if "director_prompt" in kinds:
            if not e.get("director_text"):
                errs.append(f"{where}: director_prompt 目标要有 director_text")
            sec = next((t.get("section") for t in as_list(e.get("targets")) if t.get("kind") == "director_prompt"), None)
            if sec not in DIRECTOR_SECTIONS:
                errs.append(f"{where}: director_prompt section {sec!r} 不在 {DIRECTOR_SECTIONS}")
    ids = {e.get("id") for e in rules}
    ids |= archived_ids(root)
    for e in rules:
        if e.get("supersedes") and e["supersedes"] not in ids:
            errs.append(f"{e.get('id')}: supersedes {e['supersedes']} 不存在")
    return errs


def archived_ids(root: Path = ROOT) -> set:
    """CLEANUP 2026-11-01：已被取代 / 不采纳的条目移到 knowledge/archive/（保留原文、不当现行规则读、不进任何生成物）；
    现行规则的 supersedes 和 RSI_LEDGER 的历史行指向它们也算存在"""
    out = set()
    for ap in sorted((root / "knowledge" / "archive").glob("*.yaml")):
        out |= {a.get("id") for a in (load_yaml(ap).get("rules") or [])}
    return out


def active(rules: list[dict]) -> list[dict]:
    """去掉被 supersedes 替代的条目（生成提示词 / 规则表只用现行条目）"""
    gone = {e["supersedes"] for e in rules if e.get("supersedes")}
    return [e for e in rules if e["id"] not in gone]


def consistency(rules: list[dict], root: Path = ROOT) -> list[str]:
    from ns_recipes import registry as R
    reg = R.load(use_learned=False)
    rq_path = root / "config" / "render_quality.json"
    rq = json.loads(rq_path.read_text(encoding="utf-8")) if rq_path.exists() else {}
    rules_md = (root / "config" / "script_chat_rules.md").read_text(encoding="utf-8")
    errs = []
    cache = {}
    for e in rules:
        for t in as_list(e.get("targets")):
            k = t.get("kind")
            if k == "recipe":
                rid = t["id"]
                if rid not in reg.raw:
                    errs.append(f"{e['id']}: 配方 {rid} 不存在")
                    continue
                rc = cache.setdefault(rid, reg._resolve_raw(rid))
                v = get_path(rc, t["path"])
                if v is KeyError:
                    errs.append(f"{e['id']}: 配方 {rid} 没有参数 {t['path']}")
                elif not same(v, t["value"]):
                    errs.append(f"{e['id']}: 配方 {rid}.{t['path']} = {v!r}，知识库写的是 {t['value']!r}")
            elif k == "render_quality":
                v = get_path(rq, t["path"])
                if v is KeyError or not same(v, t["value"]):
                    errs.append(f"{e['id']}: config/render_quality.json {t['path']} = "
                                f"{'（没有）' if v is KeyError else repr(v)}，知识库写的是 {t['value']!r}")
        if e.get("covered_by") == "script_chat_rules":
            for lab in e.get("covers_labels") or []:
                if f"**{lab}**" not in rules_md:
                    errs.append(f"{e['id']}: 写作规则 config/script_chat_rules.md 里找不到 **{lab}**")
    return errs


# ---------------------------------------------------------------------------------------------- 生成
LEDGER_ID_RE = re.compile(r"(?<![A-Za-z0-9-])K-(?:[A-Z]{2,4})-[A-Z]?\d{2,3}(?!\d)")


def ledger_check(rules: list[dict], root: Path = ROOT) -> list[str]:
    """knowledge/RSI_LEDGER.md：每个尝试引用的规则 id 必须存在；每行结论列要有 ✅ / ❌ / ⏳ / ◐"""
    p = root / "knowledge" / "RSI_LEDGER.md"
    if not p.exists():
        return []
    ids = {e["id"] for e in rules} | archived_ids(root)
    errs = []
    for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        if not line.startswith("| ") or line.startswith("| #") or line.startswith("|---"):
            continue
        for rid in LEDGER_ID_RE.findall(line):
            if rid not in ids:
                errs.append(f"RSI_LEDGER.md 第 {n} 行引用的规则 {rid} 不存在")
        if not any(m in line for m in ("✅", "❌", "⏳", "◐")):
            errs.append(f"RSI_LEDGER.md 第 {n} 行缺结论（✅/❌/⏳/◐）")
    return errs


def scene_alias_check(root: Path = ROOT) -> list[str]:
    """config/scene_aliases.json：剧本场景库每个 id 都登记；assets/scenes 每个目录都出现；asset_dir 指向存在的目录"""
    p = root / "config" / "scene_aliases.json"
    if not p.exists():
        return []
    d = json.loads(p.read_text(encoding="utf-8"))
    scenes, asset_only = d.get("scenes") or {}, d.get("asset_only") or {}
    errs = []
    sj = root / "data" / "import" / "script_v2.json"
    if sj.exists():
        lib = (json.loads(sj.read_text(encoding="utf-8")).get("globals") or {}).get("scene_library") or []
        for e in lib:
            sid = e.get("scene_id")
            if sid and sid not in scenes:
                errs.append(f"scene_aliases.json 没有登记剧本场景 {sid}")
    sd = root / "assets" / "scenes"
    dirs = {x.name for x in sd.iterdir() if x.is_dir()} if sd.is_dir() else set()
    mapped = {v.get("asset_dir") for v in scenes.values() if v.get("asset_dir")}
    for name in sorted(dirs - mapped - set(asset_only)):
        errs.append(f"scene_aliases.json 没有登记资产场景目录 {name}")
    for sid, v in scenes.items():
        ad = v.get("asset_dir")
        if ad and ad not in dirs:
            errs.append(f"scene_aliases.json：{sid} 的 asset_dir {ad} 不存在")
    return errs


def kb_version(rules: list[dict], settings: dict, templates: str) -> str:
    # UIRSI：ui 域规则不进任何生成物（写作 / 审片提示词、loop 规则表），不参与版本号——加界面规则不让下游提示词版本变
    rules = [e for e in rules if e.get("domain") != "ui"]
    raw = json.dumps({"rules": [{k: v for k, v in e.items() if k != "_file"} for e in rules], "settings": settings,
                      "templates": templates}, ensure_ascii=False, sort_keys=True)
    date = max((str(e.get("date")) for e in rules), default="")
    return f"kb-{date.replace('-', '')}-{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:8]}"


def addendum_version(root: Path = ROOT) -> str:
    text = (root / "config" / "script_chat_rules.md").read_text(encoding="utf-8")
    vs = re.findall(r"rules_addendum_version:\s*([A-Za-z0-9_.\-]+)", text)
    return vs[-1] if vs else "无附录"


def gen_loop_rules(rules: list[dict], settings: dict, ver: str) -> str:
    out = {"schema": "nsfs.iterate_rules/1", "kb_version": ver, "settings": settings["loop_settings"],
           "writeback": settings["loop_writeback"], "rules": [], "provenance": {}}
    for e in rules:
        if e["domain"] != "loop":
            continue
        lp = e["loop"]
        r = {"id": lp["rule_id"], "kid": e["id"]}
        for k in ("stage", "spec_rules", "when", "note", "ladder"):
            if lp.get(k) is not None:
                r[k] = lp[k]
        out["rules"].append(r)
        out["provenance"][lp["rule_id"]] = {"kid": e["id"], "src": "; ".join(ev["src"] for ev in e["evidence"]),
                                           "status": e["status"], "date": e["date"]}
    head = f"# {GEN_HEADER}\n# 来源：knowledge/rules/loop.yaml + knowledge/settings.yaml（{ver}）\n"
    return head + yaml.safe_dump(out, allow_unicode=True, sort_keys=False, width=200)


def gen_writer_pack(rules: list[dict], ver: str, root: Path = ROOT) -> str:
    tpl = (KB / "prompts" / "writer" / "pack.md").read_text(encoding="utf-8")
    by: dict[str, list[str]] = {s: [] for s in WRITER_SECTIONS}
    for e in rules:
        if e.get("covered_by") or e.get("status") in ("项目方闸门", "待许可登记"):
            continue
        for t in as_list(e.get("targets")):
            if t.get("kind") == "writer_prompt" and e.get("writer_text"):
                by[t["section"]].append(f"- {e['writer_text'].strip()} [{e['id']}]")
    secs = "\n\n".join(f"## {s}\n" + "\n".join(items) for s, items in by.items() if items)
    body = tpl.replace("{{kb_version}}", ver).replace("{{addendum_version}}", addendum_version(root)) \
              .replace("{{sections}}", secs)
    return f"<!-- {GEN_HEADER} -->\n<!-- writer_knowledge_version: {ver} -->\n" + body


VERDICT_SCHEMA = {
    "shot": "<镜头 id，原样抄输入>",
    "verdict": "pass | fail",
    "scores": {"identity": "0-10", "coherence": "0-10", "detail": "0-10", "motion": "0-10",
               "edit": "0-10（单镜可写 null）", "av_sync": "0-10（无对白写 null）", "color": "0-10"},
    "issues": ["<中文短语，每条一个问题；没有写 []>"],
    "action": "none | reseed | recipe | owner",
    "confidence": "0.0-1.0",
}


def gen_director(rules: list[dict], settings: dict, ver: str) -> str:
    tpl = (KB / "prompts" / "director" / "system.md").read_text(encoding="utf-8")
    by: dict[str, list[str]] = {s: [] for s in DIRECTOR_SECTIONS}
    for e in rules:
        for t in as_list(e.get("targets")):
            if t.get("kind") == "director_prompt" and e.get("director_text"):
                by[t["section"]].append(f"- {e['director_text'].strip()} [{e['id']}]")
    body = (tpl.replace("{{kb_version}}", ver).replace("{{criteria}}", "\n".join(by["判定标准"]))
               .replace("{{scoring}}", "\n".join(by["打分"]))
               .replace("{{min_conf}}", str(settings["director"]["min_confidence_to_act"]))
               .replace("{{schema}}", json.dumps(VERDICT_SCHEMA, ensure_ascii=False, indent=1)))
    return f"<!-- {GEN_HEADER} -->\n<!-- director_prompt_version: {ver} -->\n" + body


def gen_index(rules: list[dict], ver: str) -> str:
    return json.dumps({"kb_version": ver, "n": len(rules),
                       "by_domain": {d: sum(1 for e in rules if e["domain"] == d) for d in DOMAINS},
                       "by_link": _count_links(rules),
                       "rules": [{k: v for k, v in e.items()} for e in rules]}, ensure_ascii=False, indent=1) + "\n"


def _count_links(rules):
    out: dict[str, int] = {}
    for e in rules:
        for ln in as_list(e.get("link")):
            out[ln] = out.get(ln, 0) + 1
    return dict(sorted(out.items()))


def build(root: Path = ROOT) -> tuple[dict[Path, str], list[str], str]:
    rules = load_rules(KB / "rules")
    settings = load_yaml(KB / "settings.yaml")
    errs = validate(rules, root=root)
    if not errs:
        errs += consistency(active(rules), root)
    errs += ledger_check(rules, root)
    errs += scene_alias_check(root)
    templates = "".join(p.read_text(encoding="utf-8") for p in sorted((KB / "prompts").rglob("*.md")))
    ver = kb_version(rules, settings, templates)
    if errs:
        return {}, errs, ver
    g = settings["generated"]
    act = active(rules)
    files = {root / g["loop_rules"]: gen_loop_rules(act, settings, ver),
             root / g["writer_pack"]: gen_writer_pack(act, ver, root),
             root / g["director_prompt"]: gen_director(act, settings, ver),
             root / g["index"]: gen_index(rules, ver)}
    return files, [], ver


def episode_check(ep: int, root: Path = ROOT) -> tuple[str, int]:
    """对一集：Shot Spec → 选配方 → 编译，逐镜核对“计划参数 = 知识库对该配方（含祖先）的目标值”、静态校验、写作缺口。
    → (Markdown 报告, 不一致数)"""
    from ns_recipes import compiler as C
    from ns_recipes import registry as R
    from ns_recipes import spec_import as SI
    from ns_render import pipeline as P
    from ns_schema.shot_spec import missing_fields
    reg = R.load(use_learned=False)
    rules = active(load_rules(KB / "rules"))
    specs = SI.specs_from_import(P.load_script(), ep)
    lines = [f"# ep{ep:02d} 知识库一致性检查（{build(root)[2]}）", "",
             "| 镜 | 配方 | 状态 | 与知识库不一致 | 静态校验 error | 写作缺口（block） |", "|---|---|---|---|---|---|"]
    bad = 0
    for sp in specs:
        plan = C.compile_shot(sp, reg)
        rid = plan["recipe"]["id"]
        chain, cur = [], rid
        while cur:
            chain.append(cur)
            cur = reg.raw[cur].get("extends")
        mism = []
        if plan.get("params"):
            for e in rules:
                for t in as_list(e.get("targets")):
                    if t.get("kind") == "recipe" and t["id"] in chain and (t["id"] == rid or not any(
                            t2.get("kind") == "recipe" and t2["path"] == t["path"] and t2["id"] in chain[:chain.index(t["id"])]
                            for e2 in rules for t2 in as_list(e2.get("targets")))):
                        top = t["path"].split(".")[0]
                        if top in plan["params"]:
                            v = get_path(plan["params"], t["path"])
                            if v is not KeyError and not same(v, t["value"]) and not plan["recipe"]["overlays"]:
                                mism.append(f"{e['id']} {t['path']}")
        errs = [i["code"] for i in plan.get("lint", []) if i["level"] == "error"]
        gaps = sorted({m.rule for m in missing_fields(sp) if m.severity == "block" and m.owner == "writer"})
        bad += len(mism)
        lines.append(f"| {sp.id} | {rid} | {plan['status']} | {'；'.join(mism) or '—'} | {', '.join(errs) or '—'} | "
                     f"{', '.join(gaps) or '—'} |")
    return "\n".join(lines) + "\n", bad


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只校验，生成物与仓库不一致也算失败")
    ap.add_argument("--inbox", action="store_true", help="另外校验 knowledge/inbox/ 草案")
    ap.add_argument("--episode", type=int, help="对这一集做“计划参数 = 知识库”逐镜检查，报告写 knowledge/generated/epNN_check.md")
    a = ap.parse_args(argv)
    if a.episode:
        rep, bad = episode_check(a.episode)
        out = KB / "generated" / f"ep{a.episode:02d}_check.md"
        out.write_text(rep, encoding="utf-8")
        print(rep)
        return 1 if bad else 0
    files, errs, ver = build()
    if a.inbox:
        ib = load_rules(KB / "inbox")
        ie = validate(ib, inbox=True)
        print(f"inbox：{len(ib)} 条草案" + ("，格式问题：\n  " + "\n  ".join(ie) if ie else "，格式 OK"))
    if errs:
        print("知识库校验失败：\n  " + "\n  ".join(errs))
        return 1
    stale = [p for p, txt in files.items() if not p.exists() or p.read_text(encoding="utf-8") != txt]
    if a.check:
        if stale:
            print("生成物过期（先运行 tools/knowledge/compile.py）：" + ", ".join(str(p.relative_to(ROOT)) for p in stale))
            return 1
        print(f"OK {ver}：{len(load_rules(KB / 'rules'))} 条规则，一致性检查通过，生成物最新")
        return 0
    for p, txt in files.items():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(txt, encoding="utf-8")
    print(f"OK {ver}：{len(load_rules(KB / 'rules'))} 条规则 → " + ", ".join(str(p.relative_to(ROOT)) for p in files))
    return 0


if __name__ == "__main__":
    sys.exit(main())
