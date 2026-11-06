"""阶段 A 资产作业（总调度决策 M-AUTOPIPE-01，docs/master/DECISION_AUTOPIPE_20261103.md；AUTOPIPE-A 11-03）。

目标：下一集再遇到资产缺口，系统不靠任何 agent 自己走完：
  发现缺口（episode_ready）→ 生成作业（本文件）→ 执行器出候选（asset_worker.py）→ 投进待办通知（owner_queue pick）
  → 项目方选定（/api/owner/pick）→ 登记（register_pick）→ 重跑就绪检查（after_pick）→ 全部就绪写“可以出金样首帧”作业（阶段 B）。

作业文件：data/pipeline/asset_jobs/<run>/<job_id>.json（schema nsfs.asset_job/1）。同一个缺口只生成一个作业（job_id 由缺口类型 + 对象决定，幂等）。
作业类型（kind）与 job_id：
  face    face-<cid>              新人物身份脸候选（P1 文字设定 → 文生图 → 契约 → 取 N 个）→ pick:face:<cid>
  scene   scene-<scene_id>        场景底图候选（P1 场景描述 → 文生图）→ pick:scene:<scene_id>
  sheet   sheet-<cid>-<look>      配角造型设定图候选（P1 造型表 → 文生图）→ pick:sheet:<cid>:<look>   ※ 该角色身份脸登记进清单（file + sha256）之后才派，出图时送这张脸（ISS-1103-004547-ca20）
  voice   voice-<cid>             配角音色候选（P1 voice_phrase → voice_v2 设计 + 复刻 + check）→ pick:voice_v2:<role>
  item    item-<cid>-<look>-<slot> 单品图：清单里写了裁剪规则（crop_rule）就从项目方原图裁，否则出候选 → pick:item:<cid>:<item>
  meta    meta-name-<cid> / meta-looks-<cid> / meta-schedule-<cid>   display_name / 造型骨架 / 造型排期：直接从 P1 写入，不用项目方挑
  golden  golden-epNN             （已停，W6 11-03 / L-151）阶段 B 走 producer；ensure_golden 只在 _ready_epNN.json 记“可交 producer”；历史作业 W6b 标 state=retired（文件不删）
状态（state）：pending → running → awaiting_pick → done；失败 failed（attempts < max 时下一拍重排）；retired = 已停用的遗留作业（只留档，不执行）。
不自己写规则：缺口口径 = tools/master/episode_ready.py；清单格式 = ns_agent.asset_refs（nsfs.assets_manifest/1）。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = "nsfs.asset_job/1"
RENDER_KINDS = ("face", "scene", "sheet", "item")
KINDS = RENDER_KINDS + ("voice", "meta", "golden")
PICK_PREFIX = {"face": "pick:face:", "scene": "pick:scene:", "sheet": "pick:sheet:", "item": "pick:item:", "voice": "pick:voice_v2:"}
TS = "%Y-%m-%dT%H:%M:%S"
_CID_RE = re.compile(r"（([A-Za-z0-9_]+)）\s*$")
_EP_RE = re.compile(r"ep(\d{1,2})")


def _now() -> str:
    return time.strftime(TS)


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def atomic_json(p: Path, obj, tries: int = 8) -> None:
    """原子写。W-PICK 11-07：Windows 上 os.replace 撞上正在读清单的进程会 PermissionError（11-06 两条设定图挑选就这样失败），
    与 tools/autopilot/runs._js 一样退避重试"""
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=p.name + ".", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False, indent=1))
    for i in range(tries):
        try:
            os.replace(tmp, p)
            return
        except PermissionError:
            if i == tries - 1:
                Path(tmp).unlink(missing_ok=True)
                raise
            time.sleep(0.05 * (i + 1))


def _read_json(p: Path, what: str):
    """读不出就抛（失败关闭，不按空处理）"""
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise RuntimeError(f"{what} 读不出来：{p}（{e}）") from e


def _runs_mod():
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from tools.autopilot import runs as R   # noqa: PLC0415  tools 侧 runs 唯一入口
    return R


# ------------------------------------------------------------------ 作业文件
def jobs_dir(root: Path, run: str) -> Path:
    return root / "data" / "pipeline" / "asset_jobs" / run


def job_path(root: Path, run: str, jid: str) -> Path:
    return jobs_dir(root, run) / f"{jid}.json"


def load_job(p: Path) -> dict:
    return _read_json(p, "资产作业")


def registered_runs(root: Path) -> set[str]:
    """root 下 runs.json 登记过的剧（读不出 = 空集，失败关闭）"""
    try:
        d = json.loads((root / "config" / "pipeline" / "runs.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):   # arch-ok: 读不出 = 一部剧都不认（调用方据此拒绝写入 / 匹配）
        return set()
    return set((d.get("runs") or {}).keys())


class TrialRunInRealRepo(RuntimeError):
    """ISS-1103-004549-cb05：没在 runs.json 登记的剧（demo_v2 这类试跑 / 测试剧）不许往真实仓库写作业 / 待办 / 配置"""


def guard_run(root: Path, run: str) -> None:
    """真实仓库里只认 runs.json 登记过的剧；试跑和测试一律用临时目录（临时目录有自己的 runs.json，照常放行）"""
    try:
        real = Path(root).resolve() == ROOT.resolve()
    except OSError:
        real = True
    if real and run not in registered_runs(root):
        raise TrialRunInRealRepo(f"{run} 没在 config/pipeline/runs.json 登记，不许写真实仓库的资产作业（试跑 / 测试请用临时目录）")


def save_job(root: Path, job: dict) -> Path:
    guard_run(root, job["run"])
    job["updated_at"] = _now()
    p = job_path(root, job["run"], job["id"])
    atomic_json(p, job)
    return p


def list_jobs(root: Path, run: str) -> list[dict]:
    d = jobs_dir(root, run)
    if not d.is_dir():
        return []
    out = []
    for p in sorted(d.glob("*.json")):
        if p.name.startswith("_"):
            continue
        try:
            j = load_job(p)
        except RuntimeError as e:          # arch-ok: 一个坏作业文件只跳过并记到 worker 心跳里，不让整拍停掉
            out.append({"id": p.stem, "run": run, "kind": "?", "state": "corrupt", "error": str(e)[:200]})
            continue
        if isinstance(j, dict) and j.get("id"):
            out.append(j)
    return out


def log(job: dict, msg: str) -> None:
    job.setdefault("log", []).append(f"{_now()} {msg}")
    job["log"] = job["log"][-40:]


# ------------------------------------------------------------------ P1
def p1(root: Path, run: str) -> tuple[dict, list]:
    """本剧 P1 故事线（人物 / 场景）+ 造型表；都读不出就抛"""
    rd = _runs_mod().run_dir(run, root)
    story = _read_json(rd / "P1_storyline.json", "P1 故事线")
    lp = rd / "P1_looks.json"
    looks = _read_json(lp, "P1 造型表") if lp.is_file() else []
    return story, looks


def p1_char(story: dict, cid: str) -> dict | None:
    return next((c for c in story.get("characters") or [] if c.get("char_id") == cid), None)


def p1_name_to_cid(story: dict) -> dict:
    return {c.get("name"): c.get("char_id") for c in story.get("characters") or [] if c.get("name") and c.get("char_id")}


def p1_scene(story: dict, sid: str) -> dict | None:
    return next((s for s in story.get("scenes") or [] if s.get("scene_id") == sid), None)


def p1_looks_of(looks: list, cid: str) -> dict | None:
    return next((c for c in looks or [] if c.get("char_id") == cid), None)


def look_for_episode(lk: dict | None, episode: int) -> str | None:
    """P1 造型表 → 本集该用的造型 id：schedule（主角）> looks[].use 里写的 epNN > 第一套"""
    if not lk:
        return None
    for s in lk.get("schedule") or []:
        if int(s.get("episode") or 0) == episode and s.get("outfit"):
            return str(s["outfit"]).split("+")[-1]      # “O1+O4”这种取最后一个（整集主体造型），排期细节由排期作业自己处理
    for l in lk.get("looks") or []:
        eps = {int(x) for x in _EP_RE.findall(str(l.get("use") or ""))}
        if episode in eps:
            return l.get("id")
    first = (lk.get("looks") or [{}])[0]
    return first.get("id")


def _slots(zh: str) -> dict:
    """“服装=…｜鞋=…｜饰品=…” → {服装: …}"""
    out = {}
    for part in str(zh or "").split("｜"):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def _sex(gender: str) -> str:
    return {"女": "女性", "男": "男性"}.get(str(gender or "").strip(), "成年人")


NEUTRAL = "，中性浅灰色纯色背景，柔和均匀的影棚光，无文字无标识"
PORTRAIT = "胸像特写，脸只微微转向画面右侧（接近正脸），眼睛看着画面右侧远处的一点，头和视线都朝向右侧，"
FULLBODY = "全身造型设定图，正面站立，双手自然下垂，从头到脚完整入画，"


def _age(c: dict) -> int:
    """P1 年龄：缺 / 不是正整数 = 拦下（不生成“0岁”；AUTOFIX-O 11-03 P2）"""
    try:
        age = int(c.get("age"))
    except (TypeError, ValueError):
        age = 0
    if age <= 0:
        raise RuntimeError(f"{c.get('name') or c.get('char_id')} P1 人物表没有年龄（age={c.get('age')!r}），不出图；请写手补 P1")
    return age


ZH_LOOK_SEGS = ("年龄", "体型", "发型", "色彩基调", "标记", "五官")


def face_feats(c: dict) -> list[str]:
    """P1 zh_look 固定六段：年龄｜体型｜发型｜色彩基调｜标记｜五官 → 脸 / 身份描述只取 体型、发型、标记、五官。
    年龄另写；色彩基调是服装配色不是长相，不进脸的描述。段数不对 = 拦下（不按位置猜，免得把色彩基调当长相）"""
    segs = [x.strip() for x in str(c.get("zh_look") or "").split("｜") if x.strip()]
    if len(segs) == len(ZH_LOOK_SEGS) - 1 and not segs[0].endswith("岁"):
        segs = ["（年龄另写）"] + segs                         # 只缺年龄段：按其余五段对位
    if len(segs) != len(ZH_LOOK_SEGS):
        raise RuntimeError(f"{c.get('name') or c.get('char_id')} P1 zh_look 不是六段（{len(segs)} 段：{c.get('zh_look')!r}），不出图；请写手按 年龄｜体型｜发型｜色彩基调｜标记｜五官 补齐")
    return [segs[i] for i, k in enumerate(ZH_LOOK_SEGS) if k not in ("年龄", "色彩基调")]


def spec_face(story: dict, looks: list, cid: str, episode: int) -> dict:
    c = p1_char(story, cid)
    if not c:
        raise RuntimeError(f"P1 人物表里没有 {cid}")
    sex, age, name = _sex(c.get("gender")), _age(c), c["name"]
    feats = face_feats(c)
    lk = p1_looks_of(looks, cid)
    lid = look_for_episode(lk, episode)
    look = next((l for l in (lk or {}).get("looks") or [] if l.get("id") == lid), None) or {}
    slots = _slots(look.get("zh"))
    outfit = slots.get("服装") or "日常便装"
    if age < 18:
        raise RuntimeError(f"{name} P1 年龄 {age} 未成年，不出图（HC-07）")
    desc = f"{age}岁中国成年{sex}，{'，'.join(feats)}，真人写实"
    img = (PORTRAIT + f"成年{sex}{name}，{age}岁，{'，'.join(feats)}，穿{outfit}，表情平静自然，真实皮肤质感与成熟的五官轮廓" + NEUTRAL)
    return {"cid": cid, "name": name, "age": age, "sex": sex, "desc": desc, "look": lid, "slots": {"服装": outfit},
            "en": look.get("en") or "", "en_phrase": c.get("en_phrase") or "", "img": img, "framing": "portrait"}


def spec_sheet(story: dict, looks: list, cid: str, lid: str, episode: int) -> dict:
    s = spec_face(story, looks, cid, episode)
    lk = p1_looks_of(looks, cid) or {}
    look = next((l for l in lk.get("looks") or [] if l.get("id") == lid), None) or {}
    slots = _slots(look.get("zh"))
    if "或" in (slots.get("鞋") or ""):
        # 总调度 11-03（P1 world.rules“凡穿 O4 的集鞋都是 SH1”）：造型表写“SH1 或 SH2”时，鞋按 P1 排期（schedule）定——
        # 本集排期里含这套造型的那条 shoes；本集没排到就看这套造型在排期里是否只配过一种鞋。设定图只出一双鞋，不让模型二选一
        rows = [r for r in (lk.get("schedule") or []) if lid in str(r.get("outfit") or "").split("+") and r.get("shoes")]
        here = [r["shoes"] for r in rows if int(r.get("episode") or 0) == int(episode or 0)]
        uniq = sorted({r["shoes"] for r in rows})
        pick = here[0] if here else (uniq[0] if len(uniq) == 1 else None)
        if pick:
            slots["鞋"] = pick
    wear = "、".join(v for k, v in slots.items() if v and v != "无")
    feats = s["desc"].split("，", 1)[1].rsplit("，", 1)[0]
    img = (FULLBODY + f"成年{s['sex']}{s['name']}，{s['age']}岁，{feats}，穿{wear or '日常便装'}，表情平静，真实皮肤质感" + NEUTRAL)
    return {**s, "look": lid, "slots": slots, "en": look.get("en") or "", "img": img, "framing": "fullbody"}


def spec_scene(story: dict, sid: str) -> dict:
    sc = p1_scene(story, sid)
    if not sc:
        raise RuntimeError(f"P1 场景表里没有 {sid}")
    tod, light = str(sc.get("time_of_day") or "").strip(), str(sc.get("light") or "").strip()
    img = (f"空镜，无人物，{sc.get('name') or sid}：{sc.get('space') or ''}，"
           f"{'陈设：' + sc['fixtures'] + '，' if sc.get('fixtures') else ''}画面里没有人，无文字无标识")
    return {"scene_id": sid, "name": sc.get("name"), "space": sc.get("space"), "light": light,
            "time_of_day": tod, "fixtures": sc.get("fixtures"), "img": img,
            "suffix": scene_suffix(tod, light), "negative": EMPTY_NEGATIVE}


PERSON_WORDS = ("发丝", "头发", "人物", "皮肤", "脸", "她", "他", "身体", "模特")
EMPTY_NEGATIVE = "人物，人，人影，模特，人体，脸，手，皮肤，剪影，倒影里的人，文字，标识，水印"


# ------------------------------------------------------------------ 单品图规格（W9 ASSET-ITEMS 11-03）
# 根因（10 条 item 作业连续不过检）：① 提示词只写“只拍这一件：<P1 原文>”，P1 原文里带穿戴位置（“右手腕缠两圈的…”）、
# 指甲这种离不开手的部件、甚至“无”/ 项目方单品编号（“SH1 或 SH2”）——模型照着画手、画人；② 编译走剧情镜模式，
# 镜头语言 + L-110 融合句（“人物和环境一起清楚…环境光染到皮肤和衣服上”）整段进了单品提示词，图里必然出模特。
# 改法：按部件类别写成物件图（复用 V1 tools/gen_assets_items.py 的产品图 / 平铺 / 珠宝微距三种写法，只换成纯白底），
# 颜色和材质从 P1 造型原文的这一件里取，写进提示词和看图核对；“无”/ 项目方编号不出图（C-23：以项目方指定为准）。
ITEM_RULE = 4            # 规格版本：旧版的失败作业由 asset_worker 按新规格重排一次（1 = 只拍这一件：<原文>；2 = 提示词带“品牌”二字被 preflight I13 拦，04:54 上线过一拍；3 = 一套几件按“都是皮”核材质 + Q9 对零人单品报 extra_person，04:56–05:0x 跑过）
ITEM_NEGATIVE = EMPTY_NEGATIVE + "，模特，人台，假人，衣架上的人形，手指，手臂，手腕，腿，脚，字母，logo"   # 不写“品牌”二字：preflight I13（K-REN-959）
NO_ITEM_LABELS = ("", "无", "没有", "none", "-", "—")
OWNER_CODE_RE = re.compile(r"^\s*[A-Z]{1,3}\d+(\s*(或|/|、|or)\s*[A-Z]{1,3}\d+)*\s*$")     # “SH1 或 SH2”：项目方单品编号
WEAR_POS_RE = re.compile(r"^[左右双两]?(?:手腕|手指|手上|脚踝|脖子|颈间?|腰间?|肩上?|耳朵?|头上|发间)[^的，、]{0,8}的")
COLOR_RE = re.compile(r"(?:酒红|驼|黑|白|银灰|银|金|红|鲜红|深灰|灰|藏青|蓝|绿|粉|米|棕|咖啡|透明|裸)色?")
MATERIAL_WORDS = ("漆皮", "皮质", "皮", "丝绒", "缎面", "丝质", "真丝", "棉质", "羊绒", "针织", "牛仔", "金属", "亮片", "蕾丝", "网纱")
# V1 tools/gen_assets_items.py 的三种物件写法（PRODUCT / 平铺 / JEWEL），背景统一换成纯白（看图核对要求纯白或纯色）
ITEM_STYLE = {
    "product": "专业电商产品摄影，商品完整居中入画，纯白无缝背景，柔和箱灯，材质与缝线细节清晰",
    "flat": "服装平铺俯拍：衣物平放在纯白台面上展开摆好，只有衣服本身，没有人穿，没有人台，没有挂在人形上",
    "jewel": "饰品产品微距摄影，单独平放在纯白台面上，柔和箱灯，金属与材质反光清晰",
}
ITEM_TAIL = "画面中没有人、没有模特、没有人台、没有手和任何人体部位、没有人脸，表面光洁、没有任何标志、字母和文字"


NO_ITEM_COUNT_RE = re.compile(r"^(?:0|〇|零)\s*(?:件|个|样|款|双|套)$")     # A9 P1-①：script_v2 措辞“饰品: 0件”
OWNER_REF_RE = re.compile(r"[（(][^）)]*(?:参考照|参考图|项目方)[^）)]*[）)]")       # “（全身参考照）”：这件以项目方给的照片为准（C-23）
OWNER_SRC_RE = re.compile(r"项目方")                                                  # 清单单品 source / by 里写了项目方 = 项目方上传 / 指定


def no_item(label: str) -> str | None:
    """这一件不该出单品图的原因（None = 该出）：“无”/“0件”= 没有这件；项目方单品编号 = 用项目方的图（C-23），不重画"""
    s = str(label or "").strip()
    s0 = s.strip("。.；;，, ")
    if s.lower() in NO_ITEM_LABELS or s0.lower() in NO_ITEM_LABELS or NO_ITEM_COUNT_RE.match(s0):
        return f"P1 造型里这一项写的是“{s or '空'}”，没有这件单品，不需要单品图"
    if OWNER_CODE_RE.match(s):
        return f"P1 造型里这一项是项目方单品编号“{s}”，用项目方给的单品图（C-23），不出新图"
    return None


def item_object(label: str) -> str:
    """P1 部件原文 → 物件本身的叫法：去掉穿戴位置（“右手腕缠两圈的黑色相机皮带”→“黑色相机皮带”）和括注"""
    s = re.sub(r"[（(][^）)]*[）)]", "", str(label or "")).strip()
    s2 = WEAR_POS_RE.sub("", s).strip()
    return s2 or s


def item_traits(obj: str) -> dict:
    """物件叫法里的颜色 / 材质词（给提示词强调 + 看图核对“颜色材质对不对”）"""
    colors = list(dict.fromkeys(m.group(0) for m in COLOR_RE.finditer(obj) if len(m.group(0)) > 0))
    mats, rest = [], obj
    for w in MATERIAL_WORDS:
        if w in rest:
            mats.append(w)
            rest = rest.replace(w, "")
    return {"colors": colors, "materials": mats}


def item_render_fields(label: str, slot: str) -> dict:
    """单品图规格（img / suffix / negative / object / traits / style / item_rule）：按部件类别写成物件图"""
    obj = item_object(label)
    slot = {"服装": "outfit", "鞋": "shoes", "饰品": "accessory", "指甲": "nails"}.get(slot, slot)
    if slot == "nails":
        tr = item_traits(obj)
        col = "".join(tr["colors"][:1]) or ""
        long_ = "长款" if "长" in obj else ""
        subject = f"一套{col}{long_}穿戴甲片（假指甲片，共十片）整齐排成一排，只有甲片本身，没有手、没有手指"
        style = "product"
    elif slot == "outfit":
        pieces = [x.strip() for x in re.split(r"[、+＋,，]", obj) if x.strip()]
        subject = ("、".join(pieces) if len(pieces) > 1 else obj) + ("（整套几件分开平铺在一起）" if len(pieces) > 1 else "")
        style = "flat"
    elif slot == "shoes":
        subject = f"一双{obj}，四分之三侧面角度并排摆放"
        style = "product"
    else:
        subject = f"{obj}，只有这一件"
        style = "jewel" if any(w in obj for w in ("链", "镯", "戒", "耳", "项", "表", "甲")) else "product"
    tr = item_traits(obj)
    stress = ("，颜色：" + "、".join(tr["colors"]) if tr["colors"] else "") + ("，材质：" + "、".join(tr["materials"]) if tr["materials"] else "")
    img = f"单品物件图：{subject}{stress}。{ITEM_STYLE[style]}，{ITEM_TAIL}"
    return {"img": img, "object": obj, "traits": tr, "item_style": style, "item_rule": ITEM_RULE,
            "suffix": scene_suffix("", "影棚均匀柔光"), "negative": ITEM_NEGATIVE}


def item_checks(spec: dict) -> list[str]:
    """单品图的物件契约（看图逐条；OCR / 年龄另算）：无人 / 无人脸、单一物件、颜色材质对、纯白底无标志"""
    obj = spec.get("object") or item_object(spec.get("label") or "")
    tr = spec.get("traits") or item_traits(obj)
    nails = (spec.get("slot") or "") == "nails"
    what = f"一套穿戴甲片（假指甲片）：{obj}" if nails else obj
    out = ["画面里没有人、没有模特、没有人台，也没有手、手臂、腿、人脸等任何人体部位",
           f"画面主体只有这一样东西：{what}（一套服装的几件算一样），没有别的物品"]
    pieces = [x.strip() for x in re.split(r"[、+＋,，]", obj) if x.strip()]
    if len(pieces) > 1:                    # 一套几件：逐件对颜色材质（不能问“几件都是皮”——T 恤、工装裤本来不是皮）
        out.append("每一件的颜色和材质都和它的名字对得上：" + "；".join(pieces))
    elif tr.get("colors") or tr.get("materials"):
        out.append("这件东西的" + "，".join(x for x in (("颜色是" + "、".join(tr["colors"])) if tr.get("colors") else "",
                                                     ("材质看起来是" + "、".join(tr["materials"])) if tr.get("materials") else "") if x))
    out.append("背景是纯白或纯色，东西表面没有任何品牌标志、字母和文字")
    return out


def scene_suffix(time_of_day: str, light: str) -> str:
    """空镜 / 单品的系统后缀（ISS-1103-004550-8787）：不用人像风格后缀（“人物被闪光打亮 / 皮肤质感 / 夜里闪光灯”），
    时间和光线只从 P1 / P4 场景表取，句尾固定 = ns_agent.gen_contract.style.EMPTY_SUFFIX（preflight I7 在设定候选 scene / item 模式下认这一句）"""
    sys.path.insert(0, str(ROOT / "services" / "agent"))
    from ns_agent.gen_contract import style as ST   # noqa: PLC0415
    tod = {"日": "白天", "夜": "夜里", "晨": "清晨", "昏": "黄昏"}.get(time_of_day, time_of_day)
    light = "，".join(x for x in re.split(r"[，,；;]", light or "") if x.strip() and not any(w in x for w in PERSON_WORDS))   # “风机吹起发丝”这类带人的半句不进空镜
    head = "，".join(x for x in (f"时间：{tod}" if tod else "", f"光线：{light}" if light else "") if x)
    return (head + "，" if head else "") + ST.EMPTY_SUFFIX


# ------------------------------------------------------------------ 设定候选的一镜外壳（L-126：V2 不再拿 V1 夹具 frozen_v1_subset.json 当外壳）
V2_SHELL_NEGATIVE = "动漫脸、CGI感、娃娃脸、肢体变形、多余手指、未成年人外观、水印、字幕、画面文字"


def setting_script(run: str, source: str, img: str, detail: str, name: str | None = None, slots: dict | None = None,
                   en: str = "", desc: str = "") -> dict:
    """设定候选（身份脸 / 设定图 / 场景底图 / 单品）的一镜分镜（ns_schema.script.ScriptImport 的 dict）：从零写的 V2 中性外壳，
    没有任何 V1 人物锁 / 风格句 / LoRA / 场景；人物、造型、提示词全部来自作业 spec。asset_worker 与 tools/promptfix/cast_v2 共用"""
    slots = dict(slots or {})
    cast = [{"name": name, "presence": "在画", "x": "中", "depth": "中", "part": None, "raw": f"{name}（在画｜中｜中）"}] if name else []
    looks = [{"character": name, "from_shot": None, "slots": slots, "en": en or "", "raw": "｜".join(f"{k}={v}" for k, v in slots.items())}] if name else []
    shot = {"episode": 1, "index": 1, "img_prompt": img, "motion_prompt": "static shot，固定机位，目视前方", "img_triggers": [], "motion_triggers": [],
            "dialogue": [], "dialogue_raw": None, "cast": cast, "cast_raw": cast[0]["raw"] if cast else "", "scene_id": None, "scene_detail": detail,
            "h3_prompt": None, "adult": False, "adult_reasons": [], "link": None, "link_carry": None, "duration": 6, "source_line": 0}
    ep = {"number": 1, "title": f"{run} 设定候选", "high_intensity": False, "cast": [name] if name else [], "scene_ids": [], "looks": looks,
          "shots": [shot], "source_line": 0}
    g = {"character_locks": [{"name": name, "description": desc}] if name else [], "motion_suffix": "", "image_suffix": "",
         "base_negative": V2_SHELL_NEGATIVE, "lora_triggers": []}
    return {"sources": [{"path": source, "sha256": ""}], "globals": g, "episodes": [ep], "warnings": []}


def voice_role(cid: str) -> str:
    """char_id → voices_v2 的角色槽名（ch_zhuo_lin → zhuo_lin，与 VOICE-S 已有的槽名一致）"""
    return cid[3:] if cid.startswith("ch_") else cid


def spec_voice(story: dict, cid: str) -> dict:
    c = p1_char(story, cid)
    if not c:
        raise RuntimeError(f"P1 人物表里没有 {cid}")
    sex, age, name = _sex(c.get("gender")), int(c.get("age") or 0), c["name"]
    vp = str(c.get("voice_phrase") or "").strip()
    g = "female" if sex == "女性" else "male"
    zh_sex = "女性" if g == "female" else "男性"
    role = voice_role(cid)
    persona = f"{age} 岁{c.get('role') or ''}：{vp}（P1 voice_phrase）"
    cands = [
        ["a", "普通话（标准）", "std", f"{g}, {age} years old, {vp}, standard Mandarin"],
        ["b", "上海口音普通话 + 沪语词（ref）", "wu", f"{zh_sex}，{age}岁，{vp}，说带上海口音的普通话，吴语腔调，语速自然"],
        ["c", "上海口音普通话 + 沪语词（ref）", "wu", f"{zh_sex}，{age}岁，{vp}，说带明显上海口音的普通话，沪语味重，时髦利落"],
    ]
    return {"cid": cid, "name": name, "role": role, "gender": g, "label": f"{name} · {role}（配角，待选）", "persona": persona, "cands": cands}


# ------------------------------------------------------------------ pick id
LEGACY_PICK_RE = re.compile(r"^v2cast-([A-Za-z0-9_]+)$")      # CAST-S 11-03 投的 4 条（v2cast-<cid|scene_id>），处理器要能直接消费


def pick_object(item_id: str) -> tuple[str, list[str]]:
    """pick id → (kind, 对象各段)。pick:<kind>:<a>[:<b>]；旧式 v2cast-<对象>：ch_* = face，sk_* = scene"""
    s = str(item_id or "")
    m = LEGACY_PICK_RE.match(s)
    if m:
        obj = m.group(1)
        return ("scene" if obj.startswith("sk_") else "face"), [obj]
    parts = s.split(":")
    if len(parts) >= 3 and parts[0] == "pick":
        return parts[1], parts[2:]
    return "", []


def existing_pick(root: Path, kind: str, target: str) -> dict | None:
    """requests.json 里已经有这个对象的 pick（别的 agent 投的，如 CAST-S）→ 作业直接接管它，不再出候选"""
    p = requests_path(root)
    if not p.is_file():
        return None
    rows = _read_json(p, "待办通知 requests.json")
    rows = rows.get("items") if isinstance(rows, dict) else rows
    for r in rows or []:
        if not isinstance(r, dict) or r.get("kind") != "pick":
            continue
        k, obj = pick_object(str(r.get("id")))
        k = {"voice_v2": "voice", "image": "face"}.get(k, k)
        if k == kind and ":".join(obj) == target and any(isinstance(c, dict) and c.get("contract_ok") for c in r.get("candidates") or []):
            return r
    return None


# ------------------------------------------------------------------ 缺口 → 作业
def _cid_of(who: str) -> str | None:
    m = _CID_RE.search(str(who or ""))
    return m.group(1) if m else None


def _item_spec(what: str, name_to_cid: dict) -> dict | None:
    """“<名> 造型<lid> 的<部位>“<label>”没有图” → {cid, look, slot_label, label}"""
    m = re.match(r"^(.+?)\s*造型(\S+?)\s*的(.+?)“(.+?)”没有图", str(what or ""))
    if not m:
        return None
    name, lid, slot_label, label = m.groups()
    cid = name_to_cid.get(name.strip())
    if not cid:
        return None
    return {"cid": cid, "name": name.strip(), "look": lid, "slot_label": slot_label, "label": label}


def plan_from_gap(gap: dict, story: dict, looks: list, episode: int) -> dict | None:
    """一个缺口 → (kind, job_id, target, spec)；不是资产线能自动补的（写手 / 总调度的）→ None"""
    k, who, what = gap.get("kind"), gap.get("who") or "", gap.get("what") or ""
    n2c = p1_name_to_cid(story)
    if k == "face":
        cid = _cid_of(who) or n2c.get(who)
        return cid and {"kind": "face", "id": f"face-{cid}", "target": cid, "spec": spec_face(story, looks, cid, episode)}
    if k == "scene":
        return {"kind": "scene", "id": f"scene-{who}", "target": who, "spec": spec_scene(story, who)}
    if k == "name":
        cid = _cid_of(who) or n2c.get(who)
        c = cid and p1_char(story, cid)
        return c and {"kind": "meta", "id": f"meta-name-{cid}", "target": cid, "spec": {"op": "name", "cid": cid, "display_name": c["name"]}}
    if k == "schedule":
        cid = _cid_of(who) or n2c.get(who)
        lid = cid and look_for_episode(p1_looks_of(looks, cid), episode)
        return lid and {"kind": "meta", "id": f"meta-schedule-{cid}", "target": cid, "spec": {"op": "schedule", "cid": cid, "look": lid}}
    if k == "voice":
        cid = _cid_of(who)
        if not cid or "不在人物表" in what or "读不出来" in what:
            return None                                  # 说话人不在人物表 = 写手 / 清单别名的事；配置坏 = 总调度
        return {"kind": "voice", "id": f"voice-{cid}", "target": cid, "spec": spec_voice(story, cid)}
    if k == "look":
        cid = _cid_of(who) or n2c.get(who.split("（")[0])
        if not cid:
            return None
        lk = p1_looks_of(looks, cid)
        lid = look_for_episode(lk, episode)
        if what.endswith("没有设定图"):
            m = re.search(r"造型(\S+?)\s*没有设定图", what)
            lid2 = m.group(1) if m else lid
            if not lid2:
                return None
            return {"kind": "sheet", "id": f"sheet-{cid}-{lid2}", "target": f"{cid}:{lid2}", "spec": spec_sheet(story, looks, cid, lid2, episode)}
        if "对不上 P1 登记" in what and lk and lid:          # 清单里没登记这个人的造型 → 从 P1 造型表写骨架 + 本集排期
            l = next((x for x in lk.get("looks") or [] if x.get("id") == lid), None) or {}
            return {"kind": "meta", "id": f"meta-looks-{cid}", "target": cid,
                    "spec": {"op": "looks", "cid": cid, "look": lid, "looks": [
                        {"id": x.get("id"), "zh": x.get("zh"), "en": x.get("en"), "use": x.get("use"), "slots": _slots(x.get("zh"))}
                        for x in lk.get("looks") or [] if x.get("id")], "name": _slots(l.get("zh")).get("服装") or lid}}
        return None
    if k == "item":
        it = _item_spec(what, n2c)
        if not it or no_item(it["label"]):               # “无”/ 项目方编号：不是资产线出图的事（W9）
            return None
        return {"kind": "item", "id": f"item-{it['cid']}-{it['look']}-{it['slot_label']}", "target": f"{it['cid']}:{it['look']}:{it['label']}",
                "spec": {**it, "slot": it["slot_label"], **item_render_fields(it["label"], it["slot_label"])}}
    return None


def _new_job(run: str, episode: int, plan: dict, gap: dict) -> dict:
    return {"schema": SCHEMA, "id": plan["id"], "run": run, "episode": episode, "episodes": [episode], "kind": plan["kind"], "target": plan["target"],
            "who": gap.get("who"), "what": gap.get("what"), "owner": gap.get("owner"), "shots": list(gap.get("shots") or []),
            "state": "pending", "attempts": 0, "created_at": _now(), "updated_at": _now(), "spec": plan["spec"], "candidates": [],
            "pick_id": PICK_PREFIX[plan["kind"]] + (voice_role(plan["target"]) if plan["kind"] == "voice" else plan["target"]) if plan["kind"] in PICK_PREFIX else None,
            "log": [f"{_now()} 由 episode_ready 缺口生成"]}


def _checker():
    import importlib.util as _u
    sp = _u.spec_from_file_location("episode_ready_for_jobs", ROOT / "tools" / "master" / "episode_ready.py")
    m = _u.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m.check


FIRST_FRAME_KINDS = ("face", "name", "schedule", "look", "item", "scene", "script")   # = episode_ready.FIRST_FRAME_KINDS（音色不挡首帧）


def shot_gaps(res: dict) -> dict[str, list[str]]:
    """L-202（资产就绪按镜判）：episode_ready 缺口 → {"镜号": [缺口…]}，没写镜号的缺口记在 "*"（挡全部镜，失败关闭）。
    写进 _ready_epNN.json shot_gaps，sop_gate.check_assets(shot) 只看本镜这一段；不另算缺口，口径仍是 episode_ready.check"""
    out: dict[str, list[str]] = {}
    for g in res.get("gaps") or []:
        if g.get("kind") not in FIRST_FRAME_KINDS:
            continue
        label = f"[{g.get('kind')}] {g.get('who')}：{g.get('what')}"
        for n in (g.get("shots") or ["*"]):
            out.setdefault(str(n), []).append(label)
    return out


def generate(run: str, episode: int, root: Path = ROOT, res: dict | None = None, check=None) -> dict:
    """缺口 → 作业文件（幂等）。返回 {ready, gaps, created, existing, skipped, golden, shot_gaps}"""
    guard_run(root, run)
    res = res or (check or _checker())(run, episode)
    out = {"run": run, "episode": episode, "ready": bool(res.get("ready")), "gaps": len(res.get("gaps") or []),
           "created": [], "existing": [], "skipped": [], "reopened": [], "golden": None, "at": _now(),
           "shot_gaps": shot_gaps(res)}
    story, looks = ({}, [])
    if res.get("gaps"):
        try:
            story, looks = p1(root, run)
        except RuntimeError as e:
            out["error"] = str(e)
            return _write_ready(root, run, episode, out)
    live_ids, unplanned_kinds = set(), set()
    for g in res.get("gaps") or []:
        try:
            plan = plan_from_gap(g, story, looks, episode)
        except RuntimeError as e:
            out["skipped"].append({"gap": g.get("who"), "why": str(e)[:160]})
            unplanned_kinds.add(g.get("kind"))
            continue
        if plan:
            live_ids.add(plan["id"])
        if not plan:
            out["skipped"].append({"gap": f"{g.get('who')}：{g.get('what')}"[:120], "why": f"不是资产线能自动补的（{g.get('owner')}）"})
            continue
        p = job_path(root, run, plan["id"])
        if p.is_file():
            job = load_job(p)
            changed = False
            if episode not in (job.get("episodes") or []):
                job.setdefault("episodes", []).append(episode)
                changed = True
            if job.get("state") == "done" and job.get("kind") == "meta":      # 写过了缺口还在 = 写失败 / 被人改回；重排
                job.update(state="pending", attempts=0)
                log(job, "登记后缺口仍在，重新排队")
                out["reopened"].append(job["id"])
                changed = True
            if changed:
                save_job(root, job)
            out["existing"].append(job["id"])
            continue
        job = _new_job(run, episode, plan, g)
        ex = existing_pick(root, plan["kind"], voice_role(plan["target"]) if plan["kind"] == "voice" else plan["target"]) if plan["kind"] in PICK_PREFIX else None
        if ex:
            job.update(state="awaiting_pick", pick_id=str(ex["id"]), candidates=[{"key": c.get("key"), "file": c.get("file"), "passed": True, "label": c.get("checks") or c.get("label")}
                                                                           for c in ex.get("candidates") or [] if isinstance(c, dict) and c.get("contract_ok")],
                       adopted_from=ex.get("by") or ex.get("source"))
            log(job, f"接管已有的待办通知 {ex['id']}（{ex.get('by') or ex.get('source')} 投的 {len(job['candidates'])} 个候选），不再出候选")
            out.setdefault("adopted", []).append(f"{job['id']} ← {ex['id']}")
        save_job(root, job)
        out["created"].append(job["id"])
    out["closed"] = close_stale(root, run, episode, live_ids, unplanned_kinds)
    if out["ready"]:
        out["golden"] = ensure_golden(root, run, episode, res)
    return _write_ready(root, run, episode, out)


GAP_KIND_OF_JOB = {"face": "face", "scene": "scene", "voice": "voice", "sheet": "look", "meta": None,
                   "item": "item"}            # W9：缺口生成的 item（没有 from_sheet）缺口不在了也收；设定图派生的照旧不动


def refresh_items(root: Path, run: str) -> dict:
    """W9：item 作业按新规格收拾一遍（asset_worker 每拍调）——
    ① P1 写“无”/ 项目方单品编号的（no_item）：pending / failed 一律收尾 done（closed_reason 写原因），不出图；
    ② 旧规格（spec.item_rule < ITEM_RULE）定案失败的：规格按新规则重写（物件图提示词 + 物件契约），attempts 清零重排一次；
       旧规格还没跑的 pending 也就地换规格。在跑 / 待选 / 已完成的不动。返回 {closed: [...], requeued: [...], respec: [...]}"""
    out = {"closed": [], "requeued": [], "respec": []}
    for j in list_jobs(root, run):
        if j.get("kind") != "item" or j.get("state") not in ("pending", "failed"):
            continue
        sp = j.get("spec") or {}
        why = no_item(sp.get("label"))
        if why:
            j.update(state="done", final=True, done_at=_now(), error=None, result={"closed_reason": why})
            log(j, f"不出图，收尾：{why}")
            save_job(root, j)
            out["closed"].append(j["id"])
            continue
        if int(sp.get("item_rule") or 1) >= ITEM_RULE:
            continue
        sp.update(item_render_fields(sp.get("label") or "", sp.get("slot") or sp.get("slot_label") or ""))
        j["spec"] = sp
        if j.get("state") == "failed":
            j.update(state="pending", attempts=0, error=None, final=False)
            log(j, f"单品规格按新规则（item_rule {ITEM_RULE}：物件图提示词 + 物件契约）重写，重排一次")
            out["requeued"].append(j["id"])
        else:
            log(j, f"单品规格按新规则（item_rule {ITEM_RULE}）重写")
            out["respec"].append(j["id"])
        save_job(root, j)
    return out


def close_stale(root: Path, run: str, episode: int, live_ids: set, unplanned_kinds: set) -> list[str]:
    """ISS-1103-011049-336c：缺口已经不在的 pending / failed 作业自动收尾（state=done，result.closed_reason），不再执行。
    只收本集独有、由缺口生成的作业（face / scene / voice / sheet / meta / 缺口生成的 item）；设定图派生的 item、golden、在跑 / 待选的不动；
    本拍有同类缺口规划失败时不收这一类（缺口可能还在，只是没规划出来）"""
    closed = []
    for j in list_jobs(root, run):
        k = j.get("kind")
        if k not in GAP_KIND_OF_JOB or j.get("state") not in ("pending", "failed") or j.get("id") in live_ids:
            continue
        if (j.get("spec") or {}).get("from_sheet") or (j.get("episodes") or [j.get("episode")]) != [episode]:
            continue
        gk = GAP_KIND_OF_JOB[k]
        if (gk and gk in unplanned_kinds) or (k == "meta" and unplanned_kinds & {"name", "look", "schedule"}):
            continue
        j.update(state="done", final=True, done_at=_now(), error=None, result={"closed_reason": "缺口已不在（episode_ready 本拍没有这一项），自动收尾，不执行"})
        log(j, "缺口已不在，自动收尾")
        save_job(root, j)
        closed.append(j["id"])
    return closed


def _write_ready(root: Path, run: str, episode: int, out: dict) -> dict:
    atomic_json(jobs_dir(root, run) / f"_ready_ep{episode:02d}.json", out)
    return out


def ensure_golden(root: Path, run: str, episode: int, res: dict) -> dict:
    """阶段 B 交接（W6 11-03，L-151）：阶段 B 金样走 producer（tools/autopilot/producer.py），资产线不再生成整集 golden-epNN 作业
    （旧执行器 golden_v2 --render 不再接）。这里只把“本集资产全部就绪、可交 producer”记进 _ready_epNN.json 的 golden 字段；
    历史的 golden-epNN.json 不删，W6b 11-03 已手工标 state=retired（不执行、不进心跳 golden_pending），这里只在返回里标出来"""
    jid = f"golden-ep{episode:02d}"
    shots = [s["index"] for s in res.get("shots") or [] if not s.get("adult")]
    return {"ready_for": "producer", "ledger": "L-151", "at": _now(), "shots": shots,
            "adult_skipped": [s["index"] for s in res.get("shots") or [] if s.get("adult")],
            "legacy_job": jid if job_path(root, run, jid).is_file() else None,
            "note": "资产线只记录，不生成 golden 作业；阶段 B 由 producer 接"}


# ------------------------------------------------------------------ 待办通知（pick 请求）
def requests_path(root: Path) -> Path:
    return root / "data" / "owner_queue" / "requests.json"


def post_pick(root: Path, job: dict, cands: list[dict], title: str, detail: str, recommend: str | None = None, why: str = "") -> str:
    """按 owner_queue 现有格式投一条 pick（经 owner_pick.enqueue_pick；同 id 已有则替换）。候选：{key,label,contract_ok,file,thumb,score}"""
    guard_run(root, job["run"])
    rid = job["pick_id"]
    req = {"id": rid, "kind": "pick", "title": title, "detail": detail, "source": "ASSET-WORKER（阶段 A 资产作业）", "by": "ASSET-WORKER",
           "at": _now(), "run": job["run"], "episode": job["episode"], "job": job["id"], "candidates": cands,
           "recommend": recommend or (cands[0]["key"] if cands else None), "why": why or "系统推荐（契约全过，按顺序第一张）", "apply": "none",
           "link": job.get("review_page")}
    _owner_pick().enqueue_pick(root, req)
    return rid


# ------------------------------------------------------------------ 派生资产自动选用（总调度 11-03：项目方已睡、目标全自动）
# L-139：派生资产（sheet / item）代选模式开着时系统按分数自动登记，可修改。
# L-198（11-05 21:5x，项目方“你可以全自动……8 小时内做完”）：黎岸 / 周序 身份脸、造型、场景底图也由系统按分代选（W-ASSETS 11-06 加 face / scene）。
# 仍只在代选开着且没到期时生效（delegate_active）；代选关着照旧投 #/queue 等项目方挑；成人 / 删除 / 花钱 / 推翻旧决定永不代
AUTO_PICK_KINDS = ("face", "scene", "sheet", "item")
AUTO_BY = "系统自动（派生资产，按分数选用）"
AUTO_DETAIL = {
    "face": "{who}的身份脸按 L-198 由系统代选：候选都过了人数 / 成年 / 无裸露 / 五官与 OCR，系统按分数（看图逐项通过率）选用了 {label}，"
            "已登记进清单、造型设定图随即开出。想换就点别的候选“用这个”（下游设定图 / 单品会重做）；点的就是这张 = 确认；不合适点“修改”写一句意见。",
    "scene": "{who}的场景底图按 L-198 由系统代选：候选都过了空镜契约与看图核对，系统按分数选用了 {label}，已登记、流程继续。"
             "想换就点别的候选“用这个”；点的就是这张 = 确认；不合适点“修改”写一句意见。",
}


def delegate_active(root: Path) -> tuple[bool, str]:
    """L-139（项目方 11-03 03:1x）：设定图 / 单品裁图只在代选模式开着且没到期时自动选用；平时投 #/queue 等项目方挑。
    判断用 DELEGATE-O 的接口 ns_api.owner_delegate.active（顺带做到期检查）；载不进来就读 config/pipeline/owner_delegate.json（失败关闭）"""
    try:
        sp = str(ROOT / "services" / "api")
        if sp not in sys.path:
            sys.path.insert(0, sp)
        from ns_api import owner_delegate as OD   # noqa: PLC0415
        ok, why = OD.active(root)
        return bool(ok), str(why or "")
    except ImportError:
        pass
    p = root / "config" / "pipeline" / "owner_delegate.json"
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):   # arch-ok: 读不出 = 代选没开（失败关闭：投待办等项目方挑）
        return False, "owner_delegate.json 读不出"
    exp = d.get("expiry") or {}
    if d.get("enabled") and d.get("enabled_at") and not exp.get("expired_at"):
        return True, ""
    return False, exp.get("expired_reason") or "代选没开"


def auto_pick(root: Path, job: dict, cands: list[dict], who: str, what: str, pusher=None) -> dict:
    """候选过检后：按 score（身份余弦 + VLM 逐项通过率）自动登记最好的一张；inbox 只发一条“已自动选用，可修改”的告知
    （仍是同一个 pick：项目方点别的候选 = 换成那张，register_pick 走替换，下游自动重做）"""
    best = max(cands, key=lambda c: float(c.get("score") or 0))
    title = f"已自动选用：{who} {what}（{best.get('label')}），可修改"
    if job.get("kind") in AUTO_DETAIL:                      # L-198：身份脸 / 场景底图（W-PICK 11-07：项目方点别的候选 = 替换，下游重做）
        detail = AUTO_DETAIL[job["kind"]].format(who=who, label=best.get("label"))
    else:
        detail = (f"{who}的{what}是派生资产（身份脸和 P1 造型已定），系统按分数（身份相似度 + 看图逐项通过率）自动选用了 {best.get('label')}，已登记、流程继续。"
                  f"想换就点别的候选“用这个”，下游（单品裁图等）会自动重做；不合适点“修改”写一句意见。")
    guard_run(root, job["run"])
    req = {"id": job["pick_id"], "kind": "pick", "title": title, "detail": detail, "source": "ASSET-WORKER（阶段 A 资产作业）", "by": "ASSET-WORKER",
           "at": _now(), "run": job["run"], "episode": job["episode"], "job": job["id"], "candidates": cands, "recommend": best["key"],
           "why": "系统按分数自动选用", "apply": "none", "link": job.get("review_page"), "auto_picked": best["key"], "notice": True}
    _owner_pick().enqueue_pick(root, req)
    res = register_pick(root, job["kind"], req, best["key"], AUTO_BY, pusher=pusher)
    res["pick_id"] = req["id"]
    after_pick(root, job["kind"], res)
    return {"picked": best["key"], "score": best.get("score"), "file": res.get("file"), "sha256": res.get("sha256")}


def _replace_ok(entry: dict | None) -> bool:
    """已登记的是系统自动选用的派生资产 → 系统 / 代选也可以换它（项目方本人的选择任何时候都能换，见 may_replace）"""
    return bool(entry and str(entry.get("picked_by") or "").startswith("系统自动"))


NON_OWNER_BY = ("系统自动", "总调度代选", "POLICY", "ASSET-WORKER", "delegate")


def is_owner_by(by: str | None) -> bool:
    """by 是项目方本人（登录会话名）而不是系统 / 代选 / 自动裁图"""
    return bool(by) and not str(by).startswith(NON_OWNER_BY)


def may_replace(old: dict | None, by: str) -> bool:
    """W-PICK 11-07（项目方 11-07 01:1x“点了好几次没记录”）：已登记的东西谁能换——项目方本人的选择永远赢；
    系统 / 代选只能换系统自动选用的那张，不能推翻项目方或代选登记的"""
    return is_owner_by(by) or _replace_ok(old)


def run_writable(root: Path, run: str) -> None:
    """冻结 / 归档的剧不改资产（runs.json status），失败关闭并说清楚"""
    try:
        st = (((json.loads((root / "config" / "pipeline" / "runs.json").read_text(encoding="utf-8")).get("runs") or {}).get(run) or {}).get("status"))
    except (OSError, ValueError):   # arch-ok: 读不出登记表 = run_for_pick 已经会拒绝，这里不重复判
        return
    if st in ("frozen", "archived"):
        raise RegisterError(f"这部剧（{run}）已{'冻结' if st == 'frozen' else '归档'}，资产不再改；要改先在 runs.json 解冻")


QUARANTINE_TAG = "pick_replace"
_REG_LOCK = threading.RLock()     # 同一进程里并发的挑选（FastAPI 后台任务线程池）逐条写清单，不再互相撞（11-06 PermissionError）


def _live_files(d) -> list[str]:
    """清单里在用的 file（不含 replaced / items_replaced / sheets_replaced 历史）"""
    out = []
    if isinstance(d, dict):
        for k, v in d.items():
            if k in ("replaced", "items_replaced", "sheets_replaced"):
                continue
            if k == "file" and isinstance(v, str):
                out.append(v)
            else:
                out += _live_files(v)
    elif isinstance(d, list):
        for v in d:
            out += _live_files(v)
    return out


def retire(root: Path, d: dict, old: dict, why: str, moved: list) -> dict:
    """被替换的登记 → replaced[] 的一条历史；旧文件移进 data/_quarantine/<时间>_pick_replace/<原路径>（不删）。
    清单里别处还在用同一个文件就不移。moved 收集 (隔离路径, 原路径)，写清单失败时 unretire 回滚"""
    hist = {k: v for k, v in old.items() if k != "replaced"}
    hist.update(replaced_at=_now(), replaced_why=why)
    rel = str(old.get("file") or "")
    src = root / rel
    if rel and src.is_file() and _live_files(d).count(rel) <= 1:
        q = root / "data" / "_quarantine" / f"{time.strftime('%Y%m%d-%H%M%S')}_{QUARANTINE_TAG}" / rel
        while q.exists():
            q = q.with_name(f"{q.stem}_{len(moved) + 1}{q.suffix}")
        q.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(q))
        moved.append((q, src))
        qrel = str(q.relative_to(root)).replace(os.sep, "/")
        hist.update(file=qrel, original_file=rel, quarantined_to=qrel)
    return hist


def unretire(moved: list) -> None:
    for q, src in reversed(moved):
        if Path(q).is_file() and not Path(src).exists():
            shutil.move(str(q), str(src))


def _retire_sheets_of_face(d: dict, cid: str, new_file: str) -> list[str]:
    """换了身份脸 = 这个人往下全部换人（清单部分）：已登记的造型设定图移到 looks[lid].sheets_replaced（文件不动），
    从它们裁出的单品一并移到 items_replaced。返回退掉的造型 id"""
    looks = (((d.get("characters") or {}).get(cid) or {}).get("looks") or {})
    out = []
    for lid, lk in looks.items():
        sh = (lk or {}).get("sheet") if isinstance(lk, dict) else None
        if not (sh or {}).get("file"):
            continue
        lk.setdefault("sheets_replaced", []).append({**lk.pop("sheet"), "replaced_at": _now(), "replaced_why": f"身份脸换成 {new_file}"})
        _retire_items_of_sheet(lk, sh["file"])
        out.append(lid)
    return out


def _requeue_sheets_of_face(root: Path, run: str, cid: str, old_file: str, new_file: str) -> list[str]:
    """（作业部分，清单写成功后才做）该人的 sheet 作业重新排队：asset_worker 派 sheet 时送新脸（registered_face），
    新设定图登记后单品照常从新图裁"""
    redo = []
    for j in list_jobs(root, run):
        if j.get("kind") == "sheet" and (j.get("spec") or {}).get("cid") == cid and j.get("state") != "retired":
            j.update(state="pending", attempts=0, final=False, error=None, candidates=[])
            log(j, f"身份脸换成 {new_file}（原 {old_file}），设定图按新脸重出")
            save_job(root, j)
            redo.append(j["id"])
    return redo


def _retire_items_of_sheet(lk: dict, old_file: str) -> list[str]:
    """（清单部分）从旧设定图裁出的单品移到 items_replaced；项目方本人挑定的单品不是从旧图裁的，不动"""
    items = lk.get("items") or {}
    gone = [k for k, v in items.items() if isinstance(v, dict) and v.get("source") == old_file]
    for iid in gone:
        lk.setdefault("items_replaced", []).append({**items.pop(iid), "iid": iid, "replaced_at": _now()})
    return gone


def _requeue_items_of_sheet(root: Path, run: str, lk: dict, old_file: str, new_entry: dict) -> list[str]:
    """（作业部分，清单写成功后才做）从旧设定图裁的 item 作业改指新设定图、重新排队（先裁，裁不出再出候选）；
    这件单品已由项目方本人挑定的，作业不重排"""
    items = lk.get("items") or {}
    redo = []
    for j in list_jobs(root, run):
        sp = j.get("spec") or {}
        if (j.get("kind") == "item" and (sp.get("from_sheet") or {}).get("file") == old_file
                and not is_owner_by((items.get(sp.get("iid")) or {}).get("picked_by"))):
            sp["from_sheet"] = {"file": new_entry["file"], "sha256": new_entry["sha256"]}
            sp.pop("crop_failed", None)
            j.update(state="pending", attempts=0, final=False, error=None, spec=sp)
            log(j, f"设定图换成 {new_entry['file']}，重新裁")
            save_job(root, j)
            redo.append(j["id"])
    return redo


def _owner_pick():
    sp = str(ROOT / "services" / "api")
    if sp not in sys.path:
        sys.path.insert(0, sp)
    from ns_api import owner_pick as OP   # noqa: PLC0415
    return OP


# ------------------------------------------------------------------ 登记（项目方选定后，由 owner_pick 处理器调用）
class RegisterError(ValueError):
    """登记失败（中文原因，owner_pick 会把它转成 PickError 让条目带原因重新出现）"""


def manifest_path(root: Path, run: str) -> Path:
    mp = _runs_mod().asset_manifest(run, root)
    if not mp:
        raise RegisterError(f"{run} 不是资产包模式（runs.json 没写 assets_manifest），不能登记")
    return mp


def _read_manifest(mp: Path) -> tuple[dict, str]:
    raw = mp.read_bytes()
    d = json.loads(raw.decode("utf-8"))
    if not isinstance(d, dict):
        raise RegisterError(f"{mp} 不是 JSON 对象")
    return d, _sha(raw)


def _write_manifest(mp: Path, d: dict, sha0: str) -> str:
    if _sha(mp.read_bytes()) != sha0:
        raise RegisterError("资产清单在处理途中被别人改了，没写入；请再点一次")
    d["updated_at"] = _now()
    atomic_json(mp, d)
    return _sha(mp.read_bytes())


def push_files(root: Path, rels: list[str], hosts=("gpu33", "gpu36"), pusher=None) -> dict:
    """推到两台并核 sha：走 tools/factory/sync.py 的 verified_install（服务器端先核 sha 再原子替换；原文件先备份不删），
    然后由 FACTORY 的 sync.py auto（常驻每 10 分钟）做整个依赖闭包的补推。失败只记录，不回滚本地登记（本地清单是唯一来源）"""
    out = {}
    for host in hosts:
        try:
            out[host] = (pusher or _push_one)(root, host, rels)
        except Exception as e:  # noqa: BLE001  推送失败要带原因记下来（不吞），由调用方登记卡点
            out[host] = {"ok": False, "error": f"{type(e).__name__}: {e}"[:300]}
    return out


def push_enabled(root: Path) -> bool:
    """config/pipeline/asset_worker.json 的 push 开关（读不出 = 开，推送本身失败只记录）"""
    p = root / "config" / "pipeline" / "asset_worker.json"
    try:
        return bool(json.loads(p.read_text(encoding="utf-8")).get("push", True))
    except (OSError, ValueError):   # arch-ok: 没有配置 = 按默认开
        return True


def _push_one(root: Path, host: str, rels: list[str]) -> dict:
    sys.path.insert(0, str(ROOT / "tools" / "factory"))
    import sync as S    # noqa: PLC0415
    res = {}
    for rel in rels:
        data = (root / rel).read_bytes()
        dest = f"{S.PROD}/{rel}"
        bk = f"{S.PROD}/data/_factory_backup/{time.strftime('%Y%m%d-%H%M%S')}/{rel}"
        cmd = (f"mkdir -p $(dirname {dest}) && {{ [ -f {dest} ] && mkdir -p $(dirname {bk}) && cp -a {dest} {bk}; true; }} && "
               + S.verified_install(dest, data))
        res[rel] = S.rrun(host, cmd, data=data, timeout=600).strip().split()[0][:12]
    return {"ok": True, "sha": res}


def _cand_file(root: Path, req: dict, choice: str) -> tuple[dict, Path]:
    c = next((c for c in req.get("candidates") or [] if isinstance(c, dict) and str(c.get("key")) == str(choice)), None)
    if not c:
        raise RegisterError(f"没有候选 {choice}")
    if not c.get("contract_ok"):
        raise RegisterError(f"候选 {choice} 没过契约，不能登记")
    src = root / str(c.get("file") or "")
    if not c.get("file") or not src.is_file():
        raise RegisterError(f"候选 {choice} 的图不存在：{c.get('file')}")
    sha = _sha(src.read_bytes())
    if c.get("sha256") and sha != c["sha256"]:
        raise RegisterError(f"候选 {choice} 的图 sha 与作业登记不符，不登记")
    # 旧式候选（CAST-S v2cast-*）没写 sha256：先按现在的文件算出 sha，登记时拷贝后再核一次（AUTOFIX-O 11-03 P2）
    return {**c, "sha256": sha, "sha256_source": "candidate" if c.get("sha256") else "computed_at_register"}, src


def run_for_pick(root: Path, req: dict) -> tuple[str, dict | None]:
    """pick → (剧, 作业)。ISS-1103-004546-a997：剧优先取作业（find_job_by_pick）的 run，其次请求自己的 run；
    都拿不到 / 两者不一致 / 剧没登记 = 失败关闭。绝不回退 current_run()（00:38 就是回退到 series10_v1 导致 4 条登记全失败）"""
    pid = str(req.get("id") or "")
    want = req.get("run")
    job = (find_job_by_pick(root, pid, run=want) if want else None) or find_job_by_pick(root, pid)
    run = (job or {}).get("run") or want
    if not run:
        raise RegisterError(f"{pid} 找不到对应的资产作业，请求里也没写 run；不猜剧、不回退当前剧，不登记")
    if want and job and job.get("run") != want:
        raise RegisterError(f"{pid} 的作业属于 {job.get('run')}，请求写的是 {want}，不一致，不登记")
    if run not in registered_runs(root):
        raise RegisterError(f"{pid} 对应的剧 {run} 没在 runs.json 登记，不登记")
    return run, job


def register_pick(root: Path, kind: str, req: dict, choice: str, by: str, pusher=None, push: bool = True) -> dict:
    """CONTRACT（owner_pick）：选中 → 拷进资产包目录、写清单（file + sha256，其余候选 archived）、推两台并核 sha。
    face：characters[cid].face；scene：scenes[sid].base；sheet：characters[cid].looks[look].sheet；item：looks[look].items[<id>]
    已有登记时（W-PICK 11-07，项目方的选择永远赢）：
      · 选的就是现在这张（sha 相同）→ 成功、不改清单（noop“已是这张”）；
      · 不同 → 替换：旧 entry 进新 entry 的 replaced[]，旧文件移进 data/_quarantine/<时间>_pick_replace/（不删），新图登记并推两台，
        下游重做（sheet → 从旧图裁的单品重裁；face → 该人设定图全部重出，并登记卡点）。
        项目方本人可以换任何一张；系统 / 代选只能换系统自动选用的（may_replace）。冻结 / 归档的剧一律拒绝"""
    with _REG_LOCK:
        return _register_pick(root, kind, req, choice, by, pusher, push)


def _slot(d: dict, kind: str, obj: list, mdir: Path, choice: str, suffix: str, req: dict, job: dict | None) -> tuple[dict, str, Path, str]:
    """清单里这个对象的登记位：(holder, key, 新文件路径, 中文名)"""
    chars = d.setdefault("characters", {})
    if kind == "face":
        cid = obj[0]
        return chars.setdefault(cid, {}), "face", mdir / "characters" / cid / "face" / f"{cid}_face_{safe_name(choice)}{suffix}", f"{cid} 的身份脸"
    if kind == "scene":
        sid = obj[0]
        if not isinstance(d.get("scenes"), dict):
            d["scenes"] = {}
        return d["scenes"].setdefault(sid, {}), "base", mdir / "scenes" / sid / f"{sid}_base_{safe_name(choice)}{suffix}", f"场景 {sid} 的底图"
    if kind == "sheet":
        cid, lid = obj[0], obj[1]
        lk = chars.setdefault(cid, {}).setdefault("looks", {}).setdefault(lid, {"name": lid, "route": "server_ok", "adult": False, "items": {}})
        return lk, "sheet", mdir / "characters" / cid / "looks" / f"{cid}_{safe_name(lid)}_sheet_{safe_name(choice)}{suffix}", f"{cid} 造型 {lid} 的设定图"
    if kind == "item":
        cid, iid = obj[0], obj[1]
        jspec = (job or {}).get("spec") or {}
        lid = req.get("look") or (req.get("spec") or {}).get("look") or jspec.get("look")
        holder = chars.setdefault(cid, {})
        if lid:
            holder = holder.setdefault("looks", {}).setdefault(lid, {"name": lid, "route": "server_ok", "adult": False, "items": {}})
        return holder.setdefault("items", {}), iid, mdir / "characters" / cid / "items" / f"{safe_name(iid)}_{safe_name(choice)}{suffix}", f"{cid} 单品 {iid}"
    raise RegisterError(f"不认识的类型 {kind}")


def _register_pick(root: Path, kind: str, req: dict, choice: str, by: str, pusher=None, push: bool = True) -> dict:
    run, job = run_for_pick(root, req)
    run_writable(root, run)
    req = {**req, "run": run, "job": req.get("job") or (job or {}).get("id"), "episode": req.get("episode") or (job or {}).get("episode")}
    mp = manifest_path(root, run)
    c, src = _cand_file(root, req, choice)
    k2, obj = pick_object(str(req["id"]))
    if k2 != kind or not obj:
        raise RegisterError(f"pick id {req['id']} 不是 {kind} 类")
    d, sha0 = _read_manifest(mp)
    holder, key, dst, what = _slot(d, kind, obj, mp.parent, choice, src.suffix.lower(), req, job)
    old = holder.get(key) or {}
    base = {"run": run, "kind": kind, "picked_by": by, "object": ":".join(obj), "picked": choice, "pick_id": req["id"], "job": req.get("job"),
            "episode": req.get("episode")}
    if old.get("file"):
        if old.get("sha256") == c["sha256"]:          # 点的就是现在这张 = 确认，清单不动、不推
            return {**base, "file": old["file"], "sha256": old["sha256"], "confirmed": True, "noop": "已是这张",
                    "current_picked_by": old.get("picked_by"), "push": {"skipped": "已是这张，清单没变"}}
        if not may_replace(old, by):
            raise RegisterError(f"{what}已由{old.get('picked_by') or '别人'}登记（{old['file']}），{by} 不覆盖；只有项目方本人能换")
    moved: list = []
    try:
        hist = retire(root, d, old, f"{by} 改选候选 {choice}", moved) if old.get("file") else None
        rel = _copy_in(root, src, dst)
        entry = _entry(rel, root, c, by, req)
        if kind == "item":
            jspec = (job or {}).get("spec") or {}
            entry.update(slot=req.get("slot") or jspec.get("slot") or "item", name=req.get("item_name") or jspec.get("label") or key, no_brand=True)
        if hist:
            entry["replaced"] = (old.get("replaced") or []) + [hist]
        holder[key] = entry
        if kind == "face" and not holder.get("display_name"):       # 总调度 11-03：登记脸时一并写 display_name（来源 P1 人物表）
            try:
                story, _ = p1(root, run)
                pc = p1_char(story, obj[0])
            except RuntimeError:
                pc = None
            if not (pc and pc.get("name")):
                raise RegisterError(f"{obj[0]} 清单里没有 display_name，P1 人物表也查不到名字，不登记")
            holder["display_name"] = pc["name"]
        retired_items = _retire_items_of_sheet(holder, old["file"]) if (kind == "sheet" and hist) else []
        retired_sheets = _retire_sheets_of_face(d, obj[0], rel) if (kind == "face" and hist) else []
        sha1 = _write_manifest(mp, d, sha0)
    except Exception:
        unretire(moved)
        raise
    res = {**base, "file": rel, "sha256": _sha((root / rel).read_bytes()), "manifest_sha_before": sha0[:12], "manifest_sha_after": sha1[:12],
           "archived": [str(x.get("key")) for x in req.get("candidates") or [] if isinstance(x, dict) and str(x.get("key")) != str(choice)]}
    if hist:
        res["replaced"] = {"file": old["file"], "sha256": old.get("sha256"), "picked_by": old.get("picked_by"), "quarantined_to": hist.get("quarantined_to")}
        if kind == "sheet":
            res["redo_jobs"] = _requeue_items_of_sheet(root, run, holder, old["file"], entry)
            res["items_retired"] = retired_items
        elif kind == "face":
            res["redo_jobs"] = _requeue_sheets_of_face(root, run, obj[0], old["file"], rel)
            res["sheets_retired"] = retired_sheets
            _report(root, run, req.get("episode") or 0, "8 资产就绪",
                    f"身份脸被{by}换了：{obj[0]} {old['file']} → {rel}；这个人的设定图 {retired_sheets or '无'} 已退下、作业 {res['redo_jobs'] or '无'} 按新脸重出，"
                    "已出的镜头首帧仍是旧脸", False, "设定图重出并登记后单品自动重裁；已出首帧要不要重出由总调度定")
    rels = [str(mp.relative_to(root)).replace(os.sep, "/"), rel]
    if kind == "item" and ((job or {}).get("spec") or {}).get("part_label"):
        rels.append(map_item_part(root, run, obj[0], ((job or {}).get("spec") or {}).get("look"), job["spec"]["part_label"], obj[1]))
    res["push"] = push_files(root, rels, pusher=pusher) if (push and push_enabled(root)) else {"skipped": "push 关着（config/pipeline/asset_worker.json）"}
    bad = [h for h, v in (res["push"] or {}).items() if isinstance(v, dict) and v.get("ok") is False]
    if bad:
        _report(root, run, req.get("episode") or 0, "8 资产就绪", f"{kind} {':'.join(obj)} 已登记进清单，但推送 {','.join(bad)} 失败："
                + "；".join(str(res["push"][h].get("error")) for h in bad), False, "FACTORY sync.py auto 每 10 分钟会补推；推不上就查 rssh 主连接")
    return res


def preview_pick(root: Path, kind: str, req: dict, choice: str, by: str) -> dict:
    """只读：这次选择如果现在登记会怎样（owner_pick reapply 的 dry-run 用）。
    action：noop（已是这张）/ new（还没登记）/ replace（换掉现在的）/ refuse（不能换：冻结归档、系统想覆盖人工、候选坏了…，why 写原因）；
    conflict=True：现在这张也是项目方本人登记的（推翻他自己更早的选择），默认不自动执行，交总调度确认"""
    out = {"kind": kind, "id": req.get("id"), "choice": choice, "by": by}
    try:
        run, job = run_for_pick(root, req)
        out["run"] = run
        run_writable(root, run)
        c, _src = _cand_file(root, {**req, "run": run}, choice)
        out["chosen_sha"] = c["sha256"]
        k2, obj = pick_object(str(req["id"]))
        if k2 != kind or not obj:
            raise RegisterError(f"pick id {req['id']} 不是 {kind} 类")
        mp = manifest_path(root, run)
        d, _ = _read_manifest(mp)
        holder, key, _dst, what = _slot(json.loads(json.dumps(d)), kind, obj, mp.parent, choice, ".png", req, job)
        old = holder.get(key) or {}
        out.update(before_file=old.get("file"), before_sha=old.get("sha256"), before_by=old.get("picked_by"))
        if not old.get("file"):
            out["action"] = "new"
        elif old.get("sha256") == c["sha256"]:
            out["action"] = "noop"
        elif may_replace(old, by):
            out["action"] = "replace"
            out["conflict"] = is_owner_by(old.get("picked_by"))
        else:
            out.update(action="refuse", why=f"{what}已由{old.get('picked_by')}登记，{by} 不覆盖")
    except (RegisterError, RuntimeError, OSError, ValueError) as e:   # arch-ok: 预演只报原因，不写任何东西
        out.update(action="refuse", why=str(e)[:200])
    return out


def registered_face(root: Path, run: str, cid: str) -> dict | None:
    """清单里这个人已登记的身份脸（file 存在且 sha256 对得上）→ {file, sha256}；没有 / 对不上 = None。
    ISS-1103-004547-ca20：sheet 作业只有在这里拿到脸才派，并把这张脸作为参考送进去"""
    try:
        d, _ = _read_manifest(manifest_path(root, run))
    except (RegisterError, OSError, ValueError):   # arch-ok: 读不出清单 = 当作没有脸，sheet 继续等（失败关闭）
        return None
    f = (((d.get("characters") or {}).get(cid) or {}).get("face") or {})
    fp = root / str(f.get("file") or "")
    if not f.get("file") or not f.get("sha256") or not fp.is_file() or _sha(fp.read_bytes()) != f["sha256"]:
        return None
    return {"file": str(f["file"]), "sha256": f["sha256"]}


_UNSAFE_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def safe_name(s: str) -> str:
    """资产包里的文件名只许 [A-Za-z0-9_.-]（AUTOFIX-O 11-03：CAST-S 候选 key “ch_zhuo_lin#3” 进了文件名，
    # 在 /files/ URL 里会被当成锚点截断；空格 / 中文同理）。其余字符一律换成 _"""
    out = _UNSAFE_RE.sub("_", str(s or "")).strip("._")
    if not out:
        raise RegisterError(f"文件名片段 {s!r} 规范化后为空")
    return out


