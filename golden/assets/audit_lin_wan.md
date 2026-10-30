# 林晚资产审计（fredw-d9，2026-10-30）

> 基准：项目方通过的母版 `assets/characters/lin_wan/plates/master.png` = `golden/assets/master_cand/CM_s1.png`，sha256 `b8e7b00b675663743a75e4fa86538b70cc87764fa2bdbe06edf82c3343492733`（两文件逐字节一致，见 master.provenance.json）。
> 现行规则：`config/visual_bible.toml` sha256 `a2fd3146d981…`（最后修改 2026-10-30 11:10）；SOP S2 配方（docs/SOP_parameters.md）：Qwen 2.1 Base 35 步 cfg 3、krea2_film_texture 0.5、texture-fix VAE、精修 1.5× 12 步 denoise 0.30、QC v3（裸露一票否决）、记录溯源。
> 审计脚本逻辑：逐个读取 `assets/characters/lin_wan/**/manifest.json`，对照 references、created_at、cfg/LoRA/精修、QC 版本、bible_sha256、禁用词。

## 结论

1. **母版来源没问题，配方和溯源都过期。**
   - master.png 在 06:02:49 换成 CM_s1。现存在用的 on-model 资产全部生成于 06:05 之后，所以像素来源确实是 CM_s1。
   - 但没有一条 manifest 记录母版 sha 或 bible_sha256。visual_bible 在 11:10 又改过一次（当前 a2fd3146），晚于所有资产。
2. **生成配方不是 S2 锁定配方。** 旧资产用的是 CM 预设：
   - Base 35 步 **cfg 1**，带 **Anything2Real 0.45** + krea2 **0.4**，精修 denoise **0.25**；
   - **单段编辑**：直接拿母版做图1。参考图里的项链、手托腮、粉色背景有串进来的风险，而且会照搬正脸构图（pipeline 两段式注释）。
3. **QC 版本过期。** 全部为 v1（`nudenet3.4+clipL14-v1`，CLIP-only，已知对着装全身/男性误报，也漏过真裸露）。没有一张过 v3。
4. **禁用词。** L7 名称“纯欲水光妆”含 bible banned_words 里的“纯欲”。v2 改名为“水光咬唇妆”，配方原文不变。
5. **规格对照（不因此重出，只记录）。**
   - 美甲 N1–N6 甲长目测约 3 cm（提示词写“约为手指长度的三分之二”），钻只铺在甲前段，没有“镶满”。规格（5 cm、镶满透明钻）没变，但成图达不到 → **待项目方决定是否重出**。
   - 鞋跟（B7 针形细跟）、漆皮（B8 镜面）产品图，按 notes.md 已检查合格。

## 处理

| 类别 | 数量 | 处理 |
|---|---|---|
| 多角度底板 plates（正/素颜正/3/4 左/3/4 右/正侧/背/全身） | 9 张在用 | 重出 v2：id_front、id_front_bare、id_34L、id_34R、id_profile、id_back34（新：背面 3/4，取代 id_back）、body_F（取代 body_F_s0/s7）。id_front_heavy 由妆容 L4 v2 取代；body_S/body_B 留到下一轮 |
| 表情 expressions | 6 | 全部重出 v2 |
| 造型 looks | A×3、B×3、C 规格表 | A/B 重出 v2；C（全套 CHAIN）按项目方政策只保留单品清单，不出上身图 |
| 妆容 L1–L8 | 9（L6×2） | 全部重出 v2：在两段式做出的 v2 素颜正脸上单参考编辑（v9 §1），L6 链式叠加在 L4/L1 v2 上 |
| 妆容 M0–M6 | 13 | 早已 superseded（风格化定妆图编辑），不动 |
| 发型 hair、服装上身 outfit *_worn | 6 + 14 | 过期（同上配方/QC），不在本轮优先级 → 下一轮 |
| 产品图：outfit 产品/平铺、shoes 产品、accessory、tattoo | 18 + 8 + 8 + 4 | 不带人、规格未变 → 不重出（只缺 bible_sha256） |
| 局部上身图（手/脚美甲、鞋上脚） | 20 + 2 | 不带身份参考、规格未变 → 不重出；QC 仍为 v1（美甲甲长见上） |

v2 文件命名：`<原名去掉 _s0>_v2.png`。旧条目保留文件，manifest 标 `superseded: true` + `superseded_by`。ns_render/refs.py 已改为跳过 superseded 条目，渲染选参考时只会拿 v2。

## 逐条清单

