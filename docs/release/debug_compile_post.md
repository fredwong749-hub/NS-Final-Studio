# 封板 debug：编译与后期（debug_compile_post）

> 负责：fredw-5c（总调度 fredw-b3 派单，项目方原话“逐一debug，每一部分”）。A 组本会话直接做；B、C 两组由本会话分出的子会话做，结果在此合并。
> 每个模块四步：① 测试清单 ② 用 ep01、ep02（真实数据，只读）和固定测试数据真跑 ③ 补缺的单测 ④ 修 bug；修改都在 CHANGELOG 标“封板修复”。没有提交 git。
> 数据：ep01 = rules_v2（7 镜，v3 源，🔴）；ep02 = v2 原稿（6 镜）；固定测试数据 = tests/fixtures/t06_golden（60 集 × 6 镜 v2）。

## 0. 摘要

- 修复缺陷（封板修复）：
  - A 组（编译 / H3 / frame_spec）：0 个代码缺陷；ep01 全链路干净。导入重复 sources 由 fredw-92 修。
  - B 组（state_timeline / looks / bible）：出场角色过期、A-4 造型库只认 ep01、source_drift 相对路径与重复、配置坏格式崩溃、`per_shot: "false"` 被当成 true、`force_adult` 写成列表时报错、looks 写死 lnwan01（D-6）。
  - C 组（后期 / render_router）：BGM 时间轴过期仍按镜号套用、校色命令相对路径崩溃、Klein 选项 501（界面置灰）。
  - 同期 P1（MASTER_TODO 第 2 阶段）：X-1 gpu_grab 遵守 comfy.lock；D-6 林晚出图触发词唯一来源；models.lock 的 lnwan01 标 training；X-4 配乐按 E8 统一，后期不在 H3 已带配乐的镜头上叠 BGM；G-6、G-7。
- 测试（三组改动合并后）：全量 **561 通过 / 2 失败 / 4 跳过**，加上本次 X-4 新测试。2 个失败都不在本范围：`test_h3_prompt::test_sop_s4_blocker_for_failed_h3`（services/api/sop.py，fredw-92 正在改）、`test_gpu_monitor::test_snapshot_returned_immediately`（gpu 监控，非本组）。`NS_QA_DATA=1` 下 test_qa_laptop 22/22 通过。
- 内容缺口（不是代码缺陷）：ep02 及其余 v2 集没有 **H3提示词**，笔记本草稿过不了 §9A 机检，要按 rules_v2 重写后才能出视频；fredw-ae 已核实：gpu3 渲染器会拒绝（无 H3提示词 → S1-W7 block，字段机检不过 → S1-W8/W9；shot_audit.py:689 assert_pass 在调 GPU 前就抛错，笔记本草稿不会被发送；只有手动执行 `weita_render.py video` 能绕过，记 P2）。
- 需项目方 / 他人：ep01 BGM 要在 gpu3 重生成（T40）；gpu3 的 H3 配乐要按 E8 改（fredw-ae）；tools/s2_waiver.py 遇到坏格式豁免文件仍会崩（项目方专用工具，留到封板后）。

## A 组：importer / compiler / h3_prompt + resolve_music / frame_spec（fredw-5c）

真跑脚本：`scratchpad/qa/group_a.py`（只读）。数据：真实 `data/import/script_v2.json` 的 ep01（rules_v2，7 镜，v3 源）与 ep02（v2 原稿，6 镜）；固定测试数据 `tests/fixtures/t06_golden`（60 集 × 6 镜 v2）。另跑 721 镜边界情况（造型注入开、只有导演加强）。

