# UIAUDIT 独立复核：UIRSI 第 3 批（剧本 A/B 吸顶、进度条回退描边、PW-019 拆模块回归）

复核方：UIAUDIT。日期 2026-11-01，测的是 :5173。流程文件 `flows_uirsi_b3.json`、`flows_uirsi_b3b.json`，结果在 `ub3_detect.json`、`ub3b_detect.json`。

**结论：通过（能测的项目都通过）。** 两项因为数据状态测不到，记为"未测"。

| 项 | 实测 | 判定 |
|---|---|---|
| 1 剧本 A/B 在 1920×1080 下 scroll-padding-top | 48px；吸顶标题行高 37px | ✓ |
| 1 Tab 走焦点时有没有被吸顶条盖住 | 真实 Tab 走了 39 步：被盖住 0 步，焦点跑到屏幕外 0 步 | ✓ |
| 2 进度条回退段的细黄边 | 当前没有进度回退的段，页面上找不到这种元素 | **未测（状态相关）** |
| 3 撤销提示条（showUndo / UndoHost 拆模块） | `UndoHost` 挂在 App.tsx 第 168 行；`showUndo` 在 `ds/Undo.helpers.ts`；tsc 0 错误。界面上点"✓ 用这张""选这张"时，写请求被 UIAUDIT 拦下，出现的是失败提示（"没设成 / 没成功 · 再试一次"）。带"撤销 10s"的提示条要写成功才会出现，测不到 | 代码 ✓；界面**未测**（要真写一次） |
| 3 登录（useMe 挪到 AuthGate.helpers） | 工具菜单显示"账户 · 查看者（截图检查）"和"换账户或离开"，查看者身份判断正确 | ✓（项目方身份没测） |
| 3 待你决定（DECIDABLE / actionTitle 挪到 OwnerDecision.helpers） | 代码引用正常（Canvas.tsx:22/48、OwnerDecision.tsx:12/73），tsc 0 错误。第 1–5 集画布集头当前都没有"待你决定"按钮 | 代码 ✓；界面**未测**（现在没有待决事项） |
| 4 设置 / 导入 / 写作对话 / 模型的灰按钮原因 | 第 2 批已验证（`verify_uirsi_batch2.md`）。本批没改，也没重测 | — |
| G10 | `r15g_detect.json`：P0 = 0 | ✓ |

本复核没有发出任何写请求。
