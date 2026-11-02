# TODO_BOARD：全量待办（AUDIT-M 维护，每轮更新）

- 本版：11-02 17:4x，第 3 版。按总调度 17:4x 的要求重排：第一屏是评分卡，第二屏是冲刺。
- 每条待办都挂在某一项分数下（S1–S7）。挂不上的已经归类，或者关掉。
- 来源：
  - docs/master/SCORECARD.md
  - docs/master/ALIGNMENT.md §3
  - FOCUS_PLAN_20261102.md
  - MASTER_PICTURE §1
  - AUDIT-M 审计（A-xx）
- 分数取自 data/rsi/scores.jsonl 每条线的最后一条记录。
- 状态：✅ 完成，🔶 进行中，⏳ 未开始，⛔ 阻塞，✖ 关闭。

---

## 第一屏：评分卡（7 项都要到 100）

| 项 | 现分（出处） | 差哪些分项 | 挂在下面的待办 | 负责 | 下一轮 |
|---|---|---|---|---|---|
| S1 出图 | 68.1（image，03:56，已过时） | identity 11.76、hands 12.11、pose 13.14、gaze 7.33、pass_speed 10.12；身份和视线差得最多 | 冲刺①②；F1；A-01 A-02 A-03 A-05 A-13；L-110 L-111 L-118 L-122；A/B 实测 | PROMPTFIX + VQAGATE + DETECT-S | sv-14 上线后重算；按集顺序补图 |
| S2 视频 | 72.5（video，没有时间戳） | 视频 43/102，成片 0/10（FOCUS §1，15:5x）；分项没落库 | 冲刺⑤；F5 F6；A-15；L-088 L-084 L-081 L-124；CUTEDIT | DEBUG-RSI + ASSEMBLY + CUTEDIT | ep01 → ep10 按 L-124 推进 |
| S3 剧本 | 93.1（script，14:44） | script 34.1/35；automation 4/5 | L-096 L-097 L-104 L-108 L-109；A-08 | HOLLYWOOD + SCRIPTWRITER | lint 命中改写；ep06–10 收尾 |
| S4 UI | 没算（线 4 指标见 RSI_PROGRAM） | 指标没落库 | 冲刺③；F7 F8 F9；A-10；L-113–L-117 L-120 L-123；NAVIA、POSTER、IMGEDIT | NAVIA + ASSETUX + UISCRIPT + POSTER | 顶栏三轮自迭代；编辑器重做 |
| S5 工作流 | 没算（新） | 指标没落库 | F2；A-09 A-12；L-121 L-124 L-099 L-102 | DEBUG-RSI + FACTORY | sv-14 护栏；E30 排序 |
| S6 GPU 管理 | 没算（新） | 指标没落库 | 冲刺④；F1 F3 F4；A-06 A-07 A-15；L-100 L-105 L-106 | FACTORY + NETFIX + SENTINEL | gpu33 命令超时根治；分区唯一来源 |
| S7 代码 | 56.8（system，13:31） | self_run 35.3、structure 29.8、no_claude 62.5、release 66.7（rule_coverage 100） | A-01…A-15；F10；旧数据隔离；漂移探针归零 | AUDIT-M + FACTORY + 各负责方 | sv-14；A-01…A-10 逐条关 |

S4、S5、S6 要先有计分代码，并由 SENTINEL 每 20 分钟落库，否则没法判断到没到 100。这条挂 S7，负责 SENTINEL，状态 ⏳。

---

## 第二屏：两小时冲刺（ALIGNMENT §3，17:1x → 19:1x）

| # | 时间 | 事项 | 分数 | 负责 | 完成标准 | 状态 | 阻塞 / 关联 |
|---|---|---|---|---|---|---|---|
| ① | 17:1x–18:00 | 第 2–6 步：送脸、服装绑定、站位、种子流、两台编译一致 | S1 | PROMPTFIX | 编译测试全过；ep01 每镜 compile_trace 两台 sha 一致；能检出“不露脸”矛盾 | 🔶 | A-01 ②–⑤；A-07（sha 一致的前提是两台跑同一份代码） |
| ② | 17:1x–18:00 | 第 8 步验收入口：身份、服装、提示词、人数手数，出标签，作为闸门 | S1 | VQAGATE + DETECT-S | ep01 的 18 张帧自动出标签；回归集全对 | 🔶 | A-02、A-03、A-05 |
| ③ | 17:1x–18:00 | 第 9 步：只显示通过的图；“修改”立即收下 | S4 | ASSETUX | 测试 + 截图 | 🔶 | A-10 |
| ④ | 18:00–18:30 | cut sv-14，部署两台 | S6 / S7 | FACTORY + 总调度 | sha 一致，停派 ≤ 2 分钟 | ⏳ | 要带上：F18 remote_score、DEBUG-RSI 的 A-02 修复、AUDIT-M 改的 4 个文件 |
| ⑤ | 18:30–19:1x | 按集顺序出图：先 ep01，补缺图和尽力版；验收通过后出视频 | S1 / S2 | DEBUG-RSI + FACTORY | ep01 首尾帧全过，视频开出 | ⏳ | 林晚按镜暂停到 19:23 |

