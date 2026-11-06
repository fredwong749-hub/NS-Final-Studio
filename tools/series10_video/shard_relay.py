"""视频按镜分片的中转（笔记本端；PLAN_EP01_FINISH §11）：两台服务器互不信任（没有 ssh 互信），helper 台出的镜头
只能经笔记本送到 owner 台，owner 才能合成整集。

    python tools/series10_video/shard_relay.py --run series10_v2            # 每个分片集：helper → 笔记本 → owner，一轮
    python tools/series10_video/shard_relay.py --run series10_v2 --dry-run  # 只列要送什么
    python tools/series10_video/shard_relay.py --run series10_v2 --loop     # 每 120 s 一轮（与 sync.py 同节奏）

送的东西（只送增量：owner 上没有 / 内容不同的）：
  · state_<helper>.json（owner 只读它；owner 的 vidgen 只写 state_<owner>.json，两边不会互相覆盖）
  · helper 入选版本的原片 clips/*.mp4（合成只认原片，K-EDT-V10）
  · scores/<镜>__*.json（审片页 / 登记要读）
分片没开（video_shard.json enabled=false）= 什么都不做。

FIX-VID（11-06，REVIEW-RUN D1 / D13）：每轮先把各分片台的 state_<host>.json（和 owner 的 jobs.json）拉到笔记本——以前只在笔记本本机已有
state 时才列清单，而笔记本从来没有 helper 的 state（sync.py 的 ssh 不经 rssh），owner 永远看不到 helper 的镜、整集永远不落定。
helper 的 state 超过 helper_stale_s（默认 900 s）没更新 / 拉不到 = 失联 → 它名下没落定的镜收回给 owner（sticky 领取）；
只从 state 新鲜（≤ 300 s）的台名下抢镜（“没开工”才可信，避免两台重复出同一镜）。状态写 _shard_relay_status.json。
"""
from __future__ import annotations

import io
import json
import sys
import tarfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import video_shard as VS  # noqa: E402


def helper_payload(vid: Path, vid_rel: str, helper: str, ep: int, root: Path | None = None, only_local: bool = True) -> list[str]:
    """要送给 owner 的文件（相对仓库根的路径）。state 先于片子；只含本集 helper 台的镜。only_local=True 只列笔记本本机已有的；False 列全部（用来决定要从 helper 拉哪些）"""
    root = ROOT if root is None else root
    st_rel = f"{vid_rel}/state_{helper}.json"
    if not (root / st_rel).is_file():
        return []
    try:
        st = json.loads((root / st_rel).read_text(encoding="utf-8"))
    except (OSError, ValueError):   # arch-ok: state 读不到 / 写到一半 = 这轮不送，下一轮再来
        return []
    out = [st_rel]
    for sid, r in sorted((st.get("shots") or {}).items()):
        if int(sid[2:4]) != int(ep):
            continue
        for x in r.get("renders") or []:
            if r.get("chosen") and x.get("variant") != r.get("chosen"):
                continue                      # 只送入选版本（合成只认它），落选版本留在 helper
            f = x.get("file") or ""
            if f.startswith(vid_rel + "/clips/") and ".." not in f and (not only_local or (root / f).is_file()):
                out.append(f)
        for p in sorted((vid / "scores").glob(f"{sid}__*.json")) if (vid / "scores").is_dir() else []:
            out.append(str(p.relative_to(root)).replace("\\", "/"))
    return list(dict.fromkeys(out))


STATUS_NAME = "_shard_relay_status.json"


def pull_from_helper(helper: str, files: list[str], force: bool = False) -> int:
    """helper → 笔记本：本机没有的片子 / scores；force=True 连本机已有的也重拉（state_<host>.json / jobs.json 每轮要最新的）。
    与 sync.pull_clips 同一条 ssh + tar 流，走 rssh 常驻主连接"""
    import deploy as D
    import sync as S
    want = [f for f in files if force or not (ROOT / f).is_file()]
    if not want:
        return 0
    rem = f"cd {S.DEST} 2>/dev/null || exit 0; tar cf - --ignore-failed-read {' '.join(want)} 2>/dev/null"
    r = D.ssh(helper, rem, timeout=3600)   # 走 rssh 常驻主连接（K-OPS-N07），不自己起 ssh
    n = 0
    if r.stdout:
        with tarfile.open(fileobj=io.BytesIO(r.stdout), mode="r:") as t:
            for m in t.getmembers():
                if not m.isfile() or ".." in m.name or m.name not in want:
                    continue
                data = t.extractfile(m).read()
                if len(data) != m.size:
                    continue
                dst = ROOT / m.name
                dst.parent.mkdir(parents=True, exist_ok=True)
                S.write_atomic(dst, data)
                n += 1
    return n


