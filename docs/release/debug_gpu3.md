# gpu3 运行时封板 debug（fredw-ae / fredw-d9，2026-10-30）

范围：总调度派单“【gpu3 运行时】逐一 debug”。做法：3 个只读子 agent 分模块跑现有测试和 dry_run、补草稿单测，不改 gpu3、不占 GPU；修复由本会话统一做，每处都备份（`.bak-*-20261030`）并记 CHANGELOG（封板修复）。lnwan01 训练、ep02 预留没有被打断。

状态：✅ 已修并上线　🟡 已修，下次启动生效　📤 交给负责人　❓ 待决定　⚠ 已知、不在本次修

## 1. 桥 nsfs-canvas-bridge（:5180）

| 测试项 | 方法 | 结果 | 处理 |
|---|---|---|---|
| 现有测试 | `pytest tests` | 22 过 1 跳 → 修后 23 过 1 跳 | — |
| 24 个端点（15 GET + 9 POST） | 逐个 GET；POST 只用 dry_run 或非法 body | 全 200 / 404 / 403 / 422 符合预期；媒体、缩略图、Range、路径穿越都正常 | — |
| `/run` 端点 | 首次检查时不存在 | 进程 10-29 23:54 启动、代码 10-30 00:00 才改 | ✅ 重启后加载 |
| 读哪份剧本 | `NSC_SCRIPT_JSON` | 读的是 10-29 的旧副本（sha 217e53e9） | ✅ 改读 nsfs_mirror（P0-4） |
| 状态时间线 | `NSC_STATE_TIMELINE` 未设 | 默认路径不存在，needs_review 永远看不到 | ✅ 指向 nsfs_mirror |
| 渲染卡列表 | `NSC_COMFY` / `NSC_RUN_GPUS` | 还列着 GPU1（Qwen 写作模型） | ✅ 只剩 GPU0/GPU3；选 GPU1 → 422 |
| 占卡判断 | dry_run gpu0/gpu1 | 只看 gpu.lock / lend，看不到 train.lock：会把活排到 LoRA 卡或 Qwen 卡 | ✅ `runs.lock_holder` 加查 train.lock（`*render-reserve` 预留锁除外）+ 测试 |
| 规则说明子进程编码 | Windows 上中文输出 502 | `rules.py` 未指定编码 | ✅ fredw-25 修，已部署 |
| 不存在的镜头 / 集 | GET ep02-S9、ep99 | 200 空数据（`/run` 正确 404） | ⚠ P2 |
| 队列 stage 字段 | run 项用 `step` | 列表里 stage 显示为空 | ⚠ P2（外观） |

## 2. weita-runner（项目方按集运行的消费者）

| 测试项 | 方法 | 结果 | 处理 |
|---|---|---|---|
| op 不匹配 | 桥写 `op="run"`，runner 只认 render | 桥发的任务全部被忽略 | ✅ 接受 render/run + 2 个测试（9/9 过） |
| lend 解析、取消、中途撤 lend、GPU2 拒绝 | 现有 + 草稿测试 | 通过 | — |
| 事件名 | runner 写 `running`，桥只认 started/image_done/video_done | 运行中画布显示不出“渲染中” | ❓ 改哪边需和桥的状态约定一起定（📤 fredw-92） |
| 4K 项 | 桥按集发一项 `shot="ep02"`，runner 按镜解析 | 4K 永远被跳过 | ⚠ P2（v1.0 验收不含 4K） |
| lend 释放 | 读代码 | 跑完不释放 lend、不更新 run 记录 | ⚠ 疑点，P2 |
| 部署 | — | 从没在 gpu3 跑过；`weita-runner@` 由项目方本人启动 | — |

## 3. 渲染器各步（weita_series / weita_render / shot_audit）

