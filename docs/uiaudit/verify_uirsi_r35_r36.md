# UIAUDIT 复核：基线 r19g / r20g / r21g + UIRSI r35、r36

OT1（审镜头行）、OT4（放大看图）、OT6（挑设定图）

- 复核方：UIAUDIT，2026-11-01 15:57–17:05，测 :5173（vite 开发版，项目方看到的就是这一版）。
- 写请求：全部用 CDP 拦下（detect.mjs 拦截全部非 GET），没有一个到达 :8800。
- 测后端连不上：新开关 `DETECT_API_DOWN=1`，让全部 /api、/files 请求 ConnectionRefused。
- 截图都亲眼看过。没测到的写“未测”。

## 0 总表

| 轮 | 时间 | 对谁 | G10 功能回退 | 内容断言 | data_parity | 滚动 G1–G5 | 任务 T1–T10 | 结论 |
|---|---|---|---|---|---|---|---|---|
| r19g | 16:05 | 基线（接 r18g） | P0 0 / 35，P1 1 条（F19 串播，老问题）`r19_regress.md` | 旧口径 30/30 `r19_parity.md` | PASS 80 镜 1663 项 `r19_data_parity.json` | 38/38 `r19_scroll.md` | 页面加载时 `/api/shots/{id}/refs` 有 8 次 500 `r19t_detect.json` | 查出离线并回的数据问题，见 §1 P0-A |
| r20g | 16:32 | r35 | P0 0，P1 同上 `r20_regress.md` | 新口径 v2：9 s 取样 211/225，25 s 取样 180/181 `r20_parity2.md`、`r20q_parity2.md` | PASS 1663 项 `r20_data_parity.json` | 37/38（a_loras 1280×720 没到底，ASSETUX）`r20_scroll.md` | T3 13 s 时 MISS（还在“加载中…”）；等 30 s 能做完 `r20x_detect.json` | r35 四项通过（§2） |
| r21g | 17:01 | r36 | P0 0，P1 同上 `r21_regress.md`（`r21g_detect.json` 17:01:30，晚于 r36 的 16:30:44） | 旧口径 23/23 `r21_parity.md` | PASS 1528 项 `r21_data_parity.json` | 未重跑（r36 没改滚动相关） | — | r36 四项通过（§3）；OT4 只改善了一部分（P1-3） |

**UIRSI 连续两轮（r35、r36）通过本方复核。**按派单的停止条件，本 loop 停。

## 1 问题清单

### P0-A（数据不对，已由别人修好，本方复核确认）：离线并回把 7 张设定图换成了半截文件
- 现象：
  - `GET /api/shots/{id}/refs` 80 镜里 74 镜返回 500（本方逐镜调用计数）；
  - 进程内复现到异常 `asset_refs.sheet_crop → PIL OSError: image file is truncated`；
  - 画布场景小卡因此写“电梯与楼道 无底图”，但 `/api/assets/scenes` 里 sk_elevator 是有底图的（截图 `apps/web/e2e/uiaudit/r19g_RG_canvas_a.png`）；
  - 林晚造型 A 设定图下半截是空白（截图 `apps/web/e2e/uiaudit/r19t_T3_a.png`，大图区整块白）。
- 坏的文件（`apps/web/e2e/uiaudit/r19_trunc_scan.json`）：
  - lin_wan lookA_s101、lookB_s101、lookC_s202；
  - ch_a_lan lookB_v2、lookC_v2；
  - gu_chen lookC_v2；
  - chen_yu lookB_v2。
  - 这 7 个文件大小都是 512 的整数倍，逐字节对比都是 `data/_offline_pull/_backup/` 原件的前一截。
- 根因（G0 扫描过）：
  - 冻结时推到服务器的文件，传输中断，留下半截文件，而且 mtime 比笔记本新；
  - `ops/offline/merge_pull.py` 只比 mtime（新的为准），不验完整性，半截文件就覆盖了笔记本上的好文件。
  - 这和 K-OPS-302（“推完核 sha”，`enforced: false`）是同一类问题，第二次出现，按 GEN_CONTRACT §5 算系统缺陷。
  - 负责方：OPS（离线恢复）。
- 现状：
  - 16:19 前已有人把 7 个文件隔离到 `data/_quarantine/prod_20261101_truncated_sheets/`，并从备份还原；
  - 本方重扫，生产路径坏文件 0（`r20_trunc_scan.json`）；`/refs` 恢复 200；之后各轮 apiErr 都是 0。
- 还开着的：
  - merge_pull 还没有完整性检查。草案 K-OPS-Q20 在 `knowledge/inbox/2026-11-01_uiaudit_r20.yaml`，检查可以直接用 `apps/web/e2e/uiaudit/trunc_scan.py`。
  - 离线期间服务器拿这些半截设定图出过的帧没有核过：**未测**。