def is_safe_rel(rel: str) -> bool:
    return all(not _UNSAFE_RE.search(part) for part in str(rel).replace("\\", "/").split("/"))


def normalize_names(root: Path, run: str, pusher=None, push: bool = True) -> dict:
    """已登记文件名里有 #、空格等字符 → 迁成规范名：拷到新名（内容 sha 必须不变）、改清单 file、原文件移进
    data/_quarantine/<时间>_asset_names/（不删）、清单与新文件推两台并核 sha。幂等：全都规范时什么都不做"""
    mp = manifest_path(root, run)
    d, sha0 = _read_manifest(mp)
    moved = []

    def fix(entry: dict) -> None:
        rel = str((entry or {}).get("file") or "")
        if not rel or is_safe_rel(rel):
            return
        src = root / rel
        if not src.is_file() or _sha(src.read_bytes()) != entry.get("sha256"):
            raise RegisterError(f"{rel} 不存在或 sha 与清单不符，不迁移")
        parts = rel.split("/")
        new_rel = "/".join(parts[:-1] + [safe_name(Path(parts[-1]).stem) + Path(parts[-1]).suffix.lower()])
        dst = root / new_rel
        if dst.exists() and _sha(dst.read_bytes()) != entry["sha256"]:
            raise RegisterError(f"{new_rel} 已存在且内容不同，不迁移")
        if not dst.exists():
            shutil.copy2(src, dst)
        if _sha(dst.read_bytes()) != entry["sha256"]:
            raise RegisterError(f"{new_rel} 拷贝后 sha 不符，不迁移")
        entry["file"] = new_rel
        entry.setdefault("renamed_from", rel)
        moved.append((rel, new_rel))

    for c in (d.get("characters") or {}).values():
        if not isinstance(c, dict):
            continue
        fix(c.get("face"))
        for lk in (c.get("looks") or {}).values():
            if isinstance(lk, dict):
                fix(lk.get("sheet"))
                for it in (lk.get("items") or {}).values():
                    fix(it)
        for it in (c.get("items") or {}).values():
            fix(it)
    for sc in (d.get("scenes") or {}).values():
        if isinstance(sc, dict):
            fix(sc.get("base"))
    out = {"run": run, "renamed": moved, "manifest_sha_before": sha0[:12]}
    if not moved:
        out["note"] = "文件名都已规范"
        return out
    out["manifest_sha_after"] = _write_manifest(mp, d, sha0)[:12]
    q = root / "data" / "_quarantine" / f"{time.strftime('%Y%m%d-%H%M%S')}_asset_names"
    for old, _new in moved:
        t = q / old
        t.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(root / old), str(t))
    out["quarantine"] = str(q.relative_to(root)).replace(os.sep, "/")
    rels = [str(mp.relative_to(root)).replace(os.sep, "/")] + [n for _o, n in moved]
    out["push"] = push_files(root, rels, pusher=pusher) if (push and push_enabled(root)) else {"skipped": "push 关着"}
    return out


