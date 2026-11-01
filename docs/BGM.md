# 整集配乐 BGM 链接（BGM10 2026-11-01）

链条位置：`config/pipeline/chain.yaml` → `links.P4-P9.bgm`（产物属 P9 声音，进 P9-P10 合成）。规则：`knowledge/rules/edit_bgm.yaml`（K-EDT-B01…B06）。
项目方决定：整集统一 BGM（2026-10-31，“ep02 的配乐用哪种？”→“整集统一 BGM”）。新剧目录 `data/music/series10/`；旧剧 `data/music/epNN.wav` 不用。

## 1. 音乐模型选择（2026-11-01 核对）

| 模型 | 许可（官方来源） | 能不能用 | 说明 |
|---|---|---|---|
| **ACE-Step 1.5 XL-SFT**（4B DiT，2026-04）+ 5Hz LM 1.7B | **MIT**：HF API `cardData.license = mit`（https://huggingface.co/ACE-Step/acestep-v15-xl-sft ，https://huggingface.co/ACE-Step/Ace-Step1.5 ）；代码 LICENSE “MIT License, Copyright (c) 2026 ACEStep”（https://github.com/ace-step/ACE-Step-1.5/blob/main/LICENSE ） | **用** | `instrumental=True`、时长 10–600 s、BPM / 调 / 拍号、结构标签；README：XL “≥12GB VRAM (with offload + quantization) or ≥20GB (without offload)” |
| ACE-Step 1.5 turbo（2B，8 步） | MIT（同上） | 回退 | 显存不够 / CPU 时用 |
| YuE（m-a-p/YuE-s1-7B-anneal-en-cot） | apache-2.0（HF API） | 不用 | 歌词到歌曲（带人声）的模型，7B+1B 两段，慢；不适合纯器乐铺底 |
| Stable Audio Open 1.0 | “stable-audio-community LICENSE”（HF API `license: other`，需同意） | 不用 | 社区许可有营收门槛；单段 ≤47 s |
| MusicGen（facebook/musicgen-large） | **cc-by-nc-4.0**（HF API） | 不能用 | 非商用 |

HF 上 ACE-Step 账号最新发布（2026-11-01 查 `api/models?author=ACE-Step&sort=lastModified`）：xl-sft / xl-base / xl-turbo 及其 diffusers 版本，没有 1.6 / 2.0；GitHub 最新 release v0.1.8（2026-05-18）。
权重已在 gpu33：`/root/claude-kimi-ns-studio-v1/env/audio_models/ACE-Step/`（T40 下载，sha256 校验见 docs/music.md §6）。

## 2. 流程（tools/bgm/agent.py）

1. **时间轴**（`bgm_timeline.py`，确定性）：P4 每镜起点 / 时长 / 有无人声（`**对白**` / `**🎙**`）/ 【配乐】cue；P3 `target_duration_s`。
2. **brief**（`brief.py`）：写作模型（用途 `music_brief`，未配回退 `script_write`）读【时间轴】+ P4 全文 + P3，按 `config/prompts/bgm_brief.writer.md` 出 `nsfs.bgm_brief/1`：mood_arc、bpm 范围、key、instrumentation、style_words（只写风格词）、caption_en、energy_curve、duck（人声让位区间）、sections（段落 / 换段）、cue_change、negative、loopable、clap_text。校验 `brief_schema.py`（BGM-B01…B14），不过带错误重写 ≤2 轮。
3. **生成**（`remote.py` → gpu33 `/root/work/fredw/bgm/bgm_worker.py`，自己的 venv）：每轮 4 条（重试轮 3 条），时长 = max(时间轴, P3 目标) + 2 s，种子按集 / 轮 / 序号确定。选卡见 §3。
4. **度量**（CPU）：CLAP（laion/larger_clap_general，Apache-2.0）与 clap_text 相似度、零样本标签、人声概率；Demucs htdemucs_ft 人声能量比（vocal_rel_db）；LUFS / 真峰（4× 过采样）；平顶削波；最长静音；librosa 速度；1 s 窗响度曲线与 brief.energy_curve 的相关；可循环时首尾接缝。
5. **闸门**（`agent.gate`，阈值 `config/bgm.json gates`）：人声、削波、静音、时长、CLAP 下限、能量反向 → 淘汰；速度偏离 / 能量弱只标提示。
6. **审听**：审听模型按 `config/prompts/bgm_brief.review.md` 读 brief + 度量表，在闸门通过的里挑一条并写理由；不选就给 retry（caption / bpm / negative）。≤3 轮；3 轮都不选但有通过的 → 按度量兜底（标 `needs_owner_listen`）；一条都没通过 → `needs_owner`，合成走 `--no-bgm`。
7. **交付**（`deliver.py`）：候选统一到 −16 LUFS、真峰 ≤ −1 dBTP（只整体增益，不压缩）→ `data/music/series10/epNN.wav`（48 kHz 24-bit）+ `epNN.json`（合成格式）+ `epNN/meta.json`（全部记录）+ `epNN/cands/*.flac`。

