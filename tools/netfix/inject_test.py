"""监管进程注入测试（NETFIX 11-01；K-OPS-N01 验收：跳板一恢复，60 s 内 6 条全部恢复）。

不碰生产隧道：另起一个测试监管实例（tag 前缀 nsnetfixtest，本机口 28188/28189/28191 → gpu33，28288/28289/28290 → gpu36），
跳板换成本机假跳板 127.0.0.1:19999（真转发到 sz194:19422，可以“断”：关监听 + 冻结已有连接，和真断网一样表现为超时）。
场景：基线 → 杀 ssh → 挂起 ssh（NtSuspendProcess）→ 孤儿 ssh 占口 → 跳板断 90 s 再恢复。每段记恢复秒数。
结果：data/netfix/inject/<时间>.json + 同名 .log。
  .venv/Scripts/python.exe tools/netfix/inject_test.py [--down-s 90]
"""
from __future__ import annotations

import argparse
import ctypes
import json
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tunnel_supervisor as TS  # noqa: E402

ROOT = TS.ROOT
OUT = ROOT / "data/netfix/inject"
RELAY = ("sz194.instameta.org", 19422)
FAKE = ("127.0.0.1", 19999)


class FakeRelay:
    def __init__(self):
        self.up = False
        self.ls = None
        self.conns: list[socket.socket] = []
        self.frozen = threading.Event()

    def start(self):
        self.ls = socket.socket()
        self.ls.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.ls.bind(FAKE)
        self.ls.listen(16)
        self.up = True
        self.frozen.clear()
        threading.Thread(target=self._accept, args=(self.ls,), daemon=True).start()

    def _accept(self, ls):
        while True:
            try:
                c, _ = ls.accept()
            except OSError:
                return
            try:
                u = socket.create_connection(RELAY, timeout=20)
            except OSError:
                c.close()
                continue
            u.settimeout(None)
            self.conns += [c, u]
            for a, b in ((c, u), (u, c)):
                threading.Thread(target=self._pump, args=(a, b), daemon=True).start()

    def _pump(self, a, b):
        while True:
            try:
                d = a.recv(65536)
            except OSError:
                break
            if not d:
                break
            while self.frozen.is_set():          # 跳板断：数据不再转发（连接挂着 = 对端看来是超时）
                time.sleep(0.5)
                if not self.up:
                    pass
            try:
                b.sendall(d)
            except OSError:
                break
        for s in (a, b):
            try:
                s.close()
            except OSError:
                pass

    def down(self):
        self.up = False
        self.frozen.set()
        try:
            self.ls.close()
        except OSError:
            pass

    def restore(self):
        for s in self.conns:                     # 断网期间的旧连接作废（真网络恢复后它们也早被 ServerAlive 判死）
            try:
                s.close()
            except OSError:
                pass
        self.conns = []
        self.start()


def suspend(pid: int) -> bool:
    k, nt = ctypes.windll.kernel32, ctypes.windll.ntdll
    h = k.OpenProcess(0x0800, False, pid)
    if not h:
        return False
    try:
        return nt.NtSuspendProcess(h) == 0
    finally:
        k.CloseHandle(h)


