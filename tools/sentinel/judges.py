"""SENTINEL 判定层（纯函数、可测、实时与回放共用；规则 K-OPS-S02）。

每个 j_* 只吃“已经取到的数据”，返回 finding 列表：
  {"slo": "S2", "key": "S2:gpu33", "violated": bool, "title": "...", "evidence": {...}}
key = 去重键（同一问题只开一张工单）；violated=False 的 finding 表示“这一项已测、正常”，用来自动关单。
没测到（远程不通 / 文件缺）就不返回该 key 的 finding——不能拿“没数据”当“恢复”。
阈值一律从 config/policies/sentinel.yaml 读（K-OPS-X01），这里只收参数。
"""
from __future__ import annotations

import statistics
import time
from datetime import datetime

SLO_TITLE = {
    "S0": "探针自身故障（读不到输入 / 远程采样失败 / 探针异常）",
    "S1": "出图道 GPU 利用率", "S2": "有 ready 单时 GPU 全空", "S3": "打分 p50 / 打分服务", "S4": "连接恢复 / 跳板新建连接",
    "S5": "发版 cut / 服务器版本", "S6": "服务器配置与笔记本一致", "S7": "无主暂停时长", "S8": "内容抽检（看镜头 / 身份 / 缺件）",
    "S9": "界面彩色元素 / 裂图 / 口径矛盾", "S10": "决策与规则全绿", "S11": "编排器同段卡住", "S12": "剧本代码判定 / 尺子",
    "S13": "等人决定 / 流水线断档",
    "S14": "RSI 线分数（2 小时无新分 / 连续不升）",
    "GPU24": "GPU 24 小时等待任务原因",
    "S15": "编排器 tick 存活", "S16": "笔记本常驻进程清单",
    "S17": "单镜出图速率", "S18": "临时挂道到期", "S21": "读旧状态路径（state_legacy_read）", "S22": "冻结期间改文件", "S23": "笔记本侧出图道可达率", "S24": "API 响应时间", "S25": "常驻 CLIP", "S26": "写作推进常驻服务心跳", "S27": "P1 评审汇总", "S28": "Q10 人数检测服务", "SC": "SCORECARD 七项不到 100 分", "S20": "scratchpad 里跑的进程（K-OPS-Y04）", "G26": "声明 vs 实际（hosts.json）", "S19": "产能见底（ready 不够、没有下一批）",
}


def F(slo: str, key: str, violated: bool, title: str, **ev) -> dict:
    return {"slo": slo, "key": f"{slo}:{key}", "violated": bool(violated), "title": title, "evidence": ev}


def iso(t: float | None) -> str | None:
    return None if t is None else datetime.fromtimestamp(t).strftime("%Y-%m-%dT%H:%M:%S")


def ts(v) -> float | None:
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return datetime.fromisoformat(str(v)).timestamp()
    except ValueError:  # arch-ok: 时间串解析失败 = None（调用方按未知处理）
        return None


# ------------------------------------------------------------------ S1 出图道利用率（lane_util.measure 的结果）
def j_lane_util(rec: dict | None, cfg: dict) -> list[dict]:
    out = []
    for lane, r in ((rec or {}).get("lanes") or {}).items():
        u = r.get("util")
        if u is None:
            continue
        out.append(F("S1", lane, u < cfg["min"], f"出图道 {lane} 利用率 {u:.2f} < {cfg['min']}（{rec.get('window_min')} 分钟）",
                     util=u, jobs=r.get("jobs"), by_agent=r.get("by_agent"), window_min=rec.get("window_min"), at=rec.get("at")))
    return out


# ------------------------------------------------------------------ S2 有 ready 单时 GPU 全空
def j_gpu_idle(host: str, hist: list[tuple[float, list[float]]], ready: dict, paused: bool, now: float, cfg: dict) -> list[dict]:
    """hist：[(t, [各出图卡利用率 %])] 按时间升序（本探针自己逐拍记的样本 / 回放重建的样本）。
    违约 = 最近连续全 0 的样本跨度 ≥ idle_s，且有 ready 单（服务器登记表或笔记本登记表按分区算），且不是暂停（暂停归 S7）。"""
    if not hist:
        return []
    zero_since = None
    for t, us in hist:
        if us and max(us) <= cfg.get("util_le", 0):
            zero_since = zero_since if zero_since is not None else t
        else:
            zero_since = None
    idle_s = (now - zero_since) if zero_since is not None else 0.0
    n_ready = max(int(ready.get("server") or 0), int(ready.get("laptop_partition") or 0))
    bad = idle_s >= cfg["idle_s"] and n_ready > 0 and not paused
    return [F("S2", host, bad, f"{host} 出图卡全 0% 已 {idle_s / 60:.1f} 分钟，ready 单 {n_ready}（服务器 {ready.get('server')} / 笔记本按分区 "
              f"{ready.get('laptop_partition')}）", idle_s=round(idle_s), zero_since=iso(zero_since), last_utils=hist[-1][1], ready=ready,
              paused=paused, both_sides_not_dispatching=bool(n_ready and not ready.get("server")))]


# ------------------------------------------------------------------ S3 打分 p50 + 积压闸 + 打分服务身份
def j_score(where: str, samples: list[tuple[float, float]], backlog_ts: list[float], now: float, cfg: dict) -> list[dict]:
    w0 = now - cfg["window_min"] * 60
    vals = [s for t, s in samples if w0 <= t <= now and s is not None]
    bl = [t for t in backlog_ts if now - cfg["backlog_window_min"] * 60 <= t <= now]
    out = []
    if len(vals) >= cfg["min_samples"]:
        p50 = statistics.median(vals)
        out.append(F("S3", f"p50:{where}", p50 > cfg["p50_max_s"], f"{where} 契约打分 p50 {p50:.0f} s > {cfg['p50_max_s']} s（{len(vals)} 条 / "
                     f"{cfg['window_min']} 分钟）", p50_s=round(p50), n=len(vals), max_s=round(max(vals)), samples=sorted(vals)[-8:]))
    elif not vals and not bl:
        pass                                  # 没有打分事件：不判（没出图就没打分；GPU 空归 S2）
    out.append(F("S3", f"backlog:{where}", bool(bl), f"{where} 打分积压闸顶满、停派 {len(bl)} 次（{cfg['backlog_window_min']} 分钟内，K-OPS-E05）",
                 events=len(bl), last=iso(max(bl)) if bl else None))
    return out


