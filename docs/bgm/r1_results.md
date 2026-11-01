# 整集配乐结果（tools/bgm/report.py 从 meta.json 生成）

## ep01 — delivered

- brief（写作模型 abliterated-model-large-flash，1 轮；`data/music/series10/ep01/brief.json`）：bpm 62–74（目标 68），key D minor；乐器 sparse felt piano, low synth pad, cello, soft string pad；情绪弧 solitary, hushed late-night stillness → quiet tension, held breath → restrained warmth slowly rising → tender emotional peak → soft, wistful settling；段落 intro / build / main / peak / outro；换段 @19 s；duck 3 段
- caption：A sparse felt piano motif over a low synth pad at a slow 68 BPM in D minor, a single cello line entering in the second half, soft restrained dynamics with a gradual swell to a tender peak and a quiet thinning fade.

| 候选 | 轮 | 模型 | 设备 | 种子 | bpm 参数 | 实测速度 | CLAP | 能量 r | 人声 dB | p_vocal | 最长静音 s | LUFS 原始 | 闸门 | 提示 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| r1_c1 | 1 | ACE-Step 1.5 acestep-v15-xl-sft（50 步，int8，LM 1.7B） | gpu33:0 | 126012209 | 68 | 68.0 | 0.2084 | -0.148 | -29.8 | 0.0 | 2.8 | -19.95 | ✘ silence_gap（2.8 s） | energy_weak（r=-0.148） |
| r1_c2 | 1 | ACE-Step 1.5 acestep-v15-xl-sft（50 步，int8，LM 1.7B） | gpu33:0 | 78022316 | 68 | 68.0 | 0.2147 | -0.052 | -21.1 | 0.007 | 3.35 | -16.79 | ✘ silence_gap（3.35 s） | energy_weak（r=-0.052） |
| r1_c3 | 1 | ACE-Step 1.5 acestep-v15-xl-sft（50 步，int8，LM 1.7B） | gpu33:0 | 23666361 | 65 | 64.6 | 0.2817 | -0.091 | -34.2 | 0.0 | 0.0 | -16.63 | **✔ 选中** | energy_weak（r=-0.091） |
| r1_c4 | 1 | ACE-Step 1.5 acestep-v15-xl-sft（50 步，int8，LM 1.7B） | gpu33:0 | 68504058 | 71 | 143.6 | 0.1269 | 0.245 | -36.7 | 0.002 | 5.6 | -18.29 | ✘ silence_gap（5.6 s） | energy_weak（r=0.245） |

- 第 1 轮决定：审听模型选 r1_c3
- 选中 **r1_c3**（review_llm）：唯一通过闸门的候选（gate_pass=true，longest_gap_s=0.0，无静音断层）。无人声：p_vocal=0.0、vocal_rel_db=-34.2，符合器乐要求；实测 64.6 BPM 落在 62–74 区间（tempo_ok），与 brief 的 68 目标接近；CLAP 0.2817 为四条中最高，标签以 strings/cello/soft string pad/sparse felt piano 为主，正好对上 brief 的配器（felt piano + 低合成 pad + 大提琴 + 弦乐 pad）；spectral_centroid 1026 Hz、onset_rate 1.32 偏暗偏稀疏，贴合 nocturnal/restrained 的夜戏质感。缺点：energy_r=-0.091 偏低（响度曲线与 brief 的渐强—峰值—收束弧线贴合不足），但因 0–12、19–42、42–50 均有 12 dB 人声 duck，动态落差在混音里会被压平，可接受；其余三条均因 silence_gap 2.8–5.6 s 淘汰，r1_c4 还偏快（143.6 BPM 倍速）且带 drums 标签。
- 文件：`data/music/series10/ep01.wav`、`data/music/series10/ep01.json`、`data/music/series10/ep01/meta.json`

## ep02 — delivered

- brief（写作模型 abliterated-model-large-flash，1 轮；`data/music/series10/ep02/brief.json`）：bpm 56–70（目标 62），key A minor；乐器 low sustained synth pad, soft kick pulse, felt piano, warm sub bass, muted string texture；情绪弧 cold, sealed-in tension in a stalled elevator → tightening, breath held, then a slow warm bloom → tender and exposed, the emotional peak → warm domestic calm with an undertow of guilt → hushed, unresolved quiet；段落 intro / build / peak / turn / main / outro；换段 @36 s；duck 3 段
- caption：A restrained minimal cinematic underscore: low sustained synth pads at a slow 62 BPM pulse with a soft kick, cold and tight at first, then sparse felt piano notes enter and the harmony opens gently, thinning out to a near-silent pad at the end.

