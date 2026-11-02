"""STYLE-V2 整季主题候选 · 远端生成（config/bgm.json generation.host / workdir，与 tools/bgm/remote/bgm_worker.py 同目录同 venv）。

和生产 worker 的区别只有一处：候选可以带 cover_of（同一作业里另一条候选的 id）→ ACE-Step task_type="cover"，
以那条的 raw.wav 为 src_audio、换 caption 重编配（保留旋律走向 / 结构 / 速度），用来做"同一动机的幻想编配 vs 现实编配"。
选卡让道（allowed_gpus / ComfyUI 队列 / util_max / yield_s）、显存档位回退、打分全部复用 bgm_worker 的函数，不改生产代码。

    venv/bin/python v2style_bgm_worker.py run --job jobs/<id>/job.json     只生成（打分另投到 score_host 用 bgm_worker.py score）
"""
from __future__ import annotations

import argparse
import gc
import json
import os
import shutil
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bgm_worker as W  # noqa: E402

HB_DIR = W.HB_DIR


def heartbeat(job, label, *, gpu=None, step=None, steps=None, state="running"):
    HB_DIR.mkdir(parents=True, exist_ok=True)
    p = HB_DIR / f"STYLEV2-{job['id']}.json"
    old = W.jload(p, {}) or {}
    W.jsave(p, {"agent": "STYLE-V2-music", "label": label, "kind": "other", "server": W.HOST, "gpu": gpu, "step": step,
                "steps": steps, "state": state, "ttl": 180, "pid": os.getpid(), "updated": time.time(),
                "started": old.get("started") or time.time()})


