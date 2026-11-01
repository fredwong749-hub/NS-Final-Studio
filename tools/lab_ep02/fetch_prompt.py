"""LAB：隧道抖动导致提交脚本断开后，按 prompt_id 等结果并下载 mp4（不重渲）。
用法：.venv/Scripts/python.exe tools/lab_ep02/fetch_prompt.py <url> <prompt_id> <dest.mp4>"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "render_router"))
from ns_render.comfy_client import ComfyClient, ComfyError  # noqa: E402

url, pid, dest = sys.argv[1], sys.argv[2], Path(sys.argv[3])
c = ComfyClient(url, timeout=60)
while True:
    try:
        entry = c.wait(pid, 4 * 3600)
        break
    except ComfyError as e:
        print("retry", str(e)[:120], flush=True)
        time.sleep(30)
item = next(f for f in c.output_files(entry) if f["filename"].endswith(".mp4"))
for i in range(5):
    try:
        c.download(item, dest)
        break
    except ComfyError:
        time.sleep(15)
print("done", dest, flush=True)
