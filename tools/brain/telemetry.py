"""全局状态快照（BRAIN-FW 11-06；给 LLM 大脑看的“一屏全景”，目标 < 15 KB，只读，不动任何东西）。

一拍 = 每台服务器一次远程 python（经 tools/netfix/rssh 复用主连接，两台并行线程）+ 笔记本本地文件：
  服务器侧（REMOTE_PROBE）  每道 GPU 利用率 / 显存；ComfyUI /queue 在跑 / 排队（含 ns_tag 任务标签、模型猜测）；
                            producer 心跳 / control / 登记表（每集每镜 首/尾/视频 状态、尝试次数、原因、等待分钟、stuck_objects）；
                            master_rejects 未清；log.jsonl 尾部失败事件 + 每集首次派单时间（KPI 计时起点）；
                            视频 state_<host>.json 每镜状态 / 渲染数 / 路由；night_control / night_state 年龄 / night.log 尾行；
                            合成期子进程（finish.py / assemble_episode.py）；看图分发器 /health；lane_roles 阶段状态
  笔记本侧                  资产作业（data/pipeline/asset_jobs）；空卡巡检 status；重启队列待办；卡点 open；lane_roles 配置；
                            派单分区；大脑最近决定（data/brain/decisions.jsonl）
  KPI（L-205）               每集 ≤ 50 分钟：起点 = 该集首次派单，elapsed / 完成比 / ETA / 超预算标记
用法：
  .venv/Scripts/python.exe tools/brain/telemetry.py snapshot [--pretty] [--md] [--no-save]
快照落盘 data/brain/snapshot.json + snapshot.md（原子写）。测试用 Env 子类全 fake，不碰网络。
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT_REL = "data/brain"
SERVERS = ("gpu33", "gpu36")
NEVER_LANES = ("gpu33:2",)
KPI_EPISODE_MIN = 50          # L-205
SCHEMA = "nsfs.brain_snapshot/1"
API_BASE = "http://127.0.0.1:8800"
CODE = {"passed": "P", "ready": "R", "running": "G", "pending": "W", "failed": "F", "best_effort": "B", "blocked": "X",
        "waiting_frame": "H", "done": "D"}
LEGEND = "P=passed R=ready(可派) G=running W=pending F=failed B=best_effort X=blocked -=na；镜串 'F:状态/尝试 L:状态/尝试 V:状态'"

# 服务器侧探针（只读）。__占位__ 由 Env.probe_host 填。注意：这段代码经 stdin 送到远端 python3 -，不含反斜杠。
REMOTE_PROBE = r"""
import json, os, subprocess, time, urllib.request
from datetime import datetime
LANES = json.loads('__LANES__'); RUN = "__RUN__"; HOST = "__HOST__"; PD = "__PD__"
NLOG = int("__NLOG__"); NFAIL = int("__NFAIL__"); VQA_PORT = int("__VQA_PORT__")
now = time.time()
out = {"now": now, "host": HOST, "gpus": {}, "queues": {}}
NL = chr(10)

def J(p):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return None

def ep_t(s):
    if s is None or s == "":
        return None
    if isinstance(s, (int, float)):
        return float(s)
    try:
        return datetime.fromisoformat(str(s).strip().replace(" ", "T")).timestamp()
    except Exception:
        return None

