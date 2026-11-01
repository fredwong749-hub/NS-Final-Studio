# ASSETUX 状态 / 交接（2026-11-01）

负责范围：资产中心（apps/web/src/v3/assets/**、v3/pages/AssetsPage.tsx、ScenesTab.tsx、services/api/ns_api/character_hub.py、tests/test_character_hub_assetux.py、资产页专用 CSS）。归属见 tools/qa/ownership.yaml。

## 已完成（都过了 iter_gate）

- r11、r12 两轮 iter_gate PASS：data/qa/iter_gate/ASSETUX_r11.md、ASSETUX_r12.md。各轮记录在 docs/assetux/rounds/。
- 人物页“↻ 再生成”界面：UIAUDIT 复核通过（docs/uiaudit/verify_uirsi_regen.md 的“复测 3”）。

## 待办：线上端到端再生成（总调度 11-01 决定：暂缓）

现在不提交任何 GPU 作业。gpu33 的三条道都在跑离线视频，不能插队。

开始条件：项目方回来运行 resume_from_gpu33.sh，并且 DATAALIGN 修完。

步骤（按顺序）：
1. 用 ops/restart_api.ps1 重启 :8800，让 POST /api/character-hub/{cid}/items/{id}/unuse-regen 上线。重启后用一张不是候选的图探一下：应返回 422 或 200，不能是 404。
2. 打开 /api/render/lanes，挑一条可达、空闲、没有视频作业在跑的道（看 auto.image 选的是哪条，以及那条道的 activity）。
3. 只对单品做，不碰造型设定图、身份脸。目标单品：林晚的“黑色漆皮细带高跟凉鞋” lw-shoes-up-62fd9e。
   - 改前状态：data/qa/assetux_regen_live/item_before.json。重跑前再存一份最新的。
   - 提交：POST /api/character-hub/lin_wan/regen，body：{kind:"item", item_id, file:<主图>, prompt, gear:[]}。记下提交、开始、结束的时间。
4. 看候选：人物页这件单品的“再生成候选”里出现新图（hubApi.get 返回的 items[].regen）。截图。
5. 点“✓ 用这张”（POST …/use-regen）：主图变成新图。截图，记下返回的 file 和 prev。
6. 撤销（POST …/unuse-regen，传 {file, prev}）：拿掉加进去的那张，主图回到原来的。
7. 逐字段对比 wardrobe.json 里这件单品和改前的快照，必须完全一致。生成出的文件和生成记录保留，只作候选。
8. 结果和耗时写进 docs/assetux/rounds/，截图放 apps/web/e2e/assetux/，回报总调度。

上一次尝试（11-01 11:21）：提交成功，选的是 gpu33:3，跑了 88 秒；结果在经隧道 127.0.0.1:18191 下载时超时，候选没出来，单品没变（逐字段比过）。记录在 data/qa/assetux_regen_live/。

## 其他挂着的

- UIMASTER 复爬 assets_people，确认 UM-0513（嵌套 .pp-view 的滚动层已去掉）和 UM-0092。
- 资产抽屉 v3/edit/AssetDrawer.tsx 的“生成”按钮归 UIMASTER，不归我。
- 11-01 UIRSI r36（总调度派，ASSETUX 不在岗）：AssetCenter / PeopleHub / P1Panels / ScenesTab 加载失败提示改成人话（去掉 /api/…、:8800、“等 API 重启”），检查 tests/test_ui_copy_uirsi.py 扫全站；见 docs/uirsi/rounds/r36.md。
