# 剧本镜头 → 首帧/尾帧生图：读懂与改进方案（Frame Spec Compiler）

> 2026-10-30，项目方要求：“剧本很多镜头的提示词如何在 image 生图，要读懂细节，在这个基础上做得更好”。本文基于通读 `script play lib/为他而骚 （剧本和镜头）v2.md`（ep01、ep06、ep07、ep23、ep24 等）和 `为他而骚（image提示词） v2.md` 的 AGENT-0/1/2 规则写成。gpu3 出片按本文实现；fredw-d9 的 `ns_agent.compiler` 可共用同一份结构。

## 1. 剧本镜头文字的特点（为什么不能直接丢给 image 模型）

剧本的 `img` 行是**导演写给人看的分镜语言**，不是一张静态图的描述。逐条看到的问题：

| 现象 | 例子 | 对生图的影响 |
|---|---|---|
| 一行里有**时间过程** | ep23 S2「低头（惊悸）→咬唇定住（决意）→抬下巴（骄傲）」；ep06 S4「她一遍遍擦掉重画…最后一次」 | 一张图只能是一个瞬间。首帧取**起始状态**，尾帧取**结束状态**，中间交给 H3 |
| 写了**心理/比喻** | 「三层心理打架的脸」「像时尚大片」「领奖的姿势」 | 要翻成**看得见的**表情、姿态、构图，比喻本身不进提示词 |
| 写了**声音** | 「金属声收进布料里」「铁珠在裙内疯狂作响」 | 图里不画声音；声音进 H3 的 soundscape |
| **人物用代称** | 「蓝发齐刘海女性」「她」「他」「男性驾驶侧脸」 | 必须解析成角色（林晚/顾沉/陈宇…）并带上该角色的外观锁 |
| **跨镜/跨集指代** | 「同一条巷子，另一个黄昏」「比重逢第一次更慢」 | 需要**场景锁**（同一条巷 = 同一张场景参考图）和连续性 |
| **服装/首饰/妆容不在本镜写全** | ep06 起妆容变化、ep21 起全套珠链，本镜只写「她」 | 必须按**集数**补：装饰码 D0–D10、造型排期（妆容/服装/鞋/美甲） |
| **镜头运动写在 motion 行** | 「camera push in 极近」「static 中景」「handheld follow」 | 首帧景别 = 运动起点；push in 的尾帧更紧；follow 的首帧是背后中景 |
| **特殊画面手法** | 双重曝光（ep07 S2）、镜中半素颜半浓妆（ep06 S1）、剪影（ep23 S4）、倒影、延时 | 单次生图做不好，要用**专门配方**（合成/局部重绘/两张叠化） |
| **人数与可见性** | 「十米外虚化剪影」「男性驾驶侧脸的轮廓」 | 要写清每个人的**清晰度/虚实**和占画面比例，否则模型把背景人画成主角 |
| 全局规则散在头部 | 角色锁、统一后缀（色调/f1.2/无字幕）、基础负面、LoRA 触发词、美甲、5mm 珠、4+1+4 环 | 每镜都要按顺序拼进去，且 Turbo/cfg1 下**负面词无效**，必须改写成正面约束 |

## 2. 方案：先“读懂”成结构化 Frame Spec，再按模型“写”提示词

```
剧本镜头文字 ──► ① 解析（确定性）──► ② 读懂（本地 LLM，只重组不创作）──► Frame Spec JSON
                                                                         │
             ③ 校验（每个原文名词/数字都要落到 spec 里；不得新增剧情）◄──┘
                                                                         │
       ④ 按模型渲染提示词（Qwen 2.1 / Klein / NoctQ）+ 参考图分配 ──► ⑤ 多轮出图打分修图 ──► 首帧/尾帧定稿 ──► H3 FL2VA
```

### ① 确定性解析
- 每镜：img、motion、sound、对白（说话人+原文）、🎙、负面追加、镜头标签（收尾镜/核心名场面）、LoRA 触发词。
- 每集：装饰码（数据B）、造型排期（data/looks：妆容/服装/鞋/美甲，审阅前不注入）、场景锁候选。
- 全局：角色锁（含美甲）、统一后缀、基础负面、珠/环规格说明。

