"""服务器代码漂移探针（DEBUG-RSI 牵头，和 SENTINEL 对齐；总调度 11-02 14:5x：DEBUG-RSI 在 gpu36 热替换 build_jobs.py 是 FACTORY
人眼拦下的，要变成机器先发现）。规则 K-OPS-E27。

不另造一套：复用 deploy 的核对口径——服务器当前所在版本（服务器 data/system_version.txt 的 id）的 git 快照，
和 resident_sync.verify_sha 同样的远程 sha256sum 逐个比（LF / CRLF 都算一致）。只看代码目录
（tools / services / packages / ops；config / knowledge 会经数据同步正常更新，不算）。
deploy 本身推完会按快照核 sha 并重推，所以“服务器 ≠ 自己所在版本”= 非部署造成的漂移。连续 2 次（≥ 10 分钟）都不一致才开单，
避开部署进行中的瞬时差异。

  .venv/Scripts/python.exe tools/debug/code_drift_probe.py [gpu33 gpu36]     # 手动跑一次，打印结果
由 tools/autopilot/infra_watchdog.py 每 10 分钟后台调 run_once()（开 / 关报警 A-CODE-DRIFT-<host>，工单进 data/sentinel/tickets.jsonl）
"""
from __future__ import annotations

import hashlib
import io
import json
import subprocess
import sys
import tarfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CODE_DIRS = ["tools", "services", "packages", "ops"]
HOSTS = ("gpu33", "gpu36")
STATE = ROOT / "data" / "debug" / "code_drift_state.json"
LOG = ROOT / "data" / "debug" / "code_drift.jsonl"
TICKETS = ROOT / "data" / "sentinel" / "tickets.jsonl"
CONFIRM_N = 2


def _sv_mod():
    import importlib.util
    spec = importlib.util.spec_from_file_location("ns_sv_probe", ROOT / "tools/qa/system_version.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def server_sv(rs, host: str) -> str | None:
    raw = rs.ssh(host, f"cat {rs.R}/data/system_version.txt 2>/dev/null; true", timeout=60, tries=2).decode("utf-8", "replace")
    try:
        return (json.loads(raw) or {}).get("id")
    except ValueError:   # arch-ok: check_host 把 None 当“读不到版本”报 error，不当成无漂移
        return None


def check_host(host: str, sv_mod=None, rs=None) -> dict:
    """→ {host, sv, checked, mismatch: [...], at}；取不到版本 → error"""
    SV = sv_mod or _sv_mod()
    rs = rs or SV.load_rs()
    sv = server_sv(rs, host)
    at = time.strftime("%Y-%m-%dT%H:%M:%S")
    if not sv:
        return {"host": host, "sv": None, "error": "服务器 data/system_version.txt 读不到", "at": at}
    want = expected_shas(sv)
    names = sorted(want)
    got = remote_shas(rs, host, names)
    mismatch = [n for n in names if got.get(n) not in want[n]]
    return {"host": host, "sv": sv, "checked": len(names), "mismatch": mismatch, "at": at}


def variants(b: bytes) -> set:
    """同一文件可接受的 sha：原字节 / LF / CRLF。deploy 的 export_tag 推的字节随工作区当时是否改过而不同（没改用工作区 CRLF，
    改过用 git archive LF），只认一种会把没漂的文件报成漂移（16:5x 实测 gpu36 误报 12 个、gpu33 23 个）"""
    lf = b.replace(b"\r\n", b"\n")
    return {hashlib.sha256(x).hexdigest() for x in (b, lf, lf.replace(b"\n", b"\r\n"))}


def expected_shas(sv: str) -> dict:
    """该版本 git 快照里代码目录每个文件 → 可接受 sha 集合"""
    raw = subprocess.run(["git", "archive", "--format=tar", sv, "--", *CODE_DIRS], cwd=ROOT, capture_output=True, check=True,
                         timeout=300).stdout
    out = {}
    with tarfile.open(fileobj=io.BytesIO(raw)) as tf:
        for m in tf.getmembers():
            if m.isfile():
                out[m.name] = variants(tf.extractfile(m).read())
    return out


def remote_shas(rs, host: str, names: list[str]) -> dict:
    """和 resident_sync.verify_sha 同样的取法：服务器 repo 里 xargs sha256sum（走 rs.ssh = rssh.run_retry）"""
    raw = rs.ssh(host, f"cd {rs.R} && nice -n 19 xargs -d '\\n' -r sha256sum 2>/dev/null; true", data="\n".join(names).encode(),
                 timeout=600, tries=3).decode("utf-8", "replace")
    got = {}
    for ln in raw.splitlines():
        parts = ln.split(None, 1)
        if len(parts) == 2:
            got[parts[1].strip().lstrip("*")] = parts[0]
    return got


def judge(prev: dict, res: dict, n: int = CONFIRM_N) -> tuple[dict, bool]:
    """连续计数：同一版本、同一批不一致文件连续出现 n 次 → confirmed。→ (新状态, 是否本次刚确认)"""
    key = json.dumps([res.get("sv"), sorted(res.get("mismatch") or [])], ensure_ascii=False)
    if not res.get("mismatch"):
        return {"key": None, "count": 0, "confirmed": False}, False
    cnt = (prev.get("count", 0) + 1) if prev.get("key") == key else 1
    confirmed = cnt >= n
    return {"key": key, "count": cnt, "confirmed": confirmed}, confirmed and not prev.get("confirmed")


def _append(p: Path, rec: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def run_once(hosts=HOSTS) -> dict:
    """每台查一次、更新连续计数；刚确认的漂移开工单。→ {host: {confirmed, mismatch, sv, error}}（给 watchdog 开 / 关报警）"""
    SV = _sv_mod()
    rs = SV.load_rs()
    try:
        st = json.loads(STATE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        st = {}
    out = {}
    for h in hosts:
        try:
            res = check_host(h, SV, rs)
        except (subprocess.SubprocessError, OSError, RuntimeError) as e:
            res = {"host": h, "error": repr(e)[:200], "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        _append(LOG, res)
        if res.get("error"):                         # 未测：不改计数，不开 / 关报警
            out[h] = {"error": res["error"], "confirmed": (st.get(h) or {}).get("confirmed", False)}
            continue
        st[h], new = judge(st.get(h) or {}, res)
        if new:
            _append(TICKETS, {"at": res["at"], "kind": "server_code_drift", "host": h, "sv": res["sv"],
                              "files": res["mismatch"][:50], "n_files": len(res["mismatch"]),
                              "why": f"{h} 代码树与自己所在版本 {res['sv']} 不一致（非部署造成），连续 {CONFIRM_N} 次",
                              "by": "tools/debug/code_drift_probe.py", "rule": "K-OPS-E27",
                              "route": "FACTORY（按 sv 重新 deploy 覆盖）/ 改动方自报事故账本"})
        out[h] = {"confirmed": st[h]["confirmed"], "mismatch": res["mismatch"][:20], "sv": res["sv"], "checked": res["checked"]}
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(STATE)
    return out


if __name__ == "__main__":
    hs = tuple(sys.argv[1:]) or HOSTS
    SV = _sv_mod()
    rs = SV.load_rs()
    for h in hs:
        r = check_host(h, SV, rs)
        print(json.dumps({**r, "mismatch": r.get("mismatch", [])[:30], "n_mismatch": len(r.get("mismatch") or [])}, ensure_ascii=False))
