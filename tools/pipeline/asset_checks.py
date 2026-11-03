"""通用看图检查（阶段 A 资产候选用；CAST-S 卡点 ISS-1103-001014-aace / -c5f6 / -176b，AUTOPIPE-A 11-03）。

只进本地看图模型（ns_agent.vqa.client，K-REV-V01：图不出自有机器）。三个检查合并成一次提问（看图队列只有一条，少排队）：
  bundle_check(image, items, want_person)  逐条核对 + 年龄观感 + OCR 一次问完 → {status, items[], age, ocr, text}
  age_check(image) / ocr_check(image)      单独问（CLI 排查用）
  q9_asset(post, stage)                    设定候选的 Q9 口径：face / sheet 是证件式正脸胸像 / 全身设定图，“看镜头”（eye_contact）不判；
                                           item 是白底物件图，只问人 / 镜头的项（ITEM_NA_DEFECTS）不判、改由物件契约兜，
                                           其余缺陷按 config/vqa.json 的 blocking 原样判；未成年外观（underage_look）任何时候都不过（HC-07）
    python tools/pipeline/asset_checks.py age <图>
    python tools/pipeline/asset_checks.py ocr <图>
    python tools/pipeline/asset_checks.py bundle <图> --item "画面里只有一个人" --item "没有裸露"
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in ("services/agent", "packages/qc", "tools/vqa"):
    if str(ROOT / _p) not in sys.path:
        sys.path.insert(0, str(ROOT / _p))

SYSTEM = "你是严谨的看图核对员，只描述看到的，用中文。"
HEAD = "逐条核对这张图，每条答“符合 / 不符合 + 一句理由”，按编号一行一条。\n"
AGE_LINE = "最后再答三行：\n年龄：画面里的人看起来是“成年”还是“像未成年”（没有人就答“无人物”），加一句理由。\n"
OCR_LINE = "文字：逐字读出图里所有可见的文字、字母、数字、logo 或品牌标志；没有就只答“无”。\n"
SUM_LINE = "总结：全部符合 / 有不符合。"
NUM_RE = re.compile(r"^\s*(\d+)\s*[.、．)）:：]\s*(.*)$")


def _ask(text: str, image: str, label: str, px: int = 1400000) -> dict:
    from ns_agent.vqa import client as C
    return C.generate({"system": SYSTEM, "text": text, "images": [{"path": str(image), "max_pixels": px}]}, wait_s=600, label=label)


def _status(ok: bool, r: dict) -> str:
    return "pass" if ok else ("untested" if r.get("error") else "fail")


def age_check(image: str) -> dict:
    """年龄观感：整段回答（判词行 + 理由行）一起过 _age_status（W6b：理由里写了未成年 / 约 16 岁也要 fail）；没答出来 = untested（不算过）"""
    r = _ask("这张图里的人看起来是成年人还是未成年人？只回答第一行：“成年”或“像未成年”或“无人物”，第二行一句理由。", image, "asset_age", 1000000)
    t = (r.get("text") or "").strip()
    st = _age_status(t)
    return {"status": "untested" if r.get("error") and st != "pass" else st, "text": t, "error": r.get("error")}


def ocr_check(image: str) -> dict:
    """OCR（本地看图读字）：读到任何文字 / logo = 不过"""
    r = _ask("逐字读出这张图里所有可见的文字、字母、数字、logo 或品牌标志。没有就只回答“无”。", image, "asset_ocr")
    t = (r.get("text") or "").strip()
    return {"status": _status(_ocr_clean(t), r), "text": t, "error": r.get("error")}


def _ocr_clean(t: str) -> bool:
    t = t.strip().strip("。.")
    return bool(t) and t.startswith("无") and len(t) <= 12


# 年龄判词器（W6b 11-03，A6 审计 P1-A：失败关闭）。只有“全句无未成年 / 否定 / 不确定线索，且明确出现‘成年’”才 pass。
# ① 先抹掉“否定未成年”的安全说法（“无未成年视觉元素”“不像未成年”“没有稚气”），只抹这些固定说法；
# ② 剩下的文字里还有任何未成年线索 → fail（多人句“她是成年人；旁边的孩子未成年”一律 fail）；
# ③ 否定成年（不是 / 不像 / 非 / 并非 / 未必 … 成年）→ fail；④ 不确定（可能 / 也许 / 不确定 / ？…）→ fail；⑤ 写了 18 岁以下 → fail；
# ⑥ 只说“无人物”= na；⑦ 以上都没有且出现“成年”= pass；没判词 = fail；空 = untested。
_AGE_MINOR = r"未成年|少女|少年|孩子|儿童|小孩|幼|童|稚|学生|校服|萝莉|初中|高中|中学"
AGE_SAFE_NEG_RE = re.compile(r"(?:无|没有|没|不像|不是|并非|非|不存在|未见|看不出|毫无|不具备?|不带)(?:任何|明显的?|一丝)?(?:" + _AGE_MINOR + r")")
AGE_MINOR_RE = re.compile(_AGE_MINOR + r"|不像成年|不是成年")
AGE_MINOR_EN_RE = re.compile(r"(?<![a-z])(?:minor|teen|child|kid|underage|loli|juvenile|young\s*girl)", re.I)   # 英文线索按字母边界（不吃 eighteen）
AGE_NEG_ADULT_RE = re.compile(r"(?:不|非|没有?|未必|并非|算不上|称不上)[^，。,.;；、！!\s]{0,3}?成年")
# W6c+（A6b P2）：补“不能确定是否成年”“成年，但未必”这类——不能 / 没法 / 是否 / 未必 / 不一定 / 说不清 / 不好判断 都算不确定
AGE_UNSURE_RE = re.compile(r"可能|也许|或许|大概|不确定|无法|难以确定|难以判断|不能确定|不能判断|不好判断|没法|是否|未必|不一定|"
                           r"说不清|不好说|说不准|疑似|[?？]")
AGE_NUM_RE = re.compile(r"(\d+)\s*(?:周岁|岁)")                                       # 中文“十X岁”并进 AGE_CN_NUM_RE（“二十几岁”不再被当成“十几岁”）
AGE_CN_NUM_RE = re.compile(r"([零〇一二两三四五六七八九十几]+)\s*(?:周岁|岁)")     # 中文年龄（含“八岁”“七八岁”“十七八岁”“二十几岁”）
_CN_DIGIT = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "几": 0}


def _cn_age_min(tok: str) -> int:
    """中文年龄 → 最小可能值（失败关闭：“七八岁”= 7、“十七八岁”= 17、“十几岁”= 10、“二十几岁”= 20）"""
    if "十" in tok:
        a, _, b = tok.partition("十")
        tens = min((_CN_DIGIT.get(c, 0) for c in a), default=1) or (1 if not a else 0)
        units = min((_CN_DIGIT.get(c, 0) for c in b), default=0)
        return tens * 10 + units
    return min((_CN_DIGIT.get(c, 0) for c in tok), default=0)


def _age_under18(rest: str) -> bool:
    if any(int(m.group(1)) < 18 for m in AGE_NUM_RE.finditer(rest)):
        return True
    return any(_cn_age_min(m.group(1)) < 18 for m in AGE_CN_NUM_RE.finditer(rest))


def _minor_cues(t: str) -> bool:
    """未成年线索（不含“不确定”类措辞）：抹掉安全否定后仍有未成年词 / 英文线索 / 18 岁以下 → True。
    bundle 整段回答用它（逐条核对行里写“可能”“？”不该连坐年龄；但任何一行说了未成年 / 16 岁都要拦）"""
    s = re.sub(r"\s+", "", t or "").replace("非常", "很")
    rest = AGE_SAFE_NEG_RE.sub("〇", s)
    return bool(AGE_MINOR_EN_RE.search(t or "") or AGE_MINOR_RE.search(rest) or _age_under18(rest))


def _age_status(t: str) -> str:
    """年龄观感判词（C-22 / HC-07 红线）：失败关闭，见上方规则 ①–⑦。
    W6 修过的“成年不在句首也算”（“画面里的人看起来是“成年”，…”）保留；“成年，…无未成年视觉元素”的安全否定保留 pass。"""
    t = (t or "").strip()
    if not t:
        return "untested"
    s = re.sub(r"\s+", "", t).replace("非常", "很")
    rest = AGE_SAFE_NEG_RE.sub("〇", s)
    if AGE_MINOR_EN_RE.search(t) or AGE_MINOR_RE.search(rest) or AGE_NEG_ADULT_RE.search(rest) or AGE_UNSURE_RE.search(rest):
        return "fail"
    if _age_under18(rest):
        return "fail"
    if "无人物" in rest:
        return "na" if "成年" not in rest else "fail"
    return "pass" if "成年" in rest else "fail"


def parse_bundle(text: str, n_items: int) -> dict:
    """看图回答 → {items: [{n, ok, text}], age: {status, text}, ocr: {status, text}, summary}"""
    items: dict[int, dict] = {}
    age = ocr = summary = ""
    extra: list[str] = []                 # W6c+（A6b P2）：不是编号 / 文字 / 总结的行（年龄行的续行“理由：约 16 岁…”、散落的说明）
    for ln in (text or "").splitlines():
        s = ln.strip()
        if not s:
            continue
        m = NUM_RE.match(s)
        if m and int(m.group(1)) <= n_items:
            body = m.group(2).strip()
            items[int(m.group(1))] = {"n": int(m.group(1)), "ok": body.startswith("符合"), "text": body}
            continue
        if s.startswith("年龄"):
            age = re.sub(r"^年龄\s*[:：]\s*", "", s)
        elif s.startswith("文字"):
            ocr = re.sub(r"^文字\s*[:：]\s*", "", s)
        elif s.startswith("总结"):
            summary = re.sub(r"^总结\s*[:：]\s*", "", s)
        else:
            extra.append(s)
    rows = [items.get(i) or {"n": i, "ok": False, "text": "（没答）"} for i in range(1, n_items + 1)]
    # 年龄按整段回答判（与 age_check 同口径）：判词 = “年龄：”行 + 所有自由行，走完整判词器；
    # 另外整段（含逐条核对行）只要出现未成年线索 / 18 岁以下 → fail（核对行里的“可能”“？”不连坐年龄）
    age_text = "\n".join([age] + extra).strip() if age else ""
    st = _age_status(age_text)
    if st in ("pass", "na") and _minor_cues(text or ""):
        st = "fail"
    return {"items": rows, "age": {"status": st, "text": age_text},
            "ocr": {"status": ("pass" if _ocr_clean(ocr) else ("fail" if ocr else "untested")), "text": ocr}, "summary": summary}


def bundle_check(image: str, items: list[str], want_person: bool = True) -> dict:
    """逐条核对 + 年龄 + OCR 一次问完。status：全部条目“符合”且总结没写“有不符合”= pass；回答缺项 = untested；否则 fail。
    age / ocr 各自带 status（不想判年龄的空镜：want_person=False → age 不计）"""
    q = HEAD + "\n".join(f"{i}. {t}" for i, t in enumerate(items, 1)) + "\n" + AGE_LINE + OCR_LINE + SUM_LINE
    r = _ask(q, image, "asset_bundle")
    t = r.get("text") or ""
    p = parse_bundle(t, len(items))
    if r.get("error") or not t.strip():
        st = "untested"
    elif all(x["ok"] for x in p["items"]) and "有不符合" not in p["summary"]:
        st = "pass"
    else:
        st = "fail"
    if not want_person:
        p["age"] = {"status": "na", "text": "空镜 / 物件，不判年龄"}
    elif p["age"]["status"] == "untested" and not r.get("error"):
        p["age"]["status"] = "untested"
    return {"status": st, "text": t, "error": r.get("error"), **p}


# ------------------------------------------------------------------ 设定候选的 Q9 口径
GAZE_FREE_STAGES = ("face", "sheet")     # 证件式正脸胸像 / 全身设定图：看镜头不判（ISS-1103-001014-176b，总调度 11-03 定）
# W9（11-03）：item = 白底物件图，没有演员、没有镜头构图、没有上一镜。Q9 里只问人 / 镜头的项对它无从判起（问“演员看不看镜头”
# 对一只鞋必然乱答，10 条 item 作业 q9=fail 多半是 eye_contact / framing_mismatch）。这些项改由物件契约兜：
# 看图逐条“没有人、没有人体部位、没有人脸”+“只有这一样东西”+ 颜色材质 + 纯白底无标志，再加 OCR。不放宽：
# brand_logo / underage_look 等与物件图相关的 blocking 项照旧拦，阈值与 blocking 表（config/vqa.json）不改。
# extra_person（“人数与镜头不符”）也不判：物件契约第 1 条“画面里没有人、没有任何人体部位”更严（有一个人就不过），
# 而 Q9 拿空人数的单品镜比人数会乱报（11-03 04:59 江予白相机皮带 seed1100：画面零人、Q9 报 extra_person）。
ITEM_NA_DEFECTS = ("eye_contact", "hair_mismatch", "framing_mismatch", "continuity_break", "extra_person")
IGNORE_DEFECTS = {"face": ("eye_contact",), "sheet": ("eye_contact",), "scene": (), "item": ITEM_NA_DEFECTS}


def defect_zh(code: str) -> str:
    """缺陷代码 → 人话（config/vqa.json checks[code].zh，取括号前那段）"""
    try:
        from ns_agent.vqa import contract as VC
        zh = str((VC._all_checks().get(code) or {}).get("zh") or "")
    except Exception:  # noqa: BLE001  # arch-ok: 读不到词表就原样给代码
        zh = ""
    zh = re.split(r"[（(]", zh)[0].strip()
    return f"{zh}（{code}）" if zh else code


def _zh_list(codes) -> str:
    return "、".join(defect_zh(c) for c in codes)


def q9_asset(post: dict, stage: str) -> dict:
    """把 postflight 里的 Q9 按设定候选口径重判：去掉该阶段不判的缺陷，其余 blocking 按 config/vqa.json；underage_look 永远拦。
    没有 Q9 结果（untested / 没跑）照旧不算过。返回新的 post（items 里 Q9 被替换，evidence 记 asset_stage 与去掉的项）"""
    from ns_agent.vqa import contract as VC
    items = list((post or {}).get("items") or [])
    q9 = next((i for i in items if i.get("id") == "Q9"), None)
    if not q9:
        return post
    ev = dict(q9.get("evidence") or {})
    defects = list(ev.get("defects") or [])
    ignored = [d for d in defects if d in IGNORE_DEFECTS.get(stage, ())]
    keep = [d for d in defects if d not in ignored]
    checks = VC._all_checks()
    blocking = [d for d in keep if (checks.get(d) or {}).get("blocking") and (VC.enforced() or d == "underage_look")]
    record = [d for d in keep if d not in blocking]
    st = q9.get("status")
    contra = list(ev.get("contradiction") or [])
    if st == "untested" and contra and ev.get("model") and all(d in IGNORE_DEFECTS.get(stage, ()) for d in contra):
        # AUTOFIX-O 11-03：看图模型有结论，只是在“本阶段不判”的项（sheet / face 的看镜头）上结论与证据矛盾 → 那一项本来就不判，
        # 按其余缺陷重判（01:49 sheet 候选全因 eye_contact 矛盾 untested）；其它项矛盾照旧 untested
        ignored = sorted(set(ignored) | set(contra))
        st = "fail" if defects else "pass"
    if st in ("untested", None) or (st == "fail" and not defects):   # 没结果 / 失败关闭的原判原样保留
        new = dict(q9)
    elif blocking:
        new = {**q9, "status": "fail", "detail": "设定候选口径：" + _zh_list(blocking) + ("；只记录：" + "、".join(record) if record else "")}
    elif record:
        new = {**q9, "status": "na", "detail": "设定候选口径：只记录（不阻断）：" + "、".join(record)}
    else:
        new = {**q9, "status": "pass", "detail": "设定候选口径：本地看图模型未报需拦的缺陷" + (f"（不判：{'、'.join(ignored)}）" if ignored else "")}
    new["evidence"] = {**ev, "asset_stage": stage, "ignored_defects": ignored, "original_status": st}
    new["title"] = str(q9.get("title") or "本地看图复核") + "（设定候选口径）"
    out = dict(post or {})
    out["items"] = [i for i in items if i.get("id") != "Q9"] + [new]
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["age", "ocr", "bundle"])
    ap.add_argument("image")
    ap.add_argument("--item", action="append", default=[])
    ap.add_argument("--no-person", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "age":
        r = age_check(a.image)
    elif a.cmd == "ocr":
        r = ocr_check(a.image)
    else:
        r = bundle_check(a.image, a.item or ["画面干净、没有畸形"], not a.no_person)
    print(json.dumps(r, ensure_ascii=False, indent=1))
    return 0 if r.get("status") in ("pass", "na") else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
