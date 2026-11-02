"""HOLLYWOOD r8（总调度 fredw-2b 派，11-02）：新建剧本 → 可导入剧本，全自动、可监控、只用 API key（编排器 flow.py 的“剧本写作 + 评分”段）。

项目方 02:3x 原话：“#/script-create?new=1 这个页面……以后我会在这里创建一个新剧本，走现在的流程……全系统本地化运行……规则代码化”。

不另起写作链：
  P0→P4      tools/pipeline/run_chain.run_link（写作 LLM + 各段校验 + 返修，AUTOPILOT 的链）；本模块只在调用前给每段 system
             追加 Hollywood 模板原文（config/prompts/hollywood_writer.md §一，含红线）+ writer_knowledge（全部 K-WRT 规则），
             P3-P4 开 reasoning high 且输出上限 64000（r5 ab 实测：32000 会被推理挤断正文）。
  事实表     从 P0 Brief + P1 故事线 + 本集 P2 大纲 / P3 剧本生成（hollywood_facts.md 任务 A），P4 首稿对它自检；之后每个补丁只核改动的行（任务 C）。
  代码判定   rubric_code（27 条，免费）→ 失败项按条交写作模型逐行补丁（hollywood_r5.user_patch / apply_patches），最多 CODE_ROUNDS 轮，
             每轮代码不变量（说话人顺序、集头、镜数时长、lint 不变差、HW-F1）+ 补丁事实核对，失败项变少才采用。
  新尺子     score_r6（27 条代码 + 23 条 7 个评审逐条多数、证据逐字），记分数轨迹；policy.noise_stop 生效。
  导入       policy.pick_import（达导入线，或预算用完取不变量全过的最高分——项目方 22:3x）→ rubric 导入闸门 + validate →
             live 模式要项目方一次点选（--owner-ok，L-098 闸门范围）后走 producer.import_staged（写导入事件，episode_pipeline 接手）；
             dry 模式只跑闸门不导入（测试 Brief 不碰现行剧）。
每一步记 decider（code / api_model / owner），状态写 <run>/autoflow.json（页面与 flow.py 直接读），全程不需要 Claude。

    .venv/Scripts/python.exe tools/script_rsi/autoflow.py run --run-dir data/script_runs/<id> --episode 1 --budget 1.0 --import dry
    .venv/Scripts/python.exe tools/script_rsi/autoflow.py test-brief --run-dir data/script_runs/<id>      # 写作模型生成一份测试 Brief（不碰 series10）
    .venv/Scripts/python.exe tools/script_rsi/autoflow.py status --run-dir data/script_runs/<id>
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "tools" / "pipeline", ROOT / "tools" / "autopilot", ROOT / "packages" / "schema", ROOT / "services" / "agent",
           ROOT / "services" / "api", ROOT / "services" / "recipes"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


R5 = _load("hollywood_r5", "tools/script_rsi/hollywood_r5.py")
H, RL, FR = R5.H, R5.RL, R5.FR
def write_json(path: Path, obj) -> None:
    """状态 / 产物 JSON 一律原子写（tmp + os.replace）：页面、flow.py、预算闸门随时在读，不能读到半个文件（arch_scan nonatomic_json）"""
    import os
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp{os.getpid()}")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    # Windows：目标正被别的进程打开（API 在读、并行的集在写整季索引）时 os.replace 报 WinError 5 → 短暂重试（S2 ep03 实测崩在这里）
    for i in range(40):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(0.05 * (i + 1))
    tmp.unlink(missing_ok=True)
    raise PermissionError(f"{path} 连续 40 次替换失败（被占用）")


class SeasonBudgetUnknown(RuntimeError):
    """整季花费读不到 → 按超预算处理（失败关闭）"""


CODE_ROUNDS = 4                 # 代码判定补丁最多几轮（每轮修 1–2 条）
STATUS = "autoflow.json"
LINKS = [("P0-P1", "P1", "故事线"), ("P1-P2", "P2", "分集大纲"), ("P2-P3", "P3", "单集剧本"), ("P3-P4", "P4", "分镜")]


# ------------------------------------------------------------------ 状态（页面 / flow.py 读）

class Status:
    def __init__(self, run_dir: Path, episode: int, budget: float):
        self.run_dir, self.ep = run_dir, episode
        self.p = run_dir / f"autoflow_ep{episode:02d}.json"      # 每集一份；autoflow.json = 整季索引 + 最近一集（页面 / API 读）
        self.d = json.loads(self.p.read_text(encoding="utf-8")) if self.p.exists() else {}
        self.d.update({"schema": "nsfs.autoflow/1", "run": run_dir.name, "episode": episode, "budget_usd": budget})
        self.d.setdefault("stages", [])
        self.d.setdefault("score_trajectory", [])
        self.save()

    def stage(self, sid: str, name: str, status: str, decider: str, **kw):
        rec = next((s for s in self.d["stages"] if s["id"] == sid), None)
        if rec is None:
            rec = {"id": sid, "name": name}
            self.d["stages"].append(rec)
        rec.update({"status": status, "decider": decider, "at": time.strftime("%F %T"), **kw})
        self.save()

    def set(self, **kw):
        self.d.update(kw)
        self.save()

    def save(self):
        self.p.parent.mkdir(parents=True, exist_ok=True)
        write_json(self.p, self.d)
        idx_p = self.run_dir / STATUS
        eps = {}                 # 整季索引每次从各集文件重算（多集并行时不靠读改写，不会互相覆盖）
        unreadable = []
        for f in sorted(self.run_dir.glob("autoflow_ep*.json")):
            try:
                e = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError) as ex:      # 读不到的集记下来，整季花费置为未知（预算闸门按超支处理）
                unreadable.append(f"{f.name}: {ex!r}"[:200])
                continue
            eps[str(e.get("episode"))] = {k: e.get(k) for k in ("verdict", "usd_total", "next_action")} | {
                "score": (e.get("score_trajectory") or [{}])[-1].get("sum"),
                "code_fails": next((x.get("fails") for x in e.get("stages", []) if x["id"] == "code"), None)}
        out = dict(self.d)
        out.update({"episodes": eps, "latest_episode": self.ep, "unreadable_episodes": unreadable,
                    "season_usd": None if unreadable else round(sum(float(v.get("usd_total") or 0) for v in eps.values()), 4)})
        write_json(idx_p, out)


# ------------------------------------------------------------------ 写作段：模板 + 规则注入

PLACEHOLDER_OVERRIDE = ("【系统覆盖（总调度 11-02，SL-12）】上面‘缺信息标未提供’只适用于事实核对类字段；"
                        "故事、剧本、造型正文一律不留占位词，缺信息就按 P0 / P1 已有设定写成具体内容。")
OVERRIDE_TAG = "【系统覆盖（总调度 11-02，SL-12）】"


def extra_system() -> str:
    w = (H.PROMPTS / "hollywood_writer.md").read_text(encoding="utf-8")
    tpl = w[w.find("## 一、模板原文"):w.find("## 二、")] if "## 一、模板原文" in w else w
    wk = (ROOT / "config" / "recipes" / "writer_knowledge.md").read_text(encoding="utf-8")
    return ("【项目方 11-01 好莱坞模板（原文；红线：不改给定的剧情事实和人物设定，缺信息标“未提供”，不编剧情）】\n" + tpl
            + "\n" + PLACEHOLDER_OVERRIDE + "\n\n========\n\n" + wk)      # 模板原文不改（等项目方定），紧接覆盖说明（OVERSIGHT-F P1-8a）


STRUCTURAL = {"turns#1"}
ITEM_TRIES = 2
SCORE_RESERVE = 0.2      # 总调度 03:0x 断点①：补丁 / 拆镜花钱前先给新尺子打分留出这笔（S2 ep01/04/05 实测补丁把钱用光、没打成分）


def fact_items(devs: list) -> list[tuple[str, dict]]:
    """断点③：整集事实核对的偏差也作为补丁目标（S2 ep05：P4 把林晚换成另一套造型，与上游事实表不符）"""
    return [("fact", {"id": f"F{i + 1}", "why": f"{d.get('kind', '')}｜事实表：{d.get('ref', '')}｜改写稿里：{d.get('found', '')}"[:400]})
            for i, d in enumerate(devs or [])]         # 镜数等结构项：逐行补丁改不了（不能增删镜），只能在 P4 首稿写对


def camera_brief() -> str:
    """L-107：运镜规则注入 P3 / P4（词表出来前按资料“避坑”三条）"""
    vocab = R5.RC6.camera_vocab()
    lines = ["【运镜（项目方 AI 运镜资料 docs/reference/camera_moves_20261102.md，L-107）】",
             "- 避免“环绕 + 推拉”冲突组合；镜头运动写“匀速、无抖动”这类稳定约束。",
             "- 复杂运动拆成两镜，每镜只写一种运镜（例：先推近一镜，再环绕一镜）。",
             "- 慢镜头写“无渐变过渡”；甩镜写“运动模糊 + 瞬间清晰”。"]
    if vocab:
        lines.append("- **镜头运动** 字段只能写下面词表里的运镜名（DIRECTOR config/director/camera_moves.yaml，enabled）：" + "、".join(sorted(vocab)))
    return "\n".join(lines)


def rubric_code_brief() -> str:
    rub = json.loads(R5.RUBRIC_JSON.read_text(encoding="utf-8"))
    lines = ["【导入闸门的代码判定条目（rubric_code，写完系统逐条机检，失败项必须为 0 才能导入）】",
             "- 镜数 10–20（每镜约 6 秒），镜号 1..N 连续。", camera_brief()]
    for d in R5.RC6.DIMS:
        for i in R5.RC6.CODE_ITEMS.get(d, []):
            lines.append(f"- {d}#{i}：{rub[d][i - 1]}")
    return "\n".join(lines)


def patch_chain(RCH):
    """在本进程内给 run_chain 加两件事（不改 run_chain / writer_prompt 文件，AUTOPILOT 的链原样复用）：
    ① 每段 system 追加 extra_system()（已含 writer_knowledge 的段不重复）；② P3-P4 输出上限 64000"""
    if getattr(RCH, "_autoflow_patched", False):
        return
    orig_build, orig_chain = RCH.WP.build, RCH.chain
    extra = extra_system()

    def build(link, ctx):
        pr = orig_build(link, ctx)
        if link == "P2-P3":     # L-107：P3 剧本阶段也带运镜规则
            pr["system"] = pr["system"] + "\n\n========\n\n" + camera_brief()
        if link == "P3-P4":     # 一开始就把 27 条代码判定写给写作方（r8 测试实测：镜数 8 < 10、近景写下半身，补丁修不了镜数）
            pr["system"] = pr["system"] + "\n\n========\n\n" + rubric_code_brief()
        if "writer_knowledge_version" not in pr["system"]:
            pr["system"] = pr["system"] + "\n\n========\n\n" + extra
        else:
            pr["system"] = pr["system"] + "\n\n========\n\n" + extra.split("========")[0]
        return pr

    def chain():
        c = orig_chain()
        c["links"]["P3-P4"]["writer"]["max_tokens"] = max(int(c["links"]["P3-P4"]["writer"].get("max_tokens") or 0), R5.MAX_OUT)
        return c
    RCH.WP.build, RCH.chain = build, chain
    RCH._autoflow_patched = True


def run_links(RCH, run_dir: Path, episode: int, st: Status, tag: str, budget: float) -> dict:
    from ns_schema import storyline as SL
    brep = SL.check_brief(json.loads((run_dir / "P0_brief.json").read_text(encoding="utf-8")))
    if not brep.ok:
        st.stage("P0", "Brief", "bad_brief", "code", detail="；".join(i.message for i in brep.issues[:5]))
        return {}
    st.stage("P0", "Brief", "ok", "code")
    brief = brep.obj
    try:
        from ns_api import script_chat as SC
        rc, rs, _ = SC.registry_tables({"from": brief.registry_from})
    except Exception:  # noqa: BLE001
        rc, rs = [], []
    ctx = {"brief": brief, "episode": episode, "registry_chars": rc, "registry_scenes": rs}
    key = {"P0-P1": "storyline", "P1-P2": "outline", "P2-P3": "screenplay", "P3-P4": "p4"}
    for link, node, name in LINKS:
        path = run_dir / dict(RCH.STAGES)[link].format(ep=episode)
        obj = RCH._load_ok(path, link, ctx)
        prev_rep = path.parent / f"{path.name}.report.json"
        if obj is None and link == "P3-P4" and path.exists() and prev_rep.exists():    # 续跑：上次 P4 留给补丁环的稿直接复用，不重写（省钱）
            pr_ = json.loads(prev_rep.read_text(encoding="utf-8"))
            if pr_.get("status") == "needs_writer" and int((pr_.get("report") or {}).get("blocking") or 99) <= 6:
                t_ = path.read_text(encoding="utf-8")
                ctx[key[link]] = t_[t_.find("## ep"):] if "## ep" in t_ else t_
                st.stage(node, name, "needs_patch", "code", output=H.RC._rel(path), detail="复用上次 P4，阻断交补丁环")
                continue
        if obj is not None:
            st.stage(node, name, "reused", "code", output=H.RC._rel(path))
        else:
            st.stage(node, name, "running", "api_model")
            try:
                r = RCH.run_link(link, ctx, run_dir, tag=tag, budget=budget, reasoning=(link == "P3-P4"))
            except RCH.BudgetExceeded as e:
                st.stage(node, name, "budget_stop", "code", detail=str(e))
                return {}
            obj = r.pop("obj", None)
            st.stage(node, name, r["status"], "api_model" if r["status"] == "ok" else "code", usd=r["usd"], rounds=r["rounds"],
                     blocking=r["blocking"], output=r.get("output"))
            if r["status"] != "ok":
                # P4 返修用完仍有少量阻断（S2 ep01 实测：2 条 VQ-W1 中全景鞋没写进 img）→ 交给后面的逐行补丁环修，不停在链上
                if link == "P3-P4" and obj is not None and int(r.get("blocking") or 0) <= 6:
                    st.stage(node, name, "needs_patch", "code", usd=r["usd"], rounds=r["rounds"], blocking=r["blocking"], output=r.get("output"),
                             detail="P4 阻断交补丁环")
                else:
                    return {}
        ctx[key[link]] = obj
    return ctx


# ------------------------------------------------------------------ P4 之后：事实表 → 代码判定补丁 → 新尺子 → 导入闸门

def upstream_text(run_dir: Path, episode: int) -> str:
    parts = []
    for name in ("P0_brief.json", "P1_storyline.json", f"P2_ep{episode:02d}_outline.json", f"P3_ep{episode:02d}_screenplay.json"):
        p = run_dir / name
        if p.exists():
            parts.append(f"【{name}】\n{p.read_text(encoding='utf-8')}")
    return "\n\n".join(parts)


def facts_from_upstream(client, run_dir: Path, episode: int) -> dict:
    user = ("【任务 A：抽取事实表】这一集的“原稿”是下面这些上游文件（提纲 / 故事线 / 本集大纲 / 本集剧本），"
            f"只抽第 {episode} 集会用到的事实。\n\n" + upstream_text(run_dir, episode))
    for _ in range(2):
        d, err = H._json_block(client(R5.facts_system(), user))
        if d and d.get("lines") is not None:
            return d
    raise RuntimeError(f"事实表抽取失败：{err}")


REQUIRE_V2 = {"on": False}
REQUIRE_V3 = {"on": False}      # 总调度 11-02 v3 试点（第二季 ep01–03 起）：结尾钩子在画面里 + 一镜一个主动作，按集标记 P4_epNN.md.v3 开      # claude_agent 写的新集（第二季 ep06 起）必须按 v2 写；旧稿只在已经用了 v2 标签时才判


def code_fails(pre: str, chunk: str, ep: int, wd: Path) -> list[tuple[str, dict]]:
    obj = H.episode_obj(pre, chunk, ep, wd)
    shots = sorted(obj.shots, key=lambda s: s.index)
    blocks = [RL.block_text(chunk, k) for k in range(len(shots))]
    cc = R5.RC6.code_checks(chunk, shots, blocks, RL.block_text(chunk, "head"), H.lint(chunk, ep)["codes"])
    if R5.RC6.uses_v2(blocks) or REQUIRE_V2.get("on"):      # K-WRT-805 / 806：第二季起的镜头块 v2 + 【灯光】
        cc["v2"] = R5.RC6.v2_checks(shots, blocks, pre + RL.block_text(chunk, "head"))
    if REQUIRE_V3.get("on"):                                   # K-WRT-H19 / H20：v3 试点集（P4_epNN.md.v3 标记）
        cc["v3"] = R5.RC6.v3_checks(shots, blocks)
        SL = _load("scene_lock", "tools/script_rsi/scene_lock.py")       # K-WRT-H23–H25：场景定稿行 / 衔接点 / 不重复描述环境
        cc["scene"] = SL.check_episode(RL.block_text(chunk, "head"), shots, blocks)
        cc["k211"] = R5.RC6.mirror_hand_checks(shots, blocks)            # K-WRT-211（fb-0001）：镜面手不碰反光面 / ≤8 秒手部动作 ≤2 拍
    out = []
    for d in list(R5.RC6.DIMS) + [x for x in ("v2", "v3", "scene", "k211") if x in cc]:
        for i, (ok, why) in cc[d].items():
            if not ok:
                shots_ = sorted({int(x) for x in re.findall(r"镜(\d+)", why)} |
                                {int(x) for g in re.findall(r"\[([\d, ]+)\]", why) for x in g.split(",") if x.strip().isdigit()})
                out.append((d, {"id": i, "shots": shots_, "why": "代码判定：" + why}))
    return out


def all_fails(pre: str, chunk: str, ep: int, wd: Path) -> list[tuple[str, dict]]:
    """补丁环的目标 = P4 镜头阻断（导入关口 + 写作链级别 lint）+ rubric 代码判定失败项"""
    out = [("p4", {"id": (re.match(r"[^：]*：\[([A-Za-z0-9-]+)\]", x) or re.match(r"(.)", x)).group(1), "why": x[:300],
                   "shots": [int(m) for m in re.findall(r"S(\d+)", x.split("：")[0])]})
           for x in H.lint(chunk, ep)["shot_block"]]
    SH = _load("shootable", "tools/script_rsi/shootable.py")      # K-WRT-H13：编译后孤儿描述 / 特写双人露脸
    shoot = [("shoot", {"id": x["shot"], "shots": [x["shot"]], "why": f"镜{x['shot']}：{SH.why(x)}"})
             for x in SH.shootable_rows(pre + chunk, ep) if not x["ok"]]
    ST = _load("staging", "tools/script_rsi/staging.py")           # K-WRT-H15 / H16：在画人物接触场景物件、双人不用紧景别
    bad = [x for x in ST.staging_rows(pre + chunk, ep) if not x["ok"]]
    stage = [("stage", {"id": f"H15-{bad[i]['shot']}", "shots": [x["shot"] for x in bad[i:i + STAGE_GROUP]],
                        "why": "；".join(f"镜{x['shot']}：{ST.why(x)}" for x in bad[i:i + STAGE_GROUP])})
             for i in range(0, len(bad), STAGE_GROUP)]
    return out + shoot + stage + code_fails(pre, chunk, ep, wd)


STAGE_GROUP = 2      # 摆位补丁每条目标最多带 2 镜（一个补丁包 2 条目标 = 4 镜，改动行数在补丁上限内）


def patch_user(ep, pre, chunk, facts, targets, note="") -> str:
    """R5.user_patch 的同款请求，目标既可以是清单条目，也可以是 P4 阻断原文"""
    rub = json.loads(R5.RUBRIC_JSON.read_text(encoding="utf-8"))
    nl = R5.numbered_lines(chunk)
    tg = []
    for d, u in targets:
        if d == "p4":
            tg.append(f"- 导入校验阻断：{u['why']}")
        elif d == "fact":
            tg.append(f"- 剧情事实偏差（按事实表改回，只改表达相关的行）：{u['why']}")
        elif d not in rub:          # v2 镜头块 / 灯光等非清单条目：给原因原文
            tg.append(f"- {d}#{u.get('id')}：{u['why']}")
        else:
            i = int(u.get("id"))
            tg.append(f"- {dict(H.DIMS)[d]} 第 {i} 条：{rub[d][i - 1]}\n  没满足：镜 {u.get('shots') or '未指出'}；{u.get('why', '')}")
    parts = ["【剧情事实表（硬约束，原样遵守）】", json.dumps(facts, ensure_ascii=False, indent=1), "",
             f"【改写边界】{R5.PATCH_RULE}", "",
             f"【ep{ep:02d} 集头（只读，不许改）】", RL.block_text(chunk, "head"), "",
             "【镜头区，逐行编号（L 行号｜原文）】", *[f"L{n}｜{t}" for n, _, t in nl], "",
             "【本次只修这 1–2 条】", *tg, "",
             "只输出一个 ```json：{\"patches\": [{\"line\": 行号, \"new\": \"这一行的完整新文本\"}]}；只改必需的行（1–14 行），"
             "每行整行替换、保留原来的字段标签和 H3 的字段名 / 时间码；台词说话人和条数不变；不要复制或新增 H3 字段行。"]
    if note:
        parts += ["", f"上一次的补丁没有被采用：{note}"]
    return "\n".join(parts)


def structural_fix(writer, fact_cl, facts, pre, base, cur, fails, ep, base_lint, wd, calls) -> tuple[str, list, dict]:
    """镜数不在 10–20（turns#1）：逐行补丁加不了镜 → 请写作方整集拆镜一次（每镜 6 秒、台词逐字、事实不变），
    过代码不变量（说话人顺序 / 集头 / 时长 / lint 不变差 / HW-F1）+ 整集事实核对、且失败项变少才采用"""
    obj = H.episode_obj(pre, cur, ep, wd)
    n = len(obj.shots)
    want = max(10, n)
    user = ("【剧情事实表（硬约束）】\n" + json.dumps(facts, ensure_ascii=False, indent=1) + "\n\n【当前稿】\n" + RL.block_text(cur, "head")
            + "\n\n" + H.shots_text(cur) + f"\n\n【任务】本集现在 {n} 镜，导入闸门要求 10–20 镜。把镜头拆到 {want} 镜（每镜 6 秒，总 {want * 6} 秒），"
            "台词与 🎙 逐字保留、说话人和顺序不变，不新增情节；拆出来的新镜写反应 / 局部 / 承接。字段齐全。"
            "先输出 ```json 好莱坞方案（可沿用），再从 **镜1｜img** 起输出全部镜头块。\n\n" + rubric_code_brief())
    (calls / "split.req.txt").write_text(user, encoding="utf-8")
    raw = writer(R5.r5_writer_system(), user)
    (calls / "split.reply.txt").write_text(raw, encoding="utf-8")
    c, _p, _chg, err = R5.apply_reply(raw, cur, cur, n, {})
    if c is None:
        return cur, fails, {"structural": "split", "accepted": False, "note": err[:200]}
    c = H.mech_align_all(pre, c, ep, wd)
    g = R5.gate5(pre, base, c, ep, base_lint, wd)
    hard = [x for x in g["checks"] if not x["ok"] and x["id"] not in ("I7", "I6")]
    if hard:
        return cur, fails, {"structural": "split", "accepted": False, "note": "；".join(f"{x['id']} {x['detail']}" for x in hard)[:300]}
    okf, dev, errf = R5.check_facts(fact_cl, facts, c, ep)
    if not okf:
        return cur, fails, {"structural": "split", "accepted": False, "note": (errf or json.dumps(dev, ensure_ascii=False))[:300]}
    f2 = all_fails(pre, c, ep, wd)
    ok = len(f2) < len(fails) and not any(f"{d}#{u['id']}" in STRUCTURAL for d, u in f2)
    return (c, f2, {"structural": "split", "accepted": True, "shots": [n, len(H.episode_obj(pre, c, ep, wd).shots)], "code_fails": len(f2)}) if ok else (cur, fails, {"structural": "split", "accepted": False, "note": f"失败项 {len(fails)} → {len(f2)}"})


def run_post(run_dir: Path, episode: int, st: Status, budget: float, import_mode: str, owner_ok: bool) -> dict:
    from ns_api import script_chat as SC
    import policy as POL
    wd = run_dir / f"work_ep{episode:02d}"      # 每集独立（多集并行时 _work.md 不互踩）
    wd.mkdir(exist_ok=True)
    calls = run_dir / f"calls_ep{episode:02d}"
    calls.mkdir(exist_ok=True)
    p4 = (run_dir / f"P4_ep{episode:02d}.md").read_text(encoding="utf-8")
    body = p4[p4.find("## ep"):] if "## ep" in p4 else p4
    header, _ = SC.script_header(registry={})
    pre = header + "\n---\n\n"
    base = body.rstrip() + "\n\n---\n"
    H.ZERO_CODES[:] = ["QW-W11"]
    writer = R5.make_writer("flash-high", temperature=0.5)
    fact_cl = R5.make_fact_client()
    judges = [FR.Writer(temperature=0.0, max_tokens=8000) for _ in range(7)]
    prior_post = float(st.d.get("usd_post_cum") or st.d.get("usd_post") or 0)      # 续跑：之前几次后处理已花的也算进本集预算
    spent0 = float(st.d.get("usd_links") or 0) + prior_post
    budget_left = budget - spent0
    B = R5.Budget(max(0.0, budget_left), [writer, fact_cl] + judges)

    def guard(need: float):
        if B.left() < need:
            raise RuntimeError(f"本集预算将尽（写作链 ${spent0:.3f} + 后处理 ${B.usage()['usd']:.3f} / ${budget}）")
    split_p = run_dir / f"P4_ep{episode:02d}.split.md"
    if split_p.exists():                   # 续跑：上次已整集拆镜 → 拆镜稿是代码不变量的基线
        base = RL.split_doc(split_p.read_text(encoding="utf-8"))[1][0]
    base_lint = H.lint(base, episode)
    # 事实表（每集一份；续跑沿用，不重抽）
    fpath = run_dir / f"facts_ep{episode:02d}.json"
    try:
        if fpath.exists():
            facts = json.loads(fpath.read_text(encoding="utf-8"))
            st.stage("facts", "事实表", "reused", "code", note=H.RC._rel(fpath))
        else:
            guard(0.05)
            facts = facts_from_upstream(fact_cl, run_dir, episode)
            write_json(fpath, facts)
            ok, dev, err = R5.check_facts(fact_cl, facts, base, episode)
            st.stage("facts", "事实表", "ok" if ok else "deviation", "api_model", deviations=dev[:8], note=err or "P4 首稿对上游事实表自检")
    except RuntimeError as e:
        st.stage("facts", "事实表", "error", "code", detail=str(e))
        return st.d
    prev_final = run_dir / f"P4_ep{episode:02d}.final.md"
    cur = RL.split_doc(prev_final.read_text(encoding="utf-8"))[1][0] if prev_final.exists() else base   # 续跑：从上次的最好稿接着补
    used, hist = {}, []        # used：条目 → 已试次数（每条最多 ITEM_TRIES 次；r8 S2 实测一条要两次才修完）
    try:
        guard(0.03 + SCORE_RESERVE)
        okf0, devs, _e = R5.check_facts(fact_cl, facts, cur, episode)
    except RuntimeError:
        devs = []
    fitems = fact_items(devs)
    fails = fitems + all_fails(pre, cur, episode, wd)
    st.stage("code", "代码判定 + 补丁", "running", "code", fails=len(fails), detail=[f"{d}#{u['id']} {u['why'][:120]}" for d, u in fails])
    if any(f"{d}#{u['id']}" in STRUCTURAL for d, u in fails):
        try:
            guard(0.2 + SCORE_RESERVE)
            cur, fails, srec = structural_fix(writer, fact_cl, facts, pre, base, cur, [f for f in fails if f[0] != "fact"], episode, base_lint, wd, calls)
            fails = fitems + fails
            hist.append(srec)
            if srec.get("accepted"):
                base, base_lint = cur, H.lint(cur, episode)     # 拆镜后的稿成为新基线（镜数变了，代码不变量对它比）
                (run_dir / f"P4_ep{episode:02d}.split.md").write_text(cur, encoding="utf-8")
        except RuntimeError as e:
            hist.append({"structural": "budget", "note": str(e)})
    hist.append({"round": 0, "code_fails": len(fails)})
    try:
        for rnd in range(1, CODE_ROUNDS + 1):
            if not fails:
                break
            guard(0.06 + SCORE_RESERVE)
            targets = [(d, u) for d, u in fails if used.get(f"{d}#{u['id']}", 0) < ITEM_TRIES and f"{d}#{u['id']}" not in STRUCTURAL][:2]
            if not targets:
                break
            for d, u in targets:
                used[f"{d}#{u['id']}"] = used.get(f"{d}#{u['id']}", 0) + 1
            note, accepted = "", None
            for att in range(2):
                u_ = patch_user(episode, pre, cur, facts, targets, note)
                (calls / f"code{rnd}-a{att}.req.txt").write_text(u_, encoding="utf-8")
                raw = writer(R5.r5_writer_system(), u_)
                (calls / f"code{rnd}-a{att}.reply.txt").write_text(raw, encoding="utf-8")
                d_, err = H._json_block(raw)
                c, changed, err2 = R5.apply_patches(cur, (d_ or {}).get("patches") or [], R5.numbered_lines(cur)) if d_ else (None, [], err)
                if c is None:
                    note = err2 or err
                    continue
                c = H.mech_align_all(pre, c, episode, wd)
                g = R5.gate5(pre, base, c, episode, base_lint, wd)
                hard = [x for x in g["checks"] if not x["ok"] and x["id"] != "I7"]     # I7（镜头阻断）由“失败项变少”判
                if hard:
                    note = "；".join(f"{x['id']} {x['name']} 不满足：{x['detail']}" for x in hard)[:1200]
                    continue
                if any(d == "fact" for d, _ in targets):     # 修事实偏差：整集重核，偏差变少才算
                    okf, devf, errf = R5.check_facts(fact_cl, facts, c, episode)
                    if errf:
                        note = errf
                        continue
                    f2 = fact_items(devf) + all_fails(pre, c, episode, wd)
                else:
                    okf, devf, errf = R5.check_patch_facts(fact_cl, facts, cur, changed)
                    if not okf:
                        note = errf or ("补丁触碰了剧情事实：" + json.dumps(devf, ensure_ascii=False)[:600])
                        continue
                    f2 = fitems + all_fails(pre, c, episode, wd)
                if len(f2) < len(fails):
                    accepted = (c, f2, len(changed))
                    break
                note = f"补丁后失败项没有变少（{len(fails)} → {len(f2)}）"
            if accepted:
                cur, fails, n = accepted
                fitems = [f for f in fails if f[0] == "fact"]
                (run_dir / f"P4_ep{episode:02d}.code{rnd}.md").write_text(cur, encoding="utf-8")
            hist.append({"round": rnd, "targets": [f"{d}#{u['id']}" for d, u in targets], "accepted": bool(accepted),
                         "code_fails": len(fails), "note": "" if accepted else note[:300]})
            st.stage("code", "代码判定 + 补丁", "running", "api_model", fails=len(fails), history=hist,
                     detail=[f"{d}#{u['id']} {u['why'][:120]}" for d, u in fails])
    except RuntimeError as e:
        hist.append({"stop": str(e)})
    st.stage("code", "代码判定 + 补丁", "ok" if not fails else "fails_left", "code", fails=len(fails), history=hist,
             detail=[f"{d}#{u['id']} {u['why'][:120]}" for d, u in fails])
    # SENTINEL S12（总调度 03:1x）：新稿的代码判定失败数 + 条目 id；尺子离散度
    rub_fail = [f"{d}#{u['id']}" for d, u in fails if d not in ("p4", "fact")]
    st.set(rubric_code_fail={"n": len(rub_fail), "ids": rub_fail}, ruler_sigma=None)
    # 新尺子打分 + noise_stop
    sc, ns = None, {}
    try:
        guard(0.2)
        sc = R5.score_r6(judges, cur, episode, pre, calls, "final", wd)
        if sc:
            ns = POL.noise_stop([sc.get("judge_sums") or []])
            js_ = [float(x) for x in (sc.get("judge_sums") or [])]
            if len(js_) > 1:
                import statistics
                st.set(ruler_sigma=round(statistics.pstdev(js_), 3))     # 本次 7 个评审各自总分的标准差（单次打分内）
            st.d["score_trajectory"].append({"at": time.strftime("%F %T"), "sum": H._sum(sc), "judge_sums": sc.get("judge_sums"),
                                             "noise_stop": ns, "per_dim": {k: v["score"] for k, v in sc["scores"].items()}})
        st.stage("score", "新尺子打分", "ok" if sc else "error", "api_model", sum=H._sum(sc) if sc else None, noise_stop=ns,
                 gaps={k: v["why"][:200] for k, v in (sc or {}).get("scores", {}).items() if v["score"] < 5})
    except RuntimeError as e:
        st.stage("score", "新尺子打分", "budget_stop", "code", detail=str(e))
    # 整集事实核对（收尾）+ 导入决定
    final_md = run_dir / f"P4_ep{episode:02d}.final.md"
    final_md.write_text(pre + cur, encoding="utf-8")
    try:
        guard(0.03)
        okf, devf, errf = R5.check_facts(fact_cl, facts, cur, episode)
    except RuntimeError as e:
        okf, devf, errf = False, [], str(e)
    gF = R5.gate5(pre, base, cur, episode, base_lint, wd)
    lint_now = H.lint(cur, episode)
    cand = {"name": final_md.name, "score": H._sum(sc) if sc else 0, "invariants_pass": gF["ok"], "p4_block_zero": not lint_now["shot_block"],
            "fact_check_zero": okf, "code_fails": len(fails)}
    pick = POL.pick_import([cand] if not fails else [], spent_usd=spent0 + B.usage()["usd"], rounds_left=0)
    # DISTILL 交付契约（flow.py 现推剧本段状态）：<run_dir>/hollywood/epNN.json
    import hashlib
    sha = hashlib.sha256(final_md.read_bytes()).hexdigest()
    (run_dir / "hollywood").mkdir(exist_ok=True)
    write_json(run_dir / "hollywood" / f"ep{episode:02d}.json", {
        "candidates": [{**cand, "name": "final", "path": H.RC._rel(final_md), "sha256": sha}] if not fails else [],
        "code_fails": len(fails), "spent_usd": round(spent0 + B.usage()["usd"], 4), "rounds_left": 0,
        "staged_path": H.RC._rel(final_md) if pick.get("pick") else None, "sha256": sha if pick.get("pick") else None,
        "pick": pick})
    st.stage("decide", "导入决定", "importable" if pick.get("pick") else "not_importable", pick.get("decider", "code"),
             candidate=cand, why=pick.get("why"), fact_deviations=devf[:6], note=errf)
    usage = B.usage()
    st.set(usd_post=usage["usd"], usd_post_cum=round(prior_post + usage["usd"], 4), usd_total=round(spent0 + usage["usd"], 4), calls_post=usage["calls"])
    if not pick.get("pick"):
        st.set(verdict="not_importable", next_action="一键返修（autoflow.py run 续跑）或改 Brief")
        return st.d
    # 导入闸门（rubric + validate）→ 项目方一次点选 → import_staged
    RA = _load("rubric_audit", "tools/script_rsi/rubric_audit.py")
    rg = RA.gate(final_md)
    v = FR.validate_json(final_md)
    gate_ok = rg["ok"] and not v.get("blocking")
    st.stage("gate", "导入闸门", "ok" if gate_ok else "blocked", "code", rubric_ok=rg["ok"], validate_blocking=v.get("blocking"))
    if not gate_ok:
        st.set(verdict="blocked_by_gate", next_action="一键返修")
        return st.d
    if import_mode == "dry":
        st.stage("import", "导入", "dry_run_ok", "code", detail="测试模式：闸门全过，未导入（测试 Brief 不碰现行剧）")
        st.set(verdict="importable", next_action="项目方点“导入”（live 模式）")
        return st.d
    if not owner_ok:
        st.stage("import", "导入", "awaiting_owner", "owner", detail="等项目方在页面点一次“导入”（L-098 闸门范围）")
        st.set(verdict="importable", next_action="项目方点“导入”")
        return st.d
    import hashlib
    import subprocess
    staged = ROOT / "data/staging_v3/merged" / f"autoflow_{run_dir.name}_ep{episode:02d}_v3.md"
    staged.write_bytes(final_md.read_bytes())
    sha = hashlib.sha256(staged.read_bytes()).hexdigest()
    r = subprocess.run([sys.executable, "tools/autopilot/producer.py", "import-staged", "--obj", H.RC._rel(staged), "--reason", sha,
                        "--by", "PRODUCER", "--note", f"autoflow {run_dir.name} ep{episode:02d}（项目方页面点选导入，L-098）"],
                       cwd=ROOT, capture_output=True, timeout=1800, env={**__import__("os").environ, "PYTHONUTF8": "1"})
    out = (r.stdout.decode("utf-8", "replace").strip().splitlines() or [""])[-1]
    st.stage("import", "导入", "imported" if r.returncode == 0 else "import_failed", "code", staged=H.RC._rel(staged), sha256=sha, out=out[:300])
    st.set(verdict="imported" if r.returncode == 0 else "import_failed")
    return st.d


# ------------------------------------------------------------------ 命令

def advance_log(run_dir: Path, source: str, episode: int, verdict=None, note: str = "") -> None:
    """每次推进记一行 <run>/autoflow.log（总调度 11-02：命令行推进也要记，标来源 cli / web / daemon，以后查得到是谁推进的）"""
    rec = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "source": source, "episode": episode, "pid": os.getpid(),
           "user": os.environ.get("USERNAME") or os.environ.get("USER") or "", "agent": os.environ.get("CLAUDE_AGENT_NAME", ""),
           "verdict": verdict, "note": note}
    with open(run_dir / "autoflow.log", "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


LOCK_STALE_S = 1800


def _pid_alive(pid: int) -> bool:
    try:
        if os.name == "nt":
            import ctypes
            h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)        # PROCESS_QUERY_LIMITED_INFORMATION
            if not h:
                return False
            code = ctypes.c_ulong()
            ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
            ctypes.windll.kernel32.CloseHandle(h)
            return code.value == 259                                          # STILL_ACTIVE
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def acquire_advance_lock(run_dir: Path, episode: int, source: str) -> Path | None:
    """跨进程推进锁（OVERSIGHT-F 11-02 第 2 轮 P1-a：网页 / watch / 命令行 / 旧 autopilot 互不相认，同一集会被并发推进）：
    <run>/work_epNN/advance.lock 用 O_EXCL 建；锁主进程已死或超过 30 分钟视为陈旧、接管。拿不到 = None（本次跳过）"""
    lk = run_dir / f"work_ep{episode:02d}" / "advance.lock"
    lk.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(5):
        try:
            fd = os.open(str(lk), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(json.dumps({"pid": os.getpid(), "source": source, "at": time.time()}))
            return lk
        except FileExistsError:
            info = None
            for _r in range(20):                     # W-35：持锁方刚 O_EXCL 建好、内容还没写完时读到空 / 半截 → 等一下再读，不能当成陈旧锁删掉
                try:
                    info = json.loads(lk.read_text(encoding="utf-8"))
                    break
                except FileNotFoundError:            # 持锁方刚释放：锁已空，回去重抢
                    info = "gone"
                    break
                except (OSError, ValueError):
                    time.sleep(0.01)
            if info == "gone":
                continue
            if not isinstance(info, dict):           # 一直读不出内容：按“有人持锁”处理（宁可跳过一次，不误删别人的锁）
                return None
            stale = (time.time() - float(info.get("at") or 0) > LOCK_STALE_S) or not _pid_alive(int(info.get("pid") or 0))
            if not stale:
                return None
            lk.unlink(missing_ok=True)
    return None


def escalate_and_advance(run_dir: Path, by: str, why: str = "", token_file: str | None = None, episode: int = 1,
                         AG=None, wait_s: float = 60.0) -> dict:
    """W-38（V2-WALK 11-02）：总调度转项目方定方向后，状态文件要立刻跟上，不能等下一次推进。
    在同一把推进锁里：① review_escalate_owner（凭令牌，写 judge_p1/STATE.json 的 owner_direction）② 立刻推进一次（source=escalate），
    verdict / next_action / autoflow_ep01.json 都由推进统一写（escalate 自己不写 verdict，免得状态两套来源）。
    拿不到锁（别的入口正在推进）最多等 wait_s 秒；还拿不到 = 报错，什么都不写。"""
    AG = AG or _load("autoflow_agent", "tools/script_rsi/autoflow_agent.py")
    t0 = time.time()
    while (lk := acquire_advance_lock(run_dir, episode, "escalate")) is None:
        if time.time() - t0 > wait_s:
            raise RuntimeError(f"第 {episode} 集正在被别的入口推进，{int(wait_s)} 秒内没拿到推进锁；没有转项目方，稍后再试")
        time.sleep(0.5)
    try:
        od = AG.review_escalate_owner(run_dir, by, why, token_file)
        advance_log(run_dir, "escalate", episode, verdict="owner_direction_requested",
                    note=f"总调度转项目方定方向：{by}；令牌 {od.get('token_digest8')}；pid {od.get('pid')}；用户 {od.get('user')}；第 {od.get('round')} 轮 {od.get('mean')}/40；{why}"[:300])
        try:
            d = AG.run(run_dir, episode, "dry")
        except Exception as e:
            advance_log(run_dir, "escalate", episode, verdict="error", note=repr(e)[:300])
            raise
    finally:
        lk.unlink(missing_ok=True)
    advance_log(run_dir, "escalate", episode, verdict=d.get("verdict"), note=str(d.get("next_action") or "")[:200])
    return {"owner_direction": od, "verdict": d.get("verdict"), "next_action": d.get("next_action")}


def cmd_run(a) -> int:
    run_dir = Path(a.run_dir) if Path(a.run_dir).is_absolute() else ROOT / a.run_dir
    AG = _load("autoflow_agent", "tools/script_rsi/autoflow_agent.py")
    be = a.backend or AG.backend()
    if be == "claude_agent":       # L-109：测试期写作 / 评审都交 agent，不调外部 API
        src = getattr(a, "source", "cli") or "cli"
        lk = acquire_advance_lock(run_dir, a.episode, src)
        if lk is None:
            advance_log(run_dir, src, a.episode, verdict="skipped_locked", note="同一集正在被别的入口推进，本次跳过")
            print(json.dumps({"verdict": "skipped_locked"}, ensure_ascii=False))
            return 0
        advance_log(run_dir, src, a.episode, note="开始")
        try:
            d = AG.run(run_dir, a.episode, a.import_mode)
        except Exception as e:
            advance_log(run_dir, src, a.episode, verdict="error", note=repr(e)[:300])
            raise
        finally:
            lk.unlink(missing_ok=True)
        advance_log(run_dir, src, a.episode, verdict=d.get("verdict"), note=str(d.get("next_action") or "")[:200])
        print(json.dumps({k: d.get(k) for k in ("verdict", "awaiting", "next_action")}, ensure_ascii=False, default=str))
        return 0
    if a.season_cap:
        idx_p = run_dir / STATUS
        if not idx_p.exists():
            season = 0.0                       # 整季第一集：还没有任何花费记录
        else:
            try:
                sv = json.loads(idx_p.read_text(encoding="utf-8")).get("season_usd")
            except (OSError, ValueError) as ex:
                print(json.dumps({"verdict": "season_budget_unknown", "error": repr(ex)[:200]}, ensure_ascii=False))
                return 2                        # 失败关闭：读不到整季花费就不开跑
            if sv is None:
                print(json.dumps({"verdict": "season_budget_unknown", "why": "有集的状态文件读不到"}, ensure_ascii=False))
                return 2
            season = float(sv)
        ep_p = run_dir / f"autoflow_ep{a.episode:02d}.json"      # 续跑：本集已花的已经算在 season 里，--budget 是本集总额
        prior_ep = float(json.loads(ep_p.read_text(encoding="utf-8")).get("usd_total") or 0) if ep_p.exists() else 0.0
        if season - prior_ep + a.budget > a.season_cap:
            print(json.dumps({"verdict": "season_budget_stop", "season_usd": season, "cap": a.season_cap}, ensure_ascii=False))
            return 2
    st = Status(run_dir, a.episode, a.budget)
    st.set(started=time.strftime("%F %T"), verdict="running", import_mode=a.import_mode)
    RCH = _load("run_chain", "tools/pipeline/run_chain.py")
    patch_chain(RCH)
    tag = f"autoflow-{run_dir.name}-ep{a.episode:02d}"     # 按集记账（P1 故事线记在第一集）
    ctx = run_links(RCH, run_dir, a.episode, st, tag, a.budget)
    st.set(usd_links=round(RCH.spent(tag), 4))
    if not ctx:
        st.set(verdict="stopped_in_chain", next_action="看失败段的校验报告，一键返修（续跑）")
        print(json.dumps(st.d, ensure_ascii=False)[:2000])
        return 1
    d = run_post(run_dir, a.episode, st, a.budget, a.import_mode, a.owner_ok)
    st.set(finished=time.strftime("%F %T"))
    print(json.dumps({k: d.get(k) for k in ("verdict", "usd_total", "next_action")}, ensure_ascii=False))
    return 0 if d.get("verdict") in ("importable", "imported") else 1


def cmd_test_brief(a) -> int:
    """测试 Brief 由写作模型生成（Claude 不写内容）：1 集、与现行剧无关、按 nsfs.brief/1 结构"""
    run_dir = Path(a.run_dir) if Path(a.run_dir).is_absolute() else ROOT / a.run_dir
    # 11-02 事故：在 V2 run 上误跑 test-brief，覆盖了刚写好的 P0_brief.json 且调了外部写作 API → 两道闸：
    # ① 已有 P0_brief.json 不覆盖（要测试请用新的空目录）；② writer_backend=claude_agent（L-109 测试期）时不调外部 API
    if (run_dir / "P0_brief.json").exists():
        print(json.dumps({"ok": False, "why": f"{run_dir.name} 已有 P0_brief.json，test-brief 不覆盖（测试请用新的空目录）"}, ensure_ascii=False))
        return 2
    AG = _load("autoflow_agent", "tools/script_rsi/autoflow_agent.py")
    if AG.backend() == "claude_agent" and not getattr(a, "allow_api", False):
        print(json.dumps({"ok": False, "why": "writer_backend=claude_agent（L-109）：test-brief 会调外部写作 API，默认不跑；确需请加 --allow-api"}, ensure_ascii=False))
        return 2
    run_dir.mkdir(parents=True, exist_ok=True)
    ex = (ROOT / "config/pipeline/examples/P0_brief.json").read_text(encoding="utf-8")
    w = FR.Writer(temperature=0.9, max_tokens=3000)
    user = ("为系统流程测试生成一份短剧提纲（nsfs.brief/1 结构，字段与下面示例相同）：只要第 1 集；竖屏短剧、60–120 秒；"
            "两个成年人物；一个场景；题材自定，但不得使用《漆皮之下·十日》及其人物（林晚、顾沉、陈宇、阿岚）；registry_from 留空数组；"
            "source 写 \"autoflow-test\"。只输出一个 ```json。\n\n示例结构：\n" + ex)
    raw = w("你是短剧提纲作者。", user)
    d, err = H._json_block(raw)
    if not d:
        print(err)
        return 1
    d["episodes"] = {"from": 1, "to": 1}
    d["source"] = "autoflow-test"
    write_json(run_dir / "P0_brief.json", d)
    write_json(run_dir / "test_brief_usage.json", w.usage)
    print(json.dumps({"title": d.get("title"), "usage": w.usage}, ensure_ascii=False))
    return 0


def locked_face() -> str:
    """林晚当前身份脸（K-OPS-E29：唯一入口 asset_refs.face_of，项目 = runs.json primary）"""
    sys.path.insert(0, str(ROOT / "services/agent"))
    from ns_agent import asset_refs as AR
    reg = json.loads((ROOT / "config/pipeline/runs.json").read_text(encoding="utf-8"))
    return AR.face_of(reg.get("primary"), "lin_wan") or "（读不到当前身份脸）"
HARD_RULES = ("系统硬约束：全部人物为成年人（≥22 岁）；一切亲密情节双方自愿；人物均为虚构，非真实人物；亲密内容在剧本里按平台规则写，"
              "亲密镜头只在本地生成；不改第一季已定的剧情事实和人物设定（人物、关系、造型、林晚身份脸）；缺信息标“未提供”，不编造。" + PLACEHOLDER_OVERRIDE)


def sequel_materials(prev_eps: list[int], material_md: Path | None, material_eps: list[int]) -> str:
    """续季素材（全部机械摘取原文，系统不写内容）：① 上一季现行导入稿各集集头（标题 / 剧情 / 出场人物 / 造型）+ 全剧人物登记 + 角色锁；
    ② 旧剧本素材（只读引用）指定集的标题与剧情行"""
    srcs = H.RC.episode_sources()
    out = ["【第一季（现行导入稿 data/import/script_v2.json，各集来源见 sources）结局状态与人物设定——原文摘录】"]
    pre0 = None
    for e in prev_eps:
        text, rec = H.RC.assemble(RL, [e], srcs)
        pre, ch = RL.split_doc(text)
        pre0 = pre0 or pre
        head = RL.block_text(ch[0], "head")
        keep = [ln for ln in head.splitlines() if ln.startswith(("## ep", "**剧情**", "**出场人物**", "**造型｜"))]
        out += keep + [""]
    if pre0:
        out.append("【第一季角色锁（原文）】")
        out += [ln.strip() for ln in pre0.splitlines() if ln.strip().startswith("【")]
        out.append("【第一季全剧人物表（原文）】")
        out += [ln for ln in pre0.splitlines() if ln.startswith("| ") and ln.count("|") >= 6 and not ln.startswith("| 角色") and not ln.startswith("|---")
                and re.search(r"\|\s*[a-z_]+\s*\|", ln)]
    out.append(f"【林晚身份脸（当前，不换人）】{locked_face()}")
    if material_md and material_md.exists():
        t = material_md.read_text(encoding="utf-8")
        out.append(f"\n【旧剧本素材（只读引用：{H.RC._rel(material_md)}，第 {material_eps[0]}–{material_eps[-1]} 集的标题与剧情行原文）】")
        for m in re.finditer(r"^## ep(\d+)[^\n]*\n(?:(?!^## ep).)*?^\*\*剧情\*\*：([^\n]*)", t, re.M | re.S):
            if int(m.group(1)) in material_eps:
                title = t[m.start():t.find("\n", m.start())]
                out.append(f"{title.strip()}｜{m.group(2).strip()}")
    return "\n".join(out)


def cmd_sequel_brief(a) -> int:
    run_dir = Path(a.run_dir) if Path(a.run_dir).is_absolute() else ROOT / a.run_dir
    quote = (run_dir / "owner_quote.txt").read_text(encoding="utf-8").strip()
    eps = sorted(H.RL.parse_episodes(a.episodes))
    mat = Path(a.material_md) if a.material_md else None
    mat = mat if (mat is None or mat.is_absolute()) else ROOT / mat
    brief = {"schema": "nsfs.brief/1", "title": a.title, "outline": quote,
             "episodes": {"from": eps[0], "to": eps[-1]}, "episode_lines": {}, "seconds_per_episode": [60, 120],
             "shots_per_ep": None, "registry_from": [],
             "notes": HARD_RULES + "\n\n" + sequel_materials(sorted(H.RL.parse_episodes(a.prev_episodes)), mat,
                                                          sorted(H.RL.parse_episodes(a.material_eps))),
             "source": f"#/script-create（项目方 02:4x 原话；L-104；系统组装 {time.strftime('%F %T')}）"}
    from ns_schema import storyline as SL
    rep = SL.check_brief(brief)
    write_json(run_dir / "P0_brief.json", brief)
    try:
        import runs as RUNS_REG
        reg = RUNS_REG.register_run(run_dir.name, source="flow-start", priority=10)
        d_ = RUNS_REG.registry(); d_["runs"][run_dir.name]["status"] = "writing"; RUNS_REG._js(RUNS_REG.RUNS, d_)   # 写作中，不派生产作业（DISTILL 约定）
    except Exception as e:  # noqa: BLE001
        reg = {"error": repr(e)[:200]}
    print(json.dumps({"brief_ok": rep.ok, "issues": [i.message for i in rep.issues][:5], "notes_chars": len(brief["notes"]),
                      "registered": reg}, ensure_ascii=False))
    return 0 if rep.ok else 1


def pending_done(run_dir: Path) -> list[int]:
    """哪几集“写手已交稿（awaiting.output 的 .done 在）但还没推进”——.done 守护据此推进"""
    eps = []
    for f in sorted(run_dir.glob("autoflow_ep*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        aw = d.get("awaiting") or {}
        out = aw.get("output")
        ep = int(d.get("episode") or int(f.stem[-2:]))
        if out and (ROOT / (out + ".done")).exists():
            eps.append(ep)
        elif d.get("verdict") == "awaiting_p1_judges":         # 三评委都交了（.done 齐）→ 推进一次：自动 p1_collect + 按门槛分流
            sp = run_dir / "judge_p1" / "STATE.json"
            if sp.exists():
                rounds = json.loads(sp.read_text(encoding="utf-8")).get("rounds") or []
                if rounds:
                    jd = ROOT / rounds[-1]["dir"]
                    tasks = list(jd.glob("judge_*/p1_review_task.json"))
                    done = [t for t in tasks if (t.parent / "out" / "p1_review.json.done").exists()]
                    if tasks and len(done) == len(tasks):
                        AG = _load("autoflow_agent", "tools/script_rsi/autoflow_agent.py")
                        if rounds[-1].get("collected_sig") != AG.judge_done_sig(jd):     # 同一组 .done 收过、没收齐（坏稿）→ 不空转，等评委重交
                            eps.append(ep)
    return eps


def cmd_watch(a) -> int:
    """.done 守护（总调度 11-02）：写手交稿只建 .done，由系统推进，不靠人点。每 interval 秒扫一遍；同一集正在推进时跳过"""
    import subprocess
    run_dirs = [Path(x) if Path(x).is_absolute() else ROOT / x for x in a.run_dir]
    procs: dict[tuple, subprocess.Popen] = {}
    while True:
        for rd in run_dirs:
            for ep in pending_done(rd):
                key = (str(rd), ep)
                p = procs.get(key)
                if p is not None and p.poll() is None:
                    continue
                procs[key] = subprocess.Popen([sys.executable, str(ROOT / "tools/script_rsi/autoflow.py"), "run", "--run-dir", str(rd),
                                               "--episode", str(ep), "--import", "dry", "--source", "daemon"], cwd=ROOT,
                                              env={**os.environ, "PYTHONUTF8": "1"})
        if a.once:
            for p in procs.values():
                p.wait(timeout=1800)
            return 0
        time.sleep(a.interval)


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--run-dir", required=True)
    r.add_argument("--episode", type=int, default=1)
    r.add_argument("--budget", type=float, default=None, help="默认 config/policies/budget.yaml writing_episode_cap_usd")
    r.add_argument("--import", dest="import_mode", choices=["dry", "live"], default="dry")
    r.add_argument("--owner-ok", action="store_true", help="项目方已在页面点选“导入”（L-098 闸门：只此一次点选）")
    r.add_argument("--backend", choices=["claude_agent", "api"], default=None,
                   help="写作后端；默认读 config/llm_providers.json writer_backend（L-109：测试期 claude_agent）")
    r.add_argument("--season-cap", type=float, default=None, help="整季写作上限（如 L-104 的 $8）；已花 + 本集预算超出就不开跑")
    r.add_argument("--source", choices=["cli", "web", "daemon", "escalate"], default="cli", help="推进来源（记进 autoflow.log）")
    rv = sub.add_parser("review-state", help="P1 三评委状态：--normalize 改回工具口径；--fix 追加返修意见（带 --by 来源）")
    rv.add_argument("--run-dir", required=True)
    rv.add_argument("--normalize", action="store_true")
    rv.add_argument("--fix", action="append", default=[])
    rv.add_argument("--by", default="")
    rv.add_argument("--replace", action="store_true", help="替换本轮旧的追加意见（旧的留档）")
    rv.add_argument("--escalate-owner", action="store_true", help="总调度动作：把当前这一稿（低于门槛）连同评分转给项目方定方向")
    rv.add_argument("--why", default="")
    rv.add_argument("--token-file", default="", help="总调度令牌文件（--escalate-owner 必须带；摘要对上 config/master/escalate.sha256 才放行）")
    w = sub.add_parser("watch", help=".done 守护：写手交稿（建 .done）后自动推进，来源记 daemon")
    w.add_argument("--run-dir", action="append", required=True)
    w.add_argument("--interval", type=int, default=30)
    w.add_argument("--once", action="store_true")
    q = sub.add_parser("sequel-brief", help="续季 Brief：项目方原话（owner_quote.txt）+ 上一季原文摘录 + 旧剧本素材 + 系统硬约束；并登记 run")
    q.add_argument("--run-dir", required=True)
    q.add_argument("--title", default="")
    q.add_argument("--episodes", default="1-10")
    q.add_argument("--prev-episodes", default="1-10")
    q.add_argument("--material-md", default="")
    q.add_argument("--material-eps", default="31-60")
    t = sub.add_parser("test-brief", help="生成一份测试 Brief（调外部写作 API；目录里已有 P0_brief.json 时拒绝）")
    t.add_argument("--run-dir", required=True)
    t.add_argument("--allow-api", action="store_true", help="writer_backend=claude_agent 时也允许调外部写作 API")
    s = sub.add_parser("status")
    s.add_argument("--run-dir", required=True)
    n = sub.add_parser("narrative-patch", help="N05 叙事补丁包：相邻 3 集结尾类型重复的集，请写手改结尾类型（剧情事实不变）")
    n.add_argument("--run-dir", required=True)
    n.add_argument("--episode", type=int, required=True)
    n.add_argument("--want", default="", help="只收这些结尾类型（逗号分隔，如 gaze_out）；不给 = 按整季现状算允许集合")
    n.add_argument("--why", default="")
    ro = sub.add_parser("reopen", help="补丁预算用尽后重开（清零逐项尝试计数，记 manual 历史；不动稿、不跳闸门）")
    ro.add_argument("--run-dir", required=True)
    ro.add_argument("--episode", type=int, required=True)
    ro.add_argument("--why", required=True)
    ro.add_argument("--by", default="HOLLYWOOD")
    a = ap.parse_args(argv)
    if a.cmd == "reopen":
        AG = _load("autoflow_agent", "tools/script_rsi/autoflow_agent.py")
        rd = Path(a.run_dir) if Path(a.run_dir).is_absolute() else ROOT / a.run_dir
        print(json.dumps(AG.reopen(rd, a.episode, a.why, a.by), ensure_ascii=False))
        return 0
    if a.cmd == "narrative-patch":
        AG = _load("autoflow_agent", "tools/script_rsi/autoflow_agent.py")
        rd = Path(a.run_dir) if Path(a.run_dir).is_absolute() else ROOT / a.run_dir
        out = AG.narrative_patch(rd, a.episode, [x.strip() for x in a.want.split(",") if x.strip()] or None, a.why)
        print(json.dumps(out, ensure_ascii=False))
        return 0 if out.get("ok") else 1
    if a.cmd == "run":
        if a.budget is None:
            import policy as POL
            a.budget = float(POL.get("budget.writing_episode_cap_usd", 3.0))
        return cmd_run(a)
    if a.cmd == "watch":
        return cmd_watch(a)
    if a.cmd == "review-state":
        AG = _load("autoflow_agent", "tools/script_rsi/autoflow_agent.py")
        rd = Path(a.run_dir) if Path(a.run_dir).is_absolute() else ROOT / a.run_dir
        if a.fix:
            if not a.by:
                print("追加意见要写 --by（来源）")
                return 2
            AG.review_add_fixes(rd, a.fix, a.by, replace=a.replace)
        if a.normalize:
            AG.review_state_normalize(rd)
        if a.escalate_owner:
            r = escalate_and_advance(rd, a.by, a.why, a.token_file or None, AG=AG)     # W-38：转完立刻推进一次，状态文件和日志一致
            print(json.dumps({"verdict": r["verdict"], "next_action": r["next_action"]}, ensure_ascii=False))
        print((rd / AG.REVIEW_STATE).read_text(encoding="utf-8")[:2000])
        return 0
    if a.cmd == "sequel-brief":
        return cmd_sequel_brief(a)
    if a.cmd == "test-brief":
        return cmd_test_brief(a)
    p = (Path(a.run_dir) if Path(a.run_dir).is_absolute() else ROOT / a.run_dir) / STATUS
    print(p.read_text(encoding="utf-8") if p.exists() else "{}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
