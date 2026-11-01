"""挑局部裁切框用：一个镜头所有变体缩略图 + 每 100 px 网格线（768×1344 坐标）。python grid_preview.py <shot> <out.jpg>"""
import sys, json
from pathlib import Path
from PIL import Image, ImageDraw
sys.path.insert(0, str(Path(__file__).parent))
import xp_common as X
shot, out = sys.argv[1], sys.argv[2]
d = X.AB / "leica_sharp" / shot
names = [n for n in ["C0","C1","C2","C3","C4","C7","S1","S2","S3","S4","S5","Sstar"] if (d / f"{n}.png").exists()]
s = 0.4
tw, th = int(768*s), int(1344*s)
img = Image.new("RGB", (tw*6+70, (th+30)*2), "black"); dr = ImageDraw.Draw(img); f = X.font(18)
for i, n in enumerate(names):
    im = Image.open(d / f"{n}.png").convert("RGB").resize((tw, th))
    g = ImageDraw.Draw(im)
    for k in range(100, 1344, 100):
        g.line([(0, k*s), (tw, k*s)], fill=(255, 0, 0) if k % 500 == 0 else (255, 255, 0), width=1)
        if k < 768: g.line([(k*s, 0), (k*s, th)], fill=(255, 0, 0) if k % 500 == 0 else (255, 255, 0), width=1)
    x, y = (i % 6)*(tw+10), (i//6)*(th+30)
    img.paste(im, (x, y+28)); dr.text((x+4, y+2), n, fill="white", font=f)
img.save(out, quality=90)
