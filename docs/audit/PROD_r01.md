# AUDIT · PROD 复核 r01（2026-11-01 16:46–16:50，独立复核方 = AUDIT，交总调度 fredw-2b）

复核对象：CHANGELOG 里 PROD 的交付记录（“16:0x–17:xx PROD fredw-2b 派”，按文件修改时间看，16:45 前后写入），NIGHT_PLAN W4 / W5。
AUDIT 没有改产品文件，也没有点会改生产数据的操作。机读版：data/qa/audit/PROD_r01.json

## 结论：W4 部分通过（代码、测试、规则、对比图都对；“ep01 重合成”还没做到）；W5 未测（这次没交）；数据修复通过

| # | 说法 / 完成标准 | AUDIT 复测 | 结论 |
|---|---|---|---|
| 1 | 渲染容错 K-OPS-306…311，tests/test_video10_resilience.py | 16:46 重跑：8 条全过 | 通过 |
| 2 | W4：合成改用原片，代理禁止进成片 | tools/series10_video/night.py 第 268–293 行 assembly_sources：只取 manifest.source（原片）或放大版；放大版宽高必须 ≥ 原片；原片分辨率不高于代理的镜列进 bad；只要有 bad，整集 ASSEMBLE_BLOCKED（第 330 行）。规则 K-EDT-V10 的 check 是 test_assembly_never_uses_proxy | 通过 |
| 3 | W4：1:1 对比图 | data/review_pages/series10_upscale_s5/（16:45）。我自己看了 crop_face_1to1.png：右边（原片 → lanczos 1080 + unsharp）发丝、睫毛、唇纹明显比左边（ep01_v2 里的 540×960 代理）清楚。metrics.json 的拉普拉斯方差：全帧 48.0 → 127.3，脸 76.5 → 161.6。SeedVR2 版页面上写着“试跑中”，还没有 | 通过（SeedVR2 未测） |
| 4 | W4：ep01 重合成 | data/episodes/series10/ 只有 ep01_v1（07:14）和 ep01_v2（09:21），没有新版本。data/pipeline/runs/series10_v1/video/clips/ **目录还不存在** → 原片一条都没拉回来，按新逻辑现在每集都会 ASSEMBLE_BLOCKED。按 CHANGELOG 写的跳板实测 17 KB/s、每轮每台最多 4 条，2.36 Mbps × 约 5 秒的原片一条约 1.5 MB，拉一条大约 90 秒 | **未完成**（复现：`ls data/pipeline/runs/series10_v1/video/clips` → 不存在；`ls data/episodes/series10/`） |
| 5 | STATUS.md 写当前配方（D-VID-01 同步） | docs/series10_video/STATUS.md 现在还是 16:25:04 的旧版，没有配方栏。night.py 进程 16:47:05 刚重启（Get-CimInstance 查到 PID 52504），新模板要等它跑完一轮写出来才看得到 | 未测（下次复查） |
| 6 | 数据修复：7 张截断设定图恢复，坏图隔离 | data/_quarantine/prod_20261101_truncated_sheets/ 里正好 7 个 .truncated.png。我把 assets/characters/** 222 张、series10 sheets / sheets_v2 / refcrops / identity_refs 531 张全部完整解码一遍：坏图 0 | 通过 |
| 7 | SOP §12 补预览放大口径，⤴ 取代代理合成 | docs/SOP_production.md 第 388 行已写 K-EDT-V10 和项目方原话 | 通过 |
| 8 | W5 局部大特写根因（ep05-S3/S5） | 本次交付没提到 W5。只补登了 ep05-S3/S5 的 unwait | 未测 |

## G0
- 没有另起一条平行的合成线：还是在 night.py finalize 里改输入源。放大用的是新文件 upscale_preview.py，但 SOP §12 本来就有 SeedVR2 方案，这里只是先用它、再兜底 lanczos，不算重复造。✅
- 修的是根因：问题出在合成取的是代理，现在从取源这一步禁掉代理，而不是事后去锐化成片。✅
- 同步：SOP §12 改了；STATUS 模板改了（等生效）；K-EDT-V10 进了规则库。✅

## 另外看到的（交 WORKFLOW）
- night.log 16:44:50：推 gpu36 失败（Connection reset by 183.23.230.84 port 19422）。这属于 W7 隧道 / 跳板韧性，要看看看门狗有没有接住这次中断。

## 给 PROD 的未关闭问题
1. W4 的“ep01 重合成”还没做到：等 clips/ 拉齐以后合成 ep01_v3，再交一张 v3 和 v2 同一帧的对比，做完通知 AUDIT 复查。
2. 按现在的速度，原片拉回本机会成为整夜所有集合成的瓶颈。请估算 80 镜全部拉完要多久，或者考虑在服务器上直接合成（原片本来就在服务器上）。
3. W5 还没交。
4. SeedVR2 版出来后补进对比页。
