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
import os
import shutil
import time
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PULL = ROOT / "data" / "_offline_pull"
OWN = {"gpu33": {1, 3, 5}, "gpu36": {2, 4, 6, 7, 8, 9, 10}}      # 旧分集（partition.json 读不到时用）
OWN_IMG, OWN_VID = dict(OWN), dict(OWN)
try:   # NETFIX 22:2x：按集归属改读 config/netfix/partition.json——图 / 账本按 images，视频按 video（ep10 图归笔记本、视频归 gpu36）
    sys.path.insert(0, str(ROOT / "tools/factory"))
    import state_paths as _SP   # ARCH_ROADMAP §10（NETFIX 11-02，CONSENT AUTOPILOT → NETFIX）：先读 data/state/netfix/partition.json，没有再读旧位置并留痕
    _part = _SP.read_state("netfix/partition")
    OWN_IMG = {h: {int(x) for x in v} for h, v in (_part.get("images") or {}).items() if h != "laptop"} or OWN_IMG
    OWN_VID = {h: {int(x) for x in v} for h, v in (_part.get("video") or {}).items() if h != "laptop"} or OWN_VID
    OWN = {h: OWN_IMG.get(h, set()) | OWN_VID.get(h, set()) for h in set(OWN_IMG) | set(OWN_VID)}
except (OSError, ValueError, RuntimeError):   # arch-ok: 分区读不到 → 用上面的旧分集（显式回退，旧行为）
    pass


_OWN_SIG = None


def _reload_own() -> None:
    """A-06（AUDIT-M / NETFIX 11-02）：分区文件变了就重读（原来只在 import 时读一次，puller 常驻进程一直用启动时的快照）"""
    global OWN_IMG, OWN_VID, OWN, _OWN_SIG
    if os.environ.get("PYTEST_CURRENT_TEST") and not os.environ.get("NETFIX_TEST_RELOAD"):
        return                                    # 单元测试自己设 OWN_IMG / OWN_VID，不读真机分区
    try:
        sys.path.insert(0, str(ROOT / "tools/factory"))
        import state_paths as _SP
        f = _SP.state_path("netfix/partition") if _SP.state_path("netfix/partition").is_file() else _SP.legacy_path("netfix/partition")
        sig = (str(f), f.stat().st_mtime)
        if sig == _OWN_SIG:
            return
        part = _SP.read_state("netfix/partition")
        OWN_IMG = {h: {int(x) for x in v} for h, v in (part.get("images") or {}).items() if h != "laptop"} or OWN_IMG
        OWN_VID = {h: {int(x) for x in v} for h, v in (part.get("video") or {}).items() if h != "laptop"} or OWN_VID
        OWN = {h: OWN_IMG.get(h, set()) | OWN_VID.get(h, set()) for h in set(OWN_IMG) | set(OWN_VID)}
        _OWN_SIG = sig
    except (OSError, ValueError, RuntimeError):   # arch-ok: 分区读不到 → 沿用上一次的归属（显式回退）
        pass


VIDEO_STAGES = {"video"}


def own_stages(host: str, ep: int) -> set:
    """A-06 ②：按 stage 判归属——一个镜的 takes.json 里图归 images 分区那台、视频归 video 分区那台（原来整份按 images 判，
    ep02 图改划 gpu33 后，gpu36 上视频的作废 / 清空当前全被 skipped:不归这台，FEEDBACK 11-02 ep02-S3）"""
    _reload_own()
    out = set()
    if ep in OWN_IMG.get(host, set()):
        out |= {"image", "last"}
    if ep in OWN_VID.get(host, set()):
        out |= VIDEO_STAGES
    return out


def owns(host: str, rel: str, ep: int) -> bool:
    """data/renders/**、data/producer/** 是出图侧 → images 归属；其余（video / episodes / music / review）→ video 归属。
    例外：takes.json 两台都可能有份（按 stage 在 merge_takes 里分），渲染目录里的视频文件归 video 分区"""
    _reload_own()
    if rel.startswith("data/renders/") and rel.endswith("/takes.json"):
        return bool(own_stages(host, ep))
    if rel.startswith("data/renders/") and (rel.endswith("/video.mp4") or "/takes/video_" in rel):
        return ep in OWN_VID.get(host, set())
    m = OWN_IMG if rel.startswith(("data/renders/", "data/producer/")) else OWN_VID
    return ep in m.get(host, set())
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
    if ep is None or ep not in OWN_IMG.get(host, set()):      # 对象表都是出图侧（producer）
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
                add = [x for x in rv if x not in lv and (_ep(x) in OWN_IMG.get(host, set()))]
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
        _atomic_json(dst, out)          # A-12：原子写
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


