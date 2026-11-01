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


def check_p4(ep_md: str, episode: int, *, keep: bool = False) -> tuple[Report, list[dict], list, dict]:
    rep = Report("P4")
    p = write_script(ep_md)
    gate_raw: dict = {}
    shots: list[dict] = []
    specs: list = []
    try:
        gate = _gate_module()
        gate_raw = gate.validate(p, episode)
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
        from ns_agent.importer.script_md import import_script
        imp = import_script(p)
        ep = next((e for e in imp.episodes if e.number == episode), None)
        if ep is not None:
            shots = shots_of(ep)
            from ns_recipes.spec_import import specs_from_markdown
            from ns_schema.shot_spec import check_sequence, missing_fields
            specs = specs_from_markdown(p, episode)
            for sp in specs:
                for m in missing_fields(sp):
                    if m.severity == "block":
                        rep.add("P4-SPEC", "block", f"[{m.rule}] {m.message}", f"{m.shot}.{m.field}")
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
