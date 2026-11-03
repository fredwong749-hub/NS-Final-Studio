"""派单器（EPCHAIN-O 11-03，总调度：夜里每个写作 / 评审请求都等人手工派 agent，会卡住 → 派单做进系统）。

resident（tools/factory/autoflow_resident.py）每拍调 tick() 一次：
  - 读 <inbox>/requests/*.json（nsfs.dispatch_request/1，autoflow_agent.packet() 写），只接 kind ∈ cfg.kinds（writer / reviewer）且待处理的；
  - 跳过有人在跑的：<inbox>/requests/<id>.claimed 或 <run>__<id>.claimed 不是本派单器写的（总调度手工派单时建）；
  - 模型 = 请求的 suggested_model；写手必须是 MODEL_PLAN.writer，评审不能是写手模型（写和评不同模型），不符 = 不派、登记卡点；
  - 起无头 `claude -p`（cwd = 仓库根，--restricted，只开 Read + 只能写 output / done_marker 两个路径的 Write，不开 Bash / 联网，
    --permission-mode dontAsk + --permission-prompts none：白名单外的一律自动拒绝），提示词 = config/prompts/dispatch_<kind>.md 填请求；
  - 并发上限 cfg.max_concurrent（默认 2）；单个请求超过 cfg.timeout_s（默认 1800 秒）→ 只杀自己起的那个 pid（核对进程创建时间，防 pid 复用），
    这次尝试作废（半截产物移进 <run>/writer_out_void/，不删）、重新排队；累计 cfg.max_attempts（默认 3）次失败 → report_issue 登记卡点，不再派；
  - 每次执行结束记一行计量 <run>/metrics/epNN.jsonl（schema nsfs.metrics.dispatch/1，by = agent:<模型>(dispatcher)）；.done 第 2 行写 `model: <模型>`。
开关 config/pipeline/agent_dispatcher.json enabled（默认 false）。状态 data/factory/agent_dispatcher/state.json，日志同目录 logs/。

    .venv/Scripts/python.exe tools/factory/agent_dispatcher.py status     # 只读：开关、在跑的、累计尝试
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CFG = "config/pipeline/agent_dispatcher.json"
STATE_DIR = "data/factory/agent_dispatcher"
BY = "agent_dispatcher"
DEFAULTS = {"enabled": False, "claude_cmd": ["C:/Users/fredw/.local/bin/claude.exe"], "max_concurrent": 2, "timeout_s": 1800,
            "max_attempts": 3, "kinds": ["writer", "reviewer"], "models": {}}
DENY = ["Bash", "PowerShell", "NotebookEdit", "WebFetch", "WebSearch", "Agent", "Task", "Read(data/master/**)"]


def _load(name: str, rel: str, root: Path = ROOT):
    sp = importlib.util.spec_from_file_location(name, root / rel if (root / rel).exists() else ROOT / rel)
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


def load_cfg(root: Path = ROOT) -> dict:
    try:
        return {**DEFAULTS, **json.loads((root / CFG).read_text(encoding="utf-8"))}
    except (OSError, ValueError):   # arch-ok: 配置读不到 = 关（失败关闭）
        return dict(DEFAULTS)


def inbox_dir(root: Path = ROOT) -> Path:
    p = Path(os.environ.get("NSFS_INBOX_DIR") or "data/master/inbox")
    return p if p.is_absolute() else root / p


def _js(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + f".tmp{os.getpid()}")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


# ------------------------------------------------------------------ 进程（只认自己起的 pid：pid + 创建时间）

def proc_sig(pid: int) -> int | None:
    """进程创建时间（Windows FILETIME / POSIX /proc starttime）；进程不在 = None"""
    if pid <= 0:
        return None
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x1000, False, pid)
        if not h:
            return None
        try:
            code = wintypes.DWORD()
            if not k.GetExitCodeProcess(h, ctypes.byref(code)) or code.value != 259:
                return None
            c, e, kt, u = (wintypes.FILETIME() for _ in range(4))
            if not k.GetProcessTimes(h, ctypes.byref(c), ctypes.byref(e), ctypes.byref(kt), ctypes.byref(u)):
                return None
            return (c.dwHighDateTime << 32) | c.dwLowDateTime
        finally:
            k.CloseHandle(h)
    try:
        return int(Path(f"/proc/{pid}/stat").read_text().split(")")[-1].split()[19])
    except (OSError, ValueError, IndexError):
        try:
            os.kill(pid, 0)
            return 0
        except OSError:
            return None


def alive(pid: int, sig) -> bool:
    s = proc_sig(pid)
    return s is not None and (sig is None or s == sig)


def kill(pid: int, sig) -> bool:
    """只杀自己起的那个进程（及其子进程）：创建时间对不上 = pid 已被复用，不杀"""
    if not alive(pid, sig):
        return False
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=60)
    else:
        import signal
        os.kill(pid, signal.SIGKILL)
    return True


# ------------------------------------------------------------------ 请求 → 命令

def rel_under(root: Path, p: str) -> str | None:
    """仓库根下的相对路径（posix）；不在根下 = None（不派）"""
    q = Path(p)
    q = q if q.is_absolute() else root / q
    try:
        return q.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return None


def pick_model(req: dict, plan: dict) -> tuple[str | None, str]:
    """(模型, 不派的原因)。写手必须是写手模型；评审不能是写手模型，也不能是请求写明的 must_differ_from"""
    m = req.get("suggested_model")
    if not m:
        return None, "请求没写 suggested_model"
    if req.get("kind") == "writer" and m != plan["writer"]:
        return None, f"写手请求的模型 {m} 不是写手模型 {plan['writer']}"
    if req.get("kind") == "reviewer" and (m == plan["writer"] or m == req.get("must_differ_from")):
        return None, f"评审请求的模型 {m} 和写手模型相同（写和评必须不同）"
    return m, ""


def prompt_for(req: dict, model: str, root: Path = ROOT) -> str:
    tpl = (root / "config/prompts" / f"dispatch_{req['kind']}.md")
    tpl = tpl if tpl.exists() else ROOT / "config/prompts" / f"dispatch_{req['kind']}.md"
    t = tpl.read_text(encoding="utf-8")
    pk = rel_under(root, req["packet"]) or req["packet"]
    vals = {"model": model, "run": req.get("run"), "episode": req.get("episode"), "step": req.get("step"), "attempt": req.get("attempt"),
            "packet": pk, "run_dir": str(Path(pk).parent.parent.as_posix()), "output": rel_under(root, req["output"]),
            "done_marker": rel_under(root, req["done_marker"])}
    for k, v in vals.items():
        t = t.replace("{" + k + "}", str(v))
    return t


def build_cmd(cfg: dict, req: dict, model: str, root: Path = ROOT) -> list[str]:
    """最严的非交互：--restricted（去掉跑命令的工具和 WebFetch，忽略用户 / 项目设置，文件工具限在 cwd）+ --tools 只给 Read,Write
    + allowedTools 只放 Read 和两条 Write(<路径>) + dontAsk / permission-prompts none（白名单外自动拒绝）+ 不连任何 MCP、不留会话。
    提示词走 stdin（不放命令行，免得被变长参数吞掉）"""
    out, done = rel_under(root, req["output"]), rel_under(root, req["done_marker"])
    return [*cfg["claude_cmd"], "-p", "--model", (cfg.get("models") or {}).get(model, model),
            "--restricted", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
            "--tools", "Read,Write",
            "--allowedTools", "Read", f"Edit({out})", f"Edit({done})",   # 文件写权限规则用 Edit(<路径>)（覆盖 Write 工具；Edit 工具本身不在 --tools 里）
            "--disallowedTools", *DENY,
            "--permission-mode", "dontAsk", "--permission-prompts", "none",
            "--no-session-persistence", "--output-format", "json"]


# ------------------------------------------------------------------ 认领 / 计量 / 收尾

def claimed_by_other(inbox: Path, key: str, req: dict) -> bool:
    for name in (f"{key}.claimed", f"{req.get('id')}.claimed"):
        p = inbox / "requests" / name
        if p.exists():
            try:
                if json.loads(p.read_text(encoding="utf-8")).get("by") == BY:
                    continue
            except (OSError, ValueError, AttributeError):   # arch-ok: 不是本派单器写的 JSON = 有人手工认领
                pass
            return True
    return False


def is_void(root: Path, inbox: Path, key: str, req: dict) -> str | None:
    """TIMELINE-O 11-03：请求已作废 → 原因。<key>.void / <id>.void 标记（autoflow_agent.void_request 写），或作业包文件已不在
    （被隔离）。派单器见到就不派；在跑的杀掉、半截产物作废，不重排（P4_ep01_a3 隔离前已被领走、白跑一次）"""
    for name in (f"{key}.void", f"{req.get('id')}.void"):
        if (inbox / "requests" / name).exists():
            return f"作废标记 {name}"
    pk = req.get("packet")
    if pk and not (root / (rel_under(root, pk) or pk)).exists():
        return f"作业包 {pk} 已不在（隔离）"
    return None


def write_claim(inbox: Path, key: str, **kw) -> None:
    try:
        _js(inbox / "requests" / f"{key}.claimed", {"by": BY, "at": time.strftime("%Y-%m-%dT%H:%M:%S"), **kw})
    except OSError as e:
        print(f"[dispatcher] 写认领 {key} 失败：{e!r}")


def actual_model(log: Path, fallback: str) -> tuple[str, str]:
    """claude -p --output-format json 的结果里 modelUsage 的键 = 实际用到的模型 id（多个取输出 token 最多的）；读不到 = (请求模型, "suggested")"""
    try:
        txt = log.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return fallback, "suggested"
    for ln in reversed(txt.splitlines()):
        ln = ln.strip()
        if not (ln.startswith("{") and "modelUsage" in ln):
            continue
        try:
            mu = json.loads(ln).get("modelUsage") or {}
        except ValueError:
            mu = {}   # 截断 / 坏行 = 不是结果行，接着往上找
        if mu:
            best = max(mu.items(), key=lambda kv: float((kv[1] or {}).get("outputTokens") or 0))
            return best[0], "cli"
    return fallback, "suggested"


def metric(root: Path, req: dict, run_rec: dict, result: str, now: float) -> None:
    try:
        pk = Path(rel_under(root, req["packet"]) or req["packet"])
        rd = (root / pk).parent.parent
        ep = int(req.get("episode") or 0)
        line = {"schema": "nsfs.metrics.dispatch/1", "run": req.get("run"), "episode": ep, "stage": "dispatch", "step": req.get("step"),
                "request": req.get("id"), "started_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(run_rec["t0"])),
                "ended_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now)), "duration_s": max(0, int(now - run_rec["t0"])),
                "by": f"agent:{run_rec.get('model_id') or run_rec['model']}(dispatcher)", "model_source": run_rec.get("model_source") or "suggested",
                "suggested_model": run_rec["model"], "attempts": run_rec["n"], "result": result, "ok": result == "done"}
        p = rd / "metrics" / f"ep{ep:02d}.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
    except (OSError, ValueError, KeyError) as e:
        print(f"[dispatcher] 写计量失败：{e!r}")


def quarantine(root: Path, req: dict, tag: str) -> list[str]:
    """作废这次尝试：半截产物 / .done 移进 <run>/writer_out_void/（改名带时间，不删）"""
    moved = []
    for k in ("output", "done_marker"):
        p = root / (rel_under(root, req[k]) or req[k])
        if p.exists():
            dst = p.parent.parent / "writer_out_void" / f"{p.name}.dispatch{tag}"
            dst.parent.mkdir(parents=True, exist_ok=True)
            p.rename(dst)
            moved.append(dst.name)
    return moved


# ------------------------------------------------------------------ 一拍

def _spawn_flags() -> int:
    return (subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | getattr(subprocess, "CREATE_NO_WINDOW", 0)) if os.name == "nt" else 0


def launch(cmd: list[str], root: Path, prompt_file: Path, log_file: Path, timeout_s: float = 60) -> tuple[int, str]:
    """ISS-1103-033131-1efe（03:30 受控重启 resident 时 taskkill /T 连带杀掉了写手）：经一个“一次性启动器”起 claude -p ——
    启动器用和 resident detach 同样的 DETACHED_PROCESS + 新进程组 + CREATE_BREAKAWAY_FROM_JOB（不允许脱离作业对象时退一步）起写手，
    把写手 pid 写回后立即退出。写手的父进程（启动器）已不在，resident 的进程树里就没有它，taskkill /T resident 带不走。返回 (pid, 方式)"""
    spec = log_file.with_suffix(".launch.json")
    tmp = spec.with_name(spec.name + f".tmp{os.getpid()}")   # 原子写：启动器不会读到半个 JSON
    tmp.write_text(json.dumps({"cmd": cmd, "cwd": str(root), "stdin": str(prompt_file), "log": str(log_file)}, ensure_ascii=False),
                   encoding="utf-8")
    os.replace(tmp, spec)
    res = spec.with_suffix(".pid.json")
    res.unlink(missing_ok=True)
    kw = {"creationflags": _spawn_flags()} if os.name == "nt" else {"start_new_session": True}
    p = subprocess.Popen([sys.executable, "-X", "utf8", str(Path(__file__).resolve()), "_launch", str(spec)], cwd=str(root),
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True, **kw)
    p.wait(timeout=timeout_s)
    d = json.loads(res.read_text(encoding="utf-8"))
    if not d.get("pid"):
        raise RuntimeError(f"启动器没起来写手：{d.get('error')}")
    return int(d["pid"]), d.get("how", "")


def _launch_main(spec_path: str) -> int:
    """一次性启动器（_launch 子命令）：起写手、写回 pid、退出"""
    spec = Path(spec_path)
    s = json.loads(spec.read_text(encoding="utf-8"))
    res = spec.with_suffix(".pid.json")
    try:
        with open(s["stdin"], "rb") as fin, open(s["log"], "ab") as fout:
            kw = {"cwd": s["cwd"], "stdin": fin, "stdout": fout, "stderr": subprocess.STDOUT, "close_fds": True}
            if os.name == "nt":
                try:
                    p, how = subprocess.Popen(s["cmd"], creationflags=_spawn_flags() | subprocess.CREATE_BREAKAWAY_FROM_JOB, **kw), "breakaway"
                except OSError:            # 作业对象不允许脱离：只按 DETACHED 起（仍不在 resident 的进程树里）
                    p, how = subprocess.Popen(s["cmd"], creationflags=_spawn_flags(), **kw), "detached"
            else:
                p, how = subprocess.Popen(s["cmd"], start_new_session=True, **kw), "setsid"
        _js(res, {"pid": p.pid, "how": how})
        return 0
    except Exception as e:  # noqa: BLE001  起不来要写回原因
        _js(res, {"pid": None, "error": repr(e)[:300]})
        return 1


def tick(root: Path = ROOT, cfg: dict | None = None, now=time.time, launch_fn=launch, alive_fn=alive, kill_fn=kill,
         sig_fn=proc_sig, report=None, plan: dict | None = None) -> dict:
    cfg = cfg or load_cfg(root)
    if not cfg.get("enabled"):
        return {"enabled": False}
    plan = plan or _load("autoflow_for_dispatch", "tools/script_rsi/autoflow.py").MODEL_PLAN
    PR = _load("pending_requests_for_dispatch", "tools/master/pending_requests.py")
    inbox = inbox_dir(root)
    sp = root / STATE_DIR / "state.json"
    try:
        state = json.loads(sp.read_text(encoding="utf-8"))
    except (OSError, ValueError):   # arch-ok: 第一次 / 坏了 = 空状态（在跑的进程按 pid 再认不回来，最多多等一拍超时）
        state = {"requests": {}}
    S = state.setdefault("requests", {})
    reqs = {f"{r.get('run')}__{r.get('id')}": r for r in PR.list_requests(inbox, include_all=True, root=root) if r.get("id")}
    out = {"enabled": True, "finished": [], "started": [], "skipped": [], "failed": []}

    def give_up(key, req, why):
        rec = S.setdefault(key, {"attempts": 0})
        rec["failed"] = why
        write_claim(inbox, key, state="failed", why=why)
        try:
            (report or _load("report_issue", "tools/master/report_issue.py").report)(
                req.get("run"), int(req.get("episode") or 0), f"派单 {req.get('step')}", BY, why, True, "总调度看日志 data/factory/agent_dispatcher/logs/ 后手工派")
        except Exception as e:  # noqa: BLE001  登记失败只打印
            print(f"[dispatcher] 登记卡点失败：{e!r}")
        out["failed"].append(key)

    # ① 收尾：在跑的看完没完、超没超时
    t = now()
    for key, rec in S.items():
        run = rec.get("running")
        if not run:
            continue
        req = reqs.get(key) or run.get("req")
        live = alive_fn(run["pid"], run.get("sig"))
        vw = is_void(root, inbox, key, req)
        if live and t - run["t0"] <= float(cfg["timeout_s"]) and not vw:
            continue
        result = ("voided" if vw else "timeout") if live else ("voided" if vw else None)
        if live:
            kill_fn(run["pid"], run.get("sig"))
        done_p = root / (rel_under(root, req["done_marker"]) or req["done_marker"])
        out_p = root / (rel_under(root, req["output"]) or req["output"])
        real, src = actual_model(root / STATE_DIR / "logs" / run.get("log", "-"), (cfg.get("models") or {}).get(run["model"], run["model"]))
        run["model_id"], run["model_source"] = real, src
        if result is None and out_p.exists() and done_p.exists():
            result = "done"
            done_p.write_text(f"{BY}\nmodel: {real}\n", encoding="utf-8")       # .done 第 2 行 = 实际模型 id（METRICS_SPEC §A）
        elif result is None:
            result = "failed"
        if result != "done":
            run["voided"] = quarantine(root, req, time.strftime("%H%M%S") + f"_n{run['n']}")
        metric(root, req, run, result, t)
        rec.setdefault("history", []).append({**{k: v for k, v in run.items() if k != "req"}, "result": result, "ended": t})
        rec["running"] = None
        out["finished"].append(f"{key}:{result}")
        if result == "done":
            write_claim(inbox, key, state="done", model=run["model"])
        elif result == "voided":
            rec["failed"] = vw
            write_claim(inbox, key, state="voided", why=vw)
        elif rec["attempts"] >= int(cfg["max_attempts"]):
            give_up(key, req, f"派单 {rec['attempts']} 次都没交稿（最后一次 {result}）")
        else:
            write_claim(inbox, key, state="requeued", attempts=rec["attempts"])
    # ② 开新的：并发上限内，按请求时间先后
    running = sum(1 for r in S.values() if r.get("running"))
    for key, req in sorted(reqs.items(), key=lambda kv: str(kv[1].get("at"))):
        rec = S.get(key) or {}
        if req.get("state") != "pending" or req.get("kind") not in cfg["kinds"] or rec.get("running") or rec.get("failed"):
            continue
        if claimed_by_other(inbox, key, req):
            out["skipped"].append(f"{key}:claimed")
            continue
        if is_void(root, inbox, key, req):
            out["skipped"].append(f"{key}:void")
            continue
        if int(rec.get("attempts") or 0) >= int(cfg["max_attempts"]):
            continue
        model, why = pick_model(req, plan)
        if model is None or not rel_under(root, req["output"]) or not rel_under(root, req["done_marker"]):
            give_up(key, req, why or "产物路径不在仓库根下，不派")
            continue
        if running >= int(cfg["max_concurrent"]):
            out["skipped"].append(f"{key}:concurrency")
            continue
        rec = S.setdefault(key, {"attempts": 0})
        rec["attempts"] = int(rec.get("attempts") or 0) + 1
        logs = root / STATE_DIR / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        pf = logs / f"{key}_n{rec['attempts']}.prompt.md"
        pf.write_text(prompt_for(req, model, root), encoding="utf-8")
        lf = logs / f"{key}_n{rec['attempts']}.log"
        try:
            pid, how = launch_fn(build_cmd(cfg, req, model, root), root, pf, lf)
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as e:     # 起不来：这次不算尝试，下一拍再试
            rec["attempts"] -= 1
            out["skipped"].append(f"{key}:launch_error {e!r}"[:200])
            continue
        rec["running"] = {"pid": pid, "sig": sig_fn(pid), "t0": now(), "model": model, "n": rec["attempts"], "log": lf.name, "launch": how,
                          "req": {k: req.get(k) for k in ("id", "run", "episode", "step", "packet", "output", "done_marker")}}
        write_claim(inbox, key, state="running", pid=pid, model=model, attempt=rec["attempts"])
        running += 1
        out["started"].append(f"{key}:{model}")
    _js(sp, state)
    return out


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    a = (argv if argv is not None else sys.argv[1:]) or ["status"]
    if a[0] == "status":
        cfg = load_cfg()
        try:
            st = json.loads((ROOT / STATE_DIR / "state.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            st = {}
        print(json.dumps({"enabled": cfg.get("enabled"), "max_concurrent": cfg.get("max_concurrent"),
                          "requests": {k: {"attempts": v.get("attempts"), "running": bool(v.get("running")), "failed": v.get("failed")}
                                       for k, v in (st.get("requests") or {}).items()}}, ensure_ascii=False, indent=1))
        return 0
    if a[0] == "_launch" and len(a) > 1:
        return _launch_main(a[1])
    if a[0] == "tick":
        print(json.dumps(tick(), ensure_ascii=False))
        return 0
    print("用法：agent_dispatcher.py status | tick")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