## 3. GPU 规则（gpu33）

- 只用卡 0 / 1 / 3（GPU2 永不用）；该卡 ComfyUI 队列空、利用率 ≤10% **连续 180 s** 才占（与 vidgen.py `yield_s` 同一约定）；每条候选之间再查队列，有别人的任务就停，剩下的记 `yielded` 稍后再投。
- 档位按空闲显存：≥21 GB XL-SFT bf16；≥12.5 GB XL-SFT int8 + offload；≥7 GB turbo + offload；等卡超过 20 分钟回退 CPU turbo。
- 心跳：远端 `/root/work/fredw/gpu_heartbeats/BGM10-<job>.json`；gpu33 的由笔记本镜像到 `data/gpu_heartbeats/`（agent=BGM10，server=gpu33），gpu36 的面板直接读远端。
- **打分放 gpu36**（`generation.score_host`）：CLAP + Demucs 是纯 CPU。11-01 实跑时 gpu33 负载 400–1200（96 核，别的 agent 的 clip_srv / lipsync），本工具 nice 15 后打分一条要 40 分钟以上；gpu36 CPU 空闲，一条约 1 分钟。生成仍在 gpu33（ACE-Step 权重在那），候选 raw.wav 经笔记本 `scp -3` 拷过去（两台之间没有直连钥匙）。gpu36 上的 CLAP / Demucs 权重 sha256 与 gpu33 一致（2026-11-01 核对）。gpu36 venv：`/root/work/fredw/bgm/venv`（py311 + system-site-packages，自己装 librosa / pyloudnorm / demucs / soundfile / transformers 4.57.6）。
- CPU 让道：worker 启动即 `nice 15`；ACE-Step 单条超时调到 3600 s（CPU）/ 1200 s（GPU）——默认 600 s 在高负载 CPU 回退时 4/4 超时（ep04 第一次）。生成失败按基础设施问题重投，不占审听轮次（meta.json `infra_failures`）。
- 不改功耗墙；不碰别人的进程；不往共享环境装包（venv 用 .pth 只读引用 `env/audio` 的包）。

## 4. 合成

`tools/assemble_episode.py epNN --music-dir data/music/series10 …`（`Settings.music_dir`）。assemble 把配乐 RMS 归一后按 cues 强度（统一 2）铺满全集，并按逐句 placement 在对白处压 `duck.dialogue_db`（12 dB）、独白处压 `duck.vo_db`（11 dB），带 `gate_fade_s` 斜坡；H3 自带配乐按 `post.h3_music = duck_under_bgm` 压在 BGM 下。

## 5. 界面

声音页 `#/sound?tab=bgm&ep=N`：整集配乐播放器下列出通过闸门的候选（▶ 试听、度量摘要、「用这一版」一键换用、撤销）。接口：`GET /api/music/{ep}/candidates`、`POST /api/music/{ep}/choose {id | undo}`：只有登录的项目方能换（没登录 401、查看者 / 其他角色 403，身份检查在最前、不兜底），审计记真实账户名（data/audit）。审听理由由审听模型改写成人话存 chosen.reason_plain（tools/bgm/plain.py，提示词 config/prompts/bgm_reason_plain.md；原理由不动），候选提示的人话 flags_plain 由系统在源头生成；界面显示人话，原文与依据在悬停提示里。回归检查：node --experimental-strip-types tools/bgm/check_plain.mts。

## 6. 命令

```powershell
.venv/Scripts/python.exe tools/bgm/agent.py --run data/pipeline/runs/series10_v1 --eps 1-10      # 断点续跑，已交付跳过
.venv/Scripts/python.exe tools/bgm/agent.py --run data/pipeline/runs/series10_v1 --eps 3 --rerun  # 重做一集
.venv/Scripts/python.exe tools/bgm/agent.py --run data/pipeline/runs/series10_v1 --status
.venv/Scripts/python.exe tools/bgm/brief_schema.py data/music/series10/ep01/brief.json --run data/pipeline/runs/series10_v1
```
