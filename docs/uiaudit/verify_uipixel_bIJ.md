# UIAUDIT 独立复核：UIPIXEL 批次 I（吸顶条遮挡，G4）、批次 J（间距回到刻度）

复核方：UIAUDIT。日期 2026-11-01 约 05:55。流程文件 `flows_pixelI.json`、`flows_pixelI2.json`、`flows_pixelIJ.json`，结果在 `pxI*_detect.json`、`pxIJ_detect.json`。

**结论：通过。**"暂停"按钮那个具体场景没测到（见下）。

| 项 | 实测 | 判定 |
|---|---|---|
| I 剧本页 `main.v3-page` 的 scroll-padding-top | 72px（1440 / 1280） | ✓ |
| I 步骤条不透明 | `nav.sf-steps` 背景 rgb(12,13,16)，不透明；条底边 1440 下在 112px，1280 下在 99px | ✓ |
| I 键盘聚焦时，元素不会落到吸顶条下面 | 先把正文滚到最底，再用 `focus()` 聚焦条上方的 4 个按钮（✎ 改、🗑、林晚 A、场景名 / 用这张、▶ …）：聚焦后都在条下沿以下（1440 下 top≈500，1280 下 top≈410），在按钮中心取点，命中的都是按钮本身 | ✓ |
| I"暂停"那个场景 | 当前剧本页上没有"暂停"按钮（自动制作面板的状态变了），**未测** | 未测 |
| J 进度条段内间距 | 画布上进度条的列间距只有 4px 和 8px 两种，都落在刻度上 | ✓ |
| J `<p>` 上下外边距 | 画布上能看到的 `<p>` 外边距都是 0（没出现 3px 之类不在刻度上的值） | ✓（12px 的全局值在画布上没用到，没逐页核对） |
| — | data_parity：UIPIXEL 说 gate.sh 停在 D-FRESH ep06-S7、D-LEDGER ep02-S1。UIAUDIT 05:5x 现场复跑 `--all` 是 PASS（1394 项，0 不一致），见 verify_dataalign_d2.md | ✓ |
