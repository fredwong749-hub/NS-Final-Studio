"""offline_20261101：把 gpu33 / gpu36 离线期间改过的文件并回笔记本（resume_from_gpu33.sh 调用）。

规则：
  - 只处理冻结（FREEZE_TS）之后服务器上改过的文件（拉回时已筛好，放在 data/_offline_pull/<host>/ 下）。
  - 按集分工，两台不碰同一个镜：普通文件“新者为准”（服务器文件比笔记本新才覆盖），笔记本没有的直接放进去。
  - 永不删除笔记本文件；被覆盖的旧文件先备份到 data/_offline_pull/_backup/<相对路径>。
  - 两台都会写的共享文件按对象合并：
      data/producer/attempts.json                     按对象 key（first:epNN-SX）取负责该集那台的值
      data/producer/ 下其它 JSON（master_rejects 等）  按对象合并：别的集留笔记本；本机集按对象 *at 新者为准（K-OPS-Q20）
      data/producer/log.jsonl、current_changes.jsonl  追加：服务器上笔记本没有的行，按 ts 排序后追加
      .../video/night.log                             同上（追加没有的行）
      .../video/night_state.json                      eps 按 host 合并
  - 不拉回：data/producer/control.json（笔记本保持自己的）、leases/、*.pid、heartbeat.json、registry.json（producer 会重建）。
用法：python ops/offline/merge_pull.py [--dry]
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PULL = ROOT / "data" / "_offline_pull"
OWN = {"gpu33": {1, 3, 5}, "gpu36": {2, 4, 6, 7, 8, 9, 10}}
SKIP_NAMES = {"control.json", "heartbeat.json", "producer.pid", "registry.json", "night.pid"}
APPEND = {"data/producer/log.jsonl", "data/producer/current_changes.jsonl",
          "data/pipeline/runs/series10_v1/video/night.log"}
DRY = "--dry" in sys.argv


def ep_of_obj(k: str) -> int | None:
    import re
    m = re.search(r"ep(\d+)", k)
    return int(m.group(1)) if m else None


OBJ_DIRS = ("data/producer/",)
OBJ_SKIP = {"data/producer/attempts.json"}        # attempts 另有专门合并（上面）


def is_object_file(rel: str) -> bool:
    """data/producer/ 下的 JSON（master_rejects.json、be_rescore_keys.json、outer_suspects.json、round2_hold_for_reflock.json …）
    是多集共享的对象表：整文件按修改时间覆盖会丢掉另一台 / 笔记本对别的集做的改动（11-01 实查：master_rejects 的 unwait 丢失）"""
    return rel.startswith(OBJ_DIRS) and rel.endswith(".json") and rel not in OBJ_SKIP and rel.count("/") == 2


def _ep(key: str) -> int | None:
    import re
    m = re.search(r"ep(\d{2})", str(key))
    return int(m.group(1)) if m else None


def _ts(v) -> str:
    """对象里所有 *at 字段（ISO 字符串）的最大值——判断同一对象哪边改得更晚"""
    best = ""
    if isinstance(v, dict):
        for k, x in v.items():
            if str(k).endswith("at") and isinstance(x, str) and x[:2] == "20":
                best = max(best, x)
            elif isinstance(x, (dict, list)):
                best = max(best, _ts(x))
    elif isinstance(v, list):
        for x in v:
            best = max(best, _ts(x))
    return best


def pick(local, remote, ep: int | None, host: str):
    """同一对象：不是这台负责的集 → 留笔记本；是 → 两边谁的 *at 更晚用谁（同样晚用服务器的）；只有一边有 → 用有的那边"""
    if remote is None:
        return local
    if ep is None or ep not in OWN[host]:
        return local if local is not None else remote
    if local is None:
        return remote
    return local if _ts(local) > _ts(remote) else remote


def merge_objects(rel: str, src: Path, dst: Path, host: str) -> int:
    """→ 改动的对象数。支持三种形状：{对象键: 值}、{…, "<列表>": [{"obj": …}, …]}、{…, "keys": [字符串]}（并集）"""
    r = json.loads(src.read_text(encoding="utf-8"))
    l = json.loads(dst.read_text(encoding="utf-8")) if dst.exists() else {}
    if not isinstance(r, dict) or not isinstance(l, dict):
        return 0
    out, n = dict(l), 0
    for k in set(r) | set(l):
        lv, rv = l.get(k), r.get(k)
        if isinstance(lv, list) or isinstance(rv, list):
            lv, rv = lv or [], rv or []
            if all(isinstance(x, str) for x in lv + rv):              # keys 列表：并集（只收这台负责集的新键）
                add = [x for x in rv if x not in lv and (_ep(x) in OWN[host])]
                out[k], n = lv + add, n + len(add)
            elif all(isinstance(x, dict) and "obj" in x for x in lv + rv):
                lm = {x["obj"]: x for x in lv}
                for x in rv:
                    y = pick(lm.get(x["obj"]), x, _ep(x["obj"]), host)
                    if y is not lm.get(x["obj"]):
                        lm[x["obj"]], n = y, n + 1
                out[k] = list(lm.values())
            continue
        if _ep(k) is None and k in l:                                  # 文件级元数据（note / made_at）：留笔记本
            continue
        y = pick(lv, rv, _ep(k), host)
        if y is not lv:
            out[k], n = y, n + 1
    if n:
        backup(rel)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return n


def pulled_problem(src: Path, dst: Path) -> str | None:
    """WORKFLOW 11-01（K-OPS-W02）：offline_20261101 并回时 7 张截断的设定图（服务器副本是笔记本原图的前缀）按“新者为准”
    覆盖了笔记本好图。覆盖前先查：图片 / JSON 解码不全，或比本地小且是本地文件的字节前缀（传一半）→ 返回原因，不覆盖"""
    sys.path.insert(0, str(ROOT / "tools" / "pipeline"))
    from remote_preflight import file_problem
    why = file_problem(src)
    if why:
        return why
    if dst.is_file() and src.stat().st_size < dst.stat().st_size:
        n = src.stat().st_size
        with open(src, "rb") as a, open(dst, "rb") as b:
            if a.read(n) == b.read(n):
                return f"是本地文件的截断前缀（{n} / {dst.stat().st_size} 字节）"
    return None


def backup(rel: str):
    dst = ROOT / rel
    if dst.exists():
        b = PULL / "_backup" / rel
        if not b.exists():
            b.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(dst, b)


def main() -> int:
    stats = {"new": 0, "newer": 0, "older_kept": 0, "merged": 0, "skipped": 0}
    att = {}
    for host in ("gpu33", "gpu36"):
        base = PULL / host
        if not base.exists():
            continue
        for src in sorted(p for p in base.rglob("*") if p.is_file()):
            rel = src.relative_to(base).as_posix()
            dst = ROOT / rel
            if src.name in SKIP_NAMES or "/leases/" in rel or rel.endswith(".tmp"):
                stats["skipped"] += 1
                continue
            # 按集分工：路径里带集号的（renders/epNN、video 下的 epNN-*、episodes/epNN…）只收负责该集那台的；
            # state_<host>.json / vidgen_<host>.log 只收那台自己的（另一台副本里缺文件时 reconcile 会误改别的集，不能并回）
            import re as _re
            m = _re.search(r"(?:^|/|_)ep(\d{2})(?:\b|-|_|/)", rel)
            if m and int(m.group(1)) not in OWN[host]:
                stats["skipped"] += 1
                continue
            mh = _re.search(r"_(gpu33|gpu36)[._]", rel)
            if mh and mh.group(1) != host:
                stats["skipped"] += 1
                continue
            if rel == "data/producer/attempts.json":
                d = json.loads(src.read_text(encoding="utf-8"))
                for k, v in d.items():
                    e = ep_of_obj(k)
                    if e in OWN[host]:
                        att[k] = v
                continue
            if is_object_file(rel):                 # 多集共享的对象文件：按对象合并（K-OPS-Q20 / W02）
                if not DRY:
                    try:
                        n = merge_objects(rel, src, dst, host)
                    except (ValueError, OSError) as e:
                        print(f"!! skip corrupt {host} {rel}: {e!r}"[:200])
                        continue
                    stats["merged"] += 1
                    print(f"objects {host} {rel} +{n}")
                continue
            if rel in APPEND:
                have = set(dst.read_text(encoding="utf-8").splitlines()) if dst.exists() else set()
                import re as _re
                new = [ln for ln in src.read_text(encoding="utf-8").splitlines() if ln and ln not in have]
                # 带对象 / 集号的行只收负责那台的（另一台副本缺文件时的误判不并回）
                new = [ln for ln in new if not (mm := _re.search(r'"obj": "[a-z]+:ep(\d{2})', ln)) or int(mm.group(1)) in OWN[host]]
                if new and not DRY:
                    backup(rel)
                    with open(dst, "a", encoding="utf-8") as f:
                        f.write("\n".join(new) + "\n")
                stats["merged"] += 1
                print(f"append {host} {rel} +{len(new)}")
                continue
            if rel.endswith("video/night_state.json"):
                s = json.loads(src.read_text(encoding="utf-8"))
                l = json.loads(dst.read_text(encoding="utf-8")) if dst.exists() else {"eps": {}}
                for e, x in (s.get("eps") or {}).items():
                    if int(e) in OWN[host]:
                        l.setdefault("eps", {})[e] = x
                        if e in (s.get("pending_shots") or {}):
                            l.setdefault("pending_shots", {})[e] = s["pending_shots"][e]
                if not DRY:
                    backup(rel)
                    dst.write_text(json.dumps(l, ensure_ascii=False, indent=1), encoding="utf-8")
                stats["merged"] += 1
                continue
            bad = pulled_problem(src, dst)          # K-OPS-W02：拉回的文件读不全 / 是本地文件的截断前缀 → 不覆盖
            if bad:
                stats["corrupt_skipped"] = stats.get("corrupt_skipped", 0) + 1
                print(f"!! skip corrupt {host} {rel}: {bad}")
                continue
            if not dst.exists():
                stats["new"] += 1
            elif src.stat().st_mtime > dst.stat().st_mtime:
                stats["newer"] += 1
            else:
                stats["older_kept"] += 1
                continue
            if not DRY:
                backup(rel)
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
    if att:
        p = ROOT / "data/producer/attempts.json"
        cur = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        cur.update(att)
        if not DRY:
            backup("data/producer/attempts.json")
            p.write_text(json.dumps(cur, ensure_ascii=False, indent=1), encoding="utf-8")
        print("attempts.json merged objects:", len(att))
    print("merge", "(dry)" if DRY else "", stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
