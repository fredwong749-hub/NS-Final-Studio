"""Previz 自动摆位（L-197 B / L-206 ②）：分镜（站位 / 光学 / 机位与景别 / 人物 / 构图 / 场景）→ blocking JSON → 深度图 + 预览图。
确定性（无随机、无网络）；渲染复用 tools/previz/blocking.py。

两个入口：
  ① 导入稿（生产）：fields_from_shot(shot) + cast_from_locks(globals.character_locks) → ensure_previz(sid, fields, cast)
     （frame_job.previz_inputs 在编作业时调用；按输入哈希缓存到 data/previz/<ep>-S<n>/auto/<sha12>/，算过一次不再算；
     渲染按 render_scale 出小图再放大到出图尺寸，CPU 单镜 ~5–10 s）
  ② 分镜 md（研究 / 手工）：
  python tools/previz/auto_blocking.py --storyboard <P4_*.md> --ep ep02 [--shots 1,4,13] [--out data/previz] [--no-render]
  python tools/previz/auto_blocking.py --storyboard <P4_*.md> --ep ep02 --sheet data/previz/ep02_contact.jpg
  python tools/previz/auto_blocking.py --run series10_v2 --ep 2 [--shots 1,4] [--last] [--jobs 4]   # 预热生产缓存（导入稿）
输出：data/previz/<ep>-S<n>/S<n>.json + out/S<n>_depth.png / _preview.png（md 入口）；auto/<sha12>/S<n>_depth.png（生产缓存）。

摆位约定（相机坐标系：x 右、y 向画里、z 上；相机在 (0,0,光学高度) 看 +y 方向，仅按焦距+景别反推距离）：
  人物横向 = 人物字段的 左/中偏左/中/中偏右/右 × 该深度的画宽；深度 = 景别推出的主体距离 ± 前/中/后。
  不露脸（背对 / 只露肩）的前景人物放在主体前方 0.9 m、横向 ±0.30 画宽（只露肩与后脑）。
  局部（只拍手）镜：相机俯拍桌面，人物只出前臂+手。
"""
from __future__ import annotations
import argparse, hashlib, json, math, os, re, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT / "packages/schema"), str(ROOT / "tools/previz")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
from ns_schema.prompt_v2 import split_field, kv_field, strip_parens, parse_angle, hidden_face  # noqa: E402

RENDER_VERSION = 3            # 摆位 / 渲染算法版本：改了摆位规则或 blocking.py 的几何就 +1（进输入哈希 → 旧缓存自然作废、作业签名随之变）
DEFAULT_SCALE = 0.5           # 生产缓存的渲染倍率（1152×2016 × 0.5 → 再放大回出图尺寸；深度图只做 ControlNet 条件，半分辨率足够）
SENSOR_H = 36.0
SENSOR_W_EFF = 36.0 * 9 / 16        # 9:16 竖幅有效宽
# 景别 → 画面竖向可见高度（米，人物站在画中时）
VIS = {"大特写": 0.15, "极近特写": 0.15, "特写": 0.40, "近景": 0.70, "中近景": 0.95, "中景": 1.40, "中全景": 2.0, "全景": 2.6, "大全景": 4.0}
X_FRAC = {"左": -0.22, "中偏左": -0.11, "中": 0.0, "中偏右": 0.11, "右": 0.22}
BUILD_H = (("高大挺拔", 1.85), ("清瘦修长", 1.80), ("结实中等", 1.74), ("匀称干练", 1.65), ("高挑纤细", 1.72))


# ---------------------------------------------------------------- 分镜解析
def read_cast(md: str) -> dict:
    """全局角色锁行 【名】NN岁成年X性，…｜体型｜发型… → {name: {sex, height, hair}}"""
    out = {}
    for m in re.finditer(r"^【([^】\n]{1,6})】(\d+)岁成年([女男])性[^\n]*", md, re.M):
        line = m.group(0)
        segs = split_field(line)
        h = 1.70 if m.group(3) == "女" else 1.80
        for k, v in BUILD_H:
            if k in line:
                h = v
                break
        hair = None
        hs = segs[2] if len(segs) > 2 else ""
        if re.search(r"及腰|长发|中长发|半扎", hs):
            hair = "long"
        elif re.search(r"齐肩|及肩|中分|短发", hs):
            hair = "bob"
        out[m.group(1)] = {"sex": m.group(3), "height": h, "hair": hair}
    return out


def split_shots(md: str) -> dict:
    """{n: {field: text}}；n 为镜号（int）。首行 **镜N｜img**：<img 正文>"""
    shots = {}
    parts = re.split(r"(?m)^\*\*镜(\d+)｜img\*\*：", md)
    for i in range(1, len(parts), 2):
        n = int(parts[i])
        body = parts[i + 1]
        lines = body.split("\n")
        fields = {"img": lines[0]}
        for l in lines[1:]:
            m = re.match(r"\*\*([^*\n]{1,8})\*\*：(.*)", l)
            if m and m.group(1) not in fields:
                fields[m.group(1)] = m.group(2).strip()
            elif l.startswith("**镜") or l.startswith("---") or l.startswith("## "):
                break
        shots[n] = fields
    return shots


