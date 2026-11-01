"""审片适配：调用 tools/ep02_director/review.py（clips / episode 模式，子进程，项目 .venv），把 review.json 每镜指标
压平成规则表能用的一组数，并和 RenderPlan 的验收阈值比较。

- ReviewPy：真审片（CPU）。
- ScriptedReviewer：dry-run / 测试用，指标来自脚本（{镜: [第1次指标, 第2次指标, …]}），不读视频。
主观观感（鬼影、多肢、表演自然度）机器量不准：只出接触印样路径 + 问题清单，交剪辑导演 agent（见 loop.director_queue）。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PY = ROOT / ".venv" / "Scripts" / "python.exe"
REVIEW = ROOT / "tools" / "ep02_director" / "review.py"
OUT_BASE = ROOT / "data" / "ab" / "director"


def flatten(shot: dict) -> dict:
    """review.json 的一镜 → 扁平指标"""
    m = shot.get("motion", {}) or {}
    c = shot.get("colour", {}) or {}
    idn = shot.get("identity", {}) or {}
    people = idn.get("people") or {}
    # V2 2026-10-31：“other”是没按发色认出的人（review.py 拿它猜着比顾沉旧参考，LEARNING_BACKLOG B14），
    # 不是已确认的身份参考，不进 sface_ref_min（否则顾沉没定设定图前每个双人镜都必然判身份不过、白烧重出次数）
    refs = [p.get("ref_cos_med") for k, p in people.items() if k != "other" and p.get("ref_cos_med") is not None]
    selfs = [p.get("self_cos_min") for p in people.values() if p.get("self_cos_min") is not None and p.get("n", 0) >= 3]
    sync = [s.get("corr_lag0") for s in shot.get("lip_sync") or [] if s.get("corr_lag0") is not None]
    out = {
        "still_frac": m.get("still_frac"),
        "frozen_tail_s": m.get("frozen_tail_s"),
        "frozen_head_s": m.get("frozen_head_s"),
        "J4": m.get("J4"), "J4_z": m.get("J4_z"),
        "dark_run_s": m.get("dark_run_s"),
        "pace": m.get("pace_px_per_frame"),
        "cheek_a_drift": abs(c["cheek_a_max_drift"]) if c.get("cheek_a_max_drift") is not None else None,
        "cheek_red_max": c.get("cheek_red_max"),
        "red_blob_max": c.get("frame_red_blob_max"),
        "sface_ref_min": min(refs) if refs else None,
        "sface_self_min": min(selfs) if selfs else None,
        "lipsync_corr": sorted(sync)[len(sync) // 2] if sync else None,
        "face_sharp": idn.get("face_sharp_lapvar_med"),
    }
    # ITERAUDIT 2026-11-01：量不到的指标不再静默丢掉——记进 _untested，failures() 对“有阈值但没测到”的项判未测（不算通过）。
    # 是否适用由验收阈值决定（编译器对无人物镜 / 无画内对白镜把阈值设为 None），这里只如实记录“没测到”。
    untested = sorted(k for k, v in out.items() if v is None)
    return {k: v for k, v in out.items() if v is not None} | {"_sheet": shot.get("sheet"), "_flags": shot.get("flags", []),
                                                              "_untested": untested}


# 验收：指标名 → (阈值键, 方向)。方向 max = 指标 ≤ 阈值通过；min = 指标 ≥ 阈值通过
ACCEPT = {
    "still_frac": ("still_frac_max", "max_lt"),
    "frozen_tail_s": ("frozen_tail_s_max", "max_lt"),
    "frozen_head_s": ("frozen_head_s_max", "max_lt"),
    "cheek_a_drift": ("cheek_a_drift_max", "max_lt"),
    "cheek_red_max": ("cheek_red_max", "max_lt"),
    "red_blob_max": ("red_blob_max", "max_lt"),
    "dark_run_s": ("dark_run_s_max", "max_lt"),
    "sface_ref_min": ("sface_ref_min", "min"),
    "sface_self_min": ("sface_self_min", "min"),
    "lipsync_corr": ("lipsync_corr_min", "min"),
}


def failures(metrics: dict, acceptance: dict) -> list[dict]:
    """不通过项。阈值为 None = 本镜不适用（编译器定）→ 跳过；有阈值但指标没测到 = 未测 → 记一条 untested 失败
    （ITERAUDIT 2026-11-01：以前这里 continue，没检测到脸时身份项直接算过；与 GEN_CONTRACT postflight“未测 ≠ 通过”统一）。"""
    out = []
    for k, (ak, how) in ACCEPT.items():
        thr = acceptance.get(ak)
        if thr is None:
            continue
        v = metrics.get(k)
        if v is None:
            out.append({"metric": k, "value": None, "threshold": thr, "untested": True})
            continue
        bad = v >= thr if how == "max_lt" else v < thr
        if bad:
            out.append({"metric": k, "value": v, "threshold": thr})
    j4, z = metrics.get("J4"), metrics.get("J4_z")
    if acceptance.get("j4_max") is not None:
        if j4 is None:
            out.append({"metric": "J4", "value": None, "threshold": acceptance["j4_max"], "untested": True})
        elif j4 >= acceptance["j4_max"] and (z is None or acceptance.get("j4_z_max") is None or z >= acceptance["j4_z_max"]):
            out.append({"metric": "J4", "value": j4, "threshold": acceptance["j4_max"], "z": z})
    return out


class ReviewPy:
    dry = False

    def __init__(self, python: Path = PY, timeout: float = 1800):
        self.python, self.timeout = python, timeout

    def _run(self, args: list[str]) -> None:
        r = subprocess.run([str(self.python), str(REVIEW), *args], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=self.timeout, cwd=str(ROOT))
        if r.returncode != 0:
            raise RuntimeError(f"review.py 失败：{(r.stderr or r.stdout)[-600:]}")

    def clips(self, name: str, items: dict[str, str]) -> dict[str, dict]:
        self._run(["clips", "--name", name, *[f"{k}={v}" for k, v in items.items()]])
        rep = json.loads((OUT_BASE / name / "review.json").read_text(encoding="utf-8"))
        return {s["shot"]: flatten(s) for s in rep["shots"]}

    def episode(self, name: str, video: str, timeline: str) -> dict:
        self._run(["episode", video, timeline, "--name", name])
        return json.loads((OUT_BASE / name / "review.json").read_text(encoding="utf-8"))


class ScriptedReviewer:
    """dry-run：scenario = {镜 id: [指标 dict, …]}（第 i 次审片取第 i 个，超出取最后一个）；没写的镜给“全过”指标"""
    dry = True
    PASS = {"still_frac": 0.2, "frozen_tail_s": 0.1, "frozen_head_s": 0.0, "J4": 1.08, "J4_z": 0.5,
            "dark_run_s": 0.0, "cheek_a_drift": 2.0, "cheek_red_max": 0.05, "red_blob_max": 0.0,
            "sface_ref_min": 0.45, "sface_self_min": 0.8, "lipsync_corr": 0.5}

    def __init__(self, scenario: dict | None = None):
        self.scenario = scenario or {}
        self.count: dict[str, int] = {}

    def clips(self, name: str, items: dict[str, str]) -> dict[str, dict]:
        out = {}
        for sid in items:
            seq = self.scenario.get(sid) or [{}]
            i = self.count.get(sid, 0)
            self.count[sid] = i + 1
            out[sid] = {**self.PASS, **seq[min(i, len(seq) - 1)], "_sheet": f"data/ab/director/{name}/sheets/{sid}.jpg",
                        "_flags": []}
        return out

    def episode(self, name: str, video: str, timeline: str) -> dict:
        return {"name": name, "dry_run": True, "auto_scores": {}, "shots": []}


def load_scenario(path: str | None) -> dict:
    if not path:
        return {}
    return json.loads(Path(path).read_text(encoding="utf-8"))


if __name__ == "__main__":   # 手动：python reviewer.py <review.json> → 打印扁平指标
    rep = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    for s in rep["shots"]:
        print(s["shot"], flatten(s))