def _sig(p: Path) -> list:
    """送过的标记：≤ 8 MB 按内容 sha（state 每轮重拉、mtime 必变，内容没变就别重送 1.5 MB）；更大的按大小 + mtime"""
    import hashlib
    s = p.stat()
    if s.st_size <= 8_000_000:
        return [s.st_size, hashlib.sha256(p.read_bytes()).hexdigest()[:16]]
    return [s.st_size, int(s.st_mtime)]


def pull_states(vid: Path, vid_rel: str, hosts: list[str]) -> dict:
    """FIX-VID D1：各分片台的 state_<host>.json 先拉到笔记本（owner 的也拉：仲裁 busy / 整集视图要用）。
    返回 {host: {"ok": 拉到了, "age": state.saved 距今秒, "err": 错误}}；拉不到 = age 按本机旧文件算（没有 = inf = 失联）"""
    out = {}
    for h in hosts:
        try:
            n = pull_from_helper(h, [f"{vid_rel}/state_{h}.json"], force=True)
            out[h] = {"ok": n > 0, "age": VS.state_age(vid, h)}
            if not n:
                out[h]["err"] = "state 没拉到（远端没有 / 连接失败）"
        except Exception as e:  # noqa: BLE001  # arch-ok: 这台拉不到 = 记失联原因，按旧 state 的年龄判；不中断别的台
            out[h] = {"ok": False, "age": VS.state_age(vid, h), "err": repr(e)[:160]}
    return out


def pull_jobs(owner: str, vid_rel: str, status: dict) -> bool:
    """owner 的 jobs.json 拉到笔记本（仲裁要知道哪些镜有变体、静态归属）；只在远端大小 / mtime 变了才拉（~0.9 MB）"""
    import deploy as D
    import sync as S
    rel = f"{vid_rel}/jobs.json"
    r = D.ssh(owner, f"stat -c '%s %Y' {S.DEST}/{rel} 2>/dev/null", timeout=120)
    sig = (r.stdout or b"").decode(errors="replace").strip()
    if not sig:
        return False
    if status.get("jobs_sig") == sig and (ROOT / rel).is_file():
        return False
    if pull_from_helper(owner, [rel], force=True):
        status["jobs_sig"] = sig
        return True
    return False


def load_status(vid: Path) -> dict:
    try:
        d = json.loads((vid / STATUS_NAME).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):   # arch-ok: 状态文件没有 / 坏 = 空（只影响“jobs 要不要重拉”）
        return {}


