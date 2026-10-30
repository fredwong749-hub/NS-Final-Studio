"""T59 设计稿生成器（fredw-25）：用 data.json（ep01 真实数据，collect 脚本导出）渲染两个方向 × 三屏静态 HTML。

    python docs/design/t59/build.py            # 生成 dark/*.html、light/*.html、index.html
    python docs/design/t59/build.py --shots    # 另外用无头 Chrome 在 1600×900 截图到 shots/

文字原样取自剧本数据，不改写；只做排版。
"""
import html
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
D = json.loads((HERE / "data.json").read_text(encoding="utf-8"))
E = html.escape
CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
DIRS = {"dark": "深色剪辑台", "light": "浅色内容平台"}
SCREENS = {"episode": "集视图", "inspector": "镜头检查器", "assets": "资产角色卡"}


def img(name):
    return f"../img/{name}"


def meta(s):
    c = s["camera"]
    parts = [p for p in (c.get("size"), c.get("angle"), c.get("move")) if p]
    return parts + [f'{s["duration"]["seconds"]} 秒']


def status(s):
    if not s["last_frame"]:
        return "bad", "缺尾帧"
    if s["video"]:
        return "ok", "视频已出 · 待审"
    return "", "待出视频"


def look_line(s, items=True):
    out = []
    for c in s["characters"]:
        face = D["faces"].get(c["character"])
        av = f'<img class="av" src="{img(face)}" alt="">' if face else \
            f'<span class="av" style="display:grid;place-items:center;background:var(--c-sunken)" >{E(c["name"][:1])}</span>'
        its = ""
        if items and c["character"] == "lin_wan":
            its = '<span class="its">' + "".join(
                f'<img src="{img(D["linwan"]["items"][k][0]["img"])}" alt="">' for k in ("hair", "nails")) + "</span>"
        out.append(f'<div class="look">{av}<span>{E(c["name"])}</span><span class="t2 s">{E(c["look_name"])}造型</span>{its}</div>')
    return "".join(out)


def lines(s):
    rows = [f'<p><span class="who">{E(d["speaker_note"] or "")}</span><span>{E(d["text"])}</span></p>' for d in s["dialogue"]]
    if s.get("voiceover"):
        rows.append(f'<p><span class="who">独白</span><span>{E(s["voiceover"]["text"])}</span></p>')
    return f'<div class="lines">{"".join(rows)}</div>' if rows else ""


def frame(name, cap, cls=""):
    if not name:
        return f'<div class="frame empty {cls}"><span>还没有{E(cap)}</span><button class="btn quiet">出{E(cap)}</button></div>'
    return f'<div class="frame {cls}"><img src="{img(name)}" alt=""><span class="cap">{E(cap)}</span></div>'


def shot_row(s, sel=False, compact=False):
    n = s["id"].split("-")[1]
    st_cls, st_txt = status(s)
    m = "".join(f'<span class="{"sep" if i else ""}">{E(p)}</span>' for i, p in enumerate(meta(s)))
    acts = ""
    if sel:
        acts = ('<div class="actions"><button class="btn quiet">重出首帧</button><button class="btn quiet">重出尾帧</button>'
                '<button class="btn text">提示词</button><span class="grow"></span>'
                '<button class="btn text">全屏对比</button></div>')
    return f'''
    <section class="shot{' sel' if sel else ''}">
      <div class="frames">{frame(s["first_frame"], "首帧")}{frame(s["last_frame"], "尾帧")}</div>
      <div class="info">
        <div class="info-h"><span class="l">{n}</span><span class="t2 s">{m}</span><span class="status {st_cls}"><i class="dot {st_cls or 'none'}"></i>{st_txt}</span></div>
        <p class="script">{E(s["script_text"] or "")}</p>
        {lines(s) if not compact else ""}
        {look_line(s)}
        {acts}
      </div>
    </section>'''


def divider(a, b):
    ok = bool(a["last_frame"]) and bool(b["first_frame"])
    return (f'<div class="divider"><i></i><span>{a["id"].split("-")[1]} 尾帧 → {b["id"].split("-")[1]} 首帧</span>'
            f'<span class="status {"ok" if ok else ""}">{"已衔接" if ok else "未衔接"}</span><i></i></div>')


def topbar(active):
    tabs = [("episode", "镜头"), ("assets", "资产"), ("script", "剧本")]
    nav = "".join(f'<a class="{"on" if k == active else ""}">{t}</a>' for k, t in tabs)
    return f'''
  <header class="topbar">
    <span class="brand">NS Studio</span>
    <span class="ep-switch"><span class="l" style="font-size:var(--fs-m)">第 1 集 · {E(D["episode"]["title"])}</span><i class="caret"></i></span>
    <nav class="nav">{nav}</nav>
    <span class="grow"></span>
    <span class="status-line"><i class="dot"></i>出图就绪 · 队列 0</span>
    <button class="btn text">审片</button>
    <button class="btn text" title="总览 / 节点 / 项目 / 设置">更多</button>
  </header>'''


