"""传输流水线：笔记本侧 puller（NETFIX r2，总调度 fredw-2b 派；项目方 01:0x 原话：“在 GPU 那边写一个队列，慢慢地传输到这台电脑来……
Rendering 是一条 pipeline；生成完后的传图是另外一条 pipeline，不断地跟这台笔记本做长连接”；规则 K-OPS-N09）。

服务器侧（FACTORY 写）：/root/work/fredw/offline_20261101/outbox/<id>/{files/<rel>, manifest.json, .done}
  manifest = {"id","host","obj","event","created","files":[{"rel","sha256","size","prio"}]}；prio 0 json / 1 缩略图 / 2 原图 / 3 视频（按需）
本进程（单实例，常驻）：
  1) 经监管进程托管的常驻主连接（rssh，底座隧道，不新建跳板握手）一次列出两台 outbox 里“有 .done、没 .acked”的目录 + manifest（一条命令）；
  2) 按优先级批量拉（P0 → P1 → P2；P3 只拉 data/netfix/fetch_requests.jsonl 里请求过的），每批 tar ≤ BATCH_MB；
  3) 落到 data/_offline_pull/<host>/<id>/<rel>，核对 sha256（不符 = 本批作废、下轮重拉）；
  4) 逐文件 ops/offline/merge_pull.merge_file(host, rel, src, att) 并回（按集归属、按对象 / 按版本合并、不覆盖本地更新），一批后 flush_attempts；
  5) 一个目录的 P0–P2 都并好 → 批量 ack（服务器端建 .acked）；本地 data/netfix/puller_state.json 记已 ack 的 id（水位），重启从水位继续。
跳板断：主连接不在 → rssh 立刻失败，本轮跳过，outbox 在服务器堆着；恢复后自动追上。0 丢失（不 ack 不删）、0 重复（已 ack 的不再拉，merge 幂等）。
指标写 data/netfix/puller_status.json（监管进程并进 net_status.transfer）：每台积压条数、积压字节、最近拉取吞吐、产出→落地延迟 p50/p90。

  .venv/Scripts/python.exe tools/netfix/puller.py serve        # 常驻（laptop_autostart / 计划任务 ensure）
  .venv/Scripts/python.exe tools/netfix/puller.py once         # 跑一轮
  .venv/Scripts/python.exe tools/netfix/puller.py request <host> <rel>   # P3 按需插队（界面 /api/fetch 调这个）
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
import tarfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import rssh  # noqa: E402

OFF = "/root/work/fredw/offline_20261101"
OUTBOX = os.environ.get("NETFIX_OUTBOX", OFF + "/outbox")   # 测试可换到独立目录
HOSTS = ("gpu33", "gpu36")
STATE = Path(os.environ.get("NETFIX_PULLER_STATE", ROOT / "data/netfix/puller_state.json"))
STATUS = Path(os.environ.get("NETFIX_PULLER_STATUS", ROOT / "data/netfix/puller_status.json"))
REQ = ROOT / "data/netfix/fetch_requests.jsonl"
STAGE = ROOT / "data/_offline_pull"
LOG = ROOT / "data/netfix/puller.log"
BATCH_MB = 8
LIST_MAX = 200
TICK_S = 10


def log(*a):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(time.strftime("%Y-%m-%dT%H:%M:%S ") + " ".join(str(x) for x in a) + "\n")


def jl(p, d=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return d


def js(p: Path, d) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


LIST_PY = r'''
import json, os, sys
B = sys.argv[1]; MAX = int(sys.argv[2])
out = []
try:
    names = sorted(os.listdir(B))
except OSError:
    names = []
for n in names:
    d = os.path.join(B, n)
    if not os.path.isfile(os.path.join(d, ".done")) or os.path.exists(os.path.join(d, ".acked")):
        continue
    try:
        m = json.load(open(os.path.join(d, "manifest.json"), encoding="utf-8"))
    except Exception as e:
        m = {"id": n, "error": repr(e)[:120], "files": []}
    m["id"] = n
    out.append(m)
    if len(out) >= MAX:
        break
print(json.dumps(out))
'''


def remote(host: str, cmd: str, data: bytes | None = None, timeout: float = 600):
    return rssh.run(host, cmd, input=data, timeout=timeout)


def list_outbox(host: str) -> list[dict] | None:
    import base64
    code = base64.b64encode(LIST_PY.encode()).decode()
    r = remote(host, f"python3 -c \"import base64;exec(base64.b64decode('{code}'))\" {OUTBOX} {LIST_MAX}", timeout=120)
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout.decode("utf-8", "replace").strip().splitlines()[-1])
    except (ValueError, IndexError):
        return None


def requested() -> set[tuple[str, str]]:
    out = set()
    try:
        for ln in REQ.read_text(encoding="utf-8").splitlines():
            d = json.loads(ln)
            out.add((d["host"], d["rel"]))
    except (OSError, ValueError, KeyError):
        pass
    return out


def plan(host: str, items: list[dict], done_files: set) -> list[tuple[int, str, dict]]:
    """→ [(prio, item_id, file)]：未拉的文件按优先级排；P3 只收按需请求过的"""
    req = requested()
    out = []
    for it in items:
        for f in it.get("files") or []:
            key = (it["id"], f["rel"])
            if key in done_files:
                continue
            pr = int(f.get("prio", 2))
            if pr >= 3 and (host, f["rel"]) not in req:
                continue
            out.append((pr, it["id"], f))
    out.sort(key=lambda x: (x[0], x[1]))
    return out


def fetch_batch(host: str, batch: list[tuple[int, str, dict]]) -> list[tuple[str, dict, Path]]:
    """一批 tar 拉回 → 核对 sha → [(item_id, file, 本地暂存路径)]；不符的丢弃（下轮重拉）"""
    paths = [f"{iid}/files/{f['rel']}" for _p, iid, f in batch]
    r = remote(host, f"cd {OUTBOX} && tar cf - -T - 2>/dev/null; true", data="\n".join(paths).encode(), timeout=1800)
    got = []
    want = {f"{iid}/files/{f['rel']}": (iid, f) for _p, iid, f in batch}
    try:
        with tarfile.open(fileobj=io.BytesIO(r.stdout)) as tf:
            for m in tf.getmembers():
                if not m.isfile() or ".." in m.name or m.name.startswith("/") or m.name not in want:
                    continue
                data = tf.extractfile(m).read()
                iid, f = want[m.name]
                if hashlib.sha256(data).hexdigest() != f.get("sha256") or len(data) != int(f.get("size", len(data))):
                    log("SHA mismatch", host, m.name)
                    continue
                dst = STAGE / host / iid / f["rel"]
                dst.parent.mkdir(parents=True, exist_ok=True)
                tmp = dst.with_suffix(dst.suffix + ".part")
                tmp.write_bytes(data)
                os.replace(tmp, dst)
                got.append((iid, f, dst))
    except tarfile.TarError as e:
        log("tar 读不全（断连）", host, repr(e)[:120], "→ 下轮重拉")
    return got


def merge(host: str, got: list[tuple[str, dict, Path]]) -> dict:
    sys.path.insert(0, str(ROOT / "ops/offline"))
    import merge_pull as MP
    att: dict = {}
    res = {}
    for iid, f, src in got:
        rel = f["rel"]
        if rel.endswith(".thumb.jpg"):                 # 缩略图：只落到本地缩略图目录，不进 data 主文件
            dst = ROOT / "data/netfix/thumbs" / host / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            os.replace(src, dst)
            res[(iid, rel)] = "thumb"
            continue
        try:
            res[(iid, rel)] = MP.merge_file(host, rel, src, att)
        except Exception as e:  # noqa: BLE001
            res[(iid, rel)] = f"error:{repr(e)[:120]}"
    if att:
        MP.flush_attempts(att)
    return res


def ack(host: str, ids: list[str]) -> bool:
    if not ids:
        return True
    r = remote(host, f"cd {OUTBOX} && while read d; do [ -d \"$d\" ] && touch \"$d/.acked\"; done", data=("\n".join(ids) + "\n").encode(), timeout=120)   # 末行要有换行，否则 read 读不到最后一个
    return r.returncode == 0


def tick(state: dict) -> dict:
    stats = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "t": time.time(), "hosts": {}}
    for host in HOSTS:
        hs = state.setdefault(host, {"acked": [], "files_done": [], "lat": []})
        items = list_outbox(host)
        if items is None:
            stats["hosts"][host] = {"reachable": False, **state.get("_last_stats", {}).get(host, {})}
            continue
        acked = set(hs["acked"])
        items = [it for it in items if it["id"] not in acked]
        done_files = {tuple(x) for x in hs["files_done"]}
        todo = plan(host, items, done_files)
        backlog_bytes = sum(int(f.get("size", 0)) for _p, _i, f in todo)
        t0, moved = time.time(), 0
        cur, cur_bytes, batches = [], 0, []
        for x in todo:
            cur.append(x)
            cur_bytes += int(x[2].get("size", 0))
            if cur_bytes >= BATCH_MB * 1e6:
                batches.append(cur)
                cur, cur_bytes = [], 0
        if cur:
            batches.append(cur)
        for b in batches[:6]:                          # 一拍最多 6 批，留时间给别的主机 / 心跳
            got = fetch_batch(host, b)
            res = merge(host, got)
            for (iid, rel), act in res.items():
                if not str(act).startswith("error"):
                    hs["files_done"].append([iid, rel])
                    moved += next(int(f.get("size", 0)) for _p, i, f in b if i == iid and f["rel"] == rel)
            log("batch", host, len(b), "files →", len(got), "ok", {k[1][-40:]: v for k, v in list(res.items())[:5]})
        done_files = {tuple(x) for x in hs["files_done"]}
        ready_ack = []
        for it in items:                               # P0–P2 全部到位（P3 不等）→ ack
            need = [f for f in it.get("files") or [] if int(f.get("prio", 2)) < 3]
            if all((it["id"], f["rel"]) in done_files for f in need):
                ready_ack.append(it["id"])
                try:
                    created = it.get("created")
                    from datetime import datetime
                    ct = float(created) if isinstance(created, (int, float)) else datetime.fromisoformat(str(created)).timestamp()   # FACTORY 写带时区 ISO（+09:00）
                    hs["lat"] = (hs["lat"] + [round(time.time() - ct, 1)])[-200:]
                except (ValueError, TypeError):
                    pass
        if ack(host, ready_ack):
            hs["acked"] = (hs["acked"] + ready_ack)[-20000:]
            ids = set(ready_ack)
            hs["files_done"] = [x for x in hs["files_done"] if x[0] not in ids]
        lat = sorted(hs["lat"])
        dt = max(time.time() - t0, 0.001)
        stats["hosts"][host] = {"reachable": True, "backlog_items": len(items) - len(ready_ack), "backlog_bytes": backlog_bytes - moved,
                                "moved_bytes": moved, "throughput_kBps": round(moved / dt / 1024, 1) if moved else 0,
                                "latency_p50_s": lat[len(lat) // 2] if lat else None,
                                "latency_p90_s": lat[int(0.9 * (len(lat) - 1))] if lat else None, "acked_total": len(hs["acked"])}
    state["_last_stats"] = stats["hosts"]
    js(STATUS, stats)
    return state


def lock():
    import msvcrt
    f = open(ROOT / "data/netfix/puller.lock", "a+")
    try:
        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        f.close()
        return None
    return f


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["serve", "once", "request", "status"])
    ap.add_argument("args", nargs="*")
    a = ap.parse_args(argv)
    if a.cmd == "request":
        host, rel = a.args[0], a.args[1]
        REQ.parent.mkdir(parents=True, exist_ok=True)
        with open(REQ, "a", encoding="utf-8") as f:
            f.write(json.dumps({"host": host, "rel": rel, "at": time.time()}) + "\n")
        print("queued", host, rel)
        return 0
    if a.cmd == "status":
        print(json.dumps(jl(STATUS, {}), ensure_ascii=False, indent=1))
        return 0
    state = jl(STATE, {}) or {}
    if a.cmd == "once":
        state = tick(state)
        js(STATE, state)
        print(json.dumps(jl(STATUS, {}), ensure_ascii=False))
        return 0
    lk = lock()
    if lk is None:
        print("already running")
        return 0
    log("START", os.getpid())
    while True:
        try:
            state = tick(state)
            js(STATE, state)
        except Exception as e:  # noqa: BLE001
            log("tick error", repr(e)[:300])
        time.sleep(TICK_S)


if __name__ == "__main__":
    sys.exit(main())
