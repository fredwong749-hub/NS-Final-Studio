# 林晚资产生成笔记（tools/gen_assets.py）

## 2026-10-30 写实母版 A/B（round 1）

输入：items/makeup/M0_s0.png（v8 §5：灰底正面最干净），Qwen 2.1 编辑，输出 1024×1536，resolution=0 预缩放参考，v8 §3 去 AI 味提示词（不写“严格保持眼睛形状/五官比例”、不写精致/娃娃感）。
拼图：golden/assets/sheets/master_ab_round1.jpg

| 预设 | 设置 | 耗时/张 | 结论 |
|---|---|---|---|
| R0 | Turbo 8 步 | 18 s | 比原图写实很多（光靠提示词+去娃娃比例），但皮肤仍偏平滑 |
| R1 | Base 35 步 CFG1 + texture VAE | 51–78 s | 毛孔出来了，脸偏成熟、光线发灰 |
| R2 | R1 + krea2 0.5 | 84–102 s | 质感好，s1 偏老 |
| R3 | R2 + CFG 2.5（负面词生效） | 105–117 s | **淘汰**：人老了 20 岁、脸垮，CFG>1 在编辑里严重劣化 |
| R4 | glamour_realism 0.6（反面对照） | ~80 s | 如 v8 预期：更像 AI 美颜照 |
| R5 | NiceGirls v2 0.6 | 84 s | 写实但脸型被拉向数据集（颧骨/凹陷），身份漂移 |
| R6 | PureLens 0.6 | — | 文件截断（85MB/152MB），ComfyUI 报 “extends past the end of the file”，未测 |
| R7 | Turn2Real 0.7 + krea2 0.5 | 51–54 s | **最佳**：年轻、真实毛孔与唇纹、正常眼睛、保留唇形和脸型 |
| R8 | NiceGirls 0.5 + krea2 0.4 | 42 s | 次佳，年轻写实；s0 第一次被 CLIP 裸露分 0.811 误判（灰 T 恤），重抽通过 |
| R9 | Anything2Real 0.8 + krea2 0.5 | 63–66 s | 发色变浅、眼妆偏重，仍有 AI 美颜感 |

决定：母版用 R7；生产（底板/表情/单品/造型）用 R2（krea2 0.5，不带转写实 LoRA，v8 §2 原则）。

## 2026-10-30 项目方改方向：保留参考图的“感觉”，写实只加质感

- 第一版写实母版（R7 v2_s3，素颜灰底护照感）被项目方否决（“没有感觉”）→ plates/master_v1_rejected.png。
- 改为直接编辑项目方参考图（file_…92c081…png），提示词“只改变质感，不改变内容”，三档强度，每档 2 种子：
  - 轻 CL：Anything2Real 0.25 + krea2 0.3，refine denoise 0.20
  - 中 CM：Anything2Real 0.45 + krea2 0.4，refine denoise 0.25
  - 重 CS：Anything2Real 0.65 + krea2 0.5，refine denoise 0.30（CS_s1 因 ComfyUI “HostBuffer.read_file_slice failed” 未出）
  - 拼图：golden/assets/master_candidates.jpg
- 项目方先选 CL_s0，后改为 **CM_s1（最终）** → plates/master.png。
- 生产预设随之改为 CM（chosen_preset.json），身份类图加 --refine（0.25）；ID_KEEP 改为保留母版妆容/眼睛/发色，不再要求素颜或雾霾蓝。素颜类（id_front_bare、L1、L2）单独去妆 + 深棕眼。
- 耗时：CM 单张 75–100 s（含 refine），产品图 ~45–60 s。

## 裸露质检的误报（全身正面着装）

- 全身底板（灰 T 恤 + 长裤，或贴身连体衣）连续 8 次被 CLIP 判裸（0.83–0.99），NudeNet 无命中或误报 genitalia。
- 拆分 CLIP 三组得分：第 2 组 “from behind with a completely bare back” vs “from behind wearing a top or dress” 在**正面全身着装图**上给 0.87；同图上半身裁切只有 0.28 → 是质检提示词对全身正面图的系统性误报。
- 未改 qc.py（render_router 归另一个 agent）；绕法：全身底板改穿**深海军蓝长袖针织连衣裙（及膝）**，CLIP 0.29 通过。建议 qc 维护者给第 2 组加朝向判断或只对背影镜头启用。

