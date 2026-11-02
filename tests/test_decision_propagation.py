"""K-OPS-D02 决策全量同步检查（tools/qa/decision_propagation.py）：过期口径、⤴ 标记、历史排除、propagate 新口径。只写 tmp_path。"""
import importlib.util as ilu
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
_spec = ilu.spec_from_file_location("ns_decision_propagation_t", ROOT / "tools" / "qa" / "decision_propagation.py")
DP = ilu.module_from_spec(_spec)
_spec.loader.exec_module(DP)


def _mk(root: Path, files: dict, checks: list) -> Path:
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    d = root / "config" / "owner_decisions.yaml"
    d.parent.mkdir(parents=True, exist_ok=True)
    d.write_text(yaml.safe_dump({"checks": checks}, allow_unicode=True), encoding="utf-8")
    return d


CHECK = {"id": "D-T-01", "title": "t", "type": "exists", "paths": [],
         "stale_terms": ["(VQA|看图).{0,20}只记录"], "new_terms": ["转拦截"], "propagate": ["docs/vqa/STATE.md"]}


def test_stale_found_and_marked_or_history_skipped(tmp_path):
    d = _mk(tmp_path, {
        "docs/vqa/STATE.md": "# 状态\n- VQA 看图结果只记录\n- ⤴ VQA 只记录（已被 D-T-01 取代）\n",
        "docs/old.md": "## 旧做法 ⤴ 被 D-T-01 取代\n看图只记录\n## 新\n正常\n",
        "docs/research/x.md": "看图只记录\n",
        "docs/MORNING_REPORT_20261031.md": "看图只记录\n",
        "docs/CHANGELOG_AGENTS.md": "看图只记录\n",
        "config/vqa.json": '{"_enforce": "看图只记录，⤴ 已撤"}\n',
    }, [CHECK])
    res = DP.run(root=tmp_path, decisions=d)
    stale = [(s["file"], s["line"]) for s in res[0]["stale"]]
    assert stale == [("docs/vqa/STATE.md", 2)]
    assert res[0]["unsynced"] == [{"file": "docs/vqa/STATE.md", "why": res[0]["unsynced"][0]["why"]}]
    assert "没有新口径" in res[0]["unsynced"][0]["why"]


def test_fully_synced_passes_and_allow_glob(tmp_path):
    d = _mk(tmp_path, {"docs/vqa/STATE.md": "VQA 命中转拦截\n", "docs/rec.md": "VQA 只记录（决定本身的记录）\n"},
            [{**CHECK, "stale_allow": ["docs/rec.md"]}])
    res = DP.run(root=tmp_path, decisions=d)
    assert res[0]["stale"] == [] and res[0]["unsynced"] == []


def test_log_streams_skipped_for_stale_but_still_checked_in_propagate(tmp_path):
    """W11 / A-G1 第 22 轮：V2_LIVE.md 的卡点行由 report_issue 自动插入、原样引用报错（例“VQA 只记录”）——事件记录不是口径，不扫；
    同一句写在普通文档里照样判过期；某条决定若把日志文件列进 propagate，仍要求有新口径（排除只作用于 stale 扫描）"""
    live = "# V2 实况\n05:01 ⚠ 卡点（ASSET-WORKER）：看图只记录，q9=fail\n"
    d = _mk(tmp_path, {"docs/vqa/STATE.md": "VQA 命中转拦截\n", "docs/master/V2_LIVE.md": live,
                       "docs/master/CHANNEL.md": "05:02 | X | ASK | 看图只记录？\n", "docs/master/PLAN.md": "看图只记录\n"}, [CHECK])
    res = DP.run(root=tmp_path, decisions=d)
    assert [s["file"] for s in res[0]["stale"]] == ["docs/master/PLAN.md"]
    assert set(DP.LOG_STREAMS) == {"docs/master/V2_LIVE.md", "docs/master/CHANNEL.md"} and all(DP.LOG_STREAMS.values())
    d2 = _mk(tmp_path, {}, [{**CHECK, "propagate": ["docs/master/V2_LIVE.md"]}])
    res2 = DP.run(root=tmp_path, decisions=d2)
    assert res2[0]["unsynced"] and res2[0]["unsynced"][0]["file"] == "docs/master/V2_LIVE.md"


def test_section_marker_ends_at_same_level_heading():
    text = "## A ⤴\nx 只记录\n### sub\ny 只记录\n## B\nz 只记录\n"
    assert DP.marked_lines(text, ".md") == {1, 2, 3, 4}


def test_real_decisions_file_parses_and_has_d02_entries():
    cfg = yaml.safe_load((ROOT / "config" / "owner_decisions.yaml").read_text(encoding="utf-8"))
    ids = {c["id"] for c in cfg["checks"] if c.get("stale_terms")}
    assert {"D-VID-01", "D-VQA-01"} <= ids
    import re
    for c in cfg["checks"]:
        for t in c.get("stale_terms") or []:
            re.compile(t)
            assert "\n" not in t


def test_generated_file_in_propagate_is_config_error(tmp_path):          # K-OPS-D04
    d = _mk(tmp_path, {"docs/STATUS.md": "# 夜间进度（night.py 自动写；交总调度）\n转拦截\n"},
            [{**CHECK, "stale_terms": [], "propagate": ["docs/STATUS.md"]}])
    res = DP.run(root=tmp_path, decisions=d)
    assert res[0]["unsynced"] and "自动生成" in res[0]["unsynced"][0]["why"]


def test_real_propagate_files_all_have_owner():                           # K-OPS-D03
    cfg = yaml.safe_load((ROOT / "config" / "owner_decisions.yaml").read_text(encoding="utf-8"))
    bad = [(c["id"], f) for c in cfg["checks"] for f in c.get("propagate") or [] if DP._owner(f) in ("未指派", "未知")]
    assert not bad, f"同步清单里的文件没有 owner（tools/qa/ownership.yaml）：{bad}"
    gen = [(c["id"], f) for c in cfg["checks"] for f in c.get("propagate") or [] if (ROOT / f).exists() and DP.is_generated(ROOT / f)]
    assert not gen, f"同步清单里有程序生成的文件（改同步生成它的程序）：{gen}"