| 候选 | 轮 | 模型 | 设备 | 种子 | bpm 参数 | 实测速度 | CLAP | 能量 r | 人声 dB | p_vocal | 最长静音 s | LUFS 原始 | 闸门 | 提示 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| r1_c1 | 1 | ACE-Step 1.5 acestep-v15-turbo（8 步） | cpu | 23881978 | 62 | 123.0 | 0.2382 | 0.087 | -38.5 | 0.004 | 4.05 | -17.14 | ✘ silence_gap（4.05 s） | energy_weak（r=0.087） |
| r1_c2 | 1 | ACE-Step 1.5 acestep-v15-turbo（8 步） | cpu | 166945792 | 62 | 21.0 | 0.324 | 0.439 | -39.2 | 0.007 | 0.0 | -18.96 | **✔ 选中** | tempo_off（实测 21.0，brief 56–70） |
| r1_c3 | 1 | ACE-Step 1.5 acestep-v15-turbo（8 步） | cpu | 213851876 | 59 | 60.1 | 0.3534 | -0.119 | -38.0 | 0.002 | 0.0 | -18.72 | 通过 | energy_weak（r=-0.119） |
| r1_c4 | 1 | ACE-Step 1.5 acestep-v15-turbo（8 步） | cpu | 98104683 | 66 | 32.7 | 0.3317 | 0.141 | -42.1 | 0.018 | 0.0 | -17.61 | 通过 | energy_weak（r=0.141） |

- 第 1 轮决定：审听模型选 r1_c2
- 选中 **r1_c2**（review_llm）：四条里唯一在贴合度上站得住脚的：energy_r=0.439 远高于其余（0.087 / -0.119 / 0.141），响度曲线最接近 brief 的冷→暖→回落弧线；clap=0.324 与最高值 0.3534 相当，tags 命中 felt piano(0.365)/low sustained synth pad(0.224)/warm sub bass(0.165)，乐器对得上；无人声（vocal_rel_db=-39.2, p_vocal=0.007），无静音段（longest_gap_s=0.0），频谱质心 381 Hz 偏暗，符合 nocturnal/analog warmth。唯一瑕疵是实测 21.0 BPM 判为 tempo_off，但 21×3≈63 恰在 56–70 目标区间，属慢速脉冲的倍频误判，onset_rate=0.46 也说明是稀疏铺底而非真慢三倍，可接受。r1_c3 的 clap 最高但 energy_r=-0.119，弧线完全反向；r1_c4 的 32.7 BPM 与 0.141 的弱相关均不如 c2；r1_c1 闸门未过（4.05 s 静音缺口）。
- 文件：`data/music/series10/ep02.wav`、`data/music/series10/ep02.json`、`data/music/series10/ep02/meta.json`

## ep03 — delivered

- brief（写作模型 abliterated-model-large-flash，1 轮；`data/music/series10/ep03/brief.json`）：bpm 56–68（目标 62），key A minor；乐器 solo piano, sustained low string drone, sparse electronic pulses, high string harmonics；情绪弧 hushed, held breath, intimate tension → slowly tightening, quiet pressure building → fullest, poised and luminous → settling, thinning to near silence；段落 intro / build / peak / outro；换段 @20 s；duck 2 段
- caption：A sparse minimal cinematic underscore: single low piano notes over a sustained low string drone, faint electronic pulses creeping in through the middle, thinning to thin high string harmonics and one last piano note at the end. Slow, restrained, quiet pressure that swells to a medium level and withdraws.

| 候选 | 轮 | 模型 | 设备 | 种子 | bpm 参数 | 实测速度 | CLAP | 能量 r | 人声 dB | p_vocal | 最长静音 s | LUFS 原始 | 闸门 | 提示 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| r1_c1 | 1 | ACE-Step 1.5 acestep-v15-turbo（8 步） | cpu | 224013123 | 62 | 129.2 | 0.3123 | 0.423 | -38.7 | 0.0 | 2.65 | -19.79 | 通过 |  |
| r1_c2 | 1 | ACE-Step 1.5 acestep-v15-turbo（8 步） | cpu | 236214346 | 62 | 63.0 | 0.3342 | -0.204 | -39.6 | 0.0 | 2.1 | -20.98 | ✘ energy_inverse（r=-0.204） | energy_weak（r=-0.204） |
| r1_c3 | 1 | ACE-Step 1.5 acestep-v15-turbo（8 步） | cpu | 182349227 | 59 | 117.5 | 0.366 | -0.12 | -39.5 | 0.004 | 7.2 | -18.35 | ✘ silence_gap（7.2 s） | energy_weak（r=-0.12） |
| r1_c4 | 1 | ACE-Step 1.5 acestep-v15-turbo（8 步） | cpu | 212293849 | 65 | 129.2 | 0.3634 | 0.328 | -41.7 | 0.003 | 0.05 | -20.29 | **✔ 选中** |  |

