"""
v3 剧本机检（G3 评审用，纯 CPU、只读、只用标准库）。

解析 《为他而骚 （剧本和镜头）v3.md》，逐镜/逐集报告规则失败，规则编号：
  * docs/audit/rule_ids.md 的 S1-W1–W8、H3-A/D/S（H3 部分直接调用 packages/schema/ns_schema/h3_lint.py）；
  * 项目方 v3 目标（rule_ids.md 里没有编号的）用本地前缀 V3-*，见下方 RULES。
  * 范围（协调 2026-10-30）：露骨/做爱镜头（pose_*、露骨词、`**H3校验**：暂缓（露骨内容）`、亲密声里有呻吟/高潮）
    一律只计“暂缓”，不检查、不输出其内容；做爱镜头数量与强度 3 指标不考核。

    python tools/v3_check.py V3.md --v2 V2.md [--changes v3_changes.md] [--json out.json] [--md out.md]

退出码：0 = 没有 block 级失败；1 = 有 block 级失败；2 = 解析失败。
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "schema"))
from ns_schema.h3_lint import frames_for_seconds, lint_h3  # noqa: E402

# ------------------------------------------------------------------ 本地规则（项目方 v3 目标）
RULES = {
    "V3-L1": ("block", "每个林晚镜头强度≥2（机器估计）"),
    "V3-T1": ("block", "集总时长 50–75 秒"),
    "V3-M1": ("block", "每集有 **配乐** 与 【BGM】"),
    "V3-M2": ("block", "每镜 sound 有 【配乐】 cue"),
    "V3-A2": ("block", "【亲密声】/【H3 audio】 只让林晚发声（男方无呼吸/呻吟/说话）"),
    "V3-N1": ("block", "img 不写否定词（CFG 1 会注入被否定的东西）"),
    "V3-N2": ("warn", "motion 不写否定词"),
    "V3-F1": ("block", "脚趾/赤脚只在真正赤脚的镜头写"),
    "V3-W1": ("block", "高跟一律 12cm 针形细跟（无粗跟/其它高度）"),
    "V3-W2": ("block", "漆皮一律镜面（无哑光/缎面）"),
    "V3-W3": ("block", "铁珠 = 5mm 不锈钢银色、每环一颗、左4右4中1"),
    "V3-W4": ("warn", "林晚日常穿搭 = 镜面漆皮超短裙（出现长裤/长裙等保守穿搭）"),
    "V3-C1": ("block", "饰品/纹身不早于剧情引入集（乳环 ep09、阴环 ep15、九环 ep19、铁珠 ep21、曼陀罗 ep26、黑蛇/沉字 ep27、背羽 ep28、舌钉 ep29）"),
    "V3-V1": ("block", "对白、🎙、剧情、负面追加与 v2 逐字一致"),
    "V3-V2": ("block", "v2 原 LoRA 触发词保留（img 前缀、motion lnwan01）"),
    "V3-V3": ("block", "v2 原 sound 原文保留（v3 只在后面追加）"),
    "V3-S2": ("block", "安全：无未成年/幼态字眼"),
    "S1-W7": ("block", "每镜有 **H3提示词**"),
}

EP_RE = re.compile(r"^##\s*ep(\d+)\s*《([^》]*)》")
SHOT_RE = re.compile(r"^\\?\*\\?\*镜(\d+)｜img((?:（[^）]*）)?)(?:\\?\*\\?\*)?：\s*(.*?)\s*$")
FIELD_RE = re.compile(r"^\\?\*\\?\*([^*：]+?)\\?\*\\?\*：\s*(.*)$")
DUR_RE = re.compile(r"^\\?\*\\?\*时长\\?\*\\?\*：\s*(\d+(?:\.\d+)?)\s*秒")
TRIG_RE = re.compile(r"^\s*([a-z][a-z0-9_]*(?:\s*[,，]\s*[a-z][a-z0-9_]*)*)\s*[，,]")
QUOTE_RE = re.compile(r"“([^”]*)”")

# writer 的露骨词表（rules.py 2026-10-30 收紧版），加上几个常见写法
EXPLICIT = re.compile(
    r"操我|被操|操她|操得|操进|口腔被|喉咙被|坐到底|被填满|三穴|白浊|阴茎|阴道|阴唇|阴蒂|阴部|阴阜|私处|性器|"
    r"插入|进入她|贯穿|抽插|交合|结合处|口交|含住他|吞吐|舔舐|舔弄|精液|射精|(?<![斜照反投折散放辐喷注])射(?:在|进|入|满)|"
    r"内射|骑乘|后入|体位|做爱|交欢|性高潮|高潮|乳头|赤裸|全裸|裸身|裸体|一丝不挂|肛|顶入|潮吹|爱液|勃起")
SENSUAL = ["漆皮", "超短裙", "G罩杯", "胸线", "乳沟", "臀", "大腿", "长腿", "足弓", "腰线", "腰肢", "锁骨", "曲线",
           "细汗", "汗珠", "潮红", "唇", "内衣", "丁字", "乳环", "阴环", "束腰", "捆绑", "蕾丝", "肌肤", "胸部", "乳房",
           "丝袜", "黑丝", "吊带", "颈线", "背部", "小腹", "腿部", "膝", "喘", "湿润", "光泽", "腰", "腿", "胸",
           "深处", "按到底", "呻吟", "颤栗", "裸"]
BODY_FOCUS = re.compile(r"(聚焦|焦点在?|特写|主体|占据画面)[^，。；]{0,20}(腰|臀|胸|乳|腿|足|脚踝|锁骨|颈|背|腹|曲线|身体|唇|皮肤|肌肤)")
POSE_HINT = {
    "pose_cowgirl": r"跨坐|女上|骑|坐在[^，。]{0,6}(腰|胯|腿|身上)",
    "pose_reverse_cowgirl": r"背对[^，。]{0,8}跨坐|反向",
    "pose_missionary": r"仰卧|仰躺|躺在[^，。]{0,4}身下|压在她|俯身[^，。]{0,6}(她|上方)",
    "pose_doggy": r"双手双膝|跪趴|趴跪|后入|身后|臀部[^，。]{0,4}(抬|翘)",
    "pose_prone": r"平趴|俯卧|趴在",
    "pose_spoon": r"侧卧|侧躺",
    "pose_standing": r"站立|站着|弯腰|俯身[^，。]{0,4}(桌|台)",
    "pose_wall": r"墙",
    "pose_oral": r"跪|口|含",
    "pose_cunnilingus": r"两腿之间|双腿间|舔",
    "pose_edge_of_bed": r"床沿|床边",
    "pose_lotus": r"盘腿|怀里|坐在[^，。]{0,4}怀",
    "pose_group": r"环绕|围|三人|多人",
}
TOES = re.compile(r"脚趾|趾甲|足趾|趾尖|裸足|赤脚|赤足|光脚")
BAREFOOT_CTX = re.compile(r"赤脚|赤足|光脚|裸足|脱下[^，。]{0,6}(鞋|高跟)|踢掉[^，。]{0,6}(鞋|高跟)|淋浴|浴缸|浴室")
WEARING_HEELS = re.compile(r"(穿着|踩着|脚上)[^，。；]{0,12}(高跟|细跟|鞋)|(高跟|细跟)[^，。；]{0,6}(穿在|踩)")
NEG_IMG = re.compile(r"没有|毫无|并非|并无|未(?!来)|无(?!比|数|限|意识|名|缝|尽|疑|论|辜)|"
                     r"不(?!锈|断|停|由|自觉|经意|住|禁|同|少|时|久|远)|非(?!常)|别(?!墅|针|致|处)|勿")
NEG_WHITELIST = ["不安", "不已", "不舍", "不锈钢", "忍不住", "禁不住", "情不自禁", "目不转睛", "迫不及待", "一丝不挂", "不可抑制", "无法抑制"]
HEEL_HEIGHT = re.compile(r"(\d+(?:\.\d+)?)\s*(?:cm|厘米|公分)[^，。；]{0,10}(?:高跟|细跟|鞋跟|跟)")
BAD_HEEL = re.compile(r"粗跟|坡跟|平底|运动鞋|帆布鞋|方跟|猫跟|中跟")
MATTE = re.compile(r"哑光|缎面|磨砂漆皮")
BEADS = re.compile(r"铁珠|铁球|钢珠|小球|珠串|小钢球")
BEAD_BLACK = re.compile(r"黑色?[^，。；、]{0,8}(铁珠|铁球|钢珠|小球|珠)|(铁珠|铁球|钢珠|小球)[^，。；、]{0,6}黑")
BEAD_SIZE = re.compile(r"(\d+(?:\.\d+)?|[一二三四五六七八九十两]+)\s*(厘米|cm|公分)[^，。；]{0,8}(珠|球)")
BEAD_MULTI = re.compile(r"每(?:枚|个|串|只)[^，。；]{0,6}(?:两|三|四|五|多|[2-9])颗|串着[^，。]{0,4}(?:两|三|多|[2-9])颗|"
                        r"左5|左五|左右各[5五]|十颗|10颗|一串串")
CONSERVATIVE = re.compile(r"长裤|西裤|牛仔裤|阔腿裤|长裙|及膝|过膝裙|运动服")
SLEEP = re.compile(r"熟睡|睡着|沉睡|醉倒|醉酒|昏睡|睡熟|已睡|入睡|而眠|鼾|失去知觉|不省人事|喝醉|昏迷")
MINOR = re.compile(r"未成年|少女感|幼态|稚嫩|学生|校服|萝莉|娃娃脸|童颜")
FORCE = re.compile(r"强迫|强行|挣扎|反抗|哭喊|求饶|下药|迷药|胁迫|殴打|掐住脖|窒息")
MALE_VOCAL = re.compile(r"（S[2-9][^）]*）[^（；。]*?(呼吸|喘|呻吟|闷哼|低吼|叹息|笑|说|耳语|低语|吼|哼|嗓|喉)")
MALE_EN = re.compile(r"\b(man|men|male|his|he|him|boyfriend|husband|partner's)\b", re.I)
INTRO = [("乳环", 9, r"乳环"), ("阴环", 15, r"阴环|阴唇环"), ("九枚阴环", 19, r"九枚阴环|九环|九枚环|lbrng9(?!_)"),
         ("铁珠", 21, r"铁珠|铁球|钢珠|小钢球|lbrng9_beads"), ("曼陀罗纹身", 26, r"曼陀罗"),
         ("黑蛇纹身", 27, r"黑蛇|蛇形纹身|蛇纹身"), ("“沉”字纹身", 27, r"[“\"「]沉[”\"」]字|沉字纹身"),
         ("背羽纹身", 28, r"背羽|黑羽纹身|羽毛纹身"), ("舌钉", 29, r"舌钉")]
CAMERA_OK = re.compile(r"static|push in|pull out|zoom|tilt|pan|truck|pedestal|arc|tracking|follow|dolly|crane|固定|推|拉|摇|跟|环绕|升|降", re.I)
CUT = re.compile(r"切到|切至|切换到|转场|剪辑|硬切|\bcut to\b|闪回|叠化", re.I)
DEFER_EXTRA = re.compile(r"坐进|坐到极限|填满|占满|润滑|扩张|最深处|贯穿|舔|乳交|口技|身下|胯间|两腿之间|三向|五声位|白线|潮喷|自慰|指尖探入|含住|吞下|吞咽他")
SPEAKER_LW = re.compile(r"她|林晚|对镜|自言自语")


def clean(t: str) -> str:
    return re.sub(r"\\(?=[*`])", "", t or "").strip().strip("`").strip()


def neg_hits(text: str) -> list[str]:
    t = text
    for w in NEG_WHITELIST:
        t = t.replace(w, "")
    out = []
    for m in NEG_IMG.finditer(t):
        out.append(t[max(0, m.start() - 4):m.end() + 4])
    return out


# ------------------------------------------------------------------ 解析
def parse(path: Path) -> dict:
    lines = path.read_text(encoding="utf-8").replace("\r\n", "\n").split("\n")
    eps: dict[int, dict] = {}
    cur = None
    shot = None
    i = 0
    while i < len(lines):
        ln = lines[i]
        m = EP_RE.match(ln)
        if m:
            cur = {"ep": int(m.group(1)), "title": m.group(2), "line": i + 1, "fields": {}, "shots": []}
            eps[cur["ep"]] = cur
            shot = None
            i += 1
            continue
        if cur is None:
            i += 1
            continue
        if ln.startswith("# ") or ln.startswith("## 📋") or ln.startswith("## 规格"):
            cur, shot = None, None
            i += 1
            continue
        m = SHOT_RE.match(ln)
        if m:
            shot = {"n": int(m.group(1)), "label": m.group(2), "img": clean(m.group(3)), "line": i + 1, "fields": {},
                    "dialogue_lines": [], "mono_lines": [], "h3": None, "inserted": "v3新增" in m.group(2)}
            cur["shots"].append(shot)
            i += 1
            continue
        if re.match(r"^\\?\*\\?\*H3提示词\\?\*\\?\*", ln):
            j = i + 1
            while j < len(lines) and not lines[j].startswith("```"):
                j += 1
            k = j + 1
            while k < len(lines) and not lines[k].startswith("```"):
                k += 1
            if shot is not None:
                shot["h3"] = "\n".join(lines[j + 1:k]).strip("\n")
            i = k + 1
            continue
        m = DUR_RE.match(ln)
        if m and shot is not None:
            shot["dur"] = float(m.group(1))
            i += 1
            continue
        m = FIELD_RE.match(ln)
        if m:
            name, val = m.group(1).strip(), m.group(2).strip()
            val_clean = val.strip("`")
            if shot is None:
                cur["fields"].setdefault(name, val_clean)
                if name == "剧情" or name == "负面追加":
                    cur["fields"][name] = val
            else:
                if name.startswith("对白") or name.startswith("口型"):
                    shot["dialogue_lines"].append((name, val))
                elif name.startswith("🎙"):
                    shot["mono_lines"].append((name, val))
                elif name == "负面追加":
                    cur["fields"]["负面追加"] = val
                else:
                    shot["fields"].setdefault(name, val_clean)
        i += 1
    return eps


def triggers(img: str) -> list[str]:
    m = TRIG_RE.match(img or "")
    return [t.strip() for t in re.split(r"[,，]", m.group(1))] if m else []


def dialogue_of(shot: dict) -> tuple[list[str], list[str], list[str]]:
    """(全部台词, 林晚台词, 画外台词)；屏幕文字/口型不算口头台词"""
    allq, lw, off = [], [], []
    for name, val in shot["dialogue_lines"]:
        if "屏幕" in name or name.startswith("口型") or "心里" in name or "无台词" in name:
            continue
        label_off = "画外" in name
        pos, spk = 0, ""
        for q in QUOTE_RE.finditer(val):
            lead = val[pos:q.start()]
            sp = re.findall(r"（([^）]*)）", lead)
            if sp:
                spk = sp[-1]
            if "屏幕" in lead:
                pos = q.end()
                continue
            text = q.group(1)
            allq.append(text)
            if SPEAKER_LW.search(spk or "她"):
                lw.append(text)
            if label_off or re.search(r"画外|电话|语音|门外", spk):
                off.append(text)
            pos = q.end()
    return allq, lw, off


def monologue_of(shot: dict) -> list[str]:
    return [re.sub(r"^\*|\*$", "", v.strip()) for _, v in shot["mono_lines"]]


def shot_text(shot: dict) -> tuple[str, str, str]:
    return shot["img"], shot["fields"].get("motion", ""), shot["fields"].get("sound", "")


def estimate(shot: dict) -> dict:
    img, mot, snd = shot_text(shot)
    trig = triggers(img)
    poses = [t for t in trig if t.startswith("pose_")]
    both = img + mot
    lw = "lnwan01" in mot or "林晚" in both or "蓝发" in both
    explicit = bool(EXPLICIT.search(both))
    sens = {w for w in SENSUAL if w in both}
    level = 3 if explicit else (2 if len(sens) >= 3 else 1)
    body = level >= 2 and bool(BODY_FOCUS.search(img))
    # 范围（协调 2026-10-30）：露骨/做爱镜头只计“暂缓”，不检查、不引用。判定从宽：拿不准就暂缓。
    deferred = (bool(poses) or explicit or bool(DEFER_EXTRA.search(both))
                or bool(re.search(r"呻吟|叫床|高潮", snd)) or "暂缓" in shot["fields"].get("H3校验", ""))
    return {"lw": lw, "explicit": explicit, "level": level, "body": body, "poses": poses, "sex": bool(poses),
            "intimate": bool(poses) or explicit, "deferred": deferred, "sensual_terms": sorted(sens)}


# ------------------------------------------------------------------ 检查
def fail(out, ep, shot, rid, detail, level=None, sop_ref=None):
    lvl = level or RULES.get(rid, ("block",))[0]
    out.append({"ep": ep, "shot": shot, "rule_id": rid, "level": lvl, "detail": detail,
                "sop_ref": sop_ref or ("§6 #7；§9A.1" if rid.startswith("H3-") else ("§6" if rid.startswith("S1-") else "项目方 v3 目标"))})


def check(v3: dict, v2: dict | None, classes: dict[int, str]) -> tuple[list[dict], list[dict]]:
    fails: list[dict] = []
    v2_text = {k: " ".join(s["img"] + s["fields"].get("motion", "") for s in e["shots"]) + e["title"]
               for k, e in (v2 or {}).items()}
    table: list[dict] = []
    for epn in sorted(v3):
        e = v3[epn]
        shots = e["shots"]
        ests = [estimate(s) for s in shots]
        ef = e["fields"]
        # V3-M1 每集配乐/BGM
        sc = ef.get("配乐", "")
        if not sc or "【BGM】" not in sc:
            fail(fails, epn, None, "V3-M1", "本集缺 **配乐** 或 【BGM】")
        # 时长
        total = 0.0
        for s, est in zip(shots, ests):
            sid = f"镜{s['n']}"
            img, mot, snd = shot_text(s)
            d = s.get("dur")
            s["deferred"] = est["deferred"]
            if est["deferred"]:          # 暂缓：只计数、计时长，不检查不引用
                total += d or 0
                continue
            if d is None:
                fail(fails, epn, sid, "S1-W2", "缺 **时长**")
            else:
                total += d
                if not 5 <= d <= 15:
                    fail(fails, epn, sid, "S1-W2", f"时长 {d:g} 秒，不在 5–15 秒")
            # S1-W1 一个连续镜头 + 结束状态
            if CUT.search(mot):
                fail(fails, epn, sid, "S1-W1", f"motion 有剪辑/转场词：{CUT.search(mot).group(0)}")
            if "定格" not in mot and "——" not in mot:
                fail(fails, epn, sid, "S1-W1", "motion 没有结束状态（“——”或“定格：”）")
            # S1-W6 运镜可映射
            head = re.sub(r"^lnwan01[，,]\s*", "", mot)[:40]
            if not CAMERA_OK.search(head):
                fail(fails, epn, sid, "S1-W6", f"motion 开头找不到运镜词：{head[:20]}", level="warn")
            # S1-W3 【H3 audio】
            ha = re.search(r"【H3 audio】\s*(.*?)(?:；【|$)", snd)
            ins = re.search(r"【亲密声】\s*(.*?)(?:；【|$)", snd)
            if ha:
                t = ha.group(1)
                if re.search(r"[一-鿿]", t):
                    fail(fails, epn, sid, "S1-W3", "【H3 audio】 含中文")
                if re.search(r"\b(no|not|never|without|none|nothing)\b|n't\b", t, re.I):
                    fail(fails, epn, sid, "S1-W3", "【H3 audio】 有否定句")
                ns = len([x for x in re.split(r"(?<=[.!?])\s+", t.strip()) if x.strip()])
                if not 1 <= ns <= 4:
                    fail(fails, epn, sid, "S1-W3", f"【H3 audio】 {ns} 句（应 1–4）")
            # S1-W4 img/motion 不用双引号
            qs = re.findall(r"[“\"]([^”\"]{1,40})[”\"]", img + mot)
            if qs:
                said = dialogue_of(s)[0]
                if any(q in x or x in q for q in qs for x in said if x):
                    fail(fails, epn, sid, "S1-W4", f"台词被双引号写进 img/motion：“{qs[0]}”")
                else:
                    fail(fails, epn, sid, "S1-W4", f"img/motion 有引号文字（屏幕字/纹身字，烧字风险）：“{qs[0]}”", level="warn")
            # V3-M2 每镜配乐 cue
            if "【配乐】" not in snd:
                fail(fails, epn, sid, "V3-M2", "sound 缺 【配乐】")
            # V3-A2 声音层只让林晚发声（亲密镜已暂缓；这里查非露骨镜头里写了 【亲密声】 的情况）
            if ins and MALE_VOCAL.search(ins.group(1)):
                m = MALE_VOCAL.search(ins.group(1))
                fail(fails, epn, sid, "V3-A2", f"【亲密声】 写了男方发声：{m.group(0)[:40]}")
            if ha and MALE_EN.search(ha.group(1)):
                fail(fails, epn, sid, "V3-A2", f"【H3 audio】 写了男方：{MALE_EN.search(ha.group(1)).group(0)}")
            # V3-N1/N2 否定
            h = neg_hits(img)
            if h:
                fail(fails, epn, sid, "V3-N1", "img 否定词：" + "｜".join(h[:4]))
            h = neg_hits(mot)
            if h:
                fail(fails, epn, sid, "V3-N2", "motion 否定词：" + "｜".join(h[:4]))
            # V3-F1 脚趾
            if TOES.search(img) and not BAREFOOT_CTX.search(img):
                fail(fails, epn, sid, "V3-F1", f"img 写了“{TOES.search(img).group(0)}”但本镜不是赤脚"
                     + ("（穿着高跟）" if WEARING_HEELS.search(img) else ""))
            # 服装
            for hm in HEEL_HEIGHT.finditer(img + mot):
                if float(hm.group(1)) != 12:
                    fail(fails, epn, sid, "V3-W1", f"鞋跟高度 {hm.group(0)}")
            if BAD_HEEL.search(img):
                fail(fails, epn, sid, "V3-W1", f"非针形细跟：{BAD_HEEL.search(img).group(0)}")
            if MATTE.search(img):
                fail(fails, epn, sid, "V3-W2", f"漆皮质感：{MATTE.search(img).group(0)}")
            both = img + mot
            for rx in (BEAD_BLACK, BEAD_SIZE, BEAD_MULTI):
                mm = rx.search(both)
                if mm and not (rx is BEAD_SIZE and re.match(r"5|五", mm.group(1)) and mm.group(2) in ("毫米", "mm")):
                    fail(fails, epn, sid, "V3-W3", f"铁珠：{both[max(0, mm.start() - 6):mm.end() + 4]}")
            if est["lw"] and CONSERVATIVE.search(img):
                fail(fails, epn, sid, "V3-W4", f"保守穿搭：{CONSERVATIVE.search(img).group(0)}")
            # V3-C1 连续性
            for name, start, rx in INTRO:
                if epn < start and re.search(rx, both + " ".join(triggers(img))) \
                        and not re.search(rx, (v2_text or {}).get(epn, "")):
                    if name == "铁珠" and epn == 20:
                        continue  # ep20 上珠前夜：道具可以出现
                    fail(fails, epn, sid, "V3-C1", f"{name} 出现在 ep{epn:02d}（剧情 ep{start:02d} 才有）")
            # 安全（非露骨镜头）
            if MINOR.search(both):
                fail(fails, epn, sid, "V3-S2", f"出现“{MINOR.search(both).group(0)}”")
            # 强度（非露骨镜头：林晚镜≥2）
            if est["lw"] and est["level"] < 2:
                fail(fails, epn, sid, "V3-L1", f"估计强度 1（性感词 {len(est['sensual_terms'])} 个）")
            # H3
            if not s.get("h3"):
                fail(fails, epn, sid, "S1-W7", "缺 **H3提示词**")
                s["h3_ok"] = False
            else:
                allq, lwq, off = dialogue_of(s)
                frames = frames_for_seconds(d) if d else None
                res = lint_h3(s["h3"], frames=frames, intimate=False, seconds=d,
                              dialogue=None, offscreen=[x for x in off if x in allq],
                              monologue=monologue_of(s))
                # H3-D3：亲密镜只核林晚的台词（男方台词后期 TTS），其余镜核全部
                spoken = [re.sub(r"^\[[^\]]*\]\s?", "", b) for b in re.findall(r"<d>(.*?)</d>", s["h3"], re.S)]
                want = allq
                if spoken != want:
                    extra = [x for x in spoken if x not in allq]
                    det = (f"剧本 {len(want)} 句、提示词 {len(spoken)} 句"
                           + (f"；不在剧本里的台词：「{extra[0][:20]}」" if extra else "")
                           + (f"；剧本「{next((a for a, b in zip(want, spoken) if a != b), want[len(spoken)] if len(want) > len(spoken) else '')[:20]}」" if want else ""))
                    res.append({"rule_id": "H3-D3", "ok": False, "level": "block", "detail": det})
                # 人名进英文正文
                if re.search(r"\b(Lin Wan|Gu Chen|Chen Yu|Linwan)\b", s["h3"]):
                    res.append({"rule_id": "H3-D4", "ok": False, "level": "block", "detail": "提示词里写了人名"})
                ok = True
                for r in res:
                    if not r["ok"]:
                        fail(fails, epn, sid, r["rule_id"], r["detail"], level=r.get("level", "block"))
                        if r.get("level", "block") == "block":
                            ok = False
                s["h3_ok"] = ok
        # 集级（协调 2026-10-30：做爱镜头数量、强度 3 指标不再考核）
        live = [x for x in ests if not x["deferred"]]
        lw_shots = [x for x in live if x["lw"]]
        cls = classes.get(epn, "")
        if not 60 <= total <= 120:   # D-SCR-08（项目方 11-01 21:4x）
            fail(fails, epn, None, "V3-T1", f"总时长 {total:g} 秒")
        ep_fail = [f for f in fails if f["ep"] == epn and f["level"] == "block"]
        table.append({
            "ep": epn, "title": e["title"], "class": cls, "shots": len(shots),
            "inserted": sum(1 for s in shots if s["inserted"]),
            "deferred": sum(1 for x in ests if x["deferred"]),
            "body": sum(1 for x in live if x["body"]),
            "avg_level": round(sum(x["level"] for x in live) / len(live), 2) if live else 0,
            "lw_below2": sum(1 for x in lw_shots if x["level"] < 2),
            "duration": total, "h3_pass": sum(1 for s in shots if s.get("h3_ok") and not s.get("deferred")),
            "h3_present": sum(1 for s in shots if s.get("h3") and not s.get("deferred")),
            "checked": sum(1 for s in shots if not s.get("deferred")),
            "block_fails": len(ep_fail),
            "fail_ids": dict(collections.Counter(f["rule_id"] for f in ep_fail)),
        })
    if v2:
        verbatim(v2, v3, fails)
        for row in table:
            row["block_fails"] = sum(1 for f in fails if f["ep"] == row["ep"] and f["level"] == "block")
            row["fail_ids"] = dict(collections.Counter(f["rule_id"] for f in fails if f["ep"] == row["ep"] and f["level"] == "block"))
    return fails, table


def verbatim(v2: dict, v3: dict, fails: list[dict]) -> None:
    for epn in sorted(v2):
        if epn not in v3:
            fail(fails, epn, None, "V3-V1", "v3 缺这一集")
            continue
        a, b = v2[epn], v3[epn]
        for k in ("剧情", "负面追加"):
            if a["fields"].get(k, "").strip() != b["fields"].get(k, "").strip():
                fail(fails, epn, None, "V3-V1", f"{k} 与 v2 不同")
        orig = [s for s in b["shots"] if not s["inserted"]]
        if len(orig) != len(a["shots"]):
            fail(fails, epn, None, "V3-V1", f"v2 {len(a['shots'])} 镜、v3 原镜 {len(orig)} 镜")
        for s2, s3 in zip(a["shots"], orig):
            if s3.get("deferred"):
                continue
            sid = f"镜{s3['n']}(v2镜{s2['n']})"
            if s2["dialogue_lines"] != s3["dialogue_lines"]:
                fail(fails, epn, sid, "V3-V1", "对白与 v2 不同")
            if s2["mono_lines"] != s3["mono_lines"]:
                fail(fails, epn, sid, "V3-V1", "🎙 与 v2 不同")
            t2, t3 = triggers(s2["img"]), triggers(s3["img"])
            miss = [t for t in t2 if t not in t3]
            if miss:
                fail(fails, epn, sid, "V3-V2", f"丢了触发词 {miss}")
            if "lnwan01" in s2["fields"].get("motion", "")[:12] and "lnwan01" not in s3["fields"].get("motion", "")[:12]:
                fail(fails, epn, sid, "V3-V2", "motion 丢了 lnwan01")
            snd2 = s2["fields"].get("sound", "")
            snd3 = s3["fields"].get("sound", "")
            n2, n3 = clean(snd2).strip("`"), clean(snd3)
            if n2 and n2.rstrip("`\\") not in n3:
                fail(fails, epn, sid, "V3-V3", "sound 原文被改")
        for s3 in b["shots"]:
            if s3["inserted"] and not s3.get("deferred") and (s3["dialogue_lines"] or s3["mono_lines"]):
                fail(fails, epn, f"镜{s3['n']}", "V3-V1", "新增镜带了对白/独白")


def read_classes(path: Path | None) -> dict[int, str]:
    out = {}
    if path and path.exists():
        for ln in path.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^\|\s*ep(\d+)《[^》]*》\s*\|\s*([^|]*?)\s*\|", ln)
            if m:
                out[int(m.group(1))] = m.group(2)
    return out


def render_md(table, fails) -> str:
    out = ["| 集 | 类别 | 镜数(新增) | 暂缓 | 已检 | 身体镜 | 平均L(已检) | 林晚镜<L2 | 时长 | H3通过/已检 | block失败 | 主要失败 |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in table:
        top = "、".join(f"{k}×{v}" for k, v in sorted(r["fail_ids"].items(), key=lambda x: -x[1])[:4])
        out.append(f"| ep{r['ep']:02d} | {r['class']} | {r['shots']}({r['inserted']}) | {r['deferred']} | {r['checked']} | "
                   f"{r['body']} | {r['avg_level']} | {r['lw_below2']} | {r['duration']:g} | "
                   f"{r['h3_pass']}/{r['checked']} | {r['block_fails']} | {top} |")
    c = collections.Counter((f["rule_id"], f["level"]) for f in fails)
    out += ["", "| rule_id | 级别 | 次数 | 说明 |", "|---|---|---|---|"]
    for (rid, lvl), n in sorted(c.items(), key=lambda x: -x[1]):
        out.append(f"| {rid} | {lvl} | {n} | {RULES.get(rid, ('', ''))[1]} |")
    return "\n".join(out)


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("v3")
    ap.add_argument("--v2")
    ap.add_argument("--changes", help="v3_changes.md（取写入者标的集类别）")
    ap.add_argument("--json")
    ap.add_argument("--md")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    try:
        v3 = parse(Path(a.v3))
        v2 = parse(Path(a.v2)) if a.v2 else None
    except (OSError, ValueError) as ex:
        print(f"解析失败：{ex}")
        return 2
    if not v3:
        print("解析失败：没有找到任何 ## epNN《…》")
        return 2
    fails, table = check(v3, v2, read_classes(Path(a.changes)) if a.changes else {})
    if a.json:
        Path(a.json).write_text(json.dumps({"table": table, "failures": fails}, ensure_ascii=False, indent=1), encoding="utf-8")
    md = render_md(table, fails)
    if a.md:
        Path(a.md).write_text(md, encoding="utf-8")
    if not a.quiet:
        for f in fails:
            print(f"[{f['level']}] ep{f['ep']:02d} {f['shot'] or '—'} {f['rule_id']}: {f['detail']}")
    print(md)
    nb = sum(1 for f in fails if f["level"] == "block")
    print(f"\n合计：{len(table)} 集、{sum(r['shots'] for r in table)} 镜（暂缓 {sum(r['deferred'] for r in table)}）；block 失败 {nb}，warn {len(fails) - nb}")
    return 1 if nb else 0


if __name__ == "__main__":
    sys.exit(main())