### ② 本地 LLM 读懂（Qwen 27B 本地，禁止外发）
输入原文，输出 **Frame Spec**，规则是**只重组、不加戏**：

```json
{
  "shot": "ep23_S3",
  "subjects": [
    {"char": "lin_wan", "clarity": "主体锐利", "screen_share": "画面下2/3",
     "pose": "站在路灯正下，双手向两侧分开风衣下摆", "facing": "正面", "expression_start": "下巴微收、眼神躲闪",
     "expression_end": "下巴抬起、直视远方", "visible_body": ["大腿中段以下", "腰腹"],
     "wardrobe": ["黑色漆皮长风衣（下摆分开）", "超短裙", "黑色漆皮string丁字裤"],
     "adornment": ["阴环4+1+4，每环一颗5mm黑铁球（D6）"], "heels": "12cm侧开透明细高跟", "nails": "5cm透明钻甲（手可见）"}
  ],
  "others": [],
  "framing": {"size": "中景（大腿中段至头顶）", "angle": "平视", "lens": "85mm f/1.2"},
  "scene": {"lock": "SK-ALLEY", "time": "黄昏", "light": "钠灯路灯正上方暖黄顶光+冷色天光"},
  "props": [],
  "first_frame": "风衣刚被分开一半，铁珠刚显现",
  "last_frame": "风衣完全分开，下巴抬起直视远方，定格",
  "special": null,
  "camera_motion": "slow motion，机位固定",
  "not_in_image": ["金属碰撞声", "像时尚大片（转为：时尚大片式布光与构图）"],
  "must_have": ["九枚环", "九颗5mm黑球", "透明高跟", "漆皮风衣反光", "背景虚化", "无字幕"]
}
```

- **代称消解**：「她」→ 本集主角；「他」按集内上下文（顾沉/陈宇/路人）；未命名的男性 = 「成年男性路人」，外观只用原文给的（剪影/叼烟）。
- **起止状态**：把 motion 的时间线拆成 `first_frame` / `last_frame` 两个瞬间。
- **心理→可见**：比喻翻成表情、姿势、构图描述，原比喻进 `not_in_image`。
- **补全按集状态**：装饰码、妆容、鞋、美甲按集数/镜头可见部位补入（美甲只在手/脚入镜时）。
- **镜头**：景别、机位、焦段由 motion 推出；push in 的尾帧景别更紧。

### ③ 校验（确定性）
- 原文里的每个**名词、数字、颜色**（九、5毫米、12cm、漆皮、路灯…）必须出现在 spec；缺失即报错重跑。
- spec 里不得出现原文没有的人物、道具、事件（白名单：角色锁、装饰码、造型排期、全局风格）。
- 记录 LLM 版本与输入哈希，可复现。

### ④ 按模型写提示词
**Qwen-Image 2.1 / NoctQ（中文长句效果最好）**——固定顺序，一段话：
1. 镜头与画面质感（先写）：「竖构图9:16，中景，平视，85mm f/1.2 大光圈，主体锐利，背景奶油般虚化…浓郁暖色电影调色」
2. 主体身份（角色锁 + 参考图角色说明）：「图1是林晚的脸部身份参考…」
3. 姿势/朝向/表情（起始或结束状态）
4. 服装 → 首饰（数量、位置写死）→ 鞋 → 美甲
5. 场景与光线（场景锁参考图「图3是场景参考」）
6. 其他人物（虚实、比例、只给原文外观）
7. 正面化的约束（替代负面词）：「画面中只有一人；没有任何文字字幕；手指五根…」
- 参考图 ≤4 张（Qwen）/ ≤3（Klein），每张写明作用：脸部身份 / 造型 / 场景 / 道具；脸先缩到 768²，单品 512–768。
- LoRA：按触发词加载对应 LoRA（存在才加）。
- 分辨率：按 9:16 生成高一档（如 1088×1920）再缩到视频尺寸，细节更足。

