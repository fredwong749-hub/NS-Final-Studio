# 成人/内容闸门全库清单（2026-10-30）

> 项目方要求：先读全库，把所有成人相关限制 layout 出来；等并行代码写完，再全部 uncensored。
> 本文是**当前代码**的闸门地图，不是历史记录。`已停` = 行为已不再拦；`仍生效` = 还会改变出图/出片/自动动作；`待定` = 需要项目方决定是否保留。
> 调研依据与外部来源见 `docs/research/uncensored_deep.md`；已完成的删除见 `docs/UNCENSORED.md`。

## 0. 数据流中的闸门位置

```
剧本 .md
  ├─ importer/script_md        🔴 high_intensity、**H3校验**、对白/声音
  ├─ tools/validate_*          H3 结构与内容、MOOD_WORDS、否定词、一镜一人
  └─ compiler                   adult 分类、SAFE_SHOT_TERM/NEGATIVE、banned_words、minor_guard
        ├─ frame_spec           facts、人物/朝向/表情、VLM refine、validate
        └─ image pipeline       refs/face_crop、score(VLM/人脸/发色/焦外)、qc(NudeNet/CLIP/VLM)
              └─ takes.json     qc、score、review、active/locked
画布
  ├─ API ns_api                explicit_hold、adult/by=owner、readiness、SOP/H3 lint
  ├─ canvas_api                runs.explicit_hold、audit/shot_audit、rules
  └─ gpu3 桥                   adult_content、series、rerender
gpu3 渲染
  └─ weita_runner → weita_series / weita_adult
        ├─ precheck              explicit / held（已停）
        ├─ score/regate          SFace、发色、焦外、VLM facts、连续性
        ├─ readiness             sound_intimate、continuity、H3 字段
        ├─ shot_audit            H3-A/D/S、R-C、S3-F/K、P-A/B
        └─ H3 / Image 2.1       提示词与采样参数
后期 / QC
  └─ ns_qc (YuNet/SFace、发色、PSNR/SSIM、音频) + 成片闸门
```

## 1. 成人 / 露骨硬闸

