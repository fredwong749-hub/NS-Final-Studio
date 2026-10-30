"""
确定性剧本导入器：解析《为他而骚》v2 的两份 Markdown。

- 剧本和镜头 v2.md：全局锁（角色锁、motion 后缀、基础负面、触发词表）+ 60 集 × 6 镜
- image提示词 v2.md：数据 B 装饰状态总表、数据 D 基准图注册表、数据 E LoRA 注册表

只做结构化，不改写任何提示词原文。格式异常写进 warnings，不抛异常。
"""
import hashlib
import json
import re
from pathlib import Path

from ns_schema.script import (
    CharacterLock, DecorRange, DialogueLine, Episode, Extra, LoraTrigger, ReferenceImage,
    ScriptGlobals, ScriptImport, Shot, SourceFile, Voiceover,
)

EP_RE = re.compile(r"^## ep(\d+)《(.+?)》(.*)$")
# 原稿里有手工修改留下的残缺格式（缺结尾 **、缺冒号），这里放宽匹配
SHOT_RE = re.compile(r"^\*\*镜(\d+)｜img(?:（(.*?)）)?(?:\*\*)?[：:]\s*(.*)$")
FIELD_RE = re.compile(r"^\*\*([^*：:`]+?)(?:\*\*)?`?(?:[：:]\s*(.*))?$")
PAREN_RE = re.compile(r"（(.*?)）")
# 一句台词：可选的连续括号 + 一对引号
# 括号（可多个）后可带冒号（QA-07）；或无括号的“名字：”（QA-08）；再接一对引号
LINE_RE = re.compile(r"(?P<parens>(?:（[^）]*）\s*)*)(?:[：:]\s*)?(?:(?P<name>[^\s“\"「（）：:，。／]{1,8})[：:]\s*)?[“\"「](?P<text>.*?)[”\"」]")
CODE_BLOCK_RE = re.compile(r"```[^\n]*\n(.*?)```", re.S)

# 挂在镜头上的附加字段；其它不认识的字段挂在集上
SHOT_EXTRA_LABELS = {"对白屏幕上", "motion补充", "口型", "口型内容", "字幕卡"}
# v3 每镜的 **H3提示词**：SOP §9A.1 官方 FL2VA 全文，多行（含空行），原样保留到下一个 **字段** / 镜头 / 集标题
H3_LABELS = {"H3提示词", "H3 提示词"}
SHOTS_PER_EPISODE = (6, 8)                   # v2 每集 6 镜；v3 亲密内容集最多 8 镜
MIN_SHOT_SECONDS, MAX_SHOT_SECONDS = 3, 15   # 镜头时长（**时长**：N秒）
EPISODE_SECONDS = (50, 75)                   # 一集总时长允许范围
POSE_TRIGGER_RE = re.compile(r"pose_[A-Za-z0-9_]+")
EPISODE_COUNT = 60


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _unwrap(text: str) -> str:
    """去掉整段包裹的反引号或斜体星号；正文里的 Markdown 加粗 ** 只保留文字（QA-08：会进提示词）"""
    s = text.strip().replace("**", "")
    if len(s) >= 2 and s[0] == s[-1] == "`" and s.count("`") == 2:
        return s[1:-1].strip()
    if len(s) >= 2 and s[0] == s[-1] == "*" and not s.startswith("**"):
        return s.strip("*").strip()
    # 残缺的包裹符号（只有一边）
    return s.strip("`*").strip()


def _split_label(label: str) -> tuple[str, str | None]:
    note = PAREN_RE.search(label)
    base = PAREN_RE.sub("", label).strip()
    return base, (note.group(1) if note else None)


def _leading_triggers(prompt: str, known: set[str]) -> list[str]:
    """开头连续的触发词：触发词表里的，或姿势触发词 pose_<名称>（v3，名称见 docs/pose_library.md）"""
    found = []
    for token in re.split(r"[，,]", prompt):
        token = token.strip()
        if token in known or POSE_TRIGGER_RE.fullmatch(token):
            found.append(token)
        else:
            break
    return found


def _parse_dialogue(raw: str) -> list[DialogueLine]:
    """按引号对切分：一段“（括号…）”+“台词”算一句。
    原稿有时两句之间不写“／”（“…”（他）“…”），也有连续多个括号（（接通）（她，很小声））：
    紧挨台词的最后一个括号是说话人，更前面的括号是舞台提示。"""
    lines = []
    for part in _split_outside_quotes(raw.replace("**", ""), "／"):
        part = part.strip()
        if not part:
            continue
        matches = list(LINE_RE.finditer(part))
        if not matches:
            lines.append(DialogueLine(speaker_note=None, text=part))
            continue
        for m in matches:
            notes = PAREN_RE.findall(m.group("parens") or "")
            # “他：“…””这种无括号写法（QA-08）：名字当说话人
            if not notes and m.group("name"):
                notes = [m.group("name").strip()]
            lines.append(DialogueLine(speaker_note=notes[-1] if notes else None, text=m.group("text"),
                                      stage="；".join(notes[:-1]) or None))
    return lines


