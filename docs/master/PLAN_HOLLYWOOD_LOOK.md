# PLAN_HOLLYWOOD_LOOK — 画面从“炸”到好莱坞（PS-MASTER，2026-11-04 17:xx JST）

项目方 11-04 原话：“画面还是很炸，完全达不到 Hollywood 的要求……review 一下我们的 KPI，然后 iterate 整个 flow。”

## 0. KPI 对照（PLAN_V2_MASTER §1.3）
| 指标 | 目标 | ep01 现状 |
|---|---|---|
| 好莱坞质感分（本地 VLM 1–10） | 建立基线 → +0.5/集 → 终局 ≥ 8.5 | **未测**（hollywood_tick 只给资产 / 金样打分，从不打正片首帧） |
| 出图一次通过率 | ep02 ≥ 60% | 23.5%（51 张出 12 张过） |
| 自动化比例 | ep02 ≥ 60% | 52% |
| GPU 占用 | ≥ 40% | 0（未接上） |
| 整集时长 | 60–120 s（L-092） | 45 s → L-186 加到 16 镜，待出 |

结论：系统一直在优化“能不能过闸”，没有任何一道闸在量“好不好看”。画面质量 KPI 必须先有数，再迭代。

## 1. “炸”的诊断（PS-MASTER 亲看 ep01 成片 6 帧 + S4 原图 / 后期对比）
1. 光：白幕高调平光，无主光方向、无明暗过渡，背景大面积死白（高光溢出）——电商目录感。
2. 景深：提示词写死 “one continuous depth of field” → 全画面一样清楚，没有浅景深层次。
3. 对比 / 锐度三重叠加：提示词“高反差 + crisp sharpness + fine micro-contrast” + 后期 USM（radius 1.2 / amount 0.6）→ 发丝白边（边缘能量 +22%）。
4. 调色缺失：提示词写 ARRI / Kodak，画面实际是中性白灰；grade.py 的参考图还是 V1 粉冰蓝（L-126 应切）。
5. 构图 / 表演：正面居中全身站桩，像摆拍。
6. 皮肤：瓷娃娃 AI 美颜感（身份脸由项目方定，不改脸，只改光与质感）。

## 2. 迭代（一轮一假设；改生产配置前一律开关默认关，由项目方看对比页定）
- **H0 量起来**：hollywood_tick 加正片首帧（active takes）；评分表加 exposure（高光溢出 / 死黑）、depth（景深层次）、grade（调色统一 / 胶片感）、ai_look（AI 美颜 / 塑料感，反向）；加确定性指标（高光裁切占比、背景/主体清晰度比、边缘光晕）。出 ep01 基线。
- **H1 画风 A/B**（3 镜代表：S1 三人中景、S4 双人、S13 近景；同种子）：
  - A 现状；
  - B 提示词 look v2：去“高反差 / crisp / micro-contrast / one continuous DOF / 纪实快照”；加有动机的电影光（环形灯作实景主光、负补光、高光柔和滚落、背景低 1–2 档）、50/85mm f/2 浅景深、ARRI 柔反差、Kodak 2383 印片色、保留皮肤纹理；保留“Leica 镜头质感”（L-145 项目方要的锐利 = 光学锐利，不是数字锐化）；
  - C = B + 后期：关 USM，改胶片仿真调色（柔 S 曲线、高光滚落、黑位微抬、冷暖分离）；
  - D = C + 场景光：白幕改为现实段“顶光 + 暗场”的低调影棚（只改灯光模板，不改剧情）。
  - 打分：H0 新评分 + 确定性指标；出对比页 data/review_pages/look_v2/index.html，只给过契约的图。
- **H2 项目方选型** → 选中的做成配置（编译后缀 / 灯光模板 / 后期链），走 cut；ep01 按新画风重出（换代：新版本过闸后替换，旧版保留）。
- **H3 闸门**：好莱坞分进 postflight（先只记录，校准后再设门槛）；每集 RETRO 写分数对比。
- **H4 视频阶段**：同口径看 Pika 输出 + 超分 + _sg 锐化是否再“炸”（抽帧打分），必要时同样 A/B。

