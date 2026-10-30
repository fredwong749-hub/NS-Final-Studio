"""
林晚资产 v2：全部以项目方通过的母版 plates/master.png（CM_s1，sha b8e7b00b…）为身份来源，按 SOP S2 锁定配方重做。

    uv run python tools/gen_assets_v2.py list
    uv run python tools/gen_assets_v2.py run --only plates/ expressions/       # 按 id 前缀
    uv run python tools/gen_assets_v2.py run --only plates/id_front --pilot --edit-cfg 1   # 试跑（不进资产库）
    uv run python tools/gen_assets_v2.py sheets

方法（两段式，同 ns_render.pipeline.render_image 的 plate 模式）：
  1. 构图：文生图（或带单品产品图的编辑），不带身份参考 —— Qwen 2.1 Base 35 步 cfg 3、krea2 0.5、texture-fix VAE
  2. 换脸：图1 = 构图，图2 = 母版脸部裁切（ns_render.refs.face_crop），只换五官、发色发型（及指定妆容）
  3. 精修：1.5× 放大，12 步 denoise 0.30（同参考、同 LoRA）
  4. QC v3（NudeNet + CLIP v2 + Qwen3-VL 裁决），裸露一票否决 → 删除、换种子（最多 3 次）
妆容 L1–L8：在两段式做出的 v2 素颜正脸底板上单参考编辑（research v9 §1 骨架），再精修；L6 泪痕链式叠加。
产出：<原名>_v2.png（不覆盖旧图），manifest 记 seed/模型/LoRA/VAE/精修/bible_sha256/母版 sha；旧条目标 superseded。
每次向 ComfyUI 提交前检查队列，有别的任务在跑就等（笔记本 12 GB，一次一个任务）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
import gen_assets as G   # noqa: E402

from ns_render import workflows as W   # noqa: E402
from ns_render.comfy_client import ComfyClient   # noqa: E402
from ns_render.refs import face_crop   # noqa: E402

ROOT, BASE, MASTER = G.ROOT, G.BASE, G.MASTER
MASTER_SHA_PREFIX = "b8e7b00b"
BIBLE = ROOT / "config" / "visual_bible.toml"
WORK = ROOT / "golden" / "assets" / "v2_work"
SHEETS = ROOT / "golden" / "assets" / "sheets"

# SOP S2 锁定配方（docs/SOP_parameters.md；VB [realism]）
STEPS, CFG = 35, 3.0
LORAS = [(G.LORA_FILM, 0.5)]
REFINE = {"scale": 1.5, "steps": 12, "denoise": 0.30}
EDIT_CFG_DEFAULT = 3.0

VB = tomllib.loads(BIBLE.read_text(encoding="utf-8"))
LW = VB["characters"]["lin_wan"]
BANNED = VB["realism"]["banned_words"] + ["精致", "娃娃", "美颜", "瓷肌", "无瑕", "大眼", "仙气", "心机"]   # + v9 §1
SKIN = VB["realism"]["skin_terms"]
HAIR = LW["hair_color"]                       # 雾霾天蓝色及腰直发（…），齐刘海
EYES_BARE, EYES_GLAM = LW["eyes"]["bare"], LW["eyes"]["glam"]
NAILS = "双手手指甲为约5厘米长的透明水晶延长尖甲，甲面镶满透明水钻"
HEELS = "脚穿12厘米透明侧开细高跟鞋，鞋跟直径约6毫米、细如一根筷子的针形细跟"
HEELS_PATENT = ("脚穿12厘米黑色漆皮侧开细高跟鞋（漆皮为像抹了油一样的高亮镜面漆皮），"
                "鞋跟直径约6毫米、细如一根筷子的针形细跟")
MINI = ("黑色漆皮高腰包臀超短裙（漆皮为像抹了油一样的高亮镜面漆皮，表面湿润光泽，镜面反射清晰，高光锐利），"
        "裙长约28厘米")
GREY = G.GREY
TEE = "穿素色浅灰色圆领短袖T恤，不戴任何首饰"
BODY_DRESS = "穿一条素色深海军蓝长袖针织连衣裙（圆领、及膝、不透明），白色平底帆布鞋，不戴任何首饰"   # notes：全身正面 QC 稳定通过
PHOTO = "真实相机拍摄的人像照片，未修图原片，" + SKIN + "，真实的一根根发丝与少量碎发飞丝；shot on Leica M11, Summilux 50mm f/1.4"
NEG = ("磨皮, 塑料皮肤, 蜡像, 娃娃脸, 放大瞳孔, 粘连睫毛, 大面积圆形腮红, 满脸闪粉, 硬边唇线, CGI, 3D render, airbrushed, "
       "动漫比例, 多余手指, 手指融合, 肢体变形, 未成年人外观, 裸体, 裸露, 走光, 内衣外露, 项链, 文字, 水印")

WOMAN = ("一位22岁的东亚成年女性，鹅蛋脸，下颌线柔和，中等大小的杏眼，{eyes}，鼻梁细直，嘴唇饱满、上唇有小唇珠，"
         "左脸颊靠近鼻翼有一颗小痣，冷调白皙皮肤，" + HAIR)
MASTER_MAKEUP = "图2的粉甜妆容（草莓粉腮红、水润粉色唇釉、浓密卷翘但根根分明的睫毛）"
SWAP = ("图1是这张角色资产照的画面构图。保持图1的构图、机位、景别、人物姿势与朝向、表情、服装、背景和光线不变，"
        "只把图1中林晚的五官长相、发色与发型换成图2人物的样子（" + HAIR + "，冷白皮肤，左脸颊靠近鼻翼的小痣）{extra}；"
        "不要沿用图2的姿势、手势、项链、服装和背景。")
SWAP_GLAM = "，妆容也换成" + MASTER_MAKEUP + "，" + EYES_GLAM
SWAP_BARE = "，保持图1的素颜（不要图2的妆容），眼睛为" + EYES_BARE + "（不要图2的灰蓝色美瞳）"


@dataclass
class Job:
    id: str                 # plates/id_front → plates/id_front_v2.png
    kind: str
    design: str
    name: str
    compose: str            # 第一段提示词（或妆容编辑提示词）
    size: tuple[int, int] = (1024, 1024)
    swap_extra: str = SWAP_GLAM
    angle: str | None = None
    makeup: str | None = None
    supersedes: list[str] = field(default_factory=list)
    compose_refs: list[str] = field(default_factory=list)   # 构图段的单品参考（相对 BASE）
    mode: str = "two_stage"   # two_stage | edit（在 edit_base 上单参考编辑）
    edit_base: str | None = None
    extra: dict = field(default_factory=dict)

    @property
    def dest(self) -> Path:
        return BASE / f"{self.id}_v2.png"


def _compose(eyes: str, body: str) -> str:
    return "真实人像照片：" + WOMAN.format(eyes=eyes) + "。" + body + "。" + PHOTO


def jobs() -> list[Job]:
    J: list[Job] = []
    head = (1024, 1024)
    glam_eyes = EYES_GLAM + "（瞳孔大小正常）"
    light = "淡粉色系妆容（草莓粉腮红、水润粉色唇釉、根根分明的卷翘睫毛），"
    P = "plates/"
    J.append(Job(P + "id_front", "plate", "LW-ID-F", "正脸底板（母版妆容）",
                 _compose(glam_eyes, light + "正面头肩照，平视镜头，中性放松表情，嘴唇自然闭合，头发自然垂在两侧和身后，" + TEE + "，" + GREY),
                 head, angle="F", supersedes=["id_front_s0.png"]))
    J.append(Job(P + "id_front_bare", "plate", "LW-ID-F-bare", "正脸底板（素颜，深棕眼）",
                 _compose(EYES_BARE + "（不戴美瞳）", "完全素颜：无眼线、无睫毛膏、无唇彩、无腮红，可见自然的皮肤纹理和淡淡黑眼圈，正面头肩照，平视镜头，中性表情，嘴唇自然闭合，" + TEE + "，" + GREY),
                 head, swap_extra=SWAP_BARE, angle="F", makeup="L1", supersedes=["id_front_bare_s0.png"]))
    J.append(Job(P + "id_34L", "plate", "LW-ID-34L", "3/4 侧脸（脸朝画面左）",
                 _compose(glam_eyes, light + "四分之三侧脸头肩照：她的脸和身体朝向画面左侧约45度，眼睛看向画面左前方，中性表情，" + TEE + "，" + GREY),
                 head, angle="34L", supersedes=["id_34L_s0.png"]))
    J.append(Job(P + "id_34R", "plate", "LW-ID-34R", "3/4 侧脸（脸朝画面右）",
                 _compose(glam_eyes, light + "四分之三侧脸头肩照：她的脸和身体朝向画面右侧约45度，眼睛看向画面右前方，中性表情，" + TEE + "，" + GREY),
                 head, angle="34R", supersedes=["id_34R_s0.png"]))
    J.append(Job(P + "id_profile", "plate", "LW-ID-P", "正侧面（脸朝画面左）",
                 _compose(glam_eyes, light + "标准正侧面头肩照：她的脸完全转向画面左侧90度，只看到一只眼睛，鼻尖和下巴的侧面轮廓清晰，齐刘海从侧面看呈一条直线，长直发垂到背后，中性表情，" + TEE + "，" + GREY),
                 head, angle="P", supersedes=["id_profile_s0.png"]))
    J.append(Job(P + "id_back34", "plate", "LW-ID-B34", "背面 3/4（回头，露出侧脸轮廓与及腰长发）",
                 _compose(glam_eyes, light + "从她的左后方约135度拍摄：她背对镜头站立，头微微向左转，只露出脸颊与睫毛的侧后方轮廓，看不到正脸，" + HAIR + "顺直地垂到腰部，上半身到臀部入画，" + TEE + "，" + GREY),
                 (768, 1344), angle="B", supersedes=["id_back_s0.png"]))
    J.append(Job(P + "body_F", "plate", "LW-BODY-F", "全身底板（正面）",
                 _compose(glam_eyes, light + "从头顶到脚完整入画的正面全身站姿，面向镜头，双臂自然垂在身侧，双脚并拢平放在地上，身材修长匀称、腿长、身高约170厘米，" + BODY_DRESS + "，" + GREY),
                 (768, 1344), angle="F", extra={"framing": "full_body"}, supersedes=["body_F_s0.png", "body_F_s7.png"]))
    # ------------------------------------------------------------ 表情（母版妆容，灰蓝美瞳）
    ex = {"calm": ("平静", "平静、放空的表情，嘴唇自然闭合"),
          "smile": ("微笑", "真诚的浅浅微笑，嘴角上扬，眼睛微弯，露出一点牙齿"),
          "cry": ("哭（泪与笑）", "正在流泪：眼眶和鼻尖泛红，下眼睑盈满泪水，两道清晰发亮的泪痕从眼角流到下巴，眉头微蹙，嘴角却轻轻上扬（泪与笑同框）"),
          "angry": ("怒", "生气：眉头紧皱，目光锐利地直视镜头，嘴唇抿紧，下颌收紧"),
          "surprised": ("惊", "吃惊：眼睛睁大，眉毛上扬，嘴唇微微张开"),
          "seductive": ("媚眼", "含情的媚眼：眼皮微垂、眼神从睫毛下向上看着镜头，嘴唇微启，下巴微收")}
    for k, (n, d) in ex.items():
        J.append(Job(f"expressions/{k}", "expression", f"LW-EXP-{k}", n,
                     _compose(glam_eyes, light + "正面头肩照，" + d + "，" + TEE + "，" + GREY), head,
                     angle="F", supersedes=[f"{k}_s0.png"]))
    # ------------------------------------------------------------ 造型 A / B（C = 规格表，项目方政策：不出上身图）
    looks = {
        "REF-LW-01": ("A 素颜通勤（性感通勤）", EYES_BARE + "（不戴美瞳）",
                      "几乎素颜的通勤淡妆（豆沙粉润唇），穿收腰修身的白色衬衫（领口微开）和" + MINI + "，" + HEELS + "，" + NAILS,
                      SWAP_BARE, "L1", ["items/outfit/O02_product_s0.png", "items/shoes/S01_side45_s0.png"], "服装", "鞋子"),
        "REF-LW-02": ("B 浓妆女王", EYES_GLAM + "（瞳孔大小正常）",
                      "浓妆：梅子棕截断式眼妆、拉长黑色眼线、黑樱桃色丝绒唇；穿黑色漆皮双排扣长风衣（漆皮为像抹了油一样的高亮镜面漆皮，表面湿润光泽，镜面反射清晰，高光锐利，扣到领口、系紧腰带，下摆到小腿），"
                      + HEELS_PATENT + "，" + NAILS + "，气场冷艳",
                      "，妆容保持图1的浓妆（梅子棕截断式眼妆、拉长黑色眼线、黑樱桃色丝绒唇），" + EYES_GLAM, "L4",
                      ["items/outfit/O08_product_s0.png", "items/shoes/S02_side45_s0.png"], "风衣", "鞋子"),
    }
    views = {"front": ("F", "正面全身，面向镜头，双手自然垂在身侧"),
             "34": ("34L", "四分之三侧面全身，身体朝向画面左侧约45度"),
             "back": ("B", "背面全身：她背对镜头站立，头微微向左转露出一点侧脸轮廓，及腰的长发垂在后背，鞋跟朝向镜头")}
    for lid, (nm, eyes, d, swap, mk, refs, r1, r2) in looks.items():
        roles = f"图1只提供{r1}的款式、颜色与材质，图2只提供{r2}的款式与材质，不要沿用它们的背景和摆放。"
        for v, (ang, vd) in views.items():
            J.append(Job(f"looks/{lid}_{v}", "look", lid, f"{nm}（{v}）",
                         roles + _compose(eyes, d + "；" + vd + "，从头顶到脚完整入画，站姿自然，" + GREY),
                         (768, 1344), swap_extra=swap, angle=ang, makeup=mk, compose_refs=refs,
                         extra={"look_id": lid}, supersedes=[f"{lid}_{v}_s0.png"]))
    # ------------------------------------------------------------ 妆容 L1–L8（research v9 §2；在 v2 素颜正脸底板上编辑）
    recipes = _v9_recipes()
    keep = ("图1是林晚本人。保持她的脸型轮廓、鼻型、唇形、齐刘海和" + HAIR.split("（")[0] + "、肤色、左脸颊小痣与整体辨识度；"
            "眼睛保持真实成年亚洲女性的正常大小，不放大瞳孔，{eyes}。只修改妆容，妆感在照片里清楚可见：")
    tail = ("。真实人像照片，未修图原片，无磨皮，可见毛孔与细绒毛，真实发丝；正面头肩照，穿素色浅灰色圆领T恤，不戴首饰；"
            "灰色无缝背景，柔和窗光，50mm 镜头。其他一切保持不变")
    old = {"L1": "L1_bare_commute_s0.png", "L2": "L2_half_red_s0.png", "L3": "L3_red_lip_city_s0.png",
           "L4": "L4_queen_s0.png", "L5": "L5_night_crystal_s0.png", "L7": "L7_dewy_signature_s0.png",
           "L8": "L8_sweet_refined_s0.png"}
    for stem, (nm, d) in recipes.items():
        lid = stem.split("_")[0]
        eyes = ("眼睛为" + EYES_BARE + "，不戴美瞳") if lid in ("L1", "L2") else ("戴" + EYES_GLAM + "，瞳孔大小正常")
        J.append(Job("items/makeup/" + stem, "item/makeup", lid, nm, keep.format(eyes=eyes) + d + tail, head,
                     mode="edit", edit_base="plates/id_front_bare_v2.png", makeup=lid, angle="F", supersedes=[old[lid]]))
    tears = ("图1是林晚本人。保持图1的脸、发型、妆容颜色、服装、背景、光线和构图完全不变，只叠加刚哭过的状态，泪痕在照片里清楚可见，妆仍然好看："
             "下眼睑盈着一线泪光；一到两道细而发亮的泪痕从眼角斜向颧骨流下，沿途带走一点粉底；眼线和睫毛膏在下眼睑晕成浅灰色淡影，不是黑色污块；"
             "睫毛湿成几簇；眼周、鼻尖和鼻翼泛起淡淡的粉红；唇色被擦淡一半、边缘模糊，唇面微湿。真实人像照片，可见毛孔")
    for b, f in (("L4", "L4_queen_v2.png"), ("L1", "L1_bare_commute_v2.png")):
        J.append(Job(f"items/makeup/L6_tears_on_{b}", "item/makeup", "L6", f"泪痕妆（叠加在 {b}）", tears, head,
                     mode="edit", edit_base="items/makeup/" + f, makeup="L6", angle="F",
                     supersedes=[f"L6_tears_on_{b}_s0.png"]))
    for j in J:
        bad = [w for w in BANNED if w in j.compose or w in j.swap_extra]
        if bad:
            raise SystemExit(f"{j.id} 提示词含禁用词 {bad}")
    return J


def _v9_recipes() -> dict[str, tuple[str, str]]:
    """research v9 §2 配方（与 gen_assets_items 相同原文）；L7 名称去掉禁用词“纯欲”"""
    src = (ROOT / "tools" / "gen_assets_items.py").read_text(encoding="utf-8")
    ns: dict = {}
    start = src.index("    L = {\n        \"L1_bare_commute\"")
    end = src.index("    }\n", start) + 6
    exec("L = {" + src[start:end].split("{", 1)[1], ns)   # noqa: S102 — 本仓库文件，只取字面量字典
    out = {}
    for k, (nm, d) in ns["L"].items():
        out[k] = (nm.replace("纯欲水光妆", "水光咬唇妆"), d)
    return out


# ---------------------------------------------------------------- ComfyUI（排队礼让）
class PoliteClient(ComfyClient):
    """每次提交前看 /queue：有别人的任务在跑或排队就等（一次只跑一个任务）"""
    def __init__(self, *a, log=print, **k):
        super().__init__(*a, **k)
        self.log = log

    def submit(self, workflow: dict) -> str:
        waited = 0
        while True:
            q = self._json("/queue")
            if not q.get("queue_running") and not q.get("queue_pending"):
                break
            if waited % 300 == 0:
                self.log(f"ComfyUI 队列忙（running {len(q.get('queue_running', []))}, pending "
                         f"{len(q.get('queue_pending', []))}），等待…")
            time.sleep(15)
            waited += 15
        return super().submit(workflow)


def model(cfg: float) -> W.QwenModel:
    return W.QwenModel(unet=G.UNET_BASE, vae=G.VAE_TEX, turbo=False, steps=STEPS, cfg=cfg)


def seed_for(job_id: str, stage: str, k: int) -> int:
    return int(hashlib.sha256(f"lin_wan_v2/{job_id}/{stage}#{k}".encode()).hexdigest()[:12], 16)


def _run(client, wf, dest: Path) -> float:
    entry, secs = client.run(wf, timeout_s=3600)
    item = next(f for f in client.output_files(entry) if f["filename"].endswith(".png"))
    client.download(item, dest)
    return secs


def _small(src: Path, width: int = 768) -> Path:
    im = Image.open(src).convert("RGB")
    h = round(im.height * width / im.width / 32) * 32
    out = src.with_name(src.stem + "_ref.png")
    im.resize((width, h), Image.LANCZOS).save(out)
    return out


def _refine(client, src: Path, prompt: str, refs: list[str], size, seed: int, prefix: str, cfg: float, dest: Path) -> float:
    w, h = size
    W2, H2 = int(w * REFINE["scale"]) // 16 * 16, int(h * REFINE["scale"]) // 16 * 16
    init = client.upload_image(src)
    wf = W.qwen_edit(prompt, NEG, refs if len(refs) > 1 else refs[0], W2, H2, seed, prefix, m=model(cfg),
                     loras=LORAS, ref_resolution=0, crop=False, init_image=init, denoise=REFINE["denoise"])
    wf["37"]["inputs"]["steps"] = REFINE["steps"]
    return _run(client, wf, dest)


_vlm = None


def qc(path: Path, client) -> dict:
    global _vlm
    from ns_render.qc import nudity_qc, vlm_judge
    if _vlm is None:
        _vlm = vlm_judge(client)
    return nudity_qc(path, vlm=_vlm)


def run_job(client, job: Job, edit_cfg: float, log, pilot: str | None = None, attempts: int = 3) -> dict | None:
    master_sha = G.sha256(MASTER)
    if not master_sha.startswith(MASTER_SHA_PREFIX):
        raise SystemExit(f"母版 sha 变了（{master_sha[:12]}），不是 CM_s1 —— 停止")
    bible_sha = G.sha256(BIBLE)
    dest = (WORK / "pilot" / f"{Path(job.id).name}{pilot}.png") if pilot else job.dest
    if dest.exists() and not pilot:
        log(f"skip {job.id} (v2 exists)")
        return None
    work = WORK / Path(job.id).parent
    work.mkdir(parents=True, exist_ok=True)
    dest.parent.mkdir(parents=True, exist_ok=True)
    face = face_crop(MASTER)
    face_name = client.upload_image(face)
    prefix = f"ns_final/lw_v2/{job.id.replace('/', '_')}"
    for a in range(attempts):
        t0 = time.monotonic()
        seeds = {s: seed_for(job.id, s, a) for s in ("compose", "edit", "refine")}
        stem = f"{Path(job.id).name}{pilot or ''}_a{a}"
        rec: dict = {}
        if job.mode == "two_stage":
            comp = work / f"{stem}_compose.png"
            if job.compose_refs:
                names = [client.upload_image(G.prep_ref(BASE / r, 640)) for r in job.compose_refs]
                wf = W.qwen_edit(job.compose, NEG, names, *job.size, seeds["compose"], prefix + "_c", m=model(CFG),
                                 loras=LORAS, ref_resolution=0, crop=False)
            else:
                wf = W.qwen_t2i(job.compose, NEG, *job.size, seeds["compose"], prefix + "_c", m=model(CFG), loras=LORAS)
            _run(client, wf, comp)
            cq = qc(comp, client)
            if cq["nudity"]:
                log(f"QC FLAG compose {job.id} a{a} {cq} -> delete & retry")
                comp.unlink()
                continue
            swap = SWAP.format(extra=job.swap_extra)
            names = [client.upload_image(_small(comp)), face_name]
            mid = work / f"{stem}_swap.png"
            _run(client, W.qwen_edit(swap, NEG, names, *job.size, seeds["edit"], prefix + "_s", m=model(edit_cfg),
                                     loras=LORAS, ref_resolution=0, crop=False), mid)
            refine_prompt, refine_refs = swap, [client.upload_image(_small(mid)), face_name]
            rec = {"method": "two_stage_identity (compose → master face swap → refine)",
                   "compose_prompt": job.compose, "swap_prompt": swap,
                   "compose_file": G.rel(comp), "swap_file": G.rel(mid),
                   "compose_references": job.compose_refs, "compose_qc": cq}
        else:
            base = BASE / job.edit_base
            if not base.exists():
                log(f"ERROR {job.id}: 缺少编辑底图 {job.edit_base}（先跑它）")
                return None
            names = [client.upload_image(_small(base))]
            mid = work / f"{stem}_edit.png"
            _run(client, W.qwen_edit(job.compose, NEG, names, *job.size, seeds["edit"], prefix + "_e", m=model(edit_cfg),
                                     loras=LORAS, ref_resolution=0, crop=False), mid)
            refine_prompt, refine_refs = job.compose, [client.upload_image(_small(mid))]
            rec = {"method": "single_ref_edit on v2 plate (research v9 §1) → refine",
                   "edit_prompt": job.compose, "edit_base": "assets/characters/lin_wan/" + job.edit_base,
                   "edit_base_sha256": G.sha256(base), "edit_file": G.rel(mid)}
        _refine(client, mid, refine_prompt, refine_refs, job.size, seeds["refine"], prefix + "_r", edit_cfg, dest)
        G.clamp(dest)
        q = qc(dest, client)
        secs = time.monotonic() - t0
        if q["nudity"]:
            log(f"QC FLAG {job.id} a{a} {q} -> delete & retry")
            dest.unlink()
            continue
        entry = {"file": dest.name, "kind": job.kind, "design": job.design, "name": job.name,
                 "angle": job.angle, "makeup": job.makeup, **job.extra, **rec,
                 "negative": NEG, "seeds": seeds, "seed": seeds["refine"], "size": list(job.size),
                 "model": G.UNET_BASE, "steps": STEPS, "cfg": CFG, "edit_cfg": edit_cfg,
                 "lora": [list(x) for x in LORAS], "vae": G.VAE_TEX, "refine": dict(REFINE),
                 "references": ["assets/characters/lin_wan/plates/master.png (face crop)"]
                               if job.mode == "two_stage" else ["assets/characters/lin_wan/" + job.edit_base],
                 "master": "assets/characters/lin_wan/plates/master.png", "master_sha256": master_sha,
                 "master_source": "CM_s1 (owner-approved 2026-10-30)",
                 "bible_sha256": bible_sha, "sop": "S2 (docs/SOP_parameters.md 2026-10-30)",
                 "sha256": G.sha256(dest), "qc": q, "attempt": a, "gen_seconds": round(secs, 1),
                 "supersedes": job.supersedes, "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                 "generator": "tools/gen_assets_v2.py"}
        if not pilot:
            _write_manifest(dest.parent, entry)
        log(f"{job.id}_v2{pilot or ''} {secs:.0f}s a{a} qc_bare={q['clip_bare']} vlm={q.get('vlm')}")
        return entry
    log(f"FAILED {job.id}: {attempts} 次均被质检拦截")
    return None


def _write_manifest(folder: Path, entry: dict):
    m = G.load_manifest(folder)
    m = [e for e in m if e.get("file") != entry["file"]]
    for e in m:
        if e.get("file") in entry["supersedes"]:
            e["superseded"] = True
            e["superseded_by"] = entry["file"]
            e["status"] = (f"superseded {time.strftime('%Y-%m-%d')} by {entry['file']} "
                           "(rebuilt from CM_s1 master with SOP S2 recipe; QC v3)")
    m.append(entry)
    G.save_manifest(folder, m)


# ---------------------------------------------------------------- 拼图
def sheets():
    def pick(folder: str, names: list[str]) -> list[Path]:
        return [BASE / folder / n for n in names if (BASE / folder / n).exists()]
    out = []
    master = [MASTER]
    plates = pick("plates", ["id_front_v2.png", "id_front_bare_v2.png", "id_34L_v2.png", "id_34R_v2.png",
                             "id_profile_v2.png", "id_back34_v2.png", "body_F_v2.png"])
    out.append(G.sheet(None, SHEETS / "lin_wan_angles_v2.jpg", master + plates, cols=4, cell=384,
                       title="林晚 多角度底板 v2（母版 CM_s1 → 两段式；S2 配方；QC v3）—— 第一格为母版"))
    ex = pick("expressions", [f"{k}_v2.png" for k in ("calm", "smile", "cry", "angry", "surprised", "seductive")])
    out.append(G.sheet(None, SHEETS / "lin_wan_expressions_v2.jpg", master + ex, cols=4, cell=384,
                       title="林晚 6 表情 v2 —— 第一格为母版"))
    mk = sorted((BASE / "items" / "makeup").glob("L*_v2.png"))
    out.append(G.sheet(None, SHEETS / "lin_wan_makeup_v2.jpg", master + mk, cols=4, cell=384,
                       title="林晚 妆容 L1–L8 v2（research v9；L1/L2 深棕眼，其余灰蓝美瞳）—— 第一格为母版"))
    lk = pick("looks", [f"REF-LW-0{i}_{v}_v2.png" for i in (1, 2) for v in ("front", "34", "back")])
    out.append(G.sheet(None, SHEETS / "lin_wan_looks_v2.jpg", lk, cols=3, cell=384,
                       title="林晚 造型 A（素颜通勤）/ B（浓妆女王）v2 —— C 为规格表，不出上身图"))
    return [str(p) for p in out if p]


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    r = sub.add_parser("run")
    r.add_argument("--only", nargs="*", default=[])
    r.add_argument("--edit-cfg", type=float, default=EDIT_CFG_DEFAULT)
    r.add_argument("--pilot", default=None, help="试跑标签：输出到 golden/assets/v2_work/pilot/，不写 manifest")
    r.add_argument("--comfy", default="http://127.0.0.1:8188")
    sub.add_parser("sheets")
    args = ap.parse_args()
    J = jobs()
    if args.cmd == "list":
        for j in J:
            print(f"{j.id:40s} {j.mode:9s} {j.size} {j.name}")
        print(len(J), "jobs")
        return 0
    if args.cmd == "sheets":
        for p in sheets():
            print(p)
        return 0
    log_path = ROOT / "golden" / "assets" / "gen_log_v2.txt"

    def log(msg):
        line = time.strftime("%H:%M:%S ") + msg
        print(line, flush=True)
        with log_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    client = PoliteClient(args.comfy, log=log)
    sel = [j for j in J if not args.only or any(j.id.startswith(o) for o in args.only)]
    t0, n = time.monotonic(), 0
    for j in sel:
        try:
            if run_job(client, j, args.edit_cfg, log, pilot=args.pilot):
                n += 1
        except Exception as e:  # noqa: BLE001
            log(f"ERROR {j.id}: {type(e).__name__}: {str(e)[:300]}")
            if type(e).__name__ == "ComfyUnavailable":
                break
    log(f"done {n}/{len(sel)} in {time.monotonic() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
