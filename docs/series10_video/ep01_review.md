# ep01 视频审阅（VIDEO10 自动生成，待总调度亲审；视频不定稿，只是预览）

成片（预览，540×960 代理合成）：`data\episodes\series10\ep01_v2.mp4`；主机 gpu33

> 本集是**预览**，不是成片（K-REV-302）：V6 多肢 / V7 口型检测器 11-01 才接上，阈值只用负例标定；接上前打分的镜标“V6/V7 未测”，之后的标“V6/V7 已测”，都不是“契约通过”。尽力版不进合成，缺的镜用静帧占位。

- 镜数 7：预览·V6/V7 未测 5，未达契约（尽力，不进合成） 2，等首帧 / 阻断 0；共出片 16 次，GPU 2.8 h
- 通过率（首版 / 最终）：3/7 / 5/7

## 问题与根因（按不合格项计数）

- 多肢 × 5：—
- 口型不合 × 4：—
- 景别不符 × 3：景别：Ref2VA / 两段式构图来自提示词（K-REV-301）→ 阶梯 i2v / 换 seed
- 动作不足 × 1：静止：seed 相关（lab_recipes 批 2）→ 换 seed

## 未测项

- V6 / V7：检测器接上前打分的镜为“未测”；V8 只测了景别，造型未测；发色只记录（K-REV-303）

## ep01-S1 · 预览·V6/V7 已测（阈值只用负例标定） · 入选 v1 · 共出 1 版

- v1（i2va_pdd2，seed 2253215521，gpu33:3，296.9 s）：通过

| 项 | 内容 | 结果 | 数字 |
|---|---|---|---|
| V1 | 身份（逐帧中位 / 最低） | 通过 | 林晚 中位 0.814 最低 0.444 检出 1.0 |
| V2 | 脸颊泛红 | 通过 | cheek_red_max 0.062 |
| V3 | J4 抖动 | 通过 | J4 1.113（z 0.09） |
| V4 | 动作量 / 静止 | 通过 | mean 1.066，静止占比 0.094，头 / 尾定住 0.0/0.12 s |
| V5 | 镜内硬切 | 通过 | HSV 切点 []，跳切 [] |
| V6 | 多肢 / 手指 | 通过 | extra_hand_frac 0.0；dup_side_frac 0.0；flicker 1；bad_finger_frac 0.018 |
| V7 | 口型 | 通过 | mode closed；corr None；open_frac 0.0；seen 1.0 |
| V8 | 与首帧 / 造型一致（景别） | 通过 | 要求 特写，实测 近景/中近景（脸高 0.191，K-REN-122）；造型未测 |

印样 `data/pipeline/runs/series10_v1/video/_thumbs/ep01-S1__v1.jpg`；预览 `data/pipeline/runs/series10_v1/video/_preview/ep01-S1__v1.mp4`

## ep01-S2 · 预览·V6/V7 已测（阈值只用负例标定） · 入选 mot · 共出 2 版

- v1（i2va_pdd2，seed 4126945414，gpu33:3，555.7 s）：动作不足
- mot（i2va_pdd2，seed 823674418，gpu33:3，565.1 s）：通过

| 项 | 内容 | 结果 | 数字 |
|---|---|---|---|
| V1 | 身份（逐帧中位 / 最低） | 通过 | 林晚 中位 0.905 最低 0.526 检出 1.0 |
| V2 | 脸颊泛红 | 通过 | cheek_red_max 0.067 |
| V3 | J4 抖动 | 通过 | J4 1.117（z 0.27） |
| V4 | 动作量 / 静止 | 通过 | mean 0.645，静止占比 0.209，头 / 尾定住 0.0/0.12 s |
| V5 | 镜内硬切 | 通过 | HSV 切点 []，跳切 [] |
| V6 | 多肢 / 手指 | 通过 | extra_hand_frac 0.01；dup_side_frac 0.021；flicker 1；bad_finger_frac 0.208 |
| V7 | 口型 | 通过 | mode closed；corr None；open_frac 0.214；seen 1.0 |
| V8 | 与首帧 / 造型一致（景别） | 通过 | 要求 中景，实测 中景（脸高 0.165，K-REN-122）；造型未测 |

