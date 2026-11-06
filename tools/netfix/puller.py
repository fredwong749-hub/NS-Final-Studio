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


MIRROR_FILES = ["data/producer/registry.json"]   # DEBUG-RSI 16:4x：界面“排第几、几点完成”（queue_eta.py）要服务器实况，每 MIRROR_EVERY_S 镜像一次
MIRROR_EVERY_S = 90


def mirror(state: dict) -> dict:
    """小文件镜像：经命令主连接 cat（不新开 ssh），写 data/_offline_pull/<host>/<rel>（原子）；不走 merge（只读视图，不并回 data/）"""
    out = {}
    if time.time() - state.get("_mirror_t", 0) < MIRROR_EVERY_S:
        return state.get("_mirror_last", {})
    state["_mirror_t"] = time.time()
    rels = list(MIRROR_FILES)
    for run, rec in ((_runs().get("runs") or {}).items()):          # L-125：每个在用的 run 各自的 registry 也镜像（按 run 推路径，不写死）
        if (rec or {}).get("status") in FROZEN_STATUS:
            continue
        legacy = legacy_run()
        rel = "data/producer/registry.json" if run == legacy else f"data/producer/runs/{run}/registry.json"
        if rel not in rels:
            rels.append(rel)
    for host in HOSTS:
        for rel in rels:
            r = remote(host, f"cat {OFF}/repo/{rel}", timeout=60)
            ok = r.returncode == 0 and r.stdout[:1] in (b"{", b"[")
            if ok:
                dst = STAGE / host / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                tmp = dst.with_suffix(dst.suffix + ".part")
                tmp.write_bytes(r.stdout)
                os.replace(tmp, dst)
            out[f"{host}:{rel}"] = {"ok": ok, "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "bytes": len(r.stdout) if ok else 0,
                                    "rc": r.returncode}
    state["_mirror_last"] = out
    return out





SCAN_EVERY_S = 300
SCAN_PY = r"""
import json, os, sys
R, since = sys.argv[1], float(sys.argv[2])
out = {"changed": [], "summary": {}}
for base, dirs, files in os.walk(os.path.join(R, "data/renders")):
    if "takes.json" not in files or "/_" in base.replace(os.sep, "/"):
        continue
    f = os.path.join(base, "takes.json")
    rel = os.path.relpath(f, R).replace(os.sep, "/")
    try:
        st = os.stat(f)
        d = json.load(open(f, encoding="utf-8"))
    except Exception:
        continue
    if st.st_mtime > since:
        out["changed"].append(rel)
    out["summary"][rel] = {"active": d.get("active") or {},
                           "rejected": sorted([t.get("stage"), t.get("n")] for t in d.get("takes") or [] if t.get("rejected"))}
print(json.dumps(out))
"""