def requeue(root: Path, run: str, jid: str, why: str = "") -> dict:
    """失败的作业重新排队（state=pending、attempts=0、清 final / error）：常驻服务下一拍接手。只动 failed 的作业"""
    p = job_path(root, run, jid)
    job = load_job(p)
    if job.get("state") != "failed":
        raise RuntimeError(f"{jid} 现在是 {job.get('state')}，只有 failed 的作业能重新排队")
    job.update(state="pending", attempts=0, final=False, error=None, pid=None, lane=None)
    log(job, "重新排队（attempts 归零）" + (f"：{why}" if why else ""))
    save_job(root, job)
    (jobs_dir(root, run) / "_recheck").write_text(_now(), encoding="utf-8")
    return {"id": jid, "state": job["state"], "attempts": job["attempts"]}


def _put_item(chars: dict, cid: str, lid: str | None, iid: str, entry: dict) -> None:
    holder = chars.setdefault(cid, {})
    if lid:
        holder = holder.setdefault("looks", {}).setdefault(lid, {"name": lid, "route": "server_ok", "adult": False, "items": {}})
    items = holder.setdefault("items", {})
    old = items.get(iid) or {}
    if old.get("file") and not may_replace(old, str(entry.get("picked_by") or "")):
        raise RegisterError(f"{cid} 单品 {iid} 已由{old.get('picked_by') or '别人'}登记，自动裁图不覆盖")
    if old.get("file"):
        entry["replaced"] = (old.get("replaced") or []) + [{k: v for k, v in old.items() if k != "replaced"}]
    items[iid] = entry


