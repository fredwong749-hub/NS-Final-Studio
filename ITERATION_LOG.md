# ITERATION_LOG — NS-Final Studio（只追加；格式：轮次 | 日期 | 阶段 | 假设 | 变量 | 冒烟分 | 结局 | 备注）

| 轮 | 日期 | 阶段 | 假设（一句） | 改的唯一变量 | 冒烟分 | 结局 | 备注 |
|---|---|---|---|---|---|---|---|
| R0 | 2026-11-03 15:5x | Phase R | 先有"跑通"的定义才有迭代 | 新建 eval/run_smoke.ps1（八门） | — | 进行中 | 基线未跑；采纳 RSI 实施包（L-170）。此前 11-01～11-03 的工作按 docs/master/OVERSIGHT_LOG.md 第 1–29 轮与 MASTER_PICTURE L-001…L-169 追溯 |
| R0b | 2026-11-03 15:56 | Phase R | cut B 入版即 best 基线（服务器本地打分是跑通前提） | sv-20261103-02 发版 + 部署两台 + L-152 换代 | — | 进行中 | best=44e6c37；deploy 起跑 |
| R0 结果 | 2026-11-03 16:16 | Phase R | （同上） | eval/run_smoke.ps1 建成（W26） | **1/8**（15.2 s；只过 G7） | 基线已立 | G1 :8800 没在跑（16:15 已重启）；G2/G3 smoke_v2 缺 asset_refs.json 项目条目→5 缺口→build_first 空；G4–G6/G8 连带未跑。下一轮唯一变量：asset_refs.json 加 smoke_v2 条目 |
| R1 | 2026-11-03 16:19 | Phase R | smoke_v2 缺资产项目条目是 G2/G3 根因 | config/recipes/asset_refs.json 加 smoke_v2（inherits series10_v2） | **2/8**（10 s；G1 过因 :8800 已重启、G7 过） | 采纳（分数升，配置留下） | G2 仍 3 缺口：祁念造型对不上 P1 登记（script_match 0.35）、唐瑶本集造型排期没进 hub_episode_looks.json、第 3 条见 eval/results/20261103-1618.json；G3 StyleMissing：config/compile/run_style.json 没有 smoke_v2 风格后缀。下一轮唯一变量：smoke_v2 模板补齐本剧级配置（run_style + P1 looks/排期对齐夹具） |
| R2 | 2026-11-03 17:21 | Phase R | smoke_v2 本剧级配置对齐主剧即 G2/G3 过 | run_style.json 加 smoke_v2 + 夹具/排期对齐（W26b） | **2/8**（1690 s；G2 ✅ 新过、G7；G1/G8 失败因 :8800 在 16:52 又不通——外因） | 采纳（G2 由红转绿；总分未升因 API 外因） | G3 只差出图日志关键字（rendered + takes.references）；G4 25 分钟内首帧 3/3 + 尾帧 2/3 真出了、视频 0/3（VIDEO10 在服务器端，未换代）。下一轮唯一变量：:8800 为何反复被杀（与 cut/全量 pytest 同时段）—守卫落地后重跑 |
| R3 | 2026-11-03 22:05 | Phase R | :8800 反复被杀靠看门狗/守护自愈 | watchdog 规则 10 + resident_guard 看护 autoflow（W27） | —（未重跑：gpu36 看图服务死、cut C 被挡） | 代码采纳、分数待测 | 真机制已被 A-G3 预检抓到：system_version._kill_tree taskkill /T 按 pid 杀树、pid 复用误杀（W37 修）。换代里程碑：gpu33 本地出 ep01 首帧（L-180） |
