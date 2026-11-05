"""S4 previz → Qwen-Image 2.1 Fun ControlNet Union 出图（scratch/A-B，scope ab，不碰生产图）。
本机构图 → 上传 gpu33 → 在 gpu33 本机 POST 到 lane 的 ComfyUI → 取回。用法：gen_s4.py build  生成 jobs 与 workflow JSON"""
import sys, json, glob, copy
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "services/render_router"), str(ROOT / "packages/schema"), str(ROOT / "services/agent"), str(ROOT / "packages/qc")] + glob.glob(str(ROOT / "services/*"))
from ns_render import workflows as W, image_params as IP

NEG = "低质量，模糊，畸形手指，多余的人，第三个人，文字，水印，字幕，塑料皮肤，磨皮，卡通，CG感"
REFS = "图1是卓琳的脸部参考（只取脸和发型）。图2是祁念的脸部参考（只取脸和发型）。图3是卓琳本镜的参考板：服装为酒红色西装套装、黑色丝质吊带衫（只取款式与材质）。"
ROLES = ("卓琳：35岁，黑色齐肩直发中分，哑光正红唇，鲜红色长指甲，酒红色西装套装。祁念：23岁，雾蓝色及腰长直发、空气感碎刘海、灰绿色眼睛，黑色乳胶抹胸紧身短裙，皮肤有水光。")
BG = ("背景在数米之外：影棚白幕落到中灰，一只发光的环形灯、几支灯架与柔光箱、一台落地风机，全部化成大而柔的圆形光斑焦外。")
TAIL = "光线：天花顶灯从上侧 45° 落下，另一侧黑旗负补光，4000K 冷白。两人的脸、发型、服装以参考图为准，两人都不看镜头。电影剧照，真实皮肤质感与毛孔，Kodak 2383 印片色与细腻胶片颗粒，无字幕、无文字、无水印。"
SHOTS = {
 "V1_ots": REFS + "竖构图过肩镜头：85mm 镜头 T1.4，机位在卓琳右肩后、与她坐姿的肩同高，略仰拍祁念（an over-the-shoulder shot, 85 mm at T1.4, camera behind the seated woman's right shoulder at her shoulder height, slightly low angle looking up at the blue-haired standing woman）。画面左下三分之一是卓琳的酒红色西装肩膀和黑色齐肩发，严重焦外虚化、占据前景；祁念站在画面右侧三分之二，脸在焦点上，清晰锐利，视线落在卓琳手上的软尺。" + ROLES + BG + TAIL,
 "V2_insert": REFS + "竖构图插入特写：100mm 微距镜头 T2，一条黄色软尺绕过祁念的腰，卓琳鲜红色长指甲的手指捏着尺带刻度（macro insert shot, 100 mm macro at T2, a measuring tape around the waist, fingers with bright red long nails pinching the tape）。黑色乳胶抹胸短裙的高光反射清晰，浅景深，背景是柔和的焦外光斑。" + TAIL,
 "V3_reverse": REFS + "竖构图反打镜头：75mm 镜头 T1.4，机位在祁念腰的高度、略俯拍坐着的卓琳（reverse shot, 75 mm at T1.4, camera at the standing woman's waist height looking slightly down at the seated woman in the wine-red suit）。卓琳单人入画、脸在焦点上，低头看着软尺；画面边缘前景是祁念焦外的腰与黑色乳胶裙，大幅虚化。" + ROLES + BG + TAIL,
}
REFS4 = ("图1是卓琳的脸部参考（只取脸和发型）。图2是祁念的脸部参考（只取脸和发型）。图3是卓琳本镜的服装参考板：酒红色西装套装、黑色丝质吊带衫（只取款式与材质）。"
         "图4是祁念本镜的服装参考：黑色漆皮抹胸紧身短裙，表面高光漆亮（只取款式与材质，不取姿势和椅子）。")
