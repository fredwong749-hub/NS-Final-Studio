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
    """L-126 完全切割的 run（run 目录里有 CLEAN_CUT.json）：写作包里不带任何旧剧内容（v1_leak.redact）"""
    return (run_dir / "CLEAN_CUT.json").exists()


def packet(run_dir: Path, st, step: str, role: str, ep: int, link: str, system: str, user: str, fmt: str,
           inputs: list[str], attempt: int, extra: dict | None = None, output_path: Path | None = None) -> dict:
    if not step.startswith(("P1", "facts", "factcheck", "patch", "revise", "lockline")):     # P2 / P3 / P4 包：P1 没过项目方闸门一律不出
        OG = _load("owner_gate", "tools/script_rsi/owner_gate.py")
        if not OG.p1_approved(run_dir):
            raise RuntimeError(f"{run_dir.name}：P1 还没过项目方闸门（用这版），不出 {step} 包（11-02 19:17 事故守卫）")
    rules = CONTENT_RULES
    if clean_cut(run_dir):          # 旧规则里的举例（旧剧人物名 / 场景 / 道具）换成中性占位；内容边界用不含旧剧事实的版本
        VL = _load("v1_leak", "tools/script_rsi/v1_leak.py")
        v = VL.vocab(current=run_dir.name)
        system, user, rules = VL.redact(system, v), VL.redact(user, v), CONTENT_RULES_CLEAN
    if ("标“未提供”" in system + user + rules or "标未提供" in system + user + rules) and AF.OVERRIDE_TAG not in system + rules:
        system += "\n" + AF.PLACEHOLDER_OVERRIDE                    # OVERSIGHT-F P1-8a：单一出口兜底——提到“标未提供”的包必带 SL-12 覆盖说明
    op = output_path or out_path(run_dir, step, attempt, fmt)      # 集返修稿要落 writer_out/P4_epNN_r<k>.md（intake_full_p4 收），其余按 step 命名
    pk = {"schema": "nsfs.writer_task/1", "run": run_dir.name, "step": step, "role": role, "episode": ep, "link": link,
          "system": system + "\n\n========\n\n【内容边界】" + rules, "user": user, "inputs": inputs,
          "output": {"path": H.RC._rel(op), "format": fmt, "done_marker": H.RC._rel(op) + ".done"},
          "content_rules": rules, "attempt": attempt, "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "status": "open",
          "next": NEXT_STEP, **(extra or {})}       # 根因模式 1“双入口”（总调度 11-02）：包里不再给推进命令，推进只走 autoflow（网页 /repair 或 .done 守护）
    AF.write_json(run_dir / WT / f"{step}_a{attempt}.json", pk)
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
        tag = time.strftime("%H%M%S")
        for f in (canon, canon.parent / f"{canon.name}.report.json", run_dir / LOOKS):
            if f.exists():
                f.rename(f.with_name(f.stem + f".v{tag}" + f.suffix))
        if OG.owner_direction(run_dir):            # 项目方在“定方向”状态下点了修改 → 项目方已接手：之后的新稿照样评审，分数只作参考、不拦
            sp_ = run_dir / REVIEW_STATE
            st_ = json.loads(sp_.read_text(encoding="utf-8"))
            st_["owner_took_over"] = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "note": g.get("note", "")[:300]}
            AF.write_json(sp_, st_)
        void_downstream(run_dir, "项目方点了 P1 “修改”：" + g.get("note", "")[:100])
        k = attempts(run_dir, "P1")
        pr = RCH.WP.build("P0-P1", ctx)
        user = (pr["user"] + "\n\n【项目方修改意见（原话）】" + g.get("note", "") + "\n\n【上一版故事线（在它基础上改）】\n"
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


FIELD_LABEL = {"logline": "一句简介", "title": "标题", "owner_line": "一句话", "carry_out": "结尾状态", "premise": "故事前提"}
FILL_MAX = 3
FILL_MIN_CHARS = 6
TRIVIAL_FILL = {"", "无", "暂无", "没有", "空", "略", "同上", "见上", "none", "None", "null", "NA", "na"}


def _field_zh(path: str) -> str:
    m = re.match(r"episodes\[(\d+)\]\.(\w+)$", path)
    if m:
        return f"第 {int(m.group(1)) + 1} 集{FIELD_LABEL.get(m.group(2), '的一处文字')}"
    return FIELD_LABEL.get(path, "故事线里的一处文字")


def fill_note(fields: list[str]) -> str:
    """给项目方的一句话（总调度 11-02）：“第 3 集一句简介还没写完，写手会自动补上，不影响你选的这版。”"""
    return "、".join(dict.fromkeys(_field_zh(f) for f in fields)) + "还没写完，写手会自动补上，不影响你选的这版。"


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
            if pr_.get("status") == "needs_writer" and int((pr_.get("report") or {}).get("blocking") or 99) <= 6:
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
            st.set(verdict="not_importable", awaiting=None, next_action=f"补丁已出 {k} 次仍有失败项，交总调度")
            return st.d
        targets = [(d, u) for d, u in fails if ag["used"].get(f"{d}#{u['id']}", 0) < AF.ITEM_TRIES and f"{d}#{u['id']}" not in AF.STRUCTURAL][:2]
        if not targets:
            st.set(verdict="not_importable", awaiting=None, next_action="剩下的失败项都已试满（或是镜数这类结构项），交总调度 / 整集重写 P4")
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
        st.set(verdict="not_importable", awaiting=None, next_action="P4 阻断未清零")
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
        OG = _load("owner_gate", "tools/script_rsi/owner_gate.py")
        if OG.enabled(run_dir) and OG.get(run_dir, f"ep{ep:02d}").get("status") == "revising":
            OG.set_status(run_dir, f"ep{ep:02d}", "approved", note="项目方修改已收稿（默认自动通过，可再点修改）")
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
    return post_step(run_dir, ep, st, import_mode)
