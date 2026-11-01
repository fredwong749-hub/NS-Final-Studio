"""UIRSI r41：旧剧本版本隔离（接口默认不返回、当前版本已隔离 = 没有当前）+ 界面减法（K-UI-046）。"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/api", "services/render_router", "services/agent"):
    sys.path.insert(0, str(ROOT / p))

from ns_api import takes_ui as T  # noqa: E402
from ns_render import pipeline as P  # noqa: E402


def test_candidates_hide_quarantined_and_history(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "DATA", tmp_path)
    monkeypatch.setattr(P, "RENDERS", tmp_path / "renders")
    monkeypatch.setattr(P, "bad_reason", lambda t: None)
    monkeypatch.setattr(T, "IMPORT_LOG", tmp_path / "none.jsonl")
    T._imp_cache.update(mt=None)
    d = tmp_path / "renders" / "ep02" / "S1"
    (d / "takes").mkdir(parents=True)
    q = tmp_path / "_quarantine_20261102_oldscript" / "data" / "renders" / "ep02" / "S1" / "takes"
    q.mkdir(parents=True)
    (q / "last_001.png").write_bytes(b"x")
    (d / "takes" / "last_002.png").write_bytes(b"x")
    takes = [{"n": 1, "stage": "last", "file": "renders/ep02/S1/takes/last_001.png",
              "quarantined": {"by": "UIRSI r41（旧剧本版本隔离）", "moved_to": {"file": "data/_quarantine_20261102_oldscript/data/renders/ep02/S1/takes/last_001.png"}}},
             {"n": 2, "stage": "last", "file": "renders/ep02/S1/takes/last_002.png"}]
    (d / "takes.json").write_text(json.dumps({"takes": takes, "active": {"last": 1}}), encoding="utf-8")
    r = T.candidates(2)["shots"]["ep02-S1"]["last"]
    assert [x["n"] for x in r["takes"]] == [2] and r["active"] is None and r["active_quarantined"] == 1
    h = T.candidates(2, history=True)["shots"]["ep02-S1"]["last"]
    qt = next(x for x in h["takes"] if x["n"] == 1)
    assert qt["quarantined"] and qt["ok"] is False and "_quarantine_20261102_oldscript" in qt["url"]


def test_active_quarantined_counts_as_none():
    src = (ROOT / "services/api/ns_api/app.py").read_text(encoding="utf-8")
    i = src.index("def _active(shot_id: str")
    body = src[i: src.index("return out", i)]
    assert "out[stage] = None if (t and is_quarantined(t)) else t" in body   # r42：标记被并回冲掉、文件在隔离区的也算


def test_quarantine_tool_marks_only_and_restorable():
    tool = (ROOT / "tools/uirsi/quarantine_oldscript.py").read_text(encoding="utf-8")
    assert "quarantine_safe_move.py" in tool and "restore-all" in tool and "_takes_backup" in tool
    assert 'del ' not in tool.split("def mark")[1].split("def restore_mark")[0]     # 只追加字段，不删版本


def test_simplified_ui_keeps_features():
    sp = (ROOT / "apps/web/src/v3/pages/SeasonPage.tsx").read_text(encoding="utf-8")
    assert 'sea-page${detail ? "" : " simple"}' in sp and "显示细节" in sp and "细节 {openEp.has(e.number)" in sp
    css = (ROOT / "apps/web/src/v3/shotstatus.css").read_text(encoding="utf-8")
    assert ".sea-page.simple .sea-segs" in css and "display: none" in css
    rr = (ROOT / "apps/web/src/v3/ReviewRow.tsx").read_text(encoding="utf-8")
    # 收起的内容只是折叠：详情按钮的悬停提示列出了收起的东西（G10 按文字 / 属性查功能）
    assert "详情：本镜配乐 / 环境声 · 人物造型（本镜造型角标）与场景参考 · 分镜详情 · 首帧提示词 · 视频提示词" in rr
    assert "分镜详情 {sbOpen" in rr and "首帧提示词 {open" in rr and "视频提示词 {open" in rr and "收起 ▴" in rr
    assert "<HistoryBox shot={s.id}" in rr and ">历史版本</button>" in rr



def test_quarantined_detected_even_if_mark_lost(tmp_path, monkeypatch):
    """r42：服务器并回 takes.json“新者为准”会冲掉 quarantined 标记——文件在隔离区、不在 data/ 的照样算已隔离"""
    monkeypatch.setattr(P, "DATA", tmp_path)
    (tmp_path / "_quarantine_20261102_oldscript" / "data" / "renders" / "ep01" / "S1" / "takes").mkdir(parents=True)
    (tmp_path / "_quarantine_20261102_oldscript" / "data" / "renders" / "ep01" / "S1" / "takes" / "last_001.png").write_bytes(b"x")
    assert T.is_quarantined({"file": "renders/ep01/S1/takes/last_001.png"})
    assert not T.is_quarantined({"file": "renders/ep01/S1/takes/last_002.png"})