LOCAL_STICKY = ("quarantined",)       # 本地对版本的处置，服务器那份永远不能盖掉（UIRSI r42：整份覆盖冲掉了 72 个“已隔离”标记）


def merge_takes_docs(r: dict, l: dict, stages: set | None = None, base: dict | None = None) -> tuple[dict, int, int, dict]:
    """merge_takes 的纯函数版：远端 r 并进本地 l → (合并后, 新增, 更新, 换号表 {(stage, 远端n): 本地n})。
    stages（NETFIX 11-02 A-06）：只收这些 stage 的版本和指针（另一台负责的 stage 一概不动）；None = 全收（旧行为）。
    base：上次从这台收下的同一份 takes.json——它有、这次没有的 active / locked 键 = 服务器清空了当前版，本地跟着清（结果里 _cleared 列出）"""
    if stages is not None:
        r = {**r, "takes": [t for t in r.get("takes") or [] if t.get("stage") in stages]}
    lt = {(t.get("stage"), t.get("n")): t for t in l.get("takes") or []}
    # K-OPS-W27（11-02 ep08/09 两台各自往上编号）：同一 (stage, n) 在两边可能是不同的图。先按文件认版本：
    # 本地已有同文件的版本 → 用本地编号；编号撞了但文件不同 → 远端这条改用新编号追加（记 renumbered），active / locked 跟着换号
    by_file = {(t.get("stage"), t.get("file")): t for t in l.get("takes") or [] if t.get("file")}
    next_n: dict = {}
    for t in list(l.get("takes") or []) + list(r.get("takes") or []):
        next_n[t.get("stage")] = max(next_n.get(t.get("stage"), 0), int(t.get("n") or 0))
    remap: dict = {}
    out_takes, added, updated = [], 0, 0
    seen = set()
    for t in r.get("takes") or []:
        k = (t.get("stage"), t.get("n"))
        same = by_file.get((t.get("stage"), t.get("file"))) if t.get("file") else None
        if same is not None and same.get("n") != t.get("n"):
            remap[k] = same.get("n")
            k = (t.get("stage"), same.get("n"))
            t = {**t, "n": same.get("n")}
        elif k in lt and t.get("file") and lt[k].get("file") and lt[k].get("file") != t.get("file"):
            next_n[t.get("stage")] += 1
            nn = next_n[t.get("stage")]
            remap[k] = nn
            t = {**t, "n": nn, "renumbered": {"from_n": k[1], "why": "两边同号不同图（K-OPS-W27）"}}
            k = (t.get("stage"), nn)
        seen.add(k)
        if k in lt:
            m = {**lt[k], **t}
            for f in LOCAL_STICKY:
                if f in lt[k]:
                    m[f] = lt[k][f]
                elif f in m and f not in lt[k]:
                    pass                      # 服务器上隔离的也收（本地还没处置过）
            if m != lt[k]:
                updated += 1
            out_takes.append(m)
        else:
            out_takes.append(t)
            added += 1
    out_takes += [t for k, t in lt.items() if k not in seen]
    out_takes.sort(key=lambda t: (str(t.get("stage")), int(t.get("n") or 0)))
    quarantined = {(t.get("stage"), t.get("n")) for t in out_takes if t.get("quarantined")}
    # A-12（FACTORY 21:3x）：项目方的决定（定稿 locked / locked_src / locked_history、master_gate）以笔记本为准——服务器只是执行端，
    # 以前顶层按“服务器覆盖”合并，服务器上的旧值会盖掉笔记本上项目方刚点的定稿
    out = {**l, **{k: v for k, v in r.items() if k != "takes" and not (k in OWNER_KEYS and k in l)}}
    cleared = []
    for key in ("active", "locked"):
        sv, lv = dict(r.get(key) or {}), dict(l.get(key) or {})
        if stages is not None:
            sv = {st: n for st, n in sv.items() if st in stages}
            bv = {st: n for st, n in dict((base or {}).get(key) or {}).items() if st in stages}
            for st in bv:                                  # 祖先有、服务器现在没有 → 服务器清空了这个 stage 的当前版
                if st not in sv and st in lv:
                    lv.pop(st)
                    cleared.append((key, st))
        sv = {st: remap.get((st, n), n) if not isinstance(n, dict) else n for st, n in sv.items()}   # 远端换了号的版本，指针跟着换
        if not sv and not lv:
            continue
        merged = {**sv, **lv} if key in OWNER_KEYS else {**lv, **sv}      # 定稿：笔记本有就以笔记本为准（A-12）
        for stage, n in list(merged.items()):
            if (stage, n) in quarantined:
                if lv.get(stage) is not None and (stage, lv.get(stage)) not in quarantined:
                    merged[stage] = lv[stage]
                else:
                    merged.pop(stage, None)
        out[key] = merged
    out["takes"] = out_takes
    if cleared:
        out["_cleared"] = cleared
    return out, added, updated, remap


