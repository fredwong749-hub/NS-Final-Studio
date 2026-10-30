# 已停止工作清单（2026-10-30，claude-gpu3）

本清单只记录因政策停止的工作现在处于什么状态、文件在哪里，不包含任何生成方法或内容描述。所有文件原样保留，均未删除。

## 1. 已停止的工作线
| 工作线 | 停止前进度 | 文件位置（gpu3 = /root/claude-kimi-ns-studio-v1/） |
|---|---|---|
| 首饰 LoRA（nprng2 / lbrng9 / lbrng9_beads） | 3D 渲染与写实化做到一半；位置和材质问题未修；未训练 | gpu3 `ns-studio/data/train/jewellery/`（render/、render_archive/、tools/、logs/）；laptop `D:\NS-Final Studio\previews\jewellery\` |
| 首饰展示图 | v1、v2 已出图，v2b 未通过审核 | gpu3 `ns-studio/data/train/hardshots/showcase*/` |
| 姿势库 | 6 个测试预设（粗渲染）；分类文档；未训练 | gpu3 `ns-studio/data/train/poses/`（tools/、specs/、render/test/、HANDOFF.md）；laptop `docs/pose_library.md`、`previews/poses/` |
| 成人首帧路线 | 代码层禁用；已出的帧按原样归档 | gpu3 `ns-studio/data/archive/pre_policy_20261030/`；`renders_gpu3/*/S*/status.json` 中 `blocked: explicit_content_not_supported` |
| v3 剧本中的相关镜头 | 文字按生成时原样保留；不写 H3 提示词 | v3 定稿后在 `v3_changes.md` 的「H3 暂缓」一节 |

## 2. 被拦截的镜头怎么查
- gpu3 `ns-studio/data/run/weita/BLOCKED.jsonl`：每条记录对应一个被拦截的镜头。
- `renders_gpu3/epXX/SN/status.json` 中的 `state: blocked`：目前共 73 个镜头。
- 调度器（ns_sched）里的相关任务标记为 `halted (policy)`，不会分配到显卡。

## 3. 代码层的拦截位置（接管时需要知道）
- `ns-studio/scripts/weita_render.py`：`image_graph` / `identity_graph` / `realism_graph` 里禁用了 NoctQ 路线；另有 `frame_route` 和 `block_explicit()`。
- `ns-studio/scripts/weita_adult.py`：`do_shot` 和成人队列。
- `tools/weita_v3/h3_rules.py`：X-NONEXPLICIT 检查。
- 改动前的代码副本：`ns-studio/data/archive/pre_policy_20261030/`。
- 以上拦截是本工作流的设定。是否在本工作流之外另行处理这些镜头，由项目方自行决定；本工作流不参与。

## 4. 不受影响、继续进行的工作
剧本 v3（非露骨部分）和 H3 提示词、林晚出图身份 LoRA、鞋服 LoRA、男主角候选、场景底图、非露骨镜头的首尾帧和视频，以及 SOP、逐镜审核、调度器、显卡提速、画布、声音、4K 和成片装配。
