"""借道 / 临时挂道（DEBUG-RSI，K-OPS-Y04：会改生产状态的代码不许从 scratchpad 跑；替代 scratchpad 的 lend_any.py / hold_lane.py / lend_lane.sh）。

只改笔记本那份 partition（NETFIX 推送在同一把锁里三方合并后 30 s 内推到两台，K-OPS-N1x）；读写全程持 data/netfix/partition.lock。
字段：
  retired_lanes   被挡的道（派单层 hold 用）
  _lent_lanes     {道: {to, until, expires_at, client_prefix, by, at}}   借道；到期由 sweep() 清掉
  _temp_holds     {道: {why, at, by, expires_at}}                        临时挂道（滚动重启等）；到期由 sweep() 清掉
用法：
  .venv/Scripts/python.exe tools/debug/lanes.py lend <道> <借给谁> <分钟> <client 前缀> <by>
  .venv/Scripts/python.exe tools/debug/lanes.py hold <道> <分钟> <why>
  .venv/Scripts/python.exe tools/debug/lanes.py release <道>
  .venv/Scripts/python.exe tools/debug/lanes.py sweep [--idle]   # 清掉到期的借道 / 挂道；--idle 再收回借出后 10 分钟没人用的道
  .venv/Scripts/python.exe tools/debug/lanes.py repart <host> <集,逗号> --check-only   # K-OPS-E25 改分区前置检查
正式机制（NETFIX lent_lanes，到期自动失效）上线后本工具退役。
"""
from __future__ import annotations

import contextlib
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PART = ROOT / "data" / "state" / "netfix" / "partition.json"   # 12:39 起以新位置为准（旧位置 config/netfix/ 兼容期由 NETFIX 镜像）
LOCK = ROOT / "data" / "netfix" / "partition.lock"
AUDIT = ROOT / "data" / "debug" / "lane_loans.jsonl"
TS = "%Y-%m-%dT%H:%M:%S"


@contextlib.contextmanager
def partition_lock(timeout: float = 30, lock: Path | None = None):
    """和 NETFIX 推送共用的文件锁（Windows msvcrt / Linux fcntl）；拿不到超时抛 TimeoutError"""
    lp = lock or LOCK
    lp.parent.mkdir(parents=True, exist_ok=True)
    f = open(lp, "a+b")
    t0 = time.time()
    try:
        while True:
            try:
                if os.name == "nt":
                    import msvcrt
                    f.seek(0)
                    msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.time() - t0 > timeout:
                    raise TimeoutError(f"拿不到 {lp}")
                time.sleep(0.2)
        yield
    finally:
        try:
            if os.name == "nt":
                import msvcrt
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        f.close()


def _load(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _save(p: Path, d: dict) -> None:
    tmp = p.with_suffix(p.suffix + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def _audit(rec: dict, audit: Path | None = None) -> None:
    a = audit or AUDIT
    a.parent.mkdir(parents=True, exist_ok=True)
    with open(a, "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": time.strftime(TS), **rec}, ensure_ascii=False) + "\n")


def _mutate(fn, part: Path | None = None, lock: Path | None = None) -> dict:
    """测试传 part（临时文件）；生产不传：经 NETFIX dispatch.read_partition 读（先新后旧），
    只写新位置 data/state/netfix/partition.json（state_paths.write_state，ARCH_ROADMAP §10）"""
    if part is not None:
        with partition_lock(lock=lock or (part.parent / "partition.lock")):
            d = _load(part)
            fn(d)
            _save(part, d)
            return d
    sys.path.insert(0, str(ROOT / "tools" / "netfix"))
    import dispatch as D
    plock = D.partition_lock                    # 生产只用 NETFIX 那把锁（tools/netfix/dispatch.py class partition_lock），不留后备实现
    with plock(timeout=30):
        d = D.read_partition()
        fn(d)
        D.SP.write_state("netfix/partition", d)
        return d


def lend(lane: str, to: str, minutes: float, prefix: str, by: str, part: Path | None = None, now: float | None = None) -> dict:
    t = now or time.time()
    exp = time.strftime(TS, time.localtime(t + minutes * 60))

    def fn(d):
        rl = [x for x in d.get("retired_lanes") or [] if x != lane] + [lane]
        loans = dict(d.get("_lent_lanes") or {})
        loans[lane] = {"to": to, "until": exp, "expires_at": exp, "client_prefix": prefix, "by": by, "at": time.strftime(TS, time.localtime(t))}
        d["retired_lanes"], d["_lent_lanes"] = rl, loans
    d = _mutate(fn, part)
    _audit({"ev": "lend", "lane": lane, "to": to, "expires_at": exp, "client_prefix": prefix, "by": by},
           (part.parent / "lane_loans.jsonl") if part else None)
    return d


def hold(lane: str, minutes: float, why: str, part: Path | None = None, now: float | None = None) -> dict:
    t = now or time.time()
    exp = time.strftime(TS, time.localtime(t + minutes * 60))

    def fn(d):
        rl = [x for x in d.get("retired_lanes") or [] if x != lane] + [lane]
        th = dict(d.get("_temp_holds") or {})
        th[lane] = {"why": why, "at": time.strftime(TS, time.localtime(t)), "by": "DEBUG-RSI", "expires_at": exp}
        d["retired_lanes"], d["_temp_holds"] = rl, th
    return _mutate(fn, part)


def release(lane: str, part: Path | None = None) -> dict:
    def fn(d):
        d["retired_lanes"] = [x for x in d.get("retired_lanes") or [] if x != lane]
        for k in ("_lent_lanes", "_temp_holds"):
            m = dict(d.get(k) or {})
            m.pop(lane, None)
            d[k] = m
    d = _mutate(fn, part)
    _audit({"ev": "release", "lane": lane}, (part.parent / "lane_loans.jsonl") if part else None)
    return d


