"""写作模型自检回路（Autopilot P3→P4）：写作模型输出一集 → 确定性校验 → 不过就把错误原样带回去让它重写（最多 N 轮）。

校验三层（全部只看格式 / 可实现性，不评内容）：
1. 严格格式校验 tools/validate_script_strict.py（经 ns_api.script_chat.validate_episode_text），取 block 级；
2. ns_schema.llm_output_check：<d> 逐字、<d> 外无人名、在画角色锚点短语、画外角色外貌不出现；
3. Shot Spec 缺字段（ns_schema.shot_spec.missing_fields，只取 owner=writer 的 block）。
LLM 调用可注入（默认 ns_api.script_chat.complete，走 config/llm_providers.json 的写作网关）；dry-run / 测试用 MockWriter。
"""
from __future__ import annotations

import re
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _spec_issues(ep_text: str, episode: int, header: str = "") -> list[dict]:
    from ns_recipes import spec_import as SI
    from ns_schema.llm_output_check import check_writer_output
    from ns_schema.shot_spec import missing_fields
    out = []
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / f"ep{episode:02d}.md"
        p.write_text(header + "\n\n" + ep_text, encoding="utf-8")
        try:
            specs = SI.specs_from_markdown(p, episode, with_assets=False)
        except (StopIteration, ValueError) as e:
            return [{"rule": "IMPORT", "shot": f"ep{episode:02d}", "message": f"导入失败：{e}"}]
    names = {c.name: [c.name] for s in specs for c in s.characters_on_screen}
    for s in specs:
        for m in missing_fields(s):
            if m.owner == "writer" and m.severity == "block":
                out.append({"rule": m.rule, "shot": s.id, "message": m.message, "addendum": m.addendum})
        if s.h3.text:
            r = check_writer_output(s.h3.text, dialogue=[d.text for d in s.audio.dialogue], names=names,
                                    on_screen_anchors={c.name: [c.en_phrase] for c in s.visible if c.en_phrase})
            out += [{"rule": f"LLM-{e['rule']}", "shot": s.id, "message": e["detail"]} for e in r.errors]
    return out


def strict_issues(ep_text: str) -> list[dict]:
    from ns_api import script_chat as SC
    rep = SC.validate_episode_text(ep_text, tag="autopilot")
    if rep is None:
        return []
    out = [{"rule": i.get("rule_id"), "shot": f"ep{rep.get('number', 0):02d}", "message": i.get("message")}
           for i in rep.get("issues", []) if i.get("level") == "block"]
    for sh in rep.get("shots", []):
        out += [{"rule": i.get("rule_id"), "shot": sh.get("id") or sh.get("index"), "message": i.get("message")}
                for i in sh.get("issues", []) if i.get("level") == "block"]
    return out


def selfcheck(ep_text: str, episode: int, *, strict=True, header: str = "") -> list[dict]:
    issues = strict_issues(ep_text) if strict else []
    return issues + _spec_issues(ep_text, episode, header)


def repair_message(issues: list[dict], episode: int) -> str:
    lines = ["【格式返修】系统校验没通过。只改下面点名的格式问题，剧情、画面内容和台词原文保持不变："]
    for i in issues[:40]:
        lines.append(f"- {i.get('shot')} [{i.get('rule')}] {i.get('message')}"
                     + (f"（写法见系统可实现性规则 {i['addendum']}）" if i.get("addendum") else ""))
    lines.append(f"→ 请重新输出完整的 ep{episode:02d}（整集，从 `## ep` 到 `---`）。")
    return "\n".join(lines)


EP_BLOCK_RE = re.compile(r"(## ep\s*0*(\d+)《.*?(?:\n---\s*$|\Z))", re.S | re.M)


def extract_episode(text: str, episode: int) -> str:
    for m in EP_BLOCK_RE.finditer(text or ""):
        if int(m.group(2)) == episode:
            return m.group(1).strip()
    return (text or "").strip()


def default_llm(messages: list[dict]) -> str:
    from ns_api import script_chat as SC
    return SC.complete(messages)["content"]


SHOT_ID_RE = re.compile(r"ep\d+-S(\d+)")


