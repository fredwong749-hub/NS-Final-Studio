# ep02 迭代：已确认规格（LEARNED_SPECS）

每轮审片后更新。只收**有证据的**结论；状态分三种：
- **确认**：可以硬编码
- **建议**：证据够，但需要总调度改 config 或由开发落地
- **待验**：要做 A/B

审片工具：`tools/ep02_director/review.py`；评分标准：`tools/ep02_director/rubric.md`；每轮报告：`docs/ep02_iter/vN_*.md`。

## A. 审片度量（工具常量，在 review.py 顶部）

| 参数 | 值 | 来源证据 | 日期 | 状态 |
|---|---|---|---|---|
| 静止帧判定 | 96×168 灰度相邻帧差 <0.35 | qc_ep02 / static_fix 同值；与人工"不动"判断一致（docs/QC_ep02_20261031.md） | 2026-10-31 | 确认 |
| 4 帧一顿判定 | J4 ≥1.2 且 z ≥3（tools/motion_judder.py） | MOT：VAE 往返 J4 1.003，现行 Turbo 1.34（z 3.6） | 2026-10-31 | 确认 |
| 林晚识别 | 浅蓝发得分 = 头顶带 + 两侧带蓝色像素（H85–125、S≥60、V≥40）≥0.35 且全帧最高 | S2_C/S1/S5/S7 实测：林晚 0.55–1.5，其他人 0–0.2。旧规则 S≥30 不加 V 时，蓝光下的黑发也有 0.3，会误判 | 2026-10-31 | 确认 |
| 脸颊区 | 脸框宽 10–90%、高 50–80% | 泛红集中在脸颊（S2_C 印样） | 2026-10-31 | 确认 |
| 泛红指标 | 脸颊 LAB a* 的 p95；脸颊 a*≥25 像素占比 | 正常皮肤 a*p95 15–20、占比 0–10%；Pika S2_C 泛红 44 / 52% | 2026-10-31 | 确认 |
| 泛红闸门 | 脸颊 a*≥25 占比 ≥25% → 标记；a*p95 相对开头 0.5 s 漂移 ≥6 警告、≥12 严重 | v0 全片 + Pika 11 条分布 | 2026-10-31 | 确认（工具），作为出片闸门待总调度定 |
| 人物闸门 | SFace 余弦中位 ≥0.30 | packages/qc/ns_qc/thresholds.py Q-D1（锁定） | 2026-10-29 | 确认 |
| 接触印样末帧 | 取 dur − 1.5 帧 | 成片里取 start+dur−0.5 帧会拿到下一镜第一帧（v0 第一版印样踩过） | 2026-10-31 | 确认 |
| 近黑画面 | 96×168 灰度均值 <12，连续 ≥1 s 标记 | v0 S11 中段 1.83 s | 2026-10-31 | 确认 |
| 未标记视频的解码矩阵 | 按 bt709（播放器对高清的默认） | 与观众看到的一致 | 2026-10-31 | 确认 |

## B. 生成 / 后期规格

