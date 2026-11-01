# AUDIT · CLEANUP r1–r3 复核（AUDIT r01，2026-11-01 19:24–19:25，独立复核方 = AUDIT，交总调度 fredw-2b）

复核对象：CHANGELOG 里 CLEANUP 的三条记录（18:0x–18:4x、r2、r3）、data/_quarantine_20261101b/MANIFEST.md（77 项）、tools/qa/quarantine_refcheck.py、tools/qa/data_parity.py 的 pending_redo。机读版：data/qa/audit/CLEANUP_r01.json

## 结论：通过；pending_redo 有一个 P2（没有上限和报警）

### 1 隔离清单抽查 10 项（随机种子 20261101，从 77 项里抽）

每项查四件事：隔离区里有这个文件；原路径已经没有；在 tools / services / apps/web/src / packages / config / ops / tests 里用 ripgrep 按文件名全字搜引用；没有被删除。

| # | 原路径 | 在隔离区 | 原路径已空 | 代码引用 |
|---|---|---|---|---|
| 6 | docs/gpu3_claude_status.md | ✅ | ✅ | 0 |
| 7 | docs/halted_work_inventory.md | ✅ | ✅ | 0 |
| 8 | docs/HANDOVER.md | ✅ | ✅ | 0 |
| 12 | docs/canvas-ui-spec.md | ✅ | ✅ | 0 |
| 15 | data/_offline_pull/gpu36.tar | ✅ | ✅ | 0 |
| 17 | data/iterate_loop/ep02_dry_smoke | ✅ | ✅ | 0 |
| 29 | data/cache/refs/master_face_b8e7…_512x512.png | ✅ | ✅ | 0 |
| 36 | data/logs/vram_video_smoke.csv | ✅ | ✅ | 0 |
| 43 | data/logs/fetch_civitai_auth.log | ✅ | ✅ | 0 |
| 51 | data/logs/rerun_todo.txt | ✅ | ✅ | 0 |

10/10 通过。删除脚本 ops/cleanup/delete_quarantine_20261101b.ps1 只是生成了，没有运行（隔离区还在），符合 L-079“先隔离，验证后再删”，最终删除仍然只能由项目方本人执行。

### 2 pending_redo 判定（r3）

- 代码 data_parity.py：第 78–90 行 pending_redo() 判“没有当前首帧，或当前首帧的 created_at ≤ 现行导入时刻”；第 329–331 行**还要同时满足“人选或造型和导入稿对不上”**，才记 pending，不算不一致；其余的照常比对（D-CAST）。对白 D-DLG、时长 D-DUR、剧本字段 D-SCRIPT、脸 D-FACE 对 pending 镜**照常比对**，只有人选 / 造型字母这两项跳过。和 CHANGELOG 写的判据一致。
- 判据是合理的：剧本 80 → 93 镜（SCRIPT_RSI_r01 已核对）以后，旧首帧本来就对不上新稿的人选，全量重做期间不该当成界面数据错误。新首帧设为当前以后自动转回比对。
- **P2**：没有上限，也没有报警。如果某一镜一直没重做（比如被闸门拦住、或者是“尽力”镜），它会一直挂在 pending 里，data_parity 永远显示 PASS。建议 pending 超过 N 小时或全量重做收尾时报警，或者在 iter_gate D1 里把“pending 数”和“全量重做是否完成”放在一起判（交 CLEANUP / DATAALIGN）。
- “现 24 镜”这个数 AUDIT 没有复跑（data_parity 要连 :8800）。CODE-RSI 记的是“93 镜 1255 项 0 不一致、待重做 24”，两边数字一致，但都是自报的 = 未测。

### 3 其它
- 测试：本轮 AUDIT 串行全量 pytest（19:17 起，约 5 分 38 秒）：**1748 过 / 0 不过 / 5 跳过**，里面包括 test_quarantine_refcheck、test_import_sources。
- 写作附录等文件的原件都留在 data/_quarantine_20261101b/*_orig/，可以找回。
