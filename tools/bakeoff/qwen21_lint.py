"""Qwen Image 2.1 出图提示词 lint（BAKEOFF，R11-12）。只做格式和结构检查，不改写、不评价剧本内容。

每条规则 = 一种在真实坏例里出现过、而且模型写法研究（docs/qwen21/RESEARCH.md）能解释的提示词结构问题。
lint(prompt, size=None, on_screen=None) → [{"id", "level": "error"|"warn", "evidence", "owner": "writer"|"compiler"}]
  owner=writer   = 剧本 img 原文的写法（交写作方 / writer_text 规则 QW-*）
  owner=compiler = 系统拼进去的部分（交 REFLOCK：ns_agent.compiler / asset_refs / frame_job）
规则 id 与说明见 RULES；知识库条目 knowledge/rules/render_qwen21.yaml（K-PRM-Q2*）引用本文件作检查。
"""
from __future__ import annotations

import re

RULES = {
    "QL01": "景别与必须入画部件冲突：特写 / 近景 / 局部特写却要求腰以下部件（裙、裤、鞋、跟、腿、脚）入画",
    "QL02": "局部特写（只拍手 / 脚等）却写了在画人物的整段身份描述或脸、肩、胸等部位",
    "QL03": "正向提示词里的否定句（不…、无…、不是…、别…）：cfg 1 下负面不起作用，否定词反而把被否定的东西带进画面",
    "QL04": "油 / 湿润 / 镜面高光类词：本意是漆皮材质，但离人物描述很近，容易让皮肤也变得油亮",
    "QL05": "原始 id / 方括号标签直接进了提示词（sk_xxx、【林晚】、【场景】），模型会当成要画出来的文字",
    "QL06": "两人同框要求“两张脸都清晰入画”，却又写某人在前景虚化 / 背影 / 局部",
    "QL07": "景别句不是参考标注之后的第一句（被身份描述、场景段挤到后面）",
    "QL08": "提示词过长（> 700 字）：后段的场景和后缀权重被稀释",
    "QL09": "同一场景信息写了两遍以上（【场景】段 + 本镜场景 + 正文重复）",
    "QL10": "质感词堆叠：“毛孔 / 绒毛 / 皮肤纹理 / 真实皮肤”在同一提示词里出现 3 次以上（待 A/B 验证是否反而磨皮）",
    # 以下来自官方写法调研（docs/qwen21/RESEARCH.md 结论编号）
    "QL11": "参考图写成“图N”而不是官方的 <imageN>（结论 2：编码模板拼的是字面 <image1>，官方改写器禁止“图1”写法）",
    "QL12": "括号权重语法 (词:1.2)：Qwen3-VL 分词器 disable_weights=True，括号原样当文字（结论 6）",
    "QL13": "质量助推词（焦点锐利 / 皮肤纹理清晰 / 微反差强 / 高清 / 8K / masterpiece）：官方改写器不写，要写看得见的光源、方向、材质（结论 7）",
    "QL14": "挂了身份脸参考，正文又用文字写五官 / 肤色 / 眼睛（结论 3：文字描述长相会让模型重画、降低相似度）",
    "QL15": "写具体岁数（“22岁”）：官方人物描述只写年龄段（in her twenties），具体数字无益（结论 16）",
}

CLOSE = ("大特写", "极近特写", "特写", "近景", "中近景")
LOWER = ("裙", "裤", "鞋", "跟高", "细跟", "高跟", "鞋尖", "腿", "脚踝", "脚")
NEG = re.compile(r"(不是[^，。；]{1,14}|不(?!锈|对称|同|少|久|远|过|断|停|住|透明|规则|安|足|禁|自觉|知不觉|一样|如)[^，。；]{1,12}|无(?!名指|袖|框|线|人机)[^，。；]{1,10}|别(?!墅|针|致)[^，。；]{1,10})")
OIL = re.compile(r"抹了油|油亮|油光|湿润光泽|湿漉|镜面反射|高光锐利")
RAWID = re.compile(r"\bsk_[a-z_0-9]+|【[^】]{1,6}】")
SKIN = re.compile(r"毛孔|绒毛|皮肤纹理|皮肤质感|真实皮肤")
WEIGHT = re.compile(r"\([^()]{1,30}:\s*\d(?:\.\d+)?\)")
BOOST = re.compile(r"焦点锐利|皮肤纹理清晰|微反差强|五官锐利|高清|超清|8K|4K|masterpiece|best quality|highly detailed")
FACEDESC = re.compile(r"冷白皮肤|白皙|深棕色眼睛|[^，。]{0,6}眼睛为[^，。]{0,8}|瓜子脸|鹅蛋脸|高鼻梁|丹凤眼|大眼睛|双眼皮")
AGE = re.compile(r"\d{2}岁")
REF_LINE = re.compile(r"^(?:图\d+是[^。]*。)+")
SIZE_LEAD = re.compile(r"^(大特写|极近特写|特写|近景|中近景|中景|中全景|全景|全身|远景|大远景|空镜)")


