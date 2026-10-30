"""
林晚 Qwen Image 2.1 身份 LoRA（T37）训练集构建。

只收 manifest 里登记过、QC 通过、非露骨、以获批母版（CM_s1）为身份参考的图：
    assets/characters/lin_wan/{plates,expressions,items/makeup}/manifest.json
输出到 training/lora_lin_wan_qwen21/dataset/：<源目录>_<文件名>.png + 同名 .txt 标注，
以及 dataset_manifest.json（来源、sha256、标注、跳过原因）。

标注规则（身份 LoRA）：以触发词 lnwan_qi 开头，写清除身份以外的一切——服装、姿势/景别/角度、
表情、背景、光线、妆容状态、眼睛颜色状态（素颜=自然深棕；浓妆/夜场=灰蓝美瞳）。
不写发色、刘海、脸型、五官、痣、肤色：这些要被 LoRA 吸进触发词。

收录条件（全部满足）：
  - 在 manifest 里，文件存在，且 sha256 与 manifest 一致（QC 后被改过的文件不收）
  - entry["qc"] 是 dict，qc.nudity 为 False，qc.hits 为空，且没有 qc.pass == False
  - 没有 rejected / explicit / adult / nsfw 标记，正向提示词不含露骨词
  - 身份谱系：以获批母版 plates/master.png（provenance sha256）为身份参考——entry.master_sha256 相符，或 created_at 晚于母版落盘且 references 含 plates/master.png
  - 短边 >= 768
--with-outfit：另收 items/outfit 里的上身图（*_worn_*；产品图里没有人，不收），标注只用
     training/lora_lin_wan_qwen21/captions_outfit.json 里按画面手写的（提示词里妆容/眼睛只在“图1参考”句里，
     自动标注会标错；画面与提示词也有出入），没写标注的跳过。配合 --out-root 输出到单独目录，不动 v1 数据集。
可选：training/lora_lin_wan_qwen21/captions_override.json  {"<源目录>/<文件名>": "标注"} 手工覆盖；
     entry["train_caption"] 也可覆盖；--exclude 排除指定条目。

用法:
    python tools/build_lin_wan_dataset.py            # 构建（先清空 dataset/）
    python tools/build_lin_wan_dataset.py --dry-run  # 只列出会收哪些图
    python tools/build_lin_wan_dataset.py --sheet    # 构建后另出 golden/lora_lin_wan/dataset_sheet.jpg
    python tools/build_lin_wan_dataset.py --with-outfit --out-root training/lora_lin_wan_qwen21_outfit --sheet
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

ROOT = Path(__file__).resolve().parents[1]
CHAR = ROOT / "assets" / "characters" / "lin_wan"
SOURCES = ["plates", "expressions", "items/makeup"]
OUT_ROOT = ROOT / "training" / "lora_lin_wan_qwen21"
OUT = OUT_ROOT / "dataset"
OVERRIDES = OUT_ROOT / "captions_override.json"
OUTFIT_SRC = "items/outfit"
OUTFIT_CAPTIONS = OUT_ROOT / "captions_outfit.json"
SHEET = ROOT / "golden" / "lora_lin_wan" / "dataset_sheet.jpg"


def _auto_trigger(default: str = "lnwan_qi") -> str:
    """林晚出图 LoRA 触发词：唯一来源 config/auto_lora_triggers.json（与导入器、编译器同一份；封板修复 D-6）"""
    try:
        cfg = json.loads((ROOT / "config" / "auto_lora_triggers.json").read_text(encoding="utf-8"))
        return next(e["trigger"] for e in cfg["characters"]["林晚"] if e.get("kind", "image") == "image")
    except (OSError, ValueError, KeyError, StopIteration):
        return default


TRIGGER = _auto_trigger()
MASTER = CHAR / "plates" / "master.png"
MASTER_PROV = CHAR / "plates" / "master.provenance.json"
# 获批母版（项目方 2026-10-30 最终选 golden/assets/master_cand/CM_s1.png，取代 CL_s0）。它没有 manifest 条目，凭 provenance 收录；
# 标注手写（已人工看图确认非露骨）。
MASTER_SHA = None
MASTER_CUTOFF = None
MASTER_CAPTION = (
    f"{TRIGGER}, a young woman, close-up portrait, leaning forward with her cheek resting on one hand, looking at the camera, "
    "calm sultry gaze with softly parted lips, wearing a pink frilly off-shoulder top with a bow and a sparkly strawberry rhinestone necklace, "
    "sweet pink makeup with strawberry-pink glossy lips and rosy blush, grey-blue colored contact lenses, "
    "bright pastel room with pink roses and white fluffy cushions, soft backlit window light, creamy bokeh, "
    "photograph, soft light, natural skin texture")
MIN_SIDE = 768
MAX_SIDE = 1536

# 正向提示词里出现即拒收（负面词不检查——负面词里本来就写着“裸体”等）
EXPLICIT = ["裸", "露点", "乳", "阴", "私处", "性爱", "内衣", "胸罩", "丁字", "情趣", "harness", "lingerie",
            "nude", "naked", "nipple", "topless", "explicit", "nsfw", "sex", "bdsm", "bondage"]
FLAG_KEYS = ["rejected", "explicit", "adult", "nsfw"]

# 先去掉否定短语，避免“不戴美瞳”命中“美瞳”
NEGATIONS = ["不戴美瞳", "不戴任何首饰", "不戴首饰", "无任何道具", "不要沿用", "无美颜", "无磨皮", "未修图", "不放大瞳孔"]

FRAMING = [  # (关键词, 英文)；按顺序取第一个命中
    (["全身"], "full-body shot"),
    (["七分身", "膝盖以上"], "knee-up shot"),
    (["半身", "腰部以上"], "waist-up shot"),
    (["特写", "close-up", "close up"], "close-up portrait"),
    (["头肩"], "head-and-shoulders portrait"),
    (["胸像"], "chest-up portrait"),
]
ANGLE = [
    (["背面", "背影", "从背后", "back view"], "seen from behind"),
    (["四分之三", "3/4", "三分之四", "微侧", "45度"], "three-quarter view"),
    (["正侧面", "90度", "侧面", "侧脸", "profile", "侧身"], "side profile view"),
    (["俯拍", "俯视"], "high-angle shot"),
    (["仰拍", "仰视"], "low-angle shot"),
    (["正面"], "front view"),
]
EXPRESSION = [
    (["哭", "流泪", "泪痕"], "crying, tears on her cheeks"),
    (["愤怒", "生气", "怒"], "angry expression"),
    (["惊讶", "震惊", "吃惊", "惊"], "surprised expression"),
    (["媚眼", "勾人", "撩人"], "sultry half-lidded gaze"),
    (["大笑"], "laughing"),
    (["微笑", "笑"], "gentle smile"),
    (["悲伤", "难过"], "sad expression"),
    (["中性", "平静", "放松的表情", "放松表情"], "neutral relaxed expression"),
]
CLOTHING = [
    (["浅灰色圆领", "浅灰圆领", "灰色圆领", "灰 T", "灰T"], "plain light grey crew-neck t-shirt"),
    (["灰色连体衣", "连体衣"], "plain grey fitted long-sleeve bodysuit"),
    (["白衬衫", "白色衬衫"], "white shirt"),
    (["修身上衣"], "fitted top"),
    (["漆皮超短裙", "漆皮短裙"], "black glossy patent mini skirt"),
    (["铅笔裙"], "pencil skirt"),
    (["连衣裙"], "dress"),
    (["西装外套"], "blazer"),
]
BACKGROUND = [
    (["#808080", "无缝灰", "灰色无缝", "中性灰", "灰底"], "seamless neutral grey studio backdrop"),
    (["浅灰色摄影棚", "浅灰背景"], "plain light grey studio backdrop"),
    (["办公室"], "office background"),
    (["街道", "街头"], "street background"),
]
LIGHTING = [
    (["窗光"], "soft window light"),
    (["棚拍光", "均匀", "柔光"], "soft even studio lighting"),
    (["逆光"], "backlight"),
    (["霓虹"], "neon lighting"),
]
# 妆容状态：先看 entry 字段 / name / design，再看提示词
MAKEUP = [  # research v9 L1–L8；旧 M* 编号兼容。(关键词, 英文, 眼睛状态)；泪痕是叠加层，最先判断
    (["L6", "泪痕", "M6"], "tear-streaked makeup", None),
    (["L5", "夜场", "闪钻", "M5"], "glittering night-club cat-eye makeup with rhinestones", "glam"),
    (["L4", "浓妆", "女王", "M4"], "bold heavy smoky makeup with dark cherry lips", "glam"),
    (["L7", "水光", "纯欲"], "dewy glossy makeup with flushed cheeks and juicy berry lips", "glam"),
    (["L8", "甜妆", "M0"], "sweet pink makeup with strawberry-pink glossy lips", "glam"),
    (["L3", "正红唇", "M3"], "classic red lip makeup with winged eyeliner", "glam"),
    (["L2", "过渡妆", "M2"], "soft office makeup with subtle eyeliner and blotted red lips", "bare"),
    (["L1", "素颜", "M1"], "bare face, almost no makeup", "bare"),
    (["淡妆"], "light natural makeup", "bare"),
]
EYES = {"bare": "natural dark brown eyes", "glam": "grey-blue colored contact lenses"}


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def first(text: str, table):
    for keys, en in table:
        if any(k.lower() in text.lower() for k in keys):
            return en
    return None


def all_hits(text: str, table):
    return [en for keys, en in table if any(k.lower() in text.lower() for k in keys)]


def clean_prompt(prompt: str) -> str:
    for n in NEGATIONS:
        prompt = prompt.replace(n, " ")
    # “图1只提供…；不要沿用图1的姿势…”这类参考说明不是对本图的描述，去掉第一句
    prompt = re.sub(r"图\d只提供[^。]*。", " ", prompt)
    return prompt


def caption_for(entry: dict, src: str) -> str:
    raw = entry.get("prompt") or ""
    p = clean_prompt(raw)
    meta = " ".join(str(entry.get(k) or "") for k in ("design", "name", "makeup", "look", "expression"))

    makeup_en, eye_state = None, None
    for keys, en, state in MAKEUP:
        if any(k in meta for k in keys) or any(k in p for k in keys if not re.fullmatch(r"[A-Z]\d", k)):
            if makeup_en is None:
                makeup_en = en
            if state is not None:
                eye_state = state
                break
    if makeup_en is None:
        makeup_en = "bare face, almost no makeup"
    if eye_state is None:
        eye_state = "bare"
    # 眼睛：提示词明说的优先
    if "灰蓝色美瞳" in p or "grey-blue contact" in p.lower():
        eye_state = "glam"
    elif "深棕" in p or "dark brown" in p.lower():
        eye_state = "bare"
    if isinstance(entry.get("eyes"), str):
        eye_state = "glam" if ("灰蓝" in entry["eyes"] or "grey" in entry["eyes"].lower()) else "bare"

    parts = [TRIGGER, "a young woman"]
    framing = first(p, FRAMING)
    angle = first(p, ANGLE)
    parts += [x for x in (framing, angle) if x]
    if "朝向画面左" in p or "转向左" in p:
        parts.append("turned toward the left of the frame")
    elif "朝向画面右" in p or "转向右" in p:
        parts.append("turned toward the right of the frame")
    if "平视镜头" in p or "看镜头" in p or "看向镜头" in p or "looking at the camera" in p.lower():
        parts.append("looking at the camera")
    elif "看向画面左" in p:
        parts.append("looking off to the left")
    elif "看向画面右" in p:
        parts.append("looking off to the right")
    elif "低头" in p or "向下看" in p:
        parts.append("looking down")
    expr = first(meta + " " + p, EXPRESSION) if src == "expressions" else first(p, EXPRESSION)
    if expr:
        parts.append(expr)
    clothes = all_hits(p, CLOTHING)
    if clothes:
        parts.append("wearing " + " and ".join(clothes))
    if "首饰" in raw and ("不戴" in raw or "无" in raw):
        parts.append("no jewelry")
    if "双手不入画" in p or "手不入画" in p:
        parts.append("hands out of frame")
    parts.append(makeup_en)
    parts.append(EYES[eye_state])
    bg = first(p, BACKGROUND)
    if bg:
        parts.append(bg)
    light = first(p, LIGHTING)
    if light:
        parts.append(light)
    parts.append("photograph, natural skin texture")
    return ", ".join(parts)


def reject_reason(entry: dict, path: Path) -> str | None:
    if not path.is_file():
        return "file missing"
    for k in FLAG_KEYS:
        if entry.get(k):
            return f"flag {k}"
    if "reject" in str(entry.get("status") or "").lower() or "rejected" in path.name:
        return f"rejected: {entry.get('status')}"
    # 身份谱系：只收以当前获批母版为身份基准的图（获批母版落盘之后生成的；之前的派生自被拒母版）
    if MASTER_SHA is None:
        return "no approved master (plates/master.png + provenance sha256)"
    if entry.get("master_sha256") not in (None, MASTER_SHA):
        return "derived from a different master (master_sha256 mismatch)"
    if entry.get("master_sha256") != MASTER_SHA:
        created = str(entry.get("created_at") or "")
        if not created or created < MASTER_CUTOFF:
            return f"predates approved master ({created or 'no created_at'} < {MASTER_CUTOFF})"
        refs = [str(r).replace("\\", "/") for r in (entry.get("references") or [])]
        if not any(r.endswith("lin_wan/plates/master.png") for r in refs):
            return f"identity reference is not plates/master.png ({refs})"
    qc = entry.get("qc")
    if not isinstance(qc, dict):
        return "no qc (not QC-passed)"
    if qc.get("nudity") is not False:
        return "qc nudity not False"
    if qc.get("hits"):
        return f"qc hits {qc['hits']}"
    if qc.get("pass") is False:
        return "qc pass False"
    prompt = (entry.get("prompt") or "").lower()
    bad = [w for w in EXPLICIT if w.lower() in prompt]
    if bad:
        return f"explicit words in prompt {bad}"
    want = entry.get("sha256")
    if want and sha256(path) != want:
        return "sha256 mismatch with manifest"
    with Image.open(path) as im:
        if min(im.size) < MIN_SIDE:
            return f"too small {im.size}"
    return None


def load_master():
    """获批母版的 sha256 与时间戳下限；provenance 与文件不符则不收母版、不设谱系门（返回 None 并提示）。"""
    global MASTER_SHA, MASTER_CUTOFF
    if not (MASTER.is_file() and MASTER_PROV.is_file()):
        return None
    prov = json.loads(MASTER_PROV.read_text("utf-8"))
    digest = sha256(MASTER)
    if prov.get("sha256") != digest:
        print(f"WARN master.png sha256 {digest} != provenance {prov.get('sha256')}; master not used")
        return None
    from datetime import datetime
    MASTER_SHA = digest
    MASTER_CUTOFF = datetime.fromtimestamp(MASTER_PROV.stat().st_mtime).strftime("%Y-%m-%dT%H:%M:%S")
    return digest


def collect(exclude: set[str], with_outfit: bool = False):
    overrides = json.loads(OVERRIDES.read_text("utf-8")) if OVERRIDES.is_file() else {}
    keep, skipped, seen = [], [], set()
    digest = load_master()
    if digest and "plates/master.png" not in exclude:
        seen.add(digest)
        keep.append({"source": "plates/master.png", "path": MASTER, "sha256": digest,
                     "caption": overrides.get("plates/master.png") or MASTER_CAPTION})
    outfit_caps = json.loads(OUTFIT_CAPTIONS.read_text("utf-8")) if with_outfit and OUTFIT_CAPTIONS.is_file() else {}
    for src in SOURCES + ([OUTFIT_SRC] if with_outfit else []):
        d = CHAR / src
        mf = d / "manifest.json"
        if not mf.is_file():
            continue
        for entry in json.loads(mf.read_text("utf-8")):
            rel = f"{src}/{entry.get('file')}"
            if rel == "plates/master.png":
                continue  # 获批母版走 provenance，manifest 里的旧 master 条目不算
            path = d / str(entry.get("file"))
            if src == OUTFIT_SRC and "_worn_" not in path.name:
                continue  # 产品/平铺/人台图：没有人
            reason = "excluded by --exclude" if rel in exclude else reject_reason(entry, path)
            if reason is None and src == OUTFIT_SRC and rel not in outfit_caps:
                reason = f"no hand-written caption in {OUTFIT_CAPTIONS.name}"
            if reason is None:
                digest = sha256(path)
                if digest in seen:
                    reason = "duplicate image"
                else:
                    seen.add(digest)
            if reason:
                skipped.append({"source": rel, "reason": reason})
                continue
            cap = outfit_caps.get(rel) or overrides.get(rel) or entry.get("train_caption") or caption_for(entry, src)
            if not cap.startswith(TRIGGER):
                cap = f"{TRIGGER}, {cap}"
            keep.append({"source": rel, "path": path, "sha256": digest, "caption": cap})
    return keep, skipped


def write_dataset(keep):
    if OUT.is_dir():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    rows = []
    for item in keep:
        stem = item["source"].replace("items/makeup", "makeup").replace(OUTFIT_SRC, "outfit").replace("/", "_").rsplit(".", 1)[0]
        dst = OUT / f"{stem}.png"
        with Image.open(item["path"]) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
            if max(im.size) > MAX_SIDE:
                im.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
            im.save(dst)
        dst.with_suffix(".txt").write_text(item["caption"], "utf-8")
        rows.append({"file": dst.name, "source": item["source"], "source_sha256": item["sha256"],
                     "caption": item["caption"]})
    return rows


def make_sheet(rows, cols=6, cell=256):
    n = len(rows)
    if not n:
        return
    rws = (n + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cell, rws * (cell + 18)), "white")
    draw = ImageDraw.Draw(sheet)
    for i, r in enumerate(rows):
        with Image.open(OUT / r["file"]) as im:
            im = ImageOps.contain(im.convert("RGB"), (cell, cell))
        x, y = (i % cols) * cell, (i // cols) * (cell + 18)
        sheet.paste(im, (x + (cell - im.width) // 2, y))
        draw.text((x + 3, y + cell + 2), r["file"][:40], fill="black")
    SHEET.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(SHEET, quality=90)
    print(f"sheet -> {SHEET}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--sheet", action="store_true")
    ap.add_argument("--with-outfit", action="store_true", help="另收 items/outfit 的上身图（标注见 captions_outfit.json）")
    ap.add_argument("--out-root", help="输出目录（默认 training/lora_lin_wan_qwen21）；dataset/ 与 dataset_manifest.json 写在其下")
    ap.add_argument("--exclude", nargs="*", default=[], help="<源目录>/<文件名>, e.g. plates/id_front_s0.png")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    global OUT_ROOT, OUT, SHEET
    if a.out_root:
        OUT_ROOT = (ROOT / a.out_root).resolve()
        OUT = OUT_ROOT / "dataset"
        SHEET = OUT_ROOT / "dataset_sheet.jpg"
    keep, skipped = collect(set(a.exclude), a.with_outfit)
    for s in skipped:
        print(f"SKIP {s['source']}: {s['reason']}")
    for k in keep:
        print(f"KEEP {k['source']}\n     {k['caption']}")
    print(f"{len(keep)} kept, {len(skipped)} skipped")
    if a.dry_run:
        return 0
    rows = write_dataset(keep)
    (OUT_ROOT / "dataset_manifest.json").write_text(
        json.dumps({"trigger": TRIGGER, "count": len(rows), "images": rows, "skipped": skipped},
                   ensure_ascii=False, indent=2), "utf-8")
    print(f"dataset -> {OUT} ({len(rows)} images)")
    if a.sheet:
        make_sheet(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
