# Qwen 2.1 写法研究 → 交给各方的改动提案（BAKEOFF，2026-11-01）

依据：docs/qwen21/RESEARCH.md（官方 / 社区调研）、docs/qwen21/BACKCHECK.md（回查数字）、knowledge/rules/render_qwen21.yaml（规则）。
BAKEOFF 只出提案和检查（tools/bakeoff/qwen21_lint.py），不改别人的文件。

## A. 编译器 / 资产参考（交 REFLOCK：ns_agent.compiler、asset_refs、frame_job、gen_contract）

| # | 问题（lint 规则） | 回查数字 | 提议 | 规则 |
|---|---|---|---|---|
| A1 | 特写 / 近景里，系统补的“本镜造型要穿全：深灰铅笔裙……”句把腰以下部件写进去（QL01，系统那一半） | 命中的版本 Q3 不过 29%，未命中 6%（BACKCHECK） | “要穿全”句只列景别可见区的部件；腰以下靠参考板锁 | K-PRM-Q22 |
| A2 | 局部特写也拼了【角色】身份锁（年龄、发型、肤色）（QL02） | 命中的 9 个版本 Q1 全部不过；总调度驳回 ep05-S3 / S5、ep10-S8 | subject=part 时不拼身份锁，只写局部部件 | K-PRM-Q23 |
| A3 | 系统句里的否定（“不是长裤”“不背对镜头”“不出现脸”“无字幕、无文字、无水印”）（QL03） | 命中的版本 Q2 不过 24%，未命中 4% | 全部改成肯定句；“无字幕 / 无文字 / 无水印”在 cfg 1 下没用，删掉 | K-PRM-Q24 |
| A4 | 参考标注写“图N是…”，官方写法是 <imageN>（QL11） | 80/80 条作业都是“图N” | 先放行 A/B：请 preflight I6 同时认 `<imageN>是`；A/B（qa_imgtag）证实后再改 prompt_prefix | K-PRM-Q26 |
| A5 | 有身份脸参考时，身份锁里仍用文字写五官 / 肤色（冷白皮肤、深棕色眼睛、眼睛为真实人眼大小）（QL14） | 73/80 条作业命中 | 挂了身份脸的角色，身份锁只留体态、发型和发色（属造型），不写五官和肤色；先跑 A/B | K-PRM-Q26 |
| A6 | 【林晚】【场景】标签、sk_xxx 场景 id 原样进提示词（QL05） | 80/80 条作业命中 | 改成自然语言：“林晚：”“场景：穿孔纹身工作室”；sk_ 开头的 id 换成场景名 | K-PRM-Q28 |
| A7 | 场景写了三遍：【场景】段 + 空间描述 + 本镜场景（QL09） | 命中的版本 Q7 不过 33%，未命中 9% | 只保留“本镜场景”和一句空间概述；场景一致靠场景底图参考 | K-PRM-Q28 |
| A8 | 系统后缀含质量助推词（焦点锐利、皮肤纹理清晰、微反差强）（QL13） | 80/80 条作业命中 | 不改生产，等 A/B（qa_suffix）；后缀是项目方选的 S★，改动要项目方或总调度批 | K-REN-Q27 |

## B. 写作方 lint（交 ITERAUDIT：tools/qa/writer_lints.py，tests/test_writer_lints.py）

现有 QW-W1–W4 之后新增四条，都是 warn 级；写作链路设为 block，进返修环。判定逻辑可直接复用 tools/bakeoff/qwen21_lint.py 里 owner="writer" 的部分。

| 提案 | 规则 | 判定 | 依据 |
|---|---|---|---|
| QW-W5 | 特写 / 近景 / 中近景的 img 不写鞋、跟、裙摆、腿、脚、地面上的鞋尖 | img 景别 ∈ 近景档 且 含（鞋 / 跟 / 裙摆 / 腿 / 脚 / 鞋尖） | K-PRM-Q22；QL01 × Q3：29% vs 6% |
| QW-W6 | img 不写否定句（不… / 无… / 不是… / 别…），写要的样子 | 正则同 qwen21_lint.NEG | K-PRM-Q24；QL03 × Q2：24% vs 4% |
| QW-W7 | 两人同框时，“两人都露脸”和“一人前景虚化 / 背影 / 局部”二选一 | 同 QL06 | K-PRM-Q25；QL06 × Q1：83% vs 49% |
| QW-W8 | 局部特写（只拍手 / 脚 / 器物）的 img 不写脸、肩、胸、锁骨、发 | 同 QL02 的写作方部分 | K-PRM-Q23；9/9 Q1 不过 |

写作方说明已写进 knowledge/rules/render_qwen21.yaml 的 K-WRT-Q29，compile 后会进 config/recipes/writer_knowledge.md。

## C. GPU A/B 待跑清单（tools/bakeoff/run.py，等首帧全部出完或用让道模式；结果按契约分比）

| 组 | 改动 | 能否提交 |
|---|---|---|
| qa_native | 1536×2752 原生 9:16 | 可以（preflight 过） |
| qa_lora0 | 去掉 krea2 LoRA | 可以 |
| qa_imgtag | <imageN> 写法 | 要等 A4（preflight I6 认 <imageN>） |
| qa_suffix | 后缀去助推词、改写具体光线 | 要等 preflight I7 允许 scope=bakeoff 换后缀 |
| qa_all | 以上合并 | 同上 |

跑法：`python tools/bakeoff/run.py start --models=qa_native,qa_lora0 --modes=contract`，对照组是同镜同种子的 qwen21_sstar 契约组。