### P1-1（任务做不完）：候选格点图打开的是放大框，打不开候选对比弹窗
- 复现：
  1. 打开 #ep02，切到审片；
  2. 用真实鼠标点 S1 尾帧（候选）的图。
  - 结果：出来的是 ZoomLayer 大图框“S1 · 尾帧 #4 · 候选 · 2/2”（`apps/web/e2e/uiaudit/r20v_V2_candlabel_b.png`），候选对比弹窗（CandidateBox：并排 / 滑块 / 用左边 / 用右边）不出现。
  - 点“有 12 张候选首帧，挑一张用”、点“候选 · 暂定”标签，也都不出弹窗（`r20c_detect.json`）。
  - 用合成 click 直接点 `.v3-frame` 能打开（`r20e_V2d_candbox_js_b.png`），可见组件本身是好的，是点击被 ZoomLayer 截走了。
- 根因：
  - `ds/ZoomLayer.tsx` 判断小图“可点”的依据，是祖先元素的 `cursor === "pointer"`（hasPointerAncestor）；
  - 但 `v3.css` 里 `.v3-frame { cursor: zoom-in }` 是 K-UI-P 规则允许的写法（“看大图允许 zoom-in”）；
  - 于是帧格被当成“不可点的小图”，点击被 ZoomLayer 在捕获阶段截走。
  - 影响：帧格 title 写的“点开全屏对比（首帧 | 尾帧）”、候选标签写的“点图看全部候选、对比”，用鼠标都做不到。
  - 负责方：UIPIXEL（ZoomLayer / css），UIRSI 配合。
  - 建议：hasPointerAncestor 把 zoom-in 也算“可点”，或者帧格加 `data-nozoom`、交给自己的 onClick。改的时候要守住 G11（放大镜照常出现）。
- G10 的正则查不出这个问题（“A/B 对比后设为当前”的字还在）。已写进本方 flows_r35b.json，下次复测照跑。

### P1-2（任务做不完 / 看起来“没出”）：画布候选要 9 s 以上才出来，在那之前格子写“首帧未出”
- 复现：在同一个 Chrome 里依次打开 #ep04–#ep10，每页等 9 s 取样，14 格写“未出”，但后端 `/api/candidates` 有合格候选（`r20_parity2.md`）；同一批页面等 25 s 后一致（`r20q_parity2.md`）。
- 截图：右上角“连接中”，S1 写“首帧未出”（`apps/web/e2e/uiaudit/r20p_P2_ep08_a.png`）。
- 后端单打很快：candidates 0.08–0.21 s（本方 curl 计时）。慢是排队：浏览器对同一主机的连接数上限，加上缩略图、长连接。
- 同类：
  - 资产页 13 s 时还是“加载中…”（`r20t_T3_a.png`），30 s 后能挑设定图（`r20x_detect.json`）；
  - UIRSI r36 自己记下 `/api/episodes` 一次 24.8 s。
- 判定：取数还没回来时写“未出”，这是把“还在读”说成了“没有”。同类草案 K-UI-D01（inbox）。
- 负责方：UIRSI（ReviewRow 加载态）+ 后端慢接口。

### P1-3（OT4 没完全做到）：78px 窄格里，左上标签和右上 ↻ 仍盖在人脸上
- r36 之后标签和 ↻ 不再互相压（压标签 0，`r21v_detect.json`）。
- 但在 ep02 S1、S2 的双人首帧里，“首帧 #12 / #10”标签盖住林晚的脸，↻ 盖住顾沉的脸。见放大裁切：`apps/web/e2e/uiaudit/r21v_W1_ep02_a.png`，人物头都在格子顶部 0–30%。
- 总调度 r36 已定“78px 不动、↻ 放右上角”，本方不推翻，只报实测。
- 留给总调度判断：要不要只在悬停时显示这两样，或者把标签挪到图下方的条里（候选条已经在图下方）。

### P2
- 后端连不上时，资产中心左栏各类计数写“0”（道具·产品 0、场景 0…）（`r21d_detect.json`）。这也是“读不到”被说成“没有”，同 K-UI-D01。负责方 ASSETUX。
- 全剧总览的“候选 11”其实是“11 张合格候选”，不是“第 11 号候选”，容易看错（`r19g_RG_overview_a.png`）。负责方 UIRSI（SeasonPage）。
- 精修页 S1 显示“视频 · #1”播放器，画布同一镜写“视频未出”：后端 video 为空，只有一个没设为当前的视频版本（`r19g_RG_shot_a.png`）。两处口径不一致，负责方 UIRSI。
- 老问题 F19（“按顺序串播”在 tools / canvas 页正文里找不到）和 a_loras 720 没到底，都不是本轮引入的。

