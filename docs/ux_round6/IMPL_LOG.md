# UX6 实现日志（UI6：资产二次修改 P1 + 资产中心 B6–B10 + 剧本创作/导入合一）

- 输入：`docs/ux_round5/IMPL_LOG.md`（UI5 遗留）、`B_revision.md` §2.2 / §2.6 / §5 / §7 P1、`A_assets_ia.md` §3.4 / §5 B6–B10、`D_workflow_visual.md` D5。
- 约束（全部遵守）：
  - 没有重启 :8800，新后端等总调度安排；没有提交渲染；没有 git 提交；没有改剧本内容；不做内容检测；没删任何数据。
  - `config/` 一个字节都没改：需要改配置的回滚、音色修改，一律写提议到 `data/assets/proposals/`。
  - 没碰 `data/ab/`、`data/episodes/ep02*`、`services/post`、`services/render_router`、`tools/iterate_loop`。
- 截图在 `apps/web/e2e/ux6/`：
  - 工具：`shoot_ux6.mjs`。自起无头 Chrome（CDP :9675），在 CDP Fetch 层拦下全部非 GET 请求。
  - 只读旁路：`ux6_sidecar.py`，端口 :8802。它关掉了 observe、快照和账本写入；中间件除只读的 impact 外，其余非 GET 一律回 403。

---

## 1. B 的 P1 后端：写路径、回滚、快照、保留旧版、成片过期、LoRA registry

| 项 | 实现 | 文件 |
|---|---|---|
| 快照 | `snapshot(key)` 把某依赖键的当前内容存到 `data/assets/snapshots/<type>/<id>/<rev>/`：`manifest.json` 加上原地覆盖型文件的副本（定妆母版 `plates/master.png`、face_reference 指向的脸图）。配置型的键只存 JSON 片段。同一 rev 只存一次。复制完再算一次 rev，对不上就不写 manifest（文件留着，不删）。`observe()` 每见到新 rev 就顺手快照，所以被动观察到的版本也留得住内容。另外提供 `snapshot_before_overwrite(path)`，给以后原地覆盖母版的代码调用 | `services/agent/ns_agent/asset_revs_p1.py`、`asset_revs.py`（observe 尾部 7 行） |
| 移当前指针 / 回滚 | `POST /api/revisions/{key}/set-current {rev, by, owner_quote?, note?}`，步骤如下：<br>① 闸门类（定妆 / 身份参考 `identity`、身份 LoRA 指针 `loraslot`、音色 `voice`）要求 `by=owner` 且原话不为空，否则 **403**。<br>② 目标版本没有快照时回 **409**，并说明原因。<br>③ 原地覆盖前，先给当前内容自动快照；快照失败就不覆盖。<br>④ `assets/` 下的文件从快照恢复。<br>⑤ 配置型部分不直接写，写提议：`config/*.json`（LoRA 指针、预设、视频基底、附加视频 LoRA、音色、face_reference 指针）和 `asset_refs.json` 的身份参考启用状态。<br>⑥ 真的回到目标 rev 后，在账本 `revisions.jsonl` 记一行（by / owner_quote / source / snapshot / rollback），动作日志 `revision_actions.jsonl` 也记一行。之后 observe 不会再把它当成“未登记的改动” | `revisions_p1.py`、`asset_revs_p1.set_current` |
| 账本详情补字段 | `GET /api/revisions/{key}` 新增三项：每个版本的 `has_snapshot`，`gated` / `gate_label`（是否项目方闸门），`config_backed`（回滚只写提议） | `revisions.py` |
| 保留旧版（kept 豁免） | `POST /api/shots/{id}/deps/keep {stage, key, n?, by:"owner", owner_quote}`，缺原话 403。记到 `data/assets/dep_waivers.jsonl`，存的是豁免当时的 rev。**只对那一个 rev 生效**，依赖再变一次就重新提示。`GET /api/shots/{id}/deps` 的每条 stale 项带 `waived` 字段。`GET /api/shots/{id}/deps/waivers` 可查记录 | `revisions_p1.py`、`revisions.py` |
| 成片过期 | `GET /api/episodes/{n}/cut/deps`，取最新一版成片（不算 `_4k` 副本）：<br>· “落后 N 镜”**复用** UX5 `cuts._summary` 已有的比对：成片里用的视频不等于现在的定稿，`_cc` 校色副本算同一版。<br>· 再加一项：账本里成片之后改过的音色，标为“需要重新合成” | `revisions_p1.py` |
| LoRA registry 扩展 | gpu3 的 `LORA_REGISTRY.json` 和 `models.lock` **不改**。另建扩展文件 `data/assets/lora_registry_ext.json`：<br>· `POST /api/loras/registry` 登记一个版本，一律 candidate。视频身份 LoRA 带 `sha256`（给本机路径就现算）、`from_identity_rev`（不填就取登记时的定妆 rev）、`dataset_manifest` / `dataset_sha`、`step`。<br>· `POST /api/loras/registry/{id}/status`：采用或作废属于项目方闸门，缺原话 403。<br>· 新依赖键 `loraslot:<slug>:video`，取已采用的版本，并带上视频身份总开关。 | `services/agent/ns_agent/lora_registry.py`、`asset_revs.py` |
| 前端“回到这版” | 资产详情的版本栈：<br>· 有快照的旧版本才亮，否则悬停写原因（“P1 之前登记的，只记了指纹、没留内容快照”）。<br>· 二次确认框（`OwnerConfirm`，挂到 body）。闸门类在按钮旁和确认框里都标 **“需你本人确认”**，必须填原话，请求带 `by=owner + owner_quote`。<br>· 确认框写明：会先自动快照、配置型只写提议、不自动重出。 | `v3/assets/AssetInspector.tsx`、`OwnerConfirm.tsx`、`rev_api.ts`（`p1Api`） |
| 前端“保留旧版…” | 精修右栏“资产”页签：每条“依赖已更新”旁边加按钮，原话必填。已豁免的划线显示原话，不计入角标 | `v3/edit/ShotAssetsTab.tsx`、`edit.css` |
| 前端成片 | 成片页最新一版：成片之后改过音色时，标“音色改过 N” | `v3/pages/CutPage.tsx` |

