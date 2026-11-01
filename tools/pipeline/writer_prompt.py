"""写作 LLM 分段提示词组装（CHAINSPEC 2026-10-31）。

    build(link, inputs) -> {"system": str, "user": str, "parts": [...]}

link ∈ P0-P1 / P1-P2 / P2-P3 / P3-P4。system = config/pipeline/prompts/<link>.md 模板，
{{RULES}} ← chain.yaml 该连接的上游规则（writer_text，带规则号），{{KNOWLEDGE}} ← knowledge/rules/*.yaml 里 link 指向该连接、
状态为 确认 / 建议 的 writer_text，{{EXAMPLE}} ← 该连接输出节点的样例文件。
P3-P4 的 system 先接现行写作系统提示词（ns_api.script_chat.prompt_for：script_chat_rules.md + 按触发词附录 + 全局头），
再追加链条附加段——现行加载点不变，只多一段。
只组装格式与可实现性规则，不写剧情、不评价内容。

    .venv/Scripts/python.exe tools/pipeline/writer_prompt.py P1-P2 --show     # 打印组装后的 system
"""
from __future__ import annotations

import argparse
import json
import sys

from chainlib import ROOT, chain, knowledge_for, rules_for
import p4_fragments as PF

TEMPLATES = {k: ROOT / "config" / "pipeline" / "prompts" / f"{k}.md" for k in ("P0-P1", "P1-P2", "P2-P3", "P3-P4")}


def _strip_comment(t: str) -> str:
    return "\n".join(ln for ln in t.splitlines() if not ln.startswith("<!--")).strip()


def rules_block(link: str) -> str:
    out = []
    for r in rules_for(link):
        if (r.get("writer_text") or "").startswith("（系统用）"):
            continue
        lvl = "必须" if r.get("level") == "block" else "建议"
        out.append(f"- 【{r['id']}｜{lvl}】{r['writer_text']}")
    return "\n".join(out)


def knowledge_block(link: str) -> str:
    rs = knowledge_for(link, writer_only=True)
    if not rs:
        return ""
    return "\n已学到的可实现性规则（knowledge，按本段归属）：\n" + "\n".join(
        f"- 【{r['id']}】{r['writer_text']}" for r in rs)


def example_for(link: str) -> str:
    node = chain()["links"][link]["to"]
    ex = chain()["nodes"][node]["output"].get("example")
    return (ROOT / ex).read_text(encoding="utf-8").strip() if ex else ""


def system_for(link: str) -> str:
    t = _strip_comment(TEMPLATES[link].read_text(encoding="utf-8"))
    return (t.replace("{{RULES}}", rules_block(link)).replace("{{KNOWLEDGE}}", knowledge_block(link))
            .replace("{{EXAMPLE}}", example_for(link) if link != "P3-P4" else "")).strip()


def _j(obj) -> str:
    if hasattr(obj, "model_dump"):
        obj = obj.model_dump(mode="json", by_alias=True)
    return json.dumps(obj, ensure_ascii=False, indent=1)


def _registry_text(chars: list[dict], scenes: list[dict]) -> str:
    if not chars and not scenes:
        return "（无已登记人物 / 场景）"
    lines = ["已登记人物（各格逐字照抄，SL-10）："]
    lines += [f"- {c.get('name')}｜{c.get('char_id')}｜{c.get('zh')}｜{c.get('en')}｜{c.get('voice')}" for c in chars]
    lines.append("已登记场景（六格逐字照抄）：")
    lines += [f"- {s.get('scene_id')}｜{s.get('name')}｜{s.get('space')}｜{s.get('time_of_day')}｜{s.get('light')}｜{s.get('fixtures')}"
              for s in scenes]
    return "\n".join(lines)