## 3. 并行与约束
- ep01 出图（S9 尾帧、S12–16）照常跑完，用于把 16 镜整条链跑通；画风定了再整集换代。
- ep02+ 出图暂不铺开（避免用旧画风烧 GPU）；写作 / 资产线照常。
- A/B 只借空闲道（gpu36 / gpu33 空闲卡，走借道记录），不碰 gpu33:2 / gpu36:2，不挤占 ep01 生产。

## 3. H1 结果（11-04 18:5x，Fable 出图 12 张 + PS-MASTER 亲看 A vs C）
- 对比页：data/review_pages/look_v2/index.html（3 镜 × A/B/C/D，只放过契约的图）。
- 结论：
  1. **C（关 USM + 胶片调色）是明确改善但幅度有限**：白边 −25~30%、皮肤哑光有纹理、印片暖调黑位有底；白幕平光与正面站桩没变。
  2. **提示词尾部风格句几乎无效**（B≈A）：2–3k 字编译提示词里【场景】块（“环形灯正面高亮，白幕反光把影子打平”——来自写作阶段的本集场景表）+ 场景底图 sk_white_cyc（本身全白高调）压过了风格句。D 只改两句灯光也压不下白幕。
  3. **漏洞**：reality_c2 的 post_lut 在出图链上从未被任何代码应用（只有 tools/v2style 实验用）→“几乎没调色”的直接原因。
  4. 看图模型好莱坞分 7.9–8.7 不区分档位 → 需成对比较 / 校准；clip_hi≥250 抓不到白幕（实测 235–245）→ 加背景亮度指标。
  5. Q9 判词里出现 V1 名字（“顾沉长发、林晚发色”）→ Q9 规则文本残留 V1 例句，待清。
- 下一步：
  - **H2a（后期，零 GPU，可对已出的图立即生效）**：后期链改为 C：关 USM、胶片调色（或修好 post_lut 真正应用），做成配置开关默认关；项目方点“用 C”后打开，并对 ep01 现有首帧重新后期（原图都保留）。
  - **H2b（源头光线，要 A/B）**：①写作规则：场景表“光线”列禁止“正面高亮 / 把影子打平”类平光描述，改写有动机的主光 + 光比 + 背景压暗；②场景底图 sk_white_cyc 重出低调影棚版（项目方挑）；③镜头语言：shot_spec 减少正面居中全身，加侧 45° / 过肩 / 中近景、浅景深。三项各做 A/B，项目方看图定。
  - **H2c（表演）**：分镜表演节拍写“交流对象 + 动作中途”，避免站桩（PERFORMANCE_RULES 已有，查为什么没生效）。

## 4. H2b 结果（11-04 19:4x，Fable 出图 9 张 + 底图 2 张；PS-MASTER 亲看 S4 A/E/F/G）
- 源头光线有效：E（改【场景】块与灯光段的光线句）让白幕出现渐变 / vignette；F（E + 低调影棚底图 seed 1102）把背景亮度压 0.07–0.10（S4 .597→.50），棚顶 / 纵深出现，是 5 档里最接近电影剧照的。
- G（镜头语言词）无效：同种子 + 场景块把构图锁死；S4 还把剧本里关着的环形灯画亮（剧情违背）。
- **看图模型成对比较有位置偏置**：9 对全选“图 2”，交换顺序照样选图 2 → 当前问法不能当裁判。
- 共同残留：正面一字排开站桩；白幕仍亮（.50–.54，目标 ≈.40）。

## 5. H3（下一轮）
- H3a 底图：用 PLATE_LIGHT_DARKER（更暗一档）再出 2 张 sk_white_cyc 低调版，连同 1102 交项目方挑（资产候选，项目方挑后才登记 manifest）。
- H3b 站位 / 构图从源头改：A/B 改分镜字段（机位与景别、站位、构图），不是提示词尾句；S1 三人错落 + 前景人物、S4 过肩中近景；换种子 2–3 个；景别契约 Q3 同步。若有效 → 写作规则（P4 镜头语言：同场连续镜头不许都正面平视全身；双人以上必须有前后层次）。
- H3c 裁判：好莱坞评审改为“两图拼成一张、左右各问一次、两次一致才算”，并加背景亮度 / 主体背景亮度比；用 H1/H2b 的 15 张 + 项目方选择做校准集。
- 生产采纳（需项目方点选）：后期 C（H2a 开关）+ 光线 E + 底图（项目方挑）→ ep01 换代重出；采纳前不动生产。