HAND_PART_RE = re.compile(r"手|指|掌|腕")
STANCE_WORDS = ("背对镜头", "背对", "背影", "正面", "侧右", "侧左", "侧前偏左", "侧前", "蹲", "坐在", "俯身", "倚", "靠在")


def own_clauses(text: str, name: str, names: list[str]) -> str:
    """正文里“属于这个人”的小句：含人名、且不含别人名字的小句（逗号 / 句号 / 分号切），拼回一句——给没有 **站位** 行的导入稿推姿态"""
    others = [n for n in names if n and n != name]
    out = []
    for cl in re.split(r"[，,。；;（）()：:｜|]", text or ""):        # 括注 / 冒号也切：“（A 区过肩位：相机与卓琳蹲姿的肩同高）”里的姿态要拿到
        if name in cl and not any(o in cl for o in others):
            pre = cl[:cl.index(name)]
            if pre and _OBJ_PREP_RE.search(pre):                    # “蹲在祁念的左前方”：祁念是宾语，这句说的是别人的姿态
                continue
            out.append(cl.strip())
    return "，".join(out)


_OBJ_PREP_RE = re.compile(r"[在向朝对比从跟和与给把看望盯靠挨越过着替帮拍]$")     # 同 asset_refs._OBJ_PREP_RE（+拍）
_STANCE_RE = r"(背对镜头|背对|背影|正面|侧右|侧左|侧前偏左|侧前|蹲|坐在|俯身|倚|靠在)"


def stance_of(name: str, own: str, ctx: str) -> str:
    """姿态头段：先在此人作主语的小句里找；找不到再找紧贴人名的写法（“卓琳蹲姿”“黎岸背对镜头”），别人句里的宾语不算"""
    head = next((w for w in STANCE_WORDS if w in own), "")
    if head:
        return head
    m = re.search(re.escape(name) + r"(?:的)?" + _STANCE_RE, ctx or "")
    return m.group(1) if m else ""


def _people_from_text(f: dict) -> list[dict]:
    ppl = []
    for m in re.finditer(r"([^、，,（(]+?)（([^）]*)）", f.get("人物", "")):
        name = m.group(1).strip()
        bits = [b.strip() for b in re.split(r"[｜|]", m.group(2))]
        pres = bits[0] if bits else "在画"
        part = bits[1] if pres == "局部" and len(bits) > 1 and not re.fullmatch(r"左|中偏左|中|中偏右|右", bits[1]) else None
        rest = [b for b in bits[1:] if b != part]
        ppl.append({"name": name, "presence_raw": pres, "part_raw": part, "x": rest[0] if rest else "中", "depth": rest[1] if len(rest) > 1 else "中"})
    return ppl


def parse_people(f: dict, cast: dict) -> list[dict]:
    """人物（或导入稿 cast 结构）+ 站位 → [{name, presence in|partial|off, x, depth, hidden, part, stance, seg}]。
    局部 = 只拍手（partial，走桌面插入镜）；局部“背影 / 肩 / 后脑”（L-204 ①过肩前景不露脸）= 在画但不露脸（in + hidden），不是插入镜。
    没有 **站位** 行（导入稿）时，姿态从 img / 机位与景别 里属于此人的小句推（蹲 / 坐 / 背对 / 侧右…）"""
    if f.get("cast") is not None:
        ppl = [{"name": c.get("name"), "presence_raw": c.get("presence") or "在画", "part_raw": c.get("part") or None,
                "x": c.get("x") or "中", "depth": c.get("depth") or "中"} for c in f["cast"] if c.get("name")]
    else:
        ppl = _people_from_text(f)
    names = [p["name"] for p in ppl]
    stand = f.get("站位", "")
    segs = {}
    for seg in stand.split("；"):
        nm = next((n for n in names if seg.startswith(n + "：")), None)
        if nm:
            segs[nm] = seg[len(nm) + 1:]
    ctx = "。".join(f.get(k, "") for k in ("img", "机位与景别"))
    for p in ppl:
        pr, part = p.pop("presence_raw"), p.pop("part_raw")
        if pr == "画外":
            p["presence"] = "off"
        elif pr == "局部" and (not part or HAND_PART_RE.search(part)):
            p["presence"] = "partial"
        else:
            p["presence"] = "in"
        seg = segs.get(p["name"], "")
        if not seg:
            own = own_clauses(ctx, p["name"], names)
            head = stance_of(p["name"], own, ctx)
            if pr == "局部" and part and p["presence"] == "in":
                seg = f"背对镜头｜只以{part.replace('背影', '')or '肩与后脑'}入画" + ("，" + own if own else "")
            elif own or head:
                seg = (head + "｜" if head else "") + own
            pm = re.search(re.escape(p["name"]) + r"(?:的)?(蹲|坐在|俯身|倚|靠在)", ctx)     # 紧贴人名的姿态词（“卓琳蹲姿的肩同高”）→ 姿态
            if pm and pm.group(1) not in seg:
                seg += ("，" if seg else "") + pm.group(1)
        p["seg"] = seg
        p["stance"] = split_field(seg)[0] if seg else ""
        p["hidden"], p["part"] = hidden_face(seg)
        if pr == "局部" and part and p["presence"] == "in" and not p["hidden"]:
            p["hidden"], p["part"] = True, part
        p["cast"] = cast.get(p["name"], {"sex": "女", "height": 1.70, "hair": None})
    return ppl


