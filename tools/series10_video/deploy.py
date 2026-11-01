"""VIDEO10（2026-10-31）：把视频编排器 + 打分器 + 作业 + 输入图推到 gpu33 / gpu36 的仓库镜像目录，并起停（同 series10_imggen/server_deploy.py）。

服务器镜像目录 /root/work/fredw/video10_srv/（与仓库同样的相对路径）。只推代码和小文件（作业 json、控制文件、首帧 / 身份参考图、
YuNet/SFace 两个 onnx），不推模型。gpu36 没有 ffprobe：把 imageio_ffmpeg 的静态 ffmpeg 链进 /root/work/fredw/tools_bin，
再放 ffprobe_shim.py 当 ffprobe。

    python tools/series10_video/deploy.py push    gpu33|gpu36 [--jobs validate_jobs.json]
    python tools/series10_video/deploy.py control gpu33|gpu36 '<json>'      # 写 control_<host>.json（覆盖）
    python tools/series10_video/deploy.py start   gpu33|gpu36
    python tools/series10_video/deploy.py stop    gpu33|gpu36
    python tools/series10_video/deploy.py status  gpu33|gpu36
机器规则：只写 /root/work/fredw；BatchMode；只停自己 PID 文件里的进程；gpu33 GPU2 永不用（本工具只用 0/1/3）。
"""
from __future__ import annotations

import io
import json
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VID_REL = "data/pipeline/runs/series10_v1/video"
DEST = "/root/work/fredw/video10_srv"
PY = "/root/work/fredw/venv_idm/bin/python"
CODE_FILES = ["config/pipeline/video_policy.json", "config/vqa.json", "config/prompts/vqa_inspect.md", "services/agent/ns_agent/__init__.py",
              "config/render_quality.json", "tools/motion_judder.py", "tools/ep02_director/review.py", "tools/lab_ep02/lab_score.py",
              "tools/ep02_iter/cut_check.py"]
CODE_DIRS = ["tools/series10_video", "services/render_router/ns_render", "packages/qc/ns_qc", "services/agent/ns_agent/vqa"]
VISION = ["models_cache/vision/face_detection_yunet_2023mar.onnx", "models_cache/vision/face_recognition_sface_2021dec.onnx"]


def ssh(host, cmd, data: bytes | None = None, timeout=900):
    return subprocess.run(["ssh", "-o", "BatchMode=yes", host, cmd], input=data, capture_output=True, timeout=timeout)


def inputs_for(host: str, jobs_file: str) -> list[str]:
    d = json.loads((ROOT / VID_REL / jobs_file).read_text(encoding="utf-8"))
    out = set()
    for s in d["shots"]:
        if s["host"] != host:
            continue
        for v in s["variants"].values():
            out.update((v.get("inputs") or {}).values())
        out.update((s.get("score_refs") or {}).values())
    return sorted(out)


def image_ok(p: Path) -> bool:
    """K-OPS-311：推给服务器的参考 / 首帧图先完整解码一遍。11-01 离线：补拷设定图时跳板断开，服务器上留下截断 PNG，
    之后又被 ops/offline/merge_pull.py 按 mtime 并回笔记本，覆盖了 7 张好图（林晚 lookA/B/C 等）"""
    if p.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
        return True
    try:
        from PIL import Image
        with Image.open(p) as im:
            im.load()
        return True
    except Exception:  # noqa: BLE001
        return False


def build_tar(files, dirs) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for d in dirs:
            for p in (ROOT / d).rglob("*"):
                if p.is_file() and "__pycache__" not in p.parts and p.suffix in (".py", ".json", ".yaml", ".txt"):
                    t.add(p, arcname=str(p.relative_to(ROOT)).replace("\\", "/"))
        for f in files:
            p = ROOT / f
            if p.is_file() and not image_ok(p):
                print("  图读不全（跳过，不推坏图）:", f)
            elif p.is_file():
                t.add(p, arcname=f.replace("\\", "/"))
            else:
                print("  缺文件（跳过）:", f)
    return buf.getvalue()


def thread_guard_ok() -> bool:
    """K-OPS-V13 硬检查（总调度 L-100 第 5 条：线程问题第二次）：服务器打分 / 检测脚本没过 tools/qa/thread_guard.py 不许推、不许跑"""
    r = subprocess.run([sys.executable, str(ROOT / "tools/qa/thread_guard.py")], capture_output=True, text=True,
                       env={**__import__("os").environ, "PYTHONUTF8": "1"})
    if r.returncode != 0:
        print("拒绝推送：" + (r.stdout or r.stderr).strip()[-600:])
    return r.returncode == 0


