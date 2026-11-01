"""UIRSI r40：镜头状态标签 / 板块状态（K-UI-044）、已定决策锁 + 点图不直接换（K-UI-045）。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/api", "services/render_router", "services/agent"):
    sys.path.insert(0, str(ROOT / p))

from ns_api import decision_locks as D  # noqa: E402
from ns_api import shot_status as S  # noqa: E402


def test_tags_from_registry_and_script(monkeypatch):
    reg = {"ep06-S1": {"first": {"status": "ready", "redo": True, "master_reject": "总调度驳回 v3：脸不像"},
                       "last": {"status": "ready", "stale": True}, "video": {"status": "pending"}},
           "ep10-S2": {"first": {"status": "passed", "last_error": "契约没过：服装 / 单品对不上参考"},
                       "video": {"status": "best_effort"}, "last": {"status": "running"}}}
    monkeypatch.setattr(S, "_registry", lambda: reg)
    row = {"image": {"active": None, "takes": [{"n": 1, "script": "old"}]}, "last": {"active": 2, "takes": [{"n": 2, "script": "old"}]}}
    a = S.tags_for("ep06-S1", row)
    kinds = [t["kind"] for t in a["tags"]]
    assert a["main"] == "old" and "redo" in kinds and "stale" in kinds
    b = S.tags_for("ep10-S2", {"image": {"active": 1, "takes": [{"n": 1, "script": "current"}]}})
    kb = [t["kind"] for t in b["tags"]]
    assert "vqa_fail" not in kb          # 通过后的 last_error 是旧记录
    assert {"best", "busy", "ok"} <= set(kb)
    # 看图判定：现行版本最新一版 fail → 看图没过，原因写大白话（不出内部代号）
    takes = {"takes": [{"n": 1, "stage": "image", "params": {"vqa_rounds": [{"judge": {"verdict": "fail", "failed_checks": ["extra_limbs", "Q2", "zz_unknown"]}}]}}]}
    c = S.tags_for("ep10-S3", {"image": {"active": None, "takes": [{"n": 1, "script": "current"}]}}, takes)
    t = next(x for x in c["tags"] if x["kind"] == "vqa_fail")
    assert "多肢" in t["text"] and "缺外套" in t["text"] and "zz_unknown" not in t["text"] and "1 项其他问题" in t["text"]


def test_episode_blocks_states(monkeypatch):
    regs = {6: {"objects": {"script": {"status": "passed"}, "assembly": {"status": "passed"}},
                "shots": [{"shot": "ep06-S1", "objects": {"assets": {"status": "passed"}, "first": {"status": "ready", "redo": True, "master_reject": "总调度驳回 v3"},
                                                          "last": {"status": "pending"}, "video": {"status": "pending"}}}]}}
    monkeypatch.setattr(S, "_registry_eps", lambda: regs)
    shots = [{"id": "ep06-S1", "status": {"tags": [{"kind": "redo", "stage": "首帧"}]}}]
    b = S.episode_blocks(6, shots)
    st = {x["key"]: x["state"] for x in b["stages"]}
    assert st["script"] == "done" and st["first"] == "stale" and st["assembly"] == "stale"   # 上游过期 → 旧成片也算过期
    assert b["state"] == "stale" and "首帧" in b["text"]


def test_decision_locks_parse():
    checks = [{"id": "D-AST-93", "decision": "L-093（项目方 11-01 21:4x AskUserQuestion：…）", "type": "grep_present",
               "pattern": "lin_wan_lookA_v2_s202", "paths": ["data/pipeline/runs/series10_v1/assets/sheets_chosen.json"]},
              {"id": "D-AST-86a", "decision": "L-086（项目方 11-01 17:2x …）", "type": "json", "file": "data/looks/face_overrides.json",
               "path": ["series10_v1", "lin_wan"], "op": "eq", "value": "data/assets/identity_refs/lin_wan/x.png"},
              {"id": "D-OTHER", "type": "grep_absent", "pattern": "x", "paths": ["a"]}]
    ls = D._locks_from(checks)
    assert [(x["kind"], x["decision"], x["when"]) for x in ls] == [("sheet", "L-093", "11-01 21:4x"), ("face", "L-086", "11-01 17:2x")]
    assert ls[1]["cid"] == "lin_wan" and ls[0]["match"] == "lin_wan_lookA_v2_s202"


def test_people_hub_click_does_not_apply_and_lock_confirms():
    ph = (ROOT / "apps/web/src/v3/assets/PeopleHub.tsx").read_text(encoding="utf-8")
    # 点候选图本身只看大图（23:57 误点事故的根因：点图就直接换）
    assert "onClick={() => onBig({ src: c.url, alt: `造型 ${lk.look} 种子 ${c.seed}` })}" in ph
    assert ": onSheet(lk, c.file))}" not in ph and ": setFace(f.file))}" not in ph
    assert "onUse={() => onSheet(lk, c.file)}" in ph and "onUse={() => setFace(f.file)}" in ph     # 明确点“用这张”才换
    assert 'fetch("/api/decision-locks")' in ph and 'guardLock("sheet"' in ph and 'guardLock("face"' in ph
    assert "换掉已定的图？" in ph and ">\n                不换" in ph and ">\n                换\n" in ph


def test_overview_and_canvas_use_backend_tags():
    sp = (ROOT / "apps/web/src/v3/pages/SeasonPage.tsx").read_text(encoding="utf-8")
    assert "<MainTag st={x.status} size=\"xs\" />" in sp and "<TagLegend" in sp and "<TagCounts" in sp and "blk-stages" in sp
    rr = (ROOT / "apps/web/src/v3/ReviewRow.tsx").read_text(encoding="utf-8")
    assert "<MainTag st={rowCands?.[s.id]?.status} />" in rr
    css = (ROOT / "apps/web/src/v3/infra.css").read_text(encoding="utf-8")
    assert "@media (max-width: 1440px)" in css and ".v3-step.cur:not(.on) small { display: none; }" in css



def test_r42_full_redo_is_in_progress_not_stale(monkeypatch):
    """r42（总调度：“每集都挂过期”核实）：L-088 全量重做是现行计划——在出 = 出图中、没轮到 = 排队中，板块算进行中，不算过期"""
    reg = {"ep02-S1": {"first": {"status": "ready", "redo": True, "master_reject": "L-088 全量重做（R0：现行 frame_v9）"}},
           "ep02-S2": {"first": {"status": "running", "redo": True, "reason": "总调度驳回 v14：L-088 全量重做"}}}
    monkeypatch.setattr(S, "_registry", lambda: reg)
    a = S.tags_for("ep02-S1", {})
    b = S.tags_for("ep02-S2", {})
    assert a["main"] == "queued" and "全量重做" in a["tags"][0]["text"] and b["main"] == "busy"
    regs = {2: {"objects": {"script": {"status": "passed"}}, "shots": [{"shot": "ep02-S1", "objects": reg["ep02-S1"]}]}}
    monkeypatch.setattr(S, "_registry_eps", lambda: regs)
    blk = S.episode_blocks(2, [{"id": "ep02-S1", "status": a}])
    assert {x["key"]: x["state"] for x in blk["stages"]}["first"] == "doing" and blk["state"] != "stale"


def test_r42_topbar_counts():
    rt = (ROOT / "services/api/ns_api/render_tasks.py").read_text(encoding="utf-8")
    assert 'counts["queued"]' in rt and 'counts["planned"]' in rt and 'counts["failed_recent"]' in rt
    btn = (ROOT / "apps/web/src/components/RenderTasks.tsx").read_text(encoding="utf-8")
    assert "排队 {c.queued ?? c.pending}" in btn and "c.failed_recent ?? c.failed" in btn
    jb = (ROOT / "services/api/ns_api/jobs.py").read_text(encoding="utf-8")
    assert '"probing": bool(pr.get("probing"))' in jb
    gp = (ROOT / "apps/web/src/components/GpuPanel.tsx").read_text(encoding="utf-8")
    assert "卡 探测中…" in gp and "known" in gp
    ln = (ROOT / "apps/web/src/v3/edit/lanes.ts").read_text(encoding="utf-8")
    assert 'external: "在出（服务器派单）"' in ln and 'if (l.probing) return "探测中…";' in ln