def vqa_kind(health: str | None, models: str | None) -> str | None:
    """:8870 实际是什么：router_nf4（tools/vqa/vqa_router.py，health 里 gpu=router）/ vllm（/v1/models 有模型列表）/
    nf4（tools/vqa/server.py 单实例，health 有 loaded）/ down；两个都没取到 → None（未测）"""
    if health is None and models is None:
        return None
    h, m = str(health or ""), str(models or "")
    if '"gpu": "router"' in h or '"gpu":"router"' in h:
        return "router_nf4"
    if '"data"' in m and '"object"' in m:
        return "vllm"
    if '"loaded"' in h:
        return "nf4"
    return "down"


SCORE_DONE = ("passed", "content_fail", "redo_fail", "redo_auto_approved", "redo_candidate", "score_infra", "content_error", "best_effort")


def scoring_backlog(events: list[dict], now: float, horizon_s: float = 7200) -> int:
    """日志推算“出好、还在等契约打分 / 看图”的数量：最近 horizon_s 内 rendered 之后还没有打分结论事件的对象（producer 心跳没暴露 scoring 数）"""
    last = {}
    for e in sorted(events, key=lambda x: x.get("t") or 0):
        if e.get("obj") and now - (e.get("t") or 0) <= horizon_s:
            if e.get("ev") == "rendered":
                last[e["obj"]] = "rendered"
            elif e.get("ev") in SCORE_DONE:
                last[e["obj"]] = "done"
    return sum(1 for v in last.values() if v == "rendered")


def j_backlog_near(where: str, n: int | None, mx: int | None, cfg: dict) -> list[dict]:
    """到顶前预警（总调度 04:1x）：打分积压 ≥ warn_ratio × 上限即开单（K-OPS-E05 的闸真顶满停派另有 backlog 单）"""
    if n is None or not mx:
        return []
    ratio = n / mx
    return [F("S3", f"backlog_near:{where}", ratio >= cfg.get("backlog_warn_ratio", 0.8),
              f"{where} 打分积压 {n}/{mx}（{ratio:.0%}）≥ {cfg.get('backlog_warn_ratio', 0.8):.0%}，快到积压闸上限，到顶就停派",
              n=n, max=mx, ratio=round(ratio, 2))]


def j_vqa_endpoint(host: str, port: int, kind: str | None, expected: str | None, listener: str = "") -> list[dict]:
    """打分服务必须和声明的 backend 一致（config/vqa.json model.backends；未声明时用 sentinel.yaml S3 vqa_backends，出处 L-100）。
    例：01:5x gpu36:8870 被 13 小时前的旧 server.py（nf4 单实例）占着，而声明是 router_nf4 → 违约"""
    if kind is None or not expected:
        return []
    return [F("S3", f"vqa:{host}:{port}", kind != expected, f"{host}:{port} 打分服务实际是 {kind}，声明是 {expected}（监听：{listener[:80] or '未知'}）",
              kind=kind, expected=expected, listener=listener[:300])]


# ------------------------------------------------------------------ S4 连接
def j_ports(ports: dict, now: float, cfg: dict) -> list[dict]:
    """ports：{名字: {"ok": bool, "down_since": t|None}}（down_since 由探针跨拍记；回放从 supervisor.log 重建）"""
    out = []
    for name, p in ports.items():
        if p.get("ok") is None:
            continue
        dt = 0.0 if p["ok"] else now - (p.get("down_since") or now)
        out.append(F("S4", f"port:{name}", (not p["ok"]) and dt > cfg["recover_max_s"],
                     f"连接 {name} 断开 {dt:.0f} s 未恢复（目标 ≤ {cfg['recover_max_s']} s）", down_s=round(dt),
                     down_since=iso(p.get("down_since")), why=p.get("why")))
    return out


def j_relay_rate(per_hour: float | None, src: str, cfg: dict) -> list[dict]:
    if per_hour is None:
        return []
    return [F("S4", "relay_rate", per_hour >= cfg["relay_new_conn_per_h"], f"跳板新建连接 {per_hour:.0f}/小时 ≥ {cfg['relay_new_conn_per_h']}",
              per_hour=round(per_hour), src=src)]


# ------------------------------------------------------------------ S5 发版
def j_cut(last_cut: dict | None) -> list[dict]:
    if not last_cut:
        return []
    return [F("S5", "cut", last_cut.get("ok") is False, f"发版 cut {last_cut.get('id')} 失败：{str(last_cut.get('reason') or '')[:120]}",
              id=last_cut.get("id"), at=last_cut.get("at_iso"), reason=str(last_cut.get("reason") or "")[:300])]


def sv_rank(sv: str | None, ids: list[str]) -> int | None:
    return ids.index(sv) if sv in ids else None


def j_sv_lag(host: str, server_sv: str | None, ids: list[str], cfg: dict) -> list[dict]:
    if not server_sv or not ids:
        return []
    r = sv_rank(server_sv, ids)
    lag = (len(ids) - 1 - r) if r is not None else len(ids)
    return [F("S5", f"sv:{host}", lag > cfg["max_sv_lag"], f"{host} 代码 {server_sv} 落后最新 {ids[-1]} {lag} 版（上限 {cfg['max_sv_lag']}）",
              server_sv=server_sv, latest=ids[-1], lag=lag)]


def j_deploy_after_failed_cut(deploy: dict | None, last_cut: dict | None) -> list[dict]:
    """cut 失败之后又跑了 deploy（02:00 sv-03 被重推、vqa.json 还原成 1 的根因）"""
    if not deploy or not last_cut:
        return []
    dt, ct = ts(deploy.get("at")), last_cut.get("at")
    bad = last_cut.get("ok") is False and dt is not None and ct is not None and dt > float(ct) and deploy.get("id") != last_cut.get("id")
    return [F("S5", "deploy_after_failed_cut", bad, f"cut {last_cut.get('id')} 失败后仍 deploy 了 {deploy.get('id')}",
              deploy=deploy, cut={k: last_cut.get(k) for k in ("id", "ok", "at_iso")})]