| 位置 | 现在做什么 | 状态 |
|---|---|---|
| `services/agent/ns_agent/compiler.py` `ADULT_KEYWORDS`、`classify_adult()`（约 41–52、302–318） | 关键词 / 🔴 / `force_adult` → `adult`、`adult_reasons` | 仅 metadata；不再拦 |
| `services/agent/ns_agent/importer/script_md.py`（约 36、337） | 读取 `**H3校验**：暂缓（露骨内容）`、🔴 整集 | 仅 metadata |
| `config/adult_overrides.json` | `force_adult`、`per_shot` | 仅 metadata |
| `services/api/ns_api/explicit.py` | `hold()` 恒 `None`；`/api/explicit-holds` 空表 | **已停** |
| `services/api/ns_api/app.py` `_refuse_explicit()` | 原 409；现在 `EX.hold` 恒 None | **已停**（函数仍在） |
| `services/api/ns_api/app.py` `gpu3-rerender` | 原成人必须 `by=owner`；W2 已移除 `by` 字段 | **已停** |
| `services/api/ns_api/owner_run.py` | 原 🔴 / 成人集 409；现 `run-eligibility.allowed=true` | **已停** |
| `services/canvas_api/ns_canvas/runs.py` | 原 `explicit_hold` reason；现只在 detail 记 `adult` | **已停** |
| `services/render_router/ns_render/pipeline.py` `face_ref_approved()` | 原成人参考编辑需 `approved_for_adult`；现恒 true | **已停** |
| `pipeline.set_active()` | 原本机成人 take 不能设为当前；现不拦 | **已停** |
| `pipeline` / `qc.py` | 裸露 QC 原一票否决；现只写 `Take.qc` | **已停** |
| `tools/render_batch.py` | 原默认跳过成人（`--include-adult`）；现默认包含 | **已停** |
| `tools/gpu_grab.py` | 原 `adult/nsfw` 任务拒绝；现接受；QC 只记录 | **已停** |
| `services/api/ns_api/project_ctx.py`、`services/canvas_api/ns_canvas/models.py`、`progress.py` | `adult_content` 默认 false | 已改 true；仍会写入/显示 |
| `services/api/ns_api/readiness.py` `readiness()` | `adult and not intimate` → 缺【亲密声】→ `ok=false` | **仍生效** |
| `services/orchestrator/ns_orch/g2_candidates.py` | `G2Blocked`：未确认 AI 虚构成年人、年龄 < 22、参考图不在人物卡；`QC` 只是任务里的说明字符串，gpu_grab 已不硬失败。**项目方 2026-10-31 决定：年龄门槛改为 18** | **按新决定改**（确认门/QC 只记录保留） |
| `services/api/ns_api/wizard.py` | 写 `face_reference.json` 的 `approved_for_adult`/`approved_by` | metadata；pipeline 不再读 |
| `services/api/ns_api/readiness.py` `shot_owner` | 项目/镜头 owner 路由 | 路由，不是成人闸 |
| `services/api/ns_api/app.py` `_adult_shot` | 成人标签/日志 | metadata |
| `apps/web/src/store.tsx` 661/686/717/745/767/910 | `explicit_hold` 时通知并跳过动作；注释“成人的内容自动跳过” | **仍生效于 UI**（当前字段恒 null，实际不触发） |
| `apps/web/src/components/*`、`util.ts` | 露骨红标 chip、`explicit` 过滤、成人“本地”标签 | 显示层；可删 |
| `apps/web/src/projects/Wizard.tsx` | 成人内容开/关（只记录） | 显示/记录 |
| gpu3 `weita_render.py` `explicit_content()` | 恒 false | **已停** |
| gpu3 `weita_render.py` `no_explicit_model()` | 原禁 NoctQ；现 no-op | **已停** |
| gpu3 `weita_series.py` `held()` / `block_explicit()` | 原授权 hold / 写 blocked；现 false / no-op | **已停** |
| gpu3 `weita_series.py` `frame_route()` | 原固定 base；现 `noct` for explicit/body | **已启用 NoctQ** |
| gpu3 `weita_adult.py` | 原 block + `adult_content=false` 跳过；现无 | **已停** |
| gpu3 `weita_runner.py` `precheck()` | 原 explicit/held 跳过；现不跳过 | **已停** |
| gpu3 `shot_audit.py` | 原写 `blocked=explicit_content_not_supported`；现不写 | **已停** |
| gpu3 `shot_audit.py` `S3-F4` | 非成人裸露 block；现 `need_nudity=False` + 规则 warn | **已停**（只记录） |
| gpu3 `nsfs_canvas/.../runs.py` | 原 `explicit_hold`；现无 | **已停** |
| gpu3 `nsfs_canvas/.../models.py`、`progress.py` | `adult_content` 默认 false | 已改 true |

## 2. 裸体 / 安全衣物 / 敏感词（提示词层）