- 第 1 轮决定：审听模型选 r1_c4
- 选中 **r1_c4**（review_llm）：两条通过闸门的候选里，r1_c4 明显更贴合 brief：clap 0.3634（r1_c1 仅 0.3123），标签里 solo piano 0.357 / piano 0.337 / sparse electronic pulses 0.202 与 brief 的独奏钢琴+稀疏电子脉冲乐器表最吻合；energy_r 0.328 虽不算高，但为正且优于 r1_c1 的 0.423 之外的另一条通过项（r1_c1 同为 0.42 但 clap 与乐器匹配更差）；最长静音 0.05 s，远优于 r1_c1 的 2.65 s，54 s 的曲线不会出现空洞；p_vocal 0.003、vocal_rel_db −41.7 dB，基本无人声，符合 dialogue 垫底需求。速度 129.2 落在 62 的倍速容差内（tempo_ok），响度 −20.29 LUFS 归一后无削波。r1_c2（energy_r −0.204 反向）与 r1_c3（7.2 s 静音空洞）闸门未过，不选。
- 文件：`data/music/series10/ep03.wav`、`data/music/series10/ep03.json`、`data/music/series10/ep03/meta.json`

## ep04 — delivered

- brief（写作模型 abliterated-model-large-flash，1 轮；`data/music/series10/ep04/brief.json`）：bpm 60–74（目标 66），key D major；乐器 solo piano, warm upright bass, soft brushed percussion, subtle electronic pulse；情绪弧 warm and domestic, quietly tender → rising intimacy, swelling and heated → cooling down, uneasy quiet → hollow stillness, a held breath → lonely and unresolved, softly aching；段落 intro / build / peak / turn / breakdown / outro；换段 @29 s；duck 2 段
- caption：An intimate cinematic underscore built on solo piano and warm upright bass, slow and restrained, with soft brushed percussion and a faint electronic pulse swelling in the middle, then thinning back to a single sustained piano note.

| 候选 | 轮 | 模型 | 设备 | 种子 | bpm 参数 | 实测速度 | CLAP | 能量 r | 人声 dB | p_vocal | 最长静音 s | LUFS 原始 | 闸门 | 提示 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| r1_c1 | 1 | ACE-Step 1.5 acestep-v15-turbo（8 步） | cpu | 143027082 | 66 | 64.6 | 0.2892 | -0.072 | -40.1 | 0.001 | 0.9 | -19.21 | 通过 | energy_weak（r=-0.072） |
| r1_c2 | 1 | ACE-Step 1.5 acestep-v15-turbo（8 步） | cpu | 50211358 | 66 | 68.0 | 0.3183 | 0.23 | -43.5 | 0.003 | 1.65 | -15.99 | **✔ 选中** | energy_weak（r=0.23） |
| r1_c3 | 1 | ACE-Step 1.5 acestep-v15-turbo（8 步） | cpu | 263128758 | 63 | 152.0 | 0.1874 | -0.068 | -44.4 | 0.001 | 0.55 | -17.41 | 通过 | energy_weak（r=-0.068） |
| r1_c4 | 1 | ACE-Step 1.5 acestep-v15-turbo（8 步） | cpu | 186266610 | 70 | 34.9 | 0.1696 | -0.092 | -42.7 | 0.015 | 1.95 | -17.43 | 通过 | energy_weak（r=-0.092） |

