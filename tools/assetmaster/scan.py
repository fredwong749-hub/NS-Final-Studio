"""ASSETMASTER 资产盘点（2026-11-01，GEN_CONTRACT I3/I4 的上游）。

剧本（data/import/script_v2.json 的逐镜 img 原文 + 每集造型表头）× P1 造型登记（<run>/P1_looks.json）× 资产库
（data/looks/wardrobe.json 单品 + data/assets/asset_refs.json 造型设定图）→ "角色 × 造型 × 单品" 清单：
  有图 / 缺图 / 图不合格 / 待确认（库里有近似品但规格不同），以及每件出现在哪些镜。
同时列出剧本内的矛盾：同造型不同鞋、镜头里出现未登记单品、集表头偏离 P1 登记。

只读剧本与资产库，不改任何东西；输出：
  data/assetmaster/inventory.json   机器可读（autopilot P4-P5 读 todo 段）
  docs/assetmaster/inventory.md     人读
  data/assetmaster/todo.json        缺图 / 不合格 / 待确认 → 待补队列（补全脚本读）

用法：.venv/Scripts/python.exe tools/assetmaster/scan.py [--run data/pipeline/runs/series10_v1] [--script ...] [--no-qc]
可复用：新剧本导入后 autopilot P4-P5 自动调用 scan(run_dir)；库映射的人工覆盖写 data/assetmaster/lib_map.json。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "agent"))
try:
    from ns_agent import framing as FR          # K-REN-101 景别可见性
except Exception:                                # pragma: no cover
    FR = None

OUT_JSON = ROOT / "data" / "assetmaster" / "inventory.json"
OUT_TODO = ROOT / "data" / "assetmaster" / "todo.json"
OUT_MD = ROOT / "docs" / "assetmaster" / "inventory.md"
LIB_MAP = ROOT / "data" / "assetmaster" / "lib_map.json"
EXTRAS = {k: v for k, v in (json.loads((ROOT / "data" / "assetmaster" / "look_extras.json").read_text(encoding="utf-8"))
                            if (ROOT / "data" / "assetmaster" / "look_extras.json").exists() else {}).items() if not k.startswith("_")}

# ---------------------------------------------------------------- 词表：名词核心 → (类, 槽位)。长词在前。
NOUNS: list[tuple[str, str, str]] = [
    # 鞋
    ("侧开透明细高跟", "heels", "shoes"), ("透明细高跟", "heels", "shoes"), ("细高跟", "heels", "shoes"),
    ("高跟凉鞋", "heels", "shoes"), ("高跟鞋", "heels", "shoes"), ("细跟", "heels", "shoes"), ("高跟", "heels", "shoes"),
    ("马丁靴", "boots", "shoes"), ("短靴", "boots", "shoes"), ("球鞋", "sneakers", "shoes"), ("运动鞋", "sneakers", "shoes"),
    ("帆布鞋", "canvas", "shoes"), ("平底鞋", "flats", "shoes"), ("拖鞋", "slippers", "shoes"), ("皮鞋", "leather_shoes", "shoes"),
    # 袜
    ("丝袜", "stockings", "legwear"), ("袜", "socks", "legwear"),
    # 服装
    ("西装外套", "blazer", "outfit"), ("西装裙", "skirt_suit", "outfit"), ("铅笔裙", "skirt_suit", "outfit"),
    ("超短裙", "skirt_mini", "outfit"), ("短裙", "skirt_mini", "outfit"), ("长裙", "dress_long", "outfit"),
    ("连衣裙", "dress", "outfit"), ("睡裙", "nightdress", "outfit"), ("长风衣", "trench", "outfit"), ("风衣", "trench", "outfit"),
    ("束腰", "corset", "outfit"), ("捆绑内衣", "harness", "outfit"), ("丁字裤", "thong", "outfit"), ("内衣", "lingerie", "outfit"),
    ("高领毛衣", "turtleneck", "outfit"), ("毛衣", "sweater", "outfit"), ("针织衫", "knit_top", "outfit"),
    ("衬衫", "shirt", "outfit"), ("卫衣", "hoodie", "outfit"), ("T恤", "tee", "outfit"), ("长袖", "longsleeve", "outfit"),
    ("背心", "tank", "outfit"), ("吊带", "camisole", "outfit"), ("工装", "overalls", "outfit"), ("围裙", "apron", "outfit"),
    ("浴袍", "robe", "outfit"), ("睡袍", "robe", "outfit"), ("浴巾", "towel", "outfit"),
    ("西裤", "trousers", "outfit"), ("牛仔裤", "jeans", "outfit"), ("卡其裤", "chinos", "outfit"), ("运动裤", "sweatpants", "outfit"),
    ("阔腿裤", "wide_trousers", "outfit"), ("外套", "jacket", "outfit"), ("西装", "suit", "outfit"),
    # 饰品 / 首饰
    ("红绳手链", "red_string", "jewelry"), ("红绳", "red_string", "jewelry"), ("手链", "bracelet", "jewelry"),
    ("细银链", "necklace", "jewelry"), ("项链", "necklace", "jewelry"), ("银戒", "ring", "jewelry"), ("戒指", "ring", "jewelry"),
    ("铁珠", "beads", "jewelry"), ("钢珠", "beads", "jewelry"), ("腹链", "belly_chain", "jewelry"),
    ("耳环", "earring", "jewelry"), ("耳钉", "earring", "jewelry"), ("手套", "gloves", "accessory"),
    ("手包", "bag", "accessory"), ("发夹", "hairclip", "accessory"), ("发圈", "hairtie", "accessory"),
    # 穿孔 / 身体
    ("乳环", "nipple_ring", "piercing"), ("阴环", "labia_ring", "piercing"), ("舌钉", "tongue_stud", "piercing"),
    ("细金属环", "metal_ring_piercing", "piercing"), ("金属环", "metal_ring_piercing", "piercing"),
    ("纹身", "tattoo", "body_mark"), ("浅疤", "scar", "body_mark"),
    # 甲
    ("水晶甲", "nails_hand", "nails"), ("脚趾甲", "nails_toe", "nails"), ("短甲", "nails_short", "nails"),
    # 妆
    ("眼影", "eyeshadow", "makeup"), ("美瞳", "lens", "makeup"), ("修容", "contour", "makeup"), ("闪片", "glitter", "makeup"),
    ("腮红", "blush", "makeup"), ("莓果色唇", "lip", "makeup"),
]
NOUNS.sort(key=lambda t: -len(t[0]))
NOUN_RE = re.compile("|".join(re.escape(n) for n, _, _ in NOUNS))
NOUN_CLS = {n: (c, s) for n, c, s in NOUNS}
# 同类（同造型里视为同一件）
CLS_GROUP = {"skirt_suit": "skirt", "skirt_mini": "skirt", "dress_long": "dress", "dress": "dress",
             "turtleneck": "top_knit", "sweater": "top_knit", "knit_top": "top_knit", "suit": "suit", "blazer": "suit",
             "jacket": "suit", "red_string": "bracelet", "bracelet": "bracelet"}
ATTR = ["米白", "深灰", "浅灰", "雾蓝", "深蓝", "军绿", "卡其", "米色", "棕色", "黑色", "白色", "红色", "银色",
        "黑", "白", "灰", "红", "银", "棕", "透明", "漆皮", "针织", "真丝", "皮", "侧开", "12cm", "12厘米", "细带", "凉鞋",
        "短款", "长款", "旧", "钻石", "镶钻", "超长", "5厘米"]
DELIM = re.compile(r"[，,、；;。|｜（）()：:\n]|配|与|和|及|外罩|搭|穿|踩|戴|着|披|勒|压|握|捧|拎|捏|系|挂|垂|露出|以及|在")
POS_WORDS = ("左手无名指", "右手无名指", "左手", "右手", "手腕", "左腕", "右腕", "颈间", "锁骨", "腰侧", "腿侧", "手上",
             "脚踩", "脚上", "肩上", "一条", "一双", "一枚", "一根", "一件", "1条", "1件", "2件", "3件", "九串", "第七枚", "第八枚", "第九枚")
SHAPE_HINT = ("袖口卷起", "袖口卷到手肘", "解开到腰", "下摆垂在胯侧", "柔软贴身", "露出长腿")
PROP_RE = re.compile(r"(?:举着|手里|拿着|握着|捧着|拎着|捏着|捏住|推着|按着|攥着|托着|递过|端着|手握|握住)"
                     r"(?:一[只条张个枚把盏件双]|两[只张])?([^，。；、,\s]{1,10})")
NOT_PROP = ("手", "指", "腰", "肩", "裙", "衫", "束腰", "风衣", "外套", "系带", "前襟", "下摆", "台沿", "桌沿", "门框", "她", "他")
VISIBLE_PRESENCE = ("在画", "局部")

SLOT_ZH = {"outfit": "服装", "shoes": "鞋", "legwear": "袜/丝袜", "jewelry": "首饰", "accessory": "配件", "piercing": "穿孔饰品",
           "body_mark": "纹身/疤", "nails": "指甲", "makeup": "妆容", "hair": "发型", "prop": "道具"}
SLOT_ORDER = list(SLOT_ZH)
LIB_SLOTS = {"jewelry": ("accessory", "other"), "accessory": ("accessory", "other"), "piercing": ("accessory", "other"),
             "body_mark": ("accessory", "other"), "legwear": ("outfit", "other"), "outfit": ("outfit",), "shoes": ("shoes",),
             "nails": ("nails",), "makeup": ("makeup",), "hair": ("hair",)}
COLORS = {"米白", "深灰", "浅灰", "雾蓝", "深蓝", "军绿", "卡其", "米色", "棕色", "黑", "白", "红", "银", "透明", "灰"}
# 槽位 → 景别可见性代表词（交给 framing.visible 判断）
SLOT_PROBE = {"shoes": "鞋", "legwear": "袜", "outfit": "", "jewelry": "", "accessory": "", "piercing": "", "body_mark": "",
              "nails": "", "makeup": "", "hair": "", "prop": ""}


def _rj(p: Path, default=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return default


def attrs(s: str) -> set[str]:
    out = set()
    for a in ATTR:
        if a in s:
            out.add(a)
    if "黑色" in out:
        out.add("黑")
    if "白色" in out:
        out.add("白")
    if "12厘米" in out:
        out.add("12cm")
    return out


ATTR_START = ("室内", "工作", "冷调", "修剪") + tuple(ATTR)
ATTR_CH = set("黑白灰红蓝绿棕米深浅雾透银金短长细旧皮漆针真九军卡")


def clean_name(prefix: str, noun: str) -> str:
    """前缀只保留"规格"部分：从第一个属性词 / 颜色字开始（去掉"住""把""指勾住她"这类动作残渣）"""
    p = prefix
    for w in POS_WORDS:
        if w != "九串":
            p = p.replace(w, "")
    p = re.sub(r"^[的地得]+", "", p).strip()
    cut = len(p)
    for i in range(len(p)):
        if p[i] in ATTR_CH or p[i].isdigit() or any(p.startswith(a, i) for a in ATTR_START):
            cut = i
            break
    p = p[cut:]
    return (p + noun).strip()


def extract(text: str) -> list[dict]:
    """文本 → 单品提及 [{name, noun, cls, slot, attrs, span}]"""
    out = []
    for m in NOUN_RE.finditer(text or ""):
        noun = m.group(0)
        start = m.start()
        # 前缀：从上一个分隔符到名词前，最多 8 字
        seg = text[max(0, start - 12):start]
        cut = [x.end() for x in DELIM.finditer(seg)]
        prefix = seg[cut[-1]:] if cut else seg[-8:]
        prefix = prefix[-8:]
        cls, slot = NOUN_CLS[noun]
        # "短甲修整干净"、"九串铁珠"这类保留数量词作规格
        full = clean_name(prefix, noun)
        if noun == "铁珠" and "九串" in text[max(0, start - 3):start]:
            full = "九串铁珠"
        out.append({"name": full, "noun": noun, "cls": cls, "slot": slot, "attrs": sorted(attrs(prefix + noun)),
                    "span": [start, m.end()]})
    # 嵌套去重（"红绳手链" 已覆盖 "红绳"）
    out.sort(key=lambda d: (d["span"][0], -(d["span"][1] - d["span"][0])))
    keep, last_end = [], -1
    for d in out:
        if d["span"][0] >= last_end:
            keep.append(d)
            last_end = d["span"][1]
    return keep


def extract_props(text: str) -> list[str]:
    out = []
    for m in PROP_RE.finditer(text or ""):
        p = re.split(r"[的上在从到往向按点压贴]", m.group(1))[0]
        p = re.sub(r"^(着|住|起)", "", p)
        if len(p) >= 2 and not any(p.startswith(x) or p == x for x in NOT_PROP) and not NOUN_RE.search(p):
            out.append(p)
    return out


def canon(it: dict) -> dict:
    """同一件东西的不同写法归一（甲 / 妆 的措辞变体）"""
    it = dict(it)
    if it.get("cls") == "nails_hand":
        it["name"] = "5厘米超长透明镶钻水晶甲"
        it["attrs"] = ["透明", "镶钻", "超长", "5厘米"]
    elif it.get("cls") == "nails_short" or (it.get("slot") == "nails" and "甲" in it["name"] and "水晶" not in it["name"]):
        it["name"], it["cls"] = "短甲（本色）", "nails_short"
    elif it.get("slot") == "makeup":
        it["name"] = it["name"].replace("色眼影", "眼影")
    return it


def same_item(a: dict, b: dict) -> bool:
    """两个提及是不是同一件（名词同组 + 关键属性不冲突）"""
    ga, gb = CLS_GROUP.get(a["cls"], a["cls"]), CLS_GROUP.get(b["cls"], b["cls"])
    if ga != gb:
        return False
    A, B = set(a["attrs"]), set(b["attrs"])
    colors = {"米白", "深灰", "浅灰", "雾蓝", "深蓝", "军绿", "卡其", "米色", "棕色", "黑", "白", "红", "银", "透明", "灰"}
    ca, cb = A & colors, B & colors
    if ca and cb and not (ca & cb):
        return False
    return True


# ---------------------------------------------------------------- 造型登记
def parse_look_fields(raw: str) -> dict[str, str]:
    out = {}
    for part in re.split(r"[｜|]", raw or ""):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def items_of_fields(f: dict[str, str]) -> list[dict]:
    items = []
    for key in ("服装", "鞋", "饰品", "甲", "妆", "发"):
        v = f.get(key)
        if not v:
            continue
        if key == "发":
            items.append({"name": v.split("（")[0].split("，")[0], "noun": "发", "cls": "hair", "slot": "hair",
                          "attrs": sorted(attrs(v)), "spec": v})
            continue
        if key == "妆":
            items.append({"name": v.split("，")[0], "noun": "妆", "cls": "makeup_look", "slot": "makeup",
                          "attrs": [], "spec": v})
            continue
        found = extract(v)
        if key == "甲" and not found:
            found = [{"name": v, "noun": "甲", "cls": "nails_hand" if "水晶" in v else "nails_short", "slot": "nails",
                      "attrs": sorted(attrs(v))}]
        for d in found:
            d = dict(d)
            d.pop("span", None)
            d["spec"] = v if key in ("鞋", "甲") else d["name"]
            if key == "甲" and d["slot"] != "nails":
                continue
            if key == "饰品" and d["cls"] == "nails_hand":      # 饰品里的"钻石水晶甲"归甲
                continue
            items.append(d)
    # 去重
    seen, out = set(), []
    for d in items:
        k = (d["slot"], d["name"])
        if k not in seen:
            seen.add(k)
            out.append(d)
    return out


def load_registry(run: Path) -> dict:
    """char_id → {name, marker, looks: {A: {zh, use, eps, items}}}"""
    reg = {}
    for c in _rj(run / "P1_looks.json", []) or []:
        looks = {}
        for lk in c.get("looks", []):
            f = parse_look_fields(lk.get("zh", ""))
            eps = [int(x) for x in re.findall(r"ep(\d+)", lk.get("use", ""))]
            its = items_of_fields(f)
            # 角色标志物（P1 marker，如钻石水晶甲 / 旧银戒）在每套造型里都算登记
            for m in extract(c.get("marker") or ""):
                m = canon(dict(m, spec=c.get("marker")))
                m.pop("span", None)
                if not any(same_item(m, x) for x in its):
                    its.append(m)
            for x in (EXTRAS.get(c["char_id"], {}) or {}).get(lk["id"], []):       # 暂定外搭 / 装饰（look_extras.json）
                m = extract(x["name"])
                m = dict(m[0] if m else {"cls": x["slot"], "attrs": []}, name=x["name"], slot=x["slot"], spec=x.get("role", ""),
                         tentative=True)
                m.pop("span", None)
                its.append(m)
            looks[lk["id"]] = {"zh": lk.get("zh"), "en": lk.get("en"), "use": lk.get("use"), "eps": eps,
                               "fields": f, "items": its}
        reg[c["char_id"]] = {"name": c["name"], "marker": c.get("marker"), "looks": looks}
    return reg


def match_look(reg_char: dict, header_fields: dict) -> tuple[str | None, float]:
    """集表头 服装 → P1 造型 id（服装原文相同优先，否则单品重合度）"""
    best, score = None, 0.0
    hv = header_fields.get("服装", "")
    hitems = [d for d in extract(hv) if d["slot"] == "outfit"]
    for lid, lk in reg_char["looks"].items():
        if lk["fields"].get("服装", "") == hv:
            return lid, 1.0
        litems = [d for d in lk["items"] if d["slot"] == "outfit"]
        if not litems or not hitems:
            continue
        hit = sum(1 for h in hitems if any(same_item(h, l) for l in litems))
        s = hit / max(len(hitems), len(litems))
        if s > score:
            best, score = lid, s
    return best, score


# ---------------------------------------------------------------- 资产库
def _rel(p: Path) -> str:
    try:
        return str(Path(p).resolve().relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(p).replace("\\", "/")


def load_library(chars: list[str], run: Path | None = None) -> dict:
    w = _rj(ROOT / "data" / "looks" / "wardrobe.json", {"items": []}) or {"items": []}
    refs = _rj(ROOT / "data" / "assets" / "asset_refs.json", {}) or {}
    lib = defaultdict(list)
    for it in w.get("items", []):
        c = it.get("character")
        if c not in chars:
            continue
        files = [im["file"] for im in (it.get("images") or []) if im.get("file")]
        files += [f for f in (it.get("reference_images") or []) if f not in files and (ROOT / f).exists()]
        slot = it.get("slot")
        name = it.get("name", "")
        ex = extract(name.split("（")[0]) or extract(name)
        ex = ex[:1]                               # 只认主名词（"乳环：…细金属环" 不算细金属环）
        lib[c].append({"id": it["id"], "name": name, "slot": slot, "files": files, "source": it.get("source"),
                       "mentions": ex, "worn": "上身" in name, "notes": it.get("notes") or []})
    sheets = defaultdict(dict)
    identity = defaultdict(list)
    for c in chars:
        for r in refs.get(c, []) or []:
            if r.get("role") == "identity":
                identity[c].append(r.get("file"))
    for r in _rj(Path(run or ROOT) / "assets" / "registered_refs.json", []) or []:
        if r.get("role") == "item" and r.get("look"):
            sheets[r["asset"]][r["look"]] = r.get("file")
    return {"items": lib, "sheets": sheets, "identity": identity}


_QC_CACHE: dict[str, dict] = {}


def qc_image(rel: str) -> dict:
    """确定性小质检：尺寸、清晰度（Laplacian 方差，1024 缩放后）、底色是否中性（边框亮度方差）。不做文字检测（GPU 侧做）"""
    if rel in _QC_CACHE:
        return _QC_CACHE[rel]
    p = ROOT / rel
    r = {"file": rel, "exists": p.exists()}
    if not p.exists():
        r["ok"] = False
        r["why"] = "文件不存在"
        _QC_CACHE[rel] = r
        return r
    try:
        import numpy as np
        from PIL import Image
        im = Image.open(p)
        r["size"] = list(im.size)
        g = im.convert("L")
        sc = 1024 / max(g.size)
        if sc < 1:
            g = g.resize((int(g.size[0] * sc), int(g.size[1] * sc)))
        a = np.asarray(g, dtype=np.float32)
        lap = a[1:-1, 1:-1] * -4 + a[:-2, 1:-1] + a[2:, 1:-1] + a[1:-1, :-2] + a[1:-1, 2:]
        r["sharp"] = round(float(lap.var()), 1)
        b = np.concatenate([a[:16].ravel(), a[-16:].ravel(), a[:, :16].ravel(), a[:, -16:].ravel()])
        r["border_std"] = round(float(b.std()), 1)
        why = []
        if min(im.size) < 768:
            why.append(f"分辨率低（短边 {min(im.size)} < 768）")
        if r["sharp"] < 40:
            why.append(f"偏糊（清晰度 {r['sharp']} < 40）")
        r["ok"] = not why
        r["why"] = "；".join(why)
    except Exception as e:  # pragma: no cover
        r["ok"] = False
        r["why"] = f"读图失败 {e}"
    _QC_CACHE[rel] = r
    return r


def lib_lookup(lib: dict, char: str, item: dict, overrides: dict, do_qc: bool) -> dict:
    key = f"{char}:{item['name']}"
    cands = []
    if key not in overrides and (item["slot"] == "hair" or item.get("cls") == "nails_short"
                                 or (item["slot"] == "makeup" and char != "lin_wan") or item.get("cls") == "scar"):
        return {"status": "身份参考覆盖", "matches": [], "note": "随身份脸 / 造型设定图锁定，不单独出单品图"}
    if key in overrides:
        ov = overrides[key]
        if ov.get("status"):
            return {"status": ov["status"], "matches": [], "note": ov.get("note", "")}
        ids = ov.get("ids", [])
        cands = [x for x in lib["items"].get(char, []) if x["id"] in ids]
        exact = True
    else:
        exact = False
        for x in lib["items"].get(char, []):
            if item["slot"] in ("hair", "makeup") or item.get("cls") == "makeup_look":
                if x["slot"] != item["slot"]:
                    continue
                key_txt = item["name"]
                sc = 2 if key_txt and key_txt[:4] in x["name"] else 0
                if sc:
                    cands.append(dict(x, score=sc))
                continue
            if x["slot"] not in LIB_SLOTS.get(item["slot"], (item["slot"],)):
                continue
            for m in x["mentions"]:
                if same_item(item, m):
                    sc = 1 + len(set(item["attrs"]) & set(m["attrs"])) - (1 if x["worn"] else 0) + (1 if x["files"] else 0)
                    cands.append(dict(x, score=sc))
                    break
        cands.sort(key=lambda d: -d["score"])
    matches = []
    for x in cands[:3]:
        qcs = [qc_image(f) for f in x["files"]] if do_qc else []
        matches.append({"id": x["id"], "name": x["name"], "files": x["files"], "worn": x["worn"], "qc": qcs,
                        "score": x.get("score")})
    if not matches:
        return {"status": "缺图", "matches": []}
    top = matches[0]
    if not top["files"]:
        return {"status": "缺图", "matches": matches, "note": "库里有登记但没有图"}
    if do_qc and not any(q.get("ok") for q in top["qc"]):
        return {"status": "图不合格", "matches": matches, "note": "；".join(q.get("why", "") for q in top["qc"])}
    if not exact:
        ia, ma = set(item["attrs"]), set()
        for m in extract(top["name"]):
            ma |= set(m["attrs"])
        diff = {a for a in ia if a not in ma and a not in ("黑", "白", "12cm")}
        if diff & (COLORS | {"漆皮", "针织", "真丝", "皮"}):
            return {"status": "缺图", "matches": matches, "note": f"库里只有不同款的近似品（{top['name']}），差 {sorted(diff)}"}
        if top["worn"]:
            return {"status": "待确认", "matches": matches, "note": "库里只有上身图，缺白底产品图"}
        if diff:
            return {"status": "待确认", "matches": matches, "note": f"近似品，规格词不一致：{sorted(diff)}"}
    return {"status": "有图", "matches": matches}


# ---------------------------------------------------------------- 主扫描
def segment_by_char(text: str, names: list[str]) -> dict[str, str]:
    """按角色名把一条 img 原文切段：从某人名字出现到下一个别人的名字出现"""
    hits = []
    for n in names:
        for m in re.finditer(re.escape(n), text):
            hits.append((m.start(), n))
    hits.sort()
    if not hits:
        return {}
    segs = defaultdict(str)
    cur, cur_start = hits[0][1], 0
    for pos, n in hits[1:]:
        if n != cur:
            segs[cur] += text[cur_start:pos]
            cur, cur_start = n, pos
    segs[cur] += text[cur_start:]
    # 名字前的开头部分（景别 / 机位）归第一个人
    return dict(segs)


def scan(run: Path, script: Path | None = None, do_qc: bool = True) -> dict:
    run = Path(run)
    script = Path(script or ROOT / "data" / "import" / "script_v2.json")
    S = _rj(script, {})
    reg = load_registry(run)
    name2id = {v["name"]: k for k, v in reg.items()}
    for c in (S.get("globals", {}) or {}).get("character_registry", []) or []:
        name2id.setdefault(c["name"], c.get("char_id"))
    chars = list(reg)
    lib = load_library(chars, run)
    overrides = _rj(LIB_MAP, {}) or {}

    inv: dict[str, dict] = {}          # key char:look:slot:name
    issues: list[dict] = []
    shots_out = []
    look_by_shot: dict[tuple[int, int, str], str] = {}

    def add(char, look, it, src, shot=None, mention=None):
        it = canon(it)
        k = f"{char}:{look}:{it['slot']}:{it['name']}"
        e = inv.setdefault(k, {"key": k, "char": char, "char_name": reg.get(char, {}).get("name", char), "look": look,
                               "slot": it["slot"], "name": it["name"], "cls": it.get("cls"), "attrs": it.get("attrs", []),
                               "spec": it.get("spec", it["name"]), "sources": [], "shots_mentioned": [],
                               "shots_look_active": [], "registered": False})
        if src not in e["sources"]:
            e["sources"].append(src)
        if src == "P1":
            e["registered"] = True
        if shot and mention and shot not in e["shots_mentioned"]:
            e["shots_mentioned"].append(shot)
        return e

    # 1) P1 登记
    for cid, c in reg.items():
        for lid, lk in c["looks"].items():
            for it in lk["items"]:
                add(cid, lid, it, "P1")

    # 2) 每集表头 → 造型；偏离登记的列出
    for ep in S.get("episodes", []):
        n = ep["number"]
        heads = defaultdict(list)
        for lk in ep.get("looks", []):
            cid = name2id.get(lk["character"])
            if cid not in reg:
                issues.append({"type": "未登记角色", "ep": n, "char": lk["character"], "detail": lk.get("raw", "")[:80]})
                continue
            f = lk.get("slots") or parse_look_fields(lk.get("raw", ""))
            lid, sc = match_look(reg[cid], f)
            heads[cid].append({"from_shot": lk.get("from_shot") or 1, "look": lid, "score": sc, "fields": f})
            if lid is None or sc < 0.99:
                issues.append({"type": "表头造型偏离登记", "ep": n, "char": reg[cid]["name"], "look": lid,
                               "detail": f"服装={f.get('服装', '')}；最接近 {lid}（重合 {sc:.2f}）",
                               "owner": "写作（内容层）", "fix": f"按 P1 造型 {lid} 原文改表头，或在 P1 登记新造型（需项目方批）"})
            reg_l = reg[cid]["looks"].get(lid) if lid else None
            if reg_l:
                if n not in reg_l["eps"]:
                    issues.append({"type": "造型用在登记集之外", "ep": n, "char": reg[cid]["name"], "look": lid,
                                   "detail": f"P1 登记 {lid} 用于 {reg_l['use']}", "owner": "写作（内容层）或 P1 登记",
                                   "fix": "补 P1 use 字段，或换成该集登记造型"})
                rf = reg_l["fields"]
                for slot in ("鞋",):
                    hv, rv = f.get(slot, ""), rf.get(slot, "")
                    if hv and rv:
                        hx, rx = extract(hv), extract(rv)
                        if hx and rx and not same_item(hx[0], rx[0]):
                            issues.append({"type": "同造型不同鞋（表头）", "ep": n, "char": reg[cid]["name"], "look": lid,
                                           "detail": f"表头 鞋={hv}；P1 {lid} 鞋={rv}", "owner": "写作（内容层）",
                                           "fix": f"表头鞋改回 {rv}"})
                # 表头的发 / 妆 / 甲 记到该造型（发妆随集变）
                for it in items_of_fields({k: f[k] for k in ("妆", "发", "甲") if k in f}):
                    if it["slot"] == "hair":
                        it = dict(it, name="发型（身份锁）", spec=f.get("发", ""))
                    add(cid, lid, it, f"header:ep{n:02d}")
                for it in items_of_fields({"饰品": f.get("饰品", "")}):
                    e = add(cid, lid, it, f"header:ep{n:02d}")
        for cid in heads:
            heads[cid].sort(key=lambda h: h["from_shot"])

        # 3) 逐镜
        for sh in ep.get("shots", []):
            sid = f"E{n:02d}S{sh['index']:02d}"
            text = sh.get("img_prompt") or ""
            size = FR.size_of(text) if FR else None
            cast = [(c.get("name"), c.get("presence"), c.get("part")) for c in sh.get("cast", [])]
            vis = [(nm, pr, pt) for nm, pr, pt in cast if pr in VISIBLE_PRESENCE]
            names = [nm for nm, _, _ in cast]
            segs = segment_by_char(text, names)
            if len(vis) == 1 and vis[0][0] not in segs:
                segs[vis[0][0]] = text
            rec = {"shot": sid, "size": size, "decor": sh.get("decor_state"), "chars": []}
            for nm, pr, pt in vis:
                cid = name2id.get(nm)
                if cid not in reg:
                    continue
                hs = [h for h in heads.get(cid, []) if h["from_shot"] <= sh["index"]]
                lid = hs[-1]["look"] if hs else None
                look_by_shot[(n, sh["index"], cid)] = lid
                seg = segs.get(nm, "")
                # 第一个人的段补上开头（景别 / 机位前缀里也可能有单品）
                ments = extract(seg)
                props = extract_props(seg)
                reg_items = reg[cid]["looks"].get(lid, {}).get("items", []) if lid else []
                crec = {"char": cid, "presence": pr, "part": pt, "look": lid, "items": [], "props": props}
                hdr = next((h for h in reversed(heads.get(cid, [])) if h["from_shot"] <= sh["index"]), None)
                hdr_mk = next((h["fields"].get("妆") for h in reversed(heads.get(cid, []))
                               if h["from_shot"] <= sh["index"] and h["fields"].get("妆")), "")   # 换装行没写妆 = 沿用
                for m in ments:
                    if m["slot"] == "makeup":
                        mk = m["name"].replace("色眼影", "眼影")
                        if mk not in hdr_mk.replace("色眼影", "眼影"):
                            issues.append({"type": "镜头妆容偏离表头", "ep": n, "shot": sid, "char": nm, "look": lid,
                                           "detail": f"镜头写 {m['name']}；表头 妆={hdr_mk or '（无）'}", "owner": "写作（内容层）",
                                           "fix": "统一到表头妆容（或表头改为该妆，并补妆容参考图）"})
                        crec["items"].append({"name": m["name"], "slot": "makeup", "status": "妆容"})
                        continue
                    m = canon(m)
                    hit = next((r for r in reg_items if same_item(m, r)), None)
                    if not hit and m.get("cls") == "nails_short":
                        hit = m          # 短甲是身份默认，不算未登记
                    owner_other = None
                    if not hit:
                        for onm, _, _ in cast:
                            ocid = name2id.get(onm)
                            if ocid == cid or ocid not in reg:
                                continue
                            ohs = [h for h in heads.get(ocid, []) if h["from_shot"] <= sh["index"]]
                            olid = ohs[-1]["look"] if ohs else None
                            oit = next((r for r in reg[ocid]["looks"].get(olid, {}).get("items", []) if same_item(m, r)), None) if olid else None
                            if oit:
                                owner_other = (ocid, olid, oit, onm)
                                break
                    if owner_other:
                        ocid, olid, oit, onm = owner_other
                        add(ocid, olid, oit, "P1", sid, True)
                        crec["items"].append({"name": m["name"], "slot": m["slot"], "status": f"他人单品（{onm}）"})
                        continue
                    other = None
                    if not hit:
                        for olid, olk in reg[cid]["looks"].items():
                            if olid != lid and any(same_item(m, r) for r in olk["items"]):
                                other = olid
                                break
                    # 别人的单品（披着顾沉的外套等）——名字在段里但属另一人：按段归属，不判矛盾
                    it = dict(m)
                    it.pop("span", None)
                    if hit:
                        e = add(cid, lid, hit, "P1", sid, True)
                        status = "登记"
                    else:
                        if m["slot"] == "shoes" and any(r["slot"] == "shoes" for r in reg_items):
                            rs = next(r for r in reg_items if r["slot"] == "shoes")
                            issues.append({"type": "同造型不同鞋（镜头）", "ep": n, "shot": sid, "char": nm, "look": lid,
                                           "detail": f"镜头写 {m['name']}；{lid} 登记 {rs['name']}",
                                           "owner": "写作（内容层）", "fix": f"镜头鞋改为 {rs['name']}（台词不动）"})
                            status = "矛盾"
                        elif other:
                            issues.append({"type": "镜头混入其他造型单品", "ep": n, "shot": sid, "char": nm, "look": lid,
                                           "detail": f"镜头写 {m['name']}（属 {other} 造型），本镜造型 {lid}",
                                           "owner": "写作（内容层）", "fix": f"按 {lid} 改，或表头加 from_shot 换装"})
                            status = "跨造型"
                        elif m["slot"] in ("makeup",):
                            status = "妆容变体"
                        else:
                            issues.append({"type": "未登记单品", "ep": n, "shot": sid, "char": nm, "look": lid,
                                           "detail": f"{SLOT_ZH.get(m['slot'], m['slot'])}：{m['name']}",
                                           "owner": "写作（内容层）/ P1 登记", "fix": "登记到该造型（暂定）或从镜头删去"})
                            status = "未登记"
                        e = add(cid, lid or "?", it, f"shot:{sid}", sid, True)
                    crec["items"].append({"name": m["name"], "slot": m["slot"], "status": status})
                for p in props:
                    add(cid, lid or "?", {"name": p, "slot": "prop", "cls": "prop", "attrs": []}, f"shot:{sid}", sid, True)
                rec["chars"].append(crec)
            shots_out.append(rec)

    # 4) 造型在用的镜（按景别可见）——缺图影响面
    for (n, idx, cid), lid in look_by_shot.items():
        sid = f"E{n:02d}S{idx:02d}"
        rec = next(r for r in shots_out if r["shot"] == sid)
        for e in inv.values():
            if e["char"] == cid and e["look"] == lid and e["registered"]:
                probe = SLOT_PROBE.get(e["slot"], "")
                if FR is None or FR.visible(probe or e["name"], rec["size"]):
                    if sid not in e["shots_look_active"]:
                        e["shots_look_active"].append(sid)

    # 5) 资产库对照
    for e in inv.values():
        if e["slot"] == "prop":
            e["lib"] = {"status": "道具（场景/道具库）", "matches": []}
            continue
        e["lib"] = lib_lookup(lib, e["char"], e, overrides, do_qc)

    # 6) 造型设定图
    sheets = []
    for cid, c in reg.items():
        for lid in c["looks"]:
            f = lib["sheets"].get(cid, {}).get(lid)
            sheets.append({"char": cid, "look": lid, "file": f, "status": "有图（旧版，单品未锁）" if f else "缺图",
                           "needs_v2": True})

    # 7) 项目方上传但没挂到任何造型的单品
    owner_only = []
    for cid in chars:
        for x in lib["items"].get(cid, []):
            if x["source"] in ("hub_upload", "upload") and x["files"]:
                used = any(any(mm["id"] == x["id"] for mm in e["lib"].get("matches", [])[:1]) for e in inv.values())
                if not used:
                    owner_only.append({"char": cid, "id": x["id"], "name": x["name"], "slot": x["slot"], "files": x["files"],
                                       "status": "有图（项目方上传，暂不挂造型）"})
                    issues.append({"type": "项目方上传单品未挂造型", "char": reg[cid]["name"], "detail": f"{x['id']} {x['name']}",
                                   "owner": "总调度（挂哪个造型需项目方定）", "fix": "确认挂到哪个造型 / 替换哪件"})

    items = sorted(inv.values(), key=lambda e: (e["char"], e["look"], SLOT_ORDER.index(e["slot"]) if e["slot"] in SLOT_ORDER else 99, e["name"]))
    todo = [{"key": e["key"], "char": e["char"], "look": e["look"], "slot": e["slot"], "name": e["name"], "spec": e["spec"],
             "status": e["lib"]["status"], "note": e["lib"].get("note", ""), "shots": sorted(set(e["shots_mentioned"]) | set(e["shots_look_active"])),
             "registered": e["registered"]}
            for e in items if e["lib"]["status"] in ("缺图", "图不合格", "待确认")]
    summary = defaultdict(int)
    for e in items:
        summary[e["lib"]["status"]] += 1
    itypes = defaultdict(int)
    for i in issues:
        itypes[i["type"]] += 1
    return {"generated_at": datetime.now().isoformat(timespec="seconds"), "run": _rel(run), "script": _rel(script), "summary": dict(summary), "issue_counts": dict(itypes),
            "items": items, "sheets": sheets, "owner_uploads": owner_only, "issues": issues, "shots": shots_out, "todo": todo,
            "identity": {k: v for k, v in lib["identity"].items()}}


# ---------------------------------------------------------------- 输出
def to_md(r: dict) -> str:
    L = [f"# 资产盘点（ASSETMASTER）· {r['run']}", "",
         f"> 生成：{r['generated_at']}，工具 `tools/assetmaster/scan.py`（只读）。剧本 `{r['script']}`。",
         "> 状态：**有图** = 库里有对应单品图且通过小质检；**缺图**；**图不合格**（分辨率 / 清晰度不过）；"
         "**待确认** = 库里有近似品但规格词不同或只有上身图。机器可读版：`data/assetmaster/inventory.json`，待补队列：`data/assetmaster/todo.json`。", "",
         "## 总览", "", "| 状态 | 件数 |", "|---|---|"]
    for k, v in sorted(r["summary"].items()):
        L.append(f"| {k} | {v} |")
    L += ["", "| 问题类型 | 条数 |", "|---|---|"]
    for k, v in sorted(r["issue_counts"].items(), key=lambda x: -x[1]):
        L.append(f"| {k} | {v} |")
    L += ["", "## 造型设定图", "", "| 角色 | 造型 | 现有 | 状态 |", "|---|---|---|---|"]
    for s in r["sheets"]:
        L.append(f"| {s['char']} | {s['look']} | `{s['file'] or '—'}` | {s['status']}；需出 v2（用补全后的单品） |")
    cur = None
    for e in r["items"]:
        h = (e["char"], e["look"])
        if h != cur:
            cur = h
            L += ["", f"## {e['char_name']}（{e['char']}）· 造型 {e['look']}", "",
                  "| 槽位 | 单品 | 登记 | 资产库 | 状态 | 出现的镜（文字提及） | 造型在用且景别可见的镜 |", "|---|---|---|---|---|---|---|"]
        m = e["lib"].get("matches") or []
        libtxt = "<br>".join(f"{x['id']}（{len(x['files'])} 图）" for x in m[:2]) or "—"
        note = e["lib"].get("note", "")
        st = e["lib"]["status"] + (f"：{note}" if note else "")
        L.append(f"| {SLOT_ZH.get(e['slot'], e['slot'])} | {e['name']} | {'P1' if e['registered'] else '未登记（' + ','.join(s for s in e['sources'][:3]) + '）'} "
                 f"| {libtxt} | {st} | {' '.join(e['shots_mentioned'][:12])}{' …' if len(e['shots_mentioned']) > 12 else ''} "
                 f"| {len(e['shots_look_active'])} 镜 |")
    L += ["", "## 项目方上传的单品（已有图，暂不挂造型）", "", "| 角色 | id | 名称 | 槽位 | 图 |", "|---|---|---|---|---|"]
    for o in r.get("owner_uploads", []):
        L.append(f"| {o['char']} | {o['id']} | {o['name']} | {o['slot']} | {'<br>'.join('`' + f + '`' for f in o['files'])} |")
    L += ["", "## 剧本矛盾 / 未登记（内容层交写作模型按登记修，台词不动；系统层交 REFLOCK）", "",
          "| 类型 | 集 | 镜 | 角色 | 造型 | 内容 | 归属 | 建议 |", "|---|---|---|---|---|---|---|---|"]
    for i in r["issues"]:
        L.append(f"| {i['type']} | {i.get('ep', '')} | {i.get('shot', '')} | {i.get('char', '')} | {i.get('look', '') or ''} "
                 f"| {i.get('detail', '')} | {i.get('owner', '')} | {i.get('fix', '')} |")
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="data/pipeline/runs/series10_v1")
    ap.add_argument("--script", default=None)
    ap.add_argument("--no-qc", action="store_true")
    ap.add_argument("--out-json", default=str(OUT_JSON))
    ap.add_argument("--out-md", default=str(OUT_MD))
    a = ap.parse_args(argv)
    r = scan(ROOT / a.run, Path(a.script) if a.script else None, do_qc=not a.no_qc)
    oj, om = Path(a.out_json), Path(a.out_md)
    oj.parent.mkdir(parents=True, exist_ok=True)
    om.parent.mkdir(parents=True, exist_ok=True)
    oj.write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
    OUT_TODO.write_text(json.dumps({"generated_at": r["generated_at"], "run": r["run"], "todo": r["todo"]},
                                   ensure_ascii=False, indent=1), encoding="utf-8")
    om.write_text(to_md(r), encoding="utf-8")
    print(json.dumps({"summary": r["summary"], "issues": r["issue_counts"], "todo": len(r["todo"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
