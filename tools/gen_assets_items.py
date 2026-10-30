"""
林晚单品 / 妆容 / 发型 / 造型任务表（被 tools/gen_assets.py 加载）。
清单与 id 见 docs/lin_wan_asset_inventory.md；美甲见 research v7。
顺序很重要：产品图先出，worn 图把产品图当 图2/图3 参考（v6 §4.2：<image1> 只给身份，<image2> 只给服装…）。
裸露单品（束腰、捆绑、丁字裤、乳胶、穿孔饰品、私密纹身）只有 product，没有 worn。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "assets" / "characters" / "lin_wan"


def P(path: str) -> Path:
    """产品图参考（运行时必须已存在 _s0）。"""
    return BASE / f"{path}_s0.png"


MASTER = BASE / "plates" / "master.png"

STRIP = "，深色无缝背景配两条长条柔光灯箱，漆皮上有清晰的长条形镜面反光"
PRODUCT = ("专业电商产品摄影，商品完整居中入画，浅灰色无缝背景，柔和箱灯，材质与缝线细节清晰，"
           "画面中没有人、没有模特、没有任何人体和皮肤，无文字无水印，shot on Phase One, 100mm macro, f/8")
MANNEQUIN = ("穿在一个无头的哑光黑色裁缝人台上（人台只有躯干，没有头、手臂和腿），专业时装产品摄影，深灰色无缝背景，"
             "两条长条柔光灯箱，漆皮上有清晰的长条形镜面反光，画面中没有真人、没有皮肤，无文字无水印")
JEWEL = ("珠宝产品微距摄影，饰品平放在深灰色丝绒托盘上，柔和箱灯与清晰的金属刻面反光，"
         "画面中没有人体和皮肤，无文字无水印，100mm macro, f/11")
FLASH = ("纹身设计稿（tattoo flash）：黑色墨线画在米白色厚纸上，平铺俯拍，纸面纹理清晰，线条精细，只有设计图案，"
         "画面中没有人体和皮肤，无多余文字，柔和均匀光")


def jobs(Job, C):
    K, GREY = C["ID_KEEP"], C["GREY"]
    W = []   # worn
    J = []

    def prod(id_, design, name, prompt, size=(1024, 1024), style=PRODUCT):
        J.append(Job(id_, "item/" + id_.split("/")[1], design, name, prompt + "。" + style, size,
                     refs=[], worn=False, identity=False, style=False))

    def worn(id_, design, name, prompt, refs=(), size=(768, 1344), kind=None):
        roles = "".join(f"图{i + 2}只提供{r[1]}的款式、颜色与材质，不要沿用其背景和摆放；" for i, r in enumerate(refs))
        W.append(Job(id_, kind or ("item/" + id_.split("/")[1]), design, name, K + roles + prompt, size,
                     refs=[MASTER] + [P(r[0]) for r in refs]))

    full = "从头顶到脚完整入画的全身站姿，面向镜头，自然放松，" + GREY
    # ------------------------------------------------------------ 服装
    O = "items/outfit/"
    MINI = "黑色镜面漆皮高腰包臀超短裙（像抹了油一样的高亮镜面漆皮，表面湿润光泽，镜面反射清晰，高光锐利，裙长约28厘米，只盖住臀部）"
    HEELS = "脚穿12厘米透明侧开细高跟鞋（细如筷子的针形细跟）"
    prod(O + "O09_product", "LW-O09", "黑色镜面漆皮超短裙（产品）", "一条" + MINI + "，挂在隐形人台下半身上展示正面" + STRIP)
    prod(O + "O01_product", "LW-O01", "入职日套装（产品）", "女式入职日套装平铺：修身白色真丝衬衫与" + MINI + "，一个米色文件夹放在旁边" + STRIP)
    prod(O + "O02_product", "LW-O02", "性感通勤装（产品）", "女式性感通勤装平铺俯拍（只有衣服平放在台面上，没有人穿）：收腰修身的白色棉质衬衫与" + MINI + STRIP)
    prod(O + "O03_product", "LW-O03", "短款针织+漆皮超短裙（产品）", "平铺：一件奶白色贴身短款罗纹针织上衣与" + MINI + STRIP)
    prod(O + "O05_product", "LW-O05", "黑色修身吊带短连衣裙（产品）", "一条黑色修身细吊带短连衣裙挂在透明亚克力衣架上，裙长到大腿中部")
    prod(O + "O07_product", "LW-O07", "黑色晚礼服（产品）", "黑色缎面修身及踝晚礼服挂在透明亚克力衣架上：细肩带，深V露背，侧面高开衩到大腿，裙摆垂坠")
    prod(O + "O08_product", "LW-O08", "黑色漆皮长风衣（产品）", "黑色漆皮双排扣长风衣（像抹了油一样的高亮镜面漆皮，表面湿润光泽，镜面反射清晰，高光锐利），长度到小腿，扣到领口，系腰带，挂在隐形人台上展示正面" + STRIP)
    prod(O + "O10_product", "LW-O10", "黑色漆皮束腰（产品）", "黑色漆皮束腰（像抹了油一样的高亮镜面漆皮，表面湿润光泽，镜面反射清晰，高光锐利），前片硬挺带钢骨，交叉的漆皮绑带从肩部延伸到腰部，胸前是镂空开窗设计，银色金属扣", style=MANNEQUIN)
    prod(O + "O11_product", "LW-O11", "新束腰：更紧开窗更大（产品）", "第二件黑色漆皮束腰（像抹了油一样的高亮镜面漆皮，表面湿润光泽，镜面反射清晰，高光锐利），比普通款更窄更紧，胸前镂空开窗更大，后背交叉系带，银色金属扣", style=MANNEQUIN)
    HSTD = ROOT / "assets" / "clothes" / "owner_standard" / "latex_harness_standard.jpg"
    hdesc = ("图1只提供服装款式（不是人物参考）：极简黑色镜面漆皮细带捆绑内衣（harness）——挂脖细带配金属扣、胸前一枚银色O环、窄的下胸围带、"
             "无罩杯的开放式框架、正中一条腹部细带连到细带式丁字裤、两侧细的带扣胯带；不是大面积皮片、不是全罩文胸、不是连体衣；"
             "像抹了油一样的高亮镜面漆皮，表面湿润光泽，镜面反射清晰，高光锐利；银色金属扣和O环清晰可见")
    J.append(Job(O + "O12_flatlay_dark", "item/outfit", "LW-O12", "黑色漆皮细带捆绑内衣（平铺，深色背景）",
                 hdesc + "。整件平铺在深灰色无缝背景上俯拍，带子舒展整齐" + STRIP + "，画面中没有任何人体和皮肤，无文字", (1024, 1024),
                 refs=[HSTD], worn=False, identity=False, style=False))
    J.append(Job(O + "O12_flatlay_white", "item/outfit", "LW-O12", "黑色漆皮细带捆绑内衣（平铺，白色背景）",
                 hdesc + "。整件平铺在纯白无缝背景上俯拍，带子舒展整齐，柔和箱灯，漆皮有清晰的长条形反光，画面中没有任何人体和皮肤，无文字", (1024, 1024),
                 refs=[HSTD], worn=False, identity=False, style=False))
    J.append(Job(O + "O12_mannequin", "item/outfit", "LW-O12", "黑色漆皮细带捆绑内衣（无脸人台）",
                 hdesc + "。" + MANNEQUIN, (1024, 1344), refs=[HSTD], worn=False, identity=False, style=False))
    prod(O + "O13_product", "LW-O13", "黑色漆皮 string 丁字裤（产品）", "一条黑色漆皮 string 丁字裤平铺（像抹了油一样的高亮镜面漆皮，表面湿润光泽，镜面反射清晰，高光锐利）：正面一小片三角漆皮，两侧是细如筷子的漆皮细绳" + STRIP)
    prod(O + "O14_product", "LW-O14", "乳胶连体衣（产品）", "黑色高光乳胶连体衣，长袖长腿，后背拉链，完整包覆，表面湿润镜面反光", style=MANNEQUIN)
    prod(O + "O15_product", "LW-O15", "黑色丝袜（产品）", "一双黑色15D薄透连裤丝袜平铺展开，半透明质感，脚尖加固")
    prod(O + "O16_product", "LW-O16", "真丝吊带睡衣套装（产品）", "浅粉色真丝细吊带背心与真丝短裤睡衣套装平铺，边缘有细蕾丝")
    prod(O + "O19_product", "LW-O19", "浴巾（产品）", "一条白色厚绒浴巾，整齐叠放")
    prod(O + "O21_product", "LW-O21", "顾沉的男式西装外套（产品）", "男式黑色高定单排扣西装外套挂在木质衣架上，肩宽挺括，羊毛面料")

    sexy = "身材修长、腿长，穿搭修身显身材，"
    worn(O + "O00_worn", "LW-O00", "身份底板基础款（上身）", full.replace("面向镜头", "面向镜头，" + C["BODY_BASIC"]))
    worn(O + "O09_worn", "LW-O09", "漆皮超短裙（上身）", sexy + "她穿" + MINI + "配黑色修身短袖针织上衣，" + HEELS + "，" + full, [("items/outfit/O09_product", "裙子")])
    worn(O + "O01_worn", "LW-O01", "入职日套装（上身）", sexy + "她穿修身白色真丝衬衫（领口解开一颗扣子）和" + MINI + "，" + HEELS + "，双手在胸前抱着一个米色文件夹，表情礼貌又紧张，" + full, [("items/outfit/O01_product", "服装")])
    worn(O + "O02_worn", "LW-O02", "性感通勤装（上身）", sexy + "她穿收腰修身的白色衬衫（领口微开）和" + MINI + "，" + HEELS + "，" + full, [("items/outfit/O02_product", "服装")])
    worn(O + "O03_worn", "LW-O03", "短款针织+漆皮超短裙（上身）", sexy + "她穿奶白色贴身短款罗纹针织上衣（露出一点腰线）和" + MINI + "，" + HEELS + "，" + full, [("items/outfit/O03_product", "服装")])
    worn(O + "O04_worn", "LW-O04", "修身运动拉链外套（上身）", sexy + "她穿浅蓝色修身短款运动拉链外套（拉链拉到胸口以上）和黑色高腰短裙，双臂习惯性环抱在胸前，" + full)
    worn(O + "O06_worn", "LW-O06", "居家：吊带背心+超短短裤（上身）", sexy + "她穿黑色贴身短款罗纹长袖上衣和同色高腰针织短裤（到大腿中部），白色短袜，" + full)
    worn(O + "O07_worn", "LW-O07", "黑色晚礼服（上身）", sexy + "她穿黑色缎面修身晚礼服（细肩带，侧面高开衩露出一条腿），一手端着香槟杯，仪态端庄，脚穿12厘米黑色细高跟（细如筷子的针形细跟），" + full, [("items/outfit/O07_product", "服装")])
    worn(O + "O08_worn", "LW-O08", "黑色漆皮长风衣（上身，扣到领口）", "她穿黑色漆皮长风衣（像抹了油一样的高亮镜面漆皮，表面湿润光泽，镜面反射清晰，高光锐利），扣子一直扣到领口，系紧腰带，风衣下摆到小腿，" + HEELS + "，" + full, [("items/outfit/O08_product", "风衣")])
    worn(O + "O15_worn", "LW-O15", "黑色丝袜（上身，腿部）", "她穿" + MINI + "配黑色薄透丝袜，坐在白色椅子上，双腿并拢斜放，" + HEELS + "，画面从腰部到脚，看不到脸，" + GREY,
         [("items/outfit/O15_product", "丝袜")], size=(768, 1344))
    worn(O + "O16_worn", "LW-O16", "真丝吊带睡衣（上身）", sexy + "她穿深莓果红色真丝长袖衬衫式睡衣上衣（扣子扣好）和同色真丝短裤，坐在床沿，" + full, [("items/outfit/O16_product", "睡衣")])
    worn(O + "O17_worn", "LW-O17", "短款真丝吊带睡裙（上身）", sexy + "她穿一件香槟色真丝长袖短款睡裙（圆领，长到大腿中部），素颜，白色毛绒拖鞋，" + full)
    worn(O + "O18_worn", "LW-O18", "短款真丝睡袍（上身）", sexy + "她穿一件黑色真丝长袖睡袍（长到膝盖上方），腰带系紧，领口合拢到锁骨，白色毛绒拖鞋，" + full)
    worn(O + "O20_worn", "LW-O20", "短款修身针织开衫（上身）", sexy + "她穿炭灰色短款修身针织开衫（扣好），配黑色高腰短裤（到大腿中部），" + full)
    worn(O + "O21_worn", "LW-O21", "披着男式西装外套（上身）", "她穿白色修身衬衫，肩上披着一件过大的男式黑色西装外套，坐在办公椅上，双手抱着文件，半身构图，" + GREY,
         [("items/outfit/O21_product", "西装外套")], size=(1024, 1280))

    # ------------------------------------------------------------ 鞋
    S = "items/shoes/"
    clear = ("一只12厘米透明细高跟鞋：透明PVC鞋面，侧口开边（d'Orsay，鞋两侧镂空），尖头，透明内底，鞋跟直径约6毫米、细如一根筷子的针形细跟，跟高12厘米，侧面清楚可见鞋跟极细，透明亚克力针形细跟，没有任何logo")
    patent = ("一只12厘米黑色漆皮侧开细高跟鞋：像抹了油一样的高亮镜面漆皮，表面湿润光泽，镜面反射清晰，高光锐利，d'Orsay 侧开款：鞋头和后跟是分开的两片，中间两侧鞋帮都整段完全敞开、露出整个足弓（从侧面能清楚看到鞋头与后跟之间是空的），鞋头尖头包裹脚趾，尖头，鞋跟直径约6毫米、细如一根筷子的针形细跟，跟高12厘米，侧面清楚可见鞋跟极细，黑色金属针形细跟，没有任何logo")
    for sid, design, nm, desc in (("S01", "LW-S01", "12cm 透明侧开细高跟", clear), ("S02", "LW-S02", "12cm 黑漆皮侧开细高跟", patent + STRIP)):
        prod(S + f"{sid}_side45", design, nm + "（侧 45°）", desc + "，侧前45度角拍摄")
        prod(S + f"{sid}_pair", design, nm + "（一双，正面+侧面）", desc.replace("一只", "一双") + "，一只正面一只侧面并排摆放")
        prod(S + f"{sid}_profile", design, nm + "（正侧面：看鞋跟粗细）", desc + "，标准正侧面90度拍摄，鞋跟像一根筷子一样细，与鞋头宽度对比明显")
        prod(S + f"{sid}_back", design, nm + "（后跟）", desc + "，从后方拍摄后跟与鞋跟")
    # 脚部 worn（只有脚和小腿）
    feet = "画面只有她的脚踝和双脚，她穿着黑色九分西裤（裤脚在脚踝上方），站在浅灰色地面上，侧前方低机位，看不到身体其他部分，" + GREY
    W.append(Job(S + "S01_worn", "item/shoes", "LW-S01", "12cm 透明侧开细高跟（上脚）",
                 "图1只提供鞋子的款式与材质。成年女性冷白皮肤的双脚穿着这双12厘米透明侧开细高跟鞋（鞋跟直径约6毫米、细如一根筷子的针形细跟，跟高12厘米，侧面清楚可见鞋跟极细），足弓优美，脚趾甲是冰透满钻的方圆形长甲，" + feet,
                 (1024, 1024), refs=[P(S + "S01_side45")], identity=False))
    W.append(Job(S + "S02_worn", "item/shoes", "LW-S02", "12cm 黑漆皮侧开细高跟（上脚）",
                 "图1只提供鞋子的款式与材质。成年女性冷白皮肤的双脚穿着这双12厘米黑色漆皮侧开细高跟鞋（像抹了油一样的高亮镜面漆皮，表面湿润光泽，镜面反射清晰，高光锐利，鞋跟直径约6毫米、细如一根筷子的针形细跟，跟高12厘米，侧面清楚可见鞋跟极细），侧口露出绷起的脚背弧线，" + feet,
                 (1024, 1024), refs=[P(S + "S02_side45")], identity=False))

    # ------------------------------------------------------------ 美甲（research v7）
    N = "items/nails/"
    common = ("指甲根部与甲床自然衔接，十根手指各一枚指甲，五指完整，指节清晰，透明甲下可见指尖皮肤；"
              "钻有清晰的刻面反光；柔和侧光与小点状高光；双手手腕处露出黑色针织长袖的袖口（她穿着黑色长袖针织衫）；背景为中性中灰色丝绒台面；画面只有手和袖口，没有脸")
    hand = "成年女性冷白皮肤的纤细双手（穿着黑色针织长袖，袖口盖到手腕），"
    nails = {
        "N1": ("冰川满钻尖甲", "超长透明尖头延长甲，甲长约为手指长度的三分之二，透明水晶底，甲根带一点淡冰蓝，甲面铺满密集的细碎白色水钻，甲根一排较大的圆形钻石，指尖末端保留透明，高光镜面封层"),
        "N2": ("草莓糖霜芭蕾", "超长透明芭蕾形延长甲，甲长约为手指长度的三分之二，指尖平切、两侧收窄，透明底向甲尖渐变为淡粉色，中指和无名指各贴一颗立体粉色草莓形水晶饰品，其余手指沿甲边镶一圈细白钻，高光透亮"),
        "N3": ("极光冰透猫眼", "超长透明杏仁形延长甲，甲长约为手指长度的三分之二，冰透玻璃质感，甲面有一道银白色猫眼光带和彩虹极光偏光，甲根月牙形镶一排极光水钻，侧边点缀两三颗马眼形钻，湿润高光"),
        "N4": ("钻链珠宝甲", "超长透明尖头延长甲，甲长约为手指长度的三分之二，透明水晶底，甲根各镶一颗大水滴形钻石，一条极细的银色链条从甲根垂挂到甲面中部，末端坠一颗小钻，食指甲尖穿一个小银环"),
        "N5": ("冰晶吹制玻璃", "超长透明芭蕾形延长甲，甲长约为手指长度的三分之二，甲面有立体的透明玻璃凝胶纹理，像吹制玻璃和冰棱，冰棱之间嵌着散落的小白钻和少量冰蓝色钻，晶莹剔透"),
        "N6": ("粉钻垃圾甲", "超长透明尖头延长甲，甲长约为手指长度的三分之二，每根手指款式不同：拇指铺满粉色水钻，食指心形钻配小珍珠，中指立体草莓水晶，无名指细银链，小指铺满白钻，透明底，高光"),
    }
    for nid, (nm, d) in nails.items():
        W.append(Job(N + f"{nid}_BK", "item/nails", f"LW-{nid}", f"{nm}（手背）",
                     hand + "双手手背朝上并排平放，手掌放松、五指自然张开、彼此不交叠，俯拍特写；指甲：" + d + "；" + common,
                     (1024, 1024), identity=False))
        W.append(Job(N + f"{nid}_PL", "item/nails", f"LW-{nid}", f"{nm}（手背+掌心）",
                     hand + "左手手背朝上、右手掌心朝上翻转，展示甲尖弧度和厚度，五指自然张开不交叠；指甲：" + d + "；" + common,
                     (1024, 1024), identity=False))
    toes = {
        "T1": ("冰透满钻方圆", "脚趾甲透明冰透延长，方圆形，大脚趾甲略长出脚趾前端约7毫米，甲面铺满细白钻，其余脚趾甲根各一颗小钻，比例自然，高光镜面"),
        "T2": ("草莓裸粉法式", "脚趾甲短杏仁形透明裸粉延长，甲尖一道细白钻法式边，大脚趾点缀一颗小粉色草莓水晶，光泽饱满"),
        "T3": ("极光猫眼方甲", "脚趾甲方形透明延长，冰透底上有一道银白猫眼光带，甲根一排细小极光水钻，湿润高光"),
        "T4": ("镜面红钻", "脚趾甲方圆形，透明延长底叠樱桃红果冻色，镜面高光，大脚趾一颗心形红钻，其余光面"),
    }
    foot_common = "十个脚趾完整，小脚趾甲按比例缩短，脚型修长干净，脚踝上方露出黑色九分西裤的裤脚（她穿着黑色长裤），背景为中性中灰色地面，画面只有脚、脚踝和裤脚"
    for tid, (nm, d) in toes.items():
        W.append(Job(N + f"{tid}_BARE", "item/nails", f"LW-{tid}", f"{nm}（赤脚）",
                     "脚趾甲美甲微距特写：只拍脚趾的前半部分（五个脚趾和趾甲占满画面），放在黑色丝绒上，俯视，看不到脚背以上；脚趾甲：" + d + "；" + foot_common,
                     (1024, 1024), identity=False))
        W.append(Job(N + f"{tid}_HEEL", "item/nails", f"LW-{tid}", f"{nm}（穿 12cm 透明高跟）",
                     "图1只提供鞋子的款式与材质。成年女性冷白皮肤的双脚穿着12厘米透明侧开细高跟鞋（细如筷子的针形细跟），透明鞋面下清楚看到脚趾甲：" + d +
                     "；她穿着黑色九分西裤（裤脚在脚踝上方），侧前45度，画面只有脚踝和脚，背景为中性中灰色",
                     (768, 1024), refs=[P(S + "S01_side45")], identity=False))

    # ------------------------------------------------------------ 饰品（全部 product）
    A = "items/accessory/"
    prod(A + "A01_nipple_rings", "LW-A01", "乳环 ×2（产品）", "两枚细的抛光银色钛钢圆环（直径约12毫米、线径1.2毫米、带小珠扣），并排放置", style=JEWEL)
    prod(A + "A02_rings9", "LW-A02", "阴环 ×9（产品）", "一共只有9枚（九枚）小号抛光银色细圆环，每枚直径约8毫米，在深灰丝绒上排成一条稀疏的浅弧线，环与环之间留出较大间隔、互不接触，数量严格为9，不多不少，画面里只有这9枚小环", style=JEWEL)
    prod(A + "A03_beads9", "LW-A03", "9 颗 5mm 黑铁球（产品）", "九枚小号银色细圆环（直径约8毫米）在深灰丝绒上排成U形弧线（左四、右四、正中一），每枚环的下方各挂着一颗很小的乌亮黑色金属小球（直径只有5毫米，比环小得多，像一粒黑胡椒），共九颗，画面里只有这九枚环和九颗小球", style=JEWEL)
    prod(A + "A04_belly_chain", "LW-A04", "腹部链（产品）", "一条精细的银色腰链（腹部链），细链条中间垂下几缕短链和小水钻，呈弧形摆放", style=JEWEL)
    prod(A + "A05_tongue_stud", "LW-A05", "舌钉（产品）", "一枚舌钉：银色钛钢直杆（长约16毫米），两端各一颗4毫米抛光钢珠，旁边放着备用珠球", style=JEWEL)
    prod(A + "A06_velvet_box", "LW-A06", "丝绒小盒（产品）", "一个打开的深酒红色丝绒首饰小方盒，盒内整齐卡着九枚小银环，每环挂一颗5毫米黑色小铁球")
    prod(A + "A07_vanity_case", "LW-A07", "妆匣（产品）", "一个打开的黑色皮革双层首饰妆匣，内衬深色丝绒，格子里放着银色小环、黑色小铁球、细链和一个小清洁盒")
    prod(A + "A08_strawberry_necklace", "LW-A08", "草莓水晶项链（产品）", "一条多层银色项链，挂满粉色水钻草莓吊坠、白色珍珠和小水晶球，平铺呈U形", style=JEWEL)

    # ------------------------------------------------------------ 纹身设计稿
    T = "items/tattoo/"
    prod(T + "TT1_mandala", "LW-TT1", "曼陀罗纹身（设计稿）", "一个圆形放射对称的黑色曼陀罗图案（mandala）：中心小圆点，外面一圈圈同心花瓣与几何点线纹层层展开，整体是正圆形；正圆的下方左右各伸出一条向下弯曲的细藤蔓", style=FLASH)
    prod(T + "TT2_snake", "LW-TT2", "黑蛇纹身（设计稿）", "一条细长盘绕的黑蛇，鳞片一片片精细排列，S形蜿蜒，蛇眼点一点红宝石色", (768, 1344), style=FLASH)
    prod(T + "TT3_chen", "LW-TT3", "“沉”字纹身（设计稿）", "一个手写的黑色中文行书“沉”字，笔锋细腻优雅，居中", style=FLASH)
    prod(T + "TT4_wings", "LW-TT4", "背部黑羽纹身（设计稿）", "一对对称展开的黑色羽翼，羽毛层次分明从上向下逐渐收拢", style=FLASH)

    # ------------------------------------------------------------ 发型（ID 变体）
    H = "items/hair/"
    hb = "正面头肩照，保持图1的妆容，" + C["BASIC"] + "，" + GREY
    W.append(Job(H + "H0_front", "item/hair", "LW-H0", "默认：冰蓝及腰直发齐刘海（正）", K + "天蓝色及腰顺直长发，厚度均匀的齐刘海盖到眉毛，" + hb, (1024, 1024)))
    W.append(Job(H + "H0_back", "item/hair", "LW-H0", "默认：冰蓝及腰直发（背）", K + "背面照：她完全背对镜头站立，看不到脸，镜头只拍到她的后脑、后背和天蓝色顺直长发一直垂到腰部，发尾整齐，" + C["BASIC"] + "，" + GREY, (768, 1344)))
    W.append(Job(H + "H1_wet", "item/hair", "LW-H1", "湿发贴脸", K + "刚洗过的湿发：天蓝色头发湿透成一缕一缕贴在脸颊和肩上，刘海湿成几股，皮肤上有细小水珠，素颜，" + hb, (1024, 1024)))
    W.append(Job(H + "H2_messy", "item/hair", "LW-H2", "凌乱 / 汗湿一缕黏额角", K + "头发略显凌乱，齐刘海被汗黏住一缕贴在额角，几缕碎发散在脸侧，脸颊微红，" + hb, (1024, 1024)))
    W.append(Job(H + "H3_wind", "item/hair", "LW-H3", "风吹发", K + "一阵风从侧面吹来，天蓝色长发和刘海被吹向一侧飘起，发丝在空中散开，" + hb, (1024, 1024)))
    W.append(Job(H + "H4_bangs_swept", "item/hair", "LW-H4", "刘海被理过 / 侧拨", K + "齐刘海被轻轻拨向一侧，露出一点额头，一侧头发别在耳后，" + hb, (1024, 1024)))

    # ------------------------------------------------------------ 妆容 L1–L8（research v9 §1/§2；M0–M6 已 superseded）
    M = "items/makeup/"
    KEEP9 = ("图1是林晚本人。保持她的脸型轮廓、鼻型、唇形、齐刘海和与图1相同的天蓝色及腰直发、肤色、脸颊小痣与整体辨识度；"
             "眼睛大小与图1一致，{eyes}。去掉图1原有的妆容，只换成下面这套妆容，妆感在照片里清楚可见：")
    TAIL9 = ("。真实相机照片质感，可见毛孔与细绒毛，真实发丝；正面胸像，双手不入画，穿素色浅灰色圆领T恤，不戴首饰；"
             "灰色无缝背景，柔和窗光，50mm 镜头。其他一切保持不变")
    L = {
        "L1_bare_commute": ("素颜通勤", "几乎看不出化妆：透薄的保湿底妆，鼻翼和眼下有自然肤色不均；只用遮瑕点盖小瑕疵；灰棕色眉粉轻扫，刘海下隐约可见；睫毛只夹翘并涂一层透明睫毛膏，根根分明；无眼线、无眼影；淡淡的豆沙粉润唇膏，唇纹可见；两颊有自然血色，不是腮红块"),
        "L2_half_red": ("ep06 过渡妆（减半红唇）", "薄底妆，缎面光泽；冷调灰棕眼影只在双眼皮褶内薄薄一层；深棕细内眼线贴紧睫毛根，眼尾延长3毫米并微微上翘；睫毛膏两层，根根分明；樱桃红唇只在唇中拍开、向唇边渐淡成唇染效果，柔雾质地；玫瑰粉腮红在颧骨上方横向轻扫"),
        "L3_red_lip_city": ("正红唇都市妆", "缎面薄底，可见毛孔；冷调正红（偏蓝的红）丝绒哑光唇，唇峰清晰、边缘用指腹柔化；黑色细眼线从眼中开始加粗，眼尾利落上扬约5毫米（小猫眼）；灰棕眼影在眼尾外侧轻晕；上睫毛浓而分明，下睫毛涂一层；颧骨下方有很淡的灰棕修容；腮红极淡，用来呼应唇色"),
        "L4_queen": ("浓妆女王", "妆感明显：半哑光底妆，鼻梁和颧骨高点有缎面高光，颧骨下有清晰但晕开的灰棕修容；眼窝用梅子棕到深咖做截断式加深，眼皮中段留出浅香槟色截断面；黑色拉长眼线带内眼角下勾，形成狐狸眼的拉长感；下眼睑后三分之一用深咖烟熏晕开；簇状假睫毛，眼尾最长；黑樱桃色丝绒唇，边缘干净略晕；腮红为低饱和莓果色，斜向颧骨"),
        "L5_night_crystal": ("夜场闪钻妆", "黑色上扬猫眼眼线；沿眼线上方镶一排大小渐变的透明水钻，眼头最小、眼尾较大，眼尾向外点缀3颗，眼头点一颗小钻；眼皮中央是银灰金属光泽眼影，眼头一点冰蓝珠光；下睫毛做成几簇漫画式小簇；其余皮肤保持缎面，只在颧骨最高处有细闪；唇为莓果粉镜面唇釉，有锐利的灯光反光；水钻在灯光下出现小星芒"),
        "L7_dewy_signature": ("纯欲水光妆（招牌）", "水光底妆：颧骨上方、鼻梁、上唇峰和下巴有湿润光泽，其余部位柔雾，可见毛孔；豆沙玫瑰色腮红从下眼睑外侧横向晕到颧骨，鼻梁中段也扫一点，像微醺；眼皮用浅杏粉打底，眼尾用玫瑰棕轻晕；深棕眼线沿眼尾向下延伸3毫米，做出下垂的无辜眼；卧蚕用浅香槟色提亮，下方有一道浅棕阴影；上睫毛自然簇状，下睫毛有3到4小簇；唇用蓝调莓果唇釉做咬唇效果，唇中最深、向外晕开，唇中有湿润反光，唇线模糊"),
        "L8_sweet_refined": ("定妆原版甜妆（精修）", "保留原版粉甜方向，但收敛：薄而光泽的底妆，可见毛孔；草莓粉腮红从眼下横向轻扫，面积减半，没有圆形边界；浅粉珠光眼影，眼头有细闪；棕色内眼线，眼尾平直；睫毛浓密但根根分明，不粘连；草莓粉水润唇釉，唇中更深"),
    }
    for stem, (nm, d) in L.items():
        lid = stem.split("_")[0]
        eyes = "改为自然深棕色眼睛，不戴美瞳" if lid in ("L1", "L2") else "保持灰蓝色美瞳"
        W.append(Job(M + stem, "item/makeup", lid, nm + ("（深棕眼）" if lid in ("L1", "L2") else "（灰蓝美瞳）"),
                     KEEP9.format(eyes=eyes) + d + TAIL9, (1024, 1280), style=False))
    # L6 泪痕：链式编辑，叠加在 L4 / L1 上（v9 §1：效果在已上妆的图上再编辑一次）
    L6 = ("图1是林晚本人。保持图1的脸、发型、妆容（眼妆颜色、唇色与唇的颜色深浅完全保持图1）、服装、背景、光线和构图完全不变，只叠加正在流泪的状态，泪痕要在照片里清楚可见，妆仍然好看："
          "下眼睑盈着一线泪光；两道清晰发亮、带高光反射的泪痕从眼角斜向颧骨一直流到下颌，一颗泪珠挂在脸颊上，沿途带走一点粉底；眼线和睫毛膏在下眼睑晕成浅灰色淡影，不是黑色污块；"
          "睫毛湿成几簇；眼周、鼻尖和鼻翼泛起淡淡的粉红；唇色被擦淡一半、边缘模糊，唇面微湿。真实人像照片，可见毛孔")
    for base in ("L4_queen", "L1_bare_commute"):
        W.append(Job(M + f"L6_tears_on_{base.split('_')[0]}", "item/makeup", "L6", f"泪痕妆（叠加在 {base.split('_')[0]}）", L6,
                     (1024, 1280), refs=[P(M + base)], style=False))

    # ------------------------------------------------------------ 造型 A/B/C
    L = "looks/"
    looks = {
        "REF-LW-01": ("素颜通勤（性感通勤）", "素颜保持图1的妆容，自然深棕色眼睛，身材修长腿长，穿收腰修身的白色衬衫（领口微开）和" + MINI + "，" + HEELS,
                      [("items/outfit/O02_product", "服装"), ("items/shoes/S01_side45", "鞋子")]),
        "REF-LW-02": ("浓妆女王", "浓妆女王妆：戴灰蓝色美瞳，梅子棕截断式眼妆、拉长黑色眼线、黑樱桃色丝绒唇；穿黑色漆皮长风衣（像抹了油一样的高亮镜面漆皮，表面湿润光泽，镜面反射清晰，高光锐利，扣到领口、系紧腰带），脚穿12厘米黑色镜面漆皮侧开细高跟鞋（细如筷子的针形细跟），气场冷艳",
                      [("items/outfit/O08_product", "风衣"), ("items/shoes/S02_side45", "鞋子")]),
    }
    views = {"front": "正面全身，面向镜头", "back": "背面全身：她完全背对镜头站立，看不到脸，镜头只看到她的后脑、及腰的天蓝色长发和后背，鞋跟朝向镜头", "34": "四分之三侧面全身，身体朝向画面左侧约45度"}
    for lid, (nm, d, refs) in looks.items():
        for v, vd in views.items():
            worn(L + f"{lid}_{v}", lid, f"{nm}（{v}）", d + "；" + vd + "，从头顶到脚完整入画，站姿自然，" + GREY, refs, kind="look")
    # ------------------------------------------------------------ 男角色候选（SOP 锁定参数，文生图，项目方每角色选 1）
    import hashlib
    bible = ROOT / "config" / "visual_bible.toml"
    bible_sha = hashlib.sha256(bible.read_bytes()).hexdigest()
    SKIN = "真实皮肤质感，可见细小毛孔与细软绒毛，自然的轻微不对称，眼睛为真实人眼大小"
    MEN_NEG = ("磨皮, 塑料皮肤, 蜡像, CGI, 3D render, airbrushed, doll face, 动漫, 多余手指, 手指融合, 肢体变形, "
               "未成年人外观, 裸体, 赤裸上身, 项链, 首饰, 手表, 道具, 文字, 水印, 低清")
    men = {
        "gu_chen": ("a 34-year-old adult Chinese man who looks exactly in his early thirties (youthful face for his age, smooth skin around the eyes, no grey hair, no deep wrinkles), a CEO, mature, restrained and handsome, short neat black hair swept back, "
                    "defined jaw, light stubble, tall and lean; he wears a plain tailored black dress shirt (top button open) "
                    "and black trousers", 3, "script character lock: 34岁成年男性CEO，黑色高定衬衫，成熟克制英俊"),
        "chen_yu": ("a 23-year-old adult Chinese man, warm and sunny, gentle boyish smile, soft tousled brown-black hair with a "
                    "fringe, lightly tanned, slim athletic build; he wears a plain light-grey crew-neck sweatshirt and "
                    "dark-blue jeans", 3, "script character lock: 23岁成年男性，温暖阳光，休闲装"),
        "alex": ("Alex K, a 29-year-old adult man, tall and gentle, friendly open face, short wavy dark-blond hair, light "
                 "beard, broad shoulders; he wears a plain navy crew-neck knit sweater and grey trousers", 2,
                 "script text ep37: Alex K（29岁成年男性，高大温和，衣着得体）"),
        "ryan": ("Ryan M, an East Asian adult man around 30, sharp and capable, neat short black undercut, clean-shaven, "
                 "lean muscular build; he wears a plain charcoal fitted T-shirt and black trousers", 2,
                 "script ep41 name list (no lock; description by asset agent, needs owner review)"),
        "kai": ("Kai J, an East Asian adult man around 26, scholarly and shy, slim, round thin-rimmed glasses, soft straight "
                "black hair parted in the middle; he wears a plain white oxford shirt and beige chinos", 2,
                "script ep41 name list (no lock; description by asset agent, needs owner review)"),
        "leo": ("Leo Vane, a European adult man around 38, mature and steady, salt-and-pepper short hair, trimmed beard, "
                "deep-set calm eyes, solid build; he wears a plain dark-olive henley shirt and dark trousers", 2,
                "script ep41 name list (no lock; description by asset agent, needs owner review)"),
    }
    Mn = []
    for c, (desc, n, src) in men.items():
        for k in range(n):
            Mn.append(Job(f"../{c}/candidates/{c}_cand_{k + 1:02d}", "candidate", c, f"{c} 候选 {k + 1}",
                          f"Full-body identity reference photo of {desc}. Head to toe in frame, standing straight, front "
                          "view, arms relaxed at his sides, neutral expression, looking into the lens, plain shoes, "
                          "no necklace, no jewellery, no watch, no props in his hands. Plain neutral grey seamless studio "
                          "backdrop (#808080), soft even light, 50mm lens at f/8. Unretouched real photo. " + SKIN,
                          (1024, 1536), identity=False, preset="SOP", negative=MEN_NEG,
                          extra={"bible_sha256": bible_sha, "reference_source": src, "references_used": [],
                                 "status": "candidate (owner picks one; no master/LoRA until picked)"}))
    return J + W + Mn
