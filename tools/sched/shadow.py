"""SCHED-SHADOW（L-209 S1，11-06）：影子模式——新调度器（tools/sched/core.py 工作板）读实时数据，只出决策、逐拍和现网对比，不派任何活。

L-209 目标形态 = 一集一张任务图 + 唯一调度器 + 单一状态库。S1 = 影子：连跑一集，差异要能解释。
每一拍（`once`，或 `run --every 60 --minutes N`）：
  1. 只读取数：每台服务器一次远程 python（经 tools/netfix/rssh 复用主连接，只读）——ComfyUI 队列 / 显卡、producer 登记表、
     control、log.jsonl 窗口事件（dispatch / rendered / 闸门 …）、vidgen_<host>.log 窗口 SUBMIT / DONE / SCORE、state_<host>.json、
     night_control、lane_roles_state、两份 partition.json（config/netfix 与 data/state/netfix，ARCH_MAP_20261106 §3）。
     笔记本只读：config/pipeline/sched.json、lane_roles.json、剧本成人镜（tools/brain/actions.Env.adult_ids）。
  2. 建活 DAG：两台登记表合并成一份（首尾帧按 control.only 归属台为准，视频取两台 + vidgen 状态里最靠后的状态；
     记“两台不一致”）；成人镜整镜不进图（只由项目方触发）；passed / best_effort / 尾帧不可用（I2VA）= 定下（终态）；
     资产没齐 = 资产任务 hold；本拍 10 min 内有 sop_gate / preflight / refs 拦截的对象 = hold（规则即闸门的影子版）。
  3. 一个 run 级阶段（L-207，两台各算一份的现状不用）：最早没落定视频的集 = active；首尾帧没定完 = frames（C2 兜底：
     ≥1 镜定下且没有就绪 / 在跑的首尾帧 → videos）；按 lane_roles.json 该阶段的表给 6 条道设角色（gpu33:2 永不入池）。
  4. 问工作板：现在空着的道各派什么（board.plan，不落租约）→ data/sched/shadow/decisions.jsonl。
  5. 对比：本拍空道“现网为什么空着”（瞬时，按 ARCH_MAP §2.3 的 12 个仲裁机制归因）+ 上一拍决策 vs 两拍之间现网实际派单
     （producer dispatch + vidgen SUBMIT / state 去重，VideoBridge 进程内 night 不重复计）→ data/sched/shadow/diff.jsonl；
     累计空道分钟 / 换模型次数 / 视频饿死分钟（现网 vs 影子）→ data/sched/shadow/metrics.json；
     窗口回看（log 重建每道忙闲区间）+ 模拟器预测本集用时（影子策略续跑 vs 已用时 vs KPI 50 min）→ docs/master/SHADOW_REPORT.md。
不写服务器、不 kill、不派单；本机写入全部原子（tmp + os.replace；jsonl 单次 write 追加）。
用法：
  .venv/Scripts/python.exe tools/sched/shadow.py once [--lookback-min 60] [--seeds 3]
  .venv/Scripts/python.exe tools/sched/shadow.py run --every 60 --minutes 90
  .venv/Scripts/python.exe tools/sched/shadow.py report        # 只按已有文件重写报告
"""
from __future__ import annotations

import importlib.util
import json
import os
import random
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import core as C  # noqa: E402
import sim as SIM  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT_REL = "data/sched/shadow"
REPORT_REL = "docs/master/SHADOW_REPORT.md"
SERVERS = ("gpu33", "gpu36")
SETTLED = ("passed", "best_effort", "adopted", "done")
RANK = {"passed": 6, "done": 6, "best_effort": 5, "adopted": 5, "running": 4, "scoring": 4, "rendering": 4, "submitted": 4,
        "ready": 3, "failed": 2, "pending": 1, "blocked": 1, "waiting_frame": 1, None: 0}
GATE_EVS = ("sop_gate_block", "preflight_block", "refs_mismatch")
END_EVS = ("rendered", "content_error", "infra_error", "preflight_block", "last_preflight_fail")
VIDEO_HINTS = ("minimax", "pika", "wan2", "wan_", "fl2va", "hunyuan", "ltx", "video")
# ARCH_MAP_20261106 §2.3 仲裁机制编号 → 名字（差异归因用）
MECH = {"M1": "partition.json / control.only+hold_lanes", "M3": "lane_roles.json 工位表", "M4": "lane_roles_state._active（每台各算）",
        "M5": "video yield / shared_lanes", "M6": "video_lanes / vram_gate", "M7": "video_shard", "M8": "lane_relay",
        "M9": "per-process leases", "M11": "pauses / sop_gate / preflight", "M12": "asset_worker _temp_holds",
        "SCHED": "新调度器策略（HEFT 秩 + 集序 + 亲和）", "STATE": "状态分裂（两台登记表 / 孤儿记录）", "?": "未解释"}
PARTITION_READERS = [  # ARCH_MAP_20261106 §3：谁读哪份 partition
    ("producer probe_lanes / partition_held", "config/netfix/partition.json", "producer.py:3546"),
    ("tools/netfix/dispatch.py → control.json only / hold_lanes", "data/state/netfix/partition.json", "dispatch.py:34"),
    ("night.py（_D.read_partition）→ control_<host>.json", "data/state/netfix/partition.json", "night.py dispatch_hosts"),
    ("asset_worker（_temp_holds 写入，tools/debug/lanes.py）", "data/state/netfix/partition.json", "asset_worker.py:380"),
]