def parse_optics(text: str) -> tuple[float, float | None, float]:
    segs = split_field(text)
    f = float(re.search(r"(\d+(?:\.\d+)?)\s*mm", segs[0]).group(1)) if segs and re.search(r"mm", segs[0]) else 50.0
    t = None
    if len(segs) > 1:
        mt = re.search(r"T\s*(\d+(?:\.\d+)?)", segs[1])
        t = float(mt.group(1)) if mt else None
    h = 1.4
    for s in segs[2:]:
        mh = re.search(r"高度\s*=\s*(\d+(?:\.\d+)?)\s*m", s)
        if mh:
            h = float(mh.group(1))
    return f, t, h


def parse_size(angle_field: str, img: str) -> str:
    seg = (split_field(angle_field) or [""])[0]
    for k in sorted(VIS, key=len, reverse=True):
        if k in seg:
            return k
    for k in sorted(VIS, key=len, reverse=True):
        if k in img[:20]:
            return k
    return "中景"


# ---------------------------------------------------------------- 摆位
def _yaw_toward(dx: float, dy: float) -> list[float]:
    return [dx, dy]


def stance_facing(stance: str, hidden: bool, side_sign: float) -> tuple[float, float]:
    """站位头段 → 朝向向量（相机系，x 右、y 向画里；朝相机 = (0,-1)）"""
    s = stance or ""
    if "背对" in s or hidden and "背" in s:
        return (0.0, 1.0)
    if "正面" in s:
        return (0.0, -1.0)
    if "侧右" in s:
        return (0.6, -0.8)
    if "侧左" in s:
        return (-0.6, -0.8)
    if "侧前偏左" in s or "侧前" in s:
        return (-0.4, -0.9)
    if hidden:
        return (0.0, 1.0)
    return (0.5 * side_sign, -0.85)


def pose_of(seg: str, name_hidden: bool) -> tuple[str, dict]:
    """站位文字 → (pose, extra) ：seated / standing；蹲 → seated 低座；倚/俯身 → lean"""
    kw = {}
    if re.search(r"蹲", seg):
        return "seated", {"seat_h": 0.50, "lean_deg": 0}
    if re.search(r"坐在", seg):
        return "seated", {"seat_h": 0.46, "lean_deg": 5 + (12 if re.search(r"探到|前倾|上身探", seg) else 0)}
    if re.search(r"俯身", seg):
        return "standing", {"lean_deg": 22}
    if re.search(r"倚|靠在", seg):
        return "standing", {"lean_deg": 10}
    return "standing", kw


def head_top(H: float, pose: str, ex: dict) -> float:
    s = H / 1.70
    if pose == "seated":
        return ex.get("seat_h", 0.46) + 0.08 * s + 0.5 * s * math.cos(math.radians(ex.get("lean_deg", 0))) + 0.22 * s
    return H * 1.0


def hand_targets(seg: str, side_flip: float, H: float, pose: str, table_h: float | None) -> dict:
    """站位文字里的“右手…/左手…” → 局部系手腕目标（x 右、y 前、z 上；前=人物朝向）。只处理常见几类，其余自然下垂"""
    out = {}
    s = H / 1.70
    for sd, key in (("右手", "r"), ("左手", "l")):
        m = re.search(sd + r"([^，；。]*)", seg)
        if not m:
            continue
        a = m.group(1)
        sg = 1 if key == "r" else -1
        if re.search(r"撑桌|搭桌|压|按", a) and table_h:
            out[key] = [sg * 0.15, 0.40 * s, table_h]
        elif re.search(r"举|端|递|握杯|握着|捏|勾|攥|拿|接", a) and not re.search(r"垂|腰侧", a):
            out[key] = [sg * 0.18, 0.32 * s, 1.18 * s if pose != "seated" else 0.95]
        elif re.search(r"搭|扶|放", a):
            out[key] = [sg * 0.22, 0.34 * s, (table_h or 1.0 * s)]
        elif re.search(r"口袋", a):
            out[key] = [sg * 0.17, 0.05, 0.85 * s]
        elif re.search(r"垂|腰侧", a):
            out[key] = [sg * 0.2, 0.08, 0.80 * s]
    return out


def to_world(local, pos, yaw_vec):
    """局部（前 = +y 向量 yaw_vec 的朝向）→ 世界"""
    fx, fy = yaw_vec
    n = math.hypot(fx, fy) or 1
    fx, fy = fx / n, fy / n
    rx, ry = fy, -fx          # 右 = 前 顺时针转 90°
    return [round(pos[0] + local[0] * rx + local[1] * fx, 3), round(pos[1] + local[0] * ry + local[1] * fy, 3), round(local[2], 3)]


def _text(f: dict) -> str:
    return "｜".join(f.get(k, "") for k in ("场景", "构图", "img"))