| 位置 | 现在做什么 | 状态 |
|---|---|---|
| `services/agent/ns_agent/compiler.py` `SAFE_SHOT_TERM = "衣装完整、无裸露"`、`SAFE_SHOT_NEGATIVE` | 非成人镜头追加正向/负向“无裸露” | **仍生效** |
| `compiler.corrector_terms()`（174–180） | 非成人追加 `b.safe_term` | **仍生效** |
| `compiler.compile_shot()` `safe_negative = "" if reasons else b.safe_negative`（约 533） | 非成人负面词加“裸露、走光、低俗姿势” | **仍生效** |
| `compiler._negative()` | 所有负面词都含 `minor_guard`（“未成年人外观”） | **仍生效**（安全） |
| `compiler` `banned_words` / `scrub()` / `banned_hits()` | 网红脸、娃娃感等审美词从系统追加文本去掉/只提示 | **仍生效**（审美敏感词） |
| `config/visual_bible.toml` `[shot_rules_safe]` | `term=衣装完整、无裸露`、`negative=裸露、走光、低俗姿势` | **仍生效** |
| `config/visual_bible.toml` `[realism].banned_words` | 8 个审美词 | **仍生效** |
| `config/visual_bible.toml` `[classification].minor_guard` | 未成年人外观 | **仍生效** |
| `config/visual_bible.toml` `nudity_qc_non_adult` | 现 `report_only` | 已改；代码不读 |
| `services/render_router/ns_render/pipeline.py` `NON_ADULT_NEGATIVE_EXTRA`、`NUDITY_RETRIES` | 旧常量；`image_negative()` 已直通，不再追加 | 常量残留 |
| `pipeline` `image_negative()` | 所有镜头同一负面词（已不追加） | **已停** |
| `services/render_router/ns_render/qc.py` | NudeNet + CLIP v2 + Qwen3-VL 问句 | 只记录，仍运行 |
| gpu3 `weita_render.py` `SAFE_OFFICE`、`SAFE_HOME`、`NUDITY_NEGATIVE`、`BODY_WORDS`、`NUDE_WORDS`、`enforce_clothed()` | 非成人/露骨镜头追加“衣装完整/无裸露”，并加防裸露负面词 | **仍生效** |
| gpu3 `weita_series.py` `NUDITY_Q`、`enforce_clothed()`、`NUDITY_NEGATIVE` | 非成人镜头加 VLM 问句/负面词 | **仍生效**（QC 只记录） |
| `services/orchestrator/ns_orch/g2_candidates.py` `banned` / `strip_banned()`、`NEGATIVE` | 母版候选提示词去掉 banned_words；负面词含“裸体、赤裸上身、未成年人外观、儿童、校服” | **仍生效**（审美 + 安全） |
| `services/agent/ns_agent/frame_spec.py` `facts` / `validate()` / `refine_with_llm()` | 画面事实清单；VLM/LLM 补全；校验 | **仍生效**（内容/质量） |
| `services/agent/ns_agent/frame_spec.py` `sanitize_expression()` | 表情只留表情词 | 质量清洗 |
| `config/script_chat_rules.md`、`script_chat_rules_appendix.md`、`qwen_writer_system_prompt.txt` | 一镜一人、亲密镜只林晚、不写男声、不写否定词、不写人名/触发词、情绪词、审美词… | **仍生效于写作** |

## 3. 镜头 / 画面检测（本机）

| 位置 | 检测什么 | 状态 |
|---|---|---|
| `services/render_router/ns_render/qc.py` | NudeNet 部位、CLIP 裸露分、Qwen3-VL 问句 | 只记录 |
| `services/render_router/ns_render/score.py` | 人脸 SFace/CLIP、发色、躯干色、Laplacian 焦外、VLM facts、真人感 0–10 | 参与评分/选图 |
| `pipeline.render_image()` / `_run_candidates()` / `_default_score()` | 每张候选 QC + score；score 选当前 | 参与选图 |
| `pipeline.qc_sweep()` | 已有首帧补 QC，标记 `nudity` | 只记录 |
| `pipeline.refs.face_crop()` | NudeNet 找脸裁切 | 参考图处理 |
| `pipeline.extra_facts()` | “未写赤脚时要穿鞋”“身份/发色”等 VLM 核对 | 参与 score |
| `services/agent/ns_agent/frame_spec.py` | 人物/朝向/占比/表情/饰品/facts/validate/LLM refine | 参与编译 |
| `services/api/ns_api/readiness.py` `readiness()` / `continuity_item()` | 首尾帧、连续、sound/music、衔接 | **仍生效**；`ready` 会挡 |
| `services/api/ns_api/sop.py` `episode_status()` / `shot_status()` | H3 lint、S4/S5 阻塞 | **仍生效** |
| `services/canvas_api/ns_canvas/audit.py` / `rules.py` | 读/写 `status.json`，subprocess `shot_audit.py` | **仍生效** |
| `packages/qc/ns_qc/` | YuNet/SFace、发色、躯干色、PSNR/SSIM、音频 F0/CLAP、provenance | 报告/可接闸门 |
| `tools/qc_run.py` | 跑 `ns_qc`，fail 退出码 2 | 报告 |
| `tools/gpu_grab.py` | QC v3 写 manifest（不再硬失败） | 只记录 |
| `services/orchestrator/ns_orch/g2_candidates.py` | QC v3 硬失败（母版候选） | **仍生效** |

## 4. MiniMax H3 提示词规则（`packages/schema/ns_schema/h3_lint.py`）

