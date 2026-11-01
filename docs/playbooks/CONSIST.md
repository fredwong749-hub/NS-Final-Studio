# 角色手册：CONSIST 人物一致性

- **负责连接**：P4-P5（Spec → 资产）、P5-P6（资产 → 首帧）、P10-P11（身份闸门）
- **现在由谁做**：出候选和排序是代码；挑哪一张由项目方定（characters 闸门）；出片后的身份检查是代码，并接入规则 R-ID 和审片判定。

## 输入
- 人物表：中文外貌句、EN 外貌短语、VOICE。
- 项目方给的设定图工作流：`data/ab/owner_workflows/aisley_char_sheet`。

## 输出
- 四栏设定图候选，放在 `data/ab/char_sheets/<id>/`。
- 身份图登记：`data/assets/identity_refs/manifest.json`（by=owner）。其中脸部裁切图供 Ref2VA 用。
- 身份度量报告（ArcFace）。

## 步骤
1. 缺身份参考的角色，Autopilot 在 P4-P5 自动列出，并给出命令：`.venv/Scripts/python.exe tools/ab/char_sheet_qi21.py sheets --only <id> --seeds 101,202`。
2. 在 gpu36 上排序：`/root/work/fredw/venv_idm/bin/python identity_metric.py --ref <id>=<参考> --out out/<id>_rank c0=… c1=…`。排序会检查两点：对参考的余弦，以及和同性别其他角色的区分度（两人互相余弦要 <0.5）。
3. 项目方在资产页挑定，登记成身份图。之后系统会自动发现：`spec_import.identity_ref` 优先读 manifest。
4. 首帧改用设定图作参考出图（K-AST-R01）。Ref2VA 用脸部裁切图，不用整张定妆图（K-AST-R03），因为整张图会把服装带进画面。
5. 出片后的身份闸门：
   - review.py 的 SFace 中位 ≥0.30；
   - ArcFace 按参考归属判人，≥0.50 / 0.30 两档。
   - 不过时走 R-ID 阶梯：换种子 → Ref2VA → 交项目方换参考。

## 判定标准
- ArcFace 余弦 ≥0.5 可认作同一人，0.3–0.5 只算相像。
- 男角色彼此之间要区分得开（K-WRT-R04、K-REV-R02）。

## 资产参考锁定（REFLOCK 2026-11-01，契约 docs/GEN_CONTRACT.md I2–I5、I9）
项目方原话：“你要在 image 里面让它知道，这个女孩要穿这个鞋子、穿这个衣服、戴这个饰品等等，然后才能锁定一致性。”
1. **出图必须引用造型与单品资产图**（K-AST-230）。每镜参考图由 `services/agent/ns_agent/asset_refs.py` 解析，不由各工具手拼：
   身份脸（脸可见时）> 本镜造型设定图（特写 / 近景取半身栏，中景及更远取正面全身栏，一律去头，K-AST-233）> 景别可见单品（K-REN-101 可见性；鞋可见时鞋最先；局部特写只取该局部）> 场景。
2. 单品图来源：衣橱产品图（`config/recipes/asset_refs.json` item_map + 资产中心覆盖 `data/looks/item_map_overrides.json`）> 设定图裁切（标“仅设定图”，提示补产品图）> 都没有 = **资产缺图，阻断出图**（不得用文字代替）。
3. 槽位规划（K-REN-130）：Qwen-Image 2.1 / Edit 2511 = 3 槽，Klein = 4 槽（`config/recipes/asset_refs.json` models）；超槽时同一角色的设定图 + 单品拼成参考板（固定网格 + ①② 标注），提示词逐一写“图N是…必须完全一致（款式、颜色、材质、细节）”。双人镜只给主体角色脸参考，第二人用其造型设定图（去头）；两张脸不得同槽（preflight I9 挡）。
4. 角色锁（身份描述）不写服装（K-AST-232）：资产模式下编译前去掉“黑色高定衬衫 / 休闲装”之类分句，服装只由本镜造型锁定。
5. 剧本 / 造型审计（K-AST-231）：`tools/gen_contract/look_audit.py --write` → 每镜每人的造型 id 登记 `<run>/assets/shot_looks.json`（解析器优先读）、内容层问题 `look_revision_requests.json`；`tools/gen_contract/look_revise.py` 交写作模型（关推理，台词不动）出修订提案，导入走正式导入流程。
6. 提交闸：`from ns_agent.gen_contract import preflight; preflight("image", req)`，不过就拒交（tools/pipeline/submit_jobs.py 已接，无绕过开关）；出图后 `postflight("image", {...})`，远端测量 `tools/gen_contract/remote_score.py`。
7. 验证与审阅页：`tools/gen_contract/reflock_validate.py`（有 / 无资产参考对照）、`tools/gen_contract/reflock_page.py` → `data/review_pages/asset_reflock/index.html`。
8. **手部局部特写（W5，总调度 11-01，ep05-S3/S5 驳回 8 次）**：手部单品用设定图裁切时只取两只手（`asset_refs._hand_pair`，`*_hand2.png`），躯干占宽 > 0.35 的手部参考不送（K-AST-V10）；正文同时写到肩 / 颈 / 锁骨 / 胸时局部范围为“手与肩颈”，构图句随之改，角色锁保留发色句，参考槽仍只送手部单品（K-REN-V11）；写作方 P4 lint QW-W10 提示把肩颈动作挪到下一镜或改写成近景（K-WRT-V10）。⤴ 取代 REFLOCK 11-01“局部特写角色锁只留局部分句、发色一并去掉”的旧做法（肩颈入画时）。

## 产生的规则放在哪里
`knowledge/rules/asset_ops.yaml`、`research.yaml` 的 K-AST-*（link P4-P5 / P5-P6），以及 K-REV-*（link P10-P11）；资产参考锁定与生成契约阈值：`knowledge/rules/gen_contract.yaml`（K-AST-230..233、K-REN-130、K-REV-230、K-REV-231、K-REN-131）。

## 什么时候需要人
- 造型部件与衣橱单品对不上（例：造型 B 束腰 vs 衣橱 LW-O10 款式不同）：项目方定以哪个为准；
- characters 闸门：挑身份图；
- 同性别角色外貌字段区分度不够（写作方 / 项目方闸门）。