印样 `data/pipeline/runs/series10_v1/video/_thumbs/ep01-S2__mot.jpg`；预览 `data/pipeline/runs/series10_v1/video/_preview/ep01-S2__mot.mp4`

## ep01-S3 · 未达契约（尽力版，不进合成） · 入选 v1 · 共出 4 版

- v1（i2va_pdd2，seed 2752573223，gpu33:3，504.3 s）：多肢
- s2（i2va_pdd2，seed 2512478129，gpu33:3，514.0 s）：多肢
- s3（i2va_pdd2，seed 2364326688，gpu33:3，495.4 s）：多肢
- s4（i2va_pdd2，seed 1706107073，gpu33:3，498.6 s）：多肢

| 项 | 内容 | 结果 | 数字 |
|---|---|---|---|
| V1 | 身份（逐帧中位 / 最低） | 通过 | 林晚 中位 0.72 最低 0.665 检出 1.0 |
| V2 | 脸颊泛红 | 通过 | cheek_red_max 0.112 |
| V3 | J4 抖动 | 通过 | J4 1.155（z 2.0） |
| V4 | 动作量 / 静止 | 通过 | mean 2.264，静止占比 0.029，头 / 尾定住 0.0/0.0 s |
| V5 | 镜内硬切 | 通过 | HSV 切点 []，跳切 [] |
| V6 | 多肢 / 手指 | 不通过 | 多手 |
| V7 | 口型 | 不适用 | 本镜无对白、无独白 |
| V8 | 与首帧 / 造型一致（景别） | 通过 | 要求 中全景，实测 中全景（脸高 0.103，K-REN-122）；造型未测 |

印样 `data/pipeline/runs/series10_v1/video/_thumbs/ep01-S3__v1.jpg`；预览 `data/pipeline/runs/series10_v1/video/_preview/ep01-S3__v1.mp4`

## ep01-S4 · 预览·V6/V7 已测（阈值只用负例标定） · 入选 s2 · 共出 2 版

- v1（i2va_pdd2，seed 1251101598，gpu33:3，574.6 s）：景别不符
- s2（i2va_pdd2，seed 2039758524，gpu33:3，572.8 s）：通过

| 项 | 内容 | 结果 | 数字 |
|---|---|---|---|
| V1 | 身份（逐帧中位 / 最低） | 通过 | 顾沉 中位 0.566 最低 0.073 检出 0.75；林晚 中位 0.374 最低 0.203 检出 0.75 |
| V2 | 脸颊泛红 | 通过 | cheek_red_max 0.147 |
| V3 | J4 抖动 | 通过 | J4 1.154（z 1.02） |
| V4 | 动作量 / 静止 | 通过 | mean 4.44，静止占比 0.021，头 / 尾定住 0.0/0.04 s |
| V5 | 镜内硬切 | 通过 | HSV 切点 []，跳切 [] |
| V6 | 多肢 / 手指 | 通过 | extra_hand_frac 0.01；dup_side_frac 0.0；flicker 8；bad_finger_frac 0.399 |
| V7 | 口型 | 通过 | mode sync；corr 0.586；open_frac 0.0；seen 0.688 |
| V8 | 与首帧 / 造型一致（景别） | 通过 | 要求 中景，实测 中景（脸高 0.122，K-REN-122）；造型未测 |

印样 `data/pipeline/runs/series10_v1/video/_thumbs/ep01-S4__s2.jpg`；预览 `data/pipeline/runs/series10_v1/video/_preview/ep01-S4__s2.mp4`

## ep01-S5 · 预览·V6/V7 已测（阈值只用负例标定） · 入选 v1 · 共出 1 版

- v1（i2va_pdd2，seed 602401524，gpu33:3，506.7 s）：通过