EP_TITLES = ["旋转门", "深夜外套", "电梯初吻", "两碗汤", "漆皮束腰", "减半的红", "与陈宇的一夜", "预约单", "乳环·针刺", "愈合的痒", "镜前的第一触"]


def ep_rail():
    rows = "".join(
        f'<div class="rail-i{" on" if i == 1 else ""}"><span class="n t2">{i:02d}</span><span class="tt">{E(t)}</span>'
        f'<i class="dot{"" if i == 1 else " none"}"></i></div>' for i, t in enumerate(EP_TITLES, 1))
    return f'<aside class="rail"><div class="rail-h">60 集</div>{rows}</aside>'


def ep_head(sel_idx=None):
    idx = "".join(
        f'<span class="{"on" if i == sel_idx else ""}"><i class="dot {status(s)[0] or "none"}"></i>{s["id"].split("-")[1]}</span>'
        for i, s in enumerate(D["shots"]))
    return f'''
      <div class="ep-head">
        <div><div class="l">{E(D["episode"]["title"])}</div><p class="syn t2">{E(D["episode"]["synopsis"])}</p></div>
        <span class="grow"></span>
        <div class="shot-index">{idx}</div>
        <button class="btn quiet">批量出图</button>
        <button class="btn text">串播</button>
      </div>'''


def page(direction, screen, body):
    return f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>T59 · {DIRS[direction]} · {SCREENS[screen]}</title>