| 参数 | 值 | 来源证据 | 日期 | 状态 |
|---|---|---|---|---|
| 视频默认配方 | official_base 24 步 + 只给首帧 | config/render_quality.json default_decision；静止镜头 7/11 → 2/11（v0_base24_takes：只剩 S6 80%、S10 82%） | 2026-10-31 | 确认（config 已改，成片还没换） |
| 对白来源 | h3（保留 H3 原声） | H3 版嘴部 0 偏移相关 0.19–0.70；TTS 版 −0.17～+0.28，偏差约 2.5 s（data/ab/director/v0_preview*/review.md 声画表） | 2026-10-31 | 确认（config 默认已是 h3） |
| 后期去抖 | 所有 H3 输出过 tools/dejudder.py | J4 1.34–1.52 → 1.08–1.09（S1 Turbo / Pika） | 2026-10-31 | 建议（默认开） |
| dejudder 色彩 | 编码必须 bt709 矩阵并带 bt709 标记 | 现状输出 BT.601、无标记；被当 709 播放时脸颊 a*p95 −1.7（red_trace/S2_C_pika_chain） | 2026-10-31 | 建议（待改 tools/dejudder.py） |
| 成片分段色彩 | `_vf` 显式 out_color_matrix=bt709，加 -colorspace/-color_primaries/-color_trc bt709 | dejudder 段进 assemble 后被标 bt470bg，与 bt709 段 -c copy 混在一条流里 | 2026-10-31 | 建议 |
| 后期是否加红 | 不加：去抖、校色、成片编码前后脸颊 a*p95 变化都在 ±2 以内 | red_trace/S2_C_pika_chain | 2026-10-31 | 确认 |
| Pika Flex 参数 | lcm、ManualSigmas 7 值（6 步）、shift 12/3 已算进 sigma 表、CFG 1.0 BasicGuider、LoRA 1.0 | workflow_flex.json；官方模板要求固定 | 2026-10-31 | 确认（负面提示对 Pika 无效） |
| Pika 用在哪些镜 | 提示词含 flush/blush 描述的镜头不用 Pika | 同首帧同提示词：Pika 脸颊 a*p95 最大 43.9 / 43.2，Turbo 38.0 / 36.3，基模 37.0 / 32.5（S2 / S4） | 2026-10-31 | 建议 |
| 关键帧 krea2 胶片质感 LoRA | 0.5 → 0.25（有脸的近景/特写） | leica_sharp S4：C0 39.7 vs C2（去 krea2）29.7；texture A 34.2 vs C 39.7 | 2026-10-31 | 待验（A/B：质感不能丢） |
| USM 1.2/60/2 | 对泛红影响可忽略（+0.06～+0.8） | leica_sharp C0→C5、image_006→_post | 2026-10-31 | 确认 |
| 暖调风格后缀 | 对泛红影响可忽略（±0.5） | leica_sharp S1–S5 | 2026-10-31 | 确认 |
| 脸部 a* 限幅（skin guard） | 林晚脸框外扩 25%、羽化；a* 超过 首帧脸颊 p95+6 的部分保留 25%；排除嘴唇 | 原型 S2_C：a*p95 中位 40.2→27.7，肉眼看圆斑消失（red_trace/S2_C_skin_guard_proto/worst.jpg） | 2026-10-31 | 待验（要先加嘴唇排除再审） |

## C. 剪辑规格（短剧观感，只限剪辑）

| 参数 | 值 | 来源证据 | 日期 | 状态 |
|---|---|---|---|---|
| 平均每刀 | ≤4.5 s（及格 ≤5 s） | v0 平均 7.81 s，8/10 相邻同景别 → ⑤ 只有 2 分 | 2026-10-31 | 建议 |
| 单镜上限 | 6 s；超过就拆刀（同素材 1.15× 推近） | v0 S8 12.25 s、S11 10.1 s | 2026-10-31 | 建议 |
| 自动剪定住段 | 开头/结尾 帧差 <0.35 连续 ≥0.3 s 剪掉，单镜最少留 1.5 s | v0 10/11 镜结尾定住 0.67–6.5 s | 2026-10-31 | 建议 |
| 开场 | 第一刀 ≤3 s，或前 3 s 内节奏 ≥1 px/帧 | v0 前 3 s 无切点，首句在 8.3 / 10.8 s | 2026-10-31 | 建议 |
| 切点音频 | 100 ms 窗口跳变 ≤10 dB；不允许低于 −60 dBFS 的数字静音；edge_fade_s 0.05→0.12 | v0：S5→S6 −18、S7→S8 −15、S10→S11 −53 dB（−86 dBFS） | 2026-10-31 | 建议 |
| 独白溢出 | 溢出镜头直接判不通过（现在只是 warning） | S8 独白盖住 S9–S11 | 2026-10-31 | 建议 |
| 整集响度 | −14 LUFS ±1，TP ≤−1 dBTP | v0 两版 −14.0 / −14.2、TP −1.4 / −1.3，合格 | 2026-10-31 | 确认 |

## D. 已硬编码进系统（FIX，2026-10-31）

上面 B / C 里标“建议 / 待验”的项，下列已经落进代码和 `config/render_quality.json`（每个新键旁有 `learned_from`）。生效条件：编译 / 出片相关的要等 API :8800 重启；合成（`tools/assemble_episode.py`）下次运行即生效。测试：`tests/test_fix_ep02_p0.py`、`tests/test_fix_ep02_assemble.py`。

