"""K-OPS-V13（VQAGATE 2026-11-02 00:3x）：服务器上的打分 / 检测脚本必须限线程。
起因：v7_lipsync（insightface / onnxruntime）在 96 核服务器上一个进程吃到 7432% / 9052% CPU，两台负载 250 / 160，
拖慢 sshd 握手和 ComfyUI。规则：下面这些在服务器上按片子反复起的脚本，必须在第一个重型 import（cv2 / numpy /
onnxruntime / insightface / mediapipe / torch）之前设 OMP / MKL / OPENBLAS / NUMEXPR 线程环境变量（K-OPS-V13 标记块），
用 onnxruntime 的还要给会话设 intra_op_num_threads。静态检查，不 import 被查文件。

    .venv/Scripts/python.exe tools/qa/thread_guard.py      # 退出码 0 = 全过
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERVER_SCRIPTS = ["tools/series10_video/score_clip.py", "tools/series10_video/v6_limbs.py", "tools/series10_video/v7_lipsync.py",
                  "tools/series10_video/calibrate_v67.py", "tools/series10_video/v7_asr.py"]
HEAVY = re.compile(r"^\s*(import (cv2|numpy|onnxruntime|torch|mediapipe)\b|from (cv2|numpy|onnxruntime|torch|insightface|mediapipe)\b)")


def check(path: Path) -> list[str]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    first_heavy = next((i for i, ln in enumerate(lines) if HEAVY.match(ln)), None)
    cap = next((i for i, ln in enumerate(lines) if "OMP_NUM_THREADS" in ln and "environ" in "".join(lines[max(0, i - 2):i + 3])), None)
    bad = []
    if first_heavy is not None and (cap is None or cap > first_heavy):
        bad.append(f"{path.relative_to(ROOT).as_posix()}：第 {first_heavy + 1} 行重型 import 之前没有设线程环境变量（K-OPS-V13）")
    txt = "\n".join(lines)
    if re.search(r"^\s*(import onnxruntime|from insightface|import insightface)", txt, re.M) and "intra_op_num_threads" not in txt:
        bad.append(f"{path.relative_to(ROOT).as_posix()}：用了 onnxruntime / insightface，但没给会话设 intra_op_num_threads（K-OPS-V13）")
    return bad


def main() -> int:
    bad = [b for f in SERVER_SCRIPTS for b in check(ROOT / f)]
    for b in bad:
        print(b)
    print(f"thread_guard {'FAIL' if bad else 'PASS'}：{len(SERVER_SCRIPTS)} 个服务器打分脚本，{len(bad)} 处问题")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
