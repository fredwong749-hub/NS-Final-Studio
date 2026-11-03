"""P4 剧本分镜 → 校验 + 下游可导入性（CHAINSPEC 2026-10-31）。

    check_p4(ep_md, episode) -> (Report, shots, specs)

1. 把这一集拼上现行全局头（ns_api.script_chat.script_header：角色锁 + 触发词表 + 已登记全剧人物表 / 场景表），写临时剧本；
2. 导入关口 tools/validate_qwen_script.validate（与 #/script-create 校验、script_inbox 同款）→ 规则 P4-GATE（原规则号保留在 message）；
3. 真实导入器 ns_agent.importer.script_md.import_script → shots（给 LK34 逐字一致校验）；
4. ns_recipes.spec_import.specs_from_markdown → Shot Spec v2；missing_fields / check_sequence 的 block → 规则 P4-SPEC。
能走完 3、4 = “能被下游导入”。只查格式，不改内容。
"""
from __future__ import annotations

import importlib.util
import uuid

from chainlib import ROOT
from ns_schema.upstream_common import Report

TMP = ROOT / "data" / "pipeline" / "_tmp"

# TIMELINE-O 11-03 / L-141：时间轴类缺项（分拍覆盖 / 拍内槽位 / 运镜按拍 / H3 镜内拍序 / 镜内 At 时间码）按镜合成一条 [TL-<镜号>]，
# 补丁环按镜出“只补时间轴”的目标（每镜一个 id，不会因为同一规则号跨镜共用尝试次数而卡死）
TIMELINE_SS = {"SS-M1", "SS-M2", "SS-M5", "SS-M6", "SS-M8"}
TIMELINE_PATCH_SCOPE = ("只补这一镜的时间轴：只许改这一镜的 **分拍** / **表演节拍** 行（每拍 1.5–2 秒、从 0 写到镜长，"
                        "每拍写 动作｜视线=｜表情=｜反应=｜运镜=｜声音=）和 H3 的 integrated_multimodal_description 行。H3 镜内按 L-141 写自然英文时间顺序："
                        "第一拍紧跟锚点句、以 `In the first <N> seconds,` 开头，并用 already / still / continues / mid- 写第 0 秒已在进行的动作；"
                        "之后每拍以 `Then, around the <序数> second,` 开头（序数 = 该拍起点所在的第几秒：2 秒 → third，4 秒 → fifth）；"
                        "每拍写视线落点和表情部位；最后一拍写到 `… as the shot ends` 的进行中动作。镜内原有的 `At 00:SS.mmm,` 一律改成上面的写法"
                        "（At 时间码只用于切镜；本条优先于“保留时间码”的通用说明）。剧情、台词原文、说话人、镜长、人物、造型、运镜种类都不变")


def timeline_message(sp, items: list[str]) -> str:
    import re as _re
    n = (_re.findall(r"S(\d+)", sp.id or "") or ["?"])[-1]
    # 补丁环的 why 只留前 300 字（hollywood.lint）：这里只放缺项，改写范围 TIMELINE_PATCH_SCOPE 由 autoflow.patch_user 按 TL- 目标附上
    items = sorted(items, key=lambda x: not x.startswith(("RL-T8", "RL-T9")))     # 拍序 / At 时间码放最前（why 只留 300 字）
    return f"[TL-{n}] 镜{n} 时间轴不全（{len(items)} 项）：" + "；".join(_re.sub(r"（[^（）]*）$", "", x)[:90] for x in items)


