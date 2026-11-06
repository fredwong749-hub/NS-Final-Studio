"""“出图”页的索引（ASSETUX 1b，L-123 同批；项目方 16:4x：“‘出图’那个 uiux 点不了，里面应该是全部 ep 的每一个镜头的图片管理”）。

GET /api/frames-index?ep=&status=&char=
  → {episodes:[{ep, shots:[{id, index, chars:[cid], first:{…}, last:{…}, main:{kind,word}|null}]}],
     counts:{shots, missing, new, best, final}, gen:{running, queued, eta_at}}
每格（first / last）= {n, url, state: none|current|final|fallback, new_n / new_url（有一版比当前新、还没选用 → “新”）, gen:{state, eta_s, job_id, started_at, created_at}|None,
  fallback:{mode, word, why, at, by}|None}
  state：none = 缺图；final = 已定稿（takes.json locked）；current = 当前版（没定稿）；fallback = 尾帧兜底生效（L-204 D8：只给首帧，不出尾帧，不算缺图）。
  徽标由前端按 state / new_n / gen 画：当前 / 已定稿 / 新；其余版本不标（L-123：没有“不要”）。
筛选（服务端做，前端不猜）：status = missing（缺图）| new（待你看）| best（尽力版）| final（已定稿）；char = 人物 id；ep = 集号。
只读：不写任何文件。
"""
from __future__ import annotations

import json

from ns_api import swr as _swr
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException

from ns_api import clock as CK  # UIUX-LOOP-2 r6：时间口径单一入口（JST）

ROOT = Path(__file__).resolve().parents[3]
router = APIRouter(tags=["frames-index"])
STATUS = ("missing", "new", "best", "final")
STAGES = (("first", "image"), ("last", "last"))


def _rel(rel: str | None, run: str | None = None) -> str | None:
    """版本文件 rel（相对 data/）→ 本剧目录下的 data/ 相对路径（_url / _present 共用）。W34：先经 render_paths.resolve_rel 把旧口径
    renders/epNN/… 解析到本剧已迁移的位置 renders/<run>/epNN/…（迁移前 / 写入方旧代码留下的 rel 也能出图）；
    解析后仍不在本剧目录下（= V1 文件）→ v1_guard 挡掉（L-126）→ None"""
    from ns_api import v1_guard
    from ns_render import pipeline as _P
    from ns_render import render_paths as RPS
    if not rel:
        return None
    r = rel.replace("\\", "/").lstrip("/")
    r = r[5:] if r.startswith("data/") else r
    if RPS.is_unprefixed(r):
        try:
            q = RPS.resolve_rel(r, data=_P.DATA, run=run)
            r = q.resolve().relative_to(Path(_P.DATA).resolve()).as_posix()
        except (ValueError, OSError):  # arch-ok: 解析不出新位置 = 按原 rel 交给 v1_guard（V1 口径照旧挡掉）
            pass
    r = v1_guard.scoped(r, data_dir=_P.DATA)   # NAVIA：V1 的文件不给 V2 页面（L-126）
    return r.lstrip("/") if r else None


def _url(rel: str | None, run: str | None = None) -> str | None:
    """版本文件 rel（相对 data/）→ /files/ 地址（takes.json 里的 file 相对 data/ 目录：renders/<run>/ep01/…）"""
    r = _rel(rel, run)
    return ("/files/" + r) if r else None


def _present(rel: str | None, run: str | None = None) -> bool:
    """ORPHAN-TAKE（11-06）：这一版的图在不在笔记本上。服务器出的图要经 puller 拉回；没拉到的不能当“新”给项目方看——
    否则格子标“新”却写“文件不在”（项目方：ep01 S5 尾帧“一直出不来”）"""
    from ns_render import pipeline as _P
    r = _rel(rel, run)
    return bool(r) and (Path(_P.DATA) / r).is_file()


def _pending(lst: list[dict], act: int | None, run: str | None) -> dict | None:
    """ORPHAN-TAKE：比当前版新、还给不了项目方看的最新一版及原因——等打分（postflight 没结论）/ 图在传输中（通过了、原图还没拉到）。
    orphan（打分被进程重启打断、系统另出）和没通过的不算“待”，它们归 sys_retry（系统在重出）"""
    from ns_api import takes_ui as TU
    for t in sorted(lst, key=lambda t: t.get("n") or 0, reverse=True):
        n = t.get("n") or 0
        if t.get("quarantined") or t.get("void") or (act is not None and n <= act):
            continue
        u = TU.unscored(t)
        if u == "等打分" or (u and "链路" in u):
            return {"n": n, "word": "等打分", "why": u}
        if not u and _passing(t) and _url(t.get("file"), run) and not _present(t.get("file"), run):
            return {"n": n, "word": "图在传输中", "why": "通过了，原图还没从服务器拉到笔记本"}
    return None


