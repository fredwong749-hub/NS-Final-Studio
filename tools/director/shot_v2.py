"""镜头语言模板 v2 编译（DIRECTOR r4 / L-107 / L-111 / 镜头 P0；K-EDT-818、K-REN-802 / 803）。decider = code。
单一来源：config/director/shot_spec_v2.yaml（段落与顺序）、lighting.yaml（灯光方案）、lenses.yaml（徕卡 M 镜头组）、camera_moves.yaml（运镜）。
首帧与视频共用：image_clauses_zh() 给首帧 ②镜头 + ④灯光两句中文（IMGFIX 拼进出图提示词，替换预设 50mm 句），compile_v2() 给视频 ①–⑦ + 约束句。
输入：剧本镜（中文字段 + 写作方的英文 H3 正文）、cut_plan、config/director/{shot_spec_v2,lighting,camera_moves}.yaml
输出：{image: ①–④, video: ①–⑦ + 约束句, segments: [(no, zh, en, auto)]}"""
import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/director"))
import yaml  # noqa: E402
import cut_plan as CP  # noqa: E402

SPEC = yaml.safe_load((ROOT / "config/director/shot_spec_v2.yaml").read_text(encoding="utf-8"))
LT = yaml.safe_load((ROOT / "config/director/lighting.yaml").read_text(encoding="utf-8"))
SIDE = {"frame-right": "frame right", "frame-left": "frame left", "above": "above", "front": "the front", "behind": "behind"}


def body_of(h3):
    m = re.search(r"integrated_multimodal_description:(.*?)(overall_soundscape:|$)", h3 or "", re.S)
    return (m.group(1) if m else "").strip()


def sound_of(h3):
    m = re.search(r"overall_soundscape:(.*?)(\n\w+:|$)", h3 or "", re.S)
    return (m.group(1) if m else "").strip()


def pick_scheme(shot, lvl):
    """动机光源优先（L-111）：首帧原文里出现的光源词 = 场景里真实存在的光；方案的主光源在场 +3、场景词 +1、时段 +1、高点情绪 +1"""
    txt = f"{shot.get('scene_id') or ''} {shot.get('img_prompt') or ''}"
    present = {k for k, v in LT["sources"].items() if any(w in (shot.get("img_prompt") or "") for w in v["zh"])}
    night = bool(re.search(r"night|夜|深夜", txt, re.I)) or (bool(present & {"desk_lamp", "ceiling_lamp", "candle", "streetlight"})
                                                         and "window_day" not in present)
    hot = ("对峙", "压迫", "高点")

    def score(sc):
        v = 3 * (sc["key"]["source"] in present) + (1 if sc["when"]["scene"] and any(k in txt for k in sc["when"]["scene"]) else 0)
        v += 1 if sc["when"]["time"] == ("night" if night else "day") else -2
        hit = any(m in sc["moods"] for m in hot)
        v += (1 if hit else 0) if (lvl or 0) >= 3 else (-1 if hit else 0)
        return v
    return max(LT["schemes"], key=score)


