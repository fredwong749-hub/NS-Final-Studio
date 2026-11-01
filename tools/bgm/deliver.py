"""BGM 交付（agent 与界面“换用这一版”共用）：候选 flac → data/music/series10/epNN.wav + epNN.json（合成格式）+ meta.json 记录。"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def jload(p: Path, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def jsave(p: Path, d) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


def load_cfg() -> dict:
    return json.loads((ROOT / "config" / "bgm.json").read_text(encoding="utf-8"))


def out_dir(cfg: dict | None = None) -> Path:
    return ROOT / (cfg or load_cfg())["output"]["dir"]


def ffmpeg() -> str:
    f = shutil.which("ffmpeg")
    if not f:
        raise RuntimeError("找不到 ffmpeg")
    return f


def loudnorm(src: Path, dst: Path, lufs: float = -16.0, tp: float = -1.0, lra: float = 20.0) -> dict:
    """ffmpeg 两遍 loudnorm（EBU R128）：先测，再按测量值归一；整体增益够不到目标（真峰卡住）时 ffmpeg 自动转动态模式
    （透明限幅）。输出 48 kHz；dst 后缀决定编码（.flac / .wav=24-bit）。返回 ffmpeg 第二遍报告。"""
    import re as _re
    ff = ffmpeg()
    base = f"loudnorm=I={lufs}:TP={tp - 0.5}:LRA={lra}"   # 动态模式真峰会超出目标约 0.3 dB（ep06 实测 −0.7），留 0.5 dB 余量
    r1 = subprocess.run([ff, "-hide_banner", "-nostats", "-i", str(src), "-af", base + ":print_format=json", "-f", "null", "-"],
                        capture_output=True, text=True)
    m = json.loads(_re.findall(r"\{[^{}]*\"input_i\"[^{}]*\}", r1.stderr)[-1])
    af = (f"{base}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:"
          f"measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true:print_format=json")
    tmp = dst.with_name(dst.stem + ".tmp" + dst.suffix)
    codec = ["-c:a", "flac", "-sample_fmt", "s32"] if dst.suffix == ".flac" else ["-c:a", "pcm_s24le"]
    r2 = subprocess.run([ff, "-y", "-hide_banner", "-nostats", "-i", str(src), "-af", af, "-ar", "48000", "-ac", "2", *codec, str(tmp)],
                        capture_output=True, text=True)
    if r2.returncode != 0:
        raise RuntimeError(r2.stderr[-300:])
    tmp.replace(dst)
    out = json.loads(_re.findall(r"\{[^{}]*\"output_i\"[^{}]*\}", r2.stderr)[-1])
    return {"input_i": float(m["input_i"]), "input_tp": float(m["input_tp"]), "output_i": float(out["output_i"]),
            "output_tp": float(out["output_tp"]), "normalization_type": out.get("normalization_type")}


def flac_to_wav(src: Path, dst: Path) -> None:
    tmp = dst.with_name(dst.stem + ".tmp.wav")
    r = subprocess.run([ffmpeg(), "-y", "-v", "error", "-i", str(src), "-c:a", "pcm_s24le", "-ar", "48000", "-ac", "2", str(tmp)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-300:])
    tmp.replace(dst)


def assembly_meta(ep: int, brief: dict, chosen: dict, cfg: dict, wav: Path) -> dict:
    """ns_post.music.find_music 读的 epNN.json。cue 时间轴按 brief.sections（整集一条；强度统一 2，曲子自带动态，
    不再按段落叠加电平）；duck = 人声处压低深度（assemble 按逐句 placement 压）"""
    tl = brief["_timeline"]
    starts = [s["start_s"] for s in tl["shots"]]
    durs = [s["dur_s"] for s in tl["shots"]]

    def shot_pos(t):   # 第几段（从 1 起；与 ns_post.music 的 shot 语义一致）
        return max((k + 1 for k, s in enumerate(tl["shots"]) if s["start_s"] <= t + 1e-6), default=1)
    cc = brief.get("cue_change") or {}
    cues = []
    for k, s in enumerate(brief["sections"]):
        pos = shot_pos(float(s["t0"]))
        cues.append({"shot": pos, "start_s": float(s["t0"]), "offset_s": round(float(s["t0"]) - starts[pos - 1], 3),
                     "action": "enter" if k == 0 else "continue", "intensity": 2,
                     "text": f"{s['name']}：{s.get('note_en', '')}" +
                             ("（换段）" if cc.get("has") and abs(float(cc.get("at_s", -99)) - float(s["t0"])) <= 2 else "")})
    return {"episode": ep, "version": "bgm10/1", "file": wav.name, "duration_s": chosen["metrics"]["duration_s"],
            "episode_duration_s": tl["duration_s"], "shot_starts": starts, "shot_durations": durs, "cues": cues,
            "duck_spans": [], "duck": {"dialogue_db": cfg["output"]["duck_dialogue_db"], "vo_db": cfg["output"]["duck_vo_db"]},
            "bpm": chosen["bpm_param"], "keyscale": brief.get("key"), "model": chosen["model"], "seed": chosen["seed"],
            "candidate": chosen["id"], "prompt": chosen["caption"], "sha256": hashlib.sha256(wav.read_bytes()).hexdigest(),
            "level": f"{cfg['output']['lufs']} LUFS integrated, true peak ≤ {cfg['output']['true_peak_db']} dBTP；"
                     "assemble 再按 cues 强度与人声压低（duck）混入",
            "brief": f"{cfg['output']['dir']}/ep{ep:02d}/brief.json", "meta": f"{cfg['output']['dir']}/ep{ep:02d}/meta.json",
            "created": time.strftime("%Y-%m-%dT%H:%M:%S")}


def deliver(ep: int, state: dict, cfg: dict, chosen_id: str, reason: str, by: str) -> dict:
    """把候选 chosen_id 设为本集配乐；state = meta.json 内容（就地更新，调用方保存）"""
    od = out_dir(cfg)
    d = od / f"ep{ep:02d}"
    c = next((x for x in state.get("candidates") or [] if x["id"] == chosen_id), None)
    if c is None or not c.get("gate_pass"):
        raise ValueError(f"候选 {chosen_id} 不存在或没过闸门")
    brief = jload(d / "brief.json")
    if not brief:
        raise ValueError(f"缺 brief：{d / 'brief.json'}")
    wav = od / f"ep{ep:02d}.wav"
    flac_to_wav(d / "cands" / f"{chosen_id}.flac", wav)
    jsave(od / f"ep{ep:02d}.json", assembly_meta(ep, brief, c, cfg, wav))
    old = state.get("chosen") or {}
    prev = old.get("id")
    state["chosen"] = {"id": chosen_id, "by": by, "reason": reason, "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                       "wav": f"{cfg['output']['dir']}/ep{ep:02d}.wav", "previous": prev}
    if old.get("id") == chosen_id and old.get("reason") == reason:      # 同一条重交付：人话改写照旧
        for k in ("reason_plain", "reason_evidence", "reason_plain_by"):
            if old.get(k):
                state["chosen"][k] = old[k]
    elif by.startswith("界面"):                                          # 项目方换用：理由本来就是人话
        state["chosen"]["reason_plain"] = reason
    state.setdefault("history", []).append(dict(state["chosen"]))
    state["status"] = "delivered"
    return state


def choose(ep: int, chosen_id: str, *, by: str, reason: str) -> dict:
    """界面一键换用：更新 wav / json / meta.json"""
    cfg = load_cfg()
    mp = out_dir(cfg) / f"ep{ep:02d}" / "meta.json"
    state = jload(mp)
    if not state:
        raise ValueError(f"第 {ep} 集还没有配乐记录")
    deliver(ep, state, cfg, chosen_id, reason, by)
    jsave(mp, state)
    return state


def renorm_episode(ep: int, cfg: dict | None = None, force: bool = False) -> dict:
    """维护：把本集已下载的候选 flac 重新两遍 loudnorm 到交付响度（只对还没有 metrics.delivery 的），再按原选择重写 epNN.wav / .json"""
    cfg = cfg or load_cfg()
    d = out_dir(cfg) / f"ep{ep:02d}"
    mp = d / "meta.json"
    st = jload(mp)
    if not st:
        return {}
    for c in st.get("candidates") or []:
        f = d / "cands" / f"{c['id']}.flac"
        m = c.get("metrics") or {}
        if not f.is_file() or (m.get("delivery") and not force):
            continue
        src = f.with_name(f"{c['id']}.src.flac")
        f.replace(src)
        m["delivery"] = loudnorm(src, f, cfg["output"]["lufs"], cfg["output"]["true_peak_db"])
        src.unlink(missing_ok=True)
    ch = st.get("chosen") or {}
    if ch.get("id"):
        hist = list(st.get("history") or [])
        deliver(ep, st, cfg, ch["id"], ch.get("reason") or "", ch.get("by") or "")
        st["chosen"]["previous"] = ch.get("previous")
        st["history"] = hist or [dict(st["chosen"])]
    jsave(mp, st)
    return st


if __name__ == "__main__":
    import argparse
    import sys
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("renorm",))
    ap.add_argument("--eps", default="1-10")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from report import parse_eps  # noqa: PLC0415
    for e in parse_eps(a.eps):
        s = renorm_episode(e, force=a.force)
        print(e, (s.get("chosen") or {}).get("id"), [(c["id"], (c.get("metrics") or {}).get("delivery", {}).get("output_i"))
                                                     for c in s.get("candidates") or [] if (c.get("metrics") or {}).get("delivery")])
