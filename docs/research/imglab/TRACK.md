# IMGLAB 追踪表：研究 → 实测 → 规则 → 上线 → SENTINEL 指标

> 一条只有走到“上线并有指标”才算关闭。研究文档：00–05（本目录，逐条带引用）。更新：2026-11-02（r1）。
> 状态：研究 / 待下载批准 / 实测中 / 规则 / 上线 / 有指标=关闭。

## A. 出图问题 → 方案

| # | 问题 | 方案 | 研究出处 | 实测 | 规则 / 检查 | 上线 | 指标（SENTINEL） | 状态 |
|---|---|---|---|---|---|---|---|---|
| T1 | 双人属性串扰（ep06-S2 顾沉蓝发） | F1 删句保主语（编译层） | 05 | 编译回归 102 镜：归属错 23 镜 236 句 → 0；生产 29 镜上线前 82 版 Q1 66% / 契约过 16% → 上线后 41 版 Q1 85% / 契约过 66% | K-REN-901；tests/test_imglab_subject_binding.py；tools/imglab/orphan_check.py | sv-20261102-05 | orphan_check 0 孤儿（DEBUG-RSI release_when）；出图侧逐人发色 / 发长（VQAGATE F4）待接 | 上线 + 有指标（生产 Q1 / 契约通过率）；逐人发色闸门 F4 待 VQAGATE |
| T2 | 特写写了两人露脸 → 退成中景 | F3 双人近景首句 + preflight I6 拦截 | 05 | 编译层 5 镜；总调度 04:5x 定为写法冲突改写，不需要 A/B | K-REN-902；I6 framing_clash | sv-05（audit_framing 配套随下一版） | Q3 景别档（双人近景目标档 2） | 上线，等出图指标 |
| T3 | 写作侧继续写“特写 + 双人” | 写作 lint：framing.two_face_close_conflict | 05 | — | 交 HOLLYWOOD 接 writer_lints | 待 HOLLYWOOD | lint 命中数 | 待接 |
| T4 | 串扰残余（模型层，参考图在联合注意力里全局可见） | F5 两步法：先构图 → person-seg 逐人局部重绘、每次只挂一个人的参考 | 00 §4 B | 待 T1 上线后看残余 | — | — | 逐人发色 / 身份 | 研究 |
| T5 | 参考图权重 | Reference Strength 节点（deng232 enhancer，MIT），把非本人参考图的注意力压到 0–0.3 | 00 §4；01 §4 | 待下载批准 | — | — | Q1 双人 | 待下载批准 |
| T6 | 手部（糊 / 轻度畸形） | Impact Detailer：hand_yolov9c，Turbo cfg1 8 步，denoise 0.35，noise_mask_feather 20 | 03 | 已装（P0，两台）；冒烟 ep01-S1：身份 0.713→0.723、肢体可疑标记消失；A/B 等 gpu36:1 实验窗口 | 待写 K-REN-9xx | — | V6 / Q5 坏手 | 待下载批准 |
| T7 | 手部结构错（多指 / 缺指） | MeshGraphormer 深度 + 2.1 Fun ControlNet Union depth 局部重绘；修不好就换 seed | 03；01 | 待下载批准（无人实测过，低置信） | — | — | V6 | 研究 |
| T8 | 修脸（身份 / 糊） | FaceDetailer（face_yolov8m）+ 只在脸区 ColorMatch；修后身份不得下降（K-REV-R09） | 03 | 冒烟不合格：身份 0.713→0.585、脸色偏冷；待调参（降 denoise / 挂身份脸参考） | K-REV-R09 落地 | — | Q1 锚分 + top-k、裁脸 Laplacian、合成感 | 待下载批准 |
| T9 | 贴图感 / 光不一致（L-110/111） | 首选“不合成”：人物参考 + 场景母版一次生成（2.1 最多 10 张参考）；兜底 Apache 的 Edit-2509 Light-Migration / Fusion LoRA | 04；01 §3 | 与 IMGFIX 融合 A/B 对齐 | — | — | 合成感（SENTINEL composite 接口） | 研究 |
| T10 | 姿势 / 构图 / 景别退档 | DWPose（Apache）按景别截断骨架模板 + 2.1 Fun ControlNet Union pose；出图后用 DWPose 关键点判景别做闸门 | 04 B；01 §1 | Fun CN 冒烟失败：0.5 无效、0.8/1.0 崩成参考板拼图（多参考编辑 + Turbo 8 步不兼容）→ 总调度定不推进；景别退档走编译层 + 参考槽；DWPose 可用（9.5 s），留作景别闸门 | — | — | Q3 档差 | 待下载批准 |
| T11 | 区域提示 | 原生 Conditioning Set Mask 挡不住串扰（只按 mask 混合噪声预测，不改注意力）；EliGen 只有 20B 版；不做 | 00 §2–3 | — | — | — | — | 关闭（结论：不做） |
| T12 | Flux 引入 | FLUX.1 dev 全家授权只限非商用，不进生产；只有 FLUX.2 klein 4B 是 Apache，可以作对照 | 02 | 可选对照 | — | — | — | 研究 |

