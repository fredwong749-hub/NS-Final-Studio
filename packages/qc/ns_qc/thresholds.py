"""Gate table: one row per gate id — metric, comparison, threshold, level on breach, documentary source.

status:
  locked     the value is a locked row in docs/SOP_parameters.md or a locked rule in docs/audit/rule_ids.md
  documented written in a project doc / gpu3 code but not locked (consistency_impl.md, gpu3 constants)
  suggested  only proposed in docs/production_issues.md (not locked) → the gate may only warn
  pending    no documented number: 待项目方定 → informational / warn

on_breach: "fail" only for locked/documented gates; everything else "warn". `info` gates never change a verdict.
Gate ids use the Q- prefix so they never collide with rule_ids/v1 (claude-sop owns that table).
"""
from __future__ import annotations

import operator

PENDING = "待项目方定"

T: dict[str, dict] = {
    # ---- video vs keyframes (PI-08 / PI-19) ----
    "Q-K1": dict(pi=["PI-08"], metric="video_size", op="==", value=[768, 1344], on_breach="fail", status="locked",
                 source="rule_ids P-B3 (24 fps, 768×1344)"),
    "Q-K1b": dict(pi=["PI-08"], metric="keyframe_aspect_rel_diff", op="<=", value=0.01, on_breach="fail",
                  status="locked", source="rule_ids P-B2 (same 4:7 centre crop for first/last; stretch vs crop → ghosting)"),
    "Q-K2": dict(pi=["PI-08"], metric="first_frame_psnr_db", op=">=", value=20.0, on_breach="fail", status="locked",
                 source="SOP_parameters 视频 QC（锁定 2026-10-29）: 首帧 PSNR ≥20 dB"),
    "Q-K3": dict(pi=["PI-08"], metric="last_frame_ssim", op=">=", value=0.55, on_breach="fail", status="documented",
                 source="consistency_impl §二 视频闸门; gpu3 weita_series LAST_SSIM_MIN = 0.55"),
    "Q-K4": dict(pi=["PI-19"], metric="edge_dE2000", op="<=", value=4.0, on_breach="warn", status="suggested",
                 source="production_issues PI-19: 前/后 0.5 s 与首/尾帧人物区域 ΔE2000 ≤ 4（建议值，未锁定）"),
    "Q-K5": dict(pi=["PI-19"], metric="max_abs_dL", op="<=", value=8.0, on_breach="warn", status="suggested",
                 source="production_issues PI-19: 全片 L* 相对首帧漂移 ≤ 8（建议值，未锁定）"),
    "Q-K6": dict(pi=["PI-08"], metric="first_frame_ssim", op=">=", value=None, on_breach="info", status="pending",
                 source=f"no documented SSIM bound for the first frame ({PENDING}); reported only"),
    # ---- in-shot drift (PI-01 / PI-03 / PI-04) ----
    "Q-D1": dict(pi=["PI-01"], metric="sface_median", op=">=", value=0.30, on_breach="fail", status="locked",
                 source="SOP_parameters 视频 QC（锁定）: SFace 中位数 ≥0.30; gpu3 SIM_CLIP_MIN"),
    "Q-D2": dict(pi=["PI-01"], metric="sface_min_2s_window_median", op=">=", value=0.20, on_breach="warn",
                 status="suggested", source="production_issues PI-01: 任意连续 2 秒最小值 ≥0.20（建议值）"),
    "Q-D3": dict(pi=["PI-03"], metric="hair_hsv_bad_frames", op="==", value=0, on_breach="warn", status="documented",
                 source="S3-F3 hair_colour (gpu3 weita_series.hair_colour) applied per sampled video frame; frame "
                        "gate is block, the video use is new → warn"),
    "Q-D4": dict(pi=["PI-03"], metric="hair_max_dE2000_vs_first", op="<=", value=12.0, on_breach="warn",
                 status="suggested", source="production_issues PI-03: 头发 LAB ΔE ≤ 12（建议值）"),
    "Q-D5": dict(pi=["PI-04"], metric="torso_ab_bhattacharyya_max", op="<=", value=0.45, on_breach="warn",
                 status="suggested", source="production_issues PI-04: 人物区域 LAB 直方图相对首帧 Bhattacharyya ≤0.45（建议值）"),
    "Q-D6": dict(pi=["PI-04"], metric="torso_dominant_dE2000_max", op="<=", value=None, on_breach="info",
                 status="pending", source=f"dominant clothing colour drift; no documented bound ({PENDING})"),
    # ---- audio (PI-11 / PI-12 / PI-13 / PI-14) ----
    "Q-A1": dict(pi=["PI-11"], metric="clap_music_score", op="<=", value=0.30, on_breach="warn", status="suggested",
                 source="production_issues PI-11: non_diegetic_music = N/A 时 CLAP music ≤0.30（建议值）"),
    "Q-A1b": dict(pi=["PI-11"], metric="bed_tonal_ratio", op="<=", value=None, on_breach="info", status="pending",
                  source=f"DSP proxy for sustained tonal content in the non-vocal bed ({PENDING}); reported only"),
    "Q-A2": dict(pi=["PI-14"], metric="h3_integrated_lufs", op="in", value=[-30.0, -16.0], on_breach="warn",
                 status="suggested", source="production_issues PI-14: H3 原声 −30…−16 LUFS（建议值）"),
    "Q-A2b": dict(pi=["PI-14"], metric="h3_true_peak_dbtp", op="<=", value=-1.0, on_breach="warn", status="suggested",
                  source="production_issues PI-14 / SOP_parameters S5 响度（待验证）: 真峰值 ≤ −1 dBTP"),
    "Q-A3": dict(pi=["PI-13"], metric="male_f0_voiced_s", op="<=", value=0.5, on_breach="warn", status="suggested",
                 source="production_issues PI-13: F0 中位数 <165 Hz 的人声段 >0.5 s 且本镜不允许男声 → 报（建议值）"),
    "Q-A4": dict(pi=["PI-13"], metric="pitch_band_count_excess", op="<=", value=0, on_breach="warn",
                 status="pending", source=f"speaker-count proxy: voiced pitch bands (<165 Hz / ≥165 Hz, each >0.5 s) "
                                          f"vs genders of the H3 dialogue speakers ({PENDING}; no speaker-embedding model locally)"),
    "Q-A5": dict(pi=["PI-12"], metric="voiced_s_first_1s", op="<", value=0.3, on_breach="warn", status="suggested",
                 source="production_issues PI-12: 无对白镜头前 1.0 s 语音 <0.3 s（建议值）"),
    # ---- provenance (PI-24 / PI-25) ----
    "Q-P1": dict(pi=["PI-25", "PI-05"], metric="bible_version", op="==current", value=None, on_breach="fail",
                 status="locked", source="rule_ids R-C8 (输入未过期：take 的 bible_version 等于当前值) — block"),
    "Q-P2": dict(pi=["PI-25"], metric="prompt_compiled_after_render", op="==", value=False, on_breach="warn",
                 status="documented", source="PI-25: 规则/提示词改动后已出 take 必须标 stale; compiled.h3_prompt_compiled_at vs take.created_at"),
    "Q-P3": dict(pi=["PI-24"], metric="stems_video_sha_match", op="==", value=True, on_breach="fail",
                 status="documented", source="PI-24 / SOP S5: 每镜 video_sha256 必须等于 renders_gpu3 中的文件"),
    "Q-P4": dict(pi=["PI-08", "PI-24"], metric="keyframe_source_local", op="==", value=True, on_breach="warn",
                 status="documented", source="PI-08: 视频 take 实际用的首/尾帧要同步到 renders_gpu3"),
    "Q-P5": dict(pi=["PI-24"], metric="video_file_present_and_active", op="==", value=True, on_breach="warn",
                 status="documented", source="PI-24: 镜像里 video.mp4 = active video take（sha）"),
    "Q-P6": dict(pi=["PI-08", "PI-24"], metric="shown_frame_vs_video_frame0_structure", op=">=", value=0.85,
                 on_breach="warn", status="documented",
                 source="PI-08: 画布显示的帧（frame.png）必须是视频实际用的首帧; 0.85 = ns_post.colormatch match_min"),
    "Q-S1": dict(pi=["PI-24"], metric="sync_heartbeat_age_min", op="<=", value=30.0, on_breach="warn",
                 status="suggested", source="production_issues PI-24: 心跳超过 30 分钟没更新 → 报警（建议值）"),
}