def generate(job: dict, jdir: Path, prog) -> dict:
    W.heartbeat = lambda j, label, **kw: heartbeat(j, label, **kw)   # pick_device 里的等卡心跳也用本作业的名字
    dev, g, tier = W.pick_device(job, prog)
    os.environ["CUDA_VISIBLE_DEVICES"] = str(g) if dev == "cuda" else ""
    import torch
    if dev == "cpu":
        torch.set_num_threads(int(job["gen"].get("cpu_threads", 16)))
    lock = Path(job["gen"]["workdir"]) / f"gpu.lock.{g if g is not None else 'cpu'}"
    W.jsave(lock, {"job": job["id"], "pid": os.getpid(), "t": time.time()})   # 原子写（.tmp + os.replace）
    info = {"device": dev, "gpu": g, "tier": tier, "cands": {}, "yielded": []}
    try:
        sys.path.insert(0, W.ACE_SRC)
        os.environ["ACESTEP_CHECKPOINTS_DIR"] = W.ACE_CKPT
        os.environ.setdefault("ACESTEP_GENERATION_TIMEOUT", "3600" if dev == "cpu" else "1200")
        from acestep.handler import AceStepHandler
        from acestep.llm_inference import LLMHandler
        from acestep.inference import GenerationConfig, GenerationParams, generate_music
        t0 = time.time()
        tiers = job["gen"]["tiers"]
        order = [tier] + [t for t in tiers[tiers.index(tier) + 1:] if (t.get("device") == "cpu") == (dev == "cpu")]
        dit, errs = None, []
        for t in order:
            heartbeat(job, f"STYLE-V2 主题配乐 · 加载 {t['model']}", gpu=g)
            try:
                dit = AceStepHandler()
                msg, ok = dit.initialize_service(project_root=W.ACE_SRC, config_path=t["model"], device=dev,
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
        info["tier_errors"], info["tier"] = errs, tier
        if dit is None:
            raise RuntimeError(f"ACE-Step DiT init failed: {errs}")
        llm = LLMHandler()
        lm_ok = False
        if tier.get("lm"):
            m2, ok2 = llm.initialize(checkpoint_dir=W.ACE_CKPT, lm_model_path="acestep-5Hz-lm-1.7B", backend="pt",
                                     device=dev, offload_to_cpu=bool(tier.get("offload")))
            lm_ok = bool(ok2)
            if not ok2:
                info["lm_error"] = str(m2)[:300]
        info["load_s"], info["lm"] = round(time.time() - t0, 1), lm_ok
        cands = job["candidates"]
        for k, c in enumerate(cands):
            if dev == "cuda" and k > 0 and W.comfy_queue(int(job["gen"]["comfy_ports"][str(g)])):
                info["yielded"] = [x["id"] for x in cands[k:]]
                prog({"state": "yielded", "at": c["id"]})
                break
            heartbeat(job, f"STYLE-V2 主题配乐 · 候选 {k + 1}/{len(cands)}", gpu=g, step=k + 1, steps=len(cands))
            prog({"state": "generating", "cand": c["id"], "k": k + 1, "n": len(cands), "device": dev, "gpu": g,
                  "model": tier["model"]})
            wdir = jdir / "ace_tmp"
            wdir.mkdir(exist_ok=True)
            kw = {}
            if c.get("cover_of"):
                src = jdir / f"{c['cover_of']}.raw.wav"
                if not src.is_file():
                    info["cands"][c["id"]] = {"error": f"cover 源 {src.name} 不存在"}
                    continue
                kw = {"task_type": "cover", "src_audio": str(src), "audio_cover_strength": float(c.get("cover_strength", 0.5))}
            params = GenerationParams(
                caption=c["caption"], lyrics=c["lyrics"], instrumental=True, bpm=int(c["bpm"]) if c.get("bpm") else None,
                keyscale=c.get("keyscale") or "", timesignature=str(c.get("timesignature") or ""), duration=float(c["duration"]),
                inference_steps=int(tier["steps"]), guidance_scale=float(tier.get("cfg", 7.0)), seed=int(c["seed"]),
                thinking=lm_ok and not c.get("cover_of"), use_cot_caption=False, use_cot_language=False, use_cot_metas=False,
                lm_negative_prompt=c.get("negative") or "NO USER INPUT", fade_out_duration=1.5, **kw)
            cfg = GenerationConfig(batch_size=1, use_random_seed=False, seeds=[int(c["seed"])], audio_format="wav")
            t1 = time.time()
            try:
                res = generate_music(dit, llm, params, cfg, save_dir=str(wdir))
            except Exception as e:  # noqa: BLE001
                info["cands"][c["id"]] = {"error": f"{type(e).__name__}: {e}"[:500]}
                continue
            if not res.success or not res.audios:
                info["cands"][c["id"]] = {"error": str(res.error)[:500]}
                continue
            dst = jdir / f"{c['id']}.raw.wav"
            shutil.move(str(Path(res.audios[0]["path"])), dst)
            info["cands"][c["id"]] = {"raw": dst.name, "gen_s": round(time.time() - t1, 1), "task": kw.get("task_type", "text2music")}
        if dev == "cuda":
            info["vram_peak_mb"] = round(torch.cuda.max_memory_allocated() / 2**20)
        shutil.rmtree(jdir / "ace_tmp", ignore_errors=True)
        del dit, llm
    finally:
        gc.collect()
        try:
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:  # noqa: BLE001
            pass
        lock.unlink(missing_ok=True)
    return info


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("run",))
    ap.add_argument("--job", required=True)
    a = ap.parse_args()
    try:
        os.nice(15)
    except OSError:
        pass
    jp = Path(a.job)
    job, jdir = W.jload(jp), jp.parent
    prog_p = jdir / "progress.json"

    def prog(d):
        W.jsave(prog_p, {**d, "t": time.time()})

    t0 = time.time()
    res = {"id": job["id"], "started": t0}
    try:
        res["gen"] = generate(job, jdir, prog)
        W.jsave(jdir / "gen.json", res["gen"])
        res["metrics"], res["ok"] = {}, True
    except Exception as e:  # noqa: BLE001
        res.update(ok=False, error=f"{type(e).__name__}: {e}", trace=traceback.format_exc()[-3000:])
    res["seconds"] = round(time.time() - t0, 1)
    W.jsave(jdir / "result.json", res)
    prog({"state": "done" if res["ok"] else "failed"})
    try:
        (HB_DIR / f"STYLEV2-{job['id']}.json").unlink()
    except OSError:
        pass
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