REMOTE_PROBE = r"""
import json, os, subprocess, time, urllib.request, hashlib
from datetime import datetime, timedelta
RUN = "__RUN__"; HOST = "__HOST__"; SINCE = float("__SINCE__"); PORTS = json.loads('__PORTS__')
PD = "data/producer/runs/" + RUN
V = "data/pipeline/runs/" + RUN + "/video/"
NL = chr(10)
now = time.time()
out = {"now": now, "host": HOST, "since": SINCE, "gpus": {}, "queues": {}}

def J(p):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return None

def tail(p, nbytes):
    try:
        sz = os.path.getsize(p)
        with open(p, "rb") as f:
            if sz > nbytes:
                f.seek(sz - nbytes)
            return f.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return []

def ts(s):
    try:
        return datetime.fromisoformat(str(s).strip().replace(" ", "T")).timestamp()
    except Exception:
        return None

try:
    for ln in subprocess.run(["nvidia-smi", "--query-gpu=index,utilization.gpu,memory.used", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=20).stdout.splitlines():
        i, u, m = [x.strip() for x in ln.split(",")]
        out["gpus"][i] = {"util": int(u), "mem": int(m)}
except Exception as e:
    out["gpus_error"] = repr(e)[:100]

def models(prompt):
    names = []
    try:
        for node in (prompt or {}).values():
            if "Load" in str(node.get("class_type") or ""):
                for k in ("ckpt_name", "unet_name", "model_name", "model"):
                    v = (node.get("inputs") or {}).get(k)
                    if isinstance(v, str) and v:
                        names.append(v.rsplit("/", 1)[-1][:48])
    except Exception:
        pass
    return names[:3]

for lane, port in PORTS.items():
    try:
        q = json.loads(urllib.request.urlopen("http://127.0.0.1:%d/queue" % int(port), timeout=5).read())
        rec = {"running": [], "pending": len(q.get("queue_pending") or [])}
        for it in (q.get("queue_running") or []) + (q.get("queue_pending") or [])[:2]:
            ex = it[3] if len(it) > 3 and isinstance(it[3], dict) else {}
            tag = ex.get("ns_tag") if isinstance(ex.get("ns_tag"), dict) else {}
            pr = it[2] if len(it) > 2 and isinstance(it[2], dict) else {}
            rec["running"].append({"agent": tag.get("agent") or str(ex.get("client_id") or "?")[:10], "obj": tag.get("obj"),
                                   "job": tag.get("job"), "shot": tag.get("shot"), "kind": tag.get("kind"), "models": models(pr),
                                   "q": "run" if it in (q.get("queue_running") or []) else "pend"})
        out["queues"][lane] = rec
    except Exception:
        out["queues"][lane] = None

reg = J(PD + "/registry.json") or {}
eps = {}
for E in reg.get("episodes") or []:
    shots = {}
    for S in E.get("shots") or []:
        ob = S.get("objects") or {}
        rec = {}
        for k in ("assets", "first", "last", "video"):
            o = ob.get(k) or {}
            rec[k] = [o.get("status"), o.get("attempts") or 0, o.get("max_attempts") or 3, 1 if o.get("na") else 0,
                      1 if o.get("last_unavailable") else 0, str(o.get("where") or "")[:30],
                      str(o.get("waiting_for") or o.get("reason") or "")[:60]]
        shots[str(S.get("shot"))] = rec
    eps[str(E.get("ep"))] = {"asm": ((E.get("objects") or {}).get("assembly") or {}).get("status"), "shots": shots}
out["reg"] = eps
out["reg_updated"] = reg.get("updated")
ctrl = J(PD + "/control.json") or {}
out["ctrl"] = {"only": ctrl.get("only") or [], "hold_lanes": ctrl.get("hold_lanes") or [], "paused": bool(ctrl.get("paused"))}
hb = J(PD + "/heartbeat.json") or {}
out["hb_age_s"] = round(now - float(hb.get("t") or 0)) if hb.get("t") else None

KEEP = ("dispatch", "rendered", "passed", "content_fail", "redo_fail", "content_error", "infra_error", "best_effort",
        "review_adopt", "last_preflight_fail", "last_unavailable", "preflight_block", "refs_mismatch", "sop_gate_block",
        "lane_roles_wait", "lane_roles_phase", "lane_roles_active", "pause", "resume", "hard_cap_exhausted", "score_timeout",
        "orphan_take", "local_only_skip", "rescore_dispatch", "adopt_sweep", "rescore_cap", "score_infra", "review_fallback", "rescore")
evs, adult, first_dispatch = [], set(), {}
lines = tail(PD + "/log.jsonl", 60 * 1024 * 1024)
for ln in lines:
    if '"ev": "dispatch"' not in ln:
        continue
    try:
        d = json.loads(ln)
    except Exception:
        continue
    ob = str(d.get("obj") or "")
    ep = ob.split(":", 1)[-1].split("-", 1)[0].replace("ep", "").lstrip("0") or "0"
    t = d.get("t")
    if t and (ep not in first_dispatch or t < first_dispatch[ep]):
        first_dispatch[ep] = t
for ln in reversed(lines):
    try:
        d = json.loads(ln)
    except Exception:
        continue
    t = float(d.get("t") or 0)
    if t and t < SINCE:
        break
    ev = str(d.get("ev") or "")
    if ev == "adult_wait_owner":
        adult.add(str(d.get("obj") or "").split(":", 1)[-1])
        continue
    if ev not in KEEP:
        continue
    why = d.get("why") or d.get("reason") or d.get("error") or d.get("note") or ""
    evs.append([round(t, 1), ev, d.get("obj"), d.get("lane"), d.get("attempt"), d.get("gpu_s"), str(why)[:90],
                d.get("phase"), d.get("ep")])
evs.reverse()
out["events"] = evs[-4000:]
out["adult_wait"] = sorted(adult)
out["first_dispatch"] = first_dispatch

vl = []
base = datetime.fromtimestamp(now)
for ln in tail(V + "vidgen_" + HOST + ".log", 3 * 1024 * 1024):
    p = ln.split()
    if len(p) < 4 or p[1] not in ("SUBMIT", "DONE", "SCORE"):
        continue
    try:
        hh, mm, ss = [int(x) for x in p[0].split(":")]
    except Exception:
        continue
    dt = base.replace(hour=hh, minute=mm, second=ss, microsecond=0)
    if dt.timestamp() > now + 300:
        dt = dt - timedelta(days=1)
    t = dt.timestamp()
    if t < SINCE:
        continue
    if p[1] == "SUBMIT":
        vl.append([round(t, 1), "SUBMIT", p[2], p[3], p[6] if len(p) > 6 else None, None])
    elif p[1] == "DONE":
        sec = None
        try:
            sec = float(p[5].rstrip("s"))
        except Exception:
            pass
        vl.append([round(t, 1), "DONE", p[2], p[3], p[4] if len(p) > 4 else None, sec])
    else:
        vl.append([round(t, 1), "SCORE", p[2], p[3], None, p[4] if len(p) > 4 else None])
out["vidgen"] = vl

st = J(V + "state_" + HOST + ".json") or {}
vs = {}
for sid, r in (st.get("shots") or {}).items():
    rs = []
    for x in (r.get("renders") or [])[-8:]:
        if float(x.get("t_sub") or 0) >= SINCE - 3600 or x.get("state") in ("submitted", "rendering", "queued", "running"):
            rs.append([x.get("variant"), x.get("lane"), x.get("t_sub"), x.get("t_done"), x.get("state")])
    vs[sid] = {"status": r.get("status"), "renders": rs}
out["vstate"] = vs
nc = J(V + "night_control.json") or {}
out["nctrl"] = {k: nc.get(k) for k in ("yield_s", "video_lanes", "hold_lanes", "shared_lanes", "per_lane") if k in nc}
out["lrs"] = (J("data/pipeline/lane_roles_state.json") or {}).get(RUN) or {}
parts = {}
for p in ("config/netfix/partition.json", "data/state/netfix/partition.json"):
    d = J(p)
    if d is None:
        parts[p] = None
        continue
    holds = {}
    for ln_, h in (d.get("_temp_holds") or {}).items():
        exp = ts((h or {}).get("expires_at") or (h or {}).get("until"))
        holds[ln_] = {"by": (h or {}).get("by"), "why": str((h or {}).get("why") or "")[:50], "active": bool(exp and exp > now)}
    try:
        md5 = hashlib.md5(open(p, "rb").read()).hexdigest()[:8]
    except OSError:
        md5 = None
    parts[p] = {"images": d.get("images"), "video": d.get("video"), "retired": d.get("retired_lanes"), "lent": d.get("_lent_lanes"),
                "temp_holds": holds, "work_stealing": d.get("work_stealing"), "md5": md5}
out["partition"] = parts
print(NL + json.dumps(out, ensure_ascii=False))
"""


# ------------------------------------------------------------------ 小工具
def jst(t: float, fmt: str = "%m-%d %H:%M") -> str:
    """笔记本时钟是 EST，服务器 JST：一律按 epoch +9 h 出 JST 字符串"""
    return time.strftime(fmt, time.gmtime(float(t) + 9 * 3600))


def _j(p: Path, default=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):   # arch-ok: 影子模式的输入缺失 = 默认值，报告里标出来
        return default


