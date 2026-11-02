"""HOLLYWOOD r9（L-109）：写作后端 claude_agent——不调任何写作 / 评审 API，出任务包、收产物、跑代码判定和闸门。

项目方 11-02 03:3x 原话：“Claude后面写剧本还是你来写，用那个API太贵了，测试阶段都是用你的，之后上线再用外面的API”；
“写剧本你可以用fable5.1来写”。后端开关：config/llm_providers.json writer_backend（claude_agent | api，默认 claude_agent）。
接口说明：docs/hollywood/writer_agent_interface.md。写手（SCRIPTWRITER）只做 role=writer 的包，评审 agent 只做 role=reviewer 的包。

状态机（每调用一次推进到下一个要人写的地方就停，写 awaiting）：
  P1→P4   每段：正式文件已通过 → 复用；writer_out/<step>_a<k>.<ext> 带 .done → 用 run_chain.validate 校验，过了落正式文件
          （与 API 模式同名同格式），没过 → 返修包（attempt+1，带校验器的问题原文）；都没有 → 出包。
  事实表  reviewer 包 facts_epNN（任务 A）。
  补丁    writer 包 patch_epNN_K（P4 阻断 + 代码判定失败 + 事实偏差，每次 1–2 条），产物回来后代码不变量（说话人顺序 / 集头 / 镜数时长 /
          lint 不变差 / HW-F1）过、失败项变少才采用；包里记稿的 sha，稿变了旧包作废重出。
  核对    reviewer 包 factcheck_epNN_K（任务 B，整集）；有偏差（服装除外，K-WRT-H10）→ 回到补丁。
  决定    代码判定 0 + P4 阻断 0 + 事实核对 0 偏差 → importable（测试期打分只用代码判定 27 条）→ rubric 闸门 + validate。
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

import importlib.util

ROOT = Path(__file__).resolve().parents[2]


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


AF = _load("autoflow", "tools/script_rsi/autoflow.py")
R5, H, RL = AF.R5, AF.H, AF.RL
WT, WO = "writer_tasks", "writer_out"
PATCH_MAX = 10
CONTENT_RULES = ("全部人物成年（≥22 岁）、一切亲密情节双方自愿、人物均为虚构。暧昧和张力可以写；露骨的性描写不写。"
                 "亲密镜写成占位：该镜的 img / motion / H3 只写非露骨的画面（构图、视线、手、呼吸、环境），并在镜头块里加一行 "
                 "`**H3校验**：本地生成（亲密镜占位）`——这类镜头的画面只在本地生成。不改第一季已定的剧情事实和人物设定（身份、名字、年龄、"
                 "发色发型、脸、5 厘米透明水晶甲、人物关系、已发生剧情）；每集服装 / 造型不是事实，以本集造型行为准（K-WRT-H10）。缺信息标“未提供”。")
EXT = {"json": "json", "markdown_episode": "md", "patches_json": "json", "facts_json": "json", "factcheck_json": "json"}


SCORE_DIRTY = "line3_dirty.json"     # 稿子变了 → 要重打线 3 分；编排器 tick 看到就跑 line3_score 再删掉（总调度：自动打分，不要人工接力）


def mark_dirty(run_dir: Path, ep: int, why: str) -> None:
    p = run_dir / SCORE_DIRTY
    try:
        d = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except (OSError, ValueError):     # 标记文件坏了：重写一份（宁可多打一次分），不吞掉这次变化
        d = {}
    d.setdefault("episodes", {})[str(ep)] = {"why": why, "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    d["cmd"] = f".venv/Scripts/python.exe tools/script_rsi/line3_score.py --run-dir {H.RC._rel(run_dir)}"
    AF.write_json(p, d)


def backend() -> str:
    try:
        return json.loads((ROOT / "config/llm_providers.json").read_text(encoding="utf-8")).get("writer_backend") or "claude_agent"
    except (OSError, ValueError) as e:                       # 读不到配置 = 不能确定能不能花钱 → 按不花钱的 claude_agent
        print(f"writer_backend 读不到（{e!r}），按 claude_agent")
        return "claude_agent"


def _sha(t: str) -> str:
    return hashlib.sha256(t.encode("utf-8")).hexdigest()[:16]


def out_path(run_dir: Path, step: str, attempt: int, fmt: str) -> Path:
    return run_dir / WO / f"{step}_a{attempt}.{EXT[fmt]}"


def ready(p: Path) -> str | None:
    """产物 + .done 标记都在才读"""
    done = p.with_name(p.name + ".done")
    return p.read_text(encoding="utf-8") if p.exists() and done.exists() else None


def attempts(run_dir: Path, step: str) -> int:
    return len(list((run_dir / WT).glob(f"{step}_a*.json")))


def packet(run_dir: Path, st, step: str, role: str, ep: int, link: str, system: str, user: str, fmt: str,
           inputs: list[str], attempt: int, extra: dict | None = None) -> dict:
    op = out_path(run_dir, step, attempt, fmt)
    pk = {"schema": "nsfs.writer_task/1", "run": run_dir.name, "step": step, "role": role, "episode": ep, "link": link,
          "system": system + "\n\n========\n\n【内容边界】" + CONTENT_RULES, "user": user, "inputs": inputs,
          "output": {"path": H.RC._rel(op), "format": fmt, "done_marker": H.RC._rel(op) + ".done"},
          "content_rules": CONTENT_RULES, "attempt": attempt, "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "status": "open",
          "advance_cmd": f".venv/Scripts/python.exe tools/script_rsi/autoflow.py run --run-dir {H.RC._rel(run_dir)} --episode {ep} "
                         f"--backend claude_agent --import dry", **(extra or {})}
    AF.write_json(run_dir / WT / f"{step}_a{attempt}.json", pk)
    st.set(awaiting={"step": step, "role": role, "attempt": attempt, "packet": H.RC._rel(run_dir / WT / f"{step}_a{attempt}.json"),
                     "output": pk["output"]["path"]}, verdict="awaiting_" + role,
           next_action=f"等{'写手' if role == 'writer' else '评审'}交 {step}（第 {attempt} 次）")
    return pk


def chain_step(RCH, run_dir: Path, ep: int, st, ctx: dict) -> bool:
    """P1→P4；返回 True = 四段都齐（可进后处理），False = 在等写手"""
    key = {"P0-P1": "storyline", "P1-P2": "outline", "P2-P3": "screenplay", "P3-P4": "p4"}
    for link, node, name in AF.LINKS:
        canon = run_dir / dict(RCH.STAGES)[link].format(ep=ep)
        obj = RCH._load_ok(canon, link, ctx)
        rep_p = canon.parent / f"{canon.name}.report.json"
        if obj is None and link == "P3-P4" and canon.exists() and rep_p.exists():
            pr_ = json.loads(rep_p.read_text(encoding="utf-8"))
            if pr_.get("status") == "needs_writer" and int((pr_.get("report") or {}).get("blocking") or 99) <= 6:
                t_ = canon.read_text(encoding="utf-8")
                ctx[key[link]] = t_[t_.find("## ep"):] if "## ep" in t_ else t_
                st.stage(node, name, "needs_patch", "code", output=H.RC._rel(canon))
                continue
        if obj is not None:
            st.stage(node, name, "reused", "code", output=H.RC._rel(canon))
            ctx[key[link]] = obj
            continue
        step = "P1" if link == "P0-P1" else f"{node}_ep{ep:02d}"
        kind = RCH.chain()["links"][link]["writer"]["output"]
        fmt = "json" if kind == "json" else "markdown_episode"
        k = attempts(run_dir, step)
        pr = RCH.WP.build(link, ctx)
        if k:
            txt = ready(out_path(run_dir, step, k, fmt))
            if txt is None:
                st.stage(node, name, "awaiting_writer", "api_model", step=step, attempt=k)
                return False
            rep, obj, extra = RCH.validate(link, txt, ctx)
            blocking = rep.as_dict()["blocking"]
            if rep.ok or (link == "P3-P4" and obj is not None and blocking <= 6):
                if kind == "json":
                    AF.write_json(canon, obj.model_dump(mode="json", by_alias=True))
                else:
                    from ns_recipes.spec_import import rules_version, stamp
                    canon.write_text(stamp(obj, rules_version()), encoding="utf-8")
                AF.write_json(rep_p, {"link": link, "status": "ok" if rep.ok else "needs_writer", "rounds": [{"round": k, "blocking": blocking}],
                                      "report": rep.as_dict(), "writer": "claude_agent"})
                st.stage(node, name, "ok" if rep.ok else "needs_patch", "api_model", step=step, attempt=k, blocking=blocking,
                         output=H.RC._rel(canon), decider_note="写手 agent（claude_agent）")
                ctx[key[link]] = obj
                continue
            user = pr["user"] + "\n\n" + RCH.WP.repair_message([i.as_dict() for i in rep.issues], kind, (extra or "")[:6000])
            packet(run_dir, st, step, "writer", ep, link, pr["system"], user, fmt, [], k + 1)
            st.stage(node, name, "repair_requested", "code", step=step, attempt=k + 1, blocking=blocking)
            return False
        packet(run_dir, st, step, "writer", ep, link, pr["system"], pr["user"], fmt, [], 1)
        st.stage(node, name, "awaiting_writer", "api_model", step=step, attempt=1)
        return False
    return True


def post_step(run_dir: Path, ep: int, st, import_mode: str) -> dict:
    from ns_api import script_chat as SC
    wd = run_dir / f"work_ep{ep:02d}"
    wd.mkdir(exist_ok=True)
    p4 = (run_dir / f"P4_ep{ep:02d}.md").read_text(encoding="utf-8")
    body = p4[p4.find("## ep"):] if "## ep" in p4 else p4
    header, _ = SC.script_header(registry={})
    pre = header + "\n---\n\n"
    base = body.rstrip() + "\n\n---\n"
    split_p = run_dir / f"P4_ep{ep:02d}.split.md"
    if split_p.exists():
        base = RL.split_doc(split_p.read_text(encoding="utf-8"))[1][0]
    H.ZERO_CODES[:] = ["QW-W11"]
    base_lint = H.lint(base, ep)
    # 事实表（reviewer）
    fpath = run_dir / f"facts_ep{ep:02d}.json"
    if not fpath.exists():
        step = f"facts_ep{ep:02d}"
        k = attempts(run_dir, step)
        txt = ready(out_path(run_dir, step, k, "facts_json")) if k else None
        if txt is None:
            if not k:
                packet(run_dir, st, step, "reviewer", ep, "facts", R5.facts_system(),
                       "【任务 A：抽取事实表】这一集的“原稿”是下面这些上游文件（提纲 / 故事线 / 本集大纲 / 本集剧本），"
                       f"只抽第 {ep} 集会用到的事实。\n\n" + AF.upstream_text(run_dir, ep), "facts_json", [], 1)
            st.stage("facts", "事实表", "awaiting_reviewer", "api_model", step=step)
            return st.d
        d, err = H._json_block(txt)
        if not d or d.get("lines") is None:
            packet(run_dir, st, step, "reviewer", ep, "facts", R5.facts_system(), "上一次的回复不是任务 A 的 JSON：" + (err or "缺 lines"),
                   "facts_json", [], k + 1)
            return st.d
        AF.write_json(fpath, d)
    facts = json.loads(fpath.read_text(encoding="utf-8"))
    st.stage("facts", "事实表", "ok", "api_model", note=H.RC._rel(fpath))
    final_p = run_dir / f"P4_ep{ep:02d}.final.md"
    cur = RL.split_doc(final_p.read_text(encoding="utf-8"))[1][0] if final_p.exists() else base
    ag = st.d.setdefault("agent", {"processed": [], "used": {}, "fact_devs": None})
    fitems = AF.fact_items(ag.get("fact_devs") or [])
    fails = fitems + AF.all_fails(pre, cur, ep, wd)
    # 已回来的补丁先处理
    step_base = f"patch_ep{ep:02d}"
    k = attempts(run_dir, step_base)
    if k and f"{step_base}_a{k}" not in ag["processed"]:
        pk = json.loads((run_dir / WT / f"{step_base}_a{k}.json").read_text(encoding="utf-8"))
        txt = ready(out_path(run_dir, step_base, k, "patches_json"))
        if txt is None:
            st.stage("code", "代码判定 + 补丁", "awaiting_writer", "api_model", fails=len(fails), step=f"{step_base}_a{k}")
            return st.d
        ag["processed"].append(f"{step_base}_a{k}")
        note = ""
        if pk.get("base_sha") != _sha(cur):
            note = "稿在出包之后变了，这个补丁作废"
        else:
            d_, err = H._json_block(txt)
            c, changed, err2 = R5.apply_patches(cur, (d_ or {}).get("patches") or [], R5.numbered_lines(cur)) if d_ else (None, [], err)
            if c is None:
                note = err2 or err
            else:
                c = H.mech_align_all(pre, c, ep, wd)
                g = R5.gate5(pre, base, c, ep, base_lint, wd)
                hard = [x for x in g["checks"] if not x["ok"] and x["id"] != "I7"]
                if hard:
                    note = "；".join(f"{x['id']} {x['name']} 不满足：{x['detail']}" for x in hard)[:1200]
                elif any(t.startswith("narr#") for t in pk.get("targets", [])):
                    # 叙事补丁（N05 结尾类型）：代码判定的结尾类型落在允许集合里、失败项不变多才采用；采用后整集事实重核
                    got = ending_of(pre + c, ep)
                    f2 = fitems + AF.all_fails(pre, c, ep, wd)
                    allowed = pk.get("narrative_allowed") or []
                    if got not in allowed:
                        note = f"补丁后结尾类型代码判为 {got}，要的是 {' / '.join(allowed)}"
                    elif len(f2) > len(fails):
                        note = f"补丁后失败项变多（{len(fails)} → {len(f2)}）"
                    else:
                        cur, fails = c, f2
                        final_p.write_text(pre + cur, encoding="utf-8")
                        ag["fact_devs"] = None
                else:
                    tg_fact = any(t.startswith("fact#") for t in pk.get("targets", []))
                    keep_f = [] if tg_fact else fitems           # 修事实偏差的补丁：偏差先清掉，等下一次整集核对确认
                    f2 = keep_f + AF.all_fails(pre, c, ep, wd)
                    if len(f2) < len(fails) or (tg_fact and len(f2) <= len(fails)):
                        cur, fails = c, f2
                        final_p.write_text(pre + cur, encoding="utf-8")
                        if tg_fact or ag.get("fact_devs") == []:
                            # 修事实偏差的补丁，或已核对通过（0 偏差）的稿被补丁改了：作废旧核对，失败项清零后整集重核（剧情事实不变要有核对兜底）
                            ag["fact_devs"] = None
                    else:
                        note = f"补丁后失败项没有变少（{len(fails)} → {len(f2)}）"
        st.d.setdefault("agent_history", []).append({"step": f"{step_base}_a{k}", "accepted": not note, "note": note[:300], "fails": len(fails)})
        st.save()
        if note:
            ag["last_note"] = note
    if not final_p.exists():
        final_p.write_text(pre + cur, encoding="utf-8")
    code_n = len([f for f in fails if f[0] not in ("p4", "fact")])
    st.set(rubric_code_fail={"n": code_n, "ids": [f"{d}#{u['id']}" for d, u in fails if d not in ("p4", "fact")]}, ruler_sigma=None)
    met = 27 - code_n
    st.stage("code", "代码判定 + 补丁", "running" if fails else "ok", "code", fails=len(fails),
             detail=[f"{d}#{u['id']} {u['why'][:120]}" for d, u in fails])
    # 还有失败项 → 出下一个补丁包
    if fails:
        # 之前判过“可导入”的集被新闸门项（如 K-WRT-H13 可拍性）打回：DISTILL 契约里的候选清空，状态退回“待修”
        AF.write_json(run_dir / "hollywood" / f"ep{ep:02d}.json", {
            "candidates": [], "code_fails": code_n, "fails": [f"{d}#{u['id']}" for d, u in fails], "spent_usd": float(st.d.get("usd_total") or 0),
            "rounds_left": 0, "staged_path": None, "sha256": None, "writer_backend": "claude_agent", "status": "待修"})
        for sid in ("gate", "import", "decide"):
            if any(x["id"] == sid for x in st.d.get("stages", [])):
                st.stage(sid, {"gate": "导入闸门", "import": "导入", "decide": "导入决定"}[sid], "reopened", "code", detail="有新失败项，退回待修")
        if k >= PATCH_MAX:
            st.set(verdict="not_importable", next_action=f"补丁已出 {k} 次仍有失败项，交总调度")
            return st.d
        targets = [(d, u) for d, u in fails if ag["used"].get(f"{d}#{u['id']}", 0) < AF.ITEM_TRIES and f"{d}#{u['id']}" not in AF.STRUCTURAL][:2]
        if not targets:
            st.set(verdict="not_importable", next_action="剩下的失败项都已试满（或是镜数这类结构项），交总调度 / 整集重写 P4")
            return st.d
        for d, u in targets:
            ag["used"][f"{d}#{u['id']}"] = ag["used"].get(f"{d}#{u['id']}", 0) + 1
        user = AF.patch_user(ep, pre, cur, facts, targets, ag.pop("last_note", ""))
        packet(run_dir, st, step_base, "writer", ep, "patch", R5.r5_writer_system(), user, "patches_json", [H.RC._rel(final_p)], k + 1,
               {"base_sha": _sha(cur), "targets": [f"{d}#{u['id']}" for d, u in targets]})
        return st.d
    # 失败项清零 → 整集事实核对（reviewer）
    if ag.get("fact_devs") is None:
        step = f"factcheck_ep{ep:02d}"
        kk = attempts(run_dir, step)
        prev = json.loads((run_dir / WT / f"{step}_a{kk}.json").read_text(encoding="utf-8")) if kk else {}
        txt = ready(out_path(run_dir, step, kk, "factcheck_json")) if kk else None
        if kk and prev.get("base_sha") == _sha(cur) and txt is not None:
            d, err = H._json_block(txt)
            if d is not None and "deviations" in d:
                ag["fact_devs"] = R5.drop_wardrobe(d.get("deviations") or [])
                st.save()
                if ag["fact_devs"]:
                    st.stage("factcheck", "事实核对", "deviation", "api_model", deviations=ag["fact_devs"][:6])
                    return post_step(run_dir, ep, st, import_mode)        # 偏差 → 进补丁
            else:
                packet(run_dir, st, step, "reviewer", ep, "factcheck", R5.facts_system(), "上一次的回复不是任务 B 的 JSON：" + str(err),
                       "factcheck_json", [], kk + 1, {"base_sha": _sha(cur)})
                return st.d
        elif not (kk and prev.get("base_sha") == _sha(cur)):
            packet(run_dir, st, step, "reviewer", ep, "factcheck", R5.facts_system(),
                   f"【任务 B：核对改写稿】\n【事实表】\n{json.dumps(facts, ensure_ascii=False, indent=1)}\n\n【ep{ep:02d} 改写稿】\n{H.shots_text(cur)}",
                   "factcheck_json", [H.RC._rel(final_p)], kk + 1, {"base_sha": _sha(cur)})
            st.stage("factcheck", "事实核对", "awaiting_reviewer", "api_model", step=step)
            return st.d
        else:
            st.stage("factcheck", "事实核对", "awaiting_reviewer", "api_model", step=f"{step}_a{kk}")
            return st.d
    st.stage("factcheck", "事实核对", "ok", "api_model", deviations=[])
    st.d["score_trajectory"].append({"at": time.strftime("%F %T"), "sum_code": met, "of": 27, "note": "测试期只用代码判定（L-109）"})
    st.stage("score", "打分（测试期：代码判定）", "ok", "code", sum_code=met)
    lint_now = H.lint(cur, ep)
    if lint_now["shot_block"]:
        st.set(verdict="not_importable", next_action="P4 阻断未清零")
        return st.d
    RA = _load("rubric_audit", "tools/script_rsi/rubric_audit.py")
    rg = RA.gate(final_p)
    v = AF.FR.validate_json(final_p)
    gate_ok = rg["ok"] and not v.get("blocking")
    st.stage("gate", "导入闸门", "ok" if gate_ok else "blocked", "code", rubric_ok=rg["ok"], validate_blocking=v.get("blocking"))
    sha = hashlib.sha256(final_p.read_bytes()).hexdigest()
    AF.write_json(run_dir / "hollywood" / f"ep{ep:02d}.json", {
        "candidates": [{"name": "final", "score": met, "score_basis": "code_only_27", "invariants_pass": True, "p4_block_zero": True,
                        "fact_check_zero": True, "path": H.RC._rel(final_p), "sha256": sha}] if gate_ok else [],
        "code_fails": code_n, "spent_usd": float(st.d.get("usd_total") or 0), "rounds_left": 0,
        "staged_path": H.RC._rel(final_p) if gate_ok else None, "sha256": sha if gate_ok else None, "writer_backend": "claude_agent"})
    if not gate_ok:
        st.set(verdict="blocked_by_gate", next_action="一键返修")
        return st.d
    mark_dirty(run_dir, ep, "过导入闸门")
    re_ = reimport(run_dir, ep, final_p, sha, st)
    if re_ is not None:                  # 这一季已经导入过（项目方闸门过过一次）→ 补丁后的新稿自动覆盖导入（总调度 11-02）
        st.stage("import", "导入", "reimported" if re_.get("ok") else "reimport_failed", "code", **{k: v_ for k, v_ in re_.items() if k != "ok"})
        st.set(verdict="imported" if re_.get("ok") else "import_failed", awaiting=None,
               next_action="已用新稿覆盖导入；改了提示词的镜由下游按作业签名重置（K-OPS-E09）" if re_.get("ok") else "重新导入失败，看 stages.import")
        return st.d
    st.stage("import", "导入", "dry_run_ok" if import_mode == "dry" else "awaiting_owner", "code" if import_mode == "dry" else "owner")
    st.set(verdict="importable", awaiting=None, next_action="项目方点“导入”（导入目标待 import-staged --run）")
    return st.d


def _imported_shots(run: str, ep: int) -> dict | None:
    """这一季导入稿（data/import/runs/<run>/script_v2.json）里第 ep 集每镜的 {镜号: 提示词签名}；没导入过 = None"""
    import sys
    sys.path.insert(0, str(ROOT / "tools" / "autopilot"))
    import runs as RN
    p = RN.import_path(run, ROOT)
    if not p.exists():
        return None
    d = json.loads(p.read_text(encoding="utf-8"))
    eps = d.get("episodes") or (d.get("script") or {}).get("episodes") or []
    e = next((x for x in eps if int(x.get("number") or 0) == ep), None)
    if e is None:
        return {}
    return {int(s.get("index")): _sha(json.dumps([s.get("img_prompt"), s.get("motion_prompt"), s.get("h3_prompt"), s.get("cast_raw")],
                                                  ensure_ascii=False)) for s in e.get("shots") or []}


def reimport(run_dir: Path, ep: int, final_p: Path, sha: str, st) -> dict | None:
    """补丁过闸 + 事实核对通过后：这一季已经导入过（导入稿存在）且这一集的新稿和上次导入的不一样 → producer import-staged --run 覆盖
    （同一通道：sha 核对 + rubric 闸门 + validate，按集合并、旧导入稿留备份）。返回 None = 这一季还没导入过（仍走项目方闸门）。
    改了提示词的镜号记在 changed_shots；已出过图的镜由下游按作业签名（K-OPS-E09 job_sig vs ladder_sig）重置，不在这里动作业。"""
    before = _imported_shots(run_dir.name, ep)
    if before is None:
        return None
    if st.d.get("imported_sha") == sha:
        return {"ok": True, "skipped": "这一稿已经导入过", "sha256": sha}
    from ns_agent.importer.script_md import import_script
    e = next((x for x in import_script(final_p).episodes if x.number == ep), None)
    after = {s.index: _sha(json.dumps([s.img_prompt, s.motion_prompt, s.h3_prompt, s.cast_raw], ensure_ascii=False)) for s in (e.shots if e else [])}
    changed = sorted(k for k in after if before.get(k) != after[k])
    if before and not changed and set(before) == set(after):    # 导入稿里这一集和新稿逐镜一致：不重导
        st.set(imported_sha=sha, reimport_changed_shots=[])
        return {"ok": True, "skipped": "导入稿与新稿逐镜一致", "sha256": sha, "changed_shots": []}
    import subprocess
    r = subprocess.run([sys_exe(), "tools/autopilot/producer.py", "import-staged", "--obj", H.RC._rel(final_p), "--reason", sha,
                        "--run", run_dir.name, "--by", "PRODUCER autoflow", "--note",
                        f"autoflow {run_dir.name} ep{ep:02d} 补丁过闸 + 事实核对 0 偏差，新稿覆盖导入（总调度 11-02）；改了的镜 {changed}"],
                       cwd=ROOT, capture_output=True, timeout=1800, env={**__import__("os").environ, "PYTHONUTF8": "1"})
    out = (r.stdout.decode("utf-8", "replace").strip().splitlines() or [""])[-1]
    ok = r.returncode == 0
    if ok:
        try:                       # IMGMASTER continuity 读的场景定稿导出（K-WRT-H23）；导出失败不影响导入本身，记下原因
            SL = _load("scene_lock", "tools/script_rsi/scene_lock.py")
            st.set(scene_locks=H.RC._rel(SL.export(run_dir, ep)))
        except Exception as e:  # noqa: BLE001
            st.set(scene_locks_error=repr(e)[:200])
        st.set(imported_sha=sha, reimport_changed_shots=changed)
        st.d.setdefault("agent_history", []).append({"step": "reimport", "accepted": True, "note": f"覆盖导入，改了的镜 {changed}"})
        st.save()
    return {"ok": ok, "sha256": sha, "changed_shots": changed, "out": out[:300]}


def sys_exe() -> str:
    import sys
    return sys.executable


def reopen(run_dir: Path, ep: int, why: str, by: str = "HOLLYWOOD") -> dict:
    """补丁预算用尽（某失败项试满 ITEM_TRIES / not_importable）后重开：清零逐项尝试计数，记一条 manual 历史（自动化分如实不计这一集）。
    不动稿、不跳闸门；下一次 run 会照常重算失败项、出补丁包或走事实核对"""
    st = AF.Status(run_dir, ep, 0.0)
    ag = st.d.setdefault("agent", {"processed": [], "used": {}, "fact_devs": None})
    before = dict(ag.get("used") or {})
    ag["used"] = {}
    st.d.setdefault("agent_history", []).append({"step": "reopen", "accepted": True, "manual": True, "by": by,
                                                 "note": f"manual 重开补丁预算：{why}"[:300], "used_before": before})
    st.set(verdict="reopened", next_action="已重开补丁预算，跑 autoflow run 继续")
    st.save()
    return {"ok": True, "used_before": before}


def ending_of(text: str, ep: int) -> str:
    """整份稿（集头 + 镜头区）第 ep 集的结尾类型（N05 代码判定，narrative_code.ending_type）"""
    NC = _load("narrative_code", "tools/script_rsi/narrative_code.py")
    shots, blocks = NC._episode_material(text, ep)
    return NC.ending_type(blocks[-1], shots[-1]) if shots else "other"


def season_types(run_dir: Path) -> dict[int, str]:
    out = {}
    for f in sorted(run_dir.glob("P4_ep[0-9][0-9].final.md")):
        ep = int(f.name[5:7])
        out[ep] = ending_of(f.read_text(encoding="utf-8"), ep)
    return out


def narrative_patch(run_dir: Path, ep: int, want: list[str] | None = None, why: str = "") -> dict:
    """N05 叙事补丁包（总调度 11-02 定：相邻 3 集结尾类型重复的集出补丁，剧情事实不变）。
    want 不给 = 按整季现状算允许的结尾类型（NC.allowed_endings）；给了 = 只收这些类型（如“纯视线”= gaze_out）。
    产物回来走 post_step 的补丁处理：代码判定结尾类型在允许集合里 + 闸门不变量过 + 失败项不变多 → 采用 → 整集事实重核 → 再判可导入"""
    NC = _load("narrative_code", "tools/script_rsi/narrative_code.py")
    from ns_api import script_chat as SC
    final_p = run_dir / f"P4_ep{ep:02d}.final.md"
    if not final_p.exists():
        return {"ok": False, "why": f"{final_p.name} 不存在（这一集还没过补丁环）"}
    header, _ = SC.script_header(registry={})
    pre = header + "\n---\n\n"
    cur = RL.split_doc(final_p.read_text(encoding="utf-8"))[1][0]
    types = season_types(run_dir)
    allowed = list(want) if want else NC.allowed_endings(types, ep)
    bad = [t for t in allowed if t not in NC.ENDING_TYPES]
    if bad or not allowed:
        return {"ok": False, "why": f"结尾类型不认识或没有可选：{bad or allowed}"}
    st = AF.Status(run_dir, ep, 0.0)
    facts = json.loads((run_dir / f"facts_ep{ep:02d}.json").read_text(encoding="utf-8"))
    how = "\n".join(f"  · {t}：{NC.ENDING_HOW[t]}" for t in allowed)
    target = ("narr", {"id": "N05", "why": (
        f"整季结尾类型（代码判定）：{json.dumps(types, ensure_ascii=False)}。本集结尾现在是 {types.get(ep)}，与相邻集重复（N05：相邻 3 集结尾类型不重复）。"
        f"{why}请只改末镜（必要时连带末镜前一镜）的分拍 / 表演节拍 / 下镜 / 最后一句台词的措辞，把结尾改成下面任一类型，剧情事实不变、台词说话人和条数不变：\n{how}")})
    step_base = f"patch_ep{ep:02d}"
    k = attempts(run_dir, step_base)
    ag = st.d.setdefault("agent", {"processed": [], "used": {}, "fact_devs": None})
    if k and f"{step_base}_a{k}" not in ag["processed"]:
        ag["processed"].append(f"{step_base}_a{k}")          # 旧的未处理补丁包作废，免得补丁环等它
    user = AF.patch_user(ep, pre, cur, facts, [target], "")
    AF.write_json(run_dir / "hollywood" / f"ep{ep:02d}.json", {
        "candidates": [], "code_fails": 0, "fails": ["narr#N05"], "spent_usd": float(st.d.get("usd_total") or 0), "rounds_left": 0,
        "staged_path": None, "sha256": None, "writer_backend": "claude_agent", "status": "叙事补丁中"})
    pk = packet(run_dir, st, step_base, "writer", ep, "patch", R5.r5_writer_system(), user, "patches_json", [H.RC._rel(final_p)], k + 1,
                {"base_sha": _sha(cur), "targets": ["narr#N05"], "narrative_allowed": allowed})
    st.d.setdefault("agent_history", []).append({"step": f"{step_base}_a{k + 1}", "accepted": None, "note": f"叙事补丁包 N05 → {allowed}"})
    st.save()
    return {"ok": True, "packet": H.RC._rel(run_dir / WT / f"{step_base}_a{k + 1}.json"), "allowed": allowed, "now": types.get(ep),
            "output": pk["output"]["path"]}


def intake_full_p4(RCH, run_dir: Path, ep: int, st, ctx: dict) -> None:
    """写手交来的整集 P4 重写稿（writer_out/P4_epNN_rK.md 或 _aK.md，带 .done；SCRIPTWRITER 按 shot_spec_v2 七段重写第二季已有集）：
    run_chain.validate（P3-P4，同导入关口）过了（或只剩 ≤6 条 P4 阻断交补丁环）→ 旧 P4 / 旧 final 改名留档，新稿成为正式 P4，补丁环从新稿起。
    原文件不删，只改名为 .v<时间>.md"""
    done = st.d.setdefault("agent", {"processed": [], "used": {}, "fact_devs": None}).setdefault("full_p4_done", [])
    cands = sorted((run_dir / WO).glob(f"P4_ep{ep:02d}_[ra]*.md"), key=lambda q: int((re.findall(r"_[ra](\d+)\.md$", q.name) or ["0"])[0]))   # 按轮次号排，不按修改时间猜
    for q in cands:
        if q.name in done or not q.with_name(q.name + ".done").exists():
            continue
        done.append(q.name)
        st.save()
        if ctx.get("screenplay") is None:
            st.set(intake_note=f"{q.name}：P3 还没有，先不收")
            done.remove(q.name)
            return
        rep, obj, _extra = RCH.validate("P3-P4", q.read_text(encoding="utf-8"), ctx)
        blocking = rep.as_dict()["blocking"]
        if not (rep.ok or (obj is not None and blocking <= 6)):
            st.d.setdefault("agent_history", []).append({"step": q.name, "accepted": False, "note": f"整集稿 P4 阻断 {blocking}"})
            st.save()
            continue
        tag = time.strftime("%H%M%S")
        for old in (run_dir / f"P4_ep{ep:02d}.md", run_dir / f"P4_ep{ep:02d}.final.md", run_dir / f"P4_ep{ep:02d}.split.md"):
            if old.exists():
                old.rename(old.with_name(old.stem + f".v{tag}.md"))
        from ns_recipes.spec_import import rules_version, stamp
        (run_dir / f"P4_ep{ep:02d}.md").write_text(stamp(obj, rules_version()), encoding="utf-8")
        AF.write_json(run_dir / f"P4_ep{ep:02d}.md.report.json", {"link": "P3-P4", "status": "ok" if rep.ok else "needs_writer",
                                                                  "report": rep.as_dict(), "writer": "claude_agent", "source": H.RC._rel(q)})
        (run_dir / f"P4_ep{ep:02d}.md.v2").write_text("shot_spec_v2\n", encoding="utf-8")   # 这一集按 v2 判（K-WRT-805 / 806）
        # 整集稿替换了旧稿：旧稿上出的补丁包全部作废（记为已处理），否则补丁环会一直等一个不会再来的产物
        stale = [q2.stem for q2 in (run_dir / WT).glob(f"patch_ep{ep:02d}_a*.json")]
        st.d["agent"] = {"processed": stale, "used": {}, "fact_devs": None, "full_p4_done": done}
        st.d.setdefault("agent_history", []).append({"step": q.name, "accepted": True, "note": f"整集稿收为正式 P4（阻断 {blocking}）"})
        mark_dirty(run_dir, ep, f"收整集稿 {q.name}")
        st.save()


def run(run_dir: Path, ep: int, import_mode: str) -> dict:
    st = AF.Status(run_dir, ep, 0.0)
    st.set(writer_backend="claude_agent", started=st.d.get("started") or time.strftime("%F %T"))
    RCH = _load("run_chain", "tools/pipeline/run_chain.py")
    AF.patch_chain(RCH)
    from ns_schema import storyline as SL
    brep = SL.check_brief(json.loads((run_dir / "P0_brief.json").read_text(encoding="utf-8")))
    if not brep.ok:
        st.stage("P0", "Brief", "bad_brief", "code")
        return st.d
    st.stage("P0", "Brief", "ok", "code")
    try:
        from ns_api import script_chat as SC
        rc, rs, _ = SC.registry_tables({"from": brep.obj.registry_from})
    except Exception as e:  # noqa: BLE001  登记表读不到：照样写，记下原因（写作方会少了已登记人物的逐字格）
        rc, rs = [], []
        st.set(registry_error=repr(e)[:200])
    ctx = {"brief": brep.obj, "episode": ep, "registry_chars": rc, "registry_scenes": rs}
    for link, key in (("P0-P1", "storyline"), ("P1-P2", "outline"), ("P2-P3", "screenplay")):   # 收整集稿要用到上游
        cp = run_dir / dict(RCH.STAGES)[link].format(ep=ep)
        ctx[key] = RCH._load_ok(cp, link, ctx) if cp.exists() else None
    intake_full_p4(RCH, run_dir, ep, st, ctx)
    p4_exists = (run_dir / f"P4_ep{ep:02d}.md").exists()
    AF.REQUIRE_V2["on"] = not p4_exists or (run_dir / f"P4_ep{ep:02d}.md.v2").exists()   # 新写 / 重写的集按 v2（K-WRT-805 / 806）
    AF.REQUIRE_V3["on"] = (run_dir / f"P4_ep{ep:02d}.md.v3").exists()                   # v3 试点（K-WRT-H19 / H20，总调度 11-02）
    if not chain_step(RCH, run_dir, ep, st, ctx):
        return st.d
    return post_step(run_dir, ep, st, import_mode)
