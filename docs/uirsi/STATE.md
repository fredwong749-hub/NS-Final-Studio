# UIRSI 现状盘点（STATE）

UIRSI 是 NS-Final Studio UI/UX 的长期负责人，按 RSI 方式工作：每轮先按 `RUBRIC.md` 打分，再修分数最低的项，然后复测。本文是起点盘点，每轮结束更新 §6。

- 初版：2026-10-31
- 依据：
  - `apps/web/src` 实读；
  - 历史文档：`docs/ux_round5/*`、`docs/ux_round6/IMPL_LOG.md`、`ux_round4.md`、`ux_audit_round3.md`、`xyq_*.md`、`ep02_iter/competitor_flows.md`；
  - 链条：`docs/PIPELINE_CHAIN.md`、`config/pipeline/chain.yaml`；
  - Autopilot：`docs/AUTOPILOT.md`、`tools/autopilot/run.py`、`tools/pipeline/run_chain.py`。

---

## 1. 页面、入口、路由清单

**顶层路由**在 `projects/Root.tsx`，按 hash 分三支：
- `#/script-chat` → 旧剧本对话框；
- `#/projects…`、`#/inbox` → 项目页；
- 其余 → 画布 App（`App.tsx`）。

| 路由 / 入口 | 组件 | 状态 | 怎么进 |
|---|---|---|---|
| `#epNN`、`#epNN-SK` | `v3/Canvas.tsx`：审片（一镜一行）/ 精修（单镜三区，`?mode=edit` 或 Enter / L / 双击） | 主界面 | 默认；顶栏 ③④ |
| `#/script-create` | `v3/pages/ScriptFlowPage.tsx`（**UIRSI r1 改**）：① 新建剧本（`NewScriptPage`，`?run=<id>`）→ ② 导入（`?tab=import`，`ImportView`）；旁路“单集对话写作”（`?tab=chat`，原 `ScriptCreatePage`） | 现行 | **顶栏“＋ 新建剧本”（r1 新增）**、快捷键 N（r1 新增）、工具▾ → 剧本、项目页、资料清单“去剧本” |
| `#/assets`（`?type=… / char= / from=`） | `v3/assets/AssetCenter.tsx`（角色详情嵌 `v3/pages/AssetsPage`） | 现行 | 顶栏 ②、快捷键 4、工具▾ |
| `#/cut` | `v3/pages/CutPage.tsx` | 现行 | 顶栏 ⑤、快捷键 5 |
| `#/models` | `v3/pages/ModelsPage.tsx` | 现行 | 工具▾ |
| `#/projects`、`/new`、`/<slug>/wizard/<step>`、`/<slug>/board`、`#/inbox` | `projects/*`：项目、新建剧向导、看板、待办 | 现行，但自带一套小顶栏（D6 旧壳） | 工具▾ → 项目 · 新建剧 |
| `#/script-chat` | `chat/ChatApp.tsx` | legacy（工具▾ → 旧版入口） | 只用来翻旧会话 |
| 抽屉 / 弹层 | 资料清单 `MaterialsDrawer`（顶栏 ①）、任务队列、批量、对比、接缝、串播 `ReviewMode`（R）、看图 `Viewer`、搜索 `Palette`（G）、快捷键 `HelpDialog`（?） | 现行 | — |
| 旧视图 `view=overview / nodes / ab / classic / table / storyboard` | `OverviewGrid`、`NodeView`、`ScriptAB`、旧镜头行 + `Inspector`、表格、分镜表 | overview / nodes / classic 属于 legacy；表格 / 分镜表 / A/B 仍在用 | 工具▾；快捷键 1 仍进旧总览（D27 待办） |
| 已跳转的旧页面 | `/?view=assets` → `#/assets`；`/?view=people` → `#/assets?type=character`；`/?view=import` → `#/script-create?tab=import` | 加 `?legacy=1` 仍走旧页 | `store.tsx LEGACY_REDIRECT` |
| 死代码 | `components/TopBar.tsx`（T59 旧顶栏） | 没有引用（D22） | — |