# ------------------------------------------------------------------ S6 配置一致
def j_parity(host: str, laptop: dict[str, str | None], server: dict[str, str | None], cfg_files: list[str]) -> list[dict]:
    out = []
    for f in cfg_files:
        a, b = laptop.get(f), server.get(f, "∅")
        if a is None and b in (None, "∅"):
            continue
        if b == "∅":                         # 服务器这一轮没回这个文件的 sha（远程失败）→ 不判
            continue
        out.append(F("S6", f"{host}:{f}", a != b, f"{host} 的 {f} 与笔记本不一致（笔记本 {str(a)[:12]} / 服务器 {str(b)[:12] if b else '缺'}）",
                     laptop_sha=a, server_sha=b, file=f))
    return out


def j_handback(host: str, phase: str | None, rec: dict | None, ok_reasons: tuple[bool, list[str]] | None) -> list[dict]:
    """override_state 某台已交还服务器自派（phase=server），但交还条件（policy.handback_ok：dryrun 0 挡 + refs sha 一致 + FACTORY 写）不满足"""
    if phase is None:
        return []
    bad = phase == "server" and ok_reasons is not None and not ok_reasons[0]
    return [F("S6", f"handback:{host}", bad, f"{host} 已交还服务器自派，但交还条件不满足：{'；'.join((ok_reasons or (True, []))[1])[:160]}",
              phase=phase, why=(ok_reasons or (True, []))[1], rec={k: (rec or {}).get(k) for k in ("ready", "by", "refs_match", "preflight_dryrun_ok", "preflight_dryrun_at")})]


def j_identity(res: dict | None) -> list[dict]:
    """tools/qa/identity_face_check.check()（DISTILL，K-OPS-X07）：每个 run 每个角色的身份脸 = 项目方定的那张 / 继承一致。不一致 = P0"""
    if not res:
        return []
    out = []
    for r in res.get("rows") or []:
        f = F("S6", f"identity:{r.get('run')}:{r.get('cid')}", not r.get("ok", True),
              f"P0 身份脸不一致：{r.get('run')} {r.get('cid')} — {r.get('why')}", run=r.get("run"), cid=r.get("cid"), got=r.get("got"), want=r.get("want"))
        f.update(severity="P0", owner_loop="WORKFLOW / FACTORY")
        out.append(f)
    return out


# ------------------------------------------------------------------ S7 暂停
def j_pause(where: str, ctrl: dict | None, now: float, decide) -> list[dict]:
    """decide = policy.pause_decision（唯一实现）"""
    if ctrl is None:
        return []
    d = decide(ctrl, now) if ctrl.get("paused") else None
    bad = bool(d and d.get("action") in ("alert", "resume"))
    return [F("S7", where, bad, f"{where} producer 暂停 {((d or {}).get('paused_s') or 0) / 60:.1f} 分钟 > {int((d or {}).get('limit_s') or 180)} s"
              f"（{(d or {}).get('why') or ''}；by {ctrl.get('paused_by')}）", decision=d, paused_by=ctrl.get("paused_by"),
              paused_at=ctrl.get("paused_at"), reason_kind=ctrl.get("reason_kind"))]


# ------------------------------------------------------------------ S8 内容抽检
def j_vlm(shot: str, path: str, verdict: dict | None, current_path: str | None, labels: dict) -> list[dict]:
    """verdict：gaze_regression.judge 的结果 + defects；current_path：该镜当前版。当前版已换 → 视为恢复"""
    if current_path is not None and current_path != path:
        return [F("S8", shot, False, f"{shot} 当前版已换", path=path, current=current_path)]
    if not verdict or verdict.get("error"):
        return []
    hit = []
    if verdict.get("eye_contact"):
        hit.append(labels.get("eye_contact", "看镜头"))
    for c in verdict.get("contracts_failed") or []:
        if c in labels:
            hit.append(labels[c])
    return [F("S8", shot, bool(hit), f"{shot} 过了契约的首帧抽检命中：{'、'.join(hit)}", path=path, hits=hit,
              evidence_text=str(verdict.get("evidence") or "")[:200], gaze_mp=verdict.get("gaze_mp"))]


# ------------------------------------------------------------------ S9 界面
def j_ui(res: dict | None, cfg: dict) -> list[dict]:
    """res = sentinel DOM 规则（tools/sentinel/ui_flows.json 的 js 步骤返回值，按页面）"""
    out = []
    for page, r in ((res or {}).get("pages") or {}).items():
        if r is None or r.get("error"):
            continue
        cap = r.get("color_capsules") or []
        out.append(F("S9", f"{page}:color", len(cap) > 0, f"界面 {page} 有 {len(cap)} 个彩色胶囊 / 色块（状态色只许圆点）", samples=cap[:6]))
        brk = r.get("broken_imgs") or []
        out.append(F("S9", f"{page}:broken", len(brk) > cfg["broken_img_max"], f"界面 {page} 裂图 {len(brk)} 张", samples=brk[:6]))
        con = r.get("contradictions") or []
        out.append(F("S9", f"{page}:contradiction", len(con) > cfg["contradictions_max"], f"界面 {page} 口径矛盾 {len(con)} 处：{'；'.join(con[:3])[:160]}",
                     samples=con[:8]))
    return out


# ------------------------------------------------------------------ S10 决策与规则
def j_rules(dc_bad: list[str] | None, dp_bad: list[str] | None, compile_rc: int | None, compile_tail: str = "") -> list[dict]:
    out = []
    if dc_bad is not None:
        out.append(F("S10", "decision_check", bool(dc_bad), f"decision_check ❌ {len(dc_bad)}：{'、'.join(dc_bad[:6])}", bad=dc_bad))
    if dp_bad is not None:
        out.append(F("S10", "decision_propagation", bool(dp_bad), f"decision_propagation 残留：{'、'.join(dp_bad[:6])}", bad=dp_bad))
    if compile_rc is not None:
        out.append(F("S10", "compile", compile_rc != 0, f"knowledge compile --check 失败（rc={compile_rc}）", tail=compile_tail[-400:]))
    return out


# ------------------------------------------------------------------ S11 编排器卡段
def j_stuck(track: dict, now: float, cfg: dict) -> list[dict]:
    """track：{ep: {"stage": s, "progress": 指纹, "since": t}}（探针跨拍记：阶段或进度变了就重置 since）"""
    out = []
    for ep, r in track.items():
        dt = now - r["since"]
        out.append(F("S11", f"ep{int(ep):02d}", dt > cfg["stuck_s"], f"ep{int(ep):02d} 卡在 {r['stage']} {dt / 3600:.1f} 小时无进展（上限 {cfg['stuck_s'] / 3600:g} h）",
                     stage=r["stage"], progress=r.get("progress"), since=iso(r["since"])))
    return out


