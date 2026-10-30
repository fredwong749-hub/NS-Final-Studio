"""
把爬下来的图整理成 LoRA 训练集：校验 -> 去近似重复 -> 过滤小图 -> 缩放 -> 写标注。

用法:
    python prepare_lora_dataset.py heels
    python prepare_lora_dataset.py latex

输出: D:\\NS-Final Studio\\training\\lora_<name>\\images\\0001.jpg + 0001.txt
标注只是 "触发词 + 通用描述"，够训练概念；要更好的效果可以在服务器上用 Qwen3-VL 重新逐张标注。
"""
import os
import shutil
import sys

import imagehash
from PIL import Image, ImageOps

ASSETS = r"D:\NS-Final Studio\assets"
TRAINING = r"D:\NS-Final Studio\training"

DATASETS = {
    "heels": dict(
        # 参考图放前面，去重时优先保留
        sources=[os.path.join(ASSETS, "high heels"), os.path.join(ASSETS, "high heels", "scraped")],
        caption="nsheels, a high heel stiletto pump with an ultra-thin heel over 10cm, "
                "glossy black patent leather, pointed toe",
    ),
    "latex": dict(
        sources=[os.path.join(ASSETS, "clothes", "scraped")],
        caption="nslatex, glossy black latex outfit, high-shine wet look, tight fit",
    ),
}

MIN_SIDE = 512        # 短边小于这个直接丢
MAX_SIDE = 1536       # 长边缩到这个以内，减小上传体积
HASH_DIST = 6         # 感知哈希距离 <= 这个算重复
EXTS = (".jpg", ".jpeg", ".png", ".webp")


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in DATASETS:
        print(f"用法: python {os.path.basename(__file__)} {{{'|'.join(DATASETS)}}}")
        return 2
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    name = sys.argv[1]
    cfg = DATASETS[name]
    out = os.path.join(TRAINING, f"lora_{name}", "images")
    if os.path.isdir(out):
        shutil.rmtree(out)
    os.makedirs(out)

    kept, hashes = 0, []
    skipped = {"broken": 0, "small": 0, "dup": 0}
    for src in cfg["sources"]:
        for fn in sorted(os.listdir(src)):
            path = os.path.join(src, fn)
            if not (os.path.isfile(path) and fn.lower().endswith(EXTS)):
                continue
            try:
                img = Image.open(path)
                img = ImageOps.exif_transpose(img).convert("RGB")
            except Exception:
                skipped["broken"] += 1
                continue
            if min(img.size) < MIN_SIDE:
                skipped["small"] += 1
                continue
            h = imagehash.phash(img)
            if any(h - other <= HASH_DIST for other in hashes):
                skipped["dup"] += 1
                continue
            hashes.append(h)

            if max(img.size) > MAX_SIDE:
                img.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
            kept += 1
            stem = os.path.join(out, f"{kept:04d}")
            img.save(stem + ".jpg", quality=95)
            with open(stem + ".txt", "w", encoding="utf-8") as fh:
                fh.write(cfg["caption"])

    print(f"[{name}] 保留 {kept} 张 -> {out}")
    print(f"  损坏 {skipped['broken']}，太小 {skipped['small']}，重复 {skipped['dup']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
