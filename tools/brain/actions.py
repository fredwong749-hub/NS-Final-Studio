"""大脑动作白名单执行器（BRAIN-FW 11-06）。大脑（API 常驻 / 会话内 PS-MASTER）只能提交这里登记的动作，每个动作有 JSON schema、
护栏、速率上限、幂等键；一律先过 check() 再执行；--dry-run 只记不做。

护栏（硬）：永不涉及 gpu33:2；永不删除（没有删除类动作，含 rm/delete/unlink/quarantine 字样的参数直接拒）；永不触发成人镜（obj / shots
            落在剧本 adult 镜或 high_intensity 集 → 拒）；每种动作有速率上限（data/brain/state.json）；restart 每台 30 min 一次；
            night_control 的 hold_lanes / video_lanes 必须带到期（≤ 6 h）；lane_roles 阶段覆盖必须带到期。
审计：每个动作一行 data/brain/decisions.jsonl（时间、快照 hash、动作、理由、预期效果、复查秒数、dry、结果）。
用法：
  .venv/Scripts/python.exe tools/brain/actions.py run '<json 动作列表>' [--dry-run] [--snapshot-hash H] [--by BRAIN]
  .venv/Scripts/python.exe tools/brain/actions.py catalog          # 动作目录（schema）
动作列表元素：{"kind": "<动作名>", "reason": "...", "expected_effect": "...", "check_after_s": 300, ...参数}
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
OUT_REL = "data/brain"
WHO = "BRAIN"
SERVERS = ("gpu33", "gpu36")
NEVER_LANES = ("gpu33:2",)
ALLOWED_LANES = ("gpu33:0", "gpu33:1", "gpu33:3", "gpu36:0", "gpu36:1", "gpu36:2")
FORBIDDEN_WORDS = ("rm -", "delete", "unlink", "rmdir", "quarantine", "--apply", "shred", "truncate")
MAX_EXPIRY_MIN = 360
IDEM_WINDOW_S = 600
RESTART_GAP_S = 1800

COMMON = {"reason": {"type": "string", "description": "为什么（引用快照证据）"},
          "expected_effect": {"type": "string", "description": "预期效果（可核对）"},
          "check_after_s": {"type": "integer", "description": "多少秒后复查效果"}}
HOST = {"type": "string", "enum": list(SERVERS)}


def _schema(props: dict, required: list[str] | None = None) -> dict:
    p = {**COMMON, **props}
    return {"type": "object", "properties": p, "required": sorted(p.keys()), "additionalProperties": False}


# 目录：name → {desc, schema, rate: (次数, 窗口秒), risk}
CATALOG = {
    "producer_retry": {"desc": "把一个首/尾帧对象放回重派（清 blocked / 等资产 / 退避，不计次）。obj 形如 first:ep02-S3",
                       "schema": _schema({"host": HOST, "obj": {"type": "string"}}), "rate": (12, 3600), "risk": "low"},
    "producer_uncap": {"desc": "重试用尽的对象多给 n 次（24 h 有效）。用于你判断再试有意义时",
                       "schema": _schema({"host": HOST, "obj": {"type": "string"}, "n": {"type": "integer", "minimum": 1, "maximum": 3}}),
                       "rate": (6, 3600), "risk": "low"},
    "producer_regen": {"desc": "整镜换代重出首帧（走驳回重出链路）。只在画面确实错（视线 / 排排站 / 首尾太像）时用",
                       "schema": _schema({"host": HOST, "episode": {"type": "integer"}, "shots": {"type": "array", "items": {"type": "string"}}}),
                       "rate": (3, 3600), "risk": "medium"},
    "producer_reset_best_effort": {"desc": "把 best_effort 的镜重新给 3 次（门槛 / 编译器更新后）",
                                   "schema": _schema({"host": HOST, "shots": {"type": "array", "items": {"type": "string"}}}),
                                   "rate": (2, 3600), "risk": "medium"},
    "producer_review_adopt": {"desc": "重试用尽后手工取最高分版设为当前（n=null 自动挑）",
                              "schema": _schema({"host": HOST, "obj": {"type": "string"}, "n": {"type": ["integer", "null"]}}),
                              "rate": (10, 3600), "risk": "low"},
    "clear_stale_master_rejects": {"desc": "把该台 master_rejects.json 里超过 older_than_h 小时、对象已 passed 的驳回标 cleared（先备份）",
                                   "schema": _schema({"host": HOST, "older_than_h": {"type": "integer", "minimum": 1}}),
                                   "rate": (2, 3600), "risk": "low"},
    "asset_jobs_requeue": {"desc": "失败的资产作业重新排队（attempts 归零）并可立即跑一拍 asset_worker",
                           "schema": _schema({"job_ids": {"type": "array", "items": {"type": "string"}}, "tick": {"type": "boolean"}}),
                           "rate": (6, 3600), "risk": "low"},
    "restart_queue_request": {"desc": "请求重启该台常驻（producer-only / night-only / all）。每台 30 min 最多一次；心跳过期才用",
                              "schema": _schema({"host": HOST, "mode": {"type": "string", "enum": ["producer-only", "night-only", "all"]},
                                                 "urgent": {"type": "boolean"}}), "rate": (4, 3600), "risk": "medium"},
    "night_once": {"desc": "该台 night.py --once 重派一轮视频（道空而有可派视频时）",
                   "schema": _schema({"host": HOST}), "rate": (6, 3600), "risk": "low"},
    "set_night_control": {"desc": "改该台 night_control.json：yield_s / video_lanes / hold_lanes（null = 不改；hold/video 必须 expires_min ≤ 360）",
                          "schema": _schema({"host": HOST, "yield_s": {"type": ["integer", "null"], "minimum": 0, "maximum": 600},
                                             "video_lanes": {"type": ["array", "null"], "items": {"type": "string", "enum": list(ALLOWED_LANES)}},
                                             "hold_lanes": {"type": ["array", "null"], "items": {"type": "string", "enum": list(ALLOWED_LANES)}},
                                             "expires_min": {"type": "integer", "minimum": 5, "maximum": MAX_EXPIRY_MIN}}),
                          "rate": (4, 3600), "risk": "medium"},
    "lane_roles_phase_override": {"desc": "把某集的工位阶段强制为 frames / videos（带到期），覆盖自动推导",
                                  "schema": _schema({"episode": {"type": "integer"}, "phase": {"type": "string", "enum": ["frames", "videos"]},
                                                     "expires_min": {"type": "integer", "minimum": 5, "maximum": MAX_EXPIRY_MIN}}),
                                  "rate": (2, 3600), "risk": "medium"},
    "report_issue": {"desc": "登记卡点（data/pipeline/issues.jsonl + V2_LIVE 一行）",
                     "schema": _schema({"episode": {"type": "integer"}, "step": {"type": "string"}, "what": {"type": "string"},
                                        "fix_hint": {"type": "string"}, "blocking": {"type": "boolean"}}), "rate": (4, 3600), "risk": "low"},
    "note_to_owner": {"desc": "给项目方一句话（写 data/brain/owner_notes.md + V2_LIVE 顶部一行）。level: red/yellow/green",
                      "schema": _schema({"text": {"type": "string"}, "level": {"type": "string", "enum": ["red", "yellow", "green"]}}),
                      "rate": (6, 3600), "risk": "low"},
    "no_action": {"desc": "本轮不动手（写明为什么一切正常 / 在等什么）", "schema": _schema({}), "rate": (100, 3600), "risk": "none"},
}


def _j(p, default=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):   # arch-ok: 状态 / 配置缺 = 默认（速率表空 = 还没动过）
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


def jst(now: float, fmt: str = "%m-%d %H:%M:%S") -> str:
    return time.strftime(fmt, time.gmtime(now + 9 * 3600))


def validate(inst, schema: dict, path: str = "") -> str | None:
    """够用的 JSON schema 子集校验（type / enum / required / additionalProperties / items / min / max）→ 错误串或 None"""
    t = schema.get("type")
    types = t if isinstance(t, list) else [t] if t else []
    pyt = {"object": dict, "array": list, "string": str, "integer": int, "boolean": bool, "null": type(None), "number": (int, float)}
    if types and not any(isinstance(inst, pyt[x]) and not (x in ("integer", "number") and isinstance(inst, bool)) for x in types):
        return f"{path or '$'} 应为 {types}"
    if "enum" in schema and inst not in schema["enum"]:
        return f"{path or '$'} 不在 {schema['enum']}"
    if isinstance(inst, dict):
        for k in schema.get("required") or []:
            if k not in inst:
                return f"{path or '$'} 缺 {k}"
        props = schema.get("properties") or {}
        if schema.get("additionalProperties") is False:
            extra = sorted(set(inst) - set(props))
            if extra:
                return f"{path or '$'} 多余字段 {extra}"
        for k, v in inst.items():
            if k in props:
                e = validate(v, props[k], f"{path}.{k}")
                if e:
                    return e
    if isinstance(inst, list) and "items" in schema:
        for i, v in enumerate(inst):
            e = validate(v, schema["items"], f"{path}[{i}]")
            if e:
                return e
    if isinstance(inst, int) and not isinstance(inst, bool):
        if "minimum" in schema and inst < schema["minimum"]:
            return f"{path} < {schema['minimum']}"
        if "maximum" in schema and inst > schema["maximum"]:
            return f"{path} > {schema['maximum']}"
    return None


# ------------------------------------------------------------------ 环境（真机；测试全 fake）
class Env:
    def __init__(self, root: Path = ROOT):
        self.root = Path(root)
        self._hosts = None

    def now(self) -> float:
        return time.time()

    def hosts(self):
        if self._hosts is None:
            self._hosts = _load("hosts_for_brain_actions", "tools/factory/hosts.py", self.root)
        return self._hosts

    def primary_run(self) -> str:
        return str((_j(self.root / "config/pipeline/runs.json", {}) or {}).get("primary") or "")

    def remote(self, host: str, cmd: str, timeout: float, input: bytes | None = None) -> tuple[int, str]:
        rssh = _load("rssh_for_brain_actions", "tools/netfix/rssh.py", self.root)
        r = rssh.run_retry(host, cmd, input=input, timeout=timeout, tries=1)
        out = (r.stdout or b"").decode("utf-8", "replace") + (r.stderr or b"").decode("utf-8", "replace")
        return int(r.returncode), out[-600:]

    def producer_cmd(self, host: str, run: str, args: list[str]) -> str:
        H = self.hosts()
        return (f"cd {H.server_root(host)} && OFFLINE_SELF={host} NS_RUN={run} {H.python(host)} tools/autopilot/producer.py "
                + " ".join(shlex.quote(a) for a in args) + f" --run {shlex.quote(run)}")

    def night_once_cmd(self, host: str, run: str) -> str:
        H = self.hosts()
        root = H.video_root(host)
        return f"cd {root} && OFFLINE_SELF={host} NS_RUN={run} {H.python(host)} {root}/tools/series10_video/night.py --once"

    def server_root(self, host: str) -> str:
        return self.hosts().server_root(host)

    def local_python(self, args: list[str], timeout: float) -> tuple[int, str]:
        py = self.root / ".venv/Scripts/python.exe"
        exe = str(py) if py.is_file() else sys.executable
        r = subprocess.run([exe, *args], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                           cwd=str(self.root), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return int(r.returncode), ((r.stdout or "") + (r.stderr or ""))[-600:]

    def rq(self):
        if str(self.root / "tools/autopilot") not in sys.path:
            sys.path.insert(0, str(self.root / "tools/autopilot"))
        import restart_queue as RQ
        return RQ

    def rq_pending(self, host: str) -> list:
        return self.rq().pending(host)

    def rq_request(self, host: str, reason: str, mode: str, urgent: bool) -> dict:
        return self.rq().request(host, reason, by=WHO, urgent=urgent, mode=mode)

    def asset_requeue(self, run: str, jid: str, why: str) -> dict:
        AJ = _load("asset_jobs_for_brain_actions", "tools/pipeline/asset_jobs.py", self.root)
        return AJ.requeue(self.root, run, jid, why)

    def report(self, run: str, episode: int, step: str, what: str, fix_hint: str, blocking: bool) -> str | None:
        ri = _load("report_issue_for_brain_actions", "tools/master/report_issue.py", self.root)
        return ri.report(run=run, episode=episode, step=step, who=WHO, what=what, blocking=blocking, fix_hint=fix_hint,
                         issues=self.root / "data/pipeline/issues.jsonl", live=self.root / "docs/master/V2_LIVE.md").get("id")

    def insert_live(self, line: str) -> None:
        ri = _load("report_issue_for_brain_actions", "tools/master/report_issue.py", self.root)
        ri._insert_live(line, self.root / "docs/master/V2_LIVE.md")

    def adult_ids(self, run: str) -> set[str]:
        """剧本里 adult=true 的镜 + high_intensity 集的全部镜（失败关闭：读不到 = 空集，但 adult_overrides.force_adult 仍算）"""
        out = set()
        R = _load("runs_for_brain_actions", "tools/autopilot/runs.py", self.root)
        d = _j(R.import_path(run, self.root), {}) or {}
        for E in d.get("episodes") or []:
            try:
                ep = int(E.get("number"))
            except (TypeError, ValueError):
                continue
            for S in E.get("shots") or []:
                sid = f"ep{ep:02d}-S{S.get('index')}"
                if S.get("adult") or E.get("high_intensity"):
                    out.add(sid)
        fa = (_j(self.root / "config/adult_overrides.json", {}) or {}).get("force_adult") or {}
        out |= {str(k) for k in fa}
        return out


# ------------------------------------------------------------------ 护栏
def _shot_of(obj: str) -> str:
    return obj.split(":", 1)[-1]


def shots_in(a: dict) -> list[str]:
    out = []
    if a.get("obj"):
        out.append(_shot_of(str(a["obj"])))
    for s in a.get("shots") or []:
        out.append(str(s) if "-" in str(s) else f"ep{int(a.get('episode') or 0):02d}-{s}")
    return out


def check(a: dict, env: Env, state: dict, now: float, adult: set[str]) -> str | None:
    """→ 拒绝原因或 None。顺序：目录 → schema → 坏卡 → 删除字样 → 成人 → 到期 → 速率 → 幂等"""
    kind = a.get("kind")
    if kind not in CATALOG:
        return f"未登记的动作 {kind!r}"
    body = {k: v for k, v in a.items() if k not in ("kind", "idem")}
    e = validate(body, CATALOG[kind]["schema"])
    if e:
        return f"schema：{e}"
    blob = json.dumps(a, ensure_ascii=False)
    if any(x in blob for x in NEVER_LANES):
        return f"涉及禁区 {NEVER_LANES}"
    if a.get("host") is not None and a["host"] not in SERVERS:
        return f"host {a.get('host')} 不在 {SERVERS}"
    free_text = ("reason", "expected_effect", "text", "what", "fix_hint")       # 给人看的文案不算命令参数
    low = json.dumps({k: v for k, v in body.items() if k not in free_text}, ensure_ascii=False).lower()
    hit = [w for w in FORBIDDEN_WORDS if w in low]
    if hit:
        return f"参数含删除类字样 {hit}"
    bad = [s for s in shots_in(a) if s in adult]
    if bad:
        return f"成人镜只由项目方触发：{bad}"
    if kind == "set_night_control" and (a.get("hold_lanes") or a.get("video_lanes")) and not a.get("expires_min"):
        return "hold_lanes / video_lanes 必须带 expires_min"
    if kind in ("set_night_control", "lane_roles_phase_override") and int(a.get("expires_min") or 0) > MAX_EXPIRY_MIN:
        return f"expires_min > {MAX_EXPIRY_MIN}"
    n, win = CATALOG[kind]["rate"]
    hist = [t for t in (state.setdefault("rate", {}).get(kind) or []) if now - t < win]
    if len(hist) >= n:
        return f"速率上限：{kind} {win // 60} 分钟内已 {len(hist)} 次（上限 {n}）"
    if kind == "restart_queue_request":
        last = float((state.setdefault("restart_at", {})).get(a["host"]) or 0)
        if now - last < RESTART_GAP_S:
            return f"{a['host']} {RESTART_GAP_S // 60} 分钟内已请求过重启"
    key = idem_key(a)
    seen = float((state.setdefault("idem", {})).get(key) or 0)
    if now - seen < IDEM_WINDOW_S:
        return f"幂等：{IDEM_WINDOW_S // 60} 分钟内同样的动作已提交（{key}）"
    return None


def idem_key(a: dict) -> str:
    if a.get("idem"):
        return str(a["idem"])[:64]
    core = {k: v for k, v in a.items() if k not in ("reason", "expected_effect", "check_after_s", "idem")}
    return hashlib.sha256(json.dumps(core, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]


# ------------------------------------------------------------------ 执行
REMOTE_CLEAR_REJECTS = r"""
import json, os, time, shutil
PD = "__PD__"; H = float("__H__"); now = time.time()
p = PD + "/master_rejects.json"
rj = json.load(open(p, encoding="utf-8"))
reg = json.load(open(PD + "/registry.json", encoding="utf-8"))
passed = set()
for E in reg.get("episodes") or []:
    for S in E.get("shots") or []:
        for k, o in (S.get("objects") or {}).items():
            if (o or {}).get("status") in ("passed", "best_effort"):
                passed.add(k + ":" + str(S.get("shot")))