测试：`tests/test_revisions_p1_ux6.py`，前 8 条覆盖以下几点。
- observe 自动快照。
- 闸门 403：by≠owner、没有原话、原话只有空白，三种都拒。
- 回滚：恢复母版，被覆盖掉的一版仍能再回去，账本 by=owner、带原话、rollback，observe 不重复记。
- 没有快照时回 409。
- 配置型回滚：只写提议，config 字节不变；音色闸门 403。
- `snapshot_before_overwrite`。
- 保留旧版：只对一个 rev 生效，依赖再变就失效。
- 成片落后 1 镜，并识别成片之后改过的音色。
- LoRA 视频版本：带 sha 和定妆 rev，采用要闸门；采用后出现 `loraslot:…:video`；母版换了以后标“训练数据来自旧定妆”；gpu3 registry 和 models.lock 不被改。

## 2. A 的 B6：新版本和另存为新资产分开

- 后端：
  - `POST /api/assets/{id}/versions` 新增 `mode`：`version` 进同一资产的版本链（资产 id 不变），`save_as` 另存为新资产。不填 `mode` 时按旧的 `in_place` 处理，兼容旧调用和旧测试。
  - 新增 `POST /api/assets/{id}/fork`，专门做另存为新资产。
  - `GET /api/assets/{id}/chain` 返回形象 / 单品的版本链；以前复制出的 `<id>-vN`（`asset_versions` 里 `from_asset=本资产` 且不是 in_place，或 id 形如 `<id>-vN`）**只映射显示**为“历史复制”，**不合并、不删**。
  - `POST /api/assets/{id}/chain/set-current`：只对形象做，把链上某一版设回当前预览，经 LookStore，用到它的镜头标过期，不重出。单品的当前图按“偏好角度 + 最新版本”自动取，所以先回 409，并说明原因。
- 前端：
  - 资产编辑抽屉：“存为这个形象 / 单品的新版本（进版本链，资产不变）”放在第一项，从资产中心打开时默认选它；“另存为新…”和“只这一镜”走 `/fork`。旧后端没有 `/fork`（405 / 404 Not Found）时，退回 versions 的旧默认，行为相同。
  - 详情抽屉读版本链，“历史复制”单独一节。