# ------------------------------------------------------------------ S12 剧本
def j_script(code_fails: dict | None, ruler: dict | None, cfg: dict) -> list[dict]:
    out = []
    if code_fails is not None:
        bad = {k: v for k, v in code_fails.items() if v > cfg["code_fail_max"]}
        out.append(F("S12", "code_fail", bool(bad), f"导入闸门后的新稿代码判定失败：{bad}", fails=code_fails))
    if ruler and ruler.get("stdev") is not None:
        out.append(F("S12", "ruler_sigma", ruler["stdev"] > cfg["sigma_max"], f"尺子标准差 {ruler['stdev']:.2f} > {cfg['sigma_max']}",
                     stdev=ruler["stdev"], src=ruler.get("src")))
    return out


# ------------------------------------------------------------------ S13 等人决定 / 流水线断档（总调度 02:4x 追加）
HUMAN_WAIT = ("等总调度", "等项目方", "总调度复核", "项目方点选", "总调度定")


def is_human_wait(waiting_for: str | None) -> bool:
    w = str(waiting_for or "")
    return any(x in w for x in HUMAN_WAIT)


def j_human_wait(where: str, waits: dict[str, tuple[float, str]], now: float, cfg: dict) -> list[dict]:
    """waits：{对象 id: (进入等人状态的时刻, waiting_for)}。任何对象等人 > wait_max_s 即违约（每台一张单，证据列对象）"""
    over = {o: (now - t, w) for o, (t, w) in waits.items() if now - t > cfg["wait_max_s"]}
    oldest = max((v[0] for v in over.values()), default=0)
    return [F("S13", f"wait:{where}", bool(over), f"{where} 有 {len(over)} 个对象等人决定超过 {cfg['wait_max_s'] // 60} 分钟（最久 {oldest / 60:.0f} 分钟）",
              n=len(over), n_waiting=len(waits), oldest_min=round(oldest / 60),
              objs=sorted(over, key=lambda o: -over[o][0])[:12], reasons=sorted({w[:24] for _, w in over.values()})[:4])]


def j_pipeline_gap(where: str, gpu_idle_s: float | None, ready: int | None, pending: int | None, waiting_human: int, cfg: dict) -> list[dict]:
    """流水线断档：GPU 空闲、ready = 0、pending 很多（下游都在等上游 / 等人）"""
    if gpu_idle_s is None or ready is None or pending is None:
        return []
    bad = gpu_idle_s >= cfg["gap_idle_s"] and ready == 0 and pending >= cfg["gap_pending_min"]
    return [F("S13", f"gap:{where}", bad, f"{where} 流水线断档：GPU 空闲 {gpu_idle_s / 60:.1f} 分钟、ready 0、pending {pending}（其中等人决定 {waiting_human}）",
              gpu_idle_s=round(gpu_idle_s), ready=ready, pending=pending, waiting_human=waiting_human)]


# ------------------------------------------------------------------ S14 五条 RSI 线（总调度 03:5x，L-112）
def j_rsi(summary: dict, now: float, cfg: dict) -> list[dict]:
    """summary = tools/sentinel/rsi.summary()。每线两张单：
      stale = 距最近一轮（没有任何分数时从 program_start 算）超过 stale_s
      flat  = 最近 flat_rounds 轮都没超过它们之前那一轮（连续 N 轮不升）"""
    out = []
    t_start = ts(cfg.get("program_start")) or now
    n = int(cfg["flat_rounds"])
    for lid, s in summary.items():
        track = s.get("track") or []
        last_t = track[-1][0] if track else None
        age = now - (last_t if last_t is not None else t_start)
        f = F("S14", f"{lid}:stale", age > cfg["stale_s"], f"RSI {s['name']} {age / 3600:.1f} 小时没有新分数（上限 {cfg['stale_s'] / 3600:g} 小时）",
              line=lid, last=iso(last_t), score=s.get("score"), target=s.get("target"))
        f["owner_loop"] = s["lead"]
        out.append(f)
        if len(track) > n:
            base = track[-n - 1][1]
            flat = all(sc <= base for _t, sc in track[-n:])
            f = F("S14", f"{lid}:flat", flat, f"RSI {s['name']} 连续 {n} 轮不升（{base:g} → {' / '.join(f'{sc:g}' for _t, sc in track[-n:])}）",
                  line=lid, base=base, recent=[sc for _t, sc in track[-n:]], target=s.get("target"))
            f["owner_loop"] = s["lead"]
            out.append(f)
    return out


# ------------------------------------------------------------------ GPU 24 小时：等待任务的最大原因（总调度 04:1x）
def j_wait_top(res: dict, top_n: int = 2) -> list[dict]:
    """gpu_24h.json 的 waiting_reasons：按秒数排序，最大的 top_n 项（不含“原因不明”、秒数 > 0）各开一张单，派给该原因的负责方
    （运行期 DEBUG-RSI：服务停 / 断连 / pause / 积压闸；供单 FACTORY：队列没单 / hold）；其余原因测到即“正常”，掉出前 top_n 自动关单。
    “原因不明”超过等待任务的 20% 另开一张派 SENTINEL（探针缺口：缺证据源）"""
    wr = res.get("waiting_reasons") or {}
    sec, zh, own, pct = wr.get("seconds") or {}, wr.get("zh") or {}, wr.get("owner") or {}, wr.get("pct_of_waiting") or {}
    ranked = [r for r in sorted(sec, key=lambda r: -sec[r]) if r not in ("unknown", "pause_master") and sec[r] > 0]
    top = set(ranked[:top_n])
    out = []
    for r, s in sec.items():
        if r == "pause_master":
            bad = False                                  # 总调度自己下的暂停：照实展示、记在总调度账上，不开单
        elif r == "unknown":
            bad = (pct.get(r) or 0) > 20
        else:
            bad = r in top
        f = F("GPU24", f"wait:{r}", bad, f"GPU 24 小时“等待任务”{'第 ' + str(ranked.index(r) + 1) + ' 大' if r in top else ''}原因：{zh.get(r, r)} "
              f"{s / 3600:.1f} h（占等待 {pct.get(r)}%，生产 5 卡合计）", reason=r, hours=round(s / 3600, 1), pct_of_waiting=pct.get(r),
              window=res.get("window"))
        f["owner_loop"] = own.get(r, "总调度")
        out.append(f)
    return out