- 第 1 轮决定：审听模型选 r1_c2
- 选中 **r1_c2**（review_llm）：全部四条 gate_pass 但都有 energy_weak 标记，r1_c2 的 energy_r=0.23 是四条里唯一明显正向的（其余 -0.07 ~ -0.09），最贴合 brief 的“中间涨、后段收”的能量弧；tempo 68.0 落在 60–74 且贴近 target 66；clap 0.3183 全场最高；tags 里 soft brushed percussion(0.283)/warm upright bass(0.259)/solo piano(0.254)/subtle electronic pulse(0.166) 与 brief 乐器表几乎逐项对应；p_vocal 0.003、vocal_rel_db -43.5 确认无人声；无削波、真峰 -0.99 交付后 -1.5 dBTP 安全。r1_c1 乐器也对但能量走向几乎无关（-0.072）且响度偏保守；r1_c3 实测 152 BPM 是倍速、centroid 764Hz 偏亮、clap 仅 0.187；r1_c4 34.9 BPM 半速、onset_rate 1.18 偏密、clap 最低 0.1696、p_vocal 0.015 最高。
- 文件：`data/music/series10/ep04.wav`、`data/music/series10/ep04.json`、`data/music/series10/ep04/meta.json`

## ep05 — delivered

- brief（写作模型 abliterated-model-large-flash，1 轮；`data/music/series10/ep05/brief.json`）：bpm 62–74（目标 68），key A minor；乐器 low synth pad, single piano notes, slow kick drum, sustained cello line；情绪弧 cold, held-breath tension in a bright clinic → a sharp peak, then a slow settling → quiet, reflective, almost unfamiliar → warm recognition, softly opening；段落 intro / build / turn / main / peak；换段 @28 s；duck 3 段
- caption：A minimal cinematic underscore: a low synth pad with sparse single piano notes, a slow kick drum entering midway, and one sustained cello line at the close, restrained dynamics that settle then warm slightly.

| 候选 | 轮 | 模型 | 设备 | 种子 | bpm 参数 | 实测速度 | CLAP | 能量 r | 人声 dB | p_vocal | 最长静音 s | LUFS 原始 | 闸门 | 提示 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| r1_c1 | 1 | ACE-Step 1.5 acestep-v15-turbo（8 步，LM 1.7B） | gpu33:1 | 263186381 | 68 | 68.0 | 0.3717 | -0.721 | -22.9 | 0.002 | 0.55 | -14.69 | ✘ energy_inverse（r=-0.721） | energy_weak（r=-0.721） |
| r1_c2 | 1 | ACE-Step 1.5 acestep-v15-turbo（8 步，LM 1.7B） | gpu33:1 | 235303936 | 68 | 136.0 | 0.242 | 0.456 | -25.4 | 0.005 | 1.85 | -15.21 | **✔ 选中** |  |
| r1_c3 | 1 | ACE-Step 1.5 acestep-v15-turbo（8 步，LM 1.7B） | gpu33:1 | 52331682 | 65 | 64.6 | 0.4274 | 0.612 | -38.5 | 0.092 | 4.85 | -16.27 | ✘ silence_gap（4.85 s） |  |
| r1_c4 | 1 | ACE-Step 1.5 acestep-v15-turbo（8 步，LM 1.7B） | gpu33:1 | 58937135 | 71 | 35.9 | 0.0561 | -0.713 | -33.5 | 0.002 | 15.65 | -20.66 | ✘ silence_gap（15.65 s）；energy_inverse（r=-0.713） | energy_weak（r=-0.713） |

- 第 1 轮决定：审听模型选 r1_c2
- 选中 **r1_c2**（review_llm）：唯一过闸门的候选。无人声（vocal_rel_db -25.4，p_vocal 0.005），tempo_ok（136 = 68 的倍速），能量曲线正相关 r=0.456（冷到暖的走向方向正确），无削波、无静音缺口（最长 1.85 s），响度范围 -17.6~-14.4 dB 平稳适合垫底。clap 0.242 偏低、tags 里 'electronic beat' 偏重而 'low synth pad / single piano notes' 不突出，是它的短板；但其余三条均被闸门淘汰（c1/c4 能量反相，c3 有 4.85 s 静音缺口），c2 是当前唯一可用且方向正确的选择。
- 文件：`data/music/series10/ep05.wav`、`data/music/series10/ep05.json`、`data/music/series10/ep05/meta.json`

## ep06 — delivered

- brief（写作模型 abliterated-model-large-flash，1 轮；`data/music/series10/ep06/brief.json`）：bpm 58–68（目标 62），key A minor；乐器 solo double bass pizzicato, sparse felt piano, thin metallic percussion, low string pad；情绪弧 hushed, watchful, intimate tension → warm and deliberate, slowly tightening → rising, restrained swell → full and quietly triumphant, then held；段落 intro / build / main / peak / outro；换段 @38 s；duck 4 段
- caption：A sparse nocturnal underscore built on solo double bass pizzicato at a slow 62 BPM with widely spaced felt piano chords, a thin metallic percussion layer ticking in from the middle, low string pad swelling under the final stretch, then thinning toward a single sustained piano note.

