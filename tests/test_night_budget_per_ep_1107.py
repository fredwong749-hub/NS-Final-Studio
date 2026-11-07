"""逻辑纪律补丁 v3 §2d：合成失败重试与 BGM 自动重合成的预算按集累计，签名变不得清零（原来按 sig 分桶 = 无上限）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/series10_video"))
import night as N  # noqa: E402


def test_retry_budget_not_reset_by_sig_change(monkeypatch):
    monkeypatch.setattr(N, "log", lambda *a, **k: None)
    sigs = iter(f"S{i}" for i in range(100))
    monkeypatch.setattr(N, "ep_sig", lambda ep, host: next(sigs))
    st = {"eps": {"1": {"host": "gpu36", "status": "assemble_failed", "resolved_sig": "old", "assemble_retries": 0}}}
    reopened = 0
    for _ in range(10):                       # 每轮签名都变（vidgen 摇摆）+ 每轮合成又失败
        N.retry_assembly(st)
        x = st["eps"]["1"]
        if x["status"] == "rendering":
            reopened += 1
            x.update(status="assemble_failed", resolved_sig="old")
    assert reopened == N.ASM_RETRY_MAX


def test_bgm_budget_per_episode(monkeypatch, tmp_path):
    monkeypatch.setattr(N, "log", lambda *a, **k: None)
    monkeypatch.setattr(N, "EPS_OUT", tmp_path)
    (tmp_path / "ep01_v1.timeline.json").write_text("{}", encoding="utf-8")
    locks = iter(f"L{i}" for i in range(100))
    monkeypatch.setattr(N, "run", lambda args, t: (0, '{"status": "draft", "lock": {"locked": false, "fails": ["L5"], "sig": "%s"}}' % next(locks)))
    st = {"eps": {"1": {"status": "assembled"}}}
    n = 0
    for _ in range(10):                       # 每次剪辑签名都不同
        st["eps"]["1"]["status"] = "assembled"
        N.bgm_after_assembly(1, "v1", used_bgm=False, st=st)
        n += st["eps"]["1"]["status"] == "rendering"
    assert n == N.BGM_AUTO_MAX
