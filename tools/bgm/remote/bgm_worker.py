"""BGM10 远端作业（gpu33，/root/work/fredw/bgm，自己的 venv）：选卡让道 → ACE-Step 纯器乐生成候选 → CPU 上打分 → 归一化。

    venv/bin/python bgm_worker.py run  --job jobs/<id>/job.json        生成 + 打分（写 jobs/<id>/result.json、progress.json）
    venv/bin/python bgm_worker.py probe                               各卡显存 / 利用率 / ComfyUI 队列
    venv/bin/python bgm_worker.py score --job jobs/<id>/job.json      只重新打分已有候选

GPU 规则：只用 allowed_gpus（gpu33 永不用 GPU2）；该卡 ComfyUI 队列空 + 利用率 ≤ util_max 连续 yield_s 秒才占用；
每条候选之间再查一次队列，别人来任务就停（剩下的候选记 yielded，下次再出）。超时回退 CPU（turbo）。
不改 nvidia-smi 功耗墙，不碰别人的进程；心跳写 /root/work/fredw/gpu_heartbeats/（笔记本端再镜像到面板）。
"""
from __future__ import annotations

import argparse
import gc
import json
import math
import os
import shutil
import subprocess
import sys
import time
import traceback
import urllib.request
from pathlib import Path

R = "/root/claude-kimi-ns-studio-v1"
ON_GPU33 = Path(R).is_dir()
HOST = "gpu33" if ON_GPU33 else "gpu36"
ACE_SRC = f"{R}/env/audio_src/ACE-Step-1.5-main"
ACE_CKPT = f"{R}/env/audio_models/acestep_checkpoints"
# 打分可以放在另一台机（config/bgm.json generation.score_host）：gpu36 上 CLAP / Demucs 权重在 /root/work/fredw/bgm 下
# （sha256 与 gpu33 的同一份一致，2026-11-01 核对）
CLAP_DIR = os.environ.get("BGM_CLAP_DIR") or (f"{R}/env/audio_models/laion/larger_clap_general" if ON_GPU33
                                              else "/root/work/fredw/bgm/models/larger_clap_general")
HB_DIR = Path("/root/work/fredw/gpu_heartbeats")
FAULTY = {2} if ON_GPU33 else set()
os.environ.setdefault("TORCH_HOME", f"{R}/env/audio_models/torch" if ON_GPU33 else "/root/work/fredw/bgm/torch")
os.environ.setdefault("HF_HUB_OFFLINE", "1")


