"""INFRA（2026-10-31）：把 imggen 编排器部署到 gpu33 / gpu36 本机运行（笔记本只看结果）。

服务器上用“仓库镜像”目录 /root/work/fredw/imggen_srv/（与仓库同样的相对路径），imggen.py 的 ROOT=parents[2] 不用改。
只推代码和小文件（作业 json、control.json、作业里 @upload 的参考图、身份参考、姿势模板），不推模型、不推大图。

    python tools/series10_imggen/server_deploy.py check  gpu33|gpu36     # 演练（dry-run）：环境、import、本机 ComfyUI、打分环境
    python tools/series10_imggen/server_deploy.py push   gpu33|gpu36     # 推代码 + 输入
    python tools/series10_imggen/server_deploy.py start  gpu33|gpu36 [-- imggen 参数…]   # nohup + PID 文件
    python tools/series10_imggen/server_deploy.py stop   gpu33|gpu36     # 只停 PID 文件里记的进程
    python tools/series10_imggen/server_deploy.py status gpu33|gpu36
    python tools/series10_imggen/server_deploy.py control gpu33|gpu36    # 只推 control.json（hold_lanes / frame_eps 改了以后）

机器规则：只写 /root/work/fredw；BatchMode；只停自己记录的 PID；gpu33 GPU2 永不用（imggen 的 local33 道只含 0/1/3）。
"""
from __future__ import annotations

import io
import json
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUN_REL = "data/pipeline/runs/series10_v1"
DEST = "/root/work/fredw/imggen_srv"
HOSTS = {
    "gpu33": {"py": "/root/claude-kimi-ns-studio-v1/env/comfy/bin/python", "ports": [8188, 8189, 8191], "lanes": "local33"},
    "gpu36": {"py": "/root/work/fredw/venv/bin/python", "ports": [8188, 8189, 8190], "lanes": "local36"},
}
CODE_DIRS = ["tools/series10_imggen", "tools/prompt_v2", "services/render_router", "services/agent", "packages/schema",
             "tools/char_assets", "tools/pipeline"]
SMALL_FILES = [f"{RUN_REL}/assets/char_sheet_jobs.json", f"{RUN_REL}/assets/first_frame_jobs.json",
               f"{RUN_REL}/images/control.json", "data/ab/owner_workflows/aisley_char_sheet/character_sheet_pose.png",
               "data/assets/identity_refs/lin_wan/lin_wan_face_ref2va.png", "data/assets/identity_refs/gu_chen/gu_chen_face_ref2va.png",
               "data/assets/identity_refs/chen_yu/chen_yu_face_ref2va.png", f"{RUN_REL}/images/sheets/ch_a_lan/ch_a_lan_face_ref.png"]


def ssh(host, cmd, data: bytes | None = None, timeout=600):
    return _rssh().run_retry(host, cmd, input=data, timeout=timeout, tries=1)   # 原来不重试：tries=1；bytes 进出不变

