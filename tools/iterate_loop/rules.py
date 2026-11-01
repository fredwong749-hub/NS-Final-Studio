"""规则表求值：审片指标 + 当前计划 → 下一步动作（纯函数，便于测试）。"""
from __future__ import annotations

from pathlib import Path

import yaml

RULES_PATH = Path(__file__).resolve().parent / "rules.yaml"

OPS = {"gt": lambda v, t: v > t, "ge": lambda v, t: v >= t, "lt": lambda v, t: v < t, "le": lambda v, t: v <= t,
       "eq": lambda v, t: v == t}


def load(path: Path | None = None) -> dict:
    return yaml.safe_load((path or RULES_PATH).read_text(encoding="utf-8"))


def cond(expr: dict, m: dict) -> bool:
    if "any" in expr:
        return any(cond(e, m) for e in expr["any"])
    if "all" in expr:
        return all(cond(e, m) for e in expr["all"])
    for key, test in expr.items():
        if key == "acceptance_failed":
            if bool(m.get("_acceptance_failed")) != bool(test):
                return False
            continue
        v = m.get(key)
        if v is None:
            return False
        for op, thr in test.items():
            if not OPS[op](v, thr):
                return False
    return True


def matching(rules: dict, metrics: dict) -> list[dict]:
    return [r for r in rules["rules"] if r.get("stage") != "pre" and r.get("when") and cond(r["when"], metrics)]


def pre_render(rules: dict, spec_issues: list) -> dict | None:
    """渲染前：Shot Spec 缺字段 / 溢出（block 级）命中 pre 规则 → 返回第一步动作"""
    codes = {(i.rule if hasattr(i, "rule") else i["rule"]) for i in spec_issues
             if (i.severity if hasattr(i, "severity") else i["severity"]) == "block"}
    for r in rules["rules"]:
        if r.get("stage") == "pre" and codes & set(r.get("spec_rules") or []):
            step = dict(r["ladder"][0])
            return {"rule": r["id"], "step": 0, **step, "note": r.get("note"),
                    "codes": sorted(codes & set(r["spec_rules"]))}
    return None


def ladder_step(rule: dict, fired: int) -> list[tuple[int, dict]]:
    """这条规则第 fired 次触发（0 起）时可试的阶梯步（从第 fired 步往后，供调用方跳过不适用的）"""
    lad = rule["ladder"]
    return [(i, dict(lad[i])) for i in range(min(fired, len(lad) - 1), len(lad))]
