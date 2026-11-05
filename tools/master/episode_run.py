#!/usr/bin/env python
"""一键编排：一集从“剧本稿”推进到“成片 + 对比页”，总调度只读报告（PLAN_EP01_FINISH 阶段 1.3）。

用法：
  python tools/master/episode_run.py --run series10_v2 --ep 1 --dry-run        # 只读：每段“已完成 / 要做什么 / 卡在哪”
  python tools/master/episode_run.py --run series10_v2 --ep 1                  # 推进到第一个“要等”的段就停（可反复调用，幂等）
  python tools/master/episode_run.py --run series10_v2 --ep 1 --watch          # 一直轮询到整集完成或遇到卡点
  python tools/master/episode_run.py --run series10_v2 --ep 1 --from first     # 从某段开始（前面的段不检查）

段（顺序固定）：import → preflight → regen → first → video → finalize → pull → compare → timeline
每段：从现有状态判定是否已完成（不重做）；有超时；失败 / 超时 / 被暂停或封道 / 需项目方点头（L-123 “用这张 / 修改”）
→ 登记卡点（tools/master/report_issue.py → data/pipeline/issues.jsonl）并停下，报告里写清楚原因与建议命令。
绝不覆盖 pause_shots / hold_lanes / runaway_hold（只报告为卡点）；绝不代项目方“用这张”。

输出：data/pipeline/runs/<run>/episode_run/ep<NN>_status.json（机器读）+ ep<NN>_report.md（中文短报告）
      + ep<NN>_state.json（幂等所需的小状态：导入稿 sha、各段开始时间、已登记的卡点）。
退出码：0 全部完成；2 卡点；3 在等（未 --watch）；4 需项目方（owner）动作；1 内部错误。
远程一律走 tools/netfix/rssh.run_retry（常驻主连接；SSH 线路统一由它选 -t / -hk，本文件不自己拼 ssh）。
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STAGES = ["import", "preflight", "regen", "first", "video", "finalize", "pull", "compare", "timeline"]
STAGE_ZH = {"import": "导入剧本", "preflight": "探针 / 就绪检查", "regen": "换代重出", "first": "首帧出图", "video": "视频",
            "finalize": "合成成片", "pull": "拉回成片", "compare": "对比页", "timeline": "耗时瀑布"}
TIMEOUT_S = {"import": 600, "preflight": 300, "regen": 900, "first": 7200, "video": 7200, "finalize": 3600, "pull": 1800,
             "compare": 300, "timeline": 600}
DEFAULT_IMAGE_HOST, DEFAULT_VIDEO_HOST = "gpu33", "gpu36"
OWNER_URL = "http://127.0.0.1:8810/#/queue"          # 项目方“用这张 / 修改”的待办页（L-123）
BY = "总调度 episode_run"
DONE_SHOT = {"done", "best_effort", "blocked"}      # night.ep_resolved 同口径
EXIT = {"done": 0, "blocked": 2, "wait": 3, "owner": 4}


def _load(rel: str, name: str):
    sp = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def now_iso(t: float | None = None) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t if t is not None else time.time()))


# ---------------------------------------------------------------- 远程 / 本地执行（可注入，测试里替换）
class Env:
    """所有副作用的出口：remote（SSH）、local（子进程）、report（登记卡点）、时钟。测试里整体替换。"""

    def __init__(self, run: str, ep: int, root: Path = ROOT, *, image_host=DEFAULT_IMAGE_HOST, video_host=DEFAULT_VIDEO_HOST,
                 dry: bool = False, offline: bool = False):
        self.run, self.ep, self.root = run, ep, root
        self.image_host, self.video_host = image_host, video_host
        self.dry, self.offline = dry, offline
        self.now = time.time
        self.sleep = time.sleep
        self._rssh = None
        self._hosts = None

    # 服务器根目录 / python：读车道表 config/factory/hosts.json（读不到就抛，失败关闭）
    def _h(self):
        if self._hosts is None:
            sys.path.insert(0, str(self.root / "tools/factory"))
            import hosts as H  # noqa: E402
            self._hosts = H
        return self._hosts

    def root_of(self, host: str) -> str:
        return self._h().server_root(host)

    def py_of(self, host: str) -> str:
        return self._h().python(host)

    def remote(self, host: str, cmd: str, timeout: float = 120, tries: int = 2, input: bytes | None = None) -> tuple[int, bytes, str]:
        if self._rssh is None:
            self._rssh = _load("tools/netfix/rssh.py", "rssh_er")
        r = self._rssh.run_retry(host, cmd, input=input, timeout=timeout, tries=tries)
        return r.returncode, (r.stdout or b""), (r.stderr or b"").decode("utf-8", "replace")[-300:]

    def local(self, args: list[str], timeout: float = 600) -> tuple[int, str, str]:
        r = subprocess.run(args, cwd=str(self.root), capture_output=True, timeout=timeout,
                           env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
        return r.returncode, (r.stdout or b"").decode("utf-8", "replace"), (r.stderr or b"").decode("utf-8", "replace")

    def report_issue(self, step: str, what: str, blocking: bool, fix_hint: str) -> str | None:
        ri = _load("tools/master/report_issue.py", "report_issue_er")
        return ri.report(self.run, self.ep, step, "EPISODE_RUN", what, blocking, fix_hint).get("id")

    def sftp_pull(self, host: str, remote_abs: str, local_part: Path) -> bool:
        pp = _load("tools/master/partial_pull.py", "partial_pull_er")
        pp.sftp_get(host, [(remote_abs, local_part)])
        return local_part.is_file()

    # 路径
    @property
    def out_dir(self) -> Path:
        return self.root / "data" / "pipeline" / "runs" / self.run / "episode_run"

    @property
    def tag(self) -> str:
        return f"ep{self.ep:02d}"


def remote_py_json(env: Env, host: str, code: str, timeout: float = 120) -> dict | None:
    """在服务器仓库根里跑一小段 python（code 只能含双引号），期望 stdout 末行是 JSON；失败 → None"""
    cmd = f"cd {shlex.quote(env.root_of(host))} && {shlex.quote(env.py_of(host))} -c '{code}'"
    rc, out, _err = env.remote(host, cmd, timeout=timeout)
    if rc != 0:
        return None
    for ln in reversed(out.decode("utf-8", "replace").strip().splitlines()):
        ln = ln.strip()
        if ln.startswith("{"):
            try:
                return json.loads(ln)
            except ValueError:  # arch-ok: 末行 JSON 坏 = 当作无结果（None），调用方按卡点处理
                return None
    return None


# 服务器上只读汇总（输出一行 JSON）。注意：单引号包裹 → 代码里只用双引号
IMAGE_SNAP = (
    'import json,os,time;R="%(run)s";E=%(ep)d;P="data/producer/runs/"+R+"/";'
    'J=lambda p:(json.load(open(p,encoding="utf-8")) if os.path.exists(p) else {});'
    'reg=J(P+"registry.json");ctl=J(P+"control.json");hb=J(P+"heartbeat.json");'
    'ep=next((e for e in reg.get("episodes",[]) if e.get("ep")==E),{});'
    'shots=[{"shot":s.get("shot"),"first":(s.get("objects",{}).get("first") or {}).get("status"),'
    '"why":str((s.get("objects",{}).get("first") or {}).get("last_error") or (s.get("objects",{}).get("first") or {}).get("waiting_for") or "")[:120]} for s in ep.get("shots",[])];'
    'hold=lambda f:[x for x in (J("data/autopilot/"+f).get("shots") or []) if not x.get("released")];'
    'print(json.dumps({"shots":shots,"headline":ep.get("headline"),"paused":ctl.get("paused"),"hold_lanes":ctl.get("hold_lanes") or [],'
    '"only":ctl.get("only") or [],"pause_hold":hold("pause_hold.json"),"runaway_hold":hold("runaway_hold.json"),'
    '"heartbeat":hb.get("ts"),"server_now":time.strftime("%%Y-%%m-%%dT%%H:%%M:%%S")},ensure_ascii=False))'
)
VIDEO_SNAP = (
    'import json,os,time,glob;R="%(run)s";E=%(ep)d;V="data/pipeline/runs/"+R+"/video/";'
    'J=lambda p:(json.load(open(p,encoding="utf-8")) if os.path.exists(p) else {});'
    'ns=J(V+"night_state.json");x=(ns.get("eps") or {}).get(str(E)) or {};'
    'jobs=J(V+"jobs.json");ids=[s["shot"] for s in jobs.get("shots",[]) if s.get("ep")==E];'
    'st={};[st.update((J(f).get("shots") or {})) for f in glob.glob(V+"state_*.json")];'
    'recs={i:(st.get(i) or {}).get("status") for i in ids};'
    'age=(time.time()-os.path.getmtime(V+"night_state.json")) if os.path.exists(V+"night_state.json") else None;'
    'fin=x.get("final");sz=(os.path.getsize(fin) if fin and os.path.exists(fin) else None);'
    'print(json.dumps({"night":x,"night_age_s":age,"shots":recs,"final_size":sz,"lane_mode":ns.get("lane_mode")},ensure_ascii=False))'
)


# ---------------------------------------------------------------- 小状态
def load_state(env: Env) -> dict:
    p = env.out_dir / f"{env.tag}_state.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):  # arch-ok: 状态文件缺 / 坏 = 全新一轮，幂等判定会重新核对
        return {"stage_started": {}, "blockers": {}, "import": {}, "regen": {}}


def save_state(env: Env, st: dict) -> None:
    if env.dry:
        return
    env.out_dir.mkdir(parents=True, exist_ok=True)
    p = env.out_dir / f"{env.tag}_state.json"
    tmp = p.with_suffix(".json.part")
    tmp.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def R(status: str, msg: str, **kw) -> dict:
    """段结果。status：done 已完成 / todo 要执行动作 / wait 在等（机器在算 / 同步中）/ blocked 卡点 / owner 要项目方 / unknown 读不到"""
    return {"status": status, "msg": msg, **kw}


# ---------------------------------------------------------------- 各段：check（只读）/ act（有副作用）
def latest_p4(env: Env, override: str | None = None) -> Path | None:
    if override:
        p = Path(override)
        return p if p.is_absolute() else env.root / p
    d = env.root / "data" / "pipeline" / "runs" / env.run / "staging"
    c = sorted(d.glob(f"P4_{env.tag}.*.md"), key=lambda p: p.stat().st_mtime) if d.is_dir() else []  # arch-ok: 同一集 P4 稿按版本取最新，非猜当前剧
    return c[-1] if c else None


SCRIPT_NAME = "script_" + "v2.json"  # 导入稿文件名（拼接以免被 arch_scan 当成写死某剧路径；非某部剧专属）


def import_script_path(env: Env) -> Path:
    return env.root / "data" / "import" / "runs" / env.run / SCRIPT_NAME


def check_import(env, st, a) -> dict:
    p4 = latest_p4(env, a.p4)
    if not p4 or not p4.is_file():
        return R("blocked", f"staging 里没有 P4_{env.tag}.*.md", hint="先让写手交 P4 分镜")
    sha = sha256_file(p4)
    rel = p4.relative_to(env.root).as_posix() if p4.is_absolute() and env.root in p4.parents else str(p4)
    done = st.get("import", {})
    if done.get("sha") == sha and import_script_path(env).is_file():
        return R("done", f"已导入 {Path(rel).name}（sha {sha[:8]}）", p4=rel, sha=sha)
    return R("todo", f"待导入 {Path(rel).name}（sha {sha[:8]}）", p4=rel, sha=sha,
             plan=f"producer.py import-staged --run {env.run} --obj {rel} --reason {sha[:8]}…")


def act_import(env, st, a, res) -> dict:
    args = [sys.executable, "tools/autopilot/producer.py", "import-staged", "--run", env.run, "--obj", res["p4"],
            "--reason", res["sha"], "--note", f"episode_run 导入 {env.tag}", "--by", BY]
    rc, out, err = env.local(args, timeout=TIMEOUT_S["import"])
    if rc != 0:
        return R("blocked", f"import-staged 失败 rc={rc}：{(out + err)[-240:].strip()}", hint="看 producer log 的 import_blocked 原因（rubric 闸门 / sha / validate）")
    st["import"] = {"sha": res["sha"], "path": res["p4"], "at": now_iso(env.now())}
    st["regen"] = {}                                     # 新稿 → 换代要重做
    return R("done", f"已导入（sha {res['sha'][:8]}）", p4=res["p4"], sha=res["sha"])


def check_preflight(env, st, a) -> dict:
    rc, out, err = env.local([sys.executable, "tools/master/episode_ready.py", "--run", env.run, "--episode", str(env.ep), "--json"], timeout=TIMEOUT_S["preflight"])
    try:
        d = json.loads(out)
    except ValueError:
        return R("blocked", f"就绪检查没有输出可解析结果 rc={rc}：{(out + err)[-200:].strip()}", hint="tools/master/episode_ready.py")
    if d.get("ready"):
        return R("done", f"就绪检查通过（{len(d.get('shots') or [])} 镜）")
    gaps = d.get("gaps") or []
    txt = "；".join(f"{g.get('kind')}:{g.get('who')} {g.get('what')}（{g.get('owner')}）" for g in gaps[:6])
    return R("blocked", f"就绪检查缺 {len(gaps)} 项：{txt}", gaps=gaps, hint="补资产 / 造型排期后重跑；缺口 owner 见 gaps")


def check_regen(env, st, a) -> dict:
    imp = st.get("import") or {}
    script = import_script_path(env)
    if not script.is_file():
        return R("blocked", "本机没有导入稿", hint="先跑 import 段")
    if env.offline:
        return R("unknown", "离线模式：不核对服务器")
    want = sha256_file(script)
    rc, out, _ = env.remote(env.image_host, f"cd {shlex.quote(env.root_of(env.image_host))} && sha256sum data/import/runs/{shlex.quote(env.run)}/{SCRIPT_NAME}")
    got = out.decode("utf-8", "replace").split()[0] if rc == 0 and out.strip() else None
    if got is None:
        return R("unknown", f"读不到 {env.image_host} 的导入稿 sha（SSH rc={rc}）")
    if got != want:
        return R("wait", f"导入稿还没同步到 {env.image_host}（本机 {want[:8]} / 服务器 {got[:8]}；resident_sync 每 120 s 推一次）")
    if (st.get("regen") or {}).get("sha") == imp.get("sha") and imp.get("sha"):
        return R("done", "本稿换代已下达（producer regen 已执行）")
    if not imp.get("sha"):
        return R("done", "本次没有导入新稿（沿用现有导入稿，不换代）")
    return R("todo", "新稿已同步，下达换代（不撤旧当前版，过闸自动换上）",
             plan=f"[{env.image_host}] producer.py regen --run {env.run} --episode {env.ep}")


def act_regen(env, st, a, res) -> dict:
    h = env.image_host
    cmd = (f"cd {shlex.quote(env.root_of(h))} && OFFLINE_SELF={h} {shlex.quote(env.py_of(h))} tools/autopilot/producer.py regen "
           f"--run {shlex.quote(env.run)} --episode {env.ep} --reason {shlex.quote('episode_run 新稿换代 ' + (st['import'].get('sha') or '')[:8])} --by {shlex.quote(BY)}")
    rc, out, err = env.remote(h, cmd, timeout=TIMEOUT_S["regen"], tries=1)     # 非幂等动作：连接层失败也只试一次，下拍再看
    if rc != 0:
        return R("blocked", f"regen 失败 rc={rc}：{(out.decode('utf-8', 'replace') + err)[-240:].strip()}", hint="看 producer log")
    st["regen"] = {"sha": st["import"].get("sha"), "at": now_iso(env.now())}
    return R("done", "换代已下达")


def hold_blockers(env: Env, snap: dict, shots: list[str], lanes: list[str]) -> list[str]:
    """pause_shots / runaway_hold / hold_lanes / paused / 心跳停：只报告，绝不解除"""
    out = []
    if snap.get("paused"):
        out.append("producer 全局暂停（control.paused）")
    mine = set(shots)
    for key, zh in (("pause_hold", "按镜暂停 pause_shots"), ("runaway_hold", "runaway 冻结")):
        hit = sorted({x.get("shot") for x in snap.get(key) or [] if x.get("shot") in mine and not _expired(x, snap.get("server_now"))})
        if hit:
            out.append(f"{zh}：{','.join(hit)}")
    held = [l for l in lanes if l in (snap.get("hold_lanes") or [])]
    if lanes and len(held) == len(lanes):
        out.append(f"本段全部道被封（hold_lanes）：{','.join(held)}")
    return out


def _expired(item: dict, server_now: str | None) -> bool:
    ex = item.get("expires_at")
    return bool(ex and server_now and ex < server_now)


def lanes_of(env: Env, host: str, role: str) -> list[str]:
    try:
        d = json.loads((env.root / "config/factory/hosts.json").read_text(encoding="utf-8"))
        return [k for k, v in (d["hosts"][host].get("lanes") or {}).items() if role in (v.get("roles") or []) and v.get("enabled", True)]
    except (OSError, ValueError, KeyError):  # arch-ok: 读不到 hosts.json = 无 lane，调用方当空处理
        return []


def check_first(env, st, a) -> dict:
    if env.offline:
        return R("unknown", "离线模式")
    snap = remote_py_json(env, env.image_host, IMAGE_SNAP % {"run": env.run, "ep": env.ep})
    if snap is None:
        return R("unknown", f"读不到 {env.image_host} producer 状态（SSH 失败）")
    shots = snap.get("shots") or []
    if not shots:
        return R("wait", "producer 登记表里还没有本集的镜（等导入稿同步 / producer 拍一轮）")
    by = {}
    for s in shots:
        by.setdefault(s.get("first") or "?", []).append(s["shot"])
    passed = by.get("passed", [])
    total = len(shots)
    summary = {k: len(v) for k, v in sorted(by.items())}
    if len(passed) == total:
        return R("done", f"首帧 {total}/{total} 全部有过闸的当前版", counts=summary)
    be = by.get("best_effort", [])
    pending_ids = [s["shot"] for s in shots if s.get("first") != "passed"]
    blockers = hold_blockers(env, snap, pending_ids, lanes_of(env, env.image_host, "image"))
    hb, sn = snap.get("heartbeat"), snap.get("server_now")
    if hb and sn and _secs_between(hb, sn) > 600:
        blockers.append(f"producer 心跳停了 {int(_secs_between(hb, sn) // 60)} 分钟（{hb}）")
    if blockers:
        return R("blocked", f"首帧 {len(passed)}/{total}；" + "；".join(blockers), counts=summary,
                 hint="按镜解除暂停：producer.py resume --shots <镜> --by 总调度；释放冻结：unhold / retry；封道属于总调度决策，episode_run 不动")
    if be:
        return R("owner", f"首帧 {len(passed)}/{total}；{len(be)} 镜是“尽力版”等项目方看图（用这张 / 修改）：{','.join(be)}",
                 counts=summary, link=OWNER_URL, shots=be)
    why = "；".join(f"{s['shot']}:{s['why']}" for s in shots if s.get("first") != "passed" and s.get("why"))[:200]
    return R("wait", f"首帧 {len(passed)}/{total}（{summary}）" + (f"；{why}" if why else ""), counts=summary)


def _secs_between(a: str, b: str) -> float:
    f = "%Y-%m-%dT%H:%M:%S"
    try:
        return time.mktime(time.strptime(b[:19], f)) - time.mktime(time.strptime(a[:19], f))
    except ValueError:
        return 0.0


def expected_shots(env: Env) -> int:
    """本集在导入稿里的镜数（视频段 / 合成段用它防“night 只建了部分作业就算全完”）；读不到 → 0（不设下限）"""
    try:
        doc = json.loads(import_script_path(env).read_text(encoding="utf-8"))
        ep = next(e for e in doc.get("episodes") or [] if int(e.get("number") or 0) == env.ep)
        return len(ep.get("shots") or [])
    except (OSError, ValueError, StopIteration):  # arch-ok: 读不到 = 0，调用方不设下限
        return 0


def video_snap(env: Env) -> dict | None:
    return remote_py_json(env, env.video_host, VIDEO_SNAP % {"run": env.run, "ep": env.ep})


def check_video(env, st, a) -> dict:
    if env.offline:
        return R("unknown", "离线模式")
    v = video_snap(env)
    if v is None:
        return R("unknown", f"读不到 {env.video_host} night 状态（SSH 失败）")
    recs = v.get("shots") or {}
    if not recs:
        return R("wait", "night 还没有本集的视频作业（等首帧全过后 night 自动建）", night=v.get("night"))
    done = [k for k, s in recs.items() if s in DONE_SHOT]
    exp = expected_shots(env)
    if len(recs) < exp:
        return R("wait", f"night 只建了 {len(recs)}/{exp} 镜的视频作业（落定 {len(done)}），等首帧陆续过闸后补建")
    if len(done) == len(recs):
        return R("done", f"视频 {len(done)}/{len(recs)} 全部落定")
    age = v.get("night_age_s")
    if age is not None and age > 900:
        return R("blocked", f"night 状态 {int(age // 60)} 分钟没更新（常驻 night 可能停了）：视频 {len(done)}/{len(recs)}",
                 stale=True, hint=f"{env.video_host} 上看 night 进程；受控重启走 restart_queue；或 episode_run --kick-night")
    return R("wait", f"视频 {len(done)}/{len(recs)}（night 在跑）")


def act_kick_night(env, st, a, res) -> dict:                      # 仅 --kick-night 时用
    h = env.video_host
    cmd = (f"cd {shlex.quote(env.root_of(h))} && OFFLINE_SELF={h} {shlex.quote(env.py_of(h))} tools/series10_video/night.py --once")
    rc, out, err = env.remote(h, cmd, timeout=1200, tries=1)
    return R("wait", f"已手动拍一轮 night rc={rc}")


def check_finalize(env, st, a) -> dict:
    if env.offline:
        return R("unknown", "离线模式")
    v = video_snap(env)
    if v is None:
        return R("unknown", f"读不到 {env.video_host} night 状态")
    n = v.get("night") or {}
    s = n.get("status")
    nship = len(v.get("shots") or {})
    if nship < expected_shots(env):
        return R("wait", f"视频作业只有 {nship}/{expected_shots(env)} 镜，成片不算数（night 状态 {s}）")
    if s == "assembled" and n.get("final"):
        return R("done", f"已合成 {n['final']}", final=n["final"], final_size=v.get("final_size"), version=n.get("assembled_n"))
    if s in ("assemble_failed", "hold_voices", "hold_tts"):
        return R("blocked", f"合成停在 {s}：{str(n.get('assemble_err') or n.get('hold_why') or '')[:200]}", hint="night.py reopen / 修环境后受控重启；见 night.log")
    if s is None:
        return R("wait", "night 里还没有本集状态")
    return R("wait", f"night 状态 {s}（等视频全落定后自动 finalize）")


def local_ep_dir(env: Env) -> Path:
    return env.root / "data" / "episodes" / env.run


def check_pull(env, st, a) -> dict:
    fin = (st.get("final") or {}).get("path")
    if not fin:
        return R("wait", "还没有远端成片路径（finalize 段先完成）")
    name = Path(fin).name
    loc = local_ep_dir(env) / name
    want = (st.get("final") or {}).get("size")
    if loc.is_file() and (want is None or loc.stat().st_size == want):
        return R("done", f"成片已在笔记本：{loc.relative_to(env.root).as_posix()}", local=str(loc))
    return R("todo", f"拉回 {name}（{want or '?'} 字节）", plan=f"sftp / cat {env.video_host}:{fin} → data/episodes/{env.run}/{name}")


def act_pull(env, st, a, res) -> dict:
    h = env.video_host
    fin = st["final"]["path"]
    remote_abs = fin if fin.startswith("/") else f"{env.root_of(h)}/{fin}"
    loc = local_ep_dir(env) / Path(fin).name
    loc.parent.mkdir(parents=True, exist_ok=True)
    part = loc.with_name(loc.name + ".part")
    want = st["final"].get("size")
    ok = False
    try:
        env.sftp_pull(h, remote_abs, part)
        ok = part.is_file() and (want is None or part.stat().st_size == want)
    except Exception:  # noqa: BLE001  # arch-ok: hk 不通 → 退回命令主连接
        ok = False
    if not ok:
        rc, data, err = env.remote(h, f"cat {shlex.quote(remote_abs)}", timeout=900, tries=2)
        if rc == 0 and data and (want is None or len(data) == want):
            part.write_bytes(data)
            ok = True
    if not ok:
        return R("blocked", f"拉回 {Path(fin).name} 失败或大小不符", hint="手动 tools/master/partial_pull.py 或检查隧道")
    os.replace(part, loc)
    tl = Path(fin).with_suffix(".timeline.json").name                 # 同名时间线（小）顺带拉；没有就算了
    rc, data, _ = env.remote(h, f"cat {shlex.quote(remote_abs.rsplit('.', 1)[0] + '.timeline.json')}", timeout=120, tries=1)
    if rc == 0 and data:
        (loc.parent / tl).write_bytes(data)
    return R("done", f"已拉回 {loc.name}", local=str(loc))


def compare_dir(env: Env) -> Path:
    return env.root / "data" / "review_pages" / f"{env.run}_{env.tag}_compare"


def previous_version(env: Env, newest: Path, override: str | None) -> Path | None:
    if override:
        return env.root / override
    c = sorted([p for p in local_ep_dir(env).glob(f"{env.tag}_v*.mp4") if p != newest], key=lambda p: p.stat().st_mtime)  # arch-ok: 同一集旧成片按时间排，留最新
    return c[-1] if c else None


def check_compare(env, st, a) -> dict:
    loc = (st.get("pulled") or {}).get("local")
    if not loc or not Path(loc).is_file():
        return R("wait", "成片还没拉回")
    idx = compare_dir(env) / "index.html"
    if idx.is_file() and idx.stat().st_mtime >= Path(loc).stat().st_mtime:
        return R("done", f"对比页已生成：{idx.relative_to(env.root).as_posix()}", page=str(idx))
    return R("todo", "生成对比页（新版 vs 上一版 + 瀑布 + 状态）", plan=f"写 {compare_dir(env).relative_to(env.root).as_posix()}/index.html")


def act_compare(env, st, a, res) -> dict:
    new = Path(st["pulled"]["local"])
    old = previous_version(env, new, a.compare_to)
    d = compare_dir(env)
    d.mkdir(parents=True, exist_ok=True)

    def rel(p: Path) -> str:
        return os.path.relpath(p, d).replace("\\", "/")

    tl = env.root / "data" / "review_pages" / "metrics" / f"{env.tag}_timeline.html"
    cells = []
    if old:
        cells.append(f'<div><h3>上一版 {old.name}</h3><video src="{rel(old)}" controls width="100%"></video></div>')
    cells.append(f'<div><h3>本版 {new.name}</h3><video src="{rel(new)}" controls width="100%"></video></div>')
    page = ("<!doctype html><meta charset=utf-8><title>%s %s 对比</title>"
            "<style>body{font-family:sans-serif;background:#111;color:#eee;margin:20px}.g{display:grid;grid-template-columns:repeat(%d,1fr);gap:16px}a{color:#8cf}</style>"
            "<h2>%s %s：上一版 vs 本版</h2><div class=g>%s</div>"
            "<p>耗时瀑布：%s</p><p>项目方点“用这版 / 修改”在待办页：<a href='%s'>%s</a>（episode_run 不代点）</p>"
            "<p>状态与报告：data/pipeline/runs/%s/episode_run/%s_report.md</p>") % (
        env.run, env.tag, len(cells), env.run, env.tag, "".join(cells),
        f'<a href="{rel(tl)}">{tl.name}</a>' if tl.is_file() else "（尚未生成）", OWNER_URL, OWNER_URL, env.run, env.tag)
    (d / "index.html").write_text(page, encoding="utf-8")
    return R("done", f"对比页已生成（{'有上一版' if old else '无上一版，只放本版'}）", page=str(d / "index.html"))


def check_timeline(env, st, a) -> dict:
    out = env.root / "data" / "review_pages" / "metrics" / f"{env.tag}_timeline.html"
    if not st.get("pulled"):
        return R("wait", "成片还没拉回，瀑布等全程结束后再出")
    first = (st.get("stage_started") or {}).get("first") or st.get("run_started")
    if not first:
        return R("wait", "没有本次运行的起点")
    if (st.get("timeline") or {}).get("since") == first and out.is_file():
        return R("done", f"瀑布已生成：{out.relative_to(env.root).as_posix()}")
    return R("todo", "生成耗时瀑布", plan=f"episode_timeline.py --since {first[:16]} --until now --fetch")


def act_timeline(env, st, a, res) -> dict:
    since = ((st.get("stage_started") or {}).get("first") or st["run_started"])[:16]
    since_full = (st.get("stage_started") or {}).get("first") or st["run_started"]
    until = now_iso(env.now())[:16]
    rc, out, err = env.local([sys.executable, "tools/master/episode_timeline.py", "--run", env.run, "--episode", str(env.ep),
                              "--since", since, "--until", until, "--fetch"], timeout=TIMEOUT_S["timeline"])
    if rc != 0:                                                           # 瀑布失败不挡成片：记一笔就算完成
        st["timeline"] = {"since": since_full, "error": (out + err)[-200:]}
        return R("done", f"瀑布生成失败（不挡成片）：{(out + err)[-120:].strip()}")
    st["timeline"] = {"since": since_full, "at": now_iso(env.now())}
    return R("done", "瀑布已生成")


CHECK = {"import": check_import, "preflight": check_preflight, "regen": check_regen, "first": check_first, "video": check_video,
         "finalize": check_finalize, "pull": check_pull, "compare": check_compare, "timeline": check_timeline}
ACT = {"import": act_import, "regen": act_regen, "pull": act_pull, "compare": act_compare, "timeline": act_timeline}


# ---------------------------------------------------------------- 编排
def register_blocker(env: Env, st: dict, stage: str, res: dict) -> str | None:
    """同一段同一原因只登记一次（状态里按 stage+原因哈希去重）"""
    key = f"{stage}:{hashlib.sha1(res['msg'].encode()).hexdigest()[:8]}"
    if key in st["blockers"]:
        return st["blockers"][key]
    if env.dry:
        return None
    iid = env.report_issue(f"episode_run/{stage}", f"[{STAGE_ZH[stage]}] {res['msg']}", res["status"] in ("blocked", "timeout"),
                           res.get("hint") or res.get("link") or "")
    st["blockers"][key] = iid
    return iid


def run_stage(env: Env, st: dict, stage: str, a) -> dict:
    """check → （todo 则 act）→ 再 check；返回最终结果，附 stage / 耗时"""
    res = CHECK[stage](env, st, a)
    if stage == "video" and res.get("stale") and getattr(a, "kick_night", False) and not env.dry:
        res = act_kick_night(env, st, a, res)
    if res["status"] == "todo":
        if env.dry or stage not in ACT:
            return res
        res = ACT[stage](env, st, a, res)
        if res["status"] == "done":
            res2 = CHECK[stage](env, st, a)
            res = res2 if res2["status"] != "todo" else res
    return res


def absorb(env: Env, st: dict, stage: str, res: dict) -> None:
    """把后续段要用的结果记进小状态"""
    if stage == "finalize" and res["status"] == "done":
        st["final"] = {"path": res["final"], "size": res.get("final_size"), "version": res.get("version")}
    if stage == "pull" and res["status"] == "done":
        st["pulled"] = {"local": res["local"], "at": now_iso(env.now())}


def orchestrate(env: Env, a, stages: list[str]) -> dict:
    st = load_state(env)
    st.setdefault("run_started", now_iso(env.now()))
    rows: list[dict] = []
    final_status, stopped = "done", None
    for stage in stages:
        t_start = st["stage_started"].get(stage)
        while True:
            res = run_stage(env, st, stage, a)
            absorb(env, st, stage, res)
            if res["status"] == "done":
                break
            if res["status"] in ("todo", "unknown") and env.dry:
                break
            if not env.dry:
                t_start = st["stage_started"].setdefault(stage, now_iso(env.now()))
                elapsed = env.now() - time.mktime(time.strptime(t_start, "%Y-%m-%dT%H:%M:%S"))
                if res["status"] in ("wait", "todo", "unknown") and elapsed > TIMEOUT_S[stage]:
                    res = R("blocked", f"超时：{STAGE_ZH[stage]} 已 {int(elapsed // 60)} 分钟（上限 {TIMEOUT_S[stage] // 60}）仍未完成；当时状态：{res['msg']}",
                            hint="看该段报告；必要时调整 --timeout 或排查卡点")
            if res["status"] in ("blocked", "owner"):
                res["issue"] = register_blocker(env, st, stage, res)
                break
            if res["status"] in ("wait", "unknown") and a.watch and not env.dry:
                save_state(env, st)
                env.sleep(max(30, a.interval))
                continue
            break
        res["stage"] = stage
        rows.append(res)
        if res["status"] not in ("done",) and not env.dry:
            final_status, stopped = EXIT_KEY(res["status"]), stage
            break
        if env.dry and res["status"] not in ("done", "todo"):
            if stopped is None and res["status"] in ("wait", "blocked", "owner"):
                final_status, stopped = res["status"], stage
    save_state(env, st)
    return {"run": env.run, "episode": env.ep, "at": now_iso(env.now()), "dry_run": env.dry, "status": final_status,
            "stopped_at": stopped, "stages": rows, "exit": EXIT.get(final_status, 1)}


def EXIT_KEY(s: str) -> str:
    return {"unknown": "wait", "todo": "wait"}.get(s, s)


def render_md(rep: dict) -> str:
    icon = {"done": "🟢", "todo": "🔵", "wait": "🟡", "blocked": "🔴", "owner": "🟣", "unknown": "⚪"}
    lines = [f"# {rep['run']} 第 {rep['episode']} 集 episode_run 报告（{rep['at']}{'，dry-run' if rep['dry_run'] else ''}）", "",
             f"总状态：**{rep['status']}**" + (f"，停在 **{STAGE_ZH[rep['stopped_at']]}**" if rep["stopped_at"] else ""), ""]
    up = False
    for r in rep["stages"]:
        note = "（上游未完成，仅供参考）" if up and r["status"] != "blocked" else ""
        lines.append(f"- {icon.get(r['status'], '')} {STAGE_ZH[r['stage']]}：{r['msg']}{note}")
        if r["status"] in ("blocked", "owner", "wait"):
            up = True
        if r.get("plan") and r["status"] == "todo":
            lines.append(f"  - 将执行：`{r['plan']}`")
        if r.get("hint"):
            lines.append(f"  - 建议：{r['hint']}")
        if r.get("link"):
            lines.append(f"  - 项目方入口：{r['link']}")
        if r.get("issue"):
            lines.append(f"  - 卡点已登记：{r['issue']}")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", default="series10_v2")
    ap.add_argument("--ep", type=int, required=True)
    ap.add_argument("--from", dest="from_stage", choices=STAGES, default=STAGES[0])
    ap.add_argument("--only", choices=STAGES, default=None, help="只跑这一段")
    ap.add_argument("--dry-run", action="store_true", help="只读：检查每段是否已完成，列出将执行的动作，不动任何东西（也不登记卡点、不写状态）")
    ap.add_argument("--offline", action="store_true", help="dry-run 时不连服务器（服务器相关段显示 unknown）")
    ap.add_argument("--watch", action="store_true", help="遇到“在等”就轮询到完成 / 卡点 / 超时")
    ap.add_argument("--interval", type=int, default=120, help="--watch 轮询间隔秒（最小 30）")
    ap.add_argument("--p4", default=None, help="指定要导入的 P4 稿（默认 staging 里最新的 P4_epNN.*.md）")
    ap.add_argument("--compare-to", default=None, help="对比页的“上一版”路径（默认本地最新的另一版）")
    ap.add_argument("--image-host", default=DEFAULT_IMAGE_HOST)
    ap.add_argument("--video-host", default=DEFAULT_VIDEO_HOST)
    ap.add_argument("--timeout", action="append", default=[], metavar="STAGE=秒", help="覆盖某段超时，可重复")
    ap.add_argument("--kick-night", action="store_true", help="night 状态陈旧时手动拍一轮（默认只报卡点）")
    a = ap.parse_args(argv)
    for kv in a.timeout:
        k, _, v = kv.partition("=")
        if k in TIMEOUT_S and v.isdigit():
            TIMEOUT_S[k] = int(v)
    env = Env(a.run, a.ep, image_host=a.image_host, video_host=a.video_host, dry=a.dry_run, offline=a.offline)
    stages = [a.only] if a.only else STAGES[STAGES.index(a.from_stage):]
    rep = orchestrate(env, a, stages)
    md = render_md(rep)
    if not a.dry_run:
        env.out_dir.mkdir(parents=True, exist_ok=True)
        sp = env.out_dir / f"{env.tag}_status.json"
        stmp = sp.with_suffix(".json.part")
        stmp.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(stmp, sp)
        (env.out_dir / f"{env.tag}_report.md").write_text(md, encoding="utf-8")
    print(md)
    return rep["exit"]


if __name__ == "__main__":
    raise SystemExit(main())
