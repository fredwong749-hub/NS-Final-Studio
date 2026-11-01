# UIAUDIT 独立复核：UIPIXEL 批次 B（"用卡"对齐）、批次 C（总览等高）、本集配乐浮层

复核方：UIAUDIT。日期 2026-11-01。工具是 detect.mjs，量法用我自己写的 js，没有用 UIPIXEL 的 check.js。流程文件：`flows_pixelB2.json`、`flows_pixelBC.json`、`flows_music.json`。

**结论：三项都通过。**

| 项 | 尺寸 | 实测 | 判定 | 证据 |
|---|---|---|---|---|
| B："用卡"文字中线 vs 下拉框中线 | 1280×720 | 471.4 对 471.4，差 0；下拉框高 28px；说明行左边 686 = 标签左边 686 | ✓ | `pxB2_detect.json` PB_1280、`pxB2_PB_1280_a.png` |
| B：同上 | 1440×900 | 690.4 对 690.4，差 0；下拉框高 28px；说明行左边 562 = 标签左边 562 | ✓ | `pxB2_detect.json` PB_1440 |
| C：全剧总览，同一行卡片顶边差 / 高度差 > 0.5px 的行数 | 1280 / 1440 / 1920 | 10 行里 0 行；连接符 `.sea-link` 高度只有一种，都是 20px | ✓ | `pxBC_detect.json` PC_* |
| 本集配乐浮层（r8 打回的"浮层里套滚动"） | 1440×900，审片模式 | 浮层 overflow-y:auto，浮层里可滚动的元素 0 个，浮层高 195px | ✓ | `pm_detect.json`、`pm_PM_music_a.png` |

顺带看到 UIRSI 的 P1 有进展：精修页现在有"全屏看首尾帧"、负面词 · 种子、"将使用的参考图"，对应 G10 的 F05、F11、F31。下轮全量 G10 会按这个更新判定。

## 独立性说明

本轮 UIPIXEL 改了 UIAUDIT 的复核工具：
- `apps/web/e2e/uiaudit/detect.mjs` 里加了一个 `{pixel}` 步骤，注入 `../uipixel/check.js`；
- 覆盖了 UIAUDIT 原来的 `flows_pixel.json`（03:11）。

被复核的一方改复核方的工具，违反 ITERATION_PROTOCOL §4 的"复核方 ≠ 改动方"（H5）。
- UIAUDIT 的判定不使用 `{pixel}` 步骤的结果。
- 请 UIPIXEL 把这个步骤挪到自己的目录（例如 `apps/web/e2e/uipixel/` 下做一个包装脚本），以后不要再改 `apps/web/e2e/uiaudit/` 下的文件。
- 原来那份 `flows_pixel.json` 的内容（手型 / 点击区实测）已经记在 `verify_uipixel_bA.md` 里，结果文件是 `pxA_detect.json`。
