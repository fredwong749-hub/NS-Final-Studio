# script_v2.json 字段说明（给 gpu3 渲染器 loader；fredw-92，2026-10-30）

文件：`data/import/script_v2.json`（笔记本生产剧本，由 `tools/import_script.py` 写）；同步到 gpu3 `nsfs_mirror/data/import/script_v2.json`。
模型：`packages/schema/ns_schema/script.py`（pydantic `ScriptImport`），字段以模型为准，本文只说渲染要用的。
总调度决定（2026-10-30）：gpu3 渲染器以后读这个文件，不再解析 `为他而骚（剧本和镜头）v2.md`。

## 顶层

| 字段 | 说明 |
|---|---|
| `sources[]` | `{path, version, episodes[]}`；某集的剧本版本 = 含该集且带 version 的最后一项，否则整本版本（S1 按集判断 ≥ v3） |
| `globals.lora_triggers[]` | `{trigger, kind: image\|video, description, file, strength:[lo,hi]\|null, starts}`。**触发词 → LoRA 文件 / 强度从这里查**。`lnwan_qi` 由导入自动注册（`config/auto_lora_triggers.json`：image，0.8） |
| `globals.image_suffix` | 剧本“每条 img 统一后缀”（全局画面风格） |
| `globals.base_negative` | 图像负向基线（H3 cfg 1 无负向，视频不用） |
| `globals.character_locks[]` / `references[]` / `decor_schedule[]` | 角色锁定描述 / 参考图 / 装修进度（按集） |
| `episodes[]` | 见下 |

## episodes[]

| 字段 | 说明 |
|---|---|
| `number` | 集号（int） |
| `high_intensity` | 标题带 🔴 → **整集成人，gpu3 不得渲染**（T24，项目方本地） |
| `music` / `music_bgm` | 本集配乐行原文 / 【BGM】英文（H3 non_diegetic_music 的本集默认，须过 H3-S3，否则 N/A） |
| `negative_extra` | 本集附加负向 |
| `shots[]` | 见下 |

## shots[]（镜头 id = `ep{episode:02d}-S{index}`）

| 字段 | 说明 |
|---|---|
| `episode`, `index` | 集号、镜号（从 1 起） |
| `adult` | **true → 跳过，不渲染**（显示“成人镜·待项目方”）。与 `high_intensity` 任一为真都不渲 |
| `img_prompt` | 首帧图像提示词原文（含开头的触发词） |
| `img_triggers[]` | 图像 LoRA 触发词（已含系统自动补的 `lnwan_qi`）；去 `globals.lora_triggers` 查文件和强度 |
| `motion_prompt` / `motion_triggers[]` | 动作原文 / 视频 LoRA 触发词 |
| `h3_prompt` | **H3 官方四块 FL2VA 全文**（剧本 **H3提示词**，逐字保留，多行）；为 null 时用 `motion_prompt` + `sound_h3` 由编译器生成草稿 |
| `h3_check` | 剧本 **H3校验** 原文；“暂缓（露骨内容）”= 红标，不渲 |
| `duration` / `duration_source` | 秒（3–15，缺省 10）/ script\|default。帧数 = `frames_for_seconds(duration)`（17k+5 格，24fps：5→124，8→192，10→243，12→294，15→362） |
| `sound` / `sound_h3` / `sound_intimate` / `music_cue` | sound 行原文 / 【H3 audio】英文（→ overall_soundscape）/ 【亲密声】/ 【配乐】中文提示（含“强度0/静默”→ 音乐 N/A） |
| `dialogue[]` | `{speaker_note, text, stage}`；`dialogue_raw` 原文；`voiceover` `{note, text}` |
| `decor_state` | 本镜装修状态（按 decor_schedule 推出） |
| `img_note`, `extras[]`, `source_line`, `adult_reasons[]` | 备注 / 其他段落 / 源行号 / 成人判定原因 |

## 建议：用编译结果，而不是自己拼

H3 最终提示词有几层合成：剧本原文 → 项目方画布覆盖（`ShotEdit.h3_prompt_override`）→ 配乐 `H3.resolve_music`（镜头修改 > 剧本 H3 > 静默 cue > 本集 BGM > N/A）→ 系统自动补 LoRA 触发词。
渲染器自己拼会和画布显示的不一致（以前“图片不一致”的根源之一）。可直接调用：

```python
from ns_agent.compiler import compile_shot   # services/agent + packages/schema 加进 sys.path
```

或者由笔记本按集导出编译结果（每镜 `image_prompt, image_loras, last_prompt, video_prompt, h3_frames, video_music, adult`），到时说一声我来出。
