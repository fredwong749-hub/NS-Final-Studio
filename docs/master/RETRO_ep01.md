# 第 1 集复盘（series10_v2）

<!-- retro_status: draft -->
> 生成：2026-11-03 03:07，tools/master/episode_retro.py。总调度勾完第 4 节后跑 `episode_retro.py done --run series10_v2 --episode 1`；没 done 之前第 2 集不能进“出图”（sop_gate）。
> 本集当前 SOP 阶段：导入闸门（gate=reopened import=reopened；代码判定 7 项未过（例：p4#QW-T1 ep01-S6：[QW-T1] 镜6 时长 7 秒，超过单镜上限 6 秒（V2 硬规则，L-137）：多出来的时间拆成新镜）；等写手交 ）

## 1. 指标（和上一集对比）

```
series10_v2 ep01  镜头 11
agent 调用：写手 20（作废 8）/ 评审 2 / 评委 15 {'fable': 5, 'opus': 5, 'sonnet': 5}；本地 VLM≈148
介入：54（手工命令 9，退稿 7，修后重排 7，手起 API 8，手工挂道 23）；卡点 51（阻断 26）
时间：P1 2.71h，P2→导入 1.32h，阶段 A Noneh（in_progress），阶段 B 1.82h（trial），项目方等待 125min
出图：64 张候选，通过 30（0.4688），每张通过图 2.13 次；preflight 挡掉 12 次
自动化 0.3232（{'system': 32, 'owner': 11, 'agent': 56}）；GPU 占用 0.1446；好莱坞分 None
空缺 2 项（见 nulls[]）
```
（第 1 集，没有上一集可比）

## 2. 本集卡点：怎么修、是否写进 SOP 和代码

共 51 条（未关 19，阻断 26）。