| 项 | 内容 | 结果 | 数字 |
|---|---|---|---|
| V1 | 身份（逐帧中位 / 最低） | 通过 | 林晚 中位 0.742 最低 0.652 检出 1.0 |
| V2 | 脸颊泛红 | 通过 | cheek_red_max 0.065 |
| V3 | J4 抖动 | 通过 | J4 1.062（z 0.98） |
| V4 | 动作量 / 静止 | 通过 | mean 0.632，静止占比 0.017，头 / 尾定住 0.0/0.04 s |
| V5 | 镜内硬切 | 通过 | HSV 切点 []，跳切 [] |
| V6 | 多肢 / 手指 | 通过 | extra_hand_frac 0.0；dup_side_frac 0.0；flicker 0；bad_finger_frac 0.5 |
| V7 | 口型 | 通过 | mode sync；corr 0.747；open_frac 0.171；seen 1.0 |
| V8 | 与首帧 / 造型一致（景别） | 通过 | 要求 近景，实测 中景（脸高 0.165，K-REN-122）；造型未测 |

印样 `data/pipeline/runs/series10_v1/video/_thumbs/ep01-S5__v1.jpg`；预览 `data/pipeline/runs/series10_v1/video/_preview/ep01-S5__v1.mp4`

## ep01-S6 · 未达契约（尽力版，不进合成） · 入选 s3 · 共出 5 版

- v1（i2va_pdd2，seed 387708326，gpu33:1，588.2 s）：景别不符/口型不合
- s2（i2va_pdd2，seed 75458736，gpu33:3，588.0 s）：口型不合
- s3（i2va_pdd2，seed 519698041，gpu33:3，563.7 s）：口型不合
- s4（i2va_pdd2，seed 2645183897，gpu33:0，594.2 s）：景别不符
- r24（two_person_ref2va，seed 3839931088，gpu33:3，2004.8 s）：多肢/口型不合

| 项 | 内容 | 结果 | 数字 |
|---|---|---|---|
| V1 | 身份（逐帧中位 / 最低） | 通过 | 顾沉 中位 0.483 最低 0.187 检出 1.0；林晚 中位 0.571 最低 0.261 检出 1.0 |
| V2 | 脸颊泛红 | 通过 | cheek_red_max 0.064 |
| V3 | J4 抖动 | 通过 | J4 1.158（z 2.56） |
| V4 | 动作量 / 静止 | 通过 | mean 1.883，静止占比 0.052，头 / 尾定住 0.0/0.0 s |
| V5 | 镜内硬切 | 通过 | HSV 切点 []，跳切 [] |
| V6 | 多肢 / 手指 | 通过 | extra_hand_frac 0.0；dup_side_frac 0.0；flicker 7；bad_finger_frac 0.163 |
| V7 | 口型 | 不通过 | 嘴部开合与声音相关 0.29 < 0.3 |
| V8 | 与首帧 / 造型一致（景别） | 通过 | 要求 中近景，实测 中景（脸高 0.132，K-REN-122）；造型未测 |

印样 `data/pipeline/runs/series10_v1/video/_thumbs/ep01-S6__s3.jpg`；预览 `data/pipeline/runs/series10_v1/video/_preview/ep01-S6__s3.mp4`

## ep01-S7 · 预览·V6/V7 已测（阈值只用负例标定） · 入选 v1 · 共出 1 版

- v1（i2va_pdd2，seed 2297360167，gpu33:1，589.8 s）：通过

| 项 | 内容 | 结果 | 数字 |
|---|---|---|---|
| V1 | 身份（逐帧中位 / 最低） | 通过 | 林晚 中位 0.511 最低 0.116 检出 1.0 |
| V2 | 脸颊泛红 | 通过 | cheek_red_max 0.055 |
| V3 | J4 抖动 | 通过 | J4 1.122（z 0.18） |
| V4 | 动作量 / 静止 | 通过 | mean 1.738，静止占比 0.016，头 / 尾定住 0.0/0.0 s |
| V5 | 镜内硬切 | 通过 | HSV 切点 []，跳切 [] |
| V6 | 多肢 / 手指 | 通过 | extra_hand_frac 0.0；dup_side_frac 0.0；flicker 0；bad_finger_frac 0.016 |
| V7 | 口型 | 通过 | mode closed；corr None；open_frac 0.0；seen 1.0 |
| V8 | 与首帧 / 造型一致（景别） | 通过 | 要求 中景，实测 近景/中近景（脸高 0.173，K-REN-122）；造型未测 |

印样 `data/pipeline/runs/series10_v1/video/_thumbs/ep01-S7__v1.jpg`；预览 `data/pipeline/runs/series10_v1/video/_preview/ep01-S7__v1.mp4`

