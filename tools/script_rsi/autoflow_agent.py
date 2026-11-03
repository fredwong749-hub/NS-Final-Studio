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
NEXT_STEP = "交稿后只建 .done，等系统推进，不要自己跑命令"
PATCH_MAX = 10
CONTENT_RULES = ("全部人物成年（≥22 岁）、一切亲密情节双方自愿、人物均为虚构。暧昧和张力可以写；露骨的性描写不写。"
                 "亲密镜写成占位：该镜的 img / motion / H3 只写非露骨的画面（构图、视线、手、呼吸、环境），并在镜头块里加一行 "
                 "`**H3校验**：本地生成（亲密镜占位）`——这类镜头的画面只在本地生成。不改第一季已定的剧情事实和人物设定（身份、名字、年龄、"
                 "发色发型、脸、5 厘米透明水晶甲、人物关系、已发生剧情）；每集服装 / 造型不是事实，以本集造型行为准（K-WRT-H10）。缺信息标“未提供”。" + AF.PLACEHOLDER_OVERRIDE)
EXT = {"json": "json", "markdown_episode": "md", "patches_json": "json", "facts_json": "json", "factcheck_json": "json"}


SCORE_DIRTY = "line3_dirty.json"     # 稿子变了 → 要重打线 3 分；编排器 tick 看到就跑 line3_score 再删掉（总调度：自动打分，不要人工接力）


def mark_dirty(run_dir: Path, ep: int, why: str) -> None:
    p = run_dir / SCORE_DIRTY
    try:
        d = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except (OSError, ValueError) as e:     # 标记文件坏了：重写一份（宁可多打一次分），不吞掉这次变化
        print(f"[autoflow] {p.name} 读不了（{e!r}），重写")
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


CONTENT_RULES_CLEAN = ("全部人物成年（≥22 岁）、一切亲密情节双方自愿、人物均为虚构。暧昧和张力可以写；露骨的性描写不写。"
                       "亲密镜写成占位：该镜的 img / motion / H3 只写非露骨的画面（构图、视线、手、呼吸、环境），并在镜头块里加一行 "
                       "`**H3校验**：本地生成（亲密镜占位）`——这类镜头只在项目方自有机器上生成（笔记本 / gpu33 / gpu36，L-128），写法仍不露骨。人物、造型、场景以本剧 P0 / P1 为准；"
                       "正文里不留占位词（未提供 / 待定 / TODO / XXX / <…>，SL-12）：缺信息就按 P0 / P1 已有设定写成具体内容。" + AF.PLACEHOLDER_OVERRIDE)


def clean_cut(run_dir: Path) -> bool:
    """L-126 完全切割的 run（run 目录里有 CLEAN_CUT.json）：写作包里不许有旧剧内容（packet 只检查、出现即失败，不改写；HEADER-O 11-03）"""
    return (run_dir / "CLEAN_CUT.json").exists()


def l141_fix(run_dir: Path, p: Path, st, by: str, need_done: bool = False) -> dict | None:
    """MIGRATE-O 11-03（L-141）：稿里有 H3 镜内 At 时间码 → 确定性迁移器（tools/script_rsi/l141_migrate.py）先改成自然语言分拍，
    不派 LLM 补丁；原稿隔离备份、审计写 <run>/l141_migrate.jsonl。拍数对不上 **分拍** 的镜不动（留给补丁环）。只对 V2 完全切割 run"""
    if not clean_cut(run_dir) or not p.exists() or (need_done and not p.with_name(p.name + ".done").exists()):
        return None
    try:
        res = _load("l141_migrate", "tools/script_rsi/l141_migrate.py").apply_file(p, run_dir, by=by)
    except Exception as e:  # noqa: BLE001  迁移器出错不挡推进：原稿不动，照旧走校验 / 补丁环
        res = {"changed": False, "error": repr(e)[:200]}
    if res and (res.get("changed") or res.get("error")):
        st.d.setdefault("agent_history", []).append({"step": p.name, "accepted": bool(res.get("changed")), "by": "l141_migrate",
                                                     "note": (res.get("error") or f"L-141 迁移：镜 {res['migrated']}；交补丁环 {res['needs_llm']}")[:300]})
        st.save()
    return res


def packet(run_dir: Path, st, step: str, role: str, ep: int, link: str, system: str, user: str, fmt: str,
           inputs: list[str], attempt: int, extra: dict | None = None, output_path: Path | None = None) -> dict:
    if not step.startswith(("P1", "facts", "factcheck", "patch", "revise", "lockline")):     # P2 / P3 / P4 包：P1 没过项目方闸门一律不出
        OG = _load("owner_gate", "tools/script_rsi/owner_gate.py")
        if not OG.p1_approved(run_dir):
            raise RuntimeError(f"{run_dir.name}：P1 还没过项目方闸门（用这版），不出 {step} 包（11-02 19:17 事故守卫）")
    rules = CONTENT_RULES
    if clean_cut(run_dir):          # 完全切割的剧：内容边界用不含旧剧事实的版本
        # HEADER-O 11-03（总调度）：不再用 v1_leak.redact 偷偷改写作业包；只检查，出现 V1 id → HeaderMissing（失败关闭）
        from ns_api import script_chat as SC
        SC.assert_no_v1(system + "\n" + user, run=SC.run_for_dir(run_dir) or run_dir.name, what=f"{step} 作业包")
        rules = CONTENT_RULES_CLEAN
    if ("标“未提供”" in system + user + rules or "标未提供" in system + user + rules) and AF.OVERRIDE_TAG not in system + rules:
        system += "\n" + AF.PLACEHOLDER_OVERRIDE                    # OVERSIGHT-F P1-8a：单一出口兜底——提到“标未提供”的包必带 SL-12 覆盖说明
    op = output_path or out_path(run_dir, step, attempt, fmt)      # 集返修稿要落 writer_out/P4_epNN_r<k>.md（intake_full_p4 收），其余按 step 命名
    pk = {"schema": "nsfs.writer_task/1", "run": run_dir.name, "step": step, "role": role, "episode": ep, "link": link,
          "system": system + "\n\n========\n\n【内容边界】" + rules, "user": user, "inputs": inputs,
          "output": {"path": H.RC._rel(op), "format": fmt, "done_marker": H.RC._rel(op) + ".done"},
          "content_rules": rules, "attempt": attempt, "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "status": "open",
          "next": NEXT_STEP, **(extra or {})}       # 根因模式 1“双入口”（总调度 11-02）：包里不再给推进命令，推进只走 autoflow（网页 /repair 或 .done 守护）
    AF.write_json(run_dir / WT / f"{step}_a{attempt}.json", pk)
    packet_request(run_dir, pk, run_dir / WT / f"{step}_a{attempt}.json")    # EPCHAIN-O：写手 / 评审包都写一条派人请求（一请求一文件）
    if role == "reviewer":                       # 总调度 11-02：评审方的包一出就写派人请求（同 judge_request 的做法；兼容旧单文件）
        review_request(run_dir, step, ep, attempt, run_dir / WT / f"{step}_a{attempt}.json", pk["output"]["path"])
    st.set(awaiting={"step": step, "role": role, "attempt": attempt, "packet": H.RC._rel(run_dir / WT / f"{step}_a{attempt}.json"),
                     "output": pk["output"]["path"]}, verdict="awaiting_" + role,
           next_action=f"等{'写手' if role == 'writer' else '评审'}交 {step}（第 {attempt} 次）")
    return pk


LOOKS = "P1_looks.json"


def mark_voided(p: Path, why: str) -> None:
    """作废的写作包统一写法：文件名 <名>.void<时分秒>.json，包内 status=voided、voided_at、void_why（回稿等非包文件只改名）"""
    if p.suffix != ".json" or p.name.endswith(".done"):
        return
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:                 # 回稿不是 JSON（如 .md）：只改名，不加字段；记一行说明
        print(f"[void] {p.name} 不是写作包 JSON（{type(e).__name__}），只改名")
        return
    if isinstance(d, dict) and d.get("schema", "").startswith("nsfs.writer_task"):
        d.update(status="voided", voided_at=time.strftime("%Y-%m-%dT%H:%M:%S"), void_why=why[:300])
        AF.write_json(p, d)


def void_downstream(run_dir: Path, why: str) -> list[str]:
    """P1 返修（项目方“修改”或三评委未过）出新 P1 时，下游的造型包 / P2–P4 包和它们的回稿一并作废：移进 writer_tasks_void/、writer_out_void/
    （改名带时间戳，不删；OVERSIGHT-F 11-02）。返回移走的文件名"""
    tag = time.strftime("%H%M%S")
    moved = []
    for sub, void in ((WT, "writer_tasks_void"), (WO, "writer_out_void")):
        src = run_dir / sub
        if not src.exists():
            continue
        (run_dir / void).mkdir(exist_ok=True)
        for f in sorted(src.iterdir()):
            if f.is_file() and f.name.startswith(("P1_looks_", "P2_", "P3_", "P4_ep")):
                dst = run_dir / void / f"{f.stem}.void{tag}{f.suffix}"
                f.rename(dst)
                mark_voided(dst, why)
                moved.append(f"{sub}/{f.name}")
    if moved:
        log = run_dir / "writer_tasks_void" / "VOID_LOG.jsonl"
        log.parent.mkdir(exist_ok=True)
        with open(log, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "why": why, "moved": moved}, ensure_ascii=False) + "\n")
    return moved


def _looks_step(run_dir: Path, ep: int, st, storyline: dict, note: str = "") -> bool:
    """P1-looks：造型表做成链里的一步（总调度 11-02）。产物 writer_out/P1_looks_a<k>.json → looks_table.check（含 lead_f 只认清单 O1–O4）
    → 正式文件 <run>/P1_looks.json。返回 True = 已有正式造型表"""
    if (run_dir / LOOKS).exists():
        st.stage("P1L", "造型表", "reused", "code", output=H.RC._rel(run_dir / LOOKS))
        return True
    LT = _load("looks_table", "tools/script_rsi/looks_table.py")
    step, k = "P1_looks", attempts(run_dir, "P1_looks")
    base_user = LT.packet_user(storyline, ROOT)
    if note:
        base_user = "【项目方修改意见】" + note + "\n\n" + base_user
    sl_sha = _sha(json.dumps(storyline, ensure_ascii=False, sort_keys=True))
    if k:
        pk_prev = json.loads((run_dir / WT / f"{step}_a{k}.json").read_text(encoding="utf-8"))
        if pk_prev.get("storyline_sha") != sl_sha:      # 故事线换了版本（或旧包没记版本）：旧造型包作废，按新故事线重出
            packet(run_dir, st, step, "writer", ep, "P1-looks", LT.SYSTEM, base_user, "json", [], k + 1, {"storyline_sha": sl_sha})
            st.stage("P1L", "造型表", "awaiting_writer", "api_model", step=step, attempt=k + 1, detail="故事线有新版本，造型表按新版重写")
            return False
        txt = ready(out_path(run_dir, step, k, "json"))
        if txt is None:
            st.stage("P1L", "造型表", "awaiting_writer", "api_model", step=step, attempt=k)
            return False
        looks, err = LT.parse(txt)
        probs = [f"不是 JSON：{err}"] if looks is None else LT.check(looks, storyline) + LT.closed_check(looks, ROOT)
        if not probs:
            AF.write_json(run_dir / LOOKS, looks)
            st.stage("P1L", "造型表", "ok", "api_model", step=step, attempt=k, output=H.RC._rel(run_dir / LOOKS))
            return True
        packet(run_dir, st, step, "writer", ep, "P1-looks", LT.SYSTEM,
               base_user + "\n\n【上一版没过的地方】\n" + "\n".join(f"- {p}" for p in probs[:30]), "json", [], k + 1, {"storyline_sha": sl_sha})
        st.stage("P1L", "造型表", "repair_requested", "code", step=step, attempt=k + 1, problems=probs[:10])
        return False
    packet(run_dir, st, step, "writer", ep, "P1-looks", LT.SYSTEM, base_user, "json", [], 1, {"storyline_sha": sl_sha})
    st.stage("P1L", "造型表", "awaiting_writer", "api_model", step=step, attempt=1)
    return False


REVIEW_CFG = "config/prompts/hollywood_p1_review.yaml"
REVIEW_STATE = "judge_p1/STATE.json"


LIVE = "docs/master/V2_LIVE.md"


JUDGE_INBOX = "data/master/inbox/judge_request.json"     # 总调度 11-02：评审包一出就写一份派评委请求（只写不读；data/master 其余内容 agent 不碰）


def judge_request(run_dir: Path, n: int, d: Path, judges: int, sha: str, reference_only: bool) -> None:
    """派评委请求（测试期 L-109 不能用付费外部 API，评委由总调度派；上线后换成外部评审 API 自动派）。
    只写这一个文件（原子替换），不读、不列 data/master/ 下任何东西；写不进去不影响推进"""
    req = {"schema": "nsfs.judge_request/1", "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "run": run_dir.name, "round": n, "base_sha": sha,
           "judges": judges, "reference_only": reference_only, "dir": H.RC._rel(d),
           "packets": [H.RC._rel(d / f"judge_{j}" / "p1_review_task.json") for j in range(1, judges + 1)],
           "rules": "三位评委用不同模型、不复用上一轮；独立作答；证据必须是 P1 原文（≤60 字），不合格那条封顶 2 分，超过 3 条整份作废要重交",
           "note": ("项目方已接手：分数只作参考，评完直接交项目方看" if reference_only else "过门槛（均分 ≥ 34、无条目均分 ≤ 2）才交项目方")}
    _inbox_write(JUDGE_INBOX, req)          # 兼容：旧的单文件（只留最近一条）
    request_write(run_dir, f"judge_p1_r{n}", {
        "kind": "judge", "episode": 1, "step": "P1_review", "attempt": n, "packet": req["packets"][0] if req["packets"] else None,
        "packets": req["packets"], "outputs": [H.RC._rel(d / f"judge_{j}" / "out" / "p1_review.json") for j in range(1, judges + 1)],
        "done_marker": "<每个 output>.done", "suggested_model": AF.MODEL_PLAN["judges"][0],
        "suggested_models": AF.MODEL_PLAN["judges"][:judges], "must_differ_from": AF.MODEL_PLAN["writer"],
        "rules": req["rules"], "note": req["note"]})


REVIEW_INBOX = "data/master/inbox/review_request.json"   # reviewer 包（事实核对等）的派人请求；只写不读


INBOX_DIR = "data/master/inbox"
REQUESTS_SUB = "requests"     # EPCHAIN-O 11-03：每个派人请求一个文件 inbox/requests/<run>__<id>.json（多集排队不互相覆盖；格式见 PIPELINE_SOP_V2.md）


def inbox_dir() -> Path:
    import os
    p = Path(os.environ.get("NSFS_INBOX_DIR") or INBOX_DIR)
    return p if p.is_absolute() else ROOT / p


def request_write(run_dir: Path, rid: str, req: dict) -> Path | None:
    """写一条派人请求（nsfs.dispatch_request/1）：一请求一文件，原子替换；只写不读；写失败不影响推进"""
    out = inbox_dir() / REQUESTS_SUB / f"{run_dir.name}__{rid}.json"
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"schema": "nsfs.dispatch_request/1", "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "run": run_dir.name,
                                   "id": rid, **req}, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(out)
        return out
    except OSError as e:
        print(f"[inbox] 写 {out} 失败：{e!r}")
        return None


