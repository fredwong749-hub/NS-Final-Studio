# W38 EP01-DRIVER 收工报告（2026-11-04 08:2x）

## 结论
- sop_gate（gpu36 实判，08:0x）：**ep01 = 完成**，九阶段全有通过证据：剧本→导入闸门→资产就绪→提示词→出图→出图检测→尾帧→视频→整集预览；复盘 RETRO_ep01.md 07:56 自动 done（第 2 集可进出图）。
- 成片：gpu36 `/root/work/fredw/offline_20261101/repo/data/episodes/series10_v2/ep01_v2.mp4`（07:59，BGM 重拼版；`ep01_v1.mp4` 07:54 同长），**45.04 s**，1080×1920，h264 + aac。

## 硬规矩核（ep01_v2.timeline.json + ffprobe）
| 项 | 结果 |
|---|---|
| 单镜 ≤6 s（C-08） | 最长 S6 5.88 s，全部 ≤6 s ✓ |
| 无字幕（C-07） | timeline subtitles=false；ffprobe 只有 video + audio 两路 ✓ |
| 不看镜头（C-06） | S2 原片 6.4 s 后末帧看镜头 → 用 W46 `_le6` 裁切版且只取 4.0 s，已在裁切外 ✓；其余镜视频打分门 PASS |
| At 只标切镜（L-141） | 编译器 / 导入闸门既有规则，未改动 |
| 视频只用首帧（L-088） | 全部 i2va_pika_flex |
| BGM | 未用（disabled） |

## 11 镜（gpu33 生产账为准）
| 镜 | 首帧当前 | 尾帧当前 | 首帧未全过项 | 视频（成片所用） | 片长 |
|---|---|---|---|---|---|
| S1 | v2（Q1–Q10+QB 全过） | v2 | — | ep01-S1__mot_s1760588063 | 3.47 |
| S2 | v2 | v2 | QB 未测 | ep01-S2__alt_s2708805913（_le6） | 4.0 |
| S3 | v1 | v2 | — | ep01-S3__v1_s3786420798（_le6） | 4.0 |
| S4 | v12 **待复核** | v4 | Q10（站位/动作） | ep01-S4__v1_s2710944214 | 4.47 |
| S5 | v1 | v8 **待复核** | QB 未测 | ep01-S5__v1_s572574842 | 5.25 |
| S6 | v3 | v10 | QB 未测 | ep01-S6__v1_s250166093 | 5.88 |
| S7 | v3 | v7 **待复核** | — | ep01-S7__v1_s2540563733 | 3.0 |
| S8 | v1 **待复核** | 无（尽力，L-185 不挡） | QB | ep01-S8__v1_s54300748 | 3.0 |
| S9 | v8 **待复核** | v3 | QB（Q2 造型） | ep01-S9__v1_s3676129171 | 4.0 |
| S10 | v7 | v1 | — | ep01-S10__v1_s4109283544 | 4.0 |
| S11 | v3 | v1 **待复核** | QB 未测 | ep01-S11__v1_s2567581809 | 4.0 |

“待复核” = L-183 review_adopt（Q1–Q9 全过里分数最高版，postflight ok=true + review_needed=true，原结论留 ok_before_review）。
视频打分（vidgen gate，身份余弦）：S2 祁念 0.48/唐瑶 0.40，S3 江予白 0.58，S4 卓琳 0.60/祁念 0.70，S8 祁念 0.70，S9 祁念 0.36/江予白 0.46，S10 唐瑶 0.64；08:16 全量 rescore 后成片所用版本全部 PASS。