# ------------------------------------------------------------------ S15 / S16（总调度 04:2x）
def j_flow_tick(rec: dict | None, mtime: float | None, now: float, cfg: dict) -> list[dict]:
    """编排器 tick：last_tick.json 超过 stale_s 没更新（取文件里的 t，缺则文件修改时间），或 dry=true → 违约。文件不存在 = 违约（tick 从没跑）"""
    if rec is None and mtime is None:
        return [F("S15", "flow_tick", True, f"编排器 tick 文件 {cfg['file']} 不存在（tick 没在跑）", file=cfg["file"])]
    t = ts((rec or {}).get("t") or (rec or {}).get("at")) or mtime
    age = now - (t or 0)
    dry = bool((rec or {}).get("dry"))
    why = "；".join(x for x in (f"{age / 60:.1f} 分钟没更新" if age > cfg["stale_s"] else "", "dry=true（只演练不推进）" if dry else "") if x)
    return [F("S15", "flow_tick", age > cfg["stale_s"] or dry, f"编排器 tick 异常：{why}", age_s=round(age), dry=dry, pid=(rec or {}).get("pid"),
              at=(rec or {}).get("at"))]


def j_procs(cmdlines: list[str] | None, procs: dict) -> list[dict]:
    """笔记本常驻进程：清单里每一项按命令行正则找，缺一个开一张单派该进程的负责方；cmdlines=None（取不到进程表）不判"""
    import re
    if cmdlines is None:
        return []
    out = []
    for name, p in procs.items():
        rx = re.compile(p["match"], re.I)
        hit = [c for c in cmdlines if rx.search(c)]
        f = F("S16", name, not hit, f"笔记本常驻进程 {name} 没在跑（匹配 {p['match']}）", n=len(hit), sample=(hit[0][:160] if hit else None))
        f["owner_loop"] = p.get("owner") or "总调度"
        out.append(f)
    return out


# ------------------------------------------------------------------ S17 / S18（总调度 08:0x）
def j_shot_rate(rendered: list[dict], now: float, cfg: dict) -> list[dict]:
    """同一镜（obj）最近 1 小时 rendered 次数 > max_per_hour → 违约（无限重出）；本小时出过图的镜都给 finding（低于线 = 正常，用来关单）"""
    cnt: dict[str, list] = {}
    for e in rendered:
        if e.get("obj") and now - (e.get("t") or 0) <= 3600:
            cnt.setdefault(e["obj"], []).append(e)
    out = []
    for obj, es in cnt.items():
        n = len(es)
        out.append(F("S17", obj, n > cfg["max_per_hour"], f"{obj} 最近 1 小时出图 {n} 次 > {cfg['max_per_hour']}（疑似无限重出）",
                     n=n, lanes=sorted({str(x.get("lane")) for x in es}), last_take=max((x.get("take") or 0) for x in es)))
    return out


def j_temp_holds(holds: dict | None, now: float, cfg: dict) -> list[dict]:
    """partition.json _temp_holds：过了 expires_at，或没写 expires_at 且挂了 > no_expiry_max_s → 违约，派挂道的人（by）"""
    out = []
    for lane, h in (holds or {}).items():
        if not isinstance(h, dict):
            continue
        t0, exp = ts(h.get("at")), ts(h.get("expires_at"))
        age = now - (t0 or now)
        bad = (exp is not None and now > exp) or (exp is None and age > cfg["no_expiry_max_s"])
        why = f"已过期 {(now - exp) / 60:.0f} 分钟" if exp is not None and now > exp else f"没写 expires_at，已挂 {age / 60:.0f} 分钟"
        f = F("S18", lane, bad, f"临时挂道 {lane} {why}（{str(h.get('why') or '')[:60]}）", at=h.get("at"), expires_at=h.get("expires_at"),
              by=h.get("by"), why=h.get("why"), age_s=round(age))
        f["owner_loop"] = h.get("by") or cfg.get("owner_loop")
        out.append(f)
    return out


# ------------------------------------------------------------------ S19 产能见底（总调度 11:1x）
def j_capacity(ready: dict[str, int], pending_drafts: list[str], recent_imports: list[str], cfg: dict,
               not_producing: dict[str, dict] | None = None) -> list[dict]:
    """ready = 每台“可派”的 ready（只算 run.status=producing 的 run）；not_producing = {台: {run: ready}} 已导入但 run 还不是 producing、派不出去的，
    单独写进证据、不算可派（总调度 11:2x：第二季在 sv-08 部署、series10_s2 变 producing 之前派不出去）。
    合计 < 道数 × ready_per_lane 且没有待导入的稿 → 违约；每台也判（本机道数 × ready_per_lane），单里写清哪台见底、另一台还剩多少"""
    if not ready:
        return []
    np_ = not_producing or {}
    np_total = sum(sum(v.values()) for v in np_.values())
    total = sum(ready.values())
    floor = int(cfg["lanes"]) * int(cfg["ready_per_lane"])
    cause = "导入了没放单（最近导入：" + "、".join(recent_imports[:6]) + "）" if recent_imports else "没有新稿可导入"
    np_txt = f"；另有 {np_total} 个 ready 属于还不是 producing 的 run（派不出去）" if np_total else ""
    f = F("S19", "capacity", total < floor and not pending_drafts,
          f"产能见底：可派 ready 合计 {total} < 道数 × {cfg['ready_per_lane']} = {floor}，{cause}{np_txt}",
          ready=ready, total=total, floor=floor, not_producing=np_, pending_drafts=pending_drafts[:10], recent_imports=recent_imports[:10])
    f["owner_loop"] = cfg.get("owner_loop")
    out = [f]
    for h, n in ready.items():                       # 每台也看：分区不均时一台见底、另一台有单（11:01 gpu33 空 30 分钟）
        lanes = int((cfg.get("host_lanes") or {}).get(h, 0))
        if not lanes:
            continue
        others = "、".join(f"{o} 还剩 {m}" for o, m in ready.items() if o != h) or "没有别的机器"
        hnp = sum((np_.get(h) or {}).values())
        hf = F("S19", f"capacity:{h}", n < lanes * int(cfg["ready_per_lane"]) and not pending_drafts,
               f"{h} 见底：可派 ready {n} < 本机道数 {lanes} × {cfg['ready_per_lane']}；{others}"
               + (f"；{h} 另有 {hnp} 个 ready 属于非 producing 的 run（派不出去）" if hnp else "") + "——可改分区（config/netfix/partition.json）",
               host=h, ready=n, lanes=lanes, others={o: m for o, m in ready.items() if o != h}, not_producing=np_.get(h) or {}, total=total)
        hf["owner_loop"] = cfg.get("owner_loop")
        out.append(hf)
    return out