def void_request(run_dir: Path, rid: str, why: str) -> dict:
    """TIMELINE-O 11-03：作废一个已发出的作业包（不删）：先写 inbox/requests/<run>__<id>.void（派单器见到就不派、在跑的杀掉），
    再把作业包和请求移进 data/_quarantine/void_requests_<日期>/<run>/。→ {void, moved}"""
    rq = inbox_dir() / REQUESTS_SUB
    rq.mkdir(parents=True, exist_ok=True)
    key = f"{run_dir.name}__{rid}"
    vp = rq / f"{key}.void"
    vp.write_text(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "why": why}, ensure_ascii=False), encoding="utf-8")
    qd = ROOT / "data" / "_quarantine" / f"void_requests_{time.strftime('%Y%m%d')}" / run_dir.name
    moved = []
    for src in (run_dir / WT / f"{rid}.json", rq / f"{key}.json"):
        if src.exists():
            qd.mkdir(parents=True, exist_ok=True)
            src.replace(qd / f"{src.name}.{time.strftime('%H%M%S')}")
            moved.append(src.name)
    return {"void": str(vp), "moved": moved}


def packet_request(run_dir: Path, pk: dict, pk_path: Path) -> Path | None:
    """写作包 / 评审包一出就写派人请求：写手 → MODEL_PLAN.writer（Fable），评审 → MODEL_PLAN.reviewer（Sonnet），写和评不同模型"""
    role = pk.get("role") or "writer"
    model = AF.MODEL_PLAN["reviewer" if role == "reviewer" else "writer"]
    return request_write(run_dir, f"{pk['step']}_a{pk['attempt']}", {
        "kind": role, "episode": pk.get("episode"), "step": pk["step"], "attempt": pk["attempt"], "link": pk.get("link"),
        "packet": H.RC._rel(pk_path), "output": pk["output"]["path"], "done_marker": pk["output"]["done_marker"],
        "suggested_model": model, "must_differ_from": AF.MODEL_PLAN["writer"] if role == "reviewer" else None,
        "note": "交稿只建 .done，等系统推进（不要自己跑命令）"})


