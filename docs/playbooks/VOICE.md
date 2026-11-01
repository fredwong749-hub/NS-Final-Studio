# 角色手册：VOICE 配音 / 音色

- **负责连接**：P4-P9（Spec 音频字段 → 声音）、P8-P9（H3 原声 → 声音）
- **现在由谁做**：回听、度量、试听表、单句换音色都是代码。挑音色由项目方定。

## 输入
- 每镜 H3 原声（视频音轨）；
- 剧本台词，只用来做字符比对；
- `config/voices.json`；
- 项目方给的参考音频（wav）。

## 输出
- 试听表 `data/ab/voice_fix/table.md`，内容包括 CER、基频中位、起伏、语速；
- 换音色后的版本：`tools/voice_convert_shot.py` 只替换该句时间段，画面和嘴型不动；
- 确定后的 `config/voices.json` 条目。

## 步骤
1. 对白默认用 H3 原声（K-EDT-001）。合成时 SenseVoice 回听 CER >0.35 的镜头才用 TTS 兜底。
2. 声音有问题（例如生硬、念错）时：
   - 先换种子重出并回听：`.venv/Scripts/python.exe tools/ab_voice_fix.py render --per-shot 2`，然后 `analyze`；
   - 仍不行，就单句换音色：`tools/voice_convert_shot.py <镜> --reference <wav>`，参考音频要由项目方给。
3. 旁白 / 独白（K-EDT-I02）：
   - 每个有独白的角色要有独立的 narrator 音色：年轻都市感、语速自然、听感年龄和人物表一致；
   - 独白时长 ≤ 所在镜长 − 0.3 s，否则在 SS-A4 拦下；
   - 由系统出试听候选，项目方挑定后再写入 voices.json。
4. Ref2VA 可以用 `<Audio N>` 做音色参考，参考音频约 4 秒（h3_comfy_expert §5）。

## 判定标准
- 回听 CER ≤0.35；
- 画内对白嘴部相关 ≥0.3；
- 旁白听感年龄和人物表的差距 ≤10 岁。

## 产生的规则放在哪里
`knowledge/rules/edit.yaml`、`chain_v1.yaml`（K-EDT-I02），link 填 P4-P9 / P8-P9。

## 什么时候需要人
- 挑音色、提供参考 wav；
- voice_conversion 的开关。