def _split_outside_quotes(text: str, sep: str) -> list[str]:
    """只在引号外切分（QA-06：台词里的“／”是停顿，不是分句）"""
    parts, buf, depth = [], [], 0
    for ch in text:
        if ch in "“「":
            depth += 1
        elif ch in "”」" and depth:
            depth -= 1
        if ch == sep and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    return parts


def _parse_strength(raw: str | None) -> tuple[float, float] | None:
    if not raw:
        return None
    nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", raw)]
    if len(nums) == 1:
        return (nums[0], nums[0])
    return (nums[0], nums[1]) if len(nums) >= 2 else None


# ------------------------------------------------------------------ 全局部分

def _code_block_after(text: str, marker: str) -> str | None:
    i = text.find(marker)
    if i < 0:
        return None
    m = CODE_BLOCK_RE.search(text, i)
    return m.group(1) if m else None


def _inline_code_after(text: str, marker: str) -> str:
    for line in text.splitlines():
        if marker in line:
            m = re.search(r"`([^`]+)`", line)
            if m:
                return m.group(1).strip()
    return ""


def _parse_globals(script: str, image_doc: str | None, warnings: list[str]) -> ScriptGlobals:
    g = ScriptGlobals()

    block = _code_block_after(script, "每条prompt统一前缀")
    for line in (block or "").splitlines():
        m = re.match(r"^\s*【(.+?)】(.+)$", line)
        if m:
            g.character_locks.append(CharacterLock(name=m.group(1), description=m.group(2).strip()))
    if not g.character_locks:
        warnings.append("没有找到角色锁（每条prompt统一前缀）")

    g.motion_suffix = _inline_code_after(script, "每条motion统一后缀")
    g.image_suffix = _inline_code_after(script, "每条img统一后缀")
    g.base_negative = _inline_code_after(script, "基础负面")

    triggers: dict[str, LoraTrigger] = {}
    kind = None
    for line in (_code_block_after(script, "LoRA 触发词表") or "").splitlines():
        if line.startswith("图像LoRA"):
            kind = "image"
        elif line.startswith("视频LoRA"):
            kind = "video"
        elif kind and (m := re.match(r"^\s+([A-Za-z0-9_]+)\s+(.+)$", line)):
            triggers[m.group(1)] = LoraTrigger(trigger=m.group(1), kind=kind, description=m.group(2).strip())
        elif line.strip() and not line.startswith(" "):
            kind = None

    if image_doc:
        _merge_image_doc(g, image_doc, triggers, warnings)
    g.lora_triggers = list(triggers.values())
    return g


def _json_block(doc: str, marker: str, warnings: list[str]):
    block = _code_block_after(doc, marker)
    if block is None:
        warnings.append(f"image提示词：没有找到 {marker}")
        return None
    try:
        return json.loads(block)
    except json.JSONDecodeError as e:
        warnings.append(f"image提示词：{marker} 不是合法 JSON：{e}")
        return None


def _merge_image_doc(g: ScriptGlobals, doc: str, triggers: dict[str, LoraTrigger], warnings: list[str]):
    # 数据 B 装饰状态总表
    block = _code_block_after(doc, "数据B")
    for part in re.split(r"[｜\n]", block or ""):
        m = re.match(r"^\s*ep(\d+)(?:-(\d+))?:(D\d+|DN)(.*)$", part.strip())
        if not m:
            continue
        first = int(m.group(1))
        last = int(m.group(2) or first)
        note = m.group(4).strip()
        overrides = {int(ep): st for ep, st in re.findall(r"(\d+)为(D\d+|DN)", note)}
        g.decor_schedule.append(DecorRange(first_ep=first, last_ep=last, state=m.group(3),
                                           note=note, overrides=overrides))
    if not g.decor_schedule:
        warnings.append("image提示词：数据B 装饰状态总表为空")

    for item in _json_block(doc, "数据D", warnings) or []:
        g.references.append(ReferenceImage(id=item["id"], description=item.get("desc", ""),
                                           usage=item.get("用途")))

    for item in _json_block(doc, "数据E", warnings) or []:
        t = item["trigger"]
        kind = "video" if "视频" in item.get("类型", "") else "image"
        entry = triggers.get(t) or LoraTrigger(trigger=t, kind=kind, description=item.get("内容", ""))
        entry.file = item.get("文件")
        entry.strength = _parse_strength(item.get("强度"))
        entry.starts = item.get("起用")
        triggers[t] = entry
    for t in triggers.values():
        if t.file is None:
            warnings.append(f"触发词 {t.trigger} 在数据E里没有对应的 LoRA 文件")


