"""冻结锁第 2 层（ops/hooks/freeze_audit.py）。只测 check()，不装真 audit hook（audit hook 装上就撤不掉，会影响同进程别的测试）。"""
import importlib.util
import json
import os
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def FA(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("freeze_audit_t", ROOT / "ops/hooks/freeze_audit.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    lock = tmp_path / "cut_lock.json"
    monkeypatch.setattr(m, "LOCK", str(lock))
    monkeypatch.setattr(m, "STAT_EVERY_S", 0.0)
    monkeypatch.delenv("NS_FREEZE_EXEMPT", raising=False)

    def set_lock(active=True, pid=999999, expires=None):
        lock.write_text(json.dumps({"active": active, "sv": "sv-test", "pid": pid,
                                    "expires_t": expires if expires is not None else time.time() + 600}), encoding="utf-8")
        m._cache.update(checked=0.0, mtime=None, lock=None)
        os.utime(lock, None)
    m.set_lock = set_lock
    return m


def p(rel):
    return str(ROOT / rel)


def test_locked_blocks_write_open_replace_remove(FA):
    FA.set_lock()
    with pytest.raises(PermissionError):
        FA.check("open", (p("tools/x.py"), "w", 0))
    with pytest.raises(PermissionError):
        FA.check("open", (p("knowledge/rules/x.yaml"), None, os.O_WRONLY | os.O_CREAT))
    with pytest.raises(PermissionError):
        FA.check("os.replace", (p("data/tmp.json"), p("config/vqa.json")))
    with pytest.raises(PermissionError):
        FA.check("os.remove", (p("tests/test_x.py"),))


def test_reads_and_exempt_paths_pass(FA):
    FA.set_lock()
    FA.check("open", (p("tools/x.py"), "r", 0))
    FA.check("open", (p("data/sysarch/baseline.json"), "w", 0))
    FA.check("open", (p("ops/logs/a.log"), "a", 0))
    FA.check("open", (p("config/netfix/override.json"), "w", 0))
    FA.check("open", (p("config/netfix/partition.json"), "w", 0))
    FA.check("open", (p("docs/master/ARCH_ROADMAP.md"), "w", 0))
    FA.check("open", ("C:/elsewhere/tools/x.py", "w", 0))
    FA.check("open", (3, "w", 0))   # fd


def test_unlocked_or_expired_passes(FA):
    FA.set_lock(active=False)
    FA.check("open", (p("tools/x.py"), "w", 0))
    FA.set_lock(expires=time.time() - 1)
    FA.check("open", (p("tools/x.py"), "w", 0))


def test_lock_holder_and_exempt_env_pass(FA, monkeypatch):
    FA.set_lock(pid=os.getpid())
    FA.check("open", (p("tools/x.py"), "w", 0))
    FA.set_lock()
    monkeypatch.setenv("NS_FREEZE_EXEMPT", "1")
    FA.check("open", (p("tools/x.py"), "w", 0))


def test_hook_swallows_internal_errors(FA, monkeypatch):
    FA.set_lock()
    monkeypatch.setattr(FA, "rel_frozen", lambda path: (_ for _ in ()).throw(RuntimeError("boom")))
    FA._hook("open", (p("tools/x.py"), "w", 0))   # 守卫自身出错 → 放行，不抛


def test_lock_stat_is_cached(FA, monkeypatch):
    FA.set_lock()
    monkeypatch.setattr(FA, "STAT_EVERY_S", 60.0)
    FA._cache.update(checked=0.0, mtime=None, lock=None)
    assert FA._lock() is not None
    calls = []
    monkeypatch.setattr(os, "stat", lambda *a, **k: calls.append(a) or (_ for _ in ()).throw(OSError()))
    assert FA._lock() is not None and calls == []   # 2 s（这里 60 s）内不再 stat


def test_real_audit_hook_in_subprocess(tmp_path):
    """真装 audit hook（子进程里，装上撤不掉）：冻结目录写入被拒、data 写入照常、读照常"""
    import subprocess
    import sys
    lock = tmp_path / "lock.json"
    lock.write_text(json.dumps({"active": True, "sv": "sv-test", "pid": 1, "expires_t": time.time() + 600}), encoding="utf-8")
    target = ROOT / "tools/_freeze_audit_probe_should_not_exist.py"
    code = f"""
import importlib.util, sys
spec = importlib.util.spec_from_file_location('fa', r'{ROOT / "ops/hooks/freeze_audit.py"}')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
m.LOCK = r'{lock}'; m.install()
try:
    open(r'{target}', 'w').write('x'); print('WROTE')
except PermissionError as e:
    print('DENIED')
open(r'{tmp_path / "ok.txt"}', 'w').write('ok'); print('TMP_OK')
print(len(open(r'{ROOT / "pyproject.toml"}', encoding='utf-8').read()) > 0)
"""
    env = {k: v for k, v in os.environ.items() if k != "NS_FREEZE_EXEMPT"}
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60, env=env)
    assert "DENIED" in r.stdout and "TMP_OK" in r.stdout and "True" in r.stdout, r.stdout + r.stderr
    assert not target.exists()
