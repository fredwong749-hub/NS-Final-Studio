"""FIX（ep02_iter P0，chain_audit A12 / B4）：写作模型输出的确定性校验（只用标准库）。

写作模型（外部 API 网关）写 H3 英文段 / 台词时，系统不评价内容，只校验它有没有把剧本忠实传下去：

- D1  <d> 里只有“[语言] 台词原文”：不得带说话人、语气、舞台提示（重放：“<d>[Chinese] 顾沉，声音低沉克制：方案第三页…”）；
      语言标签只能是一个语言词（“[Chinese, Chen Yu's warm … voice]” 不合格）
- D2  <d> 台词与剧本台词逐字（去首尾空白）、同顺序、同数量
- N1  <d> 外不出现角色名（中文名 / 拼音；H3 不认识名字，身份信息全丢）
- P1  只被提到 / 画外的角色：其外貌短语不得出现（“the suit collar of Gu Chen, a 34-year-old adult male CEO…”
      等于让他在场）
- A1  每个在画角色的锚点短语（含族裔）必须逐字出现

不通过 → 调用方带着错误重试或打回写作方（needs_writer），绝不进渲染。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

D_RE = re.compile(r"<d>(.*?)</d>", re.S)
LANG_TAG_RE = re.compile(r"^\[([A-Za-z]+)\]\s?(.*)$", re.S)
# 台词开头像“名字/代称 + 逗号或冒号”的说话人 / 语气前缀（“顾沉，声音低沉克制：”“她慌：”“(林晚，慌)”）
SPEAKER_PREFIX_RE = re.compile(r"^\s*[（(]?[一-鿿A-Za-z ]{1,12}[，,、]?[^：:]{0,16}[：:]")
STAGE_WORDS = ("声音", "语气", "低声", "轻声", "说道", "开口", "慌", "背对", "画外", "voice", "tone", "says")


@dataclass
class CheckResult:
    errors: list[dict] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def add(self, rule: str, detail: str) -> None:
        self.errors.append({"rule": rule, "detail": detail})


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def pinyin_aliases(name_map: dict[str, list[str]] | None) -> dict[str, list[str]]:
    return {k: list(v) for k, v in (name_map or {}).items()}


def check_writer_output(text: str, *, dialogue: list[str], names: dict[str, list[str]] | None = None,
                        on_screen_anchors: dict[str, list[str]] | None = None,
                        absent_phrases: dict[str, list[str]] | None = None) -> CheckResult:
    """text = 写作模型写出的 H3 段（integrated_multimodal_description 或整段提示词）。
    dialogue = 本镜剧本台词（按顺序，只要台词原文）；names = {角色: [中文名, 拼音写法…]}（任何角色）；
    on_screen_anchors = {在画角色: [必须逐字出现的短语，如 EN 外貌短语 / 'East Asian']}；
    absent_phrases = {只被提到 / 画外的角色: [不得出现的外貌短语]}"""
    r = CheckResult()
    blocks = D_RE.findall(text or "")
    if (text or "").count("<d>") != (text or "").count("</d>"):
        r.add("D1", "<d> 与 </d> 不成对")
    got = []
    for b in blocks:
        m = LANG_TAG_RE.match(b.strip())
        if not m:
            r.add("D1", f"<d> 不是“[语言] 原文”格式（语言标签只能是一个词）：{b.strip()[:30]}")
            got.append(b.strip())
            continue
        line = m.group(2).strip()
        got.append(line)
        if line not in [d.strip() for d in dialogue]:
            pre = SPEAKER_PREFIX_RE.match(line)
            if pre and (any(w in pre.group(0) for w in STAGE_WORDS) or
                        any(n in pre.group(0) for v in (names or {}).values() for n in v)):
                r.add("D1", f"<d> 里带了说话人 / 语气：「{pre.group(0)}」")
    want = [_norm(d) for d in dialogue]
    if [_norm(g) for g in got] != want:
        r.add("D2", f"<d> 台词与剧本不逐字一致：剧本 {[d for d in dialogue]}，写出 {got}")
    outside = D_RE.sub(" ", text or "")
    for who, aliases in (names or {}).items():
        hit = [a for a in aliases if a and re.search(r"(?<![A-Za-z])" + re.escape(a) + r"(?![A-Za-z])", outside)]
        if hit:
            r.add("N1", f"<d> 外出现了角色名 {who}（{'、'.join(hit)}）：H3 不认识名字，改用人物表 EN 外貌短语")
    low = outside.lower()
    for who, phrases in (on_screen_anchors or {}).items():
        miss = [p for p in phrases if p and p.lower() not in low]
        if miss:
            r.add("A1", f"在画角色 {who} 缺锚点短语：{'；'.join(miss)}")
    for who, phrases in (absent_phrases or {}).items():
        hit = [p for p in phrases if p and p.lower() in low]
        if hit:
            r.add("P1", f"不在画的角色 {who} 的外貌出现在正文里（等于让他在场）：{'；'.join(hit)}")
    return r
