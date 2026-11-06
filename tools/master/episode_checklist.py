#!/usr/bin/env python
"""一集清单执法（docs/master/PIPELINE_CHECKLIST.md）：由 episode_run（唯一调度者）每拍（--watch ≤30 s）调用。
1 任务表  data/pipeline/runs/<run>/episode_run/epNN_tasks.json：每个清单步一行 + 步骤 4/5 逐镜一行
          （status / lane / started / ended / secs / attempts / timeout_s）。
2 清单外不做  episode_lock 旗标（asset_worker 等见旗标不提交 GPU）+ 两台 night_control：yield_s=0、清掉非坏卡的 hold（原值备份在控制文件里，集完成还原）。
3 超时即重做  首帧单张 > 2×预计 → producer retry；3 次后 review-adopt 最高分版；
              视频单段 > 900 s 或首帧已定稿 > 120 s 还没派 → night --once 重派（最多 2 次，仍不行 → 记卡点兜底）；night 状态陈旧 → 紧急 night-only 重启请求。
4 保持连接  笔记本 → 服务器走 rssh 常驻主连接（tunnel_supervisor 托管 gpu*-cmd*.sock，断了它自动重连；run_retry 对 rc=255 / 超时退避重试）。本模块只巡检主连接状态并记一行。
每个动作一行写 epNN_events.log（“MM-DD HH:MM(JST) | CHECKLIST | ACT | …”）；只有走到兜底（采用 / 重启请求 / 视频兜底）才 report_issue。
"""
from __future__ import annotations

import importlib.util
import json
import os
import shlex
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JST = 9 * 3600

# stage 名 → (清单步号, 清单步名, 超时秒；None = 逐镜判)
STEP_OF = {"import": (1, "导入分镜", 120), "regen": (2, "同步到出图机", 90), "preflight": (3, "提示词检查", 180),
           "first": (4, "首帧", None), "video": (5, "视频", None), "finalize": (6, "合成成片", 1200),
           "pull": (7, "拉回", 600), "compare": (7, "对比页", 600), "timeline": (8, "复盘数据", 60)}
FIRST_EXPECT_S = {"base35": 330, "turbo": 60, "turbo_previz": 60}      # 每张首帧预计秒（L-191 实测）
FIRST_FACTOR, FIRST_MAX_REDO = 2.0, 3
VIDEO_MAX_S, VIDEO_DISPATCH_S, VIDEO_MAX_REDO = 900, 120, 2
NIGHT_STALE_S = 900
PROTECTED_HOLDS = ["gpu33:2"]                                          # 坏卡：结构性 hold，不动
LOCK_TTL_S = 600
DONE_VID = {"done", "best_effort", "blocked"}


def _load(rel: str, name: str):
    sp = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


def iso(t: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t))


def _epoch(v) -> float | None:
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return time.mktime(time.strptime(str(v)[:19], "%Y-%m-%dT%H:%M:%S"))
    except ValueError:
        return None


# ---------------------------------------------------------------- 事件日志（CHANNEL 风格）
def jst_stamp(t: float) -> str:
    return time.strftime("%m-%d %H:%M", time.gmtime(t + JST)) + "(JST)"


