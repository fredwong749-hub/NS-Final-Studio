"""Job lists for character assets (run on gpu3 by asset_gen.py). Recipe: research v6 角色资产与一致性.md.

    python build_jobs.py stage1            -> jobs/stage1.jsonl
    python build_jobs.py stage2 --idf <png name in gpu3 refs/> --body ...   (after picking plates)

Conventions
- edit jobs (refs): Qwen-Image 2.1 Base (or NoctQ V4), 25 steps, CFG 1, euler/simple, resolution=0, refs pre-scaled.
- text-to-image jobs (no refs: products, male candidates): wardrobe-validated t2i settings
  (NoctQ V4 / Base, 25 steps, CFG 2.5, er_sde/beta) so the negative prompt is active.
- every prompt opens with one role line per reference ("Figure N: ...") and says what NOT to copy.
- no "photorealistic"/"8K" quality words (plastic skin on Qwen 2.1); optical wording instead.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

GR = "/root/claude-kimi-ns-studio-v1/nsfs_assets/refs/"
BASE = "qwen_image_2.1_int8_convrot.safetensors"
NOCTQ = "NoctQ_V4_int8_convrot.safetensors"
T2I = dict(cfg=2.5, sampler="er_sde", scheduler="beta")
OUT = Path(__file__).parent / "jobs"

LW_ID = ("Figure 1 is the identity reference of Lin Wan, an adult woman (22, fictional, AI-generated). Use Figure 1 ONLY for her "
         "facial identity: face shape, large eyes with light grey-blue irises, nose, lips, the small mole under her left eye, "
         "cool porcelain-white skin, light-blue waist-length straight hair with blunt bangs. Do NOT copy Figure 1's pose, hand, "
         "necklace, clothing, flowers, background, colours or lighting. ")
OPTICS_PLATE = ("85mm lens at f/8, the whole face in sharp focus, natural skin texture with visible pores, fine flyaway hairs, "
                "individual hair strands. No text, no watermark.")
OPTICS_HERO = ("Shot on a Leica M with a Summilux 50mm at f/1.4: razor-thin focus plane on the eyes, crisp micro-contrast on the "
               "lashes and iris, creamy smooth bokeh; natural skin pores and fine peach fuzz, no airbrushing. Clean, bright, "
               "richly coloured and translucent image, large soft light source with warm highlights. No text, no watermark.")
PLATE_BG = "Seamless flat mid-grey studio backdrop, soft even frontal lighting, no props. "
PRODUCT = ("Studio product photo on a seamless white background, soft even light, sharp focus, crisp material detail. "
           "No people, no text, no logo, no brand marks.")


def j(id, prompt, **kw):
    return {"id": id, "prompt": prompt, **kw}


def stage1():
    face = GR + "lw_face_closeup_768.png"
    jobs = []
    # --- prototypes: neutral front identity plate, Base vs NoctQ (same seed)
    idf = LW_ID + ("Create a neutral identity reference photo: head and shoulders, front view, facing the camera straight on, head "
                   "level, eyes looking into the lens, neutral relaxed expression with lips closed, hands out of frame. She wears a "
                   "plain heather-grey crew-neck cotton T-shirt, no jewellery, no necklace, no earrings. " + PLATE_BG + OPTICS_PLATE)
    jobs += [j("proto_idF_base", idf, refs=[face], latent="empty", w=1024, h=1024, seed=1101),
             j("proto_idF_noctq", idf, refs=[face], latent="empty", w=1024, h=1024, seed=1101, unet=NOCTQ)]
    # --- master identity (beauty-polished hero set, owner colour style)
    hero = LW_ID + ("Beauty portrait of her{frame}. Douyin-style beauty makeup kept natural: big doe eyes with full natural lashes, "
                    "soft rosy blush high on the cheeks and nose tip, glossy pink-coral gradient bitten lips, soft glow on cool "
                    "porcelain skin, healthy shine along the light-blue hair. She wears a simple white silk camisole, no jewellery. "
                    "Bright airy bedroom by a large window, out of focus. " + OPTICS_HERO)
    frames = [(", head and shoulders, front view, looking into the lens, gentle closed-mouth smile", 1024, 1024),
              (", head and shoulders, three-quarter view facing camera left, eyes to the lens, lips slightly parted", 1024, 1024),
              (", waist-up, front view, relaxed shoulders, arms down out of frame, calm soft gaze", 768, 1344)]
    for i, (fr, w, h) in enumerate(frames, 1):
        for model, tag in ((BASE, "b"), (NOCTQ, "n")):
            jobs.append(j(f"lw_master_hero_{i:02d}{tag}", hero.format(frame=fr), refs=[face], latent="empty", w=w, h=h,
                          seed=2100 + i, unet=model))
    # --- wardrobe product shots (t2i)
    prods = {
        "shoes_hh12clear": "A pair of 12 cm clear PVC side-open pointed-toe stiletto pumps with a very thin transparent stiletto "
                           "heel and a nude insole, side profile view.",
        "shoes_hh12patent": "A pair of 12 cm black high-gloss patent leather side-open (d'Orsay) pointed-toe stiletto pumps with a "
                            "very thin heel, side profile view, softbox reflections on the patent.",
        "outfit_office_suit": "A women's minimalist office outfit laid out flat: a crisp white fitted cotton shirt, a black "
                              "knee-length pencil skirt and a matching black single-button blazer, top-down flat lay.",
        "outfit_homewear": "Women's soft home wear laid out flat: an oversized light-grey knit cardigan, a loose white cotton "
                           "camisole and loose light-grey cotton lounge shorts, top-down flat lay.",
        "outfit_ptxtrench": "A black high-gloss patent leather long trench coat, double-breasted, belted, knee-to-calf length, on a "
                            "headless white dress-form mannequin, front view.",
        "outfit_ptxcorset": "A black high-gloss patent leather underbust waist-cinching corset with front silver busk and back "
                            "lacing, on a headless white dress-form mannequin, front view.",
        "outfit_ptxharness": "Black high-gloss patent strappy harness lingerie: halter neck strap, thin straps with silver buckles, "
                             "a central silver O-ring under the bust, narrow straps down the waist to a strappy thong with silver "
                             "D-rings, on a headless black dress-form mannequin, front view.",
        "outfit_ltxsuit": "A black glossy latex catsuit with long sleeves, high neck and front zip, on a headless white dress-form "
                          "mannequin, front view, liquid-shine highlights.",
    }
    for k, (pid, desc) in enumerate(prods.items()):
        jobs.append(j(f"lw_item_{pid}_prod", desc + " " + PRODUCT, latent="empty", w=1024, h=1024, seed=3100 + k,
                      unet=NOCTQ, **T2I))
    # --- male leads: text-only candidates (no owner reference), neutral clothing, grey backdrop
    men = {
        "gu_chen": ("a 34-year-old adult Chinese man, CEO, mature, restrained and handsome, short neat black hair swept back, "
                    "defined jaw, light stubble, tall and lean", 3),
        "chen_yu": ("a 23-year-old adult Chinese man, warm and sunny, boyish smile, soft tousled brown-black hair with a fringe, "
                    "lightly tanned, slim athletic build", 3),
        "alex": ("Alex K, a 29-year-old adult man, tall and gentle, friendly open face, short wavy dark-blond hair, light beard, "
                 "broad shoulders, well groomed", 2),
        "ryan": ("Ryan M, an adult man around 30, sharp and capable, neat short black undercut, clean-shaven, lean muscular build, "
                 "East Asian", 2),
        "kai": ("Kai J, an adult man around 26, scholarly and shy, slim, round thin-rimmed glasses, soft straight black hair "
                "parted in the middle, East Asian", 2),
        "leo": ("Leo Vane, an adult man around 38, mature and steady, salt-and-pepper short hair, trimmed beard, deep-set calm "
                "eyes, solid build, European", 2),
    }
    for c, (desc, n) in men.items():
        for s in range(n):
            jobs.append(j(f"{c}_cand_{s + 1:02d}",
                          f"Full-body identity reference photo of {desc}. Standing straight, front view, arms relaxed at his "
                          "sides, neutral expression, looking into the lens. Plain charcoal crew-neck T-shirt, dark straight "
                          "trousers, plain dark shoes, no jewellery. " + PLATE_BG +
                          "50mm lens at f/8, sharp from head to toe, natural skin texture with pores. No text, no watermark.",
                          latent="empty", w=832, h=1216, seed=4100 + 10 * list(men).index(c) + s, unet=BASE, **T2I))
    return jobs


def stage2(idf: str):
    """Angles, body plates, expressions, hair variants — all edited from the chosen front plate LW-ID-F."""
    ref = [GR + idf]
    role = ("Figure 1 is the neutral identity plate of Lin Wan, an adult woman (22, fictional). Keep her exact face, eye colour, "
            "skin tone, the mole under her left eye and her light-blue waist-length straight hair with blunt bangs. ")
    keep = "Same plain heather-grey T-shirt, no jewellery. " + PLATE_BG + OPTICS_PLATE
    jobs = []
    angles = {
        "34L": "three-quarter view: her face is turned toward the LEFT side of the image, about 45 degrees, eyes following the head",
        "34R": "three-quarter view: her face is turned toward the RIGHT side of the image, about 45 degrees, eyes following the head",
        "PL": "exact side profile: her face points to the LEFT edge of the image, only one eye visible",
        "PR": "exact side profile: her face points to the RIGHT edge of the image, only one eye visible",
    }
    for k, (a, d) in enumerate(angles.items()):
        jobs.append(j(f"lw_plate_ID-{a}", role + f"Rotate her head: {d}. Head and shoulders, neutral expression, lips closed. "
                      "Do not mirror the image; keep the bangs and parting as in Figure 1. " + keep,
                      refs=ref, latent="empty", w=1024, h=1024, seed=5101 + k))
    jobs.append(j("lw_plate_ID-B", role + "Back view: she stands with her back to the camera, the back of her head and her full "
                  "light-blue straight hair falling to her waist, no face visible. Upper body to the hips. " + keep,
                  refs=ref, latent="empty", w=768, h=1344, seed=5105))
    body = ("She wears a plain fitted light-grey long-sleeve seamless bodysuit and is barefoot; no jewellery. Full body from head "
            "to toe, standing straight, arms relaxed slightly away from the body, feet slightly apart. " + PLATE_BG +
            "50mm lens at f/8, sharp from head to toe, natural skin texture. No text, no watermark.")
    for k, (v, d) in enumerate((("F", "front view, facing the camera"), ("S", "side view, body facing the LEFT edge of the image"),
                                ("B", "back view, her back to the camera, hair falling to her waist"))):
        jobs.append(j(f"lw_plate_BODY-{v}", role + f"Full-body reference, {d}. " + body,
                      refs=ref, latent="empty", w=768, h=1344, seed=5201 + k))
    exprs = {
        "neutral": "a calm neutral expression, lips closed",
        "smile": "a warm natural smile showing a little of her upper teeth, eyes smiling",
        "shy": "a shy expression: eyes lowered, a small embarrassed smile, light pink flush on the cheeks",
        "tense": "a tense, anxious expression: brows drawn together, lips pressed, jaw tight",
        "lipbite": "a teasing look, biting her lower lip gently, eyes to the lens",
        "flushed": "a flushed, breathless expression: deep pink flush across cheeks and nose, lips parted, heavy-lidded eyes",
        "tearful": "a tearful expression: glassy eyes with tears on the lower lashes, one tear on the cheek, trembling lips",
    }
    for k, (e, d) in enumerate(exprs.items()):
        jobs.append(j(f"lw_expr_{e}", role + f"Change only her facial expression to {d}. Keep head pose, framing, clothing, "
                      "background and lighting identical to Figure 1.", refs=ref, latent="ref", seed=5301 + k))
    hairs = {
        "ponytail": "a sleek high ponytail, bangs kept",
        "waves": "loose glossy waves through the lengths, bangs kept",
        "wet": "wet-look hair slicked back off the face, damp strands",
        "bun": "a low elegant bun with a few loose strands, bangs kept",
    }
    for k, (h, d) in enumerate(hairs.items()):
        jobs.append(j(f"lw_hair_{h}", role + f"Change only her hairstyle to {d}; keep the same light-blue colour. Keep face, "
                      "expression, clothing, background and lighting identical.", refs=ref, latent="ref", seed=5401 + k))
    return jobs


NAILS_HAND = {  # research v7 §2 (fredw-d9), prompt descriptions verbatim
    "N1": ("冰川满钻尖甲", "超长透明尖头延长甲，甲长约为手指长度的三分之二，透明水晶底，甲根带一点淡冰蓝，甲面铺满密集的细碎白色水钻，"
                      "甲根一排较大的圆形钻石，指尖末端保留透明，高光镜面封层，钻面清晰反光"),
    "N2": ("草莓糖霜芭蕾", "超长透明芭蕾形延长甲，指尖平切、两侧收窄，透明底向甲尖渐变为淡粉色，中指和无名指各贴一颗立体粉色草莓形水晶饰品，"
                       "其余手指沿甲边镶一圈细白钻，高光透亮"),
    "N3": ("极光冰透猫眼", "超长透明杏仁形延长甲，冰透玻璃质感，甲面有一道银白色猫眼光带和彩虹极光偏光，甲根月牙形镶一排极光水钻，"
                       "侧边点缀两三颗马眼形钻，湿润高光"),
    "N4": ("钻链珠宝甲", "超长透明尖头延长甲，透明水晶底，甲根各镶一颗大水滴形钻石，一条极细的银色链条从甲根垂挂到甲面中部，末端坠一颗小钻，"
                      "食指甲尖穿一个小银环，珠宝质感，金属与钻面反光"),
    "N5": ("冰晶吹制玻璃", "超长透明芭蕾形延长甲，甲面有立体的透明玻璃凝胶纹理，像吹制玻璃和冰棱，冰棱之间嵌着散落的小白钻和少量冰蓝色钻，"
                       "整体晶莹剔透，强高光"),
    "N6": ("粉钻垃圾甲（夜场款）", "超长透明尖头延长甲，每根手指款式不同：拇指铺满粉色水钻，食指心形钻配小珍珠，中指立体草莓水晶，无名指细银链，"
                            "小指铺满白钻，极繁主义珠宝美甲，透明底，高光"),
}
NAILS_TOE = {  # research v7 §3
    "T1": ("冰透满钻方圆", "脚趾甲透明冰透延长，方圆形，大脚趾甲略长出脚趾前端，甲面铺满细白钻，其余脚趾甲根各一颗小钻，比例自然，高光镜面"),
    "T2": ("草莓裸粉法式", "脚趾甲短杏仁形透明裸粉延长，甲尖一道细白钻法式边，大脚趾点缀一颗小粉色草莓水晶，光泽饱满，脚趾修长干净"),
    "T3": ("极光猫眼方甲", "脚趾甲方形透明延长，冰透底上有一道银白猫眼光带，甲根一排细小极光水钻，湿润高光，与透明高跟鞋呼应"),
    "T4": ("镜面红钻（性感款）", "脚趾甲方圆形，透明延长底叠樱桃红果冻色，镜面高光，大脚趾一颗心形红钻，其余光面，性感而真实"),
}
HAND_SUFFIX = "指甲根部与甲床自然衔接，十根手指各一枚指甲，五指完整，指节清晰，透明甲下可见指尖皮肤"
NAIL_NEG = ("多指、少指、手指融合、指甲断裂、长短不一、甲面模糊、钻石糊成光斑, extra fingers, missing fingers, fused fingers, "
            "six fingers, broken nails, melted nails, short nails, blurry, face, text, watermark")
NAIL_LOOK = ("成年女性（22岁）纤长白皙的手，冷白皮肤，手指修长，手掌放松、五指自然张开、彼此不交叠。钻石有清晰的刻面反光。"
             "柔和侧光加小点状高光，中性浅暖灰无缝背景（#B0A8A0），微距镜头，焦点清晰。画面只有手，不出现脸和身体，无文字无水印。")
TOE_LOOK = ("成年女性（22岁）纤细白皙的双脚，冷白皮肤，五个脚趾完整、比例自然，小脚趾甲按比例缩短。柔和侧光，中性灰无缝背景，"
            "微距镜头，焦点清晰。画面只有脚和小腿下部，不出现脸，无文字无水印。")
TOE_NEG = "多趾、少趾、脚趾融合、畸形脚、尖头脚甲、过长假趾甲, extra toes, missing toes, fused toes, deformed feet, blurry, text, watermark"


def nails():
    jobs, t2i = [], dict(unet=BASE, negative=NAIL_NEG, **T2I)
    for k, (nid, (name, desc)) in enumerate(NAILS_HAND.items()):
        views = [("BK", "双手手背朝上并排平放的特写，十指张开", 2),
                 ("PL", "一只手手背朝上、另一只手掌心朝上翻转，看清甲尖弧度和厚度", 1),
                 ("34", "一只手的3/4侧角度，指尖朝向镜头斜下方，显示指甲的长度", 1)]
        for v, vd, n in views:
            for s in range(n):
                jobs.append(j(f"lw_nail_{nid}_{v}_{s + 1}", f"美甲特写：{vd}。{desc}。{HAND_SUFFIX}。{NAIL_LOOK}",
                              latent="empty", w=1024, h=1024, seed=6100 + 10 * k + 3 * views.index((v, vd, n)) + s, **t2i))
    for k, (tid, (name, desc)) in enumerate(NAILS_TOE.items()):
        views = [("HEEL", "穿着12厘米透明露趾细高跟凉鞋（透明鞋面、透明细跟）的双脚，侧前45度，脚趾从鞋头露出", 768, 1024),
                 ("BARE-TOP", "赤脚，从上往下俯视双脚，脚趾自然平放", 1024, 1024),
                 ("BARE-FRONT", "赤脚，从正前方低角度平视双脚的脚趾", 1024, 1024)]
        for i, (v, vd, w, h) in enumerate(views):
            jobs.append(j(f"lw_toe_{tid}_{v}", f"脚趾美甲特写：{vd}。{desc}。{TOE_LOOK}", latent="empty", w=w, h=h,
                          seed=6200 + 10 * k + i, unet=BASE, negative=TOE_NEG, **T2I))
    return jobs


WORN = {  # item -> (garment wording, product file in refs/, framing)
    "outfit_office_suit": ("the white shirt, black knee-length pencil skirt and black blazer", "full"),
    "outfit_homewear": ("the light-grey knit cardigan, white camisole and grey lounge shorts", "full"),
    "outfit_ptxtrench": ("the black patent leather long trench coat, belted and buttoned to the collar", "full"),
    "outfit_ptxcorset": ("the black patent underbust corset, worn over a plain black fitted bodysuit", "full"),
    "outfit_ptxharness": ("the black patent strappy harness lingerie, worn over a matte black bandeau bra and briefs", "full"),
    "outfit_ltxsuit": ("the black latex catsuit, zipped up", "full"),
    "shoes_hh12clear": ("the 12 cm clear stiletto pumps", "feet"),
    "shoes_hh12patent": ("the 12 cm black patent side-open stiletto pumps", "feet"),
}
LOOKS = {  # REF-LW-01/02/03; face from fredw-d9 makeup plates M1/M4/M5 (items/makeup/)
    "A": ("造型A 素颜通勤（REF-LW-01）", "M1_768.png", ["outfit_office_suit", "shoes_hh12clear"],
          "a white fitted shirt tucked into a black knee-length pencil skirt and 12 cm clear stiletto pumps; fresh bare-faced makeup"),
    "B": ("造型B 浓妆女王（REF-LW-02）", "M4_768.png", ["outfit_ptxtrench", "shoes_hh12patent"],
          "a black high-gloss patent long trench coat belted at the waist over a black patent corset, a black mini skirt, "
          "12 cm black patent side-open stilettos; bold heavy makeup with dark lips"),
    "C": ("造型C 全套 CHAIN 态（REF-LW-03，饰品 LoRA 未就绪，暂不含穿孔饰品）", "M5_768.png", ["outfit_ptxharness", "shoes_hh12clear"],
          "black patent strappy harness lingerie over a matte black bandeau and briefs, an open black patent trench coat on "
          "her shoulders, 12 cm clear stiletto pumps; glittering night-club cat-eye makeup"),
}


def stage3(idf: str, body_f: str):
    """Worn items (outfit swap on the body plate), nails in context, looks A/B/C (front / back / 3-4)."""
    jobs = []
    role_b = ("Figure 1 is the full-body neutral plate of Lin Wan, an adult woman (22, fictional): keep her face, body shape, "
              "skin tone, light-blue waist-length hair with blunt bangs, pose and the grey backdrop. ")
    for k, (pid, (garm, fr)) in enumerate(WORN.items()):
        p = GR + f"lw_item_{pid}_prod.png"
        if fr == "full":
            jobs.append(j(f"lw_item_{pid}_worn", role_b + f"Figure 2 shows only the garment. Dress her in {garm} from Figure 2. "
                          "Copy only the garment from Figure 2 (cut, material, colour, hardware), not any mannequin or background. "
                          "Keep her body, pose, hands, bare feet and the background exactly the same. Crisp material reflections, "
                          "natural skin texture. No text, no logo.", refs=[GR + body_f, p], latent="ref",
                          loras=[["qwen-image-2.1-outfit-swap.safetensors", 1.0]], seed=7101 + k))
        else:
            jobs.append(j(f"lw_item_{pid}_worn", "Figure 1 shows only the shoe design. Close-up of the feet and lower legs of an "
                          f"adult woman with cool porcelain-white skin, standing on a grey studio floor wearing {garm} from Figure 1, "
                          "side-front 45-degree view, five natural toes per foot, toenails with a clear icy finish and fine white "
                          "rhinestones. Copy only the shoe from Figure 1, not its background. Seamless mid-grey backdrop, soft side "
                          "light, sharp focus. No face, no text.", refs=[p], latent="empty", w=768, h=1024, seed=7101 + k))
    # nails worn in context (default design LW-N1 / LW-T1)
    n1, t1 = GR + "lw_nail_N1_BK.png", GR + "lw_toe_T1_HEEL.png"
    role_f = ("Figure 1 provides only Lin Wan's facial identity (adult woman, 22, fictional): face, eyes, mole under the left eye, "
              "cool porcelain skin, light-blue waist-length straight hair with blunt bangs; do not copy its T-shirt or grey "
              "background. Figure 2 provides only the nail design: shape, length (about two thirds of the finger length), "
              "transparency and rhinestone layout; do not copy its hand pose, skin or background. ")
    ctx = [("coffee", "Close-up of her right hand holding a white takeaway coffee cup at chest height in a bright cafe, her face "
                      "softly visible behind it, five fingers wrapped naturally around the cup, the long clear jewelled nails clearly visible"),
           ("phone", "Medium close-up of her looking at a phone held in both hands near her chin, thumbs on the screen, all ten long "
                     "clear jewelled nails visible, bright apartment by a window"),
           ("cheek", "Beauty close-up of her resting her cheek lightly on the back of her left hand, fingers relaxed and slightly "
                     "spread along her jaw, the long clear jewelled stiletto nails visible, soft warm window light")]
    for k, (cid, d) in enumerate(ctx):
        jobs.append(j(f"lw_nail_N1_ctx_{cid}", role_f + d + ". Five fingers per hand, natural nail beds. " + OPTICS_HERO,
                      refs=[GR + idf, n1], latent="empty", w=832, h=1216, seed=7201 + k))
    jobs.append(j("lw_toe_T1_ctx_heels", "Figure 1 provides only the toenail and clear-heel design; do not copy its background. "
                  "Low-angle close-up of an adult woman's feet in 12 cm clear open-toe stilettos stepping onto a polished marble "
                  "lobby floor, cool porcelain skin, five natural toes per foot with clear icy rhinestone toenails, soft warm light, "
                  "creamy bokeh. No face, no text.", refs=[t1], latent="empty", w=832, h=1216, seed=7211))
    # looks A/B/C: face (makeup plate) + body plate + garment + shoes = 4 refs (v6 cap)
    for k, (lid, (name, face, items, wear)) in enumerate(LOOKS.items()):
        refs = [GR + face, GR + body_f] + [GR + f"lw_item_{i}_prod.png" for i in items]
        role = ("Figure 1 provides only Lin Wan's face and makeup (adult woman, 22, fictional; light-blue waist-length straight "
                "hair with blunt bangs). Figure 2 provides only her body proportions. Figure 3 provides only the garment, Figure 4 "
                "only the shoes. Do not copy any pose, mannequin, T-shirt or background from the figures. ")
        for v, (vd, s) in enumerate((("front view, standing, arms relaxed", 0), ("back view, her back to the camera, hair to the waist", 1),
                                    ("three-quarter view turned toward the left of the image, weight on one leg", 2))):
            vid = ("F", "B", "34")[v]
            jobs.append(j(f"lw_look_{lid}_{vid}", role + f"Full-body look reference: she wears {wear}. {vd}. " + PLATE_BG +
                          "50mm lens at f/8, sharp from head to toe, natural skin texture, crisp material reflections. "
                          "No text, no watermark.", refs=refs, latent="empty", w=768, h=1344, seed=7301 + 10 * k + s))
    return jobs


def write(name, jobs):
    OUT.mkdir(exist_ok=True)
    p = OUT / f"{name}.jsonl"
    p.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in jobs) + "\n", encoding="utf-8")
    print(p, len(jobs))


if __name__ == "__main__":
    if sys.argv[1] == "stage1":
        write("stage1", stage1())
    elif sys.argv[1] == "stage2":
        write("stage2", stage2(sys.argv[2]))
    elif sys.argv[1] == "stage3":
        write("stage3", stage3(sys.argv[2], sys.argv[3]))
    elif sys.argv[1] == "nails":
        write("nails", nails())
