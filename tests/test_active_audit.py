"""K-OPS-Q23（RSI r5，ep01-S5 事故）：改“当前版本”只走 pipeline.set_active / clear_active / deactivate，
被驳回（总调度 master_reject / 标了不要）的版本不能再设为当前，每次变化都记 current_changes.jsonl。只写 tmp_path。"""
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/render_router", "services/agent", "packages/schema", "services/api"):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))
from ns_render import pipeline as P  # noqa: E402


def _shot(tmp_path, monkeypatch, takes, active):
    monkeypatch.setattr(P, "DATA", tmp_path)
    monkeypatch.setattr(P, "RENDERS", tmp_path / "renders")
    monkeypatch.setattr(P, "bad_reason", lambda t: None)
    d = tmp_path / "renders" / "ep99" / "S1"
    (d / "takes").mkdir(parents=True)
    for t in takes:
        (tmp_path / t["file"]).write_bytes(b"x" * 10)
    (d / "takes.json").write_text(json.dumps({"takes": takes, "active": active}), encoding="utf-8")
    return d


def _take(n, **kw):
    return {"n": n, "stage": "image", "file": f"renders/ep99/S1/takes/image_{n:03d}.png", **kw}


def _audit(tmp_path):
    f = tmp_path / "producer" / "current_changes.jsonl"
    return [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines()] if f.exists() else []


def test_master_rejected_or_owner_rejected_cannot_be_active(tmp_path, monkeypatch):
    _shot(tmp_path, monkeypatch, [_take(1), _take(2, master_reject={"by": "总调度"}), _take(3, params={"rejected": {"reason": "x"}})],
          {"image": 1})
    for n in (2, 3):
        with pytest.raises(P.BadImage):
            P.set_active("ep99-S1", "image", n)
    assert P.load_takes("ep99-S1")["active"]["image"] == 1


def test_deactivate_skips_rejected_and_every_change_is_audited(tmp_path, monkeypatch):
    _shot(tmp_path, monkeypatch, [_take(1), _take(2, master_reject={"by": "总调度"}), _take(3)], {"image": 3})
    assert P.deactivate("ep99-S1", "image") == 1                       # 跳过总调度驳回的 v2（ep01-S5 事故退到了 v3 驳回版）
    P.set_active("ep99-S1", "image", 3, reason="测试", actor="test")
    P.clear_active("ep99-S1", "image", "测试清空", actor="test")
    a = _audit(tmp_path)
    assert [(x["from"], x["to"]) for x in a] == [(3, 1), (1, 3), (3, None)] and all(x["actor"] for x in a)


def test_takes_ui_reject_falls_back_only_to_eligible(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from ns_api import takes_ui as T
    _shot(tmp_path, monkeypatch, [_take(1), _take(2, master_reject={"by": "总调度"}), _take(3)], {"image": 3})
    app = FastAPI()
    app.include_router(T.router)
    c = TestClient(app)
    r = c.post("/api/shots/ep99-S1/takes/image/3/reject", json={"reason": "不像"}).json()
    assert r == {"was_active": True, "active": 1}
    assert _audit(tmp_path)[-1]["actor"].startswith("takes_ui.reject")


# 静态检查：直接写 takes.json 的 active（不经 set_active / clear_active）的地方不能新增；现存的清空点由 owner 迁移
KNOWN_DIRECT = {
    "services/render_router/ns_render/pipeline.py",          # set_active / clear_active / deactivate 本身
    "services/render_router/ns_render/auto_current.py",      # on_contract 的 clear 分支（自己写审计，VQAGATE / PRODUCER）
    "services/api/ns_api/takes_ui.py",                       # unset：已补 audit_active
    "services/api/ns_api/trash.py",                          # _clear_active：已补 audit_active
    "tools/quarantine_bad_takes.py",                         # 一次性隔离脚本（自己记日志）
}
WRITE_RE = re.compile(r"""\[["']active["']\]\s*(?:\.pop\(|\[[^\]]+\]\s*=(?!=))|get\(["']active["']\)\s*or\s*\{\}\)\.pop\(""")


def test_no_new_direct_active_writers():
    hits = set()
    for base in ("tools", "services"):
        for f in (ROOT / base).rglob("*.py"):
            if "__pycache__" in f.parts or "tests" in f.parts:
                continue
            if WRITE_RE.search(f.read_text(encoding="utf-8", errors="replace")):
                hits.add(f.relative_to(ROOT).as_posix())
    assert hits <= KNOWN_DIRECT, f"新的直接改 active 的代码（改走 ns_render.pipeline.set_active / clear_active）：{sorted(hits - KNOWN_DIRECT)}"
