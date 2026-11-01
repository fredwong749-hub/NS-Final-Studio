"""内容缺陷猎捕（ITERAUDIT 2026-11-01，项目方 R11-11：“以上很多基础的bugs,rsi agent应该可以发现的……你生成一堆问题,然后一点点去debugs和check,
然后端更新规则到本地代码系统去”）。

把 R11-2…R11-10 这类“看片才发现”的内容缺陷，变成一张可重跑的缺陷类目表（CLASSES，≥40 类），每类一个检测器：
  auto    = 本地确定性检测（剧本字段 / 契约 postflight 记录 / score_clip 指标 / 合成 timeline / 像素统计）
  partial = 自动能抓一部分，剩下交本地 VLM 评分（VQA）
  vlm     = 只能看图看片判断 → 进 VQA 的 rubric 队列（data/qa/defect_hunt/vlm_queue.json），本工具不冒充“0 命中”
对象：现行 series10_v1（剧本 = data/staging_v3/merged 里每集最新一份；首帧 = data/renders/epNN/SN/takes.json 当前版；
视频 = data/pipeline/runs/series10_v1/video/scores/*.json；成片 = data/episodes/series10/*.timeline.json）。

    .venv/Scripts/python.exe tools/qa/defect_hunt.py              # 跑全部类，可断点续跑（已跑过的类跳过）
    .venv/Scripts/python.exe tools/qa/defect_hunt.py --force      # 全部重跑
    .venv/Scripts/python.exe tools/qa/defect_hunt.py --only DH-S01,DH-V07
    .venv/Scripts/python.exe tools/qa/defect_hunt.py --report     # 只按 state 重写 docs/rsi/DEFECT_HUNT.md
状态：data/qa/defect_hunt/state.json（每类：命中数、例子、跑的时间、输入指纹）；活文档：docs/rsi/DEFECT_HUNT.md（生成段落之外可手写）。
只读产物，不改剧本、不出图、不调 GPU / API。只查格式与可实现性 / 画面技术缺陷，不评价剧情。
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "packages" / "schema", ROOT / "services" / "agent"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from writer_lints import scan_fields  # noqa: E402

STATE = ROOT / "data" / "qa" / "defect_hunt" / "state.json"
VLMQ = ROOT / "data" / "qa" / "defect_hunt" / "vlm_queue.json"
DOC = ROOT / "docs" / "rsi" / "DEFECT_HUNT.md"
RUN = ROOT / "data" / "pipeline" / "runs" / "series10_v1"
MERGED = ROOT / "data" / "staging_v3" / "merged"
SIZE_RANK = {"大远景": 0, "远景": 1, "全景": 2, "全身": 3, "中景": 4, "中近景": 5, "近景": 6, "特写": 7, "大特写": 8}


# ------------------------------------------------------------------ 数据装载（缓存）
_cache: dict = {}


def script_eps() -> dict:
    """每集取 merged 目录里最新一份含该集的 series10_v1 稿（不含 .before_ 备份）"""
    if "eps" in _cache:
        return _cache["eps"]
    from ns_agent.importer.script_md import import_script
    files = sorted((p for p in MERGED.glob("*series10_v1*.md") if ".before_" not in p.name), key=os.path.getmtime, reverse=True)
    eps, src = {}, {}
    for f in files:
        try:
            imp = import_script(f)
        except Exception:  # noqa: BLE001
            continue
        fields = scan_fields(f.read_text(encoding="utf-8"))
        for ep in imp.episodes:
            if ep.number not in eps:
                eps[ep.number], src[ep.number] = ep, f.name
                for sh in ep.shots:
                    _cache.setdefault("fields", {})[sh.id] = fields.get((ep.number, sh.index), {})
        _cache.setdefault("globals", imp.globals)
        if len(eps) >= 10:
            break
    _cache["eps"], _cache["script_src"] = eps, src
    return eps


def shots():
    for n, ep in sorted(script_eps().items()):
        for sh in ep.shots:
            yield ep, sh


def ex(sh) -> dict:
    return {**{e.label.split("（")[0].strip(): e.text for e in (sh.extras or [])}, **(_cache.get("fields") or {}).get(sh.id, {})}


BEAT_SPLIT = re.compile(r"[；;](?=\s*\d+(?:\.\d+)?\s*(?:秒|s)?\s*[–\-~～至到]\s*\d)")
BEAT_HEAD = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(?:秒|s)?\s*[–\-~～至到]\s*(\d+(?:\.\d+)?)\s*(?:秒|s)?\s*[｜|]?")


def beats(sh) -> list[dict]:
    out = []
    for it in (x.strip() for x in BEAT_SPLIT.split(ex(sh).get("分拍", "")) if x.strip()):
        m = BEAT_HEAD.match(it)
        if not m:
            continue
        parts = [p.strip() for p in re.split(r"[｜|]", it[m.end():])]
        kv = {}
        for p in parts:
            if "=" in p or "＝" in p:
                k, v = re.split(r"[=＝]", p, 1)
                kv[k.strip()] = v.strip()
        kv["action"] = next((p for p in parts if p and "=" not in p and "＝" not in p), "")
        kv["t0"], kv["t1"] = float(m.group(1)), float(m.group(2))
        out.append(kv)
    return out


def on_screen(sh) -> list[str]:
    return [c.name for c in (sh.cast or []) if c.presence == "在画"]


def frames() -> list[dict]:
    """每镜当前首帧：{shot, file, postflight}"""
    if "frames" in _cache:
        return _cache["frames"]
    out = []
    for f in sorted(glob.glob(str(ROOT / "data/renders/ep[0-9]*/S*/takes.json"))):
        p = Path(f)
        ep, s = p.parent.parent.name, p.parent.name
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        n = (d.get("active") or {}).get("image")
        t = next((t for t in d.get("takes") or [] if t.get("stage") == "image" and str(t.get("n")) == str(n)), None)
        if not t:
            continue
        fp = ROOT / "data" / t["file"] if t.get("file") and not str(t["file"]).startswith("data/") else ROOT / str(t.get("file"))
        out.append({"shot": f"{ep}-{s}", "file": fp, "rel": t.get("file"), "pf": t.get("postflight") or {}})
    _cache["frames"] = out
    return out


def vscores() -> list[dict]:
    if "vs" in _cache:
        return _cache["vs"]
    out = []
    for f in sorted((RUN / "video" / "scores").glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out.append({"name": f.stem, "shot": f.stem.split("__")[0], **d})
    _cache["vs"] = out
    return out


def timelines() -> list[tuple[str, dict]]:
    out = []
    for f in sorted((ROOT / "data/episodes/series10").glob("*.timeline.json")):
        try:
            out.append((f.name, json.loads(f.read_text(encoding="utf-8"))))
        except (OSError, ValueError):
            pass
    return out


def pf_item(fr, qid):
    return next((i for i in (fr["pf"].get("items") or []) if i.get("id") == qid), None)


# ------------------------------------------------------------------ 检测器（返回 [(对象, 说明)]）
GAZE_CAM = re.compile(r"视线\s*[=＝]\s*(?:镜头|观众|正前方镜头)|看(?:向|着)?镜头|直视镜头|盯着镜头|对着镜头|"
                      r"(?:looks?|looking|stares?|staring|gazes?|gazing)\s+(?:directly\s+)?(?:at|into)\s+(?:the\s+)?(?:camera|lens|viewer)|"
                      r"eye contact with the (?:camera|viewer)|breaks? the fourth wall", re.I)
STATIC_START = re.compile(r"^(?:保持|定住|静止|凝固|不动|停住|看着|注视|凝视|盯着)")
STATIC_ACT = re.compile(r"^(?:保持|定住|静止|凝固|不动|停住|维持)")
MOVE = re.compile(r"抬|转|看向|望向|移|眨|呼吸|起伏|伸|握|捏|松开|走|迈|起身|坐下|站|落|推|拉|放|拿|递|接|笑|皱|咬|抿|靠|低头|抬头|"
                  r"侧头|摇头|点头|颤|抖|摸|抚|拨|撩|按|敲|翻|滑|俯|仰|回身|回头|侧身|倾|贴|退|挪|蹭|抱|吻|喘|垂|闭眼|睁眼|眯|扬|挑")
SUBTITLE_ASK = re.compile(r"字幕|标题字|caption|subtitle|on-screen text|text overlay|title card", re.I)
NEG_CTX = re.compile(r"无字幕|不加字幕|没有字幕|no subtitles?|without (?:subtitles?|text)|无文字|无水印")
HAIR_WORDS = re.compile(r"(黑发|黑色长发|棕发|金发|红发|白发|银发|短发|卷发|马尾|盘发|丸子头)")
SHOE_WORDS = re.compile(r"(高跟鞋|细高跟|高跟|平底鞋|运动鞋|皮鞋|短靴|长靴|靴子|凉鞋|拖鞋|乐福鞋|帆布鞋|赤脚|光脚|袜)")
SPEAK = re.compile(r"开口|张嘴|说话|低声说|轻声说|小声说|嘴唇(?:[^，。；]{0,4})(?:动|翕|开合)")


def d_gaze_camera():
    hits = []
    for ep, sh in shots():
        for fld, txt in (("分拍", ex(sh).get("分拍", "")), ("img", sh.img_prompt or ""), ("H3", sh.h3_prompt or ""),
                         ("motion", sh.motion_prompt or "")):
            m = GAZE_CAM.search(NEG_CTX.sub("", txt))
            if m:
                hits.append((sh.id, f"{fld}：…{m.group(0)}…"))
                break
    return hits


def d_opening_stare():
    """首拍（0 秒起）没写视线落点，或以“保持 / 定住 / 看着”开场：模型默认让演员先看镜头、停一下（R11-8）"""
    hits = []
    for ep, sh in shots():
        b = beats(sh)
        if not b or b[0]["t0"] != 0 or not on_screen(sh):
            continue
        gz = (b[0].get("视线") or "").strip()
        if gz in ("", "—", "-", "无"):
            hits.append((sh.id, f"首拍 0–{b[0]['t1']:g}s 没写视线落点：{b[0]['action'][:24]}"))
        elif STATIC_START.match(b[0]["action"]):
            hits.append((sh.id, f"首拍以静止开场：{b[0]['action'][:24]}"))
    return hits


def d_second_person_blank():
    hits = []
    for ep, sh in shots():
        on = on_screen(sh)
        if len(on) < 2:
            continue
        b = beats(sh)
        blank = [x for x in b if not x.get("反应") or x.get("反应") in ("—", "-", "无", "")]
        others = on[1:]
        named = any(o in "".join(x["action"] + x.get("反应", "") for x in b) for o in others)
        if b and (len(blank) == len(b) or not named):
            hits.append((sh.id, f"{len(on)} 人在画（{'、'.join(on)}），{len(blank)}/{len(b)} 拍反应=空"
                                f"{'，分拍里没写到 ' + '、'.join(others) if not named else ''}"))
    return hits


def d_static_beats():
    hits = []
    for ep, sh in shots():
        b = beats(sh)
        if b and (sh.duration or 0) >= 3 and not [x for x in b if x["action"] and not STATIC_ACT.match(x["action"]) and MOVE.search(x["action"])]:
            hits.append((sh.id, f"{len(b)} 拍都没有身体动作"))
    return hits


def d_slow_pacing():
    hits = []
    for n, ep in sorted(script_eps().items()):
        durs = [sh.duration or 0 for sh in ep.shots]
        if durs and sum(durs) / len(durs) > 7.5:
            hits.append((f"ep{n:02d}", f"平均镜长 {sum(durs) / len(durs):.1f}s（>7.5s）"))
        for sh in ep.shots:
            b = beats(sh)
            if (sh.duration or 0) >= 8 and len(b) <= 2:
                hits.append((sh.id, f"{sh.duration}s 只有 {len(b)} 拍"))
    return hits


def d_dialogue_density():
    hits = []
    for ep, sh in shots():
        chars = sum(len(re.sub(r"[\s，。！？、…—“”‘’：；,.!?]", "", d.text or "")) for d in sh.dialogue)
        if sh.voiceover and sh.voiceover.text:
            chars += len(re.sub(r"[\s，。！？、…—“”‘’：；,.!?]", "", sh.voiceover.text))
        if chars and sh.duration and chars / sh.duration > 5.0:
            hits.append((sh.id, f"{chars} 字 / {sh.duration}s = {chars / sh.duration:.1f} 字每秒（>5，说不完或被压缩）"))
        if not chars and sh.duration and sh.duration >= 7 and len(beats(sh)) <= 3:
            hits.append((sh.id, f"无台词 {sh.duration}s 只有 {len(beats(sh))} 拍（空镜时间长）"))
    return hits


def d_axis_flip():
    hits = []
    for n, ep in sorted(script_eps().items()):
        prev = None
        for sh in ep.shots:
            pos = {c.name: c.x for c in (sh.cast or []) if c.presence == "在画" and c.x}
            if prev and sh.link in ("接力", "同场换机位") and sh.scene_id == prev[0]:
                both = [k for k in pos if k in prev[1]]
                if len(both) >= 2:
                    a, b = both[:2]
                    order_now = (pos[a], pos[b])
                    order_prev = (prev[1][a], prev[1][b])
                    if "中" not in order_now + order_prev and order_now != order_prev and \
                            "HARD CUT" not in (sh.h3_prompt or "") and "越轴" not in json.dumps(ex(sh), ensure_ascii=False):
                        hits.append((sh.id, f"{a}/{b} 左右 {order_prev}→{order_now}（同场相邻镜，没标越轴）"))
            prev = (sh.scene_id, pos)
    return hits


def d_eyeline_missing():
    hits = []
    for ep, sh in shots():
        if not sh.dialogue:
            continue
        b = beats(sh)
        if b and not any(x.get("视线") and x["视线"] not in ("—", "-") for x in b):
            hits.append((sh.id, "对白镜分拍没写视线"))
    return hits


def _look_slots(ep, name, idx):
    out = {}
    for lk in sorted((x for x in ep.looks if x.character == name), key=lambda x: x.from_shot or 0):
        if (lk.from_shot or 0) <= idx:
            out.update(lk.slots or {})
    return out


def d_shoe_conflict():
    hits = []
    for ep, sh in shots():
        for name in on_screen(sh):
            shoe = _look_slots(ep, name, sh.index).get("鞋", "")
            img = sh.img_prompt or ""
            # 只看名字之后到下一个角色名前的片段
            seg = img.split(name, 1)[1] if name in img else ""
            for other in on_screen(sh):
                if other != name and other in seg:
                    seg = seg.split(other, 1)[0]
            w = set(SHOE_WORDS.findall(seg))
            if shoe and w and not any(x in shoe or shoe.find(x[:2]) >= 0 for x in w):
                hits.append((sh.id, f"{name} 造型鞋「{shoe}」，img 写「{'、'.join(sorted(w))}」"))
    return hits


def d_hair_conflict():
    hits = []
    locks = {c.name: c.description for c in getattr(_cache.get("globals"), "character_locks", [])} if script_eps() else {}
    for ep, sh in shots():
        for name in on_screen(sh):
            hair = _look_slots(ep, name, sh.index).get("发", "") + locks.get(name, "")
            seg = (sh.img_prompt or "").split(name, 1)[1][:80] if name in (sh.img_prompt or "") else ""
            w = set(HAIR_WORDS.findall(seg))
            bad = [x for x in w if x not in hair and not (x == "短发" and "短发" in hair)]
            if hair and bad:
                hits.append((sh.id, f"{name} 登记发型「{hair[:20]}…」，img 写「{'、'.join(bad)}」"))
    return hits


def d_outer_layer():
    hits = []
    outer = re.compile(r"西装外套|外套|风衣|大衣|夹克|开衫|披肩|西装(?!裙)")
    for ep, sh in shots():
        for name in on_screen(sh):
            cloth = _look_slots(ep, name, sh.index).get("服装", "")
            m = outer.search(cloth)
            if m and m.group(0) not in (sh.img_prompt or "") and "外套" not in (sh.img_prompt or ""):
                hits.append((sh.id, f"{name} 造型有「{m.group(0)}」，img 没写"))
    return hits


def d_lower_ambiguous():
    hits = []
    for n, ep in sorted(script_eps().items()):
        for lk in ep.looks:
            m = re.search(r"西装裙|套裙|职业裙", (lk.slots or {}).get("服装", ""))
            if m:
                hits.append((f"ep{n:02d}·{lk.character}", f"造型服装「{m.group(0)}」"))
    return hits


def d_partial_face():
    hits = []
    try:
        from ns_agent.asset_refs import face_described
    except Exception:  # noqa: BLE001
        return hits
    for ep, sh in shots():
        names = [c.name for c in (sh.cast or []) if c.presence in ("在画", "局部")]
        for c in sh.cast or []:
            if c.presence == "局部" and face_described(c.name, sh.img_prompt or "", names):
                hits.append((sh.id, f"{c.name} 标局部，img 写到脸 / 头发"))
    return hits


def d_vo_lips():
    hits = []
    for ep, sh in shots():
        if sh.voiceover and sh.voiceover.text and not sh.dialogue and sh.voiceover.speaker in on_screen(sh):
            t = ex(sh).get("分拍", "") + (sh.motion_prompt or "")
            if SPEAK.search(t):
                hits.append((sh.id, f"只有独白，{sh.voiceover.speaker} 在画，分拍写了「{SPEAK.search(t).group(0)}」"))
            if sh.h3_prompt and "voiceover" in sh.h3_prompt and not re.search(r"lips[^.]{0,40}closed", sh.h3_prompt):
                hits.append((sh.id, "H3 独白后没有 lips … closed"))
    return hits


def d_subtitle_ask():
    hits = []
    for ep, sh in shots():
        for fld, txt in (("img", sh.img_prompt or ""), ("H3", sh.h3_prompt or "")):
            t = NEG_CTX.sub("", txt)
            m = SUBTITLE_ASK.search(t)
            if m:
                hits.append((sh.id, f"{fld} 提到「{m.group(0)}」"))
    for name, tl in timelines():
        if tl.get("subtitles"):
            hits.append((name, "成片 timeline subtitles=true"))
    return hits


def d_beat_coverage():
    hits = []
    for ep, sh in shots():
        b = beats(sh)
        if b and sh.duration and (b[-1]["t1"] + 0.01 < sh.duration or b[-1]["t1"] > sh.duration + 0.01):
            hits.append((sh.id, f"分拍到 {b[-1]['t1']:g}s，镜长 {sh.duration}s"))
    return hits


def _bigrams(t: str) -> set:
    t = re.sub(r"[\s，。、；：！？“”‘’（）()｜|—…]|林晚|顾沉|陈宇|阿岚|她的|他的|她|他|的|在|着|了", "", t or "")
    return {t[i:i + 2] for i in range(len(t) - 1)}


def d_prop_carry():
    """接力“承：动作｜…”：延续的动作 / 物件要在下一镜 img 或首拍里出现（双字重合 <20% 算断）"""
    hits = []
    for n, ep in sorted(script_eps().items()):
        for sh in ep.shots[1:]:
            carry = sh.link_carry or ""
            if sh.link != "接力" or not carry.startswith("动作"):
                continue
            want = _bigrams(carry.split("｜", 1)[-1])
            b = beats(sh)
            have = _bigrams((sh.img_prompt or "") + (b[0]["action"] if b else ""))
            if want and len(want & have) / len(want) < 0.2:
                hits.append((sh.id, f"承：{carry[:30]}；img + 首拍只接上 {len(want & have)}/{len(want)}"))
    return hits


def d_scene_jump():
    hits = []
    for n, ep in sorted(script_eps().items()):
        prev = None
        for sh in ep.shots:
            if prev is not None and sh.link in ("接力", "同场换机位") and sh.scene_id != prev.scene_id:
                hits.append((sh.id, f"{sh.link} 但场景 {prev.scene_id}→{sh.scene_id}"))
            prev = sh
    return hits


def d_lighting_text():
    hits = []
    for n, ep in sorted(script_eps().items()):
        last = {}
        for sh in ep.shots:
            lt = ex(sh).get("光线", "")
            if sh.link in ("接力", "同场换机位") and sh.scene_id in last and lt and last[sh.scene_id] and \
                    (("暖" in lt) != ("暖" in last[sh.scene_id]) and ("冷" in lt) != ("冷" in last[sh.scene_id])):
                hits.append((sh.id, f"同场光线 {last[sh.scene_id][:14]} → {lt[:14]}"))
            if lt:
                last[sh.scene_id] = lt
    return hits


# ---- 首帧（契约 postflight 记录 + 像素）
def _pf_fail(qid, label):
    def f():
        out = []
        for fr in frames():
            it = pf_item(fr, qid)
            if it and it.get("status") == "fail":
                out.append((fr["shot"], f"{label}：{(it.get('detail') or '')[:60]}"))
        return out
    return f


def d_pf_untested():
    out = []
    for fr in frames():
        u = [i["id"] for i in fr["pf"].get("items") or [] if i.get("status") == "untested"]
        if u:
            out.append((fr["shot"], f"未测 {','.join(u)}"))
        if not fr["pf"]:
            out.append((fr["shot"], "当前首帧没有 postflight 记录"))
    return out


def d_low_res():
    from PIL import Image
    out = []
    for fr in frames():
        try:
            with Image.open(fr["file"]) as im:
                w, h = im.size
        except OSError:
            out.append((fr["shot"], f"文件打不开 {fr['rel']}"))
            continue
        if w < 768 or h < 1344:
            out.append((fr["shot"], f"{w}×{h}（<768×1344）"))
    for v in vscores():
        pass
    return out


def d_dup_frames():
    by = defaultdict(list)
    for fr in frames():
        try:
            by[hashlib.sha256(Path(fr["file"]).read_bytes()).hexdigest()[:16]].append(fr["shot"])
        except OSError:
            pass
    return [("、".join(v), f"不同镜头的当前首帧是同一个文件（sha {k}）") for k, v in by.items() if len(v) > 1]


def d_light_jump_px():
    import numpy as np
    from PIL import Image
    out = []
    eps = script_eps()
    sc = {sh.id: (sh.scene_id, sh.link) for _, sh in shots()}
    stats = {}
    for fr in frames():
        try:
            with Image.open(fr["file"]) as im:
                a = np.asarray(im.convert("L").resize((96, 168)), dtype=float)
            stats[fr["shot"]] = a.mean()
        except OSError:
            pass
    for n, ep in sorted(eps.items()):
        for a, b in zip(ep.shots, ep.shots[1:]):
            if b.link in ("接力", "同场换机位") and a.scene_id == b.scene_id and a.id in stats and b.id in stats:
                if abs(stats[a.id] - stats[b.id]) > 45:
                    out.append((b.id, f"同场相邻首帧平均亮度 {stats[a.id]:.0f}→{stats[b.id]:.0f}"))
    return out


# ---- 视频（score_clip 指标）
def _vs(pred, fmt):
    def f():
        return [(v["name"], fmt(v)) for v in vscores() if pred(v)]
    return f


def d_v_extra_hand():
    out = []
    for v in vscores():
        v6 = v.get("v6") or {}
        ppl = max(1, int(v6.get("people") or v6.get("poses_max") or 1))
        if (v6.get("hands_max") or 0) > 2 * ppl or (v6.get("extra_hand_frac") or 0) > 0:
            out.append((v["name"], f"手最多 {v6.get('hands_max')} 只 / {ppl} 人，extra_hand_frac {v6.get('extra_hand_frac')}"
                                   f"（V6 {v6.get('status')}）"))
    return out


def d_v_lowres():
    import cv2
    out = []
    for f in sorted((RUN / "video" / "episodes").glob("ep*/*.mp4")):
        cap = cv2.VideoCapture(str(f))
        w, h = cap.get(cv2.CAP_PROP_FRAME_WIDTH), cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
        cap.release()
        if w and (w < 720 or h < 1280):
            out.append((f.name, f"{int(w)}×{int(h)}"))
    for name, tl in timelines():
        sz = tl.get("size") or [0, 0]
        if sz and (sz[0] < 1080 or sz[1] < 1920):
            out.append((name, f"成片 {sz[0]}×{sz[1]}"))
        for k, dv in (tl.get("deliveries") or {}).items():
            if k == "4k" or "4k" in k.lower():
                break
        else:
            out.append((name, "没有 4K 交付档（R11-7：后期放大到 4K 写进 SOP）"))
    return out


# ---- 音频 / 合成（timeline）
def d_loudness():
    out = []
    for name, tl in timelines():
        m = ((tl.get("loudness") or {}).get("measured") or {})
        i, tp = m.get("integrated_lufs"), m.get("true_peak_dbtp")
        if i is not None and abs(i - (tl["loudness"].get("target_lufs") or -14)) > 1.0:
            out.append((name, f"响度 {i} LUFS（目标 ±1）"))
        if tp is not None and tp > -1.0:
            out.append((name, f"真峰值 {tp} dBTP（>-1）"))
    return out


def d_dead_air():
    out = []
    for name, tl in timelines():
        segs = sorted([(s.get("start_s") or s.get("t0") or 0, (s.get("start_s") or s.get("t0") or 0) + (s.get("dur_s") or s.get("duration_s") or 0))
                       for s in (tl.get("dialogue") or tl.get("speech") or []) if isinstance(s, dict)])
        last = 0.0
        for a, b in segs:
            if a - last > 6.0:
                out.append((name, f"{last:.1f}–{a:.1f}s 无人声 {a - last:.1f}s"))
            last = max(last, b)
    return out


def d_cut_placeholders():
    out = []
    for name, tl in timelines():
        for s in tl.get("shots") or []:
            if s.get("placeholder") or s.get("kind") == "still" or not s.get("file"):
                out.append((name, f"{s.get('shot')} 用占位 / 静帧（{s.get('kind')}）"))
        for w in tl.get("warnings") or []:
            out.append((name, f"warning：{str(w)[:60]}"))
    return out


def d_cut_missing_shots():
    out = []
    eps = script_eps()
    for name, tl in timelines():
        n = tl.get("episode")
        if n in eps:
            want = {sh.id for sh in eps[n].shots}
            have = {s.get("shot") for s in tl.get("shots") or []}
            miss = sorted(want - have)
            if miss:
                out.append((name, f"剧本有、成片没有：{'、'.join(miss)}"))
    return out


def _active_scan() -> dict:
    if "active_scan" not in _cache:
        import importlib.util as ilu
        spec = ilu.spec_from_file_location("ns_active_audit_dh", ROOT / "tools" / "qa" / "active_audit.py")
        m = ilu.module_from_spec(spec)
        spec.loader.exec_module(m)
        _cache["active_scan"] = m.scan()
    return _cache["active_scan"]


def d_active_ineligible():
    return [(f"{x['shot']}·{x['stage']}", f"当前 v{x['active']}：{x['why']}") for x in _active_scan()["ineligible_active"]]


def d_active_unaudited():
    return [(f"{x['shot']}·{x['stage']}", f"当前 {x['active']}，审计最后记到 {x['last_audit_to']}（{x['last_audit_at']}）")
            for x in _active_scan()["unaudited"]]


def vlm(_desc):
    def f():
        return None   # 交 VQA，不在这里算命中
    return f


# ---- 第 2 轮（RSI 11-01 下午，R11-11 续）：现行版本视角 / 未测≠缺陷 / 闸门空阈值 / 成片带缺陷 / 已有标签与看图结果接回来
def current_versions() -> set[str]:
    """现行视频版本（score 文件 stem）：各集 manifest 的 chosen 优先；没有 manifest 的镜取该镜最新的评分文件。
    首轮按“全部尝试”计数（含已淘汰 seed），数字偏大且不说明成片里有没有（DEFECT_HUNT §3 注）——K-REV-Q03。"""
    if "cur" in _cache:
        return _cache["cur"]
    cur, have = set(), set()
    for m in sorted((RUN / "video" / "episodes").glob("ep*/manifest.json")):
        try:
            d = json.loads(m.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for s in d.get("shots") or []:
            if s.get("shot") and s.get("chosen"):
                cur.add(f"{s['shot']}__{s['chosen']}")
                have.add(s["shot"])
    newest: dict = {}
    for f in (RUN / "video" / "scores").glob("*.json"):
        shot = f.stem.split("__")[0]
        if shot not in have and (shot not in newest or f.stat().st_mtime > newest[shot][0]):
            newest[shot] = (f.stat().st_mtime, f.stem)
    cur |= {v[1] for v in newest.values()}
    _cache["cur"] = cur
    return cur


def d_v_untested():
    """V6 / V7 = 未测：只算“没测到”，不算缺陷也不算通过（K-OPS-Q01；首轮 DH-V10 把 V7 未测记成了口型缺陷）"""
    out = []
    for v in vscores():
        u = [k.upper() for k in ("v6", "v7") if (v.get(k) or {}).get("status") == "未测"]
        if u:
            out.append((v["name"], f"{'/'.join(u)} 未测：{((v.get('v7') or {}).get('why') or (v.get('v6') or {}).get('why') or '')[:40]}"))
    return out


def d_v_null_threshold():
    """闸门阈值为空：该项每条都测了数，但阈值 None = 永远不拦（例：V6 bad_finger_frac th=null，首轮坏手指 33 条全放过）"""
    seen: dict = defaultdict(list)
    for v in vscores():
        v6 = v.get("v6") or {}
        for k, th in (v6.get("th") or {}).items():
            if th is None and v6.get(k) is not None:
                seen[k].append((v6.get(k), v["name"]))
    out = []
    for k, xs in sorted(seen.items()):
        bad = [x for x in xs if isinstance(x[0], (int, float)) and x[0] > 0.2]
        out.append((f"V6.{k}", f"阈值为空，{len(xs)} 条都测了、永不拦；其中 {len(bad)} 条 >0.2（例 {bad[0][1] if bad else xs[0][1]} = {(bad or xs)[0][0]}）"))
    return out


def _score_of(name: str) -> dict | None:
    return next((v for v in vscores() if v["name"] == name), None)


ORIGIN_RE = re.compile(r"VIDEO10\s+(ep\d+-S\d+)\s+(\S+)\s")


def d_x_shipped_defect():
    """成片里用的视频版本（timeline origin “VIDEO10 epNN-SN <版本> …”）按现在的评分仍有缺陷：闸门不过 / 多手 / 口型不过 / 分身（K-EDT-009、K-REV-Q01）"""
    out = []
    for name, tl in timelines():
        for s in tl.get("shots") or []:
            m = ORIGIN_RE.search(s.get("origin") or "")
            if not m:
                continue
            v = _score_of(f"{m.group(1)}__{m.group(2)}")
            if not v:
                out.append((name, f"{m.group(1)} 版本 {m.group(2)} 没有评分记录（未测）"))
                continue
            v6, why = v.get("v6") or {}, []
            if (v.get("gate") or {}).get("pass") is False:
                why.append("闸门不过：" + "、".join((v.get("gate") or {}).get("fails") or [])[:30])
            ppl = max(1, int(v6.get("people") or v6.get("poses_max") or 1))
            if (v6.get("hands_max") or 0) > 2 * ppl:
                why.append(f"手最多 {v6.get('hands_max')} 只 / {ppl} 人")
            if (v.get("v7") or {}).get("status") == "不通过":
                why.append("V7 口型不过")
            if (v6.get("dup_side_frac") or 0) > 0.1:
                why.append(f"分身 {v6.get('dup_side_frac')}")
            if why:
                out.append((name, f"{m.group(1)}（{m.group(2)}）进了成片：{'；'.join(why)}"))
    return out


GAZE_LABELS = ROOT / "data" / "acting" / "gaze_labels.json"


def _gaze_labels() -> dict:
    try:
        return json.loads(GAZE_LABELS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def d_f_gaze_labeled():
    """首帧看镜头（R11-2）：总调度在 acting_gaze_calib.html 标的“看镜头”。检测器（ns_qc.gaze）召回 0.42 不能用，人工标签先当真值接进来"""
    return [(k.split(":", 1)[1], "人工标注：看镜头") for k, v in sorted(_gaze_labels().items()) if k.startswith("img:") and v == "看镜头"]


def d_v_gaze_labeled():
    """视频开头看镜头 / 定格（R11-8）：同上，人工标签"""
    return [(k.split(":", 1)[1].removesuffix(".mp4"), f"人工标注：{v}") for k, v in sorted(_gaze_labels().items())
            if k.startswith("clip:") and ("看镜头" in v and "没看镜头" not in v or v == "开头定格")]


def d_shoe_not_in_img():
    """看得见脚的景别（全景 / 中全景 / 远景）鞋没写进 img（R11-4 鞋不一致的剧本侧根子；VQ-W1 原来没接进写作链路）"""
    import importlib.util as ilu
    spec = ilu.spec_from_file_location("ns_vqa_script_lint_dh", ROOT / "tools" / "vqa" / "script_lint.py")
    sl = ilu.module_from_spec(spec)
    spec.loader.exec_module(sl)
    out = []
    for ep, sh in shots():
        img = sh.img_prompt or ""
        for it in sl.check_shot(sh, ep, img, _size_of(img), level="warn"):
            out.append((sh.id, it["detail"]))
    return out


def _size_of(text: str) -> str | None:
    best = None
    for w in SIZE_RANK:
        i = (text or "").find(w)
        if i >= 0 and (best is None or i < best[0] or (i == best[0] and len(w) > len(best[1]))):
            best = (i, w)
    return best[1] if best else None


VQA_INDEX = ROOT / "data" / "vqa" / "index.json"


def vqa_bridge(*keys: str):
    """看图类：读 VQA 已有的本地看图结果（data/vqa/index.json → verdicts），只看现行首帧。
    返回 {"hits": [...], "tested": n, "total": N}；tested=0 时仍算“交 VQA”，不冒充 0 命中"""
    def f():
        try:
            idx = json.loads(VQA_INDEX.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            idx = {}
        hits, tested = [], 0
        frs = frames()
        for fr in frs:
            rel = str(fr["file"]).replace("\\", "/").split("NS-Final Studio/", 1)[-1]
            key = idx.get(rel)
            p = ROOT / "data" / "vqa" / "verdicts" / f"{key}.parsed.json" if key else None
            if not p or not p.exists():
                continue
            try:
                vd = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            tested += 1
            for k in keys:
                c = (vd.get("checks") or {}).get(k) or {}
                if c.get("s") in ("bad", "fail", "defect", "yes") or k in (vd.get("defects") or []):
                    hits.append((fr["shot"], f"VQA {k}：{(c.get('e') or '')[:50]}"))
        return {"hits": hits, "tested": tested, "total": len(frs)}
    return f


# ------------------------------------------------------------------ 类目表
# (id, 阶段, 名称, 样例 / 来源, 方式, 检测器, owner, 规则)
CLASSES = [
    ("DH-S01", "剧本", "演员看镜头（视线=镜头 / looks at the camera）", "R11-2 R11-8", "auto", d_gaze_camera, "ACTING→PROMPT", "新 QW-W5"),
    ("DH-S02", "剧本", "开场没给视线落点 / 以静止开场（模型默认先看镜头、停 1 秒）", "R11-8", "auto", d_opening_stare, "ACTING→PROMPT", "新 QW-W6"),
    ("DH-S03", "剧本", "多人镜第二人没有表情 / 视线 / 反应", "R11-9", "auto", d_second_person_blank, "ACTING→PROMPT", "K-WRT-I02 + 新 QW-W7"),
    ("DH-S04", "剧本", "整镜分拍没有身体动作（静止镜）", "ep01-S2", "auto", d_static_beats, "PROMPT", "K-WRT-Q03 QW-W2"),
    ("DH-S05", "剧本", "节奏慢：平均镜长 >7.5s / 长镜只有 ≤2 拍", "R11-2 R11-3", "auto", d_slow_pacing, "PROMPT", "K-EDT-I01"),
    ("DH-S06", "剧本", "台词密度：>5 字/秒说不完；无台词长镜拍数过少", "R11-3", "auto", d_dialogue_density, "PROMPT", "K-WRT-002"),
    ("DH-S07", "剧本", "180° 轴线：同场相邻镜两人左右互换且没标越轴", "—", "auto", d_axis_flip, "PROMPT", "K-WRT-104"),
    ("DH-S08", "剧本", "对白镜没写说话人视线（眼神线断）", "R11-6", "auto", d_eyeline_missing, "ACTING→PROMPT", "K-WRT-003"),
    ("DH-S09", "剧本", "鞋与本镜造型登记不一致", "R11-4", "auto", d_shoe_conflict, "PROMPT", "K-AST-252"),
    ("DH-S10", "剧本", "发型发色与登记不一致", "—", "auto", d_hair_conflict, "PROMPT", "HC-07"),
    ("DH-S11", "剧本", "外层衣物没写进 img", "V14", "auto", d_outer_layer, "PROMPT", "K-WRT-Q01 QW-W1"),
    ("DH-S12", "剧本", "下装泛称（西装裙 / 套裙）", "V14", "auto", d_lower_ambiguous, "PROMPT", "K-WRT-Q05 QW-W4"),
    ("DH-S13", "剧本", "局部角色写了脸 / 头发", "ep03-S6", "auto", d_partial_face, "PROMPT", "K-WRT-Q02 QW-CH6"),
    ("DH-S14", "剧本", "独白镜嘴在动 / H3 缺 lips closed", "—", "auto", d_vo_lips, "PROMPT", "K-WRT-Q04 QW-W3 H3-D5"),
    ("DH-S15", "剧本", "提示词 / 成片要了字幕或文字", "R11-8", "auto", d_subtitle_ask, "PROMPT + FIX", "新 QW-W8"),
    ("DH-S16", "剧本", "分拍时间没覆盖到镜长", "—", "auto", d_beat_coverage, "PROMPT", "SS-M2"),
    ("DH-S17", "剧本", "接力“承：动作”的物件 / 动作下一镜没接上", "—", "auto", d_prop_carry, "PROMPT", "K-WRT-R06"),
    ("DH-S18", "剧本", "接力 / 同场换机位却换了场景（空间地理断）", "—", "auto", d_scene_jump, "PROMPT", "QW-LK2"),
    ("DH-S19", "剧本", "同场相邻镜光线冷暖互换", "—", "auto", d_lighting_text, "PROMPT", "K-AST-252"),
    ("DH-F01", "首帧", "人物身份不像（Q1）", "R11-4", "auto", _pf_fail("Q1", "Q1 身份"), "REFLOCK / PRODUCER", "GEN_CONTRACT Q1"),
    ("DH-F02", "首帧", "造型 / 鞋不一致（Q2）", "R11-4", "auto", _pf_fail("Q2", "Q2 造型"), "REFLOCK / PRODUCER", "GEN_CONTRACT Q2"),
    ("DH-F03", "首帧", "景别不对（Q3）", "—", "auto", _pf_fail("Q3", "Q3 景别"), "REFLOCK / PRODUCER", "GEN_CONTRACT Q3"),
    ("DH-F04", "首帧", "塑料 / 糊 / 油光（Q4）", "—", "auto", _pf_fail("Q4", "Q4 质感"), "REFLOCK / PRODUCER", "GEN_CONTRACT Q4"),
    ("DH-F05", "首帧", "多手 / 多肢 / 多人（Q5）", "R11-4 R11-10", "auto", _pf_fail("Q5", "Q5 手肢"), "REFLOCK / PRODUCER", "GEN_CONTRACT Q5"),
    ("DH-F06", "首帧", "文字 / 水印 / 字幕（Q6）", "R11-8", "auto", _pf_fail("Q6", "Q6 文字"), "REFLOCK / PRODUCER", "GEN_CONTRACT Q6"),
    ("DH-F07", "首帧", "场景不对（Q7）", "—", "auto", _pf_fail("Q7", "Q7 场景"), "REFLOCK / PRODUCER", "GEN_CONTRACT Q7"),
    ("DH-F08", "首帧", "契约项未测 / 没有 postflight（未测冒充通过）", "—", "auto", d_pf_untested, "REFLOCK / PRODUCER", "K-OPS-Q01"),
    ("DH-F09", "首帧", "分辨率低于 768×1344", "R11-7", "auto", d_low_res, "PRODUCER", "新"),
    ("DH-F10", "首帧", "不同镜头当前首帧是同一张图", "S1–S4 事故", "auto", d_dup_frames, "DATAALIGN / PRODUCER", "新"),
    ("DH-F11", "首帧", "同场相邻首帧亮度跳变（光线连续）", "—", "auto", d_light_jump_px, "PRODUCER", "新"),
    ("DH-F12", "首帧", "演员看镜头", "R11-2 R11-8", "vlm", vqa_bridge("eye_contact"), "VQA", "VLM rubric（VQA eye_contact）"),
    ("DH-F13", "首帧", "第二人没有表情 / 眼神", "R11-9", "vlm", vqa_bridge("blank_expression"), "VQA", "VLM rubric（VQA blank_expression）"),
    ("DH-F14", "首帧", "跨镜鞋 / 饰品不一致（同造型）", "R11-4", "vlm", vqa_bridge("shoe_mismatch", "accessory_mismatch"), "VQA", "VLM rubric（VQA shoe / accessory）"),
    ("DH-F15", "首帧", "路人 / 背景人脸畸形", "—", "vlm", vqa_bridge("artifact", "face_artifact"), "VQA", "VLM rubric（VQA artifact）"),
    ("DH-F16", "首帧", "道具 / 场景陈设跨镜不一致", "—", "vlm", vqa_bridge("wrong_scene"), "VQA", "VLM rubric（VQA wrong_scene）"),
    ("DH-F17", "首帧", "剧本写的动作 / 姿势没画出来（图文不符）", "R11-10", "vlm", vlm("pose"), "VQA", "VLM rubric"),
    ("DH-V01", "视频", "动作不足 / 静止", "R11-2", "auto", _vs(lambda v: (v.get("mean") or 9) < 0.5 or (v.get("still") or 0) > 0.5,
                                                         lambda v: f"mean {v.get('mean')} still {v.get('still')}"), "VIDEO10", "K-REN-302"),
    ("DH-V02", "视频", "开头定格（head_s >0.5s，首帧盯镜头 1 秒）", "R11-8", "auto",
     _vs(lambda v: (v.get("head_s") or 0) > 0.5, lambda v: f"head_s {v.get('head_s')}"), "VIDEO10", "新"),
    ("DH-V03", "视频", "结尾定格（tail_s >0.5s）", "—", "auto", _vs(lambda v: (v.get("tail_s") or 0) > 0.5, lambda v: f"tail_s {v.get('tail_s')}"),
     "VIDEO10", "K-EDT-003"),
    ("DH-V04", "视频", "顿挫 / 抖动（J4 ≥1.2 且 z ≥3）", "—", "auto",
     _vs(lambda v: (v.get("J4") or 0) >= 1.2 and (v.get("J4_z") or 0) >= 3, lambda v: f"J4 {v.get('J4')} z {v.get('J4_z')}"), "VIDEO10", "K-REV-R06"),
    ("DH-V05", "视频", "镜内硬切 / 跳帧", "—", "auto", _vs(lambda v: bool(v.get("cuts")), lambda v: f"cuts {v.get('cuts')}"), "VIDEO10", "K-REV-R05"),
    ("DH-V06", "视频", "身份漂移（sface p10 <0.5）", "R11-4", "auto",
     _vs(lambda v: any((p.get("sface_p10") or 1) < 0.5 for p in (v.get("identity") or {}).values() if isinstance(p, dict)),
         lambda v: "；".join(f"{k} p10 {p.get('sface_p10')}" for k, p in (v.get("identity") or {}).items() if isinstance(p, dict))),
     "VIDEO10", "K-REN-301"),
    ("DH-V07", "视频", "多一只手（任何帧手数 >2×人数，闸门放过的也算）", "R11-4", "auto", d_v_extra_hand, "VIDEO10 + VQA", "新"),
    ("DH-V08", "视频", "重复人 / 分身（dup_side_frac >0.1）", "—", "auto",
     _vs(lambda v: ((v.get("v6") or {}).get("dup_side_frac") or 0) > 0.1, lambda v: f"dup_side_frac {(v.get('v6') or {}).get('dup_side_frac')}"),
     "VIDEO10", "V6"),
    ("DH-V09", "视频", "坏手指（bad_finger_frac >0.2）", "—", "auto",
     _vs(lambda v: ((v.get("v6") or {}).get("bad_finger_frac") or 0) > 0.2, lambda v: f"bad_finger_frac {(v.get('v6') or {}).get('bad_finger_frac')}"),
     "VIDEO10 + VQA", "V6"),
    ("DH-V10", "视频", "口型：对白不同步 / 独白嘴在动（V7 不过）", "—", "auto",
     _vs(lambda v: (v.get("v7") or {}).get("status") == "不通过", lambda v: f"V7 {(v.get('v7') or {}).get('status')} {(v.get('v7') or {}).get('why', '')[:40]}"),
     "VIDEO10", "V7"),
    ("DH-V11", "视频", "脸颊泛红 / 首帧色偏", "—", "auto",
     _vs(lambda v: (v.get("cheek_red_max") or 0) > 0.25 or (v.get("frame0_dE") or 0) > 8, lambda v: f"cheek_red {v.get('cheek_red_max')} dE0 {v.get('frame0_dE')}"),
     "VIDEO10", "K-REV-R0x"),
    ("DH-V12", "视频", "景别退档（实测 ≠ 要求）", "V1", "auto",
     _vs(lambda v: v.get("size_wanted") and v.get("size_measured") and abs(SIZE_RANK.get(v["size_wanted"], 0) - SIZE_RANK.get(v["size_measured"], 0)) > 1,
         lambda v: f"要 {v.get('size_wanted')} 实测 {v.get('size_measured')}"), "VIDEO10", "K-REV-301"),
    ("DH-V13", "视频", "发色漂移（hair dS/dV >25）", "—", "auto",
     _vs(lambda v: abs(v.get("hair_dS") or 0) > 25 or abs(v.get("hair_dV") or 0) > 25, lambda v: f"hair dS {v.get('hair_dS')} dV {v.get('hair_dV')}"),
     "VIDEO10", "新"),
    ("DH-V14", "视频", "分辨率低 / 没有 4K 交付档", "R11-7", "auto", d_v_lowres, "VIDEO10 + FIX", "新（SOP 4K 放大）"),
    ("DH-V15", "视频", "演员看镜头 / 开场盯镜头", "R11-2 R11-8", "vlm", vlm("gaze"), "VQA", "VLM rubric"),
    ("DH-V16", "视频", "鬼影 / 拖影 / 肢体穿模", "—", "vlm", vlm("ghost"), "VQA", "VLM rubric"),
    ("DH-V17", "视频", "第二人表情 / 视线空白", "R11-9", "vlm", vlm("second"), "VQA", "VLM rubric"),
    ("DH-V18", "视频", "表演与剧本动作不符", "R11-6", "vlm", vlm("acting"), "VQA + ACTING", "VLM rubric"),
    ("DH-A01", "声音", "响度偏离 -14 LUFS / 真峰值 >-1", "—", "auto", d_loudness, "FIX（剪辑）", "K-EDT-*"),
    ("DH-A02", "声音", "长时间无人声（>6s 死寂）", "R11-2", "auto", d_dead_air, "FIX（剪辑）", "新"),
    ("DH-A03", "声音", "配乐没给台词让路（避让）", "—", "vlm", vlm("duck"), "BGM10", "QW-M1"),
    ("DH-X01", "合成", "成片用了占位 / 静帧 / 有合成警告", "—", "auto", d_cut_placeholders, "FIX（剪辑）", "—"),
    ("DH-X02", "合成", "剧本里的镜头成片没有", "—", "auto", d_cut_missing_shots, "FIX（剪辑）", "—"),
    # 第 2 轮（RSI 11-01 下午）
    ("DH-S20", "剧本", "看得见脚的景别鞋没写进 img", "R11-4", "auto", d_shoe_not_in_img, "PROMPT（写作方）", "K-WRT-V06 VQ-W1"),
    ("DH-F18", "首帧", "演员看镜头（人工标签）", "R11-2", "auto", d_f_gaze_labeled, "ACTING / REFLOCK", "K-REN-G01 K-REV-G04"),
    ("DH-V19", "视频", "视频契约项未测（V6 / V7）", "—", "auto", d_v_untested, "VIDEO10", "K-REV-Q04"),
    ("DH-V20", "视频", "闸门阈值为空（测了但永不拦）", "R11-4", "auto", d_v_null_threshold, "VIDEO10", "K-REV-Q05"),
    ("DH-V21", "视频", "开头看镜头 / 定格（人工标签）", "R11-8", "auto", d_v_gaze_labeled, "ACTING / VIDEO10", "K-REN-G02 K-REV-G04"),
    ("DH-X03", "合成", "成片用的视频版本按现评分仍有缺陷", "R11-4", "auto", d_x_shipped_defect, "FIX + VIDEO10", "K-EDT-009 K-REV-Q01"),
    # 第 5 轮（RSI r5）：闸门被绕过
    ("DH-F19", "首帧", "当前版本指向被驳回 / 标不要 / 坏图的版本", "ep01-S5", "auto", d_active_ineligible, "PRODUCER + VQAGATE", "K-OPS-Q23"),
    ("DH-F20", "首帧", "当前版本和审计日志对不上（有路径绕过 set_active）", "ep01-S5", "auto", d_active_unaudited, "ITERAUDIT", "K-OPS-Q23"),
]


# ------------------------------------------------------------------ 运行 / 状态 / 文档
def _load_state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"classes": {}}


def _save_state(st: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    txt = json.dumps(st, ensure_ascii=False, indent=1)
    tmp.write_text(txt, encoding="utf-8")
    for i in range(5):              # Windows：state.json 被看板 / 杀毒短暂占用时 os.replace 报 WinError 5（11-01 实测），重试后退回直写
        try:
            os.replace(tmp, STATE)
            return
        except PermissionError:
            time.sleep(0.2 * (i + 1))
    STATE.write_text(txt, encoding="utf-8")
    try:
        tmp.unlink()
    except OSError:
        pass


def run(only: set[str] | None = None, force: bool = False) -> dict:
    st = _load_state()
    vq = []
    for cid, stage, name, src, how, fn, owner, rule in CLASSES:
        if only and cid not in only:
            continue
        rec = st["classes"].get(cid)
        if rec and not force and rec.get("status") in ("done", "vlm", "partial"):
            continue
        t0 = time.time()
        try:
            res = fn()
            if isinstance(res, dict):      # 看图类桥接：VQA 已判的部分算命中，没判的仍交 VQA
                if res["tested"]:
                    rec = {"status": "partial", "hits": len(res["hits"]), "examples": [f"{a}｜{b}" for a, b in res["hits"][:8]],
                           "note": f"VQA 已判现行首帧 {res['tested']}/{res['total']} 张"}
                else:
                    res = None
            if res is None:
                rec = {"status": "vlm", "hits": None, "examples": [], "note": "交 VQA 的本地 VLM rubric（data/qa/defect_hunt/vlm_queue.json）"}
                vq.append({"class": cid, "stage": stage, "name": name, "source": src})
            elif not isinstance(res, dict):
                rec = {"status": "done", "hits": len(res), "examples": [f"{a}｜{b}" for a, b in res[:8]]}
                if stage == "视频" and res and all("__" in str(a) for a, _ in res):    # K-REV-Q03：现行版本另计
                    cur = [x for x in res if x[0] in current_versions()]
                    rec["hits_current"] = len(cur)
                    rec["examples_current"] = [f"{a}｜{b}" for a, b in cur[:8]]
        except Exception as e:  # noqa: BLE001
            rec = {"status": "error", "hits": None, "examples": [], "note": f"{type(e).__name__}: {e}"[:200]}
        rec.update({"stage": stage, "name": name, "source": src, "how": how, "owner": owner, "rule": rule,
                    "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "secs": round(time.time() - t0, 2)})
        st["classes"][cid] = rec
        _save_state(st)                 # 每类一存：断了也能续跑
    st["script_src"] = _cache.get("script_src")
    st["counts"] = {"frames": len(_cache.get("frames") or []), "video_scores": len(_cache.get("vs") or []),
                    "video_current": len(current_versions()) if _cache.get("vs") is not None else None}
    _save_state(st)
    if vq:
        old = json.loads(VLMQ.read_text(encoding="utf-8")) if VLMQ.exists() else []
        have = {x["class"] for x in old}
        VLMQ.write_text(json.dumps(old + [x for x in vq if x["class"] not in have], ensure_ascii=False, indent=1), encoding="utf-8")
    return st


GEN_BEGIN, GEN_END = "<!-- defect_hunt:begin（tools/qa/defect_hunt.py 生成，勿手改本段） -->", "<!-- defect_hunt:end -->"


def write_doc(st: dict) -> None:
    rows = ["| 类 | 阶段 | 缺陷 | 样例 | 方式 | 命中（全部尝试 / 现行版） | 例子（视频优先列现行版） | owner | 规则 / 检查 |", "|---|---|---|---|---|---|---|---|---|"]
    for cid, stage, name, src, how, *_ in CLASSES:
        r = st["classes"].get(cid) or {}
        if r.get("status") in ("done", "partial"):
            hits = str(r.get("hits")) + (f" / {r['hits_current']}" if "hits_current" in r else "") + (f"（{r['note']}）" if r.get("status") == "partial" else "")
        else:
            hits = {"vlm": "交 VQA", "error": "出错", None: "未跑"}.get(r.get("status"), "未跑")
        exs = r.get("examples_current") or r.get("examples") or []
        ex1 = "<br>".join(x.replace("|", "／")[:90] for x in exs[:2]) or (r.get("note") or "")[:60]
        rows.append(f"| {cid} | {stage} | {name} | {src} | {how} | {hits} | {ex1} | {r.get('owner', '')} | {r.get('rule', '')} |")
    done = [c for c in st["classes"].values() if c.get("status") == "done"]
    hit_classes = [c for c in done if c.get("hits")]
    head = (f"更新：{time.strftime('%Y-%m-%d %H:%M')}；类目 {len(CLASSES)}；自动检测 {len(done)} 类，其中有命中 {len(hit_classes)} 类、"
            f"共 {sum(c['hits'] for c in hit_classes)} 处；交 VQA {sum(1 for c in st['classes'].values() if c.get('status') == 'vlm')} 类。"
            f"剧本来源：{json.dumps(st.get('script_src') or {}, ensure_ascii=False)[:300]}；首帧 {st.get('counts', {}).get('frames')} 镜；"
            f"视频评分 {st.get('counts', {}).get('video_scores')} 条（现行版 {st.get('counts', {}).get('video_current')} 条：manifest chosen，"
            f"无 manifest 的镜取最新评分）。")
    gen = "\n".join([GEN_BEGIN, "", head, "", *rows, "", GEN_END])
    DOC.parent.mkdir(parents=True, exist_ok=True)
    old = DOC.read_text(encoding="utf-8") if DOC.exists() else ""
    if GEN_BEGIN in old and GEN_END in old:
        new = old.split(GEN_BEGIN)[0] + gen + old.split(GEN_END, 1)[1]
    else:
        new = (old.rstrip() + "\n\n" if old else "# 内容缺陷猎捕（DEFECT_HUNT）\n\n") + "## 首轮结果（自动生成）\n\n" + gen + "\n"
    DOC.write_text(new, encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    st = _load_state() if a.report else run(set(a.only.split(",")) if a.only else None, a.force)
    write_doc(st)
    for cid, *_ in CLASSES:
        r = st["classes"].get(cid) or {}
        print(cid, r.get("status"), r.get("hits"), (r.get("examples") or [""])[0][:80] if r.get("examples") else r.get("note", ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
