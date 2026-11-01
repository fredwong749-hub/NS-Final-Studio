# AUDIT · CODE-RSI 复核 r02（系统版本 / GitHub / deploy，2026-11-02 00:17 起，独立复核方 = AUDIT，交总调度 fredw-2b）

复核对象：CHANGELOG 第 483、494、495 行（CODE-RSI r3 及续）、git 提交和标签 sv-20261101-01 / -02、data/system_versions/{index.json, deploy_*.json}、docs/system_versions/*.md。机读版：data/qa/audit/CODE_RSI_r02.json

## 结论：通过（CODE_RSI_r01 记的“没有推送”已经关闭）

| # | 说法 | AUDIT 复测 | 结论 |
|---|---|---|---|
| 1 | 两个系统版本 | `git log`：8b1d245 “sv-20261101-01：系统版本（K-OPS-V01）”、c4daaf2 “sv-20261101-02”；`git tag -l sv-*` 两个标签都在（附注标签，tagger fredwong749-hub）；标签解引用后 sv-…-01 = 8b1d245，sv-…-02 = c4daaf2 = HEAD | 通过 |
| 2 | 推到 GitHub | `git remote -v` → origin https://github.com/fredwong749-hub/NS-Final-Studio.git。`git ls-remote origin`：refs/heads/master = c4daaf29…，refs/tags/sv-20261101-01^{} = 8b1d245…，refs/tags/sv-20261101-02^{} = c4daaf29…；`git status -sb` 显示 master 和 origin/master 一致（不领先也不落后） | 通过 |
| 3 | 推前密钥扫描 | AUDIT 自己用密钥正则（sk- / hf_ / ghp_ / AKIA / 私钥头）扫了 8b1d245 和 c4daaf2 两个提交的新增行：0 命中。两版之间 34 个文件变化，没有新增 png / jpg / mp4 / 权重，也没有新增 data/ 路径 | 通过 |
| 4 | deploy 时核 sha | deploy_sv-20261101-02_235550.json：gpu33（23:51:35）核 762 个 / 不一致 0 / 重推 2；gpu36（23:54:48）核 762 / 0 / 0；两台都写了版本文件，热重启后 fwd / producer / night 都 alive，drift_local 0。sv-…-01 的三份记录：gpu33 核 761 / 0 / 重推 11（23:28）、23:38 再核一次 0 不一致；CHANGELOG 写的 gpu36“重推 292”是 LF / CRLF 差异，已经修了 | 通过（采信脚本记录） |
| 5 | 服务器上的版本文件 | AUDIT 只读 ssh gpu36：/root/work/fredw/offline_20261101/repo/data/system_version.txt = `{"id": "sv-20261101-02", "commit": "c4daaf29cbaa7cd07dc616bedec349e1837f60d5", "at": "2026-11-01T23:54:48", …}`，和本地 HEAD、GitHub master 是同一个提交。gpu33 没有登录核对 | gpu36：通过；gpu33：未测 |

## 提醒
- 授权：CHANGELOG 写的是“项目方 23:0x 授权推 GitHub，仅限发版流程”。AUDIT 没有看到这句原话的出处文件（比如 MASTER_PICTURE 账本或 owner_decisions），建议补进账本，这样以后的推送都能对上授权。
- 部署热重启时同时重启了服务器上的 producer（gpu33 pid 1417139、gpu36 pid 3471198）。笔记本 producer 从 19:41 起是暂停状态，服务器 producer 当前是否也在暂停，deploy 记录里看不出来。要和总调度的暂停决定对一下，避免发版顺手把出图恢复了。

## 补查（00:20）
- gpu36 服务器 producer：data/producer/heartbeat.json（00:19:42）`"paused": true, "inflight": 0`，发版重启后**仍然是暂停**，和总调度的暂停决定一致。
- 但同一份服务器日志 23:42:10 记了两条 preflight_block（first:ep02-S1 / S2）：“I3 本镜造型 id + 造型设定图：林晚 造型A 没有设定图”。IMGFIX r2 在笔记本上把造型 A 换回 v2_s202（sheets_chosen + 33 张 refcrops 重裁），**服务器上可能还没有这套设定图和裁切**。恢复出图之前要把新设定图 / refcrops / sheets_chosen 推到两台服务器并核 sha，否则林晚造型 A 的镜会全部被 I3 拦住（交 WORKFLOW / CODE-RSI：tier 推送清单里要包括设定图目录）。
