# 服务器工厂框架重构方案（FACTORY loop，11-02 01:2x，草案，等总调度审）

> 项目方原话（11-02 01:1x）：“单独写个 Agent，在服务器的 GPU 上写代码，把我们遇到的慢连接、断连一大堆的问题，在那边把系统的 framework 重新 reframe 一下，看怎么样做得更好”。
> 基于 docs/master/FACTORY_ARCH.md（L-099）。G0 检索词：隧道 / tunnel / IMAGE_LANES / fwd.py / OFFLINE_SELF / remote_score / base64 / object_info / MaxStartups / MaxSessions / pull_every_s / push_required / required_data / assets_ready / override / global_pause / vqa server / 让道 / hold。
> 命中的文件：tools/autopilot/producer.py、resident_sync.py；ops/offline/resident_prep.py、resident_restart.sh、merge_pull.py；服务器上的 offline_20261101/{fwd.py, bin/ssh}；tools/gen_contract/remote_score.py；tools/netfix/*；/root/work/fredw/vqa/server.py；knowledge/rules/netfix.yaml、vqa.yaml、ops_debug.yaml；docs/overnight/morning_20261102.md。
> 状态：只是方案，总调度审过之前不做大规模改动。已经做的只有不改代码的数据修复和验证（见 §7）。

## 1. 踩过的坑（每条带出处和实测）

| # | 坑 | 出处 / 实测 | 根因类别 |
|---|---|---|---|
| P1 | 跳板 sshd MaxStartups 10:30:100：同时握手超过 10 个就随机丢；服务器 MaxSessions 10：mux 报 “Session open refused” | tools/netfix/rssh.py:5、:28；knowledge/rules/netfix.yaml K-OPS-N07；morning_20261102.md:52（笔记本上 26 个 ssh）、:63 | 生产路径上有大量跨跳板的同步 ssh |
| P2 | 每单拉 /object_info，2.6 MB | morning_20261102.md:52（加缓存后每单省 16–49 s） | 笔记本当 ComfyUI 客户端，协议本来是给本机用的 |
| P3 | 打分要把参考图、成图 base64 后经 ssh stdin 传过去；身份脸另走一次 base64 上传 | tools/gen_contract/remote_score.py:43–67（_FACE_UP）、:99–140（_ONE_SHOT）、:168–200（full_score） | 打分和出图不在同一台机器、同一个进程空间 |
| P4 | 隧道派单：producer 把道写死成 127.0.0.1:18188… 这些隧道端口；服务器上还要靠 fwd.py 再把同样的端口转回 8188，才能骗过同一份代码 | producer.py:69 IMAGE_LANES；config/render_endpoints.json；服务器 offline_20261101/fwd.py；config/netfix/override.json（K-OPS-N06） | 地址写死在代码里，没有“本机工厂”这个概念 |
| P5 | 实测：经隧道的道，每单墙钟是 GPU 时间的 3 倍 | data/producer/log.jsonl，rendered 事件（11-01 20:00 之后）：gpu33 墙钟 p50 109.2 s / GPU 38.0 s（18 单）；gpu36 136.4 s / 36.7 s（12 单） | 同 P2–P4 |
| P6 | 结果每 20 分钟才整批 tar pull 一次 | resident_sync.py:607 loop(pull_every_s=1200)、:380 tar cf | 回传按“目录快照”做，不是按“结果事件” |
| P7 | 看图 VLM 只有一个实例、串行；还和出图共用 GPU0/1，按“让道”调度：ComfyUI 有活就卸载，显存不够就 OOM | gpu36:/root/work/fredw/vqa/server.py 文件头；server.log 共加载 44 次，“出图来活让道”4 次，OOM 7 次；01:15 /health：loaded=false，last_error=OOM；vqa.yaml:189 打分 p50 29 s → 646 s | 结构性死锁：出图忙时看图不跑 → 打分积压 → 积压闸（K-OPS-E05）停派 → GPU 空下来看图才跑 → 来回震荡 |
| P8 | 全局 pause 会让两台服务器一起停产：00:52 切线路时 pause 了 12 分钟没恢复 | morning_20261102.md:63；dispatch.py global_pause / control_for（服务器 paused 跟随笔记本）；resident_sync.sync_pause | 网络运维动作和生产开关耦合在一起 |
| P9 | 资产按“整目录、大小 + 修改时间”推，推一次约 90 分钟；清单靠人维护，会漏 | override.json _doc（约 90 分钟）；resident_sync.py:120–160 按大小 / mtime 比对；**今天 01:13 实测**：required_data 漏了 assets/scenes，gpu36 交还后每单都被 preflight I5（sk_elevator 没有底图）挡下 | 依赖集不是从 preflight 本身算出来的；资产不按内容寻址（scene_ref 取的是“目录里 mtime 最新的一张”，asset_refs.py:585） |
| P10 | 服务器代码和笔记本代码不一致，控制文件也不全 | **今天 01:13 实测**：服务器是 sv-20261102-01，里面没有 asset_hold_objects（IMGFIX r5 的 hold 逻辑还没进版本）；lookA_hold.json 也不在 push_control 的 CONTROL_FILES 里。结果服务器 producer 实际派出了被 hold 的 first:ep02-S1/S2，只是恰好被 I5 挡住 | 代码版本和控制状态没有绑在一起；服务器拿不到“现在应该是什么状态”的完整声明 |
| P11 | 服务器副本靠运行时打补丁：resident_prep.py 用字符串替换改 night.py / sync.py / remote_score.py；bin/ssh 包装成“ssh gpu33 = 在本机执行”（OFFLINE_ALIASES） | ops/offline/resident_prep.py:24–64；offline_20261101/bin/ssh | 代码里没有“我是哪台工厂”的身份，只能事后修改 |
| P12 | 交还状态机分散在两边，会读到过期状态：01:09:07 笔记本已判 gpu36=server，01:09:34 服务器 control 仍写 draining，要等下一次 push_control 才生效 | data/netfix/override_state.json；服务器 control.json dispatch_by.override_phases | 状态有多份副本，各自推进 |
| P13 | preflight 挡一次就锁 30 分钟；资产补到后也要干等，最长 30 分钟 | producer.py:66 PREFLIGHT_RETRY_S；服务器 attempts.json：first:ep02-S1 blocked_until = 挡住时刻 + 30 分钟 | 按时间轮询，没有“依赖到齐”这个事件 |
| P15 | 笔记本从服务器下载成图约 33 KB/s：3.1 MB 的 PNG 每单约 100 s；mux 会话被拒时 _postflight 重试 3 次（退避 30 / 60 / 90 s），然后退回本机 CPU 打分 | docs/debug/DEBUG_r1.md 第 19 / 19b 条、第 6 条（DEBUG-RSI） | 原图进了关键路径。D7 的修法：outbox 默认只回结果 json + 缩略图，原图按需再取 |
| P16 | resident_sync 只要代码有变就重启服务器常驻进程：3.5 h 里重启 22 次，每次都作废租约 | DEBUG_r1.md 第 8 条 | 发版和运行时没有解耦。D9 的修法：只在 deploy sv-* 时重启，而且按道排空后滚动重启，不打断在跑的出图 / 打分 |
| P17 | 部署按笔记本工作树推，而不是按 tag 推：sv-20261102-02 cut 之后工作树里又新建了 tools/imgfix/lookA_adopt.py 和 tools/netfix/relay_rate.py，推送前检查判“代码没推到”，gpu36 整次部署被拦；gpu33 却成功了，结果两台版本不一致，gpu36 继续跑没有 hold 逻辑的旧版，01:24:51 派出了 hold 里的 ep02-S1/S2 | 总调度 01:3x；system_version.py deploy 先 rs.push(tier=1)（从工作树推），再按 tag 核 sha | 部署的输入不是不可变的版本对象 |
| P14 | 场景底图 / 设定图取“目录里最新的一张”，两台机器 mtime 不同，就可能选到不同的图 | asset_refs.py:585 scene_ref | 逻辑名 → 文件的解析不确定 |

## 2. 对应的框架层设计（每条都是结构性的，不是单点补丁）

| 设计 | 解决 | 要点 |
|---|---|---|
| D1 工厂身份 + 本机道表 | P4、P11 | config/factory/hosts.json：每台工厂的道 = 本机 ComfyUI URL（gpu33 0/1/3，gpu36 0/1，laptop 0；按 L-100，gpu36 GPU2 和笔记本 4080 是看图卡）。代码读环境变量 NS_FACTORY_HOST，不再有隧道端口，也不需要 fwd.py、bin/ssh 包装和 resident_prep 字符串补丁 |
| D2 本地库（内容寻址） | P9、P14 | library/objects/<sha256 前 2 位>/<sha256>，外加 library/names.json（逻辑名 → sha，例如 scene:sk_elevator → sha）。作业表 / 资产解析只认 sha；scene_ref 改成“名字表里定下的那一张”，不再按 mtime 取 |
| D3 依赖闭包 = preflight 自己算 | P9、交还条件 | 在服务器上对负责的全部集跑 producer preflight dryrun（不提交），记录 preflight 和 plan 实际解析到的每个文件，得到 need = {sha}。缺什么就报什么；sync push 只补这些 sha。dryrun 挡 0 才写 assets_ready.<host>.preflight_dryrun_ok=true（总调度 01:2x 的交还条件） |
| D4 inbox = 声明式“目标状态” | P10、P12、P8 | 笔记本只推一个文件：inbox/state-<seq>.json，内容是 {作业表 sha、control、rejects、所有 *_hold.json、ready_episodes、min_code_sv、names.json 的 sha}。服务器原子替换后生效。状态里带 min_code_sv，以及每个功能字段需要的最低版本（例：holds 需要包含 asset_hold_objects 的那一版）。本机代码版本低于要求时，涉及这些功能的对象一律不派（例：版本不够时，hold 名单里列出的镜整镜不派），其余照常派，并且报警。今天 hold 被无视那种情况会被拦下（总调度 01:3x）。服务器自己计算 only / hold，不再有两边各一份的 phase |
| D5 生产开关和网络解耦 | P8 | 断网 ≠ 暂停：服务器按最后一份目标状态继续出图。暂停只认两种：①项目方或总调度显式暂停；②带 expires_at 的运维暂停（≤ 3 分钟自动恢复）。全局暂停不能再间接停掉服务器 |
| D6 本机打分常驻服务 | P3、P7 | full_score 改成服务器本机的常驻进程（ArcFace / OCR / mediapipe / CLIP 只加载一次），HTTP 走 127.0.0.1，参考图直接从 library 按路径读，不走 ssh、不走 base64。VLM 由 VQAGATE 部署到专用卡（L-100：gpu36 GPU2），批处理、不再让道。producer 出完一张就投递打分，打分和出图两条流水线并行；积压闸改按“打分服务的处理率”来算 |
| D7 outbox（事件、追加写） | P6 | outbox/<结果 id>/：成图 / 视频 + manifest.json（sha、大小、对象 id、事件：rendered / scored / take_set …）+ 最后写的 .done。NETFIX puller 用长连接收、校验 sha，再调 merge_file。服务器只追加、不改已写好的结果；回传延迟和生产解耦 |
| D8 事件驱动重查 | P13 | library 新增 sha / names.json 有变化时，清掉“缺这些依赖”的 preflight blocked_until（只清原因匹配的），不用再等 30 分钟 |
| D9 代码 = 干净的 git 工作树 | P10、P11、P16、P17 | 服务器代码目录 = git 工作树（bundle fetch → checkout sv-*）；启动前检查 git status，有手改就拒绝启动并报警。“服务器上不许留手改”从约定变成机制。**部署只发 tag 里的东西**：部署的输入 = 该 sv 的 git 对象（bundle），不是笔记本工作树。工作树里多出来的新文件 / 没入版的改动只报 drift（留给下一版），不能让整台机器的部署失败。重启按道排空：等那条道的 ComfyUI 空了再重启，空转 ≤ 1 分钟（总调度 01:3x）；只有 deploy sv-* 才重启 |
| D10 一条命令的控制台 | 笔记本只做三件事 | tools/factory/sync.py：push（state + 缺失 sha + 代码 bundle）、pull（交给 NETFIX puller / merge_file）、status（各工厂心跳、道利用率、打分 p50、outbox 积压、本机代码 sv） |

## 3. 方案比较

| 维度 | A：服务器常驻 producer + inbox / outbox（笔记本主动推 / 拉） | B：服务器自己从 GitHub / 对象存储拉代码和资产，笔记本完全退出生产路径 | C（推荐）：A 的运行时 + B 的“声明式目标状态”，传输层可替换 |
|---|---|---|---|
| 生产路径上有没有跨跳板的同步调用 | 没有 | 没有 | 没有 |
| 网络方向 | 只需要笔记本 → 服务器（现状本来就是这样，跳板只能从笔记本这边进） | 服务器 → GitHub：01:2x 实测 gpu36 能访问 github.com（HTTP 200）；但私库需要服务器上有凭据（deploy key / token），没有对象存储 | 先走笔记本推；以后有了凭据，换成服务器自己拉，工厂代码不用改 |
| 控制决策（驳回 / hold / 暂停）怎么到服务器 | 笔记本推 state 文件 | 要有一个双方都能写的中转（例如 git 私库），笔记本还得 push | state 文件；传输方式两种都支持 |
| 资产 | 缺 sha 补传（笔记本推） | 对象存储或 rsync 拉：现在没有对象存储，rsync 拉要求服务器能连到笔记本，做不到 | 缺 sha 补传；library 的布局兼容将来接对象存储 |
| 需要项目方做的事 | 无 | 给服务器配 GitHub 凭据、开对象存储（花钱 / 安全决定，属于项目方闸门） | 现在无；B 那部分以后让项目方点选 |
| 改动量 / 风险 | 中；大部分部件已有（常驻 producer、merge_file、puller） | 大；依赖外部条件 | 中 |
| 断网 30 分钟演练 | 能过（服务器按最后一份 state 继续出图，outbox 存着，恢复后补传） | 能过 | 能过 |

**选 C。** 理由：①B 的前提（服务器上的凭据、对象存储）现在没有，而且属于项目方的安全 / 花钱闸门，不能自己开。②A 的风险点在“服务器拿不到完整状态”（P10、P12），C 用声明式 state + min_code_sv 根治了这一点。③state 和 library 都是传输无关的格式：以后项目方给了 GitHub deploy key，只要把“笔记本推 state”换成“服务器 git fetch state 分支”，工厂代码一行不改。

## 4. 目标代码结构（单一代码树，按 sv-* 发版）

```
tools/factory/
  host.py        工厂身份、本机道表（config/factory/hosts.json）、thread_guard（K-OPS-V13）
  library.py     内容寻址库：put / has / path_of(sha) / names（逻辑名 → sha）/ missing(need)
  deps.py        preflight dryrun → 依赖闭包 need={sha}、挡单原因；写 assets_ready.<host>.preflight_dryrun_ok
  inbox.py       state-<seq>.json 原子应用；计算本机 only / hold / paused；检查 min_code_sv
  outbox.py      写端：<结果 id>/ + manifest.json + .done（和 NETFIX 对齐）
  scorer.py      本机 full_score 常驻服务（127.0.0.1），参考图从 library 读
  sync.py        笔记本控制台：push / pull / status
tools/autopilot/producer.py   只改接线：道表来自 host.py；打分调 scorer；结果交 outbox；preflight 挡单接 D8
```
不新造平行的 producer：状态推导、自修阶梯、租约都复用现有 producer.py（G0：复用已有部件）。

## 5. 迁移（不全局停产，每条道空转 ≤ 3 分钟）
1. 开发树 gpu36:/root/work/fredw/ns_factory_dev（已建，factory-dev 分支 = sv-20261102-01）。在服务器上写代码、跑测试，跑真实出图用 gpu36:0/1 的空档。
2. deps.py 先上：对两台各自的全部集跑 preflight dryrun，列出缺失 sha 并补齐，dryrun 挡 0 → preflight_dryrun_ok。**这一步是交还的前提**（总调度 01:2x）。
3. 下一个 sv 必须包含 asset_hold_objects（IMGFIX r5）和 inbox 里的 hold，deploy 之后才能交还（P10）。
4. gpu36 交还 → 3 镜端到端：服务器出图 → 本机打分 → outbox → puller → merge_file → UI。
5. scorer 常驻 + VLM 专用卡（和 VQAGATE 一起）→ 测出图 + 打分 p50。
6. gpu33 同样流程。
7. 隔离笔记本隧道派单路径、K-OPS-N06、fwd.py、bin/ssh、resident_prep 补丁（移到 data/_quarantine，不删）。
8. laptop:0 用同一套代码作为第三台工厂。

## 6. 验收（FACTORY_ARCH §3）+ 规则
- 服务器 GPU 平均利用率 ≥ 80%（按小时）；每单出图 + 打分 p50 ≤ 2 分钟（服务器本机计时）；跳板断 30 分钟演练不丢单、不停产，恢复后 30 分钟内补传完。
- 新规则从 K-OPS-F01 开始编号，每条都带 check：F01 生产路径不许有跨机同步调用（静态扫描 producer / scorer 有没有 ssh、隧道端口）；F02 交还前 preflight dryrun 挡 0；F03 资产按 sha 解析（scene_ref 等不许按 mtime 取）；F04 state 带 m