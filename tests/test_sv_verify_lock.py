"""system_version：verify 子命令（两台编译版本 / 清单 sha / golden dry-run 一致）+ cut 写入锁与 LOCKS.md 打通（总调度 11-03）。"""
from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("ns_system_version_vl", ROOT / "tools/qa/system_version.py")
SV = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(SV)

SV_ID = "sv-20990101-01"
CODE = {f: f"sha_{n}" for n, f in enumerate(SV.VERIFY_CODE)}
GOLD = {"shot": "ep01-S8", "prompt_sha": "p1", "refs_sha": "r1", "route": "server_ok", "adult": False,
        "preflight_ok": True, "preflight_fail": [], "refs": [{"file": "a.png", "sha": "x"}]}


def _raw(sv=SV_ID, man="b8f18d99aaaa", code=None, gold=GOLD, gold_text=None):
    m = SV.VERIFY_MARK
    code = CODE if code is None else code
    L = [f"{m} version", json.dumps({"id": sv, "commit": "c"}), f"{m} manifest", f"{man}  assets_v2/manifest.json", f"{m} code"]
    L += [f"{s}  {f}" for f, s in code.items()]
    L += [f"{m} golden", "一些日志"]
    L += [gold_text] if gold_text is not None else ["GOLDEN_SUMMARY " + json.dumps(gold, ensure_ascii=False)]
    return "\n".join(L) + "\n"


def test_parse_probe_reads_all_sections():
    p = SV.parse_probe(_raw())
    assert p["stamp"]["id"] == SV_ID and p["manifest_sha"] == "b8f18d99aaaa"
    assert p["code"] == CODE and p["golden"]["prompt_sha"] == "p1" and p["golden_err"] is None


def test_judge_all_consistent_ok():
    probes = {"gpu33": SV.parse_probe(_raw()), "gpu36": SV.parse_probe(_raw())}
    r = SV.judge_verify(SV_ID, probes, CODE, "b8f18d99")
    assert r["ok"] and r["golden_same"] and r["manifest_same"]
    assert all(h["version_ok"] and h["code_ok"] and h["manifest_ok"] for h in r["hosts"].values())


def test_judge_fails_on_each_item():
    ok = SV.parse_probe(_raw())
    cases = {
        "version": SV.parse_probe(_raw(sv="sv-20261102-16")),
        "code": SV.parse_probe(_raw(code={**CODE, SV.VERIFY_CODE[0]: "other"})),
        "manifest": SV.parse_probe(_raw(man="deadbeef")),
        "golden": SV.parse_probe(_raw(gold={**GOLD, "prompt_sha": "p2"})),           # 两台各自编译出不同结果（根因模式 #2）
        "no_golden": SV.parse_probe(_raw(gold_text="usage: golden_v2.py: error: unrecognized arguments: --summary")),
    }
    for name, bad in cases.items():
        r = SV.judge_verify(SV_ID, {"gpu33": ok, "gpu36": bad}, CODE, "b8f18d99")
        assert not r["ok"], name
    r = SV.judge_verify(SV_ID, {"gpu33": ok, "gpu36": {"error": "ssh 失败"}}, CODE, "b8f18d99")
    assert not r["ok"] and r["hosts"]["gpu36"]["error"]
    r = SV.judge_verify(SV_ID, {"gpu33": ok, "gpu36": ok}, CODE, "b8f18d99", local_golden={**GOLD, "refs_sha": "r9"})
    assert not r["ok"] and not r["golden_same"]                                     # 本地和服务器不一致也不过
    r = SV.judge_verify(SV_ID, {"gpu33": ok}, {**CODE, "x.py": None}, None)
    assert not r["ok"]                                                              # 版本快照里没有的文件 = 不通过


def test_probe_cmd_is_compile_only():
    c = SV.verify_probe_cmd("/srv/R", "/srv", "gpu36", "series10_v2", 8)
    assert "golden_v2.py --summary --shot 8" in c and "--render" not in c and "NS_RUN=series10_v2" in c
    assert "assets_v2/manifest.json" in c and "data/system_version.txt" in c


def test_verify_uses_rs_ssh_and_writes_record(monkeypatch, tmp_path):
    calls = []
    rs = NS(HOSTS=["gpu33", "gpu36"], R="/r", OFF="/o",
            ssh=lambda h, cmd, **kw: (calls.append(h), _raw().encode())[1])
    monkeypatch.setattr(SV, "DATA", tmp_path)
    monkeypatch.setattr(SV, "tag_blob_sha", lambda sv, f: CODE[f])
    r = SV.verify(SV_ID, None, 8, "series10_v2", "b8f18d99", rs=rs)
    assert r["ok"] and calls == ["gpu33", "gpu36"] and list(tmp_path.glob(f"verify_{SV_ID}_*.json"))


