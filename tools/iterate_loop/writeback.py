"""写回：把被证实有效的参数调整写进配方叠加层（config/recipes/learned.yaml，带证据与 provenance），
状态升级时同步追加到 docs/ep02_iter/LEARNED_SPECS.md「D. 自动迭代写回」；每版写 docs/ep02_iter/vN_review.md
和给剪辑导演 agent 的接触印样 + 问题清单（vN_director_queue.md）。

证据规则（rules.yaml writeback）：一次“调整”= (触发时的配方, 参数路径, 值)。调整后下一次审片里触发它的规则不再命中 = 成功。
成功 ≥ suggest_after → 建议；≥ confirm_after 且成功率 ≥ confirm_rate → 确认（只有“确认”会被配方加载时应用）。
换种子 / 换配方不是参数，只记阶梯统计（ladder_stats），不写回配方。
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from store import now

ROOT = Path(__file__).resolve().parents[2]
LEARNED = ROOT / "config" / "recipes" / "learned.yaml"
SPECS_MD = ROOT / "docs" / "ep02_iter" / "LEARNED_SPECS.md"
DOC_DIR = ROOT / "docs" / "ep02_iter"
SECTION = "## D. 自动迭代写回（tools/iterate_loop，自动维护）"


def _load(path: Path) -> dict:
    if path.exists():
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {}


def _dump(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text("# 自动迭代 Loop 写回的配方参数（tools/iterate_loop/writeback.py 维护；只有 status: 确认 的条目会被\n"
                   "# services/recipes/ns_recipes/registry.py 应用到配方）。人工改 status 也有效（改成 待验 = 撤回）。\n"
                   + yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    tmp.replace(path)


def record(effects: list[dict], cfg: dict, *, learned_path: Path = LEARNED, specs_md: Path = SPECS_MD,
           dry_run: bool = False) -> list[dict]:
    """effects: [{recipe, kind: param|ladder, path?, value?, rule, ok, shot, run, version, before, after, plans}]
    → 状态有变化的条目"""
    data = _load(learned_path)
    data.setdefault("schema", "nsfs.recipe_learned/1")
    entries = {e["key"]: e for e in data.get("entries") or []}
    stats = data.setdefault("ladder_stats", {})
    changed = []
    for ef in effects:
        if ef["kind"] == "ladder":
            k = f"{ef['rule']}|{ef['action']}"
            st = stats.setdefault(k, {"ok": 0, "n": 0})
            st["n"] += 1
            st["ok"] += int(bool(ef["ok"]))
            continue
        key = f"{ef['recipe']}|{ef['path']}|{json.dumps(ef['value'], ensure_ascii=False, sort_keys=True)}"
        e = entries.setdefault(key, {"key": key, "recipe": ef["recipe"], "path": ef["path"], "value": ef["value"],
                                     "status": "待验", "first_seen": now(), "evidence": []})
        e["evidence"].append({k: ef.get(k) for k in ("run", "version", "shot", "rule", "ok", "before", "after", "plans")}
                             | {"date": now()})
        n_ok = sum(1 for x in e["evidence"] if x["ok"])
        n = len(e["evidence"])
        old = e["status"]
        wb = cfg.get("writeback", {})
        # 留出复核（ITERAUDIT 2026-11-01）：前 suggest_after 条证据所在的镜 = “学到它的镜”；自动“确认”还要求在
        # 这些镜以外的镜上至少 holdout_min 条证据、成功率同样 ≥ confirm_rate——同一镜反复成功不算泛化。
        k_train, rate = wb.get("suggest_after", 3), wb.get("confirm_rate", 0.8)
        train = {x.get("shot") for x in e["evidence"][:k_train]}
        ho = [x for x in e["evidence"][k_train:] if x.get("shot") not in train]
        ho_ok = sum(1 for x in ho if x["ok"])
        e["holdout"] = {"n": len(ho), "ok": ho_ok, "train_shots": sorted(str(t) for t in train)}
        ho_pass = len(ho) >= wb.get("holdout_min", 2) and ho_ok / len(ho) >= rate
        if old != "确认":
            if n_ok >= wb.get("confirm_after", 5) and n_ok / n >= rate and ho_pass:
                e["status"] = "确认"
            elif n_ok >= wb.get("suggest_after", 3):
                e["status"] = "建议"
        e["updated"] = now()
        e["n_ok"], e["n"] = n_ok, n
        if e["status"] != old:
            changed.append(dict(e))
    data["entries"] = list(entries.values())
    if not dry_run:
        _dump(learned_path, data)
        if changed:
            append_specs(changed, specs_md)
    return changed


def append_specs(changed: list[dict], specs_md: Path = SPECS_MD) -> None:
    """追加到 D 节末尾（D 节是文件最后一节；不存在就新建）"""
    text = (specs_md.read_text(encoding="utf-8") if specs_md.exists() else "# LEARNED_SPECS\n").rstrip("\n") + "\n"
    if SECTION not in text:
        text += (f"\n{SECTION}\n\n状态升级时由 loop 追加一行；参数实际生效以 config/recipes/learned.yaml 为准。\n\n"
                 "| 配方 | 参数 | 值 | 证据（成功/次数） | 日期 | 状态 |\n|---|---|---|---|---|---|\n")
    text += "".join(f"| {e['recipe']} | {e['path']} | {json.dumps(e['value'], ensure_ascii=False)} | "
                    f"{e['n_ok']}/{e['n']} | {e['updated'][:10]} | {e['status']} |\n" for e in changed)
    specs_md.write_text(text, encoding="utf-8")


def version_review(state: dict, ep_review: dict | None, out: Path) -> Path:
    v = state["version"]
    lines = [f"# ep{state['episode']:02d} v{v} 自动迭代审片（iterate_loop，{now()}）", "",
             f"- run：`{state['run_id']}`；dry-run：{state.get('dry_run')}；配方注册表 `{state.get('registry_hash', '')[:12]}`",
             f"- 合成：{state['versions'].get(str(v), {}).get('assembled') or '（未合成）'}",
             "- 只评技术与剪辑；主观观感交剪辑导演 agent（见 vN_director_queue.md）。", "",
             "## 逐镜结果", "",
             "| 镜 | 状态 | 配方 | 出片次数 | 最后计划 | 未过的指标 | 触发规则 → 动作 |", "|---|---|---|---|---|---|---|"]
    for sid, sh in state["shots"].items():
        hist = "；".join(f"{a['rule']}→{a['action']}" for a in sh.get("actions", []))
        fails = "，".join(f"{f['metric']} {f['value']}≥/<{f['threshold']}" for f in sh.get("last_failures", []))
        lines.append(f"| {sid} | {sh['status']} | {sh.get('recipe')} | {sh.get('renders', 0)} | "
                     f"`{(sh.get('plan_hash') or '')[:10]}` | {fails or '—'} | {hist or '—'} |")
    pend = [sid for sid, sh in state["shots"].items() if sh["status"] in ("owner", "needs_keyframe")]
    wr = [sid for sid, sh in state["shots"].items() if sh["status"] == "needs_writer"]
    api = [sid for sid, sh in state["shots"].items() if sh["status"] == "needs_api"]
    lines += ["", "## 待处理", "",
              f"- 待项目方：{pend or '无'}",
              f"- 交写作方（格式 / 溢出）：{wr or '无'}",
              f"- 等 API 接入点（Ref2VA / 两段式等）：{api or '无'}", ""]
    if ep_review:
        lines += ["## 整集机器预评分（review.py episode）", "", "```",
                  json.dumps(ep_review.get("auto_scores", {}), ensure_ascii=False, indent=1), "```", ""]
    lines += ["## 本版写回", ""]
    for e in state["versions"].get(str(v), {}).get("writeback", []):
        lines.append(f"- {e['recipe']} `{e['path']}` = {json.dumps(e['value'], ensure_ascii=False)} → {e['status']}（{e['n_ok']}/{e['n']}）")
    if not state["versions"].get(str(v), {}).get("writeback"):
        lines.append("- 无状态变化")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def director_queue(state: dict, out: Path) -> Path:
    """给剪辑导演 agent：每镜接触印样 + 机器标记 + 需要人眼判断的问题；结论写回 data/iterate_loop/<run>/director/verdicts.json"""
    v = state["version"]
    lines = [f"# ep{state['episode']:02d} v{v} 剪辑导演审片队列", "",
             "机器指标量不准的项交人眼：鬼影 / 多肢 / 手指融合、表演是否自然、景别与节奏、结尾是否“落定”。只评技术与剪辑。",
             f"结论写入 `data/iterate_loop/{state['run_id']}/director/verdicts.json`，格式：",
             "```json", '{"ep02-S1": {"verdict": "pass|fail", "issues": ["鬼影"], "action": "reseed|owner|none", "note": "…"}}',
             "```", "Loop 下一个 tick 读入：fail + action=reseed → 按 R-DIRECTOR 重出（计入 3 次上限）；owner → 待项目方。", "",
             "| 镜 | 状态 | 接触印样 | 机器标记 | 请看 |", "|---|---|---|---|---|"]
    for sid, sh in state["shots"].items():
        if sh["status"] not in ("passed", "owner"):
            continue
        ask = "腿 / 手是否叠影；动作是否像实时" if "walk" in (sh.get("recipe") or "") else \
              ("说话人嘴型与声音；另一人是否乱动嘴" if "dialogue" in (sh.get("recipe") or "") or "two_person" in (sh.get("recipe") or "")
               else "是否静止 / 结尾定住；脸部细节")
        lines.append(f"| {sid} | {sh['status']} | `{sh.get('sheet') or '—'}` | {'；'.join(sh.get('flags', [])) or '—'} | {ask} |")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out