def ts(v):
    try:
        return float(v)
    except Exception:
        pass
    try:
        from datetime import datetime
        return datetime.fromisoformat(str(v).replace(" ", "T")).timestamp()
    except Exception:
        return None
done = []
for k, v in rj.items():
    if not isinstance(v, dict) or v.get("cleared") or k not in passed:
        continue
    t = ts(v.get("t") or v.get("at"))
    if t is None or now - t > H * 3600:
        v["cleared"] = True; v["cleared_by"] = "BRAIN"; v["cleared_at"] = time.strftime("%Y-%m-%dT%H:%M:%S"); done.append(k)
if done:
    bak = p + ".bak_brain_" + time.strftime("%Y%m%d-%H%M%S")
    shutil.copyfile(p, bak)
    tmp = p + ".tmp"
    open(tmp, "w", encoding="utf-8").write(json.dumps(rj, ensure_ascii=False, indent=1))
    os.replace(tmp, p)
print(json.dumps({"cleared": done, "backup": bool(done)}))
"""

REMOTE_NIGHT_CTRL = r"""
import json, os, time
P = "__VID__/night_control.json"; patch = json.loads('__PATCH__'); exp = "__EXP__"
try:
    c = json.load(open(P, encoding="utf-8"))
except Exception:
    c = {}
