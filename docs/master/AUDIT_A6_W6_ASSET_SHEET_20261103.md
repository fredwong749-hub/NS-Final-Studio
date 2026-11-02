# A6 · W6 ASSET-SHEET 独立审计（Fable，2026-11-03 05:0x；只审不改）

范围：tools/pipeline/asset_checks.py / asset_worker.py / asset_jobs.py（均为未入库新文件）、services/api/ns_api/owner_pick.py:326 路径、tests/test_asset_pipeline.py W6 段、sheet-lead_f-O4 作业与两张候选。
实跑：asset 相关 15 个测试文件 153 passed（含 W6 新增 7 条）；episode_ready series10_v2 ep1；两张候选绕过看图缓存重跑 age_check / bundle_check / anomaly.check。

## 逐条

### 1. 判词解析（C-22 / HC-07 红线）
- **谁说了什么**：W6：“_age_status 改为取第一个出现的判词；判词是未成年、或没有判词，一律 fail；没放宽。”
- **实际是什么**：反例集（旧 = `startswith("成年")`→pass / `startswith("无人物")`→na / 其余 fail，按 cast_v2.py:119 同款写法复原）跑新旧两版，fail→pass 翻转的有 8 条：

| 回答 | 旧 | 新 | 合理？ |
|---|---|---|---|
| 画面里的人看起来是“成年”，因… | fail | pass | 合理（W6 根因） |
| 年龄：成年 | fail | pass | 合理 |
| 她是成年人；旁边的孩子未成年 | fail | pass | **不合理**（多人句放过未成年） |
| 这个人是成年人，但另一位像未成年 | fail | pass | **不合理** |
| 不像成年人，更像未成年 | fail | pass | **不合理**（否定句，首个判词“成年”在“不像”后面） |
| 不是成年人 | fail | pass | **不合理** |
| 非成年 | fail | pass | **不合理** |
| 大概率成年，但也可能是未成年 | fail | pass | 边界（不确定句应 fail） |

  未翻转且正确：像未成年 / 看起来像未成年但穿着成熟 / 未成年 / 未成年在前混排 / 没有人 / adult / minor / 不确定 / 约15岁 / 15岁左右的少女 → 均 fail；无人物 → na；空 → untested。新旧都放过：“成年？不确定”“成年女性，约 17 岁”“成年…未成年（成年在前）”（旧写法同样 startswith 成年 → pass，不是 W6 引入）。
- **是不是 P0**：生产路径不是。sheet / face 候选的 passed 要六项全过，年龄之外还有两道独立闸：① anomaly.check 人头数 expected=1（多一个头 → duplicate_person / extra_head → count=fail）；② bundle 第 2 条“外观明显是成年人（大约 N 岁，不像未成年）”由看图模型答 符合/不符合，判未成年时会答不符合 → prompt_vlm=fail。所以“她是成年人；旁边的孩子未成年”这类多人句被 ① 拦，“不像成年人，更像未成年”被 ② 拦。但 `_age_status` 本身作为红线判词器不再失败关闭：否定句、多人句、“大概率…也可能未成年”都 pass，且 age_check（CLI）单独用时没有②这道闸。**定级 P1**（红线解析器放宽，靠别的闸兜底）。
- **证据**：本文附的 adv.py 跑表（已记在本审计）；asset_worker.vlm_items:635/639；tools/vqa/anomaly.py:769-784。
- **建议**：`_age_status` 补三条、三行即可：(a) 首个判词前若紧跟 不/非/不像/不是 → fail；(b) 文本任何位置出现 未成年 且不在“无未成年/没有未成年/不像未成年/非未成年”否定里 → fail；(c) 出现“可能/也许/不确定”且判词是成年 → fail。把表里 5 条不合理反例加进 test_age_verdict_parses_first_verdict_not_prefix。

### 2. salvage（≥2 张 sha 对得上的过检候选就收尾）
- **谁说了什么**：W6：“子进程没收尾 / pending 时若已有 ≥2 张 sha 对得上的过检候选就直接收尾。”
- **实际是什么**：salvage_records(:815) 只收 job.candidates[] 里 passed=True 且 sha256 与盘上复核图一致、且复核 JSON（若有）passed 不为 False 的条目。candidates 条目只在 render_one 完整返回后由 run_job(:915) 追加，而 render_one 的 passed = 六项 label 全 pass/na，复核图与 JSON 也只在 ok 时才拷贝；中途被杀的候选不会进 candidates，更没有 sha。**契约只跑一半的候选不可能被当过检**，核对通过。两点旁注：① 复核 JSON 缺失时 rec={} 仍接管（只影响打分）——可接受，因为 passed/sha 以作业文件为准；② pending 路径的 salvage(:343) 跑在 sop_filter 之前，SOP 闸门没过的集也会把旧候选投进待办——P2。
- **证据**：asset_worker.py:759-779（只在 ok 才写复核文件 / sha）、:915-917、:815-843、:343；test_salvage_refuses_tampered_or_too_few_candidates 通过。
- **定级**：无 P0/P1；P2 一条（SOP 闸门顺序）。

