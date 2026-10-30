# 剧本的 5 个入口（封板说明，X-2）

系统对剧本**只收发、只查格式**（tools/validate_qwen_script.py），不读不改内容；导入只在项目方确认后执行。
所有入口最终都汇到同一个导入流程：`tools/import_script.py` → `data/import/script_v2.json` → 重建状态时间线。

| # | 入口 | 在哪 | 做什么 | 产物 / 去向 |
|---|------|------|--------|-------------|
| 1 | **剧本输入**（input） | 画布 `?view=import` 页面上方「剧本输入」 | 粘贴文本或上传 .md / .txt，原样存成草稿（只统一换行为 LF）；删除移到 `.trash/` 可找回 | `data/staging_input/<名>.md` → 自动成为入口 2 的导入候选（来源标「剧本输入」） |
| 2 | **导入列表**（inbox） | 同页下方「待导入的剧本稿」（`/api/script-inbox`） | 列出全部候选（草稿、`data/staging_v3/`、Qwen 信箱交付、剧本创作对话定稿），可下载原文件；① 校验格式 → ② 勾选「我是项目方」→ ③ 导入。导入前自动备份到 `data/import/backups/`，失败自动恢复原剧本；**默认按集合并**（只替换新稿里出现的集号，其余集保持）；记 `data/import/import_log.jsonl` | 新的 `data/import/script_v2.json`；API 发现文件变化后自动换上新剧本 |
| 3 | **剧本创作对话**（chat） | 画布 `#/script-chat`（fredw-c8，T58） | 项目方输入大纲，写作模型（默认 gpu3 Qwen）按规则写剧本；回复里的整集按集号覆盖进本会话草稿，并做格式校验 | `data/script_chat/<会话>/script.md` → 入口 2 的候选（来源标「剧本创作对话」） |
| 4 | **A/B 对比**（ab） | 画布 `?view=ab`（`/api/script-ab`） | 任选两份候选，同集逐镜并排看剧本原文、H3 提示词、首尾帧提示词和各自渲染（`data/ab_renders/`）；项目方点选 A / B，只追加记录、不打分 | `data/import/ab_choices.jsonl`（选定后仍走入口 2 导入） |
| 5 | **命令行**（CLI） | 仓库根目录 | `tools/import_script.py --script <稿> [--merge-base <底稿 json>] [--source-version v3] [-o 输出]`：导入；`--merge-base` = 只替换新稿里的集；`--source-version` = 文件名里没有 vN 时（如 `script.md`）标版本，S1 按集判版本要 ≥ v3。`tools/s1_gate.py`：查看 / 记录 S1 闸门（校验器错误数、项目方 G3 原话，只能由项目方/协调写），并提示源文件导入后是否又改过。`tools/export_qwen_script.py <script.md> --episodes 1-15 --rules-tag …`：把 Qwen 剧本按集 + 全本原样复制到 `为他而骚短剧/Qwen剧本/` 供下载 | 同入口 2 |

注意
- 画布导入（入口 2）目前**不传 `--source-version`**：`script.md` 这类文件名里没有版本的稿，经画布导入后该集版本为空，
  S1 按集判会当成 < v3。需要时用命令行带 `--source-version` 导入（见 debug_api.md 的提案）。
- 剧本源文件导入后又被改过时，SOP 状态（`/api/sop/status`、`/api/sop/episode/{n}`）会出 warn 级提醒
  「剧本源文件导入后又改过，需重新导入」并列出路径；不拦镜头，重新导入仍需项目方在入口 2 确认。