| 规则 | 内容 | 类型 | 状态 |
|---|---|---|---|
| H3-A1 | 对齐句逐字、S.SS 与帧数 | 官方格式 | 保留 |
| H3-A2 | 空行/三字段顺序 | 官方格式 | 保留 |
| H3-A3 | 单镜头、无时间戳 | 官方格式 | 保留 |
| H3-A4 | Picture 1 起、Picture 2 收 | 官方格式 | 保留 |
| H3-A5 | 不写否定句/禁用清单 | 项目/社区风格（cfg 1） | **可删** |
| H3-A6 | 不复述两张静帧，写动作路径 | 官方/风格 | 可删（warn） |
| H3-A7 | `<d>` 外英文 | 官方 | 保留 |
| H3-A8 | `Live-action, cinematic, shallow depth of field,` 固定开场 | 项目模板 | **可删** |
| H3-A9 | 不写剧情概述/抽象情绪 | 官方/风格 | 可删（warn） |
| H3-A10 | 运镜官方词、句中自然动作、每镜一个运镜 | 官方/风格 | 可删（warn） |
| H3-A11 | 4–15 s | 官方技术 | 保留 |
| H3-A12 | ≤7000 字符 | 技术 | 保留（warn） |
| H3-D1 | `<d>` 只放语言标签+原文 | 官方格式 | 保留 |
| H3-D2 | 说话人 ID、首次顺序 | 官方格式 | 保留 |
| H3-D3 | 台词逐字 | 官方/项目 | 保留 |
| H3-D4 | 不用双引号包台词 | 项目/技术 | 保留 |
| H3-D5 | 画外音固定短语+嘴唇闭合 | 官方格式 | 保留 |
| H3-D6 | 🎙 独白不进 H3 | 项目 | 保留 |
| **H3-D7** | 原：亲密镜只林晚发声；普通镜一人；soundscape 不写男声。**项目方 2026-10-31 决定：普通镜仍一人；亲密镜两个人也可以发声**（不再只林晚、不再禁男声） | 项目方规则 | **按新决定改** |
| H3-D8 | 说话人年龄/性别/on-screen/音色/语速 | 官方建议（启发式） | 可删（warn） |
| H3-D9 | `<cutoff>/<scenetrans>` | 官方格式 | 保留（warn） |
| H3-S1 | soundscape 1–4 句英文一段 | 官方格式 | 保留 |
| H3-S2 | soundscape 不写 N/A | 官方 | 保留 |
| H3-S3 | music N/A 或 1–3 句英文；不写抽象情绪 | 官方 | 保留（mood 检查可删） |
| P-A1–A8 | H3 DiT、cfg、LoRA、步数、采样器、缓存、AddGuide | 技术 | 保留 |
| P-B1–B3 | 帧网格、首尾 768×1344、24fps | 技术 | 保留 |
| R-C1–C10 | 8 要素、同链、S1/S2、底板、S3-F、衔接、输入版本、去重、G4 | 技术/内容混合 | 见下 |
| S1-W1–W9 | 剧本 motion/时长/sound/对白/H3 字段 | 写作/技术 | 见下 |
| S3-K1/K3 | 首尾同景/同光/同装、结束状态 | 内容 | **可删** |
| S3-F1 | SFace 人脸 ≥0.40/0.30 | 内容 | **可删** |
| S3-F2 | 背景/主体 Laplacian <1.0 | 内容 | **可删** |
| S3-F3 | 发色 HSV | 内容 | **可删** |
| S3-F4 | 裸露（已 warn） | 内容 | 已停 |
| S3-F5 | VLM facts | 内容 | **可删** |
| S3-F6 | LoRA 强度 ≤1.6 | 技术 | 保留 |
| S3-F7 | 调色已执行、保留原图 | 技术 | 保留 |
| S3-F8 | OCR 无文字 | 内容 | **可删** |

**H3 规则所在位置**：`packages/schema/ns_schema/h3_lint.py`（全部）；`tools/validate_qwen_script.py`（H3 文本/MOOD_WORDS）；`tools/validate_script_strict.py`（NEG_ZH/ESCALATE）；`services/agent/ns_agent/h3_prompt.py`（`episode_music_ok` mood）；`services/api/ns_api/{h3view,sop}.py`；gpu3 `shot_audit.py`；`docs/audit/rule_ids.md`；`docs/SOP_production.md §9A`。

