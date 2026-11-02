"""UIRSI r43 P0（OVERVIEW_REDESIGN §2.3 K1–K7）：数字口径。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/api", "services/render_router", "services/agent"):
    sys.path.insert(0, str(ROOT / p))

from ns_api import live as L  # noqa: E402
from ns_api import shot_status as S  # noqa: E402


def test_main5_frontmost_step():
    """K6：主状态 = 最前一个没确认的步骤；上游重做时下游的旧结论不再另报"""
    f = S.main5
    full = {"status": "ready", "attempts": 0, "max_attempts": 2, "master_reject": "L-088 全量重做（R0）"}
    assert f("x", {"first": full, "last": {"status": "passed"}})["why"] == "首帧排队重出（第 1/2 次）"
    assert f("x", {"first": {"status": "running", "reason": "L-088 全量重做"}})["running"] is True
    r = f("x", {"first": {"status": "passed"}, "last": {"status": "ready", "attempts": 2, "max_attempts": 2, "last_error": "契约没过：鞋不对"}})
    assert r["main5"] == "need" and "鞋不对" in r["why"]
    r = f("x", {"first": {"status": "passed"}, "last": {"status": "ready", "attempts": 1, "max_attempts": 3, "last_error": "契约没过：鞋不对"}})
    assert r["main5"] == "doing" and "自动重试 1/3" in r["why"]
    assert f("x", {"first": {"status": "best_effort"}})["main5"] == "need"
    assert f("x", {"first": {"status": "pending", "stale": True}})["main5"] == "stale"
    assert f("x", {"first": {"status": "passed"}, "last": {"status": "pending", "waiting_for": "首帧过契约"}})["why"] == "尾帧未开始（等首帧）"
    allp = {"first": {"status": "passed"}, "last": {"status": "passed"}, "video": {"status": "passed"}}
    assert f("ep99-S1", allp)["main5"] == "need" and f("ep99-S1", allp)["why"] == "视频待你审"


def test_episode_need_stale_counts(monkeypatch):
    monkeypatch.setattr(S, "_registry_eps", lambda: {})
    b = S.episode_blocks(1, [{"id": "a", "status": {"main5": "need", "tags": []}}, {"id": "b", "status": {"main5": "stale", "tags": []}},
                             {"id": "c", "status": {"main5": "doing", "tags": []}}])
    assert b["need_n"] == 1 and b["stale_n"] == 1


def test_progress_infra_errors_and_quarantine():
    """K4：连接被拒 / API 重启打断不算内容失败；K5：隔离旧剧本后的减少不标倒退"""
    assert L.INFRA_ERR.search("/upload/image: [WinError 10061] No connection could be made")
    assert L.INFRA_ERR.search("API 重启时中断（不是画面问题）")
    assert not L.INFRA_ERR.search("契约没过：服装 / 单品对不上参考")
    assert "QUARANTINE_LOG" in dir(L) and callable(L._quarantined_since)


def test_counts_and_topbar_wording():
    rt = (ROOT / "services/api/ns_api/render_tasks.py").read_text(encoding="utf-8")
    assert "RECENT_FAIL_H = 6 " in rt and "ok_after" in rt          # K3 → r44：近 6 小时、后来没成功过的才算
    btn = (ROOT / "apps/web/src/components/RenderTasks.tsx").read_text(encoding="utf-8")
    assert "在办 {c.rendering} · 排队 {c.queued ?? c.pending}" in btn
    gp = (ROOT / "apps/web/src/components/GpuPanel.tsx").read_text(encoding="utf-8")
    assert "出图 ${fac.busy ?? 0}/${fac.total} 道在出" in gp       # K1：分母 = 5 条出图道
    fh = (ROOT / "services/api/ns_api/factory_health.py").read_text(encoding="utf-8")
    assert "RECENT_S = 60" in fh and '"出图" if (not r0 or ag) else "其他任务"' in fh and '"light": light' in fh   # K1 / K2 / 生产灯


# ---------------- UIAUDIT 复核 P0 / P1 修复（UIRSI r43）----------------
def test_decision_lock_regex_and_literal():
    """P0-1：owner_decisions 的 pattern 是正则（sleevefix\\.png），前端按字面比永远对不上 → 同时给 regex 和去转义的 match"""
    import re

    from ns_api import decision_locks as D
    pat = "lin_wan_lookA_v2_s202_sleevefix" + chr(92) + ".png"
    out = D._locks_from([{"id": "x", "type": "grep_present", "paths": ["data/looks/sheets_chosen.json"], "pattern": pat,
                          "decision": "L-093 11-01 21:4x"}])
    assert out[0]["match"] == "lin_wan_lookA_v2_s202_sleevefix.png"
    assert re.search(out[0]["regex"], "adopted/lin_wan_lookA_v2_s202_sleevefix.png")
    assert not re.search(out[0]["regex"], "adopted/lin_wan_lookA_v2_s202_sleevefixXpng")


def test_story_images_hide_old_script_drafts(monkeypatch, tmp_path):
    """P0-2：画布草图兜底只用现行剧本版本之后的草图（mtime ≥ 本集导入时间），旧剧本草图隐藏并计数"""
    import os
    import time as _t

    from ns_api import story_runs as SR
    from ns_api import takes_ui as T
    src = Path(SR.__file__).read_text(encoding="utf-8")
    assert "old_drafts_hidden" in src and "cutoff_for" in src
    monkeypatch.setattr(T, "cutoff_for", lambda ep: "2026-11-01T23:21:00")
    cut = _t.mktime(_t.strptime("2026-11-01T23:21:00", "%Y-%m-%dT%H:%M:%S"))
    old = tmp_path / "old.png"
    new = tmp_path / "new.png"
    for f, t in ((old, cut - 3600), (new, cut + 60)):
        f.write_bytes(b"x")
        os.utime(f, (t, t))
    assert old.stat().st_mtime < cut <= new.stat().st_mtime


def test_episode_counts_exclude_quarantined():
    """P1-1：/api/episodes 的 takes_count / latest_take 不算已隔离的版本（与 _active 同口径 is_quarantined）"""
    src = (ROOT / "services/api/ns_api/app.py").read_text(encoding="utf-8")
    assert "not is_quarantined(t)" in src


def test_take_checks_endpoint(monkeypatch):
    """详情抽屉“检查结果”：postflight 逐项 + 最后一轮看图判定，只读"""
    from ns_api import takes_ui as T

    class P:
        @staticmethod
        def load_takes(sid):
            return {"takes": [{"stage": "image", "n": 3, "postflight": {"items": [{"id": "Q1", "title": "身份", "status": "pass", "detail": "过线"},
                                                                                  {"id": "Q3", "title": "景别", "status": "fail", "detail": "要特写"}]},
                               "params": {"vqa_rounds": [{"judge": {"verdict": "fail", "reasons": ["景别不对"], "failed_checks": ["Q3"]}}]}}]}
    monkeypatch.setattr(T, "_P", lambda: P)
    d = T.take_checks("ep01-S1", "image", 3)
    assert [x["status"] for x in d["items"]] == ["pass", "fail"]
    assert d["judge"]["verdict"] == "fail" and d["judge"]["failed"] == ["Q3"]
    import pytest
    with pytest.raises(Exception):
        T.take_checks("ep01-S1", "image", 9)


def test_infra_reconnect_only_failing_ports():
    """P1-3：重连提示只说真断了的连接；base 叫“主连接”；cmd 连接不报"""
    src = (ROOT / "services/api/ns_api/infra_status.py").read_text(encoding="utf-8")
    assert "bad_ports" in src and "正在重连主连接" in src and '"cmd" in hk' in src


def test_f26_tick_entry_restored():
    """F26：工具 ▾ → 运行 里恢复“立即推进一步”（POST /api/projects/{slug}/production/tick）"""
    src = (ROOT / "apps/web/src/v3/TopBarV3.tsx").read_text(encoding="utf-8")
    assert "立即推进一步" in src and "/production/tick" in src and "is_default" in src


def test_breathe_light_shared_and_reduced_motion():
    """K-UI-048：全站呼吸灯一个共享类，0.35 ↔ 1、2.4–3 s、ease-in-out；减少动态时静止；排队不呼吸"""
    css = (ROOT / "apps/web/src/v3/breathe.css").read_text(encoding="utf-8")
    assert ".is-rendering" in css and "--breathe-lo: .35" in css and "ease-in-out" in css
    assert "prefers-reduced-motion" in css and ".is-queued" in css
    import re
    per = float(re.search(r"--breathe-period:\s*([\d.]+)s", css).group(1))
    assert 2.4 <= per <= 3.0
    assert 'import "./v3/breathe.css"' in (ROOT / "apps/web/src/App.tsx").read_text(encoding="utf-8")


def test_overview_three_dots_only():
    """总调度 02:2x §一：总览状态只用三种 8px 小圆点（渲染中 / 需要人看 / 已确认），其他状态不画点"""
    ts = (ROOT / "apps/web/src/v3/pages/seasonDot.ts").read_text(encoding="utf-8")
    assert 'export type SeaDot = "run" | "need" | "ok";' in ts
    css = (ROOT / "apps/web/src/v3/shotstatus.css").read_text(encoding="utf-8")
    assert ".sea-dot { display: inline-block; width: 8px; height: 8px;" in css


# ---------------- r44 / r45：:8800 守护重启（G1：把“空闲才重启”从 claude 判断改成代码）----------------
def _guard(monkeypatch, tmp_path):
    sys.path.insert(0, str(ROOT / "tools" / "uirsi"))
    import importlib

    import api_restart_guard as G
    importlib.reload(G)
    monkeypatch.setattr(G.RQ, "REQ", tmp_path / "req.jsonl")
    monkeypatch.setattr(G.RQ, "DONE", tmp_path / "done.jsonl")
    monkeypatch.setattr(G, "refresh_dist", lambda dry=False: {"stale": False})
    monkeypatch.setattr(G, "_marker", lambda: {"up_at": "2026-11-02T00:00:00"})
    (tmp_path / "svc").mkdir()
    (tmp_path / "svc" / "ok.py").write_text("x = 1" + chr(10), encoding="utf-8")
    monkeypatch.setattr(G, "COMPILE_DIRS", [tmp_path / "svc"])
    monkeypatch.setattr(G, "ALERTS", tmp_path / "alerts.jsonl")
    return G


def test_guard_waits_when_busy_and_dedupes(monkeypatch, tmp_path):
    G = _guard(monkeypatch, tmp_path)
    monkeypatch.setattr(G, "changed_since_up", lambda: ["services/api/ns_api/season.py"])
    monkeypatch.setattr(G, "busy", lambda: 2)
    a = G.tick()
    assert "后端改动合入" in a["requested"] and "等空闲" in a["skip"]
    b = G.tick()                                  # 同一批改动不重复排
    assert "requested" not in b and len(G.RQ.pending(G.HOST)) == 1
    monkeypatch.setattr(G, "busy", lambda: None)
    assert "不重启" in G.tick()["skip"]             # 读不到 /api/jobs 按不确定处理


def test_guard_restarts_when_idle(monkeypatch, tmp_path):
    G = _guard(monkeypatch, tmp_path)
    monkeypatch.setattr(G, "changed_since_up", lambda: [])
    G.RQ.request(G.HOST, "test", by="UIRSI")
    monkeypatch.setattr(G, "busy", lambda: 0)

    class R:
        returncode = 0
        stdout = b"stopped x  up y"
        stderr = b""
    calls = []
    monkeypatch.setattr(G.subprocess, "run", lambda *a, **k: calls.append(a) or R())
    a = G.tick()
    assert a["restart"]["ok"] and calls and "restart_api.ps1" in " ".join(calls[0][0])
    assert G.RQ.pending(G.HOST) == []             # 写进 done
    assert G.tick()["skip"] == "没有待办"


# ---------------------------------------------------------------- UIRSI2 L-116 待你看队列（K-UI-053，data_parity D-QUEUE）
def _oq_root(tmp_path, *, mode="auto"):
    import json as _j
    import time as _t
    from ns_api import owner_queue as Q
    today = _t.strftime("%Y-%m-%dT%H:%M:%S")
    (tmp_path / "data" / "vqa").mkdir(parents=True)
    (tmp_path / "data" / "vqa" / "autosign_state.json").write_text(_j.dumps({"mode": mode, "agreement": 1.0, "n": 35}), encoding="utf-8")
    ok = {"ok": True, "items": [{"id": "Q1", "title": "身份", "status": "pass", "detail": "过线"}, {"id": "Q9", "status": "pass"}]}
    bad = {"ok": False, "items": [{"id": "Q1", "status": "fail"}]}
    for i in range(1, 12):
        d = tmp_path / "data" / "renders" / "ep01" / f"S{i}"
        d.mkdir(parents=True)
        (d / "takes.json").write_text(_j.dumps({"active": {"image": 2}, "takes": [
            {"n": 1, "stage": "image", "file": f"renders/ep01/S{i}/a.png", "created_at": today, "postflight": bad},
            {"n": 2, "stage": "image", "file": f"renders/ep01/S{i}/b.png", "created_at": today, "postflight": ok}]}), encoding="utf-8")
    q = tmp_path / "data" / "owner_queue"
    q.mkdir(parents=True)
    (q / "requests.json").write_text(_j.dumps([
        {"id": "r-spend", "kind": "decide", "category": "spend", "title": "买 API 额度"},
        {"id": "r-misc", "kind": "decide", "category": "tune_param", "title": "调参（不该问项目方）"},
        {"id": "p-two", "kind": "pick", "title": "挑造型", "recommend": "b", "candidates": [
            {"key": "a", "sid": "ep01-S1", "stage": "image", "n": 2}, {"key": "b", "sid": "ep01-S2", "stage": "image", "n": 2},
            {"key": "x", "sid": "ep01-S3", "stage": "image", "n": 1}]},
        {"id": "p-one", "kind": "pick", "title": "只剩一张", "candidates": [
            {"key": "a", "sid": "ep01-S4", "stage": "image", "n": 2}, {"key": "x", "sid": "ep01-S4", "stage": "image", "n": 1}]}]), encoding="utf-8")
    (tmp_path / "docs" / "master").mkdir(parents=True)
    (tmp_path / "docs" / "master" / "MASTER_PICTURE.md").write_text(
        "| L-058 | t | 原话 | 旧内容先隔离，验证后由项目方删除 | 清理 | — | x | `ops/cleanup/del.ps1` 待项目方运行 | ✅（删除待项目方） |\n"
        "| L-079 | t | 原话 | 同一个删除 | 清理 | — | x | ops/cleanup/del.ps1 在 | ✅（删除待项目方） |\n", encoding="utf-8")
    (tmp_path / "data" / "sentinel").mkdir(parents=True)
    (tmp_path / "data" / "sentinel" / "open.json").write_text(_j.dumps({"issues": [
        {"id": "SN-1", "key": "S13:wait:laptop", "slo": "S13", "status": "open", "title": "等",
         "evidence": {"n": 3, "objs": ["first:ep01-S1"], "reasons": ["驳回重出 2 次都没换上，等总调度定"]}}]}), encoding="utf-8")
    return Q


def test_owner_queue_sources_and_filters(tmp_path):
    """三类事：只问项目方该拍板的五类；挑选只放过契约的候选、只剩一张自动选；等总调度的只计数；抽检每 10 张抽 1 张"""
    Q = _oq_root(tmp_path)
    q = Q.build(tmp_path)
    ids = {x["id"] for x in q["items"]}
    assert "r-spend" in ids and "r-misc" not in ids          # 非五类 → 不打扰项目方
    assert "mp:L-058" in ids and "mp:L-079" not in ids       # 同一脚本只出一项
    assert not any(i.startswith("sn:") for i in ids) and q["master_waits"]["n"] == 3
    pk = next(x for x in q["items"] if x["id"] == "p-two")
    assert [c["key"] for c in pk["candidates"]] == ["a", "b"] and pk["recommend"]["choice"] == "b"
    assert "p-one" not in ids and any(d["id"] == "p-one" and d["by"] == "POLICY" for d in Q.decisions(tmp_path))
    spots = [x for x in q["items"] if x["kind"] == "spot"]
    assert len(spots) == 2                                  # 11 张机签通过 → [::10] = 2 张
    assert q["count"] == len(q["items"]) == sum(q["counts"].values())
    # 被抽中的镜不显示“机签通过”，其余显示
    held = {x["sid"] for x in spots}
    assert set(q["machine_signed"]) == {f"ep01-S{i}" for i in range(1, 12)} - held
    assert all(v == {"image": 2} for v in q["machine_signed"].values())


def test_owner_queue_manual_mode_no_autosign(tmp_path):
    """机签没切 auto：不显示“机签通过”，也不抽检"""
    Q = _oq_root(tmp_path, mode="manual")
    q = Q.build(tmp_path)
    assert q["machine_signed"] == {} and q["counts"]["spot"] == 0


def test_owner_queue_decide_undo_and_spot(tmp_path):
    import pytest
    from fastapi import HTTPException
    Q = _oq_root(tmp_path)
    n0 = Q.build(tmp_path)["count"]
    r = Q.decide(tmp_path, "r-spend", "approve", "", "fredw")
    assert r["count"] == n0 - 1 and r["decision"]["by"] == "fredw"
    with pytest.raises(HTTPException):
        Q.decide(tmp_path, "r-spend", "approve", "", "fredw")        # 已处理
    assert Q.undo(tmp_path, "r-spend", "fredw")["count"] == n0       # Z 撤销 → 回到队列
    with pytest.raises(HTTPException):
        Q.decide(tmp_path, "mp:L-058", "bogus", "", "fredw")
    Q.decide(tmp_path, "mp:L-058", "later", "", "fredw")             # 稍后：4 小时内不出现
    assert "mp:L-058" not in {x["id"] for x in Q.build(tmp_path)["items"]}
    sp = next(x for x in Q.build(tmp_path)["items"] if x["kind"] == "spot")
    seen, redo = [], []
    r = Q.decide(tmp_path, sp["id"], "fail", "鞋不对", "fredw", spot_fn=lambda i, v: seen.append((i, v)) or {"action": "revert"},
                 redo_fn=lambda oid, n, why, plan, by: redo.append((oid, n, why, plan)) or {"ok": True})
    assert seen == [(sp["spot_id"], "fail")]
    # K-UI-055：抽检不同意 → 自动作废并按原因重出（鞋 = 造型 → faces_look）、记回归样本
    assert redo == [(f"first:{sp['sid']}", sp["n"], "项目方抽检不同意：鞋不对", ["frame_v9:faces_look", "frame_v9:faces_look"])]
    assert r["decision"]["redo"]["ok"] is True
    reg = (tmp_path / "data" / "vqa" / "regression" / "owner_spot_fail.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(reg) == 1 and '"human": "fail"' in reg[0] and sp["sid"] in reg[0]
    with pytest.raises(HTTPException):
        Q.undo(tmp_path, sp["id"], "fredw")                            # 抽检结论交给机签后撤不回


def test_owner_queue_decide_requires_logged_in_owner(monkeypatch):
    """登录即本人：没登录 / 不是项目方 → 403；登录的项目方才进到决定逻辑（这里 id 不存在 → 404）"""
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    from ns_api import auth
    from ns_api import owner_queue as Q
    app = FastAPI()
    app.include_router(Q.router)
    c = TestClient(app)
    body = {"id": "no-such-item", "choice": "approve", "by": "owner"}
    monkeypatch.setattr(auth, "user_of", lambda req: None)
    assert c.post("/api/owner/decide", json=body).status_code == 403
    monkeypatch.setattr(auth, "user_of", lambda req: {"name": "v", "role": "viewer"})
    assert c.post("/api/owner/decide", json=body).status_code == 403
    monkeypatch.setattr(auth, "user_of", lambda req: {"name": "fredw", "role": "owner"})
    monkeypatch.setattr(Q, "build", lambda root, now=None: {"items": [], "count": 0})
    assert c.post("/api/owner/decide", json=body).status_code == 404


def test_owner_queue_bad_source_is_reported_not_empty(tmp_path):
    """来源文件坏了 → 结果带 source_errors / complete=False，不悄悄当成“没有要看的”（SYSARCH 失败开放巡检）"""
    Q = _oq_root(tmp_path)
    (tmp_path / "data" / "owner_queue" / "requests.json").write_text("{坏", encoding="utf-8")
    q = Q.build(tmp_path)
    assert q["complete"] is False and any("requests.json" in e for e in q["source_errors"])
    assert q["status"] == "error" and q["status_label"] == "队列读取失败：requests.json"
    al = (tmp_path / "data" / "qa" / "alerts.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(al) == 1 and '"OWNERQ-READ"' in al[0]
    Q.build(tmp_path)                                                          # 同一错误 1 小时内不重复报警
    assert len((tmp_path / "data" / "qa" / "alerts.jsonl").read_text(encoding="utf-8").splitlines()) == 1
    (tmp_path / "data" / "owner_queue" / "requests.json").unlink()             # 可选来源没有文件 = 为空（正常）
    assert Q.build(tmp_path)["status"] == "ok"
    (tmp_path / "data" / "sentinel" / "open.json").unlink()                    # 必需来源被删 = 读取失败
    q = Q.build(tmp_path)
    assert q["status"] == "error" and q["status_label"] == "队列读取失败：open.json"


def test_owner_queue_errors_isolated_between_threads(tmp_path):
    """并发：两个请求同时汇总，坏来源的错误不串到好根目录的结果里（每次调用一份错误表）"""
    import threading as _th
    bad = tmp_path / "bad"
    good = tmp_path / "good"
    bad.mkdir()
    good.mkdir()
    Q = _oq_root(bad)
    _oq_root(good)
    (bad / "data" / "owner_queue" / "requests.json").write_text("{坏", encoding="utf-8")
    res: dict = {}

    def run(name, root):
        for _ in range(15):
            res.setdefault(name, []).append(Q.build(root)["status"])
    ts = [_th.Thread(target=run, args=("bad", bad)), _th.Thread(target=run, args=("good", good))]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert set(res["bad"]) == {"error"} and set(res["good"]) == {"ok"}


def test_guard_compile_gate_blocks_broken_restart(monkeypatch, tmp_path):
    """K-UI-054：后端有 .py 编译不过 → 不重启、开工单 API-COMPILE（只开一次），请求留着；修好后下一拍照常重启"""
    G = _guard(monkeypatch, tmp_path)
    monkeypatch.setattr(G, "changed_since_up", lambda: [])
    G.RQ.request(G.HOST, "test", by="UIRSI2")
    monkeypatch.setattr(G, "busy", lambda: 0)
    (tmp_path / "svc" / "half.py").write_text('x = "\n', encoding="utf-8")
    calls = []

    class R:
        returncode = 0
        stdout = b""
        stderr = b""
    monkeypatch.setattr(G.subprocess, "run", lambda *a, **k: calls.append(a) or R())
    a = G.tick()
    assert "编译不过" in a["skip"] and not calls and len(G.RQ.pending(G.HOST)) == 1
    assert "half.py" in a["compile_fail"][0]
    G.tick()
    assert len((tmp_path / "alerts.jsonl").read_text(encoding="utf-8").splitlines()) == 1
    (tmp_path / "svc" / "half.py").write_text('x = ""\n', encoding="utf-8")
    assert G.tick()["restart"]["ok"] and calls


def test_owner_queue_spot_fail_plan_and_redo_failure_alert(tmp_path):
    """K-UI-055：原因 → 重出计划；重出没派成 → 开工单 OWNERQ-REDO（不吞掉），回归样本照记"""
    Q = _oq_root(tmp_path)
    assert Q.spot_plan("身份不像") == ["frame_v9:double_face"] * 2
    assert Q.spot_plan("画面假，塑料感") == ["frame_v9_heavy"] * 2
    assert Q.spot_plan("手 / 肢体坏") == Q.spot_plan("") == ["frame_v9", "frame_v9"]
    sp = next(x for x in Q.build(tmp_path)["items"] if x["kind"] == "spot")

    def boom(*a):
        raise RuntimeError("跳板断了")
    r = Q.decide(tmp_path, sp["id"], "fail", "", "fredw", spot_fn=lambda i, v: {}, redo_fn=boom)
    assert r["decision"]["redo"]["ok"] is False and "跳板断了" in r["decision"]["redo"]["err"]
    al = (tmp_path / "data" / "qa" / "alerts.jsonl").read_text(encoding="utf-8")
    assert "OWNERQ-REDO" in al
    assert (tmp_path / "data" / "vqa" / "regression" / "owner_spot_fail.jsonl").exists()


def test_train_locks_request_path_never_calls_remote(monkeypatch):
    """K-UI-056（总调度 P0 14:1x）：训练锁只读后台刷新的缓存，调用线程里不连远端、不等；带缓存年龄"""
    import time as _t
    from ns_api import jobs as J

    def boom(*a, **k):
        raise AssertionError("请求路径里不许读远端训练锁")
    monkeypatch.setattr(J, "_read_locks", boom)
    monkeypatch.setattr(J, "_ensure_train_refresher", lambda: None)
    monkeypatch.setattr(J, "_train_cache", {})
    t0 = _t.monotonic()
    assert J._train_locks_async("gpu36", wait=True) == set() and _t.monotonic() - t0 < 0.1
    assert J.train_lock_age("gpu36") is None
    J._train_cache["gpu36"] = (_t.monotonic() - 12, {1})
    assert J._train_locks_async("gpu36") == {1} and 11 <= J.train_lock_age("gpu36") <= 14


def test_season_swr_returns_cache_without_blocking(monkeypatch):
    """总调度 P0 14:2x：/api/season 只读后台算好的缓存（带 cache_age_s），旧了起后台重算、不阻塞请求；算失败保留上次结果并带错误"""
    import threading as _th
    import time as _t
    from ns_api import season as SEA
    monkeypatch.setenv("SEASON_SWR_IN_TESTS", "1")
    gate = _th.Event()
    calls = []

    def slow():
        calls.append(1)
        gate.wait(5)
        return {"episodes": [{"number": len(calls)}], "faces": {}}
    monkeypatch.setattr(SEA, "season_now", slow)
    monkeypatch.setattr(SEA, "_swr", {"at": _t.monotonic() - 100, "val": {"episodes": [{"number": 0}], "faces": {}}, "thread": None, "err": None})
    t0 = _t.monotonic()
    r = SEA.season()
    assert _t.monotonic() - t0 < 0.5 and r["episodes"][0]["number"] == 0 and r["cache_age_s"] >= 99   # 旧缓存立即回
    gate.set()
    SEA._swr["thread"].join(5)
    assert SEA.season()["episodes"][0]["number"] == 1                                                  # 后台算好后换新
    monkeypatch.setattr(SEA, "season_now", lambda: (_ for _ in ()).throw(RuntimeError("坏")))
    SEA._swr["at"] = _t.monotonic() - 100
    SEA.season()
    SEA._swr["thread"].join(5)
    r = SEA.season()
    assert r["episodes"][0]["number"] == 1 and "坏" in r.get("cache_error", "")