def _gate_module():
    spec = importlib.util.spec_from_file_location("validate_qwen_script", ROOT / "tools" / "validate_qwen_script.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    if hasattr(m, "WL"):
        m.WL.WRITER_LINT_LEVEL = "block"   # ITERAUDIT 11-01：写作链路里 QW-W1–W4 拦下 → 进写作模型返修环（导入关口仍是 warn）
    return m


def write_script(ep_md: str, tag: str = "p4") -> tuple:
    from ns_api import script_chat as SC
    header, _ = SC.script_header(registry={})
    TMP.mkdir(parents=True, exist_ok=True)
    p = TMP / f"{tag}-{uuid.uuid4().hex[:6]}.md"
    body = ep_md.strip()
    if not body.endswith("---"):
        body += "\n\n---"
    p.write_text(header + "\n---\n\n" + body + "\n", encoding="utf-8", newline="\n")
    return p


def shots_of(ep) -> list[dict]:
    out = []
    for s in ep.shots:
        out.append({"index": s.index, "scene_id": s.scene_id, "duration": s.duration,
                    "cast": [c.name for c in (s.cast or [])],
                    "dialogue": [(d.speaker or "", d.text) for d in s.dialogue],
                    "voiceover": (s.voiceover.speaker or "", s.voiceover.text) if s.voiceover else None})
    return out


def segment_issues(ep_md: str, episode: int, run_info: tuple) -> list[dict]:
    """K-WRT-213：非 legacy 剧（V2 及以后）每镜段落标记——漏标 [QW-S1] block、与 P2/P3 不一致 [QW-S2]（tools/script_rsi/segment_fix.check）。
    run_info = ns_api.script_chat.run_info(...) 的 (run, legacy, ...)；legacy / 认不出剧 / 本剧 P2 P3 不在 → 不判"""
    run, legacy = (run_info[0] if run_info else None), (run_info[1] if len(run_info) > 1 else True)
    if not run or legacy:
        return []
    try:
        import sys
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from tools.autopilot import runs as runs_mod
        rd = runs_mod.run_dir(run, ROOT)
        sp = importlib.util.spec_from_file_location("segment_fix_p4", ROOT / "tools" / "script_rsi" / "segment_fix.py")
        SF = importlib.util.module_from_spec(sp)
        sp.loader.exec_module(SF)
        return SF.check_text(ep_md, rd, episode)
    except Exception as e:  # noqa: BLE001  段落检查自己出错不挡导入关口，但要看得见
        return [{"shot": 0, "code": "QW-S0", "level": "warn", "detail": f"段落检查出错：{e!r}"[:200]}]


def check_p4(ep_md: str, episode: int, *, keep: bool = False) -> tuple[Report, list[dict], list, dict]:
    rep = Report("P4")
    p = write_script(ep_md)
    gate_raw: dict = {}
    shots: list[dict] = []
    specs: list = []
    try:
        gate = _gate_module()
        from ns_api import script_chat as _SC
        # MERGE-VID-O（L-137）：临时文件认不出剧 → 显式传当前剧（run_scope / NS_RUN / primary），QW-C1 按本剧运镜词表、V2 硬项判 block
        gate_raw = gate.validate(p, episode, run=_SC.run_info(None)[0])
        rep.hard_blocks = list(gate_raw.get("hard_blocks") or [])   # 不可交补丁环的阻断（run_chain：有就不收稿）
        eps = gate_raw.get("episodes") or []
        if not eps:
            rep.add("P4-GATE", "block", f"导入器解析不出第 {episode} 集（检查 `## ep{episode:02d}《…》` 集头和字段格式）")
        # 全局头（角色锁 / 触发词表）是系统拼的现行剧本头，不是写作模型这一集的产物：它的问题不算进本段，也不进返修
        rep.global_issues = gate_raw.get("global_issues") or []
        for e in eps:
            for i in e["issues"]:
                rep.add("P4-GATE", i["level"], f"[{i['rule_id']}] {i['detail']}", f"ep{e['number']}")
            for sh in e["shots"]:
                for i in sh["issues"]:
                    rep.add("P4-GATE", i["level"], f"[{i['rule_id']}] {i['detail']}", sh["id"])
        for i in segment_issues(ep_md, episode, _SC.run_info(None)):      # K-WRT-213（K211-F 11-03）：V2 每镜必标【幻想段】/【现实段】且与 P2/P3 一致
            rep.add("P4-GATE", i["level"], f"[{i['code']}] {i['detail']}", f"ep{episode:02d}-S{i['shot']}")
        from ns_agent.importer.script_md import import_script
        imp = import_script(p)
        ep = next((e for e in imp.episodes if e.number == episode), None)
        if ep is not None:
            shots = shots_of(ep)
            from ns_recipes.spec_import import specs_from_markdown
            from ns_recipes.lint import timeline_gate
            from ns_schema.shot_spec import check_sequence, missing_fields, timeline_run
            from ns_api import script_chat as SC
            with timeline_run(SC.run_info(None)[0]):     # 临时文件认不出剧：按当前 run_scope 的剧判 strict（TIMELINE-O）
                specs = specs_from_markdown(p, episode)
                for sp in specs:
                    tl = []
                    for m in missing_fields(sp):
                        if m.severity != "block":
                            continue
                        if m.rule in TIMELINE_SS:
                            tl.append(f"{m.rule} {m.message}")
                        else:
                            rep.add("P4-SPEC", "block", f"[{m.rule}] {m.message}", f"{m.shot}.{m.field}")
                    tl += [f"{i['code']} {i['message']}" for i in timeline_gate(sp)]
                    if tl:
                        rep.add("P4-SPEC", "block", timeline_message(sp, tl), f"{sp.id}.timeline")
            for m in check_sequence(specs):
                rep.add("P4-SPEC", "warn", f"[{m.rule}] {m.message}", f"{m.shot}.{m.field}")
    except Exception as e:  # noqa: BLE001  解析崩溃 = 不能被下游导入
        rep.add("P4-GATE", "block", f"导入 / 解析失败：{type(e).__name__}: {e}")
    finally:
        if not keep:
            p.unlink(missing_ok=True)
    return rep, shots, specs, gate_raw


def repair_text(gate_raw: dict) -> str:
    """导入关口自带的逐镜返修原文（只引用格式规则）"""
    out = []
    for e in gate_raw.get("episodes") or []:
        if e.get("repair"):
            out.append(e["repair"])
        out += [sh["repair"] for sh in e["shots"] if sh.get("repair")]
    return "\n\n".join(out)
