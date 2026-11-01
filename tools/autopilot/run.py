"""Autopilot：新剧本从 P0 故事提纲到 P12 成片的端到端驱动（ARCH 2026-10-31），不依赖 Claude。

段（连接 id 与 config/pipeline/chain.yaml / knowledge/links.yaml 对齐）：
  P0-P1 / P1-P2 / P2-P3  写作分段：CHAINSPEC 的 tools/pipeline/run_chain.run（config/pipeline/chain.yaml + 分段 prompt）
                         brief → storyline → 单集大纲 → 剧本 → P4 分镜 Markdown
  P3-P4  剧本 → 自检回路（格式校验 + llm_output_check + Shot Spec 缺字段，带错误回写作模型重写，最多 2 轮）→ Shot Spec
  P4-P5  资产：缺身份参考的角色 → 出四栏设定图候选（Qwen-Image 2.1，tools/ab/char_sheet_qi21.py）
         → 【闸门 characters】项目方挑（登记进 data/assets/identity_refs/manifest.json 即视为通过）
  P5-P6  首帧：没定稿首帧的镜头 → POST /api/shots/{id}/frame-jobs 出候选
         → 【闸门 frames】项目方在画布上定稿（takes.json locked.image 齐了即视为通过）
  P6-P10 出片 Loop（tools/iterate_loop：配方编译 → 6 道提交 → 审片打分 → 规则阶梯 → 合成）
  P10-P11 审片：审片导演（tools/autopilot/director.py，本地 VLM / 网关 / 规则兜底）→ verdicts → Loop 重出不合格镜
         → 审片页 data/review_pages/<集>/index.html（自动打开）
  P11-P12 【闸门 delivery】项目方看审片页点通过 → 成片交付
每段：状态落盘（data/autopilot/<run>/state.json）、事件日志、超时；中断后 run 继续。闸门停下时进程退出（exit 3），
项目方操作后再 run 即继续。

用法（项目根目录）：
  .venv/Scripts/python.exe tools/autopilot/run.py start --episode 3 --from P3 --dry-run --auto-approve   # 全链路演练（不出片、不调付费 API）
  .venv/Scripts/python.exe tools/autopilot/run.py start --episode 1 --brief config/pipeline/examples/P0_brief.json   # 从 P0 开始
  .venv/Scripts/python.exe tools/autopilot/run.py run|status --run-id <id>
  .venv/Scripts/python.exe tools/autopilot/run.py approve --run-id <id> --gate delivery [--note "…"]
"""
from __future__ import annotations