| 测试项 | 方法 | 结果 | 处理 |
|---|---|---|---|
| 现有测试 | `pytest tests/unit` | 5619 过；4 失败（见 §8，改动前就有） | — |
| **没有 H3提示词 / lint 有 block 时会不会退回草稿出视频**（fredw-5c 问） | 追调用链 step_b_shot → run_h3 → assert_pass | **会拒绝**：无字段 → S1-W7 block；字段不过 → S1-W8/W9；后备提示词同样全量 lint；只有项目方逐条豁免才放行。笔记本草稿会被覆盖、从不送进 H3 | 不需要新拦截 |
| E8 配乐进 H3 | 项目方“写进 H3（按 E8）” | 模板 / 后备路径固定写 N/A；内置 H3-S3 把非 N/A 判失败 | ✅ 改用同步过去的笔记本 `resolve_music`；实测：无 BGM → N/A，英文 BGM → 写进 H3，静默 cue → N/A，lint 通过 |
| 规则表 | 三份 rule_ids.md | gpu3 两份还是旧版（H3-S3 固定 N/A、H3-D7 mixed），nsfs_mirror 缺失 | ✅ 同步笔记本版本 |
| 林晚出图 LoRA | 注册表 | 我覆盖时把软链接换成了副本，真表一直是 training | ✅ 真表写 accepted + sha，软链接恢复 |
| 两位数镜号 | `S(\d)` | ep01-S10 解析成 ep01s1 | ✅ `S(\d+)` |
| **渲染器读的剧本** | 追代码 | 读 `为他而骚（剧本和镜头）v2.md` 原稿，不读导入的 script_v2.json → ep02 看不到编译器补的 `lnwan_qi`，林晚 LoRA 加载不上 | ❓ 决定读哪份（📤 总调度 / fredw-92） |
| ep02 首帧被 R-C4 挡 | dry_run | 要求视频 LoRA lnwan01 也已采用才能出首帧；审计记录还是 03:50Z 的旧结果 | ❓ S2 规则口径（📤 fredw-5c） |
| CLI `weita_render.py video` | 读代码 | 手动命令不过审计、不挡露骨镜头 | ⚠ P2（只有手动能触发） |

## 4. 出图接口 qwen-image-api（:8100）+ Image Docker

| 测试项 | 方法 | 结果 | 处理 |
|---|---|---|---|
| 健康 / 任务 / 路径穿越 / 图构建 / refs 校验 | GET + 副本单测 16 个 | 通过 | — |
| worker 线程 | 坏 job.json、`up` 空输出 | 线程悄悄死掉，/health 仍 ok | ✅ 每轮兜底 + 跳过坏文件 |
| 请求校验 | body 不是对象、loras 名是数字、gpus `[3.0]`、宽度 -8、LoRA 名带 `../` | 断连接 / 能入队 | ✅ 一律 400（已实测） |
| GPU3 抢卡 | 默认卡是 GPU3 | 预留期间没有锁 | ✅ `train.lock.gpu3`（ep02-render-reserve），`up 3` → 75 |
| 回收 | ComfyUI 不响应 | 永远不回收 | ✅ 不响应时不刷新活跃时间 |
| status 被 up 卡住 | 读代码 | 最多约 240 秒 | ✅ status 不拿锁 |
| 严格先进先出 | 副本单测 | 等某张卡的任务堵住后面所有任务 | ⚠ P2 |

## 5. Qwen 信箱 + 调度程序 + 写作模型

| 测试项 | 方法 | 结果 | 处理 |
|---|---|---|---|
| 07:11 崩溃（撤任务竞争） | 副本测试 | 修后不再崩 | ✅（当时已修） |
| 超时时输出是 bytes | 副本测试 | 写结果崩，任务永远 running | 🟡 改为输出写文件 |
| 找不到 qwen / 其他异常 | 副本测试 | 不写结果 | 🟡 一律写 failed |
| 后台子进程占槽 | 副本测试 | 要等子进程结束 | 🟡 独立进程组，超时结束整组 |
| 调度程序测试 | 10 个 | 7/3 → 10/10 | — |
| `/tasks/<id>?x=1` | GET | 返回整个列表 | ✅ |
| `/files` 路径穿越 7 种写法 | GET | 全 404 | — |
| 上下文溢出 | llama 日志 | 32k 时任务大量失败；48k 后又溢出 2 次 | ✅ 每槽 48k；Qwen Code 上限 44000 留余量 |
| 1 槽回退 | 假 docker | 手动 docker stop 也会退回 1 槽 | 🟡 只在异常退出时回退 |
| CPU 版 Qwen | pid 对 nvidia-smi | 不碰任何 GPU | ✅（当时已修） |
| 本机 `qwen_task.py` | `--get` 已撤任务 | 报错堆栈 / 每 10 秒重开隧道 | ✅ |
| 任务优先级 | — | 只有先进先出 | ⚠ P2（加优先级要重启容器） |

## 6. 后期 audio_post / nsaudio-watch