def decor_state_for(schedule: list[DecorRange], ep: int) -> str | None:
    for r in schedule:
        if r.first_ep <= ep <= r.last_ep:
            return r.overrides.get(ep, r.state)
    return None


# ------------------------------------------------------------------ 分集 / 分镜

def _parse_episodes(script: str, known_triggers: set[str], warnings: list[str]) -> list[Episode]:
    episodes: list[Episode] = []
    ep: Episode | None = None
    shot: Shot | None = None
    # 当前字段的写入目标，用来接续多行内容
    target: tuple[object, str] | None = None
    # 正在收集的 **H3提示词**（多行、含空行，逐字）
    h3_shot: Shot | None = None
    h3_lines: list[str] = []

    def finish_h3():
        nonlocal h3_shot, h3_lines
        if h3_shot is not None:
            h3_shot.h3_prompt = "\n".join(h3_lines).strip("\n") or None
        h3_shot, h3_lines = None, []

    def write(obj, attr, value, append=False):
        if attr == "_extra":
            obj.text = (obj.text + "\n" + value).strip() if append else value
        elif attr == "voiceover":
            vo = obj.voiceover
            vo.text = (vo.text + "\n" + value).strip() if append else value
        else:
            old = getattr(obj, attr) or ""
            setattr(obj, attr, (old + "\n" + value).strip() if append else value)

    for lineno, raw in enumerate(script.splitlines(), start=1):
        # 原稿部分行是转义过的 Markdown（\*\*镜2…），先还原
        line = raw.rstrip().replace(r"\*", "*").replace(r"\`", "`")

        if h3_shot is not None:
            if (SHOT_RE.match(line) or FIELD_RE.match(line) or EP_RE.match(line) or line.startswith("# ")
                    or line.startswith("## ") or line.strip() == "---"):
                finish_h3()      # 字段结束，本行照常处理
            else:
                if not line.strip().startswith("```"):   # 允许用代码块包起来
                    h3_lines.append(line)
                continue

        if m := EP_RE.match(line):
            tail = m.group(3).strip()
            ep = Episode(number=int(m.group(1)), title=m.group(2), high_intensity="🔴" in tail,
                         tag=tail.replace("🔴", "").strip(), source_line=lineno)
            episodes.append(ep)
            shot, target = None, None
            continue
        if line.startswith("# ") or line.startswith("## "):
            ep, shot, target = None, None, None
            continue
        if ep is None:
            continue
        if not line.strip() or line.strip() == "---":
            target = None
            continue

        if m := SHOT_RE.match(line):
            shot = Shot(episode=ep.number, index=int(m.group(1)), img_note=m.group(2),
                        img_prompt=_unwrap(m.group(3)), source_line=lineno)
            ep.shots.append(shot)
            target = (shot, "img_prompt")
            continue

        if m := FIELD_RE.match(line):
            label, value = m.group(1), _unwrap(m.group(2) or "")
            base, note = _split_label(label)
            if base == "剧情":
                ep.synopsis, target = value, (ep, "synopsis")
            elif base == "配乐" and shot is None:
                ep.music, target = value, (ep, "music")
            elif shot is not None and base in H3_LABELS:
                first = (m.group(2) or "").strip()
                h3_shot, h3_lines = shot, ([first] if first and not first.startswith("```") else [])
                target = None
            elif base == "负面追加":
                ep.negative_extra, target = value, (ep, "negative_extra")
            elif shot is None or base not in {"motion", "sound", "🎙", "对白", "时长"} | SHOT_EXTRA_LABELS:
                extra = Extra(label=label, text=value)
                ep.extras.append(extra)
                target = (extra, "_extra")
            elif base == "时长":
                m_sec = re.search(r"\d+", value)
                if m_sec and MIN_SHOT_SECONDS <= int(m_sec.group()) <= MAX_SHOT_SECONDS:
                    shot.duration, shot.duration_source = int(m_sec.group()), "script"
                else:
                    warnings.append(f"{shot.id} 时长无法识别或超出 {MIN_SHOT_SECONDS}–{MAX_SHOT_SECONDS} 秒：{value}")
                target = None
            elif base == "motion":
                shot.motion_prompt, target = value, (shot, "motion_prompt")
            elif base == "sound":
                shot.sound, target = value, (shot, "sound")
            elif base == "🎙":
                shot.voiceover = Voiceover(note=note, text=value)
                target = (shot, "voiceover")
            elif base == "对白":
                # "对白（无台词…）" 这种空标签不能覆盖已有台词
                if value:
                    shot.dialogue_raw = f"{shot.dialogue_raw}／{value}" if shot.dialogue_raw else value
                target = (shot, "dialogue_raw")
            else:
                extra = Extra(label=label, text=value)
                shot.extras.append(extra)
                target = (extra, "_extra")
            continue

        # 续行：接到上一个字段
        if target is not None:
            write(*target, _unwrap(line), append=True)
        else:
            warnings.append(f"第 {lineno} 行无法归属：{line[:40]}")

    finish_h3()
    for ep in episodes:
        for s in ep.shots:
            s.img_triggers = _leading_triggers(s.img_prompt, known_triggers)
            s.motion_triggers = _leading_triggers(s.motion_prompt, known_triggers)
            if s.dialogue_raw:
                s.dialogue = _parse_dialogue(s.dialogue_raw)
            s.sound_intimate, s.sound_h3 = _sound_blocks(s.sound)
            s.music_cue = _block(s.sound, "配乐")
        ep.music_bgm = _block(ep.music, "BGM")
    return episodes