import argparse
import html
import json
import os
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for p in (HERE, ROOT / "tools" / "iterate_loop", ROOT / "services" / "recipes"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import director as DR  # noqa: E402
import roles as RL  # noqa: E402
import writer as WR  # noqa: E402
from store import Store, now, read_json, write_json  # noqa: E402

BASE = ROOT / "data" / "autopilot"
PAGES = ROOT / "data" / "review_pages"
STAGES = ("P0-P1", "P1-P2", "P2-P3", "P3-P4", "P4-P5", "P5-P6", "P6-P10", "P10-P11", "P11-P12")
GATES = {"P4-P5": "characters", "P5-P6": "frames", "P11-P12": "delivery"}
TIMEOUT_S = {"P0-P1": 1800, "P1-P2": 1800, "P2-P3": 3600, "P3-P4": 3600, "P4-P5": 3 * 3600, "P5-P6": 6 * 3600,
             "P6-P10": 48 * 3600, "P10-P11": 6 * 3600, "P11-P12": 7 * 24 * 3600}
EXIT_GATE = 3


def relp(p: Path) -> str:
    p = Path(p)
    return str(p.relative_to(ROOT)).replace("\\", "/") if p.is_relative_to(ROOT) else str(p)


def href(p: str | None, base: Path) -> str:
    if not p:
        return ""
    f = Path(p) if Path(p).is_absolute() else ROOT / p
    try:
        return os.path.relpath(f, base).replace("\\", "/")
    except ValueError:      # Windows 跨盘
        return f.as_uri()


class NeedsWriter(Exception):
    """写作方两轮自检后仍有 block 级缺口，整集停在 P3-P4 等写作方（exit 4）"""


EXIT_WRITER = 4


class GateWait(Exception):
    def __init__(self, gate: str, why: str):
        super().__init__(why)
        self.gate, self.why = gate, why


# ---------------------------------------------------------------------------------------------- 上下文
class Ctx:
    def __init__(self, store: Store, state: dict, *, dry: bool, auto_approve: bool, llm=None, director=None,
                 open_page: bool = True, log=print):
        self.store, self.state, self.dry, self.auto = store, state, dry, auto_approve
        self.llm = llm or (WR.MockWriter([]) if dry else WR.default_llm)
        self.director = director or (DR.RuleBased() if dry else DR.RuleBased())
        self.open_page, self.log = open_page, log
        self.ep = int(state["episode"])

    @property
    def dir(self) -> Path:
        return self.store.dir

    def save(self):
        self.store.save(self.state)

    def gate(self, name: str, satisfied: bool, why: str):
        g = self.state.setdefault("gates", {}).setdefault(name, {"status": "waiting", "since": now()})
        ap = read_json(self.dir / "gates" / f"{name}.json") or {}
        if satisfied or ap.get("approved"):
            g.update({"status": "passed", "at": now(), "by": ap.get("by") or "detected"})
            return
        if self.auto:
            g.update({"status": "passed", "at": now(), "by": "dry_run_auto_approve"})
            self.store.event("gate_auto", gate=name, why=why)
            return
        g.update({"status": "waiting", "why": why})
        self.save()
        raise GateWait(name, why)


# ---------------------------------------------------------------------------------------------- 写作分段
def stage_chain(ctx: Ctx, stage: str) -> dict:
    """P0-P1 / P1-P2 / P2-P3：调 CHAINSPEC 的链条执行器 tools/pipeline/run_chain.run（分段 prompt + 校验 + 断点续跑）。
    第一段一次跑到 P4（剧本分镜 Markdown），后两段读它的结果；产物在 <run>/chain/。dry-run 只组装 prompt 不调用模型。"""
    if stage != "P0-P1":
        r = (ctx.state["stages"]["P0-P1"].get("result") or {})
        st = next((x for x in r.get("stages", []) if x.get("link") == stage), None)
        return {"from_chain": True, "status": (st or {}).get("status", "n/a")}
    sys.path.insert(0, str(ROOT / "tools" / "pipeline"))
    from run_chain import run as chain_run
    brief = ctx.dir / "P0_brief.json"
    if not brief.exists():
        raise RuntimeError("从 P0 开始需要 brief（nsfs.brief/1 JSON，样例 config/pipeline/examples/P0_brief.json）")
    out = ctx.dir / "chain"
    kw = dict(tag=f"autopilot-{ctx.store.run_id}", budget=float(os.environ.get("NS_AUTOPILOT_BUDGET_USD", "8")),
              reasoning=False, dry=ctx.dry)
    # 可选闸门（默认关，项目方要求尽量自动）：--gate-storyline / --gate-outline 打开后，在 storyline / 单集大纲
    # 写完时停下等项目方看；run_chain 对已有且能过校验的产物会复用，所以分次跑不重复花钱
    for upto, gate in (("P1", "storyline"), ("P2", "outline")):
        if (ctx.state.get("optional_gates") or {}).get(gate) and not ctx.dry:
            chain_run(brief, ctx.ep, out, upto=upto, **kw)
            ctx.gate(gate, False, f"{gate} 已写好（{out}），请项目方看过后 approve")
    res = chain_run(brief, ctx.ep, out, upto="P4", **kw)
    stages = res.get("stages", [])
    bad = [x for x in stages if x.get("status") not in ("ok", "reused", "dry_run")]
    p4 = out / f"P4_ep{ctx.ep:02d}.md"
    if p4.exists():
        (ctx.dir / "P3_script.md").write_text(p4.read_text(encoding="utf-8"), encoding="utf-8")
    slim = {"stages": [{k: x.get(k) for k in ("link", "status", "rounds", "usd", "output")} for x in stages],
            "spent_usd": res.get("spent_tag_usd")}
    if any(x.get("status") == "needs_writer" for x in bad):
        raise NeedsWriter(f"写作链条停在 {[x['link'] for x in bad]}（见 {out}）")
    if bad:
        raise RuntimeError(f"写作链条未完成：{[(x['link'], x['status']) for x in bad]}")
    return slim


# ---------------------------------------------------------------------------------------------- P3-P4
def _episode_text(ctx: Ctx) -> tuple[str, str]:
    """→ (这一集的 Markdown, 来源)"""
    p = ctx.dir / "P3_script.md"
    from ns_api import script_chat as SC
    if p.exists() and p.read_text(encoding="utf-8").strip():
        eps = SC.split_episodes(p.read_text(encoding="utf-8"))
        if ctx.ep in eps:
            return eps[ctx.ep], str(p)
    from ns_render import pipeline as P
    si = P.load_script()
    src = next((s for s in si.sources if ctx.ep in (s.episodes or [])), si.sources[0])
    sp = Path(src.path) if Path(src.path).is_absolute() else ROOT / src.path
    eps = SC.split_episodes(sp.read_text(encoding="utf-8"))
    return eps.get(ctx.ep, ""), str(sp)


def stage_script_to_spec(ctx: Ctx) -> dict:
    text, src = _episode_text(ctx)
    if not text:
        raise RuntimeError(f"找不到 ep{ctx.ep:02d} 的剧本")
    strict = not ctx.dry and os.environ.get("NS_AUTOPILOT_STRICT", "1") == "1"
    issues = WR.selfcheck(text, ctx.ep, strict=strict, header=_header())
    res = {"source": src, "issues_before": len(issues), "rounds": 0}
    if issues:
        from ns_api import script_chat as SC
        system, _ = SC.prompt_for(text)
        msgs = [{"role": "system", "content": system},
                {"role": "user", "content": f"这是当前的 ep{ctx.ep:02d} 稿，下面按镜返修：\n\n" + text}]
        llm = ctx.llm if not isinstance(ctx.llm, WR.MockWriter) or ctx.llm.replies \
            else WR.MockWriter(["（mock 写作方：不改稿）"])
        r = WR.write_with_selfcheck(msgs, ctx.ep, llm=llm, max_rounds=_settings()["writer_selfcheck"]["max_rounds"],
                                    check=lambda t: WR.selfcheck(t, ctx.ep, strict=strict, header=_header()),
                                    log=ctx.log, initial=text, per_shot=True)
        res["repair_log"] = [n for t in r["transcript"] for n in t.get("notes", [])][:40]
        text = r["text"] or text
        res.update(rounds=r["rounds"], issues_after=len(r["issues"]), writer_ok=r["ok"],
                   remaining=[f"{i['shot']} {i['rule']}" for i in r["issues"]][:60])
    out = ctx.dir / f"ep{ctx.ep:02d}_P4.md"
    from ns_recipes import spec_import as SI
    # 规则版本章：稿件自带的优先（写作链路落稿时盖的）；写作模型在本段改过稿 → 当前规则版本；都没有 = unknown
    ver = SI.manuscript_rules_version(text)
    if res.get("rounds") and not isinstance(ctx.llm, WR.MockWriter):
        ver = SI.rules_version() or "unknown"
    out.write_text(f"<!-- rules_version: {ver} -->\n" + _header() + "\n\n" + text + "\n\n---\n", encoding="utf-8")
    res["rules_version"] = ver
    if not ctx.dry:
        res["timing_gate"] = enable_timing_gate(ctx.ep, ver)
    specs = SI.specs_from_markdown(out, ctx.ep)
    sd = ctx.dir / "specs"
    sd.mkdir(exist_ok=True)
    for s in specs:
        (sd / f"{s.id}.spec.json").write_text(s.model_dump_json(indent=1, by_alias=True), encoding="utf-8")
    res.update(script=relp(out), shots=len(specs))
    return res


def enable_timing_gate(ep: int, ver: str) -> bool:
    """K-PRM-I01 / K-WRT-I01 / K-WRT-I02：稿件盖了 sysimpl-v2 及以上的章 → 这一集的时间轴 / 分拍槽位 / 下镜按 error 校验
    （config/recipes/timing_lint.json episodes_error 局部追加；旧稿不动）"""
    import re as _re
    m = _re.search(r"sysimpl-v(\d+)", ver or "")
    if not (m and int(m.group(1)) >= 2):
        return False
    p = ROOT / "config" / "recipes" / "timing_lint.json"
    d = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"timing_lint_level": "warn", "episodes_error": []}
    eps = d.setdefault("episodes_error", [])
    if ep not in eps:
        eps.append(ep)
        p.write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return True