| 测试项 | 方法 | 结果 | 处理 |
|---|---|---|---|
| 两套配乐动作词 | 副本单测 | 都认 | — |
| N/A 跳过 BGM | 副本单测 | 带括注写法认不出 | ✅ |
| C1 忙循环 | 副本单测 | 不完整的集每轮都重算 sha、刷日志、抢 GPU | ✅ 只在真有产出时才算进展 |
| C2 任一异常退出 | 副本单测 | 永久退出 | ✅ 每集单独兜底 |
| C3 动作词误判 | 真实草稿 366 条 | 9 条判错 | ✅ 句首优先 + 英文词边界 |
| C4 静默后“延续”回到 1 | 副本单测 | — | ✅ 保持 0 |
| E8 双重配乐 | — | H3 带配乐的镜头后期还叠 BGM | ✅ 该镜 BGM 撤到静默，缓存校验值含此项 |

nsaudio-watch 已重启（08:42），新代码在跑。

## 7. 同步与隧道

| 测试项 | 方法 | 结果 | 处理 |
|---|---|---|---|
| sync_laptop 增量、中文文件名、不可达、队列合并 | 沙盒演练 16 项 | 通过；时钟偏差无影响 | — |
| 队列文件末尾无换行 / 非对象行 | 沙盒 | 粘行 / 合并崩溃但记 ok | 📤 fredw-92（ops 脚本） |
| mirror_prune 排序 locale | 沙盒 | 两边 sort 不同，会误删 | 📤 fredw-92 |
| 镜像兜底读不到队列 | 读代码 | 同步排除了队列文件 | 📤 fredw-92 |
| 只有一个会话里的同步循环在跑，计划任务全不存在 | schtasks | P0-7 | 📤 fredw-92（笔记本侧） |
| 隧道守护 | 单测 12 个 | 非 OSError 的 HTTP 异常会让守护退出 | ✅ + 测试进 `tests/` |

## 8. 已知、不在本次修

- `tests/unit` 4 个失败改动前就有：`test_h3_outputs_guard`、`test_licence_record_rules`、`test_loopback_opener`（白名单缺 ns_sched.py、upscale_4k.py 等）、`test_qwen_turbo_character_pictures`。
- P0-7 持久化（6 个临时 unit、ns-comfy 自启）、孤儿 chain.sh、作废调度计划、归档 4 条旧请求：被本会话权限检查拦下，命令 `ssh gpu33 "bash /root/qwen-agent/ops/owner_persist_20261030.sh"` 已交总调度，由项目方本人执行。
- 调度程序修复在容器下次启动时生效（不为此打断正在跑的任务）。

## 9. 第二轮（总调度两条决定之后，2026-10-30 09:00–09:15 EDT）

| 项 | 结果 | 处理 |
|---|---|---|
| 渲染器读哪份剧本 | 读项目方 v2.md，绕开了编译器补的触发词、整集🔴、S1 验收 | ✅ `load_script_json` 读 nsfs_mirror `script_v2.json`；对照工具 `ns-studio/tools/loader_parity.py`：ep02–60 除预期的 lnwan_qi 外一致 |
| 导入 JSON 缺 `daily_outfit`、`decor_tables` | 林晚着装镜头首帧会少“日常穿搭”一句 | 📤 fredw-92 已实现，等总调度选 A（新 JSON + 项目方重跑 S1，推荐）/ B |
| R-C3 S1 验收 | 切到 JSON 后会永远不过（只认 v3.md） | ✅ 按 s1_gate.json 是否接受这份 JSON 的规范化哈希 |
| R-C4 | 首帧被视频 LoRA lnwan01 挡住 | ✅ image 类拦、video 类只 warn；rule_ids 同步 fredw-5c 版 |
| 成人镜头 | 导入器判 adult 的 ep02-S5，渲染器关键词和桥都没挡 | ✅ 两边都读 JSON 的 adult；dry run S5 = explicit_hold |
| S2 闸门 | 桥不读 state_timeline 的 s2_ready；镜像里的时间线过期 | ✅ `runs.timeline_s2` 拦首帧；手动推了笔记本 22:07 JST 的时间线；dry run ep02 = 0/11 可出（等项目方跑 ep02 关口） |
| ep02 审计重跑 | 11 镜 `h3_prompt_source=script_field`，E8 配乐来自剧本 | — |
| lnwan01 交接任务失败 | Qwen Code 硬上限 21000（我把 contextWindowSize 降到 44000 所致） | ✅ 49152 + `max_tokens` 8192；任务重提交 c70977e7 |
| 旧 ep02 产物 | v2 版 6 镜 | ✅ 归档到 `_archive/ep02_v2_20261030`（gpu3 两处 + 笔记本） |
