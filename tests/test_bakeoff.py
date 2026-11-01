"""BAKEOFF（tools/bakeoff/run.py）的协议检查：K-REN-B03 提示词系统清理、K-OPS-B05 预检 / LoRA 白名单闸门、K-OPS-B06 让道。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# 用独立模块名加载：tools/autopilot/run.py 也叫 run，同一 pytest 进程里按名字 import 会撞（REFLOCK 11-01 全量测试报 no attribute 'BASE'）
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location("bakeoff_run", ROOT / "tools" / "bakeoff" / "run.py")
R = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(R)


def test_clean_prompt_drops_banned_suffix_and_trigger():
    p = ("图1是林晚的脸部参考（只取脸和发型）。lnwan_qi，近景构图，【林晚】22岁，真实皮肤质感，面部清晰对焦，"
         "专业电影镜头画面感，85mm人像镜头f/1.2大光圈，前景与背景奶油般柔焦虚化，浓郁饱和的暖色调电影调色，无字幕")
    c = R.clean_prompt(p)
    assert "lnwan_qi" not in c and not c.startswith("图1是")
    assert "奶油" not in c and "浓郁饱和" not in c and "f/1.2" not in c
    assert R.LEICA in c and c.endswith(R.TAIL)
    assert "近景构图" in c and "真实皮肤质感" in c          # 剧本内容不动


def _plan(loras, allow):
    return {"models": {"m": {"fam": "qedit", "loras": loras}}, "lora_allow": allow}


def test_submittable_blocks_unlisted_lora_and_failed_preflight():
    it = {"model": "m", "mode": "contract", "preflight": {"ok": True}}
    assert not R.submittable(it, _plan([("x.safetensors", 1.0)], []))
    assert R.submittable(it, _plan([("x.safetensors", 1.0)], ["x.safetensors"]))
    bad = {"model": "m", "mode": "contract", "preflight": {"ok": False, "fail": [{"id": "I2"}]}}
    assert not R.submittable(bad, _plan([], []))
    # 对照组（text / face）只放行“刻意缺资产”这几项；I8 不放行
    ctl = {"model": "m", "mode": "text", "preflight": {"ok": False, "fail": [{"id": "I3"}, {"id": "I4"}]}}
    assert R.submittable(ctl, _plan([], []))
    ctl8 = {"model": "m", "mode": "text", "preflight": {"ok": False, "fail": [{"id": "I8"}]}}
    assert not R.submittable(ctl8, _plan([], []))


def test_wait_yield_respects_hold_and_foreign_jobs(monkeypatch):
    calls = {"n": 0}
    monkeypatch.setattr(R, "hold_ports", lambda: {"8188"} if calls["n"] < 1 else set())
    queue = [{"queue_running": [[1, "a", {}, {"client_id": "imggen-s10-x"}]], "queue_pending": []},
             {"queue_running": [], "queue_pending": []}]

    def fake_api(url, path, data=None, timeout=60):
        if path == "/queue":
            return queue[min(calls["n"] - 1, 1)] if calls["n"] >= 1 else queue[1]
        return {}

    t = {"now": 1000.0}

    def fake_sleep(s):
        calls["n"] += 1
        t["now"] += s

    monkeypatch.setattr(R, "api", fake_api)
    monkeypatch.setattr(R.time, "sleep", fake_sleep)
    monkeypatch.setattr(R.time, "time", lambda: t["now"])
    R.wait_yield("http://x", "8188")
    # 先因 hold 等过、又见到别人的任务，之后至少空闲 YIELD_IDLE_S 才返回
    assert calls["n"] >= 2
    assert t["now"] - 1000.0 >= R.YIELD_IDLE_S


def test_refcopy_flags_board_collage_not_natural_frame():
    """K-REV-B07：参考板拼图（白色栅格分隔的多格）判“照抄参考”；连续画面（含门框等直线）不判"""
    import numpy as np
    spec = importlib.util.spec_from_file_location("bakeoff_refcopy", ROOT / "tools" / "bakeoff" / "refcopy.py")
    RC = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(RC)
    rng = np.random.default_rng(0)
    nat = (rng.normal(110, 30, (1344, 768, 3))).clip(0, 255).astype(np.uint8)
    nat[:, 380:390] = 30                                   # 一根暗色门框竖线（不是白栅格）
    board = nat.copy()
    board[660:684, :] = 255                                # 横向白栅格
    board[:, 372:396] = 255                                # 竖向白栅格
    RC._REF.clear()
    RC._REF["dummy"] = RC.feat(np.full((100, 100, 3), 128, np.uint8) + rng.integers(0, 5, (100, 100, 3), dtype=np.uint8))
    assert RC.gutters(board) >= 1 and RC.ref_copy_score(board)["copied"]
    assert RC.gutters(nat) == 0 and not RC.ref_copy_score(nat)["copied"]
