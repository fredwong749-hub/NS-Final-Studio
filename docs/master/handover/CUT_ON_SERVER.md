# 发版七门在 gpu33 上跑（W45 SERVER-DEV，2026-11-04；总调度定 B 方案）

项目方原话：“笔记本本来不适合做任务重的开发,gpu那2台服务器内存那么大,gpu 3090那么多卡,你不用,在这台笔记本做干嘛?”

## 一句话

`system_version.py cut [--dry] [--tree T] --on gpu33`：冻结树照旧在笔记本拍，**七门（syntax / kb / arch / VQA 回归 / decision / propagation / 定向 pytest）在 gpu33 跑**，每门结果与耗时、完整 pytest 输出拉回笔记本进同一份 cut 报告；commit / tag / push 仍在笔记本（仓库与 sv 标签在这里）。
默认：`config/pipeline/release.json` `"gates_on": "gpu33"`（release_tick 自动发版同样生效）；`--on local` 或 `NS_CUT_ON=local` 退回本机。

## 怎么做到的（tools/qa/remote_gates.py）

1. **代码**：冻结树清单（ls-tree：mode / blob sha / 路径）发给服务器 → 服务器在上一份自己的快照（硬链）和 producer 仓库（**只复制，不硬链**）里按 blob sha 找现成文件 → 笔记本只推缺的。
   **Git LFS**（*.png / *.wav / *.mp4 …）：git archive 给真内容、cat-file 只有指针 → 清单里换成真内容 sha（`.git/lfs/objects/<oid>`，按 oid 缓存），服务器拿到的是真图（11-04 首轮漏了这一条，快照里是 131 字节指针，19 个测试读图失败）。
2. **数据（B 方案）**：
   - 服务器快照的数据目录从 producer 仓库硬链（build_snapshot 同口径，不带 pid / 锁 / 心跳），**只接笔记本上也有的子目录**（服务器独有的旧隔离区等不带进来，否则 D-CLN-09 误红）。
   - 笔记本数据镜像覆盖在上面、笔记本版本优先：①知识库规则 / owner_decisions 引用的证据（data/、assets*/、apps/web/e2e/）+ `overlay_paths`（arch 基线）；②`mirror`：data/ assets/ assets_v2/ 下非媒体、≤1 MB、排除归档 / 隔离 / renders 等（约 1 万个文件、~110 MB）+ `mirror.extra`（定向 pytest 点名读的 25 个媒体 + 1 个隔离目录，审计钩子在笔记本实测追踪得到）。
   - 按 sha 进服务器内容寻址库 `cut_snapshots/_blobs/`，下次只推变的；**分批 ≤6 MB、每批等 run_sync 完成一拍再发**（冲刺期不抢链路）。预热：`python tools/qa/remote_gates.py mirror`。
   - **树里缺的文件**（首次、或 LFS 真内容，首轮约 500 个 / 262 MB）同样分批进 `_blobs/`（单批断线重试 3 次），服务器拼树时按 sha 从库里硬链。
   - **限速**（总调度 11-04 06:2x，ep01 出视频期间链路让路）：`config/qa/remote_dev.json` `throttle`：每批 ≤1 MB、平均 ≤50 KB/s；笔记本出现 `data/episodes/series10_v2/ep01_v1.mp4` 后自动解除。
3. **跑**：后台起（新会话，ssh 断了也继续），`nice 10`、`CUDA_VISIBLE_DEVICES=` 空（不碰任何 GPU，含坏卡 gpu33:2）；system_version.gates 原样执行（同一份代码随 runner 推过去），pytest `-n 24`（`config/qa/remote_dev.json` pytest_n / `NS_CUT_REMOTE_PYTEST_N`）。
4. **失败处理**：服务器基础设施失败（连不上、拼树失败）→ 按 release.json `gates_on_fallback`：`local`（默认，退回本机并在报告记 `gates_on_fallback`）/ `fail`（失败关闭）。闸门红 ≠ 基础设施失败，照常不发版。
5. 服务器上只写 `cut_snapshots/`（含 `_dev/`、`_blobs/`）与 `w45/`（venv、inbox）；不删任何东西（同名快照先改名 `.old<ts>`）。

