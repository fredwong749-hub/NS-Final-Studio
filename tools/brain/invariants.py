"""系统自查（W-SCAN 11-07）：每拍大脑快照后跑一组便宜的不变量检查，违规 → data/pipeline/issues.jsonl 开 / 更新一条卡点
（按 inv_key 去重），清掉后自动关；同时列在 data/brain/snapshot.md 最上面“🔴 系统自查发现”。

为什么有它：11-06 夜里每个 bug 都是项目方自己点出来的（待你看队列反复出现已点过的卡、大脑说 ep02 0/16 而 gpu36 已 14、
成人触发没人写、驳回没推到服务器……）。这里把“页面口径 vs 真相”和“流水线不变量”变成每拍自动查。

检查族（key 前缀 = 族；本拍没跑的族不自动关）：
  页面口径（只在真仓库根、本机 API 通时跑，GET only）
    queue_done      待你看里出现 pick_state 已 done / decisions 已 applied 的卡
    kpi_page        /api/episodes/kpi 的首帧 / 尾帧数 与两台登记表最大值不一致
    media_missing   /api/videos/overview 给出的视频地址本机没有文件（页面黑屏 / 404）
    slow_api        这些 GET 超过 2 s
    api_tz          API 的 at 时间戳不是 JST（差 > 30 分钟）
  本机文件
    pick_stuck      pick_state processing / accepted 超过 15 分钟；failed 没写原因
    tmp_orphan      data/owner_queue 下残留 *.tmp（原子写失败没清）
    api_log         API 日志新出现的 5xx / Traceback；同一 /api 地址 404 被轮询 > 200 次
    issue_backlog   卡点 open 超过 6 小时（汇总一条）
  快照（两台探针）
    kpi_brain       快照 KPI 与两台登记表最大值不一致（大脑看错数）
    host_disagree   同一集两台登记表首 / 尾 / 视频数相差 ≥ 2
    phase_disagree  同一集两台 lane_roles 阶段不同
    phantom_run     某台登记表有视频 running，但本台没有渲染中视频、本台所有道都空
    stuck           attention 里 ready / running 等了 > 60 分钟
    retry_loop      本台失败事件尾部同一对象同一失败 ≥ 3 次
    idle_work       空卡巡检：道空着但有活
    hold_expired    control / night_control 的 hold 已过期还在
    asset_failed    资产作业 failed 且 final（没人重排）
    ctrl_unpushed   本机 owner_triggers / master_rejects 比服务器新 10 分钟以上（推送没生效）
纯函数 checks(...) 便于测试；cycle(snap, env, now, sync) 是 telemetry.snapshot 的入口。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
JST = timezone(timedelta(hours=9))
ISSUES_REL = "data/pipeline/issues.jsonl"
STATE_REL = "data/brain/invariants_state.json"
WHO = "SELF-CHECK"
RED, YEL = "🔴", "🟡"
SLOW_S = 2.0
STUCK_MIN = 60
PICK_STUCK_MIN = 15
ISSUE_OLD_H = 6
UPDATE_EVERY_S = 3600
LOG_FIRST_BYTES = 2 * 1024 * 1024
LOG_NOISE = ("ConnectionResetError", "CancelledError")   # Windows asyncio 客户端断开，非 bug
LOG_STICKY_S = 1800      # 日志族：最后一次出现后 30 分钟内一直算在（不然每拍开关一次）
API_PAGES = ("/api/owner/inbox", "/api/episodes/kpi", "/api/videos/overview")


def V(key: str, sev: str, title: str, evidence: str, surface: str = "", fix: str = "") -> dict:
    return {"key": key, "sev": sev, "title": title, "evidence": str(evidence)[:300], "surface": surface, "fix": fix}


def _j(p: Path, default=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):   # arch-ok: 读不到 = 默认
        return default


def _local_ts(s) -> float | None:
    """笔记本 API / pick_state 写的无时区时间（本机时区）或带 +09:00 的 JST → epoch"""
    if not s:
        return None
    try:
        d = datetime.fromisoformat(str(s).replace(" ", "T"))
    except ValueError:
        return None
    return d.timestamp()


# ------------------------------------------------------------------ 快照族（纯函数）
def host_have(snap: dict) -> dict:
    """{ep: {host: {f, l, v, t}}}"""
    out: dict = {}
    for h, H in (snap.get("hosts") or {}).items():
        for ep, E in (((H or {}).get("registry") or {}).get("episodes") or {}).items():
            hv = E.get("have") or {}
            out.setdefault(str(ep), {})[h] = {k: int(hv.get(k) or 0) for k in ("t", "f", "l", "v")}
    return out


def check_snapshot(snap: dict, now: float) -> list[dict]:
    out = []
    hh = host_have(snap)
    for ep, per in hh.items():
        mx = {k: max(x[k] for x in per.values()) for k in ("f", "l", "v")}
        k = (snap.get("kpi") or {}).get(ep) or {}
        if k and (int(k.get("first_done") or 0), int(k.get("last_done") or 0)) != (mx["f"], mx["l"]):
            out.append(V(f"kpi_brain:ep{ep}", RED, f"大脑 KPI 第{ep}集数错了",
                         f"快照 首{k.get('first_done')} 尾{k.get('last_done')}，两台登记表最大 首{mx['f']} 尾{mx['l']}（{per}）",
                         "brain / snapshot.md", "telemetry.kpi 逐字段取两台最大"))
        if len(per) >= 2:
            for f, word in (("f", "首帧"), ("l", "尾帧"), ("v", "视频")):
                vals = {h: x[f] for h, x in per.items()}
                if max(vals.values()) - min(vals.values()) >= 2:
                    out.append(V(f"host_disagree:ep{ep}:{f}", YEL, f"两台对第{ep}集{word}数说法不一", f"{vals}",
                                 "registry", "查同步：帧 / 视频回传和登记表合并"))
    phases: dict = {}
    for h, H in (snap.get("hosts") or {}).items():
        for ep, rec in (((H or {}).get("lane_roles_state")) or {}).items():
            if isinstance(rec, dict) and rec.get("phase") and not str(ep).startswith("_"):
                phases.setdefault(str(ep), {})[h] = rec["phase"]
    for ep, per in phases.items():
        if len(set(per.values())) > 1:
            out.append(V(f"phase_disagree:ep{ep}", YEL, f"两台对第{ep}集阶段不一致", f"{per}", "lane_roles"))
    lanes = snap.get("lanes") or {}
    for h, H in (snap.get("hosts") or {}).items():
        H = H or {}
        reg = H.get("registry") or {}
        att = reg.get("attention") or []
        host_lanes = {ln: r for ln, r in lanes.items() if ln.split(":")[0] == h}
        busy = any((r.get("running") or []) for r in host_lanes.values())
        vrun = [a["obj"] for a in att if str(a.get("obj", "")).startswith("video:") and a.get("st") == "running"]
        vcounts = (H.get("video") or {}).get("counts") or {}
        if vrun and host_lanes and not busy and not vcounts.get("rendering"):
            out.append(V(f"phantom_run:{h}", RED, f"{h} 登记表说视频在跑，但本台没有一道在跑",
                         f"running {vrun[:6]}（共 {len(vrun)}）；视频状态 {vcounts}；道 {sorted(host_lanes)} 全空",
                         "registry / 视频页", "登记表 running 要对上 night 真实在渲染；否则退回 ready"))
        for a in att:
            if a.get("st") in ("ready", "running", "blocked", "pending") and float(a.get("wait_min") or 0) > STUCK_MIN:
                out.append(V(f"stuck:{h}:{a.get('obj')}", YEL, f"{a.get('obj')} 卡在 {a.get('st')} {a.get('wait_min')} 分钟",
                             f"{h} @{a.get('where')}：{a.get('why')}", "registry"))
        rep: dict = {}
        for f in H.get("log_fails") or []:
            rep.setdefault((f.get("ev"), f.get("obj")), []).append(f)
        for (ev, obj), fs in rep.items():
            if obj and len(fs) >= 3:
                out.append(V(f"retry_loop:{h}:{ev}:{obj}", YEL, f"{obj} 同一失败重复 {len(fs)} 次（{ev}）",
                             f"{h} 最近：{fs[-1].get('ts')} {fs[-1].get('why')}", "producer log"))
        ctrl = H.get("ctrl") or {}
        exp = _local_ts(ctrl.get("expires_at"))
        if exp and exp < now and (ctrl.get("hold_lanes") or ctrl.get("paused")):
            out.append(V(f"hold_expired:{h}:ctrl", YEL, f"{h} control 的 hold / 暂停已过期还在", f"expires_at={ctrl.get('expires_at')} hold={ctrl.get('hold_lanes')}", "control.json"))
        nc = H.get("nctrl") or {}
        nexp = _local_ts(nc.get("hold_expires"))
        if nexp and nexp < now and nc.get("hold_lanes"):
            out.append(V(f"hold_expired:{h}:night", YEL, f"{h} night_control 的 hold 已过期还在", f"hold_expires={nc.get('hold_expires')} hold={nc.get('hold_lanes')}", "night_control.json"))
    iw = snap.get("idle_watch") or {}
    if iw.get("idle_lanes") and iw.get("has_work") and float(iw.get("age_s") or 1e9) < 900:
        out.append(V("idle_work", RED, "有活但 GPU 道空着", f"空闲 {iw.get('idle_lanes')}；巡检动作 {iw.get('actions')}", "工厂健康",
                     "看 IDLE-WATCH 卡点里的 sop_gate 阻断原因（常见：提示词证据过期没人重跑 probe-prompts）"))
    a = snap.get("assets") or {}
    for j in a.get("failed") or []:
        if j.get("final"):
            out.append(V(f"asset_failed:{j.get('id')}", YEL, f"资产作业 {j.get('id')} 失败且不再重排", str(j.get("err"))[:160], "资产中心",
                         "改参数重排或交项目方挑"))
    return out


def check_ctrl_push(snap: dict, root: Path, run: str) -> list[dict]:
    out = []
    pd = root / "data/producer/runs" / run
    for nm in ("owner_triggers.json", "master_rejects.json"):
        lp = pd / nm
        if not lp.is_file():
            continue
        lm = lp.stat().st_mtime
        for h, H in (snap.get("hosts") or {}).items():
            cf = (H or {}).get("ctrl_files")
            if not isinstance(cf, dict):
                continue   # 探针老版本没这字段 → 不判
            rm = cf.get(nm)
            if rm is None or lm > float(rm) + 600:
                out.append(V(f"ctrl_unpushed:{h}:{nm}", RED, f"本机 {nm} 没推到 {h}",
                             f"本机 {time.strftime('%m-%d %H:%M', time.localtime(lm))}，{h} {'没有这个文件' if rm is None else time.strftime('%m-%d %H:%M', time.localtime(float(rm)))}",
                             "成人触发 / 修改重出", "resident_sync.push_control 是否在跑新代码"))
    return out


# ------------------------------------------------------------------ 本机文件族
def check_picks(root: Path, now: float) -> list[dict]:
    out = []
    st = _j(root / "data/owner_queue/pick_state.json", {}) or {}
    for pid, r in st.items():
        if not isinstance(r, dict):
            continue
        s, t = r.get("state"), _local_ts(r.get("updated") or r.get("accepted_at"))
        if s in ("processing", "accepted") and t and now - t > PICK_STUCK_MIN * 60:
            out.append(V(f"pick_stuck:{pid}", RED, f"你点过的 {pid} 卡在 {s} {round((now - t) / 60)} 分钟",
                         f"updated={r.get('updated')} by={r.get('by')} choice={r.get('choice')}", "#/queue",
                         "owner_pick.process 异常路径要落 failed + 原因；pick_state 写入要重试"))
        if s == "failed" and not (r.get("error") or r.get("why") or r.get("reason")):
            out.append(V(f"pick_failed_noreason:{pid}", YEL, f"{pid} 失败但没写原因", json.dumps(r, ensure_ascii=False)[:160], "#/queue"))
    for d in ("data/owner_queue", "data/producer/runs"):
        base = root / d
        if not base.is_dir():
            continue
        tmps = [p for p in base.rglob("*.tmp") if now - p.stat().st_mtime > 600]   # arch-ok: 按年龄找残留临时文件，不是“猜最新一份”
        if tmps:
            out.append(V(f"tmp_orphan:{d}", YEL, f"{d} 残留 {len(tmps)} 个 .tmp（原子写失败没清）",
                         ", ".join(p.name for p in sorted(tmps, key=lambda p: -p.stat().st_mtime)[:4]), "原子写",
                         "os.replace 在 Windows 被读者占用会 WinError 5：加重试并在失败时删 tmp"))
    return out


def check_issue_backlog(issues: list[dict], now: float) -> list[dict]:
    old = []
    for i in issues:
        if i.get("status") != "open" or i.get("inv_key"):
            continue
        t = _local_ts(i.get("time"))
        if t and now - t > ISSUE_OLD_H * 3600:
            old.append(i)
    if not old:
        return []
    by: dict = {}
    for i in old:
        by[i.get("who")] = by.get(i.get("who"), 0) + 1
    top = sorted(by.items(), key=lambda x: -x[1])[:5]
    return [V("issue_backlog", YEL, f"{len(old)} 条卡点 open 超过 {ISSUE_OLD_H} 小时没人关", f"按来源 {top}；最老 {old[0].get('id')}",
              "issues.jsonl", "已修 / 已过时的批量关；同一来源重复开的改成按 key 去重")]


_RE_REQ = re.compile(r'"(GET|POST|PUT|DELETE|PATCH) ([^ ?"]+)[^"]*" (\d{3})')


def check_api_logs(root: Path, state: dict, now: float | None = None) -> list[dict]:
    """只读新增字节（偏移存 state['logs']）；第一次读尾部 2 MB。命中记 state['log_hits']，30 分钟内持续报"""
    now = time.time() if now is None else now
    hits = state.setdefault("log_hits", {})
    out = _scan_api_logs(root, state)
    for v in out:
        hits[v["key"]] = {"t": now, "v": v}
    for k in [k for k, h in hits.items() if now - float(h.get("t") or 0) > LOG_STICKY_S]:
        hits.pop(k)
    return [h["v"] for h in hits.values()]


def _scan_api_logs(root: Path, state: dict) -> list[dict]:
    out = []
    offs = state.setdefault("logs", {})
    logs = root / "ops/logs"
    for nm in ("api_8800.out.log", "api_8800.err.log"):
        p = logs / nm
        if not p.is_file():
            continue
        sz = p.stat().st_size
        o = offs.get(nm)
        start = max(0, sz - LOG_FIRST_BYTES) if o is None or o > sz else o
        with open(p, "rb") as f:
            f.seek(start)
            txt = f.read(sz - start).decode("utf-8", "replace")
        offs[nm] = sz
        if nm.endswith("out.log"):
            c5, c404 = {}, {}
            for m in _RE_REQ.finditer(txt):
                code, path = int(m.group(3)), m.group(2)
                if code >= 500:
                    c5[f"{m.group(1)} {path}"] = c5.get(f"{m.group(1)} {path}", 0) + 1
                elif code == 404 and path.startswith("/api/"):
                    c404[path] = c404.get(path, 0) + 1
            for k, n in c5.items():
                out.append(V(f"api_log:5xx:{k}", RED, f"接口 {k} 报 5xx {n} 次", f"{nm} 新增日志", "网页按钮点了报错"))
            for k, n in c404.items():
                if n > 200:
                    out.append(V(f"api_log:404poll:{k}", YEL, f"网页反复请求不存在的 {k}（{n} 次 404）", f"{nm} 新增日志", "网页轮询",
                                 "没有内容应返回 200 + 空状态，或前端停止轮询"))
        else:
            excs = re.findall(r"^([A-Za-z_][\w.]*(?:Error|Exception)): (.{0,140})$", txt, re.M)
            kinds: dict = {}
            for k, msg in excs:
                if k.rsplit(".", 1)[-1] in LOG_NOISE:
                    continue
                kinds.setdefault(k.rsplit(".", 1)[-1], []).append(msg)
            for k, msgs in kinds.items():
                out.append(V(f"api_log:exc:{k}", RED if k in ("PermissionError", "PickError", "RegisterError") else YEL,
                             f"API 新出现 {k} × {len(msgs)}", msgs[-1], "API"))
    return out


# ------------------------------------------------------------------ 页面口径族（GET only）
def api_get(base: str, path: str, timeout: float = 20) -> tuple[dict | list | None, float]:
    t0 = time.time()
    try:
        with urllib.request.urlopen(base + path, timeout=timeout) as r:
            return json.loads(r.read()), time.time() - t0
    except (OSError, ValueError, urllib.error.URLError):   # arch-ok: API 不通 = 本族本拍不跑
        return None, time.time() - t0


def check_pages(pages: dict, timings: dict, root: Path, snap: dict, now: float) -> list[dict]:
    out = []
    for p, dt in timings.items():
        if dt > SLOW_S:
            out.append(V(f"slow_api:{p}", YEL, f"{p} 要 {dt:.1f} s", f"> {SLOW_S} s", "网页加载慢"))
    inbox = pages.get("/api/owner/inbox")
    if isinstance(inbox, dict):
        st = _j(root / "data/owner_queue/pick_state.json", {}) or {}
        applied = set()
        dp = root / "data/owner_queue/decisions.jsonl"
        if dp.is_file():
            for ln in dp.read_text(encoding="utf-8", errors="replace").splitlines()[-2000:]:
                try:
                    d = json.loads(ln)
                except ValueError:   # arch-ok: 坏行跳过
                    continue
                if d.get("applied") and d.get("id"):
                    applied.add(d["id"])
        for it in inbox.get("items") or []:
            iid = it.get("id")
            s = (st.get(iid) or {}).get("state")
            if s == "done" or (iid in applied and s not in ("failed",)):
                out.append(V(f"queue_done:{iid}", RED, f"待你看还在显示已处理的 {iid}",
                             f"pick_state={s} decisions.applied={iid in applied}；卡片 {str(it.get('title'))[:40]}", "#/queue",
                             "owner_queue 列卡时排除 done / applied"))
        at = _local_ts(inbox.get("at"))
        if at and inbox.get("at") and "+" not in str(inbox.get("at")):
            jst_now = datetime.fromtimestamp(now, JST).replace(tzinfo=None)
            shown = datetime.fromisoformat(str(inbox["at"]).replace(" ", "T"))
            if abs((jst_now - shown).total_seconds()) > 1800:
                out.append(V("api_tz:/api/owner/inbox", YEL, "待你看的时间戳不是 JST",
                             f"API at={inbox.get('at')}，JST 现在 {jst_now:%m-%d %H:%M}", "#/queue 时间",
                             "API 用 datetime.now(JST) 写 at"))
    kp = pages.get("/api/episodes/kpi")
    if isinstance(kp, dict):
        hh = host_have(snap)
        for e in kp.get("episodes") or []:
            per = hh.get(str(e.get("ep")))
            if not per:
                continue
            mf, ml = max(x["f"] for x in per.values()), max(x["l"] for x in per.values())
            if abs(int(e.get("first_done") or 0) - mf) >= 2 or abs(int(e.get("last_done") or 0) - ml) >= 2:
                out.append(V(f"kpi_page:ep{e.get('ep')}", YEL, f"KPI 页第{e.get('ep')}集数和服务器不一致",
                             f"页面 首{e.get('first_done')} 尾{e.get('last_done')}；服务器 {per}", "KPI 面板",
                             "页面口径与服务器登记表对齐（同一合并规则）"))
    vo = pages.get("/api/videos/overview")
    if vo is not None:
        urls = sorted(set(re.findall(r'"(/files/[^"?]+)', json.dumps(vo, ensure_ascii=False))))
        miss = [u for u in urls if not (root / "data" / u[len("/files/"):]).exists()]
        if miss:
            out.append(V("media_missing:/api/videos/overview", RED, f"视频页 {len(miss)}/{len(urls)} 个视频本机没有文件（点开是黑的）",
                         ", ".join(m.rsplit("/", 3)[-3] + "/" + m.rsplit("/", 1)[-1] for m in miss[:4]), "#/videos",
                         "服务器出的视频回传到笔记本，或页面只列本机有的"))
    return out


# ------------------------------------------------------------------ 卡点同步
def _now_s(now: float) -> str:
    return datetime.fromtimestamp(now, JST).strftime("%Y-%m-%d %H:%M:%S+09:00")


def _family(key: str) -> str:
    return key.split(":", 1)[0]


def load_issues(path: Path) -> list[dict]:
    """折叠事件流（open / update / close），保留 inv_key"""
    cur: dict = {}
    if not path.is_file():
        return []
    for ln in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            e = json.loads(ln)
        except ValueError:   # arch-ok: 坏行跳过
            continue
        ev, iid = e.get("event"), e.get("id")
        if ev == "open":
            cur[iid] = dict(e)
        elif iid in cur and ev == "close":
            cur[iid].update(status="closed", closed_at=e.get("time"))
        elif iid in cur and ev == "update":
            cur[iid].update(what=e.get("what", cur[iid].get("what")), last_seen=e.get("time"))
    return list(cur.values())


def _append(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)


def sync_issues(viol: list[dict], ran: set, path: Path, run: str, now: float, state: dict) -> dict:
    """违规 → 开（没 open 的）/ 更新（已 open 且距上次 ≥ 1 h 或证据变了）；open 的 inv_key 本拍没出现且所属族跑了 → 关"""
    opened = closed = updated = 0
    opens = {i["inv_key"]: i for i in load_issues(path) if i.get("inv_key") and i.get("status") == "open"}
    seen = state.setdefault("seen", {})
    cur = {v["key"]: v for v in viol}
    for k, v in cur.items():
        what = f"{v['title']}：{v['evidence']}"
        if k not in opens:
            iid = f"ISS-{datetime.fromtimestamp(now, JST):%m%d-%H%M%S}-{hashlib.sha1(k.encode()).hexdigest()[:4]}"
            _append(path, {"id": iid, "event": "open", "time": _now_s(now), "run": run, "episode": 0, "step": "系统自查",
                           "who": WHO, "what": what, "blocking": False, "sev": v["sev"], "fix_hint": v.get("fix", ""), "status": "open",
                           "inv_key": k, "surface": v.get("surface", "")})
            v["issue"] = iid
            opened += 1
            seen[k] = {"t": now, "what": what}
        else:
            v["issue"] = opens[k]["id"]
            last = seen.get(k) or {}
            if now - float(last.get("t") or 0) >= UPDATE_EVERY_S or last.get("what") != what:
                _append(path, {"id": opens[k]["id"], "event": "update", "time": _now_s(now), "what": what, "inv_key": k})
                updated += 1
                seen[k] = {"t": now, "what": what}
    for k, i in opens.items():
        if k not in cur and _family(k) in ran:
            _append(path, {"id": i["id"], "event": "close", "time": _now_s(now), "sop_updated": False, "inv_key": k, "note": "系统自查：已不再出现，自动关"})
            seen.pop(k, None)
            closed += 1
    return {"opened": opened, "updated": updated, "closed": closed}


# ------------------------------------------------------------------ 入口
SNAP_FAMILIES = {"kpi_brain", "host_disagree", "phase_disagree", "phantom_run", "stuck", "retry_loop", "idle_work", "hold_expired", "asset_failed"}
PAGE_FAMILIES = {"queue_done", "kpi_page", "media_missing", "slow_api", "api_tz"}


def checks(snap: dict, root: Path, now: float, pages: dict | None, timings: dict | None, state: dict) -> tuple[list[dict], set]:
    viol, ran = [], set()
    if not snap.get("probe_errors"):
        viol += check_snapshot(snap, now)
        ran |= SNAP_FAMILIES
        viol += check_ctrl_push(snap, root, str(snap.get("run") or ""))
        ran.add("ctrl_unpushed")
    viol += check_picks(root, now)
    ran |= {"pick_stuck", "pick_failed_noreason", "tmp_orphan"}
    viol += check_issue_backlog(load_issues(root / ISSUES_REL), now)
    ran.add("issue_backlog")
    viol += check_api_logs(root, state, now)    # 日志族只报“新增”，下拍没新增就自动关
    ran.add("api_log")
    if pages is not None and all(v is not None for v in pages.values()):
        viol += check_pages(pages, timings or {}, root, snap, now)
        ran |= PAGE_FAMILIES
    viol.sort(key=lambda v: (v["sev"] != RED, v["key"]))
    return viol, ran


def cycle(snap: dict, env, now: float, sync: bool = True) -> dict:
    root = Path(env.root)
    state = _j(root / STATE_REL, {}) or {}
    pages = timings = None
    base = getattr(env, "api_base", None)
    if base:
        pages, timings = {}, {}
        for p in API_PAGES:
            pages[p], timings[p] = api_get(base, p)
    viol, ran = checks(snap, root, now, pages, timings, state)
    res = {"violations": viol, "ran": sorted(ran), "opened": 0, "closed": 0}
    if sync:
        res.update(sync_issues(viol, ran, root / ISSUES_REL, str(snap.get("run") or ""), now, state))
        sp = root / STATE_REL
        sp.parent.mkdir(parents=True, exist_ok=True)
        tmp = sp.with_name(sp.name + f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, sp)
    return res


def main(argv=None) -> int:
    """单独跑：读 data/brain/snapshot.json 做一遍（不写卡点），打印违规"""
    import argparse
    ap = argparse.ArgumentParser(description="系统自查（只读；--sync 才写卡点）")
    ap.add_argument("--sync", action="store_true")
    a = ap.parse_args(argv)

    class _E:
        root = ROOT
        api_base = "http://127.0.0.1:8800"
    snap = _j(ROOT / "data/brain/snapshot.json", {}) or {}
    res = cycle(snap, _E(), time.time(), sync=a.sync)
    for v in res["violations"]:
        print(v["sev"], v["key"], "|", v["title"], "|", v["evidence"][:160])
    print(f"共 {len(res['violations'])} 项；跑了 {len(res['ran'])} 族；开 {res.get('opened')} 关 {res.get('closed')}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