### 3. 超时杀子进程
- **谁说了什么**：W6：“job_timeout_min 超时杀子进程并落 pending/failed + why。”
- **实际是什么**：tick(:270-283) 的 alive 判定：`_PROCS` 有 Popen 用 poll()，否则 `_pid_alive(j.pid)` 用 tasklist。常驻服务每拍用 importlib 重新载入 asset_worker（autoflow_resident._load:31-35 每次新建模块），模块级 `_PROCS` 每拍都是空的 → 生产上**永远走 tasklist 路径**，只看 pid 存不存在，不看命令行。子进程死了没收尾、pid 被 Windows 回收给别的进程（resident 自己、API、别的 run-job、ComfyUI 本地进程都可能），且作业 started_at 超 90 分钟 → `taskkill /PID <pid> /T /F`(:885) 杀错进程并连带其子树。03:30 事故正是“子进程被杀、作业停在 running”这种形态，窗口真实存在。测试里 _pid_alive/_kill 都是 monkeypatch，没覆盖 pid 复用。
- **定级**：**P1**（新引入的 /T /F 杀进程没有身份核验）。
- **建议**：杀前核验：`tasklist /FI "PID eq N" /V` 或 `Get-CimInstance Win32_Process -Filter "ProcessId=N"` 取 CommandLine，必须含 `run-job --job <该作业文件>`（或比较进程创建时间 ≥ started_at）才杀，否则只落状态不杀；并把 `_PROCS` 改成不随重载丢失（挂到 builtins / 单独模块）或干脆在 job 里记进程创建时间。

### 4. ensure_golden 停掉后 owner_pick.py:326 路径
- **谁说了什么**：W6：“ensure_golden 改为只在 _ready_epNN.json 记录，不再生成 golden 作业。”
- **实际是什么**：owner_pick._ready_hook(:325-327) → asset_jobs.after_pick(:1073) → generate(:507) → ensure_golden(:540)，唯一入口，现在只返回字典写进 _ready_epNN.json 的 golden 字段，不写作业文件；tools/autopilot/producer.py 不读 asset_jobs。全仓没有第二处生成 golden-epNN。owner_pick.py:326 的 docstring 仍写“全部就绪时写阶段 B 作业 golden-epNN”，是陈旧注释（W6 没改这个文件）。历史 golden-ep01.json（pending）原样留着，worker 心跳 golden_pending 仍列出它，master_check / UI 可能误读为“待执行”——P2。
- **证据**：grep golden 全仓；data/pipeline/asset_jobs/series10_v2/_ready_ep01.json golden=null（ep1 还有 1 缺口）；test_ensure_golden_only_records_and_keeps_legacy_job 通过。
- **定级**：无漏网；P2 两条（陈旧注释、遗留 pending 作业）。

### 5. 实跑
- 测试：`pytest tests/test_asset*.py tests/test_*asset*.py`（15 文件）→ **153 passed, 0 failed**；W6 指定 4 文件 61 passed（与 W6 报的一致；W6 报的“199 过 1 跳 1 败”是另一组 13 文件，含 test_v2cut_o，本次未复现那组）。W6 新增测试实数 7 条（age 1、salvage 3、timeout 1、golden 1、dead_child_fails 1），与声称一致。
- episode_ready series10_v2 ep1：1 缺口 = 祁念 O4 没有设定图（等 pick）；11 镜 adult 全否。
- sheet-lead_f-O4.json：state=awaiting_pick，attempts=1，candidates 3（1100 age=fail，1101/1102 六项全 pass，sha 齐），pid=None，lane=None；log 记录 04:19 接管收尾；owner_queue requests.json 有 pick:sheet:lead_f:O4（2 选 1，推荐 s1101，候选 sha 与作业一致）。
- 注意：seed1100 的失败记录仍是 age=fail（旧解析所判），W6 没重判也没重出，候选只有 2 张（配置要 3 张）——按 salvage_min=2 设计是允许的，但项目方只有 2 选 1。P2 记录。

### 6. 两张候选图重跑契约（不改阈值，绕过缓存 refresh=True）
- s1101：age_check 首行“成年”；bundle 5 条全符合、年龄“成年，…无未成年视觉元素”、文字“无”、总结全部符合；anomaly heads expected=1 got=1 pass（finger_ratio 为 low 置信只记录）。
- s1102：age_check 首行“成年”；bundle 同上全过；anomaly 同上 pass。
- 两张回答都**以“成年”开头**，旧解析也会 pass；pass 不是靠解析漏洞。缩略图亲看：单人成年女性、雾蓝长直发、黑漆皮抹胸短裙 + 黑丝 + 透明细跟，与 P1 O4 一致。
- 旁注（非 W6 引入）：render_one 的 label.identity 固定 "na"，设定图没做与已登记身份脸的相似度核；待办文案“都过了出图契约、本地看图、年龄观感和 OCR”没说身份——与事实一致，但 owner_delegate 打分口径写着“身份相似度 + …”，与实际不符，P2。

## 汇总
| # | 项 | 级别 | 一句话 |
|---|---|---|---|
| 1 | _age_status 否定句 / 多人句 / 不确定句 fail→pass | **P1** | 红线判词器不再失败关闭；生产路径靠人头数 + bundle 第 2 条兜住，需补三条规则 + 反例测试 |
| 3 | 超时 taskkill /T /F 不核进程身份，_PROCS 每拍重载为空 | **P1** | pid 复用时会杀错进程树；杀前核命令行 / 创建时间 |
| 2 | pending salvage 跑在 SOP 闸门前 | P2 | 顺序调到 sop_filter 之后 |
| 4 | owner_pick.py:326 注释陈旧；golden-ep01 pending 遗留在心跳里 | P2 | 改注释；遗留作业标 done/closed_reason 或心跳里注明“已停” |
| 5 | seed1100 未按新解析重判，候选只 2 张 | P2 | 可接受；记录 |
| 6 | identity 固定 na，代选打分文案与实际不符 | P2 | 非 W6 引入，另派 |

**W6 能否进 sv-17：否（无 P0；两条 P1 需先修：① _age_status 否定/多人/不确定句失败关闭 + 反例测试；② 超时杀进程前核验 pid 身份）。两张候选与 awaiting_pick 状态本身没问题，项目方可照常在 #/queue 选。**
