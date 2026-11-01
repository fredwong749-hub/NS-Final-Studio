"""资产参考锁定（REFLOCK 2026-10-31；契约 docs/GEN_CONTRACT.md I2–I5、I9；规则 K-AST-230 / K-REN-130）。

起因（项目方原话）：“关于女主角鞋子的一致性也全部错了，不同地方的鞋子都不一样，说明你没有做到 reference 的做法……
你要在 image 里面让它知道，这个女孩要穿这个鞋子、穿这个衣服、戴这个饰品等等，然后才能锁定一致性。”
series10 首帧原来只挂脸部裁切，服装 / 鞋 / 饰品全靠文字 → 每镜都不一样。

本模块两件事：
1. resolve_shot(ctx) —— 解析一镜每个在画角色“必须锁定”的参考图：
     身份脸（脸可见时）+ 本镜造型设定图（特写 / 近景取半身栏，中景及更远取正面全身栏）
     + 景别可见的单品图（K-REN-101 可见性：特写 / 近景只取上身与手、颈饰品；中景加下装；中全景及更远加鞋；
       局部特写只取该局部，例如鞋特写只取鞋）。
   单品图来源：衣橱产品图（config item_map 映射）> 造型设定图裁切（标“仅设定图”）> 都没有 = 资产缺图（阻断）。
2. plan_slots(refs, model) —— 按模型槽位数排参考：身份脸 > 造型设定图 > 景别关键单品 > 场景（局部特写时该局部的单品最高）；
   槽位不够 → 同一角色的设定图 / 单品拼成“参考板”（固定网格 + 编号标注）；双人镜只给主体角色脸参考，
   第二人用其造型设定图（不进同一槽，板里不出现第二张脸）；提示词逐一写“图N是…必须完全一致”。
只做格式与资产选择，不改写作方文字。
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path

from ns_agent import framing as FR

ROOT = Path(__file__).resolve().parents[3]
CFG = ROOT / "config" / "recipes" / "asset_refs.json"
WARDROBE = ROOT / "data" / "looks" / "wardrobe.json"
SCENES = ROOT / "assets" / "scenes"
IMG_EXT = (".png", ".jpg", ".jpeg", ".webp")
NAME_ID = {"林晚": "lin_wan", "顾沉": "gu_chen", "陈宇": "chen_yu", "阿岚": "ch_a_lan"}
ID_NAME = {v: k for k, v in NAME_ID.items()}
CIRCLED = "①②③④⑤⑥⑦⑧⑨"

# ---------------------------------------------------------------- 景别 → 可见区域（K-REN-101）
ZONES_BY_SIZE = {
    "极近特写": {"face", "neck", "upper", "body", "hand"},
    "大特写": {"face", "neck", "upper", "body", "hand"},
    "特写": {"face", "neck", "upper", "body", "hand"},
    "近景": {"face", "neck", "upper", "body", "hand"},
    "中近景": {"face", "neck", "upper", "body", "hand"},
    "中景": {"face", "neck", "upper", "body", "hand", "lower", "waist"},
}
ALL_ZONES = {"face", "neck", "upper", "body", "hand", "lower", "waist", "feet"}
PART_ZONES = (  # 局部特写：part_name → 可见区域
    (("鞋", "跟", "脚", "足", "踝", "趾"), {"feet"}),
    (("手", "指", "甲"), {"hand"}),
    (("腰", "腹", "臀"), {"waist", "lower", "body"}),
    (("腿", "膝"), {"lower", "feet", "body"}),
    (("锁骨", "颈", "肩", "胸", "背"), {"neck", "upper", "body"}),
)
SHEET_PANEL_BY_SIZE = {"极近特写": "half", "大特写": "half", "特写": "half", "近景": "half", "中近景": "half"}
ZONE_ORDER = {"feet": 0, "lower": 1, "body": 2, "upper": 3, "waist": 4, "hand": 5, "neck": 6, "face": 7}
SLOT_LABEL = {"outfit": "服装", "shoes": "鞋", "accessory": "饰品", "nails": "指甲", "marker": "标志"}


def _cfg() -> dict:
    try:
        return json.loads(CFG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def project_chain(project: str) -> list[str]:
    """项目 → [自己, 父, 祖父…]（"inherits": "<父项目>"；总调度 11-02：第二季继承第一季的资产项目，不另造资产库）。防环"""
    projs = _cfg().get("projects") or {}
    out, cur = [], project
    while cur and cur not in out and cur in projs:
        out.append(cur)
        cur = (projs.get(cur) or {}).get("inherits")
    return out or [project]


def _deep_merge(base: dict, over: dict) -> dict:
    out = json.loads(json.dumps(base))
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def project_cfg(project: str) -> dict:
    """项目配置；有 inherits 时从最上层父项目起逐层合并（字典键深合并：faces / item_map / female…；标量与文件路径子项目覆盖）。
    子项目没写的文件路径（looks_file / sheets_file / shot_looks_file / crop_dir / board_dir）沿用父项目的"""
    projs = _cfg().get("projects") or {}
    merged: dict = {}
    for name in reversed(project_chain(project)):
        merged = _deep_merge(merged, {k: v for k, v in (projs.get(name) or {}).items() if k != "inherits"})
    if len(project_chain(project)) > 1:
        merged["inherits"] = (projs.get(project) or {}).get("inherits")
    return merged


def chain_files(project: str, key: str) -> list[Path]:
    """继承链上每一层自己写的某个文件（子在前）：例如 sheets_file——子季新加的造型设定图写在子季文件里，没写的回落到父季"""
    projs = _cfg().get("projects") or {}
    out = []
    for name in project_chain(project):
        v = (projs.get(name) or {}).get(key)
        if v and (ROOT / v) not in out:
            out.append(ROOT / v)
    return out


def model_slots(model: str) -> int:
    m = (_cfg().get("models") or {}).get(model) or {}
    return int(m.get("slots") or 3)


def g(o, k, d=None):
    """dict / pydantic 对象统一取字段"""
    if isinstance(o, dict):
        return o.get(k, d)
    return getattr(o, k, d)


def rel(p: Path | str) -> str:
    p = Path(p)
    try:
        return p.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return p.as_posix()


def sha_file(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()[:16]


# ---------------------------------------------------------------- 造型部件解析
@dataclass
class LookPart:
    slot: str            # outfit | shoes | accessory | nails | marker
    label: str           # 中文部件名（原文）
    zone: str            # feet | lower | upper | body | waist | hand | neck | face
    item_id: str | None = None
    force_missing: bool = False          # 登记为“缺图”（设定图里也没有，例：林晚 A 的短款西装外套）
    extra: bool = False                  # ASSETMASTER 暂定登记的外搭 / 身体装饰（data/assetmaster/look_extras.json）
    eps: tuple | None = None             # extra 生效的集（None = 全部）；(n, None) = 第 n 集起
    keys: tuple = ()                     # extra 只在 img 正文写到这些词时算在画


@dataclass
class Look:
    char: str
    look_id: str         # "A" / "B" / "C"
    zh: str
    en: str
    use: str
    parts: list[LookPart] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"{self.char}_look{self.look_id}"


def _short(label: str) -> str:
    return re.sub(r"[（(].*?[）)]", "", label).strip()


def zone_of(slot: str, label: str) -> str:
    t = label
    if slot == "shoes":
        return "feet"
    if slot == "nails":
        return "hand"
    if slot == "marker":
        return "face"
    if slot == "outfit":
        if any(w in t for w in ("长裙", "浴袍", "连衣裙", "围裙", "工装", "连体", "睡裙")):
            return "body"
        if any(w in t for w in ("裙", "裤")):
            return "lower"
        return "upper"
    # accessory
    if any(w in t for w in ("疤", "眉")):
        return "face"
    if any(w in t for w in ("手链", "红绳", "戒", "手套", "手镯", "腕")):
        return "hand"
    if any(w in t for w in ("项链", "银链", "颈", "锁骨")):
        return "neck"
    if any(w in t for w in ("珠", "腰")):
        return "waist"
    return "upper"


def parse_parts(zh: str) -> list[LookPart]:
    """“服装=A配B，外罩C｜鞋=D｜饰品=E、F” → 部件清单"""
    parts: list[LookPart] = []
    for seg in (zh or "").split("｜"):
        if "=" not in seg:
            continue
        k, v = seg.split("=", 1)
        k = k.strip()
        if k == "服装":
            for p in re.split(r"配|，|,|外罩|搭", v):
                p = p.strip()
                if p:
                    parts.append(LookPart("outfit", p, zone_of("outfit", p)))
        elif k == "鞋":
            parts.append(LookPart("shoes", v.strip(), "feet"))
        elif k in ("饰品", "甲"):
            depth, cur, items = 0, "", []
            for ch in v:                                      # 括号里的顿号不切
                depth += ch in "（("
                depth -= ch in "）)"
                if ch == "、" and depth == 0:
                    items.append(cur)
                    cur = ""
                else:
                    cur += ch
            items.append(cur)
            for p in (x.strip() for x in items):
                if not p:
                    continue
                slot = "nails" if "甲" in _short(p) else ("marker" if "疤" in p else "accessory")
                parts.append(LookPart(slot, p, zone_of(slot, p)))
    return parts


OVERRIDES = ROOT / "data" / "looks" / "item_map_overrides.json"


QUARANTINE = ROOT / "data" / "looks" / "item_map_quarantine.json"


# ---------------------------------------------------------------- 解析层（覆盖配置）按 run 继承（K-OPS-W18 修订，总调度 11-02 P0）
# 解析层 = 资产中心等写的 {project: {...}} 覆盖文件：face_overrides / item_map_overrides / item_map_quarantine / hub_extra_looks。
# 子季没写的回落父季；hub_episode_looks（按集排期）每季集号不同，不继承。登记见 config/policies/resolution_layers.yaml

class DecisionFileError(ValueError):
    """决策 / 覆盖文件存在但读不出（坏 JSON、截断）——K-OPS-F09：不许静默当成“没有覆盖”，出图前就报错拒派"""


def _overlay_doc(path: Path) -> dict:
    """覆盖文件：不存在 = 没有覆盖（是否必须存在由 tools/factory/decisions_guard 在派单前查，K-OPS-F09）；
    存在但读不出 = 抛 DecisionFileError（⤴ 取代原来的“读不出 = {}”静默回退，ARCH_MAP #2；总调度 03:0x 授权，CONSENT 总调度）"""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8")) or {}
    except (OSError, ValueError) as e:
        raise DecisionFileError(f"决策文件读不出：{path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else path}（{e}）") from e


