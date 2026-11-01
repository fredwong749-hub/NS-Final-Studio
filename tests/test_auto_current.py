"""G3（MASTER_PICTURE，项目方 11-01 授权）：过契约即设为当前——所有路径同一个函数 ns_render.auto_current.on_contract。

  过契约且非坏图 → 自动设为当前；没过 / 还没算完 / 坏图 → 绝不设为当前（已是当前就退回到上一个过契约的版本，没有就清空）；
  项目方本人定稿的版本永远不被自动挤掉（自动定稿 locked_by.by == "auto" 不算项目方定稿）。
覆盖路径：PRODUCER（dryrun，见 test_producer）、ASSETMASTER register_takes、画布重出 unified_frame.run_postflight /
record_params、编辑链 frame_edit.edit_frame（源码断言：入库不设当前 + 起契约）。纯 CPU，临时 renders 目录。
"""
import inspect
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/render_router", "services/agent", "packages/schema", "tools/pipeline", "tools/gen_contract"):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))

from ns_render import auto_current as AC  # noqa: E402
from ns_render import frame_edit as FE  # noqa: E402
from ns_render import pipeline as P  # noqa: E402
from ns_render import unified_frame as UF  # noqa: E402

SID = "ep01-S1"


@pytest.fixture()
def sandbox(tmp_path, monkeypatch):
    from ns_render import image_check as IC
    monkeypatch.setattr(IC, "ENABLED", True)                   # conftest 默认关坏图检查；这里要测“坏图不设当前”
    monkeypatch.setattr(P, "DATA", tmp_path / "data")
    monkeypatch.setattr(P, "RENDERS", tmp_path / "data" / "renders")
    (tmp_path / "data" / "renders").mkdir(parents=True)
    return tmp_path


def _img(path: Path, seed=1):
    from PIL import Image
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.effect_noise((768, 1344), 40 + seed).convert("RGB").save(path)
    return path


def _add(stage="image", ok=None, bad_file=False, where="postflight"):
    from ns_schema.edits import Take
    n = P._next_n(SID, stage)
    rel = f"renders/ep01/S1/takes/{stage}_{n:03d}.png"
    if bad_file:
        (P.DATA / rel).parent.mkdir(parents=True, exist_ok=True)
        (P.DATA / rel).write_bytes(b"x")          # 坏图（< 10 KB）
    else:
        _img(P.DATA / rel, n)
    P._add_take(SID, Take(n=n, stage=stage, file=rel, seed=n, prompt="t", created_at=P.now()), activate=False)
    if ok is not None:
        pf = {"ok": ok, "items": [], "status": "done"}
        if where == "postflight":
            FE.annotate(SID, stage, n, postflight=pf)
        else:
            FE.annotate(SID, stage, n, contract={"postflight": pf})
    return n


def _active(stage="image"):
    return (P.load_takes(SID).get("active") or {}).get(stage)


def test_rules(sandbox):
    a = _add(ok=True)
    assert AC.on_contract(SID, "image", a)["action"] == "activate" and _active() == a
    b = _add(ok=False)
    assert AC.on_contract(SID, "image", b)["action"] == "keep" and _active() == a          # 没过不设
    c = _add(ok=None)
    assert AC.on_contract(SID, "image", c)["action"] == "keep" and _active() == a          # 还没算完不设
    d = _add(ok=True, bad_file=True)
    assert AC.on_contract(SID, "image", d)["action"] == "keep" and _active() == a          # 坏图不设
    e = _add(ok=True, where="contract")                                                    # unified 路径的 contract.postflight
    assert AC.on_contract(SID, "image", e)["action"] == "activate" and _active() == e


def test_owner_lock_never_displaced(sandbox):
    a = _add(ok=True)
    AC.on_contract(SID, "image", a)
    data = P.load_takes(SID)
    data["locked"] = {"image": a}
    P._save_takes(SID, data)
    b = _add(ok=True)
    r = AC.on_contract(SID, "image", b)
    assert r["action"] == "keep" and _active() == a and "项目方定稿" in r["why"]
    data = P.load_takes(SID)                                   # 自动定稿（episode_produce auto_lock）不算项目方定稿
    data["locked_by"] = {"image": {"by": "auto", "n": a}}
    P._save_takes(SID, data)
    assert AC.on_contract(SID, "image", b)["action"] == "activate" and _active() == b