**Klein**：英文短句 + 参考图，作为构图/局部编辑的备选。

### ⑤ 多轮出图打分修图（已在 gpu3 实施）
清单 = spec.must_have + subjects 的全部字段 → 每轮 2–4 张 → VLM 逐项打分 + 确定性检查（人脸相似度、背景虚化、色彩、文字）→ 定点修改（局部重绘首饰/手/服装；重出构图；难镜头走 Blender+ControlNet）→ 最多约 4 轮。尾帧以首帧为参考做编辑，保持一致。

## 3. 特殊手法配方

| 手法 | 配方 |
|---|---|
| 双重曝光（ep07 S2） | 分别生成两张（陈宇之吻 / 顾沉之吻），按原文构图叠化合成为首帧；H3 只做轻微运动 |
| 镜中半素颜半浓妆（ep06 S1） | 先出完整镜中脸，再对半张脸做妆容局部重绘（M1 素颜 ↔ M4 浓妆） |
| 剪影（ep23 S4） | 逆光剪影提示 + 「人物无面部细节」正面约束；不加人脸参考 |
| 倒影/玻璃映像（ep01 S5） | 主体背影 + 玻璃中模糊倒影，倒影区域单独局部重绘 |
| 延时/多次重复（ep06 S4） | 首帧 = 第一次，尾帧 = 最后一次结果；中间靠 H3 |
| 远处路人虚化 | 写明「十米外、画面占比约1/10、焦外虚化剪影」并在打分里检查不被画成主体 |
| 手/脚特写（美甲、高跟） | 高分辨率裁切局部重绘，五指检查 |

## 4. 场景锁与连续性
- 同一场景（电梯、写字楼大堂、出租屋、顾沉家卧室、小巷…）先出一张**场景母版**（AnyAngle/多机位可选），之后所有该场景镜头把母版作为「场景参考图」。
- 每集出完写 continuity ledger（装饰/妆容/服装/道具），下一集开工前 diff。

## 5. 分工
- gpu3（Claude 侧）：②–⑤ 全部实现于出片程序，产物与 spec/清单/每轮分数写入 `data/renders_gpu3`。
- fredw-d9：画布显示 spec 与清单、允许人工改 spec 后重渲；`ns_agent.compiler` 可直接读取同一份 spec 格式。

## 6. gpu3 渲染字段（T08，2026-10-30，只增字段，提示词不变）

格式 `packages/schema/ns_schema/frame_spec.py`，编译 `services/agent/ns_agent/frame_spec.py::build_spec(..., timeline_shot=...)`，
测试 `tests/test_t08_frame_spec.py`。全剧统计：`uv run python -m ns_agent.frame_spec stats`。
规则版里 `qwen` / `qwen_last` / `facts` / 角色 / 校验结果与 T06 金标准逐字相同（360 镜，带时间线和不带时间线都一样）。
所有启发式结果都标 `*_source`：`text` = 原文写了，`guess` = 规则默认，`same` = 尾帧沿用首帧，`none` = 不适用。

**镜头级**