def build_props(f: dict, d_g: float, d_front: float, shot_zone: dict) -> list[dict]:
    """场景 / 构图 的背景层关键词 → 道具。远景光源只做深度上的几何，没有光；位置相机系。"""
    txt = _text(f)
    comp = f.get("构图", "")
    bg = ""
    for p in split_field(comp):
        if p.startswith("背景="):
            bg = p
    scene = f.get("场景", "")
    props = []
    far = d_g + 4.2
    W_at = lambda d, frac: frac * d * SENSOR_W_EFF / shot_zone["focal"]   # noqa: E731
    if "白幕" in txt:
        props.append({"type": "cyc", "name": "cyc", "y0": round(far - 0.9, 2), "R": 0.9})
        if re.search(r"闪光灯灯架|灯架", bg + scene):
            props.append({"type": "stand", "name": "stand_A", "pos": [round(W_at(far, -0.12), 2), round(far - 0.6, 2), 0], "h": 2.2, "head": [0.7, 0.25, 0.7]})
            props.append({"type": "stand", "name": "stand_B", "pos": [round(W_at(far, -0.40), 2), round(far - 0.8, 2), 0], "h": 2.0, "head": [0.8, 0.3, 0.8]})
        if re.search(r"工作灯泡|顶棚", bg + scene):
            for i, fx in enumerate((-0.2, 0.15, 0.35)):
                props.append({"type": "sphere", "name": f"bulb{i}", "pos": [round(W_at(far, fx), 2), round(far - 1.0, 2), 3.0 - 0.15 * i], "r": 0.06})
        if "监视器" in txt:
            props.append({"type": "box", "name": "monitor_cart", "pos": [round(W_at(far, 0.30), 2), round(far - 1.0, 2), 0.6], "size": [0.6, 0.5, 1.2]})
        if "环形灯" in txt:
            fg = bool(re.search(r"环形灯[^｜，]{0,6}前景|前景=[^｜]*环形灯", txt))
            if fg and shot_zone.get("hidden"):
                pass
            elif fg:
                d = max(0.9, d_front - 0.4)                                  # 前景环形灯：略在最前的人物之前、贴右缘（不压在人物头上）
                props.append({"type": "stand", "name": "stand_ring", "pos": [round(W_at(d, 0.46), 2), round(d, 2), 0], "h": 1.6})
                props.append({"type": "ring", "name": "ringlight", "pos": [round(W_at(d, 0.46), 2), round(d, 2), 1.6], "R": 0.28, "normal_yaw_deg": 180})
            elif "环形灯架后" in txt:
                d = max(0.9, d_g - 0.3)
                props.append({"type": "rod", "name": "ring_bar", "a": [round(W_at(d, -0.45), 2), round(d, 2), 1.25], "b": [round(W_at(d, 0.1), 2), round(d, 2), 1.25], "r": 0.015})
                props.append({"type": "stand", "name": "stand_ring", "pos": [round(W_at(d, 0.0), 2), round(d, 2), 0], "h": 1.6})
            else:
                props.append({"type": "stand", "name": "stand_ring", "pos": [round(W_at(far, -0.35), 2), round(far - 0.8, 2), 0], "h": 1.6})
                props.append({"type": "ring", "name": "ringlight", "pos": [round(W_at(far, -0.35), 2), round(far - 0.8, 2), 1.9], "R": 0.28, "normal_yaw_deg": 180})
        if "风机" in txt:
            props.append({"type": "fan", "name": "fan", "pos": [round(W_at(d_g + 0.3, 0.30), 2), round(d_g + 0.3, 2), 0], "head_z": 0.95, "fy": -1})
        if re.search(r"亚克力椅|椅", scene):
            props.append({"type": "box", "name": "chair_seat", "pos": [round(W_at(d_g, -0.30), 2), round(d_g + 0.2, 2), 0.23], "size": [0.45, 0.45, 0.46]})
            props.append({"type": "box", "name": "chair_back", "pos": [round(W_at(d_g, -0.30), 2), round(d_g + 0.42, 2), 0.7], "size": [0.45, 0.04, 0.5]})
    elif "天台" in scene[:30] or "天台" in txt and "车" not in scene[:30]:
        # 天台酒吧：围栏 / 高圆桌 / 吧台 / 酒架 / 大屏
        props.append({"type": "box", "name": "railing", "pos": [0, round(far - 1.5, 2), 0.55], "size": [8.0, 0.06, 1.1]})
        props.append({"type": "box", "name": "ground_edge", "pos": [0, round(far - 1.5, 2), -0.05], "size": [12, 3.0, 0.1]})
        if re.search(r"吧台|酒架|霓虹", bg + scene):
            props.append({"type": "box", "name": "bar_counter", "pos": [round(W_at(far, -0.30), 2), round(far - 0.2, 2), 0.55], "size": [3.0, 0.7, 1.1]})
            props.append({"type": "box", "name": "bottle_shelf", "pos": [round(W_at(far, -0.30), 2), round(far + 0.5, 2), 1.6], "size": [3.0, 0.25, 1.2]})
        if "大屏" in txt:
            props.append({"type": "box", "name": "big_screen", "pos": [round(W_at(far, 0.05), 2), round(far + 0.3, 2), 3.1], "size": [2.6, 0.12, 1.4]})
        if "高圆桌" in txt:
            props.append({"type": "box", "name": "table_top", "pos": [0, round(d_g, 2), 1.03], "size": [0.68, 0.68, 0.04]})
            props.append({"type": "cylinder", "name": "table_leg", "pos": [0, round(d_g, 2), 0.5], "h": 1.0, "r": 0.04})
            props.append({"type": "box", "name": "table_base", "pos": [0, round(d_g, 2), 0.02], "size": [0.44, 0.44, 0.04]})
    if re.search(r"驾驶座|网约车", scene):
        yy = d_g
        props.append({"type": "box", "name": "seat_back", "pos": [0, round(yy + 0.28, 2), 0.78], "size": [0.5, 0.12, 0.7]})
        props.append({"type": "ring", "name": "steering_wheel", "pos": [0.0, round(yy - 0.55, 2), 0.95], "R": 0.19, "r": 0.016, "normal_yaw_deg": 0})
        props.append({"type": "box", "name": "dashboard", "pos": [0, round(yy - 0.85, 2), 0.78], "size": [1.5, 0.45, 0.28]})
        props.append({"type": "box", "name": "A_pillar_L", "pos": [-0.75, round(yy - 0.7, 2), 1.15], "size": [0.1, 0.1, 0.9]})
        props.append({"type": "box", "name": "A_pillar_R", "pos": [0.78, round(yy - 0.7, 2), 1.15], "size": [0.1, 0.1, 0.9]})
        props.append({"type": "cylinder", "name": "mirror_charm", "pos": [0.15, round(yy - 0.8, 2), 1.5], "h": 0.12, "r": 0.03})
        props.append({"type": "box", "name": "street_ground", "pos": [0, round(far, 2), -0.05], "size": [20, 20, 0.1]})
        props.append({"type": "cylinder", "name": "street_lamp", "pos": [round(W_at(far, -0.35), 2), round(far, 2), 2.5], "h": 5.0, "r": 0.1})
    return props


