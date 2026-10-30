# 4K final stage (2160×3840, 9:16): research, method, stage, commands

> 2026-10-30, Claude (gpu3 side). This is the **last** post-production step. It runs only on an episode that has already passed QA.
>
> - Code: `gpu33:/root/claude-kimi-ns-studio-v1/ns-studio/scripts/upscale_4k.py`
> - **Division of work:** this stage delivers **per-shot 4K clips plus a manifest**. The official 4K episode final (assembly + audio mix) is fredw-d9's **T38** on the laptop. The episode assembly built here is a QC preview only.
>
> Earlier research is not repeated here; see:
> - `script play lib/research v5 四个难点的技术方案.md` §4: MMH3 Ultimate Upscale / Open-H3-Regenerate-2K / SeedVR2 (batch ≥5, BlockSwap); grain after SR.
> - `research v8 写实与去AI味参数.md` §4: SeedVR2 3B; grain σ≈2 only at the final stage; chromatic aberration ≤0.5 px.
> - `docs/REQUIREMENTS.md` A2: Leica-like sharpness.
>
> This page fills the gaps: 4K specifics, FlashVSR/STAR, 3090 numbers, the stage, and the test status.

## 1. Options at 2160×3840 on one RTX 3090 (24 GB, Ampere sm_86)

Input: H3 FL2VA clips, 768×1344 (legacy 576×1024), 24 fps, 243 frames per 10 s shot.
"est." marks an estimate: no public 3090 timing exists at 4K for any diffusion VSR. Our own measurement is pending (§5).

