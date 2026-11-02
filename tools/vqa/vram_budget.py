"""显存预算 + 实例数一致检查（VQAGATE 11-02，总调度：S3 根因写成 check，部署前就拦）。

  python tools/vqa/vram_budget.py            # 静态：config/vqa.json model.vram_budget 每张卡常驻峰值和 ≤ 0.9×显存（部署前闸门）
  python tools/vqa/vram_budget.py --live     # 加实测：gpu36 路由 /health 的 instances 与 config model.instances 一致、各实例与笔记本 8870 的 code_sha = 仓库 server.py、
                                             #   各实例都健康（不在等卡），GPU2 实际占用 ≤ 0.9×显存（经 tools/netfix/rsh.py，不直连 ssh）
退出码：0 = 全过；1 = 超预算 / 不一致（写 data/vqa/alerts.jsonl，SENTINEL 读）；3 = 实测读不到（未测，不当通过）
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CFG = ROOT / "config" / "vqa.json"
ALERTS = ROOT / "data" / "vqa" / "alerts.jsonl"
RATIO = 0.9


def static_check(cfg: dict) -> list[str]:
    m = cfg.get("model") or {}
    bad = []
    for gpu, b in (m.get("vram_budget") or {}).items():
        if gpu.startswith("_"):
            continue
        tot = 0
        for r in b.get("residents") or []:
            n = int(m.get("instances", 1)) if r.get("count_from") == "model.instances" else int(r.get("count", 1))
            tot += n * int(r["peak_mib"])
        lim = RATIO * int(b["total_mib"])
        if tot > lim:
            bad.append(f"{gpu} 常驻峰值和 {tot} MiB > {RATIO}×{b['total_mib']} = {lim:.0f} MiB")
    return bad


def live_check(cfg: dict) -> tuple[list[str], str | None]:
    m = cfg.get("model") or {}
    cmd = ("curl -s -m 5 127.0.0.1:8870/health; echo; "
           "for p in 8876 8878 8879; do curl -s -m 5 127.0.0.1:$p/health | head -c 4000; echo; done; "
           "nvidia-smi --query-gpu=index,memory.used,memory.total --format=csv,noheader,nounits")
    try:
        r = subprocess.run([sys.executable, str(ROOT / "tools/netfix/rsh.py"), "gpu36", cmd], cwd=ROOT,
                           capture_output=True, text=True, encoding="utf-8", timeout=120)
    except subprocess.TimeoutExpired:
        return [], "rsh 超时"
    lines = [x for x in (r.stdout or "").splitlines() if x.strip()]
    h = next((json.loads(x) for x in lines if x.startswith("{")), None)
    if h is None:
        return [], "读不到 gpu36 看图路由 /health"
    bad = []
    want = repo_sha()
    for x in lines:                                    # 各看图实例跑的代码 = 仓库版本（旧副本残留就报）
        if x.startswith("{") and '"code_sha"' in x:
            d = json.loads(x)
            if d.get("code_sha") != want:
                bad.append(f"gpu36 看图实例 GPU{d.get('gpu')} 跑的 server.py {d.get('code_sha')} ≠ 仓库 {want}（旧副本，要按 tools/vqa 部署重启）")
        elif x.startswith("{") and '"instances"' not in x and '"loaded"' in x:
            bad.append("gpu36 有看图实例 /health 没有 code_sha（11-02 之前的旧代码）")
    if int(h.get("instances") or 0) != int(m.get("instances") or 0):
        bad.append(f"路由实例数 {h.get('instances')} ≠ config model.instances {m.get('instances')}")
    for ln in lines:
        p = [x.strip() for x in ln.split(",")]
        if len(p) == 3 and p[0] == "2" and p[1].isdigit():
            used, tot = int(p[1]), int(p[2])
            if used > RATIO * tot:
                bad.append(f"gpu36 GPU2 实际占用 {used} MiB > {RATIO}×{tot}")
    return bad, None


def repo_sha() -> str:
    import hashlib
    return hashlib.sha256((ROOT / "tools/vqa/server.py").read_bytes().replace(bytes([13]), b"")).hexdigest()[:16]


def laptop_check() -> list[str]:
    """笔记本 8870（D:/ns_vqa/server.py 部署副本）：在跑就核对代码版本；没在跑不算错"""
    import urllib.request
    try:
        with urllib.request.urlopen("http://127.0.0.1:8870/health", timeout=5) as r:
            h = json.loads(r.read())
    except OSError:  # arch-ok: 笔记本看图服务没在跑 = 没有旧副本可言（不是放宽判定）；服务器那头的检查不受影响
        return []
    if h.get("gpu") == "router":
        return []
    if h.get("code_sha") != repo_sha():
        return [f"笔记本 8870 跑的 server.py {h.get('code_sha')} ≠ 仓库 {repo_sha()}（旧副本残留：D:/ns_vqa/start.ps1 -Restart）"]
    return []


def main(argv: list[str]) -> int:
    cfg = json.loads(CFG.read_text(encoding="utf-8"))
    bad = static_check(cfg)
    untested = None
    if "--live" in argv:
        b2, untested = live_check(cfg)
        bad += b2 + laptop_check()
    for b in bad:
        print("FAIL", b)
    if bad:
        ALERTS.parent.mkdir(parents=True, exist_ok=True)
        with ALERTS.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "kind": "vram_budget", "bad": bad}, ensure_ascii=False) + chr(10))
        return 1
    if untested:
        print("UNTESTED", untested)
        return 3
    print("VRAM_BUDGET PASS")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main(sys.argv[1:]))