_OPS = {">=": operator.ge, "<=": operator.le, "<": operator.lt, ">": operator.gt, "==": operator.eq}


def describe(gate: str) -> str:
    r = T[gate]
    v = r["value"]
    if r["op"] == "==current":
        return "== current bible_version"
    if v is None:
        return PENDING
    if r["op"] == "in":
        return f"{v[0]} … {v[1]}"
    return f"{r['op']} {v}"


def check(gate: str, value) -> bool | None:
    """True = within threshold, False = breach, None = no threshold (pending) or no value."""
    r = T[gate]
    if value is None or r["value"] is None:
        return None
    if r["op"] == "in":
        lo, hi = r["value"]
        return lo <= value <= hi
    if r["op"] == "==current":
        raise ValueError("use provenance.stamp_state for Q-P1")
    return bool(_OPS[r["op"]](value, r["value"]))


def judge(gate: str, value, *, detail: str = "", unchecked: str | None = None, **extra) -> dict:
    """One gate result. verdict: pass | warn | fail | info | unchecked (unchecked never counts as pass)."""
    r = T[gate]
    out = {"gate": gate, "pi": r["pi"], "metric": r["metric"], "value": value, "threshold": describe(gate),
           "status": r["status"], "on_breach": r["on_breach"], "source": r["source"]}
    if unchecked:
        out.update(verdict="unchecked", detail=unchecked)
    else:
        ok = check(gate, value)
        if ok is None:
            out["verdict"] = "info" if value is not None else "unchecked"
        else:
            out["verdict"] = "pass" if ok else ("info" if r["on_breach"] == "info" else r["on_breach"])
        if detail:
            out["detail"] = detail
    out.update(extra)
    return out


def judge_bool(gate: str, ok: bool, value, *, detail: str = "", **extra) -> dict:
    """Gate result for gates whose comparison is not a plain number (versions, hashes)."""
    r = T[gate]
    out = {"gate": gate, "pi": r["pi"], "metric": r["metric"], "value": value, "threshold": describe(gate)
           if r["op"] != "==current" else "== current bible_version", "status": r["status"],
           "on_breach": r["on_breach"], "source": r["source"], "verdict": "pass" if ok else r["on_breach"]}
    if detail:
        out["detail"] = detail
    out.update(extra)
    return out


def worst(verdicts) -> str:
    order = {"fail": 3, "warn": 2, "unchecked": 1, "pass": 0, "info": 0}
    v = max(verdicts, key=lambda x: order.get(x, 0), default="pass")
    return "pass" if v == "info" else v
