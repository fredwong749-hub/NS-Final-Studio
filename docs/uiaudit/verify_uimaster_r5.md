# UIAUDIT 独立复核：UIMASTER r5（拆 helpers 后不回退 + ErrorBoundary / Viewer / 搜索框焦点）

复核方：UIAUDIT。日期 2026-11-01。测试对象是 :5173 开发服务器，全部用真实 CDP 鼠标和按键。
- 流程文件：`flows_uimaster_r5.json`、`flows_um5v2.json`
- 结果文件：`um5_detect.json`、`um5w_detect.json`
- 截图：`um5w_M5_viewer3_a.png`

**结论：通过。** ErrorBoundary 只核对了代码，界面上没能触发。

## 一、功能不回退

**G10**：`apps/web/e2e/uiaudit/r18g_detect.json`，判定文件 `r18g_regress.md`：**P0 = 0**，P1 只有 F19。

抽查：

| 位置 | 实测 | 判定 |
|---|---|---|
| 精修 · 参数页 | 有负面词、种子、"锁定 #n 的种子"；7 个下拉框都有值：用卡"自动（gpu33·卡1）"、出图预设"徕卡 S★（默认）"、采样 euler / simple、LoRA、尾帧来源"生成（由首帧编辑出尾帧）" | ✓ |
| 精修 · 版本页 | 版本链 `.v3e-ver .v3e-chain` 在 | ✓（ep02-S1 当前没有首帧版本，所以链上没有缩略图） |
| 精修 · 参考条换参考 | 点"场景"弹出"ep02-S1 · 场景 本镜参考：只能选资产库里已有的资产 × ③ 场景底图……④ 借用 / 恢复" | ✓ |
| 精修 · 视频底模 | 视频底模的下拉框只在"视频"那一栏，参数首页没有，本轮没单独展开 | 未测 |
| 画布 | 进度条在；评分 / 契约字样在；衔接按钮 8 个 | ✓ |
| 声音页 | 配乐 tab：播放器 4 个，波形元素 10 个 | ✓ |
| 资产中心 · 人物页 / 林晚页 | 已由 G10 的 RG_char 和 ASSETUX 复核覆盖（`verify_assetux_r13.md`，同一时段） | ✓ |

## 二、新行为

| # | 检查 | 实测 | 判定 |
|---|---|---|---|
| 1 | ErrorBoundary | 代码 `components/ErrorBoundary.tsx`：报错文案是人话（"……这一块出错了，其他部分不受影响……"）；提供"重试"和"重新加载页面"两个按钮；技术细节收在 `<details>` 里；判断为模块加载失败时自动整页重载，30 s 内不重复（存在 sessionStorage）。在控制台抛错只会走 window.onerror，进不了 React 的错误边界，所以界面上没能触发 | 代码 ✓；界面**未测** |
| 2 | Viewer（精修"⛶ 全屏看首尾帧"） | ep01-S1：打开的框是 role=dialog、aria-modal=true，标题"ep01-S1 特写 camera push in 缓慢推近 首帧 \| 尾帧"。Tab 6/6、Shift+Tab 6/6 焦点都留在框内；Esc 关掉后焦点回到 `BUTTON ⛶ 全屏看首尾帧` | ✓ |
| 2' | Viewer（全剧总览） | 在总览里点缩略图会直接跳到 #ep01-S1 那一镜，不打开看图器，所以这条路径没有对应的框可测 | 不适用 |
| 3 | 搜索框 | 顶栏"第 2 集 ▾" → "搜索"：焦点进到输入框（集号 / 标题 / 镜头）；Esc 关掉后焦点回到 `BUTTON 第 2 集 · 故障电梯 ▾` | ✓ |

附注：ep02-S1 的"全屏看首尾帧"目前是灰的（title"还没有首帧"），因为这一镜现在没有当前首帧，所以 Viewer 改在 ep01-S1 上测。

本复核只发 GET 请求，非 GET 请求 0 个。
