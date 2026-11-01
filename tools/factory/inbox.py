"""FACTORY D4（第一部分）：派单前 refs 的 sha 校验（总调度 01:3x 批准；规则 K-OPS-F03）。

起因（11-02 01:24–01:32 实测）：服务器缺 data/looks/face_overrides.json，preflight 照样 0 挡，但林晚身份脸解析成旧的 ref2va，
两台 31 个 take 用错身份脸，事后才发现。根治：笔记本（资料全、决定在这里做）用 tools/factory/deps.py 算出每镜期望的 refs
（路径 + sha），写进目标状态 data/factory/inbox/expected_refs.json，随 inbox 推到服务器；服务器 producer 每次派单前把这单
实际要上传的 refs 逐个算 sha 和期望比对，不一致 → 拒派（不提交、不计次）+ 报警事件 refs_mismatch。

    python tools/factory/inbox.py build [--hosts gpu33,gpu36,laptop]   # 笔记本：生成 expected_refs.json
笔记本上没有期望表 = 不拦（返回 None）；服务器上期望表缺失由 decisions_guard 拒派（K-OPS-F09）；表里没有这镜 = 拒派。
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(os.environ.get("NS_ROOT") or Path(__file__).resolve().parents[2]).resolve()
EXPECTED = ROOT / "data/factory/inbox/expected_refs.json"
_SHA_CACHE: dict[tuple[str, float, int], str] = {}


def _sha(p: Path) -> str | None:
    try:
        st = p.stat()
    except OSError:
        return None
    k = (str(p), st.st_mtime_ns, st.st_size)
    fresh = time.time() - st.st_mtime < 5        # 刚写过的文件不走缓存（同秒同大小改写会撞键）
    if fresh or k not in _SHA_CACHE:
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for b in iter(lambda: f.read(1 << 20), b""):
                h.update(b)
        _SHA_CACHE[k] = h.hexdigest()
    return _SHA_CACHE[k]


def _rel(r: str, root: Path) -> str:
    p = Path(r)
    if p.is_absolute():
        try:
            return p.resolve().relative_to(root).as_posix()
        except ValueError:
            return str(r)
    return Path(r).as_posix()


def load_expected(path: Path | None = None) -> dict | None:
    try:
        return json.loads((path or EXPECTED).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def check_refs(sid: str, refs: list, expected: dict | None = None, root: Path | None = None) -> list[str] | None:
    """→ None = 无期望值（不拦）；[] = 一致；[问题…] = 不一致（拒派）"""
    root = root or ROOT
    exp = expected if expected is not None else load_expected()
    if not exp:
        return None
    want = (exp.get("shots") or {}).get(sid)
    if want is None:        # K-OPS-F09：有期望表但这镜不在表里 = 目标状态没覆盖到 → 拒派（⤴ 取代“不在表里不拦”）
        return [f"期望 refs 表里没有 {sid}（先在笔记本 inbox.py build + sync push）"]
    got = [_rel(str(r), root) for r in refs or []]
    probs = []
    wl = [w["rel"] for w in want]
    if got != wl:
        probs.append(f"refs 路径不一致：期望 {wl}，实际 {got}")
    for w in want:
        if w["rel"] in got:
            s = _sha(root / w["rel"])
            if s is None:
                probs.append(f"缺文件 {w['rel']}")
            elif w.get("sha") and s != w["sha"]:
                probs.append(f"sha 不一致 {w['rel']}：期望 {w['sha'][:12]}，实际 {s[:12]}")
    return probs


def build(hosts: list[str]) -> dict:
    """笔记本：对各工厂负责的集跑 deps dryrun，写期望 refs（路径 + sha）"""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import deps
    shots = {}
    blocked = {}
    for h in hosts:
        res = deps.dryrun(deps.partition_eps(h))
        for sid, v in res["shots"].items():
            if not v.get("ok"):
                blocked[sid] = v.get("reasons")
                continue
            shots[sid] = [{"rel": _rel(r, ROOT), "sha": _sha(ROOT / _rel(r, ROOT))} for r in v.get("refs") or []]
    out = {"at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "by": "FACTORY tools/factory/inbox.py build（K-OPS-F03）", "hosts": hosts,
           "shots": shots, "laptop_blocked": blocked}
    EXPECTED.parent.mkdir(parents=True, exist_ok=True)
    tmp = EXPECTED.with_suffix(".tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, EXPECTED)
    return out


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build"])
    ap.add_argument("--hosts", default="gpu33,gpu36,laptop")
    a = ap.parse_args()
    o = build([h for h in a.hosts.split(",") if h])
    print(json.dumps({"shots": len(o["shots"]), "laptop_blocked": len(o["laptop_blocked"]), "file": str(EXPECTED)}, ensure_ascii=False))