def _header() -> str:
    from ns_api import script_chat as SC
    return SC.script_header()[0]


def _settings() -> dict:
    import yaml
    return yaml.safe_load((ROOT / "knowledge" / "settings.yaml").read_text(encoding="utf-8"))


def _specs(ctx: Ctx):
    from ns_recipes import spec_import as SI
    return SI.specs_from_markdown(ctx.dir / f"ep{ctx.ep:02d}_P4.md", ctx.ep)


# ---------------------------------------------------------------------------------------------- P4-P5 / P5-P6
def stage_assets(ctx: Ctx) -> dict:
    specs = _specs(ctx)
    need = sorted({(c.id, c.name) for s in specs for c in s.faces if c.identity_ref is None})
    plan = [{"character": n, "id": cid,
             "command": f".venv/Scripts/python.exe tools/ab/char_sheet_qi21.py sheets --only {cid} --seeds 101,202",
             # CONSIST：候选出来后在 gpu36 排序（ArcFace），排序结果给项目方参考，不代选
             "rank_command": RL.identity_rank_command(cid, [f"data/ab/char_sheets/{cid}/*.png"])}
            for cid, n in need]
    if need and not ctx.dry:
        for p in plan:
            subprocess.Popen(p["command"].split(), cwd=str(ROOT))     # 只出候选到 data/ab/char_sheets/，不改定妆
    write_json(ctx.dir / "gates" / "characters.todo.json", {"need": plan, "how": "项目方挑定后用资产页登记身份图"
                                                            "（写入 data/assets/identity_refs/manifest.json）"})
    inv = asset_inventory(ctx)
    ctx.gate("characters", not need, f"{len(need)} 个角色缺身份参考：{[n for _, n in need]}")
    return {"missing_identity": [n for _, n in need], "candidates": plan, "asset_inventory": inv}


