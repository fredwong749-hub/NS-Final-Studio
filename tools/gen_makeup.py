"""
林晚妆容资产：以项目方定妆图为编辑对象，只改妆容，脸型/五官/发型/肤色保持不变。

    uv run python tools/gen_makeup.py                 # 全部妆容，每款 2 个种子
    uv run python tools/gen_makeup.py --only M1 M3 --seeds 3

输出: assets/characters/lin_wan/items/makeup/<id>_s<seed>.png + manifest.json
妆容按剧本出现的状态设计（素颜通勤、ep06 过渡妆、正红唇、浓妆女王、夜场、泪痕），见 docs/REQUIREMENTS.md B4。
"""
import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

from ns_render import workflows as W
from ns_render.comfy_client import ComfyClient

ROOT = Path(__file__).resolve().parent.parent
REF = ROOT / "assets" / "linwan" / "file_0000000092c081fd95f7f5b85917993d.png"
OUT = ROOT / "assets" / "characters" / "lin_wan" / "items" / "makeup"
SIZE = (1024, 1280)   # 胸像 4:5

KEEP = ("图1是林晚本人：严格保持图1的脸型、五官比例、眼睛形状、鼻子、嘴唇形状、浅冰蓝色及腰直发与齐刘海、冷白皮肤完全一致，"
        "只修改妆容；改为正面胸像，双手放下不碰脸，不戴项链和任何首饰，穿素色浅灰圆领上衣，背景为干净的中性浅灰色摄影棚纸背景，"
        "柔和均匀的美妆摄影布光，Leica 镜头锐利解析力，皮肤纹理真实，画面干净无文字。妆容：")

LOOKS = {
    "M0": ("定妆原版甜妆", "保持图1原有的粉嫩甜美妆：粉色腮红、水润粉色唇釉、浓密卷翘睫毛、浅色眼影，娃娃感"),
    "M1": ("素颜通勤（REF-LW-01）", "几乎素颜的清透通勤妆：仅有薄透底妆和自然眉形，淡粉裸色润唇，无眼线无假睫毛，干净清爽的学生感"),
    "M2": ("ep06 过渡妆（减半红唇＋恰到好处的眼线）", "淡雅日常妆：薄涂的半哑光红唇（只涂一半饱和度的红），细而克制的黑色内眼线，淡棕眼影，柔和腮红"),
    "M3": ("正红唇＋精致眼线", "精致都市妆：饱满的正红色哑光红唇，利落上扬的黑色眼线，大地色眼影，轮廓清晰的眉形，干净的高光"),
    "M4": ("浓妆女王（REF-LW-02）", "浓郁女王妆：深色烟熏眼妆与浓黑眼线，浓密假睫毛，深酒红色唇，明显的修容与高光，冷艳强势"),
    "M5": ("夜场闪钻猫眼妆", "夜场派对妆：上扬的黑色猫眼眼线，上眼睑整片铺满大颗粒银色亮片与细碎水钻，眼头和眼尾各贴一排清晰可见的小颗水钻，"
                      "下眼睑也点缀细闪，水钻有清晰的刻面反光；颧骨上方明显的珠光高光；透亮玻璃感粉色唇釉带细闪"),
    "M6": ("泪痕妆", "刚哭过的妆：双眼眼眶明显泛红、下眼睑湿润发亮，睫毛被泪水打湿成簇，两道清晰发亮的泪痕从眼角沿脸颊一直流到下颌，"
                   "脸颊上挂着一颗清晰的泪珠，黑色眼线被泪水晕开在下眼睑形成淡淡的灰黑色晕染，鼻尖微红，唇色变淡"),
}


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", default=list(LOOKS))
    ap.add_argument("--seeds", type=int, default=2)
    ap.add_argument("--first-seed", type=int, default=0, help="种子序号起点（重做时换一组种子，旧文件不覆盖）")
    ap.add_argument("--comfy", default="http://127.0.0.1:8188")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    manifest_path = OUT / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else []
    client = ComfyClient(args.comfy)
    ref_name = client.upload_image(REF)
    model = W.QwenModel()

    for mid in args.only:
        name, desc = LOOKS[mid]
        prompt = KEEP + desc
        for k in range(args.first_seed, args.first_seed + args.seeds):
            seed = int(hashlib.sha256(f"lin_wan/makeup/{mid}#{k}".encode()).hexdigest()[:12], 16)
            wf = W.qwen_edit(prompt, "", ref_name, *SIZE, seed, f"ns_final/makeup_{mid}", m=model)
            entry, secs = client.run(wf, timeout_s=900)
            item = next(f for f in client.output_files(entry) if f["filename"].endswith(".png"))
            dest = client.download(item, OUT / f"{mid}_s{k}.png")
            manifest = [m for m in manifest if m["file"] != dest.name]
            manifest.append({"file": dest.name, "kind": "item/makeup", "design": mid, "name": name,
                             "prompt": prompt, "seed": seed, "model": model.unet, "workflow": "qwen_edit",
                             "references": [str(REF.relative_to(ROOT)).replace("\\", "/")],
                             "sha256": sha256(dest), "created_at": time.strftime("%Y-%m-%dT%H:%M:%S")})
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"{mid} {name} s{k}: {secs:.0f}s -> {dest.name}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
