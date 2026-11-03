"""角色手册 → 代码（ARCH 2026-10-31）：这几天每个 agent 做的“需要判断”的事，现在由哪段代码 / 哪个审片 prompt / 哪个项目方闸门完成。

每个角色：手册 docs/playbooks/<id>.md；负责的链条连接；判断步骤 → 实现方式：
  code   = 确定性代码（给出命令或函数）
  prompt = LLM / VLM 按知识库生成的提示词判断（config/recipes/*.md）
  owner  = 项目方闸门（系统停下，做完再继续）
Autopilot（tools/autopilot/run.py）在对应段调用这些入口；`run.py roles` 打印总表，`run.py report-bug` 走 CHAINSPEC 归因。
"""
from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PY = ".venv/Scripts/python.exe"

ROLES: dict[str, dict] = {
    "DIR": {
        "name": "剪辑导演 / 审片", "links": ["P10-P11", "P11-RETRY", "P8-P10"],
        "steps": [
            {"step": "逐镜机器指标 + 接触印样", "how": "code", "entry": f"{PY} tools/ep02_director/review.py clips / episode …",
             "autopilot": "P6-P10（iterate_loop.reviewer.ReviewPy）"},
            {"step": "7 维打分、判定 → 动作", "how": "prompt", "entry": "tools/autopilot/director.py（config/recipes/director_system_prompt.md）",
             "autopilot": "P10-P11"},
            {"step": "脸部泛红逐帧追踪", "how": "code", "entry": f"{PY} tools/ep02_director/red_trace.py …", "autopilot": "按需"},
            {"step": "成片能不能给项目方看", "how": "owner", "entry": "审片页 data/review_pages/<集>/ → delivery 闸门", "autopilot": "P11-P12"},
        ]},
    "LAB": {
        "name": "配方对照实验", "links": ["P7-P8", "P10-P11"],
        "steps": [
            {"step": "按道串行提交对照", "how": "code", "entry": f"{PY} tools/lab_ep02/lab_queue.py plan.json / lab_runner.py submit …",
             "autopilot": "配方 status=待验 时由总调度开实验（不自动花 GPU）"},
            {"step": "对照打分（运动、J4、硬切、泛红、身份）", "how": "code", "entry": f"{PY} tools/lab_ep02/lab_score.py <out> name=path …",
             "autopilot": "实验结束后写 knowledge/rules（证据）→ compile.py"},
            {"step": "结论是否升为默认", "how": "code", "entry": "iterate_loop 写回（learned.yaml 待验→建议→确认）+ knowledge 规则 status",
             "autopilot": "P6-P10 收版自动"},
        ]},
    "FIX": {
        "name": "止血修复 / 剪辑规则", "links": ["P4-P7", "P8-P10", "P9-P10"],
        "steps": [
            {"step": "提交前 lint 闸门（I2VA Picture 2、H3 结构）", "how": "code", "entry": "ns_render.h3_video.submit_lint / ns_recipes.lint",
             "autopilot": "P6-P10 编译与提交"},
            {"step": "合成规则（只取通过版本、剪定住段、bt709、skin guard、溢出判失败）", "how": "code",
             "entry": f"{PY} tools/assemble_episode.py epNN --sources-from … --variant …", "autopilot": "P6-P10 收版合成"},
            {"step": "依赖变更标脏", "how": "code", "entry": "ns_agent.asset_revs（registry:/identity:/vbase:… 依赖键）",
             "autopilot": "被动：take 读时比对"},
        ]},
    "PROMPT": {
        "name": "提示词 / 写作规则", "links": ["P3-P4", "P4-P7"],
        "steps": [
            {"step": "分拍 / 视线 / 表情 / 衔接 / 时间轴 lint", "how": "code", "entry": "ns_recipes.lint.lint_timeline（RL-T1–T7）+ ns_schema.shot_spec.missing_fields（SS-M*）",
             "autopilot": "P3-P4 自检 + P6-P10 编译"},
            {"step": "写作规则附录与知识包", "how": "code", "entry": "config/script_chat_rules.md 附录 sysimpl-vN + config/recipes/writer_knowledge.md（compile.py 生成）",
             "autopilot": "写作模型每次加载"},
            {"step": "缺字段 → 返修", "how": "prompt", "entry": "tools/autopilot/writer.py（逐镜【格式返修】，最多 2 轮）", "autopilot": "P3-P4"},
        ]},
    "CONSIST": {
        "name": "人物一致性", "links": ["P4-P5", "P5-P6", "P10-P11"],
        "steps": [
            {"step": "缺身份参考 → 四栏设定图候选", "how": "code", "entry": f"{PY} tools/ab/char_sheet_qi21.py sheets --only <id>",
             "autopilot": "P4-P5"},
            {"step": "候选排序（ArcFace 对参考 / 互相区分度）", "how": "code",
             "entry": "gpu36: /root/work/fredw/venv_idm/bin/python tools/identity_metric.py --ref … <候选>",
             "autopilot": "P4-P5 闸门前（只给排序，不代选）"},
            {"step": "挑定身份图", "how": "owner", "entry": "资产页登记 → data/assets/identity_refs/manifest.json", "autopilot": "characters 闸门"},
            {"step": "出片后身份闸门", "how": "code", "entry": "review.py SFace / identity_metric ArcFace → rules R-ID", "autopilot": "P6-P10"},
        ]},
    "VOICE": {
        "name": "配音 / 音色", "links": ["P4-P9", "P8-P9"],
        "steps": [
            {"step": "对白回听（CER、基频、语速）与换种子试听", "how": "code", "entry": f"{PY} tools/ab_voice_fix.py render / analyze",
             "autopilot": "按需（花 GPU 由总调度开）"},
            {"step": "单句换音色（保嘴型）", "how": "code", "entry": f"{PY} tools/voice_convert_shot.py <镜> --reference <wav>",
             "autopilot": "config post.voice_conversion.enabled 时合成自动"},
            {"step": "挑 narrator / 角色音色", "how": "owner", "entry": "试听表 data/ab/voice_fix/table.md → 写 config/voices.json",
             "autopilot": "K-EDT-016（series10 音色只来自 <char>_cand，L-078 系统按 QAg 方法自动选；旁白 K-EDT-013）"},
        ]},
    "CHAINSPEC": {
        "name": "链条契约 / 上游写作", "links": ["P0-P1", "P1-P2", "P2-P3", "P3-P4", "P11-RETRY"],
        "steps": [
            {"step": "提纲 → storyline → 大纲 → 剧本 → 分镜", "how": "prompt",
             "entry": f"{PY} tools/pipeline/run_chain.py --brief … --episode N --out …（config/pipeline/prompts/<link>.md）",
             "autopilot": "P0-P1（一次跑到 P4，断点续跑）"},
            {"step": "审片问题归因到连接 → 规则草案", "how": "code",
             "entry": f"{PY} tools/pipeline/attribute_bug.py \"<症状>\" --episode N --write", "autopilot": "run.py report-bug"},
            {"step": "草案确认", "how": "owner", "entry": "knowledge/inbox/ → knowledge/rules/（总调度）", "autopilot": "人工"},
        ]},
    "WFLIB": {
        "name": "工作流学习（WFLIB / CIVIT / RHUB）", "links": ["P7-P8"],
        "steps": [
            {"step": "解析新工作流参数", "how": "code", "entry": f"{PY} -I tools/workflow_lib/parse.py <目录> --out parsed.json",
             "autopilot": "run.py learn-workflows <目录>"},
            {"step": "生成参数对照报告", "how": "code", "entry": f"{PY} -I tools/workflow_lib/report.py parsed.json <out.md>",
             "autopilot": "同上"},
            {"step": "社区权重许可", "how": "owner", "entry": "community_pending.yaml 待许可登记 → 项目方 / 总调度登记", "autopilot": "人工"},
        ]},
    "UIRSI": {
        "name": "竞品与 UI 迭代", "links": ["P10-P11", "P11-P12"],
        "steps": [
            {"step": "审片页 / 闸门页生成", "how": "code", "entry": "tools/autopilot/run.py review_page → data/review_pages/<集>/index.html",
             "autopilot": "P10-P11"},
            {"step": "画布 UI 问题收集与修", "how": "owner", "entry": "apps/web（UI agent / 项目方验收）", "autopilot": "不在 Autopilot 内"},
        ]},
    "ARCH": {
        "name": "系统架构 / 配方引擎 / Loop", "links": ["P4-P7", "P6-P7", "P7-P8", "P11-RETRY"],
        "steps": [
            {"step": "选配方 + 编译（plan_hash）", "how": "code", "entry": "services/recipes/ns_recipes（selector / compiler）", "autopilot": "P6-P10"},
            {"step": "出片 Loop（规则阶梯 + 写回）", "how": "code", "entry": f"{PY} tools/iterate_loop/loop.py start / run / status …", "autopilot": "P6-P10"},
            {"step": "知识库校验与生成", "how": "code", "entry": f"{PY} tools/knowledge/compile.py [--check] [--episode N]", "autopilot": "规则变更时"},
        ]},
}


