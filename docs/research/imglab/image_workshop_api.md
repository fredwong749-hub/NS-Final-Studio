# 图像工坊后端接口需求（IMGLAB → FILMUI，项目方 11-02 12:5x）

实现：`tools/imglab/bases_api.py`（纯函数，不起服务）。FILMUI 在 ns_api 里挂下面两个路由，直接调用这些函数，出图走现有出图道（`ns_render.comfy_client`）。

## GET /api/image-workshop/bases → `bases_api.list_bases()`

返回数组，每项字段：

| 字段 | 说明 |
|---|---|
| id | `qwen21` / `klein` / `moss` |
| name | 显示名 |
| license | 许可证（Qwen Research / FLUX Kommunity / Apache-2.0） |
| state | `ready` / `not_ready` / `smoke_ok_pending_review` |
| state_detail | 就绪说明 |
| max_refs | 最多参考图数 |
| default_preset | 默认预设 |
| size | 默认尺寸 |
| presets | `[{id, label}]` |

就绪状态的唯一来源是 `data/ab/imglab/bases_status.json`，由 IMGLAB 在冒烟或 A/B 之后更新。只有 state = `ready` 的基座才开放出图（就绪一个开放一个）。

## POST /api/image-workshop/jobs → `bases_api.build_jobs(...)`

请求字段：

| 字段 | 说明 |
|---|---|
| base | 基座 id |
| prompt | 提示词 |
| refs | 参考图槽，最多 max_refs 张。qwen21 传仓库相对路径加 upload 回调；klein 传已上传的名字 |
| seed | 可选；给了就按 seed、seed+1… 递增 |
| count | 张数 |
| width / height | 尺寸 |
| preset | 预设 |

返回 `[{seed, graph}]`，每张一个 ComfyUI 图。路由负责把图交给出图道，再把结果文件返回前端。

规则：
- 未就绪的基座抛 `PermissionError`，路由返回 409，带上 state_detail。
- 预设不属于所选基座时抛 `ValueError`，路由返回 422。

## 当前就绪情况（11-02 12:50，如实）

| 基座 | 状态 | 说明 |
|---|---|---|
| qwen21（S★ R0） | ready | 生产在用 |
| moss | 冒烟通过，待总调度亲审 | 两台服务器权重齐全、sha256 一致。ep01-S1 出了 1 张，189.6 s，画面正常，有水晶甲；无身份参考，脸不是林晚 |
| klein | 未就绪 | 两台服务器权重齐全、sha256 一致；冒烟还没出成：12:10 的窗口隧道断开，12:46 前只出了 2 张，都不是 Klein。时尚大片对比里会出第一张 Klein |

## 预设（待项目方挑定后加入 PRESETS）

“写实”和“时尚大片”预设现在只在 `data/ab/imglab/realism/arms.json` 里登记为候选，还不开放。等项目方在 `data/review_pages/realism/` 选定后，再写进 `bases_api.PRESETS`，作为设定图、宣传图和图像工坊的新预设。
剧集观感仍是 S★ R0（L-087），换不换由项目方定。
