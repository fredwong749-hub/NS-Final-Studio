# UIAUDIT 独立复核：UIRSI"↻ 再生成"（画布审片行首帧 / 尾帧格）

项目方原话："添加一个生成按钮,基于现在再生成一个新的图"；"弹出需求提示词输入框,upload对应的装备(衣服,鞋子,视频,美甲等)图片,然后生图"。

复核方：UIAUDIT。日期 2026-11-01，测的是 :5173 第 2 集。全部用真实 CDP 鼠标和按键：键入用 `Input.insertText`，选图片用 `DOM.setFileInputFiles`，只读本地文件。所有写请求都被拦下，拦下时记录请求体（detect.mjs 本轮新增了这项记录）。
- 流程文件：`flows_regen.json`
- 结果文件：`rgn_detect.json`
- 截图：`rgn_RG1_count_a.png`、`rgn_RG2_dialog_a.png`、`rgn_RG5_gear_a.png`

**结论：通过。** 附 1 条 P2。

| # | 检查 | 实测 | 判定 |
|---|---|---|---|
| 1 | 有版本号的首帧 / 尾帧格都直接露出按钮 | 16 行里有版本号的格 36 个，带"↻ 再生成"的也是 36 个；⋯ 菜单里没有再生成 | ✓ |
| 1 | 草图 / 渲染中 / 未出的格子不出按钮 | 这类格 4 个，带按钮的 0 个 | ✓ |
| 2 | 点开是弹窗，焦点落在输入框 | `.ds-modal` 的 role=dialog，焦点在 TEXTAREA 上；底部提示"同提示词换种子" | ✓ |
| 2 | 焦点不跑出弹窗、Esc 能关 | Tab 6/6、Shift+Tab 6/6 都留在框里；Esc 关掉后焦点回到 `BUTTON ↻ 再生成` | ✓ |
| 2 | 底部提示随输入变化 | 不写：同提示词换种子 → 键入"换成侧脸"：按要求改 → 再加一张装备图：换装备参考再改 | ✓ |
| 2 | "+ 加一张装备图" | 加出一行：类别默认"鞋"，人物默认"林晚"，带一个文件选择框 | ✓ |
| 3a | 不写不传就提交 | 拦下 `POST /api/shots/ep02-S1/takes/image/12/regen`，请求体 `{}` | ✓ |
| 3b | 写了要求再提交 | 拦下同一路径，请求体 `{"instruction":"换成侧脸"}` | ✓ |
| 3c | 传了装备图再提交 | 依次拦下：`POST /api/character-hub/lin_wan/check-image`（multipart：file + cat=shoes）→ `POST /api/character-hub/lin_wan/wardrobe`（multipart：note="画布 ↻ 再生成 上传的装备参考（ep02-S1）"、file …）。第二步失败后**没有**再发 regen，弹窗里写"没提交成功：Failed to fetch" | ✓。顺序对，失败会停下。wardrobe 请求体被截断，`looks="[]"` 这一字段没看到 |
| 4 | 接口测试 | `pytest tests/test_takes_ui_uirsi.py`：6 passed | ✓ |

P2：`registerGear` 在查重（check-image）失败时会继续上传（`RegenButton.helpers.ts` 第 52–56 行，注释写"查重 / 起名失败不拦上传"）。查重接口不通时，可能把重复的装备图又登记一份。属于设计取舍，建议这种情况在弹窗里提示一句"没查重，可能重复"。

本复核没有发出任何写请求：全部被拦下，没有一个到达 :8800。

---

## 复测（:8800 于 11:06:41 重启、接口上线后；弹窗拆成 RegenDialog；P2 已改）——**通过**

- 接口：`/openapi.json` 里有 `/api/shots/{shot_id}/takes/{stage}/{n}/regen`。
- 按钮覆盖、弹窗焦点、空提交 / 写了要求两条路径：和上一版一样都通过（`rgn2_detect.json`）。
- 尾帧这条路径：点尾帧 #4 的"↻ 再生成"，弹窗标题是"ep02-S1 尾帧 #4"，提示"同提示词换种子"；拦下的请求是 `POST /api/shots/ep02-S1/takes/last/4/regen`，body `{}`。✓（`rgn3_detect.json`）
- 传装备图这条路径，multipart 请求体现在逐字段记录：
  - check-image：`file=<file am-ch_a_lan-495710cc_clean_v1.png> & cat=shoes`
  - wardrobe：`note=画布 ↻ 再生成 上传的装备参考（ep02-S1） & file=<file …png> & cat=shoes & name=鞋（再生成上传） & looks=[]`

  `looks=[]` 确认。✓
- P2（查重失败照样登记）：UIRSI 改成把这张图标成"没查重"，提交后的提示里会提醒。这条要等一次查重接口不通时提交成功才能看到，UIAUDIT 把所有写请求都拦了，所以这次没测到，只核对了改动的说明。**未测**。

---

## 复测 3：精修页、人物页的挂载，以及弹窗改动（:8800 于 11:17:38 重启后）

- **精修页（UIMASTER 挂的）**：见 `verify_uimaster_r6.md`。大格、版本页签两处都有按钮；请求体里的版号跟着选中的那一版走（#14 → #3）；视频格没有按钮。✓
- **人物页（ASSETUX 挂的）**（`flows_regen_char.json` → `rgc_detect.json`）：
  - 林晚页共 17 个"↻ 再生成"：身份脸 1 个，三套造型各 1 个，单品工具行 13 个。悬停提示是人话，例如"以当前身份脸为底图，按你的要求再生成一张候选"。✓
  - 点身份脸那个：弹窗标题"↻ 再生成 · 林晚 身份脸"，宽 560，焦点在 TEXTAREA；Tab 6/6、Shift+Tab 6/6 都留在框内；Esc 关闭后焦点回到按钮；**没有**"视频去视频格"那句。✓
  - 提交时拦下 `POST /api/character-hub/lin_wan/regen`，请求体是 `{"kind":"face","file":"assets/characters/lin_wan/refs/lin_wan/ar-f9519334bc.png","prompt":"换成侧脸","gear":[]}`。✓
- **弹窗宽度（390×844 手机宽）**：画布上打开，加两行装备图后弹窗宽 358，弹窗里没有元素超出右边。✓ 画布里"只收图片 / 视频去视频格"那句照常显示。
- P2（不在本次改动范围）：画布页本身在 390 宽下整页能横向滚动，画布没有为手机宽度做适配。
