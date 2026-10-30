# 取消 Claude 加的成人过滤器（2026-10-30）

> 项目方：Claude 在系统里加了很多成人限制，找出这些实现，删掉，整个系统 uncensored。
> 全库闸门地图见 `docs/UNCENSORED_INVENTORY.md`；模型/检测调研见 `docs/research/uncensored_deep.md`。
> 本文列出改动前后的每一处闸门。系统仍保留“成人判定”（metadata / 路由 / 日志），但**它不再阻止任何出图、重出、按集运行或视频渲染**。

## 1. 笔记本（本仓库）

| 位置 | 原行为 | 现在 |
|---|---|---|
| `services/api/ns_api/explicit.py` | gpu3 `status.json` / `BLOCKED.jsonl` / 剧本 `**H3校验**` 任一命中 → `explicit_hold` | `hold()` 恒返回 `None`；`/api/explicit-holds` 空表；兼容字段保留 |
| `services/api/ns_api/app.py` `_refuse_explicit` | 露骨红标镜头的 render / batch / gpu3-rerender / boost 一律 409 | 不再拒绝 |
| `services/api/ns_api/app.py` `gpu3-rerender` | 成人镜 / 🔴 集必须 `by=owner` | 任何调用方都可送 gpu3 |
| `services/api/ns_api/owner_run.py` | 🔴 / 有成人镜的集 409“成人集·不可经 gpu3 渲染” | 任何集都可按集渲染；仍要求 `by=owner`（这是“项目方本人启动”的通用关口，不是成人限制） |
| `services/canvas_api/ns_canvas/runs.py` | 成人 / 🔴 / `blocked` 镜头加 `explicit_hold`，`eligible=false` | 只把 `explicit` 记进 detail，不再影响资格 |
| `services/render_router/ns_render/pipeline.py` | 成人镜头参考编辑要 `approved_for_adult`；本机成人 take 不能设为当前 | 参考编辑对所有镜头开放；本机 take 可设为当前 |
| `services/render_router/ns_render/pipeline.py` + `score.py` | 非成人镜头裸露质检一票否决（总分 0、撤下当前版本） | 只写 `Take.qc` 与日志，不淘汰、不撤版 |
| `services/render_router/ns_render/pipeline.py` `image_negative` | 非成人镜头追加“裸体、裸露…”负面词 | 直通编译器负面词 |
| `tools/render_batch.py` | 默认跳过成人镜头（要 `--include-adult`）；对比表不贴成人图 | 默认包含成人镜头；对比表照常贴图 |
| `tools/gpu_grab.py` | 带 `adult/nsfw/explicit/rating` 的任务直接拒绝；QC 裸露硬失败 | 接受成人任务；QC 只记录 |
| `config/visual_bible.toml` | `nudity_qc_non_adult = "hard_fail"` | `report_only` |
| 项目 / 附带设置 | `adult_content` 默认 `false`，gpu3 跳过成人镜头 | 默认 `true`；gpu3 不再按它跳过 |

## 2. gpu3 运行时（远程，2026-10-30 已打补丁）

远程文件都在 `/root/claude-kimi-ns-studio-v1/`；每个文件旁有 `.bak-uncensored-20261030`。

| 文件 | 原行为 | 现在 |
|---|---|---|
| `ns-studio/scripts/weita_render.py` `explicit_content` | 成人 / 露骨镜头永远返回 true | 恒为 false（兼容旧判断） |
| `ns-studio/scripts/weita_render.py` `no_explicit_model` | `noct` 模型抛 `PermissionError` | 允许 NoctQ |
| `ns-studio/scripts/weita_series.py` `held` | 林晚露骨镜头等 `approved_for_adult` 授权 | 恒为 false |
| `ns-studio/scripts/weita_series.py` `block_explicit` | 写 `blocked=explicit_content_not_supported`、抛错 | 空操作 |
| `ns-studio/scripts/weita_series.py` `frame_route` | 固定 base，禁用 NoctQ | 露骨 / 身体镜头用 `noct`，其余 `base` |
| `ns-studio/scripts/weita_adult.py` | 成人镜头先 `block_explicit`；`adult_content=false` 跳过 | 不再 block，不再跳过 |
| `ns-studio/scripts/weita_runner.py` `precheck` | 每个队列项先跳过 explicit / provenance hold 镜头 | 只跑步骤闸门；explicit/held 不再跳过 |
| `ns-studio/scripts/shot_audit.py` | 露骨镜头写 `audit.blocked`；非成人镜头 `S3-F4` 裸露一票否决 | 不再写 blocked；`S3-F4` 改为 warn（只记录） |
| `docs/audit/rule_ids.md`（三处副本） | `S3-F4` = block | `warn`“只记录” |
| `nsfs_canvas/.../ns_canvas/runs.py` | 成人 / 🔴 加 `explicit_hold` | 不再加 |
| `nsfs_canvas/.../ns_canvas/models.py` / `progress.py` | `adult_content` 默认 false | 默认 true |

## 3. 仍然保留（不是成人闸门）

- `classify_adult()` / `adult` 字段 / `adult_reasons`：仅作 metadata、路由和日志。
- 非成人镜头的 `[shot_rules_safe]`（“衣装完整、无裸露”）与负面词：是普通镜头的穿着提示，不拦成人镜头。
- `minor_guard`（未成年人外观）：保留在负面词里。
- `owner_run` 的 `by=owner`：按集渲染的通用“项目方本人启动”要求，不是成人专属。
- GPU 限制（GPU1 给 Qwen，GPU2 坏卡）与成人无关。

## 4. 验证

- 全量 `pytest`：701 passed / 6 skipped（改动后；`explicit_hold`、成人 owner、QC 否决相关测试已改成新行为）。
- 本机 API 已重启：`GET /api/explicit-holds` 返回 `{"count":0,...}`（旧进程曾返回 73 条）。
- `grep -R "explicit_hold\|explicit_content_not_supported" services tools`：只剩兼容字段和测试断言。
- gpu3：`python3 -m py_compile weita_render.py weita_series.py weita_adult.py shot_audit.py` 通过。

## 5. gpu3 的 30890 端口

项目方提到 gpu3 远程服务器有 **30890** 可以跑 MiniMax H3 与 Image 2.1。封板检查时：

- `ss -ltn` 没有 `:30890`；`docker ps` 只有 `qwen-llm`（:8098）、`ns-image`（:8190）、`qwen-agent`；
- 从 gpu3 本机 `curl 127.0.0.1:30890` 无响应；仓库与 `ns-studio` 脚本里也没有 30890 的引用。

当前系统仍走 `:8188` / `:8191`（H3 渲染）与 `:8190`（Image 2.1）。30890 若要接入，需要项目方给出该服务的启动方式或监听地址（或确认它是否在另一台机器 / 另一网络命名空间）。