def asset_inventory(ctx: Ctx) -> dict:
    """ASSETMASTER（2026-11-01）：剧本导入后自动盘点"角色×造型×单品"，缺图 / 不合格 / 待确认自动列入待补
    （tools/assetmaster/scan.py；待补队列 data/assetmaster/todo.json，补图走 tools/assetmaster/gen_items.py）。
    不设闸门：缺单品图由出图 preflight（GEN_CONTRACT I4）在提交时阻断。盘点失败不影响本段。"""
    run = Path(ctx.dir)
    if not (run / "P1_looks.json").exists():
        return {"skipped": "本次运行目录没有 P1_looks.json（造型登记），不盘点"}
    try:
        sys.path.insert(0, str(ROOT / "tools" / "assetmaster"))
        import scan as AM
        r = AM.scan(run.resolve(), do_qc=not ctx.dry)
        out = run / "gates" / "assets_inventory.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        write_json(out, {"summary": r["summary"], "issue_counts": r["issue_counts"], "todo": r["todo"], "issues": r["issues"]})
        return {"summary": r["summary"], "issues": r["issue_counts"], "todo": len(r["todo"]), "file": relp(out)}
    except Exception as e:  # noqa: BLE001
        return {"error": repr(e)[:300]}


def stage_first_frames(ctx: Ctx) -> dict:
    specs = _specs(ctx)
    todo = [s.id for s in specs if "first" not in s.keyframes]
    plan = [{"shot": sid, "endpoint": f"POST /api/shots/{sid}/frame-jobs", "body": {"stage": "first", "by": "autopilot"}}
            for sid in todo]
    if todo and not ctx.dry:
        import urllib.request
        for p in plan:
            req = urllib.request.Request(f"http://127.0.0.1:8800/api/shots/{p['shot']}/frame-jobs",
                                         data=json.dumps(p["body"]).encode(), method="POST",
                                         headers={"Content-Type": "application/json"})
            try:
                urllib.request.urlopen(req, timeout=30).read()
            except Exception as e:  # noqa: BLE001
                ctx.store.event("frame_job_error", shot=p["shot"], error=str(e))
    write_json(ctx.dir / "gates" / "frames.todo.json", {"need": todo, "how": "在画布上给每镜定稿首帧（锁定）"})
    ctx.gate("frames", not todo, f"{len(todo)} 镜首帧未定稿")
    return {"unlocked_first_frames": todo, "requested": len(plan)}


