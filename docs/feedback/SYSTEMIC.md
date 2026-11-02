# 人类反馈 → 系统性问题登记（FEEDBACK）

每条从人类反馈里查出的“架构 / 共同根因”问题记在这里，并报总调度。逐条反馈记录在 `data/feedback/items/`。

## SYS-01 视频里的手：形状类缺陷没有任何一道闸门能测到（来源 fb-0001，11-02）

**现象**：第一季 ep02-S3（故障电梯，林晚手按镜面墙）当前视频 v1（`data/renders/ep02/S3/video.mp4` = `_preview/ep02-S3__v1.mp4`），项目方说“手不对”。亲审抽帧（`data/feedback/evidence/fb0001/`）：
- t≈3.6–3.8 s（第 86–91 帧）：抬手时手糊成一团，手指分不清；
- t≈4.3–5.3 s（第 104–128 帧）：手按上镜面，真手和倒影合成“合掌”，指头互相穿插，分不清哪只是倒影；
- t≈6.0–7.7 s（第 144–184 帧）：真手在领口捏衣领，倒影里却是一只握拳、位置也不对，镜像物理断了；指节变形。

**为什么全部闸门放行**：
1. V6（`tools/series10_video/v6_limbs.py`）只数手的个数、量 MediaPipe 21 点骨长比例。MediaPipe 对畸形手照样拟合出正常骨架，所以粘连 / 融化 / 倒影不一致这一类 **原理上测不到**。这条片子：手数最多 2、bad_finger_frac 0.037，现行阈值（0.85）和打分时的阈值（null）都放行。
2. 打分发生在 11-01 04:28，早于 V6 阈值落定（11-01 18:2x），之后没有对存量片子重打（score 里 `th.bad_finger_frac = null`）——阈值改了不回扫存量。
3. V9 本地看图：这条片子根本没跑过（`data/vqa` 无记录）；配置上视频只均匀抽 6 帧、`hand_malformed` blocking=false。
4. 本地看图模型 Qwen3-VL-8B nf4 对该类实测召回 0/1：本条的 4×4 印样和 4 张手部放大都判“无缺陷、置信 1.0”。即使补跑、即使改成阻断，也拦不住。
5. 文字层没有规则：编译出的视频提示词明写“presses it flat on the mirror wall … pulls her hand back and presses her knuckles against her collarbone”——镜面场景里让手接触镜面，是生成模型的已知失败模式，写作 / 编译 lint 里没有这一条。

**全剧同类**（47 条当前视频）：
- 文字层 `tools/feedback/hand_scan.py --prompts`：高风险（镜面场景 + 手贴镜面 / 玻璃）2 条：ep02/S3、ep03/S4；中风险（镜面场景 + 手部动作，或手部动作 ≥3 处）28 条（`data/feedback/scans/prompt_hand_risk.json`）。
- 亲审：ep02/S3 确认；ep03/S4、ep07/S8、ep10/S4 印样上没看出明显问题（全景手小，分辨率 360×640 判不准）；其余 14 条镜面 + 手的印样已生成（`data/feedback/scans/mirror_hand_sheets/`），交 VIDLAB 逐条看。

**要的系统改进（已派）**：
- VQAGATE：做真正能测手形状的检测器（候选：手部区域放大到 ≥512 px 后逐帧问看图模型 + MediaPipe 关键点时间抖动 / 置信度掉落 + 镜面场景真手与倒影左右对称性检查），用本条做第一个正例回归样本（`data/feedback/regression.jsonl` fb-0001），召回达标前不得宣称“V6 通过 = 手没问题”；V6 阈值一改，存量片子必须自动重打。
- VIDLAB：ep02-S3 重出（提示词去掉手按镜面，改成手扶不反光的扶手 / 墙板，或镜头避开倒影），并按文字层规则复查 2 条高风险 + 14 条镜面印样。
- HOLLYWOOD / 编译：写作和编译 lint 加规则“镜面 / 玻璃场景禁止手接触反光面；8 s 内手部动作 ≤2 处”，`prompt_risk()` 可直接复用。

## SYS-02 界面检查只看“元素在不在”，不看“行为对不对”（来源 fb-0002，11-02）

**现象**：胶片总览悬停播放的视频没有声音，标“视频 · 静音”。素材本身有声音（ep01-S2 AAC，-18.1 dB）。
**根因**（FILMUI）：r4 默认关声音；`play()` 被浏览器拒绝后退回静音，之后不再恢复。
**为什么没被发现**：
1. 需求在代码注释里被写反了：FilmOverview r46 注释写的是“悬停静音循环播放”，和项目方要的“播放声音”冲突，没有一条需求 → 检查的对照。
2. 所有 UI 检查（detect / regress_check / topbar_check）只断言元素存在、可点，没有一条断言媒体的实际状态（muted / paused / 有没有解码到音频）。
3. 界面上把“静音”写成标签，看起来像设计，而不是报警。
**系统改进**：`apps/web/e2e/uirsi/film_hover_sound.py`（FILMUI 写）已接进 `tools/qa/iter_gate.py` R1：悬停有当前视频的帧必须 muted=false、paused=false、解码到音频字节，否则 R1 不通过。后续 UI 检查要按“行为”断言（播放、出声、跳转后的数据），不只看元素在不在。
