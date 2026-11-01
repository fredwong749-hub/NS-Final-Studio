# UIAUDIT 独立复核：UIMASTER r3b（在当前版本上复测焦点：UIPIXEL 已把 Modal / Drawer 改成 createPortal）

复核方：UIAUDIT。日期 2026-11-01，在 :8800 于 03:49:43 重启之后。全部用真实 CDP 鼠标和按键：先点开弹框，再 Tab ×4、Shift+Tab ×4，最后按 Esc。
结果文件：`apps/web/e2e/uiaudit/r3b_detect.json`、`rt3_detect.json`。截图：`rt3_R3b_rowtrash_menu.png`、`rt3_R3b_rowtrash_a.png`。

**结论：通过（4/4）。**

| 弹框 | 尺寸 | Tab 焦点留在框内 | Shift+Tab 焦点留在框内 | Esc 关闭 | 关闭后焦点回到 | 判定 |
|---|---|---|---|---|---|---|
| 精修首帧 🗑 删除确认框 `.ds-modal` | 1440×900 | 4/4 | 4/4 | ✓ | `BUTTON 🗑` | ✓ |
| 精修"✎ 改"抽屉 `.ds-drawer` | 1440×900 | 4/4 | 4/4 | ✓ | `BUTTON ✎ 改` | ✓ |
| "✗ 不要"小框 | 1440×900 | 4/4 | 4/4 | ✓ | `BUTTON ✗ 不要` | ✓ |
| 审片行首帧格 ⋯ → 🗑 → 删除确认框 | **1280×720** | 4/4 | 4/4 | ✓ | `BUTTON 🗑`（r3 时说会落到 img.live-img 上，现在已修） | ✓ |

审片行格子的 ⋯ 是 `details.ds-tilebar-more > summary`，aria-label 是"更多操作"，不是 button。detect 已改成按坐标用真实鼠标点（新增 `{clickAt}` 步骤）。

## G10（文件名按 iter_gate 要求）

`apps/web/e2e/uiaudit/r11g_detect.json`，判定 `r11g_regress.md`：**P0 = 0**。
P1 有 2 条：F08、F19。实际都能找到：F08 在 ⋯ 菜单里有"只重出视频"，F19 串播在工具菜单里。判 P1 只是因为没在期望的那一页采到对应文字，下轮调采集位置。

本轮没有发出任何写请求。
