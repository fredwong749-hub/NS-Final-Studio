"""剧本导入结果的数据结构。导入器只做确定性解析，原文原样保留，代称消解等交给 Agent。"""
from typing import Literal

from pydantic import BaseModel, Field


class CharacterLock(BaseModel):
    name: str
    description: str


class LoraTrigger(BaseModel):
    trigger: str
    kind: Literal["image", "video"]
    description: str
    file: str | None = None
    strength: tuple[float, float] | None = None
    starts: str | None = None


class ReferenceImage(BaseModel):
    id: str
    description: str
    usage: str | None = None


class DecorRange(BaseModel):
    first_ep: int
    last_ep: int
    state: str
    note: str = ""
    overrides: dict[int, str] = Field(default_factory=dict)


class ScriptGlobals(BaseModel):
    character_locks: list[CharacterLock] = Field(default_factory=list)
    motion_suffix: str = ""
    image_suffix: str = ""  # 剧本里的“每条img统一后缀”（全局画面风格）
    base_negative: str = ""
    lora_triggers: list[LoraTrigger] = Field(default_factory=list)
    references: list[ReferenceImage] = Field(default_factory=list)
    decor_schedule: list[DecorRange] = Field(default_factory=list)


class DialogueLine(BaseModel):
    speaker_note: str | None  # 紧挨台词的最后一个括号，如 "顾沉低声"、"她，很小声"
    text: str
    stage: str | None = None  # 更前面的括号（舞台提示），如 "接通"


class Voiceover(BaseModel):
    note: str | None  # 如 "镜1尾入"、"全集收尾独白"
    text: str


class Extra(BaseModel):
    label: str
    text: str


class Shot(BaseModel):
    episode: int
    index: int
    img_note: str | None = None
    img_prompt: str = ""
    img_triggers: list[str] = Field(default_factory=list)
    motion_prompt: str = ""
    motion_triggers: list[str] = Field(default_factory=list)
    sound: str = ""                 # **sound** 整行原文
    sound_intimate: str = ""        # v3：sound 行里的【亲密声】…段
    sound_h3: str = ""              # v3：sound 行里的【H3 audio】…段（给 H3 的英文声音描述）
    music_cue: str = ""             # v3：sound 行里的【配乐】…段（进入/延续/推高/落下/点题，强度 0–3，压低）
    h3_prompt: str | None = None    # v3：**H3提示词** 原文（SOP §9A.1 四块官方 FL2VA 全文，多行，逐字保留；S1-W7–W9）
    voiceover: Voiceover | None = None
    dialogue_raw: str | None = None
    dialogue: list[DialogueLine] = Field(default_factory=list)
    extras: list[Extra] = Field(default_factory=list)
    decor_state: str | None = None
    duration: int = 10              # 秒；剧本 **时长**：N秒（3–15），没写时默认 10
    duration_source: str = "default"   # script | default
    adult: bool | None = None       # 导入时由编译器分类写入（两边共用同一判定：关键词 + config/adult_overrides.json）
    adult_reasons: list[str] = Field(default_factory=list)
    source_line: int

    @property
    def id(self) -> str:
        return f"ep{self.episode:02d}-S{self.index}"


class Episode(BaseModel):
    number: int
    title: str
    high_intensity: bool = False  # 标题带 🔴
    tag: str = ""
    synopsis: str = ""
    music: str = ""                 # v3：**配乐** 整行原文（本集背景音乐，后期用）
    music_bgm: str = ""             # v3：配乐行里的【BGM】…（给音乐模型的英文提示）
    negative_extra: str = ""
    shots: list[Shot] = Field(default_factory=list)
    extras: list[Extra] = Field(default_factory=list)
    source_line: int


class SourceFile(BaseModel):
    path: str
    sha256: str


class ScriptImport(BaseModel):
    sources: list[SourceFile]
    globals: ScriptGlobals
    episodes: list[Episode]
    warnings: list[str] = Field(default_factory=list)
