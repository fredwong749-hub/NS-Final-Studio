# 文件锁（UIMASTER 维护）

改文件前先看这里；别人锁着的文件不要动。要锁一个文件：发消息给 UIMASTER，或者自己在下表加一行，改完删掉。

| 文件 / 目录 | 负责人 | 起止 | 说明 |
|---|---|---|---|
| apps/web/e2e/uimaster/** | UIMASTER | 长期 | 点击爬虫 |
| docs/uimaster/** | UIMASTER | 长期 | 日志、问题清单 |
| apps/web/src/v3/assets/**、v3/pages/AssetsPage.tsx、ScenesTab.tsx | ASSETUX | 长期 | 资产中心 |
| apps/web/src/v3/edit/**、ds/editdel.*、v3/pages/TrashRoute.tsx、AuditRoute.tsx | EDITDEL | 长期 | 编辑 / 删除 / 撤销 |
| apps/web/src/**/*.css（间距、对齐、裁切） | UIPIXEL | 长期 | 只改 CSS；动 tsx 先报 UIMASTER |
| App.tsx、TopBarV3.tsx、v3/pages/其余、Canvas、ReviewRow | UIRSI | 长期 | 结构 / 功能恢复 |

## 临时锁

| 文件 | 谁 | 到什么时候 |
|---|---|---|
| services/api/ns_api/{takes_ui.py（候选按剧本版本标 script、状态标签）,season.py,shot_status.py（新建）,decision_locks.py（新建）,app.py（只加 include 两行）}、tools/qa/data_parity.py（只加 D-SCRIPT 一项）、apps/web/src/v3/{ReviewRow.tsx,candidates.ts,StatusTags.tsx（新）,StatusTags.helpers.ts（新）,shotstatus.css（新）,infra.css,pages/SeasonPage.tsx,assets/PeopleHub.tsx} | UIRSI（r40，总调度 11-02 00:0x 紧急派） | r40 收轮即释放 |
| services/api/ns_api/live.py（新建：/api/events SSE + /api/progress） | UIRSI | 实时刷新做完（总调度 11-01 任务） |
| services/api/ns_api/app.py（只加 include_router 两行） | UIRSI | 同上 |
| apps/web/src/v3/live.ts、apps/web/src/ds/StageProgress.tsx、apps/web/src/v3/LiveBridge.tsx（新建） | UIRSI | 同上 |
| apps/web/src/ds/live.css（新建：闪烁 / 进度条样式；按总调度要求先登记，样式归 UIPIXEL 之后接管） | UIRSI → UIPIXEL | 同上 |
| apps/web/src/v3/pages/NewScriptPage.tsx（只加进度条和实时刷新挂钩；与 DATAALIGN 协调） | UIRSI（与 DATAALIGN 共用） | 同上 |
| services/api/ns_api/character_hub.py（GET /api/asset-quarantine；↻ 再生成 POST /api/character-hub/{cid}/regen、items/{id}/use-regen） | ASSETUX | 资产图再生成做完（11-01） |
| tools/autopilot/producer.py、services/api/ns_api/producer.py（新建：/api/producer/status、pause、resume、gate）、data/producer/**（登记表 / 租约 / 日志） | PRODUCER（总调度 11-01：制作自动推进） | 长期 |
| services/api/ns_api/app.py（只加 include_router 一行：producer） | PRODUCER | 加完即释放 |
| VQAGATE 局部改动（项目方 11-01 16:10“检测到不对就叫系统重做”；总调度 fredw-2b 派）：tools/autopilot/producer.py（_postflight 接本地看图闸门、render 应用 prompt_delta、驳回替换版自动复核）、tools/series10_video/build_jobs.py（passed_frames 要求 Q9 通过）、services/agent/ns_agent/gen_contract/postflight.py（_q9_item 阻断口径）、services/render_router/ns_render/auto_current.py（passes 要求 Q9）、packages/qc/ns_qc/gaze_mp.py（只加 blink 输出字段）、tools/series10_video/score_clip.py（gate 接 V9 blocking 缺陷：vlm_fails）、services/agent/ns_agent/vqa/**、config/vqa.json、config/prompts/vqa_inspect.md、tools/vqa/gate_scan.py（新建） | VQAGATE | 本轮收轮即释放 |
| apps/web/src/v3/ProducerPanel.tsx（新建） | PRODUCER | 长期 |
| apps/web/src/v3/pages/NewScriptPage.tsx（只加：挂 ProducerPanel 一行 + 头部手动按钮收进“⋯ 手动插队 / 重做”；不删按钮；与 UIRSI / DATAALIGN 协调） | PRODUCER | 本次改完即释放 |

## 给 GPUVIEW / UIRSI / REFLOCK 的接口说明（PRODUCER，11-01）

- **一份登记表**：`data/producer/registry.json`（schema `nsfs.producer/1`）。`tasks[]` 是扁平的出图 / 视频对象：`{id: "first:ep01-S1", kind: first|last|video, ep, shot, status: pending|ready|running|passed|failed|best_effort, attempts, max_attempts, last_error, reason（人话）, waiting_for, where（道 / 会话）, since}`；`lanes{}` 是 PRODUCER 看到的每条出图道（free / why / agents）。GPUVIEW 的 `/api/render-tasks` 请直接读这一份（或 `GET /api/producer/status`），不要另建副本。PRODUCER 投的 ComfyUI 任务都带 `ns_tag.agent = "PRODUCER"`，`obj` / `job` = 上面的 id。
- **SSE**：PRODUCER 状态一变就重写 `data/pipeline/runs/<run>/_producer.json`，live.py 现有 Watcher 会推 `{type: "stage", run, field: "_producer.json"}`；UIRSI 若愿意可加专门的 `type: "producer"`（data/producer/registry.json 变 → 推一条），ProducerPanel 两种都认。
- **REFLOCK**：PRODUCER 出首帧 / 尾帧只调 `ns_agent.frame_job.build_first / build_last` + `ns_render.unified_frame`（`_contract` / `_run` / `_postflight`），不碰旧 qwen_two_stage；唯一路径改了这边自动跟上。
| apps/web/src/components/GpuPanel.tsx、apps/web/src/v3/edit/lanes.ts（GPU 面板实时卡；lanes.ts 本次未改） | GPUVIEW | GPU 实时详情做完（11-01） |
| apps/web/src/components/RenderTasks.tsx（新建：渲染任务中心，顶栏 + 底栏同一行组件）、apps/web/src/components/Drawer.tsx（只换“任务队列”标签内容 + 标签头改 ds Tabs；其余三个标签不动） | GPUVIEW | 同上 |
| apps/web/src/components/rendertasks.css（新建：rt-* / gl-* 样式；按规矩先登记，样式归 UIPIXEL 之后接管） | GPUVIEW → UIPIXEL | 同上 |
| apps/web/src/v3/TopBarV3.tsx（只把“● 生成中 · 排队 · 失败”按钮换成 RenderTasksButton 一处；UIRSI 文件，已报总调度） | GPUVIEW | 同上 |
| services/api/ns_api/gpu_live.py、render_tasks.py（新建）、app.py（只加 include_router 两行）、services/agent/ns_agent/comfy_tag.py、gpu_smi.py（新建）、tools/monitor/server.py（只把 nvidia-smi 解析换成共用 gpu_smi） | GPUVIEW | 同上 |
| services/api/ns_api/shot_audio.py `_music`（DATAALIGN 改：配乐镜号取剧本真实镜号、加 stale_timeline） | UIRSI 已审同意（11-01 02:5x） | — |
| apps/web/src/ds/Flash.tsx（新建，实时刷新提示包装） | UIRSI | 实时刷新做完 |
| apps/web/src/ds/live.css（UIRSI 按总调度指令新建；UIPIXEL 11-01 已同意接管：“live.css 写完交我接管没问题”） | UIPIXEL（接管） | 长期 |
| apps/web/src/projects/Root.tsx（无 owner，共享；UIRSI 11-01 03:1x 事后补登：只把 script-chat 从“旧地址重定向”里去掉，恢复写作对话路由，UIAUDIT F23） | 共享（UIRSI 已改完） | — |

## 授权（CONSENT，iter_gate O1 读这一节）

文件的 owner 允许别的 agent 改自己的某个文件时，由 owner（或总调度代录）在这里加一行；`tools/qa/iter_gate.py` 的 O1 认这一行，不再判越界。格式固定（一行一条，`|` 后面写原话 / 日期）：

`CONSENT: <文件 owner> -> <被授权 agent> : <路径或 glob> | <原话 / 日期>`

- CONSENT: 总调度 -> RESEARCH : docs/master/MASTER_PICTURE.md（只加 L-087 一行）, config/owner_decisions.yaml（只加 D-IMG-87a/b/c） | 总调度 fredw-2b 11-01 17:5x：“这两个文件总调度授权你改，写 CONSENT。”
- CONSENT: REFLOCK -> RESEARCH : services/render_router/ns_render/unified_frame.py | 总调度 fredw-2b 11-01 代录：“GPU A/B 走方案 ②：给 frame-jobs 加 scope=ab 标记，不进 auto_current，不进 rescore，不进契约账本，产物放在独立目录……改 services/api 的 frame_jobs 和 producer 时要写 CONSENT（by 总调度 fredw-2b），在 LOCKS 登记，补测试。”
- CONSENT: 总调度 -> RESEARCH : services/api/ns_api/frame_jobs.py | 总调度 fredw-2b 11-01（同上一条原话）
- CONSENT: REFLOCK -> VIDEO10 : services/agent/ns_agent/framing.py | 总调度 fredw-2b 11-01 代录（W5）：“frame 编译器的修法授权你做，CONSENT 写成 REFLOCK → VIDEO10……a) 局部镜头的单品参考只取手部，躯干占比超过阈值就拒绝或重裁；b) 局部镜头的角色句保留发色句；c) 动作句写到局部以外的身体部位……做成 P4 lint……局部范围按动作句扩大到‘手 + 肩颈局部’。”
- CONSENT: REFLOCK -> VIDEO10 : services/agent/ns_agent/asset_refs.py | 总调度 fredw-2b 11-01 代录（同上一条，W5 a：手部参考重裁 + 躯干占比检查）
- CONSENT: ITERAUDIT -> VIDEO10 : tools/qa/writer_lints.py | 总调度 fredw-2b 11-01 代录（同上一条，W5 c：“做成 P4 lint（交写作方，你只写 lint，不改剧本）”）
- CONSENT: REFLOCK -> VIDEO10 : docs/GEN_CONTRACT.md | 总调度 fredw-2b 11-01 代录（W5 派单原话：“修在根上……写成规则 + check，并同步 GEN_CONTRACT / CONSIST playbook”；只改 I4 一格）
- CONSENT: ITERAUDIT -> PRODUCER : tests/test_active_audit.py | 总调度 fredw-2b 11-01 代录（RSI r5 K-OPS-Q23 派单原话：“改完把 tests/test_active_audit.py 白名单里的 producer 那一行去掉”；只删那一行）
- CONSENT: BAKEOFF -> RESEARCH : knowledge/rules/render_qwen21.yaml（只改 K-WRT-Q29：第 6 条标 ⤴、挂写作知识包 target） | 总调度 fredw-2b 11-01：“项目方原话优先，附录胜出。把 Q29 第 6 条标 ⤴，并给 Q29 挂上写作知识包的 target。”
- CONSENT: ITERAUDIT -> CODERSI : tools/qa/iter_gate.py（只加 Y1 语法守卫一项 + CODE-RSI 别名 + parse_consents 截掉路径后的括号说明，K-OPS-C06） | by 总调度 fredw-2b 11-01 18:1x 派 CODE-RSI：“改别人拥有的文件之前，先在 docs/uimaster/LOCKS.md 写 CONSENT（by 总调度 fredw-2b），并且只做最小的局部改动”；“把它做成一个常驻检查……接进 iter_gate，作为每个 loop 收轮必过的一项”
- CONSENT: ITERAUDIT -> CODERSI : tools/qa/ownership.yaml（只加 CODERSI 条目） | by 总调度 fredw-2b 11-01 18:1x 派 CODE-RSI：“改别人拥有的文件之前，先在 docs/uimaster/LOCKS.md 写 CONSENT（by 总调度 fredw-2b），并且只做最小的局部改动”
- CONSENT: REFLOCK -> CODERSI : tests/test_image_framing.py（只改 G22 一行断言：只拍手 → 画面里只有手） | by 总调度 fredw-2b 11-01 18:1x 派 CODE-RSI：“改别人拥有的文件之前，先在 docs/uimaster/LOCKS.md 写 CONSENT（by 总调度 fredw-2b），并且只做最小的局部改动”；“测试过期就按决定更新断言，不删测试”
- CONSENT: 总调度 -> CODERSI : tests/test_review_fixes_d9.py（只改 G23：range PUT 断言伪造确认没写进去，不再假设真实排期无确认） | by 总调度 fredw-2b 11-01 18:1x 派 CODE-RSI：“改别人拥有的文件之前，先在 docs/uimaster/LOCKS.md 写 CONSENT（by 总调度 fredw-2b），并且只做最小的局部改动”
- CONSENT: ITERAUDIT -> VOICE10 : tools/qa/ownership.yaml（只改 owners.VOICE10 一行：登记 tts.py / speakers.py / voices.json / test_voice10_fix.py / docs/voice10） | by 总调度 fredw-2b 11-01 晚：“归属你自己登记：services/post/ns_post/tts.py、speakers.py、config/voices.json、tests/test_voice10_fix.py 全部登记给 VOICE10”
- CONSENT: RECALL -> VOICE10 : docs/master/MASTER_PICTURE.md（只改 §1 L-078、第 24 行 decision_check 汇总、残留表 R3 / R4、§4 G1 / G2 / G9 / G17，按实测改 ✅ / 已关并附出处） | by 总调度 fredw-2b 11-01 晚：“MASTER_PICTURE §1 L-078，以及 §4 的 G1 / G2 / G9 / G17，按实测改成 ✅ / 已关，附上出处。总调度授权，CONSENT 写 RECALL → VOICE10”；补授权 11-01 晚：“MASTER_PICTURE 第 24 行……以及残留表 R3 / R4 两行，授权你按实测更新（RECALL → VOICE10，在原有 CONSENT 基础上补）”
- CONSENT: VIDEO10 -> VOICE10 : tools/series10_video/night.py | 只改 night.py 的 tts_missing() 函数体、test_tts_missing_and_retry_assembly 夹具补模型目录；by 总调度 fredw-2b 11-01 派 VOICE10：“让 night.py 的正常流程把 ep04 合成成功……改 night.py / assemble 前先看 docs/uimaster/LOCKS.md 并登记，不要和它冲突”
- CONSENT: VIDEO10 -> VOICE10 : tests/test_video10_resilience.py | 只给 test_tts_missing_and_retry_assembly 夹具补模型目录（同上授权，总调度 fredw-2b 11-01）
- CONSENT: AUTOPILOT -> VOICE10 : tools/autopilot/resident_sync.py（只改 required_data：加 config/voices.json 各说话人 ref_wav / asset，服务器合成必需） | by 总调度 fredw-2b 11-01 晚：“TTS 在两台服务器上都要能用……同步音色文件和 voices.json……和 WORKFLOW 的推送 / 启动脚本对接，别各装一套”
- CONSENT: AUTOPILOT -> CODERSI : tools/autopilot/resident_sync.py（只改 tar_bytes 一个函数：整份读入再写成员，修打包途中文件被截短导致整包错位；push 里 rem_dirs 一行：tier 2 列回 data/） | by 总调度 fredw-2b 11-01 18:1x 派 CODE-RSI：“读 tools/autopilot/resident_sync.py……在本地模拟一次……确认会推的文件都是最新版、能完整解码、没有截断”；“改别人拥有的文件之前，先在 docs/uimaster/LOCKS.md 写 CONSENT（by 总调度 fredw-2b），并且只做最小的局部改动”
- CONSENT: 总调度 -> CODERSI : tests/test_fix_ep02_round2.py（只改 G24 过滤条件：跳过 workflow=video10 的配方引擎片） | by 总调度 fredw-2b 11-01 18:1x 派 CODE-RSI：“测试过期（断言跟不上已定的决定）就按决定更新断言，不删测试”
- CONSENT: REFLOCK -> CODERSI : tests/test_video_jobs_v1.py（只改一行期望值：编译器输出按本次帧数 realign） | by 总调度 fredw-2b 11-01 18:3x：“tests/test_video_jobs_v1 失败（时长 6.58 对 8.00）……归你按‘测试跟着现行决定走’处理：改断言，不删测试，或者改用测试夹具”
- CONSENT: REFLOCK -> CODERSI : tests/test_gen_contract.py（只改选镜：写死的 ep01-S3 / S4 换成按镜头性质选 FULL / TWO，断言不动） | by 总调度 fredw-2b 11-01 18:3x：“tests/test_gen_contract.py 新出现 3 条失败……请归因：是产品回退就修产品，是断言过期就按现行决定改断言”
- CONSENT: REFLOCK -> CODERSI : tests/test_ref_switch_assets.py（只改选镜：写死的 ep01-S3 换成“林晚单人、脚可见”的第一镜） | by 总调度 fredw-2b 11-01 18:4x：“修法是让测试改用测试夹具，或者改成按导入稿找‘对应景别的镜’，不要写死镜号……CONSENT 写 REFLOCK → CODE-RSI，by 总调度”
- CONSENT: AUTOPILOT -> CODERSI : tools/autopilot/resident_sync.py（push_dirs 抽函数 + push_gate：push / recover / video_up / bringup / switch / loop 推送前必须 push_check PASS，不过不推、不起常驻） | by 总调度 fredw-2b 11-01 18:5x：“push_check 做成 push / recover / video_up 的前置：不通过就不推、不起常驻。授权你改 resident_sync.py，CONSENT 写 AUTOPILOT → CODERSI……顺便按你的建议把 push 的目录计算抽成函数，push_check 直接调用”
- CONSENT: ITERAUDIT -> CODERSI : tools/qa/iter_gate.py（只加 V2 系统版本提示一项） | by 总调度 fredw-2b 11-01 23:0x 派 CODE-RSI r3：“iter_gate 加一项：本轮改动是否已经进了某个版本，没进就提示”；项目方 22:5x“每一次迭代都是用 override system,然后用 create a new version 那个 system versions”
- CONSENT: ITERAUDIT -> CODERSI : tools/qa/ownership.yaml（只在 CODERSI 条目加 system_version 文件） | by 总调度 fredw-2b 11-01 23:0x 派 CODE-RSI r3：“iter_gate 加一项：本轮改动是否已经进了某个版本，没进就提示”；项目方 22:5x“每一次迭代都是用 override system,然后用 create a new version 那个 system versions”
- CONSENT: SCRIPT_RSI -> CODERSI : tests/test_hollywood.py（只改 test_head_exception_pencil_skirt_only：按 HEAD_EXCEPTIONS 反做得到导入前原稿） | by 总调度 fredw-2b 11-01 23:5x：“按‘测试跟着现行决定走’修……CONSENT 写 SCRIPT_RSI → CODERSI（HOLLYWOOD 已收工）”
- CONSENT: REFLOCK -> CODERSI : tests/test_gen_contract.py（FULL 改夹具镜 + look_a 夹具） | by 总调度 fredw-2b 11-02 00:2x 派 CODE-RSI r4：“有 5 条测试读真实剧本，被 23:22 HOLLYWOOD 导入弄坏了……改成用测试夹具或临时数据，不依赖现行剧本；断言不放松。CONSENT 写各自 owner → CODERSI”
- CONSENT: REFLOCK -> CODERSI : tests/test_ref_switch_assets.py（SHOT 夹具 + 临时登记钉死造型 A） | by 总调度 fredw-2b 11-02 00:2x 派 CODE-RSI r4：“有 5 条测试读真实剧本，被 23:22 HOLLYWOOD 导入弄坏了……改成用测试夹具或临时数据，不依赖现行剧本；断言不放松。CONSENT 写各自 owner → CODERSI”
- CONSENT: PRODUCER -> CODERSI : tests/test_outer_items.py（img 夹具去掉外套分句） | by 总调度 fredw-2b 11-02 00:2x 派 CODE-RSI r4：“有 5 条测试读真实剧本，被 23:22 HOLLYWOOD 导入弄坏了……改成用测试夹具或临时数据，不依赖现行剧本；断言不放松。CONSENT 写各自 owner → CODERSI”
- CONSENT: RECALL -> CODERSI : docs/master/MASTER_PICTURE.md（只加 L-095 一行） | by 总调度 fredw-2b 11-02 00:2x：“MASTER_PICTURE §1 补一行 L-095……CONSENT 写 RECALL → CODERSI”

- CONSENT: AUTOPILOT -> ITERAUDIT : tools/pipeline/writer_prompt.py | by 总调度 fredw-2b 11-01：“tools/pipeline/writer_prompt.py 归 WORKFLOW（它在做紧急任务），总调度授权你改，在 docs/uimaster/LOCKS.md 写 CONSENT”（G29 方案 A 镜数上限；RSI 代录）
- CONSENT: RECALL -> ITERAUDIT : tools/qa/decision_check.py | by 总调度 fredw-2b 11-01：“RECALL 名下的 decision_check.py、owner_decisions.yaml、MASTER_PICTURE.md 由总调度认领……写 CONSENT”（RSI 代录）
- CONSENT: RECALL -> ITERAUDIT : config/owner_decisions.yaml | by 总调度 fredw-2b 11-01（同上）
- CONSENT: RECALL -> ITERAUDIT : docs/master/MASTER_PICTURE.md | by 总调度 fredw-2b 11-01（同上；§4 缺口表）
- CONSENT: ASSETUX -> ITERAUDIT : services/api/ns_api/character_hub.py | by 总调度 fredw-2b 11-01：“后端校验：设为身份脸时，图的宽高比和人脸占比必须像脸部裁切，否则拒绝（YuNet 已有）”（只改 set_face + 新 face_crop_check；RSI 代录）
- CONSENT: UIRSI -> ITERAUDIT : services/api/ns_api/takes_ui.py | by 总调度 fredw-2b 11-01 r5：“修根因：所有改当前版本的操作都只走一个带审计的入口，被总调度 / 项目方驳回过的版本不能再设为当前”（只改 reject 退回逻辑 + unset 补审计；RSI 代录）
- CONSENT: UIRSI -> ITERAUDIT : tests/test_takes_ui_uirsi.py | by 总调度 fredw-2b 11-01 r5（同上：set_active 桩加 **kw）
- CONSENT: REFLOCK -> VQAGATE : services/agent/ns_agent/gen_contract/postflight.py | by 总调度 fredw-2b 11-01 晚：“给 VQAGATE 补 CONSENT：postflight / producer / build_jobs / score_clip 的局部改动，总调度授权”（RSI 代录）
- CONSENT: PRODUCER -> VQAGATE : tools/autopilot/producer.py | by 总调度 fredw-2b 11-01 晚：“给 VQAGATE 补 CONSENT：postflight / producer / build_jobs / score_clip 的局部改动，总调度授权”（RSI 代录）
- CONSENT: VIDEO10 -> VQAGATE : tools/series10_video/build_jobs.py | by 总调度 fredw-2b 11-01 晚：“给 VQAGATE 补 CONSENT：postflight / producer / build_jobs / score_clip 的局部改动，总调度授权”（RSI 代录）
- CONSENT: VIDEO10 -> VQAGATE : tools/series10_video/score_clip.py | by 总调度 fredw-2b 11-01 晚：“给 VQAGATE 补 CONSENT：postflight / producer / build_jobs / score_clip 的局部改动，总调度授权”（RSI 代录）
- CONSENT: ASSETUX -> ITERAUDIT : tests/test_character_hub_assetux.py | by 总调度 fredw-2b 11-01 r5（L-086：set_face 加脸部裁切校验后，测试补一条校验用例、旧用例桩掉校验；RSI 代录）
- CONSENT: AUTOPILOT -> ITERAUDIT : tools/pipeline/image_jobs.py | by 总调度 fredw-2b 11-01 晚：“image_jobs.py 归 AUTOPILOT（WORKFLOW 在忙服务器启动），这次授权你改，CONSENT 写 AUTOPILOT → ITERAUDIT”（K-OPS-Q24：作业来源改导入稿 + G21 核 sha；RSI 代录）
- CONSENT: AUTOPILOT -> ITERAUDIT : tools/pipeline/submit_jobs.py | by 总调度 fredw-2b 11-01 晚：“image_jobs.py 归 AUTOPILOT（WORKFLOW 在忙服务器启动），这次授权你改，CONSENT 写 AUTOPILOT → ITERAUDIT”（K-OPS-Q24：作业来源改导入稿 + G21 核 sha；RSI 代录）
- CONSENT: AUTOPILOT -> ITERAUDIT : tools/autopilot/full_redo.py | by 总调度 fredw-2b 11-01 晚：“image_jobs.py 归 AUTOPILOT（WORKFLOW 在忙服务器启动），这次授权你改，CONSENT 写 AUTOPILOT → ITERAUDIT”（K-OPS-Q24：作业来源改导入稿 + G21 核 sha；RSI 代录）
- CONSENT: AUTOPILOT -> ITERAUDIT : config/pipeline/chain.yaml | by 总调度 fredw-2b 11-01 r7：“请按 G0 全量同步：时长……所有写着 50–75 / 60–65 的地方”（D-SCR-08；RSI 代录）
- CONSENT: AUTOPILOT -> ITERAUDIT : docs/PIPELINE_CHAIN.md | by 总调度 fredw-2b 11-01 r7：“请按 G0 全量同步：时长……所有写着 50–75 / 60–65 的地方”（D-SCR-08；RSI 代录）
- CONSENT: SCRIPT_RSI -> ITERAUDIT : tools/script_rsi/hollywood.py | by 总调度 fredw-2b 11-01 r7：“请按 G0 全量同步：时长……所有写着 50–75 / 60–65 的地方”（D-SCR-08；RSI 代录）
- CONSENT: REFLOCK -> ITERAUDIT : tests/test_ref_switch_assets.py | by 总调度 fredw-2b 11-01：“test_ref_switch_assets 写真实数据，这是测试本身的 bug，改成用临时目录”（RSI r3 代录）
- CONSENT: ITERAUDIT -> RESEARCH : tools/qa/writer_lints.py | by 总调度 fredw-2b 11-01：“RESEARCH 改 writer_lints.py 的越界由总调度认领”（QW-W9；RSI 代录）
- CONSENT: EDITDEL -> UIMASTER : apps/web/src/ds/editdel.tsx | 总调度 11-01 代录（UIMASTER 转录）：“The 9 EDITDEL-owned open issues are yours, since EDITDEL is inactive. Register them in LOCKS.”
- CONSENT: EDITDEL -> UIMASTER : apps/web/src/v3/edit/** | 总调度 11-01 代录（UIMASTER 转录）：“EDITDEL is inactive, so the refine-page items … come to you. The scope is the files under apps/web/src/v3/edit/**. Register them in LOCKS.md and write through safe_write.”
- CONSENT: UIPIXEL -> UIRSI : apps/web/src/ds/live.css | UIPIXEL 11-01：“live.css 写完交我接管没问题”（总调度转录，ITERAUDIT）
- CONSENT: UIRSI -> PRODUCER : apps/web/src/v3/pages/NewScriptPage.tsx | 总调度 11-01（UIRSI 已审：“继续写 / 接着写到…”收进“⋯ 手动插队 / 重做”、挂 ProducerPanel，功能都在）
- CONSENT: EDITDEL -> UIPIXEL : apps/web/src/v3/pages/AuditRoute.tsx | 总调度 11-01（EDITDEL 不活跃）
- CONSENT: EDITDEL -> UIPIXEL : apps/web/src/v3/AuditDrawer.tsx | 总调度 11-01（EDITDEL 不活跃；操作记录表格实际在这个文件里，AuditRoute.tsx 只是外壳，按同一授权）
- CONSENT: VOICE10 -> UIPIXEL : apps/web/src/v3/pages/SoundPage.tsx, apps/web/src/v3/sound/** | 总调度 11-01（VOICE10 不活跃，声音页“候选 n”点击区）
- CONSENT: 总调度 -> UIRSI : apps/web/src/components/Dialogs.tsx | 总调度 11-01（提示条位置与点击穿透）
- CONSENT: GPUVIEW -> UIRSI : apps/web/src/components/RenderTasks.tsx | GPUVIEW 11-01：同意 PW-019 把非组件导出（ago、countRows、filterRows、fmtS、humanErr、refreshRenderTasks、useRenderTasks）挪到 components/RenderTasks.helpers.ts 并改导入方（Drawer.tsx、GpuPanel.tsx、TopBarV3.tsx）；tests/test_gpuview.py::test_queue_badge_uses_same_filter 断言 countRows 在 RenderTasks.tsx，挪后请一并改成查 helpers 文件
- CONSENT: UIRSI -> UIMASTER : apps/web/src/components/Dialogs.tsx | UIRSI 11-01：同意 UIMASTER 改 Palette 关闭后焦点回位（复用 ds useFocusTrap，UM-0408）
- CONSENT: UIRSI -> DATAALIGN : services/api/ns_api/shot_audio.py | 总调度 11-01（UIRSI 已审：配乐镜号取剧本真实镜号、加 stale_timeline）
- CONSENT: AUTOPILOT -> BGM10 : config/pipeline/chain.yaml, docs/PIPELINE_CHAIN.md | 总调度 11-01（AUTOPILOT 不活跃；新增 P4-P9.bgm 链接）
- CONSENT: UIRSI -> BGM10 : services/api/ns_api/shot_audio.py | 总调度 11-01（_music_dir 指向 series10、挂 bgm 路由）
- CONSENT: AUTOPILOT -> DATAALIGN : tools/pipeline/register_takes.py | 总调度 11-01（AUTOPILOT 不活跃；--video10 视频登记 + retract_stale_video10，D-VIDEO 任务）
- CONSENT: UIRSI -> UIMASTER : apps/web/src/v3/**（仅 PW-019 导入路径改写：只改 import 行的路径，不碰其他逻辑；每步先在沙盒跑 tsc） | UIRSI 11-01
- CONSENT: DATAALIGN -> UIRSI : tools/qa/data_parity.py | by 总调度 fredw-2b 11-02 r40 紧急派单（项目方 00:0x：“图片生成错误,你刷新了图片库没有?”；00:1x：“在 UI 里面做一个错误标志吧”；误点事故 23:57）：“data_parity 加一项检查：界面显示的候选必须属于现行剧本版本，加进 iter_gate”
- CONSENT: UIPIXEL -> UIRSI : apps/web/src/v3/shotstatus.css | by 总调度 fredw-2b 11-02 r40 紧急派单（项目方 00:0x：“图片生成错误,你刷新了图片库没有?”；00:1x：“在 UI 里面做一个错误标志吧”；误点事故 23:57）（新建状态标签样式）
- CONSENT: ASSETUX -> UIRSI : apps/web/src/v3/assets/PeopleHub.tsx | by 总调度 fredw-2b 11-02 r40 紧急派单（项目方 00:0x：“图片生成错误,你刷新了图片库没有?”；00:1x：“在 UI 里面做一个错误标志吧”；误点事故 23:57）：“对象如果有项目方已定的决策锁……点选时弹一个一键确认……悬停或者翻看候选时不触发更换，必须明确点‘用这张’才生效”
- CONSENT: GPUVIEW -> UIRSI : apps/web/src/components/RenderTasks.tsx | by 总调度 fredw-2b 11-01 r39：“r38 顶栏变挤的问题，总调度的决定是 A + C……‘渲染任务’那段字缩短，CONSENT 写 GPUVIEW → UIRSI；卡片里‘ComfyUI 离线’改成大白话”
- CONSENT: GPUVIEW -> UIRSI : services/api/ns_api/gpu_live.py | by 总调度 fredw-2b 11-01 r38 派单：“全局实时连接状态条……GPU 卡片里‘暂时连不上 N 秒’要说明原因……‘最近出图’缩略图裂图：查原因……修根因”
- CONSENT: UIPIXEL -> UIRSI : apps/web/src/v3/infra.css | by 总调度 fredw-2b 11-01 r38 派单：“全局实时连接状态条……GPU 卡片里‘暂时连不上 N 秒’要说明原因……‘最近出图’缩略图裂图：查原因……修根因”（新建样式，UIPIXEL 不在岗）
- CONSENT: UIPIXEL -> UIRSI : apps/web/src/ds/ZoomLayer.tsx | by 总调度 fredw-2b 11-01 r37：“P1-1 ZoomLayer：派给你，修法是让帧格自己处理点击，守住 G11 小图仍可放大”
- CONSENT: ASSETUX -> UIRSI : apps/web/src/v3/assets/PeopleHub.tsx | by 总调度 fredw-2b 11-01 r37：“人物中心的‘设为身份脸’只允许脸部裁切……前端在非脸部裁切图上不显示这个按钮，或者点了给出说明；不许删功能”
- CONSENT: UIPIXEL -> UIRSI : apps/web/src/v3/regen.css | 总调度 11-01 r36 代录：“UIPIXEL 现在没在跑，这项归你做：在 LOCKS 登记 ux4.css 等相关文件的临时锁，改完释放”
- CONSENT: ASSETUX -> UIRSI : apps/web/src/v3/assets/AssetCenter.tsx | 总调度 11-01 r36 代录：“ASSETUX 现在没在跑，也归你做（AssetCenter.tsx、PeopleHub.tsx、P1Panels.tsx），用你 r35 的同一套做法”
- CONSENT: ASSETUX -> UIRSI : apps/web/src/v3/assets/PeopleHub.tsx | 总调度 11-01 r36 代录：“ASSETUX 现在没在跑，也归你做（AssetCenter.tsx、PeopleHub.tsx、P1Panels.tsx），用你 r35 的同一套做法”
- CONSENT: ASSETUX -> UIRSI : apps/web/src/v3/assets/P1Panels.tsx | 总调度 11-01 r36 代录：“ASSETUX 现在没在跑，也归你做（AssetCenter.tsx、PeopleHub.tsx、P1Panels.tsx），用你 r35 的同一套做法”
- CONSENT: ASSETUX -> UIRSI : apps/web/src/v3/pages/ScenesTab.tsx | 总调度 11-01 r36 代录：“ASSETUX 现在没在跑，也归你做（AssetCenter.tsx、PeopleHub.tsx、P1Panels.tsx），用你 r35 的同一套做法”（ScenesTab 同类，一并）
| services/api/ns_api/script_inbox.py（只加 PRODUCER 系统身份：令牌 + run、0 阻断、replace 遇项目方定稿 = 闸门、审计） | PRODUCER（总调度 11-01 定） | 加完即释放 |
| services/render_router/ns_render/auto_current.py（新建：G3 过契约即设为当前，全系统唯一） | PRODUCER | 长期 |
| ns_render/unified_frame.py（run_postflight 末尾调 on_contract、record_params 不再直接设当前、sweeper 也续算编辑链）、ns_render/frame_edit.py（edit_frame 入库不设当前 + 起契约）、tools/pipeline/register_takes.py（设当前改调 on_contract） | PRODUCER（G3，已告知 REFLOCK） | 本次改完即释放 |

CONSENT: AUTOPILOT -> PRODUCER : docs/AUTOPILOT.md | 总调度 11-01
| tools/series10_imggen/imggen.py（首帧改走唯一出图路径，总调度 11-01 交 REFLOCK 接管） | REFLOCK | 长期（IMGGEN 已停） |



| services/agent/ns_agent/frame_job.py（外层单品写进出图正文，K-REN-101）、services/api/ns_api/unified_stale.py（match_target 认新说明，与 DATAALIGN 协调） | PRODUCER | 本次改完即释放 |

CONSENT: REFLOCK -> PRODUCER : services/agent/ns_agent/frame_job.py (outer-layer items) | 总调度 11-01 07:35 (REFLOCK 限流)
CONSENT: AUTOPILOT -> PRODUCER : tools/iterate_loop/submitter.py、services/api/ns_api/recipe_render.py（@look: 占位符）| 总调度 11-01 批准（AUTOPILOT 未在岗）

| packages/qc/ns_qc/gaze.py、tools/acting/**、docs/acting/**、knowledge/rules/acting.yaml、tools/qa/acting_lints.py、tests/test_acting_*.py（新建：视线 / 首秒定格 / 字幕带检测，表演规则） | ACTING（总调度 11-01，R11-2/3/6/8/9） | 长期 |
| tools/vqa/**、services/agent/ns_agent/vqa/**、config/vqa.json、config/prompts/vqa_inspect.md、config/prompts/vqa_judge.md、knowledge/rules/vqa.yaml、tests/test_vqa.py、data/vqa/**、docs/vqa/**（新建：本地看图复核 Q9 / V9、R11-10 判定闭环、4K SOP；gpu36 /root/work/fredw/vqa) | VQA（总调度 11-01 派：R11-4/5/7/10；归属请 ITERAUDIT 写进 ownership.yaml） | 长期 |
| services/agent/ns_agent/gen_contract/postflight.py（只加 Q9 / V9 一行调用 ns_agent.vqa.contract，已发 REFLOCK 请其改或授权）、tools/series10_video/score_clip.py（只加 score["vlm"]，已发 VIDEO10）、tools/autopilot/producer.py（只加 review_round 记录，已发 PRODUCER） | 待 owner（VQA 只提议，不动） | — |
| tools/video_rca/**、docs/video_rca/**、data/ab/video_rca/**、data/review_pages/video_rca/**、knowledge/rules/render_video_rca.yaml、tests/test_video_rca*.py（新建：视频问题根因实验台 / 规则）；gpu36:2 实验（client_id videorca-，让道生产长镜头） | VIDEO-RCA（总调度 fredw-2b 派，W11） | 长期 |
| services/recipes/ns_recipes/prompt.py（只改：FACING_EN“镜头”译法去掉 facing the camera；新增 hide_offframe_parts 开关函数）、services/recipes/ns_recipes/lint.py（只加 RL-E3：系统编译句不得含 camera / lens 朝向）、services/recipes/recipes/_base.yaml（prompt.hide_offframe_parts + provenance）、tests/test_video_rca.py | VIDEO-RCA（AUTOPILOT 不在岗，总调度 W11 派） | 本轮收轮即释放 |
- CONSENT: ITERAUDIT -> SCRIPT-RSI : tools/validate_qwen_script.py、tools/qa/acting_lints.py、tests/test_acting_lints.py、knowledge/rules/writer_iteration.yaml、knowledge/rules/writer_camera.yaml、config/recipes/writer_knowledge.md、config/recipes/director_system_prompt.md、config/script_chat_rules_appendix.md | by 总调度 fredw-2b 11-01（K-OPS-Q22；D-SCR-07 表演 / 导演 / 镜头规则补全与返修）
- CONSENT: REFLOCK -> SCRIPT-RSI : services/agent/ns_agent/frame_job.py（eyeline_note 逐人覆盖）、services/agent/ns_agent/framing.py（two_shot_clause 去掉朝向镜头，K-REN-703） | by 总调度 fredw-2b 11-01 派单“查清 frame 编译器……视线句是否对所有镜头都生效，没生效的修上”
- CONSENT: RECALL -> SCRIPT-RSI : docs/master/MASTER_PICTURE.md §1、config/owner_decisions.yaml（D-SCR-07） | by 总调度 fredw-2b 11-01
- CONSENT: VQAGATE -> SCRIPT-RSI : docs/acting/PERFORMANCE_RULES.md（补 D-SCR-07 规则表、⤴ 统一口径） | by 总调度 fredw-2b 11-01
- 新目录 tools/script_rsi/**、data/script_rsi/**、tests/test_script_rsi_full_repair.py：SCRIPT-RSI（建议总调度登记进 ownership.yaml）
- CONSENT: ITERAUDIT -> CLEANUP : config/script_chat_rules.md（只改第 106 行统一风格后缀旧口径“徕卡、大光圈、浓郁暖调”→ 现行 S★） | by 总调度 fredw-2b 11-01 18:3x CLEANUP 派单：“writer_knowledge.md、director_system_prompt.md、script_chat_rules 及其附录里的旧人名、旧示例……都清掉。这些文件各有 owner，改之前写 CONSENT（by 总调度 fredw-2b）”
- CONSENT: 无主（写作方） -> CLEANUP : config/script_chat_rules_appendix.md（只删旧 60 集人名 / 分集表 / 地点表 / 已被取代的风格后缀与出图调度句；原件备份 data/_quarantine_20261101b/config_orig/） | by 总调度 fredw-2b 11-01 18:3x CLEANUP 派单（同上）
- CONSENT: RESEARCH -> CLEANUP : knowledge/rules/research_realism.yaml（K-REV-X01 / K-REN-X02 / K-PRM-X04 已标 ⤴ 不采纳 → 移到 knowledge/archive/） | by 总调度 fredw-2b 11-01 18:3x CLEANUP 派单：“knowledge/rules 里状态是 ⤴ 被取代……的规则，移到 knowledge/archive/（保留可追溯），从 generated 里剔除”
- CONSENT: CHAINSPEC / UIRSI / ARCH -> CLEANUP : knowledge/rules/chain_v1.yaml（K-EDT-I02）、knowledge/rules/ui.yaml（K-UI-019）、knowledge/rules/writer.yaml（K-WRT-008）移到 knowledge/archive/；tools/knowledge/compile.py 加 archived_ids（supersedes / RSI_LEDGER 指向归档条目算存在） | by 总调度 fredw-2b 11-01 18:3x CLEANUP 派单（同上）
- CONSENT: 共享 -> CLEANUP : knowledge/rules/edit.yaml（只改 K-EDT-013 标题里“对白兜底仍用 Kokoro”旧口径，指向 K-EDT-016 / L-078） | by 总调度 fredw-2b 11-01 18:3x CLEANUP 派单
- CONSENT: fredw-92（render_endpoints / endpoints / jobs）/ PRODUCER -> LOCALGPU : config/render_endpoints.json（lanes 加 laptop:0 一条，image_only + hold）、services/render_router/ns_render/endpoints.py（加 image_only / held / image_lanes，image_only 道 max_frames=0）、services/api/ns_api/jobs.py（lanes() 带 image_only / hold，pick_lane / resolve_lane 视频不派 image_only 道、hold 道不自动派）、tools/autopilot/producer.py（出图道表并入 render_endpoints 的 image_only 道，hold 道按 hold_lanes 处理）——只做局部改动 | by 总调度 fredw-2b 11-01 18:3x LOCALGPU 派单：“在 config/render_endpoints.json 加一条道 laptop:0（image_only，并发 1），producer 能派单到这条道……改 render_endpoints / producer 前在 docs/uimaster/LOCKS.md 写 CONSENT（by 总调度 fredw-2b），只做局部改动”
- CONSENT: ITERAUDIT -> CLEANUP : tools/qa/ownership.yaml（只加一行 CLEANUP 归属：新工具 / 测试 / ops_cleanup.yaml / knowledge/archive / 隔离区，以及原无主的 config/script_chat_rules_appendix.md、docs/owner_requirements_for_writer.md） | by 总调度 fredw-2b 11-01 18:3x CLEANUP 派单
- CONSENT: 无主 / ITERAUDIT -> CLEANUP : config/script_chat.json（header_sources）、config/script_mainline.json（mainline）改指 series10 现行导入稿 rsiD07（导入后 script_v2 sha d1701401…） | by 总调度 fredw-2b 11-01 CLEANUP r2：“R15：同意。header_sources 和 script_mainline.json 改指 series10 合并稿……你来改，写 CONSENT”
- CONSENT: ITERAUDIT / ARCH -> CLEANUP : packages/schema/ns_schema/upstream_common.py（CHAR_ID_RE）、packages/schema/ns_schema/storyline.py（SL-03 注释与文案）、tools/validate_qwen_script.py（QW-P2 文案）去掉 alex/ryan/kai/leo；不新增 lint 号 | by 总调度 fredw-2b 11-01 CLEANUP r2：“R16：同意去掉……由你清，写 CONSENT（by 总调度），跑相关测试。lint 号别撞”
- CONSENT: REFLOCK -> CLEANUP : config/visual_bible.toml [look].fallback_suffix 改为 S★ 原文 | by 总调度 fredw-2b 11-01 CLEANUP r2：“R17：改成 S★ 原文（L-087……项目设置页要显示现行口径）”
- CONSENT: AUTOPILOT -> CLEANUP : tools/autopilot/roles.py:76（K-EDT-I02 → 现行 K-EDT-016 / K-EDT-013） | by 总调度 fredw-2b 11-01 CLEANUP r2：“R18：roles.py:76 改为引用现行规则，CONSENT 写 AUTOPILOT → CLEANUP”
- CONSENT: CLEANUP -> ITERAUDIT : config/script_chat_rules_appendix.md、docs/owner_requirements_for_writer.md 归属改回 ITERAUDIT（写作合同 owner），CLEANUP 作协作者 | by 总调度 fredw-2b 11-01 CLEANUP r2 决定 8
- CONSENT: 无主 -> CLEANUP : services/api/ns_api/script_chat.py compact_header（全剧人物表 / 场景表改为全部保留：R15 换成自带全剧表的 series10 稿后，继承的新角色在第二张表里会被丢掉，tests/test_script_chat.py::test_registry_inherited_into_header 抓到） | by 总调度 fredw-2b 11-01 CLEANUP r2 决定 2（R15）
- CONSENT: DATAALIGN -> CLEANUP : tools/qa/data_parity.py（D-SCRIPT 只和导入稿比；P4 对照仅 NS_ALLOW_P4_SOURCE=1） | by 总调度 fredw-2b 11-01 CLEANUP r2 补充：“最要紧的是 data_parity 的 D-SCRIPT 还拿 P4 原文做比对，要改成和导入稿比对……改别人的文件写 CONSENT”
- CONSENT: BGM10 -> CLEANUP : tools/bgm/bgm_timeline.py（episode_inputs 改取导入稿来源 md 的本集原文，sha 核对；P4 仅 NS_ALLOW_P4_SOURCE=1 兜底） | by 总调度 fredw-2b 11-01 CLEANUP r2 补充（同上）
- CONSENT: ASSETMASTER -> CLEANUP : tools/assetmaster/frames_v2.py（改读 IJ.import_episode） | by 总调度 fredw-2b 11-01 CLEANUP r2 补充（同上）
- CONSENT: REFLOCK -> CLEANUP : tools/gen_contract/look_audit.py、calibrate_imgfix.py、reflock_v9.py、reflock_validate.py（调研 / 标定用途显式设 NS_ALLOW_P4_SOURCE） | by 总调度 fredw-2b 11-01 CLEANUP r2 补充（同上）
- CONSENT: IMGGEN -> CLEANUP : tools/series10_imggen/imgfix_ab.py（显式放行，对照实验）、scene_plates.py（未设 NS_ALLOW_P4_SOURCE 就退出） | by 总调度 fredw-2b 11-01 CLEANUP r2 补充（同上）
- CONSENT: VQAGATE -> LOCALGPU : tools/vqa/server.py、config/vqa.json、D:\ns_vqa\start.ps1（本机看图服务改“让道”：本机 ComfyUI 18388 队列空 ≥20 s 才加载、加载前 /free 本机 ComfyUI、来出图活立即卸载、VQA_IDLE_S=60、记切换耗时）；tools/autopilot/producer.py（攒批交看图）；tools/gen_contract/**（本机契约度量 Q1/Q3/Q5/Q6） | by 总调度 fredw-2b 11-01 晚 LOCALGPU 续派：“ns_vqa 改成和 gpu36 一样的让道模式……ns_vqa 归 VQAGATE（已收工），CONSENT 写 VQAGATE → LOCALGPU，by 总调度”
- CONSENT: 无主 / DATAALIGN -> CLEANUP : services/api/ns_api/script_chat.py（script_header 先用导入记录推导的来源）、services/api/ns_api/script_inbox.py（mainline_paths = 推导 ∪ 配置）、新 services/api/ns_api/import_sources.py、tools/qa/data_parity.py（pending_redo） | by 总调度 fredw-2b 11-01 CLEANUP r3：“header_sources 和 script_mainline 改成从 script_v2.json 登记的现行导入来源自动推导……写测试和规则”；“在 data_parity 里把‘新剧本已导入、出图未跟上’的镜标成 pending_redo”

- CONSENT: VIDEO10 -> AUTOPILOT : tools/series10_video/vidgen.py | 总调度 2026-11-01 18:22（AUDIT P1：派单前按 L-088 政策重查，K-OPS-Q24）
- CONSENT: VIDEO10 -> AUTOPILOT : data/pipeline/runs/series10_v1/video/recipe_choice.json | 总调度 2026-11-01 18:0x（L-088 全部 Pika）
- CONSENT: RECALL -> AUTOPILOT : docs/master/NIGHT_PLAN_20261101.md | 总调度 2026-11-01 18:0x（L-088 同步 / §4a）
- CONSENT: RECALL -> AUTOPILOT : config/owner_decisions.yaml | 总调度 2026-11-01 18:0x（L-088 断言）
- CONSENT: VIDEO10 -> AUTOPILOT : tools/series10_video/deploy.py | 总调度 2026-11-01 18:22（vidgen 派单政策文件随部署推送，K-OPS-Q24）
- CONSENT: VIDEO10 -> AUTOPILOT : tools/series10_video/upscale_preview.py | 总调度 2026-11-01 19:0x（VIDEO-RCA r1：Pika 去抖接进合成链路，PROD 已收工）
- CONSENT: VIDEO10 -> AUTOPILOT : tools/series10_video/night.py | 总调度 2026-11-01 19:0x（同上：assembly_sources 认去抖版）
- CONSENT: PRODUCER -> AUTOPILOT : tools/autopilot/producer.py | 总调度 2026-11-01 19:3x（CLEANUP D-LEDGER：master_reject 驳回即撤下后账本同步待重出；PROD 已收工）
- CONSENT: AUTOPILOT -> VIDEO_RCA : services/recipes/ns_recipes/prompt.py | by 总调度 fredw-2b 11-01 19:2x 派 r2：“O1：授权你改 services/recipes 的 prompt.py、lint.py、_base.yaml”
- CONSENT: AUTOPILOT -> VIDEO_RCA : services/recipes/ns_recipes/lint.py | by 总调度 fredw-2b 11-01 19:2x 派 r2：“O1：授权你改 services/recipes 的 prompt.py、lint.py、_base.yaml”
- CONSENT: AUTOPILOT -> VIDEO_RCA : services/recipes/recipes/_base.yaml | by 总调度 fredw-2b 11-01 19:2x 派 r2：“O1：授权你改 services/recipes 的 prompt.py、lint.py、_base.yaml”
- CONSENT: REFLOCK -> VIDEO_RCA : services/agent/ns_agent/framing.py（只改 two_shot_clause 措辞） | by 总调度 fredw-2b 11-01 19:2x：“现在就把 framing.two_shot_clause 改成你实测有效的句子……CONSENT 写 REFLOCK → VIDEO_RCA”
- CONSENT: SCRIPT_RSI -> VIDEO_RCA : tests/test_script_rsi_eyeline.py（只改 two_shot 一条断言，随 framing 证据例外） | by 总调度 fredw-2b 11-01 19:2x r2 决定 3（“它和 SCRIPT-RSI 的‘只写正向句’规则冲突，这里按证据例外处理”）
- CONSENT: ITERAUDIT -> VIDEO_RCA : knowledge/rules/writer_iteration.yaml（只改 K-WRT-702 证据：补“只管整件消失”的限定） | by 总调度 fredw-2b 11-02 r4 派：“你直接在 writer_iteration.yaml 的 K-WRT-702 证据里补一条……CONSENT 写 ITERAUDIT → VIDEO_RCA，然后跑 compile”
- CONSENT: 总调度 -> VIDEO_RCA : tests/test_video_rca.py | by 总调度 fredw-2b 11-01 19:2x：“tests/test_video_rca.py 你自己补登”- CONSENT: DATAALIGN -> CLEANUP : tools/qa/data_parity.py（pending_redo 过期上限 + A-PARITY-PENDING 报警）、新 config/data_parity.json | by 总调度 fredw-2b 11-01 AUDIT P2：“pending_redo 超过 N 小时……单列为‘过期待重做’，并写一条 data/qa/alerts.jsonl 报警”
- CONSENT: LOCALGPU -> VQAGATE : services/render_router/ns_render/comfy_client.py | by 总调度 fredw-2b 11-01 20:3x：“最短看图窗口由你实现：server.py 归你，comfy_client 的 _yield_peer 和 D:
s_vqastart.ps1 归 LOCALGPU（已收工），CONSENT 写 LOCALGPU → VQAGATE”（本轮只改了 server.py；_yield_peer 没改）
- CONSENT: LOCALGPU -> VQAGATE : D:/ns_vqa/start.ps1 | 同上，by 总调度 fredw-2b；补记 20:2x 插的两行：VQA_CAP_SUBJECT_PX/REF_PX/TOKENS + VQA_ATTN（口径 B）
- CONSENT: REFLOCK -> IMGFIX : services/agent/ns_agent/asset_refs.py（K-AST-262 设定图单品检查缺口句）、services/agent/ns_agent/frame_job.py（单人视线修法） | by 总调度 fredw-2b 11-01 19:4x 派单：“改别人的文件写 CONSENT（REFLOCK / AUTOPILOT → IMGFIX，by 总调度 fredw-2b）”
- CONSENT: ASSETUX -> IMGFIX : services/api/ns_api/character_hub.py（只改 _sheet_candidates：adopted v2 进候选、现行那张永远在候选、标单品检查） | by 总调度 fredw-2b 11-01 19:4x 同上派单
- CONSENT: AUTOPILOT -> IMGFIX : data/pipeline/runs/series10_v1/assets/first_frame_jobs.json（tools/pipeline/image_jobs.py 重编） | by 总调度 fredw-2b 11-01 19:4x 同上派单：“重编 first_frame_jobs.json”
- CONSENT: PROMPT -> IMGFIX : tools/prompt_v2/audit_framing.py（首句检查跳过 K-REN-704 单人朝向句） | by 总调度 fredw-2b 11-01 19:4x 派单（改别人的文件写 CONSENT）
- CONSENT: REFLOCK -> IMGFIX : tests/test_gen_contract.py、tests/test_image_jobs.py、tests/test_unified_frame.py（“提示词以图1句开头”断言改为先去掉 K-REN-704 单人朝向句）；新建 tests/test_imgfix.py、tools/imgfix/** | by 总调度 fredw-2b 11-01 19:4x 派单
- CONSENT: AUTOPILOT -> NETFIX : ops/offline/resident_prep.py（control() 非 video-only 时改调 tools/netfix/dispatch.py：only = 分区 ∩ ready_episodes、hold = 别机的道 + laptop:0、paused 跟随笔记本全局暂停）、tools/autopilot/infra_watchdog.py（监管进程心跳新鲜时只探测 / 报警，不杀 ssh、不拉循环）——只做局部改动，和 WORKFLOW 错开 | by 总调度 fredw-2b 11-01 22:1x NETFIX 派单：“WORKFLOW 拥有 resident_sync.py、full_redo.py、ops/offline/**；你要改它们，先在 LOCKS 写 CONSENT（AUTOPILOT → NETFIX，by 总调度 fredw-2b），只做局部改动”
- CONSENT: PRODUCER -> NETFIX : data/producer/control.json（只经 tools/netfix/dispatch.py apply-laptop 写 only / hold_lanes / dispatch_by，不动 paused）；tools/autopilot/producer.py 本轮未改 | by 总调度 fredw-2b 11-01 22:1x NETFIX 派单：“producer.py 归 PRODUCER（不在岗），CONSENT 写 PRODUCER → NETFIX”
- CONSENT: VQAGATE -> NETFIX : services/agent/ns_agent/vqa/client.py（加 _lan_url：服务器上走 gpu36 内网入口 10.0.0.36:8870）、config/vqa.json（model.lan_url） | by 总调度 fredw-2b 11-01 22:1x NETFIX 派单第 3 项：“gpu33 的 vqa client 先连 10.0.0.36:8870”
- CONSENT: 无主 -> NETFIX : ops/autostart/**（tunnel.sh / tunnel_gpu36.sh 退役为调用监管进程、laptop_autostart.ps1 改 ensure 监管进程）；新 tools/netfix/**、config/netfix/**、data/netfix/**、tests/test_netfix.py | by 总调度 fredw-2b 11-01 22:1x NETFIX 派单第 1 项：“所有转发改成由一个监管进程统一负责”
- CONSENT: VQAGATE -> NETFIX : tools/vqa/tunnel.ps1（退役为 ensure 监管进程；8871 → gpu36:8870 并入 tunnel_supervisor 的 gpu36 主连接） | by 总调度 fredw-2b 11-01 23:0x：“VQA 的 8871 隧道……现在就可以收编，收编前确认没有看图请求正在走这条隧道”
- CONSENT: REFLOCK -> NETFIX : services/render_router/ns_render/comfy_client.py（object_info 进程级 + 磁盘缓存 data/cache/comfy_object_info/，TTL 6 h，检查有问题先重拉再判；原版备份 data/_quarantine/netfix_20261101/comfy_client.py.bak） | by 总调度 fredw-2b 11-01 23:50：“producer.py、comfy_client 归 PRODUCER / REFLOCK，CONSENT 写 → NETFIX，by 总调度”
- CONSENT: 总调度 -> IMGFIX : docs/master/MASTER_PICTURE.md（只加 L-094 一行）、data/pipeline/runs/series10_v1/assets/shot_looks.json（旧镜号覆盖移入 _stale、L-094）、services/agent/ns_agent/compiler.py / framing.py / gen_contract/preflight.py（K-REN-705 / K-AST-263） | by 总调度 fredw-2b 11-02 00:2x：“MASTER_PICTURE §1 加 L-094，总调度授权你改，写 CONSENT”；“改 asset_refs / 编译器写 CONSENT（REFLOCK → IMGFIX，by 总调度）”
