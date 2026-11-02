"""SYSARCH 4-1 事故回归（11-02 sv-06：remote_score 换 rssh.run_retry 后 gpu36 上 full_score("gpu33") 被判跨机 → 36 单全 score_infra）。
规则 K-OPS-Y02：每个换成 rssh 的服务器侧调用点，都要在 resident_restart.sh 设的环境（OFFLINE_SELF / OFFLINE_ALIASES）下测一遍：
调本机和别名 → 本机 bash -c；调另一台 → rc=255、不起任何进程。不连服务器、不起真进程（subprocess.run 换成假的）。"""
import importlib.util
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RESTART_SH = ROOT / "ops/offline/resident_restart.sh"


def _load(rel: str):
    spec = importlib.util.spec_from_file_location("m_" + rel.replace("/", "_").replace(".", "_"), ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def fake_run(monkeypatch):
    calls = []

    def run(argv, *a, **k):
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, b"{}\n", b"")
    monkeypatch.setattr(subprocess, "run", run)
    return calls


def test_restart_sh_still_sets_the_contract():
    """契约来源：resident_restart.sh 里 gpu36 的 OFFLINE_ALIASES = gpu33（这里变了，下面的用例要跟着变）"""
    sh = RESTART_SH.read_text(encoding="utf-8")
    assert "OFFLINE_SELF=$SELF" in sh and re.search(r"OFFLINE_ALIASES=\$\(\[ \$SELF = gpu36 \] && echo gpu33\)", sh)


@pytest.mark.parametrize("me,aliases,target,want", [
    ("gpu36", "gpu33", "gpu33", "local"),   # 事故用例：gpu36 上 full_score("gpu33") = 本机
    ("gpu36", "gpu33", "gpu36", "local"),
    ("gpu33", "", "gpu33", "local"),
    ("gpu33", "", "gpu36", "refuse"),       # 两台之间无互信：立刻 255，不起进程
])
def test_remote_score_ssh_under_server_env(monkeypatch, fake_run, me, aliases, target, want):
    monkeypatch.setenv("OFFLINE_SELF", me)
    monkeypatch.setenv("OFFLINE_ALIASES", aliases)
    RS = _load("tools/gen_contract/remote_score.py")
    r = RS.ssh(target, "echo hi")
    if want == "local":
        assert r.returncode == 0 and fake_run and fake_run[-1][:2] == ["bash", "-c"]
    else:
        assert r.returncode == 255 and not fake_run


@pytest.mark.parametrize("rel,call", [
    ("tools/series10_video/night.py", lambda m: m.ssh("gpu33", "echo hi")),
    ("tools/series10_imggen/server_deploy.py", lambda m: m.ssh("gpu33", "echo hi")),
    ("tools/series10_video/deploy.py", lambda m: m.ssh("gpu33", "echo hi")),
])
def test_other_converted_sites_alias_is_local(monkeypatch, fake_run, rel, call):
    monkeypatch.setenv("OFFLINE_SELF", "gpu36")
    monkeypatch.setenv("OFFLINE_ALIASES", "gpu33")
    try:
        m = _load(rel)
    except Exception as e:   # noqa: BLE001 —— 模块顶层依赖服务器环境时跳过并写明（不是通过）
        pytest.skip(f"{rel} 在笔记本上导入不了：{type(e).__name__}: {e}")
    call(m)
    assert fake_run and fake_run[-1][:2] == ["bash", "-c"], fake_run