def _script_path(run: str | None):
    """本剧导入稿（tools/autopilot/runs.py script_path）；非 legacy 剧解析到 V1 的 data/import/script_v2.json → None（L-126，不读 V1）"""
    from ns_agent import run_paths as RPA
    if run is None:
        run = RPA.current_run(ROOT)
    m = RPA.runs_module(ROOT)
    if m is None or not run:
        return None
    f = Path(m.script_path(run, ROOT))
    if not m.is_legacy(run, ROOT) and f.resolve() == (ROOT / "data" / "import" / "script_v2.json").resolve():
        return None
    return f


def _script_chars(run: str | None = None) -> dict[str, list[str]]:
    """shot_id → 在画 / 局部的人物 id（本剧剧本 **人物** 行，与出图同口径）；读不到 → {}。
    W34：按剧读该剧导入稿（V2 = data/import/runs/<run>/script_v2.json），不再读全局 data/import/script_v2.json（V1 人物 lin_wan）"""
    try:
        f = _script_path(run)
        if f is None:
            return {}
        doc = json.loads(f.read_text(encoding="utf-8"))
        from ns_agent import asset_refs as AR
        from ns_agent import cast_table as CT
        name_id = CT.char_ids(run)
    except Exception:  # noqa: BLE001  剧本 / 资产模块读不到：人物筛选就没有数据，不影响出图页本身  # arch-ok: 剧本读不到 = 人物筛选没有数据（返回空映射），出图页本身照常显示
        return {}
    out: dict[str, list[str]] = {}
    for ep in doc.get("episodes") or []:
        n = int(ep.get("number") or 0)
        for sh in ep.get("shots") or []:
            ids = [name_id.get(nm, nm) for nm, _pr in AR.cast_on_screen(sh)]
            out[f"ep{n:02d}-S{int(sh.get('index') or 0)}"] = list(dict.fromkeys(ids))
    return out


def _jobs_by_shot() -> dict[tuple[str, str], dict]:
    """(shot, stage) → 在跑 / 排队的 job（stage 统一成 image | last | video）"""
    from ns_api import jobs as J
    out: dict[tuple[str, str], dict] = {}
    try:
        allj = J.all_jobs()
    except Exception:  # noqa: BLE001  任务表读不到：格子只是不显示生成状态  # arch-ok: 任务表读不到 = 格子只是不显示生成状态，调用方当没有在跑的任务
        return out
    for j in allj:
        if j.get("state") not in ("queued", "running") or not j.get("shot_id"):
            continue
        st = {"first": "image"}.get(j.get("stage"), j.get("stage")) or ("video" if j.get("kind") == "video" else None)
        if st in ("image", "last"):
            # UIUX-LOOP-2 r6：任务表是笔记本写的裸美东串；给页面带 +09:00 的 JST（前端 genView 用它算排了多久 / 预计几点，不靠浏览器时区）
            out[(j["shot_id"], st)] = {"state": j["state"], "eta_s": j.get("eta_s"), "job_id": j.get("job_id") or j.get("id"),
                                       "started_at": CK.local_naive_to_jst(j.get("started_at"), with_offset=True),
                                       "created_at": CK.local_naive_to_jst(j.get("created_at"), with_offset=True)}
    return out


def _passing(t: dict) -> bool:
    """给项目方看的版本必须通过验收：没隔离 / 没作废 / 坏图、质检、出图后检任何一项 fail 都不算（takes_ui._verdict 同一口径）"""
    if t.get("quarantined") or t.get("void"):
        return False
    try:
        from ns_api import takes_ui as TU
        return bool(TU._verdict(t, None)[0])
    except Exception:  # noqa: BLE001  判定器出错 = 不给项目方看（宁可少给）  # arch-ok: 判定器出错 = 这个版本不给项目方看（宁可少给），系统内部仍在
        return False


def _edits_by_cell() -> dict[tuple[str, str], dict]:
    """(shot, image|last) → 这一格最近一条没做完的“修改”的现状（排队第 N / 修改中 / 需要你看一眼…）"""
    try:
        from ns_api import frame_edit_queue as FEQ
        snap = FEQ.snapshot()
        out: dict[tuple[str, str], dict] = {}
        for r in FEQ._load()[-300:]:
            ls = FEQ.live_state(r, snap)
            if ls["state"] != "done":
                out[(r["shot"], FEQ.STAGES[r["stage"]])] = {k: ls[k] for k in ("id", "state", "word", "pos", "eta_at", "retry", "msg")}
        return out
    except Exception:  # noqa: BLE001  修改记录读不到不影响出图页本身  # arch-ok: 修改记录读不到 = 格子不显示修改状态，调用方当没有进行中的修改
        return {}