def _size_of(prompt, size):
    if size:
        return size
    m = SIZE_LEAD.search(REF_LINE.sub("", prompt))
    return m.group(1) if m else None


def _body(prompt):
    """正文：去掉参考标注、系统风格后缀"""
    b = REF_LINE.sub("", prompt)
    i = b.find("专业电影画面")
    return b[:i] if i > 0 else b


def lint(prompt: str, size: str | None = None, on_screen=None) -> list[dict]:
    out = []
    p = prompt or ""
    size = _size_of(p, size)
    body = _body(p)

    def add(rid, ev, owner, level="warn"):
        out.append({"id": rid, "level": level, "evidence": ev[:80], "owner": owner})

    part = "只拍" in body and ("局部" in body or "不出现完整人物" in body or "手这一局部" in body)
    if size in CLOSE and not part:
        hits = [w for w in LOWER if w in body]
        if hits:
            # 系统补的“要穿全：…”句是编译器的；剧本句里写到的是写作方的
            sys_part = "要穿全" in body and any(w in body[body.find("要穿全"):] for w in hits)
            add("QL01", f"{size}却写了：{'、'.join(hits[:5])}", "compiler" if sys_part else "writer", "error")
    if part:
        hits = [w for w in ("岁", "脸", "眼", "嘴", "发", "肩", "胸", "锁骨") if w in body]
        if hits:
            add("QL02", "局部特写却写了：" + "、".join(hits[:6]), "compiler" if "岁" in hits else "writer", "error")
    negs = [m.group(1) for m in NEG.finditer(REF_LINE.sub("", p).split("专业电影画面")[0])]
    if negs:
        add("QL03", "；".join(negs[:4]), "compiler" if any(x.startswith(("不出现", "不背对", "不是", "不入画", "不取")) for x in negs) else "writer")
    oil = OIL.findall(body)
    if oil:
        add("QL04", "、".join(sorted(set(oil))), "writer")
    raw = RAWID.findall(p)
    if raw:
        add("QL05", "、".join(sorted(set(raw))[:5]), "compiler", "error")
    if ("两张脸都清晰入画" in body or "两人同框" in body) and re.search(r"前景虚化|背影|(?<!不)背对|在前景.{0,4}虚", body):
        add("QL06", "要求两张脸清晰，同时写了前景虚化 / 背影 / 局部", "writer", "error")
    b0 = REF_LINE.sub("", p)
    if size and not SIZE_LEAD.match(b0):
        add("QL07", "参考标注后第一句：" + b0[:20], "compiler")
    if len(p) > 700:
        add("QL08", f"{len(p)} 字", "compiler")
    if body.count("【场景】") + body.count("本镜场景") + body.count("空间描述") >= 3:
        add("QL09", "【场景】/ 空间描述 / 本镜场景 都在", "compiler")
    sk = SKIN.findall(p)
    if len(sk) >= 3:
        add("QL10", f"{len(sk)} 处：" + "、".join(sk[:5]), "compiler")
    if re.search(r"图\d+是", p):
        add("QL11", "、".join(sorted(set(re.findall(r"图\d+", p)))[:4]), "compiler")
    if WEIGHT.search(p):
        add("QL12", WEIGHT.search(p).group(0), "writer", "error")
    bo = BOOST.findall(p)
    if bo:
        add("QL13", "、".join(sorted(set(bo))), "compiler")
    if re.search(r"(图\d+|<image\d+>)是[^。]{0,8}的脸部参考", p):
        fd = FACEDESC.findall(body)
        if fd:
            add("QL14", "、".join(sorted(set(fd))[:4]), "compiler")
    if AGE.search(body):
        add("QL15", "、".join(sorted(set(AGE.findall(body)))[:3]), "compiler")
    return out
