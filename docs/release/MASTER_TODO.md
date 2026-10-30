# NS-Final Studio 封板 Master To-Do（v1.0）

> 总调度 fredw-b3 编，2026-10-30 晚。依据：`docs/release/` 下的 `audit_laptop.md`、`audit_gpu3.md`、`task_reconcile.md`，以及各会话的 `debug_*.md`（陆续产出）。
> 分工原则（项目方定）：内容全部归 Qwen；Claude 只做系统、调度和 debug，不写内容，也不评价内容。
> 封板规则：不加新功能，只修 bug。每个修复都在 CHANGELOG 记一行，标“封板修复”。在第 5 阶段统一提交之前，任何会话都不提交 git。

## 封板标准（v1.0 = 全部打勾）

- [ ] 笔记本：pytest 全绿（含 `services/canvas_api/tests`）、`tsc` 0 错误、`vite build` 通过。
- [ ] 运行中的 API 和源码一致；所有接口返回 200，没有超过 1 秒的接口（旧的 `/api/episodes` 除外）。
- [ ] 剧本在三处（笔记本、gpu3 mirror、桥）sha 一致，s1_gate 对当前剧本有效。
- [ ] **ep02 端到端跑通**：Qwen rules_v2 剧本 → 导入 → S1/S2 → gpu3 出首尾帧（带林晚 LoRA）→ H3 视频（h3_prompt_source=script_field）→ 同步回画布 → 画布全部功能实测通过。
- [ ] 笔记本和 gpu3 重启后，核心服务都会自己起来。
- [ ] 文档没有互相矛盾（REQUIREMENTS / WORKFLOW / SOP / TASKS 和今天的决定一致）。
- [ ] 打出基线提交，加 tag `v1.0`，私人文件和会话记录都不在库里。

---

## 第 1 阶段 · P0 阻塞项（必须先做）

| # | 事项 | 负责 | 状态 |
|---|---|---|---|
| P0-1 | 运行中的 API 比代码旧，“按集渲染”接口 404 | 总调度 | ✅ 已重启（20:5x），路由已加载 |
| P0-2 | 仓库根目录有 61 MB 的会话记录和私人文件，有误入库的风险 | 总调度 | ✅ `.gitignore` 已加 `/为他而骚短剧/` 等 |
| P0-3 | ep01 已验收，却被 `script_not_v3` 拦住（`state_timeline.py:575` 用了整份剧本的版本） | fredw-92 | 进行中 |
| P0-4 | 剧本三处 sha 不一致（桥读的还是 10-29 的旧版）；桥和 mirror 的代码比笔记本旧 | fredw-ae + fredw-92 | 进行中 |
| P0-5 | 没有任何一集端到端跑通过 | 见第 4 阶段 | 等 ep02 |
| P0-6 | 改动全部没提交（101 个文件改动、约 120 个未跟踪），没法回滚 | 总调度 | 第 5 阶段 |
| P0-7 | 重启后服务不会自己起来：gpu3 有 6 个临时 unit；笔记本的 API、隧道、同步都要靠会话手动起 | fredw-ae / fredw-92 写命令，**项目方亲自执行** | 等命令 |

## 第 2 阶段 · P1 修复（封板前做完）

**gpu3（fredw-ae）**
- [ ] 停掉孤儿进程 chain.sh（35779），过期的 scheduler_plan.json 作废
- [ ] 给 GPU3 加一个预留锁，防止 :8100 抢先占卡；渲染卡列表里去掉 GPU1
- [ ] rerender_queue 里 4 条没有 run_id 的旧请求移到存档
- [ ] 更新 Qwen 读的 REQUIREMENTS 快照；把 7 份剧本 .bak 移出 Qwen 能读的目录
- [ ] qwen-agent3 改成 `Restart=on-failure`（和 P0-7 一起做）

**导入与 API（fredw-92）**
- [ ] sources 去重（D-3）；查清导入后 v2 源文件 sha 为什么变了（D-4）
- [ ] 慢接口加缓存：qwen/tasks、gpus、readiness、sop/status；前端不再退回去调旧的 `/api/episodes`
- [ ] 写清剧本 5 个入口的说明；ops 下分叉的脚本只留一份；停掉孤儿轮询进程
- [ ] QA4-01 源文件漂移，接成 warn

**写作（fredw-c8）**
- [x] 导演加强改走 Qwen，不再走付费 API（A-3）
- [x] 清掉 abliteration 残留（X-3）
- [x] 补齐拆两半和定向返修的单测；把 debug_writer.md 写完

**编译与后期（fredw-5c）**
- [x] 造型库能识别全部 60 集（A-4）
- [x] 林晚触发词只留一个规则来源（D-6）；models.lock 里补上 lnwan01
- [x] 配乐三套解析器统一成一份规则（X-4）
- [x] gpu_grab 遵守 comfy.lock（X-1）
- [x] 金标准和 T06 的说明对齐（G-6）；查清剧本库文件被改的 6 行（G-7）
- [x] **文档统一 X-01～X-08**（WORKFLOW、REQ G8、TASKS 规则 5/7、SOP §5/§8/§9A、T48 等）；以后 SOP 由 fredw-5c 维护