FALLBACK_WORD = {"i2va": "不用尾帧：只给首帧，运镜交给视频模型"}


def last_fallback(takes: dict) -> dict | None:
    """L-204 D8 / L-203 尾帧兜底：takes.json 顶层 last_frame_fallback {mode: i2va, first_n, at, by, why}。
    只有绑定的首帧（first_n）还是当前首帧时才有效（首帧换了，producer 会自动重出尾帧、兜底作废）。
    UIUX-LOOP r2：以前出图页把这类镜的尾帧格写成“在重出 / 新”，视频页写“缺尾帧 · 去出图补”，和已经定下的兜底决定打架。"""
    fb = takes.get("last_frame_fallback")
    if not isinstance(fb, dict) or not fb.get("mode"):
        return None
    cur_first = (takes.get("active") or {}).get("image")
    if fb.get("first_n") is not None and cur_first is not None and fb.get("first_n") != cur_first:
        return None
    mode = str(fb.get("mode"))
    return {"mode": mode, "word": FALLBACK_WORD.get(mode, f"不用尾帧（{mode}）"), "why": str(fb.get("why") or ""), "at": fb.get("at"), "by": fb.get("by")}


def _cell(takes: dict, stage: str, gen: dict | None, edit: dict | None = None, run: str | None = None) -> dict:
    act = (takes.get("active") or {}).get(stage)
    lst = [t for t in takes.get("takes") or [] if t.get("stage") == stage]
    cur = next((t for t in lst if t.get("n") == act), None)
    locked = bool((takes.get("locked") or {}).get(stage)) or bool(cur and cur.get("locked"))
    fb = last_fallback(takes) if stage == "last" else None
    if fb and not cur:
        # 兜底生效、没有当前尾帧：这一格不是“缺图 / 在重出 / 新”，是“不用尾帧”；没通过的旧版本留在系统里，不给项目方看
        return {"n": None, "url": None, "state": "fallback", "new_n": None, "new_url": None, "gen": gen, "sys_retry": 0, "edit": edit,
                "pending": None, "fallback": fb}
    # 项目方 17:0x（ep07-S3 尾帧 #19 Q1 fail 是陌生人，却当“新”给他看）：只有通过验收的版本才算“新”；没通过的留在系统里自动重出
    # W34：被 merge_pull 等并回本剧 takes.json 的 V1 版本（文件只在 V1 目录，v1_guard 不给地址）不算“新”，否则它的 n 更大会把本剧真版本挡住
    # ORPHAN-TAKE（11-06）：图还没拉到笔记本的也不算“新”（_present）；打分没结论的 _passing 已经不认（takes_ui.unscored）。
    # 它们进 pending（“等打分 / 图在传输中”），格子没图可给时写这个字，不写“文件不在”
    from ns_api import takes_ui as TU
    live = [t for t in lst if _passing(t) and _url(t.get("file"), run) and _present(t.get("file"), run)]
    pending = _pending(lst, act, run)
    bad_after = [t for t in lst if not _passing(t) and not t.get("quarantined") and (act is None or (t.get("n") or 0) > act)
                 and not (pending and pending["n"] == t.get("n") and TU.unscored(t))]
    new_n, new_url = None, None
    if live:
        top = max(live, key=lambda t: t.get("n") or 0)
        if act is None or (top.get("n") or 0) > act:
            new_n, new_url = top.get("n"), _url(top.get("file"), run)
    state = "none" if not cur else ("final" if locked else "current")
    return {"n": act if cur else None, "url": _url(cur.get("file"), run) if cur else None, "state": state, "new_n": new_n, "new_url": new_url, "gen": gen,
            "sys_retry": len(bad_after), "edit": edit, "pending": pending, "fallback": fb}


def _ledger_shots(ep: int | None = None) -> list[tuple[int, int]]:
    """活的登记表登记过的镜（shot_status.ledger_shots）；读不到 = []（只按目录）"""
    try:
        from ns_api import shot_status as SS
        return SS.ledger_shots(ep)
    except Exception:  # noqa: BLE001  # arch-ok: 登记表读坏 = 只按 takes.json 目录列镜（旧口径），调用方当没有额外的镜
        return []