def _ar():
    sys.path.insert(0, str(ROOT / "services" / "agent"))
    from ns_agent import asset_refs as AR   # noqa: PLC0415
    return AR


def map_item_part(root: Path, run: str, cid: str, lid: str, part_label: str, iid: str) -> str:
    """造型部件 → 清单单品：写 data/looks/item_map_overrides.json[run][cid][lid][部件名] = iid（与资产中心“单品挂到造型”同一份，
    asset_refs.item_map 读它；I4 认“这件单品有图”靠这条映射）。返回相对路径（供推送）"""
    AR = _ar()
    rel = str(Path(AR.OVERRIDES).relative_to(AR.ROOT)).replace(os.sep, "/")
    p = root / rel
    d = _read_json(p, "item_map_overrides.json") if p.is_file() else {}
    m = d.setdefault(run, {}).setdefault(cid, {}).setdefault(lid, {})
    if m.get(part_label) != iid:
        m[part_label] = iid
        m["_by"], m["_at"] = "ASSET-WORKER", _now()
        atomic_json(p, d)
    return rel


SLOT_CODE = {"outfit": "outfit", "shoes": "shoes", "accessory": "acc", "nails": "nails"}


def _norm_label(s: str) -> str:
    return re.sub(r"[\s（）()：:，,、+＋。]", "", re.sub(r"[（(][^）)]*[）)]", "", str(s or "")))