def _inbox_write(rel: str, req: dict) -> None:
    import os
    if os.environ.get("NSFS_INBOX_DIR"):              # 测试 / 演练：派人请求改写到这个目录，不碰真实 data/master/
        rel = str(Path(os.environ["NSFS_INBOX_DIR"]) / Path(rel).name)
    try:
        out = Path(rel) if Path(rel).is_absolute() else ROOT / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(req, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(out)
    except OSError as e:
        print(f"[inbox] 写 {rel} 失败：{e!r}")


def review_request(run_dir: Path, step: str, ep: int, attempt: int, pk_path: Path, output: str) -> None:
    """评审方（role=reviewer：事实表 / 事实核对）包的派人请求：data/master/inbox/review_request.json（原子替换、只写不读、写失败不影响推进）"""
    _inbox_write(REVIEW_INBOX, {"schema": "nsfs.review_request/1", "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "run": run_dir.name,
                                "step": step, "episode": ep, "attempt": attempt, "packet": H.RC._rel(pk_path), "output": output,
                                "note": "评审方包（写手不能做）；交稿只建 .done，等系统推进"})


def live_note(text: str) -> None:
    """V2_LIVE.md 顶部加一行（总调度看这里派新一轮评委）；写不进去不影响推进，但要打印出来"""
    p = ROOT / LIVE
    try:
        old = p.read_text(encoding="utf-8") if p.exists() else ""
        tmp = p.with_suffix(".md.tmp")
        tmp.write_text(time.strftime("%H:%M") + " HOLLYWOOD（autoflow）：" + text + "\n" + old, encoding="utf-8")
        tmp.replace(p)
    except OSError as e:
        print(f"[autoflow] V2_LIVE.md 写不进去：{e!r}；原文：{text}")


def judge_done_sig(d: Path) -> str:
    """一轮评审目录里评委 .done 的签名（文件名 + 产物字节数 + 修改时间 + .done 时间）；watch 用它判断“这组交稿收过没有”。
    评委重交（证据不合格整份无效后）即使字节数一样，修改时间也会变 → 重新汇总"""
    parts = []
    for f in sorted(d.glob("judge_*/out/p1_review.json.done")):
        out = f.with_name("p1_review.json")
        o = out.stat() if out.exists() else None
        parts.append(f"{f.parent.parent.name}:{o.st_size if o else 0}:{o.st_mtime_ns if o else 0}:{f.stat().st_mtime_ns}")
    return "|".join(parts)


def review_cfg() -> dict:
    import yaml
    return yaml.safe_load((ROOT / REVIEW_CFG).read_text(encoding="utf-8")) or {}


def review_round_dir(run_dir: Path, n: int) -> Path:
    return run_dir / "judge_p1" if n == 1 else run_dir / "judge_p1" / f"r{n}"


def review_add_fixes(run_dir: Path, fixes: list[str], by: str, replace: bool = False) -> dict:
    """给当前轮评审追加返修意见（如总调度汇总的共识意见）——唯一写法，带来源；状态文件不许手写（OVERSIGHT-F 11-02）"""
    sp = run_dir / REVIEW_STATE
    state = json.loads(sp.read_text(encoding="utf-8"))
    cur = state["rounds"][-1]
    if replace:                                  # 总调度给了更完整的共同意见：替换本轮旧的追加意见（旧的记进 extra_replaced 留档）
        cur.setdefault("extra_replaced", []).append({"fixes": cur.get("extra_fixes") or [], "at": time.strftime("%Y-%m-%dT%H:%M:%S")})
        cur["extra_fixes"] = []
    cur.setdefault("extra_fixes", []).extend(x for x in fixes if x.strip())
    cur.setdefault("extra_by", [])
    if isinstance(cur["extra_by"], str):
        cur["extra_by"] = [cur["extra_by"]]
    cur["extra_by"].append({"by": by, "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "n": len(fixes)})
    AF.write_json(sp, state)
    return cur


ESCALATE_DIGEST = "config/master/escalate.sha256"      # 入版：只放令牌摘要；令牌本身 data/master/escalate.token 由总调度会话生成，agent 不许读


def _check_escalate_token(token_file: str | None) -> str:
    """OVERSIGHT-F P1-4a / W-33：凭令牌放行（不是凭 --by 字符串）。返回摘要前 8 位；不对就 PermissionError"""
    import hashlib
    if not token_file:
        raise PermissionError("转项目方要带 --token-file（总调度令牌）；只写 --by 总调度不放行")
    dp = ROOT / ESCALATE_DIGEST
    if not dp.exists():
        raise PermissionError(f"{ESCALATE_DIGEST} 还没写入令牌摘要，不能转项目方")
    want = dp.read_text(encoding="utf-8").split()[0].strip().lower()
    try:
        raw = Path(token_file).read_bytes().strip()
    except OSError:                                   # OVERSIGHT-F 第 5 轮：文件不存在 / 读不了 → 大白话 PermissionError，不是 FileNotFoundError
        raise PermissionError(f"令牌文件 {token_file} 不存在或读不了，不能转项目方") from None
    got = hashlib.sha256(raw).hexdigest()
    if got != want:
        raise PermissionError("令牌不对，不能转项目方")
    return got[:8]


def review_escalate_owner(run_dir: Path, by: str, why: str = "", token_file: str | None = None) -> dict:
    """总调度动作（只能由总调度触发）：把当前这一稿（低于门槛）连同各轮评分转给项目方定方向 → owner_direction。
    凭令牌放行（--token-file，摘要对上 config/master/escalate.sha256）；记审计（谁、摘要前 8 位、pid、用户名、当时的分数、理由），只对这一稿有效"""
    if "总调度" not in (by or ""):
        raise PermissionError("只有总调度能把故事线转给项目方定方向（--by 须写总调度）")
    digest8 = _check_escalate_token(token_file)
    import hashlib
    sp = run_dir / REVIEW_STATE
    state = json.loads(sp.read_text(encoding="utf-8"))
    canon = run_dir / "P1_storyline.json"
    if not canon.exists():
        raise FileNotFoundError("当前没有 P1 正式稿（可能还在返修），不能转项目方")
    sha = hashlib.sha256(canon.read_text(encoding="utf-8").encode("utf-8")).hexdigest()[:16]
    cur = state["rounds"][-1] if state.get("rounds") else {}
    if cur.get("sha") != sha:
        raise ValueError("当前这一稿还没评审完，等评分出来再转")
    import os as _os
    state["owner_direction"] = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "by": by, "why": why, "round": cur.get("n"),
                                "mean": (cur.get("result") or {}).get("mean"), "totals": (cur.get("result") or {}).get("totals"), "sha": sha,
                                "token_digest8": digest8, "pid": _os.getpid(), "user": _os.environ.get("USERNAME") or _os.environ.get("USER") or ""}
    AF.write_json(sp, state)
    live_note(f"{run_dir.name} P1 第 {cur.get('n')} 轮 {(cur.get('result') or {}).get('mean')}/40 低于门槛，总调度转项目方定方向（用这版 / 修改 / 换方向）")
    return state["owner_direction"]


def review_mark_took_over(run_dir: Path, note: str, by: str, how: str) -> dict:
    """项目方在“定方向”状态下点了“修改”→ 记 owner_took_over（唯一写法；之后新稿照样评审，分数只作参考，轮数上限不再适用）。
    how = p1_gate（正常路径）/ repair（事后用 review-state --owner-took-over 补记，须有 owner_gates 历史里的 revise 记录作依据）"""
    sp = run_dir / REVIEW_STATE
    state = json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else {"rounds": []}
    if state.get("owner_took_over"):
        return state["owner_took_over"]
    state["owner_took_over"] = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "note": (note or "")[:300], "by": by, "how": how}
    AF.write_json(sp, state)
    return state["owner_took_over"]


def review_repair_took_over(run_dir: Path, by: str) -> dict:
    """事后补记 owner_took_over：只认 owner_gates.json 历史里 P1 的 revise（项目方亲自点的），且 STATE.json 里有 owner_direction；都没有就拒绝"""
    OG_ = _load("owner_gate", "tools/script_rsi/owner_gate.py")
    sp = run_dir / REVIEW_STATE
    state = json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else {}
    if not state.get("owner_direction"):
        raise PermissionError("STATE.json 里没有 owner_direction（总调度没转过项目方），不能补记项目方接手")
    hist = [h for h in (OG_.summary(run_dir).get("history") or []) if h.get("key") == "P1" and h.get("action") == "revise"]
    hist = [h for h in hist if h.get("at", "") >= state["owner_direction"].get("at", "")]
    if not hist:
        raise PermissionError("owner_gates 历史里没有项目方在转交之后点“修改”的记录，不能补记")
    h = hist[-1]
    return review_mark_took_over(run_dir, h.get("note", ""), by=f"{h.get('by') or 'owner'}（{by} 补记，依据 owner_gates {h.get('at')}）", how="repair")


def review_common_note(run_dir: Path) -> str:
    """上一轮评审给写手的意见块：总调度汇总的共同意见（extra_fixes）在最前面，再是三家各自最该改的；没有评审 = 空串"""
    sp = run_dir / REVIEW_STATE
    if not sp.exists():
        return ""
    state = json.loads(sp.read_text(encoding="utf-8"))
    cur = state["rounds"][-1] if state.get("rounds") else {}
    if not cur:
        return ""
    rp = ROOT / (cur.get("dir") or "_") / "RESULT.json"
    res = json.loads(rp.read_text(encoding="utf-8")) if rp.exists() else {}
    parts = [f"【上一轮三评委意见（P1 第 {cur.get('n')} 轮，均分 {(cur.get('result') or res).get('mean')}/40）】"]
    if cur.get("extra_fixes"):
        parts.append("【最先改：评委共同意见】\n" + "\n".join(f"- {x}" for x in cur["extra_fixes"]))
    if res.get("top_fixes"):
        parts.append("【三家各自最该改的地方】\n" + "\n".join(f"- {f}" for f in res["top_fixes"][:12]))
    return "\n".join(parts) if len(parts) > 1 else ""


def review_state_normalize(run_dir: Path) -> dict:
    """把评审状态里的手写痕迹改回工具口径：packed_at 取该轮评审包 created_at 的最早值"""
    sp = run_dir / REVIEW_STATE
    state = json.loads(sp.read_text(encoding="utf-8"))
    for r in state.get("rounds") or []:
        d = ROOT / r["dir"]
        ts = sorted(json.loads(f.read_text(encoding="utf-8")).get("created_at", "") for f in d.glob("judge_*/p1_review_task.json"))
        if ts and ts[0]:
            r["packed_at"] = ts[0]
        if isinstance(r.get("extra_by"), str):
            r["extra_by"] = [{"by": r["extra_by"], "at": None, "n": len(r.get("extra_fixes") or [])}]
        for e in r.get("extra_by") or []:            # W-24：占位 / 编出来的时间（如“20:xx”“19:5x”）一律去掉，改记“未记时间”
            if isinstance(e, dict) and re.search(r"\d{1,2}:[0-9]?x", str(e.get("by", "")) + str(e.get("at") or "")):
                e["by"] = re.sub(r"\s*\d{1,2}:[0-9]?x+", "", str(e.get("by", "")))
                e["at"] = None
                e["at_note"] = "当时手写、未记时间（写入早于 autoflow.log 19:25:45 那次推进）；以后只经 review_add_fixes 写"
    state["normalized_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    AF.write_json(sp, state)
    return state


def review_passed(res: dict, cfg: dict) -> tuple[bool, list[str]]:
    """门槛（config/prompts/hollywood_p1_review.yaml）→ (过没过, 没过的原因)"""
    why = []
    if res.get("n", 0) < int(cfg.get("judges", 3)):
        why.append(f"评委只交了 {res.get('n', 0)} 家")
    if cfg.get("require_distinct_judges", True) and res.get("single_judge"):
        why.append("三家 judge_id 不是三个不同评委")
    if cfg.get("require_stable") and not res.get("stable"):
        why.append(f"σ={res.get('sigma')} > 1")
    if (res.get("mean") or 0) < float(cfg.get("min_mean", 34)):
        why.append(f"均分 {res.get('mean')} < {cfg.get('min_mean', 34)}")
    low = [k for k, v in (res.get("item_mean") or {}).items() if v < float(cfg.get("min_item_mean", 2.01))]
    if low:
        why.append(f"有条目三家均分 ≤ 2：{low}")
    return not why, why


def _p1_review(RCH, run_dir: Path, ep: int, st, ctx: dict, canon: Path, sl: dict) -> bool:
    """P1 三评委（总调度 11-02：P1 先过三评委，均分 ≥ 门槛且没有条目 ≤ 2 才开项目方闸门；不过按三家“最该改的地方”自动出 P1 返修包，
    最多 max_rounds 轮，超过转总调度）。每个 P1 版本（sha）一轮；评委由总调度派，本函数只出包、收分、判门槛、出返修包。返回 True = 过了"""
    cfg = review_cfg()
    if not cfg.get("enabled", True):
        return True
    OG_ = _load("owner_gate", "tools/script_rsi/owner_gate.py")
    od = OG_.owner_direction(run_dir)
    if od:                                           # 总调度已转项目方定方向：不再判门槛，交给项目方闸门（用这版 / 修改 / 换方向）
        st.stage("P1R", "P1 三评委", "owner_direction", "owner", round=od.get("round"), mean=od.get("mean"), by="总调度")   # 审计全文在 STATE.json，给人看的不带内部编号（W-39）
        if OG_.get(run_dir, "P1").get("status") == "approved":
            return True
        txt = OG_.owner_direction_text(run_dir) + "，总调度转给你定方向"
        st.stage("P1G", "项目方看 P1", "owner_direction", "owner", detail=f"{txt}：{OG_.OWNER_CHOICES}")
        st.set(verdict="owner_direction", awaiting=None, below_threshold=True,
               next_action=f"{txt}：{OG_.OWNER_CHOICES}"
               + ("。" + fill_note(st.d["p1_owner_hold_fields"]) if st.d.get("p1_owner_hold_fields") else ""))
        return False
    JA = _load("judge_agent", "tools/script_rsi/judge_agent.py")
    sp = run_dir / REVIEW_STATE
    state = json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else {"rounds": []}
    sha = JA._sha(canon.read_text(encoding="utf-8"))
    cur = state["rounds"][-1] if state["rounds"] else None
    took = bool(state.get("owner_took_over"))       # 项目方已接手：轮数上限不再适用（评审只作参考）
    if cur is None or cur.get("sha") != sha:
        n = len(state["rounds"]) + 1
        if n > int(cfg.get("max_rounds", 3)) and not took:
            st.stage("P1R", "P1 三评委", "escalated", "code", detail=f"已评 {n - 1} 轮仍未过门槛")
            st.set(verdict="p1_review_failed", next_action="P1 三评委已到轮数上限仍未过，交总调度")
            return False
        d = review_round_dir(run_dir, n)
        legacy = n == 1 and all((d / f"judge_{j}" / "p1_review_task.json").exists() for j in range(1, int(cfg.get("judges", 3)) + 1))
        if not legacy:
            JA.p1_pack(run_dir, int(cfg.get("judges", 3)), out=d)
            judge_request(run_dir, n, d, int(cfg.get("judges", 3)), sha, reference_only=took)
            live_note(f"{run_dir.name} 第 {n} 轮 P1 评审包已出（{H.RC._rel(d)}/judge_1–{cfg.get('judges', 3)}），请派 {cfg.get('judges', 3)} 位新评委（不同模型、不复用上一轮）")
        state["rounds"].append({"n": n, "sha": sha, "dir": H.RC._rel(d), "packed_at": time.strftime("%Y-%m-%dT%H:%M:%S")})
        AF.write_json(sp, state)
        cur = state["rounds"][-1]
    d = review_round_dir(run_dir, int(cur["n"]))
    res = JA.p1_collect(run_dir, out=d)
    cur.update(result={k: res.get(k) for k in ("n", "totals", "mean", "sigma", "item_mean", "item_split", "judge_ids", "single_judge", "problems",
                                     "evidence_fail", "invalid_judges")})
    ok, why = review_passed(res, cfg)
    if res.get("n", 0) < int(cfg.get("judges", 3)):
        cur["collected_sig"] = judge_done_sig(ROOT / cur["dir"])        # 同一组评委 .done 已收过一次：watch 不再每 30 秒空转
        AF.write_json(sp, state)
        st.stage("P1R", "P1 三评委", "awaiting_judges", "judge", round=cur["n"], got=res.get("n", 0), dir=cur["dir"])
        st.stage("P1G", "项目方看 P1", "waiting_p1_review", "owner", detail="三评委过门槛后才交项目方")
        st.set(verdict="awaiting_p1_judges", awaiting=None, next_action=f"等第 {cur['n']} 轮三位评委交稿（{res.get('n', 0)} / {cfg.get('judges', 3)}）：{cur['dir']}")
        return False
    if ok:
        cur["passed"] = True
        AF.write_json(sp, state)
        st.stage("P1R", "P1 三评委", "passed", "judge", round=cur["n"], mean=res.get("mean"), totals=res.get("totals"))
        live_note(f"{run_dir.name} P1 第 {cur['n']} 轮三评委过门槛：{res.get('totals')}，均分 {res.get('mean')}/40 → 交项目方看（P1 闸门）")
        return True
    cur["passed"], cur["why"] = False, why
    if took:                                          # 项目方接手后的新稿没到门槛：自动停在 owner_direction（新稿 sha），带上评分，不再 escalate、不出返修包
        import os as _os
        state["owner_direction"] = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "by": "系统（项目方已接手，自动带评分）", "why": "；".join(why),
                                    "round": cur["n"], "mean": res.get("mean"), "totals": res.get("totals"), "sha": sha,
                                    "auto_after_owner_revise": True, "pid": _os.getpid()}
        cur["reference_only"] = True
        AF.write_json(sp, state)
        st.stage("P1R", "P1 三评委", "owner_direction", "owner", round=cur["n"], mean=res.get("mean"), reference_only=True)
        st.stage("P1G", "项目方看 P1", "owner_direction", "owner", detail="项目方改过的新稿：评分只作参考，由你定")
        st.set(verdict="owner_direction", awaiting=None, below_threshold=True,
               next_action=f"项目方改过的新稿：评审 {res.get('mean')}/40（只作参考，没到 {cfg.get('min_mean', 34)}），由你定：用这版 / 修改 / 换方向")
        live_note(f"{run_dir.name} P1 项目方改过的新稿评审 {res.get('totals')}，均分 {res.get('mean')}/40（只作参考）→ 停在 owner_direction 等项目方定")
        return False
    if int(cur["n"]) >= int(cfg.get("max_rounds", 3)):
        AF.write_json(sp, state)
        st.stage("P1R", "P1 三评委", "escalated", "judge", round=cur["n"], why=why)
        st.set(verdict="p1_review_failed", next_action=f"转总调度：第 {cur['n']} 轮仍未过（{'；'.join(why)}），不给项目方看")
        live_note(f"{run_dir.name} P1 第 {cur['n']} 轮仍未过门槛（{res.get('mean')}/40），已到轮数上限，转总调度")
        return False
    if cur.get("revise_issued"):
        AF.write_json(sp, state)
        return False
    fixes = res.get("top_fixes") or []
    low = sorted((res.get("item_mean") or {}).items(), key=lambda kv: kv[1])[:4]
    note = "P1 三评委第 " + str(cur["n"]) + " 轮未过（" + "；".join(why) + "）。"
    if int(cur["n"]) + 1 >= int(cfg.get("max_rounds", 3)):
        note += f"这是第 {int(cur['n']) + 1} 稿，也是最后一稿：这一稿三评委还不到 {cfg.get('min_mean', 34)} 分（或有条目 ≤ 2），就转总调度，不再返修。"
    if cur.get("extra_fixes"):                     # 总调度汇总的共同意见放最前面（总调度 11-02：两位评委的共同意见先改）
        note += "\n【最先改：评委共同意见】\n" + "\n".join(f"- {x}" for x in cur["extra_fixes"])
    note += ("\n【三家各自最该改的地方】\n" + "\n".join(f"- {f}" for f in fixes[:12])
             + "\n得分最低的条目：" + "、".join(f"{k} {v}" for k, v in low) + "（口径 config/prompts/hollywood_p1_judge.md）")
    tag = time.strftime("%H%M%S")
    for f in (canon, canon.parent / f"{canon.name}.report.json", run_dir / LOOKS):
        if f.exists():
            f.rename(f.with_name(f.stem + f".v{tag}" + f.suffix))
    void_downstream(run_dir, f"P1 三评委第 {cur['n']} 轮未过（{res.get('mean')}/40）")
    k = attempts(run_dir, "P1")
    pr = RCH.WP.build("P0-P1", ctx)
    user = (pr["user"] + "\n\n【三评委意见（P1 第 " + str(cur["n"]) + " 轮）】\n" + note + "\n\n【上一版故事线（在它基础上改，剧名和主线可保留）】\n"
            + json.dumps(sl, ensure_ascii=False)[:20000])
    packet(run_dir, st, "P1", "writer", ep, "P0-P1", pr["system"], user, "json", [], k + 1)
    cur["revise_issued"] = True
    cur["revise_attempt"] = k + 1
    AF.write_json(sp, state)
    st.stage("P1R", "P1 三评委", "revise_requested", "judge", round=cur["n"], mean=res.get("mean"), why=why, attempt=k + 1)
    st.stage("P1G", "项目方看 P1", "waiting_p1_review", "owner", detail="三评委过门槛后才交项目方")
    st.set(verdict="awaiting_writer", next_action=f"返修中（第 {cur['n']} 轮，评审 {res.get('mean')}/40）：等写手按三评委意见改 P1（第 {k + 1} 稿）")
    live_note(f"{run_dir.name} P1 第 {cur['n']} 轮评审 {res.get('totals')}，均分 {res.get('mean')}/40 未过门槛 → 已出返修包 P1_a{k + 1}（交 SCRIPTWRITER）")
    return False


def p1_gate(RCH, run_dir: Path, ep: int, st, ctx: dict, canon: Path) -> bool:
    """P1 审阅闸（总调度 11-02，L-123）：有 owner_gates.json 的 run，P1 故事线 + 造型表收下后停在“等项目方看”；
    “用这版”→ 继续出 P2；“修改”→ 旧稿改名留档，出 P1 返修包（带这句话），新稿回来重新等项目方看。返回 True = 可以继续"""
    OG = _load("owner_gate", "tools/script_rsi/owner_gate.py")
    if not OG.enabled(run_dir):
        return True
    g = OG.get(run_dir, "P1")
    sl = ctx["storyline"].model_dump(mode="json", by_alias=True) if hasattr(ctx["storyline"], "model_dump") else ctx["storyline"]
    if g.get("status") == "redirect_requested" and not g.get("handled"):      # “换方向”：回到 P0 Brief，P1 / 造型 / 评审全部归档重来
        tag = time.strftime("%Y%m%d_%H%M%S")
        arc = run_dir / f"_redirect_{tag}"
        arc.mkdir()
        for f in (canon, canon.parent / f"{canon.name}.report.json", run_dir / LOOKS, run_dir / "judge_p1"):
            if f.exists():
                f.rename(arc / f.name)
        void_downstream(run_dir, "项目方换方向：" + g.get("note", "")[:100])
        bp = run_dir / "P0_brief.json"
        brief = json.loads(bp.read_text(encoding="utf-8"))
        brief["outline"] = "【项目方新方向（" + time.strftime("%m-%d %H:%M") + "，取代之前的故事方向）】" + g.get("note", "") + "\n\n" + brief["outline"]
        AF.write_json(bp, brief)
        OG.set_status(run_dir, "P1", "pending", note="项目方换方向，按新 Brief 重写 P1", handled=True, archive=H.RC._rel(arc))
        live_note(f"{run_dir.name} 项目方换方向：旧 P1 / 造型 / 评审归档到 {H.RC._rel(arc)}，按新 Brief 重写 P1")
        st.stage("P1G", "项目方看 P1", "redirected", "owner", archive=H.RC._rel(arc))
        st.set(verdict="redirected", awaiting=None, next_action="项目方换了方向：下一次推进按新 Brief 出 P1 包")
        return False
    if g.get("status") == "revise_requested" and not g.get("handled"):
        in_direction = OG.owner_direction(run_dir)   # 必须在改名之前查（改名后 canon 不在，永远是 None——21:40 P1_a5 事故）
        judge_note = review_common_note(run_dir)    # 上一轮评委共同意见（总调度汇总）+ 三家各自最该改的，放在包最前面
        tag = time.strftime("%H%M%S")
        for f in (canon, canon.parent / f"{canon.name}.report.json", run_dir / LOOKS):
            if f.exists():
                f.rename(f.with_name(f.stem + f".v{tag}" + f.suffix))
        if in_direction:                           # 项目方在“定方向”状态下点了修改 → 项目方已接手：之后的新稿照样评审，分数只作参考、不拦
            review_mark_took_over(run_dir, g.get("note", ""), by=g.get("by") or "owner", how="p1_gate")
        void_downstream(run_dir, "项目方点了 P1 “修改”：" + g.get("note", "")[:100])
        k = attempts(run_dir, "P1")
        pr = RCH.WP.build("P0-P1", ctx)
        user = (pr["user"] + (("\n\n" + judge_note) if judge_note else "")
                + "\n\n【项目方修改意见（原话）】" + g.get("note", "") + "\n\n【上一版故事线（在它基础上改）】\n"
                + json.dumps(sl, ensure_ascii=False)[:20000])
        packet(run_dir, st, "P1", "writer", ep, "P0-P1", pr["system"], user, "json", [], k + 1)
        OG.set_status(run_dir, "P1", "revising", note=g.get("note", ""), handled=True, revise_attempt=k + 1)
        st.stage("P1G", "项目方看 P1", "revising", "owner", note=g.get("note", "")[:200], attempt=k + 1)
        st.set(verdict="awaiting_writer", next_action="等写手按项目方意见改 P1")
        return False
    if not _looks_step(run_dir, ep, st, sl, g.get("note", "") if g.get("status") == "revising" else ""):
        return False
    if not _p1_review(RCH, run_dir, ep, st, ctx, canon, sl):
        return False
    if g.get("status") == "revising":
        OG.set_status(run_dir, "P1", "pending", note=g.get("note", ""))
        g = {"status": "pending"}
    if g.get("status") == "approved":
        st.stage("P1G", "项目方看 P1", "approved", "owner")
        if st.d.get("p1_owner_hold_fields") and not _p1_fill(RCH, run_dir, ep, st, ctx, canon, sl):
            return False
        return True
    for s_ in st.d.get("stages", []):        # 闸门之后的段（如闸门上线前已出的 P2 包）标成“被 P1 闸门挡住”，网页不显示成在等写手
        if s_.get("id") in ("P2", "P3", "P4") and s_.get("status") in ("awaiting_writer", "repair_requested"):
            s_["status"] = "held_by_p1_gate"
    st.stage("P1G", "项目方看 P1", "awaiting_owner", "owner", detail="网页上点“用这版”出 P2；点“修改”写一句话进返修")
    st.set(verdict="awaiting_owner_p1", awaiting=None, next_action="等项目方看 P1 故事线和造型表（用这版 / 修改）")
    return False


def ep_gate(run_dir: Path, ep: int, st) -> bool:
    """每集闸门：默认自动通过；项目方点了“修改”→ 出整集返修包（writer_out/P4_epNN_r<k>.md，由 intake_full_p4 收）。返回 True = 不拦"""
    OG = _load("owner_gate", "tools/script_rsi/owner_gate.py")
    if not OG.enabled(run_dir):
        return True
    key = f"ep{ep:02d}"
    g = OG.get(run_dir, key)
    if g.get("status") != "revise_requested" or g.get("handled"):
        return True
    final_p = run_dir / f"P4_ep{ep:02d}.final.md"
    cur_p = final_p if final_p.exists() else run_dir / f"P4_ep{ep:02d}.md"
    if not cur_p.exists():
        return True                 # 这一集还没写到 P4：意见留着，写到时再出
    used = [int(m) for p in (run_dir / WO).glob(f"P4_ep{ep:02d}_r*.md") for m in re.findall(r"_r(\d+)\.md$", p.name)]
    r = max(used, default=0) + 1
    op = run_dir / WO / f"P4_ep{ep:02d}_r{r}.md"
    packet(run_dir, st, f"revise_ep{ep:02d}", "writer", ep, "owner-revise",
           "你是这部剧的编剧。项目方对这一集提了修改意见，请整集改写（剧情事实以 P1–P3 为准，只按意见改）。",
           "【项目方修改意见（原话）】" + g.get("note", "") + "\n\n【现稿】\n" + cur_p.read_text(encoding="utf-8")[-60000:],
           "markdown_episode", [H.RC._rel(cur_p)], r, output_path=op)          # 唯一出包口 packet()（OVERSIGHT-F H4）
    OG.set_status(run_dir, key, "revising", note=g.get("note", ""), handled=True, output=H.RC._rel(op))
    st.stage("EPG", "项目方修改", "revising", "owner", note=g.get("note", "")[:200], output=H.RC._rel(op))
    st.set(verdict="awaiting_writer", next_action=f"等写手按项目方意见改写 ep{ep:02d}")
    return False


FILL_MAX = 3
FILL_MIN_CHARS = 6
TRIVIAL_FILL = {"", "无", "暂无", "没有", "空", "略", "同上", "见上", "none", "None", "null", "NA", "na"}


def fill_note(fields: list[str]) -> str:
    """单一来源在 owner_gate.fill_note（API 的 p1_review 也用它）"""
    return _load("owner_gate", "tools/script_rsi/owner_gate.py").fill_note(fields)


def _path_tokens(path: str) -> list:
    return [int(x[1:-1]) if x.startswith("[") else x for x in re.findall(r"\[\d+\]|[^.\[\]]+", path)]


def _set_path(obj, path: str, value) -> None:
    t = _path_tokens(path)
    for k in t[:-1]:
        obj = obj[k]
    if isinstance(obj, dict) and t[-1] not in obj:
        raise KeyError(t[-1])
    obj[t[-1]] = value


def _get_path(obj, path: str):
    for k in _path_tokens(path):
        obj = obj[k]
    return obj


def diff_paths(a, b, path: str = "") -> list[str]:
    """逐字段 diff：返回所有不一样的叶子路径（列表长度不同 / 类型不同 / 多出或少了的键 = 这个路径本身）"""
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for k in list(a) + [k for k in b if k not in a]:
            sub = f"{path}.{k}" if path else str(k)
            out += diff_paths(a[k], b[k], sub) if (k in a and k in b) else [sub]
        return out
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return [path]
        return [x for i, (p_, q_) in enumerate(zip(a, b)) for x in diff_paths(p_, q_, f"{path}[{i}]")]
    return [] if a == b else [path]


def fill_check(RCH, sl: dict, txt: str, allowed: list[str], ctx: dict):
    """补占位稿收稿：只许改 allowed 里的字段（逐字段 diff），改完重新跑 check_storyline（含 P0-P1 连接）。→ (新故事线 dict | None, 问题列表)"""
    import copy
    d, err = H._json_block(txt)
    if d is None or not isinstance(d, dict):
        return None, [f"不是 JSON：{err}"]
    if isinstance(d.get("fields"), dict):
        new = copy.deepcopy(sl)
        for k, v in d["fields"].items():
            try:
                _set_path(new, str(k), v)
            except (KeyError, IndexError, TypeError):
                return None, [f"字段 {k} 不存在"]
    else:
        new = d                                       # 交了整份故事线：同样逐字段 diff
    changed = diff_paths(sl, new)
    probs = [f"改了不许改的字段：{x}（这一包只补 {', '.join(allowed)}）" for x in changed if x not in allowed]
    for x in allowed:                                  # OVERSIGHT-F P2：补的值要非空、去空白后 ≥ 6 字、不能只是“无”“。”这类
        try:
            v = _get_path(new, x)
        except (KeyError, IndexError, TypeError):
            v = None
        core = re.sub(r"[\s\W_]+", "", str(v or ""))
        if not isinstance(v, str) or len(re.sub(r"\s+", "", v)) < FILL_MIN_CHARS or core in TRIVIAL_FILL or len(core) < 2:
            probs.append(f"{x} 补的内容太短或是空话（{str(v)[:20]!r}）：要写成至少 {FILL_MIN_CHARS} 个字的具体内容")
    probs += [f"{x} 没补" for x in allowed if x not in changed]
    if probs:
        return None, probs
    rep, obj, _ = RCH.validate("P0-P1", json.dumps(new, ensure_ascii=False), ctx)
    if not rep.ok:
        return None, [f"{i.rule} {i.field}：{i.message}" for i in rep.issues if i.level == "block"][:20]
    return new, []                                    # 写回的是原结构只改了那几个字段的 JSON（不经 model_dump，免得补出默认字段）


def _p1_fill(RCH, run_dir: Path, ep: int, st, ctx: dict, canon: Path, sl: dict) -> bool:
    """补占位（总调度 11-02）：项目方点了“用这版”，但这一稿只剩 SL-12 占位词 → 出“补占位”小包，只许改含占位词的字段；
    不进三评委；收稿逐字段 diff + 重跑 check_storyline，过了写回正式稿（评审 / 转交记录的 sha 跟着换，审计记 placeholder_fills），再进 P2。"""
    fields = st.d["p1_owner_hold_fields"]
    note = fill_note(fields)
    sl = json.loads(canon.read_text(encoding="utf-8"))   # 逐字段 diff 的基准 = 正式稿文件本身（不是补了默认值的模型）
    step, k = "P1_fill", attempts(run_dir, "P1_fill")
    base_sha = _sha(canon.read_text(encoding="utf-8"))
    cur_vals = {f: _get_path(sl, f) for f in fields}
    user = ("项目方已经选了这一版故事线（用这版）。只有下面这几个字段还留着占位词，请把它们写成具体内容，其余字段一个字都不许动。\n"
            "【要补的字段（现在的写法）】\n" + "\n".join(f"- {f}：{v}" for f, v in cur_vals.items())
            + "\n\n【交稿格式】只交 JSON：{\"fields\": {\"" + fields[0] + "\": \"补好的文字\"" + (", …" if len(fields) > 1 else "") + "}}"
            + "\n\n【整份故事线（只读参考，按里面已有的人物、场景、前后集写）】\n" + json.dumps(sl, ensure_ascii=False)[:20000])
    system = "你是这部剧的写手。这是一个“补占位”小包：只补指定字段，不改剧情、不改其它字段；不留任何占位词（未提供 / 待定 / TODO / XXX / <…>）。"
    pk_prev = json.loads((run_dir / WT / f"{step}_a{k}.json").read_text(encoding="utf-8")) if k else None
    if pk_prev is None or pk_prev.get("base_sha") != base_sha or pk_prev.get("fields") != fields:
        packet(run_dir, st, step, "writer", ep, "P1-fill", system, user, "json", [], k + 1, {"base_sha": base_sha, "fields": fields})
        st.stage("P1F", "补占位", "awaiting_writer", "agent", step=step, attempt=k + 1, fields=fields)
        st.set(next_action="写手在补：" + note)
        return False
    txt = ready(out_path(run_dir, step, k, "json"))
    if txt is None:
        st.stage("P1F", "补占位", "awaiting_writer", "agent", step=step, attempt=k, fields=fields)
        st.set(verdict="awaiting_writer", next_action="写手在补：" + note)
        return False
    new, probs = fill_check(RCH, sl, txt, fields, ctx)
    if probs:
        if k >= FILL_MAX:
            st.stage("P1F", "补占位", "escalated", "code", attempt=k, problems=probs[:10])
            st.set(verdict="p1_fill_failed", awaiting=None, next_action=f"补占位交了 {k} 次都没过，转总调度")
            live_note(f"{run_dir.name} P1 补占位交了 {k} 次都没过（{'；'.join(probs[:3])}），转总调度")
            return False
        packet(run_dir, st, step, "writer", ep, "P1-fill", system,
               user + "\n\n【上一版补占位稿没收（原因）】\n" + "\n".join(f"- {x}" for x in probs[:20]), "json", [], k + 1,
               {"base_sha": base_sha, "fields": fields})
        st.stage("P1F", "补占位", "repair_requested", "code", step=step, attempt=k + 1, problems=probs[:10])
        st.set(next_action="写手在补：" + note)
        return False
    old_text = canon.read_text(encoding="utf-8")
    canon.rename(canon.with_name(canon.stem + f".prefill{time.strftime('%H%M%S')}" + canon.suffix))
    AF.write_json(canon, new)
    new_sha = _sha(canon.read_text(encoding="utf-8"))
    sp = run_dir / REVIEW_STATE
    if sp.exists():                                   # 这一稿内容（除了补的字段）没变：评审结果和转交记录跟着指向新 sha，不再进三评委
        state = json.loads(sp.read_text(encoding="utf-8"))
        old_sha = _sha(old_text)
        if (state.get("owner_direction") or {}).get("sha") == old_sha:
            state["owner_direction"]["sha"] = new_sha
        if state.get("rounds") and state["rounds"][-1].get("sha") == old_sha:
            state["rounds"][-1]["sha"] = new_sha
        state.setdefault("placeholder_fills", []).append({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "old_sha": old_sha, "new_sha": new_sha,
                                                          "fields": fields, "packet": f"{step}_a{k}"})
        AF.write_json(sp, state)
    ctx["storyline"] = RCH.validate("P0-P1", json.dumps(new, ensure_ascii=False), ctx)[1]
    st.set(p1_owner_hold=None, p1_owner_hold_fields=None)
    st.stage("P1F", "补占位", "ok", "agent", step=step, attempt=k, fields=fields)
    live_note(f"{run_dir.name} P1 补占位完成（{'、'.join(fields)}），重跑 check_storyline 通过，进 P2")
    return True


def _p1_owner_hold(RCH, run_dir: Path, canon: Path, ctx: dict, st):
    """P1 已在项目方手里（总调度转项目方定方向 / 项目方已通过）时，后加的规则（如 SL-12 占位词）不能让系统自动出返修包、
    绕过项目方：只要不合格项全是“新规则”这一类，就沿用这一稿并把问题挂在状态里给项目方看；其余格式错照旧返修。"""
    OG_ = _load("owner_gate", "tools/script_rsi/owner_gate.py")
    if not (OG_.owner_direction(run_dir) or OG_.get(run_dir, "P1").get("status") == "approved"):
        return None
    rep, obj, _ = RCH.validate("P0-P1", canon.read_text(encoding="utf-8"), ctx)
    blocks = [i for i in rep.issues if i.level == "block"]
    if obj is None or not blocks or any(i.rule not in OWNER_HOLD_RULES for i in blocks):
        return None
    st.set(p1_owner_hold=[f"{i.rule} {i.field}：{i.message}"[:200] for i in blocks],
           p1_owner_hold_fields=sorted({i.field for i in blocks if i.rule == "SL-12"}))
    return obj


OWNER_HOLD_RULES = {"SL-12"}


def non_tl_blocking(rep) -> int:
    """P4 阻断数，不算时间轴项 [TL-<镜>]（按镜可补，TIMELINE-O：补丁环每镜一条，不触发整集重写）。
    MERGE-VID-O（ISS-1103-030828-21b8，总调度裁定）：有 V2 硬阻断（p4_adapter rep.hard_blocks：QW-T1 单镜 >6 秒 / QW-C1 运镜不在本剧词表）
    → 99：chain_step / intake_full_p4 / patchable_p4 的“≤6 条阻断照样收稿”一律不适用"""
    if getattr(rep, "hard_blocks", None):
        return 99
    return sum(1 for i in rep.issues if i.level == "block" and not (i.message or "").startswith("[TL-"))


def patchable_p4(RCH, canon: Path, ctx: dict) -> bool:
    """已有 P4 现在不过校验，但除时间轴项外阻断 ≤ 6 → 交补丁环"""
    rep, obj, _ = RCH.validate("P3-P4", canon.read_text(encoding="utf-8"), ctx)
    return obj is not None and non_tl_blocking(rep) <= 6


def chain_step(RCH, run_dir: Path, ep: int, st, ctx: dict) -> bool:
    """P1→P4；返回 True = 四段都齐（可进后处理），False = 在等写手"""
    key = {"P0-P1": "storyline", "P1-P2": "outline", "P2-P3": "screenplay", "P3-P4": "p4"}
    for link, node, name in AF.LINKS:
        canon = run_dir / dict(RCH.STAGES)[link].format(ep=ep)
        if link == "P0-P1":
            st.set(p1_owner_hold=None, p1_owner_hold_fields=None)
        obj = RCH._load_ok(canon, link, ctx)
        if obj is None and link == "P0-P1" and canon.exists():
            obj = _p1_owner_hold(RCH, run_dir, canon, ctx, st)
        rep_p = canon.parent / f"{canon.name}.report.json"
        if obj is None and link == "P3-P4" and canon.exists() and rep_p.exists():
            pr_ = json.loads(rep_p.read_text(encoding="utf-8"))
            # TIMELINE-O：新规则（如时间轴 TL-<镜>）让旧稿不过 → 进补丁环，不打回整集重写。
            # K211-F 11-03（REVIEW-A P1①）：不再信旧 report.json 的 blocking≤6——它没有 hard_blocks（QW-T1 / QW-C1），会绕过 MERGE-VID-O 的硬阻断；
            # 一律按现行规则重验（patchable_p4 → non_tl_blocking，有硬阻断 = 99 不收）
            if patchable_p4(RCH, canon, ctx):
                t_ = canon.read_text(encoding="utf-8")
                ctx[key[link]] = t_[t_.find("## ep"):] if "## ep" in t_ else t_
                st.stage(node, name, "needs_patch", "code", output=H.RC._rel(canon))
                continue
        if obj is not None:
            st.stage(node, name, "reused", "code", output=H.RC._rel(canon))
            ctx[key[link]] = obj
            if link == "P0-P1" and not p1_gate(RCH, run_dir, ep, st, ctx, canon):
                return False
            continue
        step = "P1" if link == "P0-P1" else f"{node}_ep{ep:02d}"
        kind = RCH.chain()["links"][link]["writer"]["output"]
        fmt = "json" if kind == "json" else "markdown_episode"
        k = attempts(run_dir, step)
        pr = RCH.WP.build(link, ctx)
        if k:
            if link == "P3-P4":
                l141_fix(run_dir, out_path(run_dir, step, k, fmt), st, "chain_step", need_done=True)   # MIGRATE-O：镜内 At 先迁
                segment_fix(run_dir, out_path(run_dir, step, k, fmt), st, "chain_step", need_done=True)   # K-WRT-213：段落漏标先按 P3 补
            txt = ready(out_path(run_dir, step, k, fmt))
            if txt is None:
                st.stage(node, name, "awaiting_writer", "api_model", step=step, attempt=k)
                return False
            rep, obj, extra = RCH.validate(link, txt, ctx)
            blocking = rep.as_dict()["blocking"]
            if rep.ok or (link == "P3-P4" and obj is not None and non_tl_blocking(rep) <= 6):
                if kind == "json":
                    AF.write_json(canon, obj.model_dump(mode="json", by_alias=True))
                    AF.write_json(rep_p, {"link": link, "status": "ok" if rep.ok else "needs_writer", "rounds": [{"round": k, "blocking": blocking}],
                                          "report": rep.as_dict(), "writer": "claude_agent"})
                else:
                    # K211-F 11-03（总调度裁定 B / L-150）：P4 新稿一律走 adopt_full_p4——旧 P4 / final 改名留档、补丁环状态清零、patch_base 重置。
                    # 之前这里只覆盖 P4_epNN.md，不碰 final.md，补丁环继续补旧 final（03:42 实测：a4 成了 canon，final 还是旧稿）
                    from ns_recipes.spec_import import rules_version, stamp
                    adopt_full_p4(run_dir, ep, st, stamp(obj, rules_version()), rep, out_path(run_dir, step, k, fmt),
                                  f"P4 写手稿收为正式 P4（阻断 {blocking}，第 {k} 次）", rounds=[{"round": k, "blocking": blocking}])
                st.stage(node, name, "ok" if rep.ok else "needs_patch", "api_model", step=step, attempt=k, blocking=blocking,
                         output=H.RC._rel(canon), decider_note="写手 agent（claude_agent）")
                ctx[key[link]] = obj
                if link == "P0-P1" and not p1_gate(RCH, run_dir, ep, st, ctx, canon):
                    return False
                continue
            user = pr["user"] + "\n\n" + RCH.WP.repair_message([i.as_dict() for i in rep.issues], kind, (extra or "")[:6000])
            packet(run_dir, st, step, "writer", ep, link, pr["system"], user, fmt, [], k + 1)
            st.stage(node, name, "repair_requested", "code", step=step, attempt=k + 1, blocking=blocking)
            return False
        packet(run_dir, st, step, "writer", ep, link, pr["system"], pr["user"], fmt, [], 1)
        st.stage(node, name, "awaiting_writer", "api_model", step=step, attempt=1)
        return False
    return True


def post_step(run_dir: Path, ep: int, st, import_mode: str, RCH=None, ctx: dict | None = None) -> dict:
    from ns_api import script_chat as SC
    wd = run_dir / f"work_ep{ep:02d}"
    wd.mkdir(exist_ok=True)
    p4 = (run_dir / f"P4_ep{ep:02d}.md").read_text(encoding="utf-8")
    body = p4[p4.find("## ep"):] if "## ep" in p4 else p4
    header, _ = SC.script_header(registry={}, run=SC.run_for_dir(run_dir))   # HEADER-O：按本剧推导（L-126）
    pre = header + "\n---\n\n"
    base = body.rstrip() + "\n\n---\n"
    split_p = run_dir / f"P4_ep{ep:02d}.split.md"
    if split_p.exists():
        base = RL.split_doc(split_p.read_text(encoding="utf-8"))[1][0]
    H.ZERO_CODES[:] = ["QW-W11"]
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
            if d_ and d_.get("cannot_fit") and any(t.startswith("dur#") for t in pk.get("targets", [])):
                err = duration_cannot_fit(run_dir, ep, pk, str(d_.get("cannot_fit")))
                d_ = None
            c, changed, err2 = R5.apply_patches(cur, (d_ or {}).get("patches") or [], R5.numbered_lines(cur)) if d_ else (None, [], err)
            if c is None:
                note = err2 or err
            else:
                c = H.mech_align_all(pre, c, ep, wd)
                # K211-F 11-03（REVIEW-A P0，ISS-1103-035043-ec2e）：I6 / I2 / F1 的基线 = 当前已采用的稿 cur（final.md），不是原始 P4_epNN.md——
                # 03:42 实测 canon 被换成 a4 后，用 base 比旧 final 上的补丁，TL 码“变多”全被拒；hard 口径与 hollywood_r5 同一处（R5.hard_checks）
                base_lint = H.lint(cur, ep)
                g = R5.gate5(pre, cur, c, ep, base_lint, wd)
                hard = R5.hard_checks(g)
                # TIMELINE-O 11-03：I2 拿原始 P4（base）比集头；之前已采用过造型行补丁的集，cur 集头本来就和 base 不同，
                # 这次补丁没碰集头（cur == c）也要放过，否则之后所有补丁都卡 I2（patch_ep01_a4 实测）
                if any(x["id"] == "I2" for x in hard) and (head_only_look_lines(cur, c) or (
                        RL.block_text(cur, "head") == RL.block_text(c, "head") and head_only_look_lines(base, cur))):
                    hard = [x for x in hard if x["id"] != "I2"]     # 集头只改了人物造型行（总调度 11-02：事实核对点名的造型补丁走补丁环）
                if hard:
                    note = "；".join(f"{x['id']} {x['name']} 不满足：{x['detail']}" for x in hard)[:1200]
                elif any(t.startswith("cam#") for t in pk.get("targets", [])):
                    # 运镜补丁：只改了那一镜、镜头运动是要的那个、失败项不变多才采用
                    f2 = fitems + AF.all_fails(pre, c, ep, wd)
                    bad = camera_check(cur, c, int(pk.get("camera_shot") or 0), str(pk.get("camera_move") or ""))
                    if bad:
                        note = bad
                    elif len(f2) > len(fails):
                        note = f"补丁后失败项变多（{len(fails)} → {len(f2)}）"
                    else:
                        cur, fails = c, f2
                        final_p.write_text(pre + cur, encoding="utf-8")
                        ag["fact_devs"] = None                  # 改了 H3 / 分拍：整集事实重核兜底
                elif any(t.startswith("dur#") for t in pk.get("targets", [])):
                    # MERGE-VID-O（总调度 11-03）：缩短镜长补丁——只改这一镜的时长 / 分拍 / 表演节拍 / 台词时段 / H3 时间轴；
                    # 时长只许往下改到 ≤ 上限；镜数、镜号、台词不变；失败项不变多才采用
                    f2 = fitems + AF.all_fails(pre, c, ep, wd)
                    bad = duration_check(cur, c, int(pk.get("duration_shot") or 0), float(pk.get("duration_max") or DUR_PATCH_MAX))
                    if bad:
                        note = bad
                    elif len(f2) > len(fails):
                        note = f"补丁后失败项变多（{len(fails)} → {len(f2)}）"
                    else:
                        cur, fails = c, f2
                        final_p.write_text(pre + cur, encoding="utf-8")
                        ag["fact_devs"] = None                  # 改了分拍 / H3：整集事实重核兜底
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
                elif (tl_bad := timeline_check(cur, c, pk.get("targets", []))):
                    note = tl_bad                                # TIMELINE-O：时间轴补丁改到了时间轴以外的行 → 不收
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
                        new_ids = [f"{d2}#{u2['id']} {u2['why'][:160]}" for d2, u2 in f2 if f"{d2}#{u2['id']}" not in {f"{d3}#{u3['id']}" for d3, u3 in fails}]
                        note = (f"补丁后失败项没有变少（{len(fails)} → {len(f2)}）"
                                + ("；补丁引入了新的失败项：" + "；".join(new_ids) if new_ids else ""))     # 22:26 patch_ep01_a1：只说“没变少”写手不知道改哪
        st.d.setdefault("agent_history", []).append({"step": f"{step_base}_a{k}", "accepted": not note, "note": note[:300], "fails": len(fails)})
        st.save()
        if note:
            ag["last_note"] = note
    if not final_p.exists():
        final_p.write_text(pre + cur, encoding="utf-8")
    if fails and (l141_fix(run_dir, final_p, st, "patch_loop") or {}).get("changed"):     # MIGRATE-O：镜内 At 不派补丁，代码迁
        cur = RL.split_doc(final_p.read_text(encoding="utf-8"))[1][0]
        fails = fitems + AF.all_fails(pre, cur, ep, wd)
    if fails and (segment_fix(run_dir, final_p, st, "patch_loop") or {}).get("changed"):  # K-WRT-213：段落漏标不派补丁，按 P2/P3 补
        cur = RL.split_doc(final_p.read_text(encoding="utf-8"))[1][0]
        fails = fitems + AF.all_fails(pre, cur, ep, wd)
    code_n =len([f for f in fails if f[0] not in ("p4", "fact")])
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
        # STRUCT-O 11-03（L-158）：结构项（整段字段缺失 / 镜数 / 镜长 / 确认补丁不可修）逐行补丁改不了 → 第一次出现就转整集返修包，
        # 不先把补丁预算白耗满 10 次；整集稿交回照常 intake_full_p4 → adopt_full_p4 → l141_fix / segment_fix → 补丁环
        sr = structural_rewrite(run_dir, ep, st, cur, fails, facts, RCH, ctx)
        if sr is not None:
            if not sr.get("ok"):          # 整集返修试满 FULL_REWRITE_MAX 次仍有结构项 → 诊断 + 卡点交总调度
                patch_exhausted(run_dir, ep, st, fails, attempts(run_dir, step_base), sr["why"])
            return st.d
        if patch_budget_used(run_dir, ep, ag) >= PATCH_MAX:       # K211-F：按 reopen 基线算，用满 → 写诊断 + 登记卡点，不再静默停住
            patch_exhausted(run_dir, ep, st, fails, k, f"补丁已出 {k} 次（本轮预算 {PATCH_MAX}）仍有 {len(fails)} 项失败")
            return st.d
        targets = [(d, u) for d, u in fails if ag["used"].get(f"{d}#{u['id']}", 0) < AF.ITEM_TRIES and f"{d}#{u['id']}" not in AF.STRUCTURAL][:2]
        if not targets:
            patch_exhausted(run_dir, ep, st, fails, k, f"剩下的 {len(fails)} 项失败都已试满 ITEM_TRIES={AF.ITEM_TRIES}（或是镜数这类结构项）")
            return st.d
        for d, u in targets:
            ag["used"][f"{d}#{u['id']}"] = ag["used"].get(f"{d}#{u['id']}", 0) + 1
        user = AF.patch_user(ep, pre, cur, facts, targets, ag.pop("last_note", ""))
        packet(run_dir, st, step_base, "writer", ep, "patch", R5.r5_writer_system(), user, "patches_json", [H.RC._rel(final_p)], k + 1,
               {"base_sha": _sha(cur), "targets": [f"{d}#{u['id']}" for d, u in targets]})
        return st.d
    # 失败项清零 → 先出排队的缩短镜长补丁（MERGE-VID-O），再出运镜补丁（总调度 11-02：排在补丁环后面，一次只出一个包）
    if ag.get("duration_queue"):
        if _duration_from_queue(run_dir, ep, st) is not None and st.d.get("awaiting"):
            return st.d
    if ag.get("camera_queue"):
        if _camera_from_queue(run_dir, ep, st) is not None and st.d.get("awaiting"):
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
        st.set(verdict="not_importable", awaiting=None, next_action="P4 阻断未清零")
        return st.d
    regen = regen_header(run_dir, final_p, pre, cur)       # TIMELINE-O：成稿集头一律按本剧 script_header 重生（旧稿先隔离备份）
    if regen:
        st.set(header_regen=regen)
    v1_left = final_v1_hits(run_dir, final_p)              # 成稿 P4 不许出现旧剧 id（复用 script_chat.assert_no_v1，L-126）
    RA = _load("rubric_audit", "tools/script_rsi/rubric_audit.py")
    rg = RA.gate(final_p)
    v = AF.FR.validate_json(final_p)
    gate_ok = rg["ok"] and not v.get("blocking") and not v1_left
    st.stage("gate", "导入闸门", "ok" if gate_ok else "blocked", "code", rubric_ok=rg["ok"], validate_blocking=v.get("blocking"),
             **({"v1_ids": v1_left} if v1_left else {}))
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
        if not re_.get("ok"):            # MERGE-OPS-O：记下失败时导入器那边的指纹，修好后 pending_done 下一拍自动重导，没修不空转
            st.set(import_fail_sig=AF.import_retry_sig(run_dir.name), import_fail_detail=str(re_.get("out") or re_.get("detail") or "")[:300])
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
    # K211-F 11-03：PATCH_MAX 之前按 writer_tasks/patch_epNN_a*.json 的文件数算，reopen 不删文件 → 重开后第一拍又用满。
    # 现在 reopen 记下基线（已出包数），post_step 用 patch_budget_used = 文件数 − 基线
    ag["patch_base"] = attempts(run_dir, f"patch_ep{ep:02d}")
    st.d["structural_rewrite_base"] = len(st.d.get("structural_rewrites") or [])     # STRUCT-O：整集返修次数也按 reopen 基线算
    st.d.setdefault("agent_history", []).append({"step": "reopen", "accepted": True, "manual": True, "by": by,
                                                 "note": f"manual 重开补丁预算：{why}"[:300], "used_before": before, "patch_base": ag["patch_base"]})
    st.set(verdict="reopened", next_action="已重开补丁预算，跑 autoflow run 继续")
    st.save()
    return {"ok": True, "used_before": before, "patch_base": ag["patch_base"]}


def patch_budget_used(run_dir: Path, ep: int, ag: dict) -> int:
    """这一轮补丁环已出的包数 = patch_epNN_a*.json 文件数 − 上次 reopen 的基线（K211-F）"""
    return attempts(run_dir, f"patch_ep{ep:02d}") - int(ag.get("patch_base") or 0)


def patch_diagnosis(run_dir: Path, ep: int, st, fails: list, k: int, why: str) -> dict:
    """补丁环用满后的诊断（K211-F 11-03，series10_v2 ep01 实测：k211#2 一次都没出过包，预算被 v3#1 / cam#2 / 8 条 TL-* 耗完，
    系统却只写了一句“交总调度”）。只读状态，不改稿：剩余失败项 + 逐项已试次数 + 从没出过包的项 + 每次补丁的采用 / 拒收原因 + 改进方案"""
    ag = st.d.get("agent") or {}
    used = ag.get("used") or {}
    ids = [f"{d}#{u['id']}" for d, u in fails]
    never = [i for i in ids if not used.get(i)]
    tried_out = [i for i in ids if used.get(i, 0) >= AF.ITEM_TRIES]
    auto = [f"{d}#{u['id']}" for d, u, _k in structural_items(fails, ag)]          # STRUCT-O：会自动转整集返修的结构项
    structural = [i for i in ids if i in auto or i.startswith(("p4#QW-C1", "dur#"))]
    hist = [h for h in st.d.get("agent_history") or [] if str(h.get("step", "")).startswith(f"patch_ep{ep:02d}")]
    rejected = [h for h in hist if h.get("accepted") is False]
    reasons: dict[str, int] = {}
    for h in rejected:
        key = (h.get("note") or "")[:40]
        reasons[key] = reasons.get(key, 0) + 1
    plan = []
    if never:
        plan.append(f"{len(never)} 项从没出过补丁包（{', '.join(never[:6])}）：预算被别的项耗尽，不是写手修不好 → "
                    f"总调度确认后 `autoflow.py reopen --episode {ep} --why ...` 重开预算（基线重置），下一轮先补这些项")
    if tried_out:
        plan.append(f"{len(tried_out)} 项试满 ITEM_TRIES={AF.ITEM_TRIES} 仍失败（{', '.join(tried_out[:6])}）："
                    "先核对检查代码是否误判 V2 写法（看 why 里引用的原文），再看补丁包有没有给目标行 + 正确写法；误判 → 修检查 + 加测试，不是再出包")
    if auto:
        plan.append(f"{len(auto)} 项是结构项（缺段 / 镜数 / 镜长 / 确认补丁不可修：{', '.join(auto[:6])}）：daemon 自动出整集返修包（L-158，"
                    f"writer_out/P4_ep{ep:02d}_a<k>.md，intake_full_p4 收）；整集返修已试满 {FULL_REWRITE_MAX} 次才走到这里 → 总调度看返修稿被拒原因")
    if [i for i in structural if i not in auto]:
        plan.append(f"{len(structural) - len(auto)} 项走专用小包（运镜词表 / 缩短镜长：{', '.join(i for i in structural if i not in auto)}）：camera-patch / duration_patch")
    if reasons:
        top = max(reasons.items(), key=lambda x: x[1])
        plan.append(f"补丁被拒 {len(rejected)} 次，最多的原因“{top[0]}”×{top[1]}：若是闸门不变量（I2 / I6）或改到范围外的行，属补丁包说明不清，把该不变量写进包")
    return {"schema": "nsfs.patch_diag/1", "run": run_dir.name, "episode": ep, "at": time.strftime("%F %T"), "why": why,
            "packets": k, "patch_max": PATCH_MAX, "item_tries": AF.ITEM_TRIES, "patch_base": int(ag.get("patch_base") or 0),
            "fails": [{"id": f"{d}#{u['id']}", "shots": u.get("shots"), "tries": used.get(f"{d}#{u['id']}", 0), "why": (u.get("why") or "")[:400]} for d, u in fails],
            "used": used, "never_targeted": never, "tried_out": tried_out, "structural": structural,
            "history": [{k2: h.get(k2) for k2 in ("step", "accepted", "note", "fails")} for h in hist],
            "plan": plan}


def patch_exhausted(run_dir: Path, ep: int, st, fails: list, k: int, why: str) -> dict:
    """补丁预算用满 / 剩余项全试满：写诊断（work_epNN/patch_diag.json）+ 登记卡点交总调度（report_issue，同一 k 只登记一次）+ verdict not_importable。
    之前这里只 set 一句 next_action 就 return，总调度看不到为什么、也没人接（K211-F 11-03）"""
    ag = st.d.setdefault("agent", {"processed": [], "used": {}, "fact_devs": None})
    diag = patch_diagnosis(run_dir, ep, st, fails, k, why)
    wd = run_dir / f"work_ep{ep:02d}"
    wd.mkdir(exist_ok=True)
    AF.write_json(wd / "patch_diag.json", diag)
    reported = ag.setdefault("exhausted_reports", [])
    issue_id = next((r.get("issue") for r in reported if r.get("k") == k), None)
    if issue_id is None:
        msg = (f"{why}；剩余 {', '.join(f['id'] for f in diag['fails'][:8])}；从没出过包 {diag['never_targeted'] or '无'}；"
               f"诊断 {H.RC._rel(wd / 'patch_diag.json')}")[:600]
        try:
            RI = _load("report_issue", "tools/master/report_issue.py")
            rec = RI.report(run_dir.name, ep, "5", "autoflow 补丁环", msg, True, fix_hint="；".join(diag["plan"])[:700],
                            issues=RI.ISSUES, live=RI.LIVE)
            issue_id = rec["id"]
        except Exception as e:  # noqa: BLE001  # arch-ok: 登记失败不能把补丁环弄崩，原因写进诊断 / next_action
            issue_id = f"登记失败：{e!r}"[:120]
        reported.append({"k": k, "issue": issue_id, "at": diag["at"]})
        st.d.setdefault("agent_history", []).append({"step": f"patch_ep{ep:02d}_exhausted", "accepted": None, "note": f"{why}；卡点 {issue_id}"[:300],
                                                     "fails": len(fails)})
    st.set(verdict="not_importable", awaiting=None,
           next_action=f"{why}，已登记卡点 {issue_id} 交总调度；诊断 {H.RC._rel(wd / 'patch_diag.json')}；方案：{'；'.join(diag['plan'])}"[:600])
    st.save()
    return diag



# ---- STRUCT-O 11-03（L-158，项目方点选；CHANNEL 07:04 / 09:56）：补丁环诊断出结构项 → daemon 自动出整集返修包
FULL_REWRITE_MAX = 2          # 同一集（按 reopen 基线）最多自动出几次整集返修包；再有结构项 → patch_exhausted 交总调度
STRUCT_FIX = {
    "missing_segment": "缺段 → 在点名的镜里补全整段字段：每段单独一行、以字段名开头、按下面的固定顺序插在镜头块里（必填段一个都不能少）；"
                       "旧写法里已有的同类内容（如 **镜头运动** / **光线**）照搬进对应新段，画面、人物、台词不变",
    "shot_length": "镜长超上限（QW-T1，L-137）→ 把这一镜拆成两镜（新镜号顺延，后面各镜重编号），台词逐字分到两镜、说话人和顺序不变；"
                   "每镜 ≤6 秒，**时长** / **分拍** / **表演节拍** / **台词时段** / H3 时间轴按新镜长重写，整集总时长不变",
    "shot_count": "镜数不在本集要求的范围 → 按本集镜数要求增删镜（拆出反应 / 局部 / 承接镜，或合并重复镜），台词逐字、事实不变，各镜字段齐全",
    "unpatchable": "已确认补丁改不了（原因见失败原因原文）→ 这次整集重写时按原因改好",
}


def structural_items(fails: list, ag: dict | None = None) -> list[tuple[str, dict, str]]:
    """失败项里哪些是结构项（逐行补丁改不了）→ [(维度, 项, 种类)]。种类：
    missing_segment = v2#1 缺整段字段（补丁一行换一行，加不出字段行；ep02 v2#1 实测 a11–a13 三轮不动）；
    shot_length = p4#QW-T1 单镜超 6 秒（要拆镜）；shot_count = 镜数（AF.STRUCTURAL / turns#）；
    unpatchable = agent.unpatchable 里登记的项（被确认补丁不可修，如缩短镜长写手交 cannot_fit）。
    运镜词表（QW-C1）/ dur# 有专用小包（camera-patch / duration_patch），不在此列"""
    unp = set((ag or {}).get("unpatchable") or [])
    out = []
    for d, u in fails:
        fid, why = f"{d}#{u['id']}", u.get("why") or ""
        kind = ("unpatchable" if fid in unp else
                "shot_count" if fid in AF.STRUCTURAL or d == "turns" else
                "shot_length" if fid.startswith("p4#QW-T1") else
                "missing_segment" if fid == "v2#1" and re.search(r"缺段：\[[^\]]*镜\d+缺", why) else None)
        if kind:
            out.append((d, u, kind))
    return out


def _segment_format() -> list[str]:
    """镜头块 v2 字段的格式（单一来源 config/director/shot_spec_v2.yaml）"""
    spec = R5.RC6._yaml("shot_spec_v2.yaml")
    return [f"  {s.get('md_label', '')}<{_writer_hint(s)}>" + ("（必填）" if s.get("required") else "（可选）")
            for s in spec.get("segments") or [] if s.get("md_label")]


def _writer_hint(seg: dict) -> str:
    """镜头段只给 lenses.yaml 的镜头 id（单一来源），不给中文名：中文“徕卡”是 V1 S★ 原句标记（config/v1_guard.json，L-145 只放行英文 Leica），
    写进作业包会被 assert_no_v1 失败关闭（11-03 11:58 ep02 L-159 重开即 halted_error ISS-1103-115817-d44f），写进剧本也会被导入闸门挡"""
    if seg.get("id") != "lens":
        return str(seg.get("writer") or "")
    ids = [x.get("id") for x in (R5.RC6._yaml("lenses.yaml").get("lenses") or []) if x.get("id")]
    return f"只写镜头 id（{' / '.join(ids)}，config/director/lenses.yaml）；不写时按景别 + 情绪自动选"


def _timeline_scope() -> str:
    import p4_adapter as _P4
    return _P4.TIMELINE_PATCH_SCOPE


def _l141_rules(run_dir: Path) -> str:
    """L-141 时间轴写法：取写手包同一份（script_chat.timeline_block），取不到用补丁包的同款说明（p4_adapter.TIMELINE_PATCH_SCOPE）"""
    try:
        from ns_api import script_chat as SC
        t = SC.timeline_block(SC.run_for_dir(run_dir) or run_dir.name)
    except Exception as e:  # noqa: BLE001  # arch-ok: 取不到就用同源的补丁包说明，原因写进包
        return f"（timeline_block 取不到：{e!r}）" + _timeline_scope()
    return t or _timeline_scope()


def _segment_rule() -> str:
    """K-WRT-213 段落标记规则（单一来源 config/recipes/writer_knowledge.md 带 [K-WRT-213] 的那条）"""
    wk = (ROOT / "config" / "recipes" / "writer_knowledge.md").read_text(encoding="utf-8")
    return next((ln.strip() for ln in wk.splitlines() if "[K-WRT-213]" in ln),
                "- 每一镜的 **场景** 行细节开头写 【幻想段】 或 【现实段】，按 P2 节拍 / P3 场景的段落标记写")


VERBATIM_LINE = re.compile(r"^\*\*(对白|台词|独白|旁白)\*\*|🎙")


def full_rewrite_brief(run_dir: Path, ep: int, cur: str, fails: list, struct: list, facts: dict, note: str = "") -> str:
    """整集返修包的说明（L-158）：全部未过项原文 + 失败原因、结构项逐种改法（缺段给字段格式）、必须保留（台词逐字 / 事实表 / 未点名内容）、
    L-141 时间轴写法、K-WRT-213 段落标记规则"""
    kinds: dict[str, list] = {}
    for d, u, k in struct:
        kinds.setdefault(k, []).append((d, u))
    out = [f"【整集返修（L-158，系统自动出包）】ep{ep:02d} 补丁环诊断出 {len(struct)} 项结构项（逐行补丁改不了），转整集返修。"
           "在下面【现稿】基础上改，重新输出完整的这一集（从 `## ep` 到 `---`）；只改点名的地方，未点名的镜和行逐字保持，不写解释。", "",
           f"一、未过项（共 {len(fails)} 项，全部要改好；原文 = 系统判定的原话）"]
    for d, u in fails:
        out.append(f"- {d}#{u['id']}（镜 {u.get('shots') or '未指出'}）：{u.get('why') or ''}")
    out += ["", "二、结构项怎么改"]
    for k, items in kinds.items():
        out.append("- " + ", ".join(f"{d}#{u['id']}" for d, u in items) + "：" + STRUCT_FIX[k])
        if k == "missing_segment":
            miss = list(dict.fromkeys(m for _d, u in items for m in re.findall(r"镜\d+缺[^'’，,\]]+", u.get("why") or "")))   # 按判定原文顺序
            out.append("  要补的段：" + "、".join(miss))
            out.append("  字段格式（每段一行，顺序固定）：")
            out += _segment_format()
    out += ["", "三、必须保留",
            "- 台词 / 独白逐字（原文、说话人、条数、顺序都不改；拆镜时只分配到不同镜，不改字）："]
    vl = [ln.strip() for ln in cur.splitlines() if VERBATIM_LINE.search(ln.strip())]
    out += [f"  {ln}" for ln in vl] or ["  （现稿没有台词行）"]
    out += ["- 剧情事实表（已核对通过的事实，硬约束，原样遵守）：", json.dumps(facts or {}, ensure_ascii=False, indent=1),
            "- 集头（剧情 / 出场人物 / 用到的场景 / 造型 / 配乐 / 场景定稿）不改；没列在“未过项”里的检查现在都过了，改完要仍然过。", "",
            "四、L-141 时间轴写法（镜内）", _l141_rules(run_dir), "",
            "五、段落标记规则（K-WRT-213）", _segment_rule()]
    if note:
        out += ["", f"上一次整集返修稿没有被采用：{note}"]
    return "\n".join(out)


def structural_rewrite(run_dir: Path, ep: int, st, cur: str, fails: list, facts: dict, RCH=None, ctx: dict | None = None) -> dict | None:
    """L-158：失败项里有结构项 → 出整集返修包（step P4_epNN，产物 writer_out/P4_epNN_a<k>.md，intake_full_p4 收，adopt_full_p4 换底）。
    → None = 没有结构项（照常补丁环）；{"ok": True} = 已出包 / 在等这一包；{"ok": False, "why"} = 已试满 FULL_REWRITE_MAX 次。
    同一底稿（base_sha）上的包没交 / 交了没收就等着不重出；交了被拒（intake 阻断）→ 带被拒原因再出一次；每次出包写 report_issue + agent_history"""
    ag = st.d.setdefault("agent", {"processed": [], "used": {}, "fact_devs": None})
    struct = structural_items(fails, ag)
    if not struct:
        return None
    recs = st.d.setdefault("structural_rewrites", [])
    step = f"P4_ep{ep:02d}"
    last = recs[-1] if recs else None
    note = ""
    if last and last.get("base_sha") == _sha(cur):
        name = Path(last["output"]).name
        if name not in (ag.get("full_p4_done") or []):        # 还没收：没交稿 / 交了在缓着 → 等，不重出
            st.stage("code", "代码判定 + 补丁", "awaiting_writer", "api_model", fails=len(fails), step=f"{step}_a{last['attempt']}",
                     detail=f"整集返修包（L-158 结构项）等写手：{last['output']}")
            st.set(verdict="awaiting_writer", next_action=f"等写手交整集返修稿 {last['output']}（结构项 {', '.join(last['items'])}）")
            st.save()
            return {"ok": True, "waiting": last["output"]}
        note = next((h.get("note") for h in reversed(st.d.get("agent_history") or [])
                     if h.get("step") == name and h.get("accepted") is False), "") or "交回后仍有结构项"
    used = len(recs) - int(st.d.get("structural_rewrite_base") or 0)
    ids = [f"{d}#{u['id']}" for d, u, _k in struct]
    if used >= FULL_REWRITE_MAX:
        return {"ok": False, "why": f"整集返修包已出 {used} 次（上限 {FULL_REWRITE_MAX}）仍有结构项 {', '.join(ids)}"}
    if RCH is not None and ctx is not None:
        pr = RCH.WP.build("P3-P4", ctx)
    else:
        pr = {"system": "你是这部剧的编剧。这一集要整集返修（剧情事实以 P1–P3 为准），按下面的返修说明改。", "user": ""}
    kinds = sorted({x[2] for x in struct})
    brief = full_rewrite_brief(run_dir, ep, cur, fails, struct, facts, note)
    k = attempts(run_dir, step) + 1
    user = (pr["user"] + "\n\n" if pr.get("user") else "") + brief + "\n\n【现稿（整集返修的底稿）】\n" + cur
    pk = packet(run_dir, st, step, "writer", ep, "P3-P4", pr["system"], user, "markdown_episode", [], k,
                {"base_sha": _sha(cur), "targets": ids, "full_rewrite": "L-158", "structural": kinds})
    rec = {"attempt": k, "output": pk["output"]["path"], "base_sha": _sha(cur), "items": ids, "kinds": kinds,
           "at": time.strftime("%F %T"), "rejected_note": note[:200] or None}
    msg = (f"补丁环诊断出结构项 {', '.join(ids)}（{'、'.join(kinds)}），逐行补丁改不了 → 已自动出整集返修包 {step}_a{k}"
           f"（{pk['output']['path']}；第 {used + 1}/{FULL_REWRITE_MAX} 次），交回后 intake_full_p4 → adopt → l141_fix / segment_fix → 补丁环")[:600]
    try:
        RI = _load("report_issue", "tools/master/report_issue.py")
        rec["issue"] = RI.report(run_dir.name, ep, "5", "autoflow 结构项→整集返修（L-158）", msg, False,
                                 fix_hint="系统已自动处理，派单器派写手即可；返修稿被拒会带原因再出一次，试满交总调度",
                                 issues=RI.ISSUES, live=RI.LIVE)["id"]
    except Exception as e:  # noqa: BLE001  # arch-ok: 登记失败不挡出包，原因记进留痕
        rec["issue"] = f"登记失败：{e!r}"[:120]
    recs.append(rec)
    st.d.setdefault("agent_history", []).append({"step": f"{step}_a{k}", "accepted": None, "by": "structural_rewrite",
                                                 "note": (f"L-158 结构项转整集返修：{', '.join(ids)}；卡点 {rec['issue']}"
                                                          + (f"；上一次被拒：{note}" if note else ""))[:300], "fails": len(fails)})
    st.stage("code", "代码判定 + 补丁", "awaiting_writer", "api_model", fails=len(fails), step=f"{step}_a{k}",
             detail=f"结构项 {', '.join(ids)} → 整集返修包 {step}_a{k}")
    st.set(verdict="awaiting_writer", next_action=f"结构项 {', '.join(ids)} 逐行补丁改不了，已出整集返修包 {step}_a{k}，等写手交稿（L-158）")
    st.save()
    return {"ok": True, "packet": H.RC._rel(run_dir / WT / f"{step}_a{k}.json"), "output": pk["output"]["path"], "issue": rec["issue"]}


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
    header, _ = SC.script_header(registry={}, run=SC.run_for_dir(run_dir))   # HEADER-O：按本剧推导（L-126）
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


LOOK_LINE = re.compile(r"^\*\*造型｜[^*]+\*\*：")


def _head_lines(doc: str) -> list[str]:
    """集头 = 第一镜（**镜1｜）之前的行"""
    out = []
    for ln in doc.splitlines():
        if re.match(r"\*\*镜\d+｜", ln):
            break
        out.append(ln)
    return out


def head_only_look_lines(old: str, new: str) -> bool:
    """补丁对集头的改动是否只落在人物造型行（**造型｜<人名>**：…）：行数、行序、人名都不变，非造型行逐字不变"""
    a, b = _head_lines(old), _head_lines(new)
    if len(a) != len(b) or a == b:
        return False
    for x, y in zip(a, b):
        if x == y:
            continue
        mx, my = LOOK_LINE.match(x), LOOK_LINE.match(y)
        if not (mx and my and mx.group(0) == my.group(0)):
            return False
    return True


def _shot_block(doc: str, shot: int) -> tuple[int, int] | None:
    """P4 正文里第 shot 镜的行号范围 [起, 止)（从 **镜N｜ 到下一镜 / 文末）"""
    lines = doc.splitlines()
    starts = [i for i, ln in enumerate(lines) if re.match(r"\*\*镜\d+｜", ln)]
    idx = [i for i in starts if re.match(rf"\*\*镜{shot}｜", lines[i])]
    if not idx:
        return None
    nxt = [i for i in starts if i > idx[0]]
    return idx[0], (nxt[0] if nxt else len(lines))


def _shot_move(doc: str, shot: int) -> str | None:
    rg = _shot_block(doc, shot)
    if not rg:
        return None
    for ln in doc.splitlines()[rg[0]:rg[1]]:
        if ln.startswith("**镜头运动**："):
            return ln.split("：", 1)[1].split("｜")[0].strip()
    return None


def camera_names(move_id: str) -> set[str]:
    """camera_moves.yaml（唯一来源）里这个运镜认的写法：id / zh / aliases"""
    import yaml
    d = yaml.safe_load((ROOT / "config/director/camera_moves.yaml").read_text(encoding="utf-8")) or {}
    for m in d.get("moves") or d.get("camera_moves") or []:
        if isinstance(m, dict) and m.get("id") == move_id:
            return {m["id"], str(m.get("zh") or "")} | {str(x) for x in m.get("aliases") or []} - {""}
    return set()


def camera_check(old: str, new: str, shot: int, move_id: str) -> str:
    """运镜补丁收稿：只许改第 shot 镜那一块；那一镜的镜头运动要写成 move_id 认的写法。合格返回空串"""
    rg_o, rg_n = _shot_block(old, shot), _shot_block(new, shot)
    if not rg_o or not rg_n:
        return f"找不到镜{shot}"
    lo, ln_ = old.splitlines(), new.splitlines()
    if lo[:rg_o[0]] != ln_[:rg_n[0]] or lo[rg_o[1]:] != ln_[rg_n[1]:]:
        return f"改到了镜{shot}以外的行（这一包只改镜{shot}的运镜）"
    got = _shot_move(new, shot)
    names = camera_names(move_id)
    if got not in names:
        return f"镜{shot}的镜头运动写成了「{got}」，要写 {move_id}（认：{' / '.join(sorted(names))}）"
    return ""


TL_LINE_RE = re.compile(r"^\s*(?:\*\*分拍\*\*：|\*\*表演节拍\*\*：|integrated_multimodal_description:)")


def timeline_check(old: str, new: str, targets: list[str]) -> str:
    """TIMELINE-O：补丁目标全是时间轴（p4#TL-<镜>）时，只许改这些镜的 **分拍** / **表演节拍** / H3 正文行。合格 / 不是时间轴补丁 → 空串"""
    shots = sorted({int(t.split("TL-")[1]) for t in targets if t.startswith("p4#TL-") and t.split("TL-")[1].isdigit()})
    if not shots or len(shots) != len(targets):
        return ""
    lo, ln_ = old.splitlines(), new.splitlines()
    if len(lo) != len(ln_):
        return "时间轴补丁改变了行数（只许整行替换分拍 / 表演节拍 / H3 正文行）"
    rngs = [r for r in (_shot_block(old, s) for s in shots) if r]
    for i, (a, b) in enumerate(zip(lo, ln_)):
        if a == b:
            continue
        if not any(r[0] <= i < r[1] for r in rngs):
            return f"时间轴补丁改到了镜{'、'.join(map(str, shots))}以外的行：{a[:40]}"
        if not (TL_LINE_RE.match(a) and TL_LINE_RE.match(b)):
            return f"时间轴补丁改到了分拍 / 表演节拍 / H3 正文以外的行：{a[:40]}"
    return ""


def regen_header(run_dir: Path, final_p: Path, pre: str, cur: str) -> dict | None:
    """成稿集头 ≠ 本剧 script_header（如 V2 第 1 集还带着 V1《漆皮之下·十日》头）→ 旧稿复制进 data/_quarantine/header_regen_<日期>/
    再写 pre + cur（镜头区原样不动）。集头一致 → None"""
    old = final_p.read_text(encoding="utf-8")
    if old == pre + cur:
        return None
    qd = ROOT / "data" / "_quarantine" / f"header_regen_{time.strftime('%Y%m%d')}" / run_dir.name
    qd.mkdir(parents=True, exist_ok=True)
    bak = qd / f"{final_p.stem}.{time.strftime('%H%M%S')}.md"
    bak.write_text(old, encoding="utf-8")
    final_p.write_text(pre + cur, encoding="utf-8")
    return {"backup": H.RC._rel(bak), "at": time.strftime("%F %T")}


def final_v1_hits(run_dir: Path, final_p: Path) -> str:
    """成稿 P4（集头 + 镜头区）出现旧剧内容 → 原因（script_chat.assert_no_v1 的同一份词表）；没有 / legacy 剧 → 空串"""
    from ns_api import script_chat as SC
    try:
        SC.assert_no_v1(final_p.read_text(encoding="utf-8"), run=SC.run_for_dir(run_dir) or run_dir.name, what=f"成稿 {final_p.name}")
    except SC.HeaderMissing as e:
        return str(e)
    return ""


def camera_patch(run_dir: Path, ep: int, shot: int, move_id: str, why: str = "") -> dict:
    """只改运镜的小返修包（总调度 11-02：第 1 集幻想段镜 2 换 bolt_push_settle）。
    排队规则（总调度 11-02：不要两个包同时出、基准打架）：这一集补丁环还在跑（有没处理完的 patch 包 / 还有失败项 / 还没进补丁环）→
    只记进 agent.camera_queue，等补丁环失败项清零后由 post_step 出包；补丁环空闲才立刻出包。
    产物回来走 post_step 的补丁处理：闸门不变量过 + 只改了这一镜 + 镜头运动是这个运镜 + 失败项不变多 → 采用，事实重核"""
    if not camera_names(move_id):
        return {"ok": False, "why": f"camera_moves.yaml 里没有 {move_id}"}
    st = AF.Status(run_dir, ep, 0.0)
    ag = st.d.setdefault("agent", {"processed": [], "used": {}, "fact_devs": None})
    req = {"shot": int(shot), "move": move_id, "why": why, "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    final_p = run_dir / f"P4_ep{ep:02d}.final.md"
    step_base = f"patch_ep{ep:02d}"
    k = attempts(run_dir, step_base)
    busy = (not final_p.exists()) or (k and f"{step_base}_a{k}" not in ag["processed"]) or bool((st.d.get("rubric_code_fail") or {}).get("n"))
    q = [x for x in ag.get("camera_queue") or [] if not (x["shot"] == req["shot"])] + [req]
    if busy:
        ag["camera_queue"] = q
        st.save()
        return {"ok": True, "queued": True, "why": "这一集补丁环还在跑（或还没进补丁环），运镜包排在它后面，失败项清零后自动出", "queue": q}
    ag["camera_queue"] = q
    out = _camera_from_queue(run_dir, ep, st)
    return {"ok": True, **(out or {})}


def _camera_from_queue(run_dir: Path, ep: int, st) -> dict | None:
    """从 agent.camera_queue 取第一条出运镜补丁包（补丁环空闲时调用）。没有排队 = None"""
    from ns_api import script_chat as SC
    ag = st.d.setdefault("agent", {"processed": [], "used": {}, "fact_devs": None})
    q = ag.get("camera_queue") or []
    if not q:
        return None
    req = q.pop(0)
    ag["camera_queue"] = q
    shot, move_id, why = req["shot"], req["move"], req.get("why") or ""
    final_p = run_dir / f"P4_ep{ep:02d}.final.md"
    header, _ = SC.script_header(registry={}, run=SC.run_for_dir(run_dir))   # HEADER-O：按本剧推导（L-126）
    pre = header + "\n---\n\n"
    cur = RL.split_doc(final_p.read_text(encoding="utf-8"))[1][0]
    if not _shot_block(cur, shot):
        st.save()
        live_note(f"{run_dir.name} 第 {ep} 集运镜补丁：找不到镜{shot}，这一条作废")
        return {"skipped": f"找不到镜{shot}"}
    import yaml
    mv = next(m for m in (yaml.safe_load((ROOT / "config/director/camera_moves.yaml").read_text(encoding="utf-8")) or {}).get("moves") or []
              if isinstance(m, dict) and m.get("id") == move_id)
    facts_p = run_dir / f"facts_ep{ep:02d}.json"
    facts = json.loads(facts_p.read_text(encoding="utf-8")) if facts_p.exists() else {"lines": []}
    target = ("cam", {"id": f"CAM-{shot}", "why": (
        f"{why}只改镜{shot}的运镜：**镜头运动** 写成「{mv.get('zh')}」（词表 id {move_id}），**运镜** 行按它改写起幅 / 落幅，"
        f"必要时连带改这一镜的分拍节奏和 H3 提示词里描述镜头运动的那一句（英文模板：{mv.get('template')}；适用景别 {'、'.join(mv.get('sizes') or [])}）。"
        f"这一镜以外的任何一行都不许动；剧情、台词、人物、造型都不变。")})
    step_base = f"patch_ep{ep:02d}"
    k = attempts(run_dir, step_base)
    user = AF.patch_user(ep, pre, cur, facts, [target], "")
    pk = packet(run_dir, st, step_base, "writer", ep, "patch", R5.r5_writer_system(), user, "patches_json", [H.RC._rel(final_p)], k + 1,
                {"base_sha": _sha(cur), "targets": [f"cam#{shot}"], "camera_shot": shot, "camera_move": move_id})
    st.stage("code", "代码判定 + 补丁", "awaiting_writer", "api_model", step=f"{step_base}_a{k + 1}", detail=f"运镜补丁：镜{shot} → {move_id}")
    st.d.setdefault("agent_history", []).append({"step": f"{step_base}_a{k + 1}", "accepted": None, "note": f"运镜补丁包 镜{shot} → {move_id}"})
    st.save()
    live_note(f"{run_dir.name} 第 {ep} 集运镜补丁包已出：镜{shot} → {move_id}（{step_base}_a{k + 1}，交写手）")
    return {"packet": H.RC._rel(run_dir / WT / f"{step_base}_a{k + 1}.json"), "output": pk["output"]["path"], "now": _shot_move(cur, shot)}


# ---------------------------------------------------------------- 缩短镜长补丁（MERGE-VID-O 11-03，总调度裁定；SOP 第 6 步）
DUR_PATCH_MAX = 6.0          # 单镜上限（项目方定律，L-137；validate_qwen_script.V2_SHOT_MAX_S 同值）
DUR_LINE_RE = re.compile(r"^\s*(?:\*\*时长\*\*：|\*\*分拍\*\*：|\*\*表演节拍\*\*：|\*\*台词时段\*\*：|integrated_multimodal_description:|"
                         r"How the reference pictures align)")
DUR_RE = re.compile(r"^\*\*时长\*\*：\s*(\d+(?:\.\d+)?)\s*秒")


def _shot_duration(doc: str, shot: int) -> float | None:
    rg = _shot_block(doc, shot)
    if not rg:
        return None
    for ln in doc.splitlines()[rg[0]:rg[1]]:
        m = DUR_RE.match(ln)
        if m:
            return float(m.group(1))
    return None


def duration_check(old: str, new: str, shot: int, max_s: float = DUR_PATCH_MAX) -> str:
    """缩短镜长补丁收稿（合格返回空串）：
    只许改第 shot 镜那一块，且只许改 **时长** / **分拍** / **表演节拍** / **台词时段** / H3 正文 / H3 对齐句这几行（行数不变 = 不增删镜、不改镜号）；
    新时长 < 原时长且 ≤ max_s；台词（**对白** / 🎙）逐字不变"""
    rg_o, rg_n = _shot_block(old, shot), _shot_block(new, shot)
    if not rg_o or not rg_n:
        return f"找不到镜{shot}"
    lo, ln_ = old.splitlines(), new.splitlines()
    if len(lo) != len(ln_) or rg_o != rg_n:
        return "缩短镜长补丁改变了行数（只许整行替换时长 / 分拍 / 表演节拍 / 台词时段 / H3 时间轴行，不增删镜）"
    if lo[:rg_o[0]] != ln_[:rg_n[0]] or lo[rg_o[1]:] != ln_[rg_n[1]:]:
        return f"改到了镜{shot}以外的行（这一包只缩短镜{shot}的镜长）"
    for a, b in zip(lo[rg_o[0]:rg_o[1]], ln_[rg_n[0]:rg_n[1]]):
        if a != b and not (DUR_LINE_RE.match(a) and DUR_LINE_RE.match(b)):
            return f"改到了时长 / 分拍 / 表演节拍 / 台词时段 / H3 时间轴以外的行：{a[:40]}"
    d0, d1 = _shot_duration(old, shot), _shot_duration(new, shot)
    if d1 is None:
        return f"镜{shot}没有 **时长** 行"
    if d0 is not None and d1 >= d0:
        return f"镜{shot}时长没有缩短（{d0:g} → {d1:g} 秒）"
    if d1 > max_s + 1e-6:
        return f"镜{shot}时长 {d1:g} 秒仍超过上限 {max_s:g} 秒"
    return ""


def duration_patch(run_dir: Path, ep: int, shot: int, max_s: float = DUR_PATCH_MAX, why: str = "") -> dict:
    """缩短镜长补丁包（总调度 11-03：ep01 镜6 7 秒，不发整集返修）。排队规则同 camera_patch：补丁环还在跑 → 只排进
    agent.duration_queue，补丁环空闲后由 post_step 出包；空闲就立刻出包。派人请求由 packet() 写（派单器自动派写手）"""
    st = AF.Status(run_dir, ep, 0.0)
    ag = st.d.setdefault("agent", {"processed": [], "used": {}, "fact_devs": None})
    req = {"shot": int(shot), "max_s": float(max_s), "why": why, "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    final_p = run_dir / f"P4_ep{ep:02d}.final.md"
    step_base = f"patch_ep{ep:02d}"
    k = attempts(run_dir, step_base)
    busy = (not final_p.exists()) or (k and f"{step_base}_a{k}" not in ag["processed"]) or bool((st.d.get("rubric_code_fail") or {}).get("n"))
    q = [x for x in ag.get("duration_queue") or [] if x["shot"] != req["shot"]] + [req]
    ag["duration_queue"] = q
    if busy:
        st.save()
        return {"ok": True, "queued": True, "why": "这一集补丁环还在跑（或还没进补丁环），缩短镜长包排在它后面，失败项清零后自动出", "queue": q}
    out = _duration_from_queue(run_dir, ep, st)
    return {"ok": True, **(out or {})}


def _duration_from_queue(run_dir: Path, ep: int, st) -> dict | None:
    from ns_api import script_chat as SC
    ag = st.d.setdefault("agent", {"processed": [], "used": {}, "fact_devs": None})
    q = ag.get("duration_queue") or []
    if not q:
        return None
    req = q.pop(0)
    ag["duration_queue"] = q
    shot, max_s, why = int(req["shot"]), float(req.get("max_s") or DUR_PATCH_MAX), req.get("why") or ""
    final_p = run_dir / f"P4_ep{ep:02d}.final.md"
    header, _ = SC.script_header(registry={}, run=SC.run_for_dir(run_dir))
    pre = header + "\n---\n\n"
    cur = RL.split_doc(final_p.read_text(encoding="utf-8"))[1][0]
    d0 = _shot_duration(cur, shot)
    if d0 is None or d0 <= max_s:
        st.save()
        live_note(f"{run_dir.name} 第 {ep} 集缩短镜长补丁：镜{shot} 找不到或已 ≤{max_s:g} 秒，这一条作废")
        return {"skipped": f"镜{shot} 时长 {d0}"}
    facts_p = run_dir / f"facts_ep{ep:02d}.json"
    facts = json.loads(facts_p.read_text(encoding="utf-8")) if facts_p.exists() else {"lines": []}
    target = ("dur", {"id": f"DUR-{shot}", "why": (
        f"{why}缩短镜{shot}的镜长：**时长** 从 {d0:g} 秒改到不超过 {max_s:g} 秒（整数秒），同时按新时长重排这一镜的 **分拍** / **表演节拍**"
        f"（每拍从 0 写到新镜长）、**台词时段**（两句台词都落在新镜长以内）和 H3 的 integrated_multimodal_description 时间轴"
        f"（时间码都在新镜长以内；对齐句 How the reference pictures align… 系统会按时长重算）。"
        f"镜数、镜号、台词原文与说话人都不许改；这一镜以外的任何一行都不许动。"
        f"如果判断这一镜的内容压不进 {max_s:g} 秒，不要硬压：只输出 {{\"cannot_fit\": \"<原因>\"}}，系统登记卡点交总调度决定是否拆镜。")})
    step_base = f"patch_ep{ep:02d}"
    k = attempts(run_dir, step_base)
    user = AF.patch_user(ep, pre, cur, facts, [target], "")
    pk = packet(run_dir, st, step_base, "writer", ep, "patch", R5.r5_writer_system(), user, "patches_json", [H.RC._rel(final_p)], k + 1,
                {"base_sha": _sha(cur), "targets": [f"dur#{shot}"], "duration_shot": shot, "duration_max": max_s, "duration_from": d0})
    st.stage("code", "代码判定 + 补丁", "awaiting_writer", "api_model", step=f"{step_base}_a{k + 1}",
             detail=f"缩短镜长补丁：镜{shot} {d0:g} 秒 → ≤{max_s:g} 秒")
    st.d.setdefault("agent_history", []).append({"step": f"{step_base}_a{k + 1}", "accepted": None,
                                                 "note": f"缩短镜长补丁包 镜{shot} {d0:g}→≤{max_s:g} 秒"})
    st.save()
    live_note(f"{run_dir.name} 第 {ep} 集缩短镜长补丁包已出：镜{shot} {d0:g} 秒 → ≤{max_s:g} 秒（{step_base}_a{k + 1}，交写手）")
    return {"packet": H.RC._rel(run_dir / WT / f"{step_base}_a{k + 1}.json"), "output": pk["output"]["path"], "from_s": d0}


def duration_cannot_fit(run_dir: Path, ep: int, pk: dict, why: str) -> str:
    """写手判断压不进上限 → 登记卡点（tools/master/report_issue.py）交总调度决定是否拆镜；返回补丁不采用的原因"""
    shot = pk.get("duration_shot")
    msg = f"镜{shot} 写手判断压不进 {pk.get('duration_max')} 秒：{why}"[:400]
    try:
        RI = _load("report_issue", "tools/master/report_issue.py")
        RI.report(run_dir.name, ep, "6", "autoflow 缩短镜长补丁", msg, True,
                  fix_hint="总调度决定：是否拆成两镜（拆镜改镜数，走整集返修）")
    except Exception as e:  # noqa: BLE001  # arch-ok: 登记失败也不采用补丁，原因写进 note
        msg += f"（卡点登记失败：{e}）"
    return "写手判断压不进上限（cannot_fit），已登记卡点交总调度：" + msg


def patch_loop_active(run_dir: Path, ep: int, st) -> bool:
    """这一集补丁环正在等一个补丁（有 final.md，且最后一个 patch 包还没处理）——按包的处理记录判断，不按修改时间猜"""
    if not (run_dir / f"P4_ep{ep:02d}.final.md").exists():
        return False
    k = attempts(run_dir, f"patch_ep{ep:02d}")
    processed = ((st.d.get("agent") or {}).get("processed") or [])
    return bool(k) and f"patch_ep{ep:02d}_a{k}" not in processed


def segment_fix(run_dir: Path, p: Path, st, by: str, need_done: bool = False) -> dict | None:
    """K-WRT-213（K211-F 11-03，REVIEW-B P1-2）：V2 稿里漏标【幻想段】/【现实段】的镜 → tools/script_rsi/segment_fix 按 P2 节拍 / P3 场景确定性补标，
    不派 LLM；原稿隔离备份、审计写 <run>/segment_fix.jsonl。标了但和 P2/P3 不一致的镜不动（导入关口 QW-S2 → 补丁环）。只对 V2 完全切割 run"""
    if not clean_cut(run_dir) or not p.exists() or (need_done and not p.with_name(p.name + ".done").exists()):
        return None
    try:
        res = _load("segment_fix", "tools/script_rsi/segment_fix.py").apply_file(p, run_dir, by=by)
    except Exception as e:  # noqa: BLE001  补标出错不挡推进：原稿不动，照旧走校验 / 补丁环
        res = {"changed": False, "error": repr(e)[:200]}
    if res and (res.get("changed") or res.get("error")):
        st.d.setdefault("agent_history", []).append({"step": p.name, "accepted": bool(res.get("changed")), "by": "segment_fix",
                                                     "note": (res.get("error") or f"K-WRT-213 补段落标记：镜 {[x['shot'] for x in res['filled']]}"
                                                              + (f"；标反待补丁 {[x['shot'] for x in res['mismatch']]}" if res.get("mismatch") else ""))[:300]})
        st.save()
    return res


def void_open_patches(run_dir: Path, ep: int, why: str) -> list[str]:
    """这一集还没交稿的补丁包（writer_tasks/patch_epNN_a*.json 有、writer_out 的 .done 没有）全部作废：写 .void、包和请求移进隔离区（void_request），
    派单器见到 .void 就不派 / 杀掉在跑的写手。整集稿换底时用（旧稿上的补丁再写也是白写）→ 作废的包名"""
    out = []
    for q in sorted((run_dir / WT).glob(f"patch_ep{ep:02d}_a*.json")):
        if not (run_dir / WO / f"{q.stem}.json.done").exists():
            void_request(run_dir, q.stem, why)
            out.append(q.stem)
    return out


def adopt_full_p4(run_dir: Path, ep: int, st, text: str, rep, src: Path, note: str, rounds: list | None = None) -> dict:
    """P4 新稿（整集返修稿 / 写手 P4 稿）成为这一集唯一的事实来源（K211-F 11-03，总调度裁定 B / L-150）：
    旧 P4 / final / split 改名 .v<时分秒>.md 留档（不删），写新 P4_epNN.md + report + .v2 标记；
    补丁环状态清零：旧稿上出的补丁包全部记为已处理（否则会一直等一个不会再来的产物）、used 清零、patch_base = 现有包数（预算从 0 起算）；
    排队的运镜 / 缩短镜长包不丢。chain_step 与 intake_full_p4 共用这一处，P4_epNN.md 和 P4_epNN.final.md 不再各自为政"""
    tag = time.strftime("%H%M%S")
    for old in (run_dir / f"P4_ep{ep:02d}.md", run_dir / f"P4_ep{ep:02d}.final.md", run_dir / f"P4_ep{ep:02d}.split.md"):
        if old.exists():
            old.rename(old.with_name(old.stem + f".v{tag}.md"))
    (run_dir / f"P4_ep{ep:02d}.md").write_text(text, encoding="utf-8")
    AF.write_json(run_dir / f"P4_ep{ep:02d}.md.report.json", {"link": "P3-P4", "status": "ok" if rep.ok else "needs_writer",
                                                              **({"rounds": rounds} if rounds else {}),
                                                              "report": rep.as_dict(), "writer": "claude_agent", "source": H.RC._rel(src)})
    (run_dir / f"P4_ep{ep:02d}.md.v2").write_text("shot_spec_v2\n", encoding="utf-8")   # 这一集按 v2 判（K-WRT-805 / 806）
    voided = void_open_patches(run_dir, ep, f"整集稿 {src.name} 换底，旧稿上的补丁作废（K211-F）")
    stale = sorted(q2.stem for q2 in (run_dir / WT).glob(f"patch_ep{ep:02d}_a*.json"))
    old_ag = st.d.get("agent") or {}
    st.d["agent"] = {"processed": stale, "used": {}, "fact_devs": None, "patch_base": len(stale),
                     "full_p4_done": old_ag.get("full_p4_done") or [], "full_p4_deferred": old_ag.get("full_p4_deferred") or [],
                     "camera_queue": old_ag.get("camera_queue") or [], "duration_queue": old_ag.get("duration_queue") or []}
    st.d.setdefault("agent_history", []).append({"step": src.name, "accepted": True,
                                                 "note": f"{note}；旧稿留档 .v{tag}；补丁预算基线 {len(stale)}；作废未交稿补丁 {voided or '无'}"[:300]})
    st.save()
    return {"tag": tag, "patch_base": len(stale), "stale_patches": stale, "voided": voided}


def requeue_full_p4(run_dir: Path, ep: int, name: str, why: str, by: str = "HOLLYWOOD") -> dict:
    """已记 full_p4_done 却没被收的整集稿（旧逻辑“补丁环进行中不收”丢掉的）重新排队：下一次 run 的 intake_full_p4 照正规流程收。
    记一条 manual 历史（同 reopen）"""
    st = AF.Status(run_dir, ep, 0.0)
    ag = st.d.setdefault("agent", {"processed": [], "used": {}, "fact_devs": None})
    done = ag.setdefault("full_p4_done", [])
    if name not in done:
        return {"ok": False, "why": f"{name} 不在 full_p4_done 里"}
    done.remove(name)
    st.d.setdefault("agent_history", []).append({"step": "requeue_full_p4", "accepted": True, "manual": True, "by": by,
                                                 "note": f"manual 重排整集稿 {name}：{why}"[:300]})
    st.set(verdict="reopened", next_action=f"整集稿 {name} 已重排，下一拍收稿（daemon 对 reopened 自动推进）")   # pending_done 认 reopened
    st.save()
    return {"ok": True, "name": name}


def intake_full_p4(RCH, run_dir: Path, ep: int, st, ctx: dict) -> None:
    """写手交来的整集 P4 重写稿（writer_out/P4_epNN_rK.md 或 _aK.md，带 .done；SCRIPTWRITER 按 shot_spec_v2 七段重写第二季已有集）：
    run_chain.validate（P3-P4，同导入关口）过了（或只剩 ≤6 条 P4 阻断交补丁环）→ 旧 P4 / 旧 final 改名留档，新稿成为正式 P4，补丁环从新稿起。
    原文件不删，只改名为 .v<时间>.md"""
    ag = st.d.setdefault("agent", {"processed": [], "used": {}, "fact_devs": None})
    done = ag.setdefault("full_p4_done", [])
    deferred = ag.setdefault("full_p4_deferred", [])
    cands = sorted((run_dir / WO).glob(f"P4_ep{ep:02d}_[ra]*.md"), key=lambda q: int((re.findall(r"_[ra](\d+)\.md$", q.name) or ["0"])[0]))   # 按轮次号排，不按修改时间猜
    for q in cands:
        if q.name in done or not q.with_name(q.name + ".done").exists():
            continue
        if patch_loop_active(run_dir, ep, st):
            # K211-F 11-03（总调度裁定 B / L-150）：补丁环正等一个补丁时来的整集稿先缓着，补丁处理完下一拍就收；
            # 之前直接记 done 不收（03:42 实测项目方点的整集返修稿 a4 就这样被丢了，canon 却被 chain_step 换成了 a4）
            if q.name not in deferred:
                deferred.append(q.name)
                st.d.setdefault("agent_history", []).append({"step": q.name, "accepted": None,
                                                             "note": "补丁环正在等一个补丁：整集稿先缓着，补丁处理完下一拍收（总调度 11-03 裁定 B）"})
                st.set(intake_note=f"{q.name}：补丁环进行中，整集稿缓到下一拍收")
            continue
        if ctx.get("screenplay") is None:
            st.set(intake_note=f"{q.name}：P3 还没有，先不收")
            return
        done.append(q.name)
        if q.name in deferred:
            deferred.remove(q.name)
        st.save()
        l141_fix(run_dir, q, st, "intake_full_p4", need_done=True)     # MIGRATE-O：整集返修稿（L-150）交回仍有镜内 At → 先迁
        segment_fix(run_dir, q, st, "intake_full_p4", need_done=True)  # K-WRT-213：段落漏标按 P2/P3 确定性补，迁不了的进补丁环
        rep, obj, _extra = RCH.validate("P3-P4", q.read_text(encoding="utf-8"), ctx)
        blocking = rep.as_dict()["blocking"]
        if not (rep.ok or (obj is not None and non_tl_blocking(rep) <= 6)):
            st.d.setdefault("agent_history", []).append({"step": q.name, "accepted": False, "note": f"整集稿 P4 阻断 {blocking}"})
            st.save()
            continue
        from ns_recipes.spec_import import rules_version, stamp
        adopt_full_p4(run_dir, ep, st, stamp(obj, rules_version()), rep, q, f"整集稿收为正式 P4（阻断 {blocking}）")
        OG = _load("owner_gate", "tools/script_rsi/owner_gate.py")
        if OG.enabled(run_dir) and OG.get(run_dir, f"ep{ep:02d}").get("status") == "revising":
            OG.set_status(run_dir, f"ep{ep:02d}", "approved", note="项目方修改已收稿（默认自动通过，可再点修改）")
        mark_dirty(run_dir, ep, f"收整集稿 {q.name}")
        st.save()


def run(run_dir: Path, ep: int, import_mode: str) -> dict:
    """HEADER-O 11-03（L-126）：整段按 run_dir 这部剧取写手包 / 全局头（P3-P4 的 WP.build 不带 run，靠 run_scope）"""
    from ns_api import script_chat as SC
    with SC.run_scope(SC.run_for_dir(run_dir)):
        return _run(run_dir, ep, import_mode)


def _run(run_dir: Path, ep: int, import_mode: str) -> dict:
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
        rc, rs, _ = SC.registry_tables({"from": brep.obj.registry_from, "run": SC.run_for_dir(run_dir)})
    except Exception as e:  # noqa: BLE001  登记表读不到：照样写，记下原因（写作方会少了已登记人物的逐字格）
        rc, rs = [], []
        st.set(registry_error=repr(e)[:200])
    if clean_cut(run_dir):          # L-126：完全切割的 run 不带任何已登记（旧剧）人物 / 场景表进写作请求
        rc, rs = [], []
    ctx = {"brief": brep.obj, "episode": ep, "registry_chars": rc, "registry_scenes": rs}
    for link, key in (("P0-P1", "storyline"), ("P1-P2", "outline"), ("P2-P3", "screenplay")):   # 收整集稿要用到上游
        cp = run_dir / dict(RCH.STAGES)[link].format(ep=ep)
        ctx[key] = RCH._load_ok(cp, link, ctx) if cp.exists() else None
    if not ep_gate(run_dir, ep, st):
        return st.d
    intake_full_p4(RCH, run_dir, ep, st, ctx)
    p4_exists = (run_dir / f"P4_ep{ep:02d}.md").exists()
    AF.REQUIRE_V2["on"] = not p4_exists or (run_dir / f"P4_ep{ep:02d}.md.v2").exists()   # 新写 / 重写的集按 v2（K-WRT-805 / 806）
    AF.REQUIRE_V3["on"] = (run_dir / f"P4_ep{ep:02d}.md.v3").exists() or clean_cut(run_dir)   # v3（H19 / H20 / H23–H25 / K-WRT-211）：标记集或 V2 完全切割 run 整季强制
    if not chain_step(RCH, run_dir, ep, st, ctx):
        return st.d
    return post_step(run_dir, ep, st, import_mode, RCH=RCH, ctx=ctx)      # STRUCT-O：结构项整集返修包要用 P3-P4 写手包（WP.build）
