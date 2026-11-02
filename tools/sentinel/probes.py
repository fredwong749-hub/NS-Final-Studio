"""SENTINEL 探针（实时）：每条 SLO 一个 p_sN(ctx) → findings（判定都在 judges.py，回放共用）。规则 K-OPS-S02 / S03。

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
COMFY_PORTS = {"gpu33:0": 8188, "gpu33:1": 8189, "gpu33:3": 8191, "gpu36:0": 8188, "gpu36:1": 8189}   # = lane_util.DEFAULT_LANES


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
            rc = self.mem.setdefault("remote_calls", {}).setdefault(host, {"ok": 0, "n": 0, "hist": []})
            rc["hist"] = [x for x in rc["hist"] if self.now - x[0] <= 86400][-1500:] + [[round(self.now), self._remote[host] is not None]]
            rc["n"], rc["ok"] = len(rc["hist"]), sum(1 for x in rc["hist"] if x[1])
        return self._remote[host]


G26_MIN_SV = "sv-20261102-09"


def hosts_decl() -> dict | None:
    """声明（config/factory/hosts.json，tools/factory/hosts.py）：sv-09（hosts.py 入版）部署到服务器之前返回 None，探针继续用旧表。
    → {"lanes": {lane: rec（enabled 的）}, "broken": {host: [gpu]}, "root": {host: repo}}"""
    sv = ((jl("data/system_version.txt") or {}).get("id") or "")
    if sv < G26_MIN_SV:
        return None
    try:
        from tools.factory import hosts as HS
        d = HS.load()
    except Exception as e:  # noqa: BLE001  # arch-ok: 记 UNKNOWN（S0 工单），本拍退回旧表
        UNKNOWN["config/factory/hosts.json"] = repr(e)[:80]
        return None
    lanes = {ln: r for ln, r in HS.lanes(enabled=True, d=d).items() if not ln.startswith("laptop")}
    return {"lanes": lanes, "broken": {h: list(v.get("broken_gpus") or []) for h, v in d["hosts"].items()},
            "root": {h: v.get("repo") for h, v in d["hosts"].items() if v.get("repo")}}


def remote_batch(host: str, parity: dict, timeout: float, vqa: bool) -> dict | None:
    from tools.netfix import rssh
    files = ",".join(parity_files(parity))
    hs = hosts_decl()
    if hs:                                     # sv-09 起：端口 / 服务器路径 / 坏卡都读 config/factory/hosts.json（SYSARCH 4-2，唯一来源）
        ports = ",".join(str(int(r["comfy_port"])) for ln, r in hs["lanes"].items() if ln.startswith(host + ":"))
        broken = ",".join(str(i) for i in hs["broken"].get(host, [])) or "-"
        root = hs["root"].get(host) or parity["server_root"]
    else:
        ports = ",".join(str(p) for ln, p in COMFY_PORTS.items() if ln.startswith(host))
        broken, root = "-", parity["server_root"]
    cmd = f"timeout {int(timeout) - 8} nice -n 19 python3 - {root} {files} {1 if vqa else 0} {ports or '-'} {broken}"
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
    part = (read_state("netfix/partition", {}) or {}).get("images") or {}
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
    lanes = jl("config/debug_lanes.json") if (ROOT / "config/debug_lanes.json").exists() else None   # 可选：缺省 = lane_util.DEFAULT_LANES
    rec = lane_util.measure(c["window_min"], lanes)
    ctx.mem["lane_util_last"] = rec
    return J.j_lane_util(rec, c)


# ================================================================== S2
def p_s2(ctx: Ctx) -> list[dict]:
    c = ctx.c("S2_gpu_all_idle_s")
    lr = laptop_registry()
    out = []
    loc = local_smi()
    if loc:
        append_sample("laptop", ctx.now, loc)
    for h in HOSTS:
        r = ctx.remote(h)
        if not r or not r.get("smi"):
            continue
        utils = [u for i, u, _m in r["smi"] if i in IMAGE_GPUS[h]]
        append_sample(h, ctx.now, r["smi"])
        hist = ctx.mem.setdefault("gpu_hist", {}).setdefault(h, [])
        hist.append([ctx.now, utils])
        del hist[:-30]
        reg = r.get("registry") or {}
        ready = {"server": (reg.get("counts") or {}).get("ready", 0), "laptop_partition": (lr["by_host"].get(h) or {}).get("ready", 0)}
        paused = bool((r.get("control") or {}).get("paused") or (r.get("heartbeat") or {}).get("paused"))
        out += J.j_gpu_idle(h, [tuple(x) for x in hist], ready, paused, ctx.now, c)
        for ln, port in COMFY_PORTS.items():
            if ln.startswith(h) and str(port) in (r.get("comfy") or {}):
                v = r["comfy"][str(port)]
                out.append(J.F("S2", f"comfy:{ln}", v is not True, f"出图道 {ln} 的 ComfyUI :{port} 不通（{v}）——这条道出不了图", port=port, reply=str(v)[:120]))
    return out


def local_smi() -> list | None:
    """笔记本本机 nvidia-smi（4080 VLM 专用卡，L-100）→ [[index, util, mem]]；取不到返回 None 并记 UNKNOWN"""
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=index,utilization.gpu,memory.used", "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=15, creationflags=NOWIN)
    except (OSError, subprocess.TimeoutExpired) as e:  # arch-ok: 记 UNKNOWN（S0 工单），VLM 卡该时段记无数据
        UNKNOWN["laptop:nvidia-smi"] = repr(e)[:80]
        return None
    out = []
    for ln in r.stdout.splitlines():
        p = [x.strip() for x in ln.split(",")]
        if len(p) == 3 and p[0].isdigit():
            out.append([int(p[0]), int(p[1]) if p[1].isdigit() else -1, int(p[2]) if p[2].isdigit() else -1])
    return out or None


def append_sample(host: str, t: float, smi: list) -> None:
    """全部卡（含 VLM 卡 gpu36:2）的 nvidia-smi 采样落盘，给 GPU 24 小时统计用（以后 VLM 卡按采样算，不再“无数据”）"""
    p = ROOT / "data/sentinel/gpu_samples.jsonl"
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"t": round(t), "host": host, "smi": smi}) + chr(10))


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


def vqa_expected(c: dict) -> dict:
    """声明的打分后端：config/vqa.json model.backends 优先（VQAGATE 维护），没有这个字段时用 sentinel.yaml S3 vqa_backends"""
    decl = ((jl("config/vqa.json", {}) or {}).get("model") or {}).get("backends")
    decl = {k: v for k, v in decl.items() if not str(k).startswith("_")} if isinstance(decl, dict) else {}   # 跳过 _doc 等注释键
    return decl or dict(c.get("vqa_backends") or {})


def _http(url: str) -> str | None:
    import urllib.request
    try:
        with urllib.request.urlopen(url, timeout=4) as r:
            return r.read(600).decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001  # arch-ok: 连不上 → 文本 ERR，vqa_kind 判 down（会开单，不当正常）
        return "ERR " + repr(e)[:120]


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
        evs = r.get("events") or []
        mx = next((e.get("max") for e in sorted(evs, key=lambda x: -(x.get("t") or 0)) if e.get("ev") == "score_backlog" and e.get("max")), None)
        if mx is None:            # 还没顶过：按策略公式（本机道数 × 看图实例，K-OPS-E05 / resources.score_backlog）
            from tools.autopilot import policy
            mx = policy.score_backlog_max(len(IMAGE_GPUS[h]), int(((jl("config/vqa.json", {}) or {}).get("model") or {}).get("instances") or 1))
        out += J.j_backlog_near(h, J.scoring_backlog(evs, ctx.now), mx, c)
        if h == VQA_HOST:
            k = J.vqa_kind(r.get("vqa_health"), r.get("vqa_models"))
            out += J.j_vqa_endpoint(h, 8870, k, vqa_expected(c).get(h), r.get("vqa_listener") or "")
    out += J.j_vqa_endpoint("laptop", 8870, J.vqa_kind(_http("http://127.0.0.1:8870/health"), _http("http://127.0.0.1:8870/v1/models")),
                            vqa_expected(c).get("laptop"))
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
    own = (len(m["new"]) * 3600 / span, f"sentinel 每拍快照 {span / 60:.0f} 分钟（60 s 采样，只会少算）") if span >= 600 else None
    try:
        last = json.loads((ROOT / "data/netfix/conn_watch_rate.jsonl").read_text(encoding="utf-8").strip().splitlines()[-1])
        if ctx.now - J.ts(last["at"]) < 7200:      # relay_rate.py 每 2 s 采样的实测（2 小时内）优先参与：取两者较大值，防止粗采样把违约“测没了”
            ref = (float(last["per_hour"]), f"conn_watch_rate.jsonl {last['at']} {last.get('tag', '')}")
            return max([x for x in (own, ref) if x], key=lambda x: x[0])
        if own:
            return own
    except (OSError, ValueError, IndexError, KeyError, TypeError) as e:  # arch-ok: 记 UNKNOWN；返回 None = 本拍不判跳板新建连接
        UNKNOWN["data/netfix/conn_watch_rate.jsonl"] = type(e).__name__
    return None, ""


# ================================================================== S5
def sv_ids() -> list[str]:
    idx = jl("data/system_versions/index.json", {}) or {}
    return [v["id"] for v in idx.get("versions") or [] if v.get("id")]


def latest_deploy() -> dict | None:
    """最近一次部署 = 各 deploy 记录里主机 at 最大的那条（按记录内容，不按文件修改时间）"""
    best = None
    for f in glob.glob(str(ROOT / "data/system_versions/deploy_*.json")):
        d = jl(f) or {}
        ats = [h.get("at") for h in (d.get("hosts") or {}).values() if h.get("at")]
        if ats and (best is None or max(ats) > best["at"]):
            best = {"id": d.get("id"), "at": max(ats), "file": os.path.basename(f)}
    return best


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
    ov = (read_state("netfix/override", {}) or {}).get("hosts") or {}
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
    """复用 tools/vqa/gaze_regression.judge（和生产同一套：本地看图整图 → MediaPipe 旁证 → 拿不准裁脸复判；只调一次看图）。
    VQAGATE 11-02 03:1x 起 judge 另回 defects / identity / missing_items / contract：
      身份 = contract.Q1.status == fail（契约 ArcFace，只有 data/renders 下的生产图有）；identity.per_person 的“不像”只记交叉核对证据
      缺件 = contract.Q2.status == fail，或 missing_items 里某项 s == defect"""
    sys.path[:0] = [str(ROOT / "services/agent"), str(ROOT / "packages/qc")]
    from tools.vqa import gaze_regression as GR
    r = GR.judge(path, shot)
    ct = r.get("contract") or {}
    failed = set()
    # 身份口径以契约 Q1.status 为准（VQAGATE 03:3x）：复核带 sharp_only / 发糊（band_review sharpness < 42.3）被拦不算“不像”；
    # identity.per_person 的“不像”只作交叉核对证据，不单独判违约（没有 contract 的实验图不判身份）
    if (ct.get("Q1") or {}).get("status") == "fail":
        failed.add("Q1")
    # 合成感（人物与背景不融合）：IMGFIX 指标 / VQAGATE 契约字段到位后生效；sentinel.yaml S8 composite_max 为 null 时不判
    lim = (policy_item("S8_vlm_sample") or {}).get("composite_max")
    comp = r.get("composite") or (ct.get("composite") if isinstance(ct.get("composite"), dict) else None)
    if lim is not None and isinstance(comp, dict) and comp.get("score") is not None and float(comp["score"]) > float(lim):
        failed.add("composite")
    r["identity_crosscheck"] = [p for p in (r.get("identity") or {}).get("per_person") or [] if p.get("identity") == "不像"]
    if (ct.get("Q2") or {}).get("status") == "fail" or any((v or {}).get("s") == "defect" for v in (r.get("missing_items") or {}).values()):
        failed.add("Q2")
    r["contracts_failed"] = sorted(failed)
    return r


def policy_item(name: str) -> dict | None:
    from tools.autopilot import policy
    return (policy.load().get("sentinel") or {}).get(name, {}).get("value")


def p_s8(ctx: Ctx) -> list[dict]:
    c = ctx.c("S8_vlm_sample")
    done = ctx.mem.setdefault("vlm_done", {})
    # 抽样池 = takes.json 登记的首帧版本：1 小时内生成、契约 postflight 通过、没隔离、没抽过（按登记表，不按文件修改时间）
    fresh = []
    for tj in glob.glob(str(ROOT / "data/renders/ep*/S*/takes.json")):
        for t in (jl(tj) or {}).get("takes") or []:
            ts_ = J.ts(t.get("created_at"))
            rel = "data/" + str(t.get("file") or "")
            if (t.get("stage") == "image" and ts_ and ts_ >= ctx.now - 3600 and (t.get("postflight") or {}).get("ok") is True
                    and not t.get("quarantined") and rel not in done and (ROOT / rel).exists()):
                fresh.append((ts_, rel, Path(tj).parent))
    fresh = [str(ROOT / r) for _t, r, _d in sorted(fresh)]
    out = []
    for f in fresh[-1:]:                     # 每 6 分钟 1 张 = 每小时 10 张
        rel = os.path.relpath(f, ROOT).replace("\\", "/")
        pp = Path(f).parts
        shot = f"{pp[-4]}-{pp[-3]}" if len(pp) >= 4 and pp[-2] == "takes" else os.path.basename(f).split("_")[0]   # data/renders/ep01/S1/takes/x.png → ep01-S1
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
    fs = [ROOT / c["ruler_file"]] if c.get("ruler_file") else []          # 尺子验收文件（同稿重复打分口径），在 sentinel.yaml 登记
    ruler = None
    if fs:
        d = jl(fs[-1]) or {}
        sd = d.get("stdev")
        if sd is None and isinstance(d.get("files"), dict):
            sds = [v.get("stdev") for v in d["files"].values() if v.get("stdev") is not None]
            sd = max(sds) if sds else None
        ruler = {"stdev": sd, "src": os.path.relpath(fs[-1], ROOT)}
    # 新稿代码判定：HOLLYWOOD autoflow 每集状态 data/pipeline/runs/<run>/autoflow_epNN.json 的 rubric_code_fail {n, ids}
    # （只统计 rubric_code 27 条代码判定条目；没有该字段的旧稿不判）。σ 用尺子验收口径（同稿重复打分），不用 autoflow 的 ruler_sigma（评审间离散度，口径不同）
    from tools.autopilot import runs as RUNS
    fails = {}
    for r in dict.fromkeys([RUNS.primary_run(), *RUNS.list_runs()]):
        for f in sorted(glob.glob(str(RUNS.run_dir(r) / "autoflow_ep*.json"))):
            d = jl(f) or {}
            rc = d.get("rubric_code_fail")
            if isinstance(rc, dict) and rc.get("n") is not None:
                fails[f"{r}:{Path(f).stem.split('_')[-1]}"] = int(rc["n"])
    fails = fails or None
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


# ================================================================== S14
def p_s14(ctx: Ctx) -> list[dict]:
    """五条 RSI 线：读 data/rsi/scores.jsonl → 判 2 小时无新分 / 连续 3 轮不升（派牵头人）→ 重写晚报 data/review_pages/rsi/index.html"""
    from tools.sentinel import rsi
    c = ctx.c("S14_rsi_lines")
    recs, bad = rsi.load(c)
    if bad:
        UNKNOWN[c["scores_file"]] = f"{len(bad)} 行读不懂（{bad[0][:60]}）"
    sm = rsi.summary(c, recs, ctx.now)
    ctx.mem["rsi_summary"] = sm
    try:
        rsi.report(ctx.now, c)
    except OSError as e:  # arch-ok: 报告写失败记 UNKNOWN（S0 工单），不影响判定
        UNKNOWN[c["report"]] = repr(e)[:120]
    return J.j_rsi(sm, ctx.now, c)


# ================================================================== GPU 24 小时（项目方 04:0x）
def p_gpu24(ctx: Ctx) -> list[dict]:
    """每小时重算 data/rsi/gpu_24h.json（tools/sentinel/gpu_hours.py；服务器本机压缩 /history 后回传，每台一次 rssh）。只产数据，不开单"""
    from tools.sentinel import gpu_hours as G
    res = G.build(ctx.now)
    G.write(res)
    for k, v in (res.get("errors") or {}).items():
        UNKNOWN[f"gpu_24h:{k}"] = v[:80]
    ctx.mem["gpu24_productive_pct"] = res["for_rsi_line5"]["productive_pct"]
    return J.j_wait_top(res, ctx.c("GPU24_alloc").get("top_n", 2))


# ================================================================== S15 / S16（总调度 04:2x）
def p_s15(ctx: Ctx) -> list[dict]:
    c = ctx.c("S15_flow_tick")
    p = ROOT / c["file"]
    rec = jl(c["file"]) if p.exists() else None
    return J.j_flow_tick(rec, p.stat().st_mtime if p.exists() else None, ctx.now, c)


def laptop_cmdlines() -> list[str] | None:
    """一次 PowerShell CIM 查询拿 python / pythonw / node 进程命令行（BELOW_NORMAL、30 s 超时）；取不到返回 None 并记 UNKNOWN"""
    ps = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-CimInstance Win32_Process -Filter \"Name='python.exe' OR Name='pythonw.exe' OR Name='node.exe'\" | "
          "ForEach-Object { $_.CommandLine } | ConvertTo-Json -Compress")
    try:
        r = subprocess.run(["powershell.exe", "-NoProfile", "-Command", ps], capture_output=True, timeout=30, creationflags=NOWIN)
        d = json.loads(r.stdout.decode("utf-8", "replace") or "[]", strict=False)   # 命令行里可能有换行 / 制表符
    except (OSError, subprocess.TimeoutExpired, ValueError) as e:  # arch-ok: 记 UNKNOWN（S0 工单），本拍 S16 不判
        UNKNOWN["laptop:process_list"] = repr(e)[:80]
        return None
    return [x for x in ([d] if isinstance(d, str) else d or []) if x]


def p_s16(ctx: Ctx) -> list[dict]:
    return J.j_procs(laptop_cmdlines(), ctx.c("S16_laptop_procs")["procs"])


# ================================================================== S17 / S18 / control 历史（总调度 08:0x）
def p_s17(ctx: Ctx) -> list[dict]:
    """单镜出图速率：笔记本日志 + 两台服务器日志（remote_probe 已回传最近 3 小时 rendered）"""
    ev = [e for e in laptop_rendered()]
    for h in HOSTS:
        r = ctx.remote(h)
        if r:
            ev += [e for e in r.get("events") or [] if e.get("ev") == "rendered"]
    return J.j_shot_rate(ev, ctx.now, ctx.c("S17_shot_render_rate"))


def laptop_rendered(since_s: float = 3600) -> list[dict]:
    p = ROOT / "data/producer/log.jsonl"
    out = []
    with p.open("rb") as fh:
        fh.seek(max(0, p.stat().st_size - 1_500_000))
        for ln in fh.read().decode("utf-8", "replace").splitlines():
            if '"rendered"' in ln:
                try:
                    d = json.loads(ln)
                except ValueError:  # arch-ok: 半行跳过
                    continue
                if d.get("ev") == "rendered" and d.get("t", 0) >= time.time() - since_s:
                    out.append(d)
    return out


def p_s18(ctx: Ctx) -> list[dict]:
    c = ctx.c("S18_temp_holds")
    d = read_state("netfix/partition", {}) or {}
    return J.j_temp_holds(d.get(c["key"]) or {}, ctx.now, c)


CTRL_KEYS = ("paused", "paused_by", "paused_at", "reason_kind", "expires_at", "note", "only", "hold_lanes")


def p_ctrl_history(ctx: Ctx) -> list[dict]:
    """control.json 变更历史（唯一写入方）：笔记本 + 两台服务器的 control.json（关键字段）和 partition.json _temp_holds，
    跟上一拍比，有变化追加一行到 data/sentinel/control_history.jsonl。GPU 24 小时按它归 pause / hold，不再“原因不明”"""
    c = ctx.c("CTRL_history")
    snaps = {"laptop": jl("data/producer/control.json")}
    for h in HOSTS:
        r = ctx.remote(h)
        if r and r.get("control") is not None:
            snaps[h] = r["control"]
    snaps["temp_holds"] = (read_state("netfix/partition", {}) or {}).get("_temp_holds") or {}
    last = ctx.mem.setdefault("ctrl_last", {})
    p = ROOT / c["out"]
    for src, v in snaps.items():
        if v is None:
            continue
        cur = {k: v.get(k) for k in CTRL_KEYS} if src != "temp_holds" else v
        if last.get(src) != cur:
            with p.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"t": round(ctx.now), "at": J.iso(ctx.now), "src": src, "state": cur, "prev": last.get(src)},
                                   ensure_ascii=False) + chr(10))
            last[src] = cur
    return []


# ================================================================== S19 产能见底（总调度 11:1x）
def drafts_and_imports(now: float, recent_s: float) -> tuple[list[str], list[str]]:
    """→ (待导入的稿 ["run:epNN"], 最近 recent_s 内导入过的 ["run:epNN"])"""
    from tools.autopilot import runs as RUNS
    prim = RUNS.primary_run()
    imported, recent = set(), []
    p = ROOT / "data/autopilot/imports.jsonl"
    if p.exists():
        for ln in p.read_text(encoding="utf-8").splitlines():
            try:
                d = json.loads(ln)
            except ValueError:  # arch-ok: 半行跳过
                continue
            run = d.get("run_id") or prim
            for ep in d.get("episodes") or []:
                k = f"{run}:ep{int(ep):02d}"
                imported.add(k)
                if now - (J.ts(d.get("at")) or 0) <= recent_s:
                    recent.append(k)
    pending = []
    for r in dict.fromkeys([prim, *RUNS.list_runs(status=None)]):
        af = jl(RUNS.run_dir(r) / "autoflow.json") if (RUNS.run_dir(r) / "autoflow.json").exists() else None
        for ep, v in ((af or {}).get("episodes") or {}).items():
            k = f"{r}:ep{int(ep):02d}"
            if isinstance(v, dict) and v.get("verdict") == "importable" and k not in imported:
                pending.append(k)
    return pending, recent


def p_s19(ctx: Ctx) -> list[dict]:
    from tools.autopilot import runs as RUNS
    c = ctx.c("S19_capacity_floor")
    prim, producing = RUNS.primary_run(), set(RUNS.list_runs(status="producing"))
    ready, notp = {}, {}
    for h in HOSTS:
        r = ctx.remote(h)
        if not (r and r.get("registry")):
            continue
        by = r["registry"].get("ready_by_run")
        if by is None:                         # 旧格式（没按 run 拆）：全算可派
            ready[h] = int((r["registry"].get("counts") or {}).get("ready", 0))
            continue
        ready[h] = sum(n for k, n in by.items() if (k or prim) in producing)
        notp[h] = {k: n for k, n in by.items() if (k or prim) not in producing}
    if len(ready) < len(HOSTS):                # 少一台没取到 = 本拍不判（不能把取不到当 ready=0）
        return []
    pending, recent = drafts_and_imports(ctx.now, c["recent_import_s"])
    return J.j_capacity(ready, pending, recent, c, notp)


# ================================================================== G26 声明 vs 实际（总调度 11:2x 批）
def p_g26(ctx: Ctx) -> list[dict]:
    """以 hosts.json 为声明，每拍逐条核对启用的道：端口可达、system_stats 正常、监听进程跑在声明的 GPU 上、坏卡没有作业"""
    hs = hosts_decl()
    if hs is None:
        ctx.mem["g26_state"] = f"等 {G26_MIN_SV} 部署（hosts.py 入版）后上线"
        return []
    out = []
    for h in HOSTS:
        r = ctx.remote(h)
        if not r or "g26_lanes" not in r:
            continue
        decl = {ln: rec for ln, rec in hs["lanes"].items() if ln.startswith(h + ":")}
        out += J.j_decl_vs_actual(h, decl, r["g26_lanes"], hs["broken"].get(h, []), r.get("broken_apps") or {})
    return out


# ================================================================== S20 scratchpad 进程（K-OPS-Y04，SYSARCH 派）
def laptop_procs_full() -> list[dict] | None:
    """python / pythonw / bash / sh 进程（pid、名字、命令行）；一次 CIM 查询，取不到返回 None 并记 UNKNOWN"""
    ps = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-CimInstance Win32_Process -Filter \"Name='python.exe' OR Name='pythonw.exe' OR Name='bash.exe' OR Name='sh.exe'\" | "
          "Select-Object ProcessId,ParentProcessId,Name,CommandLine | ConvertTo-Json -Compress")
    try:
        r = subprocess.run(["powershell.exe", "-NoProfile", "-Command", ps], capture_output=True, timeout=30, creationflags=NOWIN)
        d = json.loads(r.stdout.decode("utf-8", "replace") or "[]", strict=False)   # 命令行里可能有换行 / 制表符
    except (OSError, subprocess.TimeoutExpired, ValueError) as e:  # arch-ok: 记 UNKNOWN（S0 工单），本拍 S20 不判
        UNKNOWN["laptop:process_list_full"] = repr(e)[:80]
        return None
    d = [d] if isinstance(d, dict) else d or []
    return [{"pid": x.get("ProcessId"), "ppid": x.get("ParentProcessId"), "name": x.get("Name"), "cmd": x.get("CommandLine") or ""} for x in d]


def laptop_shell_snapshot() -> list[dict] | None:
    """bash / sh / pwsh / powershell / ssh 进程（pid、父 pid、创建时间、命令行）；一次 CIM 查询"""
    ps = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-CimInstance Win32_Process -Filter \"Name='bash.exe' OR Name='sh.exe' OR Name='pwsh.exe' OR Name='powershell.exe' OR Name='ssh.exe'\" | "
          "Select-Object ProcessId,ParentProcessId,Name,CommandLine,@{n='c';e={$_.CreationDate.ToString('o')}} | ConvertTo-Json -Compress")
    try:
        r = subprocess.run(["powershell.exe", "-NoProfile", "-Command", ps], capture_output=True, timeout=30, creationflags=NOWIN)
        d = json.loads(r.stdout.decode("utf-8", "replace") or "[]", strict=False)
    except (OSError, subprocess.TimeoutExpired, ValueError) as e:  # arch-ok: 记 UNKNOWN（S0 工单），本拍不判 ssh 轮询
        UNKNOWN["laptop:shell_snapshot"] = repr(e)[:80]
        return None
    d = [d] if isinstance(d, dict) else d or []
    return [{"pid": x.get("ProcessId"), "ppid": x.get("ParentProcessId"), "name": (x.get("Name") or "").lower(), "cmd": x.get("CommandLine") or "",
             "created_t": J.ts(str(x.get("c") or "")[:19])} for x in d]


def ssh_loop_findings(ctx: Ctx, c: dict) -> list[dict]:
    snap = laptop_shell_snapshot()
    if snap is None:
        return []
    byid = {p["pid"]: p for p in snap}
    shells = {p["pid"]: p for p in snap if p["name"] in ("bash.exe", "sh.exe", "pwsh.exe", "powershell.exe")
              and "ssh_spawn_watch" not in p["cmd"] and "tools/sentinel" not in p["cmd"].replace("\\", "/")}
    first = "ssh_seen" not in ctx.mem                  # 第一次只记下已有的 ssh，不算“新起”（常驻隧道不能当轮询）
    mem = ctx.mem.setdefault("ssh_seen", {"pids": [], "spawns": {}})
    seen = set(mem["pids"])
    if first:
        seen |= {p["pid"] for p in snap if p["name"] == "ssh.exe"}
    spawns = {int(k): v for k, v in mem["spawns"].items()}
    for p in snap:
        if p["name"] != "ssh.exe" or p["pid"] in seen:
            continue
        seen.add(p["pid"])
        anc, hops = p.get("ppid"), 0                  # 往上找最近的会话 shell（父或祖父）
        while anc in byid and hops < 3 and anc not in shells:
            anc, hops = byid[anc].get("ppid"), hops + 1
        if anc in shells:
            spawns.setdefault(anc, []).append(ctx.now)
    sf = ROOT / c["ssh_loop"]["spawns_file"]          # NETFIX ssh_spawn_watch.ps1 的逐秒记录（在跑时更准）
    if sf.exists() and ctx.now - sf.stat().st_mtime < c["ssh_loop"]["window_s"]:
        for ln in sf.read_text(encoding="utf-8", errors="replace").splitlines()[-2000:]:
            try:
                d = json.loads(ln)
            except ValueError:  # arch-ok: 半行跳过
                continue
            t = J.ts(d.get("at"))
            for pid, sh in shells.items():
                if t and sh["cmd"] and sh["cmd"] in (d.get("parent") or "", d.get("grand") or ""):
                    spawns.setdefault(pid, []).append(t)
    spawns = {k: sorted(set(round(x) for x in v if ctx.now - x <= c["ssh_loop"]["window_s"])) for k, v in spawns.items() if k in shells}
    mem["pids"] = [x for x in seen if x in byid][-500:]
    mem["spawns"] = {str(k): v for k, v in spawns.items()}

    def owner(cmd: str) -> str | None:
        import re
        names = re.findall(r"([\w.\-]+\.(?:py|sh|ps1))", cmd.replace("\\", "/"))
        for nm in names:
            o = (c.get("owner_by_script") or {}).get(nm)
            if o:
                return o
            try:
                o = owner_of_file(nm)
            except Exception:  # noqa: BLE001  # arch-ok: 归属查不到就派总调度
                o = None
            if o:
                return o
        return None
    return J.j_ssh_loops(shells, spawns, ctx.now, dict(c["ssh_loop"], owner_loop=c.get("owner_loop")), owner)


def p_s20(ctx: Ctx) -> list[dict]:
    """进程消失 = 恢复：本拍没再看到的 S20 旧单补一条“正常”，让工单库自动关单"""
    procs = laptop_procs_full()
    fs = J.j_scratch_procs(procs, ctx.c("S20_scratchpad_procs")) + ssh_loop_findings(ctx, ctx.c("S20_scratchpad_procs"))
    if procs is None:
        return fs
    seen = {f["key"] for f in fs}
    st = jl("data/sentinel/state.json", {}) or {}
    for k in (st.get("open") or {}):
        if k.startswith("S20:") and k not in seen:
            fs.append(J.F("S20", k.split(":", 1)[1], False, f"{k.split(':', 1)[1]} 已不在 scratchpad 里运行"))
    return fs


# ================================================================== S21 / S22 + 运行期状态读入口（ARCH_ROADMAP §10）
def read_state(name: str, default=None):
    """运行期状态统一读法：tools/factory/state_paths.read_state（先 data/state/，读不到才读 config/ 旧位置并记 legacy_reads）；
    state_paths 还没上线时退回旧位置（sv-10 兼容期双读，sv-11 删旧读）"""
    try:
        from tools.factory import state_paths as SP
    except ImportError:  # arch-ok: state_paths 未上线 → 旧位置
        legacy = {"netfix/partition": "config/netfix/partition.json", "netfix/override": "data/netfix/override_state.json"}
        return jl(legacy[name], default) if name in legacy else default
    try:
        return SP.read_state(name, default)
    except Exception as e:  # noqa: BLE001  # arch-ok: 记 UNKNOWN（S0 工单），返回 default
        UNKNOWN[f"state:{name}"] = repr(e)[:80]
        return default


_OWN_CACHE: dict = {}


def owner_of_file(ref: str) -> str | None:
    """文件（相对路径，或 caller 的“文件名:行”）→ tools/qa/ownership.yaml 的负责方；只给了文件名时在仓库里找同名文件"""
    from tools.qa import iter_gate as IG
    f = str(ref).split(":", 1)[0].replace("\\", "/")
    if f in _OWN_CACHE:
        return _OWN_CACHE[f]
    own = _OWN_CACHE.setdefault("__own__", IG.load_own())
    cands = [f] if "/" in f else [p.relative_to(ROOT).as_posix() for d in ("tools", "services", "apps", "ops", "packages")
                                   for p in (ROOT / d).rglob(f) if "node_modules" not in p.parts][:1]
    o = IG.owner_of(cands[0], own)[0] if cands else None
    _OWN_CACHE[f] = o
    return o


def p_s21(ctx: Ctx) -> list[dict]:
    c = ctx.c("S21_state_legacy_read")
    p = ROOT / c["file"]
    rows = []
    if p.exists():
        for ln in p.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                rows.append(json.loads(ln))
            except ValueError:  # arch-ok: 半行跳过
                continue
    try:
        from tools.factory import state_paths as SP
        names = sorted(getattr(SP, "LEGACY", {}).keys())
    except ImportError:  # arch-ok: state_paths 未上线 → 只按日志里出现的状态名判
        names = []
    return J.j_legacy_reads(rows, names, ctx.now, c, owner_of_file)


def p_s22(ctx: Ctx) -> list[dict]:
    c = ctx.c("S22_freeze_drift")
    p = ROOT / c["file"]
    if not p.exists():
        return []
    rows = []
    for ln in p.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            rows.append(json.loads(ln))
        except ValueError:  # arch-ok: 半行跳过
            continue
    return J.j_freeze_drift(rows, jl("data/system_versions/last_cut.json"), owner_of_file)


# ================================================================== S23 笔记本侧出图道可达率（总调度 13:2x）
def laptop_lane_ports(c: dict) -> dict[str, int]:
    """出图道 → 笔记本隧道端口：hosts.json（enabled、role 含 image、有 tunnel_port）优先，读不到用策略里的 fallback_ports"""
    try:
        from tools.factory import hosts as HS
        d = {ln: int(r["tunnel_port"]) for ln, r in HS.lanes(enabled=True).items()
             if r.get("tunnel_port") and "image" in (r.get("roles") or []) and not ln.startswith("laptop")}
        if d:
            return d
    except Exception as e:  # noqa: BLE001  # arch-ok: 记 UNKNOWN，退回 fallback_ports
        UNKNOWN["hosts.json:tunnel_ports"] = repr(e)[:80]
    return {k: int(v) for k, v in (c.get("fallback_ports") or {}).items()}


def p_s23(ctx: Ctx) -> list[dict]:
    """每拍并发测本地隧道端口 /system_stats（每条最多 timeout_s），记 5 分钟窗口"""
    import concurrent.futures as cf
    import urllib.request
    c = ctx.c("S23_laptop_lane_reach")
    ports = laptop_lane_ports(c)

    def probe(port: int) -> bool:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/system_stats", timeout=c["timeout_s"]) as r:
                return r.status == 200
        except Exception:  # noqa: BLE001  # arch-ok: 不通就是测量结果 False（会计入可达率、可能开单），不是“未测”
            return False
    with cf.ThreadPoolExecutor(max_workers=max(1, len(ports))) as ex:
        cur = dict(zip(ports, ex.map(probe, ports.values())))
    hist = ctx.mem.setdefault("lane_reach", {})
    for ln, ok in cur.items():
        h = hist.setdefault(ln, [])
        h.append([ctx.now, ok])
        hist[ln] = [x for x in h if ctx.now - x[0] <= c["window_s"] + 60]
    for ln in list(hist):
        if ln not in cur:
            hist.pop(ln)
    return J.j_lane_reach(hist, cur, ctx.now, c)


# ================================================================== S24 API 响应时间（总调度 14:1x）
def p_s24(ctx: Ctx) -> list[dict]:
    import urllib.request
    c = ctx.c("S24_api_latency")
    tok = ""
    try:
        tok = (ROOT / "data/auth/viewer_token").read_text(encoding="utf-8").strip()
    except OSError as e:  # arch-ok: 没有查看令牌时不带头直接测（旧 API 无登录），记 UNKNOWN
        UNKNOWN["data/auth/viewer_token"] = type(e).__name__
    hist = ctx.mem.setdefault("api_latency", {})
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for path in c["paths"]:
        t0 = time.time()
        try:
            req = urllib.request.Request(c["base"] + path, headers={"x-ns-viewer-token": tok} if tok else {})
            with op.open(req, timeout=c["timeout_s"]) as r:
                r.read()
                code = r.status
        except Exception:  # noqa: BLE001  # arch-ok: 失败就是测量结果（按 timeout_s 计入 p95），不是未测
            code = 0
        h = hist.setdefault(path, [])
        h.append([round(ctx.now), round(time.time() - t0, 3), code])
        del h[:-int(c["last_n"])]
    return J.j_api_latency(hist, c)


# ================================================================== S25 常驻 CLIP（FACTORY 口径）
CLIP_REMOTE = r'''
import json, os, sys, time, urllib.request
port, hto, pidf, evf, reason = int(sys.argv[1]), float(sys.argv[2]), sys.argv[3], sys.argv[4], sys.argv[5]
out = {"pid": None, "pid_alive": None, "health": None, "reloads_1h": None}
try:
    pid = int(open(pidf).read().strip())
    out["pid"] = pid
    try:
        os.kill(pid, 0)
        out["pid_alive"] = True
    except OSError:
        out["pid_alive"] = False
except (OSError, ValueError):
    out["pid_alive"] = False if os.path.exists(os.path.dirname(pidf)) else None
try:
    with urllib.request.urlopen("http://127.0.0.1:%d/health" % port, timeout=hto) as r:
        out["health"] = "ok" if r.status == 200 else "HTTP %d" % r.status
except Exception as e:
    out["health"] = "timeout" if "timed out" in repr(e) else "ERR " + repr(e)[:80]
try:
    n, now = 0, time.time()
    for ln in open(evf, encoding="utf-8", errors="replace").readlines()[-2000:]:
        try:
            d = json.loads(ln)
        except ValueError:
            continue
        t = d.get("t") or 0
        if not t and d.get("at"):
            try:
                import datetime
                t = datetime.datetime.fromisoformat(str(d["at"])).timestamp()
            except ValueError:
                t = 0
        if d.get("reason") == reason and now - float(t) <= 3600:
            n += 1
    out["reloads_1h"] = n
except OSError:
    out["reloads_1h"] = None
print(json.dumps(out))
'''


def p_s25(ctx: Ctx) -> list[dict]:
    from tools.netfix import rssh
    c = ctx.c("S25_clip_resident")
    out = []
    for h in HOSTS:
        cmd = (f"timeout {int(c['call_timeout_s']) - 5} nice -n 19 python3 - {c['port']} {c['health_timeout_s']} {c['pid_file']} "
               f"{c['events_file']} {c['reload_reason']}")
        try:
            r = rssh.run(h, cmd, input=CLIP_REMOTE.encode(), timeout=c["call_timeout_s"])
            d = json.loads(r.stdout.decode("utf-8", "replace").strip().splitlines()[-1]) if r.returncode == 0 else None
        except (subprocess.TimeoutExpired, ValueError, IndexError) as e:  # arch-ok: 记 UNKNOWN（S0 工单），本拍该机不判
            UNKNOWN[f"{h}:clip_resident"] = repr(e)[:80]
            d = None
        if d is None:
            UNKNOWN.setdefault(f"{h}:clip_resident", "远程调用失败")
        out += J.j_clip(h, d, c)
    return out


# ================================================================== SCORECARD 七项（总调度 17:4x）
def p_scorecard(ctx: Ctx) -> list[dict]:
    from tools.sentinel import scorecard as SC
    c = ctx.c("SC_scorecard")
    SC.ensure_ui_measure(c)                    # 界面实测放后台子进程（慢）
    res = SC.compute(write=True)
    ctx.mem["scorecard"] = {k: (v or {}).get("score") for k, v in res.items()}
    return J.j_scorecard(res, c["owners"]) + J.j_ui_measure(jl("data/rsi/ui_measure.json") or {}, c["owners"].get("ui", "UIRSI"))


# ================================================================== S26 / S27（总调度 20:10）
def p_s26(ctx: Ctx) -> list[dict]:
    c = ctx.c("S26_autoflow_resident")
    p = ROOT / c["file"]
    return J.j_autoflow_resident(jl(c["file"]) if p.exists() else None, p.stat().st_mtime if p.exists() else None, ctx.now, c)


def review_rounds(base: Path, judges: int) -> list[dict]:
    rounds = []
    for d in [base] + sorted(x for x in base.glob("r*") if x.is_dir()):
        done = [(d / f"judge_{k}" / "out" / "p1_review.json.done") for k in range(1, judges + 1)]
        res = d / "RESULT.json"
        rounds.append({"name": "r1" if d == base else d.name, "done": [x.stat().st_mtime for x in done if x.exists()],
                       "result_t": res.stat().st_mtime if res.exists() else None})
    return rounds


def p_s27(ctx: Ctx) -> list[dict]:
    from tools.autopilot import runs as RUNS
    c = ctx.c("S27_p1_review_chain")
    base = RUNS.run_dir(RUNS.primary_run()) / "judge_p1"
    if not base.exists():
        return []
    return J.j_review_chain(review_rounds(base, int(c["judges"])), ctx.now, c)


PROBES = {"S1": p_s1, "S2": p_s2, "S3": p_s3, "S4": p_s4, "S5": p_s5, "S6": p_s6, "S7": p_s7, "S8": p_s8, "S9": p_s9,
          "S10": p_s10, "S11": p_s11, "S12": p_s12, "S13": p_s13, "S14": p_s14, "GPU24": p_gpu24, "S15": p_s15, "S16": p_s16, "S17": p_s17, "S18": p_s18, "S19": p_s19, "G26": p_g26, "S20": p_s20, "S21": p_s21, "S22": p_s22, "S23": p_s23, "S24": p_s24, "S25": p_s25, "SC": p_scorecard, "S26": p_s26, "S27": p_s27,
          "CTRL": p_ctrl_history}
CFG_OF = {"S1": "S1_lane_util_min", "S2": "S2_gpu_all_idle_s", "S3": "S3_score_p50_s", "S4": "S4_recover_s", "S5": "S5_release",
          "S6": "S6_config_parity", "S7": "S7_pause_max_s", "S8": "S8_vlm_sample", "S9": "S9_ui_rules", "S10": "S10_rules_green",
          "S11": "S11_stage_stuck_s", "S12": "S12_script_ruler", "S13": "S13_human_wait",
          "S14": "S14_rsi_lines", "GPU24": "GPU24_alloc",
          "S15": "S15_flow_tick", "S16": "S16_laptop_procs", "S17": "S17_shot_render_rate", "S18": "S18_temp_holds", "S19": "S19_capacity_floor", "G26": "G26_decl_vs_actual", "S20": "S20_scratchpad_procs",
          "S21": "S21_state_legacy_read", "S22": "S22_freeze_drift", "S23": "S23_laptop_lane_reach", "S24": "S24_api_latency", "S25": "S25_clip_resident", "SC": "SC_scorecard", "S26": "S26_autoflow_resident", "S27": "S27_p1_review_chain",
          "CTRL": "CTRL_history"}
