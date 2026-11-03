# 冒烟门评分表（Phase R，RSI 实施包 §4）— eval/smoke_rubric.md

> 只有总调度 / 诊断线能改本文件和 `eval/`；worker 不许改、不许给自己放行。
> 入口：`powershell -File eval\run_smoke.ps1` → `eval/smoke.py run`。每门 = 采集 `collect_gN` + 纯函数判定 `judge_gN`（不许 LLM 判门）。
> 输出：控制台表 + `eval/results/<YYYYMMDD-HHMM>.json`（`nsfs.smoke/1`：gates[{id,ok,evidence,secs}]、score=通过门数/8、total_secs、run_id、code_sha、notes）；退出码 = 失败门数。
> **达标线：8/8 且连续 3 次全过。**

## 夹具
- 剧：`smoke_v2`（`config/pipeline/runs.json` 登记，平时 `paused`；只在 G4 窗口由脚本经 `runs.set_status` 翻 `producing`，结束翻回 `paused`，常驻进程平时不碰）。
- 剧本：`eval/smoke/P4_smoke.md`，固定 3 镜（4 + 5 + 6 = 15 秒），同一场景 `sk_white_cyc`，两位角色 祁念（lead_f）/ 唐瑶（ch_tang_yao），格式取自 series10_v2 ep01（只读改写）。
- 模板：`eval/smoke/template/pipeline_run/`（series10_v2 的 P1_storyline / P1_looks / P0_brief / looks 只读拷贝：v1_leak 闸门的白名单只认“本剧自己的 P1”）。
- 每次开跑先把 `smoke_v2` 全部目录（`eval/smoke.py SMOKE_DIRS`）整目录挪到 `data/quarantine/smoke_v2/<时间>-a|b/`（隔离不删），再从模板复制。
- 低参数：`eval/smoke/preset.json`（image / video 低参数 + output 成片规格 + G4 超时）。自动定稿覆盖：`eval/smoke/owner_override.json`。⚠ 两个覆盖目前都**没有消费入口**（见 notes），不改渲染代码不生效。

## 八门

