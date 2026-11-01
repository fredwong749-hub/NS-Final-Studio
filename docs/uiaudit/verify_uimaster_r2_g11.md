# UIAUDIT 独立复核：UIMASTER r2（OT4 · G11 小图都能放大）—— **通过**（第 2 版）

复核方：UIAUDIT（不是改动方）。日期 2026-11-01。

## 第 1 版作废：测法不对

第 1 版用的是 JS 合成事件：只派发 `mouseover` 和带 `altKey` 的 `click`，没有 pointerdown / mousedown。所以悬停放大镜测不出来，林晚页左栏头像也没打开（`g11_detect.json`）。UIMASTER 指出后，我改用真实输入复测（见下），结论改为通过。这是 UIAUDIT 测法的错，与被测方无关。

## 第 2 版：真实鼠标 / 键盘

- 工具：`apps/web/e2e/uiaudit/detect.mjs` 的 `{realzoom}` 步骤，流程文件 `flows_g11.json`。
- 每张小图依次做：
  1. CDP `Input.dispatchMouseEvent` mouseMoved 悬停 0.5 s，检查 `.zl-mag`；
  2. mousePressed + mouseReleased，两次都带 `modifiers:1`（Alt）；
  3. 最多等 4 s，直到大图 `complete` 且 naturalWidth>0；
  4. 真实 Esc 键按下 / 松开，检查大图框是否关闭。
- 结果文件：`apps/web/e2e/uiaudit/g11b_detect.json`；截图：`g11b_G11_canvas_a.png`、`g11b_G11_linwan_a.png`。

| 页面 | 测了几张（< 160px） | 悬停放大镜 | Alt+点打开大图 | 原图（不含 /api/thumb） | 已加载 | 说明 + 文件名 | Esc 关闭 |
|---|---|---|---|---|---|---|---|
| 画布 #ep02 | 8（人物头像 ×3、首帧缩略 ×2、本镜参考 ×2、场景底图 ×1） | 8/8 | 8/8 | 8/8 | 8/8（520–768 宽） | 8/8 | 8/8 |
| 资产中心林晚页 | 5（左栏头像 ×4、40px 身份脸缩略 ×1） | 5/5 | 5/5 | 5/5 | 5/5（520–800 宽） | 5/5（如"阿岚 · 身份脸 · ch_a_lan_face_ref.png · 800×924 · 4/4"） | 5/5 |

判定：**G11 通过**，`g11_*` 全部为 0。第 1 版里记的 noload ×3、nobox ×4 都撤销。

## 顺带：G10 功能回退（R1 用）

见 `docs/uiaudit/scorecard_r8.md` §2：P0 = 0，P1 6 条。