**写作规则**：`config/script_chat_rules.md` 与 `config/script_chat_rules_appendix.md` 里的一镜一人、仅林晚发声、不写男声、不写否定词、不写人名/触发词、MOOD_WORDS、banned_words 都是**输入前的文本闸门**；`tools/validate_script_strict.py` 会把 H3-D7 / QW-C* 升 block。

## 5. Qwen Image 2.1 / NoctQ

| 位置 | 现在做什么 | 状态 |
|---|---|---|
| `services/render_router/ns_render/pipeline.py` `QWEN_TURBO/QWEN_BASE/QWEN_*` | 模型选择；成人镜头曾走 Base/NoctQ | 模型路由 |
| `pipeline.image_negative()` | 已直通编译器负面词 | 已停追加 |
| `pipeline.image_model()` | `NON_ADULT_USE_BASE` 开关（默认 false） | 非审查 |
| `pipeline.render_image()` | 两段式：构图 → 换脸 → 调色 → score（VLM/人脸/发色/焦外） | **score 仍生效** |
| `pipeline.refine_image()` | 精修；score/QC | 质量 |
| `pipeline.render_last_frame()` | 尾帧编辑；score/QC | 质量 |
| `frame_edit.py`（W2 画布） | `regen`/`instruct`/`refs`，1 张、不评分、不看图、不做裸露否决 | **已 uncensored** |
| `h3_video.py`（W2） | H3 只做技术格式；不做内容检测 | **已 uncensored** |
| `services/api/ns_api/video_jobs.py`（W2） | 视频任务；声明“不做内容检测 / 成人拦截”；只校验 steps/seconds/gpu | **已 uncensored** |
| `services/api/ns_api/frame_jobs.py`（W2） | 首/尾帧任务；声明“1 张、不评分、不看图、不否决” | **已 uncensored** |
| `services/api/ns_api/asset_edit.py`（W2） | 资产出图；`negative` 原样传入，没有 QC/评分 | **已 uncensored**（负面词由调用方给） |
| `weita_render.py` | `frame_route()` / `enforce_clothed` / `NUDITY_NEGATIVE` | 部分仍生效 |
| `weita_series.py` | `frame_route()` NoctQ；`score`/`qc` | 部分 |
| `config/visual_bible.toml` | safe/banned/minor/nudity | 见上 |

## 6. 画布 / API / UI

| 位置 | 现在做什么 | 状态 |
|---|---|---|
| `services/api/ns_api/app.py` `/api/explicit-holds` | 兼容端点，恒空 | 可删 |
| `app.py` `_shot_summary()` `explicit_hold` | 恒 null | 可删 |
| `app.py` `boost/suggest` / `render` / `gpu3-rerender` | `_refuse_explicit` no-op | 可删 |
| `app.py` `render` 的 `_gpu3_owner_reason` | 一条链路由（gpu3/canvas） | 路由 |
| `app.py` `_video_ok` | gpu3 audit `video_gate`；内容审计 | 仍生效 |
| `services/api/ns_api/episodes_fast.py` | `explicit_hold`/`adult` 字段 | 兼容 |
| `services/canvas_api/ns_canvas/audit.py` | `shot_state.blocked`、`video_ok` | 仍生效 |
| `services/canvas_api/ns_canvas/runs.py` | `red_note` 只 detail | 已停 |
| `apps/web/src/types.ts` `ExplicitHold`、`explicit_hold` | 类型兼容 | 可删 |
| `apps/web/src/util.ts` `Filter`/`EXPLICIT_LABEL`/`matchFilter` | “仅看红标” | **UI 仍生效** |
| `EpisodeList` / `ShotCard` / `ShotRow` / `Inspector` / `Viewer` | 红标 chip、禁用菜单、通知 | **UI 仍生效**（字段 null） |
| `store.tsx` | `explicit_hold` 跳过请求；注释“成人自动跳过” | **UI 仍生效** |
| `Wizard.tsx` / `InboxView` / `BoardView` | 成人开关/数量/说明 | 显示 |
| `config/adult_overrides.json` | 强制成人 / 逐镜 | metadata |
| `config/shot_ownership.json` | gpu3/canvas owner | 路由（W2 已改 canvas） |

