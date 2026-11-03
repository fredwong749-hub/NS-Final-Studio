"""BGM 交付（agent 与界面“换用这一版”共用）：候选 flac → <本剧 BGM 目录>/epNN.wav + epNN.json（合成格式）+ meta.json 记录。
本剧 BGM 目录 = out_dir()：V1 = data/music/series10；V2 = data/music/<剧>（曲库模式，写入方 tools/bgm/bgm_library.py）。"""
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


def current_run() -> str | None:
    """当前剧（NS_RUN / runs.json primary，经 ns_agent.run_paths）；没有登记表 = None（旧行为）"""
    import sys as _sys
    p = str(ROOT / "services" / "agent")
    if p not in _sys.path:
        _sys.path.insert(0, p)
    from ns_agent import run_paths as RP   # noqa: PLC0415
    return RP.current_run(ROOT)


def is_legacy_run(run: str | None) -> bool:
    import sys as _sys
    p = str(ROOT / "services" / "agent")
    if p not in _sys.path:
        _sys.path.insert(0, p)
    from ns_agent import run_paths as RP   # noqa: PLC0415
    m = RP.runs_module(ROOT)
    return m is None or not (ROOT / "config/pipeline/runs.json").is_file() or bool(m.is_legacy(run, ROOT))


def out_dir(cfg: dict | None = None, run: str | None = None) -> Path:
    """本剧的集级 BGM 目录（MERGE-VID-O，L-118 / L-131：不再写死 data/music/series10）：
    legacy 剧（V1）= config/bgm.json output.dir（data/music/series10）；其它剧 = ns_post.run_media.music_dir(<剧>)
    （data/music/<剧>，先校验 config/music_v2.json 曲库，不符 → V2MediaError 失败关闭）。run 不给 = 当前剧"""
    run = run or current_run()
    if run is None or is_legacy_run(run):
        return ROOT / (cfg or load_cfg())["output"]["dir"]
    import sys as _sys
    p = str(ROOT / "services" / "post")
    if p not in _sys.path:
        _sys.path.insert(0, p)
    from ns_post import run_media as RM   # noqa: PLC0415
    return RM.music_dir(run, ROOT)


def ffmpeg() -> str:
    f = shutil.which("ffmpeg")
    if not f:
        raise RuntimeError("找不到 ffmpeg")
    return f


LEVEL_TOL_LU = 0.5     # 交付响度偏离目标的容差（STYLE-V2 11-02：瞬态很尖的音轨两遍 loudnorm 只到 −19.98 LUFS，原来静默交付偏轻的音轨）


def _loudnorm_2pass(ff: str, src: Path, dst: Path, lufs: float, tp: float, lra: float) -> dict:
    import re as _re
    base = f"loudnorm=I={lufs}:TP={tp - 0.5}:LRA={lra}"   # 动态模式真峰会超出目标约 0.3 dB（ep06 实测 −0.7），留 0.5 dB 余量
    r1 = subprocess.run([ff, "-hide_banner", "-nostats", "-i", str(src), "-af", base + ":print_format=json", "-f", "null", "-"],
                        capture_output=True, text=True, timeout=600)
    m = json.loads(_re.findall(r"\{[^{}]*\"input_i\"[^{}]*\}", r1.stderr)[-1])
    af = (f"{base}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:"
          f"measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true:print_format=json")
    tmp = dst.with_name(dst.stem + ".tmp" + dst.suffix)
    codec = ["-c:a", "flac", "-sample_fmt", "s32"] if dst.suffix == ".flac" else ["-c:a", "pcm_s24le"]
    r2 = subprocess.run([ff, "-y", "-hide_banner", "-nostats", "-i", str(src), "-af", af, "-ar", "48000", "-ac", "2", *codec, str(tmp)],
                        capture_output=True, text=True, timeout=600)
    if r2.returncode != 0:
        raise RuntimeError(r2.stderr[-300:])
    tmp.replace(dst)
    out = json.loads(_re.findall(r"\{[^{}]*\"output_i\"[^{}]*\}", r2.stderr)[-1])
    return {"input_i": float(m["input_i"]), "input_tp": float(m["input_tp"]), "output_i": float(out["output_i"]),
            "output_tp": float(out["output_tp"]), "normalization_type": out.get("normalization_type")}


def _prelimit(ff: str, src: Path, dst: Path, gain_db: float, tp: float) -> None:
    """重做用：192 kHz 下先加增益再快速限幅（attack 0.1 ms / release 10 ms），压住尖瞬态，让 loudnorm 的线性增益够得到目标"""
    lim = 10 ** ((tp - 0.5) / 20)
    af = (f"aresample=192000,volume={gain_db:.2f}dB,alimiter=limit={lim:.4f}:attack=0.1:release=10:level=false,"
          f"aresample=48000")
    r = subprocess.run([ff, "-y", "-hide_banner", "-nostats", "-i", str(src), "-af", af, "-c:a", "pcm_f32le", str(dst)],
                       capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-300:])