def _rssh():
    """K-OPS-N07 / SYSARCH 4-1：远程命令统一走 tools/netfix/rssh.run_retry（笔记本走常驻主连接；服务器上 OFFLINE_SELF 调本机 = 本机执行）"""
    import importlib.util
    spec = importlib.util.spec_from_file_location("_rssh_41", Path(__file__).resolve().parents[2] / "tools/netfix/rssh.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod



def upload_refs() -> list[str]:
    out = set()
    for f in SMALL_FILES[:2]:
        p = ROOT / f
        if not p.exists():
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        for j in d.get("jobs", d if isinstance(d, list) else []):
            for n in (j.get("graph") or {}).values():
                for v in (n.get("inputs") or {}).values():
                    if isinstance(v, str) and v.startswith("@upload:"):
                        out.add(v[len("@upload:"):])
            out.update(j.get("refs") or [])
    return sorted(out)


def build_tar(files: list[str], dirs: list[str]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for d in dirs:
            for p in (ROOT / d).rglob("*"):
                if p.is_file() and "__pycache__" not in p.parts and p.suffix in (".py", ".json", ".yaml", ".md", ".txt", ".toml"):
                    t.add(p, arcname=str(p.relative_to(ROOT)).replace("\\", "/"))
        for f in files:
            p = ROOT / f
            if p.is_file():
                t.add(p, arcname=f.replace("\\", "/"))
            else:
                print("  缺文件（跳过）:", f)
    return buf.getvalue()


def push(host, only_control=False):
    files = [f"{RUN_REL}/images/control.json"] if only_control else SMALL_FILES + upload_refs()
    blob = build_tar(files, [] if only_control else CODE_DIRS)
    print(f"推送 {len(files)} 个文件 + {0 if only_control else len(CODE_DIRS)} 个代码目录，{len(blob) / 1e6:.2f} MB → {host}:{DEST}")
    r = ssh(host, f"mkdir -p {DEST} && cd {DEST} || exit 1; tar xzf - && echo PUSH_OK", blob)
    print((r.stdout + r.stderr).decode(errors="replace").strip()[-400:])
    return r.returncode == 0


def check(host):
    h = HOSTS[host]
    ports = " ".join(map(str, h["ports"]))
    cmd = (f"cd {DEST} 2>/dev/null || {{ echo 'NO_DEST（先 push）'; exit 1; }}; "
           f"{h['py']} -c 'import sys; sys.argv=[\"x\"]; sys.path.insert(0,\"tools/series10_imggen\"); import imggen; "
           f"print(\"IMPORT_OK\", imggen.ROOT, len(imggen.frame_jobs()), \"frame jobs\", len(imggen.sheet_jobs()), \"sheet jobs\")' 2>&1 | tail -2; "
           f"for p in {ports}; do printf \"comfy :$p \"; curl -s -m 5 -o /dev/null -w \"%{{http_code}} %{{time_total}}s\\n\" localhost:$p/queue; done; "
           f"/root/work/fredw/venv_idm/bin/python -c 'import cv2, numpy, insightface; print(\"SCORE_ENV_OK\")' 2>&1 | tail -1; "
           f"ls /root/work/fredw/imggen/score_remote.py >/dev/null 2>&1 && echo SCORE_SCRIPT_OK || echo SCORE_SCRIPT_MISSING; "
           f"df -h /root/work | tail -1; awk '/MemAvailable/{{printf \"MemAvailable %.0f GB\\n\", $2/1048576}}' /proc/meminfo; "
           f"[ -f run/imggen.pid ] && kill -0 $(cat run/imggen.pid) 2>/dev/null && echo RUNNING $(cat run/imggen.pid) || echo NOT_RUNNING")
    r = ssh(host, cmd)
    print((r.stdout + r.stderr).decode(errors="replace").strip())


def start(host, extra):
    h = HOSTS[host]
    args = " ".join(extra) or f"run --lanes {h['lanes']}"
    cmd = (f"cd {DEST} || exit 1; mkdir -p run logs; "
           f"if [ -f run/imggen.pid ] && kill -0 $(cat run/imggen.pid) 2>/dev/null; then echo ALREADY $(cat run/imggen.pid); exit 0; fi; "
           f"PYTHONUTF8=1 nohup {h['py']} -u tools/series10_imggen/imggen.py {args} >> logs/imggen.out 2>&1 < /dev/null & "
           f"echo $! > run/imggen.pid; echo STARTED $(cat run/imggen.pid) {args}")
    print(ssh(host, cmd).stdout.decode(errors="replace").strip())


def stop(host):
    cmd = (f"cd {DEST} || exit 1; if [ -f run/imggen.pid ] && kill -0 $(cat run/imggen.pid) 2>/dev/null; then "
           f"pid=$(cat run/imggen.pid); kill $pid; for i in $(seq 20); do kill -0 $pid 2>/dev/null || break; sleep 1; done; "
           f"kill -0 $pid 2>/dev/null && kill -9 $pid; echo STOPPED $pid; else echo NOT_RUNNING; fi; rm -f run/imggen.pid")
    print(ssh(host, cmd).stdout.decode(errors="replace").strip())


def main(argv):
    if len(argv) < 2 or argv[0] not in ("check", "push", "start", "stop", "status", "control") or argv[1] not in HOSTS:
        print(__doc__)
        return 2
    act, host = argv[0], argv[1]
    if act == "push":
        return 0 if push(host) else 1
    if act == "control":
        return 0 if push(host, only_control=True) else 1
    if act in ("check", "status"):
        check(host)
    elif act == "start":
        start(host, argv[3:] if len(argv) > 2 and argv[2] == "--" else argv[2:])
    elif act == "stop":
        stop(host)
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv[1:]))
