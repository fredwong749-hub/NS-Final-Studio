# 视觉圣经：项目方画面要求的系统化整理

> 配置文件：`config/visual_bible.toml`（本剧）｜模板：`templates/visual_bible.template.toml`（新故事复制填写）
> 需求来源：`docs/REQUIREMENTS.md`（每条规则在 toml 里注明编号）

## 为什么要有它

项目方的画面要求是在对话里陆续给出的（Leica 锐利、浓郁色调、f/1.2 焦外、无字幕、真人感、漆皮抹油镜面、筷子细跟、林晚日常性感穿搭、5cm 水晶甲、妆容精致……）。过去它们分散在编译器常量、剧本后缀和各个 agent 的说明里，改一处漏一处。现在统一放进一个文件：**改规则只改 toml，所有环节都读它。**

## 结构（每一节管什么、在哪里生效）

| 节 | 内容 | 生效环节 |
|---|---|---|
| `[look]` | 镜头（Leica/85mm f/1.2）、焦外、浓郁暖色调、无文字、色调参考图与匹配强度、剧本光源优先 | 首帧/尾帧提示词末尾；出图后色调匹配 |
| `[look.video]` | 视频风格句、结尾固定句、视频负面词 | 视频提示词 |
| `[realism]` | Base 定稿、步数、CFG、1.5MP + 0.30 第二遍、纹理 VAE、写实 LoRA、禁用 LoRA、禁用词、真实皮肤措辞 | 出图工作流参数 |
| `[[materials]]` | 关键词触发的材质规则：漆皮抹油镜面、12cm 筷子细跟 | 编译器追加到提示词，并作为评分必查项 |
| `[[shot_rules]]` / `[shot_rules_safe]` | 纠正器：特写、暗场、非成人镜头（衣装完整、无裸露，不保守） | 编译器 |
| `[characters.*]` | 身份来源、写实母版参考图、参考说明句、美甲、高跟、穿搭规则、妆容调色板与原则、按剧情选妆容底板 | 参考图选择、提示词人物段 |
| `[assembly]` | 首帧拼装顺序、尾帧保持句、剧本原文一字不改、导演加强只放项目方内容 | 编译器 / 画面说明层 |
| `[generation]` | 每轮候选数、轮数、评分权重、通过线、非成人裸露一票否决 | 多轮择优 |
| `[classification]` | 未成年外观硬规则、成人人工指定文件 | 编译器 |
| `[looks]` | 造型注入开关 `inject`（默认 false）与注入槽位 `slots` | 编译器（P2，只对项目方确认的集） |

## 三个使用者

1. **编译器 / 画面说明层**（`services/agent/ns_agent/compiler.py`、`frame_spec.py`，加载器 `ns_agent/bible.py`）：T06 起直接读 toml——`[look]` 风格兜底 `fallback_suffix`、Leica 句 `lens_template`/`lens_default`/`lens_skip_if`、`style_negative`、`[look.video]`；`[realism].banned_words`（只从系统追加的文字里去掉，剧本原文与导演加强不改，原文命中记在 compiled.json `banned_hits`）；`[[materials]]`（按条目顺序追加；`character` 指定时该角色入镜才加）；`[[shot_rules]]`、`[shot_rules_safe]`；`[characters.*]` 的 `name`/`detect`/`detect_she_with_trigger`/`identity_extra`；`[assembly].last_frame_keep`；`[classification]` 的 `minor_guard`（只能追加，内置“未成年人外观”永远在）与 `overrides`；`[looks]` 造型注入开关。缺键时退回 compiler.py 里的原常量。项目根目录按 `NS_PROJECT_ROOT`。
2. **导演 agent / 出图流水线**（`services/render_router`、gpu3 渲染器）：读 `[realism]`、`[look]`、`[generation]` 决定模型、LoRA、分辨率、色调匹配和评分。
3. **剧本写入者**（gpu3 会话）：剧本头部说明与 toml 保持一致；剧本只写剧情与画面，通用画面规则不重复写进每一镜。

## 新故事怎么用

1. 复制 `templates/visual_bible.template.toml` → `config/visual_bible.toml`。
2. 填 `[project]`（剧本路径）、`[look].color_reference`（色调参考图）、每个角色的 `[characters.<id>]`。
3. `[realism]`、`[[shot_rules]]`、`[assembly]`、`[generation]` 是本剧验证过的默认值，可直接沿用。
4. 材质、穿搭、美甲等故事专属规则，照 `[[materials]]` 的格式加条目。
5. 运行导入：`uv run python tools/import_script.py --script <剧本>`。

## 规则版本（T06）

改 toml（或剧本、造型、镜头归属）后 `bible_version` 变化；每个 compiled.json 与新 take 都记录它。
查看改动影响了哪些镜头：`uv run python tools/bible_diff.py <旧版本>`；预览造型注入：`uv run python tools/bible_diff.py --inject-preview`。
详见 docs/state_timeline.md §一。