def overlay_value(path: Path, project: str, key: str):
    """单键覆盖（例：身份脸 face_overrides[project][cid]）：继承链上第一个写了这个键的项目的值"""
    d = _overlay_doc(path)
    for name in project_chain(project):
        v = (d.get(name) or {}).get(key)
        if v is not None:
            return v
    return None


def overlay_layers(path: Path, project: str) -> list[dict]:
    """分层覆盖（例：item_map_overrides）：父季在前、子季在后，调用方依次叠加"""
    d = _overlay_doc(path)
    return [d.get(name) or {} for name in reversed(project_chain(project))]


def quarantine(project: str) -> dict:
    """待项目方确认、暂不生效的映射（总调度 11-01：疑似资产中心选择器点错的 6 条）"""
    out: dict = {}
    for layer in overlay_layers(QUARANTINE, project):
        out = _deep_merge(out, layer)
    return out


def item_map(project: str) -> dict:
    """造型部件 → 衣橱单品：config item_map（系统提议）之上合并资产中心写的 data/looks/item_map_overrides.json
    （{project:{char:{look:{部件名: item_id | null}}}}；null = 解除映射；可带 _by / _at 记录键，读时忽略）"""
    base = json.loads(json.dumps(project_cfg(project).get("item_map") or {}))
    ov: dict = {}
    for layer in overlay_layers(OVERRIDES, project):      # 解析层按 run 继承：父季的映射在前，子季的覆盖在后
        ov = _deep_merge(ov, layer)
    for cid, lks in ov.items():
        if cid.startswith("_") or not isinstance(lks, dict):
            continue
        for lid, m in lks.items():
            if lid.startswith("_") or not isinstance(m, dict):
                continue
            tgt = base.setdefault(cid, {}).setdefault(lid, {})
            qz = ((quarantine(project).get(cid) or {}).get(lid) or {})
            for k, v in m.items():
                if k.startswith("_") or (k in qz and (qz[k] or {}).get("item") == v):
                    continue                             # 隔离区里的映射暂不生效（data/looks/item_map_quarantine.json）
                if v is None:
                    tgt.pop(k, None)
                else:
                    tgt[k] = v
    return base


HUB_LOOKS = ROOT / "data" / "looks" / "hub_extra_looks.json"
HUB_EP_LOOKS = ROOT / "data" / "looks" / "hub_episode_looks.json"


def _hub(path: Path, project: str, inherit: bool = False) -> dict:
    """inherit=True：按继承链逐层合并（hub_extra_looks）；按集排期（hub_episode_looks）每季集号不同，不继承"""
    if not inherit:
        return (_overlay_doc(path).get(project) or {})
    out: dict = {}
    for layer in overlay_layers(path, project):
        out = _deep_merge(out, layer)
    return out


def hub_extra_looks(project: str, p1: list) -> list:
    """data/looks/hub_extra_looks.json {project:{cid:[{id, use, zh}]}} → 与 P1 同格式的条目（P1 已有的 id 跳过）"""
    have = {(c.get("char_id") or NAME_ID.get(c.get("name"))): {lk["id"] for lk in c.get("looks") or []} for c in p1}
    out = []
    for cid, lks in _hub(HUB_LOOKS, project, inherit=True).items():
        if cid.startswith("_") or not isinstance(lks, list):
            continue
        new = [{k: v for k, v in lk.items() if not k.startswith("_")} for lk in lks
               if isinstance(lk, dict) and lk.get("id") and lk["id"] not in have.get(cid, set())]
        if new:
            out.append({"char_id": cid, "name": ID_NAME.get(cid, cid), "looks": new})
    return out


def episode_look_override(project: str, cid: str, ep_n: int) -> str | None:
    """资产中心“排期：角色 × 集”（data/looks/hub_episode_looks.json {project:{cid:{"3":"B"}}}）：某人某集整集用该造型"""
    v = (_hub(HUB_EP_LOOKS, project).get(cid) or {}).get(str(ep_n))
    return v if isinstance(v, str) and v else None


def load_looks(project: str) -> dict[str, dict[str, Look]]:
    # 继承：父季造型表在前、子季在后（同一角色同一造型 id 以子季为准；子季新增的造型追加）
    data = []
    for p in reversed(chain_files(project, "looks_file")):
        try:
            layer = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for c in layer:
            cid = c.get("char_id") or NAME_ID.get(c.get("name"), c.get("name"))
            hit = next((x for x in data if (x.get("char_id") or NAME_ID.get(x.get("name"), x.get("name"))) == cid), None)
            if hit is None:
                data.append(json.loads(json.dumps(c)))
            else:
                ids = {lk.get("id"): i for i, lk in enumerate(hit.get("looks") or [])}
                for lk in c.get("looks") or []:
                    if lk.get("id") in ids:
                        hit["looks"][ids[lk["id"]]] = lk
                    else:
                        hit.setdefault("looks", []).append(lk)
    if not data:
        return {}
    imap = item_map(project)
    out: dict[str, dict[str, Look]] = {}
    data = list(data) + hub_extra_looks(project, data)     # 资产中心“＋ 新造型”（id 与 P1 重复时以 P1 为准）
    for c in data:
        cid = c.get("char_id") or NAME_ID.get(c.get("name"), c.get("name"))
        for lk in c.get("looks") or []:
            L = Look(cid, lk["id"], lk.get("zh", ""), lk.get("en", ""), lk.get("use", ""), parse_parts(lk.get("zh", "")))
            m = (imap.get(cid) or {}).get(lk["id"]) or {}
            L.parts += extra_parts(cid, lk["id"])
            labels = [(_short(pt.label), pt.label) for pt in L.parts]
            for key, iid in m.items():                    # 资产中心“加到造型”的附加单品（键不是任何部件名）：正文写到才挂
                if iid == MISSING or any(key == a or key == b or key in b for a, b in labels):
                    continue
                it = wardrobe().get(iid) or {}
                slot = it.get("slot") if it.get("slot") in ("outfit", "shoes", "accessory", "nails") else "accessory"
                nm = re.sub(r"（[^）]*）", "", key)
                L.parts.append(LookPart(slot, key, zone_of(slot, nm), iid, extra=True,
                                        keys=tuple(k for k in {nm, nm[-3:], nm[-2:]} if len(k) >= 2)))
            for part in L.parts:
                for label, iid in m.items():
                    if label == _short(part.label) or label == part.label or (label in part.label):
                        if iid == MISSING:
                            part.item_id, part.force_missing = None, True
                        else:
                            part.item_id = iid
                        break
            out.setdefault(cid, {})[lk["id"]] = L
    return out


MISSING = "__missing__"          # item_map / 覆盖里写这个 = 判为缺图（设定图里也没有）
EXTRAS = ROOT / "data" / "assetmaster" / "look_extras.json"
EXTRA_ZONE = {"piercing": "waist", "outfit": "upper", "shoes": "feet", "accessory": "upper"}


def _eps_of(role: str) -> tuple | None:
    m = re.search(r"ep(\d+)\s*起", role or "")
    if m:
        return (int(m.group(1)), None)
    ns = [int(x) for x in re.findall(r"ep(\d+)", role or "")]
    return tuple(ns) or None


def extra_parts(cid: str, look_id: str) -> list[LookPart]:
    """ASSETMASTER 暂定登记（总调度批）：造型外搭 / 身体装饰。不改 P1 原文；只在对应集、且 img 正文写到时算在画"""
    d = _overlay_doc(EXTRAS)          # K-OPS-F09：不存在 = 没有外搭；坏文件 = 报错，不静默
    out = []
    for e in ((d.get(cid) or {}).get(look_id) or []):
        name = e.get("name") or ""
        slot = e.get("slot") or "accessory"
        zone = EXTRA_ZONE.get(slot) or zone_of(slot if slot in ("outfit", "shoes") else "accessory", name)
        if slot == "outfit" and any(w in name for w in ("风衣", "长外套", "大衣")):
            zone = "body"
        keys = tuple(k for k in {name, name[-3:], name[-2:]} if len(k) >= 2)
        ids = e.get("lib_ids") or []
        out.append(LookPart(slot if slot in ("outfit", "shoes") else "accessory", name, zone, ids[0] if ids else None,
                            force_missing=not ids, extra=True, eps=_eps_of(e.get("role", "")), keys=keys))
    return out


def part_active(p: LookPart, ep_n: int, img: str) -> bool:
    if not p.extra:
        return True
    if p.eps:
        if len(p.eps) == 2 and p.eps[1] is None:
            if ep_n < p.eps[0]:
                return False
        elif ep_n not in p.eps:
            return False
    return any(k in (img or "") for k in p.keys)


# ---------------------------------------------------------------- 衣橱 / 设定图 / 裁切
@lru_cache(maxsize=4)
def _wardrobe(mtime: float) -> dict[str, dict]:
    try:
        return {i["id"]: i for i in json.loads(WARDROBE.read_text(encoding="utf-8")).get("items", [])}
    except (OSError, ValueError):
        return {}