| Method | Faces / skin | Temporal stability | 3090 at 4K, 10 s shot | Ampere | Node / CLI | Weights |
|---|---|---|---|---|---|---|
| **SeedVR2 3B** (ByteDance-Seed, one-step diffusion VSR) [repo](https://github.com/ByteDance-Seed/SeedVR) | Restores pores and hair without redrawing the face (one step, conditioned on the input). Slight over-sharpening. The 7B "plastic look" was fixed in v2.5.6. | Good inside a temporal batch (4n+1 frames). Batch seams if batch < 5 or overlap = 0. | est. **30–60 min** direct; est. 12–25 min at 1440 + Lanczos | fp16/bf16 native. fp8 is stored only and upcast (no speed gain). GGUF is dequantised (slowest). | [numz/ComfyUI-SeedVR2_VideoUpscaler](https://github.com/numz/ComfyUI-SeedVR2_VideoUpscaler) v2.5.24, incl. `inference_cli.py` | `numz/SeedVR2_comfyUI`: 3B fp16 6.78 GB + VAE 0.50 GB |
| SeedVR2 7B / 7B-sharp | More detail, more invented texture. Plain 7B fp8 has quality problems (use `mixed_block35`). | Same as 3B | est. 2–3× the 3B time with `blocks_to_swap` 16–24 | as above | same | 16.5 GB fp16 / 8.2–8.5 GB fp8 |
| FlashVSR v1.1 (Wan2.1-1.3B, one-step streaming) [repo](https://github.com/OpenImagingLab/FlashVSR) | Softer faces; more hallucinated fine texture | Good (causal streaming) | est. 5–10 min tiled. A 4090 does 85 frames at 3840×2048 in ≈61 s with 5 strips ([forum](https://forum.comfy.org/t/i-built-a-flashvsr-node-for-comfyui-4k-video-upscaling-that-auto-tiles-to-your-vram-16-gb-cards-included/4609)). | Block-Sparse-Attn tested on A100. [lihaoyun6/ComfyUI-FlashVSR_Ultra_Fast](https://github.com/lihaoyun6/ComfyUI-FlashVSR_Ultra_Fast) needs no build. | lihaoyun6 / smthemex | `JunhaoZhuang/FlashVSR-v1.1` |
| STAR (NJU, I2VGen-XL / CogVideoX-5B) [repo](https://github.com/NJU-PCALab/STAR) | Good on real footage | Good | Does not fit: 72 frames at 426×240 ×4 already ≈39 GB | – | community | `SherryX/STAR` |
| Upscale-A-Video (CVPR 24) [repo](https://github.com/sczhou/Upscale-A-Video) | Prompt-guided SD×4; faces drift | Medium | hours | yes | – | superseded |
| VEnhancer [repo](https://github.com/Vchitect/VEnhancer) | Regenerates content, so identity risk | Good | Very heavy above 1080p | yes | – | – |
| RealBasicVSR / BasicVSR++ [repo](https://github.com/ckkelvinchan/RealBasicVSR) | Oil-paint GAN texture on clean AI footage | Good | minutes | yes | – | small |
| Frame-wise ESRGAN / 4x-UltraSharp / Nomos | Sharp per frame | **Flickers** on hair, pores, gloss, metal and acrylic at 4× | est. 1–2 min | yes | core ComfyUI | 60 MB |
| **H3-native: Open-H3-Regenerate** (Kijai refiner r384 + LightX2V FL2V turbo v1.2 + LMS sharp + curve branches + LBH latent upscaler; all on gpu3) [pack](https://github.com/rdh9616/ComfyUI-Open-H3-Regenerate) | Best "new texture", but at σ 0.909 it **redraws**: fox → wolf in the pack's own test. 0.8 is closer. | Native video model | Reference: 5 s → 2K in 122 s + 24 s on a 72 GB Blackwell. 2K VAE decode alone peaks at 21 GB for 5 s and 45 GB for 15 s. 4K = two LBH passes and about 4× tokens. est. 3090 to 2K: 15–25 min per 10 s with offload; to 4K: not practical. | int8 base OK | staged | on gpu3 |
| H3 LBH latent upscaler alone | Must be followed by a refine pass ("saves time, not VRAM") | – | – | – | staged | 0.4 GB |
| MMH3 Ultimate Upscale (v5 research) | Same redraw risk as the H3 refine; users report up to 2550×1920 | Segment seams | – | – | – | – |

DOVE, InfVSR and UltraVSR (2025–26) have no mature ComfyUI or CLI release. As of 2026-10, SeedVR2 and FlashVSR are the only production-grade options.

## 2. Decision

**SeedVR2 3B fp16 → 2160×3840 → light finish → per-shot mezzanine.** No H3 refine by default.

- **Identity.** The rule is "no new details that change identity". SeedVR2 is a one-step restorer conditioned on the frame. The H3 regenerate is a 3-step re-generation from σ 0.8–0.91 and redraws faces, which is wrong for an approved episode.
- **Temporal stability.** SeedVR2 uses temporal batches (21 frames, 4-frame overlap) and colour-corrects to the input in LAB, so the image is not regraded. Frame-wise ESRGAN flickers on exactly our materials.
- **Fits a 3090.** Tiled VAE and CPU offload between phases (512 GB RAM), no fp8 hardware needed. It runs as its own process, so no ComfyUI instance is taken.
- **Cost risk.** It is the slowest acceptable option. If the measured time breaks the budget, the fallbacks in order are: 1440 + Lanczos (`--set sr_short=1440`, already supported), then FlashVSR (§7).

The H3 refine (2K, `start_sigma` ≤ 0.8) stays an optional **hero-shot** pass after its own identity A/B. It is not in this stage.

## 3. The stage (`upscale_4k.py`)

```
per shot  source    the ACTIVE video take in renders_gpu3/epXX/SN/takes.json (takes/video_NNN.mp4)
          prep      crop to exact 9:16 at source resolution (768×1344 → 756×1344 — the same 1.6 % side crop the 1080p
                    master makes; 576×1024 unchanged), 24 fps, lossless H.264 qp 0
          sr        SeedVR2 CLI (venv tools/seedvr2/venv on top of the comfy torch 2.11/cu128):
                    --resolution 2160 --batch_size 21 --uniform_batch_size --temporal_overlap 4 --color_correction lab
                    --seed 42, VAE encode/decode tiled 1024/128, DiT+VAE offload to CPU between phases,
                    10-bit x265 CRF 12 intermediate. OOM → batch 13 → 9 → 5 → 5 + 16 swapped blocks
          qc        flicker / colour / identity / 100 % crops (below); severe failure → Lanczos fallback for that shot
          deliver   renders_gpu3/epXX/SN/takes/video_NNN_4k.mp4
                      finish: Lanczos to 2160×3840 if SR ran below 4K · unsharp 5×5 luma 0.25 · temporal luma grain σ2
                              (ffmpeg noise) · no LUT, no grade
                      HEVC Main10 CRF 12 mezzanine, yuv420p10le, hvc1, BT.709 limited, 24 fps, frame count = source (243)
                      audio: the take's own track, stream copy
                    + video_NNN_4k.json {frames, fps, w×h, duration, sha256, size, source + sha256, settings + hash,
                      engine / fallback, GPU, peak VRAM, prep / sr / qc / deliver seconds, QC}
episode   manifest  renders_gpu3/epXX/upscale4k_manifest.json: QA gate reason, settings, SeedVR2 commit, all shot records
          preview   QC ONLY: data/run/weita/epXX/upscale4k/epXX_4k_QC_PREVIEW.mp4, made from the delivered shots with the
                    1080p final's 0.3 s crossfades and end card (from the series' manifest.jsonl record of that exact
                    final). Audio is stream-copied from the 1080p final; H.264 CRF 18. NOT the official final.
```

**Resumable.**
- A shot is skipped when its sidecar has the same source sha256 and the same settings hash, and the file sha256 still matches.
- A new active take changes `video_NNN`, so it is upscaled automatically.
- SeedVR2 intermediates are cached separately, so changing only grain or sharpening re-runs just the finish.

**Notes for T38 (final H.264).** Measured on a 4K clip (5 s, x264 `-preset slow -tune film`):

| Grain | CRF 15 | CRF 17 |
|---|---|---|
| none | 42 Mbit/s | 30 Mbit/s |
| σ2 (the default) | 76 Mbit/s | 39 Mbit/s |
| σ3 | 148 Mbit/s | 83 Mbit/s |

- Recommended: CRF 16–17 + `-maxrate 60M -bufsize 120M -profile:v high -level:v 5.1 -pix_fmt yuv420p`.
- An HEVC Main10 CRF 16 master of the same content ran at ≈21 Mbit/s.
- On gpu3's shared CPU, a 33 s 4K H.264 + HEVC10 dual encode took 140 s.
- Mezzanine size: 45 MB per 10 s shot with Lanczos content; SeedVR2 detail will raise it.

### QA gate (when a 4K run is allowed)

`weita_series.py` is only read, never modified. It records each episode in two places:
- `ns-studio/data/run/weita/STATUS.log`, one line per run at STEP D: `[epNN] ✅ …` (all six shots OK), `⚠️ … | BLOCKED:…`, `⛔` (paused), `⏸` (held).
- `renders_gpu3/epNN/status.json` (`qa`: pending/pass/fail).

The gate uses the same priority as NS-Final `services/canvas_api/ns_canvas/progress._qa`, so the canvas and this stage agree:
1. A `qa.json` with a `verdict`, in `renders_gpu3/epNN/` or `data/run/weita/epNN/`. `pass`/`passed`/`approved`/`ok` → run; anything else → no.
2. A `QA_HOLD` or `QA_FAIL` marker → no.
3. A `QA_PASS` marker → run. Optional content: the sha256 of the approved `epNN_final.mp4`. If that sha256 no longer matches, the approval is stale → no.
4. The **last** STATUS.log line of the episode is ✅ → run. ⚠️, ⛔ and ⏸ never qualify on their own.

`epNN_final.mp4` must also exist.

Tested on a fake episode: ✅ → run; QA_HOLD → no; stale QA_PASS → no; sha-matching QA_PASS → run; a later ⛔ line → no.

### GPU admission (4K is the LAST step)

A GPU is used **only when `/root/.local/state/NS-Studio/lend.gpuN` names `upscale-4k`**. The coordinator writes it when there is a gap:

```bash
echo '{"by":"coordinator","for":"upscale-4k","until":"…"}' > /root/.local/state/NS-Studio/lend.gpu3
```

Even with the lend, the stage waits until all of these hold:
1. No `train.lock.gpuN`.
2. The ComfyUI queue is empty and utilisation stays ≤ 10 % for 60 s. Some clients submit to ComfyUI without taking the lock; on 2026-10-30 the gpu3 lock was stale while `:8191` was rendering.
3. `gpu.lock.gpuN` is created with O_EXCL (`pid:<pid> upscale_4k:<unit>`; a stale lock is cleared when its pid is dead).

Then it POSTs `/free` to that GPU's ComfyUI and needs ≥ 20 GB free. The lock is held for one shot, then the lend is re-checked.

GPUs:
- **Candidates:** 3, then 0 (`--gpu`, `UPSCALE_GPUS`).
- **Never:** GPU 2 (hard-coded).
- **GPU 1:** only if listed and lent.
- `--allow-idle` / `UPSCALE_ALLOW_IDLE=1` also accepts a really idle card. Use it only after the series is final.

### QC (`upscale_4k.py qc --before --after --out`, ≈46 s per 10 s shot on CPU)

- **Flicker.**
  - `static_ratio` is the mean |ΔY| between consecutive frames (Gaussian σ 1.5) over areas that are static in the source. It is computed on the result and on a Lanczos baseline; ratio = result / baseline.
  - `hf_ratio` is the same on the high-pass residual (new texture "boiling").
  - Noise floor: a pure Lanczos deliverable scores `static_ratio` 1.22 and `hf_ratio` 1.15. That is the x265 CRF 12 encode.
- **Colour.** Mean CIE-Lab ΔE between the source and the area-downscaled result, plus the L drift. The Lanczos deliverable scores ΔE 1.01 and L −0.2.
- **Identity.** SFace cosine of the source face against the downscaled result's face, every 24 frames. The Lanczos deliverable scores 0.997–0.999.
- **Crops.** At 15/50/85 % of the shot, 640 px crops at 100 % on the 4K grid, [source Lanczos | 4K]:
  - the face (YuNet),
  - the two highest-detail regions (jewellery, hair, gloss, hands),
  - plus `--crop name:x,y,w,h`.
  - Layout example: `D:\NS-Final Studio\previews\upscale\qc_format_example_lanczos_f205_face.png` (Lanczos vs Lanczos, format only).
- **Fallback limits** (first guess, to be calibrated on real SeedVR2 output). Any of these drops the shot to Lanczos and records it:
  - identity < 0.75
  - `static_ratio` > 1.6
  - ΔE > 4

## 4. Commands

```bash
cd /root/claude-kimi-ns-studio-v1/ns-studio
.venv/bin/python scripts/upscale_4k.py status                 # QA gate + 4K state of ep01..60
.venv/bin/python scripts/upscale_4k.py episode 1              # approved episode → per-shot 4K + manifest + QC preview
.venv/bin/python scripts/upscale_4k.py shot <clip> --out DIR  # one clip + full QC (tests / A/B)
.venv/bin/python scripts/upscale_4k.py qc --before a.mp4 --after b.mp4 --out DIR [--crop heels:0.3,0.8,0.2,0.15]
systemd-run --unit=ns-upscale4k --collect -p Nice=10 -p WorkingDirectory=$PWD \
    .venv/bin/python scripts/upscale_4k.py watch              # every approved, not yet delivered episode
touch data/run/weita/UPSCALE_STOP                             # stops the watcher between episodes
# options: --gpu 3,0 · --no-wait · --no-preview · --allow-idle · --force-gate (tests)
# settings: --set sr_short=1440 · batch_size=13 · temporal_overlap=4 · color_correction=wavelet · grain=0 ·
#           unsharp=0 · input_noise_scale=0.1 · dit_model=seedvr2_ema_7b_sharp_fp16.safetensors · engine=lanczos (CPU)
# CPU-only pipeline test on a fake episode:
#   WEITA_OUT=<dir>/weita WEITA_RENDERS=<dir>/renders .venv/bin/python scripts/upscale_4k.py episode 1 --set engine=lanczos
```

The pending GPU A/B (`systemd-run` unit `up4k-test`, script `tools/seedvr2/tests/run_ab.sh`) is waiting for a lend that names upscale-4k. It upscales the QC-passed `ep01/clips/ep01s4.mp4` twice:
- direct to 2160 → `tools/seedvr2/tests/direct2160/`
- at 1440 + Lanczos → `tools/seedvr2/tests/s1440/`

Each output folder holds `ep01s4.4k.json` (timings, VRAM), `ep01s4_qc/` (crops, qc.json) and `ep01s4.seedvr2.log`.

## 5. Weights and environment (sha256 checked against the huggingface.co API, downloaded via hf-mirror)

| File | Bytes | sha256 | Location |
|---|---|---|---|
| `seedvr2_ema_3b_fp16.safetensors` | 6 783 018 808 | `2fd0e03a3dad24e0…93e2b304` ✅ | `ComfyUI/models/SEEDVR2/` |
| `ema_vae_fp16.safetensors` | 501 324 814 | `20678548f420d98d…da8612ca1` ✅ | same |

- Code: numz/ComfyUI-SeedVR2_VideoUpscaler @ `4490bd1f` (2025-12-24) in `tools/seedvr2/src`, unmodified.
- Venv `tools/seedvr2/venv`: diffusers 0.42.1, peft, accelerate, omegaconf, rotary-embedding-torch, opencv-headless, gguf, psutil.
- torch comes from `env/comfy` through a `.pth`, so the shared env is untouched. No flash-attn or sage-attn: attention runs on SDPA.
- 7B is not downloaded. It would be fetched only if the 3B fails the face A/B.

## 6. Test status and what to measure

Done on CPU (tests in `tools/seedvr2/tests/fake/`):
- QA gate cases (§3).
- Canvas take discovery: the active take; superseded folders are skipped.
- Lanczos-engine delivery of 3 shots: 2160×3840, 243 frames, 24 fps, HEVC10 + take audio, sidecars, resume.
- The QC-only preview assembly (crossfades, end card, 1080p audio copy).
- QC metrics and crops.
- Bitrate table.

Not done: **SeedVR2 on a GPU.** No GPU has been lent to upscale-4k yet. A CPU run isn't practical: bf16 runs on about 1 core, and a 256 px × 21-frame crop was still in VAE encode after 10 min.

To record from the A/B (written automatically to the sidecars), for each of direct 2160 and 1440 + Lanczos:
- seconds per 10 s shot (SR, prep, QC, deliver), peak VRAM, which OOM-ladder step succeeded;
- `static_ratio` / `hf_ratio` / ΔE / identity against the Lanczos floor (1.22 / 1.15 / 1.0 / 0.998);
- the 100 % crops (face, hair, jewellery, gloss), copied to `D:\NS-Final Studio\previews\upscale\`.

## 7. Time for 60 episodes (≈360 shots), estimates until the A/B runs

| Route | GPU time per 10 s shot (est.) | 360 shots, 1 GPU | 2 GPUs (3 + 0) |
|---|---|---|---|
| SeedVR2 3B direct to 2160 | 30–60 min | 180–360 h (7.5–15 days) | 4–7.5 days |
| SeedVR2 3B at 1440 + Lanczos | 12–25 min | 72–150 h | 1.5–3 days |
| FlashVSR (not installed) | 5–10 min | 30–60 h | 15–30 h |

CPU per shot, overlapping the next shot's GPU work: about 1 min prep + deliver + 1 min QC. The 4K preview adds about 2–4 min per episode on CPU.

## 8. Decisions for the owner / coordinator

1. **Budget versus route.** If direct-2160 SeedVR2 measures near 60 min per shot, the series needs weeks of GPU time. Choose one: the 1440 + Lanczos route, a dedicated GPU after production, or FlashVSR for the B-roll with SeedVR2 for close-ups.
2. **GPU lend.** A ≈1–2 h lend of GPU 3 or 0 (`lend.gpuN` naming upscale-4k) for the ep01s4 A/B. That measurement replaces the estimates above.
3. **Grain.** σ2 doubles the H.264 bitrate at CRF 15. Keep σ2 with a 60 Mbit/s cap, or deliver without grain and let T38 add it at the final encode.
4. **Mezzanine format.** HEVC Main10 CRF 12 with the take's audio is chosen to keep transfers small. Use ProRes or FFV1 instead if T38 wants a lossless intermediate; it is a one-line change, but the files are 5–10× larger.