def test_conf(tmp: Path) -> Path:
    c = TS.jl(TS.CONF)
    kh = subprocess.run(["ssh-keygen", "-F", f"[{RELAY[0]}]:{RELAY[1]}"], capture_output=True, text=True).stdout
    keys = [ln.split(None, 1)[1] for ln in kh.splitlines() if ln and not ln.startswith("#")]
    khf = Path(TS.os.environ.get("TEMP", "C:/Windows/Temp")) / "nsnetfix_known_hosts_fake"   # 路径不能有空格（ProxyCommand 经 shell）
    khf.write_text("".join(f"[127.0.0.1]:{FAKE[1]} {k}\n" for k in keys))
    c["tag_prefix"] = "nsnetfixtest"
    c["legacy_loops"] = []
    c["relay"] = {"check": list(FAKE),
                  "proxy_cmd": ("/usr/bin/ssh -o BatchMode=yes -o ConnectTimeout=20 -o ServerAliveInterval=10 -o ServerAliveCountMax=3 "
                                f"-o HostName=127.0.0.1 -o Port={FAKE[1]} -o UserKnownHostsFile={khf.as_posix()} "
                                "-o Tag=nsnetfix-proxy -W %h:%p 194relay")}
    c["hosts"] = {"gpu33": {"forwards": [[28188, 8188], [28189, 8189], [28191, 8191]], "probe_http": [28188, 28189, 28191]},
                  "gpu36": {"forwards": [[28288, 8188], [28289, 8189], [28290, 8190]], "probe_http": [28288, 28289, 28290]}}
    p = tmp / "tunnels_test.json"
    p.write_text(json.dumps(c, ensure_ascii=False, indent=1), encoding="utf-8")
    return p


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--down-s", type=int, default=90)
    a = ap.parse_args()
    stamp = time.strftime("%Y%m%d_%H%M%S")
    tmp = OUT / stamp
    tmp.mkdir(parents=True, exist_ok=True)
    logf = open(OUT / f"{stamp}.log", "a", encoding="utf-8")

    def say(*x):
        ln = time.strftime("%H:%M:%S ") + " ".join(str(v) for v in x)
        print(ln, flush=True)
        logf.write(ln + "\n")
        logf.flush()

    fr = FakeRelay()
    fr.start()
    sup = TS.Supervisor(test_conf(tmp), tmp)
    th = threading.Thread(target=sup.serve, daemon=True)
    th.start()
    res = {"stamp": stamp, "steps": []}

    def n_up():
        return sum(1 for st in sup.hosts.values() for p in st["ports"].values() if p.get("ok"))

    def wait_all(label, limit=240, t0=None, changed=None):
        """changed = (host, 旧 pid)：必须换成新 ssh 才算恢复（否则状态还没刷新就误判“0 秒恢复”）；t0 = 注入时刻"""
        t0 = t0 or time.time()
        while time.time() - t0 < limit:
            if changed and sup.hosts[changed[0]]["pid"] in (None, changed[1]):
                time.sleep(1)
                continue
            if n_up() == 6 and all(st["state"] == "up" for st in sup.hosts.values()):
                dt = round(time.time() - t0, 1)
                say(f"[{label}] 6/6 up in {dt}s", {h: st["pid"] for h, st in sup.hosts.items()})
                res["steps"].append({"step": label, "ok": True, "recover_s": dt})
                return dt
            time.sleep(1)
        say(f"[{label}] FAIL: {n_up()}/6 after {limit}s", {h: (st['state'], st['ports']) for h, st in sup.hosts.items()})
        res["steps"].append({"step": label, "ok": False, "recover_s": None, "up": n_up()})
        return None

    try:
        wait_all("baseline")
        # 1) 杀 ssh
        pid = sup.hosts["gpu36"]["pid"]
        ti = time.time()
        TS.kill(pid)
        say("inject kill ssh gpu36", pid)
        wait_all("kill_ssh", t0=ti, changed=("gpu36", pid))
        # 2) 挂起 ssh（活着但不干活）
        pid = sup.hosts["gpu33"]["pid"]
        ti = time.time()
        say("inject suspend ssh gpu33", pid, suspend(pid))
        wait_all("suspend_ssh", t0=ti, changed=("gpu33", pid))
        # 3) 孤儿 ssh 占口：杀掉监管的 gpu36 ssh，同时手动起一条不带 Tag 的 -L 28288/28289/28290（模拟 22:09 手动那条）
        pid = sup.hosts["gpu36"]["pid"]
        orphan = subprocess.Popen([sup.c["ssh_exe"], "-N", "-o", "BatchMode=yes", "-o", "ProxyCommand=" + sup.c["relay"]["proxy_cmd"],
                                   "-L", "28288:127.0.0.1:8188", "-L", "28289:127.0.0.1:8189", "-L", "28290:127.0.0.1:8190", "gpu36"],
                                  stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=TS.NOWIN)
        ti = time.time()
        time.sleep(8)                         # 让孤儿先占上口（模拟 22:09 手动那条已经在跑）
        TS.kill(pid)
        say("inject orphan ssh", orphan.pid, "+ kill supervised gpu36", pid)
        dt = wait_all("orphan_adopt", t0=ti, changed=("gpu36", pid))
        res["steps"][-1]["orphan_alive_after"] = orphan.poll() is None
        say("orphan still alive?", orphan.poll() is None)
        if orphan.poll() is None:
            orphan.kill()
        # 4) 跳板断
        fr.down()
        t_down = time.time()
        say(f"inject relay DOWN for {a.down_s}s")
        while time.time() - t_down < a.down_s:
            time.sleep(5)
        states = {h: st["state"] for h, st in sup.hosts.items()}
        say("states during outage", states, "spawned during outage =",
            [ln for ln in (tmp / "supervisor.log").read_text(encoding="utf-8").splitlines() if "SPAWN" in ln and ln[:19] > TS.iso(t_down + 35)])
        res["steps"].append({"step": "relay_down_states", "states": states})
        ti = time.time()
        fr.restore()
        say("relay RESTORED")
        dt = wait_all("relay_restore", limit=180, t0=ti)
        res["acceptance_relay_restore_le_60s"] = bool(dt is not None and dt <= 60)
    finally:
        (tmp / "STOP").write_text("x")
        time.sleep(6)
        for st in sup.hosts.values():
            if st["pid"]:
                TS.kill(st["pid"])
        res["supervisor_log"] = str(tmp / "supervisor.log")
        TS.js(OUT / f"{stamp}.json", res)
        say("RESULT", json.dumps(res, ensure_ascii=False))
    return 0 if all(s.get("ok", True) for s in res["steps"]) and res.get("acceptance_relay_restore_le_60s") else 1


if __name__ == "__main__":
    sys.exit(main())