---

## 第三屏：功能线（新）

| 线 | 分数 | 负责 | 做了什么 | 还差什么 | 完成标准 | 状态 |
|---|---|---|---|---|---|---|
| CUTEDIT 成片剪辑器 | S2 | CUTEDIT | 未核实：docs 里还没有文档 | 设计和实现：裁切、换 BGM、导出定稿 | 10 集成片都能在界面里剪完并导出 | ⏳ |
| POSTER 海报 | S4 | POSTER | 未核实：docs 里还没有文档 | 设计和实现 | 总调度定 | ⏳ |
| NAVIA 信息架构 | S4 | NAVIA | 未核实 | 顶栏 7 个一级入口；深链接；没有空白页 | 达到 SCORECARD S4 的标准 | 🔶 |
| IMGEDIT 图像编辑器（L-115 / L-117 / L-120） | S4 / S1 | ASSETUX + IMGLAB | docs/research/imgedit/DEEP_RESEARCH.md、UIUX_BRIEF.md、AB_PLAN_R1.md | 并入资产页；提示词走 L-119 改写；只留“用这张”和“修改”（L-123） | 契约逐项表 + 截图 | 🔶 |
| A/B 实测 | S1 | IMGLAB / VIDLAB / VQAGATE | AB_PLAN_R1.md | 新配方、新运镜都先 A/B 再启用（L-107） | 结论写进 scores.jsonl 和规则 | 🔶 |

---

## 第四屏：FOCUS 十条

| # | 待办 | 分数 | 负责 | 做了什么（出处） | 还差什么 | 完成标准 | 状态 |
|---|---|---|---|---|---|---|---|
| F1 | 打分 / 看图吞吐 | S1 / S6 | FACTORY + VQAGATE | gpu33 常驻 CLIP 8872 已起（17:0x，PID 1187649）；F17 限线程 | 看图扩容；A-02；A-03 | 连续 1 小时不因等打分空转；积压 < 5 | 🔶 |
| F2 | 重出硬上限 | S5 | DEBUG-RSI | E28 上线，24 小时最多 10 版（retry.yaml） | A-09：时间串不带时区 | 24 小时内单镜单阶段 ≤ 10 | 🔶 |
| F3 | 部署不停产 | S6 | FACTORY | sv-13 停派 17 s / 106 s（deploy_sv-20261102-13_164841.json） | 推送没有限速 | 停派 ≤ 2 分钟，隧道不掉 | 🔶 |
| F4 | 命令通道 ≥ 99% | S6 | NETFIX | base-c 已回滚 | 复测；加令牌桶 | rssh 1 小时成功率 ≥ 0.99 | 🔶 |
| F5 | 第一季视频补齐 | S2 | PROD / DEBUG-RSI | 已出 43/102（15:5x） | A-06 ③ 视频分区唯一来源 | 逐集表：还差几条、预计几点完成 | 🔶 |
| F6 | ep01 成片装配 | S2 | DIRECTOR / WORKFLOW | v1 预览 48 秒，4 镜占位 | 合成写死了 music_dir 和主剧剧本 | ep01 成片交总调度亲审 | 🔶 |
| F7 | 系统状态面板简化 | S4 | UIRSI2 | 未核实 | A-10 抽屉过滤 | 截图亲审 | ⏳ |
| F8 | 资产板块重做 | S4 | ASSETUX | path.html | 已并入 IMGEDIT 线 | 同 IMGEDIT | 🔶 |
| F9 | 剧本库页 + 造型卡 | S4 | UIRSI2 | script_library.py 已写，但没进 git | 入库 | 截图亲审 | 🔶 |
| F10 | 收尾卫生 | S7 | 总调度 | 笔记本的 takes.json.* 残留为 0 | 服务器各 20 个残留、仓库根 9 个目录：已并入隔离 | 巡检 0 ❌ | 🔶 |

---

## 第五屏：AUDIT-M 问题清单（A-xx，按 ALIGNMENT 九步归类）

