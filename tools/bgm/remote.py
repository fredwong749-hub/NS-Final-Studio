"""笔记本 → gpu33 远端作业：上传 worker / 作业、nohup 起进程、轮询进度、镜像心跳到本机面板、取回文件。
只用 BatchMode ssh / scp；只停自己记录的 PID；不在远端装包（venv 已建：/root/work/fredw/bgm/venv）。"""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKER = Path(__file__).resolve().parent / "remote" / "bgm_worker.py"


# 连接 / 中途掉线都有上限，不靠 subprocess 超时（Windows 上 ProxyJump 孙进程握着管道时 kill 不掉）
SSH_OPTS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=20", "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=4"]


class RemoteError(RuntimeError):
    pass


def ssh(host: str, cmd: str, timeout: int = 120, retries: int = 6) -> str:
    """rc=255（跳板 / 连接被重置）或超时 → 退避重试；其他非零退出码直接报错"""
    last = ""
    for k in range(retries):
        try:
            r = subprocess.run(["ssh", *SSH_OPTS, host, cmd], capture_output=True, text=True, timeout=timeout,
                               encoding="utf-8", errors="replace")
        except subprocess.TimeoutExpired:
            last = f"超时 {timeout}s"
            time.sleep(10 * (k + 1))
            continue
        if r.returncode == 0:
            return r.stdout
        last = f"rc={r.returncode}: {(r.stderr or r.stdout)[-400:]}"
        if r.returncode != 255:
            break
        time.sleep(10 * (k + 1))
    raise RemoteError(f"ssh {host} {last}")


def _scp(args: list[str], what: str, timeout: int, retries: int = 5) -> None:
    last = ""
    for k in range(retries):
        try:
            r = subprocess.run(["scp", "-q", *SSH_OPTS, *args], capture_output=True, text=True, timeout=timeout)
            if r.returncode == 0:
                return
            last = r.stderr[-300:]
        except subprocess.TimeoutExpired:
            last = f"超时 {timeout}s"
        time.sleep(10 * (k + 1))
    raise RemoteError(f"scp {what}: {last}")


def put(host: str, local: Path, remote: str, timeout: int = 300) -> None:
    _scp([str(local), f"{host}:{remote}"], f"→ {remote}", timeout)


def get(host: str, remote: str, local: Path, timeout: int = 600) -> None:
    local.parent.mkdir(parents=True, exist_ok=True)
    _scp([f"{host}:{remote}", str(local)], f"← {remote}", timeout)


def read_json(host: str, remote: str):
    out = ssh(host, f"cat {remote} 2>/dev/null || true", 60).strip()
    try:
        return json.loads(out) if out else None
    except ValueError:
        return None


def submit(gen: dict, job: dict, local_dir: Path, cmd: str = "run") -> str:
    """cmd = run（生成；job["score"] 为 False 时只生成）或 score（只打分，候选 raw.wav 已在作业目录）"""
    host, wd = gen["host"], gen["workdir"]
    jd = f"{wd}/jobs/{job['id']}"
    ssh(host, f"mkdir -p {jd}")
    put(host, WORKER, f"{wd}/bgm_worker.py")
    lj = local_dir / f"job_{job['id']}_{cmd}.json"
    lj.write_text(json.dumps(job, ensure_ascii=False, indent=1), encoding="utf-8")
    put(host, lj, f"{jd}/job.json")
    pid = ssh(host, f"cd {wd} || exit 1; rm -f {jd}/result.json {jd}/progress.json; nohup {gen['python']} bgm_worker.py {cmd} "
                    f"--job {jd}/job.json > {jd}/worker.log 2>&1 < /dev/null & echo $! > {jd}/worker.pid; cat {jd}/worker.pid").strip()
    return pid


def copy_between(src: dict, dst: dict, job_id: str, names: list[str]) -> None:
    """生成机 → 打分机（两台之间没有直连钥匙，经笔记本 scp -3 中转）"""
    jd_s, jd_d = f"{src['workdir']}/jobs/{job_id}", f"{dst['workdir']}/jobs/{job_id}"
    ssh(dst["host"], f"mkdir -p {jd_d}")
    for n in names:
        _scp(["-3", f"{src['host']}:{jd_s}/{n}", f"{dst['host']}:{jd_d}/{n}"], f"{src['host']} → {dst['host']} {n}", 900)


