"""resident_guard.ps1 守卫（ISS-1103-172950-44d8）：兜底拉起 autoflow_resident；只读 ps1 文本。"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
G = (ROOT / "ops/autostart/resident_guard.ps1").read_text(encoding="utf-8")
R = (ROOT / "ops/restart_autoflow.ps1").read_text(encoding="utf-8-sig")


def test_guard_checks_autoflow_heartbeat_and_lock():
    assert r"data\factory\autoflow_resident.json" in G
    assert r"data\factory\autoflow_resident.lock" in G
    assert ".at" in G and "TotalMinutes -le 3" in G
    assert "Get-Process -Id $lp" in G


def test_guard_calls_restart_script_once_per_round():
    assert r"ops\restart_autoflow.ps1" in G
    body = G.split("while ($true) {", 1)[1]
    assert body.count("AutoflowGuard") == 1
    assert "$afNext" in G
    assert "resident_guard.log" in G


def test_guard_never_kills_autoflow_by_command_line():
    assert "autoflow_resident" not in G.split("$match =", 1)[1].splitlines()[0]
    assert "Where-Object" in G and "autoflow_resident\\.py" not in G


def test_restart_script_only_stops_lock_pid():
    assert "只停锁里记的 pid" in R
    assert "taskkill /PID $old /T /F" in R
    assert "CommandLine" not in R.replace("不再按命令行匹配杀进程", "")