def push(host, jobs_file="jobs.json", with_vision=None):
    if not thread_guard_ok():
        return False
    chk = ssh(host, f"cd {DEST} 2>/dev/null && ls {' '.join(VISION)} 2>/dev/null | wc -l")
    have = chk.stdout.decode().strip()
    if not have.isdigit():
        # K-OPS-311 附：探测 ssh 没连上时 have = ""，旧代码把 36 MB 视觉模型也塞进推送包（16:57 推 48.1 MB，跳板约 17 KB/s）
        print(f"连不上 {host}（{chk.stderr.decode(errors='replace').strip()[-160:]}），这轮不推")
        return False
    files = CODE_FILES + [f"{VID_REL}/{jobs_file}"] + inputs_for(host, jobs_file)
    if with_vision or have != "2":
        files += VISION
    files = [f for f in files if not f.startswith(VID_REL + "/control_")]
    blob = build_tar(files, CODE_DIRS)
    print(f"推送 {len(files)} 个文件 + {len(CODE_DIRS)} 个目录，{len(blob) / 1e6:.1f} MB → {host}:{DEST}")
    pre = ""
    if host == "gpu36":
        pre = ("mkdir -p /root/work/fredw/tools_bin && ln -sf /root/work/fredw/venv/lib/python3.12/site-packages/imageio_ffmpeg/"
               "binaries/ffmpeg-linux-x86_64-v7.0.2 /root/work/fredw/tools_bin/ffmpeg; ")
    post = ("; [ -f tools/series10_video/ffprobe_shim.py ] && cp tools/series10_video/ffprobe_shim.py /root/work/fredw/tools_bin/ffprobe "
            "&& chmod +x /root/work/fredw/tools_bin/ffprobe" if host == "gpu36" else "")
    r = ssh(host, f"{pre}mkdir -p {DEST} && cd {DEST} || exit 1; tar xzf - {post}; echo PUSH_OK", blob, timeout=3600)
    print((r.stdout + r.stderr).decode(errors="replace").strip()[-400:])
    return r.returncode == 0


def control(host, js: str):
    d = json.loads(js)
    blob = json.dumps(d, ensure_ascii=False, indent=1).encode()
    r = ssh(host, f"mkdir -p {DEST}/{VID_REL} && cat > {DEST}/{VID_REL}/control_{host}.json && echo CTRL_OK", blob)
    print((r.stdout + r.stderr).decode(errors="replace").strip())


def start(host):
    cmd = (f"cd {DEST} || exit 1; mkdir -p run {VID_REL}; "
           f"if [ -f run/vidgen.pid ] && kill -0 $(cat run/vidgen.pid) 2>/dev/null; then echo ALREADY $(cat run/vidgen.pid); exit 0; fi; "
           f"PYTHONUTF8=1 nohup {PY} -u tools/series10_video/vidgen.py run {host} >> {VID_REL}/vidgen_{host}.out 2>&1 < /dev/null & "
           f"echo $! > run/vidgen.pid; echo STARTED $(cat run/vidgen.pid)")
    print(ssh(host, cmd).stdout.decode(errors="replace").strip())


def stop(host):
    cmd = (f"cd {DEST} || exit 1; if [ -f run/vidgen.pid ] && kill -0 $(cat run/vidgen.pid) 2>/dev/null; then "
           f"pid=$(cat run/vidgen.pid); kill $pid; for i in $(seq 20); do kill -0 $pid 2>/dev/null || break; sleep 1; done; "
           f"kill -0 $pid 2>/dev/null && kill -9 $pid; echo STOPPED $pid; else echo NOT_RUNNING; fi; rm -f run/vidgen.pid")
    print(ssh(host, cmd).stdout.decode(errors="replace").strip())


def status(host):
    cmd = (f"cd {DEST} || exit 1; [ -f run/vidgen.pid ] && kill -0 $(cat run/vidgen.pid) 2>/dev/null && echo RUNNING $(cat run/vidgen.pid) || echo NOT_RUNNING; "
           f"tail -15 {VID_REL}/vidgen_{host}.log 2>/dev/null; tail -5 {VID_REL}/vidgen_{host}.out 2>/dev/null; "
           f"nvidia-smi --query-gpu=index,utilization.gpu,memory.used,power.draw --format=csv,noheader")
    print(ssh(host, cmd).stdout.decode(errors="replace").strip())


def main(argv):
    if len(argv) < 2 or argv[0] not in ("push", "control", "start", "stop", "status") or argv[1] not in ("gpu33", "gpu36"):
        print(__doc__)
        return 2
    act, host = argv[0], argv[1]
    if act == "push":
        jf = argv[argv.index("--jobs") + 1] if "--jobs" in argv else "jobs.json"
        return 0 if push(host, jf) else 1
    if act == "control":
        control(host, argv[2])
    elif act == "start":
        start(host)
    elif act == "stop":
        stop(host)
    else:
        status(host)
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv[1:]))