def compile_v2(shot, plan):
    b = body_of(shot.get("h3_prompt"))
    segs = []
    size = CP.size_of(shot) or "中景"
    angle = next((v for k, v in SPEC["angle_en"].items() if k in (shot.get("img_prompt") or "")[:30]), "eye level")
    stop = re.compile(r", (?:seated|standing|sitting|leaning|with (?:her|his) (?:eyes|gaze)|her face|his face|in a dark|at the|lit by)\b|, and a \d")
    subs = []
    head = b.split(" The camera ")[0]
    for st in re.finditer(r"\ba \d{2}-year-old ", head):
        rest = head[st.start():]
        e2 = stop.search(rest)
        subs.append(rest[:e2.start()] if e2 else rest.split(".")[0])
    subj = " and ".join(subs) if subs else "the characters"
    segs.append(("①", "机位与景别", f"A {SPEC['size_en'].get(size, 'medium shot')} from {angle} of {subj}.", False))
    LN = yaml.safe_load((ROOT / "config/director/lenses.yaml").read_text(encoding="utf-8"))
    L = {x["id"]: x for x in LN["lenses"]}[LN["by_size"].get(size, ["summicron_50_f2"])[0]]
    segs.append(("②", "镜头参数", f"Shot on {L['en']} at {L['aperture']}, {L['dof_en']}.", True))
    cast = [c for c in CP._load_list(shot.get("cast")) if isinstance(c, dict) and c.get("presence") == "在画"]
    who = {"林晚": "the woman", "顾沉": "the man"}
    places = [f"{who.get(c['name'], c['name'])} at {SPEC['position_en'].get(c.get('x'), 'frame center')} in "
              f"{SPEC['depth_en'].get(c.get('depth'), 'the midground')}" for c in cast]
    bg = re.search(r"\b(?:at|in) (?:the corner of )?(a [^,.]*?(?:office|room|corner|kitchen|street|restaurant|bar|home|table)(?:(?! lit by)[^,.])*)", b)
    look = re.search(r"(?:eyes|gaze) (?:resting )?on ([^,.]*)", b)
    lead = f"leaving open space in the line of sight toward {look.group(1)}" if look else "leaving open space in the direction of the gaze"
    comp = "; ".join(places)
    segs.append(("③", "构图", f"{comp[:1].upper() + comp[1:]}, {bg.group(1) if bg else 'the room'} softly out of focus behind; {lead}.", True))
    lvl = CP.intensity(shot)
    sc = pick_scheme(shot, lvl)
    side = "frame right" if re.search(r"from the right", b) else ("frame left" if re.search(r"from the left", b)
                                                               else SIDE.get(sc["key"]["side"], "frame right"))
    lt = " ".join(sc["en"].split()).format(key_side=side, ratio_en=LT["ratios"][sc["ratio"]]["en"])
    adapt = " ".join(LT["character_adapt"][k] for k, n in (("lin_wan", "林晚"), ("gu_chen", "顾沉")) if any(c["name"] == n for c in cast))
    contact = ""   # 接触阴影由 IMGFIX 融合契约句负责（11-02 对齐）
    segs.append(("④", "灯光设计", f"{lt} {adapt} {contact}".strip(), True))
    cam = ((plan or {}).get("camera") or {}).get("clause_en") or "The camera holds a static shot"
    tail = (shot.get("motion_prompt") or "").split("——")[-1]
    em = re.search("|".join(sorted(SPEC["size_en"], key=len, reverse=True)), tail or "")
    ss = SPEC["size_en"].get(size, "medium shot")
    es = SPEC["size_en"].get(em.group(0) if em else size, ss)
    move_txt = f"{cam}, from the {ss} to a slightly tighter {es}" if "pushes in" in cam else f"{cam}, holding the {ss} framing"
    segs.append(("⑤", "运镜", move_txt + ".", True))
    first = re.search(r"The camera [^.]*? as ([^.]*)\.", b)
    beats = [f"At 00:00.000, {first.group(1)}." if first else ""]
    beats += [x.strip() for x in re.findall(r"At 00:0\d\.000, .*?(?=At 00:0\d\.000|The (?:woman|man) settles|$)", b, re.S)]
    spk = [d.get("speaker") for d in CP._load_list(shot.get("dialogue")) if isinstance(d, dict) and d.get("speaker")]
    if spk:   # VIDEO-RCA：口型开合太小（顾沉 29 条只过 15）→ 说话人加清晰口型句（V7 验证）
        beats.append(SPEC["segments"][5]["speaker_clause_en"].format(speaker={"顾沉": "The man", "林晚": "The woman"}.get(spk[0], spk[0])))
    segs.append(("⑥", "表演节拍", " ".join(x for x in beats if x), False))
    segs.append(("⑦", "声音 / 转场", sound_of(shot.get("h3_prompt")), False))
    video = " ".join(s[2] for s in segs) + " " + SPEC["constraints_en"]
    image = " ".join(s[2] for s in segs if s[0] in "①②③④")
    return {"segments": segs, "video": video, "image": image, "scheme": sc["id"],
            "transition": (plan or {}).get("transition_in", {}), "j_cut_s": (plan or {}).get("j_cut_s"), "l_cut_s": (plan or {}).get("l_cut_s")}


def key_side_zh(img: str) -> str | None:
    """首帧原文里主光源的方向（台灯右侧 / 从左 / 从上方）"""
    if re.search(r"台灯[^，]{0,4}右|右侧逆光|从右", img or ""):
        return "右侧"
    if re.search(r"从左|左侧逆光|台灯[^，]{0,4}左", img or ""):
        return "左侧"
    if re.search(r"从上方|上方", img or ""):
        return "上方"
    return None


def pick_lens(shot: dict, override: str | None = None) -> dict:
    """K-REN-802：剧本【镜头】(override) > 景别默认（lenses.yaml by_size 第一个）"""
    LN = yaml.safe_load((ROOT / "config/director/lenses.yaml").read_text(encoding="utf-8"))
    by = {x["id"]: x for x in LN["lenses"]}
    if override:
        hit = by.get(override) or next((x for x in LN["lenses"] if x["zh"] in override or override in x["zh"]), None)
        if hit:
            return hit
    return by[LN["by_size"].get(CP.size_of(shot) or "中景", [LN["baseline"]["id"]])[0]]