# ------------------------------------------------------------------ G26 声明 vs 实际（总调度 11:2x）
def lane_gpu_actual(a: dict) -> int | None:
    """监听进程实际用的 GPU：--cuda-device 优先，其次 CUDA_VISIBLE_DEVICES（单卡），再次 nvidia-smi 计算进程所在卡（唯一时）"""
    if a.get("cuda_arg") is not None:
        return int(a["cuda_arg"])
    cvd = str(a.get("cvd") or "")
    if cvd.isdigit():
        return int(cvd)
    g = a.get("smi_gpus") or []
    return int(g[0]) if len(g) == 1 else None


def j_decl_vs_actual(host: str, decl: dict, actual: dict, broken: list, broken_apps: dict) -> list[dict]:
    """decl = hosts.json 里本机 enabled 的道 {lane: {gpu, comfy_port, ...}}；actual = remote_probe g26_lanes {port: {...}}。
    每条道一张单（不可达 / system_stats 不正常 / GPU 序号不符 合在一起写）；坏卡有作业另开一张。派单：运行期 DEBUG-RSI，声明错了 FACTORY 改 hosts.json"""
    out = []
    for lane, rec in decl.items():
        a = actual.get(str(int(rec["comfy_port"])))
        if a is None:
            continue
        why = []
        if not a.get("pid"):
            why.append(f"端口 {rec['comfy_port']} 没有进程在听")
        if not a.get("stats_ok"):
            why.append(f"system_stats 不正常（{a.get('err', '')[:60]}）")
        g = lane_gpu_actual(a)
        if a.get("pid") and g is not None and g != int(rec["gpu"]):
            why.append(f"声明 GPU {rec['gpu']}，实际跑在 GPU {g}")
        f = F("G26", lane, bool(why), f"{lane} 声明与实际不符：{'；'.join(why)}", declared={"gpu": rec.get("gpu"), "port": rec.get("comfy_port")},
              actual={k: a.get(k) for k in ("pid", "cuda_arg", "cvd", "smi_gpus", "stats_ok", "devices")}, gpu_actual=g)
        f["owner_loop"] = "DEBUG-RSI（运行期）/ FACTORY（若 hosts.json 声明错）"
        out.append(f)
    for i in broken:
        pids = broken_apps.get(str(i))
        if pids is None:
            continue
        f = F("G26", f"{host}:broken{i}", bool(pids), f"{host} 坏卡 GPU {i} 上有作业（pid {pids}）——坏卡永不用", host=host, gpu=i, pids=pids)
        f["owner_loop"] = "DEBUG-RSI"
        out.append(f)
    return out


# ------------------------------------------------------------------ S20 scratchpad 进程（K-OPS-Y04）
def j_scratch_procs(procs: list[dict] | None, cfg: dict) -> list[dict]:
    """procs = [{pid, name, cmd}]（python / sh / bash）。命令行命中 scratchpad 路径即违约，每个脚本名一张单（同脚本多进程合并）；
    负责方按脚本名查 owner_by_script，查不到派 owner_loop（总调度）；known 里的标“已知，sv-10 收编”"""
    import re
    if procs is None:
        return []
    rx = re.compile(cfg["path_match"], re.I)
    hits: dict[str, list] = {}
    for p in procs:
        cmd = str(p.get("cmd") or "")
        if not rx.search(cmd):
            continue
        # 只认“脚本本身放在 scratchpad 里”（tools/ 下的脚本把输出写到 scratchpad 不算）；Claude 工具的 shell 快照（snapshot-bash-*.sh）不算
        m = [x for x in re.findall(r"scratchpad/[^\"'\s]*?([\w.\-]+\.(?:py|sh|ps1|mjs))", cmd.replace("\\", "/"), re.I)
             if not x.startswith("snapshot-bash-")]
        if not m:
            continue
        hits.setdefault(m[-1], []).append(p)
    out = []
    for script, ps0 in hits.items():
        pids = {p.get("pid") for p in ps0}
        ps = [p for p in ps0 if p.get("ppid") not in pids]          # .venv 转发器 + 子进程 = 一份（总调度 20:10）
        known = (cfg.get("known") or {}).get(script)
        exempt = (cfg.get("readonly_exempt") or {}).get(script)
        if exempt and not any(re.search(r"\bssh\b|\bscp\b|rsh\.py", str(p.get("cmd") or "")) for p in ps):
            # 只读豁免（总调度认领、命令行里没有 ssh）：出“正常”finding，已开的单自动关
            f = F("S20", script, False, f"{script} 在 scratchpad 里跑，但已登记为只读豁免：{exempt}", script=script, pids=[p.get("pid") for p in ps], exempt=exempt)
            f["owner_loop"] = "总调度"
            out.append(f)
            continue
        f = F("S20", script, True, f"scratchpad 里在跑 {script}（{len(ps)} 个进程，pid {[p.get('pid') for p in ps][:5]}）——K-OPS-Y04：会改生产状态的代码不许从 scratchpad 跑"
              + (f"【{known}】" if known else ""), script=script, pids=[p.get("pid") for p in ps], cmd=str(ps[0].get("cmd"))[:200], known=known)
        f["owner_loop"] = (cfg.get("owner_by_script") or {}).get(script) or cfg.get("owner_loop")
        out.append(f)
    return out