def _jw(p: Path, d) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def _append(p: Path, row: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _write_text(p: Path, text: str) -> None:
    """原子写；保留已有文件的换行风格（CRLF / LF），新文件按 docs/master 惯例 CRLF"""
    p.parent.mkdir(parents=True, exist_ok=True)
    crlf = True
    if p.exists():
        crlf = b"\r\n" in p.read_bytes()[:4000]
    data = text.replace("\r\n", "\n")
    if crlf:
        data = data.replace("\n", "\r\n")
    tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
    tmp.write_bytes(data.encode("utf-8"))
    os.replace(tmp, p)


def _load(name: str, rel: str, root: Path = ROOT):
    sp = importlib.util.spec_from_file_location(name, Path(root) / rel)
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


def kind_of(obj: str | None) -> str:
    return str(obj or "").split(":", 1)[0]


def shot_of(obj: str | None) -> str:
    return str(obj or "").split(":", 1)[-1]


def ep_of(shot: str) -> int:
    try:
        return int(str(shot).split("-", 1)[0].replace("ep", ""))
    except ValueError:
        return 0


def model_of_kind(kind: str) -> str:
    return C.MODEL_OF.get(kind, "image")


# ------------------------------------------------------------------ 环境（真机只读；测试用 Fake 子类）
_RM_MOD: dict = {}


class Env:
    def __init__(self, root: Path = ROOT):
        self.root = Path(root)

    def now(self) -> float:
        return time.time()

    def run(self) -> str:
        return str((_j(self.root / "config/pipeline/runs.json", {}) or {}).get("primary") or "series10_v2")

    def sched_cfg(self) -> dict:
        return C.load_config(self.root / "config/pipeline/sched.json")

    def roles_cfg(self) -> dict:
        return _j(self.root / "config/pipeline/lane_roles.json", {}) or {}

    def lanes(self) -> dict:
        T = _load("telemetry_for_shadow", "tools/brain/telemetry.py", self.root)
        return T.Env(self.root).lanes()

    def merged_registry(self, run: str) -> dict | None:
        """L-209 S2.5：笔记本写的唯一合并登记表（新鲜才给；缺 / 过期 = None → 退回两台探针各自合并）"""
        try:
            if "m" not in _RM_MOD:
                _RM_MOD["m"] = _load("registry_merged_for_shadow", "tools/autopilot/registry_merged.py", self.root)
            RM = _RM_MOD["m"]
            return RM.fresh(run, self.root, self.now(), log=RM.default_log("shadow"), actor="shadow")
        except Exception:  # noqa: BLE001  # arch-ok: 模块 / 文件读不到 = 退回探针合并
            return None

    def adult_ids(self, run: str) -> set:
        A = _load("actions_for_shadow", "tools/brain/actions.py", self.root)
        return set(A.Env(self.root).adult_ids(run))

    def probe(self, host: str, run: str, since: float, lanes: dict, timeout: float = 90) -> dict | None:
        """只读远程探针（cd 仓库 && python3 - ，代码走 stdin）"""
        H = _load("hosts_for_shadow", "tools/factory/hosts.py", self.root)
        rssh = _load("rssh_for_shadow", "tools/netfix/rssh.py", self.root)
        ports = {ln: v["comfy_port"] for ln, v in lanes.items() if v["host"] == host}
        code = (REMOTE_PROBE.replace("__RUN__", run).replace("__HOST__", host).replace("__SINCE__", f"{since:.1f}")
                .replace("__PORTS__", json.dumps(ports)))
        try:
            r = rssh.run_retry(host, f"cd {H.server_root(host)} && python3 -", input=code.encode("utf-8"), timeout=timeout, tries=1)
            txt = (r.stdout or b"").decode("utf-8", "replace")
            return json.loads([ln for ln in txt.splitlines() if ln.startswith("{")][-1])
        except (OSError, ValueError, IndexError, AttributeError):   # arch-ok: 探针失败 = 本拍该台 None（报告 probe_errors 列出）
            return None


# ------------------------------------------------------------------ 状态合并（一个 run 级视图）
def _owner_hosts(probes: dict, shot: str) -> list:
    return [h for h, p in probes.items() if p and shot in ((p.get("ctrl") or {}).get("only") or [])]


def compact_registry(reg: dict) -> dict:
    """完整登记表 → 探针的紧凑格式 {ep: {"asm", "shots": {shot: {k: [st, att, max, na, lu, where, why]}}}}（同 REMOTE_PROBE）"""
    eps = {}
    for E in (reg or {}).get("episodes") or []:
        shots = {}
        for S in E.get("shots") or []:
            ob = S.get("objects") or {}
            rec = {}
            for k in ("assets", "first", "last", "video"):
                o = ob.get(k) or {}
                rec[k] = [o.get("status"), o.get("attempts") or 0, o.get("max_attempts") or 3, 1 if o.get("na") else 0,
                          1 if o.get("last_unavailable") else 0, str(o.get("where") or "")[:30],
                          str(o.get("waiting_for") or o.get("reason") or "")[:60]]
            shots[str(S.get("shot"))] = rec
        eps[str(E.get("ep"))] = {"asm": ((E.get("objects") or {}).get("assembly") or {}).get("status"), "shots": shots}
    return eps


def merge_registry(probes: dict, merged: dict | None = None) -> tuple[dict, list]:
    """两台登记表 → 一份。L-209 S2.5：给了新鲜的唯一合并登记表（registry_merged.json）→ 只用它（divergent = 它的真冲突）；
    否则旧退路：首尾帧 / 资产以 control.only 归属台为准（没有归属 = 取最靠后状态），视频取各台登记表最靠后。两种都再用 vidgen 状态补强视频。
    返回 (eps, divergent)；eps = {ep: {"asm": bool, "shots": {shot: {k: {"st", "att", "max", "lu", "src"}}}}}"""
    eps: dict = {}
    divergent = []
    views: dict = {}
    if merged:
        divergent = [{"obj": f"{c.get('kind')}:{c.get('shot') or 'ep' + str(c.get('ep'))}", "views": c.get("views") or {},
                      "used": c.get("used"), "why": c.get("why")} for c in merged.get("conflicts") or []]
        probes_reg = {"merged": {"reg": compact_registry(merged), "ctrl": {}}}
    else:
        probes_reg = probes
    for h, p in probes_reg.items():
        for ep, E in ((p or {}).get("reg") or {}).items():
            e = eps.setdefault(int(ep), {"asm": False, "shots": {}})
            e["asm"] = e["asm"] or E.get("asm") == "passed"
            for sid, rec in (E.get("shots") or {}).items():
                views.setdefault(sid, {})[h] = rec
    for sid, by in sorted(views.items()):
        ep = ep_of(sid)
        owners = [h for h in _owner_hosts(probes_reg, sid) if h in by]
        out = {}
        for k in ("assets", "first", "last", "video"):
            cand = {h: (r.get(k) or [None, 0, 3, 0, 0, "", ""]) for h, r in by.items()}
            if k != "video" and owners:
                h = owners[0]
            else:
                h = max(sorted(cand), key=lambda x: RANK.get(cand[x][0], 0))
            st, att, mx, na, lu, where, why = (list(cand[h]) + [None] * 7)[:7]
            out[k] = {"st": "passed" if na else st, "att": int(att or 0), "max": int(mx or 3), "lu": bool(lu), "where": where,
                      "why": why, "src": h}
            settled = {x: (c[0] in SETTLED or bool(c[3])) for x, c in cand.items()}
            if not merged and len(set(settled.values())) > 1:
                divergent.append({"obj": f"{k}:{sid}", "views": {x: cand[x][0] for x in sorted(cand)}, "used": h})
        eps.setdefault(ep, {"asm": False, "shots": {}})["shots"][sid] = out
    for h, p in probes.items():         # 视频：vidgen 状态（两台）补强
        for sid, v in ((p or {}).get("vstate") or {}).items():
            ep = ep_of(sid)
            rec = eps.get(ep, {}).get("shots", {}).get(sid)
            if not rec:
                continue
            st = {"done": "passed", "best_effort": "best_effort"}.get(v.get("status"))
            if st and RANK[st] > RANK.get(rec["video"]["st"], 0):
                rec["video"].update(st=st, src=f"vstate:{h}")
    return eps, divergent


def video_running(probes: dict) -> dict:
    """视频真在跑（vidgen state 里 submitted / rendering 且没 t_done）→ {shot: lane}"""
    out = {}
    for h, p in probes.items():
        for sid, v in ((p or {}).get("vstate") or {}).items():
            for var, lane, t_sub, t_done, st in v.get("renders") or []:
                if st in ("submitted", "rendering", "queued", "running") and not t_done and lane:
                    out[sid] = lane
    return out


def live_lanes(probes: dict, lanes: dict) -> dict:
    """每道现网状态：idle / busy（label、task、model）/ unknown（探不到）"""
    out = {}
    for ln, v in sorted(lanes.items()):
        p = probes.get(v["host"]) or {}
        q = (p.get("queues") or {}).get(ln)
        util = ((p.get("gpus") or {}).get(str(v["gpu"])) or {}).get("util")
        if q is None:
            out[ln] = {"state": "unknown", "util": util}
            continue
        items = q.get("running") or []
        if not items and not q.get("pending"):
            out[ln] = {"state": "idle", "util": util}
            continue
        it = items[0] if items else {}
        task, label = None, f"{it.get('agent')}:{it.get('obj') or it.get('job') or it.get('shot') or it.get('kind')}"
        obj = str(it.get("obj") or "")
        names = " ".join(it.get("models") or []).lower()
        if obj.split(":", 1)[0] in ("first", "last", "video"):
            task = obj
        elif "VIDEO" in str(it.get("agent") or "").upper() and it.get("job"):
            task = "video:" + str(it["job"]).split("|", 1)[0]
        model = "video" if (task or "").startswith("video:") or any(x in names for x in VIDEO_HINTS) else "image"
        out[ln] = {"state": "busy", "label": label[:60], "task": task, "model": model, "util": util}
    return out


def live_dispatches(probes: dict, t0: float, t1: float) -> list:
    """(t0, t1] 内现网真实派单：producer dispatch（出图）+ 视频提交（vidgen.log SUBMIT ∪ state renders，按 镜/版本/道 去重，
    VideoBridge 进程内 night 与独立 night 都落到同一 vidgen → 不重复计）"""
    out, seen = [], {}
    for h, p in sorted(probes.items()):
        for e in (p or {}).get("events") or []:
            t, ev, obj, lane = e[0], e[1], e[2], e[3]
            if ev == "dispatch" and t0 < t <= t1 and lane:
                out.append({"t": t, "lane": lane, "task": obj, "model": "image", "src": f"producer@{h}"})
        subs = [(e[0], e[2], e[3], e[4]) for e in (p or {}).get("vidgen") or [] if e[1] == "SUBMIT"]
        for sid, v in ((p or {}).get("vstate") or {}).items():
            for var, lane, t_sub, t_done, st in v.get("renders") or []:
                if t_sub:
                    subs.append((float(t_sub), sid, var, lane))
        for t, sid, var, lane in sorted(subs, key=lambda x: x[0]):
            if not lane or not (t0 < t <= t1):
                continue
            key = (sid, var, lane)
            if key in seen and abs(seen[key] - t) < 600:
                continue
            seen[key] = t
            out.append({"t": t, "lane": lane, "task": f"video:{sid}", "model": "video", "src": f"vidgen@{h}"})
    return sorted(out, key=lambda x: (x["t"], x["lane"]))


def recent_gates(probes: dict, now: float, window_s: float = 600) -> dict:
    """10 min 内被闸门拦下的对象（sop_gate / preflight / refs；why 里写“仍可派”的不算）→ {obj: ev}"""
    out = {}
    for p in probes.values():
        for e in (p or {}).get("events") or []:
            if e[1] in GATE_EVS and e[2] and now - e[0] <= window_s and "仍可派" not in str(e[6]):
                out[e[2]] = e[1]
    return out


# ------------------------------------------------------------------ 建图 / 阶段 / 工位
def apply_roles(board: C.Board, phase: str, roles_cfg: dict) -> None:
    """L-206/L-207：按 run 级阶段给道设角色（工位表 = lane_roles.json 唯一来源）"""
    if not roles_cfg.get("enabled"):
        for lane in board.gpu_lanes():
            board.set_lane_role(lane["id"], render_capacity=1, allow_models=None)
        return
    table = (roles_cfg.get("phases") or {}).get(phase) or {}
    vqa_by = ((roles_cfg.get("review") or {}).get("vqa_instances_by_phase") or {})
    for lane in board.gpu_lanes():
        lid = lane["id"]
        models = [m for m in ("image", "video") if lid in (table.get(m) or [])]
        review = lid in (table.get("review") or [])
        board.set_lane_role(lid, render_capacity=1 if models else 0, allow_models=models,
                            vqa_slots=int(vqa_by.get(phase, 3 if phase == "frames" else 1)) if review else 0)
        if review and not models and lane["loaded_model"] in ("none", "image"):
            lane["loaded_model"] = "vqa"


def run_phase(board: C.Board, ep: int | None) -> str:
    """一个 run 级阶段（L-207 + C2 兜底）：active 集首尾帧没定完 = frames；≥1 镜定下且没有就绪 / 在跑的首尾帧 = videos"""
    if ep is None:
        return "videos"
    board.refresh(0.0)
    fr = [t for t in board.tasks.values() if t["ep"] == ep and t["kind"] in ("first", "last")]
    if not fr or all(t["state"] in C.DONE for t in fr):
        return "videos"
    settled_shots = {t["shot"] for t in fr if t["kind"] == "last" and t["state"] in C.DONE}
    live = [t for t in fr if t["state"] in ("ready", "leased", "running", "scoring")]
    if settled_shots and not live:
        return "videos"
    return "frames"


def active_episode(eps: dict, adult: set) -> int | None:
    for ep in sorted(eps):
        E = eps[ep]
        if E.get("asm"):
            continue
        shots = [s for s in E["shots"] if s not in adult]
        if any(E["shots"][s]["video"]["st"] not in SETTLED for s in shots):
            return ep
    return None


def _occupy(board: C.Board, tid: str, lane_id: str, now: float) -> None:
    t, lane = board.tasks[tid], board.lanes[lane_id]
    t["state"], t["last_lane"] = "running", lane_id
    t["lease"] = {"lane": lane_id, "token": f"live:{tid}", "t0": now, "hb": now, "ttl": 1e9, "version": t["version"]}
    lane["busy"] = tid
    board.rev += 1


def build_board(eps: dict, adult: set, live: dict, vrun: dict, gates: dict, cfg: dict, roles_cfg: dict, now: float,
                lane_models: dict | None = None) -> tuple[C.Board, dict]:
    """活 DAG：未合成的集、非成人镜；终态照搬；在跑的按道占住；闸门 / 资产 = hold。返回 (board, info)"""
    cfg = json.loads(json.dumps(cfg))
    cfg["policies"]["lane_stale_s"] = 0
    b = C.Board(cfg)
    assert not any(x in b.lanes for x in C.BAD_LANES)
    info = {"eps": [], "adult_skipped": 0, "gate_holds": [], "asset_holds": [], "inflight_no_lane": []}
    for ep in sorted(eps):
        E = eps[ep]
        if E.get("asm"):
            continue
        info["eps"].append(ep)
        for sid in sorted(E["shots"], key=lambda s: int(s.rsplit("S", 1)[-1]) if s.rsplit("S", 1)[-1].isdigit() else 0):
            if sid in adult:
                info["adult_skipped"] += 1
                continue
            rec = E["shots"][sid]
            short = sid.split("-", 1)[-1]
            deps = []
            if rec["assets"]["st"] not in SETTLED:
                a = b.add_asset("scene", f"assets@{sid}", ep)
                b.hold(a["id"], "资产作业（asset_worker）未齐", now)
                deps.append(a["id"])
                info["asset_holds"].append(sid)
            b.add_shot(ep, short, deps)
            for k in ("first", "last", "video"):
                o, tid = rec[k], f"{k}:{sid}"
                t = b.tasks[tid]
                t["attempts"] = min(int(o["att"]), t["max_attempts"] - 1) if o["st"] not in SETTLED else int(o["att"])
                if o["st"] == "passed":
                    t["state"], t["t_done"] = "passed", now
                elif o["st"] in ("best_effort", "adopted") or (k == "last" and o["lu"]):
                    t["state"], t["t_done"] = "adopted", now
                elif k == "video" and sid in vrun:
                    pass                                   # 下面按道占住
                elif o["st"] == "running" and k != "video":
                    t["state"] = "scoring"                 # 登记表在跑但没占道 = 出完在打分（或等编排器）
                    b.score_queue.append(tid)
                    info["inflight_no_lane"].append(tid)
                if tid in gates and t["state"] not in C.DONE:
                    t["hold"] = f"gate:{gates[tid]}"
                    info["gate_holds"].append(tid)
        if any(t["ep"] == ep and t["kind"] == "video" for t in b.tasks.values()):
            b.add_assembly(ep)                         # 全成人的集没有可派镜 → 不建合成
    for ln, v in live.items():
        if ln not in b.lanes:
            continue
        lane = b.lanes[ln]
        lane["last_seen"] = now
        if lane_models and lane_models.get(ln):
            lane["loaded_model"] = lane_models[ln]
        if v["state"] == "unknown":
            lane["health"] = "down"
        elif v["state"] == "busy":
            lane["loaded_model"] = v.get("model") or lane["loaded_model"]
            tid = v.get("task")
            if tid in b.tasks and b.tasks[tid]["state"] not in C.DONE:
                if tid in b.score_queue:
                    b.score_queue.remove(tid)
                _occupy(b, tid, ln, now)
            else:
                lane["busy"] = f"ext:{v.get('label')}"
    for sid, ln in vrun.items():
        tid = f"video:{sid}"
        if tid in b.tasks and b.tasks[tid]["state"] not in C.DONE and b.tasks[tid]["state"] != "running" and ln in b.lanes:
            if b.lanes[ln]["busy"] is None:
                _occupy(b, tid, ln, now)
            else:
                b.tasks[tid]["state"] = "running"          # 已提交在排队（道被别的活占着）
    b.refresh(now)
    info["inflight_no_lane"] = sorted(tid for tid, t in b.tasks.items() if t["state"] == "scoring")
    ep = active_episode(eps, adult)
    phase = run_phase(b, ep)
    apply_roles(b, phase, roles_cfg)
    info.update(active_ep=ep, phase=phase)
    return b, info


def decide(board: C.Board, now: float) -> list:
    """问工作板：现在空着的道各派什么（不落租约）"""
    out = []
    for lid, tid, score in board.plan(now):
        assert lid not in C.BAD_LANES
        if lid.startswith("cpu"):
            continue                                   # 合成在 CPU，不算卡位决策
        t, lane = board.tasks[tid], board.lanes[lid]
        out.append({"lane": lid, "task": tid, "kind": t["kind"], "ep": t["ep"], "score": score,
                    "switch": lane["loaded_model"] not in ("none", t["model"]) and t["model"] != "cpu",
                    "from_model": lane["loaded_model"], "est_s": round(board.est(t["kind"], lid, t))})
    return out


# ------------------------------------------------------------------ 差异归因
def _host_phase(p: dict | None, ep: int | None) -> str | None:
    lrs = (p or {}).get("lrs") or {}
    if ep is None:
        return None
    return (lrs.get(str(ep)) or {}).get("phase")


def live_phase_split(probes: dict, ep: int | None, shadow_phase: str) -> dict:
    """两台各自的 L-207 阶段（M4）与影子 run 级阶段对比"""
    by = {h: {"active": ((p or {}).get("lrs") or {}).get("_active", {}).get("ep"),
              "active_phase": ((p or {}).get("lrs") or {}).get("_active", {}).get("phase"),
              "ep_phase": _host_phase(p, ep)} for h, p in probes.items()}
    phases = {v["ep_phase"] for v in by.values() if v["ep_phase"]}
    actives = {(v["active"], v["active_phase"]) for v in by.values() if v["active"] is not None}
    return {"hosts": by, "shadow": {"ep": ep, "phase": shadow_phase},
            "split": len(phases) > 1 or len(actives) > 1, "differs_from_shadow": any(x != shadow_phase for x in phases)}


def _partition_owner(probes: dict, ep: int, which: str, copy: str = "config/netfix/partition.json") -> str | None:
    for p in probes.values():
        part = ((p or {}).get("partition") or {}).get(copy) or {}
        for h, eps in (part.get(which) or {}).items():
            if ep in (eps or []):
                return h
    return None


def _active_holds(probes: dict, lane: str) -> list:
    out = []
    for h, p in probes.items():
        for copy, part in ((p or {}).get("partition") or {}).items():
            hd = ((part or {}).get("temp_holds") or {}).get(lane)
            if hd and hd.get("active"):
                out.append(f"{h}:{copy.split('/')[0]}:{hd.get('by')}")
    return out


def classify_idle(lane: str, dec: dict, probes: dict, phase_info: dict, now: float, roles_cfg: dict) -> tuple[str, str, str]:
    """现网空着、影子要派 dec → (类别, 机制, 证据)。按 ARCH_MAP §2.3 机制顺序找第一个能解释的"""
    host = lane.split(":", 1)[0]
    tid, kind = dec["task"], dec["kind"]
    sid, ep = shot_of(tid), dec["ep"]
    p = probes.get(host) or {}
    model = model_of_kind(kind)
    if model == "image":
        if p.get("ctrl", {}).get("paused"):
            return "live_paused", "M11", f"{host} producer control.paused"
        owners = _owner_hosts(probes, sid)
        if not owners:
            return "not_in_control_only", "M1", f"{sid} 不在任何一台 control.only（dispatch 按镜就绪 / 资产闸没放行；影子看它可派）"
        if host not in owners:
            return "partition", "M1", f"{sid} 归 {owners[0]}（control.only），{host} 的 producer 不派它；{owners[0]} 的 hold_lanes 含 {lane}"
        if lane in (p.get("ctrl") or {}).get("hold_lanes", []):
            return "partition", "M1", f"{host} control.hold_lanes 含 {lane}"
    else:
        vown = _partition_owner(probes, ep, "video", "data/state/netfix/partition.json")
        if vown and vown != host:
            return "partition", "M1", f"ep{ep:02d} 视频归 {vown}（partition.video），{host} 的 night 不派"
    holds = _active_holds(probes, lane)
    if holds:
        return "asset_hold", "M12", ",".join(holds)
    hp = _host_phase(p, ep)
    if hp and hp != phase_info["shadow"]["phase"]:
        return "live_phase_split", "M4", f"{host} 认为 ep{ep:02d} 在 {hp}，影子 run 级 = {phase_info['shadow']['phase']}"
    if hp:
        table = ((roles_cfg.get("phases") or {}).get(hp) or {})
        if lane not in (table.get(model) or []):
            return "live_lane_roles", "M3", f"{host} 阶段 {hp} 的工位表不让 {lane} 做 {model}"
    for e in reversed(p.get("events") or []):
        if e[2] == tid and now - e[0] <= 900:
            if e[1] in GATE_EVS:
                return "live_gate", "M11", f"{e[1]} {str(e[6])[:60]}"
            if e[1] == "lane_roles_wait":
                return "live_lane_roles", "M3", "lane_roles_wait 等空闲出图位"
            if e[1] in ("rescore_dispatch", "rescore_cap", "score_infra", "review_fallback", "rescore"):
                return "live_waiting_rescore", "M11", f"{e[1]}：现网在给旧版重打分 / 打分退避，不出新版"
            if e[1] in ("content_error", "infra_error", "score_timeout"):
                return "live_error_backoff", "M11", f"{e[1]} {str(e[6])[:60]}"
    if model == "video":
        nc = p.get("nctrl") or {}
        if lane not in (nc.get("video_lanes") or []) and nc.get("yield_s"):
            return "video_yield", "M5", f"{lane} 不是专用视频道（night video_lanes={nc.get('video_lanes')}，yield {nc.get('yield_s')} s）"
        return "video_not_queued", "M6", "视频镜首尾帧已定、night 没提交（编排器节拍 / 编译 / 门槛）"
    if p.get("hb_age_s") is not None and p["hb_age_s"] > 120:
        return "producer_stale", "M11", f"{host} producer 心跳 {p['hb_age_s']} s"
    return "unexplained", "?", ""


def classify_window(prev: dict, live_ds: list, tasks_prev: dict, now: float) -> list:
    """上一拍影子决策 vs 两拍之间现网真实派单 → 每道一行"""
    rows = []
    by_lane: dict = {}
    for d in live_ds:
        by_lane.setdefault(d["lane"], []).append(d)
    live_tasks = {d["task"]: d["lane"] for d in live_ds}
    decs = {d["lane"]: d for d in prev.get("decisions") or []}
    idle_prev = {ln for ln, v in (prev.get("lanes") or {}).items() if v.get("state") == "idle"}
    for ln in sorted(set(decs) | set(by_lane)):
        X = decs.get(ln)
        Y = (by_lane.get(ln) or [None])[0]
        row = {"lane": ln, "shadow": X and X["task"], "live": Y and Y["task"], "live_src": Y and Y["src"]}
        if X and Y:
            yep = ep_of(shot_of(Y["task"]))
            if X["task"] == Y["task"]:
                cat, mech, why = "agree", "", ""
            elif prev.get("eps") and yep not in prev["eps"]:
                cat, mech, why = "live_work_on_closed_ep", "STATE", f"现网把道给了 ep{yep:02d}（已合成 / 无可派镜）的 {Y['task']}"
            elif X["task"] in live_tasks:
                cat, mech, why = "same_task_other_lane", "SCHED", f"现网派到 {live_tasks[X['task']]}"
            elif X["kind"] == "video" and kind_of(Y["task"]) != "video":
                cat, mech, why = "shadow_video_priority", "SCHED", "影子先给视频（已定镜的视频秩高 / 视频道亲和）"
            elif X["kind"] != "video" and kind_of(Y["task"]) == "video":
                cat, mech, why = "shadow_frames_first", "SCHED", "影子先补首尾帧（关键路径更长）"
            elif X["ep"] != ep_of(shot_of(Y["task"])):
                cat, mech, why = "episode_order", "SCHED", "L-207 strict：早的集先"
            else:
                cat, mech, why = "rank_order", "SCHED", "同集同类，HEFT 秩不同"
        elif X and not Y:
            ic = (prev.get("instant") or {}).get(ln) or {}
            cat, mech, why = "live_left_idle:" + str(ic.get("cat") or "unexplained"), ic.get("mech") or "?", ic.get("why") or ""
            if X["task"] in live_tasks:
                cat, mech, why = "same_task_other_lane", "SCHED", f"现网派到 {live_tasks[X['task']]}，这道空着"
        elif Y and not X:
            st = tasks_prev.get(Y["task"])
            if ln not in idle_prev:
                cat, mech, why = "lane_freed_midwindow", "", "上一拍这道还忙"
            elif st is None and ep_of(shot_of(Y["task"])) not in (prev.get("eps") or []):
                cat, mech, why = "live_work_on_closed_ep", "STATE", f"ep{ep_of(shot_of(Y['task'])):02d} 已合成 / 没有可派镜，现网还在出"
            elif st is None:
                cat, mech, why = "live_task_not_in_dag", "STATE", "影子图里没有（成人镜 / 不在登记表）"
            elif st in ("P", "A"):
                cat, mech, why = "live_redo_settled", "STATE", "影子看它已定下（两台登记表不一致 / 孤儿）"
            elif st == "H":
                cat, mech, why = "live_ignores_gate", "M11", "影子按闸门 hold 着"
            elif st == "X":
                cat, mech, why = "live_ahead_of_deps", "SCHED", "影子看上游没定（预取 / 换代中）"
            else:
                cat, mech, why = "live_breaks_role_or_gate", "M3", f"影子 {st}：该道角色 / 阶段闸不许"
        else:
            continue
        row.update(cat=cat, mech=mech, why=why)
        rows.append(row)
    return rows


def task_codes(board: C.Board) -> dict:
    code = {"passed": "P", "adopted": "A", "ready": "R", "running": "G", "leased": "G", "scoring": "S", "blocked": "X",
            "best_effort": "B", "failed": "F"}
    return {tid: ("H" if t["hold"] and t["state"] == "blocked" else code.get(t["state"], "?")) for tid, t in sorted(board.tasks.items())
            if t["kind"] in ("first", "last", "video")}


# ------------------------------------------------------------------ 回看（log 重建每道忙闲）
def retro(probes: dict, lanes: list, t0: float, t1: float, live: dict) -> dict:
    """窗口 [t0, t1] 每道忙区间（出图 dispatch→rendered/报错；视频 SUBMIT→DONE）→ 空道分钟、换模型次数。
    看不到的：笔记本 asset_worker 直接打到 ComfyUI 的资产作业（只在本拍队列里看得到）→ 空闲偏高"""
    segs = {ln: [] for ln in lanes}
    for h, p in probes.items():
        ev = (p or {}).get("events") or []
        for i, e in enumerate(ev):
            if e[1] != "dispatch" or e[3] not in segs:
                continue
            end = None
            for f in ev[i + 1:]:
                if f[2] == e[2] and f[1] in END_EVS:
                    end = f[0] if f[1] not in ("preflight_block",) else e[0]
                    break
                if f[1] == "dispatch" and f[3] == e[3]:
                    end = f[0]
                    break
            if end is None:
                end = t1 if (live.get(e[3]) or {}).get("task") == e[2] else min(t1, e[0] + 330)
            segs[e[3]].append((e[0], end, "image"))
        vg = (p or {}).get("vidgen") or []
        done = {(e[2], e[3]): e[0] for e in vg if e[1] == "DONE"}
        for e in vg:
            if e[1] == "SUBMIT" and e[4] in segs:
                end = done.get((e[2], e[3]))
                if end is None or end < e[0]:
                    end = t1 if (live.get(e[4]) or {}).get("task") == f"video:{e[2]}" else min(t1, e[0] + 420)
                segs[e[4]].append((e[0], end, "video"))
    out = {}
    for ln, ss in segs.items():
        ss = sorted((max(a, t0), min(b, t1), m) for a, b, m in ss if b > t0 and a < t1)
        busy, cur = 0.0, None
        for a, b, m in ss:
            if cur is None or a > cur[1]:
                if cur:
                    busy += cur[1] - cur[0]
                cur = [a, b]
            else:
                cur[1] = max(cur[1], b)
        if cur:
            busy += cur[1] - cur[0]
        models = [m for _, _, m in ss]
        sw = sum(1 for i in range(1, len(models)) if models[i] != models[i - 1])
        out[ln] = {"busy_min": round(busy / 60, 1), "idle_min": round(max(0.0, t1 - t0 - busy) / 60, 1), "jobs": len(ss),
                   "switches": sw, "models": "".join(m[0] for m in models)[-30:]}
    return out


def measured_from(probes: dict) -> dict:
    """窗口实测 → 模拟器参数（样本不够就用 sim.MEASURED）"""
    m = json.loads(json.dumps(SIM.MEASURED))
    g = {"gpu33": [], "gpu36": []}
    cnt = {"first": [0, 0], "last": [0, 0]}
    vd = {"gpu33": [], "gpu36": []}
    vs = [0, 0]
    for p in probes.values():
        for e in (p or {}).get("events") or []:
            k = kind_of(e[2])
            if e[1] == "rendered" and e[5] and str(e[3])[:5] in g:
                g[str(e[3])[:5]].append(float(e[5]))
                if k in cnt:
                    cnt[k][0] += 1
            if e[1] in ("content_fail", "redo_fail") and k in cnt:
                cnt[k][1] += 1
        for e in (p or {}).get("vidgen") or []:
            if e[1] == "DONE" and e[5] and str(e[4])[:5] in vd and e[5] > 60:
                vd[str(e[4])[:5]].append(float(e[5]))
            if e[1] == "SCORE":
                vs[0] += 1
                vs[1] += 1 if str(e[5]).upper() == "PASS" else 0
    for h in g:
        if len(g[h]) >= 3:
            m["frame_gpu_s"][h] = round(statistics.median(g[h]))
        if len(vd[h]) >= 3:
            m["video_gpu_s"][h] = round(statistics.median(vd[h]))
    for k, (n, f) in cnt.items():
        if n >= 5:
            m["frame_pass_p"][k] = round(min(0.95, max(0.05, 1 - f / n)), 2)
    if vs[0] >= 5:
        m["video_pass_p"] = round(min(0.95, max(0.05, vs[1] / vs[0])), 2)
    m["samples"] = {"frame": {h: len(v) for h, v in g.items()}, "video": {h: len(v) for h, v in vd.items()}, "video_scores": vs[0],
                    "frame_rendered": {k: v[0] for k, v in cnt.items()}}
    return m


# ------------------------------------------------------------------ 预测（模拟器续跑：影子策略）
class Projection(SIM.Sim):
    """从当前活 DAG 续跑（影子策略 = 工作板拉式派单 + run 级阶段工位），到 active 集合成完成"""

    def __init__(self, board: C.Board, m: dict, ep: int, roles_cfg: dict, seed: int = 1106):  # noqa: D401  (不调父类：不新建 ep01)
        self.scn, self.m, self.rng = "shadow", m, random.Random(seed)
        self.board = C.Board.from_dict(json.loads(json.dumps(board.to_dict())), json.loads(json.dumps(board.cfg)))
        self.legacy, self.turbo = False, False
        self.ep, self.roles_cfg = ep, roles_cfg
        self.phase = None
        self.night_block_until = 0.0
        self.events: list = []
        self.seq = 0
        self.lane_log = {lid: [] for lid in SIM.GPU_LANES}

    def _switch_phase_if_needed(self, now: float) -> None:
        ph = run_phase(self.board, self.ep)
        if ph != self.phase:
            self.phase = ph
            apply_roles(self.board, ph, self.roles_cfg)

    def project(self, t0: float, horizon_s: float = 8 * 3600) -> float | None:
        b = self.board
        for t in sorted(b.tasks.values(), key=lambda x: x["id"]):
            le = t["lease"]
            if t["state"] == "running" and le:
                rem = max(30.0, b.est(t["kind"], le["lane"], t) - (t0 - le["t0"]))
                self._push(t0 + rem, "done", {"token": le["token"], "secs": rem, "kind": t["kind"]})
            elif t["state"] == "running":
                t["state"] = "blocked"                      # 已提交在别的道排队：按重新派处理（保守）
        for lane in b.lanes.values():
            if isinstance(lane["busy"], str) and lane["busy"].startswith("ext:"):
                self._push(t0 + 300, "free", {"lane": lane["id"]})
        for t in b.tasks.values():                      # 闸门 hold 视为本拍暂时的；资产缺口按 10 min 补齐（乐观，报告里注明）
            if str(t["hold"] or "").startswith("gate:"):
                t["hold"] = None
            elif t["kind"] in ("face", "sheet", "scene") and t["state"] not in C.DONE:
                self._push(t0 + 600, "asset", {"task": t["id"]})
        self._push(t0, "tick")
        now = t0
        while self.events:
            now, _, kind, p = SIM.heapq.heappop(self.events)
            if now > t0 + horizon_s:
                return None
            if kind == "tick":
                self._dispatch(now)
            elif kind == "done":
                self._on_done(now, p)
            elif kind == "scored":
                self._on_scored(now, p)
            elif kind == "free":
                b.lanes[p["lane"]]["busy"] = None
                self._push(now, "tick")
            elif kind == "asset":
                b.tasks[p["task"]].update(state="passed", hold=None, t_done=now)
                b.rev += 1
                self._push(now, "tick")
            asm = b.tasks.get(C.task_id("assembly", self.ep))
            if asm and asm["state"] in C.DONE:
                return now - t0
        return None


def projection(board: C.Board, info: dict, probes: dict, roles_cfg: dict, now: float, seeds: int = 3) -> dict:
    ep = info.get("active_ep")
    if ep is None:
        return {"ep": None}
    m = measured_from(probes)
    rems = [Projection(board, m, ep, roles_cfg, seed=1106 + i).project(now) for i in range(seeds)]
    ok = [r for r in rems if r is not None]
    starts = [float(v) for p in probes.values() for k, v in ((p or {}).get("first_dispatch") or {}).items() if str(k) == str(ep)]
    t_start = min(starts) if starts else None
    elapsed = (now - t_start) / 60 if t_start else None
    shots = [t for t in board.tasks.values() if t["ep"] == ep and t["kind"] == "video"]
    vdone = sum(1 for t in shots if t["state"] in C.DONE)
    fresh = None
    try:
        mf = dict(m, shots=[f"S{i}" for i in range(1, len(shots) + 1)])
        rs = [SIM.Sim("c_affinity", mf, seed=1106 + i).run() for i in range(seeds)]
        fresh = round(sum(r["total_min"] for r in rs) / len(rs), 1)
    except (KeyError, ValueError, ZeroDivisionError):   # arch-ok: 冷启动对照算不出只在报告里标空，不影响影子决策
        fresh = None
    rem = round(sum(ok) / len(ok) / 60, 1) if ok else None
    return {"ep": ep, "start": jst(t_start) if t_start else None, "elapsed_min": round(elapsed, 1) if elapsed is not None else None,
            "shadow_remaining_min": rem, "projected_total_min": round(elapsed + rem, 1) if (elapsed is not None and rem is not None) else None,
            "live_linear_eta_min": round(elapsed / (vdone / len(shots)) - elapsed, 1) if (elapsed and shots and vdone) else None,
            "videos_done": f"{vdone}/{len(shots)}", "fresh_episode_shadow_min": fresh, "kpi_min": 50,
            "params": {k: m[k] for k in ("frame_gpu_s", "video_gpu_s", "frame_pass_p", "video_pass_p", "samples")},
            "unfinished_seeds": seeds - len(ok)}


# ------------------------------------------------------------------ 一拍
def tick(env: Env, every_s: float = 60, lookback_min: float = 60, seeds: int = 3, write: bool = True) -> dict:
    root = env.root
    out_dir = root / OUT_REL
    now = env.now()
    run = env.run()
    cfg, roles_cfg = env.sched_cfg(), env.roles_cfg()
    lanes = {ln: v for ln, v in env.lanes().items() if ln not in C.BAD_LANES and ln in cfg["lanes"]}
    prev = None
    dpath = out_dir / "decisions.jsonl"
    if dpath.exists():
        try:
            prev = json.loads(dpath.read_text(encoding="utf-8").splitlines()[-1])
        except (ValueError, IndexError):   # arch-ok: 上一拍坏行 = 当没有上一拍（本拍只出瞬时对比）
            prev = None
    since = now - lookback_min * 60
    if prev and prev.get("t"):
        since = min(since, float(prev["t"]))
    probes = {h: env.probe(h, run, since, lanes) for h in SERVERS}
    adult = set(env.adult_ids(run))
    for p in probes.values():
        adult |= set((p or {}).get("adult_wait") or [])
    mfn = getattr(env, "merged_registry", None)      # L-209 S2.5（测试 Fake 没有 = 旧口径）
    eps, divergent = merge_registry(probes, mfn(run) if mfn else None)
    live = live_lanes(probes, lanes)
    vrun = video_running(probes)
    gates = recent_gates(probes, now)
    lane_models = (prev or {}).get("lane_models") or {}
    board, info = build_board(eps, adult, live, vrun, gates, cfg, roles_cfg, now, lane_models)
    decisions = decide(board, now)
    phase_info = live_phase_split(probes, info["active_ep"], info["phase"])
    instant = {}
    decs = {d["lane"]: d for d in decisions}
    for ln, v in live.items():
        if v["state"] == "idle" and ln in decs:
            cat, mech, why = classify_idle(ln, decs[ln], probes, phase_info, now, roles_cfg)
            instant[ln] = {"cat": cat, "mech": mech, "why": why}
        elif v["state"] == "busy":
            lane = board.lanes.get(ln) or {}
            am = lane.get("allow_models")
            if v.get("task") and v["task"] not in board.tasks:
                e_ = ep_of(shot_of(v["task"]))
                closed = e_ not in info["eps"]
                instant[ln] = {"cat": "live_work_on_closed_ep" if closed else "live_task_not_in_dag", "mech": "STATE",
                               "why": f"现网在跑 {v.get('label')}：" + (f"ep{e_:02d} 已合成 / 没有可派镜" if closed else "成人镜 / 不在登记表")}
            elif am is not None and v.get("model") not in am:
                instant[ln] = {"cat": "live_role_violation", "mech": "M3/M4",
                               "why": f"影子 run 级阶段 {info['phase']} 下 {ln} 只许 {am or '审图'}，现网在跑 {v.get('label')}"}
    ready = {}
    for t in board.ready_tasks(now):
        ready[t["kind"]] = ready.get(t["kind"], 0) + 1
    video_capable = [ln for ln, l_ in board.lanes.items() if ln in lanes and l_["render_capacity"] > 0
                     and (l_["allow_models"] is None or "video" in l_["allow_models"])]
    live_idle = [ln for ln, v in live.items() if v["state"] == "idle"]
    shadow_idle = [ln for ln in live_idle if ln not in decs]
    lane_models_now = {ln: (v.get("model") if v["state"] == "busy" else lane_models.get(ln)) for ln, v in live.items()}
    row = {"t": round(now, 1), "at": jst(now, "%Y-%m-%d %H:%M:%S+09:00"), "run": run, "active_ep": info["active_ep"],
           "phase": info["phase"], "eps": info["eps"],
           "lanes": {ln: {k: v.get(k) for k in ("state", "label", "task", "model", "util") if v.get(k) is not None} for ln, v in live.items()},
           "lane_roles": {ln: {"allow": l_["allow_models"], "render": l_["render_capacity"], "vqa": l_["vqa_slots"],
                               "model": l_["loaded_model"]} for ln, l_ in sorted(board.lanes.items()) if ln in lanes},
           "ready": ready, "decisions": decisions, "instant": instant, "shadow_idle": shadow_idle,
           "video_capable": video_capable, "live_phase": phase_info, "divergent_n": len(divergent),
           "adult_excluded": info["adult_skipped"], "gate_holds": info["gate_holds"][:20], "asset_holds": info["asset_holds"][:20],
           "inflight_no_lane": info["inflight_no_lane"][:20], "probe_errors": [h for h in SERVERS if probes.get(h) is None],
           "tasks": task_codes(board), "lane_models": lane_models_now, "eta": board.eta(now, info["active_ep"]) if info["active_ep"] else None}
    # ---- 窗口对比（上一拍决策 vs 两拍之间现网真实派单）
    win_rows, dt = [], 0.0
    if prev and prev.get("t") and now - float(prev["t"]) <= max(3 * every_s, 300):
        dt = now - float(prev["t"])
        win_rows = classify_window(prev, live_dispatches(probes, float(prev["t"]), now), prev.get("tasks") or {}, now)
    # ---- 累计指标
    mpath = out_dir / "metrics.json"
    M = _j(mpath, None) or {"since": row["at"], "ticks": 0, "minutes": 0.0, "live_idle_lane_min": 0.0, "shadow_idle_lane_min": 0.0,
                            "live_idle_with_work_lane_min": 0.0, "live_switches": 0, "shadow_switches": 0,
                            "live_video_starve_min": 0.0, "shadow_video_starve_min": 0.0, "cats": {}, "instant_cats": {},
                            "phase_split_ticks": 0, "decisions": 0, "diff_rows": 0}
    if prev and dt:
        pl = prev.get("lanes") or {}
        p_idle = [ln for ln, v in pl.items() if v.get("state") == "idle"]
        p_dec = {d["lane"] for d in prev.get("decisions") or []}
        M["minutes"] += dt / 60
        M["live_idle_lane_min"] += dt / 60 * len(p_idle)
        M["shadow_idle_lane_min"] += dt / 60 * len([x for x in p_idle if x not in p_dec])
        M["live_idle_with_work_lane_min"] += dt / 60 * len([x for x in p_idle if x in p_dec])
        M["shadow_switches"] += sum(1 for d in prev.get("decisions") or [] if d.get("switch"))
        pm = dict(prev.get("lane_models") or {})
        for d in live_dispatches(probes, float(prev["t"]), now):
            if pm.get(d["lane"]) and pm[d["lane"]] != d["model"]:
                M["live_switches"] += 1
            pm[d["lane"]] = d["model"]
        rv = (prev.get("ready") or {}).get("video", 0)
        vcap_idle = [x for x in p_idle if x in (prev.get("video_capable") or [])]
        if rv and vcap_idle:
            M["live_video_starve_min"] += dt / 60
            if rv > sum(1 for d in prev.get("decisions") or [] if d["kind"] == "video") and \
                    any(x not in p_dec for x in vcap_idle):
                M["shadow_video_starve_min"] += dt / 60
        for r in win_rows:
            M["cats"][r["cat"]] = M["cats"].get(r["cat"], 0) + 1
    M["ticks"] += 1
    M["decisions"] += len(decisions)
    M["phase_split_ticks"] += 1 if phase_info["split"] else 0
    for v in instant.values():
        M["instant_cats"][v["cat"]] = M["instant_cats"].get(v["cat"], 0) + 1
    M["diff_rows"] += len(win_rows) + len(instant)
    win = retro(probes, sorted(lanes), now - lookback_min * 60, now, live)
    proj = projection(board, info, probes, roles_cfg, now, seeds=seeds)
    parts = partition_view(probes)
    if write:
        _append(dpath, row)
        for ln, v in sorted(instant.items()):
            _append(out_dir / "diff.jsonl", {"t": row["t"], "at": row["at"], "mode": "instant", "lane": ln,
                                             "shadow": (decs.get(ln) or {}).get("task"), "live": live[ln].get("label") or "idle", **v})
        for r in win_rows:
            _append(out_dir / "diff.jsonl", {"t": row["t"], "at": row["at"], "mode": "window",
                                             "window_s": round(dt), **r})
        M["updated"] = row["at"]
        _jw(mpath, M)
        _jw(out_dir / "last.json", {"row": row, "retro": win, "projection": proj, "partition": parts,
                                    "divergent": divergent[:40], "lookback_min": lookback_min})
        _write_text(root / REPORT_REL, report_md(row, M, win, proj, parts, divergent, lookback_min, win_rows))
    return {"row": row, "metrics": M, "retro": win, "projection": proj, "partition": parts, "divergent": divergent, "window": win_rows}


def partition_view(probes: dict) -> dict:
    """两份 partition 在两台上的差异 + 生效中的临时 hold（谁读哪份见 PARTITION_READERS）"""
    out = {}
    for h, p in probes.items():
        parts = (p or {}).get("partition") or {}
        a, b = parts.get("config/netfix/partition.json") or {}, parts.get("data/state/netfix/partition.json") or {}
        diff = [k for k in ("images", "video", "retired", "lent", "work_stealing") if a.get(k) != b.get(k)]
        ha = {k: v for k, v in (a.get("temp_holds") or {}).items() if v.get("active")}
        hb = {k: v for k, v in (b.get("temp_holds") or {}).items() if v.get("active")}
        out[h] = {"md5": {"config": a.get("md5"), "state": b.get("md5")}, "fields_differ": diff,
                  "active_holds": {"config": sorted(ha), "state": sorted(hb)},
                  "holds_only_in": {"config": sorted(set(ha) - set(hb)), "state": sorted(set(hb) - set(ha))},
                  "retired": {"config": a.get("retired"), "state": b.get("retired")}}
    return out


# ------------------------------------------------------------------ 报告
def report_md(row: dict, M: dict, win: dict, proj: dict, parts: dict, divergent: list, lookback_min: float, win_rows: list) -> str:
    L = [f"# SHADOW_REPORT（L-209 S1 影子调度，自动生成，勿手改）", "",
         f"最近一拍 {row['at']} · run {row['run']} · run 级 active ep{row['active_ep']:02d} 阶段 **{row['phase']}**" if row.get("active_ep") else f"最近一拍 {row['at']}（没有未完成的集）",
         f"累计 {M['ticks']} 拍 / {M['minutes']:.1f} min（自 {M['since']}）· 探针失败 {row['probe_errors'] or '无'}"
         f" · 成人镜不进图 {row['adult_excluded']} · 两台登记表不一致对象 {row['divergent_n']}", "",
         "## 1. 累计（逐拍：现网 vs 影子）", "",
         "| 指标 | 现网 | 影子 |", "|---|---|---|",
         f"| 空道分钟（道·分钟） | {M['live_idle_lane_min']:.1f} | {M['shadow_idle_lane_min']:.1f} |",
         f"| 其中“空着但影子有活派” | {M['live_idle_with_work_lane_min']:.1f} | 0 |",
         f"| 换模型次数 | {M['live_switches']} | {M['shadow_switches']} |",
         f"| 视频饿死分钟（有就绪视频且能做视频的道空着） | {M['live_video_starve_min']:.1f} | {M['shadow_video_starve_min']:.1f} |",
         f"| 两台 L-207 阶段不一致的拍数（M4） | {M['phase_split_ticks']} | 0（一个 run 级阶段） |", "",
         "差异类别（窗口：上一拍影子决策 vs 两拍间现网真实派单）：" + (", ".join(f"{k} {v}" for k, v in sorted(M["cats"].items(), key=lambda x: -x[1])) or "（还没有窗口，需 ≥2 拍）"),
         "", "瞬时类别（现网空着、影子要派 → 现网为什么空着）：" + (", ".join(f"{k} {v}" for k, v in sorted(M["instant_cats"].items(), key=lambda x: -x[1])) or "无"), "",
         "## 2. 本拍：每道", "", "| 道 | 现网 | 影子角色（run 级阶段） | 影子决策 | 差异类别 / 机制 | 证据 |", "|---|---|---|---|---|---|"]
    decs = {d["lane"]: d for d in row["decisions"]}
    for ln, v in sorted(row["lanes"].items()):
        lr = row["lane_roles"].get(ln, {})
        role = ("/".join(lr.get("allow") or []) or "—") + (f" +审图×{lr['vqa']}" if lr.get("vqa") else "")
        d = decs.get(ln)
        ins = row["instant"].get(ln) or {}
        L.append(f"| {ln} | {v.get('state')} {v.get('label') or ''} | {role} | "
                 f"{(d['task'] + (' (换模型)' if d['switch'] else '')) if d else '—'} | {ins.get('cat', '')} {('/ ' + ins['mech'] + ' ' + MECH.get(ins['mech'], '')) if ins.get('mech') else ''} | {ins.get('why', '')} |")
    L += ["", f"就绪任务 {row['ready']} · 闸门 hold {len(row['gate_holds'])} · 资产 hold {len(row['asset_holds'])} · 登记表在跑但不占道 {len(row['inflight_no_lane'])}"]
    ph = row["live_phase"]
    L += ["", "## 3. L-207 阶段：两台各算 vs 影子一个 run 级（M4）", "",
          "| 来源 | _active | active 阶段 | 本集（ep%s）阶段 |" % row.get("active_ep"), "|---|---|---|---|"]
    for h, v in sorted(ph["hosts"].items()):
        L.append(f"| {h} lane_roles_state | ep{v['active']} | {v['active_phase']} | {v['ep_phase']} |")
    L.append(f"| 影子 | ep{row['active_ep']} | {row['phase']} | {row['phase']} |")
    L.append("")
    L.append(("🔴 两台不一致" if ph["split"] else "🟢 两台一致") + ("；与影子不同" if ph["differs_from_shadow"] else ""))
    L += ["", f"## 4. 窗口回看（最近 {lookback_min:.0f} min，log 重建；资产作业不在 log 里 → 空闲偏高）", "",
          "| 道 | 忙 min | 空 min | 作业数 | 换模型 | 序列（i=出图 v=视频） |", "|---|---|---|---|---|---|"]
    tot_idle = 0.0
    for ln, v in sorted(win.items()):
        tot_idle += v["idle_min"]
        L.append(f"| {ln} | {v['busy_min']} | {v['idle_min']} | {v['jobs']} | {v['switches']} | {v['models']} |")
    L.append(f"| 合计 | | {tot_idle:.1f} | | {sum(v['switches'] for v in win.values())} | 空闲率 {100 * tot_idle / max(1e-9, lookback_min * len(win)):.0f}% |")
    L += ["", "## 5. 本集用时预测（模拟器续跑影子策略，KPI ≤ 50 min）", ""]
    if proj.get("ep"):
        L += [f"- ep{proj['ep']:02d}：KPI 起点 {proj['start']}，已用 **{proj['elapsed_min']} min**；影子续跑还需 **{proj['shadow_remaining_min']} min** → 预测总 {proj['projected_total_min']} min"
              f"（现网线性外推还需 {proj['live_linear_eta_min']} min；视频已定 {proj['videos_done']}；未收敛种子 {proj['unfinished_seeds']}）",
              f"- 同参数冷启动一集（影子策略、{proj['videos_done'].split('/')[-1]} 镜）：{proj['fresh_episode_shadow_min']} min（KPI 50）",
              f"- 参数（窗口实测，样本不足用 sim.MEASURED）：{json.dumps(proj['params'], ensure_ascii=False)}"]
    L += ["", "## 6. 两份 partition.json（ARCH_MAP_20261106 §3）", "", "| 执行者 | 读哪份 | 位置 |", "|---|---|---|"]
    for who, copy, where in PARTITION_READERS:
        L.append(f"| {who} | {copy} | {where} |")
    L += ["", "| 台 | md5 config / state | 字段不同 | 生效临时 hold config / state | 只在一份里的 hold |", "|---|---|---|---|---|"]
    for h, v in sorted(parts.items()):
        L.append(f"| {h} | {v['md5']['config']} / {v['md5']['state']} | {v['fields_differ'] or '—'} | {v['active_holds']['config']} / {v['active_holds']['state']} | {v['holds_only_in']} |")
    L += ["", f"## 7. 两台登记表不一致（前 12 / 共 {len(divergent)}；影子用的那台标在 used）", ""]
    for d in divergent[:12]:
        L.append(f"- {d['obj']}: {d['views']} → used {d['used']}")
    if win_rows:
        L += ["", "## 8. 上一窗口逐道差异", ""]
        for r in win_rows:
            L.append(f"- {r['lane']}: 影子 {r['shadow']} / 现网 {r['live']} → {r['cat']} {r.get('mech') or ''} {r.get('why') or ''}")
    L += ["", "机制编号见 docs/master/ARCH_MAP_20261106.md §2.3：" + "；".join(f"{k}={v}" for k, v in MECH.items()), ""]
    return "\n".join(L)


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="L-209 S1 影子调度（只读、不派单）")
    ap.add_argument("cmd", choices=["once", "run", "report"])
    ap.add_argument("--every", type=float, default=60)
    ap.add_argument("--minutes", type=float, default=60)
    ap.add_argument("--lookback-min", type=float, default=60)
    ap.add_argument("--seeds", type=int, default=3)
    a = ap.parse_args(argv)
    env = Env()
    if a.cmd == "report":
        last = _j(ROOT / OUT_REL / "last.json", {}) or {}
        M = _j(ROOT / OUT_REL / "metrics.json", {}) or {}
        if not last:
            print("还没有影子拍（先跑 once）")
            return 1
        _write_text(ROOT / REPORT_REL, report_md(last["row"], M, last["retro"], last["projection"], last["partition"],
                                                 last["divergent"], last["lookback_min"], []))
        return 0
    end = time.time() + a.minutes * 60
    while True:
        t0 = time.time()
        r = tick(env, every_s=a.every, lookback_min=a.lookback_min, seeds=a.seeds)
        row = r["row"]
        print(json.dumps({"at": row["at"], "active_ep": row["active_ep"], "phase": row["phase"], "ready": row["ready"],
                          "decisions": [(d["lane"], d["task"]) for d in row["decisions"]],
                          "instant": {k: v["cat"] for k, v in row["instant"].items()}, "window": [(x["lane"], x["cat"]) for x in r["window"]],
                          "projection": {k: r["projection"].get(k) for k in ("ep", "elapsed_min", "shadow_remaining_min", "projected_total_min")}},
                         ensure_ascii=False))
        if a.cmd == "once" or time.time() + a.every > end:
            return 0
        time.sleep(max(1.0, a.every - (time.time() - t0)))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
