"""P2 H3 实验 X1（Turbo 版本）/ X3（Turbo 强度）/ X4（身份通道）：ep02-S2（6 s，158 帧），锁定首尾帧、同一种子。
直交 ComfyUI，不建 take。多进程安全：每个变体用 data/ab/<exp>/<id>.claim 认领。
用法：python tools/ab/xp_h3.py run <lane keys，逗号分隔，如 1,3>   |  python tools/ab/xp_h3.py list"""
import json
import os
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import xp_common as X  # noqa: E402
from ns_render import h3_video as HV            # noqa: E402
from ns_render import pipeline as P              # noqa: E402
from ns_render import workflows as W             # noqa: E402
from ns_render.comfy_client import ComfyClient   # noqa: E402

SHOT = "ep02-S2"
SEED = 20261030            # ep02-S2 video_001 的种子
SECONDS = 6.0
CARD = X.ROOT / "assets" / "characters" / "lin_wan" / "plates" / "id_front_v2.png"   # 林晚正脸身份底板 v2（角色卡）

FL2VA = W.H3_DIT_INT8
REF2VA = "minimax_h3_ref2va_pruned_int8_convrot.safetensors"
T11 = "minimax_h3_fl2v_turbo_8step_v1.1_768p_comfyui_bf16.safetensors"
T10 = "minimax_h3_fl2v_turbo_8step_v1.0_768p_comfyui_bf16.safetensors"
T12 = "minimax_h3_fl2v_turbo_4step_v1.2_768p_comfyui_bf16.safetensors"
T13 = "minimax_h3_fl2v_turbo_4step_v1.3_768p_comfyui_bf16.safetensors"
DMAD = "minimax_h3_DMAD_4step_full_lora_avg_rank_39_bf16.safetensors"
R2V11 = "minimax_h3_ref2v_turbo_8step_v1.1_768p_comfyui_bf16.safetensors"

# id, 实验目录, 说明, unet, loras, steps, shift, 条件方式
JOBS = [
    ("A_fl2v_t8_v1.1_s1.0_8st", "X1_turbo_versions", "现状：FL2V Turbo 8step v1.1 768p @1.0 · 8 步 · shift 6/3", FL2VA, [(T11, 1.0)], 8, (6.0, 3.0), "fl2va"),
    ("B_fl2v_t8_v1.0_s1.0_8st", "X1_turbo_versions", "FL2V Turbo 8step v1.0 768p @1.0 · 8 步 · shift 6/3", FL2VA, [(T10, 1.0)], 8, (6.0, 3.0), "fl2va"),
    ("C_fl2v_t4_v1.2_s1.0_4st", "X1_turbo_versions", "FL2V Turbo 4step v1.2 768p @1.0 · 4 步 · shift 6/3", FL2VA, [(T12, 1.0)], 4, (6.0, 3.0), "fl2va"),
    ("D_fl2v_t4_v1.2_s0.5_8st", "X1_turbo_versions", "FL2V Turbo 4step v1.2 768p @0.5 · 8 步 · shift 6/3", FL2VA, [(T12, 0.5)], 8, (6.0, 3.0), "fl2va"),
    ("E_fl2v_t4_v1.3_s1.0_4st", "X1_turbo_versions", "FL2V Turbo 4step v1.3 768p @1.0 · 4 步 · shift 6/3", FL2VA, [(T13, 1.0)], 4, (6.0, 3.0), "fl2va"),
    ("F_dmad_4step_s1.0_4st", "X1_turbo_versions", "DMAD 4step（avg rank 39）@1.0 · 4 步 · shift 12/3（文件名无 768p，按仓库配对规则）", FL2VA, [(DMAD, 1.0)], 4, (12.0, 3.0), "fl2va"),
    ("G_base_noLoRA_20st", "X1_turbo_versions", "基模无 LoRA · 20 步 · shift 12/3 · cfg1（仓库 H3_BASE 档）", FL2VA, [], 20, (12.0, 3.0), "fl2va"),
    ("S0.80_fl2v_t8_v1.1_8st", "X3_turbo_strength", "FL2V Turbo 8step v1.1 @0.8 · 8 步 · shift 6/3（1.0 见 X1 A）", FL2VA, [(T11, 0.8)], 8, (6.0, 3.0), "fl2va"),
    ("S0.65_fl2v_t8_v1.1_8st", "X3_turbo_strength", "FL2V Turbo 8step v1.1 @0.65 · 8 步 · shift 6/3", FL2VA, [(T11, 0.65)], 8, (6.0, 3.0), "fl2va"),
    ("F1_ref2va_r2vT8_v1.1_8st", "X4_identity", "Ref2VA int8 + Ref2V Turbo 8step v1.1 @1.0 · ReferenceToVideo(<Picture 1>=首帧, <Picture 2>=林晚角色卡) + AddGuide(首帧,0) + AddGuide(尾帧,-1) · 8 步 · shift 6/3", REF2VA, [(R2V11, 1.0)], 8, (6.0, 3.0), "ref_first_card"),
    ("A19_fl2va_r2vT8_v1.1_8st", "X4_identity", "FL2VA int8 + Ref2V Turbo 8step v1.1 @1.0（代替 FL2V Turbo）· 首尾帧 ImageToVideo · 8 步 · shift 6/3", FL2VA, [(R2V11, 1.0)], 8, (6.0, 3.0), "fl2va"),
    ("F3_fl2va_t8_v1.1_refcard_8st", "X4_identity", "FL2VA int8 + FL2V Turbo 8step v1.1 @1.0 · ReferenceToVideo(<Picture 1>=首帧, <Picture 2>=林晚角色卡) + AddGuide 首/尾帧 · 8 步 · shift 6/3", FL2VA, [(T11, 1.0)], 8, (6.0, 3.0), "ref_first_card"),
    ("F2_ref2va_noLoRA_20st", "X4_identity", "Ref2VA int8 无 LoRA · 20 步 · shift 12/3 · 同 F1 的参考/引导接法", REF2VA, [], 20, (12.0, 3.0), "ref_first_card"),
]