## 2 r35 复核（证据：`r20v_detect.json` 16:19、`r20d_detect.json`、`r20c/r20e_detect.json` 16:50，都晚于 r35 改动 16:12）

| # | 检查 | 实测 | 判定 |
|---|---|---|---|
| 1 | ↻ 覆盖 | ep02：有版本号的格 14 个，带 ↻ 的 14 个；其他格 2 个，带 ↻ 的 0 个。ep01：14 / 14 / 0。按钮宽 28 | ✓ |
| 1 | 文字查找 | textContent 是“↻ 再生成”；innerText 是“↻⏎再生成”，按“再生成”能点到 | ✓ |
| 1 | 弹窗 | role=dialog，焦点在 TEXTAREA；Tab 6/6、Shift+Tab 6/6 不出框；Esc 后焦点回到“↻ 再生成” | ✓ |
| 2 | S1 行、ep03 整页 | ASSETMASTER / PRODUCER / 接手登记：0 处；尾帧候选显示“暂定” | ✓ |
| 2 | 候选弹窗缩略条 | 首帧弹窗：0 处内部词，“新配方 / 旧配方” 6 处；尾帧弹窗：0 处，有“#1 新配方 · 不合格”（`r20e_V2d_candbox_js_b.png`）。真实鼠标打不开弹窗，见 P1-1 | ✓（标签）/ 入口见 P1-1 |
| 3 | 后端连不上：#/cut | 没有 data/episodes/，没有路径或端口，骨架 0；写“成片列表暂时读不到：后台服务没响应” | ✓ |
| 3 | 后端连不上：#/script-create | 写“写作记录暂时读不到”和“＋ 新建剧本”；骨架 0；真实鼠标点了之后切到提纲表单（`r20d_V3_down_script_b.png`） | ✓ |
| 4 | G10 | r20g：P0 0 | ✓ |

## 3 r36 复核（证据：`r21v_detect.json`、`r21d_detect.json`、`r21g_detect.json`，16:55–17:01，都晚于 r36 的 16:30:44）

| # | 检查 | 实测 | 判定 |
|---|---|---|---|
| 1 | ↻ 位置 | ep01 14/14、ep02 14/14、剧本页 14/14；全部在右 5px、上 15px，22×22；压标签 0；草图 / 未出的格带 ↻ 的 0 个 | ✓ |
| 1 | 悬停时 ↻ 点得到 | 放大镜在 (156,106) 24×24，↻ 在 (140,130) 22×22，不重叠；↻ 中心命中按钮本身；真实鼠标点 ↻ 弹出“↻ 再生成 · ep02-S1 首帧 #12”；焦点循环 6/6，Esc 回焦点 | ✓ |
| 2 | 候选格标签 | “首帧 #12”“尾帧 #4”；有标签的候选条显示“候选 · 暂定”“候选 · 暂定 · 新配方”；标签的 title 有“候选 #n：还没设为当前”（代码 ReviewRow.tsx 第 108 行） | ✓ |
| 2 | “用这张” | 真实鼠标点 → 拦下 `POST /api/shots/ep02-S1/takes/image/12/activate`；界面提示“S1 首帧 没设成：Failed to fetch”（因为被拦了，属预期） | ✓（后端是否真的生效：未测，按硬规则不发写请求） |
| 3 | 后端连不上：资产 7 页 | #/assets、林晚、LoRA、音色、道具、模板、场景：/api/…、:8800、“API 重启”都是 0 处；骨架 0 | ✓（P2：左栏计数写 0） |
| 4 | G10 | r21g：P0 0 / 35；旧口径内容断言 23/23；data_parity PASS 80 镜 1528 项 | ✓ |

## 4 本轮给工具加的东西（只改 apps/web/e2e/uiaudit/**）
- `parity2.js` + `parity2_check.mjs`：逐格内容断言 v2。首帧 / 尾帧 / 视频都比文件和版号，同时比镜头列表，查多镜同一文件。规则 K-UI-038（`knowledge/rules/ui.yaml`，check 指向它）。
- `detect.mjs`：
  - 新增 `{parity2}` 步骤；
  - 新增 `{hoverAt}` 步骤（真实鼠标悬停）；
  - 新增 `DETECT_API_DOWN=1`（模拟后端连不上）。
- `api_distinct.py`：接口侧各镜互不相同、文件能取到。10 集 80 镜，重复 0，取不到 0（`r19_api_distinct.json`）。
- `disk_vs_api.py`：盘上 takes.json 和接口 current 对照（`r19_disk_vs_api.json`）。
  - 33 镜有版本但接口没有“当前”。这和 active 一致，属正常；界面用候选兜底，P1-2 说的是兜底出来得慢。
- `trunc_scan.py`：扫离线并回后的截断文件。
- flows：`flows_parity_s10(_slow).json`、`flows_r35*.json`、`flows_r36*.json`、`flows_t3slow.json`。