| 模块 | 检查项 | 真跑（ep01 / ep02 / 固定数据） | 发现 | 修复 | 测试 | 状态 |
|---|---|---|---|---|---|---|
| importer（script_md） | 用 ep01 自己的源（data/script_chat/…/script.md，episodes=[1]）重新解析，与 data 逐字段比对；导入警告 | ep01 7/7 镜一致（只差 decor_state：重解析没带 image 文档，预期）；ep02、固定数据与 v2 源一致 | ① 合并导入每次重复追加 sources（8 条：image 文档 ×4、script.md ×3，旧条目无 version / episodes）；② script.md 用相对路径，source_drift 按 cwd 解析会误报 | ① fredw-92 已修（`tools/import_script.py` dedupe_sources，封板修复；生产 script_v2.json 随 ep02 导入清理）；② B 组修（state_timeline，按仓库根解析 + 去重） | test_merge_import（fredw-92）；B 组单测 | ✅ |
| compiler：首尾帧规格词 + 去重 | 尾帧带首帧的材质 / 纠正器条目；同一条目不重复；格式（，，、None） | ep01 / ep02 / 固定数据：0 处缺失、0 处重复、0 处格式问题；721 镜边界情况 0 问题 | — | （本日已做：QA4-02） | test_last_frame_specs、test_release_compile::test_boost_only_last_frame_keeps_first_frame_specs | ✅ |
| compiler：成人整集判定 | 集标题 🔴 每镜 adult；per_shot 开关 | ep01（🔴）7/7 adult；ep02（无 🔴）按关键词；固定数据与 HEAD 金标准 adult 字段一致 | — | — | test_last_frame_specs（两种模式）、test_release_compile::test_red_episode_marks_every_shot_adult_by_default | ✅ |
| compiler：lnwan_qi 触发词 | 林晚入镜的首尾帧触发词最前；本机缺 LoRA 不剥；不重复 | ep01 7/7 首帧 / 尾帧 / frame_spec 以 lnwan_qi 开头，各 1 次 | — | （读 config/auto_lora_triggers.json，与导入器同一份） | test_last_frame_specs::test_identity_trigger_* | ✅ |
| h3_prompt / resolve_music | §9A 机检（lint_h3 block 级）；配乐来源；剧本 N/A 是否被 BGM 顶替（owner_req §4 #4） | ep01：7/7 h3 来源 = script，机检 0 block，配乐来源 = script；ep02 与固定数据：h3 来源 = laptop（v2 没有 **H3提示词**），每镜 A4/A7/A8/S1 block，部分 A5/D4/D7/S2 | ① owner_req #4 已不成立：剧本写明 N/A 时保持 N/A（source=script）；② v2 镜头只能用笔记本中文草稿，过不了 §9A——内容缺口（ep02 未按 rules_v2 重写），不是代码 bug | ② 画布路径已有闸门（fredw-92：gpu3 视频请求先查 shot_audit + 提示词 sha，否则 409）；fredw-ae 已核实：gpu3 渲染器会拒绝（无 H3提示词 → S1-W7 block，字段机检不过 → S1-W8/W9；shot_audit.py:689 assert_pass 在调 GPU 前就抛错，笔记本草稿不会被发送；只有手动执行 `weita_render.py video` 能绕过，记 P2） | test_music_resolve、test_h3_prompt、test_release_compile::test_script_na_music_not_replaced_by_episode_bgm | ✅（代码）／⚠（ep02 内容待重写；gpu3 拦截待 fredw-ae） |
| frame_spec | validate()；qwen / qwen_last 重复条目；尾帧缺失；触发词顺序 | ep01 / ep02 / 固定数据：validation 0 条、重复 0、尾帧缺失 0 | — | — | test_t08_frame_spec、test_last_frame_specs、test_release_compile | ✅ |

未修 / 需他人：
- ep02 及其余 v2 集没有 **H3提示词** → 必须按 rules_v2 重写后再出视频（写作 = Qwen；fredw-c8 / fredw-92 流程）。
fredw-ae 已核实：gpu3 渲染器会拒绝（无 H3提示词 → S1-W7 block，字段机检不过 → S1-W8/W9；shot_audit.py:689 assert_pass 在调 GPU 前就抛错，笔记本草稿不会被发送；只有手动执行 `weita_render.py video` 能绕过，记 P2）。
- 生产 data/import/script_v2.json 里的重复 sources：随 ep02 导入清理（避免改 sha 触发 S1 重新确认）。