def wardrobe() -> dict[str, dict]:
    try:
        return _wardrobe(WARDROBE.stat().st_mtime)
    except OSError:
        return {}


def item_image(item_id: str) -> str | None:
    it = wardrobe().get(item_id)
    if not it:
        return None
    for im in it.get("images") or []:
        if (ROOT / im["file"]).is_file():
            return im["file"]
    return next((r for r in it.get("reference_images") or [] if (ROOT / r).is_file()), None)


def item_name(item_id: str) -> str:
    it = wardrobe().get(item_id) or {}
    return re.sub(r"（[^）]*）$", "", it.get("name") or item_id)


def sheet_of(project: str, cid: str, look_id: str) -> str | None:
    """当前设定图：继承链上子季的选定表优先，没有这条（或文件不在）就回落到父季（第二季沿用第一季现行造型设定图）"""
    for p in chain_files(project, "sheets_file"):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        e = d.get(f"sheet:{cid}_look{look_id}") or {}
        f = e.get("file")
        if f and (ROOT / f).is_file():
            return f
    return None


# K-AST-262（IMGFIX 11-01，总调度 fredw-2b 派）：设定图与造型单品不一致时，参考板上的外层单品赢。
# 证据：ep01-S1/S2 林晚造型 A 一直没穿短款西装外套——sheets_chosen 现行设定图 lin_wan_lookA_s101（10-31 v1 候选，
# 画外套之前生成）上没有外套，图2 句却写“服装必须与图2完全一致”，图3 参考板又要外套，模型照图2 出（Q2 外套 0.048 / 0.068）。
# ASSETMASTER 单品一致性检查（K-AST-260，data/assetmaster/sheet_item_checks.json）只认 v2 那张；现行设定图没有检查记录 =
# 不能保证画了外层单品 → 外层单品（outfit 槽、穿在别的衣服外面的）在设定图句里明说“图N上没有画 X，X 以图M为准”。
SHEET_CHECKS = "data/assetmaster/sheet_item_checks.json"   # 相对仓库根（ROOT 运行时取，测试可替换）
SHEET_GAP_CLAUSE = "；图{n}上没有画{items}——{items}以{src}为准，穿在最外层"


def sheet_item_check(cid: str, look_id: str, file: str | None) -> dict | None:
    """这张设定图有没有通过单品一致性检查（K-AST-260）。记录带 file 时按文件认；只带 seed 的老记录只认 v2 那张（文件名含 _v2_s<seed>）"""
    if not file:
        return None
    try:
        d = json.loads((ROOT / SHEET_CHECKS).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    r = d.get(f"{cid}_look{look_id}")
    if not isinstance(r, dict) or r.get("verdict") != "pass":
        return None
    if r.get("file"):
        return r if r["file"] == file else None
    return r if r.get("seed") and f"_v2_s{r['seed']}" in Path(file).stem else None


def _outer_label(p) -> bool:
    if p.slot != "outfit" or p.extra:
        return False
    try:
        from ns_agent.gen_contract.postflight import outer_en
    except Exception:  # noqa: BLE001
        return "外套" in p.label
    return outer_en(p.label) is not None


def sheet_outer_gaps(project: str, cid: str, look_id: str, file: str | None) -> list[str]:
    """现行设定图没过单品一致性检查时，本造型的外层单品短名（这些可能没画在设定图上）；过了 → []"""
    if not cid or not look_id or sheet_item_check(cid, look_id, file):
        return []
    L = (load_looks(project).get(cid) or {}).get(look_id)
    return [_short(p.label) for p in (L.parts if L else []) if _outer_label(p)]


def _person_box(im, x0: int, x1: int):
    """设定图某一栏里非白底像素的外框（白底 > 235）"""
    import numpy as np
    a = np.asarray(im.convert("L").crop((x0, 0, x1, im.height)))
    mask = a < 235
    ys = np.where(mask.any(axis=1))[0]
    xs = np.where(mask.any(axis=0))[0]
    if len(ys) == 0:
        return (x0, 0, x1, im.height)
    return (x0 + int(xs[0]), int(ys[0]), x0 + int(xs[-1]) + 1, int(ys[-1]) + 1)


ZONE_SPAN = {  # 在正面全身栏人物外框里的纵向比例（0 = 头顶，1 = 脚底）
    "upper": (0.10, 0.50), "body": (0.10, 0.92), "lower": (0.40, 0.80), "waist": (0.30, 0.58),
    "neck": (0.08, 0.30), "feet": (0.86, 1.0), "hand": (0.38, 0.62),
}


HAND_TORSO_MAX = 0.35   # W5 a：手部参考里“实心列”（躯干 / 围裙 / 裙身）占宽度的上限，超过就不送这张参考


def _solid_cols(a, thr: float = 0.85):
    """灰度数组 → 每列非白底像素占比 ≥ thr 的布尔数组（躯干列整列实心；垂下的手只占手部带高度的一半左右）"""
    m = a < 235
    return m.mean(axis=0) >= thr


def _center_run(solid) -> tuple[int, int] | None:
    """包含中线那一列的连续实心列区间 [a, b)（= 躯干）；中线不实心 → None"""
    n = len(solid)
    c = n // 2
    if n == 0 or not solid[c]:
        return None
    a = c
    while a > 0 and solid[a - 1]:
        a -= 1
    b = c
    while b < n and solid[b]:
        b += 1
    return a, b


def _hand_pair(im, box):
    """W5 a（总调度 11-01，ep05-S3/S5）：手部参考只取两只手。旧裁法在人物外框里横向整条裁 0.38–0.62，
    中间大半是躯干 / 围裙（ch_a_lan_lookA_v2_s101_front_hand.png），把局部大特写拉回人像。
    新裁法：手部带里找“包含中线的连续实心列”= 躯干，取它左右两侧（找不到躯干就各取 0.30 外框宽），白底拼成一张“两只手”"""
    import numpy as np
    from PIL import Image
    bx0, by0, bx1, by1 = box
    w, h = bx1 - bx0, by1 - by0
    t, btm = ZONE_SPAN["hand"]
    y0, y1 = by0 + int(t * h), by0 + int(btm * h)
    band = np.asarray(im.convert("L").crop((bx0, y0, bx1, y1)))
    run = _center_run(_solid_cols(band))
    margin = max(2, int(0.04 * w))   # 围裙 / 躯干边缘是斜边，不算实心，多让 4% 外框宽
    left_end, right_start = (max(1, run[0] - margin), min(w - 1, run[1] + margin)) if run else (int(0.30 * w), w - int(0.30 * w))
    pad = int(0.02 * h)
    L = im.crop((max(0, bx0 - pad), y0, bx0 + left_end, y1))
    R = im.crop((bx0 + right_start, y0, min(im.width, bx1 + pad), y1))
    # AUDIT P2：躯干边缘是斜边，会在内侧留一条贯穿上下的深色细缝（和手臂不连通）→ 每半边只保留最大的连通块（手臂 + 手），
    # 其余非白像素涂白
    def _keep_main(img):
        import cv2
        arr = np.asarray(img).copy()
        m = (np.asarray(img.convert("L")) < 235).astype(np.uint8)
        n, lab, stats, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
        if n <= 2:
            return img
        main = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        arr[(lab != main) & (lab != 0)] = 255
        return Image.fromarray(arr)
    L, R = _keep_main(L), _keep_main(R)
    gap = max(8, int(0.04 * w))
    out = Image.new("RGB", (L.width + gap + R.width, y1 - y0), (255, 255, 255))
    out.paste(L, (0, 0))
    out.paste(R, (L.width + gap, 0))
    return out


def torso_share(path) -> float:
    """手部参考里“躯干”占宽度的比例（W5 a 的检查量）：包含中线的连续实心列宽 / 图宽；两只手拼图中线是白缝 → 0"""
    import numpy as np
    from PIL import Image
    with Image.open(ROOT / path if not Path(path).is_absolute() else path) as im:
        a = np.asarray(im.convert("L"))
    if not a.size:
        return 0.0
    run = _center_run(_solid_cols(a))
    return (run[1] - run[0]) / a.shape[1] if run else 0.0


def sheet_crop(project: str, sheet: str, panel: str, zone: str | None = None) -> str:
    """设定图裁切（half / front / side / back 栏；zone 给出时在该栏人物框内再裁该区域），缓存到 crop_dir"""
    from PIL import Image
    pc = project_cfg(project)
    lay = (_cfg().get("sheet_layout") or {})
    src = ROOT / sheet
    tag = f"{Path(sheet).stem}_{panel}" + (f"_{zone}" if zone else "") + ("2" if zone == "hand" else "")   # hand2：W5 重裁版
    out = ROOT / pc.get("crop_dir", "data/refcrops") / f"{tag}.png"
    if out.is_file() and out.stat().st_mtime >= src.stat().st_mtime:
        return rel(out)
    im = Image.open(src).convert("RGB")
    W, H = im.size
    nohead = panel.endswith("_nohead")
    a, b = lay.get(panel.replace("_nohead", ""), [0, 1])
    x0, x1 = int(a * W), int(b * W)
    if nohead:
        # 去头（项目方方向，总调度 23:5x 转、IMGGEN 提醒）：脸只由身份参考提供；设定图的脸偏娃娃感，带进槽位会和身份脸抢、
        # 把脸拉回动漫。全身栏去掉头顶往下身高的 15%（头 + 颈）；半身栏（特写栏）去掉上部 45%（头发顶到下巴）
        bx0, by0, bx1, by1 = _person_box(im, x0 + 4, x1 - 4)
        cut = by0 + int((by1 - by0) * 0.15) if panel.startswith(("front", "side", "back")) else int(H * 0.45)
        box = (x0, cut, x1, H)
    elif not zone:
        box = (x0, 0, x1, H)
    elif zone == "hand":
        out.parent.mkdir(parents=True, exist_ok=True)
        _hand_pair(im, _person_box(im, x0 + 4, x1 - 4)).save(out)
        return rel(out)
    else:
        bx0, by0, bx1, by1 = _person_box(im, x0 + 4, x1 - 4)
        h = by1 - by0
        t, btm = ZONE_SPAN.get(zone, (0, 1))
        y0, y1 = by0 + int(t * h), by0 + int(btm * h)
        pad = int(0.06 * h) if zone == "feet" else int(0.02 * h)
        box = (max(x0, bx0 - pad), max(0, y0 - pad), min(x1, bx1 + pad), min(H, y1 + pad))
    out.parent.mkdir(parents=True, exist_ok=True)
    im.crop(box).save(out)
    return rel(out)


FACE_OVERRIDES = ROOT / "data" / "looks" / "face_overrides.json"


def face_of(project: str, cid: str) -> str | None:
    """身份脸：资产中心“设为当前身份脸”（data/looks/face_overrides.json {project:{cid: 路径}}）> config faces 列表"""
    # 总调度 11-02 P0：解析层（face_overrides）也按 run 继承——子季自己设过身份脸用子季的，否则用父季的（L-086 的 hd_A_s202 在
    # series10_v1 的覆盖里；只合并 asset_refs.json faces 会退回 face_ref2va，01:24 服务器用错身份脸同一类错误）
    ov = overlay_value(FACE_OVERRIDES, project, cid)
    cands = ([ov] if isinstance(ov, str) else []) + list((project_cfg(project).get("faces") or {}).get(cid) or [])
    for f in cands:
        if (ROOT / f).is_file():
            return f
    return None


SCENE_ALIASES = ROOT / "config" / "scene_aliases.json"


def scene_dir(scene_id: str) -> tuple[str | None, str]:
    """剧本场景 id → assets/scenes/<目录>（config/scene_aliases.json，ARCH 总调度定的唯一对照表）；没登记 = 同名目录"""
    try:
        sc = (json.loads(SCENE_ALIASES.read_text(encoding="utf-8")).get("scenes") or {}).get(scene_id)
    except (OSError, ValueError):
        sc = None
    if sc is not None:
        return sc.get("asset_dir"), str(sc.get("status") or "")
    return scene_id, ""


def scene_ref(scene_id: str | None) -> str | None:
    """场景参考底图：assets/scenes/<目录>/ 下最新的一张（不进回收站目录）"""
    if not scene_id:
        return None
    sid, _ = scene_dir(scene_id)
    d = SCENES / sid if sid else None
    if d and d.is_dir():
        fs = sorted((p for p in d.rglob("*") if p.suffix.lower() in IMG_EXT and not {"trash", "_trash", "rejected"} & set(p.parts)),
                    key=lambda p: p.stat().st_mtime, reverse=True)
        if fs:
            return rel(fs[0])
    return None


# ---------------------------------------------------------------- 镜头 → 本镜造型
def _norm(t: str) -> str:
    return re.sub(r"[\s，,。、；;：:（）()]", "", t or "")


def match_look(looks: dict[str, Look], slots: dict | None, raw: str = "") -> tuple[str | None, float, list[str]]:
    """剧本造型行（服装 / 鞋）→ P1 造型 id。返回 (id, 匹配度, 偏离说明)。服装 + 鞋都对上 = 1.0"""
    slots = slots or {}
    cloth, shoe = _norm(slots.get("服装", "")), _norm(slots.get("鞋", ""))
    best = (None, 0.0, [])
    for lid, L in looks.items():
        pz = dict(seg.split("=", 1) for seg in L.zh.split("｜") if "=" in seg)
        lc, ls = _norm(pz.get("服装", "")), _norm(pz.get("鞋", ""))
        sc = (1.0 if cloth == lc else _jacc(cloth, lc)) * 0.7 + (1.0 if shoe == ls else _jacc(shoe, ls)) * 0.3
        dev = []
        if cloth != lc:
            dev.append(f"服装“{slots.get('服装', '')}”≠ 登记造型{lid}“{pz.get('服装', '')}”")
        if shoe != ls:
            dev.append(f"鞋“{slots.get('鞋', '')}”≠ 登记造型{lid}“{pz.get('鞋', '')}”")
        if sc > best[1]:
            best = (lid, sc, dev)
    if best[1] < 0.6:
        return None, best[1], best[2]
    return best


def _jacc(a: str, b: str) -> float:
    A, B = set(a), set(b)
    return len(A & B) / len(A | B) if A | B else 1.0


def look_rows(ep) -> list:
    return list(g(ep, "looks") or [])


def look_for(ep, name: str, index: int):
    """该镜生效的造型行：同一角色的造型行里 from_shot ≤ index 的最后一条（无 from_shot = 从第 1 镜起）"""
    rows = [r for r in look_rows(ep) if g(r, "character") == name]
    cur = None
    for r in sorted(rows, key=lambda r: int(g(r, "from_shot") or 0)):
        if int(g(r, "from_shot") or 0) <= index:
            cur = r
    return cur


def shot_overrides(project: str) -> tuple[dict, dict]:
    """画布“切换本镜参考”写的逐镜覆盖（DATA_MAP §6-1，REFLOCK 11-01）：shot_looks.json
    overrides {sid: {cid: {"look": X, "parts": {slot: item_id}}}}、scene_overrides {sid: 底图（assets/scenes 下相对路径）| "none"}"""
    p = ROOT / (project_cfg(project).get("shot_looks_file") or "_none_")
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}, {}
    return d.get("overrides") or {}, d.get("scene_overrides") or {}