def save_status(vid: Path, st: dict) -> None:
    vid.mkdir(parents=True, exist_ok=True)
    tmp = vid / (STATUS_NAME + ".tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(vid / STATUS_NAME)


def relay_cmd(dest: str) -> str:
    """FIX-NIGHT2 #7（多写者）：owner 上 vidgen 正在读 state_<helper>.json，`tar xf -` 直接覆盖活文件会读到半截 →
    先解到 DEST 下的临时目录，再逐个 mv（同一文件系统 = rename，原子）到位，临时目录删掉"""
    return (f"mkdir -p {dest} && cd {dest} && tmp=$(mktemp -d -p . .relay_XXXXXX) && tar xf - -C \"$tmp\" && "
            f"(cd \"$tmp\" && find . -type f) | while read -r f; do f=${{f#./}}; mkdir -p \"$(dirname \"$f\")\"; "
            f"mv -f \"$tmp/$f\" \"$f\"; done; rm -rf \"$tmp\"; echo RELAY_OK")


def push_to_owner(owner: str, files: list[str], dry: bool = False, marks_p: Path | None = None) -> int:
    """笔记本 → owner：打一个 tar 经 deploy.ssh 解到 owner 的发版目录（与 deploy.push 同一通道）。
    只送自上次成功以来变了的文件（大小 / mtime 记在 _shard_relay_marks.json，成功后才写）"""
    import deploy as D
    marks_p = marks_p or (ROOT / D.VID_REL / "_shard_relay_marks.json")
    try:
        marks = json.loads(marks_p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        marks = {}
    key = lambda f: f"{owner}:{f}"  # noqa: E731
    todo = [f for f in files if (ROOT / f).is_file() and marks.get(key(f)) != _sig(ROOT / f)]
    buf = io.BytesIO()
    n = 0
    with tarfile.open(fileobj=buf, mode="w:") as t:
        for f in todo:
            t.add(ROOT / f, arcname=f)
            n += 1
    if dry or not n:
        return n
    r = D.ssh(owner, relay_cmd(D.DEST), buf.getvalue(), timeout=3600)
    if b"RELAY_OK" not in (r.stdout or b""):
        raise RuntimeError(f"relay → {owner} 失败：{(r.stderr or b'').decode(errors='replace')[-200:]}")
    marks.update({key(f): _sig(ROOT / f) for f in todo})
    tmp = marks_p.with_name(marks_p.name + ".tmp")
    tmp.write_text(json.dumps(marks, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(marks_p)
    return n


def arbitrate_claims(run: str, vid: Path, vid_rel: str, c: dict, ep: int, busy: dict | None = None, now: float | None = None,
                     health: dict | None = None) -> dict:
    """动态抢活仲裁（只在笔记本）：读合并后的整集状态，空闲台领别台没开工的镜，写 shard_claims.json。返回新的领取表。
    busy 缺省 = 各台 state 里 state==submitted 的渲染数（笔记本上 relay 拉来的 state）。
    health = pull_states 的结果（{host: {"age"}}）；缺省按本机 state 文件算。helper 失联（age > helper_stale_s）→ 收回给 owner（D1）；
    只从 state 新鲜（age ≤ state_fresh_s）的台名下领镜（D13）。只有变体的镜才算在静态计划里（没变体 = 等资料，领了也出不了）"""
    now = time.time() if now is None else now
    jobs = json.loads((vid / "jobs.json").read_text(encoding="utf-8")) if (vid / "jobs.json").is_file() else {}
    shots = [s for s in jobs.get("shots", []) if int(s.get("ep") or 0) == int(ep)]
    plan_map = {s["shot"]: s.get("host") for s in shots if s.get("host") in c["hosts"] and s.get("variants")}
    cfg = VS.load()
    stale_s = float(cfg.get("helper_stale_s") or VS.HELPER_STALE_S)
    fresh_s = float(cfg.get("state_fresh_s") or VS.STATE_FRESH_S)
    ages = {h: float((health or {}).get(h, {}).get("age", VS.state_age(vid, h, now))) for h in c["hosts"]}
    stale_hosts = {h for h in c["hosts"] if h != c["owner"] and ages[h] > stale_s}
    claim_from = {h for h in c["hosts"] if ages[h] <= fresh_s}
    # jobs.json 里的 host 已含旧领取；还原成静态计划再叠，避免领取“固化”
    old = VS.load_claims(vid)
    for sid, cl in old.items():
        if sid in plan_map and cl.get("from") in c["hosts"] and plan_map[sid] == cl.get("host"):
            plan_map[sid] = cl["from"]
    merged = VS.merged_shots(vid, ep, c["hosts"], jobs)
    if busy is None:
        busy = {}
        for h in c["hosts"]:
            try:
                st = json.loads((vid / f"state_{h}.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):   # arch-ok: 读不到这台 state = 当它忙（不抢，宁可少派）
                busy[h] = 1
                continue
            busy[h] = sum(1 for r in (st.get("shots") or {}).values() for x in r.get("renders") or [] if x.get("state") == "submitted")
    # L-206 工位分卡：本集当前阶段没有视频道的台（首尾帧阶段的 gpu33）不抢活（当它忙），它名下没开工的镜领给有视频道的台；
    # 视频阶段把为分卡领走、还没开工的还回静态计划。不适用（关 / ep < from_episode / 模块不在）= video_hosts None = 原样
    video_hosts = role_video_hosts(run, ep, [s["shot"] for s in shots])
    if video_hosts is not None:
        busy = {**busy, **{h: max(1, int(busy.get(h, 0))) for h in c["hosts"] if h not in video_hosts}}
    new = VS.decide_claims(c, plan_map, merged, old, busy, now, claim_from=claim_from, stale_hosts=stale_hosts)
    new = VS.role_claims(c, plan_map, merged, new, video_hosts, now)
    if new != old:
        VS.save_claims(vid, new)
        back = [s for s, x in new.items() if x.get("sticky") and s not in old]
        if back:
            print(time.strftime("%H:%M:%S"), f"RECLAIM ep{ep:02d}", sorted(stale_hosts), "→", c["owner"], back,
                  {h: (round(ages[h]) if ages[h] < 1e12 else "失联") for h in stale_hosts}, flush=True)
    return new


def role_video_hosts(run: str, ep: int, shot_ids: list[str]) -> set[str] | None:
    """L-206：本集当前阶段有视频道的台；不适用 = None。阶段 = producer 阶段表，没有就按 takes / registry 算（lane_roles.phase_of）"""
    try:
        import lane_roles as LR
    except ImportError:   # arch-ok: 没有分卡模块 = 不分卡（抢活原样）
        return None
    cfg = LR.load()
    ph = LR.phase_of(run, ep, shot_ids, cfg)
    return LR.hosts_with(ph, "video", cfg) if ph else None


def once(run: str, dry: bool = False) -> dict:
    import run_ctx as RC
    vid_rel = RC.vid_rel(run)
    vid = ROOT / vid_rel
    res = {}
    status = load_status(vid)
    for ep, c in VS.shard_eps(run).items():
        health = {}
        if not dry:   # FIX-VID D1：state 先拉到笔记本（以前没有这一步 → helper_payload 永远 []、owner 永远等不到 helper 的镜）
            health = pull_states(vid, vid_rel, c["hosts"])
            try:
                pull_jobs(c["owner"], vid_rel, status)
            except Exception as e:  # noqa: BLE001  # arch-ok: jobs 拉不到 = 用本机旧的 / 没有就不仲裁，state / 片子照送
                res[f"ep{ep:02d}:jobs"] = {"error": repr(e)[:160]}
            res[f"ep{ep:02d}:health"] = health
        for helper in c["hosts"]:
            if helper == c["owner"]:
                continue
            try:
                if not dry:
                    pull_from_helper(helper, helper_payload(vid, vid_rel, helper, ep, only_local=False))
                files = helper_payload(vid, vid_rel, helper, ep)
                res[f"ep{ep:02d}:{helper}->{c['owner']}"] = {"files": len(files), "pushed": push_to_owner(c["owner"], files, dry)}
            except Exception as e:  # noqa: BLE001  # arch-ok: 这台中转失败 = 记下、下一轮再来；不影响仲裁（失联由仲裁收回）
                res[f"ep{ep:02d}:{helper}->{c['owner']}"] = {"error": repr(e)[:160]}
        if not dry:
            try:
                cl = arbitrate_claims(run, vid, vid_rel, c, ep, health=health)
                cf = [f"{vid_rel}/{VS.CLAIMS_NAME}"] if (vid / VS.CLAIMS_NAME).is_file() else []
                for h in c["hosts"]:                      # 领取表送到两台（互不信任，只经笔记本）；已有标记的不重复送
                    push_to_owner(h, cf, dry)
                res[f"ep{ep:02d}:claims"] = {"n": len(cl)}
            except Exception as e:  # noqa: BLE001  # arch-ok: 仲裁失败 = 回到静态计划，不影响 state / 片子中转
                res[f"ep{ep:02d}:claims"] = {"error": repr(e)[:160]}
        status.setdefault("eps", {})[str(ep)] = {"t": time.time(), "health": {h: {**x, "age": x["age"] if x.get("age", 0) < 1e12 else None} for h, x in health.items()}, "claims": res.get(f"ep{ep:02d}:claims")}
    if not dry:
        status["t"] = time.time()
        save_status(vid, status)
    return res


def main(argv: list[str]) -> int:
    import run_ctx as RC
    run = RC.arg_run(argv) or RC.resolve(argv)
    while True:
        print(time.strftime("%H:%M:%S"), json.dumps(once(run, "--dry-run" in argv), ensure_ascii=False), flush=True)
        if "--loop" not in argv:
            return 0
        time.sleep(120)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