def build(ep: int | None = None, status: str | None = None, char: str | None = None, *, renders: Path | None = None,
          run: str | None = None) -> dict:
    """run 不给 = 本进程当前剧（RENDERS）；给了 = 该剧渲染根 + 该剧剧本（V1 文件仍由 v1_guard 挡）"""
    from ns_render import pipeline as P
    from ns_api import shot_status as SS
    if run and renders is None:
        renders = P._run_renders(run)
    base = renders or P.RENDERS
    chars = _script_chars(run)
    jobs = _jobs_by_shot()
    edits = _edits_by_cell()
    eps: dict[int, list[dict]] = {}
    counts = {"shots": 0, "missing": 0, "new": 0, "best": 0, "final": 0}
    # UIUX-LOOP-2 r7：镜的集合 = 有 takes.json 的目录 ∪ 活的登记表登记过的镜（ep02 登记 16 镜、只有 8 镜出过图 → 原来页面只见 8 镜，
    # 排队中的 8 镜根本不显示）。没目录的镜 takes={}，格子写登记表的状态（排队 / 正在出 / 等上一步）
    found: dict[tuple[int, int], Path | None] = {}
    for d in sorted(base.glob("ep*/S*")):
        m = re.fullmatch(r"ep(\d+)", d.parent.name)
        s = re.fullmatch(r"S(\d+)", d.name)
        if m and s and (d / "takes.json").is_file():
            found[(int(m.group(1)), int(s.group(1)))] = d / "takes.json"
    for key in _ledger_shots(ep):
        found.setdefault(key, None)
    for (n_ep, idx), tp in sorted(found.items()):
        if ep is not None and n_ep != ep:
            continue
        sid = f"ep{n_ep:02d}-S{idx}"
        if char and char not in chars.get(sid, []):
            continue
        takes: dict = {}
        if tp is not None:
            try:
                takes = json.loads(tp.read_text(encoding="utf-8"))
            except (OSError, ValueError):  # arch-ok: 这一镜的 takes.json 读坏：跳过这一镜，其余照常显示
                continue
        first = _cell(takes, "image", jobs.get((sid, "image")), edits.get((sid, "image")), run)
        last = _cell(takes, "last", jobs.get((sid, "last")), edits.get((sid, "last")), run)
        for st, c in (("first", first), ("last", last)):
            c["ledger"] = SS.ledger_cell(sid, st) if c["state"] == "none" and not c["gen"] else None
        try:
            kind = SS.tags_for(sid, None, takes).get("main")
        except Exception:  # noqa: BLE001  状态标签是锦上添花；算不出就不标  # arch-ok: 状态标签算不出就不标，调用方 tag 为空
            kind = None
        tag = {"kind": kind, "word": SS.KINDS.get(kind, kind)} if kind else None
        flags = {"missing": "none" in (first["state"], last["state"]),
                 "new": bool(first["new_n"] or last["new_n"]),
                 "best": bool(tag and tag.get("kind") == "best"),
                 "final": first["state"] == "final" and last["state"] == "final"}
        if status and not flags.get(status):
            continue
        counts["shots"] += 1
        for k, v in flags.items():
            counts[k] += int(v)
        eps.setdefault(n_ep, []).append({"id": sid, "index": idx, "chars": chars.get(sid, []), "first": first, "last": last, "main": tag})
    for rows in eps.values():
        rows.sort(key=lambda r: r["index"])
    running = [g for (sh, _st), g in jobs.items() if g["state"] == "running"]
    queued = [g for g in jobs.values() if g["state"] == "queued"]
    return {"episodes": [{"ep": n, "shots": rows} for n, rows in sorted(eps.items())], "counts": counts,
            "gen": {"running": len(running), "queued": len(queued)}}


@router.get("/api/frames-index")
def frames_index(ep: int | None = None, status: str | None = None, char: str | None = None, run: str | None = None):
    if status and status not in STATUS:
        raise HTTPException(422, f"status 只能是 {' | '.join(STATUS)}")
    if run is not None and not re.fullmatch(r"[A-Za-z0-9_\-]+", run):
        raise HTTPException(422, "run 只能是剧名（字母数字下划线横线）")
    # L-212（SCAN #16）：首次 6.2 s → 先回旧值、后台重算（ns_api/swr.py，口径同 pipeline_status r13）
    from ns_render import pipeline as _P  # noqa: PLC0415  数据根进缓存键（测试会换临时目录）
    return _SWR.get((str(_P.DATA), ep, status, char, run), lambda: build(ep, status, char, run=run))


_SWR = _swr.SWRCache("frames-index", fresh_s=5.0, stale_s=120.0)
