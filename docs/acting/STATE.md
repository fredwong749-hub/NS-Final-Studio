# ACTING 会话可续表（R11-2/3/6/8/9）

> 断点续做：按下表从第一个未完成项继续。锁已登记在 docs/uimaster/LOCKS.md（ACTING 行，完成后删“本次改完即释放”那几行）。

| # | 步骤 | 状态 | 产物 |
|---|---|---|---|
| 1 | 调研 | ✅ | docs/acting/PERFORMANCE_RULES.md |
| 2 | 检测器模块 + 标定页 | ✅ 已判分：像素检测三项都分不开（CALIBRATION.md 第 1 次判分）；看镜头已转拦截，改由本地看图闸门 Q9 eye_contact 拦（项目方 11-01 16:10，D-VQA-01） | packages/qc/ns_qc/gaze.py；tools/acting/calibrate_gaze.py；data/review_pages/acting_gaze_calib.html；docs/acting/CALIBRATION.md |
| 3 | 接线 | ✅ | postflight G1（gaze_item）；score_clip `acting`（像素旁证，soft；拦截走 Q9 / V9，enforce=true） |
| 4 | 系统层 | ✅ | asset_refs.EYELINE_NOTE/RE（TEXT_NOTE_RES）+ frame_job.eyeline_note；recipes _base.yaml open_motion_cue / eyeline_cue + provenance；prompt.build_base 插入；lint RL-E1/E2；ns_post.ffmpeg.assert_no_subtitles |
| 5 | 写作层 | ✅ | K-WRT-A01–A05（writer_iteration.yaml）；K-REN-G01–G03、K-REV-G04（acting.yaml）；tools/qa/acting_lints.py QW-A1–A5，接进 validate_qwen_script；compile.py 已跑 |
| 6 | PRODUCER 返修 | ✅ 返修稿已备（未出片镜 QW-A 63 → 0，19 镜），未导入；data/staging_v3/merged/_qwa_P4_ep02…ep10.md（8 个）；等项目方 resume_from_gpu33.sh 后笔记本合并导入；冲突待总调度定：QW-SZ1 改到已出片的 ep02-S1、ep06-S1、ep06-S2 |
| 7 | REQUIREMENTS | ✅ ⚠ 状态已写 | R11-2/3/6/8/9 |

## 下一步（恢复后）
1. 收 PRODUCER 回报：每镜 QW-A 前后计数；确认只换了未出片镜
2. 总调度标注后跑 `calibrate_gaze.py --score`，分得开 → 提议 gaze.BLOCK=True
3. VIDEO10 重编 build_jobs（新 H3 两句 + 新剧本）——提醒总调度 / VIDEO10
4. :8800 未重启：API 进程里的 frame_job / postflight 改动要等总调度重启后生效
5. 预先存在的失败测试（非本会话引起，身份脸 / refcrops 数据变动）：test_single_identity_face、test_unified_frame::test_canvas_regen_graph_equals_unified_builder、test_gen_contract 3 条、test_image_jobs、test_ref_switch_assets 2 条

## 11-01 总调度决定（已执行）
- ep07–10 不暂停；合并后改动镜走正常过期 → 重出
- 合并导入在笔记本做，等项目方跑 resume_from_gpu33.sh 之后；gpu33 副本不导入（已转告 PRODUCER）
- 标定：总调度自己标。印样 data/review_pages/acting_gaze_calib/sheets/sheet_{image,clip}_NN.jpg（每张 12 个，编号 #1–#12）+ index.json；标注写 data/acting/gaze_labels.json（{样本 id: 选项}），再跑 calibrate_gaze.py --score
- :8800 总调度已重启（出图视线句、G1 生效）
- 字幕来源排查：93 个 H3 片段 / 成片每 0.5 s 抽帧跑字幕带检测，9 个有命中，抽帧目视都是误检（手机、腰带、器械盘边、桌沿），没有烧进画面的字；审片页 series10_video 与画布播放器（Player / ReviewRow / CutPage / MediaPlayer）都没有字幕叠层。来源未确认，需要项目方附图 #43 原图定位
- ACTING 临时锁已清，只留长期行

## 第 2 轮：MediaPipe 虹膜重做（总调度 11-01 批：装进项目 .venv，不进共享环境；补阴性样本 ≥40 张做标注页；过线也不开拦截——已被项目方 11-01 16:10 原话推翻：看镜头转拦截，走本地看图闸门，D-VQA-01）
- [ ] a 装 mediapipe 到 .venv
- [x] b packages/qc/ns_qc/gaze_mp.py（FaceLandmarker 478 点虹膜 + 头部朝向；小脸按 YuNet 框裁切放大再跑，100/100 对上）。预扫（同一批 100 条已标图片，偶数位定参、奇数位留出）：A=0.5、B=2、T=0.53，留出召回 0.92、误报 0.15（留出阴性只有 13 个，不作数），特征 data/acting/mp_features_v1.json
- [ ] c 从现有首帧挑候选“没看镜头”样本 ≥40 → 标注页 + 印样
- [ ] d 等总调度标注 → 重新判分 → 汇报（拦截已由 VQAGATE 走 Q9 接通）
- [x] a 装好：uv pip 装进 .venv（mediapipe 1.2.0 + 依赖 absl/matplotlib 等，只新增、没升级已有包；numpy 2.5.4 / protobuf 7.36.2 不变）。它连带的 opencv-contrib 5.0.0.93 因 cv2.pyd 被占用装失败、未登记——cv2 仍是原 opencv-python-headless 5.0.0（.pyd 未动，config.py 同版本内容，YuNet 正常，测试过）；cv2 目录里多了 contrib 的 .pyi 类型存根（无害）。mediapipe 1.2 没有 solutions 接口，改用 tasks FaceLandmarker（模型 models_cache/vision/face_landmarker.task，官方 storage.googleapis.com/mediapipe-models）
