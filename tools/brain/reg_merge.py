"""两台 producer 登记表按对象合并 —— 读侧退路（W-FIX-PIPE #8 → L-209 S2.5 收口）。

S2.5 起：唯一合并函数是 tools/autopilot/registry_merged.merge（归属台为底、别台只补已定下、项目方驳回哪台都赢、孤儿镜丢掉）；
笔记本每拍写 data/producer/runs/<run>/registry_merged.json，读者优先读它。本模块只在合并表缺 / 过期时给读者（ns_api.shot_status）
一个同口径的退路：本机登记表当底（"_local"），拉回的两台只补已定下的对象。旧“走得最远的赢”已撤（会拿别台的 ready 残影盖本机）。
纯函数，不读写文件。
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_RM = None


def _rm():
    global _RM
    if _RM is None:
        sp = importlib.util.spec_from_file_location("ns_registry_merged_for_reg_merge",
                                                    Path(__file__).resolve().parents[1] / "autopilot" / "registry_merged.py")
        m = importlib.util.module_from_spec(sp)
        sp.loader.exec_module(m)
        _RM = m
    return _RM


def merge_registries(base: dict | None, others: dict[str, dict], owner: dict | None = None) -> dict:
    """base = 本机登记表；others = {host: 那台登记表}。转调 registry_merged.merge（本机为底；给了 owner = 按归属台）。
    返回新 dict；merged_hosts = 参与合并且有内容的别台；底不是本机的集带 merged_from=<host>"""
    used = [h for h, r in (others or {}).items() if isinstance(r, dict) and r.get("episodes")]
    regs = {"_local": base or {"episodes": []}, **{h: others[h] for h in used}}
    out = _rm().merge(regs, owner)
    for E in out.get("episodes") or []:
        if E.get("base_host") and E["base_host"] != "_local":
            E["merged_from"] = E["base_host"]
    out["merged_hosts"] = used
    return out
