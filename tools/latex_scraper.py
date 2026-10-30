"""
从 Bing 图片搜索批量下载参考图（仅用标准库，无需 pip install）。

用法:
    python latex_scraper.py                          # 默认关键词，下载 100 张
    python latex_scraper.py -p heels                 # 高跟鞋预设（CL / YSL 等 10cm+ 漆皮细跟）
    python latex_scraper.py -n 200 -o D:\\out        # 指定数量和输出目录
    python latex_scraper.py -q "black latex catsuit" -q "pvc corset glossy"

注意: 搜到的图片版权归原作者所有，仅作个人参考；用于游戏/商用素材前请确认授权。
"""
import argparse
import hashlib
import html
import os
import random
import re
import sys
import time
import urllib.parse
import urllib.request

PRESETS = {
    "latex": ([
        "glossy latex lingerie",
        "shiny pvc lingerie set",
        "patent leather lingerie",
        "wet look vinyl lingerie",
        "latex bodysuit glossy",
        "latex corset shiny",
        "vinyl bodysuit high gloss",
        "pvc bra and panty set shiny",
    ], r"D:\NS-Final Studio\assets\clothes\scraped"),
    "heels": ([
        "Christian Louboutin So Kate 120 patent pump",
        "Christian Louboutin Pigalle Follies 100 patent",
        "Christian Louboutin Hot Chick 130 patent",
        "Saint Laurent Opyum 110 patent pumps",
        "Saint Laurent Opyum stiletto heel",
        "YSL Zoe 105 patent pumps",
        "Gianvito Rossi 105 patent stiletto pumps",
        "Jimmy Choo Romy 110 patent pumps",
        "Manolo Blahnik BB 115 patent pumps",
        "Casadei Blade 120 stiletto",
        "Christian Louboutin Kate 100 patent pump",
        "Aquazzura stiletto 105 patent",
        "patent leather 12cm stiletto pumps",
        "glossy patent pointed toe stiletto heels 120mm",
    ], r"D:\NS-Final Studio\assets\high heels\scraped"),
}

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")

# 文件头 -> 扩展名，用来确认下载的确实是图片
MAGIC = [
    (b"\xff\xd8\xff", ".jpg"),
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"RIFF", ".webp"),  # 后面再校验 WEBP 标记
]

MIN_BYTES = 30 * 1024  # 过滤缩略图/占位图


def fetch(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def search_bing(query, offset, count=35):
    params = urllib.parse.urlencode({
        "q": query, "first": offset, "count": count,
        "adlt": "moderate", "qft": "+filterui:imagesize-large",
    })
    page = fetch(f"https://www.bing.com/images/async?{params}").decode("utf-8", "ignore")
    page = html.unescape(page)
    return re.findall(r'"murl":"(.*?)"', page)


def sniff_ext(data):
    for magic, ext in MAGIC:
        if data.startswith(magic):
            if ext == ".webp" and data[8:12] != b"WEBP":
                return None
            return ext
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", "--num", type=int, default=100)
    ap.add_argument("-p", "--preset", choices=PRESETS, default="latex", help="预设关键词组和输出目录")
    ap.add_argument("-o", "--out")
    ap.add_argument("-q", "--query", action="append", help="搜索关键词，可多次指定")
    args = ap.parse_args()

    # 重定向到文件时 Windows 默认 cp1252，打印中文会崩
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    preset_queries, preset_out = PRESETS[args.preset]
    queries = args.query or preset_queries
    args.out = args.out or preset_out
    os.makedirs(args.out, exist_ok=True)

    # 已有文件的哈希，重复运行时不会下载重复图
    seen_hash = set()
    for f in os.listdir(args.out):
        with open(os.path.join(args.out, f), "rb") as fh:
            seen_hash.add(hashlib.md5(fh.read()).hexdigest())
    seen_url = set()
    saved = 0

    # 每个关键词平均分配名额，避免全被第一个关键词占满
    per_query = -(-args.num // len(queries))
    for query in queries:
        quota = min(args.num, saved + per_query)
        offset = 1
        empty_pages = 0
        while saved < quota and offset < 600 and empty_pages < 2:
            try:
                urls = search_bing(query, offset)
            except Exception as e:
                print(f"[搜索失败] {query} @ {offset}: {e}")
                break
            offset += 35
            new = [u for u in urls if u not in seen_url]
            if not new:
                empty_pages += 1
                continue
            empty_pages = 0

            for url in new:
                if saved >= quota:
                    break
                seen_url.add(url)
                try:
                    data = fetch(url)
                except Exception:
                    continue
                ext = sniff_ext(data)
                if not ext or len(data) < MIN_BYTES:
                    continue
                h = hashlib.md5(data).hexdigest()
                if h in seen_hash:
                    continue
                seen_hash.add(h)
                saved += 1
                path = os.path.join(args.out, f"{saved:03d}_{h[:8]}{ext}")
                with open(path, "wb") as fh:
                    fh.write(data)
                print(f"[{saved}/{args.num}] {query} <- {url[:80]}")
                time.sleep(random.uniform(0.3, 0.8))
        if saved >= args.num:
            break

    print(f"\n完成: 共保存 {saved} 张 -> {args.out}")
    return 0 if saved else 1


if __name__ == "__main__":
    sys.exit(main())