# ---------------------------------------------------------------------------------------------- P6-P10 / P10-P11
def _loop_args(ctx: Ctx, cmd: str):
    import loop as LP
    a = argparse.Namespace(cmd=cmd, run_id=f"{ctx.store.run_id}_loop", episode=ctx.ep,
                           script=str(ctx.dir / f"ep{ctx.ep:02d}_P4.md"), shots=None, dry_run=ctx.dry,
                           scenario=ctx.state.get("scenario"), api=os.environ.get("NS_API", "http://127.0.0.1:8800"),
                           graph_passthrough=False, poll=30.0, max_ticks=None)
    return LP, a


def stage_loop(ctx: Ctx) -> dict:
    LP, a = _loop_args(ctx, "start")
    lstore = Store(a.run_id)
    state = lstore.load()
    lp = LP.build(a, lstore, state)
    if not state:
        lp.init(ctx.ep)
    lp.run(poll_s=0.0 if ctx.dry else 30.0, max_ticks=None if not ctx.dry else 2000)
    st = lp.state
    ctx.state["loop_run"] = a.run_id
    res = {"loop_run": a.run_id, "status": st["status"], "version": st["version"],
           "shots": {k: v["status"] for k, v in st["shots"].items()}}
    if st["status"] != "version_done":
        raise RuntimeError(f"出片 Loop 未收版（{st['status']}）；loop.py status --run-id {a.run_id}")
    writer = {k: v.get("note") for k, v in st["shots"].items() if v["status"] == "needs_writer"}
    if writer:   # 写作方两轮自检后仍缺的字段：打包成【格式返修】请求，交写作网关 / 总调度
        lines = [f"- {k}：{n}" for k, n in writer.items()]
        head = f"# ep{ctx.ep:02d} 交写作方（Autopilot 自动生成，只列格式 / 可实现性缺口）\n\n"
        (ctx.dir / "writer_requests.md").write_text(head + "\n".join(lines) + "\n", encoding="utf-8")
    passed = [k for k, v in st["shots"].items() if v["status"] == "passed"]
    if not passed:
        if writer:
            raise NeedsWriter(f"没有一镜能出片（{len(writer)} 镜交写作方，见 writer_requests.md）")
        raise RuntimeError("没有一镜通过（全部待项目方 / 待接入点），见 loop 的 v 版审片报告")
    return res | {"passed": len(passed), "needs_writer": sorted(writer)}


