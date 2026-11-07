# 11-08 总指令 第二部分 裁决 #5（R2 第四层）：eval/smoke.py OOM 检测把 producer 的“预防性停派”说明文字（免 OOM）当成 OOM。
# 红线：只修误报判定，不动评分口径 / 过门标准——真 OOM（含 review_scale 尾巴里的 CUDA out of memory）照报。
# 夹具 = eval/results/20261107-1322.json G4 evidence.oom 原样两行（A10 窗口同一份 producer 日志）。
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sp = importlib.util.spec_from_file_location("smoke_eval_t", ROOT / "eval/smoke.py")
S = importlib.util.module_from_spec(sp)
sp.loader.exec_module(S)
LINES = json.loads((ROOT / "tests/fixtures/smoke_oom_1108.json").read_text(encoding="utf-8"))
REAL = [
    '{"ts": "2026-11-07T20:26:11", "ev": "review_scale", "ok": true, "tail": "instance :8878 up {\\"last_error\\": \\"OutOfMemoryError: CUDA out of memory. Tried to allocate 162.00 MiB."}',
    "torch.cuda.OutOfMemoryError: CUDA out of memory. Tried to allocate 2.00 GiB",
    '{"ev": "render_error", "why": "OOM on lane gpu33:0"}',
    "CUDA_ERROR_OUT_OF_MEMORY",
]


def test_fixture_is_the_a10_false_positive():
    assert len(LINES) == 2 and all("review_resident_hold" in ln and "免 OOM" in ln for ln in LINES)


def test_preventive_hold_lines_not_oom():
    assert [ln for ln in LINES if S.is_oom_line(ln)] == []


def test_real_oom_still_reported():
    assert all(S.is_oom_line(ln) for ln in REAL)