| T13 | 局部 / 不露脸镜出整张脸（ep05-S3/S6/S7 82 版） | K-REN-903：全员局部用局部首句、视线句只给露脸人、去脸部通用句、局部锁只留可见部位；兜底 B1 裁到下颌以下 | 06 | 设计已批；sv-06 后合入；B1 A/B 等实验窗口 | K-REN-903 + orphan_check noface_terms | — | Q3“局部特写出了脸”通过率 | 设计已批 |

## B. 许可证风险（🔴 需总调度 / 项目方定性）

| 项 | 许可 | 出处 | 影响 |
|---|---|---|---|
| Qwen-Image 2.1 / Turbo（现行主模型）、2.1 Fun ControlNet | Qwen Research License：“You shall not use the Materials for any commercial purpose without obtaining a separate commercial license” | 01 §摘要 1；04 §摘要 1 | 商用要另签授权，或者把控制链路切回 Apache 家族（Qwen-Image 20B / Edit-2509 / 2511） |
| FLUX.1 dev / Fill / Kontext / Redux 及其插件 | FLUX.1 [dev] Non-Commercial；2(a)“solely for your Non-Commercial Purposes” | 02 §摘要 1 | 不进生产 |
| insightface buffalo_l / antelopev2（Q1 身份度量） | 非商用科研 | 02、03 | 只用于内部度量，不进成片；需要定性 |
| OpenPose 原版 | “NONCOMMERCIAL RESEARCH USE ONLY” | 04 | 改用 DWPose（Apache） |
| LBM relighting / Harmonizer / InfiniteYou | CC BY-NC | 04、02 | 不用 |

## C. research.yaml 12 条待验规则

只有 K-AST-R06 属于出图，其余 11 条是视频（H3）或剪辑。视频条目按归属交给 VIDEO-RCA / DIRECTOR，IMGLAB 只做文献复核，不做出片实测（本线不发起视频渲染）。

| 规则 | 域 | IMGLAB 判断 | 处理 |
|---|---|---|---|
| K-AST-R06 男角先出正脸肖像再走设定图流程 | 出图 / 资产 | 现行身份脸已改成按角色裁脸（L-086、K-AST-263），“先肖像”已被现行流程覆盖 | 建议改写为“身份脸 = 单独正脸裁切（asset_refs.face_of）”，状态改“确认”；证据：data/assets/identity_refs/*/ |
| K-REN-R08 realism-people 泛红 | 视频 | 只测了 1 个 seed；H3 线 | 交 VIDEO-RCA，维持待验 |
| K-REN-R15 ref_image_size max | 视频 | 证据冲突 | 交 VIDEO-RCA |
| K-REN-R18 合镜 | 视频 | 未验证 | 交 DIRECTOR |
| K-REN-R19 H3 修脸参数 | 视频 | 和出图 T8 同一思路（裁脸 → 低 denoise → 贴回 → 身份不降），参数域不同 | 交 VIDEO-RCA；出图侧由 T8 实测 |
| K-REN-R20 TTS 锁音轨 | 视频 | — | 交 VIDEO-RCA |
| K-REN-R21 latent 续接 | 视频 | — | 交 VIDEO-RCA |
| K-PRM-R02 Subject 标签绑定 | 视频提示 | 出图侧同一原理已由 K-REN-901 证实：描写必须紧跟主语名，否则归错人 | 建议 VIDEO-RCA 按 901 的写法做 B7 A/B |
| K-REV-R02 男角身份差 0.10 | 审片 | 现行 Q1 三段 + top-k（VQAGATE）取代 | 交 VQAGATE，建议改写或推翻 |
| K-REV-R08 开口时间 | 审片 | — | 交 VIDEO-RCA |
| K-EDT-R01 ColorTransfer 0.75 | 剪辑 | 出图修脸后脸区 ColorMatch（T8）是同类操作，可共用实测 | 出图侧随 T8 一起测 |
| K-EDT-R02 插帧顺序 | 剪辑 | — | 交 DIRECTOR |