def hands_shot(f: dict, ppl: list[dict], focal: float, cam_h: float) -> dict:
    """局部（只拍手）镜：俯拍桌面。人物只出前臂 + 手"""
    table_h = 1.05
    props = [{"type": "box", "name": "table_top", "pos": [0, 0, table_h - 0.02], "size": [0.68, 0.68, 0.04]}]
    span = 0.18
    for p in ppl:
        if p["presence"] == "off":
            continue
        x_sign = -1 if p["x"] in ("左", "中偏左") else 1
        tip = [x_sign * 0.04, 0.0, table_h + 0.03]
        far_ = [x_sign * 0.40, 0.18, table_h + 0.18]
        props.append({"type": "rod", "name": p["name"] + "_arm", "a": far_, "b": tip, "r": 0.03})
        props.append({"type": "sphere", "name": p["name"] + "_hand", "pos": [tip[0], tip[1], tip[2]], "r": 0.04})
    if re.search(r"钥匙", f.get("img", "")):
        props.append({"type": "box", "name": "key", "pos": [0.09, -0.04, table_h + 0.01], "size": [0.06, 0.03, 0.012]})
    if re.search(r"邀请卡", f.get("img", "")):
        props.append({"type": "box", "name": "card", "pos": [0.14, 0.06, table_h + 0.005], "size": [0.11, 0.07, 0.006]})
    if re.search(r"香槟杯|杯", f.get("img", "")):
        props.append({"type": "cylinder", "name": "glass", "pos": [0.0, 0.14, table_h + 0.07], "h": 0.14, "r": 0.03})
    cam = {"pos": [0.0, -0.06, round(table_h + (cam_h - table_h if cam_h > table_h else 0.4), 3)], "look_at": [0, 0.02, table_h], "focal_mm": focal}
    return {"camera": cam, "actors": [], "props": props}