def registry_looks(project: str) -> dict:
    p = ROOT / (project_cfg(project).get("shot_looks_file") or "_none_")
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("shots", {})
    except (OSError, ValueError):
        return {}


# ---------------------------------------------------------------- 解析一镜
@dataclass
class Ref:
    role: str                 # face | sheet | item | scene
    character: str | None
    file: str | None
    label: str
    prio: float
    zone: str | None = None
    source: str = ""          # identity | sheet | sheet_crop | wardrobe | scene
    item_id: str | None = None
    look_id: str | None = None
    focus: bool = False
    has_face: bool = False    # 图里有人脸（脸参考 / 设定图半身、全身栏）→ 不得与另一张脸同槽
    note: str = ""


@dataclass
class ShotRefs:
    shot_id: str
    project: str
    size: str | None
    subject: str | None       # face | part | object | None
    zones: list[str]
    primary: str | None
    characters: list[dict]
    refs: list[Ref]
    missing: list[dict]       # 阻断项（资产缺图 / 造型未登记 / 脸缺）
    warnings: list[dict]
    scene_id: str | None = None
    two_person: str = ""
    mirror: bool = False      # 原文写了镜子 / 倒影（同一角色允许出现第二张脸，postflight Q1）

    @property
    def blocked(self) -> bool:
        return bool(self.missing)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["blocked"] = self.blocked
        return d


def visible_zones(img: str, kept_triggers=None) -> tuple[str | None, str | None, set[str]]:
    size = FR.size_of(img)
    subject = FR.closeup_subject(img, size)
    if subject == "part" or (size in FR.CLOSE and FR.lower_focus(img, kept_triggers) and subject != "face"):
        name = FR.part_name(img)
        # W5 c：局部范围扩大为“手与肩颈”时只扩大文字（构图句 / 发色句），参考槽仍只送手部单品——
        # 试编译 ep05-S3：并上 neck/upper 会多送内衣平铺图 + 两张造型参考板，躯干参考正是把局部拉成人像的原因之一
        for words, zs in PART_ZONES:
            if any(w in name for w in words):
                return size, "part", set(zs)
        return size, "part", {"hand"}
    if subject == "object":
        return size, subject, set()
    if size is None:
        return None, subject, set(ALL_ZONES)
    return size, subject, set(ZONES_BY_SIZE.get(size, ALL_ZONES))


BACK_WORDS = ("背影", "背面", "背身", "背对", "后背", "背部")


def back_part(shot, name: str) -> bool:
    """cast 里这个人是局部、部位写的是背影 / 背面（剧本原文）"""
    for c in g(shot, "cast") or []:
        if g(c, "name") == name and g(c, "presence") == "局部":
            return any(w in str(g(c, "part") or "") for w in BACK_WORDS)
    return False


def back_outer_items(project: str, cid: str, lid: str | None) -> list[str]:
    """背影局部人物背面看得到的外层服装（本镜造型里的外层单品短名，造型登记原文）"""
    L = (load_looks(project).get(cid) or {}).get(lid) if lid else None
    return [_short(p.label) for p in (L.parts if L else []) if _outer_label(p)]


def look_id_of(project: str, ep, shot, name: str) -> str | None:
    """本镜某人的造型 id，与 resolve_shot 同一顺序：排期（整集）> 画布逐镜 > 系统登记 > 剧本造型行"""
    cid = NAME_ID.get(name, name)
    n_ep = int(g(ep, "number") or g(shot, "episode") or 0)
    sid = f"ep{n_ep:02d}-S{int(g(shot, 'index'))}"
    lid = episode_look_override(project, cid, n_ep)
    if not lid:
        lid = ((shot_overrides(project)[0].get(sid) or {}).get(cid) or {}).get("look")
    if not lid:
        r = registry_looks(project).get(sid, {}).get(cid)
        lid = r.get("look") if isinstance(r, dict) else r
    if not lid:
        row = look_for(ep, name, int(g(shot, "index")))
        if row is not None:
            lid = match_look(load_looks(project).get(cid) or {}, g(row, "slots"), g(row, "raw") or "")[0]
    return lid


