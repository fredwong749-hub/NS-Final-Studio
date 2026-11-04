# 第 1 集复盘（series10_v2）

<!-- retro_status: done --> <!-- done_by: retro_auto -->
<!-- retro_sig: c1c17b371deae2b4 -->
> 生成：2026-11-04 08:01，tools/master/episode_retro.py。总调度勾完第 4 节后跑 `episode_retro.py done --run series10_v2 --episode 1`；没 done 之前第 2 集不能进“出图”（sop_gate）。
> 本集当前 SOP 阶段：完成（九个阶段都有通过证据）

## 1. 指标（和上一集对比）

```
series10_v2 ep01  镜头 11
agent 调用：写手 0（作废 0）/ 评审 0 / 评委 0 {}；本地 VLM≈85
介入：19（手工命令 0，退稿 12，修后重排 7，手起 API 0，手工挂道 0）；卡点 0（阻断 0）
时间：P1 2.71h，P2→导入 Noneh，阶段 A Noneh（in_progress），阶段 B 11.7h（done），项目方等待 1549min
出图：51 张候选，通过 12（0.2353），每张通过图 4.25 次；preflight 挡掉 21 次
自动化 0.5217（{'system': 36, 'owner': 10, 'agent': 23}）；GPU 占用 0.0；好莱坞分 None
§1.3 头条：自动化率 1.0（0/9 个对象有人工）；人工介入 0；GPU None；好莱坞中位 None（n=0）；一次过 首帧 1.0 / 尾帧 None / 视频 None；卡点 0（未关 0）
空缺 12 项（见 nulls[]）
```

### PLAN §1.3 头条（第1集）

| 指标 | 第0集 | 第1集 | 对比 | §1.3 目标 |
|---|---|---|---|---|
| 自动化率 | — | 1.0 | — | >= 0.6 ✅ |
| 人工介入次数 | — | 0 | — | <= 20 ✅ |
| GPU 占用 | — | — | — | >= 0.4 |
| 好莱坞分中位数 | — | — | — | — |
| 首帧一次过率 | — | 1.0 | — | — |
| 尾帧一次过率 | — | — | — | — |
| 视频一次过率 | — | — | — | — |
| 卡点数 | — | 0 | — | — |

（第 1 集，没有上一集可比）

## 2. 本集卡点：怎么修、是否写进 SOP 和代码

本集没有登记卡点。

### 下一集前必做（修法没进 SOP / 代码的卡点）

无：本集卡点的修法都已进 SOP 或代码。

## 3. 本集新增 / 改动的规则（config、knowledge、SOP）

窗口：本集开工 2026-11-02 19:10:55 起（git log --since + 未提交改动）。

- 已进版本 0 个：无
- 未提交 0 个：无

## 4. 记忆 / harness 更新清单（总调度勾选）

- [ ] MEMORY.md 现行骨架：本集新学到的事写进对应记忆文件（不新开重复文件）
- [ ] OWNER_CANON：本集项目方有没有新的重复要求 → 补定律或补“违反”计数
- [ ] PIPELINE_SOP_V2.md：本集每个卡点都写进对应步骤的“前置条件 / 卡过的地方”
- [ ] episode_ready / sop_gate：本集卡点里能自动查的，已做成检查（下一集开工前自动拦）
- [ ] master_check：本集新决策涉及的开关已进 SWITCH_EXPECT（带决策号）
- [ ] config/pipeline/sop_gate.json：observe_stages 是否可以收紧为 enforce
- [ ] 下一集开工前跑 episode_ready + sop_gate status，缺的一次性补齐

## 5. 记忆候选（给总调度写 memory；这里不写记忆文件）

- 第1集 §1.3 头条：自动化率 1.0、人工介入 0 次、GPU 占用 None、好莱坞中位 None。
- 第1集复盘由常驻 retro_tick 自动生成（W24），数据源缺的项见指标 nulls[]。
- 第1集复盘由常驻 retro_tick 自动生成（W24），数据源缺的项见指标 nulls[]。

## 6. harness 变更建议（阈值 / 规则文件 + 建议值；不自动改）

- `config/pipeline/hollywood_score.json` require_idle：本集没有好莱坞分 → 建议给 hollywood_tick 每集预留至少一段空闲窗，或 require_idle=false 跑一轮补分