def auto_blocking(n: int, f: dict, cast: dict) -> dict:
    img = f.get("img", "")
    ppl = parse_people(f, cast)
    focal, T, cam_h = parse_optics(f.get("光学", ""))
    size = parse_size(f.get("机位与景别", ""), img)
    ang = parse_angle(f.get("机位与景别", ""), [p["name"] for p in ppl])
    meta = {"shot": n, "size": size, "focal_mm": focal, "T": T, "cam_h": cam_h, "angle": {k: v for k, v in ang.items() if k != "raw"}}
    vis_all = [p for p in ppl if p["presence"] != "off"]
    if vis_all and all(p["presence"] == "partial" for p in vis_all):       # 全是“只拍手”的局部 → 桌面插入镜；混合时只拍手的人不进画
        spec = hands_shot(f, ppl, focal, cam_h)
        meta.update(focus_distance_m=round(spec["camera"]["pos"][2] - spec["camera"]["look_at"][2], 2), bg_distance_m=None)
        spec.update({"name": f"S{n} hands insert", "size": [1152, 2016], "meta": meta})
        return spec
    vis = [p for p in ppl if p["presence"] == "in"]
    faced = [p for p in vis if not p["hidden"]]
    hid = [p for p in vis if p["hidden"]]
    focus = faced or vis
    # 主体距离：景别竖向可见高度；多脸并排要把宽度放下
    d_size = VIS[size] * focal / SENSOR_H
    d_fit = (0.50 * len(faced)) * focal / SENSOR_W_EFF if len(faced) >= 2 else 0
    d_g = round(max(d_size, d_fit), 2)
    wide = lambda d, frac: frac * d * SENSOR_W_EFF / focal   # noqa: E731
    actors, table_h = [], None
    if "高圆桌" in _text(f):
        table_h = 1.05
    depth_off = {"前": -0.6, "中": 0.0, "后": 0.6}
    d_front = d_g
    for p in vis:
        c = p["cast"]
        H = c["height"]
        if p["hidden"]:
            standing_fg = not re.search(r"蹲|坐在", p["seg"])          # 站立的前景人物头在画面上部，要更靠边、更近相机，只露肩的一角
            d = max(0.6, d_g * (0.55 if standing_fg else 0.6))         # 按主体距离的比例（不是固定减 1 m）：中景 50mm 的前景人不至于占半幅
            sx = X_FRAC.get(p["x"], 0.0)
            mag = 0.48 if standing_fg else 0.42
            frac = (mag if sx >= 0 else -mag) if abs(sx) > 0 else (mag if (focus and X_FRAC.get(focus[0]["x"], 0) < 0) else -mag)
        else:
            d = d_g + depth_off.get(p["depth"], 0.0)
            frac = X_FRAC.get(p["x"], 0.0) * (0.6 if len(faced) == 1 else 1.0)
        d_front = min(d_front, d)
        pos = [round(wide(d, frac), 3), round(d, 3), 0.0]
        pose, ex = pose_of(p["seg"], p["hidden"])
        side_sign = 1.0 if frac < 0 else -1.0     # 默认朝画面中心偏一点
        fv = stance_facing(p["stance"], p["hidden"], side_sign)
        yaw_tgt = [pos[0] + fv[0], pos[1] + fv[1]]
        a = {"id": p["name"], "height": H, "pos": pos, "face_to": [round(v, 3) for v in yaw_tgt], "pose": pose}
        if c.get("hair"):
            a["hair"] = c["hair"]
        a.update(ex)
        loc = hand_targets(p["seg"], 1.0, H, pose, table_h)
        if loc:
            a["wrists"] = {k: to_world(v, pos, fv) for k, v in loc.items()}
            # 桌面手腕目标：高度直接取桌面
        actors.append(a)
    # 相机：在原点，看向主体脸部带景别构图的点
    fa = next((a for a in actors if a["id"] == (focus[0]["name"] if focus else "")), actors[0] if actors else None)
    ref = [p for p in focus if p["name"] == fa["id"]][0]["cast"] if fa else {"height": 1.7}
    top = head_top(fa["height"], fa["pose"], fa) if fa else 1.7
    if size in ("特写", "大特写", "极近特写"):
        zc = top - 0.12
    else:
        zc = min(top + 0.12, top + 0.12) - VIS[size] / 2
    yaw_b = 0.0
    look = [0.0, d_g, round(zc, 3)]
    if ang["height"] == "high":
        look[2] = round(max(cam_h - d_g * 0.35, 0.6), 3)
    cam = {"pos": [0.0, 0.0, cam_h], "look_at": look, "focal_mm": focal}
    props = build_props(f, d_g, d_front, {"focal": focal, "hidden": bool(hid)})
    meta.update(focus_distance_m=round(math.hypot(look[1], cam_h - look[2]), 2), bg_distance_m=round(d_g + 4.2, 2))     # lens_sim v2 的 spec（度量距离）
    return {"name": f"S{n} auto", "size": [1152, 2016], "camera": cam, "actors": actors, "props": props, "meta": meta}


# ---------------------------------------------------------------- 导入稿入口（生产）
def _g(o, k, d=None):
    return o.get(k, d) if isinstance(o, dict) else getattr(o, k, d)


_LABEL_PAREN_RE = re.compile(r"（[^）]*）|\([^)]*\)")
SHOT_FIELDS = ("机位与景别", "光学", "构图", "运镜", "站位")


def cast_from_locks(locks) -> dict:
    """script.globals.character_locks [{name, description}]（description = “23岁成年女性，…｜体型｜发型…”）→ 同 read_cast"""
    md = "\n".join(f"【{_g(l, 'name')}】{_g(l, 'description') or ''}" for l in (locks or []) if _g(l, "name"))
    return read_cast(md)


def fields_from_shot(shot) -> dict:
    """导入稿 shot（dict / pydantic）→ auto_blocking 用的字段表：img、机位与景别 / 光学 / 构图 / 运镜（/ 站位，有就带）、场景（scene_id｜scene_detail）、
    cast（结构化：name / presence / x / depth / part，K-REN-952 站位唯一来源）。只取影响摆位的字段 → 输入哈希只随这些变"""
    f = {"img": str(_g(shot, "img_prompt") or "")}
    for e in _g(shot, "extras") or []:
        lab = _LABEL_PAREN_RE.sub("", str(_g(e, "label") or "")).strip("*：: ")
        if lab in SHOT_FIELDS and lab not in f:
            f[lab] = str(_g(e, "text") or "").strip()
    f["场景"] = "｜".join(x for x in (str(_g(shot, "scene_id") or ""), str(_g(shot, "scene_detail") or "")) if x)
    cast = []
    for c in _g(shot, "cast") or []:
        if not _g(c, "name"):
            continue
        cast.append({"name": str(_g(c, "name")), "presence": str(_g(c, "presence") or "在画"), "x": _g(c, "x") or None,
                     "depth": _g(c, "depth") or None, "part": _g(c, "part") or None})
    f["cast"] = cast
    f["人物"] = "、".join(f"{c['name']}（{c['presence']}｜{c['x'] or '中'}｜{c['depth'] or '中'}）" for c in cast)
    return f


