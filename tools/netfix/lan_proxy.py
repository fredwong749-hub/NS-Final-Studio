#!/usr/bin/env python3
"""gpu36 看图服务的内网入口（NETFIX 11-01，总调度 fredw-2b 派；规则 K-OPS-N03）。

起因：gpu33 → 10.0.0.36:8870 Connection refused——gpu36 的 tools/vqa/server.py 只听 127.0.0.1，gpu33 出的首帧没法看图（卡在 Q9 未测）。
不重启看图服务（模型常驻、正被用），在 gpu36 上加这个小转发：
  只监听内网地址 10.0.0.36:8870（gpu36 只有 eno3 10.0.0.36/21 一块网卡，没有公网地址；11-01 22:2x `ip -4 addr` 实测），
  只接受白名单来源（默认只有 10.0.0.33 = gpu33；其它来源（包括跳板）直接断开并记日志），转给 127.0.0.1:8870。
  另加 iptables：8870 只放行 10.0.0.33（start 时幂等加上，见 lan_proxy.sh）。
两台服务器之间不配 ssh 互信（项目方刻意不配）——这里只开一个 HTTP 口，没有登录能力。图片仍只在自家机器之间走（K-REV-V01）。
用法（gpu36）：python3 lan_proxy.py [--bind 10.0.0.36] [--port 8870] [--allow 10.0.0.33] [--target 127.0.0.1:8870]
"""
import argparse
import asyncio
import time

LOG = "/root/work/fredw/netfix/lan_proxy.log"


def log(*a):
    try:
        with open(LOG, "a") as f:
            f.write(time.strftime("%F %T ") + " ".join(str(x) for x in a) + "\n")
    except OSError:
        pass


async def pipe(r, w):
    try:
        while True:
            d = await r.read(65536)
            if not d:
                break
            w.write(d)
            await w.drain()
    except (ConnectionError, OSError):
        pass
    finally:
        try:
            w.close()
        except Exception:  # noqa: BLE001
            pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bind", default="10.0.0.36")
    ap.add_argument("--port", type=int, default=8870)
    ap.add_argument("--allow", default="10.0.0.33")
    ap.add_argument("--target", default="127.0.0.1:8870")
    a = ap.parse_args()
    allow = set(a.allow.split(","))
    th, tp = a.target.rsplit(":", 1)

    async def handle(r, w):
        peer = (w.get_extra_info("peername") or ("?",))[0]
        if peer not in allow:
            log("DENY", peer)
            w.close()
            return
        try:
            tr, tw = await asyncio.open_connection(th, int(tp))
        except OSError as e:
            log("target down", e)
            w.close()
            return
        await asyncio.gather(pipe(r, tw), pipe(tr, w))

    async def run():
        srv = await asyncio.start_server(handle, a.bind, a.port)
        log("listen", a.bind, a.port, "allow", sorted(allow), "->", a.target)
        async with srv:
            await srv.serve_forever()

    asyncio.run(run())


if __name__ == "__main__":
    main()