def back_outer_clause(project: str | None, ep, shot, name: str) -> str:
    """K-REN-705 c（IMGFIX 11-02，总调度：背影局部人物要补外套）：cast 局部且部位是背影 → “背面也穿着<外层单品>”（造型登记原文）"""
    if not project or not project_cfg(project) or not back_part(shot, name):
        return ""
    items = back_outer_items(project, NAME_ID.get(name, name), look_id_of(project, ep, shot, name))
    return ("背面也穿着" + "、".join(items)) if items else ""


def cast_on_screen(shot) -> list[tuple[str, str]]:
    """[(名字, presence)]：在画 / 局部（画外、声音不算）"""
    out = []
    for c in g(shot, "cast") or []:
        pr = g(c, "presence") or ""
        if pr in ("在画", "局部"):
            out.append((g(c, "name"), pr))
    return out


# 总调度 11-01 决定 1(a)（ep03-S6）：cast 写“局部”但 img 原文写到了这个人的脸 / 头发 → 当作脸可见：挂身份脸、进 Q1。
# 原文按人切段：从角色名出现处到下一个别的角色名（或句末“；。”）为止，段里出现脸 / 头发词才算（K-AST-236）
FACE_HAIR_WORDS = ("脸", "五官", "眉", "眼", "鼻", "嘴", "唇", "下巴", "面容", "面孔", "头发", "发型", "发丝", "短发", "长发",
                   "黑发", "白发", "卷发", "直发", "刘海", "马尾", "寸头", "鬓", "侧颜")
FACE_STOP = ("她", "他", "其")
FACE_PLACE = ("公寓", "家", "的家", "办公室", "的公寓", "的办公室", "的车")
FACE_CLAUSES = 3          # 代词之后写的是另一个人（“顾沉的手掌贴在她耳侧的发上”）


MIRROR_RE = re.compile(r"镜中|镜子|镜里|镜面墙|全身镜|镜前|倒影|映出|映着|镜像")   # 不用单字“镜”（镜头 / 镜面漆皮会误中）


def face_described(name: str, img: str, others: list[str] | tuple = ()) -> bool:
    """img 原文里写到 name 的脸 / 头发（在 name 出现处到下一个别的角色名或句末之间）"""
    if not name or name not in (img or ""):
        return False
    stops = [o for o in others if o and o != name] + list(FACE_STOP)
    for m in re.finditer(re.escape(name), img):
        seg = img[m.end():]
        cut = len(seg)
        for o in stops:
            i = seg.find(o)
            if 0 <= i < cut:
                cut = i
        for ch in ("；", "。", chr(10)):
            i = seg.find(ch)
            if 0 <= i < cut:
                cut = i
        if seg.startswith(FACE_PLACE):                     # “顾沉公寓 …”：名字当地点用，不是在写这个人
            continue
        near = "，".join(seg[:cut].split("，")[:FACE_CLAUSES])   # 只看名字后面紧跟的几句（句尾的写实套话“眼睛为真实人眼大小”不算）
        if any(w in near for w in FACE_HAIR_WORDS):
            return True
    return False


# K-REN-708（IMGFIX 11-02 P0，ep02-S10：cast 写“林晚（局部｜双手）”，正文“特写……视线落在汤面，嘴唇轻抿”→ 判成不露脸、
# 没挂身份脸、还写了“林晚只露出双手，不露脸”，模型自己编了一张脸）：露脸推断不只看名字后 3 句
FACE_VIS_WORDS = ("脸", "五官", "眉", "眼", "鼻", "嘴", "唇", "下巴", "面容", "面孔", "视线", "目光", "表情", "神情", "睫", "侧颜", "抬眼", "垂眼")
FACE_VIS_SIZES = ("极近特写", "大特写", "特写", "近景", "中近景")


def partial_face_visible(name: str, img: str, cast_names: list[str] | tuple = (), size: str | None = None,
                         subject: str | None = None) -> bool:
    """cast 写“局部”的人其实露脸吗：① 名字后写到脸 / 头发（face_described，多人镜按人切段）；② 本镜只有这一个人：
    正文出现眼睛 / 视线 / 嘴唇 / 表情 / 脸等词，或景别是特写 / 近景 / 中近景且不是局部 / 物件特写 → 露脸"""
    if face_described(name, img, cast_names):
        return True
    others = [n for n in cast_names if n and n != name]
    if others:
        return False
    body = (img or "").replace("眼睛为真实人眼大小", "")
    if any(w in body for w in FACE_VIS_WORDS):
        return True
    if size is None:
        size, subject, _z = visible_zones(img)
    return size in FACE_VIS_SIZES and subject not in ("part", "object")