---

## 2. “新建剧本”入口为什么没了（查证）

**结论**：入口没有被删掉，而是被两次改动“藏”起来了。

1. **UX5 第 2 轮 D2**（`docs/ux_round5/IMPL_LOG.md` §2 第一行，`TopBarV3.tsx` 第 74 行注释“以前 ① 去写新剧本”）
   - 审查认为：步骤条 ①“剧本 · N 镜待补”点进去应该是“缺什么”的清单，而不是写新剧本的页面。
   - 于是 ① 改成打开资料清单抽屉。
   - 这一改，顶栏上唯一能一键进“写新剧本”的入口就没了。
2. **T59 → v3 顶栏**
   - 更早的旧顶栏 `components/TopBar.tsx` 有一个一级菜单“剧本▾ → 创作”。
   - v3 顶栏（W4a 规格 §1）把四个下拉都收进了“工具▾”。
   - 结果“剧本创作”只剩工具菜单里的一行。
3. **UX6 D5** 把 `/script-create` 合并成“① 创作 → ② 导入”一页。
   - 这一步本身没删入口。
   - 但页面标题变成了“剧本”，“创作”看起来像导入前的一个步骤，而不是“开一部新剧”。
4. **项目页**的“＋ 新建剧”其实是 T42 的项目目录向导：要先有剧本三件套，不能从提纲开始。名字相近，容易认错。

**r1 的修法**：
- 顶栏左侧常驻“＋ 新建剧本”，按 N 也能打开；
- 工具菜单第一项改成“新建剧本”；
- 项目页的主按钮改成“＋ 新建剧本（从提纲）”，原向导改名“新建剧项目（已有剧本）”；
- 剧本页 ① 换成真正的“提纲 → 自动写 P1–P4”。

原来的单集流式写作改名“单集对话写作”，作为旁路保留。

---

## 3. 链条 P0–P12 在界面上的位置与缺口

图例：✅ 有界面，自动填好的内容和你的闸门都在；◐ 有界面但缺一块；✗ 没有界面。

| 节点 | 内容 | 界面位置 | 自动填的内容 | 你的闸门 | 状态 / 缺口 |
|---|---|---|---|---|---|
| P0 提纲 | Brief JSON | **r1 新增** `#/script-create` ① 表单 | — | 你写 | ✅（r1） |
| P1 故事线 | 人物表、场景表、分集 | **r1** ① 运行详情 P1 卡：表格、原文、校验问题、改原文、返修 | 写作模型 | 可选（默认自动通过） | ◐ 人物表和场景表还不能一键“登记进资产中心”（P1→P5 衔接） |
| P2 单集大纲 | 节拍表 | **r1** P2 卡：节拍表、秒数合计 | 写作模型 | 可选 | ✅ |
| P3 剧本 | 场次、台词 | **r1** P3 卡：场次 + 台词排版 | 写作模型 | — | ✅ |
| P4 剧本分镜 | Markdown → Shot Spec | **r1** P4 卡（逐镜卡片）→“送去导入” → ② 导入（勾选“我是项目方”）→ 画布分镜字段 / 分镜表 | 写作模型 + 校验 | **导入确认** | ◐ D5 遗留：导入要再校验一次、确认分两步、导入后不自动打开新集 |
| P5 资产 | 身份、造型、场景、音色 | `#/assets`（总览顶部“第 N 集造型确认”）、顶栏 ② | 系统映射 | **定妆** | ◐ A1：新建人物还在旧页；P1 人物表和资产不相通 |
| P6 首尾帧 | 首帧 / 尾帧 | 画布审片行、精修中区 | 渲染 | **首尾帧定稿** | ✅ |
| P7 视频提示词 + 配方 | H3 / RenderPlan | 精修右栏提示词 / 高级 | 编译器 | — | ◐ D12：参数分散在 3 处 |
| P8 视频 | take | 审片行视频格、精修 | 渲染 | 通过 / 打回 | ✅ |
| P9 声音 | 对白 / 独白 / BGM | 审片行“声音”行；成片对白来源只读 | 系统 | — | ◐ W12：声音 A/B 没有入口；U12：对白来源不能切 |
| P10 合成 | timeline + mp4 | `#/cut`“合成新版本…” | 系统 | — | ✅ |
| P11 审片 | 判定 | 串播 R；Autopilot 审片页 `data/review_pages/<集>/` 不在 App 里 | 审片模型 | 通过 / 打回 | ◐ Autopilot 的审片结果没进 App |
| P12 成片交付 | 交付 | `#/cut` | — | **成片闸门** | ◐ 成片页没有“交付 / 确认成片”这个动作，Autopilot 的 delivery 闸门只能用命令行 approve |

