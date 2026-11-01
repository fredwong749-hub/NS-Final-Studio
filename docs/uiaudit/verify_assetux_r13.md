# UIAUDIT 独立复核：ASSETUX 资产中心这一批（r11 / r12 收尾：UM-0092/0179、0189/0199、0464–0470、0190–0192、0513）

复核方：UIAUDIT。日期 2026-11-01，晚于 ASSETUX 最后一次改动（PeopleHub.tsx、center.css）。测的是 :5173。
- 流程文件：`flows_assetux_b.json`、`flows_assetux_dis.json`
- 结果文件：`axb_detect.json`、`axd_detect.json`

**结论：通过。** 第 4 项只核对了代码，界面上没点到。

| # | 检查 | 实测 | 判定 |
|---|---|---|---|
| 1 | 加载占位不再并排、高矮不一（UM-0092/0179） | 人物页首屏 150 ms 时有 4 个 `.ds-skel`，同一行里高度不一的行数为 0；代码里人物页主占位只剩 `Skel h=880` 一块（PeopleHub.tsx:183） | ✓ |
| 2 | 启动画面不再停 12–14 s（UM-0189/0199） | 人物页首屏 1635 / 1640 ms；人物登记页 1129 / 1138 ms（每页各量 2 次） | ✓（< 2 s） |
| 3 | 慢接口 UM-0464–0470 | 不是资产中心的接口；DATAALIGN 修缓存后，UIAUDIT 测得首屏各接口都在 1 s 以内（`verify_firstscreen_0837.md`、`verify_dataalign_d2.md`） | ✓ |
| 4 | 部件换单品选择器的灰按钮写原因（UM-0190–0192） | 代码 PeopleHub.tsx:912：当前在用那件 `disabled` 并带 title。本轮没能用真实点击打开选择器（点到了"换音色"）；人物页首屏只有 1 个灰按钮（"‹ 上一集"），带了原因 | 代码 ✓；选择器界面**未测** |
| 5 | 吸顶条不盖住 Tab 聚焦到的控件（UM-0513，G4） | `.ac-main` 的 scroll-padding-top：人物页 56px，人物登记页 72px（ASSETUX 说的是 72px，人物页实测 56px，不影响结果）。真实 Tab 走 40 步：人物页（1440）被盖住 0 次，人物登记页（1280×720）被盖住 0 次；人物页滚动嵌套 0、能滚到底、吸顶占比（v2 口径）0% | ✓ |
| G10 | 功能回退 | `apps/web/e2e/uiaudit/r17g_detect.json`，判定 `r17g_regress.md`：**P0 = 0**（P1 只有 F19） | ✓ |

本复核只发了 GET 请求，非 GET 请求 0 个。