| 参数 | 值 | 证据 | 落在哪 | 日期 | 状态 |
|---|---|---|---|---|---|
| 成片取哪一版 | 只用“已定稿 + qc.motion 不是 fail + 不是坏图”的 take；没有就标缺（timeline `gates.missing_shots`），只出预览 | chain_audit D6：S1/S5/S7/S8/S11 未定稿、S3 用 #5（定稿 #4），6 个运动 fail 进了成片 | `post.edit_rules.take_policy = locked_qc`；`ns_post.assemble.qualified_take` | 2026-10-31 | 确认 |
| 自动剪定住段 | 帧差 <0.35 连续 ≥0.3 s 剪，单镜至少留 1.5 s | 同 C 表 | `post.edit_rules.trim_frozen / freeze_still_diff / freeze_min_s / min_keep_s` | 2026-10-31 | 确认 |
| 长镜拆刀 | >6 s 拆刀（每刀 ≥2 s），偶数刀同素材 1.15× 推近，切点避开对白句 | v0 S8 12.25 s、S11 10.1 s | `post.edit_rules.max_shot_s / split_zoom / split_min_piece_s` | 2026-10-31 | 确认 |
| 切点交叉淡化 | 0.12 s，H3 轨前后各多读半个淡化长度、互补斜坡重叠 | C 表“切点音频” | `Settings.edge_fade_s = 0.12` | 2026-10-31 | 确认 |
| 环境底噪 | 响度归一后，100 ms 窗口 RMS 低于 −50 dBFS 的地方补粉红底噪到 −50（窗口间线性插值） | v0 S10→S11 −86 dBFS | `post.edit_rules.room_tone*`；timeline `room_tone` 记前后最小窗口电平 | 2026-10-31 | 确认 |
| 对白 / 独白溢出 | 判不通过（timeline `gates.overflow`），在本镜结尾截断，不挪、不覆盖下一镜 | S8 独白盖住 S9–S11 | `post.edit_rules.overflow_policy = fail` | 2026-10-31 | 确认 |
| 色彩标记 | 成片段、dejudder、skin guard 全部 bt709 矩阵 + `setparams` 写 bt709 primaries/trc/colorspace | R5/R6；FIX 实测：只加 `-color_primaries` 编码参数时 x264 输出仍是 unknown，必须 `setparams` | `assemble._vf / COLOR_TAGS`、`tools/dejudder.py`、`ns_post.skin_guard` | 2026-10-31 | 确认 |
| dejudder 色彩 | 显式 bt709 解码 / 编码后，red_trace 对原片脸颊 a*p95 平均差 +0.28（<0.5）；ffprobe bt709/bt709/bt709 | `red_trace/FIX_dejudder_bt709_S2_C` | `tools/dejudder.py` | 2026-10-31 | 确认 |
| skin guard | 默认开；margin 6、**基准封顶 22**、knee 0.25、外扩 25%、只压 ≥0.5% 脸框面积的 a* 异常连通块、嘴角椭圆（0.75×0.45 嘴角距）排除 | red_trace `FIX_skin_guard_S2_C` / `_S4_C`：S2_C 脸颊 a*p95 中位 40.2→28.7、最大 43.9→29.4；S4_C 40.7→31.8 / 43.2→34.0；base24 S2 34.8→27.3；嘴唇 a* 中位变化 +0.04 / +0.68 / +0.01 / +0.21（<2）；worst.jpg 圆斑消失 | `post.skin_guard`；`ns_post.skin_guard` | 2026-10-31 | 确认（默认开） |
| skin guard 未达 DIR 验收线 | “最大 ≤ 关键帧 +8”：S2_C 29.4 vs 17.2+8=25.2，未达；脸颊 a*≥25 像素占比基本不降（压的是峰值不是面积） | 同上 | knee 再降会更平；要不要压到 0.15 交 DIR 看印样定 | 2026-10-31 | 待验 |
| 系统后缀条件化 | 原文遮脸 → 后缀去掉含“面部 / 五官”的子句；原文全黑 → 去掉“非纯黑 / 面部可辨”；编译后静态校验 `prompt_lint` | chain_audit A2 / C9（S11） | `prompt_guard.face_hidden_words / black_words …`；`compiler.guard_term / lint_prompt` | 2026-10-31 | 确认 |
| cfg=1 不放否定子句 | 系统后缀里“无 / 不 / 非 …”开头的子句不加（“非纯黑”改写成“暗部仍有可见层次”）；Turbo / cfg≤1 不送、不记负面词；`video_negative_status = ignored_cfg1` | chain_audit A3（S5“冷”字） | `prompt_guard.cfg_one_positive_only`；`workflows.negative_for`；`pipeline.image_negative(c, model)` | 2026-10-31 | 确认（剧本自带后缀里的“无字幕、无文字、无水印”是剧本内容，未改，转写作方） |
| 在画角色 | “X 的 <身体部位 / 背影 / 剪影 / 吻>”在画；“X 的 <物件 / 消息 / 动作>”只是提到（`mentioned_only`），不进角色锁；物件所有格的主人又以“他”出现 → 在画 | chain_audit A4（S8 顾沉的西装衣领）；360 镜金标准只变 4 镜（ep38-S2/S5、ep53-S5、ep55-S6） | `prompt_guard.possessive_body_words`；`compiler.without_possessive_mentions`；validate_qwen_script QW-CH4 同口径 | 2026-10-31 | 确认 |
| 视频身份 LoRA | 由“在画角色 + 是否背对”确定，与道无关；总开关 `video_identity_enabled=false`（lin_wan_h3_v1 仍是 training、gpu36 没有）→ 现在全部镜头确定性不挂；开了以后道上缺就改派到有的道，都没有 409，出片时再查一次（`MissingVideoLora`） | chain_audit C2/E3 | `prompt_guard.video_identity_*`；`compiler.video_loras_for`；`video_jobs.lane_with_video_loras`；`h3_video.render` | 2026-10-31 | 确认（开不开由总调度 / 项目方定） |
| 只给首帧的提示词 | I2VA 对齐句 + 去掉 `<d>` 外引用 Picture 2 的分句（同句前面的动作保留）+ 正文 `Picture 1` 写成 `<Picture 1>`；take.params.i2v_removed 记去掉了什么 | chain_audit C5、CHAIN F1（官方 base-en §3.1） | `h3_video.i2v_prompt` | 2026-10-31 | 确认 |
| 坏图闸门 | 与任一合法成品尺寸（post.size / 交付尺寸 / 放大出图尺寸）一致就不判“尺寸不符” | chain_audit E7（S4 image v6） | `image_check.accepted_sizes` | 2026-10-31 | 确认 |
| 写作模型输出校验 | `<d>` 只有“[语言] 原文”且逐字；`<d>` 外不出现角色名；不在画角色的 EN 外貌短语不出现；在画角色锚点必须在 | chain_audit A12/B4（重放 3/4 次失败能拦下） | `ns_schema.llm_output_check`；validate_qwen_script 新规则 H3-X4/X5/X6 | 2026-10-31 | 确认 |
| 整集 BGM 模式 | `post.h3_music.default = duck_under_bgm` 由合成读取（CLI 可覆盖）；该模式下“撤到静默（H3 已带配乐）”提示点改为铺满，且报告列出需要重新生成整集 BGM 的原因（现 ep02.wav 是按 11 个静默点作曲、名义时间轴偏差） | 项目方 10-31“整集统一 BGM” | `assemble.resolve_settings / bgm_cues_for_duck_mode`；timeline `bgm.regenerate_needed` | 2026-10-31 | 确认（ep02.wav 需要 gpu3 重新生成） |