def inputs_sha(fields: dict, cast: dict, scale: float = DEFAULT_SCALE, size=(1152, 2016)) -> str:
    """输入哈希：摆位字段 + 角色身高 / 发型 + 渲染版本 / 倍率 / 尺寸。两台机器各自算，同输入 → 同哈希（作业签名认它，不认 PNG 字节）"""
    names = {c["name"] for c in fields.get("cast") or []} | set(re.findall(r"([^、，,（(]+?)（", fields.get("人物", "")))
    cast_used = {k: cast[k] for k in sorted(cast) if k in names}
    payload = {"v": RENDER_VERSION, "scale": scale, "size": list(size), "fields": {k: fields.get(k) for k in sorted(fields)}, "cast": cast_used}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def shot_no(sid: str) -> int:
    m = re.match(r"^ep\d+-S(\d+)$", sid or "")
    if not m:
        raise ValueError(f"镜号不合法：{sid!r}（要 epNN-Sn）")
    return int(m.group(1))


def ensure_previz(sid: str, fields: dict, cast: dict, *, root: Path = ROOT, dir_: str = "data/previz", scale: float = DEFAULT_SCALE,
                  stage: str = "first") -> dict:
    """本镜摆位图（缓存）：data/previz/<sid>/auto[_last]/<sha12>/S<n>.json + S<n>_depth.png + S<n>_preview.png + meta.json。
    缓存命中 → 不渲染（cached=True）。渲染出错原样抛（调用方 frame_job 接住 → 退回裸 turbo，不拦本集）。
    写文件先写 .tmp 再 os.replace（两台 / 两进程同时算同一镜也不会读到半张图）"""
    n = shot_no(sid)
    sha = inputs_sha(fields, cast, scale)
    d = root / dir_ / sid / ("auto" if stage == "first" else "auto_last") / sha[:12]
    depth, spec_p, prev, meta_p = d / f"S{n}_depth.png", d / f"S{n}.json", d / f"S{n}_preview.png", d / "meta.json"
    rec = {"sid": sid, "stage": stage, "dir": d, "depth": depth, "spec": spec_p, "preview": prev, "inputs_sha": sha, "scale": scale}
    if depth.is_file() and spec_p.is_file():
        try:
            meta = json.loads(meta_p.read_text(encoding="utf-8"))
        except (OSError, ValueError):   # arch-ok: meta 只记耗时，缺了不影响深度图的使用
            meta = {}
        return {**rec, "cached": True, "seconds": meta.get("seconds")}
    t0 = time.time()
    spec = auto_blocking(n, fields, cast)
    d.mkdir(parents=True, exist_ok=True)
    render_shot(spec, d, f"S{n}", scale, full_size=tuple(spec.get("size") or (1152, 2016)))
    _write_atomic(spec_p, json.dumps(spec, ensure_ascii=False, indent=1))
    sec = round(time.time() - t0, 2)
    _write_atomic(meta_p, json.dumps({"sid": sid, "stage": stage, "inputs_sha": sha, "scale": scale, "render_version": RENDER_VERSION,
                                      "seconds": sec, "size": spec.get("size"), "meta": spec.get("meta")}, ensure_ascii=False, indent=1))
    return {**rec, "cached": False, "seconds": sec}


def _write_atomic(p: Path, text: str) -> None:
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, p)


def previz_for_script(run: str, ep_no: int, shots: list[int] | None = None, *, last: bool = False, root: Path = ROOT,
                      scale: float = DEFAULT_SCALE, jobs: int = 1) -> list[dict]:
    """预热生产缓存：导入稿（runs.script_path）→ 本集每镜 ensure_previz（--last 连尾帧落幅的也算，走 frame_job.compose_last_shot 同一套改写）"""
    for _p in (str(root / "tools/autopilot"), str(root / "services/agent")):
        if _p not in sys.path:
            sys.path.insert(0, _p)
    import runs as R
    sc = json.loads(Path(R.script_path(run, root)).read_text(encoding="utf-8"))
    ep = next((e for e in sc["episodes"] if int(e.get("number") or 0) == int(ep_no)), None)
    if not ep:
        raise SystemExit(f"{run} 没有第 {ep_no} 集")
    cast = cast_from_locks((sc.get("globals") or {}).get("character_locks"))
    todo = []
    for s in ep["shots"]:
        if shots and int(s["index"]) not in shots:
            continue
        sid = f"ep{int(ep_no):02d}-S{s['index']}"
        todo.append((sid, fields_from_shot(s), "first"))
        if last:
            from ns_agent import frame_job as FJ
            end = FJ.end_framing(s)
            if end:
                todo.append((sid, fields_from_shot(FJ.compose_last_shot(s, end)), "last"))

    def one(t):
        sid, f, st = t
        r = ensure_previz(sid, f, cast, root=root, scale=scale, stage=st)
        print(f"{sid} {st} {'cache' if r['cached'] else 'render'} {r['seconds']}s {r['dir'].relative_to(root).as_posix()}", flush=True)
        return {k: (v.as_posix() if isinstance(v, Path) else v) for k, v in r.items()}
    if jobs > 1:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=jobs) as ex:
            return list(ex.map(one, todo))
    return [one(t) for t in todo]