def owner_item_for(char: dict, lid: str, part) -> tuple[str, dict] | None:
    """A9 P1-①（C-23：服装 / 造型以项目方指定为准）：清单里这套造型（或角色层）已有项目方上传的同一件 → (iid, entry)，否则 None。
    认法：entry.source / by 写了“项目方”（项目方上传 assets_v2/inbox/… 登记进来的），且 ① 名字与部件原文（去括注）相同，
    或 ② 同 slot 且名字互相包含。从项目方图裁出来的派生件（source 是清单里的文件）不算项目方上传"""
    look = ((char.get("looks") or {}).get(lid) or {})
    want = _norm_label(part.label)
    if not want:
        return None
    for scope in (look.get("items") or {}, char.get("items") or {}):
        for iid, e in scope.items():
            if not isinstance(e, dict) or not e.get("file"):
                continue
            if not OWNER_SRC_RE.search(str(e.get("source") or "") + str(e.get("by") or "")):
                continue
            name = _norm_label(e.get("name") or "")
            if not name:
                continue
            if name == want or (e.get("slot") == part.slot and (name in want or want in name)):
                return iid, e
    return None


def item_skip_reason(char: dict, lid: str, part) -> str | None:
    """规划 item 作业前的跳过判断（None = 要出）：①“无”/“0件”/ 项目方编号（no_item）；② 清单里已有项目方上传的同一件 → 引用不重画；
    ③ 部件原文带“（…参考照…）”= 项目方指定照片为准，清单里还没有也不自己画（等项目方给）"""
    why = no_item(part.label)
    if why:
        return why
    own = owner_item_for(char, lid, part)
    if own:
        return f"清单里已有项目方上传的同一件 {own[0]}（{own[1].get('file')}，{own[1].get('source') or own[1].get('by')}），引用它，不重画（C-23）"
    if OWNER_REF_RE.search(str(part.label or "")):
        return f"P1 写明“{OWNER_REF_RE.search(part.label).group(0)}”= 以项目方给的照片为准（C-23），资产线不重画；清单里还没有就等项目方上传"
    return None