### D2. 第二轮（FIX，2026-10-31 晚）

测试：`tests/test_fix_ep02_round2.py`。

| 参数 | 值 | 证据 | 落在哪 | 日期 | 状态 |
|---|---|---|---|---|---|
| H3 lint 按模式分支（CHAIN F2） | `lint_h3(mode="i2va")`：第一行逐字为官方 I2VA 指令行；第一句锚定 `<Picture 1>`；全文不得出现 Picture 2。默认 fl2va 不变 | 官方 base-en §2.1/§3.1（docs/ep02_iter/h3_official_conformance.md）；ep02 11 镜最新 I2VA 提示词经 `final_prompt` 后 11/11 无 block | `ns_schema.h3_lint`（`I2V_ALIGN_LINE` 唯一来源，h3_video 引用它） | 2026-10-31 | 确认 |
| 提交前 lint（F3） | 按实际模式（首尾帧 / 只给首帧）对实际送出的提示词跑 lint_h3，有 block：video-jobs 返回 409，`h3_video.render` 抛 `PromptLintBlocked`；项目方原话覆盖（owner_edit）豁免；非 H3 结构的旧链路提示词不查 | 以前只在剧本导入时跑 | `h3_video.final_prompt / submit_lint / LINT_EXEMPT_SOURCES`、`video_jobs` | 2026-10-31 | 确认 |
| 引号规则（F4） | 只拦台词引号：`<d>` 里的、紧贴 `<d>`/`</d>` 的、“says (quietly): "…"”；`<d>` 外表示画面可见文字的英文双引号放行 | 官方 §4.5 | `h3_lint` H3-D4 | 2026-10-31 | 确认 |
| 配乐作用词（F5） | MOOD 词表加 restrained、background layer、providing … layer、underscore、supporting the scene；剧本自带配乐也检查（`CompiledShot.video_music_warn`），只报 warn，不改剧本文字 | ep02 10/11 镜 “…providing a restrained background layer”（官方 §4.7）| `h3_lint.MOOD_EN_RE`、`h3_prompt.music_warnings` | 2026-10-31 | 确认（措辞改不改交写作方） |
| 兜底构建器说话人（F6） | `<d>` 外不再放剧本括号里的中文舞台提示；有人物表 VOICE 英文就用（`voices=`），没有就只写 `(Sx) says:` | 官方 §4.4；“她慌 (S1) says:” 过不了 H3-A7 | `h3_prompt.dialogue_sentences / build` | 2026-10-31 | 确认 |
| 画外台词嘴唇句（F7） | 紧跟 `</d>`：`while the on-screen character's lips remain completely closed.`（给了 on_screen_pronoun 就用 her/his）；纯独白镜在正文加嘴唇句**没做**（会改剧本正文，需项目方确认） | 官方 §4.4 Case | `h3_prompt.LIPS_CLOSED / lips_closed` | 2026-10-31 | 确认 |
| 开场第一刀 | 整集第一镜第一刀 ≤3 s：在 3 s 处再切一刀，后一刀推近 1.15× 换景别；切点落在台词里就提前到句前；两边都要 ≥1 s，否则不拆 | v0 前 3 s 无切点（S1 一刀 8 s） | `post.edit_rules.open_first_cut_s / open_min_piece_s`；`assemble.opening_pieces` | 2026-10-31 | 确认 |
| 出图身份 LoRA | lin_wan_qi 只在“林晚在画且不背对”时挂（触发词一起去掉，`image_loras_dropped` 记原因）；ep02 只有 S9/S10（林晚背对、主体陈宇）变成不挂 | chain_audit C2（model-only LoRA 整张图生效） | `prompt_guard.image_identity_skip_back_facing`；`compiler.compile_shot` | 2026-10-31 | 确认 |
| 视频身份 LoRA 开关 | 保持 `video_identity_enabled=false`（lin_wan_h3 仍是 training） | 总调度 10-31 | `prompt_guard.video_identity_enabled` | 2026-10-31 | 确认 |
| skin guard knee | 不改（0.25），等 DIR 看 v2 印样 | 总调度 10-31 | `post.skin_guard.knee` | 2026-10-31 | 待验 |

