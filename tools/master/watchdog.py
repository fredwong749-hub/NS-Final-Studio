"""看门狗（W19 WATCHDOG-CODE，L-163“所有自动化写在代码上，少用 Agent 来推”）：总调度每 30 分钟的巡检规则写成代码，由 autoflow_resident 自己跑。

    .venv/Scripts/python.exe tools/master/watchdog.py run --dry     # 只列出会登记什么，不写任何文件
    .venv/Scripts/python.exe tools/master/watchdog.py run           # 登记卡点（who=WATCHDOG-CODE）+ ⏫ 升级 + 早报一行时间线

规则（每条 = 检测 + 去重键 + 登记文案；阈值在 config/master/watchdog.json）：
  1 同一错误反复    autoflow.log 同集连续 ≥3 条相同 error note，且停下后 30 分钟无人处理（daemon 自己 3 次停重试，这里兜底）
  2 空转出包        writer_tasks 同 step 在 10 分钟内有 ≥2 个未交稿、未作废的包（03:32 P4_ep01_a2/a3/a4 事故，ISS-81fd）
  3 心跳陈旧        resident / asset_worker / 主剧 producer 心跳 > 10 分钟；主剧无 producer 而 sop_gate 阶段在出图段 → P0“GPU 空转”
  4 抢跑            有首帧 takes 但“提示词”没放行；有视频片段但“尾帧”没放行（对照 sop_gate.status）
  5 V1 泄漏         未交稿的 writer_tasks/*.json 与 config/prompts/*.md 命中 v1_guard 词表（不含画风词）
  6 代码 agent 数    agent_dispatcher running + Orca 活着的工人 > 4
  7 卡点板陈旧      阻断卡点 > 2 小时无人 close / 回应 → V2_LIVE 顶部一行“⏫”（每条只升级一次）
  8 决策与开关      master_check ④ 不一致 → P0
  9 发版落后        工作树未提交 > 150 且最近一次 sv- cut 超过 24 小时（C-25）
 10 API :8800 不在  GET /api/owner/queue 非 200 / 连不上 → ops/restart_api.ps1 -Force -Revive 补起一次（enabled=false 只登记），
                    wait_s 内再探仍不通才登记阻断卡点；补起成功写一行 V2_LIVE，不开 ISS（W27，ISS-1103-172328）。--dry 只探不补
去重：登记文案带“〔wd:<键>〕”；同键还有 open 卡点 → 不再登记；登记过的键 re_register_after_h 内不重登（状态 data/master/watchdog_state.json）。
每轮（非 --dry）：docs/overnight/morning_<日期>.md 追加一行时间线（无变化只写“无变化”），data/master/watchdog_last.json 给 master_check ⑧。
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WHO = "WATCHDOG-CODE"
CFG_REL = "config/master/watchdog.json"
STATE_REL = "data/master/watchdog_state.json"
LAST_REL = "data/master/watchdog_last.json"
ACTIVE = ("preparing", "active", "producing")
DEFAULT_CFG = {"every_s": 1800, "same_error_min": 3, "same_error_idle_min": 30, "idle_packets_window_min": 10, "idle_packets_min": 2,
               "heartbeat_stale_min": 10, "gpu_stages": ["出图", "出图检测", "尾帧", "视频"], "max_code_agents": 4,
               "blocking_stale_h": 2, "escalate_max_ids": 8, "dirty_files_max": 150, "cut_stale_h": 24, "re_register_after_h": 6,
               "max_register_per_round": 8, "orca_cmds": [], "orca_snapshot": "data/master/orca_workers.json",
               "orca_snapshot_max_age_min": 60, "orca_timeout_s": 45, "git_timeout_s": 90,
               "api_revive": {"enabled": True, "url": "http://127.0.0.1:8800/api/owner/queue", "timeout_s": 15, "wait_s": 60, "poll_s": 5,
                             "script": "ops/restart_api.ps1", "run_timeout_s": 330}}
KEY_RE = re.compile(r"〔wd:([^〕]+)〕")


def _load(name: str, rel: str, root: Path = ROOT):
    sp = importlib.util.spec_from_file_location(name, root / rel)
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


def _j(p: Path, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):   # arch-ok: 看门狗只读，缺文件 = 按缺处理
        return default


def _ts(x) -> float | None:
    """心跳 / 日志时间：float 秒或本地 ISO 串 → 秒；读不出 = None"""
    if x is None or x == "":
        return None
    if isinstance(x, (int, float)):
        return float(x)
    try:
        return datetime.fromisoformat(str(x)[:19]).timestamp()
    except ValueError:
        return None


def _hm(t: float) -> str:
    return time.strftime("%H:%M", time.localtime(t))


def config(root: Path = ROOT) -> dict:
    return {**DEFAULT_CFG, **(_j(root / CFG_REL, {}) or {})}


def finding(rule: int, key: str, what: str, *, run: str = "-", episode: int = 0, step: str = "看门狗", blocking: bool = False,
            p0: bool = False, fix_hint: str = "", brief: str = "") -> dict:
    return {"rule": rule, "key": f"r{rule}:{key}", "run": run, "episode": int(episode or 0), "step": step, "blocking": bool(blocking or p0),
            "p0": p0, "what": what, "fix_hint": fix_hint, "brief": brief or what[:60]}


# ------------------------------------------------------------------ 上下文（真实部件；测试逐项替换）
class Ctx:
    def __init__(self, root: Path = ROOT, now: float | None = None, cfg: dict | None = None):
        self.root, self.now = Path(root), now or time.time()
        self.cfg = cfg or config(self.root)
        self._sg = None
        self.dry = False
        self._revived = False

    def registry(self) -> dict:
        return _j(self.root / "config/pipeline/runs.json", {}) or {}

    def active_runs(self) -> list[str]:
        return sorted(r for r, v in (self.registry().get("runs") or {}).items() if (v or {}).get("status") in ACTIVE)

    def primary(self) -> str | None:
        return (_j(self.root / "config/pipeline/run.json", {}) or {}).get("run_id") or self.registry().get("primary")

    def run_dir(self, run: str) -> Path:
        return self.root / "data/pipeline/runs" / run

    def sg(self):
        if self._sg is None:
            self._sg = _load("sop_gate_wd", "tools/master/sop_gate.py", ROOT)
        return self._sg

    def sop_status(self, run: str) -> list[dict]:
        return self.sg().status(run, self.root)

    def has_images(self, run: str, ep: int) -> bool:
        return any(v.get("image") for v in self.sg().shot_frames(self.root, run, ep).values())

    def has_videos(self, run: str, ep: int) -> bool:
        return any((self.run_dir(run) / "video" / "clips" / f"ep{ep:02d}").glob("*.mp4"))

    def v1_vocab(self, run: str | None) -> tuple[list[str], list[str]]:
        """v1_guard 词表（与写手包出口 script_chat.v1_vocab 同口径），但不含画风词（style）：人物 / id / 场景 / 剧名 / 道具 + extra_ids，
        本剧 P1 / 造型 / brief 里合法出现的词与弱词剔除；放行短语 = v1_leak allow_text + v1_guard allow_phrases"""
        VL = _load("v1_leak_wd", "tools/script_rsi/v1_leak.py", ROOT)
        v = VL.vocab(self.root, current=run)
        g = VL.guard_cfg(self.root)
        words = set(g.get("extra_ids") or [])
        for k in ("names", "char_ids", "scenes", "titles", "props"):
            words |= set(v.get(k) or [])
        own = "\n".join((self.run_dir(run) / f).read_text(encoding="utf-8") for f in ("P1_storyline.json", "P1_looks.json", "P0_brief.json")
                        if run and (self.run_dir(run) / f).is_file())
        weak = set((g.get("weak_props") or {}).get("items") or [])
        words = sorted(w for w in words if w and len(w) >= 2 and w not in own and w not in weak)
        allow = [a for a in list(v.get("allow_text") or []) + list((g.get("allow_phrases") or {}).get("items") or []) if a and len(a) >= 2]
        return words, allow

    def dispatcher_running(self) -> list[str]:
        st = _j(self.root / "data/factory/agent_dispatcher/state.json", {}) or {}
        return sorted(k for k, v in (st.get("requests") or {}).items() if (v or {}).get("running"))

    def orca_live(self) -> tuple[int | None, str]:
        """Orca 活着的工人数：先读总调度 / 脚本写的快照（新鲜的才算），再试 orca CLI；都不可见 = (None, 原因)"""
        snap = self.root / self.cfg.get("orca_snapshot", "")
        d = _j(snap, None) if self.cfg.get("orca_snapshot") else None
        if isinstance(d, dict) and _ts(d.get("at")) and self.now - _ts(d.get("at")) <= 60 * self.cfg["orca_snapshot_max_age_min"]:
            return int(d.get("live") or 0), str(snap.relative_to(self.root))
        for cmd in self.cfg.get("orca_cmds") or []:
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=self.cfg.get("orca_timeout_s", 45), encoding="utf-8", errors="replace",
                                   stdin=subprocess.DEVNULL)   # 不给 stdin：Windows 下 orca.exe 继承 stdin 会挂住
                ws = ((json.loads(r.stdout or "{}").get("result") or {}).get("workers")) or []
            except (OSError, subprocess.SubprocessError, ValueError):   # arch-ok: 这台机器没有 orca CLI = 试下一个
                continue
            live = [w for w in ws if w.get("liveness") == "live" and w.get("state") not in ("succeeded", "failed", "cancelled")]
            return len(live), " ".join(cmd[:3])
        return None, "Orca 不可见（无快照、无 CLI）"

    def git_dirty(self) -> int | None:
        try:
            r = subprocess.run(["git", "status", "--porcelain"], cwd=self.root, capture_output=True, text=True, timeout=self.cfg["git_timeout_s"],
                               encoding="utf-8", errors="replace")
            return len([ln for ln in (r.stdout or "").splitlines() if ln.strip()]) if r.returncode == 0 else None
        except (OSError, subprocess.SubprocessError):   # arch-ok: 拿不到 = 本条不判
            return None

    def last_cut(self) -> tuple[float | None, str]:
        try:
            r = subprocess.run(["git", "log", "-1", "--format=%ct %h %s", "--grep=^sv-"], cwd=self.root, capture_output=True, text=True,
                               timeout=self.cfg["git_timeout_s"], encoding="utf-8", errors="replace")
            t, _, rest = (r.stdout or "").strip().partition(" ")
            return (float(t), rest[:40]) if t else (None, "")
        except (OSError, subprocess.SubprocessError, ValueError):   # arch-ok: 拿不到 = 本条不判
            return None, ""

    def switch_bad(self) -> list[dict]:
        MC = _load("master_check_wd", "tools/master/master_check.py", ROOT)
        return [r for r in MC.switch_rows(self.root) if not r["ok"]]

    def api_up(self) -> bool:
        a = self.cfg["api_revive"]
        try:
            with urllib.request.urlopen(a["url"], timeout=a["timeout_s"]) as r:
                return r.status == 200
        except (OSError, ValueError):   # arch-ok: 连不上 / 非 200（HTTPError 是 OSError）/ 超时 = API 不在
            return False

    def api_revive(self) -> int | None:
        """补起 :8800：只调 ps1（-Revive 自己再测一次、健康就不动；本函数不杀任何进程）；一轮最多一次"""
        if self._revived:
            return None
        self._revived = True
        a = self.cfg["api_revive"]
        try:
            r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(self.root / a["script"]), "-Force", "-Revive"],
                               capture_output=True, text=True, timeout=a["run_timeout_s"], encoding="utf-8", errors="replace",
                               stdin=subprocess.DEVNULL, cwd=self.root)
            return r.returncode
        except (OSError, subprocess.SubprocessError):   # arch-ok: 起不来 = 按补起失败，下面再探一次后登记
            return -1

    def sleep(self, s: float) -> None:
        time.sleep(s)

    def live_note(self, line: str) -> None:
        RI = _load("report_issue_wd", "tools/master/report_issue.py", ROOT)
        RI._insert_live(line, self.root / "docs/master/V2_LIVE.md")

    def issue_events(self) -> list[dict]:
        p = self.root / "data/pipeline/issues.jsonl"
        out = []
        if p.is_file():
            for ln in p.read_text(encoding="utf-8").splitlines():
                try:
                    out.append(json.loads(ln))
                except ValueError:   # arch-ok: 追加写偶发坏行跳过
                    continue
        return out


def open_issues(events: list[dict]) -> list[dict]:
    cur: dict[str, dict] = {}
    for e in events:
        if e.get("event") == "open":
            cur[e["id"]] = dict(e)
        elif e.get("event") == "close" and e.get("id") in cur:
            cur[e["id"]]["status"] = "closed"
    return [i for i in cur.values() if i.get("status") == "open"]


# ------------------------------------------------------------------ 规则
def r1_same_error(c: Ctx) -> list[dict]:
    out = []
    n_min, idle = c.cfg["same_error_min"], 60 * c.cfg["same_error_idle_min"]
    for run in c.active_runs():
        log = c.run_dir(run) / "autoflow.log"
        if not log.is_file():
            continue
        last: dict[int, list] = {}                     # 每集：最近一段连续相同 error（跳过 verdict=None 的“开始”行）
        for i, ln in enumerate(log.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            try:
                e = json.loads(ln)
            except ValueError:   # arch-ok: 坏行跳过
                continue
            ep, v = e.get("episode"), e.get("verdict")
            if ep is None or v is None:
                continue
            s = last.get(ep)
            if v == "error":
                if s and s[0] == e.get("note"):
                    s[1] += 1
                    s[3] = (e.get("at"), i)
                else:
                    last[ep] = [e.get("note"), 1, (e.get("at"), i), (e.get("at"), i)]
            elif v != "halted_error":
                last.pop(ep, None)                     # 有别的进展 = 这段错误已被处理
        for ep, (note, n, (t0, l0), (t1, l1)) in sorted(last.items()):
            age = c.now - (_ts(t1) or c.now)
            if n < n_min or age < idle:
                continue
            rel = log.relative_to(c.root).as_posix()
            out.append(finding(1, f"{run}:ep{int(ep):02d}:{str(note)[:80]}", run=run, episode=ep, step="autoflow 推进", blocking=True,
                               what=f"第{int(ep)}集 autoflow 连续 {n} 次同一错误后停下已 {int(age // 60)} 分钟无人处理：{str(note)[:160]}"
                                    f"（{rel} 第 {l0}–{l1} 行，{str(t0)[11:16]}–{str(t1)[11:16]}）",
                               fix_hint="按错误原文修代码 / 规则后 autoflow reopen 这一集；daemon 已停重试，不会自己恢复",
                               brief=f"ep{int(ep):02d} 同错 {n} 次停 {int(age // 60)}min"))
    return out


def _packets(c: Ctx, run: str) -> list[dict]:
    out = []
    for p in sorted((c.run_dir(run) / "writer_tasks").glob("*.json")):
        if ".void" in p.name:
            continue
        d = _j(p, {}) or {}
        if d.get("status") == "voided":
            continue
        o = d.get("output") or {}
        done = o.get("done_marker")
        delivered = bool(done) and (c.root / done).exists()
        out.append({"file": p, "name": p.name, "step": d.get("step") or p.stem, "t": _ts(d.get("created_at")), "delivered": delivered,
                    "data": d, "episode": d.get("episode")})
    return out


def r2_idle_packets(c: Ctx) -> list[dict]:
    out = []
    win, n_min = 60 * c.cfg["idle_packets_window_min"], c.cfg["idle_packets_min"]
    for run in c.active_runs():
        by: dict[str, list] = {}
        for pk in _packets(c, run):
            if not pk["delivered"] and pk["t"]:
                by.setdefault(pk["step"], []).append(pk)
        for step, pks in sorted(by.items()):
            pks.sort(key=lambda x: x["t"])
            best: list = []
            j = 0
            for i in range(len(pks)):                  # 滑动窗口：10 分钟内最多的一组
                while pks[i]["t"] - pks[j]["t"] > win:
                    j += 1
                if i - j + 1 > len(best):
                    best = pks[j:i + 1]
            if len(best) < n_min:
                continue
            names = [x["name"] for x in best]
            rel = (c.run_dir(run) / "writer_tasks").relative_to(c.root).as_posix()
            out.append(finding(2, f"{run}:{step}:{'+'.join(names)}", run=run, episode=best[0]["episode"] or 0, step=step,
                               what=f"空转出包：{step} 在 {int((best[-1]['t'] - best[0]['t']) // 60)} 分钟内出了 {len(best)} 个都没交稿的包"
                                    f"（{'、'.join(names)}，{rel}/；按 output.done_marker 判未交）",
                               fix_hint="出包前先查同 step 有没有未交稿的包；多出来的 mark_voided 并把 attempt 计数回退",
                               brief=f"{step} 10min 内 {len(best)} 包未交"))
    return out


def r3_heartbeats(c: Ctx) -> list[dict]:
    out = []
    stale = 60 * c.cfg["heartbeat_stale_min"]
    for name, rel, keys in (("resident", "data/factory/autoflow_resident.json", ("t", "at")),
                            ("asset_worker", "data/pipeline/asset_jobs/worker.json", ("at", "t"))):
        hb = _j(c.root / rel, None)
        t = next((x for x in (_ts((hb or {}).get(k)) for k in keys) if x), None)
        if t is None or c.now - t > stale:
            age = "没有心跳" if t is None else f"心跳 {int((c.now - t) // 60)} 分钟前"
            out.append(finding(3, f"{name}", step=name, blocking=True,
                               what=f"{name} {age}（{rel}，阈值 {c.cfg['heartbeat_stale_min']} 分钟）",
                               fix_hint="受控重启 ops/restart_autoflow.ps1；先看 ops/logs/autoflow_resident.life.log 退出原因",
                               brief=f"{name} {age}"))
    run = c.primary()
    if not run:
        return out
    reg = c.registry()
    pd = c.root / "data/producer" if run == reg.get("legacy_unprefixed_run") else c.root / "data/producer/runs" / run
    hb = _j(pd / "heartbeat.json", {}) or {}
    t = _ts(hb.get("t"))
    alive = bool(hb) and not hb.get("exited") and t is not None and c.now - t <= stale
    if alive:
        return out
    gpu = set(c.cfg["gpu_stages"])
    try:
        eps = [r for r in c.sop_status(run) if r.get("stage") in gpu]
    except Exception as e:  # noqa: BLE001  阶段读不出：只登记心跳本身，不判 P0
        eps, err = [], repr(e)[:80]
    else:
        err = ""
    rel = (pd / "heartbeat.json").relative_to(c.root).as_posix()
    state = "没有心跳" if not hb else ("已退出" if hb.get("exited") else f"心跳 {int((c.now - (t or 0)) // 60)} 分钟前")
    if eps:
        e0 = eps[0]
        out.append(finding(3, f"producer:{run}:gpu_idle", run=run, episode=e0["episode"], step="出图", p0=True,
                           what=f"P0 GPU 空转：主剧 {run} producer {state}（{rel}），而 sop_gate 第{e0['episode']}集阶段={e0['stage']}"
                                f"（{e0.get('why', '')[:60]}；tools/master/sop_gate.py status --run {run}）",
                           fix_hint="起 / 受控重启主剧 producer（L-152 条件满足后）；没满足 → 在卡点上写明等什么",
                           brief=f"P0 GPU 空转 ep{e0['episode']:02d}={e0['stage']}，producer {state}"))
    elif err:
        out.append(finding(3, f"producer:{run}:unknown", run=run, step="producer",
                           what=f"主剧 {run} producer {state}（{rel}），sop_gate 阶段读不出（{err}），判不了是否 GPU 空转",
                           fix_hint="先修 tools/master/sop_gate.py status 报错", brief=f"producer {state}·阶段读不出"))
    elif hb and not hb.get("exited"):
        out.append(finding(3, f"producer:{run}:stale", run=run, step="producer",
                           what=f"主剧 {run} producer {state}（{rel}，阈值 {c.cfg['heartbeat_stale_min']} 分钟）{('；阶段读不出：' + err) if err else ''}",
                           fix_hint="查 producer 进程是否卡死；受控重启一次", brief=f"producer {state}"))
    return out


def r4_jump(c: Ctx) -> list[dict]:
    out = []
    for run in c.active_runs():
        for r in c.sop_status(run):
            ep, passed = int(r["episode"]), set(r.get("passed") or [])
            for need, what, has in (("提示词", "首帧 takes", c.has_images), ("尾帧", "视频片段", c.has_videos)):
                if need in passed or not has(run, ep):
                    continue
                out.append(finding(4, f"{run}:ep{ep:02d}:{what}", run=run, episode=ep, step=need, blocking=True,
                                   what=f"抢跑：第{ep}集已有{what}，但 sop_gate“{need}”阶段没放行（当前阶段={r['stage']}：{str(r.get('why'))[:60]}；"
                                        f"tools/master/sop_gate.py status --run {run}；产物 = "
                                        f"{'sop_gate.shot_frames 读的本集 takes.json' if what == '首帧 takes' else 'sop_gate.check_video 的 video/clips/ep%02d' % ep}）",
                                   fix_hint="查是谁绕过 sop_gate.require 出的产物（violations.jsonl by 字段），挡住入口；产物先隔离不删",
                                   brief=f"ep{ep:02d} {what}抢跑（{need}未放行）"))
    return out


def _hits(text: str, words: list[str], allow: list[str]) -> list[str]:
    body = text
    for a in sorted(allow, key=len, reverse=True):
        body = body.replace(a, " ")
    out = []
    for w in words:
        if w.isascii():
            if re.search(r"(?<![A-Za-z0-9_])" + re.escape(w) + r"(?![A-Za-z0-9_])", body):
                out.append(w)
        elif w in body:
            out.append(w)
    return sorted(set(out))


def _strings(o) -> list[str]:
    if isinstance(o, str):
        return [o]
    if isinstance(o, dict):
        return [x for v in o.values() for x in _strings(v)]
    if isinstance(o, list):
        return [x for v in o for x in _strings(v)]
    return []


def r5_v1_leak(c: Ctx) -> list[dict]:
    out = []
    targets: list[tuple[str | None, Path, str]] = []
    for run in c.active_runs():
        for pk in _packets(c, run):
            if not pk["delivered"]:
                targets.append((run, pk["file"], "\n".join(_strings({k: v for k, v in pk["data"].items() if k != "output"}))))
    prim = c.primary()
    for p in sorted((c.root / "config/prompts").glob("*.md")):
        targets.append((prim, p, p.read_text(encoding="utf-8", errors="replace")))
    cache: dict = {}
    for run, p, text in targets:
        if run not in cache:
            cache[run] = c.v1_vocab(run)
        hits = _hits(text, *cache[run])
        if not hits:
            continue
        rel = p.relative_to(c.root).as_posix()
        out.append(finding(5, f"{rel}:{'+'.join(hits[:6])}", run=run or "-", step="V1 隔离", blocking=True,
                           what=f"V1 泄漏：{rel} 命中旧剧词 {'、'.join(hits[:8])}（词表 config/v1_guard.json + tools/script_rsi/v1_leak.py，不含画风词）",
                           fix_hint="规则 / 提示词里的旧剧例句改成不带剧名的写法；写作包作废重出（C-14）",
                           brief=f"{p.name} 命中 {'、'.join(hits[:3])}"))
    return out


def r6_agents(c: Ctx) -> list[dict]:
    disp = c.dispatcher_running()
    orca, src = c.orca_live()
    n = len(disp) + (orca or 0)
    cap = c.cfg["max_code_agents"]
    if n <= cap:
        return []
    return [finding(6, f"agents>{cap}", step="并发", what=f"代码 agent 数 {n} > {cap}：agent_dispatcher running {len(disp)}（data/factory/agent_dispatcher/state.json"
                    f"{'：' + '、'.join(disp[:4]) if disp else ''}）+ Orca 活着的工人 {orca if orca is not None else '?'}（{src}）",
                    fix_hint="总调度收回多出的工人（项目方 11-02/03：≤4 个代码 agent）", brief=f"agent {n}>{cap}")]


def r7_stale_blocking(c: Ctx, state: dict) -> tuple[list[dict], list[str]]:
    """返回（本轮要升级的卡点，—）；升级不登记新卡点，只往 V2_LIVE 顶部插一行 ⏫"""
    ev = c.issue_events()
    resp = {e.get("id") for e in ev if e.get("event") not in ("open", None)}
    lim = 3600 * c.cfg["blocking_stale_h"]
    done = state.get("escalated") or {}
    rows = []
    for i in open_issues(ev):
        t = _ts(i.get("time"))
        if not i.get("blocking") or i["id"] in resp or i["id"] in done or t is None or c.now - t <= lim:
            continue
        rows.append({**i, "age_h": (c.now - t) / 3600})
    rows.sort(key=lambda x: -x["age_h"])
    return rows, [r["id"] for r in rows]


def r8_switches(c: Ctx) -> list[dict]:
    return [finding(8, f"{r['name']}={r['value']}", step="开关", p0=True,
                    what=f"P0 开关和决策对不上：{r['name']}={r['value']}，要求 {r['op']} {r['want']}（{r['why']}；tools/master/master_check.py ④ SWITCH_EXPECT）",
                    fix_hint="按决策号改回开关；若决策已变，先改 SWITCH_EXPECT 再改开关", brief=f"P0 {r['name']}={r['value']}")
            for r in c.switch_bad()]


def r9_release(c: Ctx) -> list[dict]:
    n = c.git_dirty()
    if n is None or n <= c.cfg["dirty_files_max"]:
        return []
    t, what = c.last_cut()
    if t is not None and c.now - t <= 3600 * c.cfg["cut_stale_h"]:
        return []
    age = "没有 sv- 提交" if t is None else f"{int((c.now - t) // 3600)} 小时前（{what}）"
    return [finding(9, f"dirty>{c.cfg['dirty_files_max']}:{time.strftime('%m%d', time.localtime(c.now))}", step="发版",
                    what=f"发版落后：工作树 {n} 个文件未提交（git status --porcelain）> {c.cfg['dirty_files_max']}，最近一次 cut {age}（C-25 / K-OPS-V01）",
                    fix_hint="按模块分批过 tools/ops/system_version.py cut 闸门发版", brief=f"未提交 {n}，cut {age[:12]}")]


def r10_api_8800(c: Ctx) -> list[dict]:
    a = c.cfg["api_revive"]
    if c.api_up():
        return []
    url = a["url"]
    if c.dry:
        return [finding(10, "api_8800", step="API :8800", blocking=True, what=f"API :8800 不在（GET {url} 非 200 / 连不上）；--dry 不补起",
                        fix_hint="ops/restart_api.ps1 -Force -Revive", brief="API :8800 不在")]
    if not a.get("enabled", True):
        return [finding(10, "api_8800", step="API :8800", blocking=True,
                        what=f"API :8800 不在（GET {url} 非 200 / 连不上）；api_revive.enabled=false，只登记不补起",
                        fix_hint="手工 ops/restart_api.ps1 -Force -Revive", brief="API :8800 不在（未补起）")]
    rc = c.api_revive()
    up, waited, poll = c.api_up(), 0.0, max(1.0, float(a.get("poll_s", 5)))
    while not up and waited < a["wait_s"]:
        c.sleep(poll)
        waited += poll
        up = c.api_up()
    if up:
        try:
            c.live_note(f"{_hm(c.now)} 🔧 看门狗（{WHO}）：:8800 不通 → 已自动补起（ops/restart_api.ps1 -Force -Revive rc={rc}），{url} 恢复 200")
        except Exception:  # noqa: BLE001  写 V2_LIVE 失败不影响补起结论
            pass
        return []
    return [finding(10, "api_8800", step="API :8800", blocking=True,
                    what=f"API :8800 不在，已自动补起一次（ops/restart_api.ps1 -Force -Revive rc={rc}），{a['wait_s']} 秒后 GET {url} 仍不通",
                    fix_hint="看 ops/logs 里 restart_api 输出；手工 ops/restart_api.ps1 -Force", brief="API :8800 补起失败")]


RULES = [(1, r1_same_error), (2, r2_idle_packets), (3, r3_heartbeats), (4, r4_jump), (5, r5_v1_leak), (6, r6_agents), (8, r8_switches),
         (9, r9_release), (10, r10_api_8800)]


# ------------------------------------------------------------------ 一轮
def due(root: Path = ROOT, now: float | None = None) -> float:
    """离下一轮还有多少秒（≤0 = 该跑了）：按 watchdog_last.json 的 at，resident 重启也不会连跑"""
    now = now or time.time()
    last = _ts((_j(root / LAST_REL, {}) or {}).get("t"))
    return 0.0 if last is None else last + config(root)["every_s"] - now


def _write_json(p: Path, d: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + f".tmp{os.getpid()}")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def _morning_line(root: Path, now: float, line: str) -> Path:
    p = root / "docs/overnight" / f"morning_{time.strftime('%Y%m%d', time.localtime(now))}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    old = p.read_text(encoding="utf-8") if p.is_file() else f"# 早报 {time.strftime('%Y-%m-%d', time.localtime(now))}\n\n## 夜间时间线\n"
    p.write_text(old + ("" if old.endswith("\n") else "\n") + line + "\n", encoding="utf-8")
    return p


def run(root: Path = ROOT, now: float | None = None, dry: bool = False, ctx: Ctx | None = None, reporter=None, live: Path | None = None) -> dict:
    """跑一轮全部规则。dry = 只返回结论、不写任何文件。规则本身出错 → 记进 errors（其余规则照跑）"""
    c = ctx or Ctx(root, now)
    c.dry = dry
    root, now = c.root, c.now
    state = _j(root / STATE_REL, {}) or {}
    findings, errors = [], []
    for n, fn in RULES:
        try:
            findings += fn(c)
        except Exception as e:  # noqa: BLE001  一条规则坏了不拖垮整轮，如实记
            errors.append(f"规则{n}：{e!r}"[:200])
    try:
        esc_rows, esc_ids = r7_stale_blocking(c, state)
    except Exception as e:  # noqa: BLE001
        esc_rows, esc_ids = [], []
        errors.append(f"规则7：{e!r}"[:200])
    try:
        open_keys = {m for i in open_issues(c.issue_events()) for m in KEY_RE.findall(str(i.get("what") or ""))}
    except Exception as e:  # noqa: BLE001
        open_keys = set()
        errors.append(f"读卡点：{e!r}"[:200])
    keys = state.get("keys") or {}
    cool = 3600 * c.cfg["re_register_after_h"]
    plan, held = [], []
    for f in findings:
        k = f["key"]
        if k in open_keys:
            held.append({**f, "held": "同键卡点还开着"})
        elif now - (keys.get(k) or {}).get("t", 0) < cool:
            held.append({**f, "held": f"{c.cfg['re_register_after_h']} 小时内登记过 {(keys.get(k) or {}).get('id')}"})
        else:
            plan.append(f)
    over = plan[c.cfg["max_register_per_round"]:]
    plan = plan[:c.cfg["max_register_per_round"]]
    held += [{**f, "held": "本轮登记数到上限，下轮再登"} for f in over]
    esc_line = ""
    if esc_rows:
        show = esc_rows[:c.cfg["escalate_max_ids"]]
        more = f" 等 {len(esc_rows)} 条" if len(esc_rows) > len(show) else ""
        esc_line = (f"{_hm(now)} ⏫ 看门狗（{WHO}）：阻断卡点超 {c.cfg['blocking_stale_h']} 小时无人 close / 回应 {len(esc_rows)} 条："
                    + "、".join(f"{r['id']}（{r.get('who')}，{r['age_h']:.0f}h）" for r in show) + more + "（data/pipeline/issues.jsonl）")
    res = {"at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now)), "t": now, "dry": dry, "findings": len(findings),
           "by_rule": {}, "plan": plan, "held": held, "escalate": esc_ids, "escalate_line": esc_line, "errors": errors, "registered": []}
    for f in findings:
        res["by_rule"][str(f["rule"])] = res["by_rule"].get(str(f["rule"]), 0) + 1
    sig = sorted(f["key"] for f in findings)
    if dry:
        return res
    RI = None
    if reporter is None or live is None:
        RI = _load("report_issue_wd", "tools/master/report_issue.py", ROOT)
    rep = reporter or RI.report
    for f in plan:
        try:
            rec = rep(run=f["run"], episode=f["episode"], step=f["step"], who=WHO, blocking=f["blocking"],
                      what=f"{f['what']} 〔wd:{f['key']}〕", fix_hint=f["fix_hint"],
                      **({"issues": root / "data/pipeline/issues.jsonl", "live": root / "docs/master/V2_LIVE.md"} if reporter is None else {}))
            keys[f["key"]] = {"id": rec.get("id"), "t": now}
            res["registered"].append(rec.get("id"))
        except Exception as e:  # noqa: BLE001  登记失败：记 errors，下轮再试
            errors.append(f"登记 {f['key'][:40]} 失败：{e!r}"[:200])
    if esc_line:
        lp = live or root / "docs/master/V2_LIVE.md"
        try:
            (RI or _load("report_issue_wd", "tools/master/report_issue.py", ROOT))._insert_live(esc_line, lp)
            done = state.setdefault("escalated", {})
            for i in esc_ids:
                done[i] = now
        except Exception as e:  # noqa: BLE001
            errors.append(f"⏫ 写 V2_LIVE 失败：{e!r}"[:200])
    changed = sig != state.get("last_sig") or bool(res["registered"]) or bool(esc_line)
    if changed:
        parts = "、".join(f"规则{k}×{v}" for k, v in sorted(res["by_rule"].items())) or "0 命中"
        briefs = "；".join(f["brief"] for f in findings[:6])
        line = (f"- {_hm(now)} 看门狗（tools/master/watchdog.py）：{parts}" + (f"（{briefs}）" if briefs else "")
                + (f"；新登记 {'、'.join(res['registered'])}" if res["registered"] else "")
                + (f"；⏫ {len(esc_ids)} 条阻断卡点 >{c.cfg['blocking_stale_h']}h" if esc_line else "")
                + (f"；规则出错 {len(errors)}" if errors else "") + "（出处：data/master/watchdog_last.json）")
    else:
        line = f"- {_hm(now)} 看门狗：无变化"
    res["line"] = line
    try:
        res["morning"] = _morning_line(root, now, line).relative_to(root).as_posix()
    except OSError as e:
        errors.append(f"写早报失败：{e!r}"[:200])
    state.update(keys=keys, last_sig=sig, t=now)
    _write_json(root / STATE_REL, state)
    _write_json(root / LAST_REL, {k: v for k, v in res.items() if k not in ("plan", "held")} |
                {"plan": [f["key"] for f in plan], "held": len(held)})
    return res


def render(res: dict) -> str:
    out = [f"看门狗 {res['at']}{'（--dry，不写任何文件）' if res['dry'] else ''}：命中 {res['findings']} 条 "
           + ("、".join(f"规则{k}×{v}" for k, v in sorted(res["by_rule"].items())) or "")]
    for f in res["plan"]:
        out.append(f"  {'会登记' if res['dry'] else '已登记'} {'P0 ' if f['p0'] else ''}{'【阻断】' if f['blocking'] else ''}[规则{f['rule']}] {f['what']}")
    for f in res["held"]:
        out.append(f"  不重登（{f['held']}）[规则{f['rule']}] {f['brief']}")
    if res["escalate_line"]:
        out.append(f"  {'会' if res['dry'] else '已'}升级到 V2_LIVE 顶部：{res['escalate_line']}")
    for e in res["errors"]:
        out.append(f"  ⚠ {e}")
    if res.get("line"):
        out.append(f"  早报：{res['line']}")
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="跑一轮")
    r.add_argument("--dry", action="store_true", help="只列出会登记什么，不写文件")
    r.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    res = run(ROOT, dry=a.dry)
    print(json.dumps(res, ensure_ascii=False, indent=1, default=str) if a.json else render(res))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