## 7. gpu3 运行时

| 位置 | 现在做什么 | 状态 |
|---|---|---|
| `weita_runner.py` `precheck()` | 只看步骤闸门；explicit/held 已不拦 | 已停 |
| `weita_series.py` `held()` / `block_explicit()` | false / no-op | 已停 |
| `weita_series.py` `frame_route()` | explicit/body → NoctQ | 已启用 |
| `weita_series.py` `score()` | SFace、发色、焦外、VLM facts、连续性 | **仍生效**（选图/记录） |
| `weita_series.py` `continuity_check()` | VLM 同衣/同地/同光 + LAB 距离 | **仍生效** |
| `weita_series.py` `clip_checks()` | owner_script_qc、首帧 PSNR、SFace、末帧 SSIM | **仍生效** |
| `weita_series.py` `readiness()` | frames_done、continuity、sound/H3/亲密声/music/BGM | **仍生效**（视频门） |
| `weita_series.py` `step_a_shot()` | score 选最佳；失败写 HARD，仍锁 | **仍生效** |
| `weita_series.py` `gen_candidates()` | `NUDITY_NEGATIVE` for `enforce_clothed` | **仍生效** |
| `weita_adult.py` | `do_shot` 不再 block；`regate`/`score` | `regate` 仍生效 |
| `weita_render.py` `explicit_content()` / `no_explicit_model()` | false / no-op | 已停 |
| `weita_render.py` `enforce_clothed()` / `NUDITY_NEGATIVE` | 非成人提示词/负面词 | **仍生效** |
| `weita_render.py` `score_candidate()` | 候选评分 | **仍生效** |
| `shot_audit.py` | H3/R-C/S3-F/K 全量；`S3-F4` warn；`audit.blocked` 已删 | 部分 |
| `nsfs_canvas` `runs.py` | explicit_hold 已删 | 已停 |
| `nsfs_canvas` `audit.py` | `shot_state.blocked` | 仍显示 |
| `audio_post.py` / `nsaudio-watch` | 配乐/人声/男声检查 | 后期 QC |
| `s4_content_safety_check.py` / `e2e_loop.py` | 内容安全检查/年龄/衣着 | 独立脚本 |
| `refresh_style_vocab.py` | “adults only, fully clothed, nothing see-through” | 风格词库 |

## 7b. 辅助 / 离线脚本

| 位置 | 现在做什么 | 状态 |
|---|---|---|
| `tools/import_script.py` | `classify_adult()` 写每镜 `adult` / `adult_reasons` | metadata |
| `tools/char_assets/asset_gen.py` / `collect.py` | 资产提示词的 `NEG`/默认负面词（含裸体、儿童等） | 资产/负面词 |
| `tools/v3_check.py` | `V3-L1` 强度、`V3-A2` 只林晚发声、`V3-N1` img 否定词、`V3-F1` 赤脚、`V3-W1..W4` 鞋/漆皮/珠/保守穿搭、`V3-C1` 饰品引入集、`V3-S2` 未成年、`EXPLICIT`/`SENSUAL`/`BODY_FOCUS`/`MALE_VOCAL` | **仍生效**（旧 v3 闸门） |
| `tools/build_lin_wan_dataset.py` | `EXPLICIT` 词、`FLAG_KEYS`（rejected/explicit/adult/nsfw）、`qc.nudity` 必须 False；正向提示词拒绝露骨词 | **仍生效**（LoRA 数据集） |
| `tools/gen_assets.py` | worn/人体图过 `nudity_qc`，命中删除换种子 | **仍生效**（资产） |
| `tools/gen_assets_v2.py` | 同上 QC v3 一票否决；`BANNED` 审美词 | **仍生效**（资产） |
| `tools/gen_assets_items.py` | 角色年龄“adult / 23–38”描述 | 描述，不是闸 |
| `tools/ab_quality.py` / `ab_history.py` / `ab_refine.py` | `non_adult()` 过滤、score/人脸/QC | 实验脚本 |
| `tools/qc_calibrate.py` | NudeNet/CLIP/VLM 校准 | 校准工具 |
| `tools/qwen_repair_loop.py` | 按 `block` 规则返修；H3 内容规则 | 写作返修 |
| `apps/web/src/v3/status.ts` | `readiness.blocked_reasons` / `gpu3_blocked_reasons` 进入“为什么卡住” | UI |
| `apps/web/src/v3/TopBarV3.tsx` / `ReviewRow.tsx` | `Filter` 过滤（含 `explicit`）、行变暗 | UI |
| `apps/web/src/v3/pages/ScriptCreatePage.tsx` | 剧本 `blocking` 数、送导入按钮 | UI |
| `apps/web/src/v3/api_v1_pages.ts` | `LightShot.adult` 字段 | UI 类型 |