def resolve_shot(project: str, ep, shot, *, kept_triggers=None, looks=None, two_person: str | None = None) -> ShotRefs:
    """一镜每个在画角色必须锁定的参考图（未排槽位）。ep / shot：导入器对象或 script_v2.json 的 dict"""
    n_ep = int(g(ep, "number") or g(shot, "episode") or 0)
    idx = int(g(shot, "index"))
    sid = f"ep{n_ep:02d}-S{idx}"
    img = g(shot, "img_prompt") or ""
    size, subject, zones = visible_zones(img, kept_triggers)
    looks = looks if looks is not None else load_looks(project)
    reg = registry_looks(project).get(sid, {})
    shot_ovs, scene_ovs = shot_overrides(project)
    on = cast_on_screen(shot)
    refs: list[Ref] = []
    missing: list[dict] = []
    warns: list[dict] = []
    chars = []
    face_visible = subject not in ("part", "object")
    primary = next((NAME_ID.get(n, n) for n, pr in on if pr == "在画"), None) or (NAME_ID.get(on[0][0]) if on else None)
    panel = SHEET_PANEL_BY_SIZE.get(size or "", "front")
    for k, (name, pr) in enumerate(on):
        cid = NAME_ID.get(name, name)
        is_primary = cid == primary
        base = 0 if is_primary else 10
        cl = looks.get(cid) or {}
        # 本镜造型：系统登记（shot_looks.json）> 剧本造型行匹配
        ov = ((shot_ovs.get(sid) or {}).get(cid) or {})
        lid = episode_look_override(project, cid, n_ep)          # 资产中心排期（整集）> 画布逐镜切换 > 逐镜系统登记 > 剧本造型行
        how = "hub_episode" if lid else ""
        if not lid and ov.get("look"):
            lid, how = ov["look"], "shot_override"
        if not lid:
            lid = (reg.get(cid) or {}).get("look") if isinstance(reg.get(cid), dict) else reg.get(cid)
            how = "registry" if lid else ""
        if not lid:
            row = look_for(ep, name, idx)
            if row is not None:
                lid, score, dev = match_look(cl, g(row, "slots"), g(row, "raw") or "")
                how = f"script_match {score:.2f}"
                if lid and dev:
                    warns.append({"character": name, "kind": "造型偏离", "detail": "；".join(dev), "look": lid})
        partial_face = pr == "局部" and partial_face_visible(name, img, [n for n, _ in on], size, subject)
        info = {"character": cid, "name": name, "presence": pr, "primary": is_primary, "look": lid, "look_how": how}
        if partial_face:
            info["face_described"] = True
            warns.append({"character": name, "kind": "局部但写到脸", "detail": f"{name} 在 cast 里是“局部”，但正文写到了脸 / 视线或景别露脸：按脸可见挂身份脸、进 Q1（K-AST-236 / K-REN-708）——cast 应改成“在画”（写作格式问题）"})
        chars.append(info)
        # 身份脸（I2）
        # 局部 / 物件特写不挂身份脸（挂了模型就会画出脸，总调度 11-01）；原文写到这个人的脸（face_described）例外
        # K-AST-263（IMGFIX 11-02）：局部且原文没写脸的人不挂身份脸——主角也一样（ep05-S3 林晚“只露出肩头”挂了脸，模型画出了脸）
        if (face_visible or partial_face) and (pr == "在画" or partial_face) and (is_primary or (two_person or _cfg().get("two_person")) == "both_faces"):
            f = face_of(project, cid)
            if f:
                refs.append(Ref("face", cid, f, f"{name}的脸部参考", 0 if is_primary else 0.5, "face", "identity", has_face=True))
            else:
                missing.append({"character": name, "kind": "身份脸缺图", "detail": f"{name} 没有登记身份脸部参考"})
        if not lid or lid not in cl:
            missing.append({"character": name, "kind": "造型未登记",
                            "detail": f"{name} 本镜造型对不上 P1 登记（{how or '剧本没有造型行'}）"})
            continue
        L = cl[lid]
        sheet = sheet_of(project, cid, lid)
        if not sheet:
            missing.append({"character": name, "kind": "资产缺图", "detail": f"{name} 造型{lid} 没有设定图"})
        part_shot = subject == "part"
        if sheet and not part_shot and (zones - {"face"}):
            sp = (panel if is_primary else "front") + "_nohead"
            # IMGFIX 11-02（总调度：背影局部人物要补外套）：局部且 cast 部位写背影 / 背面 → 送设定图背面栏裁切
            if pr == "局部" and back_part(shot, name):
                sp = "back_nohead"
            refs.append(Ref("sheet", cid, sheet_crop(project, sheet, sp),
                            f"{name}本镜造型{lid}的设定图（{'背面' if sp.startswith('back') else '半身' if sp.startswith('half') else '正面全身'}，去头）",
                            base + 1, None, "sheet", look_id=lid, has_face=False))
        # 景别可见的单品（I4）
        povs = {k: v for k, v in (ov.get("parts") or {}).items() if v}
        if povs:                                                  # 画布逐镜换单件：同槽第一件换成选中的衣橱单品
            parts = [LookPart(**{**p.__dict__}) for p in L.parts]
            for slot, iid in povs.items():
                hit = next((p for p in parts if p.slot == slot and not p.extra), None)
                if hit:
                    hit.item_id, hit.force_missing = iid, False
                else:
                    nm = item_name(iid)
                    parts.append(LookPart(slot if slot in SLOT_LABEL else "accessory", nm, zone_of(slot, nm), iid))
            L = Look(L.char, L.look_id, L.zh, L.en, L.use, parts)
        vis = [p for p in L.parts if p.zone in zones and p.slot != "marker" and part_active(p, n_ep, img)]
        if any(p.extra and p.slot == "shoes" for p in vis):     # 本镜换鞋（look_extras 备选鞋，正文写到）：登记的原鞋不挂
            vis = [p for p in vis if not (p.slot == "shoes" and not p.extra)]
        for p in sorted(vis, key=lambda p: ZONE_ORDER.get(p.zone, 9)):
            focus = part_shot and p.zone in zones
            f, src = None, ""
            if p.force_missing and not (p.item_id and item_image(p.item_id)):
                lab_ = _short(p.label)
                if p.extra or lab_ in img:
                    missing.append({"character": name, "kind": "资产缺图",
                                    "detail": f"{name} 造型{lid} 的{SLOT_LABEL[p.slot]}“{lab_}”登记为缺图（衣橱和设定图里都没有），本镜正文写到了"})
                else:
                    warns.append({"character": name, "kind": "登记缺图未写", "item": lab_,
                                  "detail": f"{name} 造型{lid} 的“{lab_}”登记为缺图；本镜正文没写到，不阻断（画面按设定图 / 正文走）"})
                continue
            if p.item_id:
                f = item_image(p.item_id)
                src = "wardrobe" if f else ""
                if not f:
                    warns.append({"character": name, "kind": "单品图缺失", "detail": f"{p.item_id} 映射了但没有图片"})
            need_own = bool(f) or p.zone == "feet" or focus       # 鞋可见 / 局部特写：必须有单独的单品图
            pnl = None
            if not f and need_own and sheet:
                pnl = "side" if p.zone == "feet" else ("half_nohead" if p.zone == "neck" else "front")
                f, src = sheet_crop(project, sheet, pnl, p.zone if pnl != "half_nohead" else None), "sheet_crop"
                if p.zone == "hand" and f and torso_share(f) > HAND_TORSO_MAX:
                    # W5 a：重裁后手部参考里仍有大块躯干 → 不送（送了模型会画成半身人像），正文照写单品
                    warns.append({"character": name, "kind": "手部参考含躯干", "item": _short(p.label),
                                  "detail": f"{f} 实心列占比 {torso_share(f):.2f} > {HAND_TORSO_MAX}：不作参考（建议补单品图）"})
                    f = None
                    continue
            if not f and not sheet:
                missing.append({"character": name, "kind": "资产缺图", "detail": f"{name} 造型{lid} 的{SLOT_LABEL[p.slot]}“{_short(p.label)}”没有图"})
                continue
            if src == "sheet_crop" or (not f and sheet):
                warns.append({"character": name, "kind": "仅设定图", "item": _short(p.label),
                              "detail": f"{name} 造型{lid} {SLOT_LABEL[p.slot]}“{_short(p.label)}”衣橱里没有产品图，用设定图{'裁切' if f else ''}代替（建议补单品图）"})
            if not f:
                continue                                              # 设定图已覆盖（同槽），不单独占位
            pr_item = (base - 1 if focus else base + 2 + ZONE_ORDER.get(p.zone, 9) * 0.1)
            if p.zone == "feet" and not part_shot:
                pr_item = base + 2                                    # 鞋可见：单品里最先
            lab = item_name(p.item_id) if src == "wardrobe" else _short(p.label)
            refs.append(Ref("item", cid, f, f"{SLOT_LABEL[p.slot]}：{lab}", pr_item, p.zone, src, p.item_id, lid, focus))
    sid_scene = g(shot, "scene_id")
    sov = scene_ovs.get(sid)
    if sov == "none":                                             # 画布选了“不用底图”
        sid_scene = None
    if sid_scene and subject != "part":
        sr = (f"assets/scenes/{sov}" if sov and (SCENES / sov).is_file() else None) or scene_ref(sid_scene)
        sdir, sst = scene_dir(sid_scene)
        if sr:
            refs.append(Ref("scene", None, sr, f"场景 {sid_scene}", 30, None, "scene"))
            if sst:
                warns.append({"character": None, "kind": "场景资产状态", "detail": f"{sid_scene} → assets/scenes/{sdir}：{sst}"})
        else:
            missing.append({"character": None, "kind": "场景缺图",
                            "detail": f"场景 {sid_scene} 没有参考底图（config/scene_aliases.json → {sdir or '未登记目录'}）"})
    refs.sort(key=lambda r: r.prio)
    return ShotRefs(sid, project, size, subject, sorted(zones), primary, chars, refs, missing, warns, sid_scene,
                    two_person or _cfg().get("two_person") or "primary_face_only", mirror=bool(MIRROR_RE.search(img)))


# ---------------------------------------------------------------- 槽位规划 + 参考板
@dataclass
class Slot:
    index: int
    kind: str                 # face | sheet | item | board | scene
    file: str
    character: str | None
    labels: list[str]
    members: list[dict]
    line: str = ""
    faces: int = 0


# 槽位不够、改走文字的固定说明（frame_job.with_note 放进 frame_v9 正文）。改这句或加新的固定句 → 同一次改动里
# 让 ns_api.unified_stale.match_target 认得出（它用 TEXT_FALLBACK_RE），否则刚出的图会被误标“编译器升级”（K-REN-136）
TEXT_FALLBACK_NOTE = "{name}的服装、鞋、饰品按文字描述（参考槽不足）。"
TEXT_FALLBACK_RE = re.compile(r"[^，。、；]{1,12}的服装、鞋、饰品按文字描述（参考槽不足）")
# 外层单品说明（K-REN-101，frame_job.outer_items_note 生成；PRODUCER 11-01 加）：本镜景别可见、正文没写到的造型单品。
# 与上面同一规矩：改句式 = 同一次改动里改这里的 RE（DATAALIGN 11-01 把两句并到这一处，唯一来源）
OUTER_ITEMS_NOTE = "{name}本镜造型{lid}要穿全：{items}（造型设定图上有，正文没写也必须入画）"
OUTER_ITEMS_RE = re.compile(r"[^，。、；]{1,12}本镜造型[A-Za-z0-9]{0,3}要穿全：[^（。]{1,120}（造型设定图上有，正文没写也必须入画）")
# frame_v9 正文里系统插的全部固定说明，按 compile_frame 拼接顺序（槽位不足在前、外层单品在后）——
# ns_api.unified_stale.match_target 按这个顺序认出来再用 frame_job.with_note 放回去比对
# 视线说明（ACTING 11-01，项目方 R11-2“演员的眼睛不要看镜头”、R11-8“每个镜头第一帧演员都看着镜头”）：出图正文没写视线时，
# frame_job.eyeline_note 用本镜第一拍的 视线= 补一句正向落点（Qwen Image cfg 1，负面词不生效，只能写正向；docs/acting/PERFORMANCE_RULES.md E1/E6）
EYELINE_NOTE = "{name}的视线落在{target}上（看画内的人或物，眼神有落点）"
EYELINE_RE = re.compile(r"[^，。、；]{1,12}的视线落在[^（。]{1,40}上（看画内的人或物，眼神有落点）")
# IMGFIX r5（总调度 fredw-2b 11-02）：外层单品的登记描述（衣橱 description，例：短款西装外套“两只袖子都是深灰西装袖，露米白衬衫袖口”）
# 作为技术契约句补进出图正文（正面、背影都适用）；句式唯一来源在这里，进 TEXT_NOTE_RES（unified_stale 自动认）
GARMENT_DETAIL_NOTE = "{name}的{label}：{desc}"
# 描述里不放逗号（逗号是正文分句符，识别式靠它定界）；袖口写在括号里
GARMENT_DETAIL_RE = re.compile(r"[^，。、；：①-⑩]{1,12}的[^，。、；：①-⑩]{0,12}(?:外套|西装|风衣|大衣|皮衣|夹克|围裙|开衫|披肩)：[^，。；：]{1,60}")
TEXT_NOTE_RES = (TEXT_FALLBACK_RE, OUTER_ITEMS_RE, EYELINE_RE, GARMENT_DETAIL_RE)


def garment_details(project: str, cid: str, lid: str | None) -> list[tuple[str, str]]:
    """本造型外层单品里，衣橱登记了 description 的 → [(短名, description)]"""
    L = (load_looks(project).get(cid) or {}).get(lid) if lid else None
    out = []
    for p in (L.parts if L else []):
        if not _outer_label(p) or not p.item_id:
            continue
        desc = ((wardrobe().get(p.item_id) or {}).get("description") or "").strip().rstrip("。")
        if desc:
            out.append((_short(p.label), desc))
    return out


@dataclass
class SlotPlan:
    shot_id: str
    model: str
    capacity: int
    slots: list[Slot]
    dropped: list[dict]
    prompt_prefix: str
    blocked: bool
    missing: list[dict]
    warnings: list[dict]
    prompt_note: str = ""          # 槽位不够改走文字的说明；放在正文末尾（风格后缀之前），不挡在景别首句前面（K-REN-101）

    @property
    def files(self) -> list[str]:
        return [s.file for s in self.slots]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["files"] = self.files
        return d


def _pron(project: str, cid: str | None) -> str:
    return "她" if cid in (project_cfg(project).get("female") or []) else "他"