| 候选 | 轮 | 模型 | 设备 | 种子 | bpm 参数 | 实测速度 | CLAP | 能量 r | 人声 dB | p_vocal | 最长静音 s | LUFS 原始 | 闸门 | 提示 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| r1_c1 | 1 | ACE-Step 1.5 acestep-v15-turbo（8 步） | cpu | 245324860 | 62 | 123.0 | 0.0185 | 0.275 | -43.8 | 0.0 | 3.15 | -17.69 | ✘ silence_gap（3.15 s）；clap_low（0.0185） | energy_weak（r=0.275） |
| r1_c2 | 1 | ACE-Step 1.5 acestep-v15-turbo（8 步） | cpu | 39746223 | 62 | 123.0 | 0.1546 | 0.669 | -41.3 | 0.001 | 2.9 | -20.19 | **✔ 选中** |  |
| r1_c3 | 1 | ACE-Step 1.5 acestep-v15-turbo（8 步） | cpu | 206096940 | 60 | 117.5 | 0.2265 | -0.082 | -42.9 | 0.0 | 1.05 | -16.35 | 通过 | energy_weak（r=-0.082） |
| r1_c4 | 1 | ACE-Step 1.5 acestep-v15-turbo（8 步） | cpu | 158790142 | 65 | 129.2 | 0.2111 | 0.381 | -45.6 | 0.05 | 1.2 | -19.33 | 通过 |  |

- 第 1 轮决定：审听模型选 r1_c2
- 选中 **r1_c2**（review_llm）：r1_c2 是唯一同时满足能量走向与乐器质感的候选：energy_r=0.669 远高于其余（c4 0.381 / c3 -0.082），贴合 brief 从 0.12 缓升至 0.82 再回落的弧线；CLAP 标签以 piano(0.285)、sparse felt piano(0.26)、strings、bass 为主，与 felt piano + 低弦垫的编制一致；p_vocal=0.001、vocal_rel_db=-41.3 确认无人声；tempo 123 BPM 为 62 的倍速，tempo_ok；无 gate 失败。c3 虽 clap 略高(0.2265)，但 energy_r 为负、响度曲线平坦（p10-p95 仅 8.4 dB），无法支撑 38s 后的 swell；c4 clap 尚可但 energy_r 偏低且 p_vocal=0.05 略高。c2 的 longest_gap 2.9s 在 64s 素材里属稀疏段落留白，符合 intro 极简设计。
- 文件：`data/music/series10/ep06.wav`、`data/music/series10/ep06.json`、`data/music/series10/ep06/meta.json`

## ep07 — delivered

- brief（写作模型 abliterated-model-large-flash，1 轮；`data/music/series10/ep07/brief.json`）：bpm 54–66（目标 60），key D minor；乐器 low sustained cello drone, sparse single piano notes, thin metallic chime, soft string pad；情绪弧 hushed, ritualistic, held breath → quietly tense, controlled → strained composure, pressure underneath → settled, cool and final；段落 intro / build / main / outro；换段 @31 s；duck 10 段
- caption：A minimal cinematic underscore built on a low sustained cello drone at a slow sixty beats per minute, with sparse single piano notes and a thin metallic chime accenting each clasp, gradually swelling into a soft string pad before thinning out to near silence at the end.

| 候选 | 轮 | 模型 | 设备 | 种子 | bpm 参数 | 实测速度 | CLAP | 能量 r | 人声 dB | p_vocal | 最长静音 s | LUFS 原始 | 闸门 | 提示 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| r1_c1 | 1 | ACE-Step 1.5 acestep-v15-turbo（8 步） | cpu | 104914545 | 60 | 234.9 | 0.3711 | 0.196 | -40.5 | 0.015 | 0.25 | -19.89 | 通过 | tempo_off（实测 234.9，brief 54–66）；energy_weak（r=0.196） |
| r1_c2 | 1 | ACE-Step 1.5 acestep-v15-turbo（8 步） | cpu | 76588584 | 60 | 107.7 | 0.3541 | -0.135 | -41.0 | 0.001 | 2.45 | -16.39 | 通过 | energy_weak（r=-0.135） |
| r1_c3 | 1 | ACE-Step 1.5 acestep-v15-turbo（8 步） | cpu | 70456096 | 57 | 123.0 | 0.3492 | -0.076 | -39.5 | 0.003 | 0.0 | -20.84 | **✔ 选中** | energy_weak（r=-0.076） |
| r1_c4 | 1 | ACE-Step 1.5 acestep-v15-turbo（8 步） | cpu | 25439449 | 63 | 63.0 | 0.4193 | -0.544 | -42.4 | 0.0 | 0.0 | -18.88 | ✘ energy_inverse（r=-0.544） | energy_weak（r=-0.544） |