def takes_scan(state: dict) -> dict:
    """服务器上直接改的 takes.json（作废 / 清空当前版等，不经 outbox）每 SCAN_EVERY_S 拉回并按 stage 归属合并；
    同时比对两边每镜“本台负责的 stage”的当前版和作废集合，不一致 → takes_drift（SENTINEL 探针读 puller_status）"""
    import base64
    import re
    if time.time() - state.get("_scan_t", 0) < SCAN_EVERY_S:
        return state.get("_scan_last", {})
    state["_scan_t"] = time.time()
    sys.path.insert(0, str(ROOT / "ops/offline"))
    import merge_pull as MP
    res = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "merged": {}, "drift": []}
    code = base64.b64encode(SCAN_PY.encode()).decode()
    for host in HOSTS:
        since = state.get(f"_scan_since_{host}")
        first = since is None                      # 第一次只建基线、只做一致性比对，不批量合并历史改动（避免一上线就全量并回）
        since = time.time() if first else since
        t_start = time.time() - 30
        r = remote(host, f"python3 -c \"import base64;exec(base64.b64decode('{code}'))\" {OFF}/repo {since}", timeout=120)
        if r.returncode != 0:
            res["merged"][host] = f"rc={r.returncode}"
            continue
        try:
            info = json.loads(r.stdout.decode("utf-8", "replace").strip().splitlines()[-1])
        except (ValueError, IndexError):
            res["merged"][host] = "bad output"
            continue
        changed = [] if first else [c for c in (info.get("changed") or []) if not frozen(c)]
        acts = {}
        if changed:
            tr = remote(host, f"cd {OFF}/repo && tar cf - -T - 2>/dev/null; true", data=("\n".join(changed) + "\n").encode(), timeout=300)
            try:
                with tarfile.open(fileobj=io.BytesIO(tr.stdout)) as tf:
                    for m in tf.getmembers():
                        if not m.isfile() or ".." in m.name or m.name not in changed:
                            continue
                        dst = STAGE / host / "_scan" / m.name
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        dst.write_bytes(tf.extractfile(m).read())
                        try:
                            acts[m.name] = MP.merge_file(host, m.name, dst)
                        except Exception as e:  # noqa: BLE001
                            acts[m.name] = f"error:{repr(e)[:100]}"
                            continue
                        if not str(acts[m.name]).startswith(("skipped", "error", "corrupt")):   # ORPHAN-TAKE：并回后补拉通过版的原图
                            try:
                                queue_missing_takes(host, m.name)
                            except Exception as e:  # noqa: BLE001
                                log("queue_missing_takes", host, m.name, repr(e)[:100])
            except tarfile.TarError as e:
                acts["_tar"] = repr(e)[:100]
        state[f"_scan_since_{host}"] = t_start if not any(str(v).startswith("error") for v in acts.values()) else since
        res["merged"][host] = {k: v for k, v in acts.items() if not str(v).startswith("skipped")}
        for rel, sv in (info.get("summary") or {}).items():           # 一致性：只比本台负责的 stage
            if frozen(rel):
                continue
            m = re.search(r"/ep(\d{2})/", rel)
            if not m:
                continue
            stages = MP.own_stages(host, int(m.group(1)))
            if not stages:
                continue
            try:
                ld = json.loads((ROOT / rel).read_text(encoding="utf-8"))
            except (OSError, ValueError):   # arch-ok: 本地还没有这镜 → 记一条漂移
                res["drift"].append({"host": host, "rel": rel, "why": "本地没有"})
                continue
            la, ra = ld.get("active") or {}, sv.get("active") or {}
            lrej = {(t.get("stage"), t.get("n")) for t in ld.get("takes") or [] if t.get("rejected")}
            rrej = {tuple(x) for x in sv.get("rejected") or []}
            for st in stages:
                if la.get(st) != ra.get(st):
                    res["drift"].append({"host": host, "rel": rel, "stage": st, "local": la.get(st), "server": ra.get(st), "why": "当前版不一致"})
            miss = sorted(x for x in rrej - lrej if x[0] in stages)
            if miss:
                res["drift"].append({"host": host, "rel": rel, "why": "服务器作废、本地没作废", "takes": miss})
    state["_scan_last"] = res
    return res



FETCH_QUEUE = ROOT / "data/netfix/fetch_queue.jsonl"
FETCH_STATUS = ROOT / "data/netfix/fetch_status.json"
FETCH_MB_PER_TICK = 12


