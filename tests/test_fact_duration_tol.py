"""L-164：factcheck“目标时长”±4 秒 / 5% 容差（时长归 QW-T 管），只去纯时长偏差"""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sp = importlib.util.spec_from_file_location("autoflow_agent_durtol_t", ROOT / "tools/script_rsi/autoflow_agent.py")
AG = importlib.util.module_from_spec(sp)
sp.loader.exec_module(AG)


def _cur(durs):
    return "\n\n".join(f"**镜{i}｜img**：近景\n**时长**：{d}秒" for i, d in enumerate(durs, 1))


EP02 = {"kind": "setting", "ref": "倒计时从十到一，零点放烟花；目标时长 66 秒",
        "found": "改写稿 11 镜的时长行依次为 5、6、5、6、6、6、6、6、6、6、5 秒，合计 63 秒，比目标 66 秒少 3 秒"}
SEG = {"kind": "setting", "ref": "天台为幻想段（紫红霓虹、烟花金光），楼下街口为现实段", "found": "镜1 场景行写【现实段】"}


def test_ep02_63_vs_66_within_tolerance_dropped():
    cur = _cur([5, 6, 5, 6, 6, 6, 6, 6, 6, 6, 5])           # 63 秒
    assert AG.duration_tolerated([EP02, SEG], cur) == [SEG]  # 时长那条去掉，段落那条保留


def test_outside_tolerance_kept():
    assert AG.duration_tolerated([EP02], _cur([5] * 11)) == [EP02]          # 55 秒，差 11 > 4
    big = dict(EP02, ref="目标时长 120 秒", found="合计 113 秒，时长少 7 秒")
    assert AG.duration_tolerated([big], _cur([113])) == [big]              # 容差 max(4, 5%×120=6)=6，差 7 → 保留
    assert AG.duration_tolerated([big], _cur([115])) == []                 # 差 5 ≤ 6 → 去掉


def test_no_duration_lines_keeps_everything():
    assert AG.duration_tolerated([EP02], "没有时长行") == [EP02]
