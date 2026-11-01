"""SENTINEL 探针（实时）：每条 SLO 一个 p_sN(ctx) → findings（判定都在 judges.py，回放共用）。规则 K-OPS-S01 / S03。

只读：读本机文件、经 rssh 常驻主连接每台每拍一次合并只读调用（remote_probe.py，timeout + nice + 限线程）、
lane_util.measure（/history）、本机看图服务抽检、无头 Chrome（只读查看令牌，非 GET 全拦）。不改生产代码、不重启、不删文件。
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools.sentinel import judges as J  # noqa: E402

NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)
HOSTS = ("gpu33", "gpu36")
IMAGE_GPUS = {"gpu33": [0, 1, 3], "gpu36": [0, 1]}      # = lane_util.DEFAULT_LANES（gpu36 GPU2 专用 vLLM，L-100）
VQA_HOST = "gpu36"


UNKNOWN: dict[str, str] = {}     # 本拍读不到 / 解析失败的输入 → tick 写进 open.json 的 unknown（探针“未测”，不当正常、不关单）


def jl(p: Path | str, default=None):
    try:
        return json.loads((ROOT / p).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:  # arch-ok: 记 UNKNOWN（未测）；judges 对 None 不出 finding，不会误关单
        UNKNOWN[str(p)] = type(e).__name__
        return default


def sha_file(p: Path) -> str | None:
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest()
    except OSError:  # arch-ok: 文件不存在 = sha None，和服务器同样“缺”时 j_parity 视为一致（解析层缺文件双方按缺处理）
        return None


def parity_files(c: dict) -> list[str]:
    """S6 清单 = sentinel.yaml files ∪ resolution_layers.yaml 的 layers + global（缺文件双方都按缺处理）"""
    fs = list(c["files"])
    try:
        import yaml
        reg = yaml.safe_load((ROOT / c.get("layers_from", "config/policies/resolution_layers.yaml")).read_text(encoding="utf-8")) or {}
        fs += [x["path"] for x in (reg.get("layers") or []) + (reg.get("global") or []) if x.get("path")]
    except (OSError, ValueError, ImportError) as e:  # arch-ok: 表读不到 → 记 UNKNOWN，退回 sentinel.yaml 的 files（其中已列全部解析层）
        UNKNOWN["config/policies/resolution_layers.yaml"] = type(e).__name__
    return list(dict.fromkeys(fs))


class Ctx:
    """一拍的上下文：配置、跨拍状态（state["mem"]）、懒加载的远程采样"""

    def __init__(self, cfg: dict, mem: dict, now: float | None = None):
        self.cfg, self.mem, self.now = cfg, mem, now or time.time()
        self._remote: dict = {}
        self.errors: dict = {}

    def c(self, name: str) -> dict:
        return self.cfg[name]["value"]

    def remote(self, host: str) -> dict | None:
        if host not in self._remote:
            self._remote[host] = remote_batch(host, self.c("S6_config_parity"), float(self.cfg["remote_timeout_s"]["value"]),
                                              host == VQA_HOST)
            if self._remote[host] is None:
                self.errors[host] = "远程采样失败（主连接不在 / 超时）"
        return self._remote[host]


def remote_batch(host: str, parity: dict, timeout: float, vqa: bool) -> dict | None:
    from tools.netfix import rssh
    files = ",".join(parity_files(parity))
    cmd = f"timeout {int(timeout) - 8} nice -n 19 python3 - {parity['server_root']} {files} {1 if vqa else 0}"
    try:
        r = rssh.run(host, cmd, input=(ROOT / "tools/sentinel/remote_probe.py").read_bytes(), timeout=timeout)
    except subprocess.TimeoutExpired:  # arch-ok: None = 远程未测，Ctx.remote 记 errors[host]，依赖它的探针本拍不出 finding
        return None
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout.decode("utf-8", "replace").strip().splitlines()[-1])
    except (ValueError, IndexError):  # arch-ok: 同上（远程输出坏 = 未测）
        return None


# ------------------------------------------------------------------ 本机登记表（按分区算 ready）
def laptop_registry() -> dict:
    reg = jl("data/producer/registry.json", {}) or {}
    part = (jl("config/netfix/partition.json", {}) or {}).get("images") or {}
    out = {h: {"ready": 0, "pending": 0} for h in part}
    waits = {}
    for E in reg.get("episodes") or []:
        host = next((h for h, eps in part.items() if E.get("ep") in eps), None)
        for S in E.get("shots") or []:
            for o in (S.get("objects") or {}).values():
                if host and o.get("kind") in ("first", "last"):
                    if o.get("status") == "ready":
                        out[host]["ready"] += 1
                    elif o.get("status") == "pending":
                        out[host]["pending"] += 1
                if o.get("status") != "passed" and J.is_human_wait(o.get("waiting_for")):
                    waits[o.get("id")] = str(o.get("waiting_for"))[:40]
    return {"by_host": out, "waits": waits}


# ================================================================== S1
def p_s1(ctx: Ctx) -> list[dict]:
    from tools.debug import lane_util
    c = ctx.c("S1_lane_util_min")
    lanes = jl("config/debug_lanes.json")
    rec = lane_util.measure(c["window_min"], lanes)
    ctx.mem["lane_util_last"] = rec
    return J.j_lane_util(rec, c)


# ================================================================== S2
def p_s2(ctx: Ctx) -> list[dict]:
    c = ctx.c("S2_gpu_all_idle_s")
    lr = laptop_registry()
    out = []
    for h in HOSTS:
        r = ctx.remote(h)
        if not r or not r.get("smi"):
            continue
        utils = [u for i, u, _m in r["smi"] if i in IMAGE_GPUS[h]]
        hist = ctx.mem.setdefault("gpu_hist", {}).setdefault(h, [])
        hist.append([ctx.now, utils])
        del hist[:-30]
        reg = r.get("registry") or {}
        ready = {"server": (reg.get("counts") or {}).get("ready", 0), "laptop_partition": (lr["by_host"].get(h) or {}).get("ready", 0)}
        paused = bool((r.get("control") or {}).get("paused") or (r.get("heartbeat") or {}).get("paused"))
        out += J.j_gpu_idle(h, [tuple(x) for x in hist], ready, paused, ctx.now, c)
    return out


# ================================================================== S3
def _score_events(evs: list[dict]) -> tuple[list, list]:
    samples = [(e["t"], float(e["contract_s"])) for e in evs if e.get("contract_s") is not None]
    backlog = [e["t"] for e in evs if e.get("ev") == "score_backlog"]
    return samples, backlog


def laptop_events(since_s: float = 3 * 3600) -> list[dict]:
    p = ROOT / "data/producer/log.jsonl"
    out = []
    try:
        with p.open("rb") as fh:
            fh.seek(max(0, p.stat().st_size - 600_000))
            for ln in fh.read().decode("utf-8", "replace").splitlines():
                if '"contract_s"' in ln or '"score_backlog"' in ln:
                    try:
                        d = json.loads(ln)
                    except ValueError:  # arch-ok: 单行坏行跳过（日志并发写半行），不影响其余样本
                        continue
                    if d.get("t", 0) >= time.time() - since_s:
                        out.append(d)
    except OSError as e:  # arch-ok: 记 UNKNOWN；无样本时 j_score 不判 p50
        UNKNOWN["data/producer/log.jsonl"] = type(e).__name__
    return out


def p_s3(ctx: Ctx) -> list[dict]:
    c = ctx.c("S3_score_p50_s")
    out = []
    s, b = _score_events(laptop_events())
    out += J.j_score("laptop", s, b, ctx.now, c)
    for h in HOSTS:
        r = ctx.remote(h)
        if not r:
            continue
        if r.get("log_err"):
            UNKNOWN[f"{h}:data/producer/log.jsonl"] = r["log_err"]
        s, b = _score_events(r.get("events") or [])
        out += J.j_score(h, s, b, ctx.now, c)
        if h == VQA_HOST and c.get("vqa_must_be_vllm") and "vqa_models" in r:
            rep = r["vqa_models"]
            out += J.j_vqa_endpoint(h, 8870, None if rep.startswith("ERR") and "refused" not in rep.lower() else rep, r.get("vqa_listener") or "")
    return out


# ================================================================== S4
def p_s4(ctx: Ctx) -> list[dict]:
    c = ctx.c("S4_recover_s")
    ns = jl("data/netfix/net_status.json", {}) or {}
    ports = {}
    rel = ns.get("relay") or {}
    if rel:
        ports["relay"] = {"ok": bool(rel.get("up")), "why": rel.get("route")}
    for h, st in (ns.get("hosts") or {}).items():
        oks = [v.get("ok") for v in (st.get("ports") or {}).values()]
        alive = any(v.get("why") == "banner_slow_but_alive" for v in (st.get("ports") or {}).values())
        if not oks:
            continue
        ports[h] = {"ok": bool(any(oks) or alive) and st.get("state") == "up",
                    "why": ",".join(sorted({str(v.get("why")) for v in st["ports"].values()}))}
    stale = ctx.now - float(ns.get("t") or 0) > 120
    if stale and ns:
        ports["supervisor"] = {"ok": False, "why": f"net_status {int(ctx.now - float(ns.get('t') or 0))} s 未更新"}
    elif ns:
        ports["supervisor"] = {"ok": True}
    ds = ctx.mem.setdefault("down_since", {})
    for k, p in ports.items():
        if p["ok"]:
            ds.pop(k, None)
        else:
            ds.setdefault(k, ctx.now)
        p["down_since"] = ds.get(k)
    out = J.j_ports(ports, ctx.now, c)
    out += J.j_relay_rate(*relay_rate(ctx), c)
    return out


def relay_rate(ctx: Ctx) -> tuple[float | None, str]:
    """每拍一次 netstat + wsl ss 快照（复用 tools/netfix/relay_rate.snap），新出现的 (本地地址,端口) 计新连接；滚动 60 分钟换算每小时。
    60 s 采一次会漏掉更短的连接——只会少算，不会多报。不足 10 分钟样本时退回 conn_watch_rate.jsonl 最近一条（2 小时内）。"""
    from tools.netfix import relay_rate as RR
    m = ctx.mem.setdefault("relay", {"prev": [], "new": []})
    cur = {"|".join(k) for k in RR.snap()}
    if m.get("t0") is None:
        m["t0"] = ctx.now
    else:
        m["new"] += [ctx.now] * len(cur - set(m["prev"]))
    m["prev"] = sorted(cur)
    m["new"] = [t for t in m["new"] if t >= ctx.now - 3600]
    span = min(3600.0, ctx.now - m["t0"])
    if span >= 600:
        return len(m["new"]) * 3600 / span, f"sentinel 每拍快照 {span / 60:.0f} 分钟"
    try:
        last = json.loads((ROOT / "data/netfix/conn_watch_rate.jsonl").read_text(encoding="utf-8").strip().splitlines()[-1])
        if ctx.now - J.ts(last["at"]) < 7200:
            return float(last["per_hour"]), f"conn_watch_rate.jsonl {last['at']} {last.get('tag', '')}"
    except (OSError, ValueError, IndexError, KeyError, TypeError) as e:  # arch-ok: 记 UNKNOWN；返回 None = 本拍不判跳板新建连接
        UNKNOWN["data/netfix/conn_watch_rate.jsonl"] = type(e).__name__
    return None, ""


# ================================================================== S5
def sv_ids() -> list[str]:
    idx = jl("data/system_versions/index.json", {}) or {}
    return [v["id"] for v in idx.get("versions") or [] if v.get("id")]


def latest_deploy() -> dict | None:
    fs = sorted(glob.glob(str(ROOT / "data/system_versions/deploy_*.json")), key=os.path.getmtime)
    if not fs:
        return None
    d = jl(fs[-1]) or {}
    ats = [h.get("at") for h in (d.get("hosts") or {}).values() if h.get("at")]
    return {"id": d.get("id"), "at": max(ats) if ats else None, "file": os.path.basename(fs[-1])}


def p_s5(ctx: Ctx) -> list[dict]:
    c = ctx.c("S5_release")
    lc = jl("data/system_versions/last_cut.json")
    out = J.j_cut(lc) + J.j_deploy_after_failed_cut(latest_deploy(), lc)
    ids = sv_ids()
    for h in HOSTS:
        r = ctx.remote(h)
        if r and r.get("sv"):
            out += J.j_sv_lag(h, r["sv"], ids, c)
    return out


# ================================================================== S6
def p_s6(ctx: Ctx) -> list[dict]:
    from tools.autopilot import policy
    c = ctx.c("S6_config_parity")
    files = parity_files(c)
    lap = {f: sha_file(ROOT / f) for f in files}
    ov = (jl("data/netfix/override_state.json", {}) or {}).get("hosts") or {}
    ar = jl("data/autopilot/assets_ready.json", {}) or {}
    out = p_identity(ctx)
    for h in HOSTS:
        r = ctx.remote(h)
        if r and r.get("sha"):
            out += annotate_parity(J.j_parity(h, lap, r["sha"], files), files)
        phase = (ov.get(h) or {}).get("phase")
        if phase:
            okr = policy.handback_ok(ar.get(h), (r or {}).get("sv"))
            out += J.j_handback(h, phase, ar.get(h), okr)
    return out


def p_identity(ctx: Ctx) -> list[dict]:
    """每拍调 DISTILL 的身份脸断言（本机只读，复用生产入口 asset_refs.face_of）；不一致 → P0，负责 WORKFLOW / FACTORY"""
    try:
        from tools.qa import identity_face_check as IFC
        return J.j_identity(IFC.check())
    except Exception as e:  # noqa: BLE001
        ctx.errors["identity_face_check"] = repr(e)[:200]
        return []


_GIT_SHA: dict = {}


def git_sha(commit: str | None, rel: str) -> str | None:
    """发版 commit 里这个文件的 sha256（判断“服务器 = 已发版本、笔记本有未发版改动”还是“服务器自己漂了”）"""
    if not commit:
        return None
    k = (commit, rel)
    if k not in _GIT_SHA:
        try:
            r = subprocess.run(["git", "show", f"{commit}:{rel}"], cwd=str(ROOT), capture_output=True, timeout=20, creationflags=NOWIN)
            _GIT_SHA[k] = hashlib.sha256(r.stdout).hexdigest() if r.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired):  # arch-ok: 只是证据注解，取不到写 None
            _GIT_SHA[k] = None
    return _GIT_SHA[k]


def annotate_parity(fs: list[dict], files: list[str]) -> list[dict]:
    sv = jl("data/system_version.txt") or {}
    for f in fs:
        ev = f["evidence"]
        g = git_sha(sv.get("commit"), ev.get("file", ""))
        if g is not None:
            ev["sv"] = sv.get("id")
            ev["server_eq_sv"] = ev.get("server_sha") == g
            ev["laptop_eq_sv"] = ev.get("laptop_sha") == g
            if f["violated"] and ev["server_eq_sv"] and not ev["laptop_eq_sv"]:
                f["title"] += f"——服务器 = 已发版 {sv.get('id')}，笔记本有未发版改动（需 cut + deploy，或回退笔记本）"
            elif f["violated"] and not ev["server_eq_sv"]:
                f["title"] += f"——服务器也不等于已发版 {sv.get('id')}（服务器侧漂移）"
    return fs


# ================================================================== S7
def p_s7(ctx: Ctx) -> list[dict]:
    from tools.autopilot import policy
    out = J.j_pause("laptop", jl("data/producer/control.json"), ctx.now, policy.pause_decision)
    for h in HOSTS:
        r = ctx.remote(h)
        if r and r.get("control") is not None:
            out += J.j_pause(h, r["control"], ctx.now, policy.pause_decision)
    return out


# ================================================================== S8
def vlm_judge(path: Path, shot: str) -> dict:
    """复用 tools/vqa/gaze_regression.judge（和生产同一套：本地看图整图 eye_contact → MediaPipe 旁证 → 拿不准裁脸复判；只调一次看图）。
    身份 / 缺件（Q1 / Q2）：judge 不回 defects，契约项暂不判（contracts_failed 空），由 VQAGATE 把 defects 透出后接上"""
    sys.path[:0] = [str(ROOT / "services/agent"), str(ROOT / "packages/qc")]
    from tools.vqa import gaze_regression as GR
    r = GR.judge(path, shot)
    r.setdefault("contracts_failed", [])
    return r


def p_s8(ctx: Ctx) -> list[dict]:
    c = ctx.c("S8_vlm_sample")
    done = ctx.mem.setdefault("vlm_done", {})
    from tools.autopilot import runs as RUNS
    rr = list(dict.fromkeys([RUNS.primary_run(), *RUNS.list_runs()]))
    fs = sorted((f for r in rr for f in glob.glob(str(RUNS.run_dir(r) / "images/frames/ep*/*.png"))), key=os.path.getmtime)
    fresh = [f for f in fs if os.path.getmtime(f) >= ctx.now - 3600 and os.path.relpath(f, ROOT).replace("\\", "/") not in done]
    out = []
    for f in fresh[-1:]:                     # 每 6 分钟 1 张 = 每小时 10 张
        rel = os.path.relpath(f, ROOT).replace("\\", "/")
        shot = os.path.basename(f).split("_")[0]
        try:
            v = vlm_judge(Path(f), shot)
        except Exception as e:  # noqa: BLE001
            v = {"error": repr(e)[:200]}
        done[rel] = {"t": ctx.now, "eye_contact": v.get("eye_contact"), "error": v.get("error")}
        out += J.j_vlm(shot, rel, v, None, c["defects"])
    for rel, d in list(done.items()):
        if d["t"] < ctx.now - 6 * 3600:
            done.pop(rel)
    return out


# ================================================================== S9
DETECT = ROOT / "apps/web/e2e/uiaudit/detect.mjs"


def p_s9(ctx: Ctx) -> list[dict]:
    c = ctx.c("S9_ui_rules")
    flows = ROOT / "tools/sentinel/ui_flows.json"
    try:
        subprocess.run(["node", str(DETECT), str(flows), "sentinel"], cwd=str(DETECT.parent), capture_output=True, timeout=240,
                       creationflags=NOWIN)
    except (OSError, subprocess.TimeoutExpired) as e:
        ctx.errors["S9"] = repr(e)[:200]
        return []
    res = jl(DETECT.parent / "sentinel_detect.json") or []
    pages = {}
    for fl in res:
        val = next((s.get("value") for s in fl.get("steps") or [] if "js" in s), None)
        pages[fl.get("id")] = val if isinstance(val, dict) else {"error": f"无 DOM 规则结果（overlay={fl.get('overlay')}）"}
        if fl.get("overlay"):
            pages[fl["id"]] = {"color_capsules": [], "broken_imgs": [], "contradictions": [f"页面报错 / 白屏：{fl['overlay']}"]}
    return J.j_ui({"pages": pages}, c)


# ================================================================== S10
def _run(args: list[str], timeout: int) -> tuple[int | None, str]:
    py = str(ROOT / ".venv/Scripts/python.exe")
    try:
        r = subprocess.run([py, *args], cwd=str(ROOT), capture_output=True, timeout=timeout, creationflags=NOWIN,
                           env={**os.environ, "PYTHONIOENCODING": "utf-8", "OMP_NUM_THREADS": "2"})
        return r.returncode, r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace")[-500:]
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, repr(e)


def p_s10(ctx: Ctx) -> list[dict]:
    tmp = ROOT / "data/sentinel/decision_check_sentinel.json"
    rc, _ = _run(["tools/qa/decision_check.py", "--json", str(tmp)], 300)
    rows = jl(tmp) if rc is not None else None
    dc_bad = [r["id"] for r in rows if r.get("ok") is False] if isinstance(rows, list) else None
    rc2, txt2 = _run(["tools/qa/decision_propagation.py", "--dry"], 300)
    dp_bad = None if rc2 is None else ([ln.strip()[:80] for ln in txt2.splitlines() if "❌" in ln][:12] if rc2 else [])
    rc3, txt3 = _run(["tools/knowledge/compile.py", "--check"], 300)
    return J.j_rules(dc_bad, dp_bad, rc3, txt3)


# ================================================================== S11
def p_s11(ctx: Ctx) -> list[dict]:
    c = ctx.c("S11_stage_stuck_s")
    st = jl("data/autopilot/flow/status.json") or {}
    tr = ctx.mem.setdefault("stuck", {})
    for e in st.get("episodes") or []:
        cur = e.get("current")
        sg = (e.get("stages") or {}).get(cur) or {}
        fp = f"{sg.get('done')}/{sg.get('total')}|{sg.get('status')}"
        k = str(e.get("ep"))
        if k not in tr or tr[k]["stage"] != cur or tr[k]["progress"] != fp:
            tr[k] = {"stage": cur, "progress": fp, "since": ctx.now}
    return J.j_stuck(tr, ctx.now, c)


# ================================================================== S12
def p_s12(ctx: Ctx) -> list[dict]:
    c = ctx.c("S12_script_ruler")
    fs = sorted(glob.glob(str(ROOT / "data/review_pages/hollywood*/**/ruler*.json"), recursive=True), key=os.path.getmtime)
    ruler = None
    if fs:
        d = jl(fs[-1]) or {}
        sd = d.get("stdev")
        if sd is None and isinstance(d.get("files"), dict):
            sds = [v.get("stdev") for v in d["files"].values() if v.get("stdev") is not None]
            sd = max(sds) if sds else None
        ruler = {"stdev": sd, "src": os.path.relpath(fs[-1], ROOT)}
    fails = None
    try:
        rows = [json.loads(x) for x in (ROOT / "data/autopilot/imports.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
        rec = [r for r in rows if "rubric_code_fail" in r]
        if rec:
            fails = {f"ep{e:02d}": int(r["rubric_code_fail"].get(str(e), 0)) if isinstance(r["rubric_code_fail"], dict) else int(r["rubric_code_fail"])
                     for r in rec[-1:] for e in r.get("episodes") or []}
    except (OSError, ValueError) as e:  # arch-ok: 记 UNKNOWN；fails=None = 新稿代码判定本拍未测
        UNKNOWN["data/autopilot/imports.jsonl"] = type(e).__name__
    return J.j_script(fails, ruler, c)


# ================================================================== S13
def p_s13(ctx: Ctx) -> list[dict]:
    c = ctx.c("S13_human_wait")
    mem = ctx.mem.setdefault("waits", {})
    out = []
    lr = laptop_registry()
    sources = {"laptop": lr["waits"]}
    regs = {}
    for h in HOSTS:
        r = ctx.remote(h)
        if r and r.get("registry"):
            sources[h] = r["registry"].get("waits") or {}
            regs[h] = r
    for where, waits in sources.items():
        m = mem.setdefault(where, {})
        for o in list(m):
            if o not in waits:
                m.pop(o)
        bf = backfill_wait_since(regs[where].get("events") or []) if where in regs else {}
        for o, w in waits.items():
            m.setdefault(o, [bf.get(o, ctx.now), w])
        out += J.j_human_wait(where, {o: (t, w) for o, (t, w) in m.items()}, ctx.now, c)
    for h, r in regs.items():
        hist = (ctx.mem.get("gpu_hist") or {}).get(h) or []
        idle = None
        if hist:
            z = None
            for t, us in hist:
                z = (z if z is not None else t) if us and max(us) <= 0 else None
            idle = (ctx.now - z) if z is not None else 0.0
        cnt = (r["registry"].get("counts") or {})
        out += J.j_pipeline_gap(h, idle, cnt.get("ready", 0), cnt.get("pending", 0), len(sources.get(h) or {}), c)
    return out


def backfill_wait_since(events: list[dict], k: int = 2) -> dict[str, float]:
    """服务器登记表没有 since：用日志里第 k 次 redo_fail 的时刻估计进入“驳回重出 k 次都没换上，等总调度定”的时刻"""
    n, out = {}, {}
    for e in sorted(events, key=lambda x: x.get("t") or 0):
        if e.get("ev") == "redo_fail" and e.get("obj"):
            n[e["obj"]] = n.get(e["obj"], 0) + 1
            if n[e["obj"]] == k:
                out[e["obj"]] = e["t"]
    return out


PROBES = {"S1": p_s1, "S2": p_s2, "S3": p_s3, "S4": p_s4, "S5": p_s5, "S6": p_s6, "S7": p_s7, "S8": p_s8, "S9": p_s9,
          "S10": p_s10, "S11": p_s11, "S12": p_s12, "S13": p_s13}
CFG_OF = {"S1": "S1_lane_util_min", "S2": "S2_gpu_all_idle_s", "S3": "S3_score_p50_s", "S4": "S4_recover_s", "S5": "S5_release",
          "S6": "S6_config_parity", "S7": "S7_pause_max_s", "S8": "S8_vlm_sample", "S9": "S9_ui_rules", "S10": "S10_rules_green",
          "S11": "S11_stage_stuck_s", "S12": "S12_script_ruler", "S13": "S13_human_wait"}
