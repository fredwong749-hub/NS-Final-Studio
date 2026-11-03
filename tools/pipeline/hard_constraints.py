"""系统硬约束机检（SERIES 2026-10-31，总调度转项目方要求；knowledge K-WRT-205）。只做关键词与数值检查，不评价内容。

HC-01 人物表年龄 ≥22；HC-02 未成年化词语（block）/ 需留意词（warn）；HC-05 出场人物都要登记、每人 2–3 套固定造型 + 标志物；
HC-06（由调用方做）P4 造型 EN 不在登记里 → warn。
英文 minor：只排除音乐调式上下文（A minor / C# minor / minor key / minor chord …），其余一律 block——
series10_v1 曾因把 “A minor” 当未成年词误判两次，修误判时不放宽成年人校验。
"""
from __future__ import annotations

import json
import re

BLOCK_WORDS = ["未成年", "儿童", "小孩", "孩子", "幼女", "幼态", "幼童", "萝莉", "学生妹", "女学生", "中学生", "小学生", "高中生",
               "初中生", "校服", "童颜",
               "teen", "child", "kid ", "kids", "schoolgirl", "school uniform", "loli", "underage", "little girl",
               "young girl", "preteen", "juvenile"]
WARN_WORDS = ["少女", "girl", "稚", "娃娃脸", "baby face", "petite"]

# 音乐语境里的 minor：调名在前（A minor、C# minor、B-flat minor、F sharp minor），或后接 key / chord / scale / mode / third …
_MUSIC_MINOR = re.compile(
    r"\b[A-G](?:#|♯|♭|b|-flat|-sharp| flat| sharp)?\s+minor\b"
    r"|\bminor[\s-](?:key|keys|chord|chords|scale|scales|mode|third|thirds|seventh|sixth|progression|tonality|harmony|harmonies|melody|motif|tone|tones|piano|strings|pad)\b"
    r"|\bin\s+(?:a\s+)?minor\b(?=\s*(?:key|,|\.|;|$))")
_MINOR = re.compile(r"\bminors?\b", re.I)


def scan(text: str) -> tuple[list[str], list[str]]:
    t = _MUSIC_MINOR.sub(" <music-key> ", text or "")
    low = t.lower()
    blk = [w for w in BLOCK_WORDS if w in low]
    if _MINOR.search(t):
        blk.append("minor")
    return blk, [w for w in WARN_WORDS if w in low]


def check_text(text: str) -> list[dict]:
    blk, wrn = scan(text)
    out = []
    if blk:
        out.append({"rule": "HC-02", "level": "block", "message": f"出现未成年化词语：{blk}（全部角色是成年人，删掉或改写这些词）"})
    if wrn:
        out.append({"rule": "HC-02", "level": "warn", "message": f"需留意的词：{wrn}"})
    return out


def check_story(story: dict, looks: list | None) -> list[dict]:
    issues = []
    for c in story.get("characters", []):
        if int(c.get("age", 0)) < 22:
            issues.append({"rule": "HC-01", "level": "block", "message": f"{c['name']} 年龄 {c.get('age')}：人物表年龄须 ≥22"})
    issues += check_text(json.dumps(story, ensure_ascii=False) + json.dumps(looks or [], ensure_ascii=False))
    if looks is not None:
        names = {c["name"] for c in story.get("characters", [])}
        got = {l.get("name") for l in looks}
        if names - got:
            issues.append({"rule": "HC-05", "level": "block", "message": f"这些角色没有登记固定造型：{sorted(names - got)}"})
        for l in looks:
            n = len(l.get("looks") or [])
            if not 2 <= n <= 3:
                issues.append({"rule": "HC-05", "level": "block", "message": f"{l.get('name')} 固定造型须 2–3 套，现为 {n}"})
            if not (l.get("marker") or "").strip():
                issues.append({"rule": "HC-05", "level": "block", "message": f"{l.get('name')} 缺标志物 marker"})
            for k in l.get("looks") or []:
                if not k.get("id") or not k.get("zh") or not k.get("en") or "|" in (k.get("zh", "") + k.get("en", "")):
                    issues.append({"rule": "HC-05", "level": "block", "message": f"{l.get('name')} 造型 {k.get('id')}：id / zh / en 都要填，格内不用半角 |"})
    roster = {c["name"] for c in story.get("characters", [])}
    for e in story.get("episodes", []):
        for m in set(re.findall(r"[A-Z][a-z]{2,}", e.get("logline", ""))):
            if m not in roster:
                issues.append({"rule": "HC-05", "level": "block",
                               "message": f"ep{e['episode']} logline 出现人物表外的名字 {m}：加入人物表，或改为画外 / 不露脸、不点名"})
    return issues


