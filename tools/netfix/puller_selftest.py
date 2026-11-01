"""puller 端到端自检（NETFIX r2，K-OPS-N09）：在 gpu36 上建独立测试 outbox（不碰 FACTORY 的真 outbox），
3 个结果：P0 json、P2 1 MB 二进制、P3 视频占位（不请求不拉）。跑 puller 一轮 → 核对本地 sha、服务器 .acked；
再跑一轮 → 0 重复；按需请求 P3 → 拉到。可选 --outage：先建 2 个结果 → 把命令主连接全停 60 s（模拟跳板断）期间服务器再建 2 个 →
恢复后 puller 追上，4 个全到、0 丢 0 重。结果 data/netfix/puller_selftest.json。
  .venv/Scripts/python.exe tools/netfix/puller_selftest.py
"""
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TB = "/root/work/fredw/netfix/outbox_selftest"
os.environ["NETFIX_OUTBOX"] = TB
os.environ["NETFIX_PULLER_STATE"] = str(ROOT / "data/netfix/puller_selftest_state.json")
os.environ["NETFIX_PULLER_STATUS"] = str(ROOT / "data/netfix/puller_selftest_status.json")
sys.path.insert(0, str(Path(__file__).resolve().parent))
import puller as P  # noqa: E402
import rssh  # noqa: E402

MAKE = r'''
import hashlib, json, os, sys, time
B, n0, n = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
for i in range(n0, n0 + n):
    d = os.path.join(B, "20261102T000000_%06d_selftest_take" % i)
    os.makedirs(d + "/files/data/netfix/selftest", exist_ok=True)
    files = []
    for rel, data, pr in (("data/netfix/selftest/a%d.json" % i, json.dumps({"i": i, "t": time.time()}).encode(), 0),
                          ("data/netfix/selftest/b%d.bin" % i, os.urandom(1 << 20), 2),
                          ("data/netfix/selftest/c%d.mp4" % i, os.urandom(4096), 3)):
        open(d + "/files/" + rel, "wb").write(data)
        files.append({"rel": rel, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data), "prio": pr})
    json.dump({"id": os.path.basename(d), "host": "gpu36", "obj": "selftest:%d" % i, "event": "take", "created": time.time(), "files": files},
              open(d + "/manifest.json", "w"))
    open(d + "/.done", "w").close()
print("made", n)
'''


def rsh(cmd, data=None):
    r = rssh.run("gpu36", cmd, input=data, timeout=300)
    return r.returncode, r.stdout.decode("utf-8", "replace")


def make(n0, n):
    import base64
    code = base64.b64encode(MAKE.encode()).decode()
    return rsh(f"python3 -c \"import base64;exec(base64.b64decode('{code}'))\" {TB} {n0} {n}")


def local_ok(i):
    a = ROOT / f"data/netfix/selftest/a{i}.json"
    b = ROOT / f"data/netfix/selftest/b{i}.bin"
    return a.exists() and b.exists() and b.stat().st_size == 1 << 20


def main():
    res = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "steps": []}
    rsh(f"rm -rf {TB}; mkdir -p {TB}")
    for f in (P.STATE, P.STATUS):
        Path(f).unlink(missing_ok=True)
    make(0, 2)
    t = time.time()
    st = P.tick({})
    P.js(P.STATE, st)
    ok = all(local_ok(i) for i in range(2))
    rc, acked = rsh(f"ls {TB}/*/.acked 2>/dev/null | wc -l")
    res["steps"].append({"step": "pull 2", "ok": ok and acked.strip() == "2", "s": round(time.time() - t, 1), "acked": acked.strip(),
                         "status": P.jl(P.STATUS)})
    before = P.LOG.read_text(encoding="utf-8").count("batch gpu36")
    st = P.tick(st)
    P.js(P.STATE, st)
    after = P.LOG.read_text(encoding="utf-8").count("batch gpu36")
    res["steps"].append({"step": "rerun no dup", "ok": after == before})
    mp4 = ROOT / "data/netfix/selftest/c0.mp4"
    res["steps"].append({"step": "P3 not pulled unrequested", "ok": not mp4.exists()})
    if "--outage" in sys.argv:
        make(2, 2)
        os.environ["NS_SSH_SHIM"] = "off"            # 模拟断：rssh 不复用 → 走直连 ssh；再把主机名指向不可达，等价跳板断
        orig = rssh.SOCK.copy()
        rssh.SOCK.clear()                            # rewrite 不认 → run 退回直连 "ssh gpu36"
        saved = P.remote
        P.remote = lambda host, cmd, data=None, timeout=600: subprocess.CompletedProcess([], 255, b"", b"simulated outage")
        st = P.tick(st)
        res["steps"].append({"step": "outage tick (no crash, nothing lost)", "ok": not local_ok(2), "status": P.jl(P.STATUS)})
        P.remote = saved
        rssh.SOCK.update(orig)
        os.environ.pop("NS_SSH_SHIM", None)
        t = time.time()
        st = P.tick(st)
        P.js(P.STATE, st)
        rc, acked = rsh(f"ls {TB}/*/.acked 2>/dev/null | wc -l")
        res["steps"].append({"step": "recover catch-up", "ok": all(local_ok(i) for i in range(4)) and acked.strip() == "4",
                             "s": round(time.time() - t, 1)})
    rsh(f"rm -rf {TB}")
    res["ok"] = all(s["ok"] for s in res["steps"])
    P.js(ROOT / "data/netfix/puller_selftest.json", res)
    print(json.dumps(res, ensure_ascii=False)[:1500])
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
