"""出图提示词按景别取舍造型部件（PROMPT 2026-10-31，knowledge K-REN-101）。

问题（方案 C 预览 S1 实测）：导演稿镜1 是“手部特写起手 → 上摇到侧脸近景”，出图提示词却把整套造型（12cm 透明细跟、漆皮短裙、
长腿）都拼了进去，Qwen-Image 2.1 出成了全身坐姿（data/pipeline/runs/ep02_claude_director_v1/preview/_wrong_framing/S1_1_fullbody.png）。
规则：出图提示词只写该景别下画面里看得见的造型部件；首句先写景别与构图。
- 特写 / 大特写 / 极近特写：只留头脸、手、上身领口一带；去掉下装、腿、鞋、脚
- 近景 / 中近景：去掉下装、腿、鞋、脚
- 中景：去掉鞋、脚（膝上构图）
- 中全景及更远：全套
只做格式取舍（删掉看不见的部件描述），不改写作方的 img 原文。
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

SIZES = ("极近特写", "大特写", "特写", "中近景", "近景", "中景", "中全景", "全身", "全景", "远景", "大远景")
LOWER = ("裙", "裤", "腿", "膝", "臀", "鞋", "高跟", "细跟", "鞋跟", "袜", "脚", "足弓", "赤足", "趾",
         "skirt", "miniskirt", "trouser", "pants", "leg", "heel", "stiletto", "shoe", "sneaker", "boot", "sock", "feet", "foot", "toe")
FEET = ("鞋", "高跟", "细跟", "鞋跟", "袜", "脚", "足弓", "赤足", "趾", "heel", "stiletto", "shoe", "sneaker", "boot", "sock", "feet", "foot", "toe")
HIDE = {"极近特写": LOWER, "大特写": LOWER, "特写": LOWER, "中近景": LOWER, "近景": LOWER, "中景": FEET}
LEAD = {"极近特写": "极近特写构图", "大特写": "大特写构图", "特写": "特写构图", "中近景": "中近景构图（胸部以上）",
        "近景": "近景构图（胸部以上）", "中景": "中景构图（膝盖以上）", "中全景": "中全景构图", "全身": "全身构图",
        "全景": "全景构图", "远景": "远景构图", "大远景": "大远景构图"}
CFG = Path(__file__).resolve().parents[3] / "config" / "recipes" / "image_framing.json"


REPO = Path(__file__).resolve().parents[3]


def _cfg() -> dict:
    try:
        return json.loads(CFG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _locked_image(root: Path, episode: int, index: int) -> bool:
    """该镜首帧已定稿（data/renders/epNN/SN/takes.json locked.image 有值）→ 不改它的出图提示词，免得触发重出"""
    p = Path(root) / "data" / "renders" / f"ep{episode:02d}" / f"S{index}" / "takes.json"
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return bool((d.get("locked") or {}).get("image")) if isinstance(d, dict) else False


def enabled(episode: int | None = None, index: int | None = None, root: str | Path | None = None,
            project: str | None = None) -> bool:
    """config/recipes/image_framing.json（总调度 2026-10-31 定）：
    default（新剧 / 新集默认开）→ per_project[<项目>]：off_episodes 整集关（ep02：方案 A/B 正用已定稿首帧跑片）；
    keep_locked_shots：已定稿首帧的镜保持旧提示词。项目键：默认项目（本仓库根）= "__default__"，其它 = 项目根目录名。
    旧格式 {"enabled": bool} 仍认。"""
    c = _cfg()
    if "default" not in c:
        return bool(c.get("enabled"))
    on = bool(c.get("default"))
    r = Path(root or os.environ.get("NS_PROJECT_ROOT") or REPO)
    key = project or ("__default__" if r.resolve() == REPO.resolve() else r.name)
    pc = (c.get("per_project") or {}).get(key) or {}
    if project:                                  # 显式项目键（流水线新剧）：没有本仓库的 renders，不查已定稿镜
        pc = {k: v for k, v in pc.items() if k != "keep_locked_shots"}
    if "default" in pc:
        on = bool(pc["default"])
    if episode is not None and episode in (pc.get("off_episodes") or []):
        return False
    if episode is not None and episode in (pc.get("on_episodes") or []):
        on = True
    if on and pc.get("keep_locked_shots") and episode is not None and index is not None and _locked_image(r, episode, index):
        return False
    return on


def size_of(text: str) -> str | None:
    """img 原文里第一个景别词（规则 §6A：紧跟触发词写，系统取第一个）"""
    best = None
    for s in SIZES:
        i = (text or "").find(s)
        if i >= 0 and (best is None or i < best[0] or (i == best[0] and len(s) > len(best[1]))):
            best = (i, s)
    return best[1] if best else None


def hidden_words(size: str | None) -> tuple[str, ...]:
    return HIDE.get(size or "", ())


def visible(fragment: str, size: str | None) -> bool:
    """这段造型 / 规格描述在该景别下看得见吗（含任一隐藏部件词 = 看不见）"""
    low = (fragment or "").lower()
    for w in hidden_words(size):
        if w.isascii():
            if re.search(rf"\b{w}s?\b", low):        # 英文按词边界（leg 不匹配 elegant）
                return False
        elif w in low:
            return False
    return True


def filter_parts(text: str, size: str | None, sep: str = "，") -> str:
    """按分隔符切开，去掉看不见的部件分句（用于角色锁 / 造型段这类并列描述）"""
    if not hidden_words(size):
        return text
    m = re.match(r"^(【[^】]*】)", text or "")          # “【林晚造型】超短裙，…”：标签头保留
    head = m.group(1) if m else ""
    body = (text or "")[len(head):]
    parts = [p for p in re.split(r"[，,、；;]", body) if p.strip()]
    keep = [p for p in parts if visible(p, size)]
    return head + sep.join(keep) if keep else ""


FOCUS_TRIGGERS = ("hh12", "ptxheel", "feet_", "foot_")   # 鞋 / 脚 LoRA 触发词：画面主体就是下半身
# 景别词后面紧跟的机位分句（“低机位”“平视”）不是画面主体，判主体时跳过（K-REN-123）
CAMERA = ("机位", "平视", "俯拍", "仰拍", "俯视", "仰视", "低角度", "高角度", "侧拍", "跟拍", "固定镜头", "手持", "过肩")
FACE_WORDS = ("脸", "眼", "唇", "嘴", "眉", "视线", "表情", "目光", "睫", "鼻", "下巴", "面部", "神情", "笑", "额")
PART_WORDS = ("手", "指", "甲", "腰", "腹", "锁骨", "肩", "背", "颈", "腿", "膝", "脚", "足", "鞋", "跟", "踝", "臀", "胸")
# 脸部特写里会把画面拉成全身 / 半身的分句（K-REN-123：特写常退成中景，原因之一是正文同时写了站姿 / 全身镜）
FULLBODY = ("全身", "站定", "站立", "站在", "站着", "侧身站", "跪坐", "跪在", "坐在", "坐着", "躺在", "走向", "走进", "迈步",
            "从头到脚", "整个人")
CLOSE = ("极近特写", "大特写", "特写")


def content_clauses(text: str) -> list[str]:
    """景别词之后的分句，去掉机位分句"""
    t = text or ""
    size = size_of(t)
    rest = t[t.find(size) + len(size):] if size else t
    return [p for p in re.split(r"[，,；;。]", rest) if p.strip() and not any(c in p for c in CAMERA)]


def lower_focus(img_raw: str, kept_triggers=None) -> bool:
    """img 原文（含触发词）以下半身为主体 → 不按景别删下半身部件（例：hh12clear 极近特写 = 鞋的特写）。
    判定：有鞋 / 脚触发词（kept_triggers 给出时，只认编译器真正保留的触发词——LoRA 不可用被剥掉的触发词不算证据，
    K-REN-123：写作方习惯性带 hh12clear，导致特写不删高跟 / 短裙，出图退成中景），或景别词后第一个非机位分句就写下半身部件"""
    t = img_raw or ""
    size = size_of(t)
    if size and closeup_subject(t, size) == "face":   # 特写正文写了脸 / 视线 → 脸部特写：鞋触发词也不改主体（REFLOCK 11-01：
        return False                                  # 以前触发词先判 True，资产规划与编译器对 ep02-S1 的主体判断不一致）
    trig = [k for k in FOCUS_TRIGGERS if k in t.lower()]
    if trig and (kept_triggers is None or any(k in str(x).lower() for x in kept_triggers for k in trig)):
        return True
    if not size:
        return False
    first = next(iter(content_clauses(t)), "")
    return not visible(first, size)


def closeup_subject(img_body: str, size: str | None) -> str | None:
    """特写类镜头的主体：face（写了脸 / 眼 / 视线…）、part（只写手 / 腰 / 鞋…等局部）、object（都没写）；非特写 → None"""
    if size not in CLOSE:
        return None
    t = (img_body or "").replace("眼睛为真实人眼大小", "")      # 写作方的通用质感句，不代表画面里有脸
    if any(w in t for w in FACE_WORDS):
        return "face"
    if any(w in t for w in PART_WORDS):
        return "part"
    return "object"


HAND_WORDS = ("手", "指", "甲", "腕")
NECK_WORDS = ("锁骨", "颈", "肩", "胸")


def part_name(img_body: str) -> str:
    """局部特写的局部名：正文里最先写到的局部词。
    W5（总调度 11-01，ep05-S3/S5 手部大特写 8 次出成带肩颈 / 脸的近景）：局部是手、而动作句同时写到肩 / 颈 / 锁骨 / 胸口
    （例：手套按在林晚肩头、记号笔点在胸口）→ 局部范围扩大为“手与肩颈”，构图句与之一致，不再写“只有手”和动作句打架"""
    t = img_body or ""
    hits = sorted(((t.find(w), w) for w in PART_WORDS if w in t))
    first = hits[0][1] if hits else "局部"
    if first in HAND_WORDS and any(w in t for w in NECK_WORDS):
        return "手与肩颈"
    return first


def strip_fullbody(text: str) -> str:
    """去掉写站姿 / 全身的分句（只用于脸部特写）"""
    parts = [p for p in re.split(r"[，,；;]", text or "") if p.strip()]
    keep = [p for p in parts if not any(w in p for w in FULLBODY)]
    return "，".join(keep)


def closeup_lead(size: str | None, subject: str | None, img_body: str = "") -> str:
    """K-REN-123：特写首句加构图约束（中英各一句，Qwen-Image 2.1 对英文构图词更敏感）"""
    if size not in CLOSE or not subject:
        return lead(size)
    if subject == "face":
        if size == "特写":
            return ("特写构图：只拍头部与肩颈，脸部占画面约六成，头顶到下巴完整入画，胸口以下不入画"
                    "（tight close-up portrait, the face fills about 60% of the frame）")
        return ("大特写构图：脸部充满画面，只见眉眼到下巴（extreme close-up, the face fills the whole frame）")
    part = part_name(img_body) if subject == "part" else "物件"
    # 肯定句写法（BAKEOFF R11-12 A3：cfg=1 下否定句不生效，“不出现脸”反而把“脸”写进了提示词）
    return (f"{size}构图：画面里只有{part}这一局部，{part}占画面大半，画框紧贴{part}裁切"
            f"（tight close-up crop on the {PART_EN.get(part, 'detail')} only, filling the frame）")


PART_EN = {"手与肩颈": "hands and the shoulder-collarbone area", "手": "hands", "脚": "feet", "鞋": "shoes", "腰": "waist", "腿": "legs", "胸": "chest", "肩": "shoulder",
           "锁骨": "collarbone", "物件": "object"}


# 局部特写：角色锁只留与局部相关的分句（REFLOCK 11-01）；纠正器里写脸的条目不加
PART_LOCK_WORDS = {"手": ("手", "指", "甲", "腕", "戒", "钻"), "脚": ("脚", "足", "趾", "鞋", "踝"), "鞋": ("脚", "足", "趾", "鞋", "踝", "跟"),
                   "腰": ("腰", "束腰"), "腿": ("腿",), "胸": ("胸",), "肩": ("肩",), "锁骨": ("锁骨",)}
FACE_TERM_RE = re.compile(r"面部|五官|脸")
HAIR_COLOR_RE = re.compile(r"发色|(?:蓝|冰蓝|黑|金|棕|栗|红|银|白|粉|紫|绿|灰|亚麻)[^，,；;]{0,3}发")


def part_lock(lock: str, part: str) -> str:
    """【名】描述 → 只留与 part 相关的分句；没有就返回空串（整条不放）"""
    m = re.match(r"(【[^】]+】)(.*)", lock or "", re.S)
    if not m:
        return ""
    part = part or ""
    if part == "手与肩颈":
        words = PART_LOCK_WORDS["手"] + PART_LOCK_WORDS["肩"] + PART_LOCK_WORDS["锁骨"] + PART_LOCK_WORDS["胸"]
    else:
        words = next((v for k, v in PART_LOCK_WORDS.items() if k in part), ("甲",))
    cl = [c for c in re.split(r"[，,；;]", m.group(2)) if c.strip()]
    keep = [c for c in cl if any(w in c for w in words)]
    # W5 b（总调度 11-01）：局部范围到了肩 / 颈 / 锁骨 / 胸（头发会入画）→ 保留发色句；
    # ep05-S3/S5 去掉发色句后林晚的发梢被画成黑色。纯手 / 脚局部头发不入画，不加（加了会把构图拉回人像）
    if any(w in part for w in NECK_WORDS + ("背",)):
        keep += [c for c in cl if HAIR_COLOR_RE.search(c) and c not in keep]
    adult = [c for c in cl if "成年" in c and c not in keep]   # 成年人锁定（HC-07）永远保留（局部里没有这个人的部件时也留年龄句）
    return (m.group(1) + "，".join(adult + keep)) if keep or adult else ""


def two_shot_clause(n_people: int, subject: str | None) -> str:
    """K-REV-122 / 总调度第二轮：双人镜第二个人常不出脸 → 写清两人朝向（局部特写不加）。
    SCRIPT-RSI 11-01（K-REN-703 / D-SCR-07，项目方 18:2x“所有图片不要看镜头”）：原句“各自至少四分之三侧脸朝向镜头（… toward the camera）”
    让两人都对镜头（VIDEO-RCA：首帧看镜头 → 片头看镜头 49/54）。改成正向视线落点；Qwen Image cfg 1 负面不生效，不写“不看镜头”。
    视线具体落在谁 / 什么上由剧本 img 写（QW-A7），这里只给朝向和“有落点”。
    ⤴ VIDEO-RCA 11-01 19:2x（总调度 r2 决定：按 G0 有实测证据的优先，“只写正向句”在此按证据例外）：换成实测句
    “互相看着对方……眼睛不看镜头”——同参考同 seed 2 个 seed，4 张脸看镜头 3 → 0（data/ab/video_rca/r1_img_gaze/faces.jpg，
    K-REN-703）。上面 SCRIPT-RSI 的正向句（TWO_SHOT_POSITIVE）还没实测；r2 做 3-seed A/B，若同样有效就改回正向句。
    ⤴ VIDEO-RCA r2（11-01 20:5x）A/B 完成（data/ab/video_rca/r5_img_twoshot/faces_01S5.jpg、faces_03S4.jpg，ep01-S5 / ep03-S4 × 3 seed，人工看脸）：
    旧句看镜头 8/10 张脸；正向句 0–1/10（1 张存疑）；实测句 0/12 → 两句同样有效，按总调度决定改回正向句（K-REN-703）。"""
    if n_people < 2 or subject in ("part", "object"):
        return ""
    return TWO_SHOT_POSITIVE


TWO_SHOT_TESTED = ("两人同框，两张脸都清晰入画，两人以侧脸到四分之三侧脸互相看着对方，目光落在对方脸上，眼睛不看镜头"
                   "（both faces visible in profile to three-quarter view, each looking at the other person, eyes off the lens）")
TWO_SHOT_POSITIVE = ("两人同框，两张脸都清晰入画，侧脸到四分之三侧脸，各自的视线落在画面里的人或物上"
                     "（both faces visible in profile to three-quarter view, each gaze resting on a person or object in the scene）")


def lead(size: str | None) -> str:
    return LEAD.get(size or "", "")