def stage_review(ctx: Ctx) -> dict:
    LP, a = _loop_args(ctx, "run")
    lstore = Store(a.run_id)
    rounds = 0
    while True:
        verdicts = DR.review_run(lstore, ctx.director, min_conf=_settings()["director"]["min_confidence_to_act"])
        lp = LP.build(a, lstore, lstore.load())
        acts = [s for s, v in verdicts.items() if v.get("verdict") == "fail" and v.get("action") == "reseed"
                and lp.state["shots"].get(s, {}).get("status") == "passed"]
        if not acts or rounds >= 2:
            break
        lp.state["status"] = "running"
        lp.run(poll_s=0.0 if ctx.dry else 30.0, max_ticks=None if not ctx.dry else 2000)
        rounds += 1
    page = review_page(ctx, lstore)
    return {"verdicts": {k: v["verdict"] for k, v in verdicts.items()}, "director_rounds": rounds,
            "page": relp(page)}


def review_page(ctx: Ctx, lstore: Store) -> Path:
    st = lstore.load() or {}
    vd = lstore.verdicts()
    out = PAGES / f"ep{ctx.ep:02d}" / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    rel = lambda p: href(p, out.parent)  # noqa: E731
    v = str(st.get("version", 1))
    vid = (st.get("versions", {}).get(v) or {}).get("assembled") or ""
    rows = []
    for sid, sh in (st.get("shots") or {}).items():
        d = vd.get(sid) or {}
        sheet = sh.get("sheet")
        rows.append(f"<tr><td>{html.escape(sid)}</td><td class='st {html.escape(sh['status'])}'>{html.escape(sh['status'])}</td>"
                    f"<td>{html.escape(str(sh.get('recipe') or ''))}</td><td>{sh.get('renders', 0)}</td>"
                    f"<td>{html.escape(d.get('verdict', '—'))} / {html.escape(d.get('action', ''))}<br>"
                    f"<small>{html.escape('；'.join(d.get('issues') or []))}</small></td>"
                    f"<td><small>{html.escape(sh.get('note') or '')}</small></td>"
                    f"<td>{f'<a href={chr(34)}{rel(sheet)}{chr(34)}><img src={chr(34)}{rel(sheet)}{chr(34)}></a>' if sheet else '—'}</td></tr>")
    gates = "".join(f"<li><b>{html.escape(k)}</b>：{html.escape(g.get('status', ''))} {html.escape(g.get('why', '') or '')}</li>"
                    for k, g in (ctx.state.get("gates") or {}).items())
    cmd = f".venv/Scripts/python.exe tools/autopilot/run.py approve --run-id {ctx.store.run_id} --gate delivery"
    doc = f"""<!doctype html><html lang="zh"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ep{ctx.ep:02d} 审片</title><style>
:root{{--bg:#fafaf8;--fg:#1d1d1b;--mut:#6b6b66;--line:#e2e1dc;--ok:#1f7a3f;--bad:#b3261e;--warn:#9a6700}}
@media (prefers-color-scheme:dark){{:root{{--bg:#161615;--fg:#ecebe6;--mut:#a3a29c;--line:#33322f;--ok:#5fc27e;--bad:#f2786d;--warn:#e0b44a}}}}
body{{background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif;margin:0;padding:16px;max-width:1200px;margin:auto}}
table{{border-collapse:collapse;width:100%}}td,th{{border-bottom:1px solid var(--line);padding:6px;vertical-align:top;text-align:left}}
img{{max-width:220px}}small{{color:var(--mut)}}.passed{{color:var(--ok)}}.owner,.failed,.needs_writer{{color:var(--bad)}}
.needs_api,.needs_keyframe,.blocked{{color:var(--warn)}}code{{background:var(--line);padding:2px 4px;border-radius:4px}}
.wrap{{overflow-x:auto}}</style></head><body>
<h1>ep{ctx.ep:02d} 审片（Autopilot {html.escape(ctx.store.run_id)}，第 {v} 版）</h1>
<p>成片：{f'<a href="{rel(vid)}">{html.escape(vid)}</a>' if vid and not str(vid).startswith(str(ROOT / '.venv')) and Path(str(vid)).suffix == '.mp4' else html.escape(str(vid) or '（未合成）')}</p>
<h2>闸门</h2><ul>{gates}</ul>
<p>看完没问题：<code>{html.escape(cmd)}</code>（或在 data/autopilot/{html.escape(ctx.store.run_id)}/gates/delivery.json 写 {{"approved": true, "by": "owner"}}）。
某镜不行：在 data/iterate_loop/{html.escape(st.get('run_id', ''))}/director/verdicts.json 给该镜写 {{"verdict":"fail","action":"reseed"}}，再运行 run。</p>
<div class="wrap"><table><tr><th>镜</th><th>状态</th><th>配方</th><th>出片次数</th><th>审片判定</th><th>备注</th><th>接触印样</th></tr>
{''.join(rows)}</table></div></body></html>"""
    out.write_text(doc, encoding="utf-8")
    if ctx.open_page:
        try:
            webbrowser.open(out.as_uri())
        except Exception:  # noqa: BLE001
            pass
    return out


