"""SCRIPT-RSI 11-01（D-SCR-07，K-WRT-T03）：全量返修的系统部分——重切算术、改号、多块解析。不调写作方。"""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("script_rsi_full_repair_t", ROOT / "tools" / "script_rsi" / "full_repair.py")
FR = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(FR)


def _check(durs, lims, cap):
    groups, left = FR.plan_groups(durs, lims, len(durs), cap)
    # 总时长不变：让出秒数 = 新镜秒数
    for g in groups:
        assert sum(durs[k - 1] - v for k, v in g["donors"].items()) == g["dur"]
        assert FR.INSERT_MIN_S <= g["dur"] <= FR.INSERT_MAX_S
        assert g["insert_after"] in g["donors"]
    assert len(durs) + len(groups) <= cap
    return groups, left


def test_plan_all_fit():
    groups, left = _check([5, 8, 8, 7, 8, 7, 7, 7], [6] * 8, 10)
    assert len(groups) == 2 and left == []
    new = {k: v for g in groups for k, v in g["donors"].items()}
    assert all(v <= 6 for v in new.values())


def test_plan_cap_limits_groups_and_reports_left():
    groups, left = _check([4, 8, 8, 10, 8, 8, 8], [6] * 7, 9)
    assert len(groups) == 2 and left            # 上限只多 2 镜，装不下的列出来


def test_plan_no_room_no_change():
    groups, left = _check([8, 8, 8, 8, 8, 8, 8, 8], [6] * 8, 8)
    assert groups == [] and len(left) == 8


def test_renumber_only_after_insert_point():
    chunk = "**造型｜林晚｜镜3起**：…\n**镜2｜img**：a\n**镜3｜img**：b\n**镜4｜img**：c\n"
    out = FR.renumber(chunk, 2)
    assert "**镜2｜img**" in out and "**镜4｜img**：b" in out and "**镜5｜img**：c" in out and "镜4起" in out


def test_parse_blocks_requires_exact_numbers():
    RC = FR._load("repair_chain_t", "tools/pipeline/repair_chain.py")
    RL = RC._load_rl()
    raw = "**镜3｜img**：a\n**时长**：5秒\n**镜4｜img**：b\n**时长**：4秒\n"
    blocks, err = FR.parse_blocks(RL, raw, [3, 4])
    assert not err and len(blocks) == 2 and blocks[1].startswith("**镜4｜img**")
    _, err = FR.parse_blocks(RL, raw, [3])
    assert err


def test_codes_cover_new_acting_lints():
    AL = FR._load("acting_lints_t2", "tools/qa/acting_lints.py")
    assert set(FR.CODES) <= set(AL.RULES)
