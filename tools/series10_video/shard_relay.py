"""视频按镜分片的中转（笔记本端；PLAN_EP01_FINISH §11）：两台服务器互不信任（没有 ssh 互信），helper 台出的镜头
只能经笔记本送到 owner 台，owner 才能合成整集。

    python tools/series10_video/shard_relay.py --run series10_v2            # 每个分片集：helper → 笔记本 → owner，一轮
    python tools/series10_video/shard_relay.py --run series10_v2 --dry-run  # 只列要送什么
    python tools/series10_video/shard_relay.py --run series10_v2 --loop     # 每 120 s 一轮（与 sync.py 同节奏）

送的东西（只送增量：owner 上没有 / 大小不同的）：
  · state_<helper>.json（owner 只读它；owner 的 vidgen 只写 state_<owner>.json，两边不会互相覆盖）
  · helper 入选版本的原片 clips/*.mp4（合成只认原片，K-EDT-V10）
  · scores/<镜>__*.json（审片页 / 登记要读）
分片没开（video_shard.json enabled=false）= 什么都不做。
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


def helper_payload(vid: Path, vid_rel: str, helper: str, ep: int, root: Path = ROOT, only_local: bool = True) -> list[str]:
    """要送给 owner 的文件（相对仓库根的路径）。state 先于片子；只含本集 helper 台的镜。only_local=True 只列笔记本本机已有的；False 列全部（用来决定要从 helper 拉哪些）"""
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


def pull_from_helper(helper: str, files: list[str]) -> int:
    """helper → 笔记本：本机没有的片子 / scores（state 由 sync.py 拉）。与 sync.pull_clips 同一条 ssh + tar 流"""
    import deploy as D
    import sync as S
    want = [f for f in files if not (ROOT / f).is_file()]
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
    s = p.stat()
    return [s.st_size, int(s.st_mtime)]


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
    r = D.ssh(owner, f"mkdir -p {D.DEST} && cd {D.DEST} && tar xf - && echo RELAY_OK", buf.getvalue(), timeout=3600)
    if b"RELAY_OK" not in (r.stdout or b""):
        raise RuntimeError(f"relay → {owner} 失败：{(r.stderr or b'').decode(errors='replace')[-200:]}")
    marks.update({key(f): _sig(ROOT / f) for f in todo})
    tmp = marks_p.with_name(marks_p.name + ".tmp")
    tmp.write_text(json.dumps(marks, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(marks_p)
    return n


def arbitrate_claims(run: str, vid: Path, vid_rel: str, c: dict, ep: int, busy: dict | None = None, now: float | None = None) -> dict:
    """动态抢活仲裁（只在笔记本）：读合并后的整集状态，空闲台领别台没开工的镜，写 shard_claims.json。返回新的领取表。
    busy 缺省 = 各台 state 里 state==submitted 的渲染数（笔记本上 sync 来的 state）"""
    now = time.time() if now is None else now
    jobs = json.loads((vid / "jobs.json").read_text(encoding="utf-8")) if (vid / "jobs.json").is_file() else {}
    shots = [s for s in jobs.get("shots", []) if int(s.get("ep") or 0) == int(ep)]
    plan_map = {s["shot"]: s.get("host") for s in shots if s.get("host") in c["hosts"]}
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
    new = VS.decide_claims(c, plan_map, merged, old, busy, now)
    if new != old:
        VS.save_claims(vid, new)
    return new


def once(run: str, dry: bool = False) -> dict:
    import run_ctx as RC
    vid_rel = RC.vid_rel(run)
    vid = ROOT / vid_rel
    res = {}
    for ep, c in VS.shard_eps(run).items():
        for helper in c["hosts"]:
            if helper == c["owner"]:
                continue
            if not dry:
                pull_from_helper(helper, helper_payload(vid, vid_rel, helper, ep, only_local=False))
            files = helper_payload(vid, vid_rel, helper, ep)
            res[f"ep{ep:02d}:{helper}->{c['owner']}"] = {"files": len(files), "pushed": push_to_owner(c["owner"], files, dry)}
        if not dry:
            try:
                cl = arbitrate_claims(run, vid, vid_rel, c, ep)
                cf = [f"{vid_rel}/{VS.CLAIMS_NAME}"] if (vid / VS.CLAIMS_NAME).is_file() else []
                for h in c["hosts"]:                      # 领取表送到两台（互不信任，只经笔记本）；已有标记的不重复送
                    push_to_owner(h, cf, dry)
                res[f"ep{ep:02d}:claims"] = {"n": len(cl)}
            except Exception as e:  # noqa: BLE001  # arch-ok: 仲裁失败 = 回到静态计划，不影响 state / 片子中转
                res[f"ep{ep:02d}:claims"] = {"error": repr(e)[:160]}
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