| 编号 | 步骤 | 分数 | 严重度 | 问题（位置） | 负责 | 状态 |
|---|---|---|---|---|---|---|
| A-01 | 5 | S1 / S7 | P0 | **身份脸不止一个来源，旧脸还有残留。**<br>① config faces.lin_wan 已由总调度改成 ar-c2351c9dcf（已修）；<br>② preflight I2 用所有登记脸的并集判断；<br>③ Ref2VA 配方写死旧脸；<br>④ assets.py:201 face_url 读旧 plates；<br>⑤ imggen / imgfix / server_deploy 写死旧脸；<br>⑥ set_face 不同步 manifest，覆盖文件坏时会只写回一条；<br>⑦ gpu33 打分还在跑 imggen 旁路，F18 随 sv-14 | ②–⑤ VQAGATE + PROMPTFIX（按 E29）；⑥ ASSETUX；⑦ FACTORY | 🔶 |
| A-02 | 8 | S1 / S6 | P0 | 打分超时（producer.py:2259）命中 INFRA_PAT，不计次，整张重出 | DEBUG-RSI（进 sv-14） | 🔶 |
| A-03 | 8 | S1 | P1 | 契约结果有两份；sweeper 重复打分。笔记本 1975 个版本中，sweeper 口径下有 1296 个算“未打分” | VQAGATE / CODE-RSI | ⏳ |
| A-04 | 7 | S7 | P1 | takes.json 还有写入口绕开 mutate_takes：_pf_write、_record_look_hash、rescore_takes、pipeline 旧路径 | CODE-RSI | ⏳ |
| A-05 | 8 | S1 | P1 | VQA 闸门读配置失败时放行 | VQAGATE | ⏳ |
| A-06 | 同步 | S6 | P1 | **puller 用的是旧分区快照。** “不归这台”的也 ack 了（gpu33 共 142 次）。锁超时被记成 corrupt（已修）。<br>总调度定：partition.json 为唯一来源，hosts.json 由它生成；具体分法由 FACTORY + DEBUG-RSI 定；“重读分区”和“takes 按 stage 判归属”一起上线 | NETFIX + WORKFLOW + FACTORY + DEBUG-RSI | 🔶 |
| A-07 | 2 / 部署 | S6 / S7 | P1 | **服务器代码不等于 sv 版本。** 漂移：gpu33 2 个文件、gpu36 3 个。原因：dispatch 推代码；resident_prep 在服务器上就地改源码；vidgen 跑在 video10_srv；VQA 跑在 vqa_ab | FACTORY（dispatch 归 NETFIX） | ⏳ |
| A-08 | 1 | S3 | P1 | 导入默认并入旧剧的 image 文档；带 run=s2 导入会覆盖第一季 | FACTORY | ⏳ |
| A-09 | 7 | S5 | P1 | E21 / E28 的时间不带时区；runaway_hold 多部剧共用；restart_queue 会清掉全局暂停 | DEBUG-RSI / WORKFLOW | ⏳ |
| A-10 | 9 | S4 | P2 | 渲染抽屉写死 DEFAULT_RUN，failed 永不过期（43 条里 40 条是重导前的）；edit 显示错（已修）；195 条旧记录已批准隔离 | UIRSI2 / GPUVIEW | 🔶 |
| A-11 | 同步 | S7 | P2 | 仓库根有 9 个脏目录：根因已修，目录已批准隔离 | NETFIX | 🔶 |
| A-12 | 同步 | S5 | P2 | merge_pull 写共享账本不是原子写；push_frames 用 cp -a 覆盖 takes.json；locked / master_gate 以服务器为准 | WORKFLOW / NETFIX | ⏳ |
| A-13 | 8 | S1 | P2 | remote_score 写死 FACE_PROJECT；远端子进程没有 timeout | VQAGATE / FACTORY | ⏳ |
| A-14 | 测试 | S7 | P3 | 4 项测试本来就失败（和本次改动无关）；测试读真实的分区文件 | CODE-RSI | ⏳ |
| A-15 | 7 | S2 / S6 | P1 | **新发现：gpu33 重复出的 ep02/04/06 版本已经成了当前版。** 16:30 之后共 93 个，按 16:3x 快照：<br>· 32 个是 gpu33 那份 takes.json 的当前版；<br>· 22 个是笔记本的当前版，也就是笔记本界面上一部分 ep02/04/06 不是正本 gpu36 的；<br>· 按 K-OPS-W27 判定，81 个应改用 gpu36 的版本，1 个用 gpu33 的（ep04-S6 尾帧），5 个两边都没过 | WORKFLOW（resolve_dup_takes apply，重复清单路径要先参数化） | ⏳ 待总调度定 |

AUDIT-M 已修、还没发版、随 sv-14 走的 4 个文件：

