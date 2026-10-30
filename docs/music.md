# Music (BGM) and GPU-side audio assets — T40

> 2026-10-30, claude-gpu3. Scope (after the coordinator's 2026-10-30 change): gpu3 makes the **assets only**:
> the BGM per episode plus the per-shot stems. TTS (🎙/dialogue), the final mix to −14 LUFS / −1 dBTP and episode
> assembly are **T38** (fredw-d9, `services/post/ns_post/`). The audio plan is in `docs/intimate_audio.md`.
> Code: `gpu33:/root/claude-kimi-ns-studio-v1/ns-studio/scripts/audio_post.py` + `audio_bank.py`. Venv: `env/audio`.

## 1. Music model choice

Requirements: runs locally on one RTX 3090 (24 GB); good cinematic or sensual instrumental underscore; length and
BPM can be controlled; commercial-friendly license.

| Model (latest release) | Weights license | 3090 | Instrumental / control | Fit for underscore |
|---|---|---|---|---|
| **ACE-Step 1.5 XL-SFT** (4B DiT, 2026-04) + 5 Hz LM 1.7B | **MIT** (HF card of `ACE-Step/acestep-v15-xl-sft`, `ACE-Step/Ace-Step1.5`) | ≥20 GB without offload; 12 GB with offload | `instrumental=True`, duration 10–600 s, BPM, key, time signature, caption; repaint/cover; seeds | Best open text-to-music quality; follows genre/instrument captions; full-length pieces |
| ACE-Step 1.5 turbo (2B, 8 steps) | MIT | <8 GB | same | Fast fallback (`AUDIO_ACE_MODEL=acestep-v15-turbo`, `AUDIO_ACE_STEPS=8`) |
| DiffRhythm 2 (ASLP, 2025-11) | Apache-2.0 | yes | Built for full songs with lyrics; instrumental mode exists | Song-oriented; weaker control over sparse underscore |
| YuE (2025) | Apache-2.0 | heavy (7B + 1B stages), slow | Lyrics-to-song | Vocal songs, not underscore |
| HeartMuLa oss 3B (2026-01) | Apache-2.0 (since 2026-01-20) | yes, RTF ≈ 1 | Tags + lyrics LM | Song LM; reference-audio control not released yet |
| Stable Audio Open 1.0 | Stability AI Community License (revenue threshold) | yes | ≤47 s clips | Loops and sound design, not 60–90 s structured pieces |
| MusicGen (Meta) | code MIT, **weights CC-BY-NC-4.0** | yes | 30 s windows | Not allowed for commercial use |

Licenses come from the huggingface.co API (`cardData.license`) on 2026-10-30. The ACE-Step facts come from its repo
README and `docs/en/INFERENCE.md`. No ACE-Step 1.6 or 2.0 had been released as of 2026-10-30.

**Decision: ACE-Step 1.5 XL-SFT, 50 steps, CFG 7, with the 1.7B LM ("thinking", PyTorch backend).** The 2B turbo
is installed as the fast fallback. Reasons:
- It is MIT licensed.
- It is the only candidate that is natively an instrumental-capable, duration/BPM/key-controlled generator at
  60–90 s quality on a 3090.
- It uses the same model family ComfyUI ships templates for, so it is easy to inspect.


> **Rule (X-4, owner 2026-10-30, E8):** the episode / per-shot music goes into the H3 prompt (`non_diegetic_music`, `ns_agent.h3_prompt.resolve_music`); at assembly the BGM is muted over shots whose H3 clip already carries music (`ns_post.music.h3_music_shots`, recorded as `bgm.h3_music_shots` in the timeline). The episode BGM below fills only the shots whose H3 music is `N/A`.

## 2. BGM per episode

Input: `Episode.music_bgm` (v3 `**配乐**：… 【BGM】 <English prompt>`) and the per-shot `Shot.music_cue` (`【配乐】`).
Until the shared importer publishes `script_v3.json`, both come from the v3 writer's draft
`tools/weita_v3/work/epXX.json` (`score.en`, `cues`). The json records this as `music_source`. Shot durations come
from the imported script.

Steps:
1. **Cues.** Each `【配乐】` is parsed into `{action, intensity 0–3, duck_db}`:
   - **action:** 进入 = enter · 延续 = continue · 渐强 / 推到高点 = swell · 撤到静默 / 落下 = drop · 重音 = stinger.
   - **ducking:** 对白避让 / 独白避让 = duck 6 dB; 无需避让 = no duck.
   - A missing intensity is inherited from the previous cue.
2. **Caption.** The 【BGM】 prompt plus "Instrumental only, no vocals, cinematic underscore" plus an arrangement
   sentence built from the cue timeline, e.g. "enters at 0:00, sparse and quiet; from 0:06 it swells to fuller,
   building; a soft accent hit at 0:13; at 0:26 it drops away". The lyrics field carries section tags
   (`[Intro] [Build] [Hook] [Breakdown] [Outro]`, each `[Instrumental]`). BPM and key are taken from the prompt
   when it states them.
3. **Generation.** ACE-Step generates 2 seeds (deterministic per episode), each the episode length + 2 s.
4. **Selection.** For each candidate:
   - CLAP (`laion/larger_clap_general`, Apache-2.0) similarity to the 【BGM】 prompt;
   - minus a penalty when Demucs finds vocals (vocal level above −25 dB relative to the mix).
   The best candidate is kept.
5. **Output.**
   - `epXX.wav`: 48 kHz stereo, 24-bit, −20 dBFS RMS, **unshaped**. T38 applies the cue levels and the ducking with
     its `level_curve`, so the levels are not baked in twice.
   - `epXX.json` with: `cues` (the format of `ns_post.music._cue_from_json`), `duck_spans` (H3 vocal activity —
     dialogue and moans — in absolute seconds, from the shots' Demucs vocals), `shot_starts`, `bpm`, `keyscale`,
     `model`, `seed`, `steps`, `prompt`, `caption`, `lyrics`, `candidates` (CLAP and vocal scores), `sha256`,
     `input_sha256` (the rebuild key), and GPU timing and VRAM.

Where the files go:
- gpu3: `nsfs_mirror/data/music/` (+ a copy in `renders_gpu3/epXX/music/`).
- Laptop: `D:\NS-Final Studio\data\music\`.

**Owner's canvas music edits** (`ns_schema.edits`). The laptop's `data/renders/epXX/…` is mirrored on gpu3 at
`nsfs_mirror/data/renders_laptop/epXX/`.
- `SN/edits.json` → `ShotEdit.music` replaces that shot's 【配乐】 cue. It is parsed with the same vocabulary, and
  the cue is marked `"source": "edit"`.
- `episode_edit.json` → `EpisodeEdit.music` replaces the 【BGM】 prompt.
- The sha256 of the edits is part of the BGM cache key (`input_sha256`). `epXX.json` records `edits`,
  `edits_sha256` and `bgm_source`.
- `nsaudio-watch` checks every episode that already has a BGM on each pass (≤ 5 min), whatever its QA gate. When the
  edits hash changes it regenerates right away: on a lent or idle GPU if one is free at that moment, otherwise on the
  CPU (turbo, ≈ 8 min). Removing an edit regenerates back to the script cues.
- Test (ep01): a fake `S3/edits.json` `{"music": "撤到静默，强度0，无需避让"}` was picked up in ≤ 5 min and
  regenerated on CPU in 462 s. Cue S3 changed from `stinger/2 (script)` to `drop/0 (edit)`, and the caption gained
  "at 0:20 it drops away". Removing the file triggered the regeneration back to the script cues.

**Needs a hook in T38:** today `assemble.py` ducks BGM only under its own TTS lines. To duck under H3 moans and
dialogue, it should also apply `epXX.json:duck_spans`.

## 3. Per-shot stems (`renders_gpu3/epXX/SN/audio/`)

All stems are 48 kHz stereo, 24-bit, and exactly the clip length. `stems.json` follows `ns_post.music.load_stems`:
`stems.{name}.{file, offset_s, gain_db, role, duck_under_voice_db, duck_under_vo_db, sha256, source}`, plus
`vocal_spans`, `h3_rest_tags`, `plan`, `timings_s` and `gpu`.

| Stem | How | Role / suggested gain |
|---|---|---|
| `h3_vocals.wav` | Demucs **htdemucs_ft** (MIT; weights from dl.fbaipublicfiles.com, torch-hub hash-prefix check) two-stem split on CPU (≈10–20 s per 10 s shot) | vocals, 0 dB |
| `h3_rest.wav` | Everything that is not vocals. If CLAP finds **music** in it (H3 invents music when the prompt has no `non_diegetic_music: N/A`; 4 of the 5 ep01 shots), `h3_rest.wav` becomes the Demucs **drums** stem only (transients) and the full bed is kept as `h3_rest_full.wav` | scene, −3 dB |
| `foley.wav` | HunyuanVideo-Foley **XL** (video + English prompt from the shot's `sound`/`【亲密声】` via a phrase table, plus the non-voice sentences of `【H3 audio】`; negative "speech, voice, music, moaning, breathing"), 50 steps, seed per shot; loudness-matched to the H3 track | foley, −8 dB, duck 8 dB under voice |
| `motifs.wav` | Procedural bank (§4). Heels follow H3 transient onsets (2–9 kHz band) or a walking cadence (0.55 s; 0.36 s for 急促) through the scene's synthetic room (大堂 = lobby RT60 1.9 s, …). Bells, 5 mm balls and patent-leather creaks follow picture-motion peaks (frame-difference curve). The heartbeat follows a tempo (72, or 112 bpm and accelerating for 渐强 / 一声比一声) | foley, −6 dB, duck 6 dB |
| `partner.wav` | Synthetic male breathing (calm / aroused / heavy / sleep-snore), only when the text asks for it (他的呼吸, 两人…呼吸, 交错的鼻息, 鼾, `【亲密声】` 男/他…喘). Off-centre pan; −4.5 dB wherever it overlaps H3 vocal spans, so he never covers 林晚 | vocals, −8 dB |

Episode marker: `renders_gpu3/epXX/AUDIO_STEMS.json` (`complete` is true when every shot has its stems and no
pending Foley).

## 4. Sample bank (`ns-studio/data/audio_bank/`, `bank.json`)

**Source and license: 100 % procedural synthesis in `audio_bank.py`.** Numpy noise and oscillators, modal
resonators, stick-slip pulse trains, formant-filtered noise; fixed seeds. There are no recordings and no
third-party samples, so the bank is original, project-owned audio usable commercially. `bank.json` lists every
file with its seed and sha256. 186 files, 25 MB.

| Group | Variants | Model |
|---|---|---|
| heel_marble / tile / wood / carpet | 16/12/12/12 | 12 cm needle heel: sub-ms tip contact + heel-stem ring modes (2.1–8.9 kHz) + shoe-body knock + softer sole contact 60–130 ms later; surface-specific damping |
| bell_tinkle / bell_shake | 12/12 | small jingle bell: inharmonic shell partials (f0 2.7–3.9 kHz) struck 1–5 times + inner-ball rattle |
| ball | 20 | 5 mm steel ball on a thin piercing ring: 7–15 kHz ticks + ring mode 3.3–4.6 kHz, 1–3 hits |
| patent_creak / patent_squeak | 12/12 | oiled-gloss patent leather: stick-slip pulse train (80–330 Hz creak, 550–1400 Hz squeak) through body resonances |
| heartbeat | 8 | lub-dub, 48–68 Hz |
| breath_calm / aroused / heavy / sleep | 12/12/12/8 | male inhale (nasal or teeth formants) + exhale (male neutral-vowel formants), light voiced component for heavy, snore flutter for sleep |

Audition: `D:\NS-Final Studio\previews\audio\bank_audition.wav` (index in `bank_audition.txt`).

## 5. Trigger and GPU

- `audio_post.py watch` (default `--gate qa`) takes an episode only when the 4K stage's QA gate holds:
  `epXX_final.mp4` exists, there is no QA_HOLD or QA_FAIL, and either QA_PASS (sha-checked) or the last STATUS.log
  line is ✅.
- Stems are rebuilt when a shot's `video.mp4` sha256 changes. The BGM is rebuilt when its input key changes
  (caption, structure, duration, model). Touch `data/run/weita/AUDIO_STOP` to stop.
- `--gate shots` makes stems as soon as each shot's `video.mp4` is approved (`status.json` ok), without waiting for
  the episode final.
- GPU rules:
  - GPU 0 or 3 only when `lend.gpuN` exists; GPU 1 when idle; never GPU 2.
  - `gpu.lock.gpuN` is taken with O_EXCL and released after each job.
  - The ComfyUI queue must be empty and utilisation ≤ 10 % for 60 s. ComfyUI is sent `/free` before loading.
  - Required free memory: Foley 17 GB, BGM 18 GB.
- CPU only: Demucs, CLAP tagging, motifs, partner.

```bash
cd /root/claude-kimi-ns-studio-v1/ns-studio
../env/audio/bin/python scripts/audio_post.py status
../env/audio/bin/python scripts/audio_post.py stems 1 [--shots 1,2] [--no-foley] [--force]
../env/audio/bin/python scripts/audio_post.py bgm 1 [--prompt "..."] [--seeds 2] [--force]
../env/audio/bin/python scripts/audio_post.py episode 1
systemd-run --unit=nsaudio-watch --collect -p WorkingDirectory=$PWD ../env/audio/bin/python scripts/audio_post.py watch
```

## 6. Weights (hf-mirror; sha256 checked against the huggingface.co API, queried from the laptop)

Location: `env/audio_models/`. Downloader: `env/audio_src/fetch_hf.sh` + `hf_manifest*.tsv`, which hold the sha256
of every LFS file.

| Repo | Files | License |
|---|---|---|
| ACE-Step/acestep-v15-xl-sft | 4 × safetensors (19.9 GB, fp32) | MIT |
| ACE-Step/Ace-Step1.5 | vae, Qwen3-Embedding-0.6B, acestep-5Hz-lm-1.7B, acestep-v15-turbo | MIT |
| tencent/HunyuanVideo-Foley | hunyuanvideo_foley_xl.pth, synchformer_state_dict.pth, vae_128d_48k.pth | Tencent Hunyuan Community License (excludes EU/UK/KR; commercial terms need legal review, see intimate_audio.md §4.1) |
| google/siglip2-base-patch16-512 | model.safetensors | Apache-2.0 |
| laion/larger_clap_general | pytorch_model.bin | Apache-2.0 |
| Demucs htdemucs_ft | 4 × .th (dl.fbaipublicfiles.com) | MIT |

Code: ACE-Step-1.5 `main` (codeload tarball, 2026-10-30) and HunyuanVideo-Foley `main`, both in `env/audio_src/`.

## 7. Test results (ep01)

Test material:
- Shots: ep01 S1–S5, the approved v2 renders `renders_gpu3/ep01/SN/video.mp4`, 10.125 s each. S6 has no video yet,
  and no ep01 final exists yet.
- BGM input: the v3 draft (`tools/weita_v3/work/ep01.json`).

**GPU: none was available during the test (≈ 2.5 h).**
- GPU 0 was held by the v3 LLM (gpu.lock).
- GPU 3 was held by frame renders (gpu.lock).
- GPU 1 ran ComfyUI jobs at 100 % that take no lock.

So everything below ran on the CPU fallback (EPYC 7K62, shared with other jobs), and GPU timings and VRAM are not
measured yet. A GPU-only job is queued: `nsaudio-bgm-xl-ep01` regenerates the ep01 BGM with XL-SFT when GPU 1
becomes idle or a GPU is lent, and records the time and VRAM peak in `ep01.json:gpu`. Expected VRAM, from the
model cards: Foley XL ≈ 16 GB; ACE-Step XL bf16 ≈ 10 GB plus the LM ≈ 4 GB.

### Timings (CPU)

| Step | Time |
|---|---|
| Demucs htdemucs_ft | 10–15 s per shot (first load 159 s including the weight download) |
| CPU stems pass (Demucs + CLAP tags + motifs + partner) | 10–30 s per shot |
| HunyuanVideo-Foley XL, **fp32** on CPU | 254–574 s per shot (model load 38 s) |
| ACE-Step 1.5 **turbo**, 8 steps, CPU | 2 seeds × 62 s of audio: 226 s; 3 seeds: 352 s (713 s including load and CLAP/Demucs scoring) |

Foley in bf16 on the CPU took **600 s per step** (Zen 2 has no native bf16), so the CPU path casts the model to
fp32 (3.5 s per step).

### Findings

1. **H3 invents music.** CLAP on the Demucs non-vocal bed finds piano or background music in 4 of the 5 shots:
   S1 0.99, S3 0.99, S4 0.85, S5 1.0. The weita H3 prompts have a `Soundscape:` line but no
   `non_diegetic_music: N/A`. For those shots, `h3_rest.wav` is now only the drums stem (transients), and the full
   bed is kept as `h3_rest_full.wav`.
   - **Recommendation for the series renderer:** add a line equivalent to "Background music: none (N/A)" to
     every H3 prompt.
   - H3 also produced **no heel clicks** in S1, so the motif layer carries them.
2. **Foley.** Video-conditioned Foley invents murmured speech when lips move (S2 "speech" 0.95, S4 0.92).
   - Every Foley take now goes through Demucs, which removes the vocals.
   - A CLAP QC gate then rejects takes that are still speech- or music-dominated (speech + music > 0.6). On the
     GPU it reseeds once first.
   - ep01 result: S4 "dishes clinking" 0.74 ✓; S5 "fabric rustling / water" ✓; S2 hum/speech 0.47/0.47 (passes,
     borderline); **S1 lobby and S3 elevator rejected** (music + speech 0.88 / 0.95). For those two shots T38 has
     no Foley and only the H3 drums stem as scene.
3. **Motif bank.** CLAP was used as a stand-in for listening.
   - The v1 heel heard as "dripping water" 0.92. The v2 heel (CLAP-tuned: broadband 10 ms tip, quiet low ring,
     strong sole contact) scores "footsteps" 0.75 in the lobby room.
   - In the S1 context with the gait model (L/R asymmetry, jitter) CLAP is undecided (heartbeat / dripping /
     breathing ≈ 0.3 each), so the heels **need a human listen**.
   - Heartbeat: 0.99 ✓. Partner calm breathing (v2): "breathing" 0.98 ✓. Aroused/heavy: 0.85.
   - Bells, balls and patent leather are not in ep01 and are not yet checked in context.
4. **BGM.** Of the three turbo seeds, two were drum-led ("drums and beat" 0.89 / 0.99; one had vocals at −19 dB)
   although the prompt asks for minimal electric piano. The drum and vocal penalty picked seed 96849675 ("ambient
   pad" 0.86, drums 0.02, vocals −45.7 dB, CLAP-to-prompt 0.28, 60 BPM, 62.0 s).
5. **Audition.** Stems summed at their suggested gains + BGM at the cue levels, ducked under H3 vocal spans,
   single-pass loudnorm: **−15.3 LUFS, −0.9 dBTP** (T38's two-pass loudnorm gets −14).
   File: `D:\NS-Final Studio\previews\audio\ep01_stems_audition.mp4`. This is **not** the production mix.

### Still weak / next steps

- The **synthetic heels are the weakest motif**. If a human listen confirms it, replace them with 10–20 CC0 or
  in-house recordings of a 12 cm stiletto on marble/tile/wood (a 30-minute recording session). They would drop into
  the same bank layout with no code change.
- **Foley on lobby and elevator shots** is rejected or borderline. Options: try the XXL model on a GPU, or keep a
  synthetic room-tone bed per location (elevator hum, lobby air) in the bank.
- **H3 music** should be fixed at the source (the prompt line above). That gives back a clean ambience bed instead
  of a drums-only stem.
- **BGM:** listen to the XL-SFT version from the queued GPU job before switching all episodes to it.
- **GPU access:** at the current load (lockless ComfyUI clients on GPU 1), a lend (`lend.gpu1` or a slot on GPU 3)
  is needed for ≈ 6 shots × 30–60 s of Foley + 1–2 min of BGM per episode. The CPU fallback costs ≈ 30–60 min per
  episode.