def shot_cap(sp) -> int:
    """镜数上限（script_chat_rules.md §2 / QW-E2 + G29：max(8, 说话轮次 + 独白段数, ⌈目标秒数 ÷ 6⌉)），由系统从 P3 算好给写作模型。
    RSI 11-01 经总调度授权改（CONSENT 见 docs/uimaster/LOCKS.md）：单镜 ≤6 秒（K-WRT-Q07），目标 60 秒 → 至少能写 10 镜"""
    return max(8, len(sp.speech("dialogue")) + len(sp.speech("voiceover")), -(-int(sp.target_duration_s or 0) // 6))


def user_for(link: str, inp: dict) -> str:
    if link == "P0-P1":
        return ("【P0 提纲】\n" + _j(inp["brief"]) + "\n\n【已登记】\n"
                + _registry_text(inp.get("registry_chars") or [], inp.get("registry_scenes") or [])
                + "\n\n已登记的是本剧现有的角色和场景：storyline 用到它们时各格逐字照抄（SL-10）；提纲里的人物（含用代称指的人）"
                  "若是已登记角色，就用登记的名字，不另起新名字。现在输出 storyline JSON。")
    if link == "P1-P2":
        prev = inp.get("prev_outline")
        tail = f"\n\n【上一集 carry_out】{prev.carry_out}" if prev is not None else ""
        return f"【P1 storyline】\n{_j(inp['storyline'])}\n\n【本集号】{inp['episode']}{tail}\n\n现在输出第 {inp['episode']} 集的单集大纲 JSON。"
    if link == "P2-P3":
        s = inp["storyline"]
        roster = [c for c in s.characters if c.name in inp["outline"].characters]
        return ("【P2 单集大纲】\n" + _j(inp["outline"]) + "\n\n【P1 人物表（本集）】\n"
                + "\n".join(f"- {c.name}（{c.role}，{c.age}岁，{c.gender}）" for c in roster)
                + "\n\n现在输出本集剧本 JSON。")
    if link == "P3-P4":
        s, o, sp = inp["storyline"], inp["outline"], inp["screenplay"]
        chars = [c for c in s.characters if c.name in o.characters]
        scenes = [x for x in s.scenes if x.scene_id in o.scenes]
        table_c = "\n".join(f"| {c.name} | {c.char_id} | {c.zh_look} | {c.en_phrase} | {c.voice_phrase} |" for c in chars)
        table_s = "\n".join(f"| {x.scene_id} | {x.name} | {x.space} | {x.time_of_day} | {x.light} | {x.fixtures} |" for x in scenes)
        return (f"写第 {sp.episode} 集。\n\n【P3 单集剧本（台词 / 独白逐字照抄）】\n{_j(sp)}\n\n"
                f"【本集人物（来自 storyline；全局头全剧人物表里没有的，按 §2P 写进本集人物表，各格逐字照抄）】\n"
                f"| 角色 | 角色id | 中文外貌句 | EN外貌短语 | VOICE声线短语 |\n{table_c}\n\n"
                f"【本集场景（来自 storyline；全剧场景表里没有的，按 §2S 写进本集场景表，各格逐字照抄）】\n"
                f"| 场景id | 名称 | 空间描述 | 时段 | 光线 | 固定陈设 |\n{table_s}\n\n"
                f"【本集】intimate={o.intimate}；各镜时长之和目标 {sp.target_duration_s} 秒（±5，且 60–120，LK34-11；D-SCR-08）；镜数 6–{shot_cap(sp)}"
                f"（上限 = max(8, 说话轮次 {len(sp.speech('dialogue'))} + 独白段数 {len(sp.speech('voiceover'))})，LK34-09）。"
                f"从 `## ep{sp.episode:02d}《{sp.title}》` 开始输出。"
                + ("\n\n" + PF.block_for(chars, inp.get("looks")) if chars else ""))   # K-WRT-206 系统预拼片段
    raise KeyError(link)


def build(link: str, inp: dict) -> dict:
    user = user_for(link, inp)
    parts = [{"name": f"config/pipeline/prompts/{link}.md"}]
    if link == "P3-P4":
        from ns_api import script_chat as SC
        cfg = SC.load_config()
        cfg["registry"] = {}
        base, bparts = SC.prompt_for(user, context=user, cfg=cfg)
        parts = [{"name": p.get("name"), "path": p.get("path")} for p in bparts] + parts
        system = base + "\n\n========\n\n" + system_for(link)
    else:
        system = system_for(link)
    return {"system": system, "user": user, "parts": parts}


def repair_message(issues: list[dict], output_kind: str, extra: str = "") -> str:
    # 带上位置（field，如 ep02-S4.motion.beats）：SERIES 2026-10-31，series10_v1 里 SS-M2 / LK34 只给“分拍只写到 6.0s”
    # 不说哪一镜，写作模型两轮都改不到点上（knowledge K-WRT-206 证据）
    lines = [f"- 【{i['rule']}】" + (f"{i['field']}：" if i.get("field") else "") + i["message"]
             for i in issues if i.get("level") == "block"]
    what = "完整 JSON 对象" if output_kind == "json" else "完整的这一集（从 `## ep` 到 `---`）"
    return ("【格式返修】系统机检没通过，下面是不通过的规则（规则号对应系统提示词里的规则）：\n" + "\n".join(lines)
            + (("\n\n逐镜返修要求：\n" + extra) if extra else "")
            + f"\n\n重新输出{what}，只改被点名的地方，其余逐字保持不变；不写解释。")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("link", choices=sorted(TEMPLATES))
    ap.add_argument("--show", action="store_true")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    print(system_for(a.link))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
