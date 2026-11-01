# UIAUDIT 独立复核：ASSETUX（资产中心 r12 最新版）

复核方：UIAUDIT。日期 2026-11-01。方法：`apps/web/e2e/uiaudit/detect.mjs`（无头 Chrome，GET 带只读查看令牌，非 GET 一律拦下并计数）。

**结论：通过。**

| 检查 | 结果 | 证据 |
|---|---|---|
| G1–G5 滚动：资产 8 页 × 1440×900 / 1280×720 | 第一次 15/18。复测 4 个不过 / 关键组合（S720 总览、S720 衣橱、S900 衣橱、S900 林晚），4/4 全过。第一次的 S720 总览、S720 衣橱都记成 `main.ac-main` 没到底，判断是页面数据晚到、高度跳动（ASSETUX 已加占位），复测后不再出现。滚轮落在图上和落在空白处，结果一样（`wh_detect.json`）。 | `va1_detect.json`、`va2_detect.json`、`va2_*_scroll_main.png` |
| 衣橱 1440×900 滚到底 | ✓（lastInView=true、notBottom=[]），包括等图片加载 8 s 后再滚的情况（VA_item_late） | `va1_detect.json` VA_item_late、`va2_detect.json` S900_a_item |
| 打开页面时的非 GET 请求 | **0**（林晚页、衣橱、总览等 18 个页面全部为 0）；r8 里那条 `POST /api/voices/preview` 没有再出现 | `va1_detect.json`、`va2_detect.json` 各流程 `blocked` 字段 |
| G10 F32 缺图 / 未登记警示 | ✓ 页内导航条右端常驻"不缺图 · 文件未登记 0 个" | `va1_detect.json` VA_char collect_char |
| G11 小图放大（真实鼠标） | 5/5：悬停出放大镜，Alt+点打开原图（520–800 宽），Esc 关闭 | `va1_detect.json` VA_char zoom_linwan |
| G0 白屏 / 报错层 | 0 | `va1_stdout.txt`、`va2_stdout.txt` |

**未测（写操作，按规矩不在线上测）**：场景暂定底图的选定 / 删除、新造型的实际建立。这两项以 ASSETUX 的 pytest `test_scene_space_ref_shows_on_card_and_one_click_pick`、`test_new_look_sheet_upload_and_schedule` 为准。本复核没有跑这两个测试，未测不等于通过。

**慢页**：提示词模板页首屏 31 s（`va1_stdout.txt` 中的 S900_a_template），记 P1，归 ASSETUX 查。