if patch.get("yield_s") is not None:
    c["yield_s"] = int(patch["yield_s"])
for k in ("video_lanes", "hold_lanes"):
    if patch.get(k) is not None:
        c[k] = list(patch[k])
if patch.get("hold_lanes") is not None:
    he = c.get("hold_expires") if isinstance(c.get("hold_expires"), dict) else {}
    c["hold_expires"] = {ln: exp for ln in patch["hold_lanes"]}
    c["hold_at"] = time.strftime("%Y-%m-%dT%H:%M:%S+09:00")
if patch.get("video_lanes") is not None:
    c["video_lanes_expires"] = exp
c["brain_at"] = time.strftime("%Y-%m-%dT%H:%M:%S+09:00"); c["brain_by"] = "BRAIN"
tmp = P + ".tmp"
open(tmp, "w", encoding="utf-8").write(json.dumps(c, ensure_ascii=False, indent=1))
os.replace(tmp, P)
print(json.dumps({k: c.get(k) for k in ("yield_s", "video_lanes", "hold_lanes", "hold_expires")}))
"""


def execute(a: dict, env: Env, run: str, now: float, dry: bool) -> str:
    kind = a["kind"]
    if dry:
        return "dry-run（没动手）"
    note = f"BRAIN：{str(a.get('reason') or '')[:160]}"
    if kind == "producer_retry":
        rc, out = env.remote(a["host"], env.producer_cmd(a["host"], run, ["retry", "--obj", a["obj"], "--by", WHO, "--note", note]), 120)
        return f"rc={rc} {out[-160:].strip()}"
    if kind == "producer_uncap":
        rc, out = env.remote(a["host"], env.producer_cmd(a["host"], run, ["uncap", "--obj", a["obj"], "--n", str(a["n"]), "--by", WHO, "--note", note]), 120)
        return f"rc={rc} {out[-160:].strip()}"
    if kind == "producer_regen":
        rc, out = env.remote(a["host"], env.producer_cmd(a["host"], run, ["regen", "--episode", str(a["episode"]), "--shots", ",".join(a["shots"]),
                                                                        "--reason", note, "--by", WHO]), 180)
        return f"rc={rc} {out[-200:].strip()}"
    if kind == "producer_reset_best_effort":
        rc, out = env.remote(a["host"], env.producer_cmd(a["host"], run, ["reset-best-effort", "--shots", ",".join(a["shots"]), "--by", WHO, "--note", note]), 180)
        return f"rc={rc} {out[-160:].strip()}"
    if kind == "producer_review_adopt":
        args = ["review-adopt", "--obj", a["obj"], "--by", WHO] + (["--n", str(a["n"])] if a.get("n") else [])
        rc, out = env.remote(a["host"], env.producer_cmd(a["host"], run, args), 120)
        return f"rc={rc} {out[-160:].strip()}"
    if kind == "clear_stale_master_rejects":
        code = REMOTE_CLEAR_REJECTS.replace("__PD__", f"data/producer/runs/{run}").replace("__H__", str(int(a["older_than_h"])))
        assert chr(92) not in code
        rc, out = env.remote(a["host"], f"cd {env.server_root(a['host'])} && python3 -", 60, input=code.encode("utf-8"))
        return f"rc={rc} {out[-200:].strip()}"
    if kind == "asset_jobs_requeue":
        res = []
        for jid in a["job_ids"]:
            try:
                res.append(env.asset_requeue(run, jid, note)["state"])
            except Exception as e:  # noqa: BLE001  一个作业失败不影响其它
                res.append(f"err {e!s}"[:60])
        tick = ""
        if a.get("tick"):
            rc, out = env.local_python(["tools/pipeline/asset_worker.py", "tick"], 600)
            tick = f"；tick rc={rc}"
        return f"requeue {dict(zip(a['job_ids'], res))}{tick}"
    if kind == "restart_queue_request":
        if env.rq_pending(a["host"]):
            return "已有待办重启请求，不重复"
        return "request " + str(env.rq_request(a["host"], note[:200], a["mode"], bool(a.get("urgent"))).get("id"))
    if kind == "night_once":
        rc, out = env.remote(a["host"], env.night_once_cmd(a["host"], run), 180)
        return f"rc={rc} {out[-160:].strip()}"
    if kind == "set_night_control":
        exp = jst(now + int(a["expires_min"]) * 60, "%Y-%m-%dT%H:%M:%S+09:00")
        patch = {k: a.get(k) for k in ("yield_s", "video_lanes", "hold_lanes")}
        code = REMOTE_NIGHT_CTRL.replace("__VID__", f"data/pipeline/runs/{run}/video").replace("__PATCH__", json.dumps(patch)).replace("__EXP__", exp)
        assert chr(92) not in code
        rc, out = env.remote(a["host"], f"cd {env.server_root(a['host'])} && python3 -", 60, input=code.encode("utf-8"))
        return f"rc={rc} {out[-200:].strip()}"
    if kind == "lane_roles_phase_override":
        p = env.root / "data/pipeline/lane_roles_override.json"
        d = _j(p, {}) or {}
        d.setdefault(run, {})[str(int(a["episode"]))] = {"phase": a["phase"], "expires_at": jst(now + int(a["expires_min"]) * 60, "%Y-%m-%dT%H:%M:%S+09:00"),
                                                        "by": WHO, "at": jst(now, "%Y-%m-%dT%H:%M:%S+09:00"), "why": str(a.get("reason") or "")[:160]}
        _jw(p, d)
        res = ["local"]
        import base64
        b64 = base64.b64encode(json.dumps(d, ensure_ascii=False).encode("utf-8")).decode("ascii")
        for host in SERVERS:      # 两台的读方（producer / night）各读本机文件 → 同步过去；失败只记
            try:
                code = ("import json, os, base64; p='data/pipeline/lane_roles_override.json'; d=json.loads(base64.b64decode('" + b64
                        + "').decode('utf-8')); t=p+'.tmp'; open(t,'w',encoding='utf-8').write(json.dumps(d, ensure_ascii=False)); os.replace(t,p); print('ok')")
                assert chr(92) not in code
                rc, out = env.remote(host, f"cd {env.server_root(host)} && python3 -", 30, input=code.encode("utf-8"))
                res.append(f"{host} rc={rc}")
            except Exception as e:  # noqa: BLE001  # arch-ok: 同步失败只记，本地文件已写
                res.append(f"{host} err {e!r}"[:60])
        return "override " + ", ".join(res)
    if kind == "report_issue":
        iid = env.report(run, int(a["episode"]), a["step"], a["what"][:900], a["fix_hint"][:300], bool(a["blocking"]))
        return f"卡点 {iid}"
    if kind == "note_to_owner":
        icon = {"red": "🔴", "yellow": "🟡", "green": "🟢"}[a["level"]]
        line = f"{jst(now, '%m-%d %H:%M')} {icon} BRAIN：{a['text'][:400]}"
        p = env.root / OUT_REL / "owner_notes.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        env.insert_live(f"{jst(now, '%H:%M')} {icon} BRAIN：{a['text'][:300]}")
        return "noted"
    if kind == "no_action":
        return "ok"
    return f"没有执行器：{kind}"


def run(actions: list[dict], env: Env | None = None, dry: bool = True, snapshot_hash: str | None = None, by: str = WHO,
        max_actions: int | None = None) -> list[dict]:
    """逐个 check → execute → 记 decisions.jsonl。返回每个动作的记录（含 rejected / result）"""
    env = env or Env()
    now = env.now()
    run_id = env.primary_run()
    st_path = env.root / OUT_REL / "state.json"
    st = _j(st_path, {}) or {}
    adult = env.adult_ids(run_id)
    out = []
    for i, a in enumerate(actions or []):
        if not isinstance(a, dict):
            a = {"kind": str(a)}
        rec = {"at": jst(now, "%Y-%m-%d %H:%M:%S+09:00"), "t": now, "by": by, "snapshot_hash": snapshot_hash, "kind": a.get("kind"),
               "params": {k: v for k, v in a.items() if k != "kind"}, "dry": dry}
        if max_actions is not None and i >= max_actions:
            rec["rejected"] = f"本轮动作数超过上限 {max_actions}"
        else:
            rec["rejected"] = check(a, env, st, now, adult)
        if rec["rejected"]:
            rec["result"] = "拒绝：" + rec["rejected"]
        else:
            try:
                rec["result"] = execute(a, env, run_id, now, dry)
            except subprocess.TimeoutExpired:
                rec["result"] = "失败：超时"
            except Exception as e:  # noqa: BLE001  一个动作失败只记，不影响其它动作
                rec["result"] = f"失败 {e!r}"[:200]
            if not dry:
                st.setdefault("rate", {}).setdefault(a["kind"], []).append(now)
                st["rate"][a["kind"]] = [t for t in st["rate"][a["kind"]] if now - t < CATALOG[a["kind"]]["rate"][1]]
                st.setdefault("idem", {})[idem_key(a)] = now
                if a["kind"] == "restart_queue_request" and not str(rec["result"]).startswith("已有"):
                    st.setdefault("restart_at", {})[a["host"]] = now
        out.append(rec)
        _append(env.root / OUT_REL / "decisions.jsonl", rec)
    if not dry:
        st["idem"] = {k: v for k, v in (st.get("idem") or {}).items() if now - v < 6 * 3600}
        _jw(st_path, st)
    return out


def _append(p: Path, rec: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def catalog_text() -> str:
    """给系统提示词用的动作目录（稳定文本，可缓存）"""
    L = []
    for k, v in CATALOG.items():
        props = {p: s for p, s in v["schema"]["properties"].items() if p not in COMMON}
        L.append(f"- {k}（风险 {v['risk']}，上限 {v['rate'][0]} 次/{v['rate'][1] // 60} 分钟）：{v['desc']}\n  参数：{json.dumps(props, ensure_ascii=False)}")
    return "\n".join(L)


def tool_defs() -> list[dict]:
    """Anthropic tools（strict）：每个动作一个工具，输入 = 该动作参数（含 reason / expected_effect / check_after_s）"""
    return [{"name": k, "description": v["desc"], "strict": True, "input_schema": v["schema"]} for k, v in CATALOG.items()]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="大脑动作执行器（白名单）")
    ap.add_argument("cmd", choices=["run", "catalog", "tools"])
    ap.add_argument("actions", nargs="?", default="[]", help="JSON 动作列表或 @文件路径")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--snapshot-hash", default=None)
    ap.add_argument("--by", default=WHO)
    ap.add_argument("--max", type=int, default=None)
    a = ap.parse_args(argv)
    if a.cmd == "catalog":
        print(catalog_text())
        return 0
    if a.cmd == "tools":
        print(json.dumps(tool_defs(), ensure_ascii=False, indent=1))
        return 0
    txt = Path(a.actions[1:]).read_text(encoding="utf-8") if a.actions.startswith("@") else a.actions
    acts = json.loads(txt)
    if isinstance(acts, dict):
        acts = acts.get("actions") or [acts]
    res = run(acts, dry=a.dry_run, snapshot_hash=a.snapshot_hash, by=a.by, max_actions=a.max)
    for r in res:
        print(json.dumps({k: r[k] for k in ("kind", "result")}, ensure_ascii=False))
    try:
        import brain_status
        brain_status.write(ROOT)
    except Exception:  # noqa: BLE001  # arch-ok: 状态页生成失败不影响动作结果
        pass
    return 0 if all(not r.get("rejected") for r in res) else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    raise SystemExit(main())