### D3. 项目方 2026-10-31 两项决定（FIX 落地）

测试：`tests/test_fix_ep02_owner_1031.py`。

| 参数 | 值 | 证据 / 原话 | 落在哪 | 日期 | 状态 |
|---|---|---|---|---|---|
| 写作节奏 | 原规则“动作量能在 N 秒内以正常或偏慢速度做完”改为“动作量按正常速度在 N 秒内做完，并留出最后约 1 秒仍在进行的动作” | 项目方原话“改成正常节奏”；writer_rules_addendum §12 第 1 条（v0：7/11 镜静止、10/11 镜结尾定住） | `config/script_chat_rules.md` 第 131 行；H3-A11 的规则文字（validate_qwen_script、docs/audit/rule_ids.md、h3_lint 提示） | 2026-10-31 | 确认 |
| 声线语速（规则 / 示例） | 原“语速偏慢”改为“自然语速”，音色、音区不动 | 同上；§12 第 2、3 条 | `config/script_chat_rules_appendix.md` 第 67 行、`docs/production_rules_v3.md` 第 114 行 | 2026-10-31 | 确认 |
| TTS 语速（系统侧） | 林晚 speed 0.9→1.0、vo_speed 0.86→1.0；顾沉 0.92→1.0 | 同上；§12 第 5 条（独白更长、更容易盖镜） | `config/voices.json`（每条带 speed_owner_decision） | 2026-10-31 | 确认 |
| ep02 人物表 VOICE 实际值 | `soft slow pace` / `measured slow pace` 属于写作方产出，系统不改 | §12 第 4 条 | `docs/ep02_iter/writer_requests.md` W1 | 2026-10-31 | 待写作方 |
| 独白镜嘴唇闭合 | 纯独白镜（有 🎙、没有台词、有人在画）由编译器在 H3 正文第一句末尾补 “, while the on-screen character's lips remain completely closed.”。放在第一句：只给首帧时末句的 Picture 2 分句会被去掉，放末句会被一起删掉；已有嘴唇闭合句就不补；剧本文字不改；`CompiledShot.h3_lips_closed_added` 记录。ep02 补了 S8、S11 两镜 | 项目方原话“加”；官方 base-en §4.4 | `ns_agent.h3_prompt.add_lips_closed / monologue_only`、`compiler.compile_shot` | 2026-10-31 | 确认（S8/S11 现有视频版本会显示“提示词已改”，属预期） |