def plan_items_from_sheet(root: Path, run: str, cid: str, lid: str, episode: int, sheet: dict,
                          skipped: list | None = None, dry: bool = False) -> list[str]:
    """sheet 登记后（总调度 11-03 定 A）：按 P1_looks 这套造型的部件（asset_refs.parse_parts，与 I4 同一口径）生成 item 作业，
    先从设定图裁（spec.crop），裁不出来再出候选。已在清单 / 已有作业的不重复生成。返回新建的作业 id。
    W6c+（A9 P1-①）：规划前先过 item_skip_reason——“无”/“0件”/ 项目方编号 / 项目方已上传的同一件 / “（参考照）”一律跳过，
    理由追加进 skipped（[{part, slot, why}]，调用方写进 sheet 作业 log）。dry=True 只规划不写作业文件（返回的是将要新建的 id）"""
    AR = _ar()
    story, looks = p1(root, run)
    lk = p1_looks_of(looks, cid) or {}
    look = next((x for x in lk.get("looks") or [] if x.get("id") == lid), None)
    if not look:
        return []
    name = (p1_char(story, cid) or {}).get("name") or cid
    d, _ = _read_manifest(manifest_path(root, run))
    char = (d.get("characters") or {}).get(cid) or {}
    have = (((char.get("looks") or {}).get(lid) or {}).get("items") or {})
    made, n = [], {}
    for part in AR.parse_parts(look.get("zh") or ""):
        why = item_skip_reason(char, lid, part)
        if why:
            if skipped is not None:
                skipped.append({"part": part.label, "slot": part.slot, "why": why})
            continue
        code = SLOT_CODE.get(part.slot, "acc")
        n[code] = n.get(code, 0) + 1
        iid = f"{lid}_{code}{n[code]}"
        jid = f"item-{cid}-{lid}-{code}{n[code]}"
        if iid in have or job_path(root, run, jid).is_file():
            continue
        spec = {"cid": cid, "name": name, "look": lid, "slot": part.slot, "zone": part.zone, "label": part.label, "part_label": part.label,
                "iid": iid, "crop": True, "from_sheet": {"file": sheet["file"], "sha256": sheet["sha256"]},
                **item_render_fields(part.label, part.slot)}
        job = {"schema": SCHEMA, "id": jid, "run": run, "episode": episode, "episodes": [episode], "kind": "item", "target": f"{cid}:{iid}",
               "who": f"{name}（{cid}）", "what": f"{name} 造型{lid} 的{AR.SLOT_LABEL.get(part.slot, '单品')}“{part.label}”（从设定图裁）", "owner": "资产线",
               "shots": [], "state": "pending", "attempts": 0, "created_at": _now(), "updated_at": _now(), "spec": spec, "candidates": [],
               "pick_id": f"pick:item:{cid}:{iid}", "log": [f"{_now()} 设定图 {sheet['file']} 登记后生成：先裁，裁不出来再出候选"]}
        if not dry:
            save_job(root, job)
        made.append(jid)
    return made