- 测试：`test_b6_version_chain_vs_save_as_and_history_copies`。现网数据里目前没有 `<id>-vN` 复制品，映射逻辑由测试覆盖。

## 3. A 的 B7–B10：只读 + 最小可编辑

| # | 后端 | 前端（资产中心） |
|---|---|---|
| B7 道具 | `GET /api/props`：衣橱里带 LoRA 的饰品**只读映射**，加上 `data/props.json` 的自建条目。`POST` / `PUT /api/props` 只改自建条目的登记信息（名称、类型、LoRA 文件、触发词、说明），不动衣橱 | “道具·产品”页顶部加自建道具表，有“新建 / 改…”；下面照常是映射卡 |
| B8 音色 | `GET /api/voices`：`config/voices.json` 只读，带当前 rev / vN 和待处理提议。`POST /api/voices/{cid}/proposals` 写提议到 `data/assets/proposals/`，**不改 config**；标 `requires_owner`，附了原话就标 `owner_confirmed` | “声音·音色”页：音色表加“提议修改…”，可选附原话（换音色属于项目方闸门） |
| B9 LoRA 总表 | `GET /api/loras`：只读合并 gpu3 registry、models.lock、出图指针、附加视频 LoRA、衣橱、剧本 `lora_triggers`、登记扩展；另列训练数据集是否来自旧定妆 | 左栏“风格 → 全部 LoRA（总表）”：阶段、所属、状态、sha（没有就标“没有 sha”）、触发词·强度、版本 / 训练、来源 |
| B10 提示词模板 | `/api/prompt-templates`（存在 `data/prompt_templates.json`）：每次修改加一个新版本，旧版本保留。**正文只能由 `by=owner` 或 `writer:<名>` 写**，其他一律 403，系统不生成、不改写。引用记录写 `data/prompt_template_refs.jsonl`，`/usage` 可反查 | “提示词模板”页：列表、新建、“存新版本…”（选“项目方本人 / 写作方”） |

测试：`test_b7_b8_b10_props_voices_templates`，覆盖音色提议不改 config、模板作者闸门、引用版本校验。

## 4. D5：剧本创作和导入合成一页；旧壳改成跳转

- `#/script-create` 改成“剧本”一页：顶部是 **① 创作 → ② 导入**。① 是原剧本创作页，② 是原 ImportView（`#/script-create?tab=import`）。两个组件都没改，只改了入口和跳转。①“去导入页”换成页内切到 ②。
- 跳转（旧代码保留，地址栏带 `?legacy=1` 仍走旧页）：
  - `/?view=import` 跳到 ②。
  - `/?view=assets` 跳到 `#/assets`。
  - `/?view=people` 跳到 `#/assets?type=character`。
  - 上次停在旧页（存在 `ns.view` 里）时，刷新也一样跳转。
  - `setView("assets" | "people" | "import")` 的其他调用方，也一律改成跳转。
- 工具菜单：
  - “剧本导入”指向 ②。
  - “新建人物·上传参考图”改成“人物（角色）”，指向资产中心。
  - “旧资产库”改成“旧资产库 → 已并入资产中心”。
  - 资产中心左栏底部写“旧资产库、人物管理已并入这里”，保留“人物登记（旧页）↗”：新建人物还没搬过来。
- 写作对话框里“去导入”的链接也改到 ②。
- 截图：`impl_r3_script_create_*`、`impl_r3_script_import_*`、`impl_r3_redirect_people_1440_dark`、`impl_r3_redirect_import_1440_light`。

## 5. 截图复核

| 轮 | 内容 | 张数 | 非 GET | 转旁路 | 控制台错误 | 横向滚动 |
|---|---|---|---|---|---|---|
| r1 | 初版全看一遍 | 47 | 0 | 236 | 0 | 0 |
| r2 | 修正后：林晚音色回滚闸门、预设回滚、音色提议、新建道具 / 模板、形象编辑抽屉 | 27 | 0 | 186 | 0 | 0 |
| r3 | 最终矩阵 1280 / 1440 / 1920 × 深浅 | 69 | 0 | 360 | 0 | 0 |
| r3_apiold | 关掉旁路，模拟 :8800 未重启 | 5 | 0 | 0 | 0 | 0 |