## 实测

最后一次（11-04 08:2x）：`system_version.py cut --dry --tree a81cfa33 --on gpu33 --id w45dry-20261104-04`（工作树此刻状态，不提交）

| 闸门 | gpu33 结论 / 耗时 | 笔记本结论 / 耗时（同工作树） | 一致？ |
|---|---|---|---|
| 语法守卫 | ❌ 1.4 s（resident_sync.py:1838 merge_takes 未定义） | ❌ 2.6 s 同一处 | ✅ 真红（他人进行中改动） |
| 知识库 compile --check | ✅ 2.0 s | ✅ 2.1 s | ✅ |
| arch_scan --check | ❌ 14.1 s（8 处） | ❌ 26.2 s（19 处 = 8 处 + 11 处 untracked_*，快照非 git 仓库两边都查不到） | ✅ 真红 |
| VQA 回归集 | ✅ 5.8 s | ✅ 16.6 s | ✅ |
| decision_check | ✅ 13.6 s（87：83 ✅ 0 ❌） | ✅ 23.9 s | ✅ |
| decision_propagation | ❌ 3.7 s（D-VQA-01 2 处没同步） | ❌ 9.7 s 同一处 | ✅ 真红（他人改 config） |
| 定向 pytest（44 文件） | ❌ 43.2 s（-n 24：730 过 / 14 红） | 上次 cut 194 s；14 个红用例在笔记本重跑：3 红 11 过 | ✅ 3 个真红两边一致；11 个 = 已列 fixture 项（V1 派生参考图 308 MB 不镜像） |
| **七门合计** | **83.8 s**（快照准备 143 s，链路限速中；无改动时只推几个文件） | **≈ 277 s**（六门 82.6 s + pytest 194 s）+ 本机快照硬链 6.5 万文件 | |

早先各轮：w45-trial1 首推 6 MB（代替 390 MB）；w45-full2 七门 73.7 s；LFS 根因修后 w45dry-01/03 结论同上。

## 与笔记本结论的差异（已列 BACKLOG，不在本轮改别人的测试）

- **限速期 LFS 延后**：限速生效时，服务器没有真内容、又不在 `mirror.extra` / `lfs_priority` 的 LFS 文件（299 个）先用指针（与 full2 首轮同口径，其余测试照过）；ep01 成片落地笔记本后限速自动解除，补齐：`python tools/qa/remote_gates.py mirror --lfs`（约 190 MB，链路空时跑）。
- 依赖笔记本真实数据的定向测试：靠 `mirror.extra` 点名镜像兜住，应逐个改 fixture（BACKLOG 有文件、负责方、建议）。新测试再读真实媒体 → 服务器红、笔记本绿：把文件加进 `mirror.extra` 只是权宜，正解是 fixture。
- 并行污染：tests/test_producer_w44.py 的全局 RUN_ID 让 test_video10_resilience 在 xdist 下偶发红，串行重跑过（cut 记 flaky）。
- 快照不是 git 仓库（两边一样）：arch_scan 的 untracked_* 在快照里查不到，只在笔记本工作树查。
- Linux 真 bug 已修：`ns_api.infra_status._hm(-1e12)` Linux 返回 07:32:19（Windows 抛错 → None），已统一负数 → None（test_factory::test_infra_status_hm_invalid_timestamp）。

## 相关

- 工人日常测试：docs/master/handover/DEV_ON_SERVER.md（`tools/qa/remote_pytest.py`）
- 冒烟门提案：docs/master/handover/SMOKE_ON_SERVER.md（eval/ 未改，待总调度审）
- 配置：config/qa/remote_dev.json；测试：tests/test_w45_remote_gates.py