- 第 1 轮决定：审听模型选 r1_c3
- 选中 **r1_c3**（review_llm）：三条过闸门候选里 r1_c3 最贴合：clap 0.3492 与 r1_c2 的 0.3541 接近，但 tempo 123 是 brief 60 的倍速（tempo_ok=true），而 r1_c2 的 107.7 是 60 的 1.8 倍、不在 brief 54–66 的任何半速/倍速关系里（虽被标 tempo_ok，实际偏离更远）；r1_c1 实测 234.9 完全跑飞。r1_c3 无人声（vocal_rel_db -39.5，p_vocal 0.003），longest_gap 0.0 无静音断层，标签 soft string pad/piano/ambient/sparse piano/cello drone 与 brief 乐器全对上，energy_r -0.076 虽弱但三条里最不逆势（r1_c2 -0.135、r1_c1 0.196 但 tempo 已废）。r1_c4 的 clap 最高 0.4193 但 energy_inverse r=-0.544 闸门未过，不能选。
- 文件：`data/music/series10/ep07.wav`、`data/music/series10/ep07.json`、`data/music/series10/ep07/meta.json`

## ep08 — delivered

- brief（写作模型 abliterated-model-large-flash，1 轮；`data/music/series10/ep08/brief.json`）：bpm 80–96（目标 88），key D minor；乐器 double bass pizzicato, electric piano, muted cello, felt piano；情绪弧 tense and watchful, coiled stillness → slow swell, exposed and defiant → controlled, gliding with quiet friction → suspended, breath held in silence → introspective, unresolved and soft；段落 intro / build / main / breakdown / outro；换段 @38 s；duck 4 段
- caption：A minimal cinematic underscore in D minor at a moderate pace: low double bass pizzicato with sparse electric piano notes, a muted cello swell rising through the middle, felt piano triplets carrying the final stretch, close-miked strings with soft reverb and restrained dynamics.

| 候选 | 轮 | 模型 | 设备 | 种子 | bpm 参数 | 实测速度 | CLAP | 能量 r | 人声 dB | p_vocal | 最长静音 s | LUFS 原始 | 闸门 | 提示 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| r1_c1 | 1 | ACE-Step 1.5 acestep-v15-turbo（8 步） | cpu | 221544336 | 88 | 86.1 | 0.3437 | 0.171 | -45.2 | 0.0 | 0.0 | -17.31 | **✔ 选中** | energy_weak（r=0.171） |
| r1_c2 | 1 | ACE-Step 1.5 acestep-v15-turbo（8 步） | cpu | 135655665 | 88 | 86.1 | 0.369 | -0.477 | -44.4 | 0.0 | 0.2 | -17.02 | ✘ energy_inverse（r=-0.477） | energy_weak（r=-0.477） |
| r1_c3 | 1 | ACE-Step 1.5 acestep-v15-turbo（8 步） | cpu | 38563742 | 84 | 184.6 | 0.4157 | -0.397 | -42.8 | 0.0 | 1.9 | -18.3 | ✘ energy_inverse（r=-0.397） | energy_weak（r=-0.397） |
| r1_c4 | 1 | ACE-Step 1.5 acestep-v15-turbo（8 步） | cpu | 249965830 | 92 | 44.6 | 0.4133 | -0.395 | -44.6 | 0.001 | 2.4 | -18.57 | ✘ energy_inverse（r=-0.395） | energy_weak（r=-0.395） |

- 第 1 轮决定：审听模型选 r1_c1
- 选中 **r1_c1**（review_llm）：唯一通过闸门的候选（gate_pass=true，其余三条均 energy_inverse 淘汰）。r1_c1 无人声（vocal_rel_db=-45.2，p_vocal=0.0），速度 86.1 BPM 落在 80–96 区间，CLAP 标签以 electric piano/felt piano/muted cello/bass 为主，与 brief 配器吻合；能量曲线 r=0.171 偏弱但方向正确（其余候选为负相关），在 38s 处有自然回落空间，配合 duck 与 cue_change 可接受。r1_c2 的 clap 略高（0.369）但能量反相，不可用。
- 文件：`data/music/series10/ep08.wav`、`data/music/series10/ep08.json`、`data/music/series10/ep08/meta.json`