SOUND_TAGS = ("亲密声", "配乐", "H3 audio", "BGM")


def _block(text: str, tag: str) -> str:
    """取出【tag】后面的内容，到下一个已知【…】标记或结尾为止（整行原文另行保留）"""
    others = "|".join(re.escape(f"【{t}】") for t in SOUND_TAGS if t != tag)
    m = re.search(rf"【{re.escape(tag)}】\s*(.*?)(?={others}|$)", text, re.S)
    return m.group(1).strip().rstrip("；;，, ") if m else ""


def _sound_blocks(sound: str) -> tuple[str, str]:
    """v3 的 sound 行：原文；【亲密声】…；【配乐】…；【H3 audio】…（整行原文仍保留在 sound）"""
    return _block(sound, "亲密声"), _block(sound, "H3 audio")


def _validate(episodes: list[Episode], warnings: list[str]):
    numbers = [e.number for e in episodes]
    missing = sorted(set(range(1, EPISODE_COUNT + 1)) - set(numbers))
    if missing:
        warnings.append(f"缺少集数：{missing}")
    dupes = sorted({n for n in numbers if numbers.count(n) > 1})
    if dupes:
        warnings.append(f"重复集数：{dupes}")
    for ep in episodes:
        idx = [s.index for s in ep.shots]
        if idx != list(range(1, len(idx) + 1)):
            warnings.append(f"ep{ep.number:02d} 镜号不连续：{idx}")
        if not SHOTS_PER_EPISODE[0] <= len(idx) <= SHOTS_PER_EPISODE[1]:
            warnings.append(f"ep{ep.number:02d} 有 {len(idx)} 镜（应为 {SHOTS_PER_EPISODE[0]}–{SHOTS_PER_EPISODE[1]}）")
        for s in ep.shots:
            for field in ("img_prompt", "motion_prompt", "sound"):
                if not getattr(s, field):
                    warnings.append(f"{s.id} 缺少 {field}")
        # 只在剧本写了时长时检查整集总长（v2 没写，全部默认 10 秒）
        if any(s.duration_source == "script" for s in ep.shots):
            total = sum(s.duration for s in ep.shots)
            if not EPISODE_SECONDS[0] <= total <= EPISODE_SECONDS[1]:
                warnings.append(f"ep{ep.number:02d} 总时长 {total} 秒，超出 {EPISODE_SECONDS[0]}–{EPISODE_SECONDS[1]} 秒")


def import_script(script_path: Path, image_doc_path: Path | None = None) -> ScriptImport:
    warnings: list[str] = []
    script = script_path.read_text(encoding="utf-8")
    image_doc = image_doc_path.read_text(encoding="utf-8") if image_doc_path else None
    sources = [SourceFile(path=str(script_path), sha256=_sha256(script_path))]
    if image_doc_path:
        sources.append(SourceFile(path=str(image_doc_path), sha256=_sha256(image_doc_path)))

    g = _parse_globals(script, image_doc, warnings)
    episodes = _parse_episodes(script, {t.trigger for t in g.lora_triggers}, warnings)
    for ep in episodes:
        state = decor_state_for(g.decor_schedule, ep.number)
        for s in ep.shots:
            s.decor_state = state
        if g.decor_schedule and state is None:
            warnings.append(f"ep{ep.number:02d} 在装饰状态总表里没有对应状态")
    _validate(episodes, warnings)
    return ScriptImport(sources=sources, globals=g, episodes=episodes, warnings=warnings)
