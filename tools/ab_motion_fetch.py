"""MOT：按 prompt id 从某条道取回 ab_motion_fix 的输出（等待时隧道超时 / 进程中断时用）。
用法：python tools/ab_motion_fetch.py <道> <prompt_id> <stem 如 S1_PIKA>"""
import sys
import time
sys.path.insert(0, "tools")
import ab_motion_fix as A
from ns_render.comfy_client import ComfyUnavailable

lane, pid, stem = sys.argv[1:4]
cl = A.client_for(lane)
for i in range(60):
    try:
        e = cl.wait(pid, 7200)
        break
    except ComfyUnavailable as ex:
        print("retry", ex, flush=True)
        time.sleep(20)
(A.OUT / "renders").mkdir(exist_ok=True)
for f in cl.output_files(e):
    if f["filename"].endswith(".mp4"):
        tag = "fp16" if "_fp16" in f["filename"] else "int8"
        cl.download(f, A.OUT / "renders" / f"{stem}_{tag}.mp4")
        print("got", tag, flush=True)