def graph(unet, loras, steps, shift, mode, prompt, first, last, card, frames, seed, prefix):
    m = W.H3Model()
    wf = {
        "127": {"class_type": "UNETLoader", "inputs": {"unet_name": unet, "weight_dtype": "default"}},
        "128": {"class_type": "CLIPLoader", "inputs": {"clip_name": m.clip, "type": "minimax", "device": "default"}},
        "119": {"class_type": "VAELoader", "inputs": {"vae_name": m.video_vae}},
        "120": {"class_type": "VAELoader", "inputs": {"vae_name": m.audio_vae}},
        "200": {"class_type": "LoadImage", "inputs": {"image": first}},
        "201": {"class_type": "LoadImage", "inputs": {"image": last}},
    }
    w, h = P.VIDEO_SIZE
    for lid, sid in (("200", "202"), ("201", "203")):
        wf[sid] = {"class_type": "ImageScale", "inputs": {"image": [lid, 0], "upscale_method": "lanczos",
                                                          "width": w, "height": h, "crop": "center"}}
    model = W._lora_chain(wf, ["127", 0], loras, 140)
    wf["150"] = {"class_type": "MiniMaxH3SigmaShift",
                 "inputs": {"model": model, "shift_video": float(shift[0]), "shift_audio": float(shift[1])}}
    model = ["150", 0]
    if mode == "fl2va":
        wf["131"] = {"class_type": "MiniMaxH3ImageToVideo",
                     "inputs": {"clip": ["128", 0], "prompt": prompt, "width": w, "height": h, "length": frames,
                                "vae": ["119", 0], "first_frame": ["202", 0], "last_frame": ["203", 0]}}
        cond, latent = ["131", 0], ["131", 1]
    else:
        # 01_h3_face_identity §3.3 的坑：接了参考图，首尾帧就不进文本编码器 → 首帧同时接 ref 槽 1 和 AddGuide(0)
        wf["204"] = {"class_type": "LoadImage", "inputs": {"image": card}}
        wf["131"] = {"class_type": "MiniMaxH3ReferenceToVideo",
                     "inputs": {"clip": ["128", 0], "prompt": prompt, "width": w, "height": h, "length": frames,
                                "ref_image_size": "match", "vae": ["119", 0], "audio_vae": ["120", 0],
                                "ref_images.ref_image_0": ["202", 0], "ref_images.ref_image_1": ["204", 0]}}
        wf["132"] = {"class_type": "MiniMaxH3AddGuide",
                     "inputs": {"positive": ["131", 0], "latent": ["131", 1], "frame_idx": 0, "vae": ["119", 0],
                                "image": ["202", 0]}}
        wf["133"] = {"class_type": "MiniMaxH3AddGuide",
                     "inputs": {"positive": ["132", 0], "latent": ["131", 1], "frame_idx": -1, "vae": ["119", 0],
                                "image": ["203", 0]}}
        cond, latent = ["133", 0], ["131", 1]
    wf.update({
        "126": {"class_type": "BasicGuider", "inputs": {"model": model, "conditioning": cond}},
        "129": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "123": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": m.sampler}},
        "124": {"class_type": "BasicScheduler", "inputs": {"model": model, "scheduler": m.scheduler, "steps": steps,
                                                            "denoise": 1.0}},
        "125": {"class_type": "SamplerCustomAdvanced",
                "inputs": {"noise": ["129", 0], "guider": ["126", 0], "sampler": ["123", 0], "sigmas": ["124", 0],
                           "latent_image": latent}},
        "122": {"class_type": "VAEDecode", "inputs": {"samples": ["125", 0], "vae": ["119", 0]}},
        "121": {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["125", 0], "vae": ["120", 0]}},
        "130": {"class_type": "CreateVideo", "inputs": {"images": ["122", 0], "audio": ["121", 0], "fps": m.fps}},
        "92": {"class_type": "SaveVideo", "inputs": {"video": ["130", 0], "filename_prefix": prefix,
                                                     "format": "mp4", "codec": "auto"}},
    })
    return wf


