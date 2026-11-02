"""改视频分区（night 的 video/hosts.json：集 → 出视频的主机）。前置检查（K-OPS-E25 同理）：要搬走的集在原主机 vidgen 上
不能已有出片 / 在出，否则拒绝（会重复出）。原文件先备份到 data/_quarantine/debug_rsi_20261102/。
在服务器 repo 目录跑（经 rsh 从 stdin 喂给 python3 -）：
  python3 video_rehost.py <video repo（video10_srv）> <本机名> <集=主机,…> [--apply]
"""
import json
import os
import shutil
import sys
import tempfile
import time

vrepo, me, spec = sys.argv[1], sys.argv[2], sys.argv[3]
RUN = json.load(open("config/pipeline/runs.json", encoding="utf-8"))["primary"]   # 总调度 11-02：不写死剧名（arch_scan hard_run）
VID = f"data/pipeline/runs/{RUN}/video"
hp = os.path.join(VID, "hosts.json")
hosts = json.load(open(hp, encoding="utf-8"))
st = json.load(open(os.path.join(vrepo, VID, f"state_{me}.json"), encoding="utf-8")).get("shots") or {}
want = dict(x.split("=") for x in spec.split(","))
bad = []
for ep, h in want.items():
    if hosts.get(ep) == me and h != me:      # 从本机搬走：本机 vidgen 不能已有出片 / 在出
        used = [s for s, r in st.items() if int(s[2:4]) == int(ep) and (r.get("renders") or [])]
        if used:
            bad.append({"ep": ep, "shots_with_renders": used})
print(json.dumps({"host": me, "before": {k: hosts.get(k) for k in want}, "want": want, "blocked": bad}, ensure_ascii=False))
if "--apply" in sys.argv and not bad:
    q = "data/_quarantine/debug_rsi_20261102"
    os.makedirs(q, exist_ok=True)
    shutil.copy2(hp, os.path.join(q, f"video_hosts.{time.strftime('%H%M%S')}.json"))
    hosts.update(want)
    fd, tmp = tempfile.mkstemp(dir=VID, prefix="hosts.", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(hosts, f, ensure_ascii=False, indent=1)
    os.replace(tmp, hp)
    print(json.dumps({"applied": want}, ensure_ascii=False))