def loudnorm(src: Path, dst: Path, lufs: float = -16.0, tp: float = -1.0, lra: float = 20.0) -> dict:
    """ffmpeg 两遍 loudnorm（EBU R128）：先测，再按测量值归一；整体增益够不到目标（真峰卡住）时 ffmpeg 自动转动态模式
    （透明限幅）。输出 48 kHz；dst 后缀决定编码（.flac / .wav=24-bit）。返回 ffmpeg 第二遍报告。
    交付检查：output_i 偏离目标 > LEVEL_TOL_LU → 报警（stderr + 返回 level_warn）并重做一次（先限幅再两遍 loudnorm）；
    重做后仍偏离 → level_ok=False（调用方 / 闸门据此拦），不静默交付。"""
    import sys as _sys
    ff = ffmpeg()
    rep = _loudnorm_2pass(ff, src, dst, lufs, tp, lra)
    dev = rep["output_i"] - lufs
    rep["level_dev_lu"] = round(dev, 2)
    rep["level_ok"] = abs(dev) <= LEVEL_TOL_LU
    if rep["level_ok"]:
        return rep
    warn = f"BGM 响度偏离目标 {dev:+.2f} LU（目标 {lufs} LUFS，实测 {rep['output_i']}，{Path(src).name}）→ 限幅后重做"
    print("WARN", warn, file=_sys.stderr, flush=True)
    import tempfile
    gain = max(0.0, -dev) + 1.0
    # best = (|偏差|, 限幅增益, 报告)：交付偏差最小的那一次，不是最后一次（OVERSIGHT-F P2）；第 1 遍（不限幅，增益 None）也算候选
    tries, best, last = [], (abs(dev), None, rep), None
    with tempfile.TemporaryDirectory(prefix="bgm_prelimit_") as td:   # 中间文件放系统临时目录，不落 data/music
        lim = Path(td) / "prelimit.wav"
        for _ in range(5):        # 限幅会吃掉一部分响度：按剩余偏差加增益，最多 5 次
            _prelimit(ff, src, lim, gain, tp)
            r = _loudnorm_2pass(ff, lim, dst, lufs, tp, lra)
            last = gain
            d = r["output_i"] - lufs
            tries.append({"prelimit_gain_db": round(gain, 2), "output_i": r["output_i"]})
            if abs(d) < best[0]:
                best = (abs(d), gain, r)
            if abs(d) <= LEVEL_TOL_LU:
                break
            gain += max(0.0, -d) + 1.0
        if best[1] != last:       # 最后写出的不是最好的那次 → 按最好那次重写 dst（None = 第 1 遍：不限幅直接两遍 loudnorm）
            if best[1] is None:
                _loudnorm_2pass(ff, src, dst, lufs, tp, lra)
            else:
                _prelimit(ff, src, lim, best[1], tp)
                _loudnorm_2pass(ff, lim, dst, lufs, tp, lra)
    rep2 = best[2]
    dev2 = rep2["output_i"] - lufs
    rep2.update(level_dev_lu=round(dev2, 2), level_ok=abs(dev2) <= LEVEL_TOL_LU, level_warn=warn,
                redo={"why": "level_dev", "first": {k: rep[k] for k in ("output_i", "output_tp", "normalization_type")},
                      "tries": tries, "kept_gain_db": None if best[1] is None else round(best[1], 2),
                      "kept": "first_pass" if best[1] is None else "prelimit"})
    if not rep2["level_ok"]:
        print("WARN", f"重做后仍偏离 {dev2:+.2f} LU：level_ok=False", file=_sys.stderr, flush=True)
    return rep2


def flac_to_wav(src: Path, dst: Path) -> None:
    tmp = dst.with_name(dst.stem + ".tmp.wav")
    r = subprocess.run([ffmpeg(), "-y", "-v", "error", "-i", str(src), "-c:a", "pcm_s24le", "-ar", "48000", "-ac", "2", str(tmp)],
                       capture_output=True, text=True, timeout=600)
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
    if state.get("mode") == "library":       # V2：配乐来自曲库（tools/bgm/bgm_library.py），换用 = 按指定曲目重铺整集
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).resolve().parent))
        import bgm_library as LB   # noqa: PLC0415
        return LB.deliver_episode(state.get("run") or current_run(), ep, track=chosen_id, by=by, reason=reason)
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
