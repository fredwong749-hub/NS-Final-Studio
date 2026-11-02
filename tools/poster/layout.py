"""海报排版（PIL）：画面由出图服务出，所有字由代码叠加（不让模型画字）。
尺寸：portrait 2:3 (1600x2400) / landscape 16:9 (2560x1440) / square 1:1 (1600x1600)。
安全区：2:3 与 1:1 四边留 8%；16:9 标题安全区 SMPTE 90%（四边各 5%），再收到左右 6%、上下 7%。
版式 A 居中 / B 左对齐 / C 标题在上，与出图构图一一对应。"""
from __future__ import annotations

from pathlib import Path

import re

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[2]
SIZES = {"portrait": (1600, 2400), "landscape": (2560, 1440), "square": (1600, 1600)}
SAFE = {"portrait": (0.08, 0.08), "landscape": (0.06, 0.07), "square": (0.08, 0.08)}   # (左右, 上下)
FONT_ZH = "C:/Windows/Fonts/NotoSerifSC-VF.ttf"
FONT_ZH_SANS = "C:/Windows/Fonts/NotoSansSC-VF.ttf"
FONT_EN = "C:/Windows/Fonts/georgiab.ttf"
FONT_EN_R = "C:/Windows/Fonts/georgia.ttf"
FONT_EN_I = "C:/Windows/Fonts/georgiai.ttf"
ACCENT = {1: (236, 205, 150), 2: (186, 214, 240)}   # 按季：第 1 季暖金，第 2 季起冷蓝
FACES = {
    "林晚": "assets/characters/lin_wan/refs/lin_wan/ar-c2351c9dcf.png",
    "顾沉": "data/assets/identity_refs/gu_chen/gu_chen_face_ref2va.png",
    "陈宇": "data/assets/identity_refs/chen_yu/chen_yu_face_ref2va.png",
    "阿岚": "data/assets/identity_refs/ch_a_lan/ch_a_lan_face_ref2va.png",
}
EN2ZH = {"Lin Wan": "林晚", "Gu Chen": "顾沉", "Chen Yu": "陈宇", "A-Lan": "阿岚"}


def zh_font(size, weight=800, sans=False):
    f = ImageFont.truetype(FONT_ZH_SANS if sans else FONT_ZH, size)
    f.set_variation_by_axes([weight])
    return f


def font(lang, size, kind="title"):
    if lang == "zh":
        return zh_font(size, {"title": 900, "tag": 500, "body": 400, "name": 600}[kind], sans=kind in ("body", "name"))
    return ImageFont.truetype({"title": FONT_EN, "tag": FONT_EN_I, "body": FONT_EN_R, "name": FONT_EN}[kind], size)


def _cjk(c):
    return "\u4e00" <= c <= "\u9fff" or c in "，。、；：！？（）—“”"


def wrap(draw, text, fnt, width):
    lines, cur = [], ""
    zh = any(_cjk(c) for c in text)
    for tok in (list(text) if zh else text.split(" ")):
        t = (cur + ("" if zh else " ") + tok) if cur else tok
        if draw.textlength(t, font=fnt) <= width:
            cur = t
        else:
            lines.append(cur)
            cur = tok
    if cur:
        lines.append(cur)
    return lines


def cover_crop(img, w, h, cx=0.5, cy=0.4):
    s = max(w / img.width, h / img.height)
    im = img.resize((round(img.width * s), round(img.height * s)), Image.LANCZOS)
    x = min(max(round(im.width * cx - w / 2), 0), im.width - w)
    y = min(max(round(im.height * cy - h / 2), 0), im.height - h)
    return im.crop((x, y, x + w, y + h))


def scrim(base, box, direction="up", strength=235):
    """文字区垫渐变暗，保证字清楚。direction：up=底部最暗 / down=顶部最暗 / right / left"""
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    n = h if direction in ("up", "down") else w
    ramp = bytes(int(strength * min(1.0, (i / max(n - 1, 1)) ** 1.4 * 1.15)) for i in range(n))
    if direction in ("down", "left"):
        ramp = ramp[::-1]
    g = Image.new("L", (1, n)) if direction in ("up", "down") else Image.new("L", (n, 1))
    g.putdata(list(ramp))
    g = g.resize((w, h))
    base.paste(Image.new("RGB", (w, h), (8, 8, 12)), (x0, y0), g)