def table_md() -> str:
    lines = ["| 角色 | 负责连接 | 判断步骤 | 方式 | 入口 | Autopilot 位置 |", "|---|---|---|---|---|---|"]
    how = {"code": "代码", "prompt": "LLM/VLM 提示词", "owner": "**项目方闸门**"}
    for rid, r in ROLES.items():
        for i, s in enumerate(r["steps"]):
            lines.append(f"| {rid if i == 0 else ''} | {', '.join(r['links']) if i == 0 else ''} | {s['step']} | "
                         f"{how[s['how']]} | `{s['entry']}` | {s['autopilot']} |")
    return "\n".join(lines) + "\n"


def attribute_bug(symptoms: list[str], episode: int | None = None, write: bool = True, run: str | None = None) -> dict:
    """CHAINSPEC 归因（确定性，不调 LLM）：审片 / 项目方反馈 → 连接 → 规则草案 knowledge/inbox/。
    run = 哪部剧的导入稿（不给 = 当前剧，MERGE-OPS-O）"""
    cmd = [str(ROOT / PY), str(ROOT / "tools" / "pipeline" / "attribute_bug.py"), *symptoms]
    if run:
        cmd += ["--run", run]
    if episode:
        cmd += ["--episode", str(episode)]
    if write:
        cmd.append("--write")
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(ROOT), timeout=900)
    return {"rc": r.returncode, "out": (r.stdout or "")[-4000:], "err": (r.stderr or "")[-1000:], "cmd": " ".join(cmd)}


def learn_workflows(directory: str, out_md: str) -> list[str]:
    """WFLIB：新到的工作流目录 → 解析 + 报告（只读解析，不执行工作流）。返回要运行的命令（调用方决定是否执行）"""
    parsed = str(Path(out_md).with_suffix(".parsed.json"))
    return [f"{PY} -I tools/workflow_lib/parse.py \"{directory}\" --out \"{parsed}\"",
            f"{PY} -I tools/workflow_lib/report.py \"{parsed}\" \"{out_md}\""]


def identity_rank_command(char_id: str, candidates: list[str], ref: str | None = None) -> str:
    """CONSIST：候选设定图对已定参考（或候选之间）做 ArcFace 排序的命令（在 gpu36 venv 跑）"""
    refs = f"--ref {char_id}={ref} " if ref else ""
    items = " ".join(f"c{i}={p}" for i, p in enumerate(candidates))
    return f"/root/work/fredw/venv_idm/bin/python identity_metric.py {refs}--out out/{char_id}_rank {items}"