try:
    for ln in subprocess.run(["nvidia-smi", "--query-gpu=index,utilization.gpu,memory.used,memory.total",
                              "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=20).stdout.splitlines():
        i, u, m, t = [x.strip() for x in ln.split(",")]
        out["gpus"][i] = {"util": int(u), "mem": int(m), "mem_total": int(t)}
except Exception as e:
    out["gpus_error"] = repr(e)[:120]

def model_guess(prompt):
    names = []
    try:
        for node in (prompt or {}).values():
            ct = str(node.get("class_type") or "")
            if "Loader" in ct or "Load" in ct:
                for k in ("ckpt_name", "unet_name", "model_name", "lora_name", "model"):
                    v = (node.get("inputs") or {}).get(k)
                    if isinstance(v, str) and v and v not in names:
                        names.append(v.rsplit("/", 1)[-1][:40])
    except Exception:
        pass
    return names[:3]

for g, port in LANES.items():
    try:
        q = json.loads(urllib.request.urlopen("http://127.0.0.1:%d/queue" % int(port), timeout=5).read())
        rec = {"running": [], "pending": 0, "model": []}
        for it in (q.get("queue_running") or []):
            ex = it[3] if len(it) > 3 and isinstance(it[3], dict) else {}
            tag = ex.get("ns_tag") if isinstance(ex.get("ns_tag"), dict) else {}
            lab = (tag.get("agent") or str(ex.get("client_id") or "?")[:8]) + ":" + str(tag.get("obj") or tag.get("job") or tag.get("shot") or tag.get("kind") or "?")
            rec["running"].append(lab[:48])
            pr = it[2] if len(it) > 2 and isinstance(it[2], dict) else {}
            rec["model"] = rec["model"] or model_guess(pr)
        rec["pending"] = len(q.get("queue_pending") or [])
        pend = []
        for it in (q.get("queue_pending") or [])[:6]:
            ex = it[3] if len(it) > 3 and isinstance(it[3], dict) else {}
            tag = ex.get("ns_tag") if isinstance(ex.get("ns_tag"), dict) else {}
            pend.append(str(tag.get("obj") or tag.get("job") or tag.get("agent") or "?")[:28])
        rec["pending_labels"] = pend
        out["queues"][g] = rec
    except Exception:
        out["queues"][g] = None

out["hb"] = J(PD + "/heartbeat.json")
ctrl = J(PD + "/control.json") or {}
out["ctrl"] = {k: ctrl.get(k) for k in ("paused", "paused_by", "reason_kind", "hold_lanes", "expires_at")}
only = ctrl.get("only") or []
out["ctrl"]["only"] = only if len(only) <= 4 else only[:3] + ["+%d" % (len(only) - 3)]
out["ctrl"]["dispatch_at"] = (ctrl.get("dispatch_by") or {}).get("at")
reg = J(PD + "/registry.json") or {}
rj = J(PD + "/master_rejects.json") or {}
open_rj = [k for k, v in rj.items() if isinstance(v, dict) and not v.get("cleared")]
out["master_rejects_open"] = {"n": len(open_rj), "ids": open_rj[:12]}
CODE = {"passed": "P", "ready": "R", "running": "G", "pending": "W", "failed": "F", "best_effort": "B", "blocked": "X", "waiting_frame": "H", "done": "D"}
eps = {}
attention = []
for E in reg.get("episodes") or []:
    ep = str(E.get("ep"))
    shots = {}
    for S in E.get("shots") or []:
        sid = str(S.get("shot") or "")
        ob = S.get("objects") or {}
        parts = []
        for k in ("first", "last", "video"):
            o = ob.get(k) or {}
            st = str(o.get("status") or "-")
            c = "-" if o.get("na") else CODE.get(st, st[:2])
            a = o.get("attempts")
            parts.append(k[0].upper() + ":" + c + ("/" + str(a) if a not in (None, 0) and k != "video" else ""))
            if st not in ("passed", "pending") and not o.get("na"):
                t0 = ep_t(o.get("since"))
                rec = {"obj": k + ":" + sid, "st": st, "att": a, "where": o.get("where"),
                       "why": str(o.get("waiting_for") or o.get("reason") or o.get("last_error") or "")[:80]}
                if t0:
                    rec["wait_min"] = round((now - t0) / 60, 1)
                attention.append(rec)
        shots[sid.split("-", 1)[-1]] = " ".join(parts)
    if shots and len(set(shots.values())) == 1:
        shots = {"_all": next(iter(shots.values())), "n": len(shots)}
    hv = E.get("have") or {}
    pz = hv.get("passed") or {}
    obj = {k: (v or {}).get("status") for k, v in (E.get("objects") or {}).items() if k != "script" and (v or {}).get("status") != "passed"}
    eps[ep] = {"headline": str(E.get("headline") or "")[:100],
               "have": {"t": hv.get("total"), "f": pz.get("first"), "l": pz.get("last"), "v": pz.get("video")},
               "asm": ((E.get("objects") or {}).get("assembly") or {}).get("status") == "passed", "obj_open": obj, "shots": shots}
out["registry"] = {"updated": reg.get("updated"), "paused": reg.get("paused"), "counts": reg.get("counts"), "episodes": eps,
                   "attention": attention[:16], "attention_n": len(attention),
                   "stuck_objects": [str(x)[:100] for x in (reg.get("stuck_objects") or [])][:8]}
first_dispatch, last_t, fails, evc = {}, None, [], {}
try:
    lp = PD + "/log.jsonl"
    sz = os.path.getsize(lp)
    with open(lp, "rb") as f:
        if sz > 60 * 1024 * 1024:
            f.seek(sz - 60 * 1024 * 1024)
        lines = f.read().decode("utf-8", "replace").splitlines()
    tail = lines[-NLOG:]
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
        if t and (last_t is None or t > last_t):
            last_t = t
    for ln in tail:
        try:
            d = json.loads(ln)
        except Exception:
            continue
        ev = str(d.get("ev") or "")
        evc[ev] = evc.get(ev, 0) + 1
        if any(x in ev for x in ("fail", "err", "block", "timeout", "infra", "down", "stuck", "refused", "cap")):
            fails.append({"ts": str(d.get("ts") or "")[5:16], "ev": ev, "obj": d.get("obj"),
                          "why": str(d.get("reason") or d.get("note") or d.get("error") or d.get("why") or "")[:100]})
except Exception as e:
    out["log_error"] = repr(e)[:120]
out["log"] = {"first_dispatch": first_dispatch, "last_dispatch_t": last_t, "fails": fails[-NFAIL:], "ev_counts_tail": evc}
V = "data/pipeline/runs/" + RUN + "/video/"
nc = J(V + "night_control.json") or {}
out["nctrl"] = {k: nc.get(k) for k in ("yield_s", "video_lanes", "hold_lanes", "hold_expires", "per_lane", "force_eps", "poll_s") if k in nc}
try:
    out["night_state_age_s"] = round(now - os.stat(V + "night_state.json").st_mtime)
except OSError:
    out["night_state_age_s"] = None
ns = J(V + "night_state.json") or {}
out["night_state"] = {"eps": {k: {"status": v.get("status"), "host": v.get("host")} for k, v in (ns.get("eps") or {}).items()},
                      "lane_mode": ns.get("lane_mode"), "pending_shots": ns.get("pending_shots")}
try:
    with open(V + "night.log", "rb") as f:
        sz = os.path.getsize(V + "night.log")
        f.seek(max(0, sz - 12000))
        out["night_log_tail"] = [x[:120] for x in f.read().decode("utf-8", "replace").splitlines()[-5:]]
except OSError:
    out["night_log_tail"] = None
st = J(V + "state_" + HOST + ".json") or {}
vs, vcount = {}, {}
for sid, r in (st.get("shots") or {}).items():
    s = str(r.get("status") or "?")
    vcount[s] = vcount.get(s, 0) + 1
    if s in ("done", "best_effort"):
        continue
    rs = r.get("renders") or []
    lastr = rs[-1] if rs else {}
    last = "%s@%s %s %s" % (lastr.get("state"), lastr.get("lane"), lastr.get("recipe"), ((lastr.get("score") or {}).get("verdict") or "")) if rs else ""
    route = str(r.get("route") or r.get("why") or "")[:40]
    vs[sid] = (s + " n" + str(len(rs)) + " " + last + ((" | " + route) if route else "")).strip()
out["video"] = {"counts": vcount, "active": dict(list(vs.items())[:14]), "active_n": len(vs)}
try:
    ps = subprocess.run(["ps", "-eo", "pid,etimes,args"], capture_output=True, text=True, timeout=10).stdout.splitlines()
    kids = [x.strip()[:120] for x in ps if ("finish.py" in x or "assemble_episode.py" in x or "assemble_series.py" in x) and "grep" not in x]
    out["finalize_procs"] = kids[:4]
    out["procs"] = {"producer": sum(1 for x in ps if "producer.py serve" in x), "night": sum(1 for x in ps if "night.py" in x and "--once" not in x),
                    "vqa": sum(1 for x in ps if "vqa" in x and "python" in x)}
except Exception as e:
    out["procs_error"] = repr(e)[:80]
try:
    h = json.loads(urllib.request.urlopen("http://127.0.0.1:%d/health" % VQA_PORT, timeout=3).read())
    out["vqa"] = {"queue": h.get("queue"), "loaded": h.get("loaded"), "instances": h.get("instances")}
except Exception:
    out["vqa"] = None
out["lane_roles_state"] = ((J("data/pipeline/lane_roles_state.json") or {}).get(RUN) or {})
out["ctrl_files"] = {}
for nm in ("owner_triggers.json", "master_rejects.json"):
    try:
        out["ctrl_files"][nm] = os.path.getmtime(PD + "/" + nm)
    except OSError:
        out["ctrl_files"][nm] = None
print(NL + json.dumps(out, ensure_ascii=False))
"""


def _j(p, default=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):   # arch-ok: 快照里的每一项“读不到 = None/默认”，由大脑按缺失处理
        return default


def _jw(p: Path, d) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def _load(name: str, rel: str, root: Path = ROOT):
    src = Path(root) / rel if (Path(root) / rel).is_file() else ROOT / rel
    sp = importlib.util.spec_from_file_location(name, src)
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


_RM_MOD: dict = {}


def _rm_mod():
    """registry_merged 模块只加载一次（它的“每 10 分钟记一条”限流在模块里）"""
    if "m" not in _RM_MOD:
        _RM_MOD["m"] = _load("registry_merged_for_brain", "tools/autopilot/registry_merged.py")
    return _RM_MOD["m"]


def jst(now: float, fmt: str = "%m-%d %H:%M") -> str:
    return time.strftime(fmt, time.gmtime(now + 9 * 3600))


DEFAULT_CFG = {"probe_timeout_s": 60, "log_tail": 600, "fail_n": 8, "decisions_n": 8, "max_bytes": 15000}


def load_cfg(root: Path = ROOT) -> dict:
    d = _j(root / "config/brain/brain.json", {}) or {}
    return {**DEFAULT_CFG, **{k: v for k, v in (d.get("telemetry") or {}).items() if not k.startswith("_")}}


# ------------------------------------------------------------------ 环境（真机；测试全 fake）
class Env:
    def __init__(self, root: Path = ROOT):
        self.root = Path(root)
        self._hosts = None
        # W-SCAN：本机 API（网页看到的口径）只在真仓库根上查；测试的临时根 = None → 自查跳过 API 类检查
        self.api_base = API_BASE if self.root.resolve() == ROOT.resolve() else None

    def now(self) -> float:
        return time.time()

    def import_epochs(self, run: str) -> dict:
        """本机 imports.jsonl → {集: 最近导入 epoch}（KPI 计时起点用，L-212 #9）"""
        try:
            return _load("kpi_core_for_brain", "tools/brain/kpi_core.py", self.root).import_epochs(self.root, run)
        except Exception:  # noqa: BLE001  # arch-ok: 读不到导入记录 = 起点按首派
            return {}

    def j(self, rel, default=None):
        return _j(self.root / rel, default)

    def hosts(self):
        if self._hosts is None:
            self._hosts = _load("hosts_for_brain", "tools/factory/hosts.py", self.root)
        return self._hosts

    def lanes(self) -> dict:
        H = self.hosts()
        d = H.load()
        out = {}
        for host in SERVERS:
            broken = {int(x) for x in ((d.get("hosts") or {}).get(host) or {}).get("broken_gpus") or []}
            for lane, rec in H.lanes(host, role="image", d=d).items():
                if lane in NEVER_LANES or int(rec.get("gpu", -1)) in broken:
                    continue
                out[lane] = {"host": host, "gpu": int(rec["gpu"]), "comfy_port": int(rec["comfy_port"])}
        assert not any(ln in NEVER_LANES for ln in out)
        return out

    def primary_run(self) -> str:
        return str((self.j("config/pipeline/runs.json", {}) or {}).get("primary") or "")

    def producer_rel(self, run: str) -> str:
        return f"data/producer/runs/{run}"

    def vqa_port(self) -> int:
        try:
            LRO = _load("lane_roles_for_brain", "tools/autopilot/lane_roles_producer.py", self.root)
            return int(LRO.review_ports(LRO.load_cfg(self.root))["router"])
        except Exception:  # noqa: BLE001  # arch-ok: 读不到 = 默认分发器端口
            return 8870

    def probe_host(self, host: str, run: str, lanes: dict, cfg: dict) -> dict | None:
        H = self.hosts()
        ports = {str(v["gpu"]): v["comfy_port"] for v in lanes.values() if v["host"] == host}
        code = (REMOTE_PROBE.replace("__LANES__", json.dumps(ports)).replace("__RUN__", run).replace("__HOST__", host)
                .replace("__PD__", self.producer_rel(run)).replace("__NLOG__", str(cfg["log_tail"]))
                .replace("__NFAIL__", str(cfg["fail_n"])).replace("__VQA_PORT__", str(self.vqa_port())))
        assert chr(92) not in code
        cmd = f"cd {H.server_root(host)} && python3 -"
        try:
            rssh = _load("rssh_for_brain", "tools/netfix/rssh.py", self.root)
            r = rssh.run_retry(host, cmd, input=code.encode("utf-8"), timeout=cfg["probe_timeout_s"], tries=1)
            txt = (r.stdout or b"").decode("utf-8", "replace")
            return json.loads([ln for ln in txt.splitlines() if ln.startswith("{")][-1])
        except (OSError, ValueError, IndexError, AttributeError):   # arch-ok: 探针失败 = 本拍该台 None（快照 probe_errors 列出）
            return None

    def merged_registry(self, run: str) -> dict | None:
        """L-209 S2.5：笔记本写的唯一合并登记表（新鲜才给；缺 / 过期 = None → KPI / 自查退回两台探针）"""
        try:
            RM = _rm_mod()
            return RM.fresh(run, self.root, self.now(), log=RM.default_log("brain"), actor="brain")
        except Exception:  # noqa: BLE001  # arch-ok: 模块 / 文件读不到 = 退回两台探针
            return None

    def asset_jobs(self, run: str) -> list[dict]:
        AJ = _load("asset_jobs_for_brain", "tools/pipeline/asset_jobs.py", self.root)
        return AJ.list_jobs(self.root, run)

    def restart_pending(self) -> list[dict]:
        if str(self.root / "tools/autopilot") not in sys.path:
            sys.path.insert(0, str(self.root / "tools/autopilot"))
        import restart_queue as RQ
        return RQ.pending()

    def issues_open(self) -> list[dict]:
        ri = _load("report_issue_for_brain", "tools/master/report_issue.py", self.root)
        return [x for x in ri.load(self.root / "data/pipeline/issues.jsonl") if x.get("status") == "open"]


# ------------------------------------------------------------------ 纯逻辑
def kpi(now: float, probes: dict, budget_min: int = KPI_EPISODE_MIN, imports: dict | None = None, merged: dict | None = None) -> dict:
    """每集 KPI：两台探针 → 起点（各台首派取最早）+ 完成数 → kpi_core.episodes（L-212 #9：和网页 KPI 面板同一函数；
    起点 = max(首派, 最近导入)，imports = kpi_core.import_epochs）。完成数：L-209 S2.5 合并登记表新鲜（merged = ep_have 结果）→ 只用它；
    否则两台探针逐字段取最大（旧退路）"""
    KC = _load("kpi_core_for_brain", "tools/brain/kpi_core.py")
    starts, have = {}, {}
    for pr in probes.values():
        if not pr:
            continue
        for ep, t in ((pr.get("log") or {}).get("first_dispatch") or {}).items():
            if ep not in starts or t < starts[ep]:
                starts[ep] = t
        if merged is None:
            for ep, E in ((pr.get("registry") or {}).get("episodes") or {}).items():
                # W-SCAN 11-07：逐字段取两台最大值（以前整条替换 → gpu33 首帧 0 把 gpu36 的 14 盖掉）
                have[ep] = KC.merge_have(have.get(ep), **KC.have_from_registry_episode(E))
    for ep, h in (merged or {}).items():
        have[str(ep)] = KC.merge_have(None, **KC.have_from_registry_episode({"have": h, "asm": h.get("asm")}))
    return KC.episodes(now, starts, have, imports, budget_min)


def merged_view(doc: dict | None, now: float) -> dict | None:
    """快照里的合并登记表摘要：{at, age_s, have{ep:{t,f,l,v,asm}}, conflicts[], conflicts_n, orphans_n}"""
    if not doc:
        return None
    RM = _rm_mod()
    return {"at": doc.get("computed_at"), "age_s": round(now - float(doc.get("computed_t") or now)), "have": RM.ep_have(doc),
            "conflicts": [{k: c.get(k) for k in ("ep", "shot", "kind", "why", "views", "used", "owner")} for c in (doc.get("conflicts") or [])][:20],
            "conflicts_n": int(doc.get("conflicts_n") or 0),
            "orphans_n": int(((doc.get("orphans") or {}).get("shots_dropped_n")) or 0)}


def lane_view(lanes: dict, probes: dict, lr_cfg: dict, phases: dict) -> dict:
    """每道：util / mem / 在跑标签 / 排队数 / 模型猜测 / 角色（按当前阶段）"""
    out = {}
    for ln, v in lanes.items():
        pr = probes.get(v["host"]) or {}
        g = (pr.get("gpus") or {}).get(str(v["gpu"])) or {}
        q = (pr.get("queues") or {}).get(str(v["gpu"]))
        roles = sorted({r for ph in set(phases.values()) or {"frames"} for r, lns in ((lr_cfg.get("phases") or {}).get(ph) or {}).items() if ln in lns})
        rec = {"util": g.get("util"), "mem_gb": round(g["mem"] / 1024, 1) if g.get("mem") is not None else None,
               "roles": roles, "probe": bool(pr)}
        if q is None:
            rec["queue"] = None
        else:
            rec["running"] = q.get("running") or []
            rec["pending"] = q.get("pending")
            if q.get("pending_labels"):
                rec["pending_labels"] = q["pending_labels"]
            if q.get("model"):
                rec["model"] = q["model"]
        if rec["util"] is not None and q is not None:
            rec["idle"] = rec["util"] < 5 and not rec.get("running") and not rec.get("pending")
        out[ln] = rec
    return out


def host_view(pr: dict | None, now: float) -> dict:
    if not pr:
        return {"probe": None}
    hb = pr.get("hb") or {}
    hb_age = round((pr.get("now") or now) - float(hb.get("t") or 0)) if hb else None
    return {"producer": {"hb_age_s": hb_age, "paused": hb.get("paused"), "inflight": hb.get("inflight"), "scoring": hb.get("scoring"),
                         "started": hb.get("started"), "pid": hb.get("pid")},
            "ctrl": pr.get("ctrl"), "nctrl": pr.get("nctrl"), "night_state_age_s": pr.get("night_state_age_s"),
            "night_state": pr.get("night_state"), "night_log_tail": pr.get("night_log_tail"),
            "finalize_procs": pr.get("finalize_procs") or [], "procs": pr.get("procs"), "vqa": pr.get("vqa"),
            "master_rejects_open": pr.get("master_rejects_open"), "video": pr.get("video"),
            "registry": pr.get("registry"), "log_fails": (pr.get("log") or {}).get("fails"),
            "ev_counts_tail": (pr.get("log") or {}).get("ev_counts_tail"), "lane_roles_state": pr.get("lane_roles_state"),
            "ctrl_files": pr.get("ctrl_files"),
            "errors": {k: v for k, v in pr.items() if k.endswith("_error")}}


def assets_view(jobs: list[dict]) -> dict:
    by = {}
    for j in jobs:
        by[str(j.get("state"))] = by.get(str(j.get("state")), 0) + 1
    pend = [j["id"] for j in jobs if j.get("state") == "pending"][:10]
    failed = [{"id": j["id"], "kind": j.get("kind"), "err": str(j.get("error") or "")[:80], "final": bool(j.get("final"))}
              for j in jobs if j.get("state") == "failed"][:8]
    running = [{"id": j["id"], "lane": j.get("lane")} for j in jobs if j.get("state") == "running"][:8]
    return {"counts": by, "pending": pend, "failed": failed, "running": running}


def recent_decisions(root: Path, n: int) -> list[dict]:
    p = root / OUT_REL / "decisions.jsonl"
    out = []
    try:
        lines = p.read_text(encoding="utf-8").splitlines()[-n:]
    except OSError:   # arch-ok: 还没有决定记录 = 空列表
        return out
    for ln in lines:
        try:
            d = json.loads(ln)
        except ValueError:   # arch-ok: 坏行跳过（只追加日志里半行）
            continue
        out.append({"at": d.get("at"), "kind": d.get("kind"), "params": {k: v for k, v in (d.get("params") or {}).items() if k not in ("reason", "expected_effect")},
                    "dry": d.get("dry"), "result": str(d.get("result") or "")[:100]})
    return out


def compact(snap: dict, max_bytes: int) -> dict:
    """超出预算时按优先级裁剪（night.log 尾行 → 镜串 → attention → 失败事件）"""
    def size(d):
        return len(json.dumps(d, ensure_ascii=False).encode("utf-8"))
    cuts = [
        lambda: [v.update(evidence=str(v.get("evidence") or "")[:90], fix="", surface="")
                 for v in ((snap.get("self_check") or {}).get("violations") or []) if isinstance(v, dict)],
        lambda: [h.update(ev_counts_tail=None) for h in snap["hosts"].values()],
        lambda: [h.update(night_log_tail=(h.get("night_log_tail") or [])[-3:]) for h in snap["hosts"].values() if h.get("probe") is not False],
        lambda: [h["video"].update(active=dict(list((h["video"].get("active") or {}).items())[:6])) for h in snap["hosts"].values() if h.get("video")],
        lambda: snap.update(issues_open=[{**i, "what": str(i.get("what") or "")[:50]} for i in (snap.get("issues_open") or []) if isinstance(i, dict)][-3:]),
        lambda: [E.pop("shots", None) for h in snap["hosts"].values() if h.get("registry") for E in (h["registry"].get("episodes") or {}).values() if E.get("asm")],
        lambda: [h["registry"].update(attention=(h["registry"].get("attention") or [])[:8]) for h in snap["hosts"].values() if h.get("registry")],
        lambda: [h.update(log_fails=(h.get("log_fails") or [])[-3:], night_state=None) for h in snap["hosts"].values()],
        lambda: [h["registry"].update(shots_dropped=True) or [E.pop("shots", None) for E in (h["registry"].get("episodes") or {}).values()]
                 for h in snap["hosts"].values() if h.get("registry")],
        lambda: isinstance(snap.get("self_check"), dict) and snap["self_check"].update(   # 红在前已排好；只留前 12 项，其余看 issues.jsonl
            violations_n=len(snap["self_check"].get("violations") or []), violations=(snap["self_check"].get("violations") or [])[:12]),
    ]
    for cut in cuts:
        if size(snap) <= max_bytes:
            break
        cut()
        snap["truncated"] = snap.get("truncated", 0) + 1
    snap["bytes"] = size(snap)
    return snap


def snapshot(env: Env | None = None, cfg: dict | None = None, save: bool = True) -> dict:
    env = env or Env()
    cfg = cfg or load_cfg(env.root)
    now = env.now()
    run = env.primary_run()
    lanes = env.lanes()
    with ThreadPoolExecutor(len(SERVERS)) as ex:
        probes = dict(zip(SERVERS, ex.map(lambda h: env.probe_host(h, run, lanes, cfg), SERVERS)))
    lr_cfg = env.j("config/pipeline/lane_roles.json", {}) or {}
    phases = {}
    for pr in probes.values():
        for ep, rec in ((pr or {}).get("lane_roles_state") or {}).items():
            if isinstance(rec, dict) and rec.get("phase"):
                phases[str(ep)] = rec["phase"]
    ovr = env.j("data/pipeline/lane_roles_override.json", {}) or {}
    mfn = getattr(env, "merged_registry", None)      # L-209 S2.5：唯一合并登记表（测试 fake Env 没有 = 旧口径）
    mv = merged_view(mfn(run) if mfn else None, now)
    snap = {"schema": SCHEMA, "at": jst(now, "%Y-%m-%d %H:%M:%S+09:00"), "t": now, "run": run, "legend": LEGEND,
            "kpi": kpi(now, probes, imports=env.import_epochs(run), merged=(mv or {}).get("have")), "registry_merged": mv, "lanes": lane_view(lanes, probes, lr_cfg, phases),
            "lane_roles": {"enabled": lr_cfg.get("enabled"), "from_episode": lr_cfg.get("from_episode"), "phases": phases,
                           "tables": lr_cfg.get("phases"), "override": (ovr.get(run) or {}) if isinstance(ovr, dict) else {}},
            "partition": (env.j("data/state/netfix/partition.json", {}) or {}).get("images"),     # L-209 S2.3：只认唯一一份
            "hosts": {h: host_view(probes.get(h), now) for h in SERVERS},
            "probe_errors": [h for h in SERVERS if probes.get(h) is None]}
    try:
        snap["assets"] = assets_view(env.asset_jobs(run))
    except Exception as e:  # noqa: BLE001  # arch-ok: 资产作业读不了只记错误，不影响快照其余部分
        snap["assets"] = {"error": repr(e)[:120]}
    iw = env.j("data/pipeline/idle_watch/status.json", {}) or {}
    snap["idle_watch"] = {"at": iw.get("at"), "age_s": round(now - float(iw.get("t") or now)), "idle_lanes": iw.get("idle_lanes"),
                          "has_work": iw.get("has_work"), "probe_errors": iw.get("probe_errors"),
                          "actions": [f"{a.get('kind')}:{a.get('host')}→{str(a.get('result') or '')[:40]}" for a in (iw.get("actions") or [])][:4]}
    try:
        snap["restart_pending"] = [f"{r.get('host')} {r.get('mode')} by {r.get('by')} @{str(r.get('at') or '')[5:16]}" for r in env.restart_pending()][-4:]
    except Exception as e:  # noqa: BLE001  # arch-ok: 证据项
        snap["restart_pending"] = {"error": repr(e)[:80]}
    try:
        snap["issues_open"] = [{"id": i.get("id"), "who": i.get("who"), "what": str(i.get("what") or "")[:90]} for i in env.issues_open()[-5:]]
    except Exception as e:  # noqa: BLE001  # arch-ok: 证据项
        snap["issues_open"] = {"error": repr(e)[:80]}
    snap["recent_decisions"] = recent_decisions(env.root, cfg["decisions_n"])
    sc_line = (_j(env.root / "data/brain/scorecard.json", {}) or {}).get("line")   # W-E2E：tools/qa/scorecard.py 的“做完”记分卡一行
    if sc_line:
        snap["scorecard"] = str(sc_line)[:300]
    if cfg.get("self_check", True):
        try:   # W-SCAN 11-07：系统自查（tools/brain/invariants.py）——违规开 / 更新 / 自动关卡点，列在 snapshot.md 最上面
            INV = _load("invariants_for_brain", "tools/brain/invariants.py", env.root)
            snap["self_check"] = INV.cycle(snap, env, now, sync=save)
        except Exception as e:  # noqa: BLE001  # arch-ok: 自查本身出错只记一条，不影响快照
            snap["self_check"] = {"error": repr(e)[:160]}
    sc_full = json.loads(json.dumps(snap.get("self_check"), ensure_ascii=False))   # md 列全量；JSON 里按预算裁
    snap = compact(snap, cfg["max_bytes"])
    snap["hash"] = hashlib.sha256(json.dumps({k: v for k, v in snap.items() if k not in ("hash", "bytes", "at", "t")},
                                             ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:12]
    if save:
        _jw(env.root / OUT_REL / "snapshot.json", snap)
        p = env.root / OUT_REL / "snapshot.md"
        tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
        tmp.write_text(summary_md({**snap, "self_check": sc_full} if sc_full is not None else snap), encoding="utf-8")
        os.replace(tmp, p)
    return snap


def summary_md(s: dict) -> str:
    """一屏 markdown 摘要（给人 / 给会话内大脑）"""
    L = [f"# 全局快照 {s.get('at')}  run={s.get('run')}  hash={s.get('hash')}  {s.get('bytes', '?')} B"
         + (f"  探针失败: {s['probe_errors']}" if s.get("probe_errors") else "")]
    if s.get("scorecard"):
        L.append(str(s["scorecard"]))
    sc = s.get("self_check")
    if isinstance(sc, dict) and sc.get("error"):
        L.append(f"## 🔴 系统自查发现：自查本身出错 {sc['error']}")
    elif isinstance(sc, dict) and sc.get("violations"):
        L.append(f"## 🔴 系统自查发现（{len(sc['violations'])} 项；卡点新开 {sc.get('opened', 0)} / 自动关 {sc.get('closed', 0)}）")
        L += [f"- {v.get('sev')} {v.get('title')} —— {v.get('evidence')} [{v.get('key')}{' ' + v['issue'] if v.get('issue') else ''}]" for v in sc["violations"]]
    elif isinstance(sc, dict):
        L.append(f"## 🟢 系统自查：{len(sc.get('ran') or [])} 类检查全过")
    L.append("## KPI（L-205 每集 ≤ 50 min）")
    for ep, k in (s.get("kpi") or {}).items():
        L.append(f"- ep{int(ep):02d}: {k.get('state')} 起 {k.get('start')} 已 {k.get('elapsed_min')} min · 首 {k.get('first_done')}/{k.get('total')} "
                 f"尾 {k.get('last_done')}/{k.get('total')} 视频 {k.get('video_done')}/{k.get('total')} · ETA {k.get('eta_min')} min")
    L.append("## 道（阶段 " + json.dumps(s.get("lane_roles", {}).get("phases"), ensure_ascii=False) + "）")
    for ln, r in (s.get("lanes") or {}).items():
        run_ = ",".join(r.get("running") or []) or "-"
        L.append(f"- {ln} {'/'.join(r.get('roles') or [])}: util {r.get('util')}% mem {r.get('mem_gb')}G 在跑 [{run_}] 排队 {r.get('pending')}"
                 + (f" 模型 {r.get('model')}" if r.get("model") else "") + (" **空闲**" if r.get("idle") else "") + ("" if r.get("probe") else " (探不到)"))
    for h, H in (s.get("hosts") or {}).items():
        if H.get("probe") is None and not H.get("registry"):
            L.append(f"## {h}: 探针失败")
            continue
        p = H.get("producer") or {}
        L.append(f"## {h}: producer 心跳 {p.get('hb_age_s')}s paused={p.get('paused')} inflight={p.get('inflight')} · "
                 f"ctrl only={(H.get('ctrl') or {}).get('only')} hold={(H.get('ctrl') or {}).get('hold_lanes')} · "
                 f"night 状态龄 {H.get('night_state_age_s')}s nctrl={json.dumps(H.get('nctrl'), ensure_ascii=False)} · "
                 f"合成子进程 {len(H.get('finalize_procs') or [])} · 看图 {H.get('vqa')} · 驳回未清 {(H.get('master_rejects_open') or {}).get('n')}")
        reg = H.get("registry") or {}
        for ep, E in (reg.get("episodes") or {}).items():
            L.append(f"  - ep{int(ep):02d} {E.get('headline')}")
            if E.get("shots"):
                L.append("    " + " | ".join(f"{k} {v}" for k, v in E["shots"].items()))
        for a in (reg.get("attention") or [])[:12]:
            L.append(f"  - ⚠ {a.get('obj')} {a.get('st')} 第{a.get('att')}次 @{a.get('where')}" + (f" 等 {a['wait_min']} min" if a.get("wait_min") is not None else "") + f"：{a.get('why')}")
        if reg.get("stuck_objects"):
            L.append(f"  - STUCK {reg['stuck_objects']}")
        v = H.get("video") or {}
        if v:
            L.append(f"  - 视频 {v.get('counts')} 在途 {v.get('active_n')}: " + "; ".join(f"{k} {x}" for k, x in (v.get("active") or {}).items()))
        for f in (H.get("log_fails") or [])[-5:]:
            L.append(f"  - ✗ {f.get('ts')} {f.get('ev')} {f.get('obj') or ''} {f.get('why')}")
        for t in (H.get("night_log_tail") or [])[-3:]:
            L.append(f"  - night: {t}")
    a = s.get("assets") or {}
    L.append(f"## 资产作业 {a.get('counts')} pending {a.get('pending')} failed {[x.get('id') + ':' + x.get('err', '')[:40] for x in (a.get('failed') or [])]}")
    iw = s.get("idle_watch") or {}
    L.append(f"## 空卡巡检 {iw.get('at')}（{iw.get('age_s')}s 前）空闲 {iw.get('idle_lanes')} 有活 {iw.get('has_work')} 动作 {iw.get('actions')}")
    L.append(f"## 重启待办 {s.get('restart_pending')}")
    L.append("## 卡点 open: " + "; ".join(f"{i.get('id')} {i.get('who')} {i.get('what')[:60]}" for i in (s.get("issues_open") or []) if isinstance(i, dict)))
    L.append("## 大脑最近决定: " + "; ".join(f"{d.get('at')} {d.get('kind')} {d.get('params')} → {d.get('result')}" for d in (s.get("recent_decisions") or [])))
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="全局状态快照（BRAIN-FW）")
    ap.add_argument("cmd", choices=["snapshot", "md"], nargs="?", default="snapshot")
    ap.add_argument("--pretty", action="store_true")
    ap.add_argument("--md", action="store_true", help="同时打印 markdown 摘要")
    ap.add_argument("--no-save", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "md":
        print(summary_md(_j(ROOT / OUT_REL / "snapshot.json", {}) or {}))
        return 0
    s = snapshot(save=not a.no_save)
    if a.md:
        print(summary_md(s))
    else:
        print(json.dumps(s, ensure_ascii=False, indent=1 if a.pretty else None))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