| 卡点 | 谁 | 步骤 | 什么事 | 怎么修（fix_hint） | 状态 | 写进 SOP | 写进代码 |
|---|---|---|---|---|---|---|---|
| ISS-1103-001014-cf0d | CAST-S | 0 | 没有“新角色/场景设定候选”的出图入口：golden_v2 只能出写死的女主一镜，我只能另写 tools/promptf | 资产阶段做成正式工具：按 P1 人物表/场景表批量出身份脸与场景候选，自带检查和候选页 | closed | ✅ | ❌ 没找到 |
| ISS-1103-001014-c7ea | CAST-S | 0 | 新角色没有身份脸/造型设定图，preflight I2、I3 必挂，没有“设定候选模式”；我在 cast_v2 里只豁免 | preflight 加 asset_stage 模式：文生图设定候选只豁免 I2/I3，其余照查，由系统写死不靠脚本自己 | closed | ✅ | services/agent/ns_agent/gen_contract/preflight.py |
| ISS-1103-001014-176b | CAST-S | 0 | Q9 看镜头判断不稳：同一张图结论与证据矛盾，约一半候选 untested；要求胸像正脸又与“不看镜头”规则冲突，只能改 | 设定图（正脸证件式胸像）单独一档：看镜头不判；或重问次数加到 2-3 次 | closed | ✅ | ❌ 没找到 |
| ISS-1103-001014-c5f6 | CAST-S | 0 | 借道和检查排队：看图只有一个本地 Qwen3-VL 队列，每张图 4 次看图约 2 分钟，GPU 空转；lanes.py | 资产阶段并行派单（lanes 批量 hold + 每道一个 worker），看图合并成一次提问（Q9+逐条+年龄+OCR | closed | ✅ | ❌ 没找到 |
| ISS-1103-001014-aace | CAST-S | 0 | 缺通用 OCR 和年龄观感检查工具，我用本地看图模型问话代替；候选页和 pick 通知也要手写 JSON（request | 做 tools 级 age/ocr 检查；加 owner_queue 投递函数 post_pick() | closed | ✅ | ❌ 没找到 |
| ISS-1103-003637-9d25 | AUTOPIPE-A | 8 资产就绪 | 阶段 A 需要总调度定：① config/pipeline/asset_worker.json 的 apply_meta | 建议：先开 apply_meta + push，等 CAST-S 四条 pick 选定后看 episode_ready； | closed | ✅ | ❌ 没找到 |
| ISS-1103-003720-f86a | SV17-O | 8 | sv-17 发版前测试不过，未 cut 未部署：tests/test_master_sop_tools.py::test | 系统层面：① episode_ready 的现状快照测试不要写死真实数据，改成对临时夹具断言，或把'当前预期缺口'放进一 | closed | ✅ | ❌ 没找到 |
| ISS-1103-003851-4541 | MASTER | 9 | golden_v2.vlm_prompt_check 写死某一镜的服装/场景描述（抹胸/白幕/亚克力椅；默认外滩风衣）， | 核对文本改为从该镜 P4 编译结果（cast/造型/场景）动态生成；加测试：两镜不同造型得到不同核对项 | closed | ✅ | tools/promptfix/golden_v2.py |
| ISS-1103-004546-a997 | OVERSIGHT-A | 8 资产就绪 | P0 登记断链：asset_jobs.register_pick 第 536 行 run = req.run 或 cur | register_pick / after_pick 的 run 优先取 find_job_by_pick(pick_i | closed | ✅ | ❌ 没找到 |
| ISS-1103-004547-6260 | OVERSIGHT-A | 8 资产就绪 | P1 owner_pick._replay_on_startup（第 398-407 行）在 API startup 事 | replay 放到后台线程或只由 CLI owner_pick.py replay 触发；启动只做占位不做推送 | closed | ✅ | ❌ 没找到 |
| ISS-1103-004547-ca20 | OVERSIGHT-A | 8 资产就绪 | P1 sheet 作业没有等 face 登记：preflight.ASSET_STAGE_WAIVE[sheet] 豁免 | generate 时脸没登记就不生成 sheet 作业，或 tick 派发 sheet 前检查 manifest cha | closed | ✅ | services/agent/ns_agent/gen_contract/preflight.py |
| ISS-1103-004549-cb05 | OVERSIGHT-A | 8 资产就绪 | P1 demo_v2 试跑污染真实数据：data/pipeline/asset_jobs/demo_v2/ 三个作业留在 | 删 data/pipeline/asset_jobs/demo_v2；voices_v2.json support_ca | closed | ✅ | tools/v2style/voice_v2.py |
| ISS-1103-004550-8787 | OVERSIGHT-A | 8 资产就绪 | P1 scene 作业提示词接的是人像风格后缀：试编译 scene-sk_white_cyc 得到“…人物被闪光打得很亮 | scene 作业用场景段 / 空镜专用后缀（去掉人物、皮肤句），time_of_day 与后缀光线一致；先 --comp | closed | ✅ | services/agent/ns_agent/gen_contract/preflight.py、services/agent/ns_agent/gen_contract/style.py |
| ISS-1103-005000-2af2 | SV17-O | 8 | L-126 疑似 V1 夹带：golden_v2 不带 --shot 时的默认金样（build_script）从 tes | 系统层面：默认金样改成从当前剧导入稿取一个指定镜（配置项，例如 runs.json 里的 golden_shot）；ve | closed | ✅ | tests/test_promptfix_v2.py、tools/promptfix/golden_v2.py、tools/qa/system_version.py |
| ISS-1103-005241-bf53 | SV17-O | 8 | L-130 段落标记泄漏进出图提示词：镜头有 scene_id 时，scene_detail 里的【幻想段】经 fram | 系统层面：在 build_first 组装完最终 prompt 之后统一调一次 ST.strip_segment_mar | closed | ❌ | services/agent/ns_agent/compiler.py、services/agent/ns_agent/frame_job.py、tests/test_promptfix_v2.py |
| ISS-1103-011049-7420 | OVERSIGHT-A | 8 资产就绪 | P0 第二个推进入口：owner_pick._replay_on_startup 挂在 FastAPI startup  | startup replay 只在看门狗管的正式实例跑（api_watchdog 给子进程设 NS_API_MANAGE | closed | ✅ | services/api/ns_api/app.py、services/api/ns_api/frame_jobs.py、tools/factory/api_watchdog.py |
| ISS-1103-011049-336c | OVERSIGHT-A | 8 资产就绪 | P2 缺口消失的作业不收尾：meta-name-ch_* 三条仍 pending（display_name 已在登记脸时 | generate 时把缺口已不在的 pending 作业标 done(gap_closed)；受控重启 resident | closed | ✅ | ❌ 没找到 |
| ISS-1103-011343-a0ff | V2CUT-O | 4 | V2 写作链的全局头仍取自 V1：ns_api.script_chat.script_header 从 V1 导入稿（P | script_header(cfg, registry, run=None)：非 legacy 剧 header_sou | closed | ✅ | services/api/ns_api/script_chat.py |
| ISS-1103-011516-79c4 | ASSET-WORKER | 8 资产就绪 | 资产作业 sheet-ch_jiang_yubai-A（江予白）连续失败：没有候选过检：seed 1200: Runti | 看 data/pipeline/asset_jobs/<run>/<job>.json 的 log；修好后把 state | closed | ✅ | ❌ 没找到 |
| ISS-1103-011516-d684 | ASSET-WORKER | 8 资产就绪 | 资产作业 sheet-ch_tang_yao-A（唐瑶）连续失败：没有候选过检：seed 1200: RuntimeEr | 看 data/pipeline/asset_jobs/<run>/<job>.json 的 log；修好后把 state | closed | ✅ | ❌ 没找到 |
| ISS-1103-011622-e6d4 | ASSET-WORKER | 8 资产就绪 | 资产作业 sheet-ch_zhuo_lin-A（卓琳）连续失败：没有候选过检：seed 1200: RuntimeEr | 看 data/pipeline/asset_jobs/<run>/<job>.json 的 log；修好后把 state | closed | ✅ | ❌ 没找到 |
| ISS-1103-013144-ebe9 | ASSET-WORKER | 8 资产就绪 | 资产作业 sheet-ch_jiang_yubai-A（江予白）连续失败：没有候选过检：seed 1200: Runti | 看 data/pipeline/asset_jobs/<run>/<job>.json 的 log；修好后把 state | closed | ✅ | ❌ 没找到 |
| ISS-1103-013144-c94f | ASSET-WORKER | 8 资产就绪 | 资产作业 sheet-ch_tang_yao-A（唐瑶）连续失败：没有候选过检：seed 1200: RuntimeEr | 看 data/pipeline/asset_jobs/<run>/<job>.json 的 log；修好后把 state | closed | ✅ | ❌ 没找到 |
| ISS-1103-013228-cab4 | AUTOFIX-O | 8 | 3 条 sheet 作业（卓琳/唐瑶/江予白 造型A）身份脸送参考已通过，但 preflight I4 不过：全身设定图 | 需总调度定：A) ASSET_STAGE_WAIVE[sheet] 加 I4（设定图就是造型的产出，单品图之后从设定图裁 | closed | ✅ | services/agent/ns_agent/gen_contract/preflight.py |
| ISS-1103-013251-c584 | ASSET-WORKER | 8 资产就绪 | 资产作业 sheet-ch_zhuo_lin-A（卓琳）连续失败：没有候选过检：seed 1200: RuntimeEr | 看 data/pipeline/asset_jobs/<run>/<job>.json 的 log；修好后把 state | closed | ✅ | ❌ 没找到 |
| ISS-1103-013358-10ac | HEADER-O | 3 | 待总调度定：写作规则正文（config/script_chat_rules.md、qwen_writer_system_ | 派 ITERAUDIT / 写作合同 owner 去 V1 化规则正文 + 换 P0-P1 示例；scrub 表留作兜底 | closed | ✅ | config/script_chat.json |
| ISS-1103-014614-86aa | OVERSIGHT-R | 8 | P2 非正式实例仍写缓存/留痕：decision_check.py:95 设的 NS_DISABLE_BG 无人读（se | api_snapshot.in_tests() 与 _dump_shot_cache 加 instance.startu | closed | ❌ | services/api/ns_api/api_snapshot.py、tools/qa/decision_check.py |
| ISS-1103-014614-9db2 | OVERSIGHT-R | 8 | P2 restart_api.ps1 / guard 小缺口：(1) ps1:77-79 Kill-Recorded 的 | Kill-Recorded kids 加 CreationDate>=父 判断；old_stopped 事件已带 lis | closed | ❌ | tools/uirsi/api_restart_guard.py |
| ISS-1103-022443-a371 | ASSET-WORKER | 8 资产就绪 | 资产作业 sheet-ch_jiang_yubai-A（江予白）连续失败：没有候选过检： | 看 data/pipeline/asset_jobs/<run>/<job>.json 的 log；修好后把 state | open | — | ❌ 没找到 |
| ISS-1103-023132-1c46 | METRICS-F | 9 | 集级指标已能算（tools/master/episode_metrics.py，ep01 summary 已出）；两件事 | 总调度批准后由 METRICS-F 跑 --hollywood-score；EPCHAIN-O 按 METRICS_SP | closed | ❌ | tools/factory/autoflow_resident.py |
| ISS-1103-023528-1509 | GOLDEN-O | 9 | 镜1（卓琳+祁念+唐瑶三人）编译出的 faces 只有 ch_zhuo_lin，preflight I2 拦下：露脸三人 | compiler/build_first 三人镜脸部参考板的 faces 追踪 / 参考槽，归编译线 | open | — | services/agent/ns_agent/asset_refs.py、services/agent/ns_agent/frame_job.py、services/agent/ns_agent/gen_contract/preflight.py |
| ISS-1103-023528-2869 | GOLDEN-O | 9 | build_first 目前没接 shot_spec_v2.yaml 镜头语言模板（tools/director/sho | 由总调度定：是否让编译线把 image_clauses_zh 接进 build_first（会改所有镜的 prompt  | open | — | config/compile/run_style.json、config/director/shot_spec_v2.yaml、services/agent/ns_agent/frame_job.py |
| ISS-1103-023528-dd39 | GOLDEN-O | 9 | 阶段 B 新代码要生效需重启 autoflow_resident（它缓存了旧 golden_worker / asset | 总调度批准后受控重启 resident；:8800 等下次发版重载 | open | — | ❌ 没找到 |
| ISS-1103-023529-71ed | GOLDEN-O | 9 | 两台服务器还在 sv-20261102-16，golden_v2 没有 --summary/--shot，system_ | 下一次 system_version cut + deploy 后跑 verify --shot 8 / 9 --loc | open | — | ❌ 没找到 |
| ISS-1103-023635-e0e0 | ASSET-WORKER | 8 资产就绪 | 资产作业 item-ch_zhuo_lin-A-acc1（卓琳（ch_zhuo_lin））连续失败：没有候选过检（4 张 | 看 data/pipeline/asset_jobs/<run>/<job>.json 的 log；修好后把 state | open | — | ❌ 没找到 |
| ISS-1103-023635-5bed | ASSET-WORKER | 8 资产就绪 | 资产作业 item-ch_zhuo_lin-A-outfit1（卓琳（ch_zhuo_lin））连续失败：没有候选过检（ | 看 data/pipeline/asset_jobs/<run>/<job>.json 的 log；修好后把 state | open | — | ❌ 没找到 |
| ISS-1103-023748-abe6 | DELEGATE-O | delegate | 代选范围未含 pick:golden（阶段 B 金样首帧，GOLDEN-O 新加的类型）；按派单只代 face/scen | 总调度拍板：要代就把 golden 加进 config/pipeline/owner_delegate.json sco | closed | ❌ | ❌ 没找到 |
| ISS-1103-023749-2903 | DELEGATE-O | delegate | P1 处于 owner_direction 且评委分不达代选门槛（均分<30 或有项≤2）时，代选不放行也不点修改：au | 若要在这种情况下自动退回补丁环，需 EPCHAIN-O 在 autoflow_agent 的修改分支里排除 by=总调度 | open | — | ❌ 没找到 |
| ISS-1103-024205-8856 | CARRYOVER-F | 9 | 近景/特写镜服装信息全丢（ep01 S8 只读编译证据）：K-REN-707 隐藏词把整句“穿黑色漆皮抹胸紧身短裙、黑色 | framing.filter_parts 按单品拆分句再过滤（保留上身件）；asset_refs.zone_of 对含抹 | open | — | services/agent/ns_agent/asset_refs.py、services/agent/ns_agent/frame_job.py、services/agent/ns_agent/framing.py、services/agent/ns_agent/gen_contract/preflight.py |
| ISS-1103-024206-c8c0 | CARRYOVER-F | 9 | Q1a 逐人头发/性别属性闸门（K-REV-V19）对 V2 失效：config/gen_contract.json Q | 从 assets_v2/manifest.json + P1 人物表自动生成 cards（gender / hair_c | open | — | config/gen_contract.json、services/agent/ns_agent/gen_contract/postflight.py、services/agent/ns_agent/vqa/contract.py |
| ISS-1103-024206-4b21 | CARRYOVER-F | 10 | 本地看图闸门没有挡在视频之前：config/vqa.json gate.video_requires_q9=false（ | V2 直接置 true（V2 没有历史欠账）。见 CARRYOVER P0-3 | open | — | config/policies/gates.yaml、config/vqa.json、tools/series10_video/build_jobs.py |
| ISS-1103-024206-3737 | CARRYOVER-F | 10 | V2 视频链不存在：tools/series10_video/build_jobs.py:37、vidgen.py:37 | build_jobs/vidgen/night 按 runs.run_dir 参数化或接 gate_legacy_too | open | — | tools/series10_video/build_jobs.py、tools/series10_video/night.py、tools/series10_video/vidgen.py |
| ISS-1103-024206-0474 | CARRYOVER-F | 10 | 运镜词表按剧条目在视频端拿到 run=None：services/recipes/ns_recipes/prompt.p | 两处显式传 run（compile_shot framing_project / normalize_video_pro | open | — | services/recipes/ns_recipes/prompt.py、services/render_router/ns_render/pipeline.py |
| ISS-1103-024206-9974 | CARRYOVER-F | 2 | CLEAN_CUT“交稿须 v1_leak scan 0 命中”没有代码执行点：autoflow_agent.py 交稿 | 三处接 v1_leak scan（0 命中才放行）；重新出 ep01 的 final.md 并重导入；导入器剥掉非本剧  | closed | ❌ | tools/import_script.py |
| ISS-1103-024456-6b8d | TIMELINE-O | 6 | 需拍板：官方 base-en 只给切镜写时间码（[Shot N] At MM:SS.mmm），镜内按拍用同一写法是 sy | 总调度定：保持 At 00:SS.mmm / 改 At the N-second mark / 派 VIDLAB A/B | closed | ✅ | ❌ 没找到 |
| ISS-1103-024835-af9a | ASSET-WORKER | 8 资产就绪 | 资产作业 item-ch_jiang_yubai-A-acc1（江予白（ch_jiang_yubai））连续失败：没有候 | 看 data/pipeline/asset_jobs/<run>/<job>.json 的 log；修好后把 state | open | — | ❌ 没找到 |
| ISS-1103-024835-322b | ASSET-WORKER | 8 资产就绪 | 资产作业 item-ch_jiang_yubai-A-outfit1（江予白（ch_jiang_yubai））连续失败： | 看 data/pipeline/asset_jobs/<run>/<job>.json 的 log；修好后把 state | open | — | ❌ 没找到 |
| ISS-1103-030155-1e03 | MERGE-OPS-O | 0 | （延后，ep01 后做）SENTINEL：S6 'list'.get 已在 probes.py 修（override_p | probes.py 加 producer_dirs()/render_roots() 按 runs.json 未归档剧取 | open | — | ❌ 没找到 |
| ISS-1103-030155-548c | MERGE-OPS-O | 0 | （延后）本机 data/system_version.txt 停在 sv-20261102-04，scores.json | 查 system_version.py deploy 是否只写服务器、不写笔记本本机文件 | open | — | ❌ 没找到 |
| ISS-1103-030156-9fcb | MERGE-OPS-O | 0 | 发版闸门 decision_propagation --dry 退出码 1：D-IMG-01 default_prese | 交 MERGE-IMG-O / MERGE-VID-O；或总调度定 V2 下这两条决定是否限 run=series10_ | open | — | config/owner_decisions.yaml |
| ISS-1103-030156-3095 | MERGE-OPS-O | 0 | （延后）SOP：关单选了 SOP 未更新的条目，经验还没补进 PIPELINE_SOP_V2.md | report_issue list --all 过滤 sop_updated=no，逐条补对应步骤 | open | — | ❌ 没找到 |