def test_deploy_calls_verify_after_hosts():
    src = (ROOT / "tools/qa/system_version.py").read_text(encoding="utf-8")
    body = src[src.index("def deploy("):src.index("def rollback(")]
    assert body.index("deploy_host(") < body.index("verify(sv, ok_hosts")
    assert "run_verify" in body


# ---------------------------------------------------------------- 写入锁 ↔ LOCKS.md
LOCKS = "# 文件锁（UIMASTER 维护）\n\n| a | b |\n|---|---|\n\n## 临时锁\n\n| x | y |\n"


def test_locks_md_active_then_inactive(monkeypatch, tmp_path):
    md = tmp_path / "LOCKS.md"
    md.write_text(LOCKS, encoding="utf-8")
    monkeypatch.setattr(SV, "CUT_LOCK", tmp_path / "cut_lock.json")
    monkeypatch.setattr(SV, "LOCKS_MD", md)
    SV.cut_lock(True, "sv-x", "t")
    t = md.read_text(encoding="utf-8")
    assert "🔒 冻结中" in t and "sv-x" in t and all(d in t for d in ("services/", "tools/", "tests/"))
    assert t.index(SV.LOCK_BEGIN) < t.index("## 临时锁") and t.count(SV.LOCK_BEGIN) == 1
    SV.cut_lock(False, "sv-x", "end")
    t2 = md.read_text(encoding="utf-8")
    assert "🔒 冻结中" not in t2 and "未冻结" in t2 and t2.count(SV.LOCK_BEGIN) == 1
    assert t2.replace(SV.locks_md_block(None), "") .replace("\n\n\n", "\n\n") .startswith("# 文件锁")
    assert SV.locks_md_text(t2, None) == t2                                         # 未冻结版本稳定：不会每次多一个改动
    assert "| x | y |" in t2                                                        # 别人登记的锁一字不动


def test_locks_md_keeps_crlf():
    t = LOCKS.replace("\n", "\r\n")
    out = SV.locks_md_text(t, {"active": True, "sv": "s", "pid": 1, "expires_t": 0})
    assert "\r\n" in out and "\n" not in out.replace("\r\n", "")


def test_frozen_tree_gets_inactive_locks_md(tmp_path):
    """cut 期间工作树 LOCKS.md 是 🔒；冻结树（进版本的）里必须是“未冻结”版本"""
    def g(*a, env=None):
        return subprocess.run(["git", *a], cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", env=env, check=True, timeout=60).stdout
    g("init", "-q")
    g("config", "user.email", "t@t")
    g("config", "user.name", "t")
    md = tmp_path / SV.LOCKS_MD_REL
    md.parent.mkdir(parents=True)
    md.write_text(SV.locks_md_text(LOCKS, None), encoding="utf-8")
    g("add", "-A")
    g("commit", "-qm", "base")
    md.write_text(SV.locks_md_text(LOCKS, {"active": True, "sv": "s", "pid": 1, "expires_t": 0}), encoding="utf-8")
    idx = tmp_path / "idx"
    env = {**SV.ENV, "GIT_INDEX_FILE": str(idx)}
    g("read-tree", "HEAD", env=env)
    g("add", "-A", env=env)
    assert "🔒" in g("show", f":{SV.LOCKS_MD_REL}", env=env)
    SV.index_locks_md_inactive(env, tmp_path)
    staged = g("show", f":{SV.LOCKS_MD_REL}", env=env)
    assert "🔒 冻结中" not in staged and "未冻结" in staged


def test_freeze_tree_calls_inactive_override():
    src = (ROOT / "tools/qa/system_version.py").read_text(encoding="utf-8")
    body = src[src.index("def freeze_tree("):src.index("def ignored_paths(")]
    assert body.index('"add", "-A"') < body.index("index_locks_md_inactive(env)") < body.index("write-tree")


def test_verify_without_shot_fails_closed(monkeypatch, tmp_path):
    """没有镜号：不碰服务器、不退回默认金样，直接记一条不通过（ISS-1103-005000-2af2）"""
    import pytest
    calls = []
    rs = NS(HOSTS=["gpu33", "gpu36"], R="/r", OFF="/o", ssh=lambda *a, **k: calls.append(a) or b"")
    monkeypatch.setattr(SV, "DATA", tmp_path)
    r = SV.verify(SV_ID, None, None, "series10_v2", "b8f18d99", rs=rs)
    assert r["ok"] is False and "必须指定镜号" in r["reason"] and calls == []
    assert list(tmp_path.glob(f"verify_{SV_ID}_*.json"))
    with pytest.raises(ValueError):
        SV.verify_probe_cmd("/r", "/o", "gpu36", "series10_v2", None)
    with pytest.raises(ValueError):
        SV.local_golden_summary("series10_v2", None)