## 8. 技术闸（建议保留）

- H3 官方格式：对齐句、三字段、`<d>` 语法、帧数网格 17k+5、124–362、4–15 s、24 fps、768×1344。
- 文件/哈希：首尾帧存在、768×1344、sha256、take 链、去重键。
- 模型参数：DiT、cfg、LoRA 配对、步数、采样器、禁用缓存节点。
- 音频技术：采样率/声道/时长/响度（若需要）。
- 输出：H.264、1080×1920/2160×3840、时长、封装。

## 9. 待删除 / 待决定（按优先级）

**P0 成人硬闸（仍生效）**
1. `readiness.py`：`adult and not intimate` 的【亲密声】要求。
2. `g2_candidates.py`：`age >= 18`（项目方 2026-10-31 决定）、`ai_generated_fictional_adult` 确认保留。
3. UI：`explicit_hold` 跳过动作/过滤/红标（字段已恒 null，可整段删）。
4. `weita_series.readiness` 的 `sound_intimate`、`continuity` 成人/内容项。

**P1 裸体/安全衣物/敏感词**
5. `compiler.SAFE_SHOT_TERM/NEGATIVE`、`corrector_terms`、`safe_negative`；`visual_bible [shot_rules_safe]`。
6. `banned_words` / `minor_guard`（minor 待定）；`g2.banned`。
7. gpu3 `SAFE_OFFICE/SAFE_HOME/NUDITY_NEGATIVE/enforce_clothed`。
8. 写作规则里的“不写否定词/不写人名/不写触发词/情绪词/审美词”。

**P2 检测/评分**
9. `pipeline` 的 `score_fn`/`qc_fn`（画布 W2 已关；旧 RenderBatch/API 仍开）。
10. `shot_audit` S3-F1–F8、S3-K1/K3、R-C6/C7；`packages/qc` 的人脸/发色/PSNR/SSIM（或只报告）。
11. gpu3 `weita_series.score/continuity/clip_checks/regate`；`shot_audit` 同项。

**P3 H3 内容规则**
12. H3-A5/A6/A8/A9/A10、D7/D8、S3 mood；`validate_qwen_script` / `script_chat_rules` 同步。
13. H3-D7：按项目方 2026-10-31 决定——普通镜仍一人；亲密镜两个人也可以发声。不再只林晚、不再禁男声。

**P4 兼容字段/文档**
14. `explicit.py`、`/api/explicit-holds`、`ExplicitHold` 类型、红标 CSS。
15. `docs/audit/rule_ids.md`、`SOP_*`、`qc_gates.md`、`script_chat_rules*` 同步。

## 10. 项目方已决定（2026-10-31）

1. **年龄**：门槛改为 **18**（原代码 `MIN_AGE=22`）。
2. **H3-D7**：普通镜仍一人；**亲密镜两个人也可以发声**；不再“只林晚”、不再禁男声。
3. **AI 虚构成年人确认 / minor_guard**：保留（用户未要求删除）。
4. **H3 官方格式**：保留；删了对齐句/四块/`<d>`/帧网格，H3 直接不按格式出片。
5. **技术 QC**：尺寸/帧数/哈希/时长/文件存在保留；PSNR/SSIM、人脸/发色/焦外等内容检测按“全删”处理，待解锁时执行。
6. **Qwen / H3 许可**：本地无服务端过滤，但许可/AUP 仍在；代码 uncensored 不等于法律 uncensored。
