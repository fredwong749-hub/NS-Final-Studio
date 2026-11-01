"""VQAGATE：跳板 / 看图服务恢复后的收尾清单（总调度 11-01 17:3x 批）。按顺序、可重复跑（幂等）：

  1. 看图服务可达？（本机 127.0.0.1:8870 或 ssh gpu36）不可达 → 退出码 3，什么都不改
  2. tools/vqa/gate_scan.py scan --resume（最多 3 遍，直到没有“看图没跑成”的行）
  3. gate_scan apply（写回 Q9、撤看图不过的当前版 → PRODUCER 自动重出）
  4. gate_scan report（各项占比 → data/vqa/gate_scan/rates.json）
  5. 80 镜里每个有当前首帧的镜都看成并 apply 过 → config/vqa.json gate.video_requires_q9 = true（D-VQA-02 的打开条件），
     写 data/vqa/gate_scan/complete.json；没满足就保持 false 并列出缺哪些镜
  6. --push：把 score_clip.py + ns_agent/vqa + config/vqa.json + vqa_inspect.md 推到 gpu33 / gpu36 的 video10_srv（只推代码，
     不推 jobs.json，不起停进程；score_clip 每条片子单独起进程，推完下一条就生效）
  7. --calib：eye_contact 看图标定（gate_scan calib_gaze，总调度 100 张标签）

    .venv/Scripts/python.exe tools/vqa/after_network.py [--push] [--calib]
"""
from __future__ import annotations

import io
import json
import subprocess
import sys
import tarfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PY = str(ROOT / ".venv/Scripts/python.exe")
OUT = ROOT / "data/vqa/gate_scan"
CFG = ROOT / "config/vqa.json"
DEST = "/root/work/fredw/video10_srv"
PUSH = ["tools/series10_video/score_clip.py", "config/vqa.json", "config/prompts/vqa_inspect.md",
        "services/agent/ns_agent/__init__.py"]
PUSH_DIRS = ["services/agent/ns_agent/vqa"]


def say(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def run(args, timeout=36000) -> int:
    say("$", " ".join(args[1:]))
    return subprocess.run(args, cwd=str(ROOT), timeout=timeout, env={**__import__("os").environ, "PYTHONUTF8": "1"}).returncode


def reachable() -> bool:
    import urllib.request
    try:
        urllib.request.urlopen("http://127.0.0.1:8870/health", timeout=3)
        return True
    except Exception:  # noqa: BLE001
        pass
    r = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20", "gpu36", "curl -s -m5 127.0.0.1:8870/health"],
                       capture_output=True, text=True, timeout=60)
    return '"loaded"' in (r.stdout or "")


def missing() -> list[str]:
    sys.path[:0] = [str(ROOT / "services/agent"), str(ROOT / "services/render_router"), str(ROOT / "packages/schema")]
    from ns_render import pipeline as P
    rows = json.loads((OUT / "latest.json").read_text(encoding="utf-8"))["rows"] if (OUT / "latest.json").exists() else []
    ok = {(r["shot"], r.get("take")) for r in rows if r.get("take") and not r.get("error")}
    s = json.loads((ROOT / "data/import/script_v2.json").read_text(encoding="utf-8"))
    out = []
    for e in s["episodes"]:
        for x in e["shots"]:
            sid = f"ep{e['number']:02d}-S{x['index']}"
            d = P.load_takes(sid)
            n = (d.get("active") or {}).get("image")
            t = next((t for t in d.get("takes") or [] if t.get("stage") == "image" and t.get("n") == n), None)
            if t is None:
                continue                      # 没有当前首帧（被撤 / 重出中）：由 PRODUCER 新出的图在 _postflight 里过闸门
            q9 = next((i for i in (t.get("postflight") or {}).get("items") or [] if i.get("id") == "Q9"), None)
            if (sid, n) not in ok and not q9:
                out.append(f"{sid} v{n}")
    return out


def open_video_gate(miss: list[str]) -> None:
    txt = CFG.read_text(encoding="utf-8")
    if miss:
        say("video_requires_q9 保持 false，还缺", len(miss), "镜：", ", ".join(miss[:20]))
        return
    # 总调度 18:0x（AUDIT 建议）：不全自动放量——先写拦截名单 complete.json 交总调度亲审，--open 才真的打开
    applied = json.loads((OUT / "applied.json").read_text(encoding="utf-8"))["rows"] if (OUT / "applied.json").exists() else []
    blocked = [{"shot": r["shot"], "take": r.get("take"), "q9": r.get("q9"), "defects": r.get("defects"), "current": r.get("current")}
               for r in applied if r.get("now_ok") is False]
    (OUT / "complete.json").write_text(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "by": "tools/vqa/after_network.py",
                                                   "blocked": blocked, "opened": "--open" in sys.argv}, ensure_ascii=False, indent=1),
                                       encoding="utf-8")
    say("拦截名单", len(blocked), "镜 → data/vqa/gate_scan/complete.json（交总调度亲审）")
    if "--open" in sys.argv and '"video_requires_q9": false' in txt:
        CFG.write_text(txt.replace('"video_requires_q9": false', '"video_requires_q9": true', 1), encoding="utf-8")
        say("总调度亲审后 --open → gate.video_requires_q9 = true（D-VQA-02）")


def push() -> None:
    if subprocess.run([PY, str(ROOT / "tools/qa/thread_guard.py")]).returncode != 0:
        say("thread_guard 没过（K-OPS-V13），不推")
        return
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for f in PUSH:
            t.add(ROOT / f, arcname=f)
        for d in PUSH_DIRS:
            for p in (ROOT / d).rglob("*.py"):
                if "__pycache__" not in p.parts:
                    t.add(p, arcname=str(p.relative_to(ROOT)).replace("\\", "/"))
    for host in ("gpu33", "gpu36"):
        r = subprocess.run(["ssh", "-o", "BatchMode=yes", host, f"cd {DEST} && tar xzf - && echo PUSH_OK"], input=buf.getvalue(),
                           capture_output=True, timeout=1800)
        say("push", host, (r.stdout + r.stderr).decode(errors="replace").strip()[-200:])


def main(argv) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    if not reachable():
        say("看图服务不可达（本机 8870 未起、ssh gpu36 不通），什么都不改")
        return 3
    for k in range(3):
        run([PY, "tools/vqa/gate_scan.py", "scan", "--resume"])
        rows = json.loads((OUT / "latest.json").read_text(encoding="utf-8"))["rows"]
        err = [r["shot"] for r in rows if r.get("error")]
        say(f"第 {k + 1} 遍：看图没跑成 {len(err)} 镜", err[:10])
        if not err:
            break
    run([PY, "tools/vqa/gate_scan.py", "backfill"])      # 补判 Q9 untested 的新版本（含 laptop:0），通过的自动设为当前
    if "--apply" in argv:                                  # 总调度 18:4x：现行旧首帧不 apply（新剧本全部重做），要时显式加 --apply
        run([PY, "tools/vqa/gate_scan.py", "apply"])
    run([PY, "tools/vqa/gate_scan.py", "report"])
    open_video_gate(missing())
    if "--push" in argv:
        push()
    if "--calib" in argv:
        run([PY, "tools/vqa/gate_scan.py", "calib_gaze"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
