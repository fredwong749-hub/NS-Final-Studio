# AUDIT · CODE-RSI 复核 r01（2026-11-01 19:18–19:21，独立复核方 = AUDIT，交总调度 fredw-2b）

复核对象：CHANGELOG 里 CODE-RSI 的两条记录（17:5x–19:0x、18:5x–19:2x）：tools/qa/syntax_guard.py、push_check.py、resident_sync.py（tar_bytes / tier 2 / push_dirs / push_gate），以及本地提交 0a91a20。机读版：data/qa/audit/CODE_RSI_r01.json

## 结论：代码改动通过；提交 0a91a20 不含密钥，也没有新增媒体或数据，但不是“只含代码”的提交（里面有 100 个删除和资产清单 json，见第 5 条）

| # | 说法 | AUDIT 复测 | 结论 |
|---|---|---|---|
| 1 | syntax_guard（全仓编译 / 非法转义 / 未定义名 / 项目内导入） | 19:3x 跑：PASS，633 个文件，0 个有错，1.51 秒；test_syntax_guard 通过 | 通过 |
| 2 | tar_bytes：先读完再按实际字节数写成员（K-OPS-C04） | resident_sync.py 第 151–166 行：先取 stat，再 read_bytes，ti.size = len(data)，addfile(BytesIO)。有用例 test_tar_bytes_member_matches_bytes_even_if_stat_is_stale | 通过 |
| 3 | tier 2 远端清单漏了 data/（K-OPS-C05） | test_simulated_push_converges_and_server_has_latest 通过（临时目录模拟服务器） | 通过（只靠测试核对） |
| 4 | push_gate：推送前 push_check 必须 PASS，不过就不推、不起常驻 | 第 226 行 push_dirs（目录只在这一处计算），第 235 行 PushGateFailed，第 243–260 行 push_gate（15 分钟内同档复用），第 540、697 行在 video_up / recover 上接住。test_push_is_gated_by_push_check 通过；test_push_check + test_syntax_guard + test_localgpu_lane 共 25 条全过 | 通过 |
| 5 | 提交 0a91a20 只含代码 | `git show --stat 0a91a20`：1359 个文件（+171137 / −93541 行），其中新增 1078、修改 178、改名 3、**删除 100**。<br>• 密钥：在新增内容里搜 sk- / api_key= / 私钥头 / AKIA / hf_ / ghp_ / password=，0 命中；config/llm_providers.json 只写 key_env / key_files 的名字，config/abliteration.local.json 没有被提交；.gitignore 有 .env、data/、*.png、*.mp4。<br>• 新增 / 修改的文件里没有 png / jpg / mp4 / 权重。<br>• 新增了 10 个 assets/** 的 manifest.json / provenance.json（资产清单元数据，不是图）。<br>• 100 个删除：apps/web/src 旧组件、assets/characters 下旧角色的候选和底板 png、golden/ 的 jpg、“script play lib” 下的 .bak 剧本备份。这些文件在磁盘上已经不存在，提交只是记下了这个状态。抽查去向：AssetsView.tsx → data/_archive/20261031/code/…；alex_cand_01_s0.png → data/_archive/20261031_r2/…；golden/video_smoke/ep01-S1_contact.jpg → data/_quarantine_20261101b/…；而且父提交 b7eb37e 里都还有，可以从 git 找回 | 不含密钥 / 媒体：通过；“只含代码”：**不准确**（P2） |
| 6 | 推到最新版本 | `git remote -v` 为空：仓库没有配置远端，0a91a20 只是本地提交，**没有推出去** | 未完成（不是缺陷，但项目方说的“push 到最新版本”还没做到） |

## 提醒
- 工作区里还有已跟踪的截图被改动（`git status` 显示 M apps/web/e2e/v33_params.png）。.gitignore 加了 *.png，但对已经在跟踪的文件不起作用，下次 `git add -A` 还会把截图带进提交。建议对这类文件做一次 `git rm --cached`。这一步要改 git 索引，按规定交给 CODE-RSI / 总调度做，AUDIT 不做。
- 18:5x 这条记录写的是“暂存 1359 个文件，未 commit”，但 18:59:45 已经有提交 0a91a20（作者 fredwong749-hub），文件数一致。谁提交的、是不是总调度批准的，要在 CHANGELOG 里补一句。
- 全量 pytest -n 16 的 1761 passed 和 AUDIT 的串行全量（见 LOCALGPU / 汇总报告）不是同一种跑法，不能直接比数字。