**跨节点缺口**：
- 没有一屏能看到“这部剧现在走到 P 几、卡在谁手上”。顶栏 5 步是按集的。
- Autopilot 运行（`data/autopilot/<id>/state.json`）在 App 里看不到。

---

## 4. 已知问题清单（历史审查提出、还没修）

完整清单由 UIRSI 第一步汇总（来源 UX5/6 IMPL_LOG 的“还没做”和 A/B/C/D 审查），下面按优先级排。编号沿用原文档。

**P0：影响主流程**
- **D5 余项**：导入复用创作时的校验结果；“我是项目方 + 导入”合成一步；导入后打开新集。
- **W1**：没有“新建一集”的动作（r1 的新建剧本部分解决：提纲 → 分镜 → 导入）。
- **P12**：成片页缺“确认交付”闸门。
- **P1→P5**：故事线里的人物表 / 场景表进不了资产中心。
- **D13**：导入页 14 份候选平铺，最新一份不置顶。
- **D32**：一个区域里主按钮太多（审片 4 个、导入 5 个、模型页 3 个）。

**P1：找东西 / 一致性**
- **D6**：旧壳还有 5 套（旧总览、旧镜头行、剧本 A/B、`#/script-chat`、项目页小顶栏）。
- **D27**：快捷键 1 仍进旧总览。
- **D§3.3**：词表没统一（出 / 生成 / 渲染 / 重渲，定稿 / 锁定 / 设为当前，底图 / 底板 / 场景图）。
- **D§5**：顶栏重排（卡和队列合成“后台”，整集出片挪进画布页头）。
- **A1**：新建人物没迁过来。
- **A7**：角色详情仍是旧页嵌入。
- **A9**：场景有两套键。
- **A11**：本镜资产面板不全。
- **A13**：预设 / LoRA 没有作用范围。
- **D12**：参数分散在 3 处。
- **W6**：“设为当前”和“定稿”是两个概念。
- **W8**：打回没有常用原因可选。

**P2：状态 / 视觉 / 可达性**
- **D3 / D28**：断线、冷启动时没有外壳和缓存。
- **D9 / D24**：状态胶囊重复；红字“资料不全”口径不一。
- **D25**：任务抽屉在换页时不收起。
- **D29**：浅色 `--c-text-2` 偏淡。
- **D30**：审片行不在 Tab 顺序里。
- **D31**：整集出片弹层显示英文 “Failed to fetch”。
- **D16 / D17 / D19 / D§4.3**：旧按钮类名、重复选择器、间距 token 没落地。
- **#30**：对比视图没有 A/B 播放条。
- **3(b)**：参考切换面板是模态的。
- **U8**：1280 宽下声音行被隐藏。

**需要后端或别的线**：
- G11 修改重出队列；
- 同种子 A/B；
- 按字段 diff 剧本；
- 片段行、按场预演、best-of-k、局部重做（COMP，ARCH 负责）。

---

## 5. 设计系统现状（`npm run ds:stats`，2026-10-31）

