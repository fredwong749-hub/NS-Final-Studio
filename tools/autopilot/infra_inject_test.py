"""W7 注入测试（K-OPS-W05）：对一条隧道注入故障，量自动恢复用时。
  kill   杀掉持有 -L <port> 的 ssh（模拟断线；靠 tunnel*.sh 循环重连）
  freeze 挂起该 ssh 进程（模拟“进程活着、转发卡死”；只有看门狗能救）
结果追加到 data/qa/infra_inject.jsonl。用法：.venv/Scripts/python.exe tools/autopilot/infra_inject_test.py freeze 18288
"""
import ctypes, json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import infra_watchdog as W

def suspend(pid):
    h = ctypes.windll.kernel32.OpenProcess(0x0800, False, pid)   # PROCESS_SUSPEND_RESUME
    ctypes.windll.ntdll.NtSuspendProcess(h); ctypes.windll.kernel32.CloseHandle(h)

def main(mode, port, limit=300):
    port = int(port)
    assert W.probe(port), "注入前这条隧道本来就不通"
    pids = W.ssh_pids_for(port)
    t0 = time.time()
    for p in pids:
        W.kill(p) if mode == "kill" else suspend(p)
    down_seen = None
    while time.time() - t0 < limit:
        ok = W.probe(port, timeout=5) is not None
        if not ok and down_seen is None:
            down_seen = round(time.time() - t0, 1)
        if ok and down_seen is not None:
            break
        time.sleep(3)
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "mode": mode, "port": port, "pids": pids, "down_seen_s": down_seen,
           "recovered_s": round(time.time() - t0, 1) if W.probe(port) else None, "limit_s": limit}
    rec["pass"] = bool(rec["recovered_s"] is not None and rec["recovered_s"] <= 120)
    with open(W.ROOT / "data/qa/infra_inject.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(json.dumps(rec, ensure_ascii=False))
    if mode == "freeze":     # 被挂起的进程看门狗应已杀掉；兜底：还在就杀
        for p in pids:
            W.kill(p)

if __name__ == "__main__":
    main(*sys.argv[1:3])