def _sid_run_of(dst: Path) -> tuple[str, str | None] | None:
    """仓库内 data/renders/[<run>/]epNN/SN/takes.json → (镜号, run)；不在仓库渲染目录下（测试临时目录）→ None"""
    try:
        parts = dst.resolve().relative_to((ROOT / "data" / "renders").resolve()).parts
    except ValueError:
        return None
    if len(parts) == 3 and parts[2] == "takes.json":
        return f"{parts[0]}-{parts[1]}", None
    if len(parts) == 4 and parts[3] == "takes.json":
        return f"{parts[1]}-{parts[2]}", parts[0]
    return None


def _quarantine_current(dst: Path, cleared: list) -> list:
    """服务器清空了当前视频：笔记本渲染目录里的 video.mp4 移进 data/_quarantine/netfix_sync_<日>/（不删）"""
    moved = []
    if any(st in VIDEO_STAGES for key, st in cleared if key == "active"):
        v = dst.parent / "video.mp4"
        if v.exists():
            q = ROOT / "data/_quarantine" / time.strftime("netfix_sync_%Y%m%d") / v.relative_to(ROOT)
            q.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(v), str(q))
            moved.append(str(q.relative_to(ROOT)))
    return moved


def merge_takes(src: Path, dst: Path, dry: bool = False, host: str | None = None, ep: int | None = None) -> str:
    """data/renders/**/takes.json 按版本（stage, n）逐条合并（UIRSI r42，总调度 01:3x）：
      · 服务器有、本地没有的版本 → 收；本地有、服务器没有的 → 留；
      · 两边都有 → 服务器字段覆盖同名字段（契约 / 打分是服务器上算的），本地独有字段保留，LOCAL_STICKY（已隔离）一律用本地的；
      · 顶层（active / locked / master_gate …）同理按键合并；但服务器的 active / locked 若指向本地已隔离的版本，保留本地的值；
      · restore_log 等本地独有的顶层键保留"""
    r = json.loads(src.read_text(encoding="utf-8"))
    stages = own_stages(host, ep) if host and ep else None
    base_p = (PULL / "_base" / host / dst.relative_to(ROOT)
              if host and dst.is_relative_to(ROOT) and not os.environ.get("PYTEST_CURRENT_TEST") else None)   # 测试不读写真机祖先
    base = json.loads(base_p.read_text(encoding="utf-8")) if base_p and base_p.exists() else None
    sid_run = _sid_run_of(dst)
    if sid_run and not dry:                  # K-OPS-W29：仓库内的 takes.json 只经 mutate_takes 写（锁里现读本地再并，不会盖掉并发写入）
        sys.path.insert(0, str(ROOT / "services/render_router"))
        from ns_render import pipeline as P
        cnt = {}

        def _fn(local):
            o, a, u, _rm = merge_takes_docs(r, local if local.get("takes") is not None else {"takes": []}, stages, base)
            cnt.update(a=a, u=u, cleared=o.pop("_cleared", []))
            return o
        P.mutate_takes(sid_run[0], _fn, op="merge_pull.merge_takes", by="ops/offline/merge_pull.py", run=sid_run[1])
        _save_base(base_p, r)
        moved = _quarantine_current(dst, cnt.get("cleared") or [])
        return f"takes+{cnt.get('a', 0)}~{cnt.get('u', 0)}" + (f" cleared={cnt['cleared']} moved={moved}" if cnt.get("cleared") else "")
    l = json.loads(dst.read_text(encoding="utf-8")) if dst.exists() else {"takes": []}
    out, added, updated, _remap = merge_takes_docs(r, l, stages, base)
    cleared = out.pop("_cleared", [])
    if not dry:
        if dst.exists():
            backup(dst.relative_to(ROOT).as_posix())
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, dst)
        _save_base(base_p, r)
        moved = _quarantine_current(dst, cleared)
        if cleared:
            return f"takes+{added}~{updated} cleared={cleared} moved={moved}"
    return f"takes+{added}~{updated}"