# ---------------------------------------------------------------- 渲染 / 总览
def render_shot(spec: dict, outdir: Path, stem: str, scale: float = 1.0, full_size: tuple | None = None):
    """渲染深度 + 预览到 outdir/<stem>_depth.png / _preview.png。full_size=(W,H)：按 scale 出小图后放大到该尺寸（生产缓存用）。
    先写 .tmp 再 os.replace（原子）"""
    import blocking as B
    from PIL import Image
    depth, ids, joints, names, ci = B.render(spec, scale)
    outdir.mkdir(parents=True, exist_ok=True)
    dimg = Image.fromarray(B.depth_to_img(depth, spec.get("depth_near"), spec.get("depth_far")))
    pimg = B.preview_img(depth, ids, names)
    if full_size and tuple(dimg.size) != tuple(full_size):
        dimg = dimg.resize(tuple(int(x) for x in full_size), Image.BILINEAR)
    for im, name in ((dimg, f"{stem}_depth.png"), (pimg, f"{stem}_preview.png")):
        tmp = outdir / (name + ".tmp.png")
        im.save(tmp, format="PNG")
        os.replace(tmp, outdir / name)


def contact_sheet(items: list[tuple[str, Path]], dest: Path, cols: int = 6, th: int = 360):
    from PIL import Image, ImageDraw
    ims = []
    for lab, p in items:
        if p.exists():
            im = Image.open(p).convert("RGB")
            w = int(im.width * th / im.height)
            ims.append((lab, im.resize((w, th))))
    if not ims:
        return
    cw = max(i.width for _, i in ims) + 8
    rows = (len(ims) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cw, rows * (th + 22)), (24, 24, 28))
    dr = ImageDraw.Draw(sheet)
    for k, (lab, im) in enumerate(ims):
        x, y = (k % cols) * cw + 4, (k // cols) * (th + 22)
        dr.text((x, y + 4), lab, fill=(230, 230, 230))
        sheet.paste(im, (x, y + 20))
    dest.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(dest, quality=88)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--storyboard", default=None, help="分镜 md（研究 / 手工入口）")
    ap.add_argument("--run", default=None, help="导入稿入口：剧名（如 series10_v2），预热 data/previz/<ep>-S<n>/auto 缓存")
    ap.add_argument("--ep", required=True, help="md 入口写 ep02；--run 入口写集号 2")
    ap.add_argument("--shots", default="all")
    ap.add_argument("--out", default=str(ROOT / "data/previz"))
    ap.add_argument("--no-render", action="store_true")
    ap.add_argument("--scale", type=float, default=None, help="md 入口默认 1.0；--run 入口默认 DEFAULT_SCALE")
    ap.add_argument("--sheet", default=None, help="联系表输出路径（预览图拼图）")
    ap.add_argument("--last", action="store_true", help="--run：连尾帧（落幅）摆位图一起预热")
    ap.add_argument("--jobs", type=int, default=1, help="--run：并行线程数")
    a = ap.parse_args()
    if a.run:
        sel = None if a.shots == "all" else [int(x) for x in a.shots.split(",")]
        recs = previz_for_script(a.run, int(a.ep.replace("ep", "")), sel, last=a.last, scale=a.scale or DEFAULT_SCALE, jobs=max(1, a.jobs))
        if a.sheet:
            contact_sheet([(f"{r['sid']} {r['stage']}", Path(r["preview"])) for r in recs], Path(a.sheet))
        return
    if not a.storyboard:
        raise SystemExit("要 --storyboard <md> 或 --run <剧名>")
    a.scale = a.scale or 1.0
    md = Path(a.storyboard).read_text(encoding="utf-8")
    cast = read_cast(md)
    shots = split_shots(md)
    sel = sorted(shots) if a.shots == "all" else [int(x) for x in a.shots.split(",")]
    items = []
    for n in sel:
        spec = auto_blocking(n, shots[n], cast)
        d = Path(a.out) / f"{a.ep}-S{n}"
        d.mkdir(parents=True, exist_ok=True)
        _tmp = d / f"S{n}.json.tmp"
        _tmp.write_text(json.dumps(spec, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(_tmp, d / f"S{n}.json")              # 原子写（arch_scan nonatomic_json）
        if not a.no_render:
            render_shot(spec, d / "out", f"S{n}", a.scale)
        items.append((f"{a.ep}-S{n} {spec['meta']['focal_mm']:.0f}mm", d / "out" / f"S{n}_preview.png"))
        print("ok", a.ep, n)
    if a.sheet:
        contact_sheet(items, Path(a.sheet))


if __name__ == "__main__":
    main()
