# STATE — NS-Final Studio（唯一当前真相；每个会话结束覆盖更新；≤80 行）

- 更新：2026-11-07 10:4x JST（PS-MASTER，按《审计与修复指令 20261106》Step 2 重写；旧文不抄）
- 当前阶段：**Phase R（跑通）—— 冻结期**：禁止新功能、新计划文档、cut 新版本；唯一目标 = 冒烟可证明 ≥6/8
- 仓库 HEAD / 服务器实跑：**sv-20261107-13**（ec89806e，11-07 20:24 deploy 两台；补丁 v3 §2 + 闸门修正）。已知：发版工具的提交信息仍是“系统版本（K-OPS-V01）”模板（违反审计规则，待改）
- 自动发版：**已冻结**（config/pipeline/release.json enabled=false，11-07 10:4x）
- 冒烟分数：**3/8**（11-07 18:5x，code be687475 + A6，eval/results/20261107-0432.json；G1/G2/G7 过）。基线 2/8 → A6 升到 3/8。下一门 G4：producer once 25 分钟 0 派图

## 各环节最后一次成功证据（series10_v2 真实数据，非冒烟）
- 剧本 / 分镜 / 提示词：ep01–ep04 已过（sop_gate 阶段见 data/pipeline/runs/series10_v2/）
- 首帧 / 尾帧：ep01 15/16 有视频（S1 缺首帧）；ep02 首帧 16/16、尾帧 12/16；ep03 首尾帧齐、11 镜视频排队；ep04 首尾帧齐（/api/videos/overview，11-07 10:4x）
- 视频：ep01 待审 15；ep02 尽力版 12 + 排队 3 + 待审 1；ep04 待审 7 + 尽力版 5；ep03 0（gpu33 本机把阶段算成 frames，没视频道）
- 整集合成：ep04_v3.mp4（11-07 10:00）；ep01_v72/_v73_post（11-07 08:27 / 10:56）；ep01 首次全自动成片 ep01_v1.mp4（11-04 08:53，45.04 s）
- 复盘：RETRO_ep01.md（11-04 07:56，film_score 28.3/50）

## 已知坏点（≤5）
1. **冒烟三天没测**：没有任何证据证明当前 HEAD 过自己的冒烟门（审计 P0-2）
2. ~~gpu33 视频道为 0~~ 11-07 18:24 已修：项目方 a 放行，两台 run_phase enforce（回退：ops/psmaster/runphase_enforce_1107.py --revert）；ep03 11 镜 rendering。gpu36 三卡仍空：ep02 3 镜排队未派（jobs.json 未重建，待查）
3. ~~ep01 整集反复合成~~ 代码已修未上线（补丁 v3 §2）：a 内容签名 6107bdd2、b 同输入不占版本号 3de38aa1、c 单一递增者=视频机 ef01f578、d 预算按集累计 043333a7、e sweep 熔断 5b53e5d5。已上线 sv-20261107-13（11-07 20:24，项目方 both 放行）；签名口径切换致 ep01/ep04 各重开一次（ep01→v76，预期）；验收（同输入 0 新版本 / 断同步 30 min 0 新版本）观察中
4. **常驻进程动物园**：resident_sync / autoflow / api / tunnel / producer / night / gpu36 看图 多进程分三台；死一个就停（11-07 视频页全黑 = 当前版本视频回拉只剩手动，01:45 自查已报无人修；已加常驻回拉线，笔记本侧生效）
5. 冒烟 G4 永远 0 派图：笔记本冒烟 producer 的 smoke_v2 control 被一个仍跑 11-01 版 dispatch 的常驻进程每拍写成 hold 全部 6 道 / only=__none__（A7 证据）；候选 = 11-03 起没重启的笔记本 producer serve / sentinel / monitor。另：笔记本内存常剩 4–7 GB

## 下一步（按审计 Step 顺序，前一步不过不进下一步）
- Step 3：在 HEAD 上跑 eval/run_smoke.ps1，结果 eval/results/*.json 入库；G1→G8 一次只修一门
- Step 4：ops/start_all.ps1 + ops/health.ps1；看门狗只留一个（其余停用，不删）
- Step 6：冒烟连续两次 ≥6/8 后才把 take_sig / e2e_owner_gate 改 enforce
- Step 7：测试瘦身（Phase R 之后）

## 下一轮候选（等项目方拍板，本轮不开工）
- ep01：整集 45 s < 60 s（L-092）怎么办；11-04 起挂的 6 个待复核版本逐一给结论 / 废弃
- ep02：资产就绪缺口清单 + 故事线方向
- X 版内容（S3 调度器 record、run_phase enforce、自愈卡点自动关、master_check 口径）：冻结期内是否单独放行 run_phase enforce（它是 ep03 不出视频的直接原因）

## 禁区
- eval/ 评分表与冒烟判定逻辑：修门期间不许改（评估器与工人分离）
- producer.py：冻结，只许改冒烟门直接相关的行