def takes_to_fetch(host: str, rel: str, td: dict, stages, exists=None) -> list[dict]:
    """ORPHAN-TAKE（11-06）：takes.json 并回后，本台负责 stage 里“当前版 / 已打分通过”的版本原图笔记本还没有 → 要拉的队列项。
    打分没结论（state=running / ok=None）、orphan、没通过的不拉——只给项目方看通过的图，它们在服务器上打完分才会经 outbox 过来。
    exists(rel) 可注入（测试）；默认看 ROOT 下有没有"""
    import re as _re
    exists = exists or (lambda r: (ROOT / r).exists())
    active = td.get("active") or {}
    out, seen = [], set()
    for t in td.get("takes") or []:
        st, f = t.get("stage"), t.get("file")
        if st not in set(stages or ()) or not f or t.get("quarantined") or t.get("void"):
            continue
        pf = t.get("postflight") if isinstance(t.get("postflight"), dict) else {}
        passing = pf.get("ok") is True and pf.get("state") not in ("running", "orphan")
        if not (passing or active.get(st) == t.get("n")):
            continue
        frel = "data/" + _re.sub(r"^data/", "", str(f).replace("\\", "/"))
        if frel in seen or exists(frel):
            continue
        seen.add(frel)
        out.append({"host": host, "rel": frel, "stage": st, "shot_rel": rel, "at": time.time(), "why": "orphan_take:scored_missing"})
    return out


def enqueue_fetch(items: list[dict], queue: Path | None = None) -> int:
    """追加进 fetch_queue.jsonl（按 rel 去重：队列里已有的不再写）→ 新写条数"""
    q = queue or FETCH_QUEUE
    have = set()
    try:
        for ln in q.read_text(encoding="utf-8").splitlines():
            try:
                have.add(json.loads(ln).get("rel"))
            except ValueError:   # arch-ok: 半行跳过
                continue
    except OSError:   # arch-ok: 没有队列文件 = 空队列
        pass
    new = [it for it in items if it.get("rel") and it["rel"] not in have]
    if new:
        q.parent.mkdir(parents=True, exist_ok=True)
        with open(q, "a", encoding="utf-8") as fh:
            for it in new:
                fh.write(json.dumps(it, ensure_ascii=False) + "\n")
    return len(new)


def queue_missing_takes(host: str, rel: str, queue: Path | None = None) -> int:
    """takes_scan 并回一份 takes.json 后调：本台负责 stage 的当前版 / 通过版原图没在笔记本 → 排进按需拉取队列"""
    import re as _re
    sys.path.insert(0, str(ROOT / "ops/offline"))
    import merge_pull as MP
    m = _re.search(r"/ep(\d{2})/", rel)
    if not m:
        return 0
    stages = MP.own_stages(host, int(m.group(1)))
    if not stages:
        return 0
    try:
        td = json.loads((ROOT / rel).read_text(encoding="utf-8"))
    except (OSError, ValueError):   # arch-ok: 刚并好的 takes.json 读不出 = 这镜本轮不排拉取（下轮 scan 再来）
        return 0
    return enqueue_fetch(takes_to_fetch(host, rel, td, stages), queue)


