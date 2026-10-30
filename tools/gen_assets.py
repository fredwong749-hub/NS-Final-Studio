"""
林晚角色资产生成器（写实母版 → 身份底板 → 表情 → 单品 → 造型）。

    uv run python tools/gen_assets.py list                          # 列出全部任务
    uv run python tools/gen_assets.py run --only plates/ --seeds 2  # 按 id 前缀筛选
    uv run python tools/gen_assets.py run --only master-ab/ --preset R1 R2
    uv run python tools/gen_assets.py sheet plates                  # 某目录的拼图

规则（research v6 §4 / v7 / docs/lin_wan_asset_inventory.md）：
- 身份参考只用写实母版 plates/master.png（不再喂风格化定妆图，母版 A/B 阶段除外）。
- 裸露单品（束腰、捆绑、丁字裤、穿孔饰品、私密纹身）只出产品图：job.worn=False 且提示词不含人体。
- 所有 worn / 人体图过 nudity_qc；命中即删除，换种子重出（最多 3 次）。
- 输出长边 ≤1536；每个目录一个 manifest.json。
复用 ns_render.workflows.qwen_t2i / qwen_edit（不改 render_router）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from dataclasses import dataclass, field, replace
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from ns_render import workflows as W
from ns_render.comfy_client import ComfyClient

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "assets" / "characters" / "lin_wan"
SHEETS = ROOT / "golden" / "assets" / "sheets"
OWNER_REF = ROOT / "assets" / "linwan" / "file_0000000092c081fd95f7f5b85917993d.png"
MASTER = BASE / "plates" / "master.png"
M0_REF = BASE / "items" / "makeup" / "M0_s0.png"   # v8 §5：灰底正面最干净
MAX_SIDE = 1536

UNET_BASE = "qwen_image_2.1_int8_convrot.safetensors"
UNET_TURBO = "qwen_image_2.1_turbo_int8_convrot.safetensors"
VAE_STD = "qwen_image_2.1_vae_bf16.safetensors"
VAE_TEX = "texture_fix_vae_for_qwen_image_2.1_bf16.safetensors"
LORA_GLAM = "glamour_realism_qwen21.safetensors"
LORA_FILM = "krea2_film_texture_qwen21.safetensors"
LORA_NICE = "nicegirls_v2_qwen21.safetensors"
LORA_PURE = "purelens_qwen21.safetensors"
LORA_T2R = "qwen21-t2r-v1.safetensors"
LORA_A2R = "Qwen2.1_Anything2RealCharacters.safetensors"


# ---------------------------------------------------------------- 写实预设（research v8）
@dataclass(frozen=True)
class Preset:
    name: str
    unet: str = UNET_BASE
    vae: str = VAE_STD
    turbo: bool = False
    steps: int = 25
    cfg: float = 2.5
    sampler: str = "euler"
    loras: tuple[tuple[str, float], ...] = ()
    style: str = ""        # 追加在提示词末尾的摄影/质感段
    negative: str = ""
    trigger: str = ""     # LoRA 触发词，加在提示词开头
    refine_denoise: float = 0.30

    def model(self) -> W.QwenModel:
        return W.QwenModel(unet=self.unet, vae=self.vae, turbo=self.turbo, steps=self.steps, cfg=self.cfg,
                           sampler=self.sampler)


# research v8 §3：去 AI 味提示词（不写 精致/完美/photorealistic/8K）
PHOTO = ("真实相机拍摄的照片质感（写实只加在质感上，不改五官和妆容）：可见细小毛孔和细绒毛、粉底下真实的肤质，真实的一根根发丝与少量碎发飞丝，"
         "自然的光线衰减，真实的眼神光与湿润感；shot on Leica M11, Summilux 50mm f/1.4")
NEG = ("磨皮, 塑料皮肤, 蜡像, 瓷娃娃, 大眼睛, 美瞳, 动漫比例, 网红脸, 过度化妆, 过锐, CGI, 3D render, airbrushed, doll, "
       "多余手指, 手指融合, 肢体变形, 未成年人外观, 裸体, 裸露, 内衣外露, 水印, 文字")

PRESETS: dict[str, Preset] = {
    # 基线：现行出图方式（Turbo 8 步，原版 VAE）
    "R0": Preset("R0", unet=UNET_TURBO, turbo=True, style=PHOTO, negative=NEG),
    # Base 35 步 CFG1 + 纹理 VAE，无 LoRA（只靠提示词）
    "R1": Preset("R1", vae=VAE_TEX, steps=35, cfg=1.0, style=PHOTO, negative=NEG),
    # + krea2 胶片纹理 0.5（v8 推荐）
    "R2": Preset("R2", vae=VAE_TEX, steps=35, cfg=1.0, loras=((LORA_FILM, 0.5),), style=PHOTO, negative=NEG),
    # + krea2 0.5，CFG 2.5 + 负面词生效
    "R3": Preset("R3", vae=VAE_TEX, steps=35, cfg=2.5, loras=((LORA_FILM, 0.5),), style=PHOTO, negative=NEG),
    # 反面对照：glamour_realism 0.6（v8 §0.3 预期更假）
    "R4": Preset("R4", vae=VAE_TEX, steps=35, cfg=1.0, loras=((LORA_GLAM, 0.6),), style=PHOTO, negative=NEG),
    # NiceGirls UltraReal v2（亚洲真人脸质感）
    "R5": Preset("R5", vae=VAE_TEX, steps=35, cfg=1.0, loras=((LORA_NICE, 0.6),), style=PHOTO, negative=NEG),
    # PureLens RAW 实拍
    "R6": Preset("R6", vae=VAE_TEX, steps=35, cfg=1.0, loras=((LORA_PURE, 0.6),), style=PHOTO, negative=NEG,
                 trigger="p3r4l4ns"),
    # Turn2Real（转写实，只用于底板）+ krea2
    "R7": Preset("R7", vae=VAE_TEX, steps=35, cfg=1.0, loras=((LORA_T2R, 0.7), (LORA_FILM, 0.5)), style=PHOTO,
                 negative=NEG, trigger="make the eyes realistic size, make the head smaller"),
    # NiceGirls 0.5 + krea2 0.4（v8 C7 叠加）
    "R8": Preset("R8", vae=VAE_TEX, steps=35, cfg=1.0, loras=((LORA_NICE, 0.5), (LORA_FILM, 0.4)), style=PHOTO,
                 negative=NEG),
    # 母版候选（项目方 2026-10-30：保留参考图的妆容/色调/氛围，写实只加在质感上）轻 / 中 / 强
    "CL": Preset("CL", vae=VAE_TEX, steps=35, cfg=1.0, loras=((LORA_A2R, 0.25), (LORA_FILM, 0.3)), refine_denoise=0.20,
                 trigger="transform the image to realistic photograph"),
    "CM": Preset("CM", vae=VAE_TEX, steps=35, cfg=1.0, loras=((LORA_A2R, 0.45), (LORA_FILM, 0.4)), refine_denoise=0.25,
                 trigger="transform the image to realistic photograph"),
    "CS": Preset("CS", vae=VAE_TEX, steps=35, cfg=1.0, loras=((LORA_A2R, 0.65), (LORA_FILM, 0.5)), refine_denoise=0.30,
                 trigger="transform the image to realistic photograph"),
    # SOP 锁定（visual_bible [realism]，2026-10-30 SOP keeper）：男角色候选 / 文生图
    "SOP": Preset("SOP", vae=VAE_TEX, steps=35, cfg=3.0, loras=((LORA_FILM, 0.5),), refine_denoise=0.30),
    # 同 CM 写实强度，但无触发词（文生图用：男角色候选、场景底板）
    "CMT": Preset("CMT", vae=VAE_TEX, steps=35, cfg=1.0, loras=((LORA_A2R, 0.45), (LORA_FILM, 0.4)), refine_denoise=0.25),
    # Anything2RealCharacters 0.8 + krea2 0.5（v8 §5 底板首选）
    "R9": Preset("R9", vae=VAE_TEX, steps=35, cfg=1.0, loras=((LORA_A2R, 0.8), (LORA_FILM, 0.5)), style=PHOTO,
                 negative=NEG, trigger="transform the image to realistic photograph"),
}
DEFAULT_PRESET = "R2"   # A/B 后改成选中的预设（写进 golden/assets/notes.md）
CHOSEN_FILE = ROOT / "golden" / "assets" / "chosen_preset.json"


def chosen_preset() -> Preset:
    if CHOSEN_FILE.exists():
        d = json.loads(CHOSEN_FILE.read_text(encoding="utf-8"))
        base = PRESETS[d["base"]]
        over = {k: (tuple(tuple(x) for x in v) if k == "loras" else v) for k, v in d.get("override", {}).items()}
        return replace(base, **over)
    return PRESETS[DEFAULT_PRESET]


# ---------------------------------------------------------------- 任务
@dataclass
class Job:
    id: str                    # 目录/文件名，如 plates/id_front
    kind: str                  # plate / expression / item/outfit / item/shoes / ... / look
    design: str                # 设计/单品 id（LW-O08 等）
    name: str
    prompt: str
    size: tuple[int, int] = (1024, 1024)
    refs: list[Path] = field(default_factory=list)   # 空 = 文生图
    worn: bool = True          # 有人体 → 过裸露质检
    identity: bool = True      # 用母版做身份参考（refs 为空时自动补母版）
    preset: str | None = None  # None = 选中的预设
    style: bool = True         # 是否追加预设的摄影段（产品图用自己的段）
    extra: dict = field(default_factory=dict)   # 额外写进 manifest 的字段
    negative: str | None = None                  # 覆盖负面词

    @property
    def folder(self) -> Path:
        if self.id.startswith(("master_ab/", "master_cand/")):
            return ROOT / "golden" / "assets" / self.id.split("/")[0]
        return BASE / Path(self.id).parent

    @property
    def stem(self) -> str:
        return Path(self.id).name


ID_KEEP = ("图1只提供林晚的身份与妆容：同一个人，保持图1的脸型、眉形、眼型与眼线、睫毛、鼻子、唇形与饱满度、冷白肤色、脸颊小痣、灰蓝色眼睛（大小与图1一致）、"
           "与图1相同的天蓝色及腰直发与齐刘海，以及图1的粉甜妆容（粉色腮红、水润粉色唇釉、浓密卷翘但根根分明的睫毛）；"
           "不要沿用图1的姿势、手势、项链、服装、背景和构图。")
ID_KEEP_BARE = ("图1只提供林晚的身份：同一个人，保持图1的脸型、眉形、眼型、鼻子、唇形与饱满度、冷白肤色、脸颊小痣、与图1相同的天蓝色及腰直发与齐刘海；"
                "去掉图1的全部妆容：没有腮红、没有唇彩、没有眼线和假睫毛，眼睛改为自然深棕色（不戴美瞳，大小与图1一致）；"
                "不要沿用图1的姿势、手势、项链、服装、背景和构图。")
GREY = "背景为纯净的中性灰色无缝摄影背景纸（#808080），无任何道具，柔和均匀的大面积棚拍光"
BASIC = "穿素色浅灰色圆领短袖T恤，不戴任何首饰"
BODY_BASIC = "穿一条素色深海军蓝长袖针织连衣裙（圆领、及膝、不透明），白色平底帆布鞋，不戴任何首饰"
PRODUCT = ("专业电商产品摄影，商品居中完整入画，纯白或浅灰无缝背景，柔和箱灯与清晰的材质反光，"
           "画面中没有任何人体、没有模特、没有皮肤，无文字无水印，100mm 微距镜头，细节锐利")
PRODUCT_NEG = "人体、模特、皮肤、手、脚、脸、裸体、文字、水印、标志、低清、变形"


def jobs_master_ab() -> list[Job]:
    """写实母版 A/B：以项目方定妆图为编辑对象，做同一人的写实照片版。"""
    p = ("把图1转为真实人像摄影：同一个人，保持脸型轮廓、鼻型、唇形、雾霾天蓝色及腰顺直长发（偏灰的中浅蓝，比图1略深略灰，像真实染发，发根略深）和齐刘海、冷白肤色、整体辨识度；"
         "保留左脸颊靠近鼻翼的小痣；把眼睛改为真实成年亚洲女性的正常大小（中等大小的杏眼），自然深棕色眼睛，不戴美瞳，瞳孔大小正常，去掉夸张粘连的睫毛，腮红减到很淡，唇部自然不嘟；皮肤有毛孔和细绒毛，无磨皮。"
         "正面胸像，平视镜头，放松的中性表情，双手不入画，不戴首饰，穿素色浅灰色圆领T恤；"
         "灰色无缝背景，柔和窗光，真实照片")
    return [Job(f"master_ab/{k}", "plate", "LW-MASTER", f"写实母版 A/B {k}", p, (1024, 1536),
                refs=[M0_REF], identity=False, preset=k) for k in PRESETS]


CAND_PROMPT = ("把图1变成一张真实相机拍摄的照片，只改变质感，不改变内容：保持图1的同一个人、脸型、眉形、眼型与眼线、睫毛、鼻子、唇形与饱满度、"
               "粉色腮红、水润粉色唇釉、精致的粉甜妆容、手托腮的姿势、草莓水晶项链、粉色衣服、粉色玫瑰与柔和暖色逆光、奶油般的背景虚化和整体色调，构图不变；"
               "加入真实的皮肤纹理：可见细小毛孔和细绒毛，粉底下真实的肤质，自然的光线衰减；头发是真实的一根根发丝，有少量碎发与飞丝，"
               "发色与图1相近的天蓝色、只略深一点点，不发灰；灰蓝色眼睛，眼睛大小只比图1略小一点点，更接近真人比例；"
               "睫毛浓密卷翘但根根分明；真实的眼神光与湿润感；shot on Leica M11, Summilux 50mm f/1.4, natural skin texture")


def jobs_master_cand() -> list[Job]:
    """母版候选：从项目方参考图本身编辑，写实强度 轻/中/强 × 2 种子（tag 由 run 的 seed 区分）。"""
    return [Job(f"master_cand/{k}", "plate", "LW-MASTER", f"母版候选 {k}", CAND_PROMPT, (1024, 1472),
                refs=[OWNER_REF], identity=False, preset=k, style=False) for k in ("CL", "CM", "CS")]


def jobs_plates() -> list[Job]:
    J = []
    head = (1024, 1024)
    J.append(Job("plates/id_front", "plate", "LW-ID-F", "正脸底板（淡妆）",
                 ID_KEEP + "正面头肩照，平视镜头，中性放松表情，嘴唇自然闭合，保持图1的妆容，头发自然垂在两侧和身后，" + BASIC + "，" + GREY, head))
    J.append(Job("plates/id_front_bare", "plate", "LW-ID-F-bare", "正脸底板（素颜，深棕眼）",
                 ID_KEEP_BARE + "正面头肩照，平视镜头，中性表情，完全素颜（不保留图1的妆容）：无眼线无睫毛膏无唇彩，自然深棕色眼睛（不戴美瞳），可见自然的皮肤纹理和淡淡黑眼圈，" + BASIC + "，" + GREY, head))
    J.append(Job("plates/id_front_heavy", "plate", "LW-ID-F-heavy", "正脸底板（浓妆）",
                 ID_KEEP + "正面头肩照，平视镜头，中性冷艳表情，灰蓝色眼睛，不保留图1的粉甜妆，改为浓妆女王妆（妆感明显）：半哑光底妆，颧骨下晕开的灰棕修容；梅子棕到深咖截断式眼窝，拉长黑色狐狸眼线，下眼睑后三分之一深咖烟熏；簇状睫毛；黑樱桃色丝绒唇，边缘干净略晕；低饱和莓果腮红；粉底下仍可见毛孔，" + BASIC + "，" + GREY, head))
    J.append(Job("plates/id_34L", "plate", "LW-ID-34L", "3/4 侧脸（脸朝画面左）",
                 ID_KEEP + "四分之三侧脸头肩照：她的脸和身体朝向画面左侧约45度，眼睛看向画面左前方，能看到她的右耳一侧的头发，中性表情，保持图1的妆容，" + BASIC + "，" + GREY, head))
    J.append(Job("plates/id_34R", "plate", "LW-ID-34R", "3/4 侧脸（脸朝画面右）",
                 ID_KEEP + "四分之三侧脸头肩照：她的脸和身体朝向画面右侧约45度，眼睛看向画面右前方，中性表情，保持图1的妆容，" + BASIC + "，" + GREY, head))
    J.append(Job("plates/id_profile", "plate", "LW-ID-P", "正侧面（脸朝画面左）",
                 ID_KEEP + "标准正侧面头肩照：她的脸完全转向画面左侧90度，只看到一只眼睛，鼻尖和下巴的侧面轮廓清晰，齐刘海从侧面看呈一条直线，长直发垂到背后，中性表情，" + BASIC + "，" + GREY, head))
    J.append(Job("plates/id_back", "plate", "LW-ID-B", "背面：后脑与及腰长发",
                 ID_KEEP + "从正后方拍摄她的背影，看不到脸，只看到后脑和天蓝色顺直长发一直垂到腰部，发尾整齐，上半身到臀部入画，" + BASIC + "，" + GREY, (768, 1344)))
    for k, (view, desc) in {"F": ("正面", "正面全身站姿，面向镜头，双臂自然垂在身侧，双脚并拢平放在地上"),
                            "S": ("侧面", "正侧面全身站姿，身体朝向画面左侧，双臂自然垂下"),
                            "B": ("背面", "背面全身站姿，背对镜头，看不到脸，天蓝色直发垂到腰部")}.items():
        J.append(Job(f"plates/body_{k}", "plate", f"LW-BODY-{k}", f"全身底板（{view}）",
                     ID_KEEP + f"从头顶到脚完整入画的{desc}，身材修长匀称、腿长、身高约170厘米，" + BODY_BASIC + "，" + GREY, (768, 1344)))
    return J


def jobs_expressions() -> list[Job]:
    ex = {"calm": ("平静", "平静、放空的表情，嘴唇自然闭合"),
          "smile": ("微笑", "真诚的浅浅微笑，嘴角上扬，眼睛微弯，露出一点牙齿"),
          "cry": ("哭（泪与笑）", "正在流泪：眼眶和鼻尖明显泛红，下眼睑盈满泪水，两道清晰发亮的泪痕从眼角一直流到下巴，一颗泪珠挂在脸颊上，眉头微蹙，嘴角却轻轻上扬（泪与笑同框）"),
          "angry": ("怒", "生气：眉头紧皱，目光锐利地直视镜头，嘴唇抿紧，下颌收紧"),
          "surprised": ("惊", "吃惊：眼睛睁大，眉毛上扬，嘴唇微微张开"),
          "seductive": ("媚眼", "含情的媚眼：眼皮微垂、眼神从睫毛下向上看着镜头，嘴唇微启，下巴微收")}
    return [Job(f"expressions/{k}", "expression", f"LW-EXP-{k}", n,
                ID_KEEP + "正面头肩照，只改变表情：" + d + "，保持图1的妆容，" + BASIC + "，" + GREY, (1024, 1024))
            for k, (n, d) in ex.items()]


def load_extra() -> list[Job]:
    """单品 / 造型任务定义在 tools/gen_assets_items.py（体量大，单独放）。"""
    try:
        import gen_assets_items as I
    except ImportError:
        return []
    return I.jobs(Job, dict(ID_KEEP=ID_KEEP, GREY=GREY, BASIC=BASIC, BODY_BASIC=BODY_BASIC, PRODUCT=PRODUCT))


def all_jobs() -> list[Job]:
    return jobs_master_ab() + jobs_master_cand() + jobs_plates() + jobs_expressions() + load_extra()


# ---------------------------------------------------------------- 运行
def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def rel(p: Path) -> str:
    return str(p.resolve().relative_to(ROOT)).replace("\\", "/")


def seed_for(job_id: str, k: int) -> int:
    return int(hashlib.sha256(f"lin_wan/{job_id}#{k}".encode()).hexdigest()[:12], 16)


def prep_ref(p: Path, side: int = 1024) -> Path:
    """参考图预缩放（长边 side），存到 golden/assets/_refs/。"""
    out = ROOT / "golden" / "assets" / "_refs" / f"{p.stem}_{side}.png"
    if not out.exists() or out.stat().st_mtime < p.stat().st_mtime:
        out.parent.mkdir(parents=True, exist_ok=True)
        im = Image.open(p).convert("RGB")
        im.thumbnail((side, side), Image.LANCZOS)
        im.save(out)
    return out


def clamp(p: Path):
    im = Image.open(p)
    if max(im.size) > MAX_SIDE:
        im.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
        im.save(p)


def load_manifest(folder: Path) -> list[dict]:
    mp = folder / "manifest.json"
    return json.loads(mp.read_text(encoding="utf-8")) if mp.exists() else []


def save_manifest(folder: Path, entries: list[dict]):
    (folder / "manifest.json").write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")


_qc = None
_vlm = None


def qc(path: Path, client: ComfyClient | None = None) -> dict:
    """QC v3：NudeNet + CLIP + Qwen3-VL 看图裁决（ns_render.qc.vlm_judge）"""
    global _qc, _vlm
    if _qc is None:
        from ns_render.qc import nudity_qc as _qc_fn, vlm_judge
        _qc = _qc_fn
        _vlm = vlm_judge(client or ComfyClient())
    return _qc(path, vlm=_vlm)


REFINE = {"scale": 1.5, "steps": 12, "denoise": 0.30}


def refine_graph(first_pass: str, prompt: str, negative: str, refs: list[str], w: int, h: int, seed: int,
                 prefix: str, preset: Preset) -> dict:
    """v8 §4.1 第二遍低重绘：1.5× 放大 → VAEEncode → Base 12 步 denoise 0.30（同提示词/参考/LoRA）。"""
    m = replace(preset, unet=UNET_BASE, turbo=False).model()
    W2, H2 = int(w * REFINE["scale"]) // 16 * 16, int(h * REFINE["scale"]) // 16 * 16
    if refs:
        wf = W.qwen_edit(prompt, negative, refs if len(refs) > 1 else refs[0], W2, H2, seed, prefix, m=m,
                         loras=list(preset.loras), ref_resolution=0, crop=False)
    else:
        wf = W.qwen_t2i(prompt, negative, W2, H2, seed, prefix, m=m, loras=list(preset.loras))
    wf["201"] = {"class_type": "LoadImage", "inputs": {"image": first_pass}}
    wf["202"] = {"class_type": "ImageScale", "inputs": {"image": ["201", 0], "upscale_method": "lanczos",
                                                        "width": W2, "height": H2, "crop": "disabled"}}
    wf["203"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["202", 0], "vae": ["12", 0]}}
    wf["40"]["inputs"]["latent_image"] = ["203", 0]
    wf["37"]["inputs"].update({"steps": REFINE["steps"], "denoise": preset.refine_denoise})
    wf.pop("34", None)
    return wf


def run_job(client: ComfyClient, job: Job, k: int, preset: Preset, force: bool, log, refine: bool = False) -> dict | None:
    job.folder.mkdir(parents=True, exist_ok=True)
    suffix = f"_s{k}"
    dest = job.folder / f"{job.stem}{suffix}.png"
    manifest = load_manifest(job.folder)
    if dest.exists() and not force and any(m["file"] == dest.name for m in manifest):
        log(f"skip {job.id}{suffix} (exists)")
        return None
    refs = list(job.refs)
    if not refs and job.identity:
        if not MASTER.exists():
            raise SystemExit("缺少写实母版 plates/master.png —— 先跑 master_ab 并选定")
        refs = [MASTER]
    prompt = job.prompt + (("。" + preset.style) if job.style and job.identity and preset.style else "")
    if not job.identity and job.worn:
        prompt += "。真实相机拍摄的原片，未修图，皮肤有真实纹理与细小毛孔，shot on Leica M11, 50mm, Kodak Portra 400 film look"
    if preset.trigger:
        prompt = preset.trigger + "，" + prompt
    negative = job.negative if job.negative is not None else (preset.negative if job.worn or job.identity else PRODUCT_NEG)
    model = preset.model()
    for attempt in range(4):
        seed = seed_for(job.id, k + 100 * attempt)
        prefix = f"ns_final/lw_assets/{job.id.replace('../', 'chars_').replace('/', '_')}"
        if refs:
            names = [client.upload_image(prep_ref(r)) for r in refs]
            wf = W.qwen_edit(prompt, negative, names if len(names) > 1 else names[0], *job.size, seed, prefix,
                             m=model, loras=list(preset.loras), ref_resolution=0, crop=False)
        else:
            wf = W.qwen_t2i(prompt, negative, *job.size, seed, prefix, m=model, loras=list(preset.loras))
        entry, secs = client.run(wf, timeout_s=3600)
        item = next(f for f in client.output_files(entry) if f["filename"].endswith(".png"))
        client.download(item, dest)
        if refine:
            fp = client.upload_image(dest)
            wf2 = refine_graph(fp, prompt, negative, names if refs else [], *job.size, seed + 1, prefix + "_r", preset)
            entry2, secs2 = client.run(wf2, timeout_s=3600)
            item = next(f for f in client.output_files(entry2) if f["filename"].endswith(".png"))
            client.download(item, dest)
            secs += secs2
        clamp(dest)
        qres = None
        if job.worn:
            qres = qc(dest, client)
            if qres["nudity"]:
                log(f"QC FLAG {job.id}{suffix} seed={seed} {qres} -> delete & retry")
                import os, shutil
                q = os.environ.get("NS_QC_QUARANTINE")
                if q:   # 诊断用：被拦截的图移到临时目录（不进资产库，事后删除）
                    Path(q).mkdir(parents=True, exist_ok=True)
                    shutil.move(str(dest), str(Path(q) / f"{job.stem}_{seed}.png"))
                else:
                    dest.unlink()
                continue
        entry_m = {"file": dest.name, "kind": job.kind, "design": job.design, "name": job.name,
                   "prompt": prompt, "negative": negative, "seed": seed, "size": list(job.size),
                   "model": preset.unet, "steps": 8 if preset.turbo else preset.steps,
                   "cfg": 1.0 if preset.turbo else preset.cfg, "preset": preset.name,
                   "lora": [list(x) for x in preset.loras], "vae": preset.vae,
                   "refine": dict(REFINE, denoise=preset.refine_denoise) if refine else None,
                   "references": [rel(r) for r in refs], "sha256": sha256(dest),
                   "qc": qres, "gen_seconds": round(secs, 1), **job.extra,
                   "created_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        manifest = [m for m in load_manifest(job.folder) if m["file"] != dest.name] + [entry_m]
        save_manifest(job.folder, manifest)
        log(f"{job.id}{suffix} [{preset.name}] {secs:.0f}s seed={seed}" + (f" qc_bare={qres['clip_bare']}" if qres else ""))
        return entry_m
    log(f"FAILED {job.id}{suffix}: 4 次均被质检拦截")
    return None


def sheet(folder: Path, out: Path, files: list[Path] | None = None, cols: int = 4, cell: int = 384,
          title: str = ""):
    files = files or sorted(p for p in folder.glob("*.png"))
    if not files:
        return None
    ims = []
    for p in files:
        im = Image.open(p).convert("RGB")
        im.thumbnail((cell, int(cell * 1.75)), Image.LANCZOS)
        ims.append((p.stem, im))
    rows = (len(ims) + cols - 1) // cols
    ch = max(im.size[1] for _, im in ims) + 22
    top = 30 if title else 0
    W_, H_ = cols * cell, rows * ch + top
    canvas = Image.new("RGB", (W_, H_), (24, 24, 24))
    d = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 16)
    except OSError:
        font = ImageFont.load_default()
    if title:
        d.text((8, 6), title, fill=(240, 240, 240), font=font)
    for i, (name, im) in enumerate(ims):
        x, y = (i % cols) * cell, top + (i // cols) * ch
        canvas.paste(im, (x + (cell - im.size[0]) // 2, y))
        d.text((x + 4, y + ch - 20), name, fill=(230, 230, 230), font=font)
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out, quality=88)
    return out


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.path.insert(0, str(Path(__file__).parent))
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    r = sub.add_parser("run")
    r.add_argument("--only", nargs="*", default=[])
    r.add_argument("--seeds", type=int, default=1)
    r.add_argument("--seed-offset", type=int, default=0)
    r.add_argument("--preset", nargs="*", default=None, help="覆盖预设（master_ab 自带）")
    r.add_argument("--force", action="store_true")
    r.add_argument("--refine", action="store_true", help="v8 第二遍低重绘")
    r.add_argument("--tag", default="", help="输出文件名后缀（A/B 用）")
    r.add_argument("--class", dest="klass", choices=["product", "worn", "identity"], default=None,
                   help="product=不带身份参考的图（产品/手脚/男候选），identity=用母版做身份参考的图")
    r.add_argument("--comfy", default="http://127.0.0.1:8188")
    s = sub.add_parser("sheet")
    s.add_argument("folder")
    s.add_argument("--cols", type=int, default=4)
    args = ap.parse_args()

    jobs = all_jobs()
    if args.cmd == "list":
        for j in jobs:
            print(f"{j.id:40s} {j.kind:14s} {j.design:14s} worn={j.worn} {j.name}")
        print(len(jobs), "jobs")
        return 0
    if args.cmd == "sheet":
        folder = BASE / args.folder
        out = SHEETS / (args.folder.replace("/", "_") + ".jpg")
        print(sheet(folder, out, cols=args.cols, title=f"lin_wan/{args.folder}"))
        return 0

    sel = [j for j in jobs if not args.only or any(j.id.startswith(o) for o in args.only)]
    if args.cmd == "run" and args.klass:
        uses_master = lambda j: j.identity or any(r == MASTER for r in j.refs)
        sel = [j for j in sel if (args.klass == "identity") == uses_master(j)] if args.klass != "worn" else               [j for j in sel if j.worn]
    client = ComfyClient(args.comfy)
    log_path = ROOT / "golden" / "assets" / "gen_log.txt"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    def log(msg):
        line = time.strftime("%H:%M:%S ") + msg
        print(line, flush=True)
        with log_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    t0 = time.monotonic()
    n = 0
    for j in sel:
        presets = [PRESETS[p] for p in args.preset] if args.preset else [PRESETS[j.preset] if j.preset else chosen_preset()]
        for p in presets:
            jj = j if len(presets) == 1 else replace(j, id=f"{j.id}_{p.name}")
            if args.tag:
                jj = replace(jj, id=f"{jj.id}{args.tag}")
            for k in range(args.seed_offset, args.seed_offset + args.seeds):
                try:
                    if run_job(client, jj, k, p, args.force, log, refine=args.refine):
                        n += 1
                except Exception as e:  # noqa: BLE001 — 单张失败不拖垮整批
                    log(f"ERROR {jj.id}_s{k}: {type(e).__name__}: {str(e)[:300]}")
    log(f"done {n} images in {time.monotonic() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
