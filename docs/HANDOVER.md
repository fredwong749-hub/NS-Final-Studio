# 交接清单：非露骨部分，未完成事项（2026-10-30）

gpu3 根目录：`/root/claude-kimi-ns-studio-v1/`，下文简称“根目录”。

## 1. 剧本 v3（进行中）
- **状态：** `weita-v3-finish5` 正在写 H3 提示词。写完后自动合成，放到 `ns-studio/data/owner_scripts/weita_ersao/staging_v3/`，然后把 GPU 0 交给林晚 LoRA。
- **怎么判断完成：** `tools/weita_v3/work/FINISH_DONE` 出现即完成；进度在 `finish.log`。
- **完成后：**
  1. 把 v3 拷到 `D:\NS-Final Studio\script play lib\`；
  2. 项目方确认是否采纳；
  3. 导入。
- **待定：** 8 个插入镜头短于 5 秒，是否改为 5 秒。

## 2. 林晚出图身份 LoRA（等显卡）
- **状态：** `lw-qi-lora.service` 已装好，拿到 GPU 0 后自动开始训练。
- **完成后：** 样图交项目方审核；审过后登记到 `nsfs_mirror/data/renders_gpu3/LORA_REGISTRY.json`。

## 3. 鞋子 / 服装 LoRA（进行中）
- **状态：** `wardrobe-gen` 正在补鞋子训练图，之后做服装训练图（只做有遮盖的款）。
- **放行训练：** 审核关口在等。先在 `ns-studio/data/train/wardrobe/tools/rejects.txt` 写入淘汰名单，再新建空文件 `ns-studio/data/train/wardrobe/REVIEWED_heels`，训练开始。服装同理，用 `REVIEWED_clothes`。
- **审核图：** `D:\NS-Final Studio\previews\wardrobe\`
- **审图停在这里（2026-10-30 停止时的状态）：**
  - **透明款：** 保留 19 张（`foot_00,01,02,08,09,10,11,12,14,16,18,20,21,22,23`、`prod_01,04,05`、`web_105`），淘汰 25 张。
  - **漆皮款：** 22 张全部淘汰。原因是全都画成了包头或露趾鞋，不是侧开款。
  - **淘汰名单：** 已写入 `rejects.txt`，每张附原因，并有备份。
- **补做的图：** 放在 `jobs/jobs_clothes.jsonl` 的最前面，共 44 张：
  - 透明款 `hh12clear_v3`：24 张，直跟 6mm，暖光；
  - 漆皮侧开款 `hh12patent_v3`：20 张。
  - 输出位置是 `synth/clothes/hh12*`，**还没链接进 `synth/heels`**。
  - 新建 `REVIEWED_heels` 之前，必须先链接，并审核这些新图。
- **服装：** 64 个任务已改成有遮盖的款式。`ptxharness_v2_prod_*`（假人商品图）没有同步修改。任务单备份是 `jobs_clothes.orig.jsonl` 和 `jobs_clothes.pre_cover_*.jsonl`。
- **还没做：** 训练、挑选检查点、交付、写入 LoRA 登记清单（清单目前是空的）。

## 4. 男角色候选（快完成）
- **状态：** `char-variety` 在 GPU 1 上跑 7 张：顾沉 4 张、陈宇 3 张。
- **输出：** `nsfs_mirror/data/char_variety/`
- **完成后：** 交给另一个开发 agent 拼成总览图，由项目方挑选。

## 5. 显卡调度器（只记录、不执行）
- **状态：** `ns-sched` 在试运行。
- **v3 完成后补齐分卡改动：** `systemd-run --unit=t46-after-v3 根目录/ns-studio/scripts/t46_after_v3.sh`
- **正式接管（需项目方批准）：** `echo active > /root/.local/state/NS-Studio/scheduler_mode`
- **文档：** `docs/gpu_scheduler.md`

## 6. 首尾帧和视频（暂停）
- **开工条件：** v3 已确认、LoRA 已验收、第一集样片参数已锁定。
- **出视频前：** 每个镜头都要过 `ns-studio/scripts/shot_audit.py`。报告在 `docs/audit/shot_audit_report.md`。

## 7. 文档入口（都在 `D:\NS-Final Studio\docs\`）
- SOP：`SOP_production.md`
- 参数：`SOP_parameters.md`
- 规则编号：`audit/rule_ids.md`
- 任务：`TASKS.md`
- 已停止的工作：`halted_work_inventory.md`

## 8. 本机后台循环（本次会话关闭后会停）
- **位置：** `C:\Users\fredw\AppData\Local\Temp\claude\D--kimi-ns-storyboard\7785c2ec-d9a3-410d-8df0-17711614c3a9\scratchpad\`
- **包括：** `sync_laptop.sh`、`pull_laptop.sh`、`previews_sync.sh`、`music_sync.sh`、`mirror_prune.sh`、`nsfs_watch.sh`
- 需要长期运行的话，把它们改成你自己的计划任务。