SHOTS["V1b_ots"] = (REFS4 + "画面中只有两个人：前景背影的卓琳与中景的祁念，没有第三个人。竖构图过肩镜头：85mm 镜头 T1.4，机位低，在卓琳右肩后、约坐姿肩部再低一些，明显仰拍祁念（low-angle over-the-shoulder shot, 85 mm at T1.4, camera low behind the seated woman's right shoulder, clearly looking up at the standing blue-haired woman）。"
    "前景左侧是卓琳的背影，只露出酒红色西装的右肩和手臂，看不到她的脸，严重焦外虚化；她的右手从前景伸出，把一条软尺绕在祁念的腰上，鲜红色长指甲捏着软尺。"
    "中景右侧三分之二只有祁念一人：站立，穿黑色漆皮抹胸紧身短裙，雾蓝色及腰长直发、空气感碎刘海，脸在焦点上，清晰锐利，低头看着腰间软尺，不看镜头，双手自然下垂。"
    + BG + TAIL)
REF_FILES = ["assets_v2/characters/ch_zhuo_lin/face/ch_zhuo_lin_face_ch_zhuo_lin_3.png", "assets_v2/characters/lead_f/face/lead_f_face_v1.png",
             "data/pipeline/runs/series10_v2/images/refboards/board_397e6f94e511.png"]
OVR = {"style_suffix": "", "unet": "base", "steps": 35, "cfg": 3.0, "sampler": "euler", "scheduler": "simple"}

def build(shot, seed, ref_names, ctl_name, strength, tag, start=0.0, end=1.0):
    wf = W.qwen_edit(SHOTS[shot], NEG, ref_names, 1152, 2016, seed, f"ns_ab/previz_s4/{tag}", m=W.QwenModel(), loras=[], ref_resolution=0, crop=False)
    wf = IP.apply(wf, IP.resolve("frame_v9", OVR), set())
    for n in wf.values():
        if "TextEncodeQwenImage" in n.get("class_type", "") and "negative_prompt" in n.get("inputs", {}):
            n["inputs"]["negative_prompt"] = NEG
    wf["200"] = {"class_type": "ModelPatchLoader", "inputs": {"name": "qwen_image_2.1_fun_controlnet_union_int8_convrot.safetensors"}}
    wf["201"] = {"class_type": "LoadImage", "inputs": {"image": ctl_name}}
    wf["202"] = {"class_type": "ZImageFunControlnet", "inputs": {"model": ["60", 0], "model_patch": ["200", 0], "vae": ["12", 0],
                 "strength": strength, "image": ["201", 0], "start_percent": start, "end_percent": end}}
    wf["13"]["inputs"]["model"] = ["202", 0]
    return wf

def _wj(path, obj):
    """原子写 JSON（tmp + os.replace）"""
    import os
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj), encoding="utf-8")
    os.replace(tmp, path)


def build_v1b(end=1.0):
    out = ROOT / "data/ab/previz_s4/wf"
    refs = ["ns_previz/ref1.png", "ns_previz/ref2.png", "ns_previz/ref3.png", "ns_previz/ref4_dress.png"]
    sfx = "" if end >= 1.0 else f"_end{end}"
    tag = f"V1b_ots_depth0.55{sfx}_s101"
    wf = build("V1b_ots", 101, refs, "ns_previz/V1b_ots_depth.png", 0.55, tag, end=end)
    _wj(out / f"{tag}.json", wf)


if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "v1b":
    build_v1b(float(sys.argv[2]) if len(sys.argv) > 2 else 1.0); sys.exit(0)

if __name__ == "__main__":
    out = ROOT / "data/ab/previz_s4/wf"; out.mkdir(parents=True, exist_ok=True)
    jobs = []
    for shot in SHOTS:
        for seed in (101,):
            for kind, st in (("depth", 0.55), ("depth", 0.75)):
                tag = f"{shot}_{kind}{st}_s{seed}"
                wf = build(shot, seed, ["ns_previz/ref1.png", "ns_previz/ref2.png", "ns_previz/ref3.png"], f"ns_previz/{shot}_{kind}.png", st, tag)
                _wj(out / f"{tag}.json", wf); jobs.append(tag)
    print(jobs)