## 6. P4 镜头语言规则草稿（Fable，11-04 H3b 验证后写；草稿，待项目方采纳 L1 后进写作规则）
1. 同一场连续镜头里不许连续两镜都是“正面 / 侧面平视 + 全身或中景一字排开”：至少一镜要换机位（侧 45° / 过肩 / 俯仰）或换景别（中近景 / 近景）。
2. 两人以上在画必须写前 / 中 / 后三层——【构图】写“前景=谁的什么部位略在焦外｜中景=谁在焦点上｜背景=谁或什么陈设”，cast 的 depth（前 / 中 / 后）必须与之一致；在焦点上的主体脸高不得低于本镜景别档位的下限（H3b S1 实测：错落写过头会把中景拍成中全景，Q1 小脸不过）。
3. 【灯光】只写有动机的主光（方向 + 光比 ≤ 3:1）+ 负补光 + 背景比人物低 1–2 档；场景表与分镜里禁止“正面高亮 / 把影子打平 / 白幕反射补脸”这类平光句（H2b E 档实测：改源头光线句有效，尾句无效）。

## 7. H3c 结论：本地看图模型不能当“好莱坞感”裁判（11-04 20:0x，Sonnet）
- 拼图双向问法 30 对 60 问全答“右”（位置偏置），不确定 100%；三问法同样偏置，只有“背景哪张更暗”能答一致（等于读亮度）。
- 确定性指标 bg_lum 与 PS-MASTER 亲看排序一致 11/15（73%）。
- 工具：tools/pipeline/look_judge.py（compare / deterministic / calibrate）；look_metrics 加 bg_lum、subj_lum、subj_bg_ratio。
- **KPI 定义需改（待项目方定）**：PLAN_V2_MASTER §1.3 的“好莱坞质感分（本地 VLM 1–10）”在现模型下不可测。PS-MASTER 建议：
  1. 好莱坞 KPI = 确定性“画面指数”（bg_lum↓、subj_bg_ratio↑、dof_ratio↑、halo↓，相对 ep01 基线的改善）+ 每集项目方 / 总调度亲看抽检（只看过闸的图，L-123 两个动作）；
  2. 模型只做单图缺陷（Q9），不做审美；
  3. Spark（128 GB 统一内存）到位后试更大的本地看图模型（如 72B 级 VL）重做 H3c 校准，过 70% 一致再恢复模型审美分。

## 8. H4 镜头感与虚化（Fable，11-05；项目方：“镜头感很差，镜头的虚化感也没有……看看 ARRI / 徕卡是怎么做的，重新做一下”）

