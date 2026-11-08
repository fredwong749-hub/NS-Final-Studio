"""R4（11-08）：gpu33:3 审图实例 :8877/:8878 无 pid 文件 → review_instances.sh scale 1 静默不停、rc 0（producer 记 ok 79 次），
三实例与同卡视频 ComfyUI :8191 互挤 OOM（ep03 6 镜 blocked、冒烟 G4“日志有 OOM”）。
修：stop_ports 无 pid 文件时按监听端口认回（只认命令行是 server.py 的）；scale 后活着的实例 > K → SCALE_EXCESS、rc ≠ 0。"""
from __future__ import annotations

import pytest

from tests.test_w_infra_1106 import BASH, _run_review


def _orphans(tmp, pids=("3972951", "3976738"), cmd=b"/x/vqa/venv/bin/python\x00-u\x00/x/vqa/server.py\x00"):
    st = tmp / "state"
    st.mkdir(parents=True, exist_ok=True)
    for port, pid in zip(("8877", "8878"), pids):
        (st / f"{port}.up").write_text("1")
        (st / f"{port}.loaded").write_text("1")
        d = tmp / "proc" / pid
        d.mkdir(parents=True, exist_ok=True)
        (d / "cmdline").write_bytes(cmd)
    return {"FAKE_SS_EXTRA": " ".join(f"{p}:{i}" for p, i in zip(("8877", "8878"), pids))}


@pytest.mark.skipif(not BASH, reason="需要 bash")
def test_scale_down_adopts_orphan_instances_by_port_and_reports_excess(tmp_path):
    env = _orphans(tmp_path)
    r = _run_review(tmp_path, ["scale", "1"], free_mib=30000, live=True, extra_env=env)
    out = r.stdout + r.stderr
    assert "ADOPT :8877 pid 3972951" in out and "ADOPT :8878 pid 3976738" in out, out   # 以前：无 pid 文件 = 什么都不做
    # 假 pid 杀不掉（不是真进程）→ 仍活 3 个 > 1：必须报出来，不能再 rc 0（以前 health 只判 ≥K）
    assert "SCALE_EXCESS" in out and r.returncode != 0, out


@pytest.mark.skipif(not BASH, reason="需要 bash")
def test_scale_down_never_touches_non_server_listener(tmp_path):
    env = _orphans(tmp_path, cmd=b"/usr/bin/python3\x00-u\x00/root/other/app.py\x00")
    r = _run_review(tmp_path, ["scale", "1"], free_mib=30000, live=True, extra_env=env)
    out = r.stdout + r.stderr
    assert "ADOPT :887" not in out and "NOT_OURS :8877" in out and "NOT_OURS :8878" in out, out
    assert "SCALE_EXCESS" in out and r.returncode != 0
