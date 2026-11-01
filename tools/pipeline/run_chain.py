"""上游链条执行器：P0 提纲 → P1 storyline → P2 单集大纲 → P3 单集剧本 → P4 剧本分镜（CHAINSPEC 2026-10-31）。

每段：组装分段提示词（writer_prompt.build）→ 写作 LLM（config/llm_providers.json 用途 script_write）→ 校验
（chain.yaml 该连接的校验器）→ 不过就带错误重写，最多 chain.yaml settings.writer_max_repair_rounds 轮 → 仍不过就停（needs_writer）。
每次调用记账（data/pipeline/ledger.jsonl：tokens、美元），超预算前停。不写剧情，不改模型输出；只收发和校验。

    .venv/Scripts/python.exe tools/pipeline/run_chain.py --brief <P0.json> --episode 2 --out data/pipeline/runs/<id>
        [--upto P4] [--budget-usd 8] [--budget-tag chainspec-20261031] [--reasoning off|on] [--dry-run]

已有产物（out 目录里的 P1_storyline.json 等且已通过）会被复用，从下一段继续（断点续跑）。
ARCH Autopilot 调用：run_link(link, inputs, out_dir, ...) 或整条 run(...)，返回每段 {status, output_path, report, rounds, usd}。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from chainlib import ROOT, chain, rel
import writer_prompt as WP
from ns_schema import episode_outline as EO
from ns_schema import screenplay as SPM
from ns_schema import storyline as SL
from ns_schema.upstream_common import Report, extract_json

LEDGER = ROOT / chain()["settings"]["budget_ledger"]
FALLBACK_PRICE = {"prompt": 1e-6, "completion": 2e-6}   # chain_audit §0：large-flash $1/M 入、$2/M 出


class BudgetExceeded(RuntimeError):
    pass


def spent(tag: str) -> float:
    if not LEDGER.exists():
        return 0.0
    tot = 0.0
    for ln in LEDGER.read_text(encoding="utf-8").splitlines():
        try:
            d = json.loads(ln)
        except ValueError:
            continue
        if d.get("tag") == tag:
            tot += float(d.get("usd") or 0)
    return tot


def _price(rv: dict) -> dict:
    try:
        from ns_api import llm_config as LC
        return LC.model_pricing(rv["id"]).get(rv["model"]) or FALLBACK_PRICE
    except Exception:  # noqa: BLE001
        return FALLBACK_PRICE


def call_llm(system: str, user_msgs: list[dict], *, max_tokens: int, reasoning: bool, tag: str, budget: float,
             meta: dict) -> dict:
    from ns_api import llm_config as LC
    rv = LC.resolve("script_write", {"params": {"reasoning": reasoning, "max_tokens": max_tokens}})
    pr = _price(rv)
    est_in = (len(system) + sum(len(m["content"]) for m in user_msgs)) // 1.6   # 中文约 1.6 字 / token（上限估计）
    upper = est_in * pr["prompt"] + max_tokens * pr["completion"]
    have = spent(tag)
    if have + upper > budget:
        raise BudgetExceeded(f"预算 {tag}：已花 ${have:.4f}，本次上限 ${upper:.4f}，超过 ${budget}")
    msgs = [{"role": "system", "content": system}] + user_msgs
    t0 = time.time()
    with LC.chat_request(rv, msgs, False, max_tokens) as r:
        data = json.loads(r.read().decode("utf-8"))
    ch = data["choices"][0]
    usage = data.get("usage") or {}
    pt, ct = int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0)
    usd = pt * pr["prompt"] + ct * pr["completion"]
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "tag": tag, "provider": rv["id"], "model": rv["model"],
                            "prompt_tokens": pt, "completion_tokens": ct, "usd": round(usd, 6),
                            "seconds": round(time.time() - t0, 1), **meta}, ensure_ascii=False) + "\n")
    msg = ch.get("message") or {}
    return {"content": msg.get("content") or "", "finish": ch.get("finish_reason"), "usage": usage, "usd": usd,
            "model": rv["model"]}


# ----------------------------------------------------------------------------- 每段的校验
def validate(link: str, out_text: str, ctx: dict) -> tuple[Report, object, str]:
    """→ (合并报告, 解析后的产物, 额外返修原文)"""
    if link == "P0-P1":
        rep = SL.check_storyline(out_text, registry_chars=ctx.get("registry_chars"), registry_scenes=ctx.get("registry_scenes"))
        if rep.obj is not None:
            rep.issues += SL.check_link_p0_p1(ctx["brief"], rep.obj).issues
        return rep, rep.obj, ""
    if link == "P1-P2":
        rep = EO.check_outline(out_text, seconds=tuple(ctx["brief"].seconds_per_episode))
        if rep.obj is not None:
            rep.issues += EO.check_link_p1_p2(ctx["storyline"], rep.obj, ctx.get("prev_outline")).issues
        return rep, rep.obj, ""
    if link == "P2-P3":
        rep = SPM.check_screenplay(out_text, roster=[c.name for c in ctx["storyline"].characters])
        if rep.obj is not None:
            rep.issues += SPM.check_link_p2_p3(ctx["outline"], rep.obj).issues
        return rep, rep.obj, ""
    if link == "P3-P4":
        from p4_adapter import check_p4, repair_text
        body = out_text.strip()
        i = body.find("## ep")
        body = body[i:] if i >= 0 else body
        rep, shots, specs, gate_raw = check_p4(body, ctx["episode"])
        if shots:
            rep.issues += SPM.check_link_p3_p4(ctx["screenplay"], shots).issues
        rep.obj = body
        ctx["_p4_specs"] = len(specs)
        # K-WRT-206：H3-X1 / X3 / X4 换成“镜N 逐字插入 / 删除哪个系统预拼片段”，P4-SPEC 带镜号——放在最前，确定性优先
        import p4_fragments as PF
        chars = list(ctx["storyline"].characters) if ctx.get("storyline") is not None else []
        frag = PF.repair_lines(gate_raw, body, chars, ctx.get("looks")) + PF.spec_lines([i.as_dict() for i in rep.issues])
        if ctx.get("screenplay") is not None and not rep.ok:
            sp = ctx["screenplay"]
            frag += PF.speech_lines(body, sp.speech("dialogue"), sp.speech("voiceover"))
        return rep, body, "\n".join(frag) + ("\n\n" if frag else "") + repair_text(gate_raw)
    raise KeyError(link)


STAGES = [("P0-P1", "P1_storyline.json"), ("P1-P2", "P2_ep{ep:02d}_outline.json"), ("P2-P3", "P3_ep{ep:02d}_screenplay.json"),
          ("P3-P4", "P4_ep{ep:02d}.md")]


def run_link(link: str, ctx: dict, out_dir: Path, *, tag: str, budget: float, reasoning: bool, dry: bool = False) -> dict:
    lk = chain()["links"][link]
    kind = lk["writer"]["output"]
    max_rounds = int(chain()["settings"]["writer_max_repair_rounds"])
    pr = WP.build(link, ctx)
    name = dict(STAGES)[link].format(ep=ctx["episode"])
    (out_dir / "prompts").mkdir(parents=True, exist_ok=True)
    (out_dir / "prompts" / f"{link}.system.md").write_text(pr["system"], encoding="utf-8")
    (out_dir / "prompts" / f"{link}.user.md").write_text(pr["user"], encoding="utf-8")
    if dry:
        return {"link": link, "status": "dry_run", "system_chars": len(pr["system"]), "user_chars": len(pr["user"])}
    msgs = [{"role": "user", "content": pr["user"]}]
    usd, hist = 0.0, []
    ver = None
    if link == "P3-P4":   # 写稿时的规则版本（ARCH spec_import.stamp；导入时按稿件章记录，不拿导入时配置冒充）
        from ns_recipes.spec_import import rules_version
        ver = rules_version()
    for rnd in range(max_rounds + 1):
        res = call_llm(pr["system"], msgs, max_tokens=int(lk["writer"]["max_tokens"]), reasoning=reasoning, tag=tag,
                       budget=budget, meta={"link": link, "round": rnd, "run": out_dir.name})
        usd += res["usd"]
        (out_dir / "raw").mkdir(exist_ok=True)
        (out_dir / "raw" / f"{link}.r{rnd}.txt").write_text(res["content"], encoding="utf-8")
        rep, obj, extra = validate(link, res["content"], ctx)
        hist.append({"round": rnd, "blocking": rep.as_dict()["blocking"], "warnings": rep.as_dict()["warnings"],
                     "finish": res["finish"], "usage": res["usage"], "usd": round(res["usd"], 6),
                     "rules": sorted({i.rule for i in rep.issues if i.level == "block"})})
        if rep.ok:
            break
        msgs += [{"role": "assistant", "content": res["content"]},
                 {"role": "user", "content": WP.repair_message([i.as_dict() for i in rep.issues], kind, extra[:6000])}]
    system_fix: list[str] = []
    if link == "P3-P4" and not rep.ok and isinstance(obj, str):
        # K-WRT-209：写作模型返修用完仍不过 → 系统自有片段 / 枚举槽位的确定性补全（预拼锚点片段、造型切换镜号、配乐避让），
        # 只在补全后 block 变少时采用；台词、画面描述不动；改动记录进报告
        import p4_fragments as PF
        chars = list(ctx["storyline"].characters) if ctx.get("storyline") is not None else []
        fixed, system_fix = PF.auto_fix(obj, ctx["episode"], chars, ctx.get("looks"))
        if system_fix:
            rep2, obj2, _ = validate(link, fixed, ctx)
            if rep2.as_dict()["blocking"] < rep.as_dict()["blocking"]:
                rep, obj = rep2, obj2
                obj = "<!-- system-fix (p4_fragments.auto_fix): " + "；".join(system_fix) + " -->\n" + obj
            else:
                system_fix = []
    status = "ok" if rep.ok else "needs_writer"
    path = out_dir / name
    if obj is not None:
        if kind == "json":
            path.write_text(json.dumps(obj.model_dump(mode="json", by_alias=True), ensure_ascii=False, indent=1), encoding="utf-8")
        else:
            from ns_recipes.spec_import import stamp
            path.write_text(stamp(obj, ver), encoding="utf-8")
    (out_dir / f"{name}.report.json").write_text(json.dumps({"link": link, "status": status, "rounds": hist,
                                                             "report": rep.as_dict(), "system_fix": system_fix},
                                                            ensure_ascii=False, indent=1),
                                                 encoding="utf-8")
    return {"link": link, "status": status, "output": rel(path) if obj is not None else None, "rounds": len(hist),
            "usd": round(usd, 6), "blocking": rep.as_dict()["blocking"], "warnings": rep.as_dict()["warnings"],
            "history": hist, "obj": obj}


def _load_ok(path: Path, link: str, ctx: dict):
    """断点续跑：已有产物重新过校验，通过才复用"""
    if not path.exists():
        return None
    rep, obj, _ = validate(link, path.read_text(encoding="utf-8"), ctx)
    return obj if rep.ok else None


def run(brief_path: Path, episode: int, out_dir: Path, *, upto: str = "P4", tag: str, budget: float,
        reasoning: bool = False, dry: bool = False) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    brep = SL.check_brief(json.loads(Path(brief_path).read_text(encoding="utf-8")))
    if not brep.ok:
        return {"status": "bad_brief", "report": brep.as_dict()}
    brief = brep.obj
    (out_dir / "P0_brief.json").write_text(json.dumps(brief.model_dump(mode="json", by_alias=True), ensure_ascii=False, indent=1),
                                           encoding="utf-8")
    try:
        from ns_api import script_chat as SC
        rc, rs, _ = SC.registry_tables({"from": brief.registry_from})
    except Exception:  # noqa: BLE001
        rc, rs = [], []
    ctx = {"brief": brief, "episode": episode, "registry_chars": rc, "registry_scenes": rs}
    results = []
    order = [s for s, _ in STAGES]
    last = {"P1": "P0-P1", "P2": "P1-P2", "P3": "P2-P3", "P4": "P3-P4"}[upto]
    key = {"P0-P1": "storyline", "P1-P2": "outline", "P2-P3": "screenplay", "P3-P4": "p4"}
    for link in order[: order.index(last) + 1]:
        name = dict(STAGES)[link].format(ep=episode)
        obj = None if dry else _load_ok(out_dir / name, link, ctx)
        if obj is not None:
            results.append({"link": link, "status": "reused", "output": rel(out_dir / name)})
        else:
            try:
                r = run_link(link, ctx, out_dir, tag=tag, budget=budget, reasoning=reasoning, dry=dry)
            except BudgetExceeded as e:
                results.append({"link": link, "status": "budget_stop", "error": str(e)})
                break
            obj = r.pop("obj", None)
            results.append(r)
            if r["status"] != "ok":
                break
        ctx[key[link]] = obj
    summary = {"run": out_dir.name, "brief": rel(brief_path), "episode": episode, "spent_tag_usd": round(spent(tag), 6),
               "stages": results}
    (out_dir / "run.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    return summary


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="上游链条 P0→P4（写作 LLM + 校验 + 返修 ≤2 轮）")
    ap.add_argument("--brief", required=True)
    ap.add_argument("--episode", type=int, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--upto", default="P4", choices=["P1", "P2", "P3", "P4"])
    ap.add_argument("--budget-usd", type=float, default=8.0)
    ap.add_argument("--budget-tag", default="chainspec-" + time.strftime("%Y%m%d"))
    ap.add_argument("--reasoning", default="off", choices=["on", "off"])
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    out = Path(a.out) if Path(a.out).is_absolute() else ROOT / a.out
    s = run(Path(a.brief), a.episode, out, upto=a.upto, tag=a.budget_tag, budget=a.budget_usd,
            reasoning=a.reasoning == "on", dry=a.dry_run)
    print(json.dumps(s, ensure_ascii=False, indent=1))
    return 0 if all(x.get("status") in ("ok", "reused", "dry_run") for x in s.get("stages", [])) else 1


if __name__ == "__main__":
    raise SystemExit(main())
