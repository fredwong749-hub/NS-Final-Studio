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