def register_item_auto(root: Path, job: dict, img: Path, box: list[int], check: dict, by: str = "ASSET-WORKER（设定图自动裁）",
                       pusher=None, push: bool = True) -> dict:
    """从设定图裁出的单品图过契约后直接登记（不需要项目方挑；总调度 11-03）：清单 looks[look].items[iid] + 部件映射 + 推两台"""
    spec, run = job["spec"], job["run"]
    cid, lid, iid = spec["cid"], spec["look"], spec["iid"]
    src_sheet = root / spec["from_sheet"]["file"]
    if not src_sheet.is_file() or _sha(src_sheet.read_bytes()) != spec["from_sheet"]["sha256"]:
        raise RegisterError(f"设定图 {spec['from_sheet']['file']} 不在或 sha 变了，不登记裁图")
    mp = manifest_path(root, run)
    d, sha0 = _read_manifest(mp)
    dst = mp.parent / "characters" / cid / "items" / f"{safe_name(iid)}_crop{img.suffix.lower()}"
    rel = _copy_in(root, img, dst)
    sha = _sha((root / rel).read_bytes())
    _put_item(d.setdefault("characters", {}), cid, lid, iid, {
        "file": rel, "sha256": sha, "slot": spec["slot"], "name": spec["label"], "no_brand": True, "route": "server_ok", "adult": False,
        "source": spec["from_sheet"]["file"], "picked_by": AUTO_BY if by.startswith("ASSET-WORKER") else by, "picked_at": _now(),
        "note": f"从设定图 {spec['from_sheet']['file']}（sha256 {spec['from_sheet']['sha256']}）纯裁剪，裁剪框 (left,top,right,bottom)={tuple(box)}，不生成不修图",
        "contract": {k: (check.get(k) or {}).get("status") if isinstance(check.get(k), dict) else check.get(k) for k in ("status", "ocr")}})
    sha1 = _write_manifest(mp, d, sha0)
    rels = [str(mp.relative_to(root)).replace(os.sep, "/"), rel, map_item_part(root, run, cid, lid, spec["part_label"], iid)]
    res = {"run": run, "kind": "item", "object": f"{cid}:{iid}", "file": rel, "sha256": sha, "box": list(box), "manifest_sha_after": sha1[:12],
           "pick_id": job.get("pick_id"), "job": job["id"], "auto": True}
    res["push"] = push_files(root, rels, pusher=pusher) if (push and push_enabled(root)) else {"skipped": "push 关着"}
    bad = [h for h, v in (res["push"] or {}).items() if isinstance(v, dict) and v.get("ok") is False]
    if bad:
        _report(root, run, job.get("episode") or 0, "8 资产就绪", f"单品 {cid}:{iid} 已登记进清单，但推送 {','.join(bad)} 失败", False,
                "FACTORY sync.py auto 每 10 分钟会补推")
    return res