# ------------------------------------------------------------------ S21 / S22（SYSARCH / FACTORY 12:3x）
def j_legacy_reads(rows: list[dict], names: list[str], now: float, cfg: dict, owner_of=lambda caller: None) -> list[dict]:
    """rows = data/state/legacy_reads.jsonl；每个登记的状态名一张单：window_s 内有旧路径读取即违约（sv-11 删旧读前提 = 0）"""
    recent: dict[str, list] = {}
    for r in rows:
        t = ts(r.get("at"))
        if t is not None and now - t <= cfg["window_s"]:
            recent.setdefault(r.get("name"), []).append(r)
    out = []
    for name in sorted(set(names) | set(recent)):
        rs = recent.get(name) or []
        callers: dict[str, int] = {}
        for r in rs:
            callers[str(r.get("caller"))] = callers.get(str(r.get("caller")), 0) + 1
        owners = sorted({o for o in (owner_of(c) for c in callers) if o}) or ([cfg.get("owner_loop")] if rs else [])
        f = F("S21", str(name), bool(rs), f"24 小时内读旧路径 {rs[0].get('old_path') if rs else ''} 共 {len(rs)} 次（状态 {name}）——sv-11 删旧读前要清零",
              name=name, n=len(rs), callers=callers, hosts=sorted({str(r.get('host')) for r in rs}), last=rs[-1].get("at") if rs else None)
        f["owner_loop"] = " / ".join(owners) or "总调度"
        out.append(f)
    return out


def j_freeze_drift(rows: list[dict], last_cut: dict | None, owner_of=lambda path: None) -> list[dict]:
    """rows = data/rsi/freeze_drift.jsonl {sv, at, files}；每条按文件负责方分组开单；之后有成功的 cut（时间晚于记录）→ 已进下一版，关单"""
    ok_t = float(last_cut["at"]) if last_cut and last_cut.get("ok") and last_cut.get("at") is not None else None
    out = []
    for r in rows:
        t = ts(r.get("at"))
        groups: dict[str, list] = {}
        for fpath in r.get("files") or []:
            groups.setdefault(owner_of(fpath) or "总调度", []).append(fpath)
        for own, files in groups.items():
            done = ok_t is not None and t is not None and ok_t > t
            f = F("S22", f"{r.get('sv')}:{own}", not done, f"{r.get('sv')} 冻结期间改了 {len(files)} 个文件（{own}）：{'、'.join(files[:4])}"
                  + ("——之后已成功 cut，改动进了下一版" if done else "——不会进这一版，请确认并在解冻后重提 / 留到下一版"),
                  sv=r.get("sv"), at=r.get("at"), files=files[:30])
            f["owner_loop"] = own
            out.append(f)
    return out


# ------------------------------------------------------------------ S23 笔记本侧出图道可达率（总调度 13:2x）
def j_lane_reach(hist: dict[str, list], cur: dict[str, bool], now: float, cfg: dict) -> list[dict]:
    """hist = {lane: [[t, ok], ...]}（含本拍）；cur = 本拍 {lane: ok}。
    每条道：window_s 内可达率 < min_ratio → 违约；全局：本拍不通的道 ≥ half_down × 道数 → 违约（隧道整体抖 / 断）"""
    out = []
    for lane, h in hist.items():
        w = [ok for t, ok in h if now - t <= cfg["window_s"]]
        if len(w) < int(cfg.get("min_samples", 3)):      # 样本太少不判可达率（一次重连就开单太吵；整体断由 half_down 管）
            continue
        ratio = sum(1 for x in w if x) / len(w)
        f = F("S23", lane, ratio < cfg["min_ratio"], f"笔记本侧 {lane} {cfg['window_s'] // 60} 分钟可达率 {ratio:.0%} < {cfg['min_ratio']:.0%}（{len(w)} 次测量）",
              ratio=round(ratio, 2), n=len(w), now_ok=cur.get(lane))
        f["owner_loop"] = cfg.get("owner_loop")
        out.append(f)
    if cur:
        down = sorted(ln for ln, ok in cur.items() if not ok)
        f = F("S23", "half_down", len(down) >= cfg["half_down"] * len(cur), f"笔记本侧本拍 {len(down)}/{len(cur)} 条出图道同时不通：{'、'.join(down)}",
              down=down, total=len(cur))
        f["owner_loop"] = cfg.get("owner_loop")
        out.append(f)
    return out


# ------------------------------------------------------------------ S20 扩展：会话 shell 里的 ssh 轮询（总调度 13:3x）
def j_ssh_loops(shells: dict, spawns: dict, now: float, cfg: dict, owner_by_cmd=lambda c: None) -> list[dict]:
    """shells = {pid: {cmd, created_t}}（bash / sh / pwsh / powershell）；spawns = {shell_pid: [ssh 新起时刻]}。
    活了 > min_age_s 且 window_s 内在它下面新起 ssh ≥ min_spawns → 违约，派起它的 loop（命令行看不出派总调度）"""
    out = []
    for pid, sh in shells.items():
        age = now - (sh.get("created_t") or now)
        n = sum(1 for t in spawns.get(pid, []) if now - t <= cfg["window_s"])
        if n == 0:                                   # 没起 ssh 的 shell 不出 finding；之前开过的单由 p_s20 的“已不在”补正常关掉
            continue
        bad = age >= cfg["min_age_s"] and n >= cfg["min_spawns"]
        f = F("S20", f"ssh_loop:{pid}", bad, f"会话 shell pid {pid} 已跑 {age / 3600:.1f} 小时，{cfg['window_s'] // 60} 分钟内新起 ssh {n} 次——疑似永不结束的轮询（跳板新建连接）",
              pid=pid, age_h=round(age / 3600, 1), spawns=n, cmd=str(sh.get("cmd"))[:240])
        f["owner_loop"] = owner_by_cmd(str(sh.get("cmd"))) or cfg.get("owner_loop") or "总调度"
        out.append(f)
    return out


# ------------------------------------------------------------------ S24 API 响应时间（总调度 14:1x）
def p95(vals: list[float]) -> float:
    v = sorted(vals)
    return v[min(len(v) - 1, max(0, int(round(0.95 * len(v) + 0.5)) - 1))]


def j_api_latency(hist: dict[str, list], cfg: dict) -> list[dict]:
    """hist = {path: [[t, 秒, http 状态], ...]}；最近 last_n 次（≥ 5 次才判）的 p95 ≥ p95_max_s → 违约；失败 / 超时按 timeout_s 计"""
    out = []
    for path, h in hist.items():
        w = h[-int(cfg["last_n"]):]
        if len(w) < 5:
            continue
        secs = [float(x[1]) if x[2] == 200 else float(cfg["timeout_s"]) for x in w]
        q = p95(secs)
        fails = sum(1 for x in w if x[2] != 200)
        f = F("S24", path, q >= cfg["p95_max_s"], f"{path} 最近 {len(w)} 次 p95 {q:.2f} s ≥ {cfg['p95_max_s']} s（失败 {fails} 次）——页面会卡在加载",
              p95_s=round(q, 3), n=len(w), max_s=round(max(secs), 2), fails=fails)
        f["owner_loop"] = cfg.get("owner_loop")
        out.append(f)
    return out