## 改过的文件（热修台账 data/system_versions/hotfix_ledger.jsonl，均 .bak-<hf> 可回退）
| hf | 文件（服务器现行 sha256 前 12 位） | 要点 |
|---|---|---|
| 01 | sop_gate / gen_contract/accept / asset_refs(W42) | 按集清单指纹；QB 人数服务器走 HTTP |
| 02 | sop_gate / config/vqa.json | Q9 只记录 na 认过；ask 超时 180 s |
| 03 | vqa/judge.py bea9d7c340cf | 看图修正不改参考图标注（S8 I6） |
| 04 | gen_contract/accept + tools/vqa/accept | 尾帧核结束状态 |
| 05 | series10_video/vidgen.py 7eacb7b44d10（W41） | 视频不派坏卡 |
| 06 | framing / compiler | 双人镜剧本有各自视线不加对视套话 |
| 07 | gen_contract/accept + tools/vqa/accept | L-183 描述条只记录、尾帧 Q10 prompt 只记录、QB 人数用 Q10 |
| 08 / 10 / 15 | tools/master/sop_gate.py d96160ecf0ee | 视频闸门逐镜；vidgen_guard 不因一集不过整份退出；L-185 尾帧尽力不挡视频 |
| 09 | tools/assetmaster/frames_v2.py b12bed3b309e | 参考板格成员带 zone（S9 I4） |
| 11 | tools/autopilot/producer.py d5b2b202e26b（含 W44） | L-183 review_adopt（主循环 + CLI，账本同步）；video_takeover 只接本机分区 |
| 12 | vqa/client.py bc1608091076 | 服务器上 8870 卸模型仍发请求（看图死锁） |
| 13 | pipeline/hard_constraints.py a4a09472f757、gen_contract/preflight.py 74fd7dd40c3f | V1 指甲锁不套 V2（S1 I10） |
| 14 | gen_contract/accept.py f0c91fc1dd7a（W42 L-184） | 推送 |
| 16 | series10_video/build_jobs.py（服务器原地补丁） | review_needed 首帧视同验收过 |
| 17 | framing.py 26c6d4275c8a、compiler.py c941de6ff56d | 视线“画面右/左/正前方”改离轴（C-07） |
| sync36 | gpu36 同步上述 8 文件 | 视频段放 gpu36 前提② |

非热修：BACKLOG.md（重复行已撤）；docs/master/V2_LIVE.md（逐步记录）；data/system_versions/hotfix_ledger.jsonl；tools/master/_w38_make_board.py（一次性参考板生成）。
运维动作：gpu36 人数检测 8893 按原脚本拷贝改 GPU1 拉起（/root/work/fredw/w38/anomaly_gpu1.sh，未用红线 GPU2）；gpu36 repo/models_cache/vision 补 YuNet/SFace（从 video10_srv 复制）；gpu33 migrate_renders_prefix --apply（18 文件迁回本剧前缀）；ep01 11 镜参考板生成推 gpu33。

## 测试（笔记本短单测；gpu33 部署树无 tests/、生产 venv 无 pytest）
sop 系列 52 / 36 passed；producer 105 + 32 passed；accept / vqa 系列 122 passed；vqa_route 31 passed；compil/framing/gaze 200 passed；hard_constraints + preflight 241 passed；video（merge_vid_o + resilience）40 passed。

## 没做完 / 待定
1. **S8 尾帧**：hf-17 后又出 3 版（take 8–10），Q9 判“看镜头 fail”但证据写“瞳孔偏向画面右侧，未直视镜头”——看图结论与证据矛盾（重问机制没兜住尾帧），尽力态；L-185 下不挡视频 / 成片。建议：Q9 eye_contact 矛盾在尾帧按证据重判，或项目方看 take 8–10 选一。
2. **三条（及全部）视频的视频级看图（VLM）**：08:16 rescore36 跑完，门判结论不变（成片所用全 PASS），但 `vidgen rescore` 不调视频 VLM（vlm=None），视频级看图结论仍缺，需另起视频 VLM 判（vqa.client.inspect_video）。
3. **待项目方复核**（L-183）：首帧 S4 v12 / S8 v1 / S9 v8，尾帧 S5 v8 / S7 v7 / S11 v1。
4. 首帧 QB“未测”的 S2/S5/S6/S11 是 hf-07 前的旧打分，未影响成片。
5. 笔记本看守 / 轮询循环全部已关（keeper、各 watcher 均结束；pgrep 无 W38 进程）。服务器上留有脚本于 /root/work/fredw/w38/（只读诊断与一次性工具）。
6. 成人镜：ep01 无（producer 只在 ep03/ep04 记 adult_wait_owner，未派）。
