"""FACTORY D10：笔记本控制台（docs/master/FRAMEWORK_REFRAME.md；L-099b）。笔记本只做 push / pull / status。

  python tools/factory/sync.py push HOST [--eps 2,4]   # 缺 sha 补传：笔记本算依赖闭包 need（tools/factory/deps.py dryrun），
                                                      # 服务器按 need 逐个核 sha，只补缺的 / 不同的（先解到临时目录再搬入，K-OPS-W02）
  python tools/factory/sync.py verify HOST [--eps …] [--write-ready]
                                                      # 交还闸门 K-OPS-F02：服务器 dryrun 挡 0 + 每镜 refs 与笔记本一致 → ready
  python tools/factory/sync.py pull                    # 交 NETFIX puller（长连接、断点续传）+ ops/offline/merge_pull.merge_file
  python tools/factory/sync.py status                  # 各工厂心跳 / 道 / 代码版本

远程命令一律走 tools/netfix/rssh.py 的常驻主连接（K-OPS-N07），不新建握手。不删任何文件。
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import sys
import tarfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/netfix"))
sys.path.insert(0, str(ROOT / "tools/factory"))
OFF = "/root/work/fredw/offline_20261101"
PROD = OFF + "/repo"                      # 服务器生产副本（迁移完成后换成 git 工作树，D9）
DEV = "/root/work/fredw/ns_factory_dev"   # 服务器开发树：deps.py 从这里跑，读 PROD 的代码和数据（NS_ROOT）
PY = OFF + "/venv/bin/python"
ENV = f"export NS_ROOT={PROD} OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 NUMEXPR_NUM_THREADS=4 TZ=Asia/Tokyo PYTHONUTF8=1"
STATE = ROOT / "data/factory/sync_state.json"
CODE_PREFIX = ("tools/", "services/", "packages/", "config/", "knowledge/", "ops/")   # = resident_sync.CODE_DIRS，只随 deploy 走


def rrun(host: str, cmd: str, data: bytes | None = None, timeout: float = 900) -> str:
    import rssh
    r = rssh.run(host, cmd, input=data, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"{host} rc={r.returncode}: {r.stderr.decode('utf-8', 'replace')[-400:]}")
    return r.stdout.decode("utf-8", "replace")


def ensure_tool(host: str) -> None:
    """把本机 deps.py 放进服务器开发树（同一份文件，回仓即本仓库这一份）"""
    code = (ROOT / "tools/factory/deps.py").read_bytes()
    rrun(host, f"mkdir -p {DEV}/tools/factory && cat > {DEV}/tools/factory/deps.py", data=code, timeout=120)


# 视频阶段 night 合成链的静态依赖（config/post 属于代码目录：随 deploy 走，这里只核对、报 code_drift；data/sfx_lib 由 sync 补）（总调度 01:4x：DIRECTOR 导演层 / 后期层接进 night，config/post/director.json enabled=true）：
# 音效库（含 LICENSES.json）+ 后期配置（含 LUT）。整目录进闭包，缺什么补什么
NIGHT_DIRS = ("data/sfx_lib", "config/post")


def night_files() -> dict[str, str]:
    import deps
    out = {}
    for d in NIGHT_DIRS:
        for p in sorted((ROOT / d).rglob("*")):
            if p.is_file() and "__pycache__" not in p.parts:
                out[p.relative_to(ROOT).as_posix()] = deps.sha256_file(p)
    return out


def laptop_need(host: str, eps: list[int] | None) -> dict:
    import deps
    res = deps.dryrun(eps or deps.partition_eps(host))
    res["host"] = host
    if host in ("gpu33", "gpu36"):          # 两台都跑 night（视频分区），合成依赖一并补齐
        res["files"].update(night_files())
    return res


def remote_diff(host: str, need: dict) -> dict:
    ensure_tool(host)
    out = rrun(host, f"cat > /tmp/factory_need.json && {ENV} && cd {PROD} && nice {PY} {DEV}/tools/factory/deps.py diff /tmp/factory_need.json",
               data=json.dumps(need, ensure_ascii=False).encode(), timeout=600)
    return json.loads(out)


def tar_of(files: list[str]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for r in files:
            tf.add(str(ROOT / r), arcname=r)
    return buf.getvalue()


def push(host: str, eps: list[int] | None = None, dry: bool = False) -> dict:
    need = laptop_need(host, eps)
    d = remote_diff(host, need)
    allx = sorted(set(d["absent"]) | set(d["changed"]))
    # D9 / K-OPS-F06：代码目录（tools / services / packages / config / knowledge / ops）只随 sv-* deploy 走，sync 不推——
    # 否则新配置会配上服务器的旧代码（例：K-REN-706 的 image_framing.json 先到、framing.py 还没部署）。差异只报 code_drift
    todo = [r for r in allx if not r.startswith(CODE_PREFIX)]
    res = {"host": host, "need": len(need["files"]), "absent": d["absent"], "changed": d["changed"], "sent": 0,
           "code_drift": [r for r in allx if r.startswith(CODE_PREFIX)],
           "laptop_blocked": need["blocked"], "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    if todo and not dry:
        blob = tar_of(todo)
        # 被覆盖的旧文件先备份（不删）：data/_factory_backup/<时间>/<相对路径>
        bk = f"{PROD}/data/_factory_backup/{time.strftime('%Y%m%d-%H%M%S')}"
        lst = " ".join(f"'{r}'" for r in todo)
        rrun(host, f"set -e; cd {PROD}; for f in {lst}; do [ -f \"$f\" ] && mkdir -p \"{bk}/$(dirname \"$f\")\" && cp -a \"$f\" \"{bk}/$f\"; done; "
                   f"T=$(mktemp -d {OFF}/.fpush.XXXXXX); tar xf - -C $T; cp -a $T/. {PROD}/; rm -rf $T; echo ok", data=blob, timeout=1200)
        res["sent"] = len(todo)
        res["backup"] = bk
        d2 = remote_diff(host, need)
        res["after"] = {"absent": d2["absent"], "changed": d2["changed"]}
    if not dry:
        res["expected_refs"] = push_expected(host)
    _save(host, "push", res)
    return res


def push_expected(host: str, rebuild: bool = True) -> str:
    """K-OPS-F03：期望 refs 表（data/factory/inbox/expected_refs.json）随 push 推到服务器，原子替换"""
    import inbox as IB
    if rebuild:
        IB.build()
    b = IB.EXPECTED.read_bytes()
    rel = IB.EXPECTED.relative_to(ROOT).as_posix()
    return rrun(host, f"mkdir -p {PROD}/$(dirname {rel}) && cat > {PROD}/{rel}.tmp && mv {PROD}/{rel}.tmp {PROD}/{rel} && sha256sum {PROD}/{rel}",
                data=b, timeout=300).strip()[:80]


def verify(host: str, eps: list[int] | None = None, write_ready: bool = False) -> dict:
    """K-OPS-F02 交还闸门：服务器 dryrun 挡 0，且每镜 refs（路径 + sha）与笔记本 dryrun 一致"""
    import deps
    need = laptop_need(host, eps)
    ensure_tool(host)
    e = ",".join(str(x) for x in need["eps"])
    # 长任务在服务器本机后台跑、结果落服务器本地文件；笔记本只做短轮询（跳板抖动不打断任务，FRAMEWORK_REFRAME P1）
    tag = time.strftime("%Y%m%d%H%M%S")
    out = f"/tmp/factory_dry_{host}_{tag}.json"
    rrun(host, f"{ENV} && cd {PROD} && (setsid nohup nice {PY} {DEV}/tools/factory/deps.py dryrun --host {host} --eps {e} --out {out}.part "
               f"</dev/null >/tmp/factory_dry_{host}.log 2>&1; mv {out}.part {out}) >/dev/null 2>&1 & echo started", timeout=120)
    srv, t0 = None, time.time()
    while srv is None and time.time() - t0 < 1800:
        time.sleep(15)
        try:
            txt = rrun(host, f"test -f {out} && cat {out} || echo __wait__", timeout=120)
        except RuntimeError:
            continue                       # 主连接抖动：下一拍再查，任务在服务器上照跑
        if not txt.startswith("__wait__"):
            srv = json.loads(txt)
    if srv is None:
        raise RuntimeError(f"{host} dryrun 30 分钟没出结果（{out}）")
    mism = {}
    for sid, v in need["shots"].items():
        s = srv["shots"].get(sid) or {}
        a = [(r, need["files"].get(deps.rel_of(ROOT / r) or r)) for r in v.get("refs") or []]
        b = [(r, srv["files"].get(r)) for r in s.get("refs") or []]
        if a != b:
            mism[sid] = {"laptop": [x[0] for x in a], "server": [x[0] for x in b]}
    res = {"host": host, "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "total": srv["total"], "server_blocked": srv["blocked"],
           "laptop_blocked": need["blocked"], "refs_mismatch": len(mism), "mismatch": mism,
           "ok": srv["total"] > 0 and srv["blocked"] == 0 and not mism}
    if write_ready:
        res["assets_ready"] = write_ready_flag(host, res)
    _save(host, "verify", {k: v for k, v in res.items() if k != "mismatch"} | {"mismatch_shots": sorted(mism)[:30]})
    return res


def write_ready_flag(host: str, v: dict, path: Path | None = None) -> dict:
    """assets_ready.<host>：preflight_dryrun_ok / refs_match / ready（只在两条都满足时 true；NETFIX reconcile 认 preflight_dryrun_ok）"""
    p = path or (ROOT / "data/autopilot/assets_ready.json")
    try:
        cur = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cur = {}
    rec = dict(cur.get(host) or {})
    ok_pf = v["total"] > 0 and v["server_blocked"] == 0
    rec.update(preflight_dryrun_ok=ok_pf and v["refs_mismatch"] == 0, refs_match=v["refs_mismatch"] == 0,
               preflight_dryrun_blocked=v["server_blocked"], preflight_dryrun_shots=v["total"], refs_mismatch=v["refs_mismatch"],
               ready=bool(v["ok"]), preflight_dryrun_at=v["at"], preflight_dryrun_by="FACTORY tools/factory/sync.py verify（K-OPS-F02）")
    cur[host] = rec
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(cur, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)
    return rec


def status() -> dict:
    out = {}
    for h in ("gpu33", "gpu36"):
        try:
            s = rrun(h, f"cat {PROD}/data/system_version.txt 2>/dev/null | head -c 200; echo; cat {PROD}/data/producer/heartbeat.json 2>/dev/null | tr -d '\\n'; echo; "
                        "nvidia-smi --query-gpu=index,utilization.gpu --format=csv,noheader | tr '\\n' ' '", timeout=60)
            out[h] = s.strip().split("\n")
        except Exception as e:  # noqa: BLE001
            out[h] = f"不可达：{e!r}"[:200]
    return out


def _save(host: str, kind: str, rec: dict) -> None:
    try:
        st = json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        st = {}
    st.setdefault(host, {})[kind] = rec
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("push", "verify"):
        s = sub.add_parser(name)
        s.add_argument("host")
        s.add_argument("--eps", default="")
        if name == "push":
            s.add_argument("--dry", action="store_true")
        else:
            s.add_argument("--write-ready", action="store_true")
    sub.add_parser("pull")
    sub.add_parser("status")
    a = ap.parse_args(argv)
    eps = [int(x) for x in getattr(a, "eps", "").split(",") if x] or None
    if a.cmd == "push":
        print(json.dumps(push(a.host, eps, a.dry), ensure_ascii=False, indent=1))
    elif a.cmd == "verify":
        r = verify(a.host, eps, a.write_ready)
        print(json.dumps({k: v for k, v in r.items() if k != "mismatch"} | {"mismatch_sample": dict(list(r["mismatch"].items())[:3])},
                         ensure_ascii=False, indent=1))
        return 0 if r["ok"] else 2
    elif a.cmd == "pull":
        print("pull 由 NETFIX puller 负责（长连接 + 断点续传 + sha 校验），落地后调 ops/offline/merge_pull.merge_file；本命令不另起传输")
    else:
        print(json.dumps(status(), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