# ------------------------------------------------------------------ S25 常驻 CLIP（FACTORY 口径，总调度 14:3x）
def j_clip(host: str, r: dict | None, cfg: dict) -> list[dict]:
    """r = {pid_alive: bool|None, health: "ok"|"timeout"|"ERR …", reloads_1h: int}；进程不在 / 一小时重载 > reload_max_per_h → 违约。
    /health 超时（单线程忙）不单独算挂，只写进证据"""
    if not r:
        return []
    out = []
    if r.get("pid_alive") is not None:
        f = F("S25", f"{host}:alive", not r["pid_alive"], f"{host} 常驻 CLIP 进程不在（pid 文件 {cfg['pid_file']}；/health {r.get('health')}）",
              pid=r.get("pid"), health=r.get("health"))
        f["owner_loop"] = cfg.get("owner_loop")
        out.append(f)
    if r.get("reloads_1h") is not None:
        f = F("S25", f"{host}:reload", r["reloads_1h"] > cfg["reload_max_per_h"], f"{host} 常驻 CLIP 一小时重载 {r['reloads_1h']} 次 > {cfg['reload_max_per_h']}（{cfg['reload_reason']}）",
              reloads_1h=r["reloads_1h"])
        f["owner_loop"] = cfg.get("owner_loop")
        out.append(f)
    return out


# ------------------------------------------------------------------ SCORECARD（总调度 17:4x）
def j_scorecard(res: dict, owners: dict) -> list[dict]:
    """七项每项一张单：< 100 即违约，派负责方并抄送总调度；证据写最低分项、未测条目、打分器出处"""
    out = []
    for line, r in res.items():
        if r and r.get("score") is None and r.get("pending_stage"):
            out.append(F("SC", line, False, f"SCORECARD {line} 阶段未到：{r['pending_stage']}", pending_stage=r["pending_stage"]))   # 关掉旧单
            continue
        if not r or r.get("score") is None:
            continue
        low = r.get("lowest")
        parts = r.get("parts") or {}
        f = F("SC", line, float(r["score"]) < 100, f"SCORECARD {line} {r['score']} 分 < 100：最低分项 {low}={parts.get(low)}"
              + (f"；未测：{'、'.join(r['unmeasured'][:3])}" if r.get("unmeasured") else ""),
              score=r["score"], parts=parts, lowest=low, unmeasured=r.get("unmeasured"), src=r.get("src"), evidence=r.get("evidence"))
        f["owner_loop"] = f"{owners.get(line, '总调度')}（抄送总调度）"
        out.append(f)
    return out


# ------------------------------------------------------------------ S26 / S27（总调度 20:10）
def j_autoflow_resident(hb: dict | None, mtime: float | None, now: float, cfg: dict) -> list[dict]:
    t = ts((hb or {}).get("t") or (hb or {}).get("at")) or mtime
    age = None if t is None else now - t
    bad = age is None or age > cfg["stale_s"]
    f = F("S26", "heartbeat", bad, f"写作推进常驻服务心跳{'不存在' if age is None else f' {age:.0f} s 没更新'}（上限 {cfg['stale_s']} s）",
          age_s=None if age is None else round(age), pid=(hb or {}).get("pid"), runs=(hb or {}).get("runs"), last_started=(hb or {}).get("last_started"))
    f["owner_loop"] = cfg.get("owner_loop")
    return [f]


def j_review_chain(rounds: list[dict], now: float, cfg: dict) -> list[dict]:
    """rounds = [{name, done: [交卷时刻], result_t: RESULT.json 修改时刻或 None}]；交齐 judges 份后 aggregate_max_s 内没有更新的 RESULT → 违约（每轮一张）"""
    out = []
    for r in rounds:
        if len(r["done"]) < cfg["judges"]:
            continue
        last = max(r["done"])
        ok = r.get("result_t") is not None and r["result_t"] >= last - 5
        late = now - last > cfg["aggregate_max_s"]
        f = F("S27", r["name"], (not ok) and late, f"P1 评审 {r['name']} 交齐 {now - last:.0f} s 了还没自动汇总（上限 {cfg['aggregate_max_s']} s）",
              last_done=iso(last), result_at=iso(r.get("result_t")))
        f["owner_loop"] = cfg.get("owner_loop")
        out.append(f)
    return out


def j_ui_measure(m: dict, owner: str) -> list[dict]:
    """SCORECARD 界面实测的扣分项按页开单（总调度 20:3x）：技术词一张、彩色胶囊 / 口径矛盾 / 裂图一张；探针失败的页不判"""
    out = []
    for page, p in (m.get("pages") or {}).items():
        if p.get("error"):
            continue
        jg = p.get("jargon") or []
        f = F("S9", f"sc{page}:jargon", bool(jg), f"界面 {page} 出现技术词：{'、'.join(jg)}", page=page, words=jg, at=m.get("at"))
        f["owner_loop"] = owner
        out.append(f)
        caps, con, brk = p.get("color_capsules") or [], p.get("contradictions") or [], p.get("broken_imgs") or []
        f = F("S9", f"sc{page}:clean", bool(caps or con or brk), f"界面 {page} 不整洁：彩色胶囊 {len(caps)} 个、口径矛盾 {len(con)} 处、裂图 {len(brk)} 张"
              + (f"（{con[0][:40]}）" if con else ""), page=page, capsules=caps[:6], contradictions=con[:4], broken=brk[:4], at=m.get("at"))
        f["owner_loop"] = owner
        out.append(f)
    return out


def j_q10(fails: int, last: dict, cfg: dict) -> list[dict]:
    """连续 fail_n 次失败（不通，或 loaded 不是 true）→ 违约：两台首帧都会卡在 Q10（失败关闭）"""
    why = last.get("err") or ("loaded=" + str(last.get("loaded")) if last.get("ok") else "不通")
    f = F("S28", "q10_detector", fails >= cfg["fail_n"], f"Q10 人数检测服务（{cfg['url']}，从 {cfg['from_host']} 测）连续 {fails} 次失败：{why}——两台首帧会全卡在 Q10",
          fails=fails, last=last)
    f["owner_loop"] = cfg.get("owner_loop")
    return [f]


def now() -> float:
    return time.time()
