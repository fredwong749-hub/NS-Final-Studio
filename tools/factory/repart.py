"""改派单分区的唯一入口（K-OPS-F21 / K-OPS-E25，总调度 11-02 17:3x）。

16:31 把 ep02/04/06 的出图划给 gpu33 时没先过 repart_check：gpu33 本地没有这三集的版本，16:30 起重出首帧 61 次、尾帧 33 次。
以后改 partition.json 一律走这里：算出要换主机的集 → 到各台数本机已有版本（data/renders/epNN/S*/takes.json 里有 take 的镜）→
tools/debug/lanes.py repart_check → 有问题就拒绝；通过才在 partition_lock 里写 partition.json，先推“撤掉集”的那台、再推“加集”的那台。

    python tools/factory/repart.py --images gpu33=1,3,5,7,9,10 gpu36=2,4,6,8 --video same [--dry]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/netfix"))


def _lanes_mod():
    sp = importlib.util.spec_from_file_location("debug_lanes", ROOT / "tools/debug/lanes.py")
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


def moved(old: dict, new: dict) -> dict:
    """{host: [新分到这台、原来不在这台的集]}"""
    was = {e: h for h, eps in (old or {}).items() for e in eps}
    out: dict = {}
    for h, eps in (new or {}).items():
        for e in eps:
            if was.get(e) != h:
                out.setdefault(h, []).append(e)
    return out


TAKES_PY = r'''
import json, os, sys
R, eps = sys.argv[1], [int(x) for x in sys.argv[2].split(",") if x]
RD = sys.argv[3]
have = []
for e in eps:
    d = os.path.join(R, RD, "ep%02d" % e)
    n = 0
    for s in (os.listdir(d) if os.path.isdir(d) else []):
        try:
            t = json.load(open(os.path.join(d, s, "takes.json")))
        except Exception:
            continue
        # 只算本机真有当前首帧文件的镜（takes.json 可能是同步过来的元数据，文件不在 = 这台没有这一版，K-OPS-E25 实测 gpu36 ep01）
        a = (t.get("active") or {}).get("image") if isinstance(t, dict) else None
        rec = next((x for x in t.get("takes") or [] if x.get("stage") == "image" and x.get("n") == a), None) if a else None
        f = (rec or {}).get("file") or ""
        if f and os.path.isfile(os.path.join(R, "data", f)):
            n += 1
    if n:
        have.append(e)
print(json.dumps(have))
'''


def renders_rels(root: Path | None = None) -> list[tuple[str, str]]:
    """MERGE-OPS-O（carryover 第 14 项，L-137）：要数版本的各剧渲染根 [(run, 相对仓库的目录)]。分区按集、所有剧共用，
    所以每部没归档的剧都要数（runs.renders_dir：legacy = 旧根，其它剧 = 带剧号的根）。归档 / 冻结的剧不再出图，不挡改分区。
    登记表读不出 → 抛错（失败关闭：apply 不改分区）"""
    root = root or ROOT
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from tools.autopilot import runs as RN
    reg = RN.registry(root, strict=True)
    out = []
    for r, v in (reg.get("runs") or {}).items():
        if (v or {}).get("status") == "archived":
            continue
        rel = Path(RN.renders_dir(r, root)).resolve().relative_to(Path(root).resolve()).as_posix()
        if rel not in [x for _r, x in out]:
            out.append((r, rel))
    return out


def have_takes(hosts: list[str], eps: list[int], renders_rel: str, run=None) -> dict:
    """{host: {本机有版本的集}}（只数要换主机的那些集；连不上的机器当作“有”，宁可拒绝也不误放）。renders_rel = 哪部剧的渲染根"""
    import base64
    if run is None:
        import rssh
        run = rssh.run_retry
    sys.path.insert(0, str(ROOT / "tools/factory"))
    import hosts as H
    out = {}
    code = base64.b64encode(TAKES_PY.encode()).decode()
    for h in hosts:
        r = run(h, f'python3 -c "$(echo {code} | base64 -d)" {H.server_root(h)} {",".join(map(str, eps))} {renders_rel}', timeout=120, tries=3, text=True)
        try:
            out[h] = set(json.loads((r.stdout or "").strip().splitlines()[-1]))
        except (ValueError, IndexError):   # arch-ok: 数不出来 → 当作这台全有，repart_check 会把要搬走的集都拦下
            out[h] = set(eps)
    return out


def check(old: dict, new: dict, run=None, renders: list[tuple[str, str]] | None = None) -> list[str]:
    mv = moved(old.get("images", {}), new["images"])
    for h, eps in moved(old.get("video", {}), new["video"]).items():
        mv.setdefault(h, [])
        mv[h] = sorted(set(mv[h]) | set(eps))
    if not mv:
        return []
    eps = sorted({e for v in mv.values() for e in v})
    hosts = sorted(set(new["images"]) | set(old.get("images", {})))
    hosts = [h for h in hosts if h != "laptop"]
    probs = []
    for run_name, rel in (renders if renders is not None else renders_rels()):     # MERGE-OPS-O：每部剧分别过 repart_check
        probs += [f"[{run_name}] {x}" for x in _lanes_mod().repart_check(mv, have_takes(hosts, eps, rel, run=run))]
    return probs


def apply(new_images: dict, new_video: dict, why: str, by: str, dry: bool = False, run=None) -> dict:
    import dispatch as D
    part = D.read_partition()
    new = {"images": {**{h: [] for h in part.get("images", {})}, **new_images}, "video": new_video}
    probs = check(part, new, run=run)
    if probs:
        return {"ok": False, "refused": probs}
    if dry:
        return {"ok": True, "dry": True, "moved_images": moved(part.get("images", {}), new["images"])}
    with D.partition_lock():
        p = D.read_partition()
        hist = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "from": {"images": p.get("images"), "video": p.get("video")},
                "to": {"images": new["images"], "video": new["video"]}, "why": why, "by": by, "repart_check": "pass"}
        p["images"], p["video"] = new["images"], new["video"]
        p.setdefault("_images_history", []).append(hist)
        errs = D.check_partition(p)
        if errs:
            return {"ok": False, "refused": errs}
        D.SP.write_state(D.PART_NAME, p)
    # 先推“撤掉集”的机器（停派），再推“加集”的机器
    losing = [h for h in part.get("images", {}) if set(part["images"].get(h, [])) - set(new["images"].get(h, []))]
    order = [h for h in losing if h != "laptop"] + [h for h in new["images"] if h not in losing and h != "laptop"]
    pushed = {h: D.push_server_control(h) for h in order}
    return {"ok": True, "pushed": {h: {k: v.get(k) for k in ("rc", "only_n")} for h, v in pushed.items()}}


def _parse(items: list[str]) -> dict:
    out = {}
    for it in items:
        h, eps = it.split("=", 1)
        out[h] = sorted(int(x) for x in eps.split(",") if x)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--images", nargs="+", required=True)
    ap.add_argument("--video", nargs="+", required=True, help="same = 与出图相同（帧和视频同一台）")
    ap.add_argument("--why", required=True)
    ap.add_argument("--by", required=True)
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args(argv)
    imgs = _parse(a.images)
    vid = {h: list(v) for h, v in imgs.items() if h != "laptop"} if a.video == ["same"] else _parse(a.video)
    r = apply(imgs, vid, a.why, a.by, dry=a.dry)
    print(json.dumps(r, ensure_ascii=False, indent=1))
    return 0 if r.get("ok") else 2


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
