"""
Qwen 剧本格式校验（docs/qwen_writing_contract.md）。只查格式，不评价内容，不改写任何文本。

    .venv\\Scripts\\python.exe tools\\validate_qwen_script.py <script.md> [--episode N] [--json]
        [--repair-dir DIR] [--names "Lin Wan,Gu Chen"]

- 解析：真实导入器 ns_agent.importer.script_md.import_script。
- H3 机检：真实 ns_schema.h3_lint.lint_h3（不复写规则）。唯一例外 H3-S3：项目方 2026-10-30 新规
  （non_diegetic_music = N/A 或 1–3 句英文，乐器/速度/节奏/强弱，无抽象情绪词），lint 的 H3-S3 结果被丢弃，
  由本文件 check_music 代替。
- 其它字段检查：rule_ids.md 有编号的用原编号（R-C1、S1-W1/W2/W3/W4/W7），没有的用契约本地编号 QW-*。
- 每个不通过的镜头输出一段“返修请求”（只引用格式规则原文，不提内容）。

退出码：0 = 无 block 级失败；1 = 有 block 级失败；2 = 解析不出任何集。
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "packages" / "schema", ROOT / "services" / "agent"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from ns_agent.importer.script_md import (  # noqa: E402
    CHARACTER_ID_RE, LINK_VALUES, SCENE_ID_RE, _code_block_after, character_tables, import_script, scene_tables,
    shot_cap, EPISODE_SECONDS,
)
from ns_schema import h3_lint as L  # noqa: E402
from ns_schema import llm_output_check as LOC  # noqa: E402
import importlib.util as _ilu  # noqa: E402

# ITERAUDIT 11-01（项目方：“发现 bug、找到 solution 后把规则写到系统 code，剧本 LLM 好自动改进”）：写作方 QW-W* 机检。
# 级别 WL.WRITER_LINT_LEVEL：默认 warn（导入关口）；写作链路（p4_adapter / qwen_repair_loop）设 block → 进返修环
_wl_spec = _ilu.spec_from_file_location("ns_writer_lints", ROOT / "tools" / "qa" / "writer_lints.py")
WL = _ilu.module_from_spec(_wl_spec)
_wl_spec.loader.exec_module(WL)
# ACTING 11-01（R11-2/3/6/8/9）：表演 / 视线 / 节奏 / 多人 QW-A1–A5（tools/qa/acting_lints.py）；级别跟 WL.WRITER_LINT_LEVEL
_al_spec = _ilu.spec_from_file_location("ns_acting_lints", ROOT / "tools" / "qa" / "acting_lints.py")
AL = _ilu.module_from_spec(_al_spec)
_al_spec.loader.exec_module(AL)
# RSI 11-01（R11-4 鞋不一致；缺陷猎捕 DH-S20）：VQA 的 VQ-W1（看得见脚的景别鞋写进 img，K-WRT-V06）原来只在 tools/vqa 里定义、
# 写作链路从没跑过 → 接进来；级别跟 WL.WRITER_LINT_LEVEL（导入关口 warn / 返修环 block）
_vq_spec = _ilu.spec_from_file_location("ns_vqa_script_lint", ROOT / "tools" / "vqa" / "script_lint.py")
VQL = _ilu.module_from_spec(_vq_spec)
_vq_spec.loader.exec_module(VQL)

try:   # 剧本对白 → lint 参数（seconds / dialogue / offscreen / monologue），与出视频流水线同一映射
    from ns_agent.h3_prompt import lint_inputs as _lint_inputs
except Exception:  # noqa: BLE001  其它会话可能正在改 h3_prompt.py；退回同义的本地映射
    _lint_inputs = None

OFFSCREEN_MARKS = ("画外", "电话", "语音", "OS", "V.O", "VO")
POSSESSIVE_PLACES = r"(?:的)?(?:家|公寓|公司|办公室|车|楼下|楼|别墅|卧室|浴室|客厅)"   # 同 ns_agent.compiler.POSSESSIVE_PLACES
REQUIRE_SCENES = False   # 严格校验（tools/validate_script_strict.py main）置 True
# R3（docs/production_rules_v3.md）：v3 字段（人物表、出场人物、用到的场景、造型、人物、衔接）的检查。
# False（导入关口）= 剧本里一个 v3 字段都没有时不查（旧剧本照常导入，同 S-back 的场景规则）；写了任一 v3 字段 = 声明 v3 格式，按表中级别查。
# 严格校验（剧本创作）置 True：总按表中级别查
REQUIRE_V3 = False


def lint_inputs(shot) -> dict:
    if _lint_inputs is not None:
        return _lint_inputs(shot)
    off = [d.text for d in shot.dialogue
           if d.text and any(m in f"{d.speaker_note or ''}{d.stage or ''}" for m in OFFSCREEN_MARKS)]
    return {"seconds": shot.duration or 10,
            "dialogue": [d.text for d in shot.dialogue if d.text and d.text.strip()],
            "offscreen": off,
            "monologue": [shot.voiceover.text] if shot.voiceover and shot.voiceover.text else []}


# ------------------------------------------------------------------ 规则原文（返修请求引用；格式规则，不含内容）
RULES: dict[str, tuple[str, str]] = {
    "QW-E1": ("block", "集标题行写成 `## ep<数字>《<标题>》`，紧接一行非空的 `**剧情**：`"),
    "QW-E2": ("block", "镜号从 1 连续递增；镜数 6 ≤ n ≤ max(8, 说话轮次 + 独白段数, ⌈各镜时长之和 ÷ 6⌉)（K1 + G29：单镜 ≤6 秒要装得下总时长）"),
    "QW-E3": ("block", "各镜 `**时长**` 之和 60–120 秒，超出不过（项目方 11-01 21:4x：“改成 60–120 秒”，L-092 / D-SCR-08）"),
    "QW-F0": ("block", "每行都要属于一个字段：`**标签**：值` 一行写完，不要写无标签的散行"),
    "QW-C1": ("warn", "motion 在触发词之后以英文运镜指令开头，运镜只从 config/director/camera_moves.yaml 里 enabled、且本剧可用的"
                      "运镜中选（写运镜 id、英文名或英文别名，如 `camera push in <中文运镜词>，`、`static shot，`；词表是唯一来源，"
                      "这里不另列）"),
    "QW-C2": ("warn", "img 写出景别词（远景/全景/中景/近景/特写/极近特写…）"),
    "QW-C3": ("warn", "motion 至少一个可观察的表情线索短句（眼神/嘴角/睫毛/呼吸/抿/笑…，≤28 字）"),
    "QW-S1": ("warn", "`【H3 audio】` 与 H3 提示词里的 `overall_soundscape` 逐字一致"),
    "R-C1": ("block", "必备要素齐全：img、motion、sound、sound 里的 `【配乐】` cue、本集 `**配乐**` 的 `【BGM】`（写在镜1 之前）"),
    "S1-W1": ("block", "motion 是一个连续镜头：无 切/转场/cut/剪辑，最后一个 `——` 之后写结束状态"),
    "S1-W2": ("block", "`**时长**：<整数>秒`，4–15 秒，必须写（K4；系统不再默认 10 秒）"),
    "S1-W3": ("block", "`【H3 audio】` 是 1–4 句英文、一段，不含台词/<d>、无否定词、无中文"),
    "S1-W4": ("block", "每句台词写成 `（<说话人>）“<台词>”`，多句用 `／` 分隔；img、motion 里不出现双引号台词"),
    "QW-Q1": ("warn", "img、motion 不用引号包台词（S1-W4）；引号只用于画面里真实可见的文字"),
    "S1-W7": ("block", "每镜都有 `**H3提示词**` 字段（标签单独一行，正文放在 ```text 代码块里）"),
    "H3-S3": ("block", "non_diegetic_music：本镜有配乐写 1–3 句英文（乐器、速度、节奏、强弱变化），一段，无中文、无 <d>、"
                       "无抽象情绪词；本镜没有配乐写 `N/A`（2026-10-30 新规）"),
    "H3-D4": ("block", "H3 提示词不写人名、不写触发词，人物用 (S1)/(S2) 编号 + 外貌指代；不用双引号"),
    # S1 场景（fredw-92/S-back，契约 §1.2 / §2.7）：只查结构与一致性，不评内容
    "QW-SC1": ("block", "每镜在 `**镜N｜img**` 下一行写 `**场景**：<场景id>｜<本镜场景细节>`"),
    "QW-SC2": ("block", "场景 id 写成 `sk_<小写英文、数字、下划线>`（如 sk_office_lobby），与 data/scenes.json 同一套 id"),
    "QW-SC3": ("block", "镜头的场景 id 必须在全剧场景表或本集场景表里"),
    "QW-SC4": ("block", "场景表写成 `**本集场景表**：` + 表头 `| 场景id | 名称 | 空间描述 | 时段 | 光线 | 固定陈设 |` + "
                        "分隔行 + 每场景一行（6 格，格内不用 |，每格都填）"),
    "QW-SC5": ("block", "同一场景 id 再次出现在场景表里时，各字段与第一次定义逐字相同（只写新场景；沿用的场景不要改写）"),
    "QW-SC6": ("warn", "`**场景**` 行在 ｜ 之后写本镜场景细节（机位看到的部分、道具状态）"),
    # fredw-92 2026-10-31 定：人物表 / 场景表全剧一份、逐集继承；继承来的（全局头全剧表）登记不得改写
    "QW-SC9": ("block", "全局头 `**全剧场景表**` 里已登记的场景（继承来的）各格逐字照抄，不改写；本集场景表只写新场景"),
    "QW-P7": ("block", "全局头 `**全剧人物表**` 里已登记的角色（继承来的）EN外貌短语 / VOICE声线短语 / 各格逐字照抄，不改写；"
                       "本集人物表只写新角色"),
    # R3（docs/production_rules_v3.md §1.1–1.3）：只查结构与字符串，不评内容
    "QW-G1": ("warn", "全局头有 `**每条prompt统一前缀**` 代码块，至少一行 `【角色名】…`（项目方维护）"),
    "QW-G2": ("warn", "`**LoRA 触发词表**` 代码块只分 `图像LoRA` / `视频LoRA` 两段，每行缩进写 `<trigger>  <说明>`，"
                      "trigger 只用英文字母、数字、下划线"),
    "QW-P1": ("block", "人物表写成 `**全剧人物表**：` / `**本集人物表**：` + 表头 `| 角色 | 角色id | 中文外貌句 | EN外貌短语 | "
                       "VOICE声线短语 |` + 分隔行 + 每人一行 5 格（格内不用 |）"),
    "QW-P2": ("block", "角色名全剧唯一；角色id 照抄全局头已登记的 id，新角色写 "
                       "`ch_<小写英文数字下划线>`（V2 女主等项目方指定资产的角色可用 `lead_<…>`，如 lead_f），一个 id 只对应一个角色名"),
    "QW-P3": ("block", "EN外貌短语：一条英文名词短语，只写身份（年龄、性别、发色长度与刘海、脸 / 肤色 / 体型），不写服装；"
                       "无中文、无否定词、无双引号、不含人名和触发词"),
    "QW-P4": ("block", "VOICE声线短语：一条英文短语，含 voice（音色、音区、语速），无中文、无否定词、无双引号；"
                       "对白或 🎙 里出现的每个说话人都要有"),
    "QW-P5": ("block", "同一角色再次出现在人物表里时各格与第一次逐字相同（只登记新角色；已登记的不要改写）"),
    "QW-P6": ("warn", "中文外貌句六项，用全角 ｜ 分隔：年龄段｜体型｜发型发色｜服装主色｜标志物｜不可变特征；"
                      "有系统角色锁的角色写 `系统锁`"),
    "QW-SC7": ("warn", "img 第⑤项“场景”照抄场景表的名称或至少一件固定陈设"),
    "QW-SC8": ("block", "场景表的 空间描述、固定陈设 不写人物（不出现角色名、她、他）；固定陈设 1–3 件，用中文逗号或顿号分隔"),
    "QW-E4": ("block", "集头 `**出场人物**：<角色名>、<角色名>…`：每个名字已登记（人物表或角色锁），"
                       "且正好等于本集各镜 `**人物**` 行里所有角色"),
    "QW-E5": ("block", "集头 `**用到的场景**：sk_<id>、sk_<id>…`：每个 id 在场景表里，且正好等于本集各镜 `**场景**` 的 id"),
    "QW-E6": ("block", "本集任一镜“在画 / 局部”的角色都有一行 `**造型｜<角色名>**：服装=<…>｜鞋=<…>｜妆=<…>｜发=<…>｜甲=<…>｜"
                       "饰品=<…>｜EN=<English outfit phrase>`；槽位名只用 服装/鞋/妆/发/甲/饰品/其他 + EN；服装、鞋、妆、发、EN 必填；"
                       "EN 无中文、无否定词、无双引号"),
    "QW-E6b": ("warn", "造型槽位里的已有单品照抄 data/looks/wardrobe.json 的名称；新单品写 `新：<颜色+款式+材质>`；"
                       "与上一集相同写 `沿用`"),
    "QW-E7": ("block", "换装行 `**造型｜<角色名>｜镜<N>起**：` 的镜N 在本集存在；该镜 img 备注或 motion 写明换装"),
    "QW-CH1": ("block", "每镜在 `**场景**` 下一行写 `**人物**：<角色名>（在画｜<左/中/右>｜<前/中/后>）、"
                        "<角色名>（局部｜<部位>｜<左/中/右>）、<角色名>（画外）`；只列入镜或发声的人；不写“她 / 他”"),
    "QW-CH2": ("block", "`**人物**` 行的名字都已登记（人物表或角色锁）"),
    "QW-CH3": ("block", "每镜 在画 + 局部 的角色不超过 3 人"),
    "QW-SZ2": ("warn", "局部特写（手 / 脚 / 腰…）只写这个局部：不写靠近脸的部位（肩头 / 锁骨 / 颈 / 下颌 / 胸口）和脸部写实套话（眼睛为真实人眼大小）；要写就写清画面上沿停在哪里（例：画面上沿在锁骨以下，不出现脸）"),
    "QW-SZ1": ("warn", "特写 / 大特写只容一张脸为主体：两人都在画写近景或中近景；脸部特写不同时写鞋踩地 / 鞋尖鞋跟（要拍鞋就写鞋的特写，不写脸）"),
    "QW-CH6": ("warn", "人物行写“局部”的角色，img 里不写他的脸 / 五官 / 头发；脸或头发入画的角色在人物行写“在画”"),
    "QW-CH4": ("block", "img 与结束状态里出现的角色名都在 `**人物**` 行（在画或局部）；人物行在画的人在 img 里写出名字"),
    "QW-CH5": ("block", "对白和 🎙 的说话人都在 `**人物**` 行；人物行标“画外”的人，对白括号里带画外标记（画外/电话/语音/OS/VO）"),
    "QW-LK1": ("block", "每镜在 `**人物**` 下一行写 `**衔接**：<接力 / 同场换机位 / 换场 / 接上一集>｜承：<延续项>`；"
                        "镜1 只能写 换场 或 接上一集；接力时 `承：` 必填"),
    "QW-LK2": ("block", "接力 / 同场换机位：场景 id 与上一镜相同；接力时本镜 img 景别与上一镜结束状态景别最多差一档"),
    "QW-LK3": ("block", "换场：场景 id 与上一镜不同，或 img 备注 / motion 写了换段词（次日、第二天、翌日、闪回、回忆、梦境、"
                        "数日后、几天后、一周后、当晚、句首“周X”）"),
    "QW-C4": ("warn", "motion 的英文运镜与 H3 正文里的运镜是同一种"),
    "QW-K1": ("block", "结束状态（最后一个 `——` 之后）以景别词开头"),
    "QW-K2": ("block", "结束状态景别与 img 景别最多差一档；运镜为 static / pan / tilt / truck 时景别相同"
                       "（大远景 < 远景 < 全景 < 全身 < 中景 < 中近景 < 近景 < 特写 < 大特写）"),
    "QW-K3": ("warn", "朝向只用 背影 / 背对 / 背抵 / 后脑 / 侧脸 / 侧影 / 侧面；img 与结束状态朝向一致（motion 主动作写了转身除外）"),
    "QW-M1": ("block", "【配乐】<动作>，强度<0–3>，<避让>：动作只用 进入/延续/渐强/推到高点/撤到静默/落下/重音；"
                       "避让只用 对白避让/独白避让/无需避让；有台词写对白避让，有 🎙 写独白避让"),
    "QW-D1": ("block", "对白括号以已登记的角色名开头：`（<角色名>，<语气 / 画外标记>）“…”`；画外标记只用 画外/电话/语音/OS/VO"),
    "QW-D2": ("block", "🎙 写成 `**🎙（<角色名>，<说明>）**：`，角色名已登记且人物表里有 VOICE声线短语"),
    "IMG-C2": ("warn", "img 长度只统计（上限待 A/B 实测，C2），暂不提示"),
}
RULES.update(WL.RULES)   # QW-W1–W4（tools/qa/writer_lints.py）
RULES.update(AL.RULES)   # QW-A1–A8 / QW-AX1（tools/qa/acting_lints.py，ACTING 11-01；A6–A8、AX1 SCRIPT-RSI 11-01；AX1 原名 QW-D1，与对白说话人规则撞号，RSI 改名）
RULES.update(VQL.RULES)  # VQ-W1（tools/vqa/script_lint.py，VQA K-WRT-V06；RSI 11-01 接线）
# h3_lint 规则的原文摘要（docs/audit/rule_ids.md）
LINT_RULE_TEXT = {
    "H3-A1": "第一行是官方对齐句，逐字；Picture 2 (from Shot 1)；S.SS = 按 **时长** 查表的帧数/24（两位小数）",
    "H3-A2": "对齐句后恰好空一行；integrated_multimodal_description → overall_soundscape → non_diegetic_music，各空一行，每个字段一段",
    "H3-A3": "正文以 [Shot 1] 开头，只有一个镜头，[Shot 1] 后不写时间戳",
    "H3-A4": "第一句含 “established by Picture 1”；最后一句 “settles into … established by Picture 2 at the end of the shot.”",
    "H3-A5": "<d> 外不写否定词（no/not/never/without/don't/n't…）",
    "H3-A6": "正文写连接两帧的动作路径，不复述两张静帧",
    "H3-A7": "<d> 外全部英文，不出现中文字符",
    "H3-A8": "[Shot 1] 后以 “Live-action, cinematic, shallow depth of field,” 开场；不写图像风格/画质词",
    "H3-A9": "只写看得见、听得见的内容；不写剧情概述和抽象情绪词",
    "H3-A10": "运镜写成句中自然动作，官方词汇与幅度/速度词，每镜一个运镜",
    "H3-A11": "时长 4–15 s（K4）；动作量按正常速度在 N 秒内做完，并留出最后约 1 秒仍在进行的动作（项目方 2026-10-31“改成正常节奏”）",
    "H3-A12": "全文 ≤7000 字符（官方 API 硬上限）",
    "H3-D1": "台词写成 <d>[Chinese] 原文</d>，<d> 里只有语言标签和原文",
    "H3-D2": "每个 <d> 前写 (S1)/(S2) 编号，按首次开口顺序；音色语气写在 <d> 外",
    "H3-D3": "<d> 台词与 **对白** 逐条、逐字（含标点）、同顺序一致",
    "H3-D4": "不用双引号；不写人名",
    "H3-D5": "画外台词写 “says in an off-screen voiceover”，</d> 后紧跟 “… lips remain closed.”",
    "H3-D6": "🎙 内心独白不进 H3",
    "H3-D7": "亲密镜只有 (S1) 一个说话人，soundscape 不写男性声音",
    "H3-D8": "说话人首次出现写清年龄、性别、是否在画面内、音色、语速",
    "H3-D9": "<cutoff>/<scenetrans> 只在剧本标注处使用",
    "H3-S1": "overall_soundscape 写 1–4 句英文、一段，不含 <d>",
    "H3-S2": "overall_soundscape 不写 N/A",
    "P-B1": "帧数在 17k+5 网格、107–362（4–15 s），并等于按 **时长** 查表的值",
    "H3-X1": "锚点句（integrated_multimodal_description 第一句）逐字包含每个在画角色的 EN外貌短语（人物表）与本集造型 EN（造型行）",
    "H3-X2": "首句与末句不放 <d>（台词放在中间的句子）",
    "H3-X3": "每个说话人第一次出现的那一句逐字包含其 VOICE声线短语（人物表）",
    "H3-X4": "人物行里不在画（画外 / 只被提到）的角色，其 EN外貌短语不得出现在 H3 正文（写进去 = 让他在场）",
    "H3-X5": "<d> 外不写角色名（中文名 / 拼音）；H3 不认识名字，用 EN外貌短语指代",
    "H3-X6": "<d> 里只写台词原文：不带说话人、语气、舞台提示（说话人和语气写在 <d> 前）",
}

# 抽象情绪 / 情绪功能词（官方 §4.7：“do not use abstract mood words or explain the emotional function of the score”）
MOOD_WORDS = re.compile(
    r"\b(mood(?:y)?|emotion(?:al|ally|s)?|feel(?:s|ing|ings)?|sad(?:ness)?|happ(?:y|iness)|joy(?:ful)?|romantic|"
    r"romance|melanchol(?:y|ic)|nostalgi(?:a|c)|tense|tension|suspense(?:ful)?|myster(?:y|ious)|ominous|eerie|"
    r"haunting|dream(?:y|like)|hopeful|uplifting|heartwarming|heartbreaking|bittersweet|sentimental|tender|"
    r"passionate|sensual|seductive|sexy|erotic|intimate|longing|yearning|lonely|loneliness|sorrow(?:ful)?|"
    r"cheerful|playful|dramatic|epic|dark(?:ness)?|anxious|anxiety|fear(?:ful)?|dread|desire|lust(?:ful)?|"
    r"atmospheric|atmosphere|evok(?:e|es|ing)|convey(?:s|ing)?|symboli[sz](?:e|es|ing)|reflect(?:s|ing) her|"
    r"reflect(?:s|ing) his|underscor(?:e|es|ing) (?:her|his|the) (?:feeling|emotion))\b", re.I)
STATIC_SHOT_RE = re.compile(r"static shot\b", re.I)   # K14：官方 §4.3 同形（static camera 过渡期仍认）
TRIGGER_LIKE = re.compile(r"\b(?:[a-z]+\d+[a-z0-9_]*|pose_[A-Za-z0-9_]+)\b")
CUT_RE = re.compile(r"切到|切至|切换|转场|剪辑|\bcut\b", re.I)
QUOTE_IN_PROMPT = re.compile(r"[“\"「][^”\"」]{2,}[”\"」]")

try:   # 画布实际用的景别 / 运镜 / 表情解析（只读引用）
    from ns_api.shotinfo import EXPR_CUES, MOVE_EN, SIZE_WORDS, CLAUSE_SPLIT, strip_triggers as _strip_trig
except Exception:  # noqa: BLE001
    SIZE_WORDS = ("大远景", "远景", "大全景", "全景", "中全景", "全身", "中景", "中近景", "近景", "极近特写", "大特写",
                  "特写", "极近")
    MOVE_EN = re.compile(r"((?:extreme )?slow motion|camera [a-z ]+|static camera|handheld(?: follow)?|orbit|"
                         r"push in|pull (?:back|out)|tracking(?: shot)?|dolly [a-z]+|pan (?:left|right)|"
                         r"tilt (?:up|down)|crane [a-z]+|zoom [a-z]+)", re.I)
    EXPR_CUES = ("眼神", "眼睛", "睫毛", "瞳孔", "嘴角", "嘴唇", "抿", "笑", "泪", "脸红", "呼吸", "喘", "皱眉", "抬眼",
                 "瞥", "表情", "神情")
    CLAUSE_SPLIT = re.compile(r"[，,。；;！!？?]|——")

    def _strip_trig(text):
        return re.sub(r"^([a-z0-9_]+[，,])+", "", text or "", flags=re.I).strip()


def _issue(rule_id: str, detail: str, level: str | None = None, field: str = "") -> dict:
    lvl = level or RULES.get(rule_id, ("block", ""))[0]
    return {"rule_id": rule_id, "level": lvl, "field": field, "detail": detail}


def _english_ok(text: str) -> bool:
    return not L.CJK_RE.search(text or "")


# ------------------------------------------------------------------ 新规 H3-S3

def check_music(music: str) -> list[str]:
    """non_diegetic_music（2026-10-30 新规）。返回问题列表，空 = 通过"""
    m = (music or "").strip()
    if m == "N/A":
        return []
    if not m:
        return ["non_diegetic_music 为空（没有配乐写 N/A）"]
    probs = []
    if "\n" in m:
        probs.append("要写成一段")
    if "<d>" in m:
        probs.append("不写 <d>")
    if L.CJK_RE.search(m):
        probs.append("要用英文")
    n = len(L._sentences(m))
    if not 1 <= n <= 3:
        probs.append(f"应为 1–3 句，现有 {n} 句")
    moods = sorted({x.group(0).lower() for x in MOOD_WORDS.finditer(m)})
    if moods:
        probs.append(f"出现抽象情绪/功能词：{'、'.join(moods)}（只写乐器、速度、节奏、强弱变化）")
    return probs


# ------------------------------------------------------------------ 逐镜

def check_shot(shot, ep, triggers: set[str], names: list[str]) -> list[dict]:
    out: list[dict] = []
    if not shot.img_prompt.strip():
        out.append(_issue("R-C1", "缺少 img（`**镜N｜img**：` 后为空）", field="img"))
    if not shot.motion_prompt.strip():
        out.append(_issue("R-C1", "缺少 `**motion**：`", field="motion"))
    if not shot.sound.strip():
        out.append(_issue("R-C1", "缺少 `**sound**：`", field="sound"))
    elif not shot.music_cue:
        out.append(_issue("R-C1", "sound 行缺少 `【配乐】` 段（或为空）", field="sound"))

    # 时长
    if shot.duration_source != "script":
        out.append(_issue("S1-W2", "缺少 `**时长**：N秒`，或不是 4–15 的整数秒", field="时长"))
    elif not 4 <= shot.duration <= 15:
        out.append(_issue("S1-W2", f"时长 {shot.duration} 秒，不在 4–15 秒", field="时长"))

    # motion：一个连续镜头 + 结束状态
    mo = shot.motion_prompt
    if mo:
        if "——" not in mo:
            out.append(_issue("S1-W1", "motion 里没有 `——`（最后一个 —— 之后写结束状态）", field="motion"))
        if CUT_RE.search(mo):
            out.append(_issue("S1-W1", f"motion 出现剪辑词：{CUT_RE.search(mo).group(0)}", field="motion"))
        body = _strip_trig(mo)
        if not (MOVE_EN.match(body) or STATIC_SHOT_RE.match(body) or motion_move(mo)):
            out.append(_issue("QW-C1", "motion 触发词后不是英文运镜指令开头（画布取不到“运镜”）", field="motion"))
        clauses = [c.strip(" 、") for t in (_strip_trig(mo), _strip_trig(shot.img_prompt))
                   for c in CLAUSE_SPLIT.split(t)]
        if not any(c and len(c) <= 28 and any(w in c for w in EXPR_CUES) for c in clauses):
            out.append(_issue("QW-C3", "img/motion 里没有可识别的表情线索短句（画布取不到“表情”）", field="motion"))
    if shot.img_prompt and not any(w in shot.img_prompt for w in SIZE_WORDS):
        out.append(_issue("QW-C2", "img 里没有景别词（画布取不到“景别”）", field="img"))

    # 对白
    for field, text in (("img", shot.img_prompt), ("motion", shot.motion_prompt)):
        if QUOTE_IN_PROMPT.search(text or ""):
            out.append(_issue("QW-Q1", f"{field} 里有引号包住的文字（若是台词，移到 **对白**；屏幕文字可保留）",
                              field=field))
    for d in shot.dialogue:
        if not d.speaker_note:
            out.append(_issue("S1-W4", f"台词缺少（说话人）或引号：{d.text[:20]}", field="对白"))
    for st in getattr(shot, "dialogue_stage", None) or []:   # 没有引号的段：导入器不当台词（T04），格式上仍要报
        out.append(_issue("S1-W4", f"台词缺少（说话人）或引号：{st[:20]}", field="对白"))

    # 【H3 audio】
    ha = shot.sound_h3
    if shot.sound.strip() and not ha:
        out.append(_issue("S1-W3", "sound 行缺少 `【H3 audio】` 段（或为空）", field="sound"))
    elif ha:
        probs = []
        n = len(L._sentences(ha))
        if not 1 <= n <= 4:
            probs.append(f"应为 1–4 句，现有 {n} 句")
        if not _english_ok(ha):
            probs.append("要用英文")
        if "<d>" in ha:
            probs.append("不写 <d>")
        neg = sorted({x.group(0).lower() for x in L.NEG_EN_RE.finditer(ha)})
        if neg:
            probs.append(f"否定词：{'、'.join(neg)}")
        if probs:
            out.append(_issue("S1-W3", "【H3 audio】" + "；".join(probs), field="sound"))

    # H3 提示词
    h3 = (shot.h3_prompt or "").strip("\n")
    if not h3:
        out.append(_issue("S1-W7", "缺少 `**H3提示词**` 字段（或为空）", field="H3提示词"))
        return out
    frames = L.frames_for_seconds(shot.duration or 10)
    intimate = bool(shot.sound_intimate)
    for r in L.lint_h3(h3, frames, intimate, **lint_inputs(shot)):
        if r["ok"] or r["rule_id"] == "H3-S3":      # H3-S3 按新规另查
            continue
        out.append(_issue(r["rule_id"], r["detail"], level=r.get("level", "block"), field="H3提示词"))
    fields = L.parse_h3(h3)["fields"]
    music = fields.get(L.FIELDS[2])
    if music is not None:
        probs = check_music(music)
        if probs:
            out.append(_issue("H3-S3", "；".join(probs), field="H3提示词"))
    # 名字 / 触发词（H3-D4 后半条：lint 只查引号）
    outside = L._outside_d(h3)
    bad = sorted({t for t in TRIGGER_LIKE.findall(outside)} | {t for t in triggers if t and t in outside}
                 | {n for n in names if n and re.search(rf"\b{re.escape(n)}\b", outside, re.I)})
    if bad:
        out.append(_issue("H3-D4", f"H3 里出现人名/触发词：{'、'.join(bad)}", field="H3提示词"))
    sc = fields.get(L.FIELDS[1], "")
    if ha and sc and ha.strip() != sc.strip():
        out.append(_issue("QW-S1", "【H3 audio】 与 overall_soundscape 不一致", field="sound"))
    return out


def check_episode(ep) -> list[dict]:
    out = []
    if not ep.synopsis.strip():
        out.append(_issue("QW-E1", "缺少 `**剧情**：`"))
    if not ep.music.strip():
        out.append(_issue("R-C1", "缺少本集 `**配乐**：`（必须写在镜1 之前）"))
    elif not ep.music_bgm:
        out.append(_issue("R-C1", "`**配乐**` 行缺少 `【BGM】` 段（或为空）"))
    elif not _english_ok(ep.music_bgm):
        out.append(_issue("R-C1", "`【BGM】` 要写英文（给音乐模型）"))
    for s in ep.shots:   # **配乐** 写在镜头之后会进 shot.extras
        if any(e.label.startswith("配乐") for e in s.extras):
            out.append(_issue("R-C1", f"`**配乐**` 写在了镜{s.index} 之后，被当成镜头附加字段；移到镜1 之前"))
    idx = [s.index for s in ep.shots]
    if idx != list(range(1, len(idx) + 1)):
        out.append(_issue("QW-E2", f"镜号 {idx}（应为 1..N 连续）"))
    cap = shot_cap(ep)          # K1 + G29：max(8, 说话轮次 + 独白段数, ⌈各镜时长之和 ÷ 6⌉)
    if not 6 <= len(idx) <= cap:
        out.append(_issue("QW-E2", f"镜数 {len(idx)}（本集应为 6–{cap}）"))
    if ep.shots and all(s.duration_source == "script" for s in ep.shots):
        total = sum(s.duration for s in ep.shots)
        lo, hi = EPISODE_SECONDS            # D-SCR-08：60–120 秒（导入器同一常量）
        if not lo <= total <= hi:
            out.append(_issue("QW-E3", f"总时长 {total} 秒（应为 {lo}–{hi}）"))
    return out


# ------------------------------------------------------------------ 场景（S1）

def check_scenes(imp, text: str, require: bool) -> tuple[list[dict], dict[int, list[dict]], dict[str, list[dict]]]:
    """→ (全局头问题, {集号: 集级问题}, {镜头 id: 镜头问题})。
    require=False（导入关口兼容旧剧本）：整份剧本没有任何场景表 / **场景** 行时缺场景只报 warn；
    有了场景表或任一镜写了 **场景**，就按 block 查。严格校验（剧本创作）require=True 总按 block"""
    lib = {e.scene_id: e for e in imp.globals.scene_library}
    _defs, problems, _used = scene_tables(text)
    in_play = require or bool(lib) or bool(problems) or any(s.scene_id for e in imp.episodes for s in e.shots)
    glob: list[dict] = []
    eps: dict[int, list[dict]] = {}
    shots: dict[str, list[dict]] = {}

    def at(ep_no, issue):
        (glob if ep_no is None else eps.setdefault(ep_no, [])).append(issue)

    for pr in problems:
        at(pr["episode"], _issue("QW-SC4", f"第 {pr['line']} 行：{pr['detail']}", field="场景表"))
    for e in lib.values():
        first = e.defined_in[0] if e.defined_in else None
        if not SCENE_ID_RE.match(e.scene_id):
            at(first, _issue("QW-SC2", f"场景表里的 id「{e.scene_id}」格式不对", field="场景表"))
        empty = [lab for lab, v in (("名称", e.name), ("空间描述", e.space), ("时段", e.time_of_day),
                                    ("光线", e.light), ("固定陈设", e.fixtures)) if not v]
        if empty:
            at(first, _issue("QW-SC4", f"场景 {e.scene_id} 的 {'、'.join(empty)} 为空", level="warn", field="场景表"))
        for c in e.conflicts:
            where = f"ep{c.episode:02d} 本集场景表" if c.episode else "全剧场景表"
            if first is None and c.episode:   # 继承来的登记被改写：QW-SC9，返修里附要照抄的原文全文
                at(c.episode, _issue("QW-SC9", f"场景 {e.scene_id} 已在全剧场景表登记，{where}（第 {c.source_line} 行）改写了{c.field}："
                                               f"要逐字照抄「{c.first}」（或从本集场景表删掉这一行），这里为「{c.other}」",
                                     field="场景表"))
                continue
            at(c.episode, _issue("QW-SC5", f"场景 {e.scene_id} 在{where}（第 {c.source_line} 行）重写了{c.field}："
                                           f"第一次为「{c.first[:30]}」，这里为「{c.other[:30]}」", field="场景表"))
    for ep in imp.episodes:
        for sh in ep.shots:
            out = shots.setdefault(sh.id, [])
            if not sh.scene_id:
                if in_play:   # 旧格式剧本（整份没有场景表 / 场景行）不报，免得 60 集逐镜刷屏；严格校验 require=True 总报
                    out.append(_issue("QW-SC1", "缺少 `**场景**：<场景id>｜<本镜场景细节>`", field="场景"))
                continue
            if not SCENE_ID_RE.match(sh.scene_id):
                out.append(_issue("QW-SC2", f"场景 id「{sh.scene_id}」格式不对", field="场景"))
            elif sh.scene_id not in lib:
                out.append(_issue("QW-SC3", f"场景 {sh.scene_id} 不在全剧场景表 / 本集场景表里", field="场景"))
            if not sh.scene_detail:
                out.append(_issue("QW-SC6", "`**场景**` 行没有本镜场景细节（｜ 之后）", field="场景"))
    return glob, eps, shots


# ------------------------------------------------------------------ v3 字段（R3，docs/production_rules_v3.md §1.1–1.5）
# 只查结构、取值词表与字符串一致性；不评内容。

SIZE_RANK = {"大远景": 0, "远景": 1, "大全景": 2, "全景": 2, "中全景": 3, "全身": 3, "中景": 4, "中近景": 5, "近景": 6,
             "特写": 7, "大特写": 8, "极近特写": 8, "极近": 8}
# QW-C1 运镜词表：唯一来源 = config/director/camera_moves.yaml（总调度 11-02 21:5x：不另存一份词表）。
# 只认 enabled、并且对本剧可用（camera_norm.is_enabled(id, run)：标了 runs 的按剧运镜只在列出的剧里）的运镜；
# 写法 = 运镜 id（例 bolt_push_settle）或它的英文别名 / 英文名。下面是“运镜 id → h3_lint.camera_moves 类型名”的映射（QW-C4 / QW-K2 用），
# 不是词表；id 不在这里 = 没有对应的 H3 类型（按剧运镜），QW-C4 不比
MOVE_TYPE = {"push_in": "push in", "pull_out": "pull out", "zoom_in": "zoom", "pan": "pan", "truck": "truck", "tilt_up": "tilt",
             "tilt_down": "tilt", "pedestal_up": "pedestal", "arc": "arc", "static": "static"}
_RUN: dict = {"run": None}


def _camera_norm():
    import importlib.util
    sp = importlib.util.spec_from_file_location("cn_validate", ROOT / "services" / "agent" / "ns_agent" / "camera_norm.py")
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


def camera_vocab(run: str | None = None) -> dict[str, str]:
    """英文写法（小写）→ 运镜 id；只含 camera_moves.yaml 里 enabled 且对本剧可用的运镜（run 显式传；不传按 validate 解析出的剧）"""
    CN = _camera_norm()
    r = run if run is not None else _RUN["run"]
    out = {}
    for m in CN.vocab().get("moves") or []:
        if not CN.is_enabled(m["id"], r):
            continue
        for a in [m["id"], (m.get("en") or "").lower(), *[x for x in m.get("aliases") or [] if x.isascii()]]:
            if a:
                out[a.lower()] = m["id"]
    return out


def run_of_path(path) -> str | None:
    """剧本属于哪部剧：路径里出现 runs.json 登记的剧名（data/import/runs/<剧>/、data/pipeline/runs/<剧>/）；否则 legacy 剧"""
    import json as _json
    f = ROOT / "config" / "pipeline" / "runs.json"
    if not f.is_file():
        return None
    reg = _json.loads(f.read_text(encoding="utf-8"))
    parts = set(Path(path).resolve().parts)
    hit = [r for r in (reg.get("runs") or {}) if r in parts]
    return hit[0] if hit else reg.get("legacy_unprefixed_run")
ORIENT_WORDS = {"back": ("背影", "背对", "背抵", "后脑"), "side": ("侧脸", "侧影", "侧面")}   # ns_render/refs.py 认得的词
TRANSITION_RE = re.compile(r"次日|第二天|翌日|闪回|回忆|梦境|数日后|几天后|一周后|当晚|(?:^|[，,。；;（(])周[一二三四五六日天]")
CUE_ACTIONS = ("进入", "延续", "渐强", "推到高点", "撤到静默", "落下", "重音")
CUE_AVOID = ("对白避让", "独白避让", "无需避让")
OFFSCREEN_OK = ("画外", "电话", "语音", "OS", "VO")
OFFSCREEN_LIKE = re.compile(r"^(?:V\.O\.?|O\.S\.?|V\.?O|O\.?S|旁白|画外音|画外声|电话里|电话那头|语音条)$", re.I)
LOOK_SLOTS = ("服装", "鞋", "妆", "发", "甲", "饰品", "其他")
LOOK_REQUIRED = ("服装", "鞋", "妆", "发")
PRONOUN_RE = re.compile(r"(?<!其)[她他]")
WARDROBE = ROOT / "data" / "looks" / "wardrobe.json"


def size_of(text: str) -> str | None:
    """文本里第一个景别词（同一位置取最长的）"""
    best = None
    for w in SIZE_RANK:
        i = (text or "").find(w)
        if i >= 0 and (best is None or i < best[0] or (i == best[0] and len(w) > len(best[1]))):
            best = (i, w)
    return best[1] if best else None


def motion_move(motion: str, run: str | None = None) -> str | None:
    """motion 触发词后的英文运镜 → 运镜 id（camera_moves.yaml 本剧可用的写法；不在表里返回 None）"""
    voc = camera_vocab(run)
    for tok in re.split(r"[，,]", motion or ""):                 # 运镜 id（bolt_push_settle）长得像触发词，会被 _strip_trig 剥掉：先按句首逗号段认
        t = tok.strip().lower()
        if t in voc and "_" in t:
            return voc[t]
        if not re.fullmatch(r"[a-z0-9_]+", t):
            break
    body = _strip_trig(motion or "").lower()
    body = re.sub(r"^camera\s+", "", body)
    for w in sorted(voc, key=len, reverse=True):
        if body.startswith(w):
            return voc[w]
    return None


def end_state(shot) -> str:
    mo = shot.motion_prompt or ""
    return mo.rsplit("——", 1)[1].strip(" ，。；、") if "——" in mo else ""


def orient(text: str) -> set[str]:
    return {k for k, ws in ORIENT_WORDS.items() if any(w in (text or "") for w in ws)}


def _en_problems(text: str, extra_bad: list[str] = ()) -> list[str]:
    probs = []
    if not (text or "").strip():
        return ["为空"]
    if L.CJK_RE.search(text):
        probs.append("有中文")
    neg = sorted({x.group(0).lower() for x in L.NEG_EN_RE.finditer(text)})
    if neg:
        probs.append(f"否定词：{'、'.join(neg)}")
    if '"' in text or "“" in text or "”" in text:
        probs.append("有双引号")
    bad = [b for b in extra_bad if b and re.search(rf"(?<![A-Za-z0-9_]){re.escape(b)}(?![A-Za-z0-9_])", text)]
    if bad:
        probs.append(f"含人名 / 触发词：{'、'.join(bad)}")
    return probs


def _wardrobe_names() -> set[str]:
    try:
        data = json.loads(WARDROBE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return set()
    items = data.get("items", []) if isinstance(data, dict) else data
    names = {i.get("name", "") for i in items if isinstance(i, dict) and i.get("name")}
    return names | {re.sub(r"[（(][^）)]*[）)]\s*$", "", n).strip() for n in names}     # 衣橱名带“（产品）”后缀：去掉后也认（QW-E6b，总调度 11-02）


E6B_SLOTS = ("服装", "鞋", "其他")          # QW-E6b 只查单品槽；发 / 妆 / 甲 / 饰品 是属性槽，不查衣橱（总调度 11-02）


def look_items(v: str) -> list[str]:
    """造型槽位值 → 单品名列表：组合串按 、 / ， / 与 / 配 / 外罩 / 外搭 / 内搭 拆开，去括号；0件 / 无 / 沿用 / 新：… 跳过"""
    out = []
    for part in re.split(r"[、，,；;]|与|配|外罩|外搭|内搭", v or ""):
        part = re.sub(r"[（(][^）)]*[）)]", "", part).strip()
        if part and part not in ("0件", "无", "沿用") and not part.startswith(("新：", "新:")):
            out.append(part)
    return out


def lora_table_problems(text: str) -> list[str]:
    block = _code_block_after(text, "LoRA 触发词表")
    if block is None:
        return []
    probs, section = [], None
    for ln in block.splitlines():
        if not ln.strip():
            continue
        if not ln[0].isspace():
            section = ln.strip() if ln.strip() in ("图像LoRA", "视频LoRA") else None
            if section is None:
                probs.append(f"分段名应为 图像LoRA / 视频LoRA：{ln.strip()[:30]}")
        elif section is None:
            probs.append(f"触发词行不在 图像LoRA / 视频LoRA 段下：{ln.strip()[:30]}")
        elif not re.match(r"^\s+[A-Za-z0-9_]+\s+\S", ln):
            probs.append(f"触发词行应为“<trigger>  <说明>”，trigger 只用字母数字下划线：{ln.strip()[:30]}")
    return probs


def v3_declared(imp, text: str) -> bool:
    """剧本里写了任一 v3 字段 = 声明 v3 格式（同 S-back：写了场景表 / 场景行就按 block 查场景）"""
    if imp.globals.character_registry or character_tables(text)[1]:
        return True
    for ep in imp.episodes:
        if ep.cast is not None or ep.scene_ids is not None or ep.looks:
            return True
        if any(s.cast is not None or s.link is not None for s in ep.shots):
            return True
    return False


def current_look(looks: list, name: str, shot_index: int):
    """角色在镜N 的当前造型 EN：起始造型行，被 镜M起（M ≤ N）的换装行覆盖"""
    en = None
    for lk in sorted((x for x in looks if x.character == name), key=lambda x: x.from_shot or 0):
        if (lk.from_shot or 0) <= shot_index and lk.en:
            en = lk.en
    return en


def check_v3(imp, text: str, require: bool) -> tuple[list[dict], dict[int, list[dict]], dict[str, list[dict]], bool]:
    """→ (全局头问题, {集号: 集级问题}, {镜头 id: 镜头问题}, 是否查了)。
    require=False（导入关口兼容旧剧本）：剧本里一个 v3 字段都没写时整段不查；写了任一 v3 字段就按表中级别查。
    严格校验（剧本创作）require=True 总按表中级别查。"""
    glob: list[dict] = []
    eps: dict[int, list[dict]] = {}
    shots: dict[str, list[dict]] = {}
    if not (require or v3_declared(imp, text)):
        return glob, eps, shots, False
    g = imp.globals
    from ns_schema.looks import CHARACTER_SLUG, CHARACTERS
    reg = {e.name: e for e in g.character_registry}
    locks = {c.name for c in g.character_locks}
    known = set(reg) | locks
    triggers = sorted({t.trigger for t in g.lora_triggers})
    lib = {e.scene_id: e for e in g.scene_library}

    def at(ep_no, issue):
        (glob if ep_no is None else eps.setdefault(ep_no, [])).append(issue)

    # ---- 全局头：角色锁、触发词表
    if not g.character_locks:
        glob.append(_issue("QW-G1", "全局头没有角色锁代码块（**每条prompt统一前缀** 后的 ``` 块，每行 【角色名】…）", field="全局头"))
    for pr in lora_table_problems(text):
        glob.append(_issue("QW-G2", pr, field="全局头"))

    # ---- 人物表
    _d, cproblems, _u = character_tables(text)
    for pr in cproblems:
        at(pr["episode"], _issue("QW-P1", f"第 {pr['line']} 行：{pr['detail']}", field="人物表"))
    id_names: dict[str, set[str]] = {}
    for e in reg.values():
        first = e.defined_in[0] if e.defined_in else None
        cid = e.char_id
        if not (cid in CHARACTERS or CHARACTER_ID_RE.match(cid or "")):
            at(first, _issue("QW-P2", f"角色 {e.name} 的角色id「{cid}」应为已有 slug、ch_<小写英文数字下划线> 或 lead_<…>", field="人物表"))
        elif e.name in CHARACTER_SLUG and cid != CHARACTER_SLUG[e.name]:
            at(first, _issue("QW-P2", f"角色 {e.name} 已有 slug {CHARACTER_SLUG[e.name]}，人物表写成了 {cid}", field="人物表"))
        id_names.setdefault(cid, set()).add(e.name)
        probs = _en_problems(e.en, list(known) + triggers)
        if probs:
            at(first, _issue("QW-P3", f"角色 {e.name} 的 EN外貌短语：{'；'.join(probs)}", field="人物表"))
        probs = _en_problems(e.voice, list(known) + triggers)
        if e.voice and not re.search(r"\bvoice\b", e.voice, re.I):
            probs.append("没有 voice")
        if probs:
            at(first, _issue("QW-P4", f"角色 {e.name} 的 VOICE声线短语：{'；'.join(probs)}", field="人物表"))
        for c in e.conflicts:
            where = f"ep{c.episode:02d} 本集人物表" if c.episode else "全剧人物表"
            if first is None and c.episode:   # 继承来的登记被改写：QW-P7，返修里附要照抄的原文全文
                at(c.episode, _issue("QW-P7", f"角色 {e.name} 已在全剧人物表登记，{where}（第 {c.source_line} 行）改写了{c.field}："
                                              f"要逐字照抄「{c.first}」（或从本集人物表删掉这一行），这里为「{c.other}」",
                                     field="人物表"))
                continue
            at(c.episode, _issue("QW-P5", f"角色 {e.name} 在{where}（第 {c.source_line} 行）重写了{c.field}：第一次为「{c.first[:30]}」，"
                                          f"这里为「{c.other[:30]}」", field="人物表"))
        if e.zh != "系统锁" and len([x for x in e.zh.split("｜") if x.strip()]) != 6:
            at(first, _issue("QW-P6", f"角色 {e.name} 的中文外貌句应为六项（全角｜分隔）或“系统锁”", field="人物表"))
    for cid, ns in id_names.items():
        if cid and len(ns) > 1:
            glob.append(_issue("QW-P2", f"角色id {cid} 对应了多个角色名：{'、'.join(sorted(ns))}", field="人物表"))

    # ---- 场景表：空场景（QW-SC8）
    for e in lib.values():
        first = e.defined_in[0] if e.defined_in else None
        probs = []
        for lab, v in (("空间描述", e.space), ("固定陈设", e.fixtures)):
            hit = sorted({n for n in known if n and n in v}) + (["她/他"] if PRONOUN_RE.search(v or "") else [])
            if hit:
                probs.append(f"{lab}里有人物：{'、'.join(hit)}")
        n_fix = len([x for x in re.split(r"[，、,]", e.fixtures or "") if x.strip()])
        if e.fixtures and not 1 <= n_fix <= 3:
            probs.append(f"固定陈设 {n_fix} 件（应为 1–3 件）")
        if probs:
            at(first, _issue("QW-SC8", f"场景 {e.scene_id}：{'；'.join(probs)}", field="场景表"))

    wardrobe = None
    _wl_fields = WL.scan_fields(text)              # **分拍** / **嘴型** 等增补字段（导入器不挂到镜头上）
    for ep in imp.episodes:
        ep_out = eps.setdefault(ep.number, [])
        ep_out.extend(WL.check_episode(ep, _wl_fields))          # QW-W4 造型行下装品类（ITERAUDIT 11-01）
        ep_out.extend(WL.check_l1(ep, text))                     # QW-L1 / QW-L2（L-188 L1：平光句 / 多人三层构图）
        if hard_run(_RUN["run"]):                                # QW-L3–L8（L2 镜头语言，K-WRT-810–815；只对 V2 及以后的剧）
            ep_out.extend(WL.check_l2(ep, text, _RUN["run"]))
            ep_out.extend(WL.check_l3(ep, text))                 # QW-L9–L11（L3 焦段光圈表 / 背景光源 / 双人站位，K-WRT-816–818，warn）
        ep_out.extend(WL.check_rubric(ep, text))                 # QW-RB1 清单代码判定（HOLLYWOOD r7，CONSENT 总调度 -> HOLLYWOOD）
        idx = {s.index for s in ep.shots}
        all_cast = [c for s in ep.shots for c in (s.cast or [])]
        cast_names = list(dict.fromkeys(c.name for c in all_cast))
        visible = list(dict.fromkeys(c.name for c in all_cast if c.visible))
        # QW-E4 出场人物
        if ep.cast is None:
            ep_out.append(_issue("QW-E4", "缺少集头 `**出场人物**：<角色名>、<角色名>…`", field="出场人物"))
        else:
            unk = [n for n in ep.cast if n not in known]
            if unk:
                ep_out.append(_issue("QW-E4", f"出场人物没有登记（人物表 / 角色锁）：{'、'.join(unk)}", field="出场人物"))
            if all(s.cast is not None for s in ep.shots) and set(ep.cast) != set(cast_names):
                miss, extra = sorted(set(cast_names) - set(ep.cast)), sorted(set(ep.cast) - set(cast_names))
                ep_out.append(_issue("QW-E4", "出场人物与各镜人物行不一致：" + "；".join(
                    x for x in (f"漏了 {'、'.join(miss)}" if miss else "", f"多了 {'、'.join(extra)}" if extra else "") if x),
                    field="出场人物"))
        # QW-E5 用到的场景
        if ep.scene_ids is None:
            ep_out.append(_issue("QW-E5", "缺少集头 `**用到的场景**：sk_<id>、sk_<id>…`", field="用到的场景"))
        else:
            unk = [x for x in ep.scene_ids if x not in lib]
            if unk:
                ep_out.append(_issue("QW-E5", f"用到的场景不在场景表里：{'、'.join(unk)}", field="用到的场景"))
            used = {s.scene_id for s in ep.shots if s.scene_id}
            if all(s.scene_id for s in ep.shots) and set(ep.scene_ids) != used:
                miss, extra = sorted(used - set(ep.scene_ids)), sorted(set(ep.scene_ids) - used)
                ep_out.append(_issue("QW-E5", "用到的场景与各镜场景行不一致：" + "；".join(
                    x for x in (f"漏了 {'、'.join(miss)}" if miss else "", f"多了 {'、'.join(extra)}" if extra else "") if x),
                    field="用到的场景"))
        # QW-E6 / E6b / E7 造型
        base_looks = {lk.character for lk in ep.looks if lk.from_shot is None}
        for n in visible:
            if n not in base_looks:
                ep_out.append(_issue("QW-E6", f"{n} 在本集入镜，缺少 `**造型｜{n}**：…` 行", field="造型"))
        for lk in ep.looks:
            label = f"造型｜{lk.character}" + (f"｜镜{lk.from_shot}起" if lk.from_shot else "")
            probs = []
            bad = [k for k in lk.slots if k not in LOOK_SLOTS]
            if bad:
                probs.append(f"槽位名不对：{'、'.join(bad)}（只用 {'/'.join(LOOK_SLOTS)} + EN，写成 槽位=值）")
            if lk.from_shot is None:
                miss = [k for k in LOOK_REQUIRED if not lk.slots.get(k)]
                if miss:
                    probs.append(f"缺 {'、'.join(miss)}")
            p_en = _en_problems(lk.en)
            if p_en:
                probs.append("EN " + "、".join(p_en))
            if probs:
                ep_out.append(_issue("QW-E6", f"`**{label}**`：{'；'.join(probs)}", field="造型"))
            if wardrobe is None:
                wardrobe = _wardrobe_names()
            if wardrobe:
                unknown = [it for k, v in lk.slots.items() if k in E6B_SLOTS and v for it in look_items(v) if it not in wardrobe]
                if unknown:
                    ep_out.append(_issue("QW-E6b", f"`**{label}**` 的单品不在 wardrobe.json：{'、'.join(u[:20] for u in unknown)}"
                                                   "（已有单品照抄名称；新单品写 新：…）", field="造型"))
            if lk.from_shot is not None:
                if lk.from_shot not in idx:
                    ep_out.append(_issue("QW-E7", f"`**{label}**` 的镜{lk.from_shot} 在本集不存在", field="造型"))
                else:
                    sh = next(s for s in ep.shots if s.index == lk.from_shot)
                    if "换" not in f"{sh.img_note or ''}{sh.motion_prompt or ''}":
                        ep_out.append(_issue("QW-E7", f"镜{lk.from_shot} 的 img 备注或 motion 没写换装", level="warn", field="造型"))
        # QW-P4 说话人都有 VOICE
        speakers = list(dict.fromkeys([d.speaker for s in ep.shots for d in s.dialogue if d.speaker]
                                      + [s.voiceover.speaker for s in ep.shots if s.voiceover and s.voiceover.speaker]))
        nov = [n for n in speakers if n in known and not (reg.get(n) and reg[n].voice)]
        if nov:
            ep_out.append(_issue("QW-P4", f"说话人在人物表里没有 VOICE声线短语：{'、'.join(nov)}", field="人物表"))

        prev = None
        for sh in ep.shots:
            out = shots.setdefault(sh.id, [])
            img, end = sh.img_prompt or "", end_state(sh)
            # ---- 人物行
            if sh.cast is None:
                out.append(_issue("QW-CH1", "缺少 `**人物**：<角色名>（在画｜左/中/右｜前/中/后）…`", field="人物"))
            else:
                for c in sh.cast:
                    ok = ((c.presence == "在画" and c.x in ("左", "中", "右") and c.depth in ("前", "中", "后"))
                          or (c.presence == "局部" and c.part and c.x in ("左", "中", "右"))
                          or (c.presence == "画外" and c.raw.endswith("（画外）")))
                    if not ok:
                        out.append(_issue("QW-CH1", f"人物项格式不对：{c.raw[:30]}", field="人物"))
                if PRONOUN_RE.search(sh.cast_raw or ""):
                    out.append(_issue("QW-CH1", "人物行里写了“她 / 他”（只写角色名）", field="人物"))
                unk = [c.name for c in sh.cast if c.name not in known]
                if unk:
                    out.append(_issue("QW-CH2", f"人物行的名字没有登记：{'、'.join(unk)}", field="人物"))
                vis = [c.name for c in sh.cast if c.visible]
                if len(vis) > 3:
                    out.append(_issue("QW-CH3", f"在画 + 局部 {len(vis)} 人（最多 3 人）", field="人物"))
                # fredw-92/D2：所有格地点（“顾沉家餐厅”“林晚的公寓”）不算人物入镜（与 compiler.without_possessive_places 同口径）
                img_np, end_np = (re.sub("(" + "|".join(re.escape(n) for n in known if n) + ")" + POSSESSIVE_PLACES, "", t)
                                  if any(known) else t for t in (img, end))
                # FIX（ep02_iter P0 ⑦）：“顾沉的西装衣领”是物件所有格，只是提到，不算入镜（与 compiler 同口径）
                from ns_agent.compiler import without_possessive_mentions
                img_np, end_np = (without_possessive_mentions(t)[0] for t in (img_np, end_np))
                stray = sorted({n for n in known if n and (n in img_np or n in end_np) and n not in vis})
                if stray:
                    out.append(_issue("QW-CH4", f"img / 结束状态里出现了人物行没有（在画 / 局部）的角色：{'、'.join(stray)}",
                                      field="人物"))
                unnamed = [c.name for c in sh.cast if c.presence == "在画" and c.name not in img]
                if unnamed:
                    out.append(_issue("QW-CH4", f"人物行在画的角色没在 img 里写出名字：{'、'.join(unnamed)}", level="warn",
                                      field="img"))
                # 总调度 11-01 决定 1(b)（ep03-S6）：cast=局部但 img 写到他的脸 / 头发——与 asset_refs.face_described 同一判定
                from ns_agent.asset_refs import face_described
                on_names = [c.name for c in sh.cast if c.presence in ("在画", "局部")]
                pf = [c.name for c in sh.cast if c.presence == "局部" and face_described(c.name, img, on_names)]
                if pf:
                    out.append(_issue("QW-CH6", f"人物行写“局部”，img 却写到了脸 / 头发：{'、'.join(pf)}", level="warn", field="人物"))
                # REFLOCK 11-01（PRODUCER 尽力清单 ep02-S1/S2、ep06-S8 等 Q3 连续不过：出图退成中近景）：特写写了两人在画 / 脸与鞋踩地并存
                from ns_agent import framing as _FR
                _sz = _FR.size_of(img)
                if _sz in _FR.CLOSE and _FR.closeup_subject(img, _sz) == "face":
                    _two = [c.name for c in sh.cast if c.presence == "在画"]
                    _feet = [w for w in ("踩", "鞋尖", "鞋跟") if w in img]
                    if len(_two) >= 2:
                        out.append(_issue("QW-SZ1", f"{_sz}却有两人在画：{'、'.join(_two)}", level="warn", field="img"))
                    elif _feet:
                        out.append(_issue("QW-SZ1", f"脸部{_sz}同时写了{'、'.join(_feet)}", level="warn", field="img"))
                # REFLOCK 11-01（ep05-S3/S5、ep10-S8 局部大特写出成带脸的中景，总调度驳回）
                if _sz in _FR.CLOSE and _FR.closeup_subject(img, _sz) in ("part", "object"):
                    _near = [w for w in ("肩头", "肩膀", "锁骨", "颈", "下颌", "胸口", "眼睛为真实人眼大小") if w in img]
                    if _near and "不出现脸" not in img and "上沿" not in img:
                        out.append(_issue("QW-SZ2", f"局部{_sz}写到了靠近脸的部位 / 脸部套话：{'、'.join(_near)}", level="warn", field="img"))
                names_here = {c.name for c in sh.cast}
                spk = [d.speaker for d in sh.dialogue if d.speaker] + \
                    ([sh.voiceover.speaker] if sh.voiceover and sh.voiceover.speaker else [])
                miss = sorted({x for x in spk if x not in names_here})
                if miss:
                    out.append(_issue("QW-CH5", f"说话人不在人物行：{'、'.join(miss)}", field="人物"))
                off = {c.name for c in sh.cast if c.presence == "画外"}
                for d in sh.dialogue:
                    note = f"{d.speaker_note or ''}{d.stage or ''}"
                    if d.speaker in off and not any(m in note for m in OFFSCREEN_OK):
                        out.append(_issue("QW-CH5", f"{d.speaker} 标为画外，台词括号里没有画外标记：{d.text[:16]}", field="对白"))
            # ---- 写作方机检 QW-W1–W4（ITERAUDIT 11-01；tools/qa/writer_lints.py）
            out.extend(WL.check_shot(sh, ep, img, size_of(img), _wl_fields.get((ep.number, sh.index))))
            out.extend(AL.check_shot(sh, ep, img, size_of(img), _wl_fields.get((ep.number, sh.index)),
                                     level=WL.WRITER_LINT_LEVEL))   # ACTING 11-01 QW-A1–A5；SCRIPT-RSI 11-01 QW-A6–A8
            # SCRIPT-RSI 11-01（D-SCR-07）：QW-AX1 轴线是相邻两镜的关系，记在后一镜上，返修环按单镜发
            out.extend(i for i in AL.check_episode(ep, _wl_fields) if i.get("shot") == sh.index)
            out.extend(VQL.check_shot(sh, ep, img, size_of(img), _wl_fields.get((ep.number, sh.index)),
                                      level=WL.WRITER_LINT_LEVEL))  # VQ-W1 鞋（RSI 11-01 接线）
            # ---- 衔接行
            if sh.link is None:
                out.append(_issue("QW-LK1", "缺少 `**衔接**：<接力/同场换机位/换场/接上一集>｜承：<延续项>`", field="衔接"))
            elif sh.link not in LINK_VALUES:
                out.append(_issue("QW-LK1", f"衔接取值「{sh.link}」不在 接力 / 同场换机位 / 换场 / 接上一集 里", field="衔接"))
            elif sh.index == 1 and sh.link not in ("换场", "接上一集"):
                out.append(_issue("QW-LK1", f"镜1 的衔接只能写 换场 或 接上一集（现为 {sh.link}）", field="衔接"))
            else:
                if sh.link == "接力" and not sh.link_carry:
                    out.append(_issue("QW-LK1", "接力时要写 `｜承：<延续项>`", field="衔接"))
                if prev is not None and sh.link in ("接力", "同场换机位") and sh.scene_id != prev.scene_id:
                    out.append(_issue("QW-LK2", f"{sh.link}：场景 {sh.scene_id} 与上一镜 {prev.scene_id} 不同", field="衔接"))
                if prev is not None and sh.link == "接力":
                    a, b = size_of(img), size_of(end_state(prev))
                    if a and b and abs(SIZE_RANK[a] - SIZE_RANK[b]) > 1:
                        out.append(_issue("QW-LK2", f"接力：img 景别 {a} 与上一镜结束状态 {b} 相差超过一档", level="warn",
                                          field="img"))
                if prev is not None and sh.link == "换场" and sh.scene_id == prev.scene_id and \
                        not TRANSITION_RE.search(f"{sh.img_note or ''}，{sh.motion_prompt or ''}"):
                    out.append(_issue("QW-LK3", "换场：场景 id 与上一镜相同，且 img 备注 / motion 没有换段词", field="衔接"))
            # ---- 运镜 / 景别 / 朝向
            mv = motion_move(sh.motion_prompt)
            if sh.motion_prompt and mv is None and MOVE_EN.match(_strip_trig(sh.motion_prompt)):   # 能认出运镜但不在词表
                out.append(_issue("QW-C1", "motion 的英文运镜不在运镜词表里（config/director/camera_moves.yaml 里 enabled、且本剧可用的）",
                                  field="motion"))
            if mv and sh.h3_prompt:
                found = L.camera_moves(L._description(sh.h3_prompt))
                if found and MOVE_TYPE.get(mv) and MOVE_TYPE[mv] not in found:
                    out.append(_issue("QW-C4", f"motion 运镜 {mv} 与 H3 正文的运镜（{'、'.join(found)}）不是同一种", field="motion"))
            if sh.motion_prompt and end:
                es = next((w for w in sorted(SIZE_RANK, key=len, reverse=True) if end.startswith(w)), None)
                if es is None:
                    out.append(_issue("QW-K1", f"结束状态没有以景别词开头：{end[:16]}", field="motion"))
                a = size_of(img)
                if es and a:
                    diff, cap = abs(SIZE_RANK[a] - SIZE_RANK[es]), (0 if mv and MOVE_TYPE.get(mv) in
                                                                      ("static", "pan", "tilt", "truck") else 1)
                    if diff > cap:
                        out.append(_issue("QW-K2", f"img 景别 {a} → 结束状态 {es} 相差 {diff} 档（{mv or '运镜'} 最多 {cap} 档）",
                                          field="motion"))
                o1, o2 = orient(img), orient(end)
                if (o1 or o2) and o1 != o2 and "转身" not in (sh.motion_prompt or ""):
                    out.append(_issue("QW-K3", f"img 朝向（{'、'.join(sorted(o1)) or '正面'}）与结束状态（{'、'.join(sorted(o2)) or '正面'}）"
                                               "不一致，motion 也没写转身", field="motion"))
            # ---- 场景用词（QW-SC7）
            e = lib.get(sh.scene_id or "")
            if e is not None and img:
                fixtures = [x.strip() for x in re.split(r"[，、,]", e.fixtures or "") if x.strip()]
                if not ((e.name and e.name in img) or any(f in img for f in fixtures)):
                    out.append(_issue("QW-SC7", f"img 里没有场景 {sh.scene_id} 的名称或固定陈设（照抄场景表）", field="img"))
            # ---- 【配乐】cue（QW-M1）
            cue = sh.music_cue or ""
            if cue:
                parts = [x.strip() for x in re.split(r"[，,；;]", cue) if x.strip()]
                probs = []
                if not parts or parts[0] not in CUE_ACTIONS:
                    probs.append(f"动作「{parts[0] if parts else ''}」不在 {'/'.join(CUE_ACTIONS)} 里")
                m = re.search(r"强度\s*(\d+)", cue)
                if m and not 0 <= int(m.group(1)) <= 3:
                    probs.append(f"强度 {m.group(1)} 不在 0–3")
                if not any(a in cue for a in CUE_AVOID):
                    probs.append(f"缺避让（{'/'.join(CUE_AVOID)}）")
                if sh.dialogue and "对白避让" not in cue:
                    probs.append("本镜有台词，要写对白避让")
                if sh.voiceover and sh.voiceover.text and "独白避让" not in cue:
                    probs.append("本镜有 🎙，要写独白避让")
                if probs:
                    out.append(_issue("QW-M1", "【配乐】" + "；".join(probs), field="sound"))
            # ---- 说话人（QW-D1 / D2）
            for d in sh.dialogue:
                if d.speaker not in known:
                    out.append(_issue("QW-D1", f"对白括号没有以已登记的角色名开头：（{(d.speaker_note or '')[:16]}）", field="对白"))
                toks = [t.strip() for t in re.split(r"[，,、\s]", d.speaker_note or "")[1:] if t.strip()]
                bad = [t for t in toks if OFFSCREEN_LIKE.match(t) and t not in OFFSCREEN_OK]
                if bad:
                    out.append(_issue("QW-D1", f"画外标记只用 画外/电话/语音/OS/VO：{'、'.join(bad)}", field="对白"))
            if sh.voiceover is not None:
                vs = sh.voiceover.speaker
                if vs not in known:
                    out.append(_issue("QW-D2", f"🎙 括号没有以已登记的角色名开头：（{(sh.voiceover.note or '')[:16]}）", field="🎙"))
                elif not (reg.get(vs) and reg[vs].voice):
                    out.append(_issue("QW-D2", f"🎙 的 {vs} 在人物表里没有 VOICE声线短语", field="🎙"))
            # ---- H3-X1 / X3（人物表锚点 / 声线）
            if sh.h3_prompt and sh.cast is not None:
                anchors = []
                for c in sh.cast:
                    if c.presence != "在画":
                        continue
                    if reg.get(c.name) and reg[c.name].en:
                        anchors.append((f"{c.name} EN外貌短语", reg[c.name].en))
                    look_en = current_look(ep.looks, c.name, sh.index)
                    if look_en:
                        anchors.append((f"{c.name} 造型 EN", look_en))
                order = list(dict.fromkeys(d.speaker for d in sh.dialogue if d.speaker))
                voices = [(n, reg[n].voice if reg.get(n) else "") for n in order]
                for r in L.lint_h3_registry(sh.h3_prompt, anchors=anchors, voices=voices if order else None):
                    if not r["ok"]:
                        out.append(_issue(r["rule_id"], r["detail"], level=r["level"], field="H3提示词"))
                # FIX（ep02_iter P0，B4）：写作模型输出的确定性校验（ns_schema.llm_output_check）
                on = {c.name for c in sh.cast if c.presence == "在画"}
                absent = {n: [reg[n].en] for n in known if n and n not in on and reg.get(n) and reg[n].en}
                res = LOC.check_writer_output(sh.h3_prompt, dialogue=[d.text for d in sh.dialogue],
                                              names={n: [n] for n in known if n}, absent_phrases=absent)
                for e in res.errors:
                    rid = {"P1": "H3-X4", "N1": "H3-X5", "D1": "H3-X6"}.get(e["rule"])
                    if rid:
                        out.append(_issue(rid, e["detail"], level="block", field="H3提示词"))
            prev = sh
    return glob, eps, shots, True


# ------------------------------------------------------------------ 返修请求

def rule_text(rule_id: str) -> str:
    return RULES[rule_id][1] if rule_id in RULES else LINT_RULE_TEXT.get(rule_id, "")


def repair_request(ep_no: int, shot_index: int | None, issues: list[dict], scope: bool = True) -> str:
    """scope=True（单镜返修工具 tools/qwen_repair_loop.py）：末行写“只输出这一镜 / 集头”。
    scope=False（校验报告里的 repair 文本，剧本创作对话框再统一加“重新输出完整整集”）：不写输出范围，免得前后矛盾"""
    where = f"ep{ep_no:02d} 镜{shot_index}" if shot_index else f"ep{ep_no:02d} 集头"
    lines = [f"【格式返修】{where}：以下格式规则未通过（docs/qwen_writing_contract.md）。",
             "只修正格式；剧情、画面内容、台词原文保持不变" + ("；其它镜头不要输出。" if scope else "。")]
    seen = set()
    for i in issues:
        key = (i["rule_id"], i["detail"])
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"- [{i['rule_id']}|{i['level']}] 规则：{rule_text(i['rule_id'])}｜现状：{i['detail']}")
    if scope:
        tail = (f"请输出 ep{ep_no:02d} 镜{shot_index} 的完整 Markdown（从 `**镜{shot_index}｜img**` 到 `**H3提示词**` 代码块结束）。"
                if shot_index else f"请输出 ep{ep_no:02d} 的集头（`## ep…《…》`、`**剧情**`、`**出场人物**`、`**用到的场景**`、"
                                   f"`**造型｜…**`、`**配乐**`、有新角色 / 新场景时 `**本集人物表**` / `**本集场景表**`）。")
        lines.append(tail)
    return "\n".join(lines)


# ------------------------------------------------------------------ 主流程

def _episode_lines(episodes, ep):
    nxt = [e.source_line for e in episodes if e.source_line > ep.source_line]
    return ep.source_line, (min(nxt) if nxt else 10 ** 9)


V2_SHOT_MAX_S = 6.0          # 项目方定律：单镜不超过 6 秒（V1 视频链规则，L-137 原样带进 V2）
V2_HARD_RULES = ("QW-T1", "QW-C1")


def hard_run(run: str | None) -> bool:
    """MERGE-VID-O（L-137）：非 legacy 剧（V2 及以后的新剧）——QW-T1（单镜 ≤6 秒）/ QW-C1（运镜在本剧词表里）判 block，
    而且不可交补丁环（补丁环不能改镜数 / 时长；运镜不在词表 = 视频端会被改回固定机位）。legacy（V1）/ 认不出剧 → 保持旧级别"""
    if not run:
        return False
    import json as _json
    f = ROOT / "config" / "pipeline" / "runs.json"
    if not f.is_file():
        return False
    legacy = _json.loads(f.read_text(encoding="utf-8")).get("legacy_unprefixed_run")
    return bool(legacy) and run != legacy


def _apply_hard_rules(ep, ep_issues: list, shot_issues: dict) -> list[dict]:
    """V2：去掉 QW-T1 的集级 warn，按镜加 QW-T1 block（>6 秒，台词多也不放宽）；QW-C1 升 block。→ 硬阻断清单"""
    ep_issues[:] = [i for i in ep_issues if i["rule_id"] != "QW-T1"]
    hard = []
    for s in ep.shots:
        iss = shot_issues.setdefault(s.id, [])
        for i in iss:
            if i["rule_id"] == "QW-C1":
                i["level"] = "block"
        if s.duration and float(s.duration) > V2_SHOT_MAX_S + 1e-6:
            iss.append(_issue("QW-T1", f"镜{s.index} 时长 {s.duration} 秒，超过单镜上限 {V2_SHOT_MAX_S:g} 秒（V2 硬规则，L-137）："
                                       "多出来的时间拆成新镜，不拉长这一镜", level="block", field="时长"))
        hard += [{"shot": s.id, "rule_id": i["rule_id"], "detail": i["detail"]} for i in iss
                 if i["rule_id"] in V2_HARD_RULES and i["level"] == "block"]
    return hard


def validate(path: Path, episode: int | None = None, names: list[str] | None = None,
             require_scenes: bool = False, require_v3: bool = False, run: str | None = None) -> dict:
    _RUN["run"] = run or run_of_path(path)            # QW-C1 按剧取运镜词表（camera_moves.yaml runs）
    hard_on = hard_run(_RUN["run"])
    imp = import_script(Path(path))
    triggers = {t.trigger for t in imp.globals.lora_triggers}
    eps = [e for e in imp.episodes if episode is None or e.number == episode]
    report = {"script": str(path), "episodes": [], "counts": {}, "blocking": 0, "warnings": 0, "run": _RUN["run"],
              "hard_blocks": []}
    counts: collections.Counter = collections.Counter()
    text = Path(path).read_text(encoding="utf-8")
    sc_glob, sc_eps, sc_shots = check_scenes(imp, text, require_scenes)
    v3_glob, v3_eps, v3_shots, v3_on = check_v3(imp, text, require_v3 or REQUIRE_V3)
    sc_glob = sc_glob + v3_glob
    for k, v in v3_eps.items():
        sc_eps.setdefault(k, []).extend(v)
    for k, v in v3_shots.items():
        sc_shots.setdefault(k, []).extend(v)
    report["global_issues"] = sc_glob          # 全局头（全剧场景表 / 全剧人物表）的问题；不属于任何一集
    report["scene_library"] = [e.model_dump() for e in imp.globals.scene_library]
    report["character_registry"] = [e.model_dump() for e in imp.globals.character_registry]
    report["v3"] = v3_on                       # True = 按 v3 字段规则查过（声明了 v3 格式或严格模式）
    for i in sc_glob:
        counts[(i["rule_id"], i["level"])] += 1
    for ep in eps:
        lo, hi = _episode_lines(imp.episodes, ep)
        ep_issues = check_episode(ep) + sc_eps.get(ep.number, [])
        for w in imp.warnings:     # 导入器“无法归属”的散行
            m = re.match(r"第 (\d+) 行无法归属：(.*)", w)
            if m and lo <= int(m.group(1)) < hi:
                ep_issues.append(_issue("QW-F0", f"第 {m.group(1)} 行无法归属：{m.group(2)}"))
        shot_iss = {s.id: check_shot(s, ep, triggers, names or []) + sc_shots.get(s.id, []) for s in ep.shots}
        if hard_on:
            report.setdefault("hard_blocks", []).extend(_apply_hard_rules(ep, ep_issues, shot_iss))
        ep_rep = {"number": ep.number, "title": ep.title, "issues": ep_issues, "shots": [],
                  "repair": repair_request(ep.number, None, [i for i in ep_issues if i["level"] == "block"], scope=False)
                  if any(i["level"] == "block" for i in ep_issues) else ""}
        all_issues = list(ep_issues)
        for s in ep.shots:
            iss = shot_iss[s.id]
            all_issues += iss
            ep_rep["shots"].append({"id": s.id, "index": s.index, "duration": s.duration,
                                    "frames": L.frames_for_seconds(s.duration or 10), "issues": iss,
                                    "img_chars": len(s.img_prompt or ""),   # IMG-C2：只统计（上限待实测）
                                    "ok": not any(i["level"] == "block" for i in iss),
                                    "repair": repair_request(ep.number, s.index, iss, scope=False)
                                    if any(i["level"] == "block" for i in iss) else ""})
        for i in all_issues:
            counts[(i["rule_id"], i["level"])] += 1
        report["episodes"].append(ep_rep)
    report["counts"] = {f"{r}|{lvl}": n for (r, lvl), n in sorted(counts.items())}
    report["blocking"] = sum(n for (_, lvl), n in counts.items() if lvl == "block")
    report["warnings"] = sum(n for (_, lvl), n in counts.items() if lvl != "block")
    report["episodes_found"] = len(eps)
    return report


def render_text(rep: dict) -> str:
    out = [f"剧本：{rep['script']}  集数：{rep['episodes_found']}  block：{rep['blocking']}  warn：{rep['warnings']}"]
    for i in rep.get("global_issues") or []:
        out.append(f"  [全局头] {i['rule_id']:<7} {i['level']:<5} {i['detail']}")
    for ep in rep["episodes"]:
        out.append(f"\n== ep{ep['number']:02d}《{ep['title']}》")
        for i in ep["issues"]:
            out.append(f"  [集] {i['rule_id']:<7} {i['level']:<5} {i['detail']}")
        for s in ep["shots"]:
            mark = "OK " if s["ok"] else "ERR"
            out.append(f"  {mark} {s['id']}（{s['duration']} 秒 / {s['frames']} 帧）")
            for i in s["issues"]:
                out.append(f"      {i['rule_id']:<7} {i['level']:<5} {i['detail'][:160]}")
    out.append("\n按规则计数：")
    for k, n in rep["counts"].items():
        out.append(f"  {k:<16} {n}")
    return "\n".join(out)


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(description="Qwen 剧本格式校验（docs/qwen_writing_contract.md）")
    ap.add_argument("script")
    ap.add_argument("--episode", type=int)
    ap.add_argument("--json", action="store_true", help="输出 JSON 报告")
    ap.add_argument("--rubric-gate", action="store_true", help="导入闸门：QW-RB1（rubric_code 代码判定）升为阻断（HOLLYWOOD r7）")
    ap.add_argument("--repair-dir", help="把每个失败镜头的返修请求写成 txt 文件")
    ap.add_argument("--names", default="", help="H3 里禁止出现的人名（英文/拼音），逗号分隔")
    ap.add_argument("--require-scenes", action="store_true",
                    help="每镜必须有 **场景**（不给时：整份剧本没有任何场景表 / 场景行的旧剧本只提示）")
    ap.add_argument("--require-v3", action="store_true",
                    help="按 v3 字段规则查（人物表 / 出场人物 / 用到的场景 / 造型 / 人物 / 衔接；不给时：一个 v3 字段都没写的旧剧本不查）")
    a = ap.parse_args(argv)
    if a.rubric_gate and hasattr(WL, "RUBRIC_LEVEL"):
        WL.RUBRIC_LEVEL = "block"
    rep = validate(Path(a.script), a.episode, [n.strip() for n in a.names.split(",") if n.strip()],
                   require_scenes=a.require_scenes or REQUIRE_SCENES, require_v3=a.require_v3 or REQUIRE_V3)
    if not rep["episodes_found"]:
        print("没有解析出任何集（检查 `## ep<N>《<标题>》` 标题行）", file=sys.stderr)
        return 2
    if a.repair_dir:
        d = Path(a.repair_dir)
        d.mkdir(parents=True, exist_ok=True)
        for ep in rep["episodes"]:
            if ep["repair"]:
                (d / f"ep{ep['number']:02d}-head.txt").write_text(ep["repair"], encoding="utf-8")
            for s in ep["shots"]:
                if s["repair"]:
                    (d / f"{s['id']}.txt").write_text(s["repair"], encoding="utf-8")
    print(json.dumps(rep, ensure_ascii=False, indent=1) if a.json else render_text(rep))
    return 1 if rep["blocking"] else 0


if __name__ == "__main__":
    sys.exit(main())