OWNER_KEYS = ("locked", "locked_src", "locked_history", "master_gate")   # 项目方决定：笔记本为准（A-12）


def _atomic_json(p: Path, obj) -> None:
    """A-12：先写同目录临时文件再 os.replace（读方不会读到半截文件）"""
    import os as _os
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + f".{_os.getpid()}.tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    _os.replace(tmp, p)


def _save_base(base_p: Path | None, r: dict) -> None:
    """记下这次从该台收下的 takes.json（下次三方比较的祖先）"""
    if base_p is None:
        return
    base_p.parent.mkdir(parents=True, exist_ok=True)
    tmp = base_p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(r, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, base_p)


def merge_file(host: str, rel: str, src: Path, att: dict | None = None, dry: bool = False) -> str:
    """并回一个文件的唯一入口（NETFIX puller 与本脚本共用；总调度 01:0x 新架构：传图流水线由 puller 接管，规则仍在这里）。
    host = 文件来自哪台服务器；rel = 仓库相对路径（data/…）；src = 拉回来的本地临时文件。
    → 动作："skipped:<原因>" / "objects+N" / "append+N" / "night_state" / "attempts:N" / "corrupt:<原因>" /
            "new" / "newer" / "older_kept"
    规则（K-OPS-Q20 / W02 / N04）：
      ① 名单外文件不收（SKIP_NAMES、leases、.tmp）；
      ② 带集号的路径只收负责那台的：data/renders/**、data/producer/** 看 partition.images，其余看 partition.video（owns）；
         文件名带 _gpu33 / _gpu36 的只收那台自己的；
      ③ data/producer/attempts.json：负责集的对象收进 att（调用方最后统一写，见 flush_attempts）；
      ④ data/producer/*.json 对象表（master_rejects 等）：按对象合并，对象内 *at 更晚者胜（merge_objects）；
      ⑤ APPEND 日志：只追加本地没有的行，带集号的行只收负责那台的；
      ⑥ night_state.json：按集合并；
      ⑦a data/renders/**/takes.json：按版本逐条合并，本地“已隔离”（quarantined）永远保留（merge_takes，UIRSI r42）；
      ⑦ 其余：先验完整（图片解码、mp4 有 moov、json 能解析、不是本地文件的截断前缀，pulled_problem），再“新者为准”覆盖，
         覆盖前备份到 data/_offline_pull/_backup/。永不删除本地文件"""
    import re as _re
    dst = ROOT / rel
    if src.name in SKIP_NAMES or "/leases/" in rel or rel.endswith(".tmp"):
        return "skipped:名单外"
    m = _re.search(r"(?:^|/|_)ep(\d{2})(?:\b|-|_|/)", rel)
    if m and not owns(host, rel, int(m.group(1))):
        return "skipped:不归这台"
    mh = _re.search(r"_(gpu33|gpu36)[._]", rel)
    if mh and mh.group(1) != host:
        return "skipped:另一台的文件"
    if rel == "data/producer/attempts.json":
        d = json.loads(src.read_text(encoding="utf-8"))
        n = 0
        for k, v in d.items():
            if ep_of_obj(k) in OWN_IMG.get(host, set()) and att is not None:
                att[k] = v
                n += 1
        return f"attempts:{n}"
    if is_object_file(rel):
        if dry:
            return "objects(dry)"
        try:
            return f"objects+{merge_objects(rel, src, dst, host)}"
        except (ValueError, OSError) as e:
            return f"corrupt:{e!r}"[:200]
    if rel in APPEND:
        have = set(dst.read_text(encoding="utf-8").splitlines()) if dst.exists() else set()
        new = [ln for ln in src.read_text(encoding="utf-8").splitlines() if ln and ln not in have]
        own = OWN_IMG if rel.startswith("data/producer/") else OWN_VID
        new = [ln for ln in new if not (mm := _re.search(r'"obj": "[a-z]+:ep(\d{2})', ln)) or int(mm.group(1)) in own.get(host, set())]
        if new and not dry:
            backup(rel)
            with open(dst, "a", encoding="utf-8") as f:
                f.write("\n".join(new) + "\n")
        return f"append+{len(new)}"
    if rel.endswith("video/night_state.json"):
        s_ = json.loads(src.read_text(encoding="utf-8"))
        l_ = json.loads(dst.read_text(encoding="utf-8")) if dst.exists() else {"eps": {}}
        for e, x in (s_.get("eps") or {}).items():
            if int(e) in OWN_VID.get(host, set()):
                l_.setdefault("eps", {})[e] = x
                if e in (s_.get("pending_shots") or {}):
                    l_.setdefault("pending_shots", {})[e] = s_["pending_shots"][e]
        if not dry:
            backup(rel)
            _atomic_json(dst, l_)       # A-12：原子写
        return "night_state"
    bad = pulled_problem(src, dst)
    if bad:
        return f"corrupt:{bad}"
    if rel.startswith("data/renders/") and rel.endswith("/takes.json"):      # ⑦a 版本表：逐条合并，本地“已隔离”永远保留
        try:
            return merge_takes(src, dst, dry, host, int(m.group(1)) if m else None)
        except TimeoutError:
            raise          # AUDIT-M 11-02：拿不到 takes 锁不是“坏文件”——交给调用方记 error 下轮重试（puller 不 ack），不能记 corrupt 被 ack 丢掉
        except (ValueError, OSError) as e:
            return f"corrupt:{e!r}"[:200]
    if not dst.exists():
        act = "new"
    elif src.stat().st_mtime > dst.stat().st_mtime:
        act = "newer"
    else:
        return "older_kept"
    if not dry:
        backup(rel)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    return act


