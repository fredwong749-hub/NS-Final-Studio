"""一次性存量并回（NETFIX 11-02，总调度 18:2x 批准）：两边 takes.json 不一致的镜按服务器为准、按 stage 归属并回。
  · 范围 = puller 一致性比对（takes_scan）列出的漂移：第二季笔记本没有的、第一季当前版不一致的；
  · 并回前把本地 takes.json 复制进 data/_quarantine/netfix_backfill_<日>/（不删），再经 merge_pull.merge_file 按 stage 合并；
  · 并完把各镜“当前版”（active 指向的 take 文件）里笔记本还没有的原图 / 视频写进 data/netfix/fetch_queue.jsonl，
    由 puller 按队列顺序按需拉（第一季在前，按集、镜号排；视频排在图后面）。
  .venv/Scripts/python.exe tools/netfix/takes_backfill.py [--dry]
"""
from __future__ import annotations

import io
import json
import re
import shutil
import sys
import tarfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "ops/offline"))
import puller as P  # noqa: E402
import merge_pull as MP  # noqa: E402

QUEUE = ROOT / "data/netfix/fetch_queue.jsonl"


def order_key(rel: str, stage: str) -> tuple:
    m = re.search(r"renders/(?:([^/]+)/)?ep(\d{2})/S(\d+)/", rel)
    run, ep, s = (m.group(1) or "", int(m.group(2)), int(m.group(3))) if m else ("~", 99, 99)
    return (1 if run else 0, ep, s, 1 if stage == "video" else 0)     # 第一季在前；同镜先图后视频


def main() -> int:
    dry = "--dry" in sys.argv
    scan = P.takes_scan({})
    drift = scan.get("drift") or []
    targets: dict[str, set] = {}
    for d in drift:
        targets.setdefault(d["host"], set()).add(d["rel"])
    qdir = ROOT / "data/_quarantine" / time.strftime("netfix_backfill_%Y%m%d")
    res = {"merged": 0, "new": 0, "skipped": 0, "errors": 0, "queued": 0, "by_host": {}}
    queue = []
    for host, rels in targets.items():
        rels = sorted(rels)
        tr = P.remote(host, f"cd {P.OFF}/repo && tar cf - -T - 2>/dev/null; true", data=("\n".join(rels) + "\n").encode(), timeout=600)
        got = {}
        try:
            with tarfile.open(fileobj=io.BytesIO(tr.stdout)) as tf:
                for m in tf.getmembers():
                    if m.isfile() and m.name in rels and ".." not in m.name:
                        got[m.name] = tf.extractfile(m).read()
        except tarfile.TarError as e:
            print(host, "tar error", e)
            continue
        hres = {}
        for rel, data in got.items():
            src = P.STAGE / host / "_backfill" / rel
            src.parent.mkdir(parents=True, exist_ok=True)
            src.write_bytes(data)
            dst = ROOT / rel
            if dry:
                hres[rel] = "dry"
                continue
            if dst.exists():
                b = qdir / rel
                b.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dst, b)
            try:
                act = MP.merge_file(host, rel, src)
            except Exception as e:  # noqa: BLE001
                act = f"error:{repr(e)[:120]}"
            hres[rel] = act
            k = "errors" if act.startswith(("error", "corrupt")) else "skipped" if act.startswith("skipped") else "merged"
            res[k] += 1
            if not dst.exists():
                continue
            try:
                td = json.loads(dst.read_text(encoding="utf-8"))
            except ValueError:   # arch-ok: 刚并好的文件读不出 → 记 error，不排拉取
                res["errors"] += 1
                continue
            stages = MP.own_stages(host, int(re.search(r"/ep(\d{2})/", rel).group(1)))
            for st, n in (td.get("active") or {}).items():
                if st not in stages:
                    continue
                t = next((x for x in td.get("takes") or [] if x.get("stage") == st and x.get("n") == n), None)
                f = (t or {}).get("file")
                if f and not (ROOT / "data" / f).exists():
                    queue.append({"host": host, "rel": f"data/{f}", "stage": st, "shot_rel": rel, "at": time.time()})
        res["by_host"][host] = {"targets": len(rels), "got": len(got)}
    queue.sort(key=lambda q: order_key(q["rel"], q["stage"]))
    if not dry and queue:
        with open(QUEUE, "a", encoding="utf-8") as fh:
            for q in queue:
                fh.write(json.dumps(q, ensure_ascii=False) + "\n")
    res["queued"] = len(queue)
    res["drift_before"] = len(drift)
    print(json.dumps(res, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