| 文件 | 改了什么 |
|---|---|
| ops/offline/merge_pull.py | 锁超时改为 raise；不再把暂存写到仓库根；MERGE_ONLY_HOST 生效 |
| services/api/ns_api/render_tasks.py | 加 edit→精修 |
| tools/debug/code_drift_probe.py | 去掉混合换行造成的误报 |
| tools/netfix/puller_selftest.py | 改用独立的暂存区 |

另外新增了 tools/qa/audit_quarantine.py。

---

## 第六屏：账本里还没关的决策（MASTER_PICTURE §1）

| 决策 | 分数 | 状态 | 负责 | 还差什么 |
|---|---|---|---|---|
| L-124 按集顺序 | S2 / S5 | ⏳ | DEBUG-RSI + FACTORY | ep01 剩下的镜；E30 排序 |
| L-123 只留正向动作 | S4 | ⏳ | ASSETUX | 全站去掉“不要 / 不选” |
| L-122 新身份脸 | S1 | ⚠ | 总调度 + FACTORY + VQAGATE | A-01 收口；生产打分能用新脸检出 Q1 |
| L-121 第一季唯一主线 | S5 | ⚠ | 总调度 | “第二季暂停”只认一个来源 |
| L-120 / L-117 / L-115 编辑器 | S4 | ⏳ / ⚠ | ASSETUX + IMGLAB | 见 IMGEDIT |
| L-116 待你看 | S4 | ⚠ | FILMUI / UIRSI / VQAGATE | 只放通过验收的图 |
| L-114 / L-113 胶片 UI | S4 | ⚠ | FILMUI / UIRSI | 空闲时做 |
| L-118 / L-111 / L-110 一致性、灯光、融合 | S1 | ⚠ | IMGMASTER / DIRECTOR / VQAGATE | 并入 ALIGNMENT 第 2–8 步 |
| L-112 五条 RSI 线 | S1–S7 | ✖ 已被 SCORECARD 取代 | 各线 | 计分口径以 SCORECARD 为准 |
| L-109 / L-108 / L-107 / L-104 / L-097 / L-096 写作 | S3 | ⚠ | HOLLYWOOD | 照常推进 |
| L-102 系统自跑 | S7 | ⚠ | DISTILL | self_run 35.3 → 100 |
| L-106 / L-105 / L-100 / L-099 / L-099b | S6 | ⚠ | SENTINEL / FACTORY / VQAGATE | A-07 就是 L-099 里的“代码只有一个来源” |
| L-098 全权委托 | — | ✖ 转为工作原则 | 总调度 | 不再单列 |
| L-088 全 Pika | S2 | ⚠ | WORKFLOW | recipe_choice 缺文件时直接失败，不静默回退 |
| L-084 视频代理分辨率 | S2 | ❌ | WORKFLOW | night.py 仍用 540×960 |
| L-081 video_requires_q9 | S2 | ❌ | VQAGATE | 等回扫 |
| L-072 检测器缺 | S1 | ❌ | VQAGATE / DETECT-S | 并入冲刺② |
| L-056 / L-053 | S4 | ❌ | DATAALIGN | 下一轮核实 |
| 未核实：L-003 / L-011 / L-029 / L-042 / L-045 / L-052 / L-055 / L-069 / L-073 / L-077 | S1–S5 | ⚠ | AUDIT-M | 下一轮逐条核实；核实不了的写明理由后关掉 |
| 其余 ⚠：L-008、L-024、L-044、L-047、L-066、L-067、L-070、L-076、L-080、L-082、L-083、L-090–L-094、L-101 | S1–S4 | ⚠ | 见账本 | 下一轮逐条核实 |

---

## 第七屏：旧数据隔离（S7）

- **已批准**（总调度 17:2x）：
  - 笔记本和两台服务器 renders 的全部候选类别；
  - 仓库根的 9 个 *_take/ 目录；
  - 11-01 23:20 之前的 195 条任务记录。
- **17:3x 追加**：gpu33 在 16:30 之后重复出的 ep02/04/06 版本。先和 gpu36 当前版交叉核对；当前版和被引用的不动，这部分见 A-15。
- **暂缓**：data/_offline_pull 和服务器 outbox，等 A-06 修好、重新合并之后再处理。
- **怎么执行**：
  - 时间：sv-14 部署之后；
  - 工具：tools/qa/audit_quarantine.py；
  - takes.json 只经 takes_cli 改，先打标记、再移文件；
  - 记录写进 moves.jsonl 和 MANIFEST，可以用 restore 还原；
  - 移到 data/_quarantine_20261102_audit/。
- **预演**（17:2x dry-run，笔记本）：约 2215 MB，包括 1208 个版本、248 个孤儿文件、7 个 S11 目录；另外还有 9 个目录和 195 条任务记录。
- **状态**：⏳ 等 sv-14。