- r1 → r2 的改动：
  - 确认框改为挂到 body，从抽屉里打开也能盖住整页。
  - LoRA 总表和模板页去掉重复标题；文件列加最小宽度。
  - 音色提议没改动时，确认键禁用并写原因。
  - 原话框的提示文字按资产写。
- 演示账本：真实账本 `data/assets/revisions.jsonl` 要等 :8800 重启后才开始记，现在是空的。为了截到“版本列表 + 回到这版”，旁路在**内存里**给林晚定妆、林晚音色、徕卡 S★ 各造了一条“上一版”，没写盘。截图里这几张卡显示的“依赖已更新 / 未经系统的改动”来自这份演示账本。
- 降级（`impl_r3_apiold_*`）：LoRA 总表、音色、模板、道具都显示 LoadError，写明“等 API 重启后出现”。详情抽屉的版本链读不到时，退回资产里已有的图片版本；“回到这版”禁用并写原因。其余照常。
- 精修“资产”页签（`impl_r3_edit_assets_*`）：ep02-S3 首帧 #5 / 尾帧 #2 的“依赖已更新：本镜输入”旁有“保留旧版…”。

## 6. 检查

- `npx tsc --noEmit` 通过。
- `vite build` 通过，输出到 scratchpad，不覆盖 `apps/web/dist`。
- `npm run ds:stats` 没超过基线。
- 本轮测试 `tests/test_revisions_p1_ux6.py` 10 条全部通过。相关旧测试（`test_asset_revs_p0`、`test_ref_switch_w5`、`test_scenes_s2_s3`、`test_cuts_ux5`、`test_revisions_impact_shots_ux5`）43 条全部通过。
- `pytest` 全量：**1111 passed，6 skipped，3 failed**。失败的 3 条都在别的线：
  - `test_recipes_engine::test_select_types`、`::test_graph_variants_link_integrity`：期望 Motion_Repair 强度 0.9，实际 0.4。recipes 注册表被并行的 LAB / V2 线改过；这个测试文件本身也是未跟踪的新文件。
  - `test_iterate_loop::test_recipe_plan_body_for_api`：`tools/iterate_loop`，本轮不碰。
  - 本轮没有碰 `services/recipes`、`tools/iterate_loop`，已报总调度。
- 测试全部用临时项目根。跑完后真实 `data/assets/` 只有原来 3 个文件，没有新增账本、快照或提议。

## 7. 要等 :8800 重启才生效

上线时只需要重启 API，前端已就绪。没上线前，界面都按第 5 节写的方式降级。

- 新路由：`revisions_p1`、`asset_center_p1`。`app.py` 只加了两行 `include_router`。
- 改动的已有模块：`revisions.py`（has_snapshot / gated / waived）、`asset_edit.py`（`mode`）、`asset_revs.py`（observe 快照、视频 LoRA 指针）。

**重启后会自动发生**：第一次 `GET /api/revisions/keys` 时，observe 会写 baseline 账本，并给所有当前版本各存一份快照。体量：林晚母版约 2.6 MB，其余是小 JSON。

## 8. 还没做 / 留给下一轮

- 修改重出队列 `POST /api/revisions/rerun`：带 reason / priority 的 EB、进度挂在账本行上。现在的重出仍走 UX5 的“影响面 → 勾选 → `/produce`（review）”。
- 同种子 A/B（代表镜按旧 / 新 rev 各出一版）、剧本按字段对比：都要提交渲染或碰导入，本轮不做。
- 装配器把 `deps` 写进 `epXX.timeline.json`：要改 `services/post`，本轮禁止碰。成片过期目前靠“定稿视频比对 + 账本里音色改动的时间”。
- 单品主图指针（单品“回到这版”）：现在是禁用的，并写明原因。
- 提议的落地（把 `data/assets/proposals/*.json` 应用到 config）：要项目方 / 总调度同意写入通道。
- COMP 建议的片段行、按场预演、best-of-k、局部重做（`competitor_flows.md` §4）：需要 ARCH 的后端支持，没动。
