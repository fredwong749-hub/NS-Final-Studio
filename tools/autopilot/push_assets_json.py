"""一次性：把出图用的小 JSON（首帧作业、造型 / 场景覆盖、选定设定图）推到两台并核 sha（WORKFLOW，作业每次重编后用）。
用法：.venv/Scripts/python.exe tools/autopilot/push_assets_json.py [gpu36 gpu33]"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import resident_sync as RS  # noqa: E402

FILES = ["data/pipeline/runs/series10_v1/assets/first_frame_jobs.json", "data/pipeline/runs/series10_v1/assets/shot_looks.json",
         "data/pipeline/runs/series10_v1/assets/sheets_chosen.json"]

for h in (sys.argv[1:] or ["gpu36", "gpu33"]):
    try:
        RS.ssh(h, f"set -e; T=$(mktemp -d {RS.OFF}/.push.XXXXXX); tar xf - -C $T; cp -a $T/. {RS.R}/; rm -rf $T; echo ok",
               data=RS.tar_bytes(FILES), timeout=300, tries=4)
        v = RS.verify_sha(h, FILES)
        print(h, "pushed; sha mismatch", v["mismatch"], flush=True)
    except Exception as e:  # noqa: BLE001
        print(h, "ERR", repr(e)[:200], flush=True)