def sweep(part: Path | None = None, now: float | None = None) -> list[str]:
    """到期的借道 / 临时挂道自动清掉（含 retired_lanes 里对应的道）→ 清掉的道"""
    t_now = time.strftime(TS, time.localtime(now or time.time()))
    gone: list[str] = []

    def fn(d):
        for k in ("_lent_lanes", "_temp_holds"):
            m = dict(d.get(k) or {})
            for lane, rec in list(m.items()):
                exp = str(rec.get("expires_at") or rec.get("until") or "")[:19]
                if exp and exp < t_now:
                    m.pop(lane)
                    gone.append(lane)
            d[k] = m
        keep = set((d.get("_lent_lanes") or {})) | set((d.get("_temp_holds") or {}))
        d["retired_lanes"] = [x for x in d.get("retired_lanes") or [] if x not in gone or x in keep]
    _mutate(fn, part)
    for lane in gone:
        _audit({"ev": "expired_release", "lane": lane}, (part.parent / "lane_loans.jsonl") if part else None)
    return gone


IDLE_MIN = 10          # 借出去的道这么多分钟没人用（队列空、最近一单结束超过这么久）就自动收回（总调度 11-02 14:0x）


def _read_live() -> dict:
    sys.path.insert(0, str(ROOT / "tools" / "netfix"))
    import dispatch as D
    return D.read_partition()


def lane_port(lane: str) -> int:
    """gpu33:3 → 8191（每台 ComfyUI 一卡一道，8188 + 卡号）"""
    return 8188 + int(str(lane).split(":", 1)[1])


def probe_lane(lane: str) -> dict:
    """经 rssh 看这条道：{busy: 队列里有没有单, last_end: 最近一单结束的 epoch 秒 | None, ok}。失败 ok=False（不收回）"""
    host, port = lane.split(":", 1)[0], lane_port(lane)
    sys.path.insert(0, str(ROOT / "tools" / "netfix"))
    import rssh
    py = ("import json,sys,urllib.request as u\n"
          f"q=json.load(u.urlopen('http://127.0.0.1:{port}/queue',timeout=5))\n"
          f"h=json.load(u.urlopen('http://127.0.0.1:{port}/history?max_items=20',timeout=8))\n"
          "ts=[m[1].get('timestamp',0) for v in h.values() for m in (v.get('status') or {}).get('messages') or []"
          " if m[0] in ('execution_success','execution_error','execution_interrupted')]\n"
          "print(json.dumps({'busy':bool(q['queue_running'] or q['queue_pending']),'last_end':(max(ts)/1000 if ts else None)}))\n")
    r = rssh.run(host, "timeout 30 nice -n 10 python3 -", input=py.encode(), timeout=40)
    try:
        d = json.loads(r.stdout.decode("utf-8", "replace").strip().splitlines()[-1])
        return {**d, "ok": True}
    except (ValueError, IndexError):
        return {"ok": False}


def idle_sweep(idle_min: float = IDLE_MIN, probe=None, part: Path | None = None, now: float | None = None) -> list[str]:
    """借道（_lent_lanes）借出满 idle_min 分钟、队列空、最近一单结束也超过 idle_min 分钟 → 自动收回（记 idle_release）。
    探测失败的道不动；只看借道，不碰临时挂道（滚动重启等）"""
    t = now or time.time()
    probe = probe or probe_lane
    d = (_load(part) if part else _read_live())
    gone = []
    for lane, rec in (d.get("_lent_lanes") or {}).items():
        try:
            at = time.mktime(time.strptime(str(rec.get("at") or "")[:19], TS))
        except ValueError:
            at = 0
        if t - at < idle_min * 60:
            continue
        st = probe(lane)
        if not st.get("ok") or st.get("busy"):
            continue
        if st.get("last_end") and t - float(st["last_end"]) < idle_min * 60:
            continue
        gone.append(lane)
    for lane in gone:
        release(lane, part)
        _audit({"ev": "idle_release", "lane": lane, "idle_min": idle_min, "to": (d.get("_lent_lanes") or {}).get(lane, {}).get("to")},
               (part.parent / "lane_loans.jsonl") if part else None)
    return gone


def repart_check(host_eps: dict, have_takes: dict) -> list[str]:
    """K-OPS-E25：改分区前置检查。host_eps = {host: [新分到这台的集]}，have_takes = {host: {本机已有版本的集}}。
    新分到某台、但那台本地没有这一集版本、而别的机器有 → 会整集重做 → 返回问题（拒绝改）"""
    probs = []
    for host, eps in host_eps.items():
        others = set().union(*[v for h, v in have_takes.items() if h != host]) if len(have_takes) > 1 else set()
        for ep in eps:
            if ep not in have_takes.get(host, set()) and ep in others:
                probs.append(f"ep{int(ep):02d} 分给 {host}，但 {host} 本地没有这一集的版本、别的机器有 → 会整集重做（先同步 takes 再搬）")
    return probs


def main(argv=None) -> int:
    a = list(sys.argv[1:] if argv is None else argv)
    if not a:
        print(__doc__)
        return 2
    cmd = a[0]
    if cmd == "lend":
        lend(a[1], a[2], float(a[3]), a[4], a[5])
    elif cmd == "hold":
        hold(a[1], float(a[2]), a[3])
    elif cmd == "release":
        release(a[1])
    elif cmd == "sweep":
        print(json.dumps({"released": sweep(), "idle_released": idle_sweep() if "--idle" in a else None}, ensure_ascii=False))
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
