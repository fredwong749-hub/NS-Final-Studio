"""P0 安装后的一次性重启（K-OPS-R11）：逐道等队列连续空闲 ≥ idle_s 再重启，起来后用 /object_info 核节点。
    .venv/Scripts/python.exe tools/imglab/restart_lanes.py gpu33:0 gpu33:1 gpu33:3 gpu36:0
只重启点名的道（gpu36:1 借给 cm_r2、gpu36:2 看图卡不在默认清单）。"""
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOCAL = {"gpu33:0": 18188, "gpu33:1": 18189, "gpu33:3": 18191, "gpu36:0": 18288}
sys.path.insert(0, str(ROOT / "tools/autopilot"))
from resident_sync import SMOKE_LANE  # noqa: E402  服务器 ComfyUI 输出目录常量（唯一来源）；gpu36 的 comfy.sh 在其上两级


def _gpu36_comfy_sh() -> str:
    from pathlib import PurePosixPath
    return str(PurePosixPath(SMOKE_LANE["gpu36"][1]).parent.parent / "comfy.sh")


RESTART = {"gpu33:0": "systemctl restart ns-comfy@0-8188", "gpu33:1": "systemctl restart ns-comfy@1-8189",
           "gpu33:3": "systemctl restart ns-comfy@3-8191", "gpu36:0": _gpu36_comfy_sh() + " restart 0"}
NEED = ["FaceDetailer", "UltralyticsDetectorProvider", "DetailerForEach", "InpaintCropImproved", "InpaintStitchImproved",
        "DWPreprocessor", "ZImageFunControlnet", "ModelPatchLoader"]


def q(port):
    try:
        d = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/queue", timeout=10).read())
        return bool(d["queue_running"] or d["queue_pending"])
    except Exception:  # noqa: BLE001  # arch-ok: 连不上按忙处理（不重启）
        return True


def nodes(port):
    try:
        d = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/object_info", timeout=60).read())
        return set(d)
    except Exception:  # noqa: BLE001  # arch-ok: 还没起来，调用方轮询
        return None


def main(lanes, idle_s=120):
    for lane in lanes:
        port, since = LOCAL[lane], None
        while True:
            if q(port):
                since = None
            else:
                since = since or time.time()
                if time.time() - since >= idle_s:
                    break
            time.sleep(5)
        host = lane.split(":")[0]
        t0 = time.time()
        r = subprocess.run([sys.executable, str(ROOT / "tools/netfix/rsh.py"), host, RESTART[lane]], capture_output=True, text=True, timeout=180)
        got = None
        for _ in range(120):
            time.sleep(5)
            got = nodes(port)
            if got:
                break
        miss = [n for n in NEED if not got or n not in got]
        ref = sorted(n for n in (got or ()) if "eference" in n and "trength" in n)
        print(json.dumps({"lane": lane, "rc": r.returncode, "secs": round(time.time() - t0, 1), "missing": miss, "ref_strength_nodes": ref,
                          "at": time.strftime("%Y-%m-%dT%H:%M:%S")}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main(sys.argv[1:] or ["gpu33:0", "gpu33:1", "gpu33:3", "gpu36:0"])
