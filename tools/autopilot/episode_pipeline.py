"""逐集流水线（WORKFLOW 牵头，总调度 11-01 22:06；项目方“跳板连上了吗,全部gpu跑起来”；规则 K-OPS-W12）。

HOLLYWOOD 逐集导入（每集导入后 docs/CHANGELOG_AGENTS.md 追加一行“HOLLYWOOD 导入 epNN”）。每发现一集新导入：
  1. 重编 first_frame_jobs.json（tools/pipeline/image_jobs.rebuild_first_frame_jobs，唯一写入口），jobs_vs_import 对这一集 ok；
  2. full_redo plan → apply 只标这一集（新镜号、新作业；同一导入稿 sha 下标过的跳过，旧版本保留）；
  3. full_redo reset-redo 恢复这一集的驳回次数；
  4. producer control.json 的 only = 已准备好的各集的全部镜（只派已导入的集）；
  5. 记时：导入 → 第一张图派出 / 出来（data/producer/log.jsonl），→ 第一条视频提交 / 打分（并回的 vidgen 状态），附当时各卡利用率
     （resident_sync health 的最近一次结果）。
视频侧不用管：服务器 night 首帧一过闸门就自动编 Pika 变体派单（K-OPS-W07 / W11）。

  watch [--interval 60]      常驻：盯 CHANGELOG，新集就准备；每拍刷新记时
  prepare EP [--force]       手动准备一集
  hold EP --note N / release EP     暂停 / 放行某集（例：等造型换图）
  report                     各集记时表 → data/autopilot/episode_pipeline/report.md
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
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).parent))
OUT = ROOT / "data/autopilot/episode_pipeline"
STATE = OUT / "state.json"
CHANGELOG = ROOT / "docs/CHANGELOG_AGENTS.md"
def run_dir() -> Path:
    """现行剧本所属项目的运行目录（DISTILL 冷启动演练 ①：不写死 series10_v1）——config/recipes/asset_refs.json 里来源路径
    命中的项目的 run_dir（与 ns_render.unified_frame.project_for 同一规则）；判不出时退回唯一登记的项目 / series10_v1"""
    def _j(p):
        try:
            return json.loads(Path(p).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
    run = (_j(ROOT / "config/pipeline/runs.json") or {}).get("primary")         or (_j(ROOT / "config/pipeline/run.json") or {}).get("run_id")     # PRODMERGE-O：当前剧只认 runs.json（run.json 只在没有登记表时兜底）
    if run:
        return ROOT / "data/pipeline/runs" / run
    cfg = _j(ROOT / "config/recipes/asset_refs.json") or {}
    projects = cfg.get("projects") or {}
    srcs = [str(x.get("path") or "") for x in ((_j(ROOT / "data/import/script_v2.json") or {}).get("sources") or [])]
    for name, c in projects.items():
        if any(name in sp for sp in srcs) and c.get("run_dir"):
            return ROOT / c["run_dir"]
    if len(projects) == 1:
        only = next(iter(projects.values()))
        if only.get("run_dir"):
            return ROOT / only["run_dir"]
    return ROOT / "data/pipeline/runs/series10_v1"


RUN = run_dir()
IMPORT_RE = re.compile(r"HOLLYWOOD\s*导入\s*ep\s*0*(\d+)", re.I)


def jl(p, d=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return d


def js(p, d):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    t = p.with_suffix(".tmp")
    t.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(t, p)


def log(*a):
    line = time.strftime("%F %T ") + " ".join(str(x) for x in a)
    print(line, flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "log.txt", "a", encoding="utf-8") as f:
        f.write(line + "\n")


def imported_eps(text: str | None = None) -> list[int]:
    text = CHANGELOG.read_text(encoding="utf-8") if text is None else text
    seen = []
    for m in IMPORT_RE.finditer(text):
        n = int(m.group(1))
        if n not in seen:
            seen.append(n)
    return seen


def import_eps() -> list[int]:
    d = jl(ROOT / "data/import/script_v2.json", {}) or {}
    return sorted(int(e.get("number") or 0) for e in d.get("episodes") or [] if e.get("number"))


def candidate_eps() -> list[int]:
    """要看的集（总调度 02:0x，K-OPS-W15）= data/autopilot/imports.jsonl 导入事件里的集（producer import_staged 成功后追加）
    ∪ 导入稿里的全部集（按集内容哈希判断新导入 / 重导：兜底，事件漏写也不会漏准备）。
    CHANGELOG 的“HOLLYWOOD 导入 epNN”只给人看，⤴ 不再作为触发"""
    import import_events as IE
    out = IE.episodes_imported()
    for e in import_eps():
        if e not in out:
            out.append(e)
    return out


def _image_jobs():
    sp = importlib.util.spec_from_file_location("ns_image_jobs_ep", ROOT / "tools/pipeline/image_jobs.py")
    m = importlib.util.module_from_spec(sp)
    sys.path.insert(0, str(ROOT / "tools/pipeline"))
    sp.loader.exec_module(m)
    return m


def ep_shots_from_import(ep: int) -> list[str]:
    d = jl(ROOT / "data/import/script_v2.json", {}) or {}
    for e in d.get("episodes") or []:
        if int(e.get("number") or 0) == ep:
            return [f"ep{ep:02d}-S{int(s['index'])}" for s in e.get("shots") or [] if s.get("index") is not None]
    return []


def ep_hash(ep: int) -> str:
    """这一集在导入稿里的内容哈希：别的集导入时整份 sha 会变，但这一集没变就不重做"""
    import hashlib
    d = jl(ROOT / "data/import/script_v2.json", {}) or {}
    e = next((x for x in d.get("episodes") or [] if int(x.get("number") or 0) == ep), None)
    return hashlib.sha256(json.dumps(e, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16] if e else ""


READY = "data/autopilot/ready_episodes.json"


def write_ready(ep: int, shots: list[str]) -> dict:
    """NETFIX 派单接口（总调度 22:2x）：已准备好的集写进 ready_episodes.json（读-改-写，只追加 / 更新，不删）；
    tools/netfix/dispatch.py 按 config/netfix/partition.json 算每个 producer 的 only = 本机负责的集 ∩ 已准备好的集"""
    p = ROOT / READY
    d = jl(p, {}) or {}
    d["by"] = "WORKFLOW episode_pipeline"
    d["at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    eps = d.setdefault("episodes", {})
    eps[str(ep)] = {"ready_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "shots": sorted(shots)}
    js(p, d)
    return d


def owner_of_ep(ep: int) -> str:
    """负责这一集的机器（config/netfix/partition.json，归 NETFIX）；没有就按 resident_sync 旧分集"""
    part = jl(ROOT / "config/netfix/partition.json", {}) or {}
    for host, eps in (part.get("images") or {}).items():      # 出图（驳回 / 账本）归属看 images
        if isinstance(eps, list) and ep in [int(x) for x in eps]:
            return host
    import resident_sync as RS
    return next((h for h, e in RS.HOSTS.items() if ep in e), "laptop")


def remote_reset_redo(ep: int, shots: list[str]) -> str:
    """reset-redo 要对负责这一集的机器生效（服务器 producer 的账本在服务器上）；笔记本负责的集本地已做"""
    host = owner_of_ep(ep)
    if host in ("laptop", None):
        return "laptop（本地已做）"
    import resident_sync as RS
    out = RS.ssh(host, f"cd {RS.R} && PYTHONUTF8=1 {RS.OFF}/venv/bin/python tools/autopilot/full_redo.py reset-redo "
                       f"--shots {','.join(shots)} --by 'WORKFLOW episode_pipeline'", timeout=180, tries=3)
    return f"{host}: " + out.decode("utf-8", "replace").strip()[-200:]


def set_producer_only(shots: list[str]) -> dict:
    """producer control.json 的 only（PRODUCER 的派单白名单）= 已准备好的各集的镜；读-改-写，其它字段不动"""
    p = ROOT / "data/producer/control.json"
    c = jl(p, {}) or {}
    c["only"] = sorted(set(shots))
    c["only_by"] = {"by": "WORKFLOW episode_pipeline", "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "note": "逐集流水线（总调度 22:06）：只派已导入并准备好的集"}
    js(p, c)
    return c


# K-OPS-F22（总调度 11-02 17:4x，FACTORY 接 WORKFLOW）：作业编译只用已发版的代码。17:15–17:35 autoflow 每 70 s 用工作树里
# 改到一半的编译代码重写 first_frame_jobs.json（test_image_jobs 一直红），差点被推上服务器触发 E24 成批重出
COMPILE_DIRS = ["services/agent/ns_agent", "services/recipes", "services/render_router", "tools/pipeline", "config/recipes", "config/compile"]


def _sv():
    sp = importlib.util.spec_from_file_location("sv_for_compile_gate", ROOT / "tools/qa/system_version.py")
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


def compile_gate(sv=None) -> str | None:
    """None = 可以重编；否则返回不重编的原因：cut 冻结中 / 工作树的编译代码和最新已发版 tag 不同（服务器部署树没有 .git = 就是发版代码，放行）"""
    try:
        sv = sv or _sv()
        if sv.cut_locked():
            return "cut 冻结中，不重编作业（冻结结束后自动继续）"
        tags = sv.sv_tags()
        if not tags:
            return None
        drift = sv.drift_files(tags[-1], COMPILE_DIRS)
    except Exception:  # noqa: BLE001  # arch-ok: 没有 git（服务器部署树）= 运行的就是发版代码，放行
        return None
    if drift:
        return f"工作树编译代码与已发版 {tags[-1]} 不同（{len(drift)} 个文件，例 {drift[:3]}），等发版后再重编"
    return None


def prepare(ep: int, st: dict, force: bool = False) -> dict:
    import full_redo as FR
    rec = st.setdefault("eps", {}).setdefault(str(ep), {})
    if (st.get("holds") or {}).get(str(ep)) and not force:
        rec["status"] = "hold"
        return rec
    why = compile_gate()
    if why:
        rec.update(status="compile_frozen", note=why, at=time.strftime("%F %T"))
        log("prepare", f"ep{ep:02d}", "不重编：", why)
        return rec
    t0 = time.time()
    IJ = _image_jobs()
    r = IJ.rebuild_first_frame_jobs(RUN, write=True)
    r.pop("data", None)
    chk = IJ.jobs_vs_import(RUN)
    mine = set(ep_shots_from_import(ep))
    bad = {k: [x for x in chk.get(k) or [] if x in mine or x.startswith(f"ep{ep:02d}-")] for k in ("missing", "extra", "stale_sha")}
    if any(bad.values()):
        rec.update(status="jobs_mismatch", jobs_check=bad, at=time.strftime("%F %T"))
        log("prepare", f"ep{ep:02d}", "作业与导入稿对不上，不派：", bad)
        return rec
    green = FR.image_jobs_green()            # AUDIT 22:13：test_image_jobs 绿 + jobs_vs_import ok 才开派
    if not green["ok"]:
        rec.update(status="jobs_red", image_jobs=green, at=time.strftime("%F %T"))
        log("prepare", f"ep{ep:02d}", "作业清单与编译器 / 导入稿不一致，不开派：", green.get("tests"), green.get("jobs_vs_import"))
        return rec
    FR.make_plan()
    ap = FR.apply(eps={ep})
    rr = FR.reset_redo(shots=sorted(mine), by="WORKFLOW episode_pipeline")
    write_ready(ep, sorted(mine))            # NETFIX 接口：不再直接改 control.json 的 only
    try:                                     # 笔记本 producer 只派 laptop:0（partition images.laptop 的集），由 dispatch 算
        r_ap = subprocess.run([sys.executable, str(ROOT / "tools/netfix/dispatch.py"), "apply-laptop"], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=120, cwd=ROOT, env={**os.environ, "PYTHONUTF8": "1"})
        rec["apply_laptop"] = {"rc": r_ap.returncode, "out": (r_ap.stdout + r_ap.stderr).strip()[-200:]}
    except Exception as e:  # noqa: BLE001
        rec["apply_laptop"] = {"error": repr(e)[:200]}
    prepared = sorted({s for k, v in st["eps"].items() if v.get("status") == "prepared" for s in v.get("shots") or []} | mine)
    try:
        import resident_sync as RS
        host = owner_of_ep(ep)
        if host not in ("laptop", None):
            RS.push_control(host)            # master_rejects + ready_episodes 按对象合并推到负责机器
        rec["remote_reset_redo"] = remote_reset_redo(ep, sorted(mine))
    except Exception as e:  # noqa: BLE001
        rec["remote_error"] = repr(e)[:300]
        log("prepare", f"ep{ep:02d}", "推控制文件 / 远端 reset-redo 失败（loop 下一拍会再推控制文件）：", repr(e)[:200])
    rec.update(status="prepared", shots=sorted(mine), prepared_at=time.time(), prepared_iso=time.strftime("%F %T"),
               import_sha=FR.import_sha_now(), ep_hash=ep_hash(ep), apply=ap, reset_redo=rr.get("changed"), secs=round(time.time() - t0, 1))
    log("prepare", f"ep{ep:02d}", f"{len(mine)} 镜；apply {ap}；reset_redo {rr.get('changed')}；producer only 共 {len(prepared)} 镜")
    if not st.get("kickoff") and not st.get("no_kickoff"):
        rec["kickoff"] = kickoff(st)
    return rec


def kickoff(st: dict) -> dict:
    """总调度 22:2x 预先授权：第一集导入、作业转绿之后直接执行（只做一次）：
    ① ops/autostart/restart_producer.ps1（安全重载 producer，带上驳回即同步账本、Q9 补判的新代码；它会恢复原暂停状态）
    ② 本机看图服务 D:\\ns_vqa\\start.ps1 -Restart，VQA_WIN_N=0（最短看图窗口基线，先跑 30 分钟）
    ③ producer.py resume"""
    if st.get("kickoff"):
        return st["kickoff"]
    res = {"at": time.strftime("%F %T")}
    ps = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass"]
    # 23:1x 实测：capture_output=True 时，restart_producer.ps1 用 Start-Process 拉起的 producer 继承了管道句柄，
    # subprocess.run 一直等管道 EOF（producer 不退出就永远等）→ 开工卡在第 1 步。改为输出写文件、不接管道
    lf = OUT / "kickoff.log"

    def run(args, timeout, env=None):
        with open(lf, "a", encoding="utf-8") as fh:
            fh.write(time.strftime("%F %T ") + " ".join(map(str, args)) + chr(10))
            fh.flush()
            r = subprocess.run(args, stdin=subprocess.DEVNULL, stdout=fh, stderr=subprocess.STDOUT, timeout=timeout,
                               cwd=ROOT, env=env or {**os.environ, "PYTHONUTF8": "1"})
        return {"rc": r.returncode, "log": str(lf.relative_to(ROOT))}
    res["restart_producer"] = run(ps + ["-File", str(ROOT / "ops/autostart/restart_producer.ps1")], 1800)
    res["vqa_restart"] = {**run(ps + ["-Command", r"& 'D:\ns_vqa\start.ps1' -Restart"], 600,
                                env={**os.environ, "VQA_WIN_N": "0", "PYTHONUTF8": "1"}),
                          "VQA_WIN_N": 0, "baseline_until": time.strftime("%F %T", time.localtime(time.time() + 1800))}
    res["resume"] = run([sys.executable, str(ROOT / "tools/autopilot/producer.py"), "resume", "--by", "WORKFLOW episode_pipeline",
                         "--note", "逐集流水线：第一集导入、作业转绿（总调度 22:2x 预先授权）"], 120)
    st["kickoff"] = res
    log("kickoff", json.dumps(res, ensure_ascii=False)[:600])
    return res


# ---------------------------------------------------------------- 多剧并行（docs/AUTOPILOT.md §0.1，K-OPS-W17）
# primary（series10_v1）走上面原来的路径，零变化；其它 run 走下面：自己的导入稿 / 作业 / ready / 状态，镜号带 run 前缀。

def run_ep_shots(run: str, ep: int) -> list[str]:
    import runs as RN
    d = jl(RN.import_path(run, ROOT), {}) or {}
    for e in d.get("episodes") or []:
        if int(e.get("number") or 0) == ep:
            return [f"ep{ep:02d}-S{int(s['index'])}" for s in e.get("shots") or [] if s.get("index") is not None]
    return []


def run_ep_hash(run: str, ep: int) -> str:
    import hashlib
    import runs as RN
    d = jl(RN.import_path(run, ROOT), {}) or {}
    e = next((x for x in d.get("episodes") or [] if int(x.get("number") or 0) == ep), None)
    return hashlib.sha256(json.dumps(e, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16] if e else ""


def run_candidate_eps(run: str) -> list[int]:
    import import_events as IE
    import runs as RN
    out = IE.episodes_imported(run_id=run)
    d = jl(RN.import_path(run, ROOT), {}) or {}
    for e in d.get("episodes") or []:
        n = int(e.get("number") or 0)
        if n and n not in out:
            out.append(n)
    return out


def write_ready_run(run: str, ep: int, shots: list[str]) -> list[str]:
    """ready 写 data/autopilot/runs/<run>/ready_episodes.json（primary 另有旧路径，见 write_ready）；
    非 primary 的镜号带 run 前缀 <run>/<shot>（过渡期规则：producer / dispatch 认前缀之前 primary 不加）"""
    import runs as RN
    written = []
    for path in RN.ready_paths(run, ROOT):
        d = jl(path, {}) or {}
        d.update(by="WORKFLOW episode_pipeline", at=time.strftime("%Y-%m-%dT%H:%M:%S"), run_id=run)
        tag = (lambda x: x) if RN.is_primary(run, ROOT) else (lambda x: f"{run}/{x}")
        d.setdefault("episodes", {})[str(ep)] = {"ready_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "shots": sorted(tag(x) for x in shots)}
        js(path, d)
        written.append(path.relative_to(ROOT).as_posix())
    return written


def prepare_run(run: str, ep: int, st: dict) -> dict:
    """非 primary run 的一集：按该 run 的导入稿重编作业 → jobs_vs_import(该 run) 对这一集无缺 / 多 / 过期 → 写该 run 的 ready。
    新剧本没有旧版本，不需要 full_redo / reset-redo；作业 / ready 都在该 run 自己的目录，与 primary 的同名镜（ep01-S1）互不覆盖"""
    import runs as RN
    rs = st.setdefault("runs", {}).setdefault(run, {"eps": {}})
    rec = rs.setdefault("eps", {}).setdefault(str(ep), {})
    IJ = _image_jobs()
    rd = RN.run_dir(run, ROOT)
    why = compile_gate()
    if why:
        rec.update(status="compile_frozen", note=why, at=time.strftime("%F %T"))
        log("prepare_run", run, f"ep{ep:02d}", "不重编：", why)
        return rec
    try:
        IJ.rebuild_first_frame_jobs(rd, project=run, write=True, run=run)
        chk = IJ.jobs_vs_import(rd, run=run)
    except Exception as e:  # noqa: BLE001
        rec.update(status="jobs_error", error=repr(e)[:300], at=time.strftime("%F %T"))
        log("prepare_run", run, f"ep{ep:02d}", "作业重编失败：", repr(e)[:200])
        return rec
    mine = run_ep_shots(run, ep)
    bad = {k: [x for x in chk.get(k) or [] if x in mine] for k in ("missing", "extra", "stale_sha")}
    if any(bad.values()):
        rec.update(status="jobs_mismatch", jobs_check=bad, at=time.strftime("%F %T"))
        return rec
    written = write_ready_run(run, ep, mine)
    rec.update(status="prepared", shots=mine, prepared_at=time.time(), prepared_iso=time.strftime("%F %T"),
               ep_hash=run_ep_hash(run, ep), ready_files=written)
    log("prepare_run", run, f"ep{ep:02d}", f"{len(mine)} 镜 → {written}")
    return rec


def watch_other_runs(st: dict) -> None:
    import runs as RN
    for run in RN.list_runs(ROOT):
        if RN.is_primary(run, ROOT):
            continue
        rs = st.setdefault("runs", {}).setdefault(run, {"eps": {}})
        for ep in run_candidate_eps(run):
            rec = rs["eps"].get(str(ep)) or {}
            redo = rec.get("status") == "prepared" and rec.get("ep_hash") != run_ep_hash(run, ep)
            if redo or rec.get("status") in (None, "jobs_mismatch", "jobs_error"):
                try:
                    prepare_run(run, ep, st)
                except Exception as e:  # noqa: BLE001
                    rs["eps"].setdefault(str(ep), {}).update(status="error", error=repr(e)[:300])


def first_events(ep: int, since: float) -> dict:
    """producer log.jsonl：这一集首帧 / 尾帧第一次 dispatch / rendered；并回的 vidgen 状态：第一条视频提交 / 打分"""
    out = {}
    pref = (f"first:ep{ep:02d}-", f"last:ep{ep:02d}-")
    try:
        with open(ROOT / "data/producer/log.jsonl", encoding="utf-8") as f:
            for ln in f:
                if f"ep{ep:02d}-" not in ln:
                    continue
                try:
                    d = json.loads(ln)
                except ValueError:
                    continue
                if float(d.get("t") or 0) < since or not str(d.get("obj", "")).startswith(pref):
                    continue
                k = {"dispatch": "image_dispatch", "rendered": "image_rendered"}.get(d.get("ev"))
                if k and k not in out:
                    out[k] = float(d["t"])
    except OSError:
        pass
    for h in ("gpu33", "gpu36"):
        stv = jl(RUN / "video" / f"state_{h}.json", {}) or {}
        for sid, r in (stv.get("shots") or {}).items():
            if not sid.startswith(f"ep{ep:02d}-"):
                continue
            for x in r.get("renders") or []:
                ts, td = float(x.get("t_sub") or 0), float(x.get("t_done") or 0)
                if ts >= since and ("video_submit" not in out or ts < out["video_submit"]):
                    out["video_submit"] = ts
                if td >= since and x.get("score") and ("video_scored" not in out or td < out["video_scored"]):
                    out["video_scored"] = td
    return out


def gpu_snapshot() -> dict:
    rs = jl(ROOT / "data/autopilot/resident_sync.json", {}) or {}
    snap = {h: {g: x.get("util") for g, x in ((rs.get(h) or {}).get("health") or {}).get("lanes", {}).items()}
            for h in ("gpu33", "gpu36")}
    snap["at"] = {h: ((rs.get(h) or {}).get("health") or {}).get("at") for h in ("gpu33", "gpu36")}
    return snap


def refresh_timings(st: dict) -> None:
    for k, rec in (st.get("eps") or {}).items():
        if rec.get("status") != "prepared":
            continue
        ev = first_events(int(k), float(rec["prepared_at"]))
        tm = rec.setdefault("timing", {})
        for name, t in ev.items():
            if name not in tm:
                tm[name] = {"min_after_prepare": round((t - rec["prepared_at"]) / 60, 1),
                            "at": time.strftime("%H:%M:%S", time.localtime(t)), "gpu": gpu_snapshot()}
                log("timing", f"ep{int(k):02d}", name, tm[name]["min_after_prepare"], "分钟")


def report(st: dict) -> str:
    rows = ["# 逐集流水线记时（WORKFLOW，总调度 22:06）", "",
            "| 集 | 状态 | 镜数 | 准备完成 | 第一张图派出 | 第一张图出来 | 第一条视频提交 | 第一条视频打分 |", "|---|---|---|---|---|---|---|---|"]
    for k in sorted(st.get("eps") or {}, key=int):
        r = st["eps"][k]
        tm = r.get("timing") or {}
        cell = lambda n: f"+{tm[n]['min_after_prepare']} 分（{tm[n]['at']}）" if n in tm else "—"   # noqa: E731
        rows.append(f"| ep{int(k):02d} | {r.get('status')} | {len(r.get('shots') or [])} | {r.get('prepared_iso', '—')} | "
                    f"{cell('image_dispatch')} | {cell('image_rendered')} | {cell('video_submit')} | {cell('video_scored')} |")
    rows += ["", f"各卡利用率（最近一次 health）：{json.dumps(gpu_snapshot(), ensure_ascii=False)}"]
    txt = "\n".join(rows) + "\n"
    (OUT / "report.md").write_text(txt, encoding="utf-8")
    return txt


def watch(interval: int = 60) -> None:
    while True:
        st = jl(STATE, {}) or {}
        try:
            for ep in candidate_eps():
                rec = (st.get("eps") or {}).get(str(ep)) or {}
                redo = rec.get("status") == "prepared" and rec.get("ep_hash") and rec["ep_hash"] != ep_hash(ep)   # 这一集又导入了新版
                if (redo or rec.get("status") in (None, "hold", "jobs_mismatch", "jobs_red", "error", "compile_frozen")) and not (st.get("holds") or {}).get(str(ep)):
                    st.setdefault("eps", {}).setdefault(str(ep), {}).setdefault("import_seen_at", time.strftime("%F %T"))
                    try:
                        prepare(ep, st)
                    except Exception as e:  # noqa: BLE001
                        st["eps"][str(ep)].update(status="error", error=repr(e)[:300])
                        log("prepare error", f"ep{ep:02d}", repr(e)[:300])
            watch_other_runs(st)             # §0.1：非 primary 的 run 各自准备（primary 上面原样）
            refresh_timings(st)
            report(st)
        except Exception as e:  # noqa: BLE001
            log("watch error", repr(e)[:300])
        js(STATE, st)
        time.sleep(interval)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["watch", "prepare", "hold", "release", "report"])
    ap.add_argument("ep", nargs="?", type=int)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--note", default="")
    ap.add_argument("--interval", type=int, default=60)
    a = ap.parse_args(argv)
    st = jl(STATE, {}) or {}
    if a.cmd == "watch":
        watch(a.interval)
    elif a.cmd == "prepare":
        print(json.dumps(prepare(a.ep, st, a.force), ensure_ascii=False, indent=1, default=str)[:3000])
        js(STATE, st)
    elif a.cmd in ("hold", "release"):
        h = st.setdefault("holds", {})
        if a.cmd == "hold":
            h[str(a.ep)] = {"note": a.note, "at": time.strftime("%F %T")}
        else:
            h.pop(str(a.ep), None)
        js(STATE, st)
        print(h)
    elif a.cmd == "report":
        refresh_timings(st)
        js(STATE, st)
        print(report(st))
    return 0


if __name__ == "__main__":
    sys.exit(main())