| 门 | 判定命令（采集） | 证据路径 | 通过线 |
|---|---|---|---|
| G1 启动 | `collect_g1`：GET `http://127.0.0.1:8800/api/sop/status?run=smoke_v2`（`http_json_retry`：单次超时 30 s，失败再试 2 次、共 3 次，W32 — API 冷启动慢）；Windows 进程命令行含 `autoflow_resident.py`、`tunnel_supervisor.py`；GET `http://127.0.0.1:8870/health`；`config/**/*.json|yaml` 全部能 load；子进程 import `CONFIG_IMPORTS`（runs / sop_gate / ns_schema.script / frame_job / preflight / asset_refs / ns_render.pipeline / unified_frame / image_params / ns_post.assemble / ns_api.app） | evidence.api_status / api_attempts / api_timeout_s / procs / vqa_status / config_errors / import_errors | API=200 且两进程在 且 8870=200 且 config_errors=[] 且 import_errors=[] |
| G2 输入 | `collect_g2`：`tools/validate_qwen_script.py P4_ep01.md --json`；`tools/import_script.py --script … -o data/import/runs/smoke_v2/script_v2.json --no-timeline`（= producer import_staged_run 的同一导入器）；脚本按真实结果写 `autoflow_ep01.json` gate/import 段（decider=smoke_harness）；`tools/master/episode_ready.py --run smoke_v2 --episode 1 --json`；就绪才 `asset_jobs.generate`（写 `_ready_ep01.json`，无缺口 = 不生成作业）+ `sop_gate.py probe-prompts`；判 `sop_gate.check_prompts` + `sop_gate.judge(…, "出图")` | data/import/runs/smoke_v2/script_v2.json；data/pipeline/asset_jobs/smoke_v2/_ready_ep01.json；data/pipeline/sop_gate/smoke_v2/ep01_prompts.json | validate block ⊆ {QW-E2 镜数, QW-E3 总时长}（3 镜夹具按设计过不了一集 6–8 镜 / 60–120 秒）；import rc=0；ep01=3 镜；资产就绪 0 缺口；提示词 3/3 过且“出图”前所有阶段有证据 |
| G3 角色 | 编译侧：`eval/smoke/refs_probe.py --run smoke_v2 --episode 1`（按 `runs.run_env` 子进程调 `frame_job.build_first`）；出图侧 `render_refs`（W32，不靠 ComfyUI 文本日志）：`data/producer/runs/smoke_v2/log.jsonl` 里本次 G4 窗口（t ≥ t0）的 `"ev": "rendered"`，`obj` 以 `first:ep01-SN` / `last:ep01-SN` 结尾，按其 `take` 号到 `data/renders/smoke_v2/ep01/SN/takes.json` 找对应 stage 的版本；该版本须过 G4 同一“本次自己出的”规则（`fresh_take_why`），其参考文件列表 = `references` ∪ `refs` ∪ `asset_refs.slots[].file`（take 上或 take.contract 里；去掉“ (image vN)”后缀） | evidence.refs（每镜 cast / refs / face_files / missing_refs）、evidence.render_refs（每对象 ok / take / lane / refs / missing / faces_hit / why） | 3 镜都有身份脸、参考文件全在；6 个对象（3 首帧 + 3 尾帧）各有一个本次 rendered 版本：参考列表非空、文件全在、且含编译侧按名解析出的身份脸至少一张。说明：V2 出图 `loras=[]`（W-40，参考图挂身份），ns_render 不打“LoRA 加载成功”日志，所以按名加载取 producer `rendered` + takes 参考列表 |
| G4 生成 | `collect_g4`：记窗口起点 t0 → 前置 G2 过且 `sop_gate.judge(smoke_v2, 1, "出图")` 放行 → 翻 producing → `producer.py once --run smoke_v2 --wait`（超时 = preset.json gate_timeout_s.G4，默认 1500 s = 25 min）→ 翻回 paused；`scan_g4_outputs(t0)` 扫描产物 | takes.json（image / last / video 版本）；data/pipeline/runs/smoke_v2/video/clips/ep01/ep01-SN__*.mp4；log.jsonl OOM / 超时行；evidence.t0 / excluded / excluded_count | 3 首帧 + 3 尾帧 + 3 段视频都有**本次自己出的**文件；退出码 0（124 = 超时）；日志无 OOM / 超时。“本次自己出的”（W32，`fresh_take_why`）= 文件在 `data/renders/smoke_v2/` 下且存在、非 bad；不是 adopt 来的（log.jsonl `ev=adopt` 的 (对象, take) 排除，`params.origin.adopted_by` 排除）；首/尾帧 `take.producer.lane` 非空；`created_at`（读不了用 mtime）≥ t0 − 2 s。视频同理（takes stage=video 同规则但不要求 producer.lane；clips 下 mp4 要 mtime ≥ t0 − 2 s）。W26b 证据：adopt 把 V1 旧图（`renders/ep01/…`）登记进 smoke_v2 takes（data/quarantine/smoke_v2/20261103-1652-b/）——这些一律不算 |
| G5 合成 | `collect_g5`：前置 G4 过 → `tools/assemble_episode.py ep01 --run smoke_v2 --out data/episodes/smoke_v2 --no-asr --fake-tts --no-bgm --4k off --no-color-match`（ns_post.assemble.assemble_episode） | data/episodes/smoke_v2/ep01*.mp4、ep01.timeline.json | rc=0、有 mp4、时间线里静帧占位 = 0 |
| G6 规格 | `collect_g6`：ffprobe（WinGet Gyan.FFmpeg_*/ffmpeg-*/bin/ffprobe.exe，找不到退 PATH） | evidence.probe / want | 时长 = 剧本 3 镜时长和 ±2 s；分辨率 = preset.json output（1080×1920）；帧率 = 24 |
| G7 幂等 | 第二遍：再隔离清空 → 模板 → 只重跑 G2（不重出图）；`tree_fingerprint`（STRUCT_DIRS 四个目录：相对路径时间戳归一，.json 去时间字段后哈希） | evidence.first / second（files + sha）、residue_before | 清空后零残留；两遍指纹 sha 一致；第一遍 G2 过则第二遍 G2 也要过 |
| G8 无人值守 | `owner_points`：`sop_gate.stage_view(smoke_v2)` 的 pending_owner；GET `/api/owner/queue?run=smoke_v2`（同 G1：30 s × 重试 2 次）里提到 smoke_v2 的条目；autoflow_ep01.json 里 decider=owner / awaiting_owner 段；全部子进程 stdin=DEVNULL | evidence.owner_points / queue_status / pipeline_complete | 零等项目方点位 且 owner_queue 可读（200）且 G5 过（流水线没走完 = 无法证明无人值守，记失败） |

## 改动规则
- 通过线只许收紧，不许为了“让门过”放宽；放宽要总调度在 STATE.md 里写理由。
- 不许改渲染 / producer 代码让门过；过不去就是基线，原因进 STATE.md“已知坏点”。
- 测试：`.venv/Scripts/python.exe -m pytest eval -q`（`eval/test_smoke_harness.py` 桩掉 GPU / 网络，验证八门判定与 JSON schema）。
