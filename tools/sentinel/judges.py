"""SENTINEL 判定层（纯函数、可测、实时与回放共用；规则 K-OPS-S01）。

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


def j_vqa_endpoint(host: str, port: int, models_reply: str | None, listener: str) -> list[dict]:
    """打分服务必须是 vLLM（/v1/models 有 data）；端口被别的进程（例：13 小时前的旧 server.py）占着 = 违约"""
    if models_reply is None:
        return []
    ok = '"data"' in models_reply and '"object"' in models_reply
    return [F("S3", f"vqa:{host}:{port}", not ok, f"{host}:{port} 打分服务不是 vLLM（/v1/models 无模型列表；监听进程：{listener[:80] or '未知'}）",
              reply=models_reply[:200], listener=listener[:300])]


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


def now() -> float:
    return time.time()
