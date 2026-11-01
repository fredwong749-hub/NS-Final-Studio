# V6 多手：用看图模型数手作主判据的标定方案（VQAGATE，2026-11-01 17:4x；数据等跳板恢复后再跑）

## 起因
- tools/series10_video/v6_limbs.py 第 26 行 `TH["bad_finger_frac"] = None`：阈值为空，等于这一项从不拦。RSI 实测 150 条片子都量了，其中 91 条超过 0.2，全部放行（总调度 17:3x 转述）。按 K-REV-Q05，空阈值算缺陷。
- 总调度点名的正例：ep01_v2 的 S2（mot 版，3 只手）、S4（s2 版，两个人 5 只手）。这两条现在的 gate 都是 pass（data/pipeline/runs/series10_v1/video/episodes/ep01/manifest.json）。

## 判据（同一套 V9 rubric，不另写检测器）
1. **主判据：看图模型数手**。score_clip.v9_vlm 已经抽 6 帧（含第 1 帧和第 1 秒），复用 `client.inspect_video`。判 V6 不过的条件（任一满足）：
   - 某一帧 `people[].hands_visible` 加起来大于 2 × `people_count`；
   - `checks.extra_limbs = defect`，且证据里写了第几帧、哪个人。
   - 自相矛盾的（判 defect、证据却写“双手各 5 指”这类）照 contract.sanitize 的做法降为拿不准。
2. **辅判据：v6_limbs 的 bad_finger_frac**。阈值用下面的标定定，写进 config/gen_contract.json 的 video_thresholds.V6，不再留空。
3. 看图模型判多手，或 bad_finger_frac 超过高置信线 → V6 不过，进 gate.fails 标“多肢”（score_clip.vlm_fails 已经把 extra_limbs 映射成“多肢”）。

## 标定集
- 正例：ep01-S2 mot、ep01-S4 s2，再加 DEFECT_HUNT.md“交 VQAGATE”表里列的多手片（拿 docs/rsi/DEFECT_HUNT.md 里的片名），目标至少 8 条。
- 反例：manifest 里 status=done、总调度看过没提手的片子，至少 16 条（ep01 S5、S7，加上 ep04 / ep05 已通过的镜）。
- 标签写进 data/vqa/gate_calib/v6_labels.json（{片子路径: "多手" | "正常"}），只用总调度点名过的，不自己标。

## 步骤（网络恢复后）
1. 把正反例片子从 gpu33 / gpu36 的 video10_srv/…/clips 拉到本机（片子在服务器上，本机只有 540×960 代理；代理也能用，要注明）。
2. 每条跑 `client.inspect_video`（本地看图）和 v6_limbs（服务器 venv_hand），结果写 data/vqa/gate_calib/v6_runs.json。
3. 奇偶两折留出，分别扫：①看图模型数手的规则；② bad_finger_frac 阈值 0.2–0.6，每 0.05 一档；③两者取 OR。报每种的召回和误报。
4. 选留出误报 ≤ 1/8 的最高召回组合，写进 config/gen_contract.json V6 和 v6_limbs.TH（附出处），规则补进 K-REV-V08 的 check。
5. ep01 的 S2、S4 按新口径重新打分（vidgen rescore 只在服务器上跑，命令交 PROD），不过就进重出。

## 现在已经能用的
- score_clip.vlm_fails：V9 判 extra_limbs 为 defect、并且该项 blocking=true 时，进 fails 标“多肢”。extra_limbs 现在 blocking=false：首扫 11 张首帧里报了 2 张，没有标定，先不拦。