**前端（fredw-25）**
- [x] 把 canvas_api 测试接入根目录 pytest，并能在 Windows 上通过（T-1）
- [x] 写完 debug_frontend.md；ui_smoke 回归脚本放进 tools/

## 第 3 阶段 · 决定事项（已分好类，只有少数要项目方定）

**A. 总调度已定（按现有规则）**
- D-37 首尾帧由谁发起：系统编译器加 gpu3 渲染器（和“系统自动补”一致），WORKFLOW 里的 frames.json 透传方案作废。
- D-38 gpu3 服务常驻和隧道自启：封板期内做（P0-7），由项目方执行命令。
- D-22 阶段调度器 T46：关闭，改用固定分卡（GPU1 给 Qwen 写作模型，GPU0/GPU3 给 Qwen 做 LoRA，渲染时借用）。
- D-13 配乐：**项目方 2026-10-30 定“写进 H3（按 E8）”**：本集配乐加单镜覆盖写进 H3；后期对已经带配乐的镜头不再叠加 BGM。gpu3 的 weita_render 和 shot_audit 由 fredw-ae 改。（总调度之前写的“只在后期加”作废。）

**B. 内容类，交给 Qwen 定（按分工 Claude 和项目方都不用逐条拍板）**
D-07/08（亲密场次的男方台词、男方呼吸）、D-09 单品颜色、D-10 多人规则、D-11 配角描述、D-12 “精致”能不能用、D-15 标志音、D-16 独白溢出、D-17 光圈、D-18 人数写法、D-19 顾沉的年龄感、D-30/31 QC 阈值、D-32 每集镜数和时长、D-33～36 妆容、痣、美甲、淡出。没有改动的就沿用默认值；Qwen 的决定通过信箱写回规则文件。

**C. 必须项目方本人定**
1. ep02 造型确认，以及这次跳过底图（3 行命令，见聊天记录）——**ep02 现在卡在这一步**
2. 执行 P0-7 的两条持久化命令（gpu3 和笔记本各一条）
3. T59 画布新设计验收（D-23）
4. 底图：除了 ep02，其他集是不是必须先出底图（D-29）
5. 饰品 / 姿势 LoRA 要不要交给 Qwen 训练（D-27）
6. 导演加强规则（D-20）、重启 Civitai 下载（D-21）：要还是不要
7. ep02 出片后锁定参数（D-28），以及之后各集逐一采纳剧本（D-26）和确认造型（D-25）
8. 男主候选挑选（D-24，等 Qwen 出候选）

## 第 4 阶段 · ep02 端到端验收

1. fredw-c8：Qwen rules_v2 版 ep02 通过严格校验和 SRC-D1 → 导出
2. 项目方：执行 ep02 的 3 行确认命令
3. fredw-92：合并导入（`--source-version v3`）→ S1 → 三处同步，核对 sha
4. fredw-ae：GPU3 出首尾帧和视频 → 逐镜核对 script_field 和 lnwan_qi → 同步回笔记本 → 卡还给 Qwen
5. fredw-92 / fredw-25：用真实产物把画布实测一遍（ui_smoke），出深浅两套截图
6. 项目方：看片验收（Claude 只报技术指标，不评价内容）

## 第 5 阶段 · 基线提交与 v1.0

1. 等后台写作批量在一集的边界暂停，或者在说明里写明“不计入本版”
2. 全量测试、tsc、build 再跑一遍，全部通过
3. 分批提交（总调度执行；需要项目方说一句“提交”）：①依赖和配置 ②packages/services ③apps/web ④tools、tests ⑤docs、release；剧本和产出数据不入库
4. 加 tag `v1.0`，在 `docs/release/RELEASE_NOTES_v1.0.md` 写明：已知限制（ep01 等🔴集只能由项目方渲染、本机出视频的开发者开关、React Flow 水印）、怎么启动、怎么回滚
5. gpu3 同步打一个对应的快照（备份目录加 v1.0 标记）

## 第 6 阶段 · 封板后（v1.1 及以后）

- #8/#9 系统提示词改成正面写法（Qwen 措辞交回后再替换，金标准会变）
- CSS 层层覆盖整理（v2/v3/t59/ux-fix 合并）
- 机检 SC-01～SC-29 里还没做的部分
- QC 闸门接进 gpu3（PI-07/08 等 9 个没有闸门的生产问题）
- T47 一致性、T18 成集 QA、T30 改动监控、T40 其余集音频
- 全本 58 集写完后，逐集导入、渲染（🔴集由项目方启动）
- 林晚视频 LoRA（lnwan01）、林晚 + 服装 LoRA、资产 T10～T13（Qwen）
- 4K（up4k-test 失败，需要重新排查）