## 3. 本集新增 / 改动的规则（config、knowledge、SOP）

窗口：本集开工 2026-11-02 19:10:55 起（git log --since + 未提交改动）。

- 已进版本 33 个：`config/compile/brand_words.json`、`config/compile/run_style.json`、`config/director/camera_moves.yaml`、`config/edit_engines.json`、`config/factory/hosts.json`、`config/master/escalate.sha256`、`config/netfix/partition.json`、`config/owner_decisions.yaml`、`config/pipeline/chain.yaml`、`config/pipeline/run.json`、`config/pipeline/runs.json`、`config/policies/sentinel.yaml`、`config/post/luts/v2_fantasy_a.cube`、`config/post/luts/v2_fantasy_b.cube`、`config/post/luts/v2_fantasy_b2.cube`、`config/post/luts/v2_fantasy_c.cube`、`config/post/luts/v2_reality_a.cube`、`config/post/luts/v2_reality_b.cube`、`config/post/luts/v2_reality_c.cube`、`config/post/luts/v2_reality_c2.cube`、`config/prompts/hollywood_p1_judge.md`、`config/prompts/hollywood_p1_review.yaml`、`config/recipes/asset_refs.json`、`config/recipes/director_system_prompt.md`、`config/recipes/writer_knowledge.md`、`config/render_quality.json`、`config/v2style.json`、`config/voices_v2.json`、`config/vqa.json`、`knowledge/generated/index.json` …
- 未提交 48 个：`config/compile/bible_series10_v2.toml`、`config/compile/run_style.json`、`config/director/camera_moves.yaml`、`config/director/shot_spec_v2.yaml`、`config/gen_contract.json`、`config/music_v2.json`、`config/netfix/partition.json`、`config/owner_decisions.yaml`、`config/pipeline/agent_dispatcher.json`、`config/pipeline/asset_worker.json`、`config/pipeline/chain.yaml`、`config/pipeline/examples/P4_episode.md`、`config/pipeline/hollywood_score.json`、`config/pipeline/owner_delegate.json`、`config/pipeline/runs.json`、`config/pipeline/sop_gate.json`、`config/pipeline/video_policy.json`、`config/policies/gates.yaml`、`config/policies/sentinel.yaml`、`config/prompts/dispatch_reviewer.md`、`config/prompts/dispatch_writer.md`、`config/prompts/hollywood_judge.md`、`config/prompts/hollywood_writer.md`、`config/prompts/vqa_inspect.md`、`config/qwen_writer_system_prompt.txt`、`config/recipes/director_system_prompt.md`、`config/recipes/timing_lint.json`、`config/recipes/writer_knowledge.md`、`config/render_quality.json`、`config/s2_waivers.json` …