def job_state(gen: dict, jid: str, todo: list[dict]) -> str:
    """scored（每条都有度量）/ gen_done（每条 raw.wav 都在）/ running / failed"""
    jd = f"{gen['workdir']}/jobs/{jid}"
    res = read_json(gen["host"], f"{jd}/result.json")
    if res and res.get("ok") and all("error" not in ((res.get("metrics") or {}).get(c["id"]) or {"error": 1}) for c in todo):
        return "scored"
    if not res and alive(gen, jid):
        return "running"
    have = set(ssh(gen["host"], f"cd {jd} 2>/dev/null && ls *.raw.wav 2>/dev/null || true").split())
    if all(f"{c['id']}.raw.wav" in have for c in todo):
        return "gen_done"
    return "failed"


def find_job(gen: dict, ep: int, rnd: int, todo: list[dict]) -> tuple[str, str] | None:
    """远端已有的同一批候选作业（id、种子、caption 都一致）→ (作业 id, job_state)；失败的不算"""
    want = [(c["id"], c["seed"], c["caption"]) for c in todo]
    out = ssh(gen["host"], f"cd {gen['workdir']}/jobs 2>/dev/null && ls -d ep{ep:02d}_r{rnd}_* 2>/dev/null || true").split()
    for jid in sorted(out, reverse=True):
        j = read_json(gen["host"], f"{gen['workdir']}/jobs/{jid}/job.json") or {}
        if [(c["id"], c["seed"], c["caption"]) for c in j.get("candidates") or []] != want:
            continue
        st = job_state(gen, jid, todo)
        if st != "failed":
            return jid, st
    return None


def alive(gen: dict, job_id: str) -> bool:
    jd = f"{gen['workdir']}/jobs/{job_id}"
    out = ssh(gen["host"], f"p=$(cat {jd}/worker.pid 2>/dev/null); [ -n \"$p\" ] && kill -0 $p 2>/dev/null && echo yes || echo no")
    return out.strip() == "yes"


def wait(gen: dict, job: dict, *, log=print, poll_s: int = 20, max_h: float = 6.0) -> dict:
    """等远端 result.json；期间把进度镜像成本机心跳（data/gpu_heartbeats，面板读）"""
    from ns_agent import comfy_tag as CT
    jd = f"{gen['workdir']}/jobs/{job['id']}"
    hb_id = f"BGM10-{job['id']}"
    t_end = time.time() + max_h * 3600
    last = None
    try:
        while time.time() < t_end:
            res = read_json(gen["host"], f"{jd}/result.json")
            if res:
                return res
            pr = read_json(gen["host"], f"{jd}/progress.json") or {}
            st = pr.get("state")
            host = gen["host"]
            mirror = host not in CT.REMOTE_HEARTBEAT_DIR   # gpu36 的远端心跳面板直接读；gpu33 的由这里镜像到本机
            if mirror and st == "generating":
                CT.heartbeat("BGM10", f"配乐 · ACE-Step {pr.get('model', '')} 候选 {pr.get('k')}/{pr.get('n')}", kind="other",
                             server=host if pr.get("device") == "cuda" else f"{host}-cpu", gpu=pr.get("gpu"),
                             step=pr.get("k"), steps=pr.get("n"), episode=job.get("episode"), hb_id=hb_id, ttl=120)
            elif mirror and st == "scoring":
                CT.heartbeat("BGM10", f"配乐 · 打分 {pr.get('k')}/{pr.get('n')}（CPU）", kind="other", server=host,
                             step=pr.get("k"), steps=pr.get("n"), episode=job.get("episode"), hb_id=hb_id, ttl=120)
            elif mirror and st == "waiting_gpu":
                CT.heartbeat("BGM10", "配乐 · 等空闲卡（给出图 / 视频让道）", kind="other", server=host,
                             episode=job.get("episode"), hb_id=hb_id, ttl=120, state="waiting")
            if st != last:
                log(f"  ep{job.get('episode'):02d} {job['id']}: {st} {json.dumps({k: v for k, v in pr.items() if k in ('cand', 'k', 'n', 'gpu', 'model')}, ensure_ascii=False)}")
                last = st
            if not alive(gen, job["id"]) and not read_json(gen["host"], f"{jd}/result.json"):
                tail = ssh(gen["host"], f"tail -c 1500 {jd}/worker.log 2>/dev/null || true")
                raise RemoteError(f"远端进程已退出但没有 result.json：{tail}")
            time.sleep(poll_s)
        raise RemoteError(f"{job['id']} 超过 {max_h} 小时")
    finally:
        CT.heartbeat_done("BGM10", hb_id)