def image_clauses_zh(shot: dict, lens_override: str | None = None) -> dict:
    """首帧用的 ②镜头 + ④灯光（中文）。→ {lens_id, lens_zh, lighting_zh, scheme, key_side, decider, auto}"""
    lvl = CP.intensity(shot)
    sc = pick_scheme(shot, lvl)
    side = key_side_zh(shot.get("img_prompt") or "")
    zh = sc["zh_text"]
    if side in ("右侧", "左侧"):
        zh = zh.replace("画面右侧", f"画面{side}").replace("画面一侧", f"画面{side}")
    cast = [c["name"] for c in CP._load_list(shot.get("cast")) if isinstance(c, dict) and c.get("presence") == "在画"]
    adapt = [LT["character_adapt_zh"][k] for k, n in (("lin_wan", "林晚"), ("gu_chen", "顾沉")) if n in cast]
    L = pick_lens(shot, lens_override)
    return {"lens_id": L["id"], "lens_zh": f"{L['zh']}，光圈 {L['aperture']}，{L['dof_zh']}",
            "lighting_zh": "；".join([zh, *adapt]) + "。", "scheme": sc["id"], "key_side": side, "decider": "code",
            "auto": {"lighting": True, "lens": lens_override is None}}


def page(rows, out):
    e = html.escape
    css = ("body{font-family:system-ui,'Microsoft YaHei';margin:20px;background:#111;color:#ddd;max-width:1500px}"
           "td,th{border:1px solid #444;padding:6px 10px;vertical-align:top;font-size:13px}table{border-collapse:collapse;width:100%}"
           "th{background:#222}.auto{color:#8cf}.seg{color:#fc6;font-weight:bold}h2{margin-top:30px}code{color:#9cf}")
    o = [f"<html><head><meta charset='utf-8'><title>镜头语言模板 v2 对照</title><style>{css}</style></head><body>",
         "<h1>镜头语言模板 v2：新旧提示词对照（ep01 三镜）</h1>",
         "<p>模板 <code>config/director/shot_spec_v2.yaml</code>；灯光 <code>config/director/lighting.yaml</code>；运镜 <code>config/director/camera_moves.yaml</code>"
         "（目前 enabled = 固定、推近，其余 Pika A/B 中）。新稿全部由代码按模板编（decider=code）：写作方原文英文按段落位，"
         "<span class='auto'>蓝色 = 代码按词表自动补（第一季剧本没有该字段）</span>。首帧用 ①–④，视频用 ①–⑦ + 约束句。剧情和台词一字不改。</p>"]
    for s, plan, r in rows:
        o.append(f"<h2>ep01-S{s['index']}（{e(CP.size_of(s) or '')}；灯光方案 {e(r['scheme'])}；转场 "
                 f"{e(json.dumps(r['transition'], ensure_ascii=False))}，J {r['j_cut_s']} / L {r['l_cut_s']}）</h2>")
        o.append("<table><tr><th style='width:40%'>旧（现行 H3 正文）</th><th>新 v2（按段）</th></tr><tr><td>"
                 + e(body_of(s.get("h3_prompt"))) + "</td><td>")
        for no, zh, en, auto in r["segments"]:
            o.append(f"<div><span class='seg'>{no} {e(zh)}</span>{'（自动）' if auto else ''}：<span class='{'auto' if auto else ''}'>{e(en)}</span></div>")
        o.append(f"<div><span class='seg'>约束</span>：{e(SPEC['constraints_en'])}</div></td></tr>")
        o.append(f"<tr><td colspan=2><b>首帧提示（①–④，与视频同一份模板）</b>：{e(r['image'])}</td></tr></table>")
    o.append("</body></html>")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(o), encoding="utf-8")


if __name__ == "__main__":
    d = json.loads((ROOT / "data/import/script_v2.json").read_text(encoding="utf-8"))
    ep = next(x for x in d["episodes"] if x["number"] == 1)
    plans = {p["index"]: p for p in CP.plan_episode(ep)}
    rows = [(s, plans.get(int(s["index"])), compile_v2(s, plans.get(int(s["index"])))) for s in ep["shots"] if int(s["index"]) in (1, 3, 5)]
    out = ROOT / "data/review_pages/shot_spec_v2/index.html"
    page(rows, out)
    (out.parent / "samples.json").write_text(json.dumps([{"shot": f"ep01-S{s['index']}", "video": r["video"], "image": r["image"],
                                                         "scheme": r["scheme"], "segments": [list(x) for x in r["segments"]]}
                                                        for s, _, r in rows], ensure_ascii=False, indent=1), encoding="utf-8")
    for s, _, r in rows:
        print("==", s["index"], r["scheme"])
        print(r["video"][:2200])
        print()