- theme.css 以外仍有：写死的 hex 14 处、rgba 29 处、px 字号 125 处、不在档位上的圆角 18 处。**没有超过基线。**
  - 多的几个文件：`canvas-v2.css`（px 字号 20）、`canvas-v3.css`（18）、`styles.css`（17）、`assets-v3.css`（11）、`projects.css`（10）。
- 已有的 token：
  - 颜色 `--c-*`，深浅两套，含 `*-soft / *-text`；
  - 圆角 4 档；
  - 字号 `--fs-xs/sm/m/lg/xl`；
  - 间距 `--sp-1…8`（已定义，但老 CSS 基本没用）；
  - 控件高 `--h-xs/s/m`；
  - 阴影 `--sh-1/pop`；
  - 层级 `--z-*`。
- 组件层 `src/ds`：Button、Tag、Card、Seg、Tabs、Empty、Loading / Skel、LoadError、Drawer、Modal、StatusTag。
- 截图工具 `apps/web/e2e/uirsi/shoot.mjs`：
  - 用 CDP :9681；
  - 拦下全部非 GET 请求；
  - `/api/story-runs` 在 :8800 重启前转到只读旁路 :8803（`uirsi_sidecar.py`）。

---

## 6. 进展（每轮更新）

| 轮 | 改了什么 | 记录 |
|---|---|---|
| r1 | 新建剧本入口和页面：提纲 → P1–P4 自动写，每段可看、可改、可返修，送去导入；后端 `/api/story-runs`，测试 7 条 | `rounds/r1.md` |
| r2–r4 | P1↔资产中心对照、P4 逐镜卡片、导入页最新置顶/折叠/定位、成片交付闸门、链条下游带真实进度 | `rounds/r1-r4.md` |
| r5–r7 | **全站重构**：只剩一个外壳（新建剧本 / 导入 / 资产中心 / 画布 / 成片 / 模型），31 个旧文件归档到 `data/_archive/20261031/code/apps_web/`（MANIFEST.tsv）；momoso 品牌（候选 2 双环）；整季运行 series10_v1 可看；方案 A/B/C 成片自动出现；资产卡显示挑定设定图 + 身份参考；排版自动审计（R14–R17）并收敛到 token | `rounds/r5-r7.md` |

> **r5 起 §1 的路由表已过时**：`#/script-chat`、`#/projects…`、`#/inbox`、`/?view=overview|nodes|ab|people|assets|import`、`?legacy=1`、旧镜头行 + 检查器全部下线（旧地址跳转到新页面）；人物登记在 `#/assets?type=people`；快捷键 1 = 换集搜索。

| r8–r34 | 见各轮记录（本表 r7 之后没逐轮更新，⤴ 以 `rounds/` 为准） | `rounds/r8-r10.md` … `rounds/r34.md` |
| r35 | 候选标签去内部记录（plainLabel）、画布 ↻ 只露图标、后端连不上时成片页 / 剧本页说人话；K-UI-037 | `rounds/r35.md` |
| r36 | 按总调度决定把 ↻ 放到帧格右上角（TileTop 一行、不压脸、78px 不动）；资产中心等加载失败提示去接口路径（ASSETUX 不在岗，总调度派）；检查扫全站 | `rounds/r36.md` |
| r37 | 候选对比弹窗鼠标打得开（data-zoom-own）、读取中 / 读不到不说成“没有”、窄帧格标签和 ↻ 悬停才显示、视频 N 版待选、身份脸只收脸部裁切的前端关口；K-UI-039/040/041 | `rounds/r37.md` |
| r38 | 实时连接状态（顶栏胶囊 + GPU 面板顶部明细，/api/infra/status 只读看门狗 / 常驻状态）、卡片“连不上”说原因、最近出图先用本机副本不裂图；K-UI-042 | `rounds/r38.md` |
| r39 | 连接状态改以 NETFIX net_status.json 为主（不新鲜退回看门狗）、派图模式一行、顶栏短字（A + C）、卡片离线说人话；K-UI-042 补充 | `rounds/r39.md` |