# B 组：state_timeline / scenes、looks / 造型确认与 s2_waiver、bible / visual_bible 读取

> fredw-5c（fork），2026-10-30 封板 debug。真跑脚本：`scratchpad/release/b_run.py`（只读：state_timeline.build 只算不写；looks 用临时目录副本；坏配置在临时目录构造）。
> 数据：真实 `data/import/script_v2.json`（合并导入后 60 集 / 361 镜；ep01 = rules_v2 七镜，ep02–60 = v2）+ 固定数据 `tests/fixtures/t06_golden`（60 集 / 360 镜 v2）。

## state_timeline / scenes

| 模块 | 检查项 | 真跑（ep01 / ep02 / 固定数据） | 发现 | 修复 | 测试 | 状态 |
|---|---|---|---|---|---|---|
| state_timeline | build 全量（只算不写） | ep01 7 镜 4 场景；ep02 6 镜 4 场景；全剧 361 镜 32 场景 1.4 s；固定数据 360 镜 33 场景 | 无崩溃；timeline scene_id 全部在 scenes.json；scenes.json 列的镜头全在 timeline | — | 既有 test_grouping_* / test_episode_boundary_* | ✅ |
| state_timeline | 每镜出场角色（来自 looks Resolver） | ep01：S7 无角色、S2 缺顾沉、S5 缺陈宇、S6 多陈宇 | 根因在 looks（见下表 L-1） | 修 looks 后 ep01 七镜与新剧本 / 编译器 present_characters 一致 | test_characters_follow_current_script_after_reimport | ✅（磁盘上 data/state_timeline.json 需重建才生效） |
| state_timeline | S1 闸门 per-episode（fredw-92 的 episode_version） | ep01 无 s1_gate_not_passed（rules_v2）；ep02 全部 s1_gate_not_passed（v2） | 符合预期 | — | test_episode_version | ✅ |
| state_timeline | source_drift | 真实数据：两份 v2 源 .md 导入后改过，正确报出 | A 组报告：相对路径按 cwd 找 → cwd ≠ 根时误报“文件不见了”；重复条目报两次 | 相对路径按项目根找；同一 (path, sha) 只报一次 | test_source_drift_relative_path_duplicates_and_cwd（含 monkeypatch.chdir） | ✅ |
| state_timeline | read_s1_gate 坏文件 | s1_gate.json = `[]` / `"x"` | AttributeError 崩溃 | 非对象按“没有记录”（S1 不通过） | test_malformed_gate_and_manifest_do_not_crash | ✅ |
| state_timeline | plate_info 坏 manifest | assets/scenes/*/manifest.json = `[]` | AttributeError 崩溃 | 非对象按“没有 manifest” → missing | 同上 | ✅ |
| state_timeline | lora_registry 坏文件 | 根是列表 / loras=null / 条目是字符串 | 已能兜底（返回 {}） | — | 既有 test_lora_registry_merge | ✅ |
| state_timeline | stale_inputs | 磁盘时间线 20:25:31，stale_inputs=[] | — | — | test_inputs_sha_tracks_inputs | ✅ |
| tools/build_state_timeline.py | --check | 361 镜、32 场景、142 段、地点未知 0 | — | — | — | ✅ |

## looks / 造型确认与 s2_waiver

| 模块 | 检查项 | 真跑（ep01 / ep02 / 固定数据） | 发现 | 修复 | 测试 | 状态 |
|---|---|---|---|---|---|---|
| looks（L-1） | 出场角色 Resolver.characters | ep01 七镜：S7 返回空、S2/S5/S6 与新剧本不符；ep02 正常 | schedule.shot_characters 只在种子时写，重新 / 合并导入后过期 | 按当前剧本现算 detect_characters；人工增删仍走 shot_overrides；不改 schema | test_characters_follow_current_script_after_reimport | ✅ |
| looks（A-4，P1） | LookStore 剧本缓存 | /api/looks/episodes/2 404 “unknown episode: 2” | LookStore.script 进程内只读一次；API 单例在只有 ep01 的导入时读入，合并导入后不更新（app.py 导入钩子这次没走到） | 剧本文件 (mtime_ns, size) 变了就重读；测试手工注入的 _script 不重读；不改 services/api | test_store_rereads_script_after_reimport；真实数据 LookStore() 现 60 集、ep02 可解析 | ✅ |
| looks（D-6） | “她”→ 林晚的触发词 | — | detect_characters 写死 "lnwan01" | 读 bible.CharacterRule.she_trigger（visual_bible detect_she_with_trigger），与编译器同一处配置 | test_she_trigger_read_from_bible | ✅ |
| looks | shot_looks / look_prompt 全部镜头 | ep01、ep02 每镜都能解析，无异常；冲突数 1–4（数据侧） | — | — | 既有 test_prompt / test_conflicts | ✅ |
| looks | 集造型确认 | ep01、ep02 episode_confirmed(lin_wan) = False（时间线 look_unconfirmed:ep01/02） | 数据状态，非缺陷：项目方尚未确认 | — | test_owner_confirmation_clears_review_and_marks_episode | ✅（待项目方） |
| s2_waiver | waived() | 无 config/s2_waivers.json → None | 根是列表 / waivers=null / 条目非对象时崩溃 | 格式不对 = 没有豁免；条目非对象跳过 | test_malformed_waiver_file_means_no_waiver | ✅ |
| tools/s2_waiver.py | 写入 / 撤销 | 未真跑（只由项目方本人运行，会写 config 并重建时间线） | 已有文件格式坏时 `data["waivers"]` 会崩 | 未修（项目方专用工具；read 侧已兜底） | — | ⚠ 记录 |

## bible / visual_bible 读取

| 模块 | 检查项 | 真跑（ep01 / ep02 / 固定数据） | 发现 | 修复 | 测试 | 状态 |
|---|---|---|---|---|---|---|
| bible | 当前仓库 visual_bible.toml | 正常加载；bible_version 8eabf6852ea5 | — | — | test_current_repo_bible_compiles | ✅ |
| bible | 缺文件 / 空文件 | 回退到编译器常量（材质 3、角色 3、lens 50/1.4） | — | — | test_missing_bible_falls_back_to_constants | ✅ |
| bible | 坏 TOML | 报“不是合法 TOML（…）”ValueError | 符合设计 | — | — | ✅ |
| bible | 类型写错 | lens_default="x" → IndexError；characters=[] → AttributeError | 报错看不出哪里错 | `_check_types`：表 / 表数组 / lens_default 类型不对时报清楚的 ValueError（指出键名） | test_wrong_types_raise_clear_error | ✅ |
| bible | adult_overrides per_shot | `"per_shot": "false"`（字符串）→ True | 会悄悄把成人判定切成逐镜 | 只认布尔 true 或字符串 "true" | test_adult_overrides_per_shot_and_list_force_adult | ✅ |
| bible | force_adult 写成列表 | `["ep01-S1"]` → 编译器 forced[shot.id] TypeError | 根因在读取侧 | forced_adult() 把列表规范成 {镜号: "（未写原因）"}，不动 compiler.py | 同上 | ✅ |
| bible | overrides 路径按项目根 | — | — | — | test_overrides_path_is_project_root_aware | ✅ |

## 未修 / 需他人

- **data/state_timeline.json 需重建**：L-1 修复只改了解析逻辑；磁盘上的时间线还是旧结果。按规定 B 组不写 data/，下一次导入 / 造型修改会自动重建，或由 fredw-92 手动 `tools/build_state_timeline.py`。
- **tools/s2_waiver.py**：已有 s2_waivers.json 格式坏时写入会崩（项目方专用；读取侧已兜底），封板后再改。
- **services/api/ns_api/app.py L87**（fredw-92）：导入后 `default_store()._script = None` 的钩子已不再必要（现按文件变化自动重读），保留无害。
- **全量失败 1 项，不在 B 组**：`tests/test_h3_prompt.py::test_sop_s4_blocker_for_failed_h3` —— `services/api/sop.py::shot_status` 读测试替身上不存在的属性（AttributeError），sop / h3 组正在改。另 `test_script_chat_batch` 曾在一次全量中失败，单跑 8/8 通过（并发改动期间）。

## 全量 pytest

`561 passed, 1 failed（test_h3_prompt::test_sop_s4_blocker_for_failed_h3，非 B 组）, 4 skipped`（2026-10-30 晚，约 117 s）。
B 组相关文件单跑：test_looks / test_state_timeline / test_t06_bible / test_s2_waiver 全部通过。
CHANGELOG：6 行“封板修复”（fredw-5c）。


# 封板 debug — C 组：post 与 render_router（fredw-5c）

真跑数据：live `data/import/script_v2.json` 的 ep01（rules_v2，7 镜）、ep02（v2，6 镜）；固定剧本 `tests/fixtures/t06_golden/data/import/script_v2.json`（60 集 v2）；真实 H3 片段用 gpu3 归档 `data/renders_gpu3/_archive/ep01_v2_20261030/S1–S3`（每段 243 帧）。所有装配输出写到 scratchpad，未写 data/episodes、data/renders（render_router 真跑时把 `_write_json` 换成空操作）。

## post / assemble（T38，按实际片长 G13）

| 模块 | 检查项 | 真跑（ep01 / ep02 / 固定数据） | 发现 | 修复 | 测试 | 状态 |
|---|---|---|---|---|---|---|
| assemble | 完整装配（假 TTS、无回听、4K off） | ep01：7 镜黑场占位（gpu3 ep01 旧视频已清、等重渲），54.25 s，-14.3 LUFS；ep02：6 镜静帧占位，60.0 s，-14.0 LUFS；都正确输出为 `_PREVIEW_未完成` | 无 | — | test_post 16 项 | ✅ |
| assemble | G13：有视频按 H3 实际片长，占位按剧本秒数 | ep02 剧本 + 归档真实 H3 片段 S1–S3：每段 10.125 s（243 帧），`duration_from=h3_video`、`trimmed_s=0`；S4–S6 静帧 10 s；时间线 1449 帧 = 成片 ffprobe 1449 帧 | 无 | — | test_assemble_episode_end_to_end | ✅ |
| assemble | 4K VBV、_cc source_sha256（fredw-92） | 保留未动 | — | — | test_research_adoption_params 10 项 | ✅ |
| assemble / music | BGM 提示时间轴与当前剧本是否同一版 | ep01：`data/music/ep01.json` 按旧 6 镜（10 s × 6）生成，被按镜号套到现在 7 镜的 ep01（S7 无提示、起点错位），无任何警告 | **缺陷** | 镜数不一致 → 时间轴作废，改用剧本【配乐】/ 修改，并警告“需 gpu3 T40 重生成 BGM”；复跑 ep01：7 条提示全部来自剧本，S6 撤到静默 | test_stale_json_cue_timeline_falls_back_to_script_cues | ✅ 已修 |

## post / colormatch（T52）

| 模块 | 检查项 | 真跑（ep01 / ep02 / 固定数据） | 发现 | 修复 | 测试 | 状态 |
|---|---|---|---|---|---|---|
| color_match_clips | `--episode N --dry-run` | ep01 / ep02：no clips found（两集现在都没有 gpu3 视频，正确） | 无 | — | — | ✅ |
| color_match_clips | `--clip <相对路径> --first … --dry-run` | 归档 S3 片段：崩溃 `ValueError: … is not in the subpath of 'D:\\NS-Final Studio'` | **缺陷**：判断用 resolve 后的路径、relative_to 用原路径 | 改为 `clip.resolve().relative_to(ROOT)`；复跑：frame0 dE 1.03、end dE 8.25，计划 hold，正常 | test_cli_dry_run_accepts_relative_clip_path（修复前失败、修复后通过） | ✅ 已修 |
| colormatch | 端到端写 _cc、音轨直拷、暗场不提亮 | — | 无 | — | test_colormatch 9 项 | ✅ |

## post / music

| 模块 | 检查项 | 真跑（ep01 / ep02 / 固定数据） | 发现 | 修复 | 测试 | 状态 |
|---|---|---|---|---|---|---|
| parse_cue_text | 剧本【配乐】词表 | ep01 七条：进入/渐强/延续/撤到静默、强度 0–2、对白避让 6 dB / 无需避让，全部解析正确；ep02 无提示 → 默认进入强度 1 | 无 | — | test_parse_cue_text、test_music_resolve 5 项 | ✅ |
| find_music | 文件缺失 | ep02 无 BGM → 警告并跳过音乐层 | 无 | — | test_assemble_without_music_warns_and_skips | ✅ |
| resolve_cues | json 时间轴过期 | 见上（assemble / music） | 缺陷 | 已修 | 新增 1 项 | ✅ 已修 |

## post / TTS

| 模块 | 检查项 | 真跑（ep01 / ep02 / 固定数据） | 发现 | 修复 | 测试 | 状态 |
|---|---|---|---|---|---|---|
| speakers / voice_for | 说话人归属、固定音色 | ep01 8 句、ep02 10 句：顾沉 zm_029、陈宇 zm_050、林晚 zf_067；“他”按镜头上下文归给顾沉；独白归林晚 | 无 | — | test_resolve_* 3 项、test_voice_config_is_fixed_and_distinct | ✅ |
| KokoroBackend | 真实合成（CPU） | ep01 `--tts-only`：8 段写入 data/cache/tts | 无 | — | — | ✅ |

## render_router

| 模块 | 检查项 | 真跑（ep01 / ep02 / 固定数据） | 发现 | 修复 | 测试 | 状态 |
|---|---|---|---|---|---|---|
| pipeline.compile_with_edits | 带修改编译 + frame_spec + inputs_sha | ep01 7、ep02 6、固定剧本抽样 30 镜，共 43 镜：无异常（只读：`_write_json` 换成空操作） | 无 | — | — | ✅ |
| workflows | qwen_t2i / qwen_edit 图结构（节点引用、None 输入） | 同上 43 镜：0 问题 | 无 | — | test_render_workflows 18 项 | ✅ |
| refs | 参考图计划 `_ref_plan` | 同上：0 异常 | 无 | — | 同上 | ✅ |
| shot_is_adult | 与编译判定一致 | ep01/ep02：一致（整集 🔴） | 无 | — | test_real_adult_shots_detected（固定剧本） | ✅ |
| 资产生成 Klein | 选 Klein 返回 501 | 笔记本 / gpu3 都没有 Klein / Flux2 模型，补工作流不可行 | **缺陷**（用户能选到必然失败的选项） | 改动最小：界面选项置灰“Klein（未接入）”（parts.tsx 一行；fredw-92 回复同意：“Agreed, go ahead… keeping the backend 501 as a backstop is right”）；API 501 保留兜底；tsc 通过 | test_klein_option.py（API 为 501 时选项必须置灰） | ✅ 已修 |

## 未修 / 需他人

- **ep01 BGM 要重生成（gpu3 T40）**：`data/music/ep01.wav/.json` 是旧版 6 镜 ep01 的音乐；现在装配会警告并改用剧本提示，但音乐本身仍是旧版。
- ~~ep01 的 duration_source 为空~~：fredw-5c 复核，fredw-92 重新合并导入后 data/import/script_v2.json 的 ep01 七镜都是 `script`（12/8/5/10/5/8/5），load_episode 原样读出，无需修复。
- **ep02 没有 BGM、没有 gpu3 视频**：属于生产进度，不是缺陷。
- **H3 工作流（h3_fl2va）本轮只靠单测**，没用真实镜头构图；视频由 gpu3 出，笔记本不跑 H3。

## 全量测试

`pytest -q tests`：**556 passed, 4 skipped**（含本组新增 3 项：colormatch CLI、BGM 时间轴过期、Klein 选项）。


## P1 修复（MASTER_TODO 第 2 阶段 · 编译与后期）

| ID | 内容 | 结果 | 测试 |
|---|---|---|---|
| A-4 | 造型库只认 ep01（/api/looks/episodes/2 404） | ✅ B 组：剧本文件变了就重读，真实数据能识别 60 集、能解析 ep02 | B 组单测 |
| D-6 | 林晚触发词规则只留一处 | ✅ 出图 lnwan_qi 唯一来源 = config/auto_lora_triggers.json（导入器、编译器、frame_spec、tools/build_lin_wan_dataset.py）；判断“她”的 lnwan01 统一读 visual_bible she_trigger（looks.py，B 组）；models.lock 的 lin_wan_h3_v1（lnwan01）未交付，标 status=training | test_last_frame_specs、B 组单测 |
| X-4 | 配乐三套规则统一 | ✅ 项目方选 E8：H3 带本集 / 单镜配乐（resolve_music 不变）；后期对 H3 已带配乐的镜头不叠 BGM（ns_post.music.h3_music_shots）；E8、SOP §11、music.md 已写明；API 文档串与 types.ts 注释 fredw-92 已改（画布文案已核对无误）；gpu3 固定写 N/A 交 fredw-ae | test_post::test_h3_music_shots_follow_compiler_rule |
| X-1 | gpu_grab 不认 comfy.lock | ✅ 判断空闲时查 comfy.lock 占用者；在本机执行前不等待拿锁，拿不到就放回队列（不计失败）；测试用临时锁文件 | test_gpu_grab 50 通过（含 test_laptop_yields_when_comfy_lock_held） |
| G-6 | 金标准与 T06“0 差异”说法 | ✅ TASKS T06 注明已被 G1 修复取代 | — |
| G-7 | image提示词 v2.md 被改 6 行 | ✅ 查清：本会话按项目方原话“还是不锈钢本色”改的珠色（3 处替换 = diff 6 行），有授权，保留 | — |
| 文档统一 | X-01～X-08（+X-11、X-12、D-22、D-37） | ✅ WORKFLOW、REQ G8 / E 节、TASKS 规则 5/7 与 T34 / T46 / T48 / T53、SOP ★ / §2 / §4 / §5 / §8 / §9A.1 / 示例 2；SOP 管理员 = fredw-5c | — |


## 追加（同日）

- 规则：rule_ids 新增 mixed 级别；H3-S3 → mixed（与 lint 一致）；R-C4 → 首尾帧只要求 image 类 LoRA accepted，视频 LoRA 只在视频步检查、accepted 前只 warn（总调度定）；笔记本补回归测试 test_r_c4_frames_only_wait_for_image_loras。
- gpu3（fredw-ae）：H3 配乐已按 E8 同步（模板 / 兜底提示词用 resolve_music，shot_audit H3-S3、audio_post 不在 H3 已带配乐的镜头上叠 BGM）。
- 最新全量：608 通过 / 4 跳过；canvas_api 22 通过 / 2 跳过。
- 笔记本 S4（fredw-92）：sop.py shot_status 的 stages.S4.warnings 新增 video_lora_unaccepted（rule_ids=[R-C4]），视频 LoRA 未验收只提示、不进 blockers；回归测试 test_sop_s4_video_lora_warn_not_blocker；fredw-92 报全量 631 通过（API 重启后生效）。