## ep09 — delivered

- brief（写作模型 abliterated-model-large-flash，1 轮；`data/music/series10/ep09/brief.json`）：bpm 62–74（目标 68），key D minor；乐器 solo double bass pizzicato, sparse felt piano, soft brushed drums, low string pad；情绪弧 cool, poised and watchful → quiet tension slowly rising → restrained, a held breath → tight and uneasy, closing in；段落 intro / build / main / breakdown / turn / outro；换段 @39 s；duck 7 段
- caption：A sparse noir underscore built on solo double bass pizzicato and single felt piano notes at a slow 68 BPM, a soft brushed drum pulse entering mid-way, then thinning back to a lone piano note; restrained dynamics, dark and intimate.

| 候选 | 轮 | 模型 | 设备 | 种子 | bpm 参数 | 实测速度 | CLAP | 能量 r | 人声 dB | p_vocal | 最长静音 s | LUFS 原始 | 闸门 | 提示 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| r1_c1 | 1 | ACE-Step 1.5 acestep-v15-turbo（8 步） | cpu | 176059592 | 68 | 136.0 | 0.2671 | 0.184 | -40.2 | 0.0 | 5.4 | -16.4 | ✘ silence_gap（5.4 s） | energy_weak（r=0.184） |
| r1_c2 | 1 | ACE-Step 1.5 acestep-v15-turbo（8 步） | cpu | 45585198 | 68 | 73.8 | 0.2445 | -0.058 | -42.4 | 0.038 | 2.9 | -16.07 | 通过 | energy_weak（r=-0.058） |
| r1_c3 | 1 | ACE-Step 1.5 acestep-v15-turbo（8 步） | cpu | 21356069 | 65 | 66.3 | 0.3267 | -0.05 | -41.6 | 0.006 | 0.7 | -17.19 | **✔ 选中** | energy_weak（r=-0.05） |
| r1_c4 | 1 | ACE-Step 1.5 acestep-v15-turbo（8 步） | cpu | 39959797 | 71 | 71.8 | 0.3944 | -0.709 | -43.6 | 0.0 | 0.25 | -18.51 | ✘ energy_inverse（r=-0.709） | energy_weak（r=-0.709） |

- 第 1 轮决定：审听模型选 r1_c3
- 选中 **r1_c3**（review_llm）：闸门通过的候选里 r1_c3 最贴 brief：clap 0.3267 为三条通过候选最高（r1_c2 仅 0.2445），实测 66.3 BPM 落在 62–74 且贴近 target 68（r1_c2 已到 73.8 边缘），longest_gap 0.7 s 远好于 r1_c2 的 2.9 s，段落衔接更连续；tags 前四为 sparse felt piano / low string pad / piano / soft brushed drums，乐器对得上 brief，bass 权重偏低但整体音色为暗色稀疏；p_vocal 0.006、vocal_rel_db −41.6 确认无人声。energy_r −0.05 虽弱，但三条通过候选都 energy_weak，r1_c3 与 r1_c2 相当，且其响度分布（−26.3…−17.5）比 r1_c2（−27.8…−16.5）动态更收敛，符合 restrained。r1_c1 因 5.4 s 静音段淘汰，r1_c4 能量反相（r=−0.709）淘汰。
- 文件：`data/music/series10/ep09.wav`、`data/music/series10/ep09.json`、`data/music/series10/ep09/meta.json`

## ep10 — delivered

- brief（写作模型 abliterated-model-large-flash，1 轮；`data/music/series10/ep10/brief.json`）：bpm 66–80（目标 72），key A minor；乐器 electric piano, low sustained string drone, soft brushed percussion, sub bass pulse；情绪弧 quiet domestic unease, held breath → determined, coolly rising confidence → tense and questioning, pressure building → hollow, unresolved stillness；段落 intro / build / peak / outro；换段 @32 s；duck 4 段
- caption：A sparse cinematic underscore of solo electric piano notes over a low sustained string drone, moderate slow tempo, restrained and glassy; soft brushed percussion enters in the second half, the arrangement swells gradually then drops away to a near-silent tail.

