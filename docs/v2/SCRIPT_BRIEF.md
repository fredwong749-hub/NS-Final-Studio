# V2 剧本任务书（总调度 fredw-2b，11-02 18:4x；L-125）

项目方点选：第一季剧本也从头写（v3 规则 + 今天的新规则），V2 run = series10_v2，全新目录，不继承 V1 的任何稿子。

## ⤴ 18:5x 作废说明
项目方要求完全切割：V1 的方向文件、人物、身份脸、画风偏好都不带进 V2。本任务书下面的“输入”一节作废，等项目方给出 V2 新方向后重写。只保留写作的技术规则（v3 格式、lint、闸门）。

## （作废）输入
- 项目方方向：data/pipeline/runs/series10_v1/owner_direction.md、P0_brief.json、hard_constraints.md（全部是成年人、自愿、虚构人物；亲密镜只在本地生成）
- 人物：林晚、顾沉、陈宇、阿岚（人物设定可以由写作重新打磨；林晚长相锚点 = L-122 身份脸，雾霾天蓝、及腰长直发）
- 写作规则：knowledge/rules/writer*.yaml 和 config/recipes/writer_knowledge.md（v3：H17–H25 场景定稿行；K-WRT-211 / 212；QW-W13 写局部就不能写会露脸的动作；QW-W14 两人以上在画时不写倒影；手部动作 ≤ 2 拍；背影 / 远景写明景深）
- 运镜词表：config/camera_moves.yaml（L-107）；镜数 ≤ ⌈总时长 ÷ 6⌉；每集 60–120 秒（L-092）

## 流程（每步过闸）
1. P1 故事线（十集弧线 + 人物 + 造型表：每个人物几套造型、每套服装 / 鞋 / 饰品）→ 交总调度 → 交项目方看（一次）
2. P2 分集大纲（场景、节拍、亲密标记、scene_type 戏的性质）
3. P3 剧本 → P4 分镜（cast 写清露脸 / 局部 / 背影、站位行、场景定稿行、造型排期）
4. 闸门：writer lint 0 命中 + rubric gate + FACTCHECK + 盲评 3 评委
5. 导入 series10_v2，走 autoflow；不许引用旧剧文档（A-08）

## 写作分工
测试期由 Claude 写作 agent 写（L-109）：HOLLYWOOD 牵头，SCRIPTWRITER（Fable）执行。总调度只核对技术契约，不改写内容。
## 金样
ep01 写完后先从中挑 3 镜（单人特写、双人中景、背影或远景）作为金样镜，交 PROMPTFIX 走全流程。