def stage_delivery(ctx: Ctx) -> dict:
    ctx.gate("delivery", False, "项目方看审片页后确认交付")
    return {"delivered_at": now()}


RUNNERS = {"P0-P1": lambda c: stage_chain(c, "P0-P1"), "P1-P2": lambda c: stage_chain(c, "P1-P2"),
           "P2-P3": lambda c: stage_chain(c, "P2-P3"), "P3-P4": stage_script_to_spec, "P4-P5": stage_assets,
           "P5-P6": stage_first_frames, "P6-P10": stage_loop, "P10-P11": stage_review, "P11-P12": stage_delivery}


# ---------------------------------------------------------------------------------------------- 驱动
def init_state(run_id: str, episode: int, start: str, *, dry: bool, outline: str | None, scenario: str | None) -> dict:
    st = {"schema": "nsfs.autopilot/1", "run_id": run_id, "episode": episode, "dry_run": dry, "created_at": now(),
          "start": start, "scenario": scenario, "stages": {}, "gates": {}}
    for s in STAGES:
        st["stages"][s] = {"status": "skipped" if STAGES.index(s) < STAGES.index(start) else "pending"}
    return st


def drive(ctx: Ctx) -> int:
    for s in STAGES:
        rec = ctx.state["stages"][s]
        if rec["status"] in ("done", "skipped"):
            continue
        rec.setdefault("started", now())
        rec["status"] = "running"
        ctx.save()
        ctx.store.event("stage_start", stage=s)
        t0 = time.monotonic()
        try:
            res = RUNNERS[s](ctx)
        except GateWait as g:
            rec["status"] = "waiting_owner"
            rec["gate"] = g.gate
            ctx.save()
            ctx.store.event("gate_wait", stage=s, gate=g.gate, why=g.why)
            ctx.log(f"[autopilot] {s} 停在项目方闸门「{g.gate}」：{g.why}")
            return EXIT_GATE
        except NeedsWriter as e:
            rec["status"] = "needs_writer"
            rec["error"] = str(e)
            ctx.save()
            ctx.store.event("needs_writer", stage=s, why=str(e))
            ctx.log(f"[autopilot] {s} 停下等写作方：{e}")
            return EXIT_WRITER
        except Exception as e:  # noqa: BLE001
            rec["status"] = "failed"
            rec["error"] = f"{type(e).__name__}: {e}"
            ctx.save()
            ctx.store.event("stage_failed", stage=s, error=rec["error"])
            ctx.log(f"[autopilot] {s} 失败：{rec['error']}")
            return 1
        el = time.monotonic() - t0
        rec.update(status="done", finished=now(), result=res, elapsed_s=round(el, 1),
                   over_timeout=el > TIMEOUT_S[s])
        ctx.save()
        ctx.store.event("stage_done", stage=s, elapsed_s=round(el, 1))
        ctx.log(f"[autopilot] {s} 完成（{el:.1f}s）")
    ctx.state["status"] = "done"
    ctx.save()
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("start", "run", "status", "approve", "roles", "report-bug", "learn-workflows"))
    ap.add_argument("--symptom", action="append", default=[], help="report-bug：审片 / 项目方反馈的问题（可多次）")
    ap.add_argument("--dir", help="learn-workflows：新工作流目录")
    ap.add_argument("--run-id")
    ap.add_argument("--episode", type=int)
    ap.add_argument("--from", dest="start", default="P0-P1", choices=STAGES + ("P0", "P3"))
    ap.add_argument("--brief", help="P0 故事提纲 brief（nsfs.brief/1 JSON；从 P0 开始时必给）")
    ap.add_argument("--dry-run", action="store_true", help="不出图 / 不出片 / 不调付费 API（写作与审片用 mock）")
    ap.add_argument("--auto-approve", action="store_true", help="dry-run 演练用：闸门自动通过（记为 dry_run_auto_approve）")
    ap.add_argument("--scenario", help="dry-run 审片指标脚本（同 iterate_loop）")
    ap.add_argument("--gate-storyline", action="store_true", help="可选闸门：storyline 写完停下给项目方看（默认关）")
    ap.add_argument("--gate-outline", action="store_true", help="可选闸门：单集大纲写完停下给项目方看（默认关）")
    ap.add_argument("--gate")
    ap.add_argument("--note", default="")
    ap.add_argument("--no-open", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "roles":
        print(RL.table_md())
        return 0
    if a.cmd == "learn-workflows":
        if not a.dir:
            ap.error("learn-workflows 需要 --dir")
        out = ROOT / "docs" / "workflow_learn" / (Path(a.dir).name + ".md")
        out.parent.mkdir(parents=True, exist_ok=True)
        for c in RL.learn_workflows(a.dir, str(out)):
            print("$", c)
            r = subprocess.run(c, shell=True, cwd=str(ROOT))
            if r.returncode:
                return r.returncode
        return 0
    if a.cmd == "report-bug":
        if not a.symptom:
            ap.error("report-bug 需要 --symptom")
        res = RL.attribute_bug(a.symptom, a.episode, write=True)
        print(res["out"] or res["err"])
        if a.run_id:
            Store(a.run_id, base=BASE).event("report_bug", symptoms=a.symptom, rc=res["rc"])
        return res["rc"]
    start = {"P0": "P0-P1", "P3": "P3-P4"}.get(a.start, a.start)
    run_id = a.run_id or (f"ep{a.episode:02d}_{'dry' if a.dry_run else 'live'}_{time.strftime('%Y%m%d_%H%M%S')}"
                          if a.episode else None)
    if not run_id:
        ap.error("需要 --run-id 或 --episode")
    store = Store(run_id, base=BASE)
    state = store.load()
    if a.cmd == "approve":
        write_json(store.dir / "gates" / f"{a.gate}.json", {"approved": True, "by": "owner", "at": now(), "note": a.note})
        store.event("gate_approved", gate=a.gate, note=a.note)
        print(f"闸门 {a.gate} 已通过，运行 run 继续")
        return 0
    if a.cmd == "status":
        print(json.dumps({k: state.get(k) for k in ("run_id", "episode", "status", "stages", "gates")} if state
                         else {"error": "没有这个 run"}, ensure_ascii=False, indent=1))
        return 0 if state else 1
    if a.cmd == "start" and not state:
        state = init_state(run_id, a.episode, start, dry=a.dry_run, outline=a.brief, scenario=a.scenario)
        state["optional_gates"] = {"storyline": a.gate_storyline, "outline": a.gate_outline}
        if start == "P0-P1":
            if not a.brief:
                ap.error("从 P0 开始需要 --brief")
            (store.dir / "P0_brief.json").write_text(Path(a.brief).read_text(encoding="utf-8"), encoding="utf-8")
        store.save(state)
        store.event("init", episode=a.episode, start=start, dry_run=a.dry_run)
    ctx = Ctx(store, state, dry=bool(state.get("dry_run")), auto_approve=a.auto_approve and bool(state.get("dry_run")),
              open_page=not a.no_open)
    return drive(ctx)


if __name__ == "__main__":
    sys.exit(main())