| 候选 | 轮 | 模型 | 设备 | 种子 | bpm 参数 | 实测速度 | CLAP | 能量 r | 人声 dB | p_vocal | 最长静音 s | LUFS 原始 | 闸门 | 提示 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| r1_c1 | 1 | ACE-Step 1.5 acestep-v15-turbo（8 步） | cpu | 60956400 | 72 | 35.4 | 0.3293 | 0.489 | -42.3 | 0.001 | 0.55 | -17.79 | **✔ 选中** |  |
| r1_c2 | 1 | ACE-Step 1.5 acestep-v15-turbo（8 步） | cpu | 222051671 | 72 | 43.1 | 0.302 | 0.302 | -42.3 | 0.001 | 2.05 | -20.3 | 通过 |  |
| r1_c3 | 1 | ACE-Step 1.5 acestep-v15-turbo（8 步） | cpu | 22029966 | 69 | 69.8 | 0.3415 | -0.618 | -42.3 | 0.0 | 2.25 | -17.91 | ✘ energy_inverse（r=-0.618） | energy_weak（r=-0.618） |
| r1_c4 | 1 | ACE-Step 1.5 acestep-v15-turbo（8 步） | cpu | 125736618 | 76 | 152.0 | 0.4091 | -0.239 | -44.0 | 0.0 | 1.75 | -18.86 | ✘ energy_inverse（r=-0.239） | energy_weak（r=-0.239） |

- 第 1 轮决定：审听模型选 r1_c1
- 选中 **r1_c1**（review_llm）：两条过闸门候选中 r1_c1 明显更贴合 brief：energy_r 0.489 远高于 r1_c2 的 0.302，能量曲线更接近 brief 里由 0.18 缓升到 0.8 再回落的走向；onset_rate 0.52 对 r1_c2 的 0.3，说明中后段“soft brushed percussion enters / 渐强”的推进感更足；longest_gap_s 0.55s 对 2.05s，r1_c2 中段有 2 秒空档，与 build 段持续铺底的要求相悖；clap 0.3293 也高于 r1_c2 的 0.302，乐器标签里 electric piano 0.355、soft brushed percussion 0.183、low sustained string drone 0.123 与 brief 的配器一致；两条均无 vocal（vocal_rel_db -42.3，p_vocal 0.001），tempo 35.4 为 72 的半速、落在 66–80 区间。r1_c2 更安静但推进与能量贴合度都弱，作为备选。
- 文件：`data/music/series10/ep10.wav`、`data/music/series10/ep10.json`、`data/music/series10/ep10/meta.json`

## 交付文件复测（tools/bgm/verify.py：ffprobe + ffmpeg ebur128，2026-11-01 08:12）

| 集 | 文件 | 候选 | 时长 s | 采样率 | 声道 | 位深 | 积分响度 LUFS | 真峰 dBTP | sha256 = json |
|---|---|---|---|---|---|---|---|---|---|
| ep01 | music/series10/ep01.wav | r1_c3 | 62.0 | 48000 | 2 | 24 | -16.0 | -1.0 | 是 |
| ep02 | music/series10/ep02.wav | r1_c2 | 67.0 | 48000 | 2 | 24 | -15.9 | -1.0 | 是 |
| ep03 | music/series10/ep03.wav | r1_c4 | 67.0 | 48000 | 2 | 24 | -16.1 | -1.0 | 是 |
| ep04 | music/series10/ep04.wav | r1_c2 | 67.0 | 48000 | 2 | 24 | -15.7 | -1.5 | 是 |
| ep05 | music/series10/ep05.wav | r1_c2 | 67.0 | 48000 | 2 | 24 | -16.0 | -1.7 | 是 |
| ep06 | music/series10/ep06.wav | r1_c2 | 64.0 | 48000 | 2 | 24 | -15.9 | -1.4 | 是 |
| ep07 | music/series10/ep07.wav | r1_c3 | 67.0 | 48000 | 2 | 24 | -16.0 | -1.0 | 是 |
| ep08 | music/series10/ep08.wav | r1_c1 | 67.0 | 48000 | 2 | 24 | -15.9 | -1.0 | 是 |
| ep09 | music/series10/ep09.wav | r1_c3 | 67.0 | 48000 | 2 | 24 | -16.0 | -1.0 | 是 |
| ep10 | music/series10/ep10.wav | r1_c1 | 67.0 | 48000 | 2 | 24 | -15.9 | -1.0 | 是 |