### 8.1 研究要点（每条：结论 ← 来源 · 原文短引 · 可信度 🟢官方/一手 🟡行业媒体/二手 🔴论坛）
1. **机身 / 画幅**：好莱坞剧集主流 ALEXA Mini LF / Alexa 35；LF 同视角要用 1.5× 长的焦段（75mm LF ≈ 50mm S35），景深随之更浅。← [CVP × ARRI LF 测试](https://www.fdtimes.com/2019/05/08/cvp-large-format-test-with-arri/)“75 ÷ 1.5 = 50mm”🟡；[Deakins 谈 Mini LF](https://ymcinema.com/2019/10/22/large-format-cinematography-roger-deakins-talks-about-the-alexa-mini-lf/)“that sort of depth of field”🟡；Tim Ives ASC（Stranger Things 3）[Leitz 访谈](https://www.leitz-cine.com/article/tim-ives-asc-talks-leitz-thalia-lenses-on-stranger-things-season-three)“feel the fall off so much faster”🟢一手；Dan Laustsen ASC [“The depth of field is so small”](https://theasc.com/articles/arri-large-format) 🟢。
2. **焦段 / T 值**：Signature Prime 全组 T1.8（47/58/75/95/125…）🟢 [ARRI 官网](https://www.arri.com/en/cine-lenses/signature-lenses/signature-primes-zooms/signature-primes)；Summilux-C T1.4，Ives 实拍“T2 – T2.8”🟢一手；Thalia 70mm 拍近景（“I love using the 70mm Thalia for a close up”）🟢一手；Mare of Easttown（Mini + Summilux-C）近景多用 40mm，“backgrounds fall off in this really delightful way”🟡 [转载](https://deepfriedmovies.com/2021/06/10/mare-of-easttown-cinematographer-ben-richardson/)；Euphoria 试播集“99% 用 65mm”🟡 [AFC](https://www.afcinema.com/Rebel-without-a-cause.html?lang=en)；Deakins：“40 mm is very comfortable … for a close-up”🟡。→ **本项目取等效 LF：三人中景 58、双人中近景 75、近景 95，T2**。
3. **徕卡焦外 / 焦平面**：Summilux-C“Very high contrast / Extremely high resolution / No breathing”🟢 [数据表](https://www.afcinema.com/afcinema_com/IMG/pdf/7/2/7/2017.01.french.-summilux-c-data-sheet-.pdf)；“rich blacks … no hazy internal barrel flare”🟡 [FDTimes](https://www.fdtimes.com/2011/02/25/leica-summilux-c-in-ny/)；Leitz 官网“skin tones … gentle, creamy softness”“telecentric … almost no distortion”🟢 [Summilux-C](https://www.leitz-cine.com/product/summilux-c)；Thalia“bokeh smooth … through all stops”“Out-of-focus elements maintain their structure … dimensionality”“gradual focus fall off curve”🟢 [Thalia](https://www.leitz-cine.com/product/thalia)。“3D pop / 微反差”只有论坛说法 🔴（[l-camera-forum](https://www.l-camera-forum.com/topic/293758-the-leica-look-is-real/page/12)）→ 实现只做“焦平面原样 + 焦外顺滑过渡”，微反差做成可选项默认 0。
4. **ARRI 肤色 / 高光**：Signature Prime“Warm, smooth skin”“open shadows with crisp blacks”“bokeh like looking through a window in the rain”🟢 ARRI 官网；Alexa 35“naturalistic, film-like highlight roll-off”“17 stops”🟢 [ARRI](https://www.arri.com/en/camera-systems/cameras/alexa-35)。→ 高光滚落已在 film_look（knee），lens_sim 不重复。
5. **光斑形状**：球面 = 圆（Signature 11 片光圈“smooth, round bokeh”🟡 [零售转述](https://hotrodcameras.com/products/arri-signature-prime-125mm-t1-8-lens-feet)）；变形 = 竖椭圆 + 横向（常偏蓝）光晕，“caused by bright light hitting the cylinder … front of the lens”🟡 [DIYPhotography](https://www.diyphotography.net/this-is-why-anamorphic-lenses-have-oval-bokeh-its-nothing-to-do-with-the-aperture/)、[NoFilmSchool](https://nofilmschool.com/anamorphic-bokeh-balls)。
6. **实景光源 + 雾**：雾“creates depth separation between foreground, mid-ground, and background”，光源须在雾后方才显 🟡 [RedShark](https://redsharknews.com/how-smoke-can-make-your-shots-look-magical)；Neil Oseman“foreground is darker than the background, helping the eye to distinguish … layers”，边光“ostensibly from the wall sconces”🟡 [Depth Cues](https://neiloseman.com/?p=4107)。→ 白幕空场没有可虚化的东西：**虚化感 = 先要有背景实景光源 / 陈设 / 雾（D 档提示词），再谈光学**。
7. **Halation**：底片背面反射回曝，“the halo appears primarily reddish”、带绿则“orange to a warm golden yellow”、“hardly become bluish”，“should only be used very subtly”🟡 [Digital Production](https://digitalproduction.com/2024/01/30/halation-and-diffusion-on-the-hunt-for-the-ultimate-film-look/)；Vision3 remjet 2025 换 AHU 🟡 [Kosmo Foto](https://kosmofoto.com/2025/06/eastman-kodak-replacing-remjet-layer-from-vision3-cinema-films/)。→ 只在亮区边缘外侧加暖红晕，gain 0.10。
8. **物理校核**（CoC = f²/N · (d−s)/(d(s−f))，LF 36.7 mm 宽 → 768 px）：三人中景 50mm T2、人 3 m、白幕再 2 m → 模糊直径 ≈ 3.5 px（几乎看不出）；近景 95mm T2、人 2 m、幕 3 m → ≈ 30 px。**提示词写 50mm f/2 本来就不该有明显虚化；要虚化感得用 75–95mm 等效 + 背景有东西。**

### 8.2 lens_sim（services/render_router/ns_render/lens_sim.py，`lens_sim/v1`，开关默认关）
- 深度：Depth Anything V2 Small（HF 格式，models_cache/depth_anything_v2_small/，99 MB；本机原有 partial_copy 只有 82/99 MB 不完整，按 HF 规则在 gpu33 用 hf-dl 下载后 scp 拷回，sha256 3152477c…；CPU 推理首张 9 s / 之后 0.8 s，逐次输出逐位相同）→ 以灰度为引导的导向滤波细化（发丝边缘贴图像）。
- 焦点：YuNet 找脸，取“面积 × 居中度”最高的脸；焦点带 = 眼睛区视差 20–80 分位 ± 0.05（整张脸在景深内）；没脸 → 中心；可指定 [x,y]。
- 虚化：半径 = coc_px/2 × (f/50)² × (2/T) × |视差 − 焦点带|（前景 ×0.8），上限 28 px；15 档带符号半径分层，每层 disk 核归一化卷积（只用本层像素 → 前景不渗进背景、背景不渗进脸），远→焦平面→近 over 合成后按覆盖率归一；焦平面像素原样写回。
- 圆斑：线性光里把“白顶帽”小亮点（灯、反光；大面积白幕 = 0，人物暗边旁的白幕也不误判）抬 1.8× 再散焦 → 圆斑；anamorphic=2 → 竖椭圆（面积不变）+ 横向偏蓝光晕（同样只认小亮点）。
- 镜头特征：暗角 0.10（r^2.4）、横向色散 ±0.0006（角落 ≈0.5 px）、halation：亮区边缘外侧暖红 (1, .36, .12)×0.10、σ=1.2% 短边。
- 顺序：缩回 → **lens_sim** → film_look（散焦 / 光晕是镜头与底片上的事，印片曲线和颗粒在后；颗粒先加会被抹掉、高光先滚落则圆斑没能量）。
- 单测 tests/test_lens_sim_h4.py（7 项：关闭逐字节不变、焦平面像素不变、远处更模糊、确定性、光圈越大越虚、圆斑能量、椭圆核）。

### 8.3 H4 A/B（页：data/review_pages/look_v2/index.html 顶部“H4 镜头感”；数据 data/ab/look_v2/h4/h4.json；工具 tools/research/lens_sim_ab.py）
| 镜 | 档 | 脸/背景清晰度比 fbg | dof_ratio | halo | bg_lum | clip_hi | 亲看（Fable） |
|---|---|---|---|---|---|---|---|
| S1 三人 | A | 1.31 | 1.25 | 22.2 | .458 | .0002 | 三人一样清楚，白幕平 |
| S1 | B 球面 58mm T2 | **3.41** | 2.23 | 11.4 | .447 | .005 | 祁念锐、卓琳 / 唐瑶柔、棚灯成圆斑；最自然 |
| S1 | C 变形 | 3.16 | 2.12 | 14.5 | .448 | .018 | 同 B + 棚灯竖椭圆 + 淡横晕；差别小 |
| S1 | D0 同种子重出 | — | 1.79 | — | .501 | — | 没过契约（Q1 小脸）— 不进页 |
| S4 双人 | A | 1.61 | 3.14 | 24.6 | .446 | .0001 | 两人都清楚 |
| S4 | B 75mm T2 | **3.80** | 1.61 | 12.7 | .434 | .006 | 卓琳（焦点）锐、祁念柔、灯架虚；第一版有白幕“光晕”bug（亮点检测误判人物暗边）已改白顶帽后消失 |
| S4 | C | 3.81 | 1.61 | 9.1 | .436 | .012 | 同 B |
| S4 | D0 | — | 2.31 | — | .483 | — | 过契约（对照，无实景光源句） |
| S13 近景 | A | 1.68 | 1.38 | 17.4 | .475 | 0 | 风扇 / 椅子清楚 |
| S13 | B 95mm T2 | **2.18** | 1.41 | 13.3 | .462 | .004 | 脸 / 发丝锐利无白边，风扇椅子化成柔和光斑，白幕更顺 |
| S13 | C | 2.21 | 1.46 | 13.4 | .462 | .006 | 棚灯竖椭圆 + 淡蓝横晕 |
| S13 | D0 | — | 1.46 | — | .476 | — | 过契约（对照） |

- dof_ratio（中心 40% / 四周）在 S4 反而降（卓琳在中心区被散焦算进去），**fbg（脸框 / 背景圈）才与亲看一致**：B 把三镜的脸/背景清晰度比抬到 2.2–3.8×（A 1.3–1.7），halo 全降（11–13 vs 17–25），bg_lum 不变或略降，clip_hi ≤ 0.6%。
- **视频保留虚化**：B 档 S13 首帧 → h3_fl2va 158 帧（gpu33:0，691 s，scope=ab，data/ab/look_v2/h4/video/）：抽帧 dof 1.40 → 1.74 → 1.87 → 2.25（相机微推近，背景风扇 / 椅子一直是光斑，脸一直锐），Pika 没有把背景“修回”清楚。
- **D（提示词加实景光源 / 雾 / 大画幅）没拿到结果**：第一轮锚点没中（当前编译后缀已是 look v2，“保留真实皮肤纹理与毛孔”不在提示词里）→ 与 D0 同图；修好锚点（接在“镜头：…”行尾 + Kodak 句后，dry-run 已验 5 处替换）后的第二轮 GPU 作业被本机内存保护中止，未重跑。D0 对照说明同种子重出（当前剧本写法）本身 dof 不变（S13 1.46 vs A 1.38）。

### 8.4 结论与建议
1. **推荐 B（球面，等效 LF 58/75/95mm T2）**：三镜都明显出现“焦平面锐、焦外顺滑、棚灯成圆斑”，不动身份 / 造型，不加数字锐化；C 的变形特征在白幕场几乎看不出，不建议默认开（可留作幻想段 / 片头风格开关）。
2. **白幕空场的上限**：焦外只有白幕和几件陈设，虚化感有限（研究 §8.1-6）；要“好莱坞感”还得在源头给背景实景光源 / 陈设 / 雾（D 档，待重跑）——那是写作 / 场景表的事，不是后期能补的。
3. 双人镜（S4）只有说话人在焦点，另一人柔——这是电影做法，但若项目方要“两人都清楚”，lens_sim 可加 focus=all_faces（焦点带覆盖所有脸），一行参数。
4. **做成生产开关需要的改动（都默认关，项目方点“用 B”后再开）**：
   - config/render_quality.json 加 `post_lens: {enabled: false, focal_by_size: {近景: 95, 中近景: 75, 中景: 58, 全景: 47}, t_stop: 2.0, anamorphic: 0, …}`；
   - services/render_router/ns_render/image_params.post_file：缩回之后、USM / film 之前插 `lens_sim.apply`（enabled=false 时逐字节不变），焦段按 asset_refs.size 景别档取；take.params.post 记 lens 记录（version / focus / radius / depth_sha16）；深度 .npy 存在 take 旁便于 replay；
   - 焦点主体：从 cast 的 focus=True 成员定位脸（现用“面积 × 居中度”，改成 SFace 对身份脸匹配 cast.focus 的角色）；
   - tools/pipeline/repost.py 支持重后期已出首帧（L-188 同一条路）；
   - 视频阶段：首帧已带虚化即可（本轮视频试验证明 Pika 保留），不在视频后再做；超分 / _sg 锐化要对焦外加保护（按深度 .npy 的焦外掩码不锐化），否则会把光斑锐回去；
   - 依赖：models_cache/depth_anything_v2_small/（99 MB，已到位，服务器上用 hf-dl 同一个 repo depth-anything/Depth-Anything-V2-Small-hf）；transformers + torch-CPU 已在 .venv；每张 ~5 s CPU。

## 9. L2 镜头语言研究（Fable，11-05；项目方原话“取景 angle 缺一致性……像手机拍的，也没有任何运镜”）
来源经 WebFetch 读到页面原文（置信 高）；每条 ≤15 词原文短引。落成规则 K-WRT-810–815（knowledge/rules/writer_camera.yaml），代码判定 rubric_code.l2_checks（QW-L3–L8）。

| # | 要点 | 原文短引 | 来源 |
|---|---|---|---|
| 1 | coverage：先最宽的主镜头（全员入画），再逐步推近到过肩、单人；主镜头是 coverage 的地基 | "start with the widest shots, then progressively move closer" / "the foundation of what is called camera coverage" | studiobinder.com/blog/film-coverage；en.wikipedia.org/wiki/Master_shot |
| 1 | 过肩镜与正反打配套 | "used in tandem with 'shot reverse shot'" | studiobinder.com/blog/film-coverage |
| 2 | 180° 轴线：两人之间一条假想线，机位跳过去 = 越轴；越轴只用中性镜（轴重置）或一镜内机位可见地跨过去 | "When the camera jumps over the invisible axis, this is known as crossing the line" / "your line resets" | studiobinder.com/blog/what-is-the-180-degree-rule/ |
| 2 | 正反打本身是视线匹配 | "It is an example of an eyeline match." | en.wikipedia.org/wiki/Shot_reverse_shot |
| 3 | 正反打成对镜头同焦段、同离轴角 | "we use the same lens, in millimeters, in both shots." | newsletters.animationmentor.com/newsletter/0206/feature_film.html |
| 3 | 85mm 面部压缩讨喜（特写 / 情绪）；35mm 带环境又能拍特写，可整片单焦段（Call Me By Your Name） | "flattering compression of facial features" / "captures more of the background than a 50mm" | wolfcrow.com（most-used-focal-lengths）；nofilmschool.com/most-popular-focal-lengths-in-film |
| 4 | 运镜必须有动机，不必花哨 | "it just has to be motivated." | nofilmschool.com/2018/06/key-good-camera-movement-motivation |
| 4 | push-in = 紧张 / 情绪推高；跟拍 = 跟随移动主体；arc 给静态场面加动感；crane / boom 揭示；手持 = 纪录片感 / 混乱 / 亲密 | "Pushing in can help indicate growing tension" / "mimics a documentary style" | studiobinder.com/camera-shots/camera-movements/push-in-shot/；studiobinder.com/blog/different-types-of-camera-movements-in-film |
| 5 | cut on action 掩盖剪辑点；J / L cut 让对白节奏自然、可停在听者反应；L cut 打破正反打单调 | "helps hide edits that occur during an action" / "a more natural rhythm to a conversation" / "breaks up the monotony of a shot-reverse shot" | nofilmschool.com（cuts-101）；studiobinder.com/blog/what-is-an-l-cut-in-film/；premiumbeat.com（9-essential-video-editing-cuts） |
| 6 | 竖屏：人物填满画面、眼睛落在上方三分线交点；加前景做纵深；下部被字幕 / 界面挡，关键信息放上方；横向摇移易晕 → 运镜优先推进 | "allow their eye to fall near one of the top intersection points" / "Even one object in the foreground can completely change…" / "Pans or rapid action moving across the frame can be discombobulating" | social.colostate.edu（vertical-video-and-using-composition-rules）；omgadrian.beehiiv.com（master-vertical-video-framing）；adamsebire.info（9-16-tips-and-tricks） |
| 7 | 时尚片运镜：Bolt 机械臂 + Phantom（GlamBOT 1 秒 1000 帧再慢放），机械运动精确可重复、按服装预先设计；极慢动作让衣料动态成主角 | "We shoot 1,000 frames in that one second." / "a precise (and repeatable) movement" / "Even the robot movements are decided in advance" | en.wikipedia.org/wiki/GlamBOT；fstoppers.com（high-speed-camera-and-high-speed-robot）；numeronetherlands.com（Corentin Huard）；anothermag.com（km3d-1） |

没找到可信原文（不写进规则）：“对白场必须统一焦段”只有 Animation Mentor 一处实践说明；crane“抽离收尾”、arc“对峙 / 转变”只有第三方视频摘要；“主体上三分之一”只来自博客；Vogue 官方“推近急停”幕后无原句。

**对本项目的落点（V2 / Pika 可执行边界，config/director/camera_moves.yaml exec_modes）**：Pika 只按提示词执行 推近（1.0）/ 固定（1.0）；横移 0.10、俯仰 0.0、环绕 0.64 不受控 → 这些词不写；V2 按剧放开 bolt_push_settle（幻想段，3/3）与 handheld_follow（走动镜，2/2）。所以 L2 的“动机运镜”在本阶段 = 推近（起落幅 + 动机）、bolt（幻想段登场）、手持跟拍（走动）、固定 ≤20%（写理由）；横移 / 弧形 / 升降 等 camctl A/B 通过后再进词表。