def _shot_index(shot) -> int | None:
    if isinstance(shot, int):
        return shot
    m = SHOT_ID_RE.search(str(shot or ""))
    return int(m.group(1)) if m else None


def shot_repair_message(issues: list[dict], episode: int, index: int, shot_text: str) -> str:
    lines = [f"【格式返修】ep{episode:02d} 镜{index} 没过系统校验。只改下面点名的格式问题，剧情、画面内容和台词原文保持不变："]
    for i in issues[:20]:
        lines.append(f"- [{i.get('rule')}] {i.get('message')}"
                     + (f"（写法见系统可实现性规则 {i['addendum']}）" if i.get("addendum") else ""))
    lines += ["", "这一镜当前全文：", shot_text.strip(), "",
              f"→ 只输出这一镜（从 **镜{index}｜img** 开始，到它的 H3提示词代码块结束），其它镜头不要输出。"]
    return "\n".join(lines)


def repair_round(text: str, issues: list[dict], episode: int, msgs: list[dict], llm) -> tuple[str, list[str]]:
    """逐镜返修（CHAINSPEC 系统问题 ②）：有镜号的问题按镜分组，一镜一次请求、只换这一镜；
    没有镜号的（集头 / 整集级）问题最后再整集返修一次。→ (新全文, 日志)"""
    from ns_api import script_chat as SC
    by: dict[int, list[dict]] = {}
    whole = []
    for i in issues:
        k = _shot_index(i.get("shot"))
        (by.setdefault(k, []) if k is not None else whole).append(i)
    notes = []
    _, shots, _ = SC.split_shots(text)
    for k in sorted(by):
        if k not in shots:
            whole += by[k]
            continue
        reply = llm(msgs + [{"role": "user", "content": shot_repair_message(by[k], episode, k, shots[k])}])
        try:
            text = SC.merge_shot(text, k, reply)
            notes.append(f"镜{k}：已替换（{len(by[k])} 个问题）")
        except ValueError as e:
            notes.append(f"镜{k}：回复里没有这一镜，保留原文（{e}）")
    if whole:
        reply = extract_episode(llm(msgs + [{"role": "assistant", "content": text},
                                            {"role": "user", "content": repair_message(whole, episode)}]), episode)
        if reply:
            text = reply
            notes.append(f"整集返修（{len(whole)} 个集级问题）")
    return text, notes


def write_with_selfcheck(messages: list[dict], episode: int, *, llm=None, max_rounds: int = 2, check=None,
                         log=print, initial: str | None = None, per_shot: bool = True) -> dict:
    """messages = [system, user…]（system 由 ns_api.script_chat.prompt_for 组装，已含知识包）。
    initial = 已有稿（不再先写一遍，直接校验 + 返修）。per_shot = 逐镜返修（默认）；False = 整集返修。
    → {text, rounds, issues, ok, transcript}"""
    llm = llm or default_llm
    check = check or (lambda t: selfcheck(t, episode))
    msgs = list(messages)
    transcript = []
    text = initial if initial is not None else extract_episode(llm(msgs), episode)
    issues = check(text)
    transcript.append({"round": 0, "issues": issues})
    r = 0
    while issues and r < max_rounds:
        r += 1
        log(f"[writer] 第 {r} 轮返修：{len(issues)} 个问题")
        if per_shot:
            text, notes = repair_round(text, issues, episode, msgs, llm)
        else:
            msgs += [{"role": "assistant", "content": text}, {"role": "user", "content": repair_message(issues, episode)}]
            text, notes = extract_episode(llm(msgs), episode), ["整集返修"]
        issues = check(text)
        transcript.append({"round": r, "issues": issues, "notes": notes})
    return {"text": text, "rounds": r, "issues": issues, "ok": not issues, "transcript": transcript}


class MockWriter:
    """dry-run：不调用付费 / 外部 API。按脚本依次返回文本（最后一个重复）；记录收到的消息，便于证明回路走通。"""

    def __init__(self, replies: list[str]):
        self.replies, self.calls = list(replies), []

    def __call__(self, messages: list[dict]) -> str:
        self.calls.append(messages)
        return self.replies[min(len(self.calls) - 1, len(self.replies) - 1)]