def log_event(env, kind: str, text: str) -> str:
    line = f"{jst_stamp(env.now())} | CHECKLIST | {kind} | {text}"
    if not env.dry:
        try:
            env.out_dir.mkdir(parents=True, exist_ok=True)
            with open(env.out_dir / f"{env.tag}_events.log", "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:  # arch-ok: 日志写不进不挡编排
            pass
    return line


# ---------------------------------------------------------------- 任务表
def table_path(env) -> Path:
    return env.out_dir / f"{env.tag}_tasks.json"


def load_table(env) -> dict:
    try:
        return json.loads(table_path(env).read_text(encoding="utf-8"))
    except (OSError, ValueError):  # arch-ok: 缺 / 坏 = 新表
        return {"run": env.run, "ep": env.ep, "rows": {}}


def save_table(env, tb: dict) -> None:
    if env.dry:
        return
    env.out_dir.mkdir(parents=True, exist_ok=True)
    p = table_path(env)
    tmp = p.with_suffix(".json.part")
    tmp.write_text(json.dumps(tb, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def _row(tb: dict, key: str, **init) -> dict:
    return tb["rows"].setdefault(key, {"status": "todo", "lane": None, "started": None, "ended": None, "secs": None,
                                       "attempts": 0, "timeout_s": None, **init})


def _finish(r: dict, now: float) -> None:
    if r.get("started") and not r.get("ended"):
        r["ended"] = iso(now)
    s, e = _epoch(r.get("started")), _epoch(r.get("ended"))
    if s is not None and e is not None:
        r["secs"] = round(e - s)


def note_stage(tb: dict, stage: str, res: dict, now: float, started_iso: str | None = None) -> None:
    """orchestrate 每段出结果后调：更新清单步骤行（第 7 步 = pull + compare 两行分记）"""
    n, zh, to = STEP_OF[stage]
    r = _row(tb, f"step{n}_{stage}", step=n, name=zh, stage=stage)
    if to is not None:
        r["timeout_s"] = to
    st = res.get("status")
    r["status"] = {"done": "done", "wait": "running", "todo": "running", "unknown": "running"}.get(st, st)
    if r["started"] is None and (st != "done" or started_iso):
        r["started"] = started_iso or iso(now)
    if st == "done":
        if r["started"] is None:
            r["started"] = iso(now)
        _finish(r, now)
    r["msg"] = str(res.get("msg") or "")[:160]
    if to and r["status"] == "running" and r["started"] and now - (_epoch(r["started"]) or now) > to:
        r["overdue"] = True


# ---------------------------------------------------------------- 首帧 / 视频 逐镜
def tier_expect_s(env) -> int:
    try:
        d = json.loads((env.root / "config" / "render_quality.json").read_text(encoding="utf-8"))
        return FIRST_EXPECT_S.get(str((d.get("runs") or {}).get(env.run) or "base35"), 330)
    except (OSError, ValueError):  # arch-ok: 读不到按最慢档（不误杀）
        return 330


def update_first_rows(tb: dict, shots: list, now: float, expect_s: int) -> None:
    for s in shots or []:
        sid = s.get("shot")
        if not sid:
            continue
        r = _row(tb, f"first:{sid}", step=4, shot=sid)
        r["timeout_s"] = int(expect_s * FIRST_FACTOR)
        st = s.get("first")
        if st == "running":
            since = _epoch(s.get("since")) or r.get("_since") or now
            if r["status"] != "running" or r.get("_since") != since:     # 新开一轮出图
                if r.get("_since") not in (None, since):
                    r["attempts"] += 1
                r.update(status="running", started=iso(since), ended=None, secs=None, _since=since)
            r["lane"] = s.get("where")
        elif st in ("passed", "best_effort"):
            if r["status"] not in ("done", "best_effort"):
                r["status"] = "done" if st == "passed" else "best_effort"
                if r["started"] is None:
                    r["started"] = iso(now)
                r["ended"] = iso(now)
                _finish(r, now)
                r["done_at"] = now
        elif r["status"] in ("running", "todo"):
            r["status"] = "waiting"


def update_video_rows(tb: dict, vsnap: dict | None, now: float) -> None:
    if not vsnap:
        return
    recs, rn = vsnap.get("shots") or {}, vsnap.get("renders") or {}
    for sid, stt in recs.items():
        r = _row(tb, f"video:{sid}", step=5, shot=sid)
        r["timeout_s"] = VIDEO_MAX_S
        fr = tb["rows"].get(f"first:{sid}") or {}
        if fr.get("done_at") and not r.get("ready_at"):
            r["ready_at"] = fr["done_at"]
        subs = [x for x in rn.get(sid) or [] if x.get("t")]
        if stt in DONE_VID:
            if r["status"] not in ("done", "best_effort", "blocked"):
                r["status"] = "done" if stt == "done" else stt
                if r["started"] is None:
                    r["started"] = iso(now)
                r["ended"] = iso(now)
                _finish(r, now)
        elif subs:
            t0 = min(float(x["t"]) for x in subs)
            r.update(status="running", lane=subs[0].get("lane"), started=iso(t0), ended=None, secs=None, _since=t0)
        else:
            r["status"] = "waiting"


# ---------------------------------------------------------------- 决策（纯函数，便于测）
def decide(tb: dict, vsnap: dict | None, now: float) -> list:
    acts: list = []
    for key, r in tb["rows"].items():
        if key.startswith("first:") and r["status"] == "running" and r.get("_since"):
            lim = r.get("timeout_s") or 660
            if now - r["_since"] > lim and now - (r.get("last_act") or 0) > lim / 2:
                kind = "first_retry" if r.get("redos", 0) < FIRST_MAX_REDO else "first_adopt"
                acts.append({"kind": kind, "key": key, "obj": f"first:{r['shot']}", "run_s": int(now - r["_since"]), "lane": r.get("lane")})
        elif key.startswith("video:"):
            if r["status"] == "running" and r.get("_since") and now - r["_since"] > VIDEO_MAX_S:
                why = f"视频 {r['shot']} 出了 {int(now - r['_since'])} s > {VIDEO_MAX_S} s"
            elif r["status"] == "waiting" and r.get("ready_at") and now - r["ready_at"] > VIDEO_DISPATCH_S:
                why = f"{r['shot']} 首帧定稿 {int(now - r['ready_at'])} s 还没派视频 > {VIDEO_DISPATCH_S} s"
            else:
                continue
            if now - (r.get("last_act") or 0) < VIDEO_DISPATCH_S:
                continue
            acts.append({"kind": "video_kick" if r.get("redos", 0) < VIDEO_MAX_REDO else "video_fallback", "key": key, "why": why})
    age = (vsnap or {}).get("night_age_s")
    if age is not None and age > NIGHT_STALE_S and tb.get("night_restart_at") is None and any(
            k.startswith("video:") and v["status"] == "waiting" for k, v in tb["rows"].items()):
        acts.append({"kind": "night_restart", "key": "night", "why": f"night 状态 {int(age)} s 没更新（>{NIGHT_STALE_S}）"})
    return acts


# ---------------------------------------------------------------- 两台都要干活（FIX-A 11-05，项目方“pipeline 不要漏掉这 2 台 gpu 服务器”）
LANE_IDLE_S = 120                   # 有排队的活时，某台所有视频道空这么久 → 记卡点 + 重新派活
LANE_IDLE_REACT_S = 600             # 同一台同一次空闲，重新派活最多每 10 分钟一次
HOST_VID_SNAP = (
    'import json,os,glob;R="%(run)s";E=%(ep)d;H="%(host)s";V="data/pipeline/runs/"+R+"/video/";'
    'J=lambda p:(json.load(open(p,encoding="utf-8")) if os.path.exists(p) else {});'
    'jobs=J(V+"jobs.json");ids=[s["shot"] for s in jobs.get("shots",[]) if s.get("ep")==E];'
    'st={};[st.update({k:r for k,r in (J(f).get("shots") or {}).items() if not r.get("orphan")}) for f in glob.glob(V+"state_*.json")];'   # W-SCHED 11-06：孤儿记录（被别台领走，pending）不盖掉领取台的 done
    'mine=(J(V+"state_"+H+".json").get("shots") or {});'
    'busy=sum(1 for r in mine.values() for x in (r.get("renders") or []) if x.get("state")=="submitted");'
    'q=[i for i in ids if (st.get(i) or {}).get("status") not in ("done","best_effort","blocked")];'
    'print(json.dumps({"host":H,"busy":busy,"queued":len(q)}))'
)


def lane_idle_acts(env, ER, tb: dict, now: float) -> list:
    """有排队的活（本集还有没落定的视频镜）时，两台任一台所有道空 > LANE_IDLE_S → 动作 lane_idle（记卡点 + 该台 night --once 重派）。
    忙了 / 没活了 → 清计时。读不到 = 本拍不判（不凭空报）"""
    acts = []
    idle = tb.setdefault("idle", {})
    for h in sorted({env.image_host, env.video_host}):
        snap = ER.remote_py_json(env, h, HOST_VID_SNAP % {"run": env.run, "ep": env.ep, "host": h})
        if snap is None:
            continue
        if int(snap.get("busy") or 0) > 0 or int(snap.get("queued") or 0) == 0:
            idle.pop(h, None)
            continue
        rec = idle.setdefault(h, {"since": now})
        if now - rec["since"] > LANE_IDLE_S and now - (rec.get("last_act") or 0) > LANE_IDLE_REACT_S:
            acts.append({"kind": "lane_idle", "key": f"idle:{h}", "host": h, "queued": int(snap["queued"]),
                         "why": f"{h} 所有视频道空了 {int(now - rec['since'])} s（>{LANE_IDLE_S}），本集还有 {snap['queued']} 镜没落定"})
    return acts


FIRST_SNAP = (
    'import json,os;P="data/producer/runs/%(run)s/registry.json";'
    'reg=json.load(open(P,encoding="utf-8")) if os.path.exists(P) else {};'
    'ep=next((e for e in reg.get("episodes",[]) if e.get("ep")==%(ep)d),{});'
    'f=lambda s:(s.get("objects",{}).get("first") or {});'
    'print(json.dumps({"shots":[{"shot":s.get("shot"),"first":f(s).get("status"),"where":f(s).get("where"),"since":f(s).get("since")} for s in ep.get("shots",[])]}))'
)


def first_snap(env, ER) -> dict | None:
    """首帧逐镜状态含 where / since（出图机 producer registry.json 只读；不依赖 producer status --json 的字段）"""
    return ER.remote_py_json(env, env.image_host, FIRST_SNAP % {"run": env.run, "ep": env.ep})


def _prod(env, sub: str) -> tuple:
    h = env.image_host
    cmd = (f"cd {shlex.quote(env.root_of(h))} && OFFLINE_SELF={h} {shlex.quote(env.py_of(h))} tools/autopilot/producer.py {sub} "
           f"--run {shlex.quote(env.run)} --by CHECKLIST")
    rc, out, err = env.remote(h, cmd, timeout=120, tries=1)
    return rc, ((out.decode("utf-8", "replace") if isinstance(out, (bytes, bytearray)) else str(out)) + err)[-200:].strip()


def execute(env, tb: dict, acts: list) -> list:
    """执行动作；每个动作一行日志。兜底类（采用 / 视频兜底 / 重启请求）才 report_issue"""
    lines = []
    now = env.now()
    for a in acts:
        r = tb["rows"].get(a["key"]) or tb.setdefault("misc", {})
        k = a["kind"]
        if k == "first_retry":
            rc, _t = _prod(env, f"retry --obj {shlex.quote(a['obj'])} --note {shlex.quote('清单：出图超 2x 预计，放回重派')}")
            r["redos"] = r.get("redos", 0) + 1
            r["last_act"] = now
            lines.append(log_event(env, "ACT", f"{a['obj']} 在 {a.get('lane')} 已跑 {a['run_s']} s 超 2x 预计 -> producer retry（第 {r['redos']} 次）rc={rc}"))
        elif k == "first_adopt":
            rc, tail = _prod(env, f"review-adopt --obj {shlex.quote(a['obj'])} --note {shlex.quote('清单：3 次超时，采用最高分版')}")
            r["last_act"] = now
            r["redos"] = 0
            lines.append(log_event(env, "FALLBACK", f"{a['obj']} 3 次超时仍没出 -> review-adopt 最高分版 rc={rc} {tail[:80]}"))
            env.report_issue("checklist/first", f"{a['obj']} 超时 3 次，已自动采用最高分版（review-adopt rc={rc}）", False, "看图确认；必要时“修改”")
        elif k == "video_kick":
            h = env.video_host
            cmd = f"cd {shlex.quote(env.root_of(h))} && OFFLINE_SELF={h} {shlex.quote(env.py_of(h))} tools/series10_video/night.py --once"
            rc, _o, _e = env.remote(h, cmd, timeout=180, tries=1)
            r["redos"] = r.get("redos", 0) + 1
            r["last_act"] = now
            lines.append(log_event(env, "ACT", f"{a['why']} -> night --once 重派（第 {r['redos']} 次）rc={rc}"))
        elif k == "video_fallback":
            r["last_act"] = now
            lines.append(log_event(env, "FALLBACK", f"{a['why']}；重派 {VIDEO_MAX_REDO} 次仍不行 -> 记卡点（兜底：上一个可用片段 / 静帧推镜）"))
            env.report_issue("checklist/video", a["why"] + f"；已重派 {VIDEO_MAX_REDO} 次", False, "用上一版片段或静帧推镜兜底；或看 vidgen 日志")
        elif k == "lane_idle":
            h = a["host"]
            cmd = f"cd {shlex.quote(env.root_of(h))} && OFFLINE_SELF={h} {shlex.quote(env.py_of(h))} tools/series10_video/night.py --once"
            rc, _o, _e = env.remote(h, cmd, timeout=180, tries=1)
            tb.setdefault("idle", {}).setdefault(h, {})["last_act"] = now
            lines.append(log_event(env, "ACT", f"{a['why']} -> {h} night --once 重新派活 rc={rc}"))
            env.report_issue("checklist/lane_idle", a["why"] + f"；已重新派活 rc={rc}", False,
                             "两台都要干活：看 shard_claims.json / 分片配置 / 该台 vidgen 是否在跑")
        elif k == "night_restart":
            ok = True
            try:
                rq = _load("tools/autopilot/restart_queue.py", "restart_queue_cl")
                rq.request(env.video_host, f"CHECKLIST：{a['why']}", by="CHECKLIST", urgent=True, mode="night-only")
            except Exception as e:  # noqa: BLE001  # arch-ok: 请求写不进 = 记一行，卡点里写明
                ok = False
                a["why"] += f"（请求失败 {e!r}）"[:80]
            tb["night_restart_at"] = now
            lines.append(log_event(env, "FALLBACK", f"{a['why']} -> 紧急 night-only 重启请求 ok={ok}"))
            env.report_issue("checklist/video", a["why"] + "；已请求紧急 night-only 重启", False, "restart_queue status")
    return lines


# ---------------------------------------------------------------- 独占：旗标 + night 控制（服务器端小脚本，只含双引号）
CTRL_CODE = (
    'import json,os;p="data/pipeline/runs/%(run)s/video/night_control.json";'
    'd=json.load(open(p,encoding="utf-8")) if os.path.exists(p) else {};'
    'b=d.get("_ep_lock_backup");'
    'b=b if b else {"yield_s":d.get("yield_s"),"hold_lanes":d.get("hold_lanes"),"hold_expires":d.get("hold_expires")};'
    'd["_ep_lock_backup"]=b;d["yield_s"]=0;d["hold_lanes"]=[l for l in (d.get("hold_lanes") or []) if l in %(prot)s];'
    'tmp=p+".part";json.dump(d,open(tmp,"w",encoding="utf-8"),ensure_ascii=False,indent=1);os.replace(tmp,p);'
    'print(json.dumps({"ok":True,"backup":b}))'
)
RESTORE_CODE = (
    'import json,os;p="data/pipeline/runs/%(run)s/video/night_control.json";'
    'd=json.load(open(p,encoding="utf-8")) if os.path.exists(p) else {};b=d.pop("_ep_lock_backup",None) or {};'
    '[(d.__setitem__(k,b[k]) if b.get(k) is not None else d.pop(k,None)) for k in ("yield_s","hold_lanes","hold_expires")] if b else None;'
    'tmp=p+".part";json.dump(d,open(tmp,"w",encoding="utf-8"),ensure_ascii=False,indent=1);os.replace(tmp,p);'
    'print(json.dumps({"ok":True,"restored":bool(b)}))'
)


def _ctrl(env, host: str, code: str) -> bool:
    cmd = f"cd {shlex.quote(env.root_of(host))} && {shlex.quote(env.py_of(host))} -c '{code}'"
    rc, out, _e = env.remote(host, cmd, timeout=60, tries=2)
    return rc == 0 and b'"ok": true' in (out if isinstance(out, (bytes, bytearray)) else str(out).encode())


def acquire(env, tb: dict, now: float) -> list:
    """刷新旗标；每集第一次应用 night 控制（yield_s=0、清非坏卡 hold）"""
    if env.dry:
        return []
    el = _load("tools/pipeline/episode_lock.py", "episode_lock_cl")
    el.write(env.root, env.run, env.ep, ttl_s=LOCK_TTL_S, now=now)
    lines = []
    if not tb.get("ctrl_applied") and not env.offline:
        res = {h: _ctrl(env, h, CTRL_CODE % {"run": env.run, "prot": json.dumps(PROTECTED_HOLDS)}) for h in sorted({env.image_host, env.video_host})}
        tb["ctrl_applied"] = res
        lines.append(log_event(env, "LOCK", f"清单独占开始：旗标 episode_lock（{LOCK_TTL_S}s 滚动）+ night yield_s=0 / 清非坏卡 hold {res}"))
    return lines


def release(env, tb: dict) -> list:
    if env.dry:
        return []
    el = _load("tools/pipeline/episode_lock.py", "episode_lock_cl")
    el.clear(env.root, env.run, env.ep)
    res = {}
    if tb.get("ctrl_applied") and not env.offline:
        res = {h: _ctrl(env, h, RESTORE_CODE % {"run": env.run}) for h in tb["ctrl_applied"]}
        tb["ctrl_applied"] = None
    return [log_event(env, "LOCK", f"清单独占结束：旗标已清，night 控制还原 {res}")]


def conn_health(env, tb: dict, now: float) -> list:
    """rssh 常驻主连接（tunnel_supervisor 托管 gpu*-cmd*.sock）巡检：某台一条 up 的都没有 -> 记一行（10 分钟一次）"""
    try:
        hs = json.loads((env.root / "data" / "netfix" / "net_status.json").read_text(encoding="utf-8")).get("hosts") or {}
    except (OSError, ValueError):  # arch-ok: 没有状态文件 = 不巡检
        return []
    out = []
    for h in sorted({env.image_host, env.video_host}):
        ups = [k for k, v in hs.items() if k.startswith(h + "-cmd") and v.get("state") == "up"]
        if not ups and now - (tb.setdefault("conn_logged", {}).get(h) or 0) > 600:
            tb["conn_logged"][h] = now
            out.append(log_event(env, "CONN", f"{h} 没有可用的常驻主连接（supervisor 会自动重连；run_retry 退避重试中）"))
    return out


# ---------------------------------------------------------------- 每拍入口
def tick(env, ER, tb: dict) -> dict:
    """刷新旗标 -> 读两台状态 -> 更新任务表（tb 由调用方持有并保存）-> 决策 -> 执行。远程读失败 = 本拍只刷新旗标"""
    now = env.now()
    lines = acquire(env, tb, now) + conn_health(env, tb, now)
    acts: list = []
    if not env.offline:
        snap = first_snap(env, ER)
        if snap:
            update_first_rows(tb, snap.get("shots") or [], now, tier_expect_s(env))
        v = ER.video_snap(env)
        update_video_rows(tb, v, now)
        acts = decide(tb, v, now) + lane_idle_acts(env, ER, tb, now)
        if not env.dry:
            lines += execute(env, tb, acts)
    tb["tick_at"] = iso(now)
    save_table(env, tb)
    return {"acts": acts, "lines": lines}


# ---------------------------------------------------------------- 报告表
def render_table_md(tb: dict) -> str:
    rows = tb.get("rows") or {}
    out = ["", "## 清单与耗时", "", "| # | 步骤 | 状态 | 开始 | 结束 | 用时(s) | 超时(s) | 重做 |", "|---|---|---|---|---|---|---|---|"]

    def line(v, name):
        return (f"| {v['step']} | {name} | {v['status']}{' (超时)' if v.get('overdue') else ''} | {(v.get('started') or '')[11:19]} | "
                f"{(v.get('ended') or '')[11:19]} | {v['secs'] if v.get('secs') is not None else ''} | {v.get('timeout_s') or ''} | "
                f"{v.get('attempts', 0) + v.get('redos', 0)} |")
    for v in sorted((v for k, v in rows.items() if k.startswith("step")), key=lambda v: (v["step"], v.get("stage", ""))):
        out.append(line(v, v["name"]))
    for pre, zh in (("first:", "首帧"), ("video:", "视频")):
        for v in sorted((v for k, v in rows.items() if k.startswith(pre)), key=lambda v: v["shot"]):
            out.append(line(v, f"{zh} {v['shot']}"))
    return "\n".join(out) + "\n"
