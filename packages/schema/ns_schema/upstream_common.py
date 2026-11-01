"""上游链条（P0→P4）共用：校验结果结构、JSON 提取、格式小检查（CHAINSPEC 2026-10-31）。

只查格式与可实现性（字段齐不齐、id 合不合法、下游能不能逐字接上），不评价剧情和内容。
规则号与 config/pipeline/chain.yaml 的 rules 一一对应；check_chain.py 校验两边一致。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from pydantic import BaseModel, ValidationError

CJK_RE = re.compile(r"[㐀-鿿豈-﫿　-〿＀-￯]")
NEG_EN_RE = re.compile(r"\b(no|not|never|without|don't|doesn't|avoid|nothing|none|nobody|neither|nor)\b|n't\b", re.I)
SCENE_ID_RE = re.compile(r"^sk_[a-z0-9_]+$")
CHAR_ID_RE = re.compile(r"^(lin_wan|gu_chen|chen_yu|ch_[a-z0-9_]+)$")   # CLEANUP 11-01（总调度 R16）：旧 60 集 alex/ryan/kai/leo 撤下；阿岚 = ch_a_lan
PUNCT_RE = re.compile(r"[\s，。！？、；：,.!?;:…—\-“”\"'‘’（）()《》【】]")
SPEECH_CPS = 3.5          # 字 / 秒：config/script_chat_rules.md §2“对白（不计标点）≤ 3.5×N”
EPISODE_S = (60, 120)     # 每集秒数：script_chat_rules.md §2“各镜 N 之和 60–120 秒”（项目方 11-01 21:4x：“改成 60–120 秒”，L-092 / D-SCR-08）
SHOT_MAX_S = 15           # 单镜上限（H3-A11 / 官方 5.5 第 2 项）


@dataclass
class Issue:
    rule: str
    level: str            # block | warn
    message: str
    field: str = ""

    def as_dict(self) -> dict:
        return {"rule": self.rule, "level": self.level, "field": self.field, "message": self.message}


@dataclass
class Report:
    node: str
    issues: list[Issue] = field(default_factory=list)
    obj: object | None = None

    def add(self, rule: str, level: str, message: str, fld: str = "") -> None:
        self.issues.append(Issue(rule, level, message, fld))

    @property
    def ok(self) -> bool:
        return not any(i.level == "block" for i in self.issues)

    def as_dict(self) -> dict:
        return {"node": self.node, "ok": self.ok, "blocking": sum(i.level == "block" for i in self.issues),
                "warnings": sum(i.level != "block" for i in self.issues), "issues": [i.as_dict() for i in self.issues]}


FENCE_RE = re.compile(r"```(?:json)?\s*\n(.*?)\n```", re.S)


def extract_json(text: str):
    """写作模型回复 → JSON 对象。允许外面包一层 ```json 代码块；其余前后缀不允许（格式规则 *-01）。"""
    t = (text or "").strip()
    m = FENCE_RE.search(t)
    if m:
        t = m.group(1).strip()
    if not t.startswith("{"):
        i = t.find("{")
        if i < 0:
            raise ValueError("回复里没有 JSON 对象")
        t = t[i:]
    obj, end = json.JSONDecoder().raw_decode(t)
    return obj


def parse_model(rep: Report, rule: str, model: type[BaseModel], data):
    """解析 + schema 校验；失败记 block（rule = 各节点的 *-01）"""
    try:
        if isinstance(data, str):
            data = extract_json(data)
        obj = model.model_validate(data)
        rep.obj = obj
        return obj
    except (ValueError, ValidationError) as e:
        msg = str(e)
        if isinstance(e, ValidationError):
            msg = "；".join(f"{'.'.join(str(x) for x in er['loc'])}: {er['msg']}" for er in e.errors()[:12])
        rep.add(rule, "block", f"输出不是合规的 JSON / 不符合 schema：{msg}")
        return None


def en_problems(text: str, names: list[str] = ()) -> list[str]:
    """进 H3 的英文短语：非空、无中文、无否定词、无双引号、无人名 / 触发词（同 validate_qwen_script._en_problems）"""
    probs = []
    if not (text or "").strip():
        return ["为空"]
    if CJK_RE.search(text):
        probs.append("有中文")
    neg = sorted({x.group(0).lower() for x in NEG_EN_RE.finditer(text)})
    if neg:
        probs.append("否定词：" + "、".join(neg))
    if any(q in text for q in ('"', "“", "”")):
        probs.append("有双引号")
    bad = [n for n in names if n and re.search(rf"(?<![A-Za-z0-9_]){re.escape(n)}(?![A-Za-z0-9_])", text, re.I)]
    if bad:
        probs.append("含人名 / 触发词：" + "、".join(bad))
    return probs


def spoken_len(text: str) -> int:
    """对白字数（不计标点与空白）"""
    return len(PUNCT_RE.sub("", text or ""))


def norm(text: str) -> str:
    return re.sub(r"\s+", "", text or "")