def _copy_in(root: Path, src: Path, dst: Path) -> str:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not dst.is_file():
        shutil.copy2(src, dst)
    if _sha(dst.read_bytes()) != _sha(src.read_bytes()):
        raise RegisterError(f"{dst.name} 已存在且与候选内容不同，不覆盖、不登记")
    return str(dst.relative_to(root)).replace(os.sep, "/")


def _entry(rel: str, root: Path, c: dict, by: str, req: dict) -> dict:
    sha = _sha((root / rel).read_bytes())
    if c.get("sha256") and sha != c["sha256"]:
        raise RegisterError(f"拷进资产包后的 sha 与候选不符（{rel}），不登记")
    return {"file": rel, "sha256": sha, "sha256_source": c.get("sha256_source"), "source": f"阶段 A 资产作业 {req.get('job')} 候选 {c.get('key')}（{c.get('file')}）",
            "picked_by": by, "picked_at": _now(), "route": "server_ok", "adult": False,
            "candidates_archived": [str(x.get("file")) for x in req.get("candidates") or [] if isinstance(x, dict) and str(x.get("key")) != str(c.get("key"))]}


def _report(root: Path, run: str, episode: int, step: str, what: str, blocking: bool, hint: str = "") -> None:
    import importlib.util as _u
    sp = _u.spec_from_file_location("report_issue_for_jobs", ROOT / "tools" / "master" / "report_issue.py")
    m = _u.module_from_spec(sp)
    sp.loader.exec_module(m)
    live = root / "docs" / "master" / "V2_LIVE.md"
    m.report(run, int(episode or 0), step, "ASSET-WORKER", what, blocking, hint, issues=root / "data" / "pipeline" / "issues.jsonl",
             live=live if live.is_file() else None)


# ------------------------------------------------------------------ 选定后：作业收尾 + 重跑就绪检查（owner_pick.READY_HOOK）
def find_job_by_pick(root: Path, pick_id: str, run: str | None = None) -> dict | None:
    """pick id → 资产作业。只看 runs.json 登记过的剧（试跑剧 demo_v2 之类不参与匹配）；给了 run 就只看这一部（ISS-1103-004549-cb05）"""
    base = root / "data" / "pipeline" / "asset_jobs"
    if not base.is_dir():
        return None
    reg = registered_runs(root)
    for rd in sorted(base.iterdir()):
        if not rd.is_dir() or rd.name not in reg or (run and rd.name != run):
            continue
        for j in list_jobs(root, rd.name):
            if j.get("pick_id") == pick_id:
                return j
    return None


def after_pick(root: Path, kind: str, res: dict, check=None) -> dict | None:
    """登记完成 → 作业标 done → 重跑 episode_ready（generate 幂等）→ 全部就绪时写阶段 B 作业"""
    pid = (res or {}).get("pick_id")
    job = find_job_by_pick(root, pid, run=(res or {}).get("run")) if pid else None
    if job is None:
        return None
    job.update(state="done", result={k: v for k, v in (res or {}).items() if k != "push"} | {"push": (res or {}).get("push")}, done_at=_now())
    log(job, f"{res.get('picked_by') or '选定'}：{res.get('picked') or res.get('choice') or ''}，已登记")
    save_job(root, job)
    if kind == "sheet" and res.get("file"):          # 设定图登记 → 自动生成单品作业（先从设定图裁，总调度 11-03）
        try:
            skipped: list = []
            made = plan_items_from_sheet(root, job["run"], job["spec"]["cid"], job["spec"]["look"], int(job["episode"]),
                                         {"file": res["file"], "sha256": res["sha256"]}, skipped=skipped)
            log(job, f"生成单品作业 {made}")
            for sk in skipped:
                log(job, f"单品“{sk['part']}”不生成作业：{sk['why']}"[:300])
        except Exception as e:  # noqa: BLE001  生成失败登记卡点，不影响设定图登记
            log(job, f"生成单品作业失败：{e!r}"[:200])
            _report(root, job["run"], job.get("episode") or 0, "8 资产就绪", f"{job['id']} 登记后生成单品作业失败：{e!r}"[:300], False)
        save_job(root, job)
    (jobs_dir(root, job["run"]) / "_recheck").write_text(_now(), encoding="utf-8")
    try:
        return generate(job["run"], int(job["episode"]), root, check=check)
    except Exception as e:  # noqa: BLE001  重跑检查失败只记在作业里，不影响登记结果
        log(job, f"登记后重跑就绪检查失败：{e!r}"[:200])
        save_job(root, job)
        return None


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate", help="按 episode_ready 缺口生成作业（幂等，只生成不执行）")
    g.add_argument("--run", required=True)
    g.add_argument("--episode", type=int, required=True)
    ls = sub.add_parser("list")
    ls.add_argument("--run", required=True)
    rq = sub.add_parser("requeue", help="失败的作业重新排队（attempts 归零），常驻服务下一拍接手")
    rq.add_argument("--run", required=True)
    rq.add_argument("--job", required=True, action="append")
    rq.add_argument("--why", default="")
    nn = sub.add_parser("normalize-names", help="清单里文件名带 # / 空格等字符的迁成规范名（sha 不变，推两台）")
    nn.add_argument("--run", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "generate":
        print(json.dumps(generate(a.run, a.episode), ensure_ascii=False, indent=1))
        return 0
    if a.cmd == "requeue":
        print(json.dumps([requeue(ROOT, a.run, j, a.why) for j in a.job], ensure_ascii=False, indent=1))
        return 0
    if a.cmd == "normalize-names":
        print(json.dumps(normalize_names(ROOT, a.run), ensure_ascii=False, indent=1))
        return 0
    for j in list_jobs(ROOT, a.run):
        print(f"{j['id']:<32} {j.get('kind'):<7} {j.get('state'):<14} {j.get('who') or ''}：{(j.get('what') or '')[:60]}")
    return 0


def owner_revise(root: Path, run: str, job_id: str, note: str, by: str) -> dict:
    """W-FIX-PIPE #13（L-212）：项目方在“需要修改描述”上写的一句 → 记进作业 owner_notes（asset_worker._compile 加进提示词），作业重排。
    重排计数清零（attempts / auto_requeues / escalated），下一轮用没用过的种子"""
    guard_run(root, run)
    note = str(note or "").strip()
    if not note:
        raise RegisterError("要写一句想怎么改")
    jp = job_path(root, run, job_id)
    job = load_job(jp)
    notes = list(job.get("owner_notes") or []) + [note[:200]]
    job.update(owner_notes=notes, state="pending", attempts=0, auto_requeues=0, final=False, error=None, escalated=None, retry_after=None)
    log(job, f"项目方修改（{by}）：{note[:200]}——加进描述，重新出候选")
    save_job(root, job)
    return {"job": job_id, "state": "pending", "owner_notes": notes}


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