# HC-07 已锁定角色的外貌锚点（发色、发型、标志物）不得被剧情改变（项目方 2026-10-31 决定：ep03“为他改换发色”改掉）。
# 只抓“改变”动作；“真实染发色”这类描述锁定发色本身的名词不算。
_LOOK_CHANGE = re.compile(
    r"(?:改|换|剪|漂|烫|重新染|染成|染了|变)(?:了|掉|短|成)?(?:个|一个)?(?:新)?(?:头发|发色|发型|发尾)"
    r"|发色(?:改|换|变)|发型(?:改|换|变)"
    r"|(?:头发|发色|发型)(?:被)?(?:染|剪|改|换|漂|烫)(?:成|了|短|掉)"
    r"|\b(?:dyes?|dyed|dyeing|bleach(?:es|ed)?|cuts?|chops?)\s+(?:off\s+)?her\s+hair\b"
    r"|\bnew\s+hair\s*colou?r\b|\bchang(?:e|es|ed|ing)\s+her\s+(?:hair|hairstyle|hair\s*colou?r)\b"
    # 标志物（林晚：5 厘米透明镶钻水晶甲）：同款重涂合规（总调度 2026-10-31）；换色 / 换款 / 改长短 / 卸掉不再做 → 拦
    r"|(?:甲|指甲|美甲)[^。；\n]{0,8}?(?:换成|改成|涂成|染成|剪成|磨成|修成|变成)[^。；\n]{0,10}?(?:色|款|短|长|圆|方|哑光|单色)"
    r"|(?:换|改)(?:了)?(?:个|一个)?(?:新)?(?:颜色|款式|色)[^。；\n]{0,4}?(?:甲|指甲|美甲)"
    r"|(?:红|黑|白|粉|紫|蓝|绿|金|银|裸)色(?:的)?(?:指甲|美甲|甲油|短甲)"
    r"|\bnails?\b[^.;\n]{0,20}?\b(?:painted|polished|lacquered|dyed)\s+(?:in\s+)?(?:red|black|pink|white|nude|purple|gold|silver|green)\b"
    r"|\b(?:red|black|pink|nude|purple|gold|green)\s+(?:nail\s*polish|nails)\b|\bshort\s+nails\b|\bnew\s+nails\b", re.I)


def check_look_lock(text: str, extra_banned: list[str] | None = None) -> list[dict]:
    """extra_banned：已作废的标志物写法（如 “痣”、“mole”），出现即 block"""
    out = []
    hits = sorted({m.group(0) for m in _LOOK_CHANGE.finditer(text or "")})
    if hits:
        out.append({"rule": "HC-07", "level": "block",
                    "message": f"剧情改变了已锁定角色的外貌锚点（发色 / 发型 / 标志物不得改变）：{hits}；换一个不改变外貌的等效情节点"})
    bad = [w for w in extra_banned or [] if w and (re.search(rf"\b{re.escape(w)}s?\b", text or "", re.I) if w.isascii()
                                                   else w in (text or ""))]
    if bad:
        out.append({"rule": "HC-07", "level": "block", "message": f"出现已作废的标志物写法：{bad}（标志物以全局头角色锁为准）"})
    return out