def flush_attempts(att: dict, dry: bool = False) -> int:
    """merge_file 收集的 attempts 对象统一写回 data/producer/attempts.json（按对象覆盖负责集的对象）"""
    if not att:
        return 0
    p = ROOT / "data/producer/attempts.json"
    cur = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    cur.update(att)
    if not dry:
        backup("data/producer/attempts.json")
        _atomic_json(p, cur)            # A-12：原子写（共享账本 attempts.json）
    return len(att)


def main() -> int:
    stats: dict = {}
    att: dict = {}
    only = os.environ.get("MERGE_ONLY_HOST")          # resident_sync.pull 传这个变量，原来没人读（AUDIT-M 11-02）
    for host in ((only,) if only else ("gpu33", "gpu36")):
        base = PULL / host
        if not base.exists():
            continue
        for src in sorted(p for p in base.rglob("*") if p.is_file()):
            rel = src.relative_to(base).as_posix()
            if not rel.startswith(("data/", "docs/")):
                # puller 暂存 <iid>/<rel> 由 puller 自己并；原来这里把它当仓库相对路径 copy2，写出了仓库根 2026110*_take/ 脏目录（AUDIT-M 11-02）
                continue
            act = merge_file(host, rel, src, att, DRY)
            k = act.split(":")[0].split("+")[0]
            stats[k] = stats.get(k, 0) + 1
            if act.startswith(("objects", "append", "corrupt")):
                print(host, rel, act)
    n = flush_attempts(att, DRY)
    if n:
        print("attempts.json merged objects:", n)
    print("merge", "(dry)" if DRY else "", stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