def test_failing_current_reverts_or_clears(sandbox):
    a = _add(ok=True)
    AC.on_contract(SID, "image", a)
    b = _add(ok=None)
    P.set_active(SID, "image", b)                              # 旧路径曾在契约前就设了当前
    FE.annotate(SID, "image", b, postflight={"ok": False, "status": "done"})
    r = AC.on_contract(SID, "image", b)
    assert r["action"] == "revert" and _active() == a
    data = P.load_takes(SID)
    data["takes"] = [t for t in data["takes"] if t["n"] == b]
    data["active"] = {"image": b}
    P._save_takes(SID, data)
    assert AC.on_contract(SID, "image", b)["action"] == "clear" and _active() is None


def test_register_takes_path(sandbox, tmp_path):
    import register_takes as RT
    ok_f, bad_f = _img(tmp_path / "ok.png", 3), _img(tmp_path / "no.png", 4)
    r1 = RT.register({"shot": SID, "stage": "image", "file": str(ok_f), "postflight": {"ok": True}}, label="t")
    assert r1["active"] and _active() == r1["n"]
    r2 = RT.register({"shot": SID, "stage": "image", "file": str(bad_f), "postflight": {"ok": False}}, label="t")
    assert not r2["active"] and _active() == r1["n"]


def test_unified_postflight_path(sandbox, monkeypatch):
    calls = iter([{"ok": False, "items": []}, {"ok": True, "items": []}])
    monkeypatch.setattr(UF, "_postflight", lambda rel, job, host: next(calls))
    monkeypatch.setattr(UF, "_ctx_for", lambda sid, t: {"cast": [], "host": None})
    a = _add()
    UF.record_params(SID, "image", a)                          # 过坏图检查也不再直接设当前
    assert _active() is None
    UF.run_postflight(SID, "image", a)
    assert _active() is None                                   # 契约没过
    b = _add()
    UF.record_params(SID, "image", b)
    UF.run_postflight(SID, "image", b)
    assert _active() == b                                      # 契约过了 → 自动设为当前


def test_edit_chain_and_producer_use_shared_rule():
    src = inspect.getsource(FE.edit_frame)
    assert "activate=False" in src and "postflight_async" in src and "activate=True" not in src
    prod = (ROOT / "tools" / "autopilot" / "producer.py").read_text(encoding="utf-8")
    assert "activate=True" not in prod and "AC.on_contract" in prod
    assert "AC.on_contract" in inspect.getsource(UF.run_postflight)


def test_master_reject_keeps_current_until_review(sandbox):
    """总调度驳回当前版本（master_gate）：替换版过契约也不自动换上，等总调度复核；当前版本先留着"""
    a = _add(ok=True)
    AC.on_contract(SID, "image", a)
    data = P.load_takes(SID)
    data["master_gate"] = {"image": {"reject_n": a, "reason": "塑料感"}}
    P._save_takes(SID, data)
    b = _add(ok=True)
    r = AC.on_contract(SID, "image", b)
    assert r["action"] == "keep" and _active() == a and "等总调度复核" in r["why"]


def test_every_current_change_is_audited(sandbox):
    """DATAALIGN 11-01：当前版本每次变化都记 data/producer/current_changes.jsonl（镜、阶段、从、到、原因、谁、时间）"""
    import json
    a = _add(ok=True)
    AC.on_contract(SID, "image", a)
    b = _add(ok=None)
    P.set_active(SID, "image", b)
    FE.annotate(SID, "image", b, postflight={"ok": False, "status": "done"})
    AC.on_contract(SID, "image", b)                            # 退回 a
    c = _add(ok=False)
    AC.on_contract(SID, "image", c)                            # 不变 → 不记
    rows = [json.loads(x) for x in (P.DATA / "producer" / "current_changes.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [(r["from"], r["to"]) for r in rows] == [(None, a), (b, a)]
    assert all(r["shot"] == SID and r["stage"] == "image" and r["reason"] and r["actor"] and r["ts"] for r in rows)