<link rel="stylesheet" href="../tokens.css"><link rel="stylesheet" href="../ui.css"></head>
<body class="dir-{direction}"><div class="app">{body}</div></body></html>
'''


def screen_episode(direction):
    sh = D["shots"]
    rows = shot_row(sh[0], sel=True) + divider(sh[0], sh[1]) + shot_row(sh[1]) + divider(sh[1], sh[2]) + shot_row(sh[2])
    return page(direction, "episode", f'''{topbar("episode")}
  <div class="body ep">{ep_rail()}
    <main class="main">{ep_head(0)}<div class="rows">{rows}</div></main>
  </div>''')


def screen_inspector(direction):
    sh = D["shots"]
    rows = shot_row(sh[0], sel=True, compact=True) + divider(sh[0], sh[1]) + shot_row(sh[1], compact=True) + \
        divider(sh[1], sh[2]) + shot_row(sh[2], compact=True)
    s = sh[0]
    takes = "".join(
        f'<span class="{"on" if i == 7 else "cur" if i == 6 else ""}"><img src="{img(f"ep01_S1_take{i}.jpg")}" alt=""></span>'
        for i in (3, 4, 5, 6, 7))
    m = " · ".join(meta(s))
    return page(direction, "inspector", f'''{topbar("episode")}
  <div class="body ep-insp">
    <main class="main">{ep_head(0)}<div class="rows compact">{rows}</div></main>
    <aside class="insp">
      <div class="insp-h">
        <div class="row"><span class="l">S1</span><span class="t2 s">{E(m)}</span><span class="grow"></span><span class="status new"><i class="dot new"></i>新版本待选</span></div>
        <nav class="tabs"><a class="on">首帧</a><a>尾帧</a><a>视频</a><a>剧本</a><a>人物</a></nav>
      </div>
      <div class="insp-b">
        <div class="flow"><b>改提示词</b><i></i><b>重出</b><i></i><b class="on">对比</b><i></i><b>选定</b></div>
        <div class="compare">
          <div><h4><span>当前 v6</span></h4>{frame("ep01_S1_take6.jpg", "v6")}</div>
          <div><h4><span>新 v7</span></h4>{frame("ep01_S1_take7.jpg", "v7", "pick")}</div>
        </div>
        <div class="takes">{takes}</div>
        <div class="field"><label>首帧提示词</label><div class="textarea">{E(s["image_prompt"] or "")}</div></div>
      </div>
      <div class="insp-f"><button class="btn text">全屏对比</button><span class="grow"></span><button class="btn quiet">再出一版</button><button class="btn primary">选定 v7</button></div>
    </aside>
  </div>''')


CAT = [("outfit", "服装"), ("shoes", "鞋"), ("nails", "美甲"), ("hair", "发型"), ("makeup", "妆容"), ("accessory", "饰品")]
PEOPLE = [("林晚", True), ("顾沉", False), ("陈宇", False), ("Alex", False), ("Ryan", False), ("Kai", False), ("Leo", False)]


def screen_assets(direction):
    A = D["linwan"]
    rail = "".join(
        f'<div class="rail-i{" on" if face else ""}">'
        + (f'<img class="av" src="{img(D["faces"]["lin_wan"])}" alt="">' if face else f'<span class="av ph t2">{E(n[:1])}</span>')
        + f'<span class="tt">{E(n)}</span></div>' for n, face in PEOPLE)
    looks = "".join(f'<div class="lk{" on" if i == 0 else ""}"><img src="{img(lk["img"])}" alt=""><p>{E(lk["name"])}</p>'
                    f'<p class="t2 s">参考图组 · 未建造型</p></div>' for i, lk in enumerate(A["looks"]))
    looks = (f'<div class="lk on"><div class="ph">无预览图 · 生成预览</div><p>默认造型</p><p class="t2 s">用于 {A["used_by_shots"]} 镜</p></div>'
             + looks.replace(' on"', '"') + '<div class="lk add"><div>新建造型</div></div>')
    cats = "".join(f'<a class="{"on" if k == "outfit" else ""}">{t} <span class="t2">{len(A["items"].get(k, []))}</span></a>' for k, t in CAT)
    items = "".join(f'<div><img src="{img(x["img"])}" alt=""><p>{E(x["name"])}</p></div>' for x in A["items"]["outfit"]) + \
        '<div><div class="add">上传</div></div>'
    plates = "".join(f'<figure><img src="{img(A["plates"][k])}" alt=""><figcaption>{t}</figcaption></figure>'
                     for k, t in (("front", "正面"), ("3q", "3/4"), ("side", "侧面"), ("back", "背面")) if k in A["plates"])
    return page(direction, "assets", f'''{topbar("assets")}
  <div class="body assets">
    <aside class="rail"><div class="rail-h">人物 7</div>{rail}</aside>
    <main class="asset-main">
      <div class="hero-row">
        <div class="hero"><img src="{img(A["hero"])}" alt=""></div>
        <div class="hero-i">
          <div><div class="l">林晚</div><p class="t2">女主 · 默认造型</p></div>
          <div class="facts"><div><b>{A["used_by_shots"]}</b><span>入镜</span></div><div><b>{A["wardrobe"]}</b><span>衣橱单品</span></div>
            <div><b>1</b><span>造型</span></div><div><span class="status bad"><i class="dot bad"></i>缺图 {A["missing"]}</span></div></div>
          <div class="looks">{looks}</div>
        </div>
      </div>
      <section class="sec"><nav class="cats">{cats}</nav><div class="items">{items}</div></section>
    </main>
    <aside class="side">
      <section class="sec"><div>身份底板</div><div class="plates">{plates}</div></section>
      <section class="sec sched"><div>每集造型</div><p><span>第 1–60 集</span><span class="t2">默认造型</span></p></section>
      <span class="grow"></span>
      <button class="btn primary" style="justify-content:center">用这些参考出图</button>
    </aside>
  </div>''')


def index():
    cells = "".join(
        f'<figure><a href="{d}/{s}.html"><img src="shots/{d}-{s}.png" alt=""></a><figcaption>{DIRS[d]} · {SCREENS[s]}</figcaption></figure>'
        for d in DIRS for s in SCREENS)
    notes = "".join(f"<li>{E(n)}</li>" for n in D.get("notes", []))
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>T59 设计稿</title>
<style>body{{font-family:"PingFang SC","Microsoft YaHei UI",sans-serif;background:#f4f4f2;color:#17181c;margin:0;padding:40px}}
h1{{font-size:22px;margin:0 0 8px}}p,li{{color:#555;font-size:14px;line-height:1.7}}
.g{{display:grid;grid-template-columns:repeat(3,1fr);gap:24px;margin-top:24px}}img{{width:100%;border-radius:8px;box-shadow:0 4px 20px rgba(0,0,0,.1)}}
figcaption{{font-size:13px;margin-top:6px}}</style></head><body>
<h1>T59 画布重设计 · 两个方向</h1>
<p>原则：页面干净清晰——集视图主角是首尾帧大图；字号 3 级、正文 2 色、强调色 1 个，状态色只在状态标签上；操作只在选中行出现，主操作（重出 / 选定）固定在检查器底部。</p>
<p>数据：第 1 集真实首尾帧与剧本文字（data.json）。检查器里的“当前 v6 / 新 v7”用 S1 本地的两个历史版本示意对比流程。</p>
<ul>{notes}</ul>
<div class="g">{cells}</div></body></html>'''


def main():
    for d in DIRS:
        (HERE / d).mkdir(exist_ok=True)
        for s, fn in (("episode", screen_episode), ("inspector", screen_inspector), ("assets", screen_assets)):
            (HERE / d / f"{s}.html").write_text(fn(d), encoding="utf-8", newline="\n")
    (HERE / "index.html").write_text(index(), encoding="utf-8", newline="\n")
    if "--shots" in sys.argv:
        (HERE / "shots").mkdir(exist_ok=True)
        for d in DIRS:
            for s in SCREENS:
                out = HERE / "shots" / f"{d}-{s}.png"
                subprocess.run([str(CHROME), "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1",
                                "--window-size=1600,900", f"--screenshot={out}", (HERE / d / f"{s}.html").as_uri()],
                               check=True, capture_output=True, timeout=60)
                print(out)


if __name__ == "__main__":
    main()