def circle_face(path, d):
    im = Image.open(ROOT / path).convert("RGB")
    s = min(im.size)
    top = int((im.height - s) * 0.25)
    im = im.crop(((im.width - s) // 2, top, (im.width + s) // 2, top + s)).resize((d, d), Image.LANCZOS)
    m = Image.new("L", (d * 3, d * 3), 0)
    ImageDraw.Draw(m).ellipse((0, 0, d * 3 - 1, d * 3 - 1), fill=255)
    return im, m.resize((d, d), Image.LANCZOS)


def shadow_text(img, xy, text, fnt, fill, anchor="la", blur=10):
    sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).text(xy, text, font=fnt, fill=(0, 0, 0, 200), anchor=anchor)
    sh = sh.filter(ImageFilter.GaussianBlur(blur))
    img.paste(sh, (0, 0), sh)
    ImageDraw.Draw(img).text(xy, text, font=fnt, fill=fill, anchor=anchor)


def cast_strip(img, x, y, cast, lang, d, accent, align="left"):
    gap = int(d * 0.35)
    dr = ImageDraw.Draw(img)
    fn = font(lang, max(18, int(d * 0.2)), "name")
    fr = font(lang, max(15, int(d * 0.16)), "body")
    total = len(cast) * d + (len(cast) - 1) * gap
    if align == "center":
        x = x - total // 2
    for name, role in cast:
        im, m = circle_face(FACES[EN2ZH.get(name, name)], d)
        ring = Image.new("RGBA", (d + 8, d + 8), (0, 0, 0, 0))
        ImageDraw.Draw(ring).ellipse((0, 0, d + 7, d + 7), outline=accent + (255,), width=3)
        img.paste(im, (x, y), m)
        img.paste(ring, (x - 4, y - 4), ring)
        dr.text((x + d // 2, y + d + 14), name, font=fn, fill=(255, 255, 255), anchor="ma")
        dr.text((x + d // 2, y + d + 14 + int(d * 0.26)), role, font=fr, fill=accent, anchor="ma")
        x += d + gap


def render(art_path, kind, lang, comp, content, run, out_path, focus=(0.5, 0.38), show_cast=True):
    W, H = SIZES[kind]
    c = content[lang]
    season = int(m.group(1)) if (m := re.search(r"_s(\d+)$", run)) else 1
    acc = ACCENT.get(season, ACCENT[2])
    img = cover_crop(Image.open(art_path).convert("RGB"), W, H, *focus)
    sx, sy = SAFE[kind]
    L, R, T, B = int(W * sx), int(W * (1 - sx)), int(H * sy), int(H * (1 - sy))
    dr = ImageDraw.Draw(img)
    title = c["title"]
    sub = None
    if season > 1:
        for s in (" 第二季", " Season 2", " Season Two"):
            title = title.replace(s, "")
        sub = f"第{'一二三四五六七八九'[season - 1]}季" if lang == "zh" else f"SEASON {season}"
    parts = title.split(": ") if lang == "en" else [title]
    subfont = font(lang, 56, "tag") if lang == "en" else zh_font(56, 700)

    if kind == "landscape":
        scrim(img, (0, 0, int(W * 0.62), H), "left", 235)
        scrim(img, (0, int(H * 0.72), W, H), "up", 190)
        tw = int(W * 0.40)
        x, y = L, T + int(H * 0.05)
        tfs = 150 if lang == "zh" else 100
        ft = font(lang, tfs, "title")
        shadow_text(img, (x, y), c["tagline"], font(lang, 38, "tag"), acc)
        y += 84
        for part in parts:
            for ln in wrap(dr, part, ft, tw):
                shadow_text(img, (x, y), ln, ft, (255, 255, 255))
                y += int(tfs * 1.12)
        if sub:
            shadow_text(img, (x, y + 6), sub, subfont, acc)
            y += 90
        y += 24
        fb = font(lang, 33, "body")
        for ln in wrap(dr, c["synopsis"], fb, tw):
            dr.text((x, y), ln, font=fb, fill=(236, 236, 236))
            y += 50
        if show_cast:
            cast_strip(img, L, B - 215, c["cast"], lang, 120, acc)
        return _save(img, out_path)

    top_title = comp == "C"
    left = comp == "B"
    cx = L if left else W // 2
    anc = "l" if left else "m"
    tw = R - L
    portrait = kind == "portrait"
    tfs = (170 if lang == "zh" else 112) if portrait else (140 if lang == "zh" else 92)
    ft = font(lang, tfs, "title")
    ffl = font(lang, 44 if portrait else 38, "tag")
    fb = font(lang, 36 if portrait else 31, "body")
    blocks = [ln for p in parts for ln in wrap(dr, p, ft, tw)]
    th = len(blocks) * int(tfs * 1.12)
    syn = wrap(dr, c["synopsis"], fb, tw) if portrait else wrap(dr, c["logline"], fb, tw)
    cast_h = 190 if (show_cast and portrait) else 0
    block_h = 86 + th + (100 if sub else 0) + 64
    syn_h = len(syn) * 52
    if top_title:
        scrim(img, (0, 0, W, int(H * 0.5)), "down", 225)
        scrim(img, (0, int(H * 0.74), W, H), "up", 225)
        y = T
        yy = B - cast_h - syn_h - 10
    else:
        scrim(img, (0, int(H * 0.46), W, H), "up", 240)
        y = B - cast_h - syn_h - block_h - 20
        yy = y + block_h
    shadow_text(img, (cx, y), c["tagline"], ffl, acc, anchor=anc + "a")
    y += 86
    for ln in blocks:
        shadow_text(img, (cx, y), ln, ft, (255, 255, 255), anchor=anc + "a")
        y += int(tfs * 1.12)
    if sub:
        shadow_text(img, (cx, y + 4), sub, subfont, acc, anchor=anc + "a")
    for ln in syn:
        dr.text((cx, yy), ln, font=fb, fill=(236, 236, 236), anchor=anc + "a")
        yy += 52
    if cast_h:
        cast_strip(img, cx, B - cast_h + 30, c["cast"], lang, 104, acc, align="left" if left else "center")
    return _save(img, out_path)


def _save(img, out_path):
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, quality=95)
    return str(out_path)