### P1. H3 提示词时间轴 / 互动槽位（PROMPT 2026-10-31，详见 docs/ep02_iter/prompt_bug_v1.md）

测试：`tests/test_prompt_timeline_v2.py`。

| 参数 | 值 | 证据 | 落在哪 | 日期 | 状态 |
|---|---|---|---|---|---|
| 镜内分拍格式 | 第一拍不写时间；之后每 1.5–2 s 一拍，以 `At 00:SS.mmm,` 开头，递增、在镜长内 | 项目方原话“按秒来计算动作”；官方时间格式只有 `At MM:SS.mmm`（base-en §4.2）；v1 共 11 镜，0 个时间点 | 写作规则附录 sysimpl-v2；lint RL-T1/T2 | 2026-10-31 | 待验（A/B 等方案 A/B 出片） |
| 每拍槽位 | 每拍写视线落点和表情变化；双人镜写对方的可见反应；台词拍写听者 `lips closed`；手部 / 局部镜头不查视线和表情 | v1 有 5 镜表情词或视线词为 0；S2/S3/S4/S6 共用同一段描述；binwu1 dialogue-facing-bind | RL-T3/T4；Spec SS-M5/M6 | 2026-10-31 | 建议（格式已落地，效果待验） |
| 衔接与结尾 | 开头写“第 0 秒已在进行”的动作（already / still / mid-）；最后一拍写进行中的动作 + as the shot ends，不写 settles / freezes；**下镜** 行对接下一镜开头 | v1 共 11 镜，每镜都是“静 → 动 → 静”，S1→S2 切点 ΔE 13.2；h3_comfy_expert §5 结尾冻结 | RL-T5/T6；SS-M7 | 2026-10-31 | 待验 |
| 速度 | 正文不写 at slow speed / slowly / gently…；每秒 18–25 词（v1 是 11–22） | 项目方原话“节奏很慢”；h3_comfy_expert §6 | RL-T7（warn） | 2026-10-31 | 建议 |
| lint 级别开关 | 默认 warn；写作规则 ≥ sysimpl-v2 并且 `timing_lint_level=error`（或该集在 `episodes_error` 里）时才 block | 总调度 10-31：现有剧本不能被拦 | `config/recipes/timing_lint.json` | 2026-10-31 | 确认 |
| 分拍解析 | 只有“；”后面紧跟下一拍的时间时才断拍 | ep02 S2 写作模型在一拍里用“；”分隔两个人 | `spec_import.parse_beats` | 2026-10-31 | 确认 |

