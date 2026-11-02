"""出图后验收批量回填（ALIGNMENT 第 8 步；总调度 11-02 17:3x：视频闸门收紧，首帧要有第 8 步验收 pass 才进视频，sv-14 上线前先把现有首帧验完）。

在笔记本上跑、数据取自出图主机（D9：不手推服务器代码，accept.py 随 sv-14 部署前服务器上没有它）：
  1. rsh 到出图主机，用标准库只读 repo 的 data/renders/epNN/S*/takes.json，导出每镜当前首帧（active.image）的文件名和 postflight；
  2. 把这些首帧拷回本机 data/vqa/accept/mirror/<host>/（只读副本）；
  3. 本机出四项标签（tools/vqa/accept.label：身份 / 服装（含谁穿什么、水晶甲）/ 提示词 / 人数；人数测量经 rssh 连 gpu36，看图走隧道）；
  4. 写回出图主机 repo 的 data/vqa/accept/epNN.json（数据文件，先写 .tmp 再 mv）——DEBUG-RSI 的接口：
     [{"key": "epNN-SN|image", "file": 当前首帧文件名, "ok": pass|fail|untested, ...}]

    python tools/vqa/accept_batch.py ep01 ep07 ep09 ep10 ep03 ep05        # gpu33 的集
    python tools/vqa/accept_batch.py --host gpu36 ep02 ep04 ep06 ep08     # 也可显式指定；缺省按集号查主机分工
"""
from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
HOST_OF = {"ep01": "gpu33", "ep03": "gpu33", "ep05": "gpu33", "ep07": "gpu33", "ep09": "gpu33", "ep10": "gpu33",
           "ep02": "gpu36", "ep04": "gpu36", "ep06": "gpu36", "ep08": "gpu36"}     # 总调度 11-02 17:3x 给的分工
MIRROR = ROOT / "data" / "vqa" / "accept" / "mirror"

LIST_SRC = r'''
import json, glob, os, sys, base64
ep, repo = sys.argv[1], sys.argv[2]
out = []
for tj in sorted(glob.glob(os.path.join(repo, "data/renders", ep, "S*", "takes.json"))):
    sid = ep + "-" + os.path.basename(os.path.dirname(tj))
    try:
        d = json.load(open(tj, encoding="utf-8"))
    except Exception as e:
        out.append({"sid": sid, "error": repr(e)[:200]}); continue
    n = (d.get("active") or {}).get("image")
    t = next((x for x in d.get("takes") or [] if x.get("stage") == "image" and x.get("n") == n), None)
    if not t or not t.get("file"):
        continue
    p = os.path.join(repo, "data", t["file"])
    if not os.path.exists(p):
        out.append({"sid": sid, "file": t["file"], "error": "文件不在"}); continue
    out.append({"sid": sid, "n": n, "file": t["file"], "postflight": t.get("postflight") or {},
                "b64": base64.b64encode(open(p, "rb").read()).decode()})
print("@@LIST@@" + json.dumps(out))
'''


def _remote(host: str, cmd: str, data: str | None = None, timeout: int = 900) -> str:
    """远端命令一律走 tools/netfix/rssh.run_retry（常驻主连接，不在跳板上新建连接，K-OPS-N09）"""
    from tools.netfix.rssh import run_retry
    r = run_retry(host, cmd, input=data, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"{host} 远端命令失败 rc={r.returncode}：{(r.stderr or '')[-300:]}")
    return r.stdout


def repo_of(host: str) -> str:
    from tools.factory import hosts as H
    return H.load()["hosts"][host]["repo"].rstrip("/")


def fetch(host: str, ep: str) -> list[dict]:
    repo = repo_of(host)
    _remote(host, "cat > /tmp/vqagate_accept_list.py", LIST_SRC, timeout=60)
    out = _remote(host, f"python3 /tmp/vqagate_accept_list.py {ep} {repo}", timeout=900)
    line = next((ln for ln in out.splitlines() if ln.startswith("@@LIST@@")), None)
    if not line:
        raise RuntimeError(f"{host} {ep} 没拿到首帧清单")
    rows = json.loads(line[8:])
    d = MIRROR / host / ep
    d.mkdir(parents=True, exist_ok=True)
    for r in rows:
        if r.get("b64"):
            p = d / Path(r["file"]).name
            p.write_bytes(base64.b64decode(r.pop("b64")))
            r["local"] = str(p)
    return rows


def run_ep(ep: str, host: str | None = None) -> list[dict]:
    from tools.vqa import accept as ACC
    host = host or HOST_OF[ep]
    out = []
    for r in fetch(host, ep):
        key = f"{r['sid']}|image"
        if r.get("error"):
            out.append({"key": key, "file": Path(str(r.get("file") or "")).name, "ok": "untested", "why": r["error"]})
            continue
        lab = ACC.label(r["sid"], "image", r["local"], r["postflight"], via_tunnel=True)
        out.append({"key": key, "file": Path(r["file"]).name, "n": r["n"], **lab})
        print(key, lab["ok"], *(f"{k}={lab[k]['status']}" for k in ACC.ORDER), flush=True)
    data = json.dumps(out, ensure_ascii=False, indent=1)
    local = ROOT / "data" / "vqa" / "accept" / f"{ep}.{host}.json"
    tmp = local.with_suffix(".json.tmp")
    tmp.write_text(data, encoding="utf-8")
    os.replace(tmp, local)
    repo = repo_of(host)
    _remote(host, f"mkdir -p {repo}/data/vqa/accept && cat > {repo}/data/vqa/accept/{ep}.json.tmp && mv {repo}/data/vqa/accept/{ep}.json.tmp {repo}/data/vqa/accept/{ep}.json",
         data, timeout=120)
    print(f"写回 {host}:{repo}/data/vqa/accept/{ep}.json（{len(out)} 条）", flush=True)
    return out


def main(argv: list[str]) -> int:
    host = None
    if argv[:1] == ["--host"]:
        host, argv = argv[1], argv[2:]
    for ep in argv:
        run_ep(ep, host)
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main(sys.argv[1:]))