## 2026-10-30 生产批次（母版 CM_s1，预设 CM）检查记录

- 产品图（CM，无 refine）约 30–60 s/张；身份类（CM + refine 0.25）约 80–130 s/张。
- O02_product 第一张出了真人模特 → 加“只有衣服平放、没有人穿”重出（tools/redo_asset.py 换种子并放回 _s0）。
- B8 漆皮：深色背景 + 两条长条灯箱 → 漆皮镜面长条反光明显，合格。
- B7 鞋跟：全部为针形细跟（目测约为鞋头宽度的 1/6–1/8），合格。S02 漆皮 d'Orsay：side45 / pair 能看出侧开；正侧面（profile）三次都画成闭合尖头鞋——模型在纯侧视角下不画 d'Orsay，已接受并备注，下游参考用 side45。
- A02 九枚阴环 / A03 九环九球：扩散模型数不准（10–15 枚），manifest 标 known_issue；数量由文字 + LoRA 控制。
- TT1 曼陀罗第一张画成两朵对称花 → 改写“圆形放射对称 mandala”重出，合格。
- 手部美甲：手放在肤灰色背景上 CLIP 判裸（0.82–0.95）→ 手腕加黑色针织袖口、背景改中灰丝绒后通过率正常；甲长目测约手指 2/3（不足 5 cm 的视觉比例）。
- 脚部：赤脚俯拍 4/4 被判裸 → 改成“只拍脚趾前半部分的微距”，T1/T3 通过，T2 仍失败；穿透明高跟的 TOE-HEEL 全部通过（加黑色九分裤脚）。
- 全身底板：深海军蓝针织连衣裙方案稳定通过（0.29–0.59）。

## 男角色候选被裸露质检系统性误报

- 14 个候选（顾沉×3、陈宇×3、Alex/Ryan/Kai/Leo×2）几乎全部 4 次重抽都被 CLIP 判裸（0.85–0.99），NudeNet 无命中。
- 人工查看了一张被拦截的样本（顾沉候选 01：黑色长袖衬衫 + 黑西裤，三分之二身，完全着装）→ 明确误报；看完已删除。
- 原因：qc.py 的 CLIP 句对全部是女性措辞（“topless woman” vs “woman wearing clothing…”），男性图两边都不匹配，softmax 偏向“裸”的一侧。
- 按规则不保留被拦截的图；只有 gu_chen_cand_02 通过（0.796）。需要 render_router 维护者给 qc 加男性句对（或按性别选句对）后再出男角色候选。

## 男角色候选（SOP 锁定参数 + QC v3）

- 参数：Qwen 2.1 Base 35 步 CFG 3.0、1024×1536（1.57MP）+ 第二遍 0.30（1.5× 放大后回缩到 ≤1536）、texture-fix VAE、krea2 0.5（文生图无风格化参考 → 不加 Anything2Real）；提示词不含 visual_bible banned_words，加 skin_terms；灰底、素色衣服、无项链/首饰/道具。manifest 记 seed、model、lora、vae、bible_sha256、reference_source（剧本角色锁原文或“无锁，需项目方确认”）。
- QC v3（NudeNet + CLIP v2 + Qwen3-VL 看图裁决）：17/17 一次通过（clip_bare 0.001–0.006）。旧 CLIP-only 版本对着装男性 13/14 误报。
- 每张约 140 s（含第二遍）。
- 问题：CFG 3 下顾沉 3 个候选都显 42–45 岁（锁定 34）→ 提示词加“看起来就是三十出头、无白发、无深皱纹”另出 3 张 *_young（参数不变），观感约 33–38 岁。对比：golden/assets/sheets/gu_chen_age_compare.jpg。
- 同一角色不同种子之间脸差异偏小（像同一人换光）；角色之间差异明显。
- 场景底板：按 SOP keeper 指示暂停（等 v3 剧本过 S1）；tools/gen_scenes.py 已写好，但还是旧参数，启用前需改成锁定参数（cfg 3、1152×2016 + 0.30 + 768×1344 裁切、Reinhard LAB 调色、记录 scenes.json sha）。