### P2. 镜头语言与写作调用（PROMPT 2026-10-31，详见 docs/ep02_iter/camera_language.md）

| 参数 | 值 | 证据 | 落在哪 | 日期 | 状态 |
|---|---|---|---|---|---|
| 一镜一个连续镜头 | H3 里只有一个 `[Shot 1]`；镜内景别变化用运镜表达，换机位就拆镜 | base-en §4.2 “prefer camera motion”；binwu1 “Prefer a single [Shot 1]” | K-WRT-101；sysimpl-v3 | 2026-10-31 | 确认 |
| 镜内多镜（`[Shot N] At …, the camera cuts to`） | 只做实验，不进生产 | civitai 2734359 有样例；对身份和嘴型的影响没有实测 | K-WRT-102 | 2026-10-31 | 待验 |
| 转场 | 写在 **下镜** 行，由剪辑执行：同场用动作匹配或视线匹配，换场用声音先行 0.3–0.5 s，时间过渡用叠化 0.3–0.5 s | StudioBinder 转场定义；runninghub 焦点接力；v1 切点 ΔE 13–25 | K-EDT-101/102；tools/prompt_v2/assemble_plan_c.py | 2026-10-31 | 建议 |
| 写作模型调用关推理 | abliteration large-flash 写分镜或转写提示词时，设 reasoning_effort=none | 方案 C 转写：3 次 24000 token 全被截断（推理 19–24k）；关推理后 11k token 一次输出完整 | K-WRT-108；run_chain 默认 `--reasoning off` | 2026-10-31 | 确认 |
| 纯 Ref2VA 首句 | 编译器删掉 “established by <Picture 1>” 首帧锚定句；构图写在正文第一句 | ref-en §2.2；方案 C 编译时发现的问题 | K-PRM-103；`ns_recipes.prompt.build_ref2va` | 2026-10-31 | 确认 |

## E. V2 / 方案 A（2026-10-31，ep02 实验 21:35 中止前）

| 参数 | 值 | 证据 | 落在哪 | 状态 |
|---|---|---|---|---|
| 双人镜配方 | 纯 Ref2VA（不放定稿首帧、不 AddGuide）+ 项目方挑定脸部裁切 | 新组 SFace S2 0.504 / S4 0.718 / S6 0.678（v1 0.36 / 0.46 / 0.48），cheek_red ≤0.076；E5 multiframe 旧组 self 0.33–0.43（docs/ep02_iter/planA_report.md） | services/recipes/recipes/two_person_ref2va.yaml；K-REN-011 | 建议（4 镜） |
| 按秒时间码 | Ref2VA 下不会造成硬切 | 6 条 0 处（data/ab/v2_iter/cut_check.json） | K-PRM-I01 证据 | 确认（Ref2VA 线） |
| 合成节奏 | max_shot_s 4.5；pace_tighten；J-cut 0.3 s；每镜 ≥3 s | 项目方原话“节奏有点慢……很不 smooth”“transition 非常生硬”；v1 take 试合成 81.4→52.5 s | config/render_quality.json post.edit_rules；K-EDT-010/011 | 建议（未在成片验证） |
| ep02 独白 | 去掉 S8 / S11 | 项目方原话“A. 去掉” | post.voiceover_drop；K-EDT-012 | 确认 |
| 派单 | 每道总负载 ≤2（含直连 ComfyUI）；API 提交超时 180 s + 按 seed 找回 | 共用 6 道时单道排 3–4 个；20:24 三次 30 s 超时但服务端已收 | tools/iterate_loop/submitter.py；K-REN-018 | 确认 |
| skin guard 合成 | 压峰值不压面积 | v2a：a*p95 max −2.4～−8.0，占比 ±3% | post.skin_guard | 确认（⑦ 3→4） |