def fetch_queue(state: dict) -> dict:
    """按需拉取队列（takes_backfill / 界面插队写 data/netfix/fetch_queue.jsonl：{host, rel(仓库相对), stage}）：
    按文件顺序每拍最多拉 FETCH_MB_PER_TICK MB；本地已有就跳过（绝不覆盖）；拉到原子落盘。
    data/netfix/fetch_status.json = {pending: [rel…], done_n, failed}——界面据此对没拉到的显示“原图传输中”，不显示裂图"""
    try:
        lines = FETCH_QUEUE.read_text(encoding="utf-8").splitlines()
    except OSError:   # arch-ok: 没有队列 = 没有待拉
        return {"pending": 0}
    items, seen = [], set()
    for ln in lines:
        try:
            q = json.loads(ln)
        except ValueError:   # arch-ok: 半行跳过
            continue
        if q.get("rel") in seen or (ROOT / q.get("rel", "")).exists() or frozen(q.get("rel", "")):
            continue
        seen.add(q["rel"])
        items.append(q)
    done, failed, budget = 0, state.setdefault("_fetch_failed", {}), FETCH_MB_PER_TICK * 1e6
    for host in HOSTS:
        mine = [q for q in items if q.get("host") == host and failed.get(q["rel"], 0) < 3][:20]
        if not mine or budget <= 0:
            continue
        r = remote(host, f"cd {OFF}/repo && tar cf - -T - 2>/dev/null; true", data=("\n".join(q["rel"] for q in mine) + "\n").encode(), timeout=900)
        try:
            with tarfile.open(fileobj=io.BytesIO(r.stdout)) as tf:
                for m in tf.getmembers():
                    if not m.isfile() or ".." in m.name or m.name.startswith("/"):
                        continue
                    dst = ROOT / m.name
                    if dst.exists():
                        continue
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    tmp = dst.with_suffix(dst.suffix + ".part")
                    tmp.write_bytes(tf.extractfile(m).read())
                    os.replace(tmp, dst)
                    done += 1
                    budget -= m.size
        except tarfile.TarError as e:
            log("fetch tar error", host, repr(e)[:120])
        for q in mine:
            if not (ROOT / q["rel"]).exists():
                failed[q["rel"]] = failed.get(q["rel"], 0) + 1
    pending = [q["rel"] for q in items if not (ROOT / q["rel"]).exists()]
    stt = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "pending_n": len(pending), "pending": pending[:500], "done_this_tick": done,
           "failed": {k: v for k, v in failed.items() if v >= 3}}
    tmp = FETCH_STATUS.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(stt, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, FETCH_STATUS)
    if not pending:                                   # 全部拉完：队列清空（保留到 .done 归档）
        try:
            FETCH_QUEUE.replace(FETCH_QUEUE.with_suffix(time.strftime(".%Y%m%d%H%M%S.done")))
        except OSError:   # arch-ok: 归档失败下拍再试
            pass
    return {"pending": len(pending), "done": done}



FROZEN_STATUS = ("frozen", "readonly", "archived")


def run_of(rel: str) -> str:
    """仓库相对路径属于哪个 run（L-125：一律按 run 区分路径，不写死）：data/renders/<run>/epNN/… → run；
    不带 run 段的旧路径 data/renders/epNN/… → runs.json 的 legacy_unprefixed_run（缺省 series10_v1）"""
    import re
    m = re.match(r"data/renders/([^/]+)/ep\d{2}/", rel)
    if m and not re.fullmatch(r"ep\d{2}", m.group(1)):
        return m.group(1)
    return legacy_run()


def _runs() -> dict:
    try:
        sys.path.insert(0, str(ROOT / "tools/factory"))
        import state_paths as SP
        return SP.read_state("pipeline/runs", default={}) or {}
    except Exception:  # noqa: BLE001  # arch-ok: 读不到 run 登记表 → 当作没有冻结的 run
        return {}


def legacy_run() -> str:
    """用不带 run 前缀旧路径的那部剧 = runs.json 的 legacy_unprefixed_run（K-OPS-F24）；字段缺失就报错，不猜默认值（总调度 18:5x）"""
    v = _runs().get("legacy_unprefixed_run")
    if not v:
        raise RuntimeError("runs.json 缺 legacy_unprefixed_run：无法判断不带前缀的旧路径属于哪部剧（K-OPS-F24）")
    return v


def frozen(rel: str) -> bool:
    """L-125：冻结（只读视频库）的 run 不再同步 / 拉取新东西"""
    st = ((_runs().get("runs") or {}).get(run_of(rel)) or {}).get("status")
    return st in FROZEN_STATUS


def tick(state: dict) -> dict:
    stats = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "t": time.time(), "hosts": {}}
    try:
        stats["mirror"] = mirror(state)
        stats["fetch"] = fetch_queue(state)
        sc = takes_scan(state)
        stats["takes_sync"] = {"at": sc.get("at"), "merged": sc.get("merged"), "drift_n": len(sc.get("drift") or []),
                               "drift": (sc.get("drift") or [])[:30]}
    except Exception as e:  # noqa: BLE001
        stats["mirror"] = {"error": repr(e)[:200]}
        log("mirror error", repr(e)[:200])
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