def jload(p, default=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def jsave(p, d):
    p = Path(p)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


# ------------------------------------------------------------------ GPU 状态 / 让道
def gpu_state() -> dict[int, dict]:
    out = subprocess.run(["nvidia-smi", "--query-gpu=index,memory.used,memory.total,utilization.gpu",
                          "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=30).stdout
    st = {}
    for ln in out.strip().splitlines():
        i, used, tot, util = [x.strip() for x in ln.split(",")]
        st[int(i)] = {"used_mb": int(used), "free_mb": int(tot) - int(used), "util": int(util)}
    return st


def comfy_queue(port: int) -> int | None:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/queue", timeout=5) as r:
            d = json.loads(r.read().decode())
        return len(d.get("queue_running") or []) + len(d.get("queue_pending") or [])
    except Exception:  # noqa: BLE001
        return None   # ComfyUI 没起：只看利用率


def probe(gen: dict) -> dict:
    st = gpu_state()
    out = {}
    for g in gen["allowed_gpus"]:
        if g in FAULTY or g not in st:
            continue
        out[g] = {**st[g], "comfy_queue": comfy_queue(int(gen["comfy_ports"][str(g)]))}
    return out


def busy(gen: dict, g: int, st: dict | None = None) -> bool:
    st = st or gpu_state()
    q = comfy_queue(int(gen["comfy_ports"][str(g)]))
    return bool(q) or st[g]["util"] > int(gen["util_max"])


def my_lock_alive(gen: dict, g: int) -> bool:
    """本工具另一个作业正占着这张卡（gpu.lock.N 里的 pid 还活着）"""
    p = Path(gen["workdir"]) / f"gpu.lock.{g}"
    d = jload(p)
    if not d:
        return False
    try:
        os.kill(int(d["pid"]), 0)
        return int(d["pid"]) != os.getpid()
    except (OSError, KeyError, ValueError, TypeError):
        return False


def acquire_lock(gen: dict, g: int, job: dict) -> bool:
    """O_EXCL 建 gpu.lock.N（本工具多个作业不抢同一张卡）；残留锁（pid 已退出）先清掉"""
    p = Path(gen["workdir"]) / f"gpu.lock.{g}"
    for _ in range(2):
        try:
            fd = os.open(str(p), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w") as f:
                f.write(json.dumps({"job": job["id"], "pid": os.getpid(), "t": time.time()}))
            return True
        except FileExistsError:
            if my_lock_alive(gen, g):
                return False
            p.unlink(missing_ok=True)
    return False


def heartbeat(job: dict, label: str, *, gpu=None, step=None, steps=None, state="running"):
    HB_DIR.mkdir(parents=True, exist_ok=True)
    rec = {"agent": "BGM10", "label": label, "kind": "other", "server": HOST, "gpu": gpu, "step": step, "steps": steps,
           "episode": job.get("episode"), "state": state, "ttl": 180, "pid": os.getpid(), "updated": time.time()}
    p = HB_DIR / f"BGM10-{job['id']}.json"
    old = jload(p, {}) or {}
    rec["started"] = old.get("started") or time.time()
    jsave(p, rec)


def pick_device(job: dict, prog) -> tuple[str, int | None, dict]:
    gen = job["gen"]
    tiers = gen["tiers"]
    gpu_tiers = [t for t in tiers if t.get("device") != "cpu"]
    cpu_tier = next((t for t in tiers if t.get("device") == "cpu"), None)
    idle_since: dict[int, float | None] = {}
    t_end = time.time() + float(gen["wait_gpu_min"]) * 60
    force = job.get("force_device")
    if force == "cpu" and cpu_tier:
        return "cpu", None, cpu_tier
    while True:
        st = gpu_state()
        now = time.time()
        ready = []
        for g in gen["allowed_gpus"]:
            if g in FAULTY or g not in st:
                continue
            if busy(gen, g, st) or my_lock_alive(gen, g):
                idle_since[g] = None
            else:
                idle_since[g] = idle_since.get(g) or now
                if now - idle_since[g] >= float(gen["yield_s"]):
                    ready.append(g)
        for t in gpu_tiers:
            ok = sorted((g for g in ready if st[g]["free_mb"] >= int(t["need_mb"])), key=lambda g: -st[g]["free_mb"])
            for g in ok:
                if acquire_lock(gen, g, job):
                    return "cuda", g, t
        if now > t_end:
            if gen.get("cpu_fallback") and cpu_tier:
                return "cpu", None, cpu_tier
            raise RuntimeError("等不到空闲 GPU，且不允许 CPU 回退")
        prog({"state": "waiting_gpu", "gpus": {g: {**st[g], "idle_s": round(now - idle_since[g], 0) if idle_since.get(g) else 0}
                                                 for g in gen["allowed_gpus"] if g in st}})
        heartbeat(job, f"配乐 · 第{job.get('episode')}集 · 等空闲卡（让道）", state="waiting")
        time.sleep(15)


# ------------------------------------------------------------------ 生成
def generate(job: dict, jdir: Path, prog) -> dict:
    dev, g, tier = pick_device(job, prog)
    if dev == "cuda":
        os.environ["CUDA_VISIBLE_DEVICES"] = str(g)
    else:
        os.environ["CUDA_VISIBLE_DEVICES"] = ""
    import torch
    if dev == "cpu":
        torch.set_num_threads(int(job["gen"].get("cpu_threads", 24)))
    lock = Path(job["gen"]["workdir"]) / f"gpu.lock.{g if g is not None else 'cpu'}"
    lock.write_text(json.dumps({"job": job["id"], "pid": os.getpid(), "t": time.time()}))
    info = {"device": dev, "gpu": g, "tier": tier, "cands": {}, "yielded": []}
    try:
        sys.path.insert(0, ACE_SRC)
        os.environ["ACESTEP_CHECKPOINTS_DIR"] = ACE_CKPT
        # ACE-Step 默认单条 600 s 超时；CPU 回退在共享机高负载（且本作业已 nice）时会超时（ep04 11-01 实测 4/4 超时）
        os.environ.setdefault("ACESTEP_GENERATION_TIMEOUT", "3600" if dev == "cpu" else "1200")
        from acestep.handler import AceStepHandler
        from acestep.llm_inference import LLMHandler
        from acestep.inference import GenerationConfig, GenerationParams, generate_music
        t0 = time.time()
        # 选中的档位加载失败（显存 / 量化库）→ 同一张卡上退到下一个更小的档位，记录原因
        tiers = job["gen"]["tiers"]
        order = [tier] + [t for t in tiers[tiers.index(tier) + 1:] if (t.get("device") == "cpu") == (dev == "cpu")]
        dit, errs = None, []
        for t in order:
            heartbeat(job, f"配乐 · 第{job.get('episode')}集 · 加载 {t['model']}", gpu=g)
            try:
                dit = AceStepHandler()
                msg, ok = dit.initialize_service(project_root=ACE_SRC, config_path=t["model"], device=dev,
                                                 offload_to_cpu=bool(t.get("offload")), quantization=t.get("quant"),
                                                 prefer_source="huggingface")
                if ok:
                    tier = t
                    break
                errs.append(f"{t['model']}/{t.get('quant')}: {str(msg)[:300]}")
            except Exception as e:  # noqa: BLE001
                errs.append(f"{t['model']}/{t.get('quant')}: {type(e).__name__}: {str(e)[:300]}")
            dit = None
            gc.collect()
            if dev == "cuda":
                torch.cuda.empty_cache()
        info["tier_errors"] = errs
        info["tier"] = tier
        if dit is None:
            raise RuntimeError(f"ACE-Step DiT init failed: {errs}")
        llm = LLMHandler()
        lm_ok = False
        if tier.get("lm"):
            m2, ok2 = llm.initialize(checkpoint_dir=ACE_CKPT, lm_model_path="acestep-5Hz-lm-1.7B", backend="pt",
                                     device=dev, offload_to_cpu=bool(tier.get("offload")))
            lm_ok = bool(ok2)
            if not ok2:
                info["lm_error"] = str(m2)[:300]
        info["load_s"] = round(time.time() - t0, 1)
        info["lm"] = lm_ok
        cands = job["candidates"]
        for k, c in enumerate(cands):
            # 生成中只看 ComfyUI 队列（利用率是自己占的）：别人投了任务就停，剩下的候选让道
            if dev == "cuda" and k > 0 and comfy_queue(int(job["gen"]["comfy_ports"][str(g)])):
                info["yielded"] = [x["id"] for x in cands[k:]]
                prog({"state": "yielded", "at": c["id"]})
                break
            heartbeat(job, f"配乐 · 第{job.get('episode')}集 · ACE-Step 候选 {k + 1}/{len(cands)}", gpu=g, step=k + 1,
                      steps=len(cands))
            prog({"state": "generating", "cand": c["id"], "k": k + 1, "n": len(cands), "device": dev, "gpu": g,
                  "model": tier["model"]})
            wdir = jdir / "ace_tmp"
            wdir.mkdir(exist_ok=True)
            params = GenerationParams(
                caption=c["caption"], lyrics=c["lyrics"], instrumental=True, bpm=int(c["bpm"]) if c.get("bpm") else None,
                keyscale=c.get("keyscale") or "", timesignature=str(c.get("timesignature") or ""), duration=float(c["duration"]),
                inference_steps=int(tier["steps"]), guidance_scale=float(tier.get("cfg", 7.0)), seed=int(c["seed"]),
                thinking=lm_ok, use_cot_caption=False, use_cot_language=False, use_cot_metas=False,
                lm_negative_prompt=c.get("negative") or "NO USER INPUT", fade_out_duration=1.5)
            cfg = GenerationConfig(batch_size=1, use_random_seed=False, seeds=[int(c["seed"])], audio_format="wav")
            t1 = time.time()
            res = generate_music(dit, llm, params, cfg, save_dir=str(wdir))
            if not res.success or not res.audios:
                info["cands"][c["id"]] = {"error": str(res.error)[:500]}
                continue
            src = Path(res.audios[0]["path"])
            dst = jdir / f"{c['id']}.raw.wav"
            shutil.move(str(src), dst)
            info["cands"][c["id"]] = {"raw": dst.name, "gen_s": round(time.time() - t1, 1)}
        if dev == "cuda":
            info["vram_peak_mb"] = round(torch.cuda.max_memory_allocated() / 2**20)
        shutil.rmtree(jdir / "ace_tmp", ignore_errors=True)
        del dit, llm
    finally:
        gc.collect()
        try:
            import torch as _t
            if _t.cuda.is_available():
                _t.cuda.empty_cache()
        except Exception:  # noqa: BLE001
            pass
        lock.unlink(missing_ok=True)
    return info


# ------------------------------------------------------------------ 打分（CPU）
def _db(x):
    import numpy as np
    return 20 * np.log10(np.maximum(x, 1e-9))


def frame_rms(mono, sr, win_s):
    import numpy as np
    n = int(sr * win_s)
    k = len(mono) // n
    if k == 0:
        return np.zeros(0)
    return np.sqrt(np.mean(mono[: k * n].reshape(k, n) ** 2, axis=1))


_CLAP = None
_DEMUCS = None


def clap_model():
    global _CLAP
    if _CLAP is None:
        from transformers import ClapModel, ClapProcessor
        _CLAP = (ClapModel.from_pretrained(CLAP_DIR).eval(), ClapProcessor.from_pretrained(CLAP_DIR))
    return _CLAP


def clap_embed(mono48, texts):
    import torch
    model, proc = clap_model()
    with torch.no_grad():
        inp = proc(text=texts, audios=[mono48], sampling_rate=48000, return_tensors="pt", padding=True)
        out = model(**inp)
        a = out.audio_embeds / out.audio_embeds.norm(dim=-1, keepdim=True)
        t = out.text_embeds / out.text_embeds.norm(dim=-1, keepdim=True)
        sims = (a @ t.T)[0]
        logits = out.logits_per_audio[0]
    return sims.numpy(), logits.numpy()


def demucs_vocals(x48):
    """→ (vocals, mix) at 44.1 kHz stereo (htdemucs_ft, CPU)"""
    global _DEMUCS
    import numpy as np
    import torch
    from demucs.apply import apply_model
    from demucs.pretrained import get_model
    from scipy.signal import resample_poly
    if _DEMUCS is None:
        _DEMUCS = get_model("htdemucs_ft")
        _DEMUCS.eval()
    x = resample_poly(x48, 147, 160, axis=0).astype(np.float32)
    wav = torch.from_numpy(x.T.copy())[None]
    ref = wav.mean(1).mean()
    sd = wav.std() + 1e-8
    with torch.no_grad():
        src = apply_model(_DEMUCS, (wav - ref) / sd, device="cpu", split=True, overlap=0.25, progress=False)[0]
    src = src * sd + ref
    vi = _DEMUCS.sources.index("vocals")
    return src[vi].numpy().T, x


def score_one(path: Path, brief: dict, gates_dur: float) -> dict:
    import numpy as np
    import soundfile as sf
    import librosa
    import pyloudnorm as pyln
    from scipy.signal import resample_poly
    x, sr = sf.read(str(path), dtype="float32", always_2d=True)
    if x.shape[1] == 1:
        x = np.repeat(x, 2, axis=1)
    if sr != 48000:
        x = resample_poly(x, 48000, sr, axis=0).astype(np.float32)
        sr = 48000
    mono = x.mean(1)
    m = {"duration_s": round(len(x) / sr, 2)}
    meter = pyln.Meter(sr)
    lufs = float(meter.integrated_loudness(x))
    m["lufs_raw"] = round(lufs, 2)
    tp = float(np.max(np.abs(resample_poly(x, 4, 1, axis=0))))
    m["true_peak_raw"] = round(float(_db(tp)), 2)
    # 削波：ACE-Step 输出已按峰值归一到 −1 dBFS，所以不看“满刻度”，看“平顶”——贴着本条峰值（±0.1%）且连续 ≥3 个样本
    ax = np.abs(x).max(axis=1)
    pk = float(ax.max()) or 1.0
    hot = ax >= pk * 0.999
    runs = np.convolve(hot.astype(np.int8), np.ones(3, dtype=np.int8), mode="same") >= 3
    m["clip_ratio"] = float(np.mean(runs))
    fr = _db(frame_rms(mono, sr, 0.05))
    thr = lufs - 30
    sil = fr < thr
    a, b = int(1.0 / 0.05), len(sil) - int(3.0 / 0.05)
    run = best = 0
    for v in sil[a:max(a, b)]:
        run = run + 1 if v else 0
        best = max(best, run)
    m["longest_gap_s"] = round(best * 0.05, 2)
    y22 = librosa.resample(mono, orig_sr=sr, target_sr=22050)
    tempo, _ = librosa.beat.beat_track(y=y22, sr=22050)
    tempo = float(np.atleast_1d(tempo)[0])
    m["tempo_bpm"] = round(tempo, 1)
    lo, hi = float(brief["bpm"]["min"]), float(brief["bpm"]["max"])
    tol = float(brief.get("_tempo_tol", 0.08))
    m["tempo_ok"] = any(lo * (1 - tol) <= tempo * f <= hi * (1 + tol) for f in (1.0, 0.5, 2.0))
    # 能量曲线：1 s 窗 RMS dB，3 s 平滑，对 brief 曲线插值后求相关（只比 brief 的时长范围）
    dur = float(brief["duration_s"])
    e = _db(frame_rms(mono, sr, 1.0))[: int(dur)]
    if len(e) >= 4:
        e = np.convolve(e, np.ones(3) / 3, mode="same")
        pts = np.array(brief["energy_curve"], dtype=float)
        tgt = np.interp(np.arange(len(e)) + 0.5, pts[:, 0], pts[:, 1])
        r = float(np.corrcoef(e, tgt)[0, 1]) if np.std(e) > 1e-6 and np.std(tgt) > 1e-6 else 0.0
        m["energy_r"] = round(r if math.isfinite(r) else 0.0, 3)
        m["energy_db_p10_p95"] = [round(float(np.percentile(e, 10)), 1), round(float(np.percentile(e, 95)), 1)]
    else:
        m["energy_r"] = 0.0
    if brief.get("loopable"):
        n = int(0.5 * sr)
        m["loop_seam_db"] = round(float(abs(_db(np.sqrt(np.mean(mono[-n:] ** 2))) - _db(np.sqrt(np.mean(mono[:n] ** 2))))), 2)
    m["spectral_centroid_hz"] = round(float(np.mean(librosa.feature.spectral_centroid(y=y22, sr=22050))), 0)
    m["onset_rate"] = round(float(len(librosa.onset.onset_detect(y=y22, sr=22050)) / max(1.0, len(y22) / 22050)), 2)
    # CLAP：与 brief.clap_text 的相似度 + 零样本标签 + 人声概率
    tags = list(dict.fromkeys([*brief.get("instrumentation", []), "piano", "strings", "synth pad", "drums", "bass",
                               "electric guitar", "choir", "ambient", "orchestral", "electronic beat"]))
    texts = [brief["clap_text"], "instrumental music without vocals", "music with a person singing",
             *[f"the sound of {t}" for t in tags]]
    sims, logits = clap_embed(librosa.resample(mono, orig_sr=sr, target_sr=48000) if sr != 48000 else mono, texts)
    m["clap"] = round(float(sims[0]), 4)
    lv = logits[1:3]
    pv = np.exp(lv - lv.max())
    m["p_vocal"] = round(float(pv[1] / pv.sum()), 3)
    tag_s = sorted(zip(tags, sims[3:]), key=lambda z: -z[1])
    m["tags"] = {t: round(float(s), 3) for t, s in tag_s[:6]}
    voc, mix44 = demucs_vocals(x)
    vr = float(_db(np.sqrt(np.mean(voc ** 2))) - _db(np.sqrt(np.mean(mix44 ** 2))))
    m["vocal_rel_db"] = round(vr, 1)
    vf = _db(frame_rms(voc.mean(1), 44100, 1.0))
    mf = _db(frame_rms(mix44.mean(1), 44100, 1.0))
    m["vocal_active_frac"] = round(float(np.mean(vf > mf - 12)) if len(vf) else 0.0, 3)
    return m


def normalise(path: Path, out_flac: Path, lufs_target: float, tp_target: float) -> dict:
    """整体增益到 lufs_target；真峰超过 tp_target 时整体再降（不压缩、不限幅）。记录最终值。"""
    import numpy as np
    import soundfile as sf
    import pyloudnorm as pyln
    from scipy.signal import resample_poly
    x, sr = sf.read(str(path), dtype="float32", always_2d=True)
    if x.shape[1] == 1:
        x = np.repeat(x, 2, axis=1)
    if sr != 48000:
        x = resample_poly(x, 48000, sr, axis=0).astype(np.float32)
        sr = 48000
    meter = pyln.Meter(sr)
    l0 = float(meter.integrated_loudness(x))
    g = 10 ** ((lufs_target - l0) / 20)
    y = x * g
    tp = float(_db(np.max(np.abs(resample_poly(y, 4, 1, axis=0)))))
    if tp > tp_target:
        y = y * 10 ** ((tp_target - tp) / 20)
    l1 = float(meter.integrated_loudness(y))
    tp1 = float(_db(np.max(np.abs(resample_poly(y, 4, 1, axis=0)))))
    sf.write(str(out_flac), y, sr, subtype="PCM_24")
    return {"lufs": round(l1, 2), "true_peak_db": round(tp1, 2), "gain_db": round(float(_db(g)), 2),
            "tp_limited": tp > tp_target}


def score_job(job: dict, jdir: Path, prog) -> dict:
    import torch
    torch.set_num_threads(int(job["gen"].get("cpu_threads", 24)))
    brief = dict(job["brief"])
    brief["_tempo_tol"] = job.get("tempo_tol", 0.08)
    out = {}
    for k, c in enumerate(job["candidates"]):
        raw = jdir / f"{c['id']}.raw.wav"
        if not raw.is_file():
            continue
        prog({"state": "scoring", "cand": c["id"], "k": k + 1, "n": len(job["candidates"])})
        heartbeat(job, f"配乐 · 第{job.get('episode')}集 · 打分 {k + 1}/{len(job['candidates'])}（CPU）")
        try:
            m = score_one(raw, brief, float(job["brief"]["duration_s"]))
            m["normalised"] = normalise(raw, jdir / f"{c['id']}.flac", float(job["out"]["lufs"]),
                                        float(job["out"]["true_peak_db"]))
            out[c["id"]] = m
        except Exception as e:  # noqa: BLE001
            out[c["id"]] = {"error": f"{type(e).__name__}: {e}"[:500]}
    return out


def cmd_run(job_path: Path, only_score: bool = False) -> int:
    try:
        os.nice(15)   # CPU 让道：出图 / 视频的打分与合成优先（gpu33 共享机，负载高时不抢）
    except OSError:
        pass
    job = jload(job_path)
    jdir = job_path.parent
    prog_p = jdir / "progress.json"

    def prog(d):
        jsave(prog_p, {**d, "t": time.time()})

    t0 = time.time()
    res = {"id": job["id"], "episode": job.get("episode"), "started": t0}
    try:
        if not only_score:
            res["gen"] = generate(job, jdir, prog)
            jsave(jdir / "gen.json", res["gen"])   # 打分前先落盘：打分中断时，笔记本端仍知道用的是哪个模型 / 设备
        elif (jdir / "gen.json").is_file():
            res["gen"] = jload(jdir / "gen.json")
        res["metrics"] = score_job(job, jdir, prog) if job.get("score", True) or only_score else {}
        res["ok"] = True
    except Exception as e:  # noqa: BLE001
        res["ok"] = False
        res["error"] = f"{type(e).__name__}: {e}"
        res["trace"] = traceback.format_exc()[-3000:]
    res["seconds"] = round(time.time() - t0, 1)
    jsave(jdir / "result.json", res)
    prog({"state": "done" if res["ok"] else "failed"})
    try:
        (HB_DIR / f"BGM10-{job['id']}.json").unlink()
    except OSError:
        pass
    return 0 if res["ok"] else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("run", "score", "probe"))
    ap.add_argument("--job")
    ap.add_argument("--cfg")
    a = ap.parse_args()
    if a.cmd == "probe":
        gen = jload(a.cfg)["generation"] if a.cfg else {"allowed_gpus": [0, 1, 3], "comfy_ports": {"0": 8188, "1": 8189, "3": 8191}}
        print(json.dumps(probe(gen)))
        return 0
    return cmd_run(Path(a.job), only_score=(a.cmd == "score"))


if __name__ == "__main__":
    raise SystemExit(main())
