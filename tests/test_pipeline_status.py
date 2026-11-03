"""NAVFLOW-F：/api/pipeline/status 的纯函数（fold / plain / plain_episode）——六步折叠正确，且给项目方看的文案里没有技术词。"""
from __future__ import annotations

import re

import pytest

from ns_api import pipeline_status as PS

# 页面上不许出现的东西：英文状态词 / 代码编号 / 文件名 / 命令 / 规则编号
TECH = re.compile(r"gate=|import=|reopened|autoflow|probe-prompts|sop_gate|preflight|episode_ready|P4|QW-T\d|K-[A-Z]+-|L-\d{3}|\.json|\.md|\.py|#|\bep\d{2}\b|run\b")

ROWS_EP1 = [
    {"stage": "剧本", "ok": True, "why": "P4 在"},
    {"stage": "导入闸门", "ok": False, "why": "gate=reopened import=reopened；代码判定 6 项未过（例：p4#QW-T1 ep01-S6：[QW-T1] 镜6 时长 7 秒，超过单镜上限 6 秒（V2 硬规则，L-137））；补丁已出 10 次仍有失败项，交总调度"},
    {"stage": "资产就绪", "ok": True, "why": "episode_ready 全部就绪 2026-11-03T03:10:44"},
    {"stage": "提示词", "ok": False, "why": "0/11 镜过；镜1：拒绝：镜 1 的人物是 ['卓琳']，只出祁念（lead_f）单人镜"},
    {"stage": "出图", "ok": False, "why": "0/11 镜有首帧；缺 镜1,2,3"},
    {"stage": "出图检测", "ok": False, "why": "0/11 镜首帧过契约 + Q9；缺 镜1"},
    {"stage": "尾帧", "ok": False, "why": "0/11 镜有过契约的尾帧；缺 镜1"},
    {"stage": "视频", "ok": False, "why": "0/11 镜有视频"},
    {"stage": "整集预览", "ok": False, "why": "没有 data/episodes/series10_v2/ep01*.mp4"},
]


def _all_plain(cells: dict) -> list[str]:
    return [c["plain"] for c in cells.values()]


def test_fold_states_and_gating():
    cells = PS.fold(ROWS_EP1, 1)
    # 有通过证据的阶段照实 ✓（资产就绪已过）；它后面的提示词没过且原因带“拒绝”= 卡住；再往后没到
    assert [cells[s]["state"] for s, _l, _st in PS.STEPS] == ["blocked", "done", "blocked", "todo", "todo", "todo"]
    # 卡住的那一步把 sop_gate 原文留在 why（给开发者），没到的步骤 why 清空
    assert "gate=reopened" in cells["script"]["why"]
    assert cells["frames"]["why"] == "" and cells["frames"]["plain"] == "还没到这一步"


def test_fold_all_done():
    rows = [dict(r, ok=True, why="ok") for r in ROWS_EP1]
    cells = PS.fold(rows, 3)
    assert all(c["state"] == "done" for c in cells.values())
    assert cells["cut"]["plain"] == "整集预览已拼好"


def test_fold_doing_vs_blocked():
    rows = [dict(r) for r in ROWS_EP1]
    rows[1] = {"stage": "导入闸门", "ok": True, "why": "gate=ok import=imported"}
    rows[3] = {"stage": "提示词", "ok": False, "why": "3/11 镜过；镜4：I3 造型没有设定图"}
    cells = PS.fold(rows, 1)
    assert cells["script"]["state"] == "done" and cells["assets"]["state"] == "done"
    assert cells["board"]["state"] == "doing"
    assert cells["board"]["plain"] == "11 镜里 3 镜的画面说明准备好了，其余还在补资料"
    assert cells["frames"]["state"] == "todo"


def test_plain_has_no_tech_words():
    cells = PS.fold(ROWS_EP1, 1)
    for t in _all_plain(cells):
        assert not TECH.search(t), t
    assert cells["script"]["plain"] == "第 1 集剧本还有 6 处要改，系统自动修了多次没修好，已交总调度处理"
    # 集级一句话
    s = PS.plain_episode(1, "导入闸门", "等第0集复盘 done；" + ROWS_EP1[1]["why"], {r["stage"]: r for r in ROWS_EP1})
    assert not TECH.search(s), s
    assert s.startswith("要等第 0 集复盘完成才能继续；停在“导入闸门”")


@pytest.mark.parametrize("stage,ok,why", [
    ("剧本", False, "没有 data/pipeline/runs/series10_v2/P4_ep02.md（P4 分镜还没交）"),
    ("导入闸门", False, "gate=无 import=无"),
    ("导入闸门", False, "gate=reopened import=reopened；代码判定 2 项未过；已重开补丁预算，跑 autoflow run 继续"),
    ("资产就绪", False, "episode_ready 缺口 3 个"),
    ("资产就绪", False, "没有 episode_ready 结果（_ready_epNN.json）"),
    ("提示词", False, "还没有逐镜编译 + preflight 证据（跑 sop_gate.py probe-prompts）"),
    ("提示词", False, "证据过期（2026-11-03 之后导入稿或资产清单变了，重跑 probe-prompts）"),
    ("提示词", False, "本集只有成人镜（等项目方在自有机器上触发）"),
    ("出图", False, "导入稿里没有本集镜头"),
    ("尾帧", False, "5/11 镜有过契约的尾帧；缺 镜6,7"),
    ("视频", False, "2/11 镜有视频"),
    ("整集预览", False, "没有 data/episodes/series10_v2/ep01*.mp4"),
    ("随便", False, "x"),
])
def test_plain_each_stage_no_tech(stage, ok, why):
    t = PS.plain(stage, ok, why, 2)
    assert t and not TECH.search(t), t


def test_gate_loads_without_sys_path(monkeypatch):
    import sys
    before = list(sys.path)
    PS._gate_mod = None
    mod = PS._gate()
    assert hasattr(mod, "status") and sys.path == before