| 字段 | 含义 / 规则 |
|---|---|
| `focus_part` | 焦点部位：`eye` `lips` `hand` `nails` `shoes` `foot` `face` `legs` `back` `torso` `screen` `object` `other`；`""` = 中景/全景，没有单一焦点。原先的 `foot` 拆成 `shoes`（高跟/鞋）和 `foot`（脚/脚趾）；“手机”不再算 `hand`，“背景”不再算 `back` |
| `focus_label` / `focus_object` | 中文标签（眼睛/嘴唇/手/美甲/高跟鞋/脚/脸/腿/背/身体/屏幕/物件词）；焦点是鞋、屏幕、物件时 `focus_object` 是原文词 |
| `focus_part_source` | `text`：同一分句写了“特写X / X特写 / 手部特写 / 镜头推向X / 焦点落在X”；`guess`：特写/近景镜头取第一个描述分句里的部位；`none` |
| `framing` / `framing_source` | 直接取 `data/state_timeline.json` 的 `framing`（extreme_close / close / medium / full）；没有时间线时用同一函数（`gpu3_fields.shot_framing`）现算 |
| `faces_visible` / `faces_visible_source` | 同上，取时间线 `faces_visible` |
| `prop_states[]` | 时间线 `props` 原样：`id` `name` `state` `state_end`（worn/hanging/held/on_table）+ 各自 `*_source`、`holder`、`mention`、`trigger`、`trigger_conflict` |
| `timeline_inputs_sha` | 用到的时间线条目的 `inputs_sha`；`null` = 没读时间线（字段为现算） |
| `risks[]` | `far_small_face`（全景且脸入镜，SOP §8 H3 小脸弱点）/ `trigger_conflict`（触发词会画成穿着，但 state≠worn）/ `wardrobe_change`（镜内换装，尾帧按 `items_end`） |
| `expression_stripped[]` | 表情清洗去掉的片段（`位置：片段｜原因`），审计用 |

**每个角色（`characters[]`）**

| 字段 | 含义 / 规则 |
|---|---|
| `gaze_start` / `gaze_end` | `{target, at, cue, source}`。`target`：`camera` 看镜头 · `other` 看另一角色（`at` = 角色 id）· `down` 低头 · `up` 抬眼/仰头 · `away` 看别处/背对 · `object` 看物件（`at` = 原文物件词）· `closed` 闭眼 · `unknown`（路人）。首帧 = img + motion 起点里**最早**的线索，尾帧 = motion 终态里**最后**的线索（没有 → 沿用首帧，`source: same`） |
| 视线线索 | 看向镜头/对着镜头/直视（后面不是人）→ camera；看向他/看着她/望着他/目光落在她/迎着他的视线/对视/对望/目光交汇 → other；低头/垂眼/俯视 → down；抬眼/抬头/仰头/望着天花板 → up；看向窗外/别过脸/转过头/出神/背影/背对/看向画外 → away；看着手机/盯着屏幕/看了一眼X → object；闭眼 → closed；侧脸 → 有另一人 other，否则 away（都标 guess）。主语按 `gpu3_fields.who`（“X的” > 分句里最近的人名/代词 > 林晚） |
| 没写视线时（guess） | 脸不可见 → away；有另一人入镜 → 看对方；屏幕镜头 → 看屏幕；否则 away（不看镜头） |
| `screen_share_value` / `screen_share_source` | 0–1。主角（原文最先提到、非焦外）= 景别表（大特写 0.9、特写 0.7、近景 0.5、中近景 0.45、中景 0.4、全景 0.2、远景 0.1）；次要人物 ×0.6；焦外 0.1；原文写了“占满画面 / 三分之二”→ `text`。`screen_share` 文本保留旧格式（次要人物改为 “0.24（次要人物）”） |
| `screen_position` | 原文位置词：left / right / center / foreground / background / top / bottom |
| `face_visible` | 该角色是否在 `faces_visible` 里 |
| `changes_within_shot` / `items_end` / `visibility_end` | 时间线原样（docs/state_timeline.md §七.2） |
| `expression.start/end` | **只放表情词**。规则版的表情词要带上下文才算（“湿透的衬衫”不再是睫毛湿润，“抿了一口汤”不再是抿唇，“环咬着”不再是咬唇；新增 咬牙、耳根泛红、皱眉、眼神迷离、发愣 等）。`sanitize_expression` 按顺序去掉含服装（clothing）、运镜（camera）、视线（gaze）、动作（action）词的片段，剩下不含表情词的也去掉（not_expression）；LLM 补全后同样清洗，`validate` 发现残留会报“表情含非表情词” |

gpu3 读法：`FrameSpec.model_validate(json)`；优先看 `focus_part` + `focus_label`、每角色 `gaze_start/gaze_end.target`、
`screen_share_value`、`expression.start/end`；`*_source == "guess"` 的字段可以被出片侧的 VLM / 人工覆盖。