## 4. 记忆 / harness 更新清单（总调度勾选）

- [ ] ISS-1103-001014-cf0d：修复做成代码 / 检查（代码或测试里带卡点号），或写明不需要的理由
- [ ] ISS-1103-001014-176b：修复做成代码 / 检查（代码或测试里带卡点号），或写明不需要的理由
- [ ] ISS-1103-001014-c5f6：修复做成代码 / 检查（代码或测试里带卡点号），或写明不需要的理由
- [ ] ISS-1103-001014-aace：修复做成代码 / 检查（代码或测试里带卡点号），或写明不需要的理由
- [ ] ISS-1103-003637-9d25：修复做成代码 / 检查（代码或测试里带卡点号），或写明不需要的理由
- [ ] ISS-1103-003720-f86a：修复做成代码 / 检查（代码或测试里带卡点号），或写明不需要的理由
- [ ] ISS-1103-004546-a997：修复做成代码 / 检查（代码或测试里带卡点号），或写明不需要的理由
- [ ] ISS-1103-004547-6260：修复做成代码 / 检查（代码或测试里带卡点号），或写明不需要的理由
- [ ] ISS-1103-005241-bf53（SV17-O）：经验写进 PIPELINE_SOP_V2.md 后 report_issue close --sop-updated yes
- [ ] ISS-1103-011049-336c：修复做成代码 / 检查（代码或测试里带卡点号），或写明不需要的理由
- [ ] ISS-1103-011516-79c4：修复做成代码 / 检查（代码或测试里带卡点号），或写明不需要的理由
- [ ] ISS-1103-011516-d684：修复做成代码 / 检查（代码或测试里带卡点号），或写明不需要的理由
- [ ] ISS-1103-011622-e6d4：修复做成代码 / 检查（代码或测试里带卡点号），或写明不需要的理由
- [ ] ISS-1103-013144-ebe9：修复做成代码 / 检查（代码或测试里带卡点号），或写明不需要的理由
- [ ] ISS-1103-013144-c94f：修复做成代码 / 检查（代码或测试里带卡点号），或写明不需要的理由
- [ ] ISS-1103-013251-c584：修复做成代码 / 检查（代码或测试里带卡点号），或写明不需要的理由
- [ ] ISS-1103-014614-86aa（OVERSIGHT-R）：经验写进 PIPELINE_SOP_V2.md 后 report_issue close --sop-updated yes
- [ ] ISS-1103-014614-9db2（OVERSIGHT-R）：经验写进 PIPELINE_SOP_V2.md 后 report_issue close --sop-updated yes
- [ ] ISS-1103-022443-a371（ASSET-WORKER）：经验写进 PIPELINE_SOP_V2.md 后 report_issue close --sop-updated yes
- [ ] ISS-1103-022443-a371：修复做成代码 / 检查（代码或测试里带卡点号），或写明不需要的理由
- [ ] ISS-1103-023132-1c46（METRICS-F）：经验写进 PIPELINE_SOP_V2.md 后 report_issue close --sop-updated yes
- [ ] ISS-1103-023528-1509（GOLDEN-O）：经验写进 PIPELINE_SOP_V2.md 后 report_issue close --sop-updated yes
- [ ] ISS-1103-023528-2869（GOLDEN-O）：经验写进 PIPELINE_SOP_V2.md 后 report_issue close --sop-updated yes
- [ ] ISS-1103-023528-dd39（GOLDEN-O）：经验写进 PIPELINE_SOP_V2.md 后 report_issue close --sop-updated yes
- [ ] ISS-1103-023528-dd39：修复做成代码 / 检查（代码或测试里带卡点号），或写明不需要的理由
- [ ] ISS-1103-023529-71ed（GOLDEN-O）：经验写进 PIPELINE_SOP_V2.md 后 report_issue close --sop-updated yes
- [ ] ISS-1103-023529-71ed：修复做成代码 / 检查（代码或测试里带卡点号），或写明不需要的理由
- [ ] ISS-1103-023635-e0e0（ASSET-WORKER）：经验写进 PIPELINE_SOP_V2.md 后 report_issue close --sop-updated yes
- [ ] ISS-1103-023635-e0e0：修复做成代码 / 检查（代码或测试里带卡点号），或写明不需要的理由
- [ ] ISS-1103-023635-5bed（ASSET-WORKER）：经验写进 PIPELINE_SOP_V2.md 后 report_issue close --sop-updated yes
- [ ] ISS-1103-023635-5bed：修复做成代码 / 检查（代码或测试里带卡点号），或写明不需要的理由
- [ ] ISS-1103-023748-abe6（DELEGATE-O）：经验写进 PIPELINE_SOP_V2.md 后 report_issue close --sop-updated yes
- [ ] ISS-1103-023748-abe6：修复做成代码 / 检查（代码或测试里带卡点号），或写明不需要的理由
- [ ] ISS-1103-023749-2903（DELEGATE-O）：经验写进 PIPELINE_SOP_V2.md 后 report_issue close --sop-updated yes
- [ ] ISS-1103-023749-2903：修复做成代码 / 检查（代码或测试里带卡点号），或写明不需要的理由
- [ ] ISS-1103-024205-8856（CARRYOVER-F）：经验写进 PIPELINE_SOP_V2.md 后 report_issue close --sop-updated yes
- [ ] ISS-1103-024206-c8c0（CARRYOVER-F）：经验写进 PIPELINE_SOP_V2.md 后 report_issue close --sop-updated yes
- [ ] ISS-1103-024206-4b21（CARRYOVER-F）：经验写进 PIPELINE_SOP_V2.md 后 report_issue close --sop-updated yes
- [ ] ISS-1103-024206-3737（CARRYOVER-F）：经验写进 PIPELINE_SOP_V2.md 后 report_issue close --sop-updated yes
- [ ] ISS-1103-024206-0474（CARRYOVER-F）：经验写进 PIPELINE_SOP_V2.md 后 report_issue close --sop-updated yes
- [ ] ISS-1103-024206-9974（CARRYOVER-F）：经验写进 PIPELINE_SOP_V2.md 后 report_issue close --sop-updated yes
- [ ] ISS-1103-024456-6b8d：修复做成代码 / 检查（代码或测试里带卡点号），或写明不需要的理由
- [ ] ISS-1103-024835-af9a（ASSET-WORKER）：经验写进 PIPELINE_SOP_V2.md 后 report_issue close --sop-updated yes
- [ ] ISS-1103-024835-af9a：修复做成代码 / 检查（代码或测试里带卡点号），或写明不需要的理由
- [ ] ISS-1103-024835-322b（ASSET-WORKER）：经验写进 PIPELINE_SOP_V2.md 后 report_issue close --sop-updated yes
- [ ] ISS-1103-024835-322b：修复做成代码 / 检查（代码或测试里带卡点号），或写明不需要的理由
- [ ] ISS-1103-030155-1e03（MERGE-OPS-O）：经验写进 PIPELINE_SOP_V2.md 后 report_issue close --sop-updated yes
- [ ] ISS-1103-030155-1e03：修复做成代码 / 检查（代码或测试里带卡点号），或写明不需要的理由
- [ ] ISS-1103-030155-548c（MERGE-OPS-O）：经验写进 PIPELINE_SOP_V2.md 后 report_issue close --sop-updated yes
- [ ] ISS-1103-030155-548c：修复做成代码 / 检查（代码或测试里带卡点号），或写明不需要的理由
- [ ] ISS-1103-030156-9fcb（MERGE-OPS-O）：经验写进 PIPELINE_SOP_V2.md 后 report_issue close --sop-updated yes
- [ ] ISS-1103-030156-3095（MERGE-OPS-O）：经验写进 PIPELINE_SOP_V2.md 后 report_issue close --sop-updated yes
- [ ] ISS-1103-030156-3095：修复做成代码 / 检查（代码或测试里带卡点号），或写明不需要的理由
- [ ] MEMORY.md 现行骨架：本集新学到的事写进对应记忆文件（不新开重复文件）
- [ ] OWNER_CANON：本集项目方有没有新的重复要求 → 补定律或补“违反”计数
- [ ] PIPELINE_SOP_V2.md：本集每个卡点都写进对应步骤的“前置条件 / 卡过的地方”
- [ ] episode_ready / sop_gate：本集卡点里能自动查的，已做成检查（下一集开工前自动拦）
- [ ] master_check：本集新决策涉及的开关已进 SWITCH_EXPECT（带决策号）
- [ ] config/pipeline/sop_gate.json：observe_stages 是否可以收紧为 enforce
- [ ] 下一集开工前跑 episode_ready + sop_gate status，缺的一次性补齐
