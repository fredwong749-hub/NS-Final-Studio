"""发版流水线自动化（W17 RELEASE-AUTO，总调度 MASTER-WSL 11-03；L-160 / L-163 项目方：“自动化运行起来，把代码修一下，
把所有自动化写在代码上，少用 Agent 来推”）。把总调度手工做的发版动作编成代码，挂在 resident_sync loop 上每拍检查。

release_once（一拍）：
  输入 data/system_versions/release_request.json（schema nsfs.release_request/1）：
    {"schema": "nsfs.release_request/1", "list": "docs/system_versions/LIST_cutB.txt", "base": "HEAD"（可省）,
     "reviews": [{"group": "G2", "verdict": "可入", "p0": []}, ...], "requested_by": "MASTER-WSL", "at": "...",
     "deploy": true, "handover": true, "verify_shot": 8（可省，默认 release.json）, "verify_run": null}
  所有 group verdict=可入 且 p0 为空 → 临时 GIT_INDEX_FILE 按清单拼树（system_version.build_tree_from_list，清单项可写 path@blob）
  → system_version cut --dry --tree（NS_CUT_PYTEST_N = release.json pytest_n，默认 4）→ 全绿则 cut --tree（commit / tag / push 走现有实现）
  → deploy=true 则 deploy --verify（release.json hosts，两台）→ release_result.json + CHANGELOG 一行 + V2_LIVE 一行。
  任何一步红 → report_issue（who=release_tick，阻断）并停，不绕闸门；同一份请求（内容 sha）只跑一次，改请求才会再跑。
  同一时间只允许一个 release：cut_lock 活跃 = 等；release_lock.json（O_EXCL）= 另一个 release 在跑。
handover_once（L-152 换代）：release_result.deployed=true 且请求 handover=true 且 runs.json primary 的 sop_gate 阶段（任一集）≥ 出图 →
  ① 笔记本 ops/autostart/restart_producer.ps1 -Run <primary>（W1 identity：新代码自交接到主剧）；② 服务器 resident_sync.request_restart
  (host, 'L-152 handover') 走 restart_queue；③ 停遗留实验进程（release.json handover.legacy_procs：bench2 / bakeoff），只 TERM 不删，
  受保护进程（sentinel S16 清单 + handover.protect）永不停，写 data/system_versions/handover_killed.jsonl；④ 每步写 V2_LIVE，失败 report_issue。
  每个 release 只尝试一次（handover.attempted）；手工入口 system_version.py handover --dry|--apply [--force]。
逻辑都调用 tools/qa/system_version.py（拼树 / cut / deploy / cut_lock / release_cfg），本文件不复制。
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REQ_REL = "data/system_versions/release_request.json"
RES_REL = "data/system_versions/release_result.json"
LOCK_REL = "data/system_versions/release_lock.json"
KILLED_REL = "data/system_versions/handover_killed.jsonl"
CHANGELOG_REL = "docs/CHANGELOG_AGENTS.md"
LIVE_REL = "docs/master/V2_LIVE.md"
ISSUES_REL = "data/pipeline/issues.jsonl"
REQ_SCHEMA = "nsfs.release_request/1"
RES_SCHEMA = "nsfs.release_result/1"
APPROVED = {"可入"}
# W17b P1-3（A17 第 28 轮）：L-157“G2–G7 逐组 Fable 复审无 P0 才 cut”。必须齐的组 = release.json required_groups（缺省本表）
# ∪ 请求里写的 required_groups；请求只能加组、不能减组。缺任一组（没写 / verdict≠可入 / 有 P0）= not_approved，不发
DEFAULT_REQUIRED_GROUPS = ["G2", "G3", "G4", "G5", "G6", "G7"]
TERMINAL = {"done", "failed", "not_approved", "invalid"}
LOCK_TTL_S = 6 * 3600
WHO = "release_tick"
STAGES_FALLBACK = ["剧本", "导入闸门", "资产就绪", "提示词", "出图", "出图检测", "尾帧", "视频", "整集预览"]
PROBE_PS = ("for d in /proc/[0-9]*; do p=${d#/proc/}; a=$(tr '\\0' ' ' < $d/cmdline 2>/dev/null); [ -n \"$a\" ] || continue; "
            "pp=$(awk '{print $4}' $d/stat 2>/dev/null); c=$(readlink $d/cwd 2>/dev/null); printf '%s\\t%s\\t%s\\t%s\\n' \"$p\" \"$pp\" \"$c\" \"$a\"; done")
DEFAULT_PROTECT = [r"producer\.py", r"night\.py", r"fwd\.py", r"ComfyUI", r"main\.py --listen", r"resident_sync\.py", r"sshd"]

_MODS: dict[str, object] = {}


def _mod(rel: str, name: str):
    if name not in _MODS:
        spec = importlib.util.spec_from_file_location(name, ROOT / rel)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        _MODS[name] = m
    return _MODS[name]


def load_sv():
    return _mod("tools/qa/system_version.py", "ns_system_version_rt")


def _issue_mod():
    return _mod("tools/master/report_issue.py", "ns_report_issue_rt")


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _j(p: Path, d=None):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):  # arch-ok: 文件不在 / 坏 = 默认值（请求 / 结果由调用方判）
        return d


def _wj(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + f".tmp{os.getpid()}")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    os.replace(tmp, p)


def _primary(root: Path) -> str:
    return str((_j(root / "config/pipeline/runs.json", {}) or {}).get("primary") or "unknown")


# ---------------------------------------------------------------- 请求
def read_request(root: Path = ROOT) -> dict | None:
    return _j(root / REQ_REL)


def validate_request(req) -> list[str]:
    if not isinstance(req, dict):
        return ["请求不是 JSON 对象"]
    bad = []
    if req.get("schema") not in (None, REQ_SCHEMA):
        bad.append(f"schema 应为 {REQ_SCHEMA}")
    if not isinstance(req.get("list"), str) or not req.get("list"):
        bad.append("缺 list（清单文件路径，仓库相对）")
    rv = req.get("reviews")
    if not isinstance(rv, list) or not rv:
        bad.append("缺 reviews（至少一组复审结论）")
    elif not all(isinstance(x, dict) and x.get("group") for x in rv):
        bad.append("reviews 每项要有 group")
    rg = req.get("required_groups")
    if rg is not None and (not isinstance(rg, list) or not all(isinstance(x, str) and x for x in rg)):
        bad.append("required_groups 要是组名列表（例 [\"G2\", …, \"G7\"]）")
    return bad


def required_groups(req: dict, cfg: dict | None = None) -> list[str]:
    """必须齐的复审组：release.json required_groups（缺省 G2–G7）∪ 请求 required_groups（W17b P1-3）"""
    base = (cfg or {}).get("required_groups")
    base = list(base) if isinstance(base, list) and base else list(DEFAULT_REQUIRED_GROUPS)
    extra = req.get("required_groups") if isinstance(req.get("required_groups"), list) else []
    return list(dict.fromkeys([*base, *[str(x) for x in extra]]))


def review_blockers(req: dict, cfg: dict | None = None) -> list[str]:
    """不能发的理由：必须齐的组缺复审（W17b P1-3）、任一组 verdict 不是“可入”，或 p0 不空"""
    have = {str(r.get("group")) for r in req.get("reviews") or [] if isinstance(r, dict)}
    miss = [g for g in required_groups(req, cfg) if g not in have]
    out = [f"缺复审组 {'、'.join(miss)}（必须齐：{'、'.join(required_groups(req, cfg))}）"] if miss else []
    for r in req.get("reviews") or []:
        if r.get("verdict") not in APPROVED:
            out.append(f"{r.get('group')}：verdict={r.get('verdict')!r}（要“可入”）")
        if r.get("p0"):
            out.append(f"{r.get('group')}：还有 P0 {len(r['p0'])} 条：{'；'.join(map(str, r['p0']))[:200]}")
    return out


# ---------------------------------------------------------------- 互斥
def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":       # Windows 的 os.kill(pid, 0) 会真的结束进程，只能用 tasklist
        try:
            r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True, timeout=30)
            return str(pid) in (r.stdout or "")
        except (OSError, subprocess.TimeoutExpired):  # arch-ok: 查不到当作还活着（宁可等，不抢锁）
            return True
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def acquire_lock(root: Path, what: str) -> dict | None:
    """release_lock.json（O_EXCL）：拿到 → 锁记录；别人持有且未过期 / 进程还活着 → None。过期或持有进程已死 → 接管"""
    p = root / LOCK_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    rec = {"pid": os.getpid(), "t": time.time(), "at": _now(), "what": what}
    for _ in range(2):
        try:
            fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        except FileExistsError:
            cur = _j(p, {}) or {}
            stale = time.time() - float(cur.get("t") or 0) > LOCK_TTL_S or not _pid_alive(int(cur.get("pid") or 0))
            if not stale:
                return None
            p.unlink(missing_ok=True)       # 过期锁：接管（只删锁文件本身）
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False))
        return rec
    return None


def release_lock(root: Path, rec: dict | None) -> None:
    p = root / LOCK_REL
    cur = _j(p, {}) or {}
    if rec and cur.get("pid") == rec.get("pid") and cur.get("t") == rec.get("t"):
        p.unlink(missing_ok=True)


def lock_holder(root: Path = ROOT) -> dict | None:
    cur = _j(root / LOCK_REL)
    if not cur:
        return None
    if time.time() - float(cur.get("t") or 0) > LOCK_TTL_S or not _pid_alive(int(cur.get("pid") or 0)):
        return None
    return cur


# ---------------------------------------------------------------- cut / deploy 的执行器（真实 = 子进程调 system_version CLI；测试打桩）
class CliRunner:
    """W17b P1-1（A17 第 28 轮）：以前 subprocess.run(timeout=) 超时只杀直接子进程 = .venv 启动器 stub，真 cut / deploy 孤儿继续跑
    （可能在已记 failed 之后仍 commit / push / 推服务器）。现在走 system_version.run_watched：超时 _kill_tree 杀整棵进程树
    （W37：Windows 按身份核对后逐个 taskkill /PID /F、不用 /T；POSIX 新会话 killpg）。不做 CPU 僵死判断（cpu_fn 恒 None）——cut 里的 pytest 自己有 xdist 僵死自愈"""

    def __init__(self, sv, cfg: dict, root: Path = ROOT, poll_s: float = 30):
        self.sv, self.cfg, self.root, self.poll_s = sv, cfg, root, poll_s

    def _run(self, args: list[str], timeout: int, extra_env: dict | None = None) -> dict:
        fd, rp = tempfile.mkstemp(prefix="nsfs_release_", suffix=".json")
        os.close(fd)
        Path(rp).unlink(missing_ok=True)
        env = {**self.sv.ENV, **(extra_env or {})}
        cmd = [self.sv.PY, str(self.root / "tools/qa/system_version.py"), *args, "--report-json", rp]
        rc, out, info = self.sv.run_watched(cmd, timeout, cwd=self.root, env=env, stall_s=float(timeout) + 3600, poll_s=self.poll_s,
                                            cpu_fn=lambda _pid: None)
        if info.get("timeout"):
            rc, out = 124, f"超时 {timeout}s，已杀整棵进程树（W17b P1-1）\n" + (out or "")[-2000:]
        rep = _j(Path(rp)) or {}
        Path(rp).unlink(missing_ok=True)
        if not rep:
            rep = {"ok": False, "reason": f"没拿到报告（rc={rc}）：{out[-400:]}"}
        rep["rc"] = rc
        return rep

    def cut(self, tree: str, dry: bool) -> dict:
        env = {"TZ": "JST-9", "NS_CUT_PYTEST_N": str(int(self.cfg.get("pytest_n") or 4)),
               "NS_CUT_XDIST_STALL_S": str(float(self.cfg.get("xdist_stall_min") or 10) * 60)}
        return self._run(["cut", "--tree", tree, *(["--dry"] if dry else [])], int(self.cfg.get("cut_timeout_s") or 4 * 3600), env)

    def deploy(self, sv_id: str, hosts: list[str], verify_shot, verify_run) -> dict:
        args = ["deploy", sv_id, "--hosts", ",".join(hosts)]
        if verify_shot:
            args += ["--verify-shot", str(int(verify_shot))]
        if verify_run:
            args += ["--verify-run", str(verify_run)]
        rep = self._run(args, int(self.cfg.get("deploy_timeout_s") or 3 * 3600))
        hs = rep.get("hosts") or {}
        rep["ok"] = rep.get("rc") == 0 and bool(hs) and all(x.get("ok") for x in hs.values()) and bool((rep.get("verify") or {}).get("ok"))
        if not rep["ok"] and not rep.get("reason"):
            bad = [h for h, x in hs.items() if not x.get("ok")]
            rep["reason"] = (f"部署失败：{bad}" if bad else "") + ("" if (rep.get("verify") or {}).get("ok")
                                                                     else f" verify 不过：{str((rep.get('verify') or {}).get('reason') or rep.get('verify'))[:300]}")
        return rep


def _brief(rep: dict) -> dict:
    keep = ("ok", "id", "tree", "commit", "reason", "rc", "xdist_heal", "remote_push", "files", "drift_during_cut", "dry")
    out = {k: rep[k] for k in keep if k in rep}
    if rep.get("gates"):
        out["gates"] = [{"id": g.get("id"), "ok": g.get("ok"), "detail": str(g.get("detail") or "")[:200]} for g in rep["gates"]]
    if rep.get("hosts") is not None:
        out["hosts"] = {h: {"ok": x.get("ok"), "reason": str(x.get("reason") or x.get("error") or "")[:200]} for h, x in (rep.get("hosts") or {}).items()}
        out["verify"] = {k: (rep.get("verify") or {}).get(k) for k in ("ok", "reason")}
    return out


# ---------------------------------------------------------------- 记录
def live(root: Path, line: str) -> None:
    try:
        _issue_mod()._insert_live(f"{time.strftime('%H:%M')} {line}", root / LIVE_REL)
    except OSError:  # arch-ok: V2_LIVE 写不进去不拦发版（结果文件是权威）
        pass


def issue(root: Path, step: str, what: str, hint: str = "") -> str | None:
    rec = _issue_mod().report(_primary(root), 0, step, WHO, what, True, hint, issues=root / ISSUES_REL, live=root / LIVE_REL)
    return rec.get("id")


def changelog(root: Path, line: str) -> None:
    p = root / CHANGELOG_REL
    if not p.exists():
        return
    txt = p.read_text(encoding="utf-8")
    with open(p, "a", encoding="utf-8") as f:
        f.write(("" if txt.endswith("\n") else "\n") + line + "\n")


# ---------------------------------------------------------------- release_once
def release_once(root: Path = ROOT, sv=None, runner=None, cfg: dict | None = None) -> dict:
    sv = sv or load_sv()
    cfg = cfg or sv.release_cfg(root)
    if not cfg.get("enabled", True):
        return {"status": "disabled"}
    rp = root / REQ_REL
    if not rp.exists():
        return {"status": "idle"}
    raw = rp.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()[:16]
    prev = _j(root / RES_REL, {}) or {}
    if prev.get("request_sha") == sha and prev.get("status") in TERMINAL | {"running"}:
        if prev.get("status") != "running" or lock_holder(root):
            return {"status": "already", "prev_status": prev.get("status"), "request_sha": sha}
    res = {"schema": RES_SCHEMA, "request_sha": sha, "status": "running", "step": "validate", "started_at": _now(),
           "steps": {}, "deployed": False}
    try:
        req = json.loads(raw.decode("utf-8-sig"))
    except ValueError as e:
        req = None
        probs = [f"不是合法 JSON：{e}"]
    else:
        probs = validate_request(req)
    if probs:
        res.update(status="invalid", reason="；".join(probs), finished_at=_now(), request=req)
        res["issue_id"] = issue(root, "release:validate", f"release_request.json 不合格，没跑：{res['reason']}", "按 nsfs.release_request/1 改请求")
        _wj(root / RES_REL, res)
        return res
    res.update(request=req, handover_requested=bool(req.get("handover")), deploy_requested=bool(req.get("deploy")))
    res["required_groups"] = required_groups(req, cfg)
    blk = review_blockers(req, cfg)
    if blk:      # 还没审完不是“红”：只记结果，不登记卡点；请求改了（审完）会重新跑
        res.update(status="not_approved", reason="；".join(blk), finished_at=_now())
        _wj(root / RES_REL, res)
        return res
    lk_cut = sv.cut_locked()
    if lk_cut:
        return {"status": "busy", "why": f"cut_lock 活跃（{lk_cut.get('sv')}，{lk_cut.get('note')}）", "request_sha": sha}
    lk = acquire_lock(root, f"release {sha}")
    if not lk:
        return {"status": "busy", "why": f"另一个 release 在跑：{lock_holder(root)}", "request_sha": sha}
    runner = runner or CliRunner(sv, cfg, root)
    try:
        _wj(root / RES_REL, res)

        def fail(step: str, reason: str) -> dict:
            res.update(status="failed", step=step, reason=str(reason)[:1000], finished_at=_now())
            res["issue_id"] = issue(root, f"release:{step}", f"发版流水线在“{step}”红，已停（不绕闸门）：{str(reason)[:300]}",
                                    "修好后改 release_request.json（内容一变就重新跑）")
            _wj(root / RES_REL, res)
            return res

        res["step"] = "tree"
        try:
            bt = sv.build_tree_from_list(root / req["list"], req.get("base") or "HEAD", repo=root)
        except Exception as e:  # noqa: BLE001
            return fail("tree", f"按清单拼树失败：{e}")
        res["tree"], res["steps"]["tree"] = bt["tree"], bt
        _wj(root / RES_REL, res)
        for step, dry in (("cut --dry", True), ("cut", False)):
            res["step"] = step
            _wj(root / RES_REL, res)
            try:
                rep = runner.cut(bt["tree"], dry)
            except Exception as e:  # noqa: BLE001
                return fail(step, f"{type(e).__name__}: {e}")
            res["steps"][step] = _brief(rep)
            if not rep.get("ok"):
                return fail(step, rep.get("reason") or f"rc={rep.get('rc')}")
        res.update(sv=rep.get("id"), commit=rep.get("commit"))
        if req.get("deploy"):
            res["step"] = "deploy"
            _wj(root / RES_REL, res)
            hosts = list(req.get("hosts") or cfg.get("hosts") or [])
            try:
                dp = runner.deploy(res["sv"], hosts, req.get("verify_shot") or cfg.get("verify_shot"), req.get("verify_run") or cfg.get("verify_run"))
            except Exception as e:  # noqa: BLE001
                return fail("deploy", f"{type(e).__name__}: {e}")
            res["steps"]["deploy"] = _brief(dp)
            if not dp.get("ok"):
                return fail("deploy", dp.get("reason") or "deploy / verify 不过")
            res["deployed"], res["deployed_hosts"] = True, hosts
        res.update(status="done", step="done", finished_at=_now())
        _wj(root / RES_REL, res)
        groups = "、".join(str(r.get("group")) for r in req.get("reviews") or [])
        dep = f"已部署 {'、'.join(res.get('deployed_hosts') or [])} 并 verify 通过" if res["deployed"] else "只入 git，不 deploy"
        changelog(root, f"- {_now()[:16].replace('T', ' ')} 发版 {res['sv']}（release_tick 自动，W17 / K-OPS-V01）：清单 {req['list']}"
                        f"（{bt['items']} 项），tree {bt['tree'][:8]}，commit {str(res.get('commit') or '')[:7]}；复审 {groups} 全部可入、P0 0；"
                        f"闸门全绿（cut --dry + cut）；{dep}；请求人 {req.get('requested_by') or '—'}。")
        live(root, f"✅ 发版（{WHO}）：{res['sv']} tree {bt['tree'][:8]} commit {str(res.get('commit') or '')[:7]}，{dep}"
                   + ("；换代（L-152）待条件满足后自动执行" if req.get("handover") else ""))
        return res
    finally:
        release_lock(root, lk)


# ---------------------------------------------------------------- handover（L-152）
def stage_of(root: Path, run: str) -> dict:
    """runs.json primary 在 sop_gate 唯一阶段视图里的位置：best = 走得最远的一集（与 promote 的“任一集”同口径）"""
    sg = _mod("tools/master/sop_gate.py", "ns_sop_gate_rt")
    v = sg.stage_view(run, root)
    eps = v.get("episodes") or []
    best = max(eps, key=lambda e: e["stage_index"], default=None)
    return {"stages": list(v.get("stages") or sg.STAGES), "best_index": best["stage_index"] if best else -1,
            "best_stage": best["stage"] if best else None, "best_episode": best["episode"] if best else None,
            "run_stage": v.get("stage"), "episodes": len(eps)}


def _protect_patterns(root: Path, cfg_h: dict) -> list[str]:
    pats = list(DEFAULT_PROTECT) + list(cfg_h.get("protect") or [])
    try:
        import yaml
        doc = yaml.safe_load((root / "config/policies/sentinel.yaml").read_text(encoding="utf-8")) or {}
        procs = ((((doc.get("items") or {}).get("S16_laptop_procs") or {}).get("value") or {}).get("procs") or {})
        pats += [str(x.get("match")) for x in procs.values() if isinstance(x, dict) and x.get("match")]
    except Exception:  # noqa: BLE001  # arch-ok: 读不到 sentinel 清单 = 只用默认保护表
        pass
    return pats


def parse_probe(raw: str) -> list[dict]:
    out = []
    for ln in raw.splitlines():
        parts = ln.split("\t", 3)
        if len(parts) == 4 and parts[0].isdigit():
            out.append({"pid": int(parts[0]), "ppid": int(parts[1]) if parts[1].isdigit() else 0, "cwd": parts[2], "args": parts[3].strip()})
    return out


def select_legacy(procs: list[dict], entry: dict, protect: list[str]) -> list[dict]:
    hit = []
    for p in procs:
        if p["pid"] <= 1 or not re.search(entry["match"], p["args"]):
            continue
        if entry.get("cwd_match") and not re.search(entry["cwd_match"], p["cwd"] or ""):
            continue
        if any(re.search(x, p["args"]) for x in protect):
            continue
        hit.append(p)
    return hit


def handover_plan(root: Path, cfg: dict, stage_fn=None, force: bool = False) -> dict:
    res = _j(root / RES_REL, {}) or {}
    req = res.get("request") or {}
    hcfg = cfg.get("handover") or {}
    run = _primary(root)
    min_stage = hcfg.get("min_stage") or "出图"
    try:
        st = (stage_fn or stage_of)(root, run)
    except Exception as e:  # noqa: BLE001
        st = {"error": f"{type(e).__name__}: {e}"[:300], "best_index": -1}
    stages = st.get("stages") or STAGES_FALLBACK
    need = stages.index(min_stage) if min_stage in stages else 4
    ho = res.get("handover") or {}
    conds = [
        {"id": "deployed", "ok": res.get("deployed") is True and res.get("status") == "done",
         "detail": f"release_result：status={res.get('status')} deployed={res.get('deployed')} sv={res.get('sv')}"},
        {"id": "handover_requested", "ok": bool(req.get("handover")), "detail": f"请求 handover={req.get('handover')}"},
        {"id": "stage", "ok": int(st.get("best_index", -1)) >= need,
         "detail": (f"{run} 走得最远的一集 ep{st.get('best_episode')} 在“{st.get('best_stage')}”（要 ≥ “{min_stage}”；全剧最靠前：{st.get('run_stage')}）"
                    if "error" not in st else f"{run} 阶段读不到：{st['error']}")},
        {"id": "not_attempted", "ok": force or not ho.get("attempted"),
         "detail": f"本版换代{'已于 ' + str(ho.get('at')) + ' 尝试过（--force 重做）' if ho.get('attempted') else '还没做过'}"},
    ]
    hosts = list(res.get("deployed_hosts") or cfg.get("hosts") or [])
    ps1 = hcfg.get("laptop_ps1") or "ops/autostart/restart_producer.ps1"
    legacy = list(hcfg.get("legacy_procs") or [])
    steps = [
        {"n": 1, "id": "laptop_producer", "desc": f"笔记本：powershell -File {ps1} -Run {run}（新代码自交接到主剧，W1 identity）"},
        {"n": 2, "id": "server_restart", "desc": "服务器：" + "、".join(f"resident_sync.request_restart({h!r}, reason='L-152 handover')" for h in hosts)
         + " → restart_queue 排空后合并执行"},
        {"n": 3, "id": "stop_legacy", "desc": "停遗留实验进程（只 TERM 不删，受保护进程不停，记 " + KILLED_REL + "）："
         + "；".join(f"{e.get('host')} /{e.get('match')}/" + (f" cwd~/{e['cwd_match']}/" if e.get("cwd_match") else "") + (f"（{e.get('name')}）" if e.get("name") else "") for e in legacy)},
        {"n": 4, "id": "record", "desc": "每步结果写 docs/master/V2_LIVE.md；失败 report_issue（who=release_tick，阻断）；结果写 release_result.json handover"},
    ]
    return {"run": run, "sv": res.get("sv"), "conditions": conds, "ready": all(c["ok"] for c in conds), "steps": steps,
            "hosts": hosts, "ps1": ps1, "legacy": legacy, "stage": st}


def _laptop_restart(root: Path, ps1: str, run: str) -> dict:
    exe = "powershell.exe"
    try:
        r = subprocess.run([exe, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(root / ps1), "-Run", run], cwd=root,
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600, stdin=subprocess.DEVNULL)
        out = ((r.stdout or "") + (r.stderr or "")).strip()
        return {"ok": r.returncode == 0 and "restarted" in out, "rc": r.returncode, "out": out[-400:]}
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"[:300]}


def handover_once(root: Path = ROOT, apply: bool = False, sv=None, rs=None, stage_fn=None, laptop_fn=None, cfg: dict | None = None,
                  force: bool = False) -> dict:
    sv = sv or load_sv()
    cfg = cfg or sv.release_cfg(root)
    plan = handover_plan(root, cfg, stage_fn, force)
    plan["mode"] = "apply" if apply else "dry"
    if not apply:
        plan["ok"] = True
        return plan
    if not plan["ready"]:
        plan.update(ok=True, skipped="条件不满足，不动：" + "；".join(c["id"] for c in plan["conditions"] if not c["ok"]))
        return plan
    lk = acquire_lock(root, "handover")
    if not lk:
        plan.update(ok=True, skipped=f"release / handover 正在跑：{lock_holder(root)}")
        return plan
    try:
        res = _j(root / RES_REL, {}) or {}
        ho = {"attempted": True, "at": _now(), "steps": []}
        res["handover"] = ho
        _wj(root / RES_REL, res)
        run = plan["run"]
        rs_box = {"rs": rs}

        def _rs():
            if rs_box["rs"] is None:
                rs_box["rs"] = sv.load_rs()
            return rs_box["rs"]

        def step1() -> dict:
            return {"id": "laptop_producer", **(laptop_fn or _laptop_restart)(root, plan["ps1"], run)}

        def step2() -> dict:
            r2 = {"id": "server_restart", "ok": True, "requests": {}}
            for h in plan["hosts"]:
                try:
                    r2["requests"][h] = _rs().request_restart(h, "L-152 handover", by=WHO)
                except Exception as e:  # noqa: BLE001
                    r2["ok"] = False
                    r2["requests"][h] = {"error": f"{type(e).__name__}: {e}"[:300]}
            return r2

        def step3() -> dict:
            protect = _protect_patterns(root, cfg.get("handover") or {})
            r3 = {"id": "stop_legacy", "ok": True, "killed": [], "none_found": []}
            for e in plan["legacy"]:
                h = e.get("host")
                try:
                    procs = parse_probe(_rs().ssh(h, PROBE_PS, timeout=120, tries=2).decode("utf-8", "replace"))
                    hit = select_legacy(procs, e, protect)
                    if not hit:
                        r3["none_found"].append(f"{h}:{e.get('name') or e.get('match')}")
                        continue
                    pids = " ".join(str(p["pid"]) for p in hit)
                    out = _rs().ssh(h, f"kill -TERM {pids}; sleep 5; for p in {pids}; do kill -0 $p 2>/dev/null && echo STILL $p || echo STOPPED $p; done",
                                    timeout=120, tries=1).decode("utf-8", "replace")
                    state = dict(reversed(x.split()) for x in out.splitlines() if x.startswith(("STILL", "STOPPED")) and len(x.split()) == 2)
                    for p in hit:
                        rec = {"at": _now(), "host": h, "pid": p["pid"], "ppid": p["ppid"], "cwd": p["cwd"], "args": p["args"][:400],
                               "signal": "TERM", "result": state.get(str(p["pid"]), "unknown"), "by": WHO, "sv": plan["sv"],
                               "name": e.get("name"), "note": "L-152 只停不删；回退命令见 docs/master/DEPLOY_V2_PRODUCER.md §6.3"}
                        _append(root / KILLED_REL, rec)
                        r3["killed"].append(rec)
                        if rec["result"] != "STOPPED":
                            r3["ok"] = False
                except Exception as ex:  # noqa: BLE001
                    r3["ok"] = False
                    r3.setdefault("errors", []).append(f"{h}: {type(ex).__name__}: {ex}"[:300])
            return r3

        # ④ 每步写 V2_LIVE，失败 report_issue。W17b P1-5（A17 第 28 轮）：L-152 口径“起 V2 之后再停旧”——任一步失败即停，
        # 后面的步不做（记 skipped），写 handover.aborted_at
        names = {"laptop_producer": "笔记本 producer 交接", "server_restart": "服务器重启请求", "stop_legacy": "停遗留实验进程"}
        detail_fn = {"laptop_producer": lambda s: s.get("out") or s.get("error") or "",
                     "server_restart": lambda s: "、".join(f"{h}:{(v or {}).get('id') or (v or {}).get('error')}" for h, v in s["requests"].items()),
                     "stop_legacy": lambda s: (f"停 {len(s['killed'])} 个：" + "、".join(f"{k['host']}:{k['pid']}={k['result']}" for k in s["killed"])
                                               + (f"；没找到 {s['none_found']}" if s["none_found"] else "") + (f"；错误 {s.get('errors')}" if s.get("errors") else ""))}
        seq = [("laptop_producer", step1), ("server_restart", step2), ("stop_legacy", step3)]
        for i, (sid, fn) in enumerate(seq):
            try:
                s = fn()
            except Exception as ex:  # noqa: BLE001
                s = {"id": sid, "ok": False, "error": f"{type(ex).__name__}: {ex}"[:300]}
            ho["steps"].append(s)
            try:
                detail = detail_fn[sid](s)
            except Exception:  # noqa: BLE001  # arch-ok: 步内抛异常时没有 requests / killed 字段，退回 error
                detail = s.get("error") or ""
            live(root, f"{'✅' if s.get('ok') else '❌'} 换代 L-152（{WHO}）{plan['sv']} {names[sid]}：{str(detail)[:300]}")
            if not s.get("ok"):
                rest = [x for x, _f in seq[i + 1:]]
                s["issue_id"] = issue(root, f"handover:{sid}", f"L-152 换代第 {names[sid]} 步失败，后续步骤已停（{'、'.join(rest) or '无'}）：{str(detail)[:300]}",
                                      "看 release_result.json handover；修好后 system_version.py handover --apply --force")
                ho["aborted_at"] = sid
                ho["skipped"] = rest
                for x in rest:
                    ho["steps"].append({"id": x, "ok": None, "skipped": f"前一步 {sid} 失败，未执行（W17b P1-5）"})
                if rest:
                    live(root, f"⛔ 换代 L-152（{WHO}）{plan['sv']} 在“{names[sid]}”失败即停：未执行 {'、'.join(names[x] for x in rest)}")
                break
            _wj(root / RES_REL, res)
        ho["done"] = "aborted_at" not in ho and all(s.get("ok") for s in ho["steps"])
        _wj(root / RES_REL, res)
        plan.update(ok=ho["done"], result=ho)
        return plan
    finally:
        release_lock(root, lk)


def _append(p: Path, rec: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(p, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, (json.dumps(rec, ensure_ascii=False) + "\n").encode("utf-8"))
    finally:
        os.close(fd)


def format_handover(out: dict) -> str:
    ln = [f"L-152 换代（{out.get('mode')}）：剧 {out.get('run')}，版本 {out.get('sv') or '—'}，条件{'全部满足' if out.get('ready') else '未满足'}"]
    for c in out.get("conditions") or []:
        ln.append(f"  {'✅' if c['ok'] else '❌'} {c['id']}：{c['detail']}")
    ln.append("将做的步骤" + ("（dry：不执行）" if out.get("mode") == "dry" else "") + "：")
    for s in out.get("steps") or []:
        ln.append(f"  {s['n']}. {s['desc']}")
    if out.get("skipped"):
        ln.append("跳过：" + out["skipped"])
    if out.get("result"):
        ln.append(json.dumps(out["result"], ensure_ascii=False, indent=1)[:3000])
    return "\n".join(ln)


# ---------------------------------------------------------------- resident_sync loop 每拍
def tick(root: Path = ROOT, rs=None) -> dict:
    sv = load_sv()
    cfg = sv.release_cfg(root)
    if not cfg.get("enabled", True):
        return {"release": {"status": "disabled"}}
    r1 = release_once(root, sv=sv, cfg=cfg)
    res = _j(root / RES_REL, {}) or {}
    if res.get("deployed") and (res.get("request") or {}).get("handover") and not (res.get("handover") or {}).get("attempted"):
        r2 = handover_once(root, apply=True, sv=sv, rs=rs, cfg=cfg)      # 只有“已部署、要换代、还没做过”才去判阶段（stage_view 不是每拍都跑）
    else:
        r2 = {"skipped": "没有待换代的 release"}
    return {"release": r1, "handover": {k: r2.get(k) for k in ("ready", "skipped", "ok", "result") if k in r2}}


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001  # arch-ok: 老终端不支持 reconfigure
        pass
    print(json.dumps(tick(), ensure_ascii=False, indent=1, default=str)[:6000])