def make_board(project: str, tiles: list[tuple[str, str]]) -> str:
    """参考板：固定网格（≤2 横排 / ≤4 2×2 / ≤6 3×2），每格白底等比缩放 + 底部编号标注。按内容哈希缓存"""
    from PIL import Image, ImageDraw, ImageFont
    bc = _cfg().get("board") or {}
    T, LH = int(bc.get("tile", 512)), int(bc.get("label_h", 60))
    key = hashlib.sha1(json.dumps([[f, l, sha_file(ROOT / f)] for f, l in tiles], ensure_ascii=False).encode()).hexdigest()[:12]
    out = ROOT / project_cfg(project).get("board_dir", "data/refboards") / f"board_{key}.png"
    if out.is_file():
        return rel(out)
    n = len(tiles)
    cols = n if n <= 2 else (2 if n <= 4 else 3)
    rows = (n + cols - 1) // cols
    W, H = cols * T, rows * (T + LH)
    board = Image.new("RGB", (W, H), "white")
    font = None
    for fp in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf", "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"):
        try:
            font = ImageFont.truetype(fp, 26)
            break
        except OSError:
            continue
    font = font or ImageFont.load_default()
    d = ImageDraw.Draw(board)
    for i, (f, label) in enumerate(tiles):
        im = Image.open(ROOT / f).convert("RGB")
        im.thumbnail((T - 12, T - 12))
        x, y = (i % cols) * T, (i // cols) * (T + LH)
        board.paste(im, (x + (T - im.width) // 2, y + (T - im.height) // 2))
        d.rectangle([x, y, x + T - 1, y + T + LH - 1], outline=(200, 200, 200), width=2)
        d.text((x + 10, y + T + 12), f"{CIRCLED[i]} {label}"[:22], fill=(20, 20, 20), font=font)
    out.parent.mkdir(parents=True, exist_ok=True)
    board.save(out)
    return rel(out)


def _line(project: str, s: Slot) -> str:
    name = ID_NAME.get(s.character or "", s.character or "")
    pron = _pron(project, s.character)
    n = s.index
    if s.kind == "faceboard":
        parts = "".join(f"{CIRCLED[i]}{lab}" for i, lab in enumerate(s.labels))
        return f"图{n}是脸部参考板：{parts}——每一格是对应人物的脸（只取脸和发型），每个人的长相必须与自己那一格一致。"
    if s.kind == "face":
        return f"图{n}是{name}的脸部参考（只取脸和发型）。"
    if s.kind == "scene":
        return f"图{n}是本镜场景参考（只取空间、陈设与光线，不取人物）。"
    m = s.members[0]
    if s.kind == "sheet":
        if m.get("secondary"):
            return f"图{n}是{name}的造型设定图（已去头，只取{name}的服装、鞋、饰品与体型，背景与姿势不取）。"
        return (f"图{n}是{name}本镜造型{m.get('look_id')}的设定图（已去头，只看服装）——{pron}这一镜的服装、鞋、饰品必须与图{n}完全一致"
                f"（款式、颜色、材质、细节），背景与姿势不取。")
    if s.kind == "item":
        return f"图{n}是{name}这一镜穿戴的{m['label']}，必须与图{n}完全一致（款式、颜色、材质、细节）。"
    parts = "".join(f"{CIRCLED[i]}{lab}" for i, lab in enumerate(s.labels))
    return (f"图{n}是{name}本镜的参考板：{parts}——{pron}这一镜穿戴的就是板上这些，"
            f"每一件都必须与板上对应格完全一致（款式、颜色、材质、细节）。")


def _apply_sheet_gaps(project: str, slots: list) -> None:
    """K-AST-262：主角设定图（单张 sheet 槽，非 secondary）没过单品一致性检查 → 外层单品让位给参考板 / 单品图（同一角色、标签里有它的槽）"""
    for s in slots:
        if s.kind != "sheet" or not s.members or s.members[0].get("secondary"):
            continue
        m = s.members[0]
        lid = m.get("look_id")
        gaps = sheet_outer_gaps(project, s.character, lid, sheet_of(project, s.character, lid) or s.file)
        if not gaps:
            continue
        by_src: dict[str, list[str]] = {}
        for it in gaps:
            o = next((x for x in slots if x is not s and x.character == s.character and x.kind in ("board", "item")
                      and any(it in str(lab) for lab in x.labels)), None)
            by_src.setdefault(f"图{o.index}" if o else "文字", []).append(it)
        add = "".join(SHEET_GAP_CLAUSE.format(n=s.index, items="、".join(v), src=k) for k, v in by_src.items())
        s.line = s.line.rstrip("。") + add + "。"


def plan_slots(sr: ShotRefs, model: str = "qwen_image_2.1", capacity: int | None = None) -> SlotPlan:
    """按模型槽位排参考图（I9）。规则：脸不进参考板；一块板只放同一角色、最多一张带脸的图（设定图）；
    超出时先合并同角色低优先级项为参考板，仍超出才丢（场景 → 第二人单品 → 第二人设定图），丢弃项记 dropped（走文字）"""
    N = capacity or model_slots(model)
    max_tiles = int((_cfg().get("board") or {}).get("max_tiles", 6))
    groups: list[list[Ref]] = [[r] for r in sr.refs]           # 已按 prio 排好
    # K-AST-263（IMGFIX 11-02）：身份脸不丢——露脸的人 ≥3 且槽位不够时，全部身份脸拼成一张脸板（每格标名字），占第 1 槽
    fg = [g0 for g0 in groups if g0[0].role == "face"]
    if len(fg) >= 3 and len(groups) > N:
        groups = [[r for g0 in fg for r in g0]] + [g0 for g0 in groups if g0[0].role != "face"]
    dropped: list[dict] = []

    def mergeable(a: list[Ref], b: list[Ref]) -> bool:
        if any(r.role in ("face", "scene") for r in a + b):
            return False
        if {r.character for r in a + b} != {a[0].character}:
            return False
        return sum(r.has_face for r in a + b) <= 1 and len(a) + len(b) <= max_tiles

    while len(groups) > N:
        sc = [k for k, gr in enumerate(groups) if gr[0].role == "scene"]
        if sc:                                                   # 优先级最低：场景先让位（走文字 + 【场景】段）
            for r in groups[sc[-1]]:
                dropped.append({"file": r.file, "label": r.label, "character": None, "role": "scene",
                                "why": f"{model} 只有 {N} 个参考槽，场景让位给人物资产，走文字"})
            del groups[sc[-1]]
            continue
        merged = False
        for i in range(len(groups) - 1, 0, -1):                 # 从低优先级往前找能合并的相邻组
            for j in range(i - 1, -1, -1):
                if mergeable(groups[j], groups[i]):
                    groups[j] = groups[j] + groups[i]
                    del groups[i]
                    merged = True
                    break
            if merged:
                break
        if merged:
            continue
        # 合并不了 → 丢最低优先级（脸和主体角色永不丢）
        cand = [k for k, gr in enumerate(groups) if not any(r.role == "face" for r in gr)
                and not any(r.character == sr.primary and r.role != "scene" for r in gr)]
        if not cand:
            break
        k = max(cand, key=lambda k: min(r.prio for r in groups[k]))
        for r in groups[k]:
            dropped.append({"file": r.file, "label": r.label, "character": r.character, "role": r.role,
                            "why": f"{model} 只有 {N} 个参考槽，改走文字"})
        del groups[k]
    slots: list[Slot] = []
    for n, gr in enumerate(groups, 1):
        r0 = gr[0]
        members = [{"file": r.file, "label": r.label, "role": r.role, "source": r.source, "item_id": r.item_id,
                    "look_id": r.look_id, "zone": r.zone, "focus": r.focus,
                    "secondary": bool(r.character and r.character != sr.primary)} for r in gr]
        if len(gr) == 1:
            s = Slot(n, r0.role, r0.file, r0.character, [r0.label], members, faces=int(r0.has_face))
        elif all(r.role == "face" for r in gr):
            names = [ID_NAME.get(r.character or "", r.character or "") for r in gr]
            s = Slot(n, "faceboard", make_board(sr.project, [(r.file, nm) for r, nm in zip(gr, names)]), r0.character,
                     names, members, faces=len(gr))
        else:
            labels = [("造型" + (r.look_id or "") + "设定图") if r.role == "sheet" else r.label for r in gr]
            s = Slot(n, "board", make_board(sr.project, [(r.file, lab) for r, lab in zip(gr, labels)]), r0.character,
                     labels, members, faces=sum(r.has_face for r in gr))
        s.line = _line(sr.project, s)
        slots.append(s)
    _apply_sheet_gaps(sr.project, slots)
    prefix = "".join(s.line for s in slots)
    if dropped:                                          # 槽位不够、改走文字的人物资产：每人一句
        names = []
        for d in dropped:
            n = ID_NAME.get(d["character"] or "", "")
            if n and n not in names:
                names.append(n)
        note = "".join(TEXT_FALLBACK_NOTE.format(name=n) for n in names)
    else:
        note = ""
    return SlotPlan(sr.shot_id, model, N, slots, dropped, prefix, sr.blocked, sr.missing, sr.warnings, prompt_note=note)


# K-REN-704（IMGFIX 11-01，总调度 fredw-2b 派；项目方原话“所有图片不要看镜头，不要看镜头！”）：单人镜首帧的头部朝向句。
# 证据（data/ab/imgfix/takes.jsonl，同镜同 seed 只改一句）：现行 / “平视”改“平视机位” / “图1 只取身份不取视线”三种写法
# ep01-S1、S2 都正对镜头；只有“四分之三侧脸、脸转向<落点>一侧”这句让脸转开。图1 是正脸直视的身份脸（L-086 不改），
# 正文里“视线落在屏幕下方”压不住（Qwen 连头部朝向一起抄参考）。句子放在提示词最前面（参考说明之前）；落点只取剧本原文。
# ⤴ 21:3x：再加视线正向落点句在前（F2acc：ep01-S1 s20261301 只有朝向句时仍正对镜头，加上后 S1/S2 4/4 都转开；S3/S6 见 data/ab/imgfix）
SINGLE_TURN_LEAD = "{name}的眼睛看着{target}，头和视线都朝向{target}，眼睛不看镜头。{name}四分之三侧脸，脸转向{target}一侧，脸和身体都不正对镜头。"
SINGLE_TURN_RE = re.compile(r"[^，。、；]{1,12}的眼睛看着[^，。]{1,40}，头和视线都朝向[^，。]{1,40}，眼睛不看镜头。"
                            r"[^，。、；]{1,12}四分之三侧脸，脸转向[^。]{1,40}一侧，脸和身体都不正对镜头。")
_GAZE_TARGET_RE = re.compile(r"视线(?:落在|朝|看向|停在|转向|移向|投向)([^，。；（(]{1,20})")


def gaze_target(shot) -> str:
    """单人镜视线落点（剧本原文）：img 行“视线落在 / 朝 …”→ 第一拍 视线= / motion 行 → “画面里的人或物”"""
    m = _GAZE_TARGET_RE.search(g(shot, "img_prompt") or "")
    t = (m.group(1).strip() if m else "")
    if not t or "镜头" in t:
        from ns_agent import frame_job as _FJ
        t = _FJ.first_beat_gaze(shot)
    t = (t or "画面里的人或物").strip()
    return t[:-1] if t.endswith("上") and len(t) > 1 else t


def single_turn_line(sr: ShotRefs, shot) -> str:
    """单人在画、主体是人（不是局部 / 物件特写）、有身份脸槽 → 朝向句；否则空"""
    if sr.subject in ("part", "object"):
        return ""
    img = g(shot, "img_prompt") or ""
    on = [c for c in sr.characters or [] if c.get("presence", "在画") == "在画" or c.get("face_described")]   # K-REN-708：局部但露脸的也算
    if len(on) != 1:
        return ""
    name = on[0].get("name") or ID_NAME.get(on[0].get("character") or "", "")
    # 剧本写了这个人背对镜头 → 不加。只看这个人自己的分句（名字后到下一个别的角色名 / 句号）：ep02-S4 背影是局部的林晚，
    # 顾沉照样要朝向句（IMGFIX 11-02：原先整段找“背影”，顾沉 s20261304 没加句、正对镜头）
    others = [c.get("name") for c in sr.characters or [] if c.get("name") and c.get("name") != name]
    for m in re.finditer(re.escape(name or "__none__"), img):
        seg = img[m.end():]
        cut = min([i for i in (seg.find(o) for o in others) if i >= 0] + [i for i in (seg.find("。"), seg.find("；")) if i >= 0] + [len(seg)])
        if any(w in seg[:cut] for w in ("背影", "背对", "背身")):
            return ""
    return SINGLE_TURN_LEAD.format(name=name, target=gaze_target(shot)[:30]) if name else ""


def _apply_single_turn(plan: SlotPlan, line: str) -> None:
    if not line:
        return
    if not any(s.kind == "face" for s in plan.slots):
        return
    # 放在提示词最前面（参考说明之前）：验收时放在身份脸句之后 ep01-S1 仍正对镜头（data/ab/imgfix ACC s20261201），
    # 放最前面 S1 / S2 各 2 seed 都转开（T3）。仍算参考说明段的一部分（prompt_prefix），正文切分不变
    plan.prompt_prefix = line + plan.prompt_prefix


def plan_for(project: str, ep, shot, model: str = "qwen_image_2.1", **kw) -> tuple[ShotRefs, SlotPlan]:
    sr = resolve_shot(project, ep, shot, kept_triggers=kw.get("kept_triggers"), two_person=kw.get("two_person"))
    plan = plan_slots(sr, model, kw.get("capacity"))
    _apply_single_turn(plan, single_turn_line(sr, shot))
    return sr, plan


WARDROBE_WORDS = ("衬衫", "休闲装", "西装", "裙", "裤", "鞋", "外套", "毛衣", "浴袍", "卫衣", "T恤", "针织衫", "束腰", "围裙", "工装", "吊带")


def strip_wardrobe(desc: str) -> tuple[str, list[str]]:
    """角色锁（身份描述）里不得写服装：资产模式下服装由本镜造型锁定（K-AST-232）。
    例：系统角色锁“顾沉：34岁成年男性CEO，黑色高定衬衫，成熟克制英俊”与造型 A（黑色高领毛衣配深灰西装）冲突"""
    parts = [p for p in re.split(r"[，,；;]", desc or "") if p.strip()]
    keep = [p for p in parts if not any(w in p for w in WARDROBE_WORDS)]
    return "，".join(keep), [p for p in parts if p not in keep]


def locks_without_wardrobe(g_):
    """ScriptGlobals 的角色锁去掉服装分句（返回新对象 + 去掉的分句记录）"""
    locks, removed = [], {}
    for c in g_.character_locks:
        d, rm = strip_wardrobe(c.description)
        if rm:
            removed[c.name] = rm
        locks.append(c.model_copy(update={"description": d}))
    return g_.model_copy(update={"character_locks": locks}), removed


def look_inventory(project: str, char: str | None = None) -> list[dict]:
    """资产中心用：每套造型每个部件的参考来源。
    → [{character, name, look, use, sheet, parts:[{slot, label, zone, item_id, item_file, status}]}]
    status: wardrobe（衣橱产品图）| sheet_only（只有设定图，建议补单品图）| missing（连设定图都没有 = 资产缺图，阻断）"""
    out = []
    for cid, lks in load_looks(project).items():
        if char and cid != char:
            continue
        for lid, L in sorted(lks.items()):
            sheet = sheet_of(project, cid, lid)
            parts = []
            for p in L.parts:
                f = item_image(p.item_id) if p.item_id else None
                st = "wardrobe" if f else ("missing" if p.force_missing or not sheet else "sheet_only")
                if p.slot == "marker":
                    st = "identity"
                parts.append({"slot": p.slot, "label": _short(p.label), "raw": p.label, "zone": p.zone,
                              "item_id": p.item_id, "item_file": f, "status": st, "extra": p.extra,
                              "eps": list(p.eps) if p.eps else None})
            out.append({"character": cid, "name": ID_NAME.get(cid, cid), "look": lid, "use": L.use, "zh": L.zh,
                        "sheet": sheet, "face": face_of(project, cid), "parts": parts})
    return out


def record(sr: ShotRefs, plan: SlotPlan) -> dict:
    """写进作业 / 给界面（资产中心“每镜用了哪些参考图”）的记录"""
    return {"shot_id": sr.shot_id, "model": plan.model, "capacity": plan.capacity, "size": sr.size,
            "subject": sr.subject, "zones": sr.zones, "primary": sr.primary, "characters": sr.characters,
            "slots": [asdict(s) for s in plan.slots], "dropped": plan.dropped,
            "missing": sr.missing, "warnings": sr.warnings, "blocked": sr.blocked, "two_person": sr.two_person, "mirror": sr.mirror,
            "rule": "K-AST-230 / GEN_CONTRACT I2–I5、I9（ns_agent.asset_refs）"}


SHOE_EN = re.compile(r"\b(heels?|stilettos?|shoes?|sneakers?|boots?|slippers?|sandals?|flats?|loafers?)\b", re.I)


def look_en_for_shot(project: str, ep, shot, name: str) -> tuple[str | None, list[str]]:
    """H3 / 视频锚点句用的造型 EN（ASSETMASTER 11-01 提：本镜换鞋时 EN 仍写原鞋）。
    本镜生效的附加鞋（look_extras / 资产中心附加单品，正文写到）带 "en" 时，把造型 EN 里写鞋的那一段换成它。
    → (EN, 说明)；没有登记 EN 的附加鞋 → 原 EN + 一条说明（请在 look_extras 里补 en）"""
    cid = NAME_ID.get(name, name)
    n_ep, idx = int(g(ep, "number") or g(shot, "episode") or 0), int(g(shot, "index"))
    reg = registry_looks(project).get(f"ep{n_ep:02d}-S{idx}", {})
    lid = episode_look_override(project, cid, n_ep) or         (reg.get(cid) if isinstance(reg.get(cid), str) else (reg.get(cid) or {}).get("look"))
    looks = load_looks(project).get(cid) or {}
    if not lid:
        row = look_for(ep, name, idx)
        lid = match_look(looks, g(row, "slots"))[0] if row is not None else None
    if not lid or lid not in looks:
        return None, ["造型未登记"]
    L = looks[lid]
    img = g(shot, "img_prompt") or ""
    alt = [p for p in L.parts if p.extra and p.slot == "shoes" and part_active(p, n_ep, img)]
    if not alt:
        return L.en, []
    en = _extra_en(cid, lid, alt[0].label)
    if not en:
        return L.en, [f"本镜换鞋“{alt[0].label}”，但 look_extras 没有 en，EN 仍是原鞋——请补 en"]
    segs = [x.strip() for x in L.en.split(",")]
    k = next((i for i, x in enumerate(segs) if SHOE_EN.search(x)), None)
    if k is None:
        segs.append(en)
    else:
        segs[k] = en
    return ", ".join(segs), [f"本镜换鞋：{alt[0].label} → {en}"]


def _extra_en(cid: str, lid: str, name: str) -> str | None:
    try:
        d = json.loads(EXTRAS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return next((e.get("en") for e in ((d.get(cid) or {}).get(lid) or []) if e.get("name") == name and e.get("en")), None)
