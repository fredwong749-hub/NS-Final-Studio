"""项目方 11-06：每版推独立分支 release/<sv> + 开 PR 合到 master，不再直接推 master"""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("sv_rel_pr", ROOT / "tools/qa/system_version.py")
SV = importlib.util.module_from_spec(spec)
spec.loader.exec_module(SV)


def test_push_remote_pushes_release_branch_and_opens_pr(monkeypatch, tmp_path):
    calls = []

    def fake_sh(cmd, timeout=1800, **k):
        calls.append(cmd)
        if cmd[:3] == ["gh", "pr", "create"]:
            return 0, "https://github.com/o/r/pull/7\n"
        return 0, "ok"

    monkeypatch.setattr(SV, "sh", fake_sh)
    monkeypatch.setattr(SV, "secret_hits", lambda prev: [])
    monkeypatch.setattr(SV, "git", lambda *a, **k: "master")
    monkeypatch.setattr(SV, "ROOT", tmp_path)
    r = SV.push_remote("sv-prev", "sv-20990101-01")
    pushes = [c for c in calls if c[:2] == ["git", "push"]]
    assert ["git", "push", "origin", "sv-20990101-01^{commit}:refs/heads/release/sv-20990101-01"] in pushes
    assert not any(c[-2:] == ["master", "--follow-tags"] or c[3:4] == ["master"] for c in pushes)
    pr = next(c for c in calls if c[:3] == ["gh", "pr", "create"])
    assert pr[pr.index("--base") + 1] == "master" and pr[pr.index("--head") + 1] == "release/sv-20990101-01"
    assert r["ok"] and r["branch"] == "release/sv-20990101-01" and r["pr"]["url"].endswith("/pull/7")
    body = (tmp_path / "data/system_versions/sv-20990101-01_pr_body.md").read_text(encoding="utf-8")
    assert "Generated with [Claude Code]" in body


def test_secret_hit_blocks_push(monkeypatch, tmp_path):
    monkeypatch.setattr(SV, "sh", lambda cmd, timeout=1800, **k: (0, "x"))
    monkeypatch.setattr(SV, "secret_hits", lambda prev: ["a.py:1"])
    monkeypatch.setattr(SV, "ROOT", tmp_path)
    r = SV.push_remote("p", "sv-x")
    assert r["ok"] is False and r.get("blocked")
