# 系统 SLO 与主动探测（总调度 fredw-2b，11-02 02:3x，L-103）

> 项目方 02:3x：“每次都是我指出来你才去修……这不是 RSI……你还没有具备 fully autopilot 的能力。”
> 原则：问题必须由系统自己先发现。每条 SLO 都配一个自动探针；违约时自动开工单（data/sentinel/issues.jsonl）并派给负责 loop。项目方先于系统发现的问题，一律记一条“探针缺口”，并补上探针。

| # | SLO | 目标 | 探针 | 违约后派给 |
|---|---|---|---|---|
| S1 | 每条出图道 GPU 利用率（滚动 30 分钟，/history 执行时间并集） | ≥ 0.8 | lane_util | DEBUG-RSI |
| S2 | 每台服务器有 ready 单时，GPU 不能全空 | 连续 3 分钟全 0% 即违约 | nvidia-smi + producer 登记表 | DEBUG-RSI |
| S3 | 打分 p50（出图完成 → 契约结论） | ≤ 120 s | producer log | VQAGATE |
| S4 | 连接：底座或内层断开后恢复时间 | ≤ 30 s；跳板新建连接 < 50 次/小时 | net_status + relay_rate | NETFIX |
| S5 | 发版：cut 成功率；服务器代码版本 = 最新 sv | cut 一次通过；版本差 ≤ 1 | last_cut.json + system_version.txt | FACTORY |
| S6 | 服务器配置和笔记本一致（refs、覆盖配置、vqa.json 等） | 0 差异 | sync verify | FACTORY |
| S7 | 暂停：无主暂停时长 | ≤ 180 s | policy.pause_decision | DEBUG-RSI |
| S8 | 内容：过契约首帧的看镜头率、身份失败率、缺件率（本地 VLM 抽检） | 看镜头 0、身份 0、缺件 0 | VLM 抽检每小时 10 张 | VQAGATE / IMGFIX |
| S9 | 界面：彩色元素数、旧图 / 裂图、口径矛盾（截图 + 规则检查） | 状态色只有圆点；裂图 0；矛盾 0 | 无头截图 + DOM 规则 | UIRSI |
| S10 | 决策与规则：decision_check / propagation / compile | 0 ❌ | 每拍 | 规则 owner |
| S11 | 编排器：每集卡在同一段的时长 | 同段 > 2 小时无进展即违约 | flow status | DISTILL |
| S12 | 剧本：代码判定失败项、尺子标准差 | 新稿 0 失败；σ ≤ 1 | rubric_code / ruler | HOLLYWOOD |
| S13 | 等人决定：任何对象等总调度 / 项目方定；流水线断档（GPU 空、ready 0、pending 多） | 等人 ≤ 10 分钟；断档 0 | 登记表 waiting_for + nvidia-smi（总调度 02:4x 追加：02:22 gpu33 全 0% 根因 = 77 个首帧“等总调度定”） | DEBUG-RSI |

探针实现：tools/sentinel/（K-OPS-S02…S07；阈值 config/policies/sentinel.yaml）；工单 data/sentinel/issues.jsonl，未关闭快照 data/sentinel/open.json，看板 :8810“工单”区。

总调度每拍只做三件事：看工单 → 按 G0 派单 → 核对上一批工单是否真的关闭（看探针数据，不看报告）。