_ctx = {}
_ctx_lock = threading.Lock()


def context():
    with _ctx_lock:
        if not _ctx:
            d = X.get_json(f"{X.API}/api/shots/{SHOT}", 180)
            c = d["compiled"]
            prompt, src = c["video_prompt"], c.get("h3_prompt_source")
            ov = ((d.get("edit") or {}).get("h3_prompt_override") or {})
            if ov.get("text"):
                src += "（注意：存在项目方覆盖，未使用；与生产一致性需核对）"
            frames, want = HV.frames_for(SECONDS)
            fr = HV.locked_frames(SHOT)
            _ctx.update(prompt=HV.realign(prompt, frames), prompt_source=src, frames=frames, frames_in=fr)
        return _ctx


def claim(path: Path) -> bool:
    try:
        os.close(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
        return True
    except FileExistsError:
        return False


def run_job(job, key, url):
    jid, exp, label, unet, loras, steps, shift, mode = job
    out = X.AB / exp
    cx = context()
    cl = ComfyClient(url, timeout=120)
    first = HV.upload_once(cl, P.DATA / cx["frames_in"]["first"]["file"])
    last = HV.upload_once(cl, P.DATA / cx["frames_in"]["last"]["file"])
    card = cl.input_image(CARD, "ns_final/refs", size=None) if mode != "fl2va" else None
    wf = graph(unet, loras, steps, shift, mode, cx["prompt"], first, last, card, cx["frames"], SEED,
               f"ns_ab/{exp}_{jid}")
    miss = cl.check(wf)
    if miss:
        return {"skipped": "；".join(miss)}
    t0 = time.time()
    with HV.VramSampler(cl) as vram:
        entry, secs = cl.run(wf, timeout_s=7200)
    item = next(f for f in cl.output_files(entry) if f["filename"].endswith(".mp4"))
    dst = cl.download(item, out / f"{jid}.mp4")
    t1 = time.time()
    rec = {"id": jid, "label": label, "file": dst.name, "lane": f"gpu33 GPU{key}" if key in X.GPU33 else url,
           "exec_s": X.exec_seconds(entry), "wall_s": round(t1 - t0, 1), "vram_peak_gb": vram.peak,
           "params": {"unet": unet, "loras": [list(x) for x in loras], "steps": steps, "shift": list(shift),
                      "mode": mode, "sampler": "euler", "scheduler": "simple", "cfg": 1.0, "seed": SEED,
                      "frames": cx["frames"], "fps": 24, "size": list(P.VIDEO_SIZE),
                      "clip": W.H3Model().clip, "video_vae": W.H3Model().video_vae, "audio_vae": W.H3Model().audio_vae,
                      "first": cx["frames_in"]["first"], "last": cx["frames_in"]["last"],
                      "card": str(CARD.relative_to(X.ROOT)) if mode != "fl2va" else None,
                      "prompt_source": cx["prompt_source"]}}
    X.log(f"{exp} {jid}", rec["lane"], t0, t1, [dst], f"exec {rec['exec_s']} s, VRAM 峰值 {vram.peak} GB")
    return rec


def save(rec, exp):
    out = X.AB / exp
    f = out / "results.json"
    with _ctx_lock:
        d = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
        d[rec["id"]] = rec
        f.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


def worker(key, url, gpu36_sem):
    while True:
        job = None
        for j in JOBS:
            out = X.AB / j[1]
            out.mkdir(parents=True, exist_ok=True)
            if (out / f"{j[0]}.claim").exists():
                continue
            job = j
            break
        if job is None:
            return
        while not X.lane_free(key, url):
            time.sleep(30)
        if not claim(X.AB / job[1] / f"{job[0]}.claim"):
            continue
        sem = gpu36_sem if X.is_gpu36(key, url) else None
        if sem:
            sem.acquire()
        try:
            rec = run_job(job, key, url)
        except Exception as e:  # noqa: BLE001
            rec = {"error": str(e)[:1500]}
            X.log(f"{job[1]} {job[0]}", key, time.time(), time.time(), [], f"失败：{str(e)[:200]}")
        finally:
            if sem:
                sem.release()
        rec.update(id=job[0], label=job[2])
        save(rec, job[1])
        print(key, job[0], rec.get("exec_s"), rec.get("error") or rec.get("skipped") or "", flush=True)


def main():
    keys = sys.argv[2].split(",")
    lanes = X.lanes()
    sem = threading.Semaphore(2)
    ts = [threading.Thread(target=worker, args=(k, lanes[k], sem)) for k in keys if k in lanes]
    for t in ts:
        t.start()
    for t in ts:
        t.join()


if __name__ == "__main__":
    if sys.argv[1] == "list":
        for j in JOBS:
            print(j[0], j[1], j[2])
    else:
        main()
