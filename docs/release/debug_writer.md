# 封板 debug：写作流水线（fredw-c8，2026-10-30）

> 范围：`services/api/ns_api/script_chat.py`（对话 / 校验 / 返修 / 会话接口）、`tools/script_chat_batch.py`（批量 / 续跑 / 拆两半 / 预算 / 导出）、
> `tools/script_chat_repair.py`（定向返修）、`tools/validate_script_strict.py` + `tools/validate_qwen_script.py` + `packages/schema/ns_schema/h3_lint.py`（校验）、
> `config/script_chat_rules.md` + `config/script_chat_rules_appendix.md`（规则与附录注入）。
> 只测系统行为（格式、流程、预算、出错处理），不评价剧本内容。
> 测试命令：`.venv\Scripts\python.exe -m pytest tests/test_script_chat.py tests/test_script_chat_batch.py tests/test_validate_script_strict.py tests/test_validate_qwen_script.py tests/test_h3_prompt.py tests/test_script_inbox.py -q` → **70 passed**。
> 真跑：gpu3 Qwen 只用小样本（冒烟 1 次 + ep01/ep02 返修），没有打断正在跑的全本批量。

## 测试结果

| 模块 | 测试项 | 类别 | 结果 | 问题 | 修复 | 严重度 |
|---|---|---|---|---|---|---|
| script_chat.py | 会话新建 / 列表 / 读取 / 非法 id（`..%2F`） | 正常 / 边界 | ✅ 单测 | — | — | — |
| script_chat.py | 对话 SSE：start → progress → reasoning/content → saved → validating → done | 正常 | ✅ 单测 + **真跑**（:8800 → gpu3 Qwen，prompt 10438、finish=stop） | — | — | — |
| script_chat.py | 缺 key / HTTP 401·429·503 / 超时 / 流式中断存 partial / 会话忙 409 | 出错 | ✅ 单测 | — | — | — |
| script_chat.py | 附录按触发词挑选；命中节优先、“全部”节后丢；dropped 标注 | 正常 / 边界 | ✅ 单测 + 实测 60 集原稿 | 合并后附录变大时，命中节也被挤掉 | 加 reserve、精简全局头（2922→897 token）、按整体实测收紧预算；任何一节放不下就拆两半 | P1（已修） |
| script_chat.py | 上下文预算：prompt+输出 ≤ ctx−reserve；超了先丢历史、再压输出；<4000 报错 | 边界 | ✅ 单测 | `provider()` 没传出 `reserve`，余量按 0 算 | provider 返回 reserve / timeout | P1（已修） |
| script_chat.py | /api/script-chat/config 显示的 max_tokens | 正常 | ✅ | 显示全局默认 12000，不是 Qwen 实际 10000 | 改显示 provider 值并加 ctx | P2（已修） |
| script_chat.py | 整集切分 / 去 ```markdown 围栏 / 单镜切分合并往返 | 正常 | ✅ 单测 | — | — | — |
| script_chat.py | `spoken_entries` / `dialogue_checklist`：原稿台词、独白、说话人、原稿镜号 | 正常 | ✅ ep02 实测抽出 10 句 | — | — | — |
| script_chat.py | `source_check`（SRC-D1）：原稿台词 / 独白逐字保留 | 正常 / 出错 | ✅ 单测 + ep01/ep02 真跑 | 格式校验不比原稿，Qwen 为“一镜一人”删台词也能过 | 新增 SRC-D1（集级 block） | **P0（已修）** |
| script_chat.py | `missing_lines_repair` 定向返修 | 正常 / 边界 | ✅ 单测 | ① 只列缺句、不给段内预算，ep02 实测扩成 9 镜 84 秒并丢别的句子；② 一镜一人放不下时仍局部修 | ① 加段内镜数 / 时长预算 + 段内必须出现的全部台词；② 说话轮次 > 段内镜数时返回 None 改走整集返修 | P1（已修） |
| script_chat.py | `splice_shots` + `splice_reply_ok` | 正常 / 出错 | ✅ 单测 | 回复不从镜 a 开始也被接受，会丢镜 a 与台词（单测发现） | 新增 `splice_reply_ok`，批量与返修工具都用 | P1（已修） |
| script_chat.py | 多进程同时改同一会话（批量 + 返修工具 + 画布） | 出错 | ✅ 单测（批量 / 返修路径） | 各自“读入→修改→写回”，并发时后写的会覆盖先写的那一集 | 新增 session_file_lock / update_session（O_EXCL 锁文件，120 秒残留自动接管）；批量、返修工具、画布 /chat、/validate 写会话都改为加锁重读后追加，结束时只写回 validation | P1（已修） |
| script_chat_batch.py | 返修循环：缺台词与格式问题同时存在 | 正常 | ⚠ 真跑 ep03 | 补台词后直接进下一轮，3 轮都花在补台词上，格式问题（H3-A4 缺 Picture 1/2 句、H3-D7 一镜两人）一次没修，结束 block=10 | 同一轮补完台词、重新校验后接着做格式返修 | P1（已修） |
| script_chat_batch.py | 首写请求附“必须逐字出现的台词清单” | 正常 | ✅ 单测 | — | — | — |
| script_chat_batch.py | 拆两半（前半集头 + 前几镜，后半带集头只读） | 正常 | ✅ 单测 + ep01 真跑（17681 / 17723 prompt，finish=stop） | — | — | — |
| script_chat_batch.py | 续跑：已有稿未过校验 → 从已有稿接着修，不重写 | 边界 | ✅ 单测 | — | — | — |
| script_chat_batch.py | 预算：到上限不接新集；本地 Qwen 计 0 | 边界 | ✅ 单测 | Qwen 一度按 abliteration 单价计费（日志显示 $0.19） | 非 abliteration 单价为 0 | P2（已修） |
| script_chat_batch.py | 用量日志 / 拆半数 / 截断数 / 每 10 集进度 / `--export-tag` 导出 | 正常 | ✅ 真跑日志 | — | — | — |
| script_chat_batch.py | gpu3 隧道断开 | 出错 | ⚠ 真跑 | 18098 隧道掉线时，重试 3 次后该集记“返修失败”（ep03），批量继续下一集 | 续跑会从已有稿接着修；隧道自启属 D-38（总调度定） | P2 |
| script_chat_batch.py | 并发：1 路（留 1 槽给 Qwen 容器） | 正常 | ✅ | 6 路会饿死 LoRA/Blender 的 LLM 调用 | 改 1 路 | P1（已改） |
| script_chat_repair.py | 单镜返修 / 整集返修 / 缺台词定向返修 / 重试 | 正常 / 出错 | ✅ 单测 + ep01 真跑（block 2→0，台词 8/8） | 无重试，Qwen 容器重启时直接失败 | 加 4 次重试 | P2（已修） |
| validate_script_strict.py | 全部 H3 规则（lint_h3 含 lint_h3_extra）+ IMG-N1/L1/L2/T1 + QW-C1/C2/C3 升 block | 正常 | ✅ 单测 | — | — | — |
| validate_script_strict.py | H3-D7 非亲密镜升 block（项目方：一镜一人） | 正常 | ✅ ep01 真跑 | — | — | — |
| validate_script_strict.py | 否定字白名单与规则一致（22 词 + 勿 / 避免 / 去掉） | 边界 | ✅ 单测 | 白名单比规则多 11 个词 | 与规则逐一对齐 | P2（已修） |
| validate_script_strict.py | 不改 validate_qwen_script 的全局规则表（fredw-92 返修循环共用） | 边界 | ✅ 单测 | 第一版直接改了 V.RULES 级别 | 只在 strict_check_shot 里升级 | P1（已修） |
| validate_qwen_script / h3_lint | 时长：缺 `**时长**` / 不在 5–15 / S.SS 与查表不符 | 出错 | ✅ 单测（S1-W2、H3-A1、H3-A11 都是 block） | — | — | — |
| 规则文件 | 核心 ≤ 6000 token（实测 5708）；两条 ★ 原话原样；附录 13 节触发词 | 正常 | ✅ /tokenize 实测 | 核心曾经扩到约 3.6 万字 | 拆核心 + 附录 | P1（已修） |
| 规则文件 | 写作者看不到项目文档：条文自成一体 | 正常 | ✅ 审计第七节 | — | — | — |
| 全局 | heredoc 写 Python 时转义被 Git Bash 吃掉 | 出错 | ⚠ | 两次把 `\n` 写成真换行，script_chat.py 短暂语法错误（运行中的进程不受影响） | 改用 Edit / 临时文件拼接；改完都 py_compile | P1（已修，流程问题） |

## 还没做 / 已知限制

- 审计建议的机检 SC-02、SC-04–SC-28（景别差、运镜种类、对白字数与时长比、人数等）未实现：属新功能，封板期不做。
- 说话轮次按“说话人标签”数，原稿把同一人写成“顾沉 / 他”时会多算一轮，可能多走一次整集返修（只影响效率，不影响结果）。
- 画布剧本创作页不显示“哪些附录没带 / 拆两半”，只在批量日志里（前端布局已冻结）。
- `:8800` 需要重启才会加载本次的 script_chat.py 修复（对话框路径）；批量与返修工具不依赖它。