| 目录 | 文件 | 设计 | 生成 | 用母版 | 结论 | 问题 |
|---|---|---|---|---|---|---|
| expressions | calm_s0.png | LW-EXP-calm | 07:33 | 是 | **过期 → 本轮重出 v2** | manifest 无母版 sha（按时间推断为 CM_s1）；无 bible_sha256（bible 已于 11:10 更新为 a2fd3146）；cfg 1.0≠3；精修 0.25≠0.30；单段编辑（非两段式）；QC nudenet3.4+clipL14-v1（非 v3） |
| expressions | smile_s0.png | LW-EXP-smile | 07:35 | 是 | **过期 → 本轮重出 v2** | manifest 无母版 sha（按时间推断为 CM_s1）；无 bible_sha256（bible 已于 11:10 更新为 a2fd3146）；cfg 1.0≠3；精修 0.25≠0.30；单段编辑（非两段式）；QC nudenet3.4+clipL14-v1（非 v3） |
| expressions | angry_s0.png | LW-EXP-angry | 07:38 | 是 | **过期 → 本轮重出 v2** | manifest 无母版 sha（按时间推断为 CM_s1）；无 bible_sha256（bible 已于 11:10 更新为 a2fd3146）；cfg 1.0≠3；精修 0.25≠0.30；单段编辑（非两段式）；QC nudenet3.4+clipL14-v1（非 v3） |
| expressions | surprised_s0.png | LW-EXP-surprised | 07:39 | 是 | **过期 → 本轮重出 v2** | manifest 无母版 sha（按时间推断为 CM_s1）；无 bible_sha256（bible 已于 11:10 更新为 a2fd3146）；cfg 1.0≠3；精修 0.25≠0.30；单段编辑（非两段式）；QC nudenet3.4+clipL14-v1（非 v3） |
| expressions | seductive_s0.png | LW-EXP-seductive | 07:41 | 是 | **过期 → 本轮重出 v2** | manifest 无母版 sha（按时间推断为 CM_s1）；无 bible_sha256（bible 已于 11:10 更新为 a2fd3146）；cfg 1.0≠3；精修 0.25≠0.30；单段编辑（非两段式）；QC nudenet3.4+clipL14-v1（非 v3） |
| expressions | cry_s0.png | LW-EXP-cry | 09:41 | 是 | **过期 → 本轮重出 v2** | manifest 无母版 sha（按时间推断为 CM_s1）；无 bible_sha256（bible 已于 11:10 更新为 a2fd3146）；cfg 1.0≠3；精修 0.25≠0.30；单段编辑（非两段式）；QC nudenet3.4+clipL14-v1（非 v3） |
| items/accessory | A01_nipple_rings_s0.png | LW-A01 | 06:46 | 否 | 产品图：规格未变，只缺溯源 → 不重出 | 无 bible_sha256（bible 已于 11:10 更新为 a2fd3146） |
| items/accessory | A04_belly_chain_s0.png | LW-A04 | 06:48 | 否 | 产品图：规格未变，只缺溯源 → 不重出 | 无 bible_sha256（bible 已于 11:10 更新为 a2fd3146） |
| items/accessory | A05_tongue_stud_s0.png | LW-A05 | 06:49 | 否 | 产品图：规格未变，只缺溯源 → 不重出 | 无 bible_sha256（bible 已于 11:10 更新为 a2fd3146） |
| items/accessory | A06_velvet_box_s0.png | LW-A06 | 06:50 | 否 | 产品图：规格未变，只缺溯源 → 不重出 | 无 bible_sha256（bible 已于 11:10 更新为 a2fd3146） |
| items/accessory | A07_vanity_case_s0.png | LW-A07 | 06:51 | 否 | 产品图：规格未变，只缺溯源 → 不重出 | 无 bible_sha256（bible 已于 11:10 更新为 a2fd3146） |
| items/accessory | A08_strawberry_necklace_s0.png | LW-A08 | 06:52 | 否 | 产品图：规格未变，只缺溯源 → 不重出 | 无 bible_sha256（bible 已于 11:10 更新为 a2fd3146） |
| items/accessory | A03_beads9_s0.png | LW-A03 | 06:57 | 否 | 产品图：规格未变，只缺溯源 → 不重出 | 无 bible_sha256（bible 已于 11:10 更新为 a2fd3146） |
| items/accessory | A02_rings9_s0.png | LW-A02 | 06:59 | 否 | 产品图：规格未变，只缺溯源 → 不重出 | 无 bible_sha256（bible 已于 11:10 更新为 a2fd3146） |
| items/hair | H0_front_s0.png | LW-H0 | 08:28 | 是 | 过期 → 下一轮（不在本轮优先级） | manifest 无母版 sha（按时间推断为 CM_s1）；无 bible_sha256（bible 已于 11:10 更新为 a2fd3146）；cfg 1.0≠3；精修 0.25≠0.30；单段编辑（非两段式）；QC nudenet3.4+clipL14-v1（非 v3） |
| items/hair | H1_wet_s0.png | LW-H1 | 08:31 | 是 | 过期 → 下一轮（不在本轮优先级） | manifest 无母版 sha（按时间推断为 CM_s1）；无 bible_sha256（bible 已于 11:10 更新为 a2fd3146）；cfg 1.0≠3；精修 0.25≠0.30；单段编辑（非两段式）；QC nudenet3.4+clipL14-v1（非 v3） |
| items/hair | H2_messy_s0.png | LW-H2 | 08:32 | 是 | 过期 → 下一轮（不在本轮优先级） | manifest 无母版 sha（按时间推断为 CM_s1）；无 bible_sha256（bible 已于 11:10 更新为 a2fd3146）；cfg 1.0≠3；精修 0.25≠0.30；单段编辑（非两段式）；QC nudenet3.4+clipL14-v1（非 v3） |
| items/hair | H3_wind_s0.png | LW-H3 | 08:33 | 是 | 过期 → 下一轮（不在本轮优先级） | manifest 无母版 sha（按时间推断为 CM_s1）；无 bible_sha256（bible 已于 11:10 更新为 a2fd3146）；cfg 1.0≠3；精修 0.25≠0.30；单段编辑（非两段式）；QC nudenet3.4+clipL14-v1（非 v3） |
| items/hair | H4_bangs_swept_s0.png | LW-H4 | 08:35 | 是 | 过期 → 下一轮（不在本轮优先级） | manifest 无母版 sha（按时间推断为 CM_s1）；无 bible_sha256（bible 已于 11:10 更新为 a2fd3146）；cfg 1.0≠3；精修 0.25≠0.30；单段编辑（非两段式）；QC nudenet3.4+clipL14-v1（非 v3） |
| items/hair | H0_back_s0.png | LW-H0 | 10:11 | 是 | 过期 → 下一轮（不在本轮优先级） | manifest 无母版 sha（按时间推断为 CM_s1）；无 bible_sha256（bible 已于 11:10 更新为 a2fd3146）；cfg 1.0≠3；精修 0.25≠0.30；单段编辑（非两段式）；QC nudenet3.4+clipL14-v1（非 v3） |
| items/makeup | M0_s0.png | M0 | 04:29 | 否 | 已停用（历史） |  |
| items/makeup | M1_s0.png | M1 | 04:29 | 否 | 已停用（历史） |  |
| items/makeup | M2_s0.png | M2 | 04:29 | 否 | 已停用（历史） |  |
| items/makeup | M3_s0.png | M3 | 04:30 | 否 | 已停用（历史） |  |
| items/makeup | M4_s0.png | M4 | 04:30 | 否 | 已停用（历史） |  |
| items/makeup | M5_s0.png | M5 | 04:51 | 否 | 已停用（历史） |  |
| items/makeup | M5_s1.png | M5 | 04:51 | 否 | 已停用（历史） |  |
| items/makeup | M6_s0.png | M6 | 04:51 | 否 | 已停用（历史） |  |
| items/makeup | M6_s1.png | M6 | 04:51 | 否 | 已停用（历史） |  |
| items/makeup | M5_s2.png | M5 | 05:39 | 否 | 已停用（历史） |  |
| items/makeup | M5_s3.png | M5 | 05:41 | 否 | 已停用（历史） |  |
| items/makeup | M6_s2.png | M6 | 05:42 | 否 | 已停用（历史） |  |
| items/makeup | M6_s3.png | M6 | 05:43 | 否 | 已停用（历史） |  |
| items/makeup | L1_bare_commute_s0.png | L1 | 08:37 | 是 | **过期 → 本轮重出 v2** | manifest 无母版 sha（按时间推断为 CM_s1）；无 bible_sha256（bible 已于 11:10 更新为 a2fd3146）；cfg 1.0≠3；精修 0.25≠0.30；单段编辑（非两段式）；QC nudenet3.4+clipL14-v1（非 v3） |
| items/makeup | L2_half_red_s0.png | L2 | 08:39 | 是 | **过期 → 本轮重出 v2** | manifest 无母版 sha（按时间推断为 CM_s1）；无 bible_sha256（bible 已于 11:10 更新为 a2fd3146）；cfg 1.0≠3；精修 0.25≠0.30；单段编辑（非两段式）；QC nudenet3.4+clipL14-v1（非 v3） |
| items/makeup | L3_red_lip_city_s0.png | L3 | 08:40 | 是 | **过期 → 本轮重出 v2** | manifest 无母版 sha（按时间推断为 CM_s1）；无 bible_sha256（bible 已于 11:10 更新为 a2fd3146）；cfg 1.0≠3；精修 0.25≠0.30；单段编辑（非两段式）；QC nudenet3.4+clipL14-v1（非 v3） |
| items/makeup | L4_queen_s0.png | L4 | 08:42 | 是 | **过期 → 本轮重出 v2** | manifest 无母版 sha（按时间推断为 CM_s1）；无 bible_sha256（bible 已于 11:10 更新为 a2fd3146）；cfg 1.0≠3；精修 0.25≠0.30；单段编辑（非两段式）；QC nudenet3.4+clipL14-v1（非 v3） |
| items/makeup | L5_night_crystal_s0.png | L5 | 08:44 | 是 | **过期 → 本轮重出 v2** | manifest 无母版 sha（按时间推断为 CM_s1）；无 bible_sha256（bible 已于 11:10 更新为 a2fd3146）；cfg 1.0≠3；精修 0.25≠0.30；单段编辑（非两段式）；QC nudenet3.4+clipL14-v1（非 v3） |
| items/makeup | L7_dewy_signature_s0.png | L7 | 08:46 | 是 | **过期 → 本轮重出 v2** | manifest 无母版 sha（按时间推断为 CM_s1）；无 bible_sha256（bible 已于 11:10 更新为 a2fd3146）；cfg 1.0≠3；精修 0.25≠0.30；单段编辑（非两段式）；QC nudenet3.4+clipL14-v1（非 v3）；含禁用词 纯欲 |
| items/makeup | L8_sweet_refined_s0.png | L8 | 08:47 | 是 | **过期 → 本轮重出 v2** | manifest 无母版 sha（按时间推断为 CM_s1）；无 bible_sha256（bible 已于 11:10 更新为 a2fd3146）；cfg 1.0≠3；精修 0.25≠0.30；单段编辑（非两段式）；QC nudenet3.4+clipL14-v1（非 v3） |
| items/makeup | L6_tears_on_L4_s0.png | L6 | 09:53 | 链式 | **过期 → 本轮重出 v2** | manifest 无母版 sha（按时间推断为 CM_s1）；无 bible_sha256（bible 已于 11:10 更新为 a2fd3146）；cfg 1.0≠3；精修 0.25≠0.30；QC nudenet3.4+clipL14-v1（非 v3） |
| items/makeup | L6_tears_on_L1_s0.png | L6 | 09:55 | 链式 | **过期 → 本轮重出 v2** | manifest 无母版 sha（按时间推断为 CM_s1）；无 bible_sha256（bible 已于 11:10 更新为 a2fd3146）；cfg 1.0≠3；精修 0.25≠0.30；QC nudenet3.4+clipL14-v1（非 v3） |
| items/nails | N1_BK_s0.png | LW-N1 | 06:59 | 否 | 局部上身图（无身份参考）：溯源/QC 过期，规格未变 → 不重出 | 无 bible_sha256（bible 已于 11:10 更新为 a2fd3146）；cfg 1.0≠3；无精修；QC nudenet3.4+clipL14-v1（非 v3） |
| items/nails | N1_PL_s0.png | LW-N1 | 07:02 | 否 | 局部上身图（无身份参考）：溯源/QC 过期，规格未变 → 不重出 | 无 bible_sha256（bible 已于 11:10 更新为 a2fd3146）；cfg 1.0≠3；无精修；QC nudenet3.4+clipL14-v1（非 v3） |
| items/nails | N2_BK_s0.png | LW-N2 | 07:03 | 否 | 局部上身图（无身份参考）：溯源/QC 过期，规格未变 → 不重出 | 无 bible_sha256（bible 已于 11:10 更新为 a2fd3146）；cfg 1.0≠3；无精修；QC nudenet3.4+clipL14-v1（非 v3） |
| items/nails | N2_PL_s0.png | LW-N2 | 07:03 | 否 | 局部上身图（无身份参考）：溯源/QC 过期，规格未变 → 不重出 | 无 bible_sha256（bible 已于 11:10 更新为 a2fd3146）；cfg 1.0≠3；无精修；QC nudenet3.4+clipL14-v1（非 v3） |
| items/nails | N3_BK_s0.png | LW-N3 | 07:04 | 否 | 局部上身图（无身份参考）：溯源/QC 过期，规格未变 → 不重出 | 无 bible_sha256（bible 已于 11:10 更新为 a2fd3146）；cfg 1.0≠3；无精修；QC nudenet3.4+clipL14-v1（非 v3） |
| items/nails | N3_PL_s0.png | LW-N3 | 07:04 | 否 | 局部上身图（无身份参考）：溯源/QC 过期，规格未变 → 不重出 | 无 bible_sha256（bible 已于 11:10 更新为 a2fd3146）；cfg 1.0≠3；无精修；QC nudenet3.4+clipL14-v1（非 v3） |
| items/nails | N4_BK_s0.png | LW-N4 | 07:05 | 否 | 局部上身图（无身份参考）：溯源/QC 过期，规格未变 → 不重出 | 无 bible_sha256（bible 已于 11:10 更新为 a2fd3146）；cfg 1.0≠3；无精修；QC nudenet3.4+clipL14-v1（非 v3） |
| items/nails | N4_PL_s0.png | LW-N4 | 07:06 | 否 | 局部上身图（无身份参考）：溯源/QC 过期，规格未变 → 不重出 | 无 bible_sha256（bible 已于 11:10 更新为 a2fd3146）；cfg 1.0≠3；无精修；QC nudenet3.4+clipL14-v1（非 v3） |
| items/nails | N5_BK_s0.png | LW-N5 | 07:07 | 否 | 局部上身图（无身份参考）：溯源/QC 过期，规格未变 → 不重出 | 无 bible_sha256（bible 已于 11:10 更新为 a2fd3146）；cfg 1.0≠3；无精修；QC nudenet3.4+clipL14-v1（非 v3） |
| items/nails | N5_PL_s0.png | LW-N5 | 07:08 | 否 | 局部上身图（无身份参考）：溯源/QC 过期，规格未变 → 不重出 | 无 bible_sha256（bible 已于 11:10 更新为 a2fd3146）；cfg 1.0≠3；无精修；QC nudenet3.4+clipL14-v1（非 v3） |
| items/nails | N6_BK_s0.png | LW-N6 | 07:09 | 否 | 局部上身图（无身份参考）：溯源/QC 过期，规格未变 → 不重出 | 无 bible_sha256（bible 已于 11:10 更新为 a2fd3146）；cfg 1.0≠3；无精修；QC nudenet3.4+clipL14-v1（非 v3） |
| items/nails | N6_PL_s0.png | LW-N6 | 07:09 | 否 | 局部上身图（无身份参考）：溯源/QC 过期，规格未变 → 不重出 | 无 bible_sha256（bible 已于 11:10 更新为 a2fd3146）；cfg 1.0≠3；无精修；QC nudenet3.4+clipL14-v1（非 v3） |
| items/nails | T1_HEEL_s0.png | LW-T1 | 07:12 | 链式 | 局部上身图（无身份参考）：溯源/QC 过期，规格未变 → 不重出 | 无 bible_sha256（bible 已于 11:10 更新为 a2fd3146）；cfg 1.0≠3；无精修；QC nudenet3.4+clipL14-v1（非 v3） |
| items/nails | T2_HEEL_s0.png | LW-T2 | 07:16 | 链式 | 局部上身图（无身份参考）：溯源/QC 过期，规格未变 → 不重出 | 无 bible_sha256（bible 已于 11:10 更新为 a2fd3146）；cfg 1.0≠3；无精修；QC nudenet3.4+clipL14-v1（非 v3） |
| items/nails | T3_HEEL_s0.png | LW-T3 | 07:19 | 链式 | 局部上身图（无身份参考）：溯源/QC 过期，规格未变 → 不重出 | 无 bible_sha256（bible 已于 11:10 更新为 a2fd3146）；cfg 1.0≠3；无精修；QC nudenet3.4+clipL14-v1（非 v3） |
| items/nails | T4_BARE_s0.png | LW-T4 | 07:20 | 否 | 局部上身图（无身份参考）：溯源/QC 过期，规格未变 → 不重出 | 无 bible_sha256（bible 已于 11:10 更新为 a2fd3146）；cfg 1.0≠3；无精修；QC nudenet3.4+clipL14-v1（非 v3） |
| items/nails | T4_HEEL_s0.png | LW-T4 | 07:21 | 链式 | 局部上身图（无身份参考）：溯源/QC 过期，规格未变 → 不重出 | 无 bible_sha256（bible 已于 11:10 更新为 a2fd3146）；cfg 1.0≠3；无精修；QC nudenet3.4+clipL14-v1（非 v3） |
| items/nails | T1_BARE_s0.png | LW-T1 | 07:22 | 否 | 局部上身图（无身份参考）：溯源/QC 过期，规格未变 → 不重出 | 无 bible_sha256（bible 已于 11:10 更新为 a2fd3146）；cfg 1.0≠3；无精修；QC nudenet3.4+clipL14-v1（非 v3） |
| items/nails | T3_BARE_s0.png | LW-T3 | 07:28 | 否 | 局部上身图（无身份参考）：溯源/QC 过期，规格未变 → 不重出 | 无 bible_sha256（bible 已于 11:10 更新为 a2fd3146）；cfg 1.0≠3；无精修；QC nudenet3.4+clipL14-v1（非 v3） |
| items/nails | T2_BARE_s0.png | LW-T2 | 09:37 | 否 | 局部上身图（无身份参考）：溯源/QC 过期，规格未变 → 不重出 | 无 bible_sha256（bible 已于 11:10 更新为 a2fd3146）；cfg 1.0≠3；无精修；QC nudenet3.4+clipL14-v1（非 v3） |
| items/outfit | O09_product_s0.png | LW-O09 | 06:29 | 否 | 产品图：规格未变，只缺溯源 → 不重出 | 无 bible_sha256（bible 已于 11:10 更新为 a2fd3146） |
| items/outfit | O01_product_s0.png | LW-O01 | 06:30 | 否 | 产品图：规格未变，只缺溯源 → 不重出 | 无 bible_sha256（bible 已于 11:10 更新为 a2fd3146） |
| items/outfit | O03_product_s0.png | LW-O03 | 06:31 | 否 | 产品图：规格未变，只缺溯源 → 不重出 | 无 bible_sha256（bible 已于 11:10 更新为 a2fd3146） |
| items/outfit | O05_product_s0.png | LW-O05 | 06:31 | 否 | 产品图：规格未变，只缺溯源 → 不重出 | 无 bible_sha256（bible 已于 11:10 更新为 a2fd3146） |
| items/outfit | O07_product_s0.png | LW-O07 | 06:32 | 否 | 产品图：规格未变，只缺溯源 → 不重出 | 无 bible_sha256（bible 已于 11:10 更新为 a2fd3146） |
| items/outfit | O08_product_s0.png | LW-O08 | 06:33 | 否 | 产品图：规格未变，只缺溯源 → 不重出 | 无 bible_sha256（bible 已于 11:10 更新为 a2fd3146） |
| items/outfit | O10_product_s0.png | LW-O10 | 06:33 | 否 | 产品图：规格未变，只缺溯源 → 不重出 | 无 bible_sha256（bible 已于 11:10 更新为 a2fd3146） |
| items/outfit | O11_product_s0.png | LW-O11 | 06:34 | 否 | 产品图：规格未变，只缺溯源 → 不重出 | 无 bible_sha256（bible 已于 11:10 更新为 a2fd3146） |
| items/outfit | O12_flatlay_dark_s0.png | LW-O12 | 06:35 | 否 | 产品图：规格未变，只缺溯源 → 不重出 | 无 bible_sha256（bible 已于 11:10 更新为 a2fd3146） |
| items/outfit | O12_flatlay_white_s0.png | LW-O12 | 06:35 | 否 | 产品图：规格未变，只缺溯源 → 不重出 | 无 bible_sha256（bible 已于 11:10 更新为 a2fd3146） |
| items/outfit | O12_mannequin_s0.png | LW-O12 | 06:36 | 否 | 产品图：规格未变，只缺溯源 → 不重出 | 无 bible_sha256（bible 已于 11:10 更新为 a2fd3146） |
| items/outfit | O13_product_s0.png | LW-O13 | 06:37 | 否 | 产品图：规格未变，只缺溯源 → 不重出 | 无 bible_sha256（bible 已于 11:10 更新为 a2fd3146） |
| items/outfit | O14_product_s0.png | LW-O14 | 06:37 | 否 | 产品图：规格未变，只缺溯源 → 不重出 | 无 bible_sha256（bible 已于 11:10 更新为 a2fd3146） |
| items/outfit | O02_product_s0.png | LW-O02 | 06:38 | 否 | 产品图：规格未变，只缺溯源 → 不重出 | 无 bible_sha256（bible 已于 11:10 更新为 a2fd3146） |
| items/outfit | O15_product_s0.png | LW-O15 | 06:38 | 否 | 产品图：规格未变，只缺溯源 → 不重出 | 无 bible_sha256（bible 已于 11:10 更新为 a2fd3146） |
| items/outfit | O16_product_s0.png | LW-O16 | 06:39 | 否 | 产品图：规格未变，只缺溯源 → 不重出 | 无 bible_sha256（bible 已于 11:10 更新为 a2fd3146） |
| items/outfit | O19_product_s0.png | LW-O19 | 06:40 | 否 | 产品图：规格未变，只缺溯源 → 不重出 | 无 bible_sha256（bible 已于 11:10 更新为 a2fd3146） |
| items/outfit | O21_product_s0.png | LW-O21 | 06:40 | 否 | 产品图：规格未变，只缺溯源 → 不重出 | 无 bible_sha256（bible 已于 11:10 更新为 a2fd3146） |
| items/outfit | O00_worn_s0.png | LW-O00 | 07:42 | 是 | 过期 → 下一轮（不在本轮优先级） | manifest 无母版 sha（按时间推断为 CM_s1）；无 bible_sha256（bible 已于 11:10 更新为 a2fd3146）；cfg 1.0≠3；精修 0.25≠0.30；单段编辑（非两段式）；QC nudenet3.4+clipL14-v1（非 v3） |
| items/outfit | O09_worn_s0.png | LW-O09 | 07:44 | 是 | 过期 → 下一轮（不在本轮优先级） | manifest 无母版 sha（按时间推断为 CM_s1）；无 bible_sha256（bible 已于 11:10 更新为 a2fd3146）；cfg 1.0≠3；精修 0.25≠0.30；单段编辑（非两段式）；QC nudenet3.4+clipL14-v1（非 v3） |
| items/outfit | O01_worn_s0.png | LW-O01 | 07:46 | 是 | 过期 → 下一轮（不在本轮优先级） | manifest 无母版 sha（按时间推断为 CM_s1）；无 bible_sha256（bible 已于 11:10 更新为 a2fd3146）；cfg 1.0≠3；精修 0.25≠0.30；单段编辑（非两段式）；QC nudenet3.4+clipL14-v1（非 v3） |
| items/outfit | O02_worn_s0.png | LW-O02 | 07:48 | 是 | 过期 → 下一轮（不在本轮优先级） | manifest 无母版 sha（按时间推断为 CM_s1）；无 bible_sha256（bible 已于 11:10 更新为 a2fd3146）；cfg 1.0≠3；精修 0.25≠0.30；单段编辑（非两段式）；QC nudenet3.4+clipL14-v1（非 v3） |
| items/outfit | O03_worn_s0.png | LW-O03 | 07:50 | 是 | 过期 → 下一轮（不在本轮优先级） | manifest 无母版 sha（按时间推断为 CM_s1）；无 bible_sha256（bible 已于 11:10 更新为 a2fd3146）；cfg 1.0≠3；精修 0.25≠0.30；单段编辑（非两段式）；QC nudenet3.4+clipL14-v1（非 v3） |
| items/outfit | O04_worn_s0.png | LW-O04 | 07:51 | 是 | 过期 → 下一轮（不在本轮优先级） | manifest 无母版 sha（按时间推断为 CM_s1）；无 bible_sha256（bible 已于 11:10 更新为 a2fd3146）；cfg 1.0≠3；精修 0.25≠0.30；单段编辑（非两段式）；QC nudenet3.4+clipL14-v1（非 v3） |
| items/outfit | O07_worn_s0.png | LW-O07 | 07:59 | 是 | 过期 → 下一轮（不在本轮优先级） | manifest 无母版 sha（按时间推断为 CM_s1）；无 bible_sha256（bible 已于 11:10 更新为 a2fd3146）；cfg 1.0≠3；精修 0.25≠0.30；单段编辑（非两段式）；QC nudenet3.4+clipL14-v1（非 v3） |
| items/outfit | O08_worn_s0.png | LW-O08 | 08:02 | 是 | 过期 → 下一轮（不在本轮优先级） | manifest 无母版 sha（按时间推断为 CM_s1）；无 bible_sha256（bible 已于 11:10 更新为 a2fd3146）；cfg 1.0≠3；精修 0.25≠0.30；单段编辑（非两段式）；QC nudenet3.4+clipL14-v1（非 v3） |
| items/outfit | O15_worn_s0.png | LW-O15 | 08:04 | 是 | 过期 → 下一轮（不在本轮优先级） | manifest 无母版 sha（按时间推断为 CM_s1）；无 bible_sha256（bible 已于 11:10 更新为 a2fd3146）；cfg 1.0≠3；精修 0.25≠0.30；单段编辑（非两段式）；QC nudenet3.4+clipL14-v1（非 v3） |
| items/outfit | O17_worn_s0.png | LW-O17 | 08:13 | 是 | 过期 → 下一轮（不在本轮优先级） | manifest 无母版 sha（按时间推断为 CM_s1）；无 bible_sha256（bible 已于 11:10 更新为 a2fd3146）；cfg 1.0≠3；精修 0.25≠0.30；单段编辑（非两段式）；QC nudenet3.4+clipL14-v1（非 v3） |
| items/outfit | O21_worn_s0.png | LW-O21 | 08:26 | 是 | 过期 → 下一轮（不在本轮优先级） | manifest 无母版 sha（按时间推断为 CM_s1）；无 bible_sha256（bible 已于 11:10 更新为 a2fd3146）；cfg 1.0≠3；精修 0.25≠0.30；单段编辑（非两段式）；QC nudenet3.4+clipL14-v1（非 v3） |
| items/outfit | O06_worn_s0.png | LW-O06 | 09:14 | 是 | 过期 → 下一轮（不在本轮优先级） | manifest 无母版 sha（按时间推断为 CM_s1）；无 bible_sha256（bible 已于 11:10 更新为 a2fd3146）；cfg 1.0≠3；精修 0.25≠0.30；单段编辑（非两段式）；QC nudenet3.4+clipL14-v1（非 v3） |
| items/outfit | O16_worn_s0.png | LW-O16 | 09:22 | 是 | 过期 → 下一轮（不在本轮优先级） | manifest 无母版 sha（按时间推断为 CM_s1）；无 bible_sha256（bible 已于 11:10 更新为 a2fd3146）；cfg 1.0≠3；精修 0.25≠0.30；单段编辑（非两段式）；QC nudenet3.4+clipL14-v1（非 v3） |
| items/outfit | O20_worn_s0.png | LW-O20 | 09:35 | 是 | 过期 → 下一轮（不在本轮优先级） | manifest 无母版 sha（按时间推断为 CM_s1）；无 bible_sha256（bible 已于 11:10 更新为 a2fd3146）；cfg 1.0≠3；精修 0.25≠0.30；单段编辑（非两段式）；QC nudenet3.4+clipL14-v1（非 v3） |
| items/shoes | S01_side45_s0.png | LW-S01 | 06:41 | 否 | 产品图：规格未变，只缺溯源 → 不重出 | 无 bible_sha256（bible 已于 11:10 更新为 a2fd3146） |
| items/shoes | S01_pair_s0.png | LW-S01 | 06:41 | 否 | 产品图：规格未变，只缺溯源 → 不重出 | 无 bible_sha256（bible 已于 11:10 更新为 a2fd3146） |
| items/shoes | S01_profile_s0.png | LW-S01 | 06:42 | 否 | 产品图：规格未变，只缺溯源 → 不重出 | 无 bible_sha256（bible 已于 11:10 更新为 a2fd3146） |
| items/shoes | S01_back_s0.png | LW-S01 | 06:43 | 否 | 产品图：规格未变，只缺溯源 → 不重出 | 无 bible_sha256（bible 已于 11:10 更新为 a2fd3146） |
| items/shoes | S02_back_s0.png | LW-S02 | 06:45 | 否 | 产品图：规格未变，只缺溯源 → 不重出 | 无 bible_sha256（bible 已于 11:10 更新为 a2fd3146） |
| items/shoes | S02_side45_s0.png | LW-S02 | 06:47 | 否 | 产品图：规格未变，只缺溯源 → 不重出 | 无 bible_sha256（bible 已于 11:10 更新为 a2fd3146） |
| items/shoes | S02_pair_s0.png | LW-S02 | 06:49 | 否 | 产品图：规格未变，只缺溯源 → 不重出 | 无 bible_sha256（bible 已于 11:10 更新为 a2fd3146） |
| items/shoes | S02_profile_s0.png | LW-S02 | 06:50 | 否 | 产品图：规格未变，只缺溯源 → 不重出 | 无 bible_sha256（bible 已于 11:10 更新为 a2fd3146） |
| items/shoes | S01_worn_s0.png | LW-S01 | 06:55 | 链式 | 局部上身图（无身份参考）：溯源/QC 过期，规格未变 → 不重出 | 无 bible_sha256（bible 已于 11:10 更新为 a2fd3146）；cfg 1.0≠3；无精修；QC nudenet3.4+clipL14-v1（非 v3） |
| items/shoes | S02_worn_s0.png | LW-S02 | 06:56 | 链式 | 局部上身图（无身份参考）：溯源/QC 过期，规格未变 → 不重出 | 无 bible_sha256（bible 已于 11:10 更新为 a2fd3146）；cfg 1.0≠3；无精修；QC nudenet3.4+clipL14-v1（非 v3） |
| items/tattoo | TT2_snake_s0.png | LW-TT2 | 06:53 | 否 | 产品图：规格未变，只缺溯源 → 不重出 | 无 bible_sha256（bible 已于 11:10 更新为 a2fd3146） |
| items/tattoo | TT3_chen_s0.png | LW-TT3 | 06:53 | 否 | 产品图：规格未变，只缺溯源 → 不重出 | 无 bible_sha256（bible 已于 11:10 更新为 a2fd3146） |
| items/tattoo | TT4_wings_s0.png | LW-TT4 | 06:54 | 否 | 产品图：规格未变，只缺溯源 → 不重出 | 无 bible_sha256（bible 已于 11:10 更新为 a2fd3146） |
| items/tattoo | TT1_mandala_s0.png | LW-TT1 | 06:58 | 否 | 产品图：规格未变，只缺溯源 → 不重出 | 无 bible_sha256（bible 已于 11:10 更新为 a2fd3146） |
| looks | REF-LW-01_front_s0.png | REF-LW-01 | 08:53 | 是 | **过期 → 本轮重出 v2** | manifest 无母版 sha（按时间推断为 CM_s1）；无 bible_sha256（bible 已于 11:10 更新为 a2fd3146）；cfg 1.0≠3；精修 0.25≠0.30；单段编辑（非两段式）；QC nudenet3.4+clipL14-v1（非 v3） |
| looks | REF-LW-01_back_s0.png | REF-LW-01 | 08:55 | 是 | **过期 → 本轮重出 v2** | manifest 无母版 sha（按时间推断为 CM_s1）；无 bible_sha256（bible 已于 11:10 更新为 a2fd3146）；cfg 1.0≠3；精修 0.25≠0.30；单段编辑（非两段式）；QC nudenet3.4+clipL14-v1（非 v3） |
| looks | REF-LW-01_34_s0.png | REF-LW-01 | 08:57 | 是 | **过期 → 本轮重出 v2** | manifest 无母版 sha（按时间推断为 CM_s1）；无 bible_sha256（bible 已于 11:10 更新为 a2fd3146）；cfg 1.0≠3；精修 0.25≠0.30；单段编辑（非两段式）；QC nudenet3.4+clipL14-v1（非 v3） |
| looks | REF-LW-02_front_s0.png | REF-LW-02 | 08:59 | 是 | **过期 → 本轮重出 v2** | manifest 无母版 sha（按时间推断为 CM_s1）；无 bible_sha256（bible 已于 11:10 更新为 a2fd3146）；cfg 1.0≠3；精修 0.25≠0.30；单段编辑（非两段式）；QC nudenet3.4+clipL14-v1（非 v3） |
| looks | REF-LW-02_34_s0.png | REF-LW-02 | 09:04 | 是 | **过期 → 本轮重出 v2** | manifest 无母版 sha（按时间推断为 CM_s1）；无 bible_sha256（bible 已于 11:10 更新为 a2fd3146）；cfg 1.0≠3；精修 0.25≠0.30；单段编辑（非两段式）；QC nudenet3.4+clipL14-v1（非 v3） |
| looks | REF-LW-02_back_s0.png | REF-LW-02 | 09:50 | 是 | **过期 → 本轮重出 v2** | manifest 无母版 sha（按时间推断为 CM_s1）；无 bible_sha256（bible 已于 11:10 更新为 a2fd3146）；cfg 1.0≠3；精修 0.25≠0.30；单段编辑（非两段式）；QC nudenet3.4+clipL14-v1（非 v3） |
| plates | master_v1_rejected.png | LW-MASTER | 05:29 | 链式 | 已停用（历史） |  |
| plates | id_front_s0_v1superseded.png | LW-ID-F | 05:39 | 是 | 已停用（历史） |  |
| plates | id_front_bare_s0_v1superseded.png | LW-ID-F-bare | 05:40 | 是 | 已停用（历史） |  |
| plates | id_34L_s0_v1superseded.png | LW-ID-34L | 05:43 | 是 | 已停用（历史） |  |
| plates | master.png | LW-MASTER | 05:59 | 否 | 母版本身（CM_s1，sha b8e7b00b，基准） | manifest 条目 created_at 05:59 为候选生成时间；provenance 见 master.provenance.json |
| plates | id_front_s0.png | LW-ID-F | 06:05 | 是 | **过期 → 本轮重出 v2** | manifest 无母版 sha（按时间推断为 CM_s1）；无 bible_sha256（bible 已于 11:10 更新为 a2fd3146）；cfg 1.0≠3；精修 0.25≠0.30；单段编辑（非两段式）；QC nudenet3.4+clipL14-v1（非 v3） |
| plates | id_front_heavy_s0.png | LW-ID-F-heavy | 06:08 | 是 | 过期 → 由妆容 L4 v2 取代（不单独重出） | manifest 无母版 sha（按时间推断为 CM_s1）；无 bible_sha256（bible 已于 11:10 更新为 a2fd3146）；cfg 1.0≠3；精修 0.25≠0.30；单段编辑（非两段式）；QC nudenet3.4+clipL14-v1（非 v3） |
| plates | id_34L_s0.png | LW-ID-34L | 06:10 | 是 | **过期 → 本轮重出 v2** | manifest 无母版 sha（按时间推断为 CM_s1）；无 bible_sha256（bible 已于 11:10 更新为 a2fd3146）；cfg 1.0≠3；精修 0.25≠0.30；单段编辑（非两段式）；QC nudenet3.4+clipL14-v1（非 v3） |
| plates | body_F_s7.png | LW-BODY-F | 06:28 | 是 | **过期 → 本轮重出 v2** | manifest 无母版 sha（按时间推断为 CM_s1）；无 bible_sha256（bible 已于 11:10 更新为 a2fd3146）；cfg 1.0≠3；精修 0.25≠0.30；单段编辑（非两段式）；QC nudenet3.4+clipL14-v1（非 v3） |
| plates | id_34R_s0.png | LW-ID-34R | 07:23 | 是 | **过期 → 本轮重出 v2** | manifest 无母版 sha（按时间推断为 CM_s1）；无 bible_sha256（bible 已于 11:10 更新为 a2fd3146）；cfg 1.0≠3；精修 0.25≠0.30；单段编辑（非两段式）；QC nudenet3.4+clipL14-v1（非 v3） |
| plates | id_profile_s0.png | LW-ID-P | 07:25 | 是 | **过期 → 本轮重出 v2** | manifest 无母版 sha（按时间推断为 CM_s1）；无 bible_sha256（bible 已于 11:10 更新为 a2fd3146）；cfg 1.0≠3；精修 0.25≠0.30；单段编辑（非两段式）；QC nudenet3.4+clipL14-v1（非 v3） |
| plates | id_back_s0.png | LW-ID-B | 07:27 | 是 | **过期 → 本轮重出 v2** | manifest 无母版 sha（按时间推断为 CM_s1）；无 bible_sha256（bible 已于 11:10 更新为 a2fd3146）；cfg 1.0≠3；精修 0.25≠0.30；单段编辑（非两段式）；QC nudenet3.4+clipL14-v1（非 v3） |
| plates | body_F_s0.png | LW-BODY-F | 07:29 | 是 | **过期 → 本轮重出 v2** | manifest 无母版 sha（按时间推断为 CM_s1）；无 bible_sha256（bible 已于 11:10 更新为 a2fd3146）；cfg 1.0≠3；精修 0.25≠0.30；单段编辑（非两段式）；QC nudenet3.4+clipL14-v1（非 v3） |
| plates | body_S_s0.png | LW-BODY-S | 07:31 | 是 | 过期 → 下一轮（本轮做正面全身 + 背面 3/4） | manifest 无母版 sha（按时间推断为 CM_s1）；无 bible_sha256（bible 已于 11:10 更新为 a2fd3146）；cfg 1.0≠3；精修 0.25≠0.30；单段编辑（非两段式）；QC nudenet3.4+clipL14-v1（非 v3） |
| plates | body_B_s0.png | LW-BODY-B | 07:32 | 是 | 过期 → 下一轮（本轮做正面全身 + 背面 3/4） | manifest 无母版 sha（按时间推断为 CM_s1）；无 bible_sha256（bible 已于 11:10 更新为 a2fd3146）；cfg 1.0≠3；精修 0.25≠0.30；单段编辑（非两段式）；QC nudenet3.4+clipL14-v1（非 v3） |
| plates | id_front_bare_s0.png | LW-ID-F-bare | 09:39 | 是 | **过期 → 本轮重出 v2** | manifest 无母版 sha（按时间推断为 CM_s1）；无 bible_sha256（bible 已于 11:10 更新为 a2fd3146）；cfg 1.0≠3；精修 0.25≠0.30；单段编辑（非两段式）；QC nudenet3.4+clipL14-v1（非 v3） |
