"""L-196（项目方 11-05：“我需要你全自动，不要检测那么多了”）：首 / 尾帧闸门只留硬项。

config/gen_contract.json "blocking_items"（缺键 / 非列表 = 不启用本策略，保持旧口径）：
  Q1     身份（Q1 项；Q10 identity、QB identity 同源）
  count  人数（Q10 count、QB count、Q9 extra_person）
  text   文字 / 水印 / 字幕（Q6、QB ocr、Q9 text_watermark / brand_logo）
  adult  成人安全（Q9 underage_look、QB age）
  gaze   视线 / 排排站（L-200 项目方 11-06 看 ep01 总览：画中任何人看镜头、或多人正面并排站成一排合影式 = 不过、换种子重出）：
         Q9 看图 eye_contact / lineup 缺陷 + G1（YuNet 头部朝向）疑似看镜头。两者都有结论时以看图为准：看图真看过
         （evidence.model）且没报视线缺陷 → G1 只记录（YuNet 误报多）；看图没结果 → G1 自己挡。
  也可直接写项 id（如 "Q3"），该项整项照旧挡。
不在名单里的项（Q1a/Q1x/Q2–Q5/Q7/Q8/G1/Q9 其余缺陷/Q10 其余/QB 其余）照常跑、照常记，但 status 改成 na（原判留
status_recorded + record_only=true），不进 blocking。apply() 原地改 pf 并返回；ok / blocking / score_infra 重算。"""
from __future__ import annotations

from . import cfg

BAD = ("fail", "untested")
GAZE_DEFECTS = {"eye_contact", "lineup"}       # L-200：看图里算“视线 / 排排站”的缺陷 id（config/vqa.json checks）
Q9_HARD = {"count": {"extra_person"}, "text": {"text_watermark", "brand_logo"}, "adult": {"underage_look"}, "gaze": GAZE_DEFECTS}
QB_HARD = {"Q1": ("identity",), "count": ("count",), "text": ("ocr",), "adult": ("age",)}
Q10_HARD = {"Q1": ("identity",), "count": ("count",)}


def hard_set(conf: dict | None = None) -> set | None:
    v = (conf if conf is not None else cfg()).get("blocking_items")
    return set(map(str, v)) if isinstance(v, list) else None


def _lab_bad(lab: dict, key: str) -> bool:
    v = lab.get(key)
    st = v.get("status") if isinstance(v, dict) else v
    return st in BAD


def _q10_prompt_people_bad(ev: dict) -> bool:
    """Q10 evidence.prompt 判 fail 且原因是人数（people_count）→ 算人数硬项"""
    p = ev.get("prompt")
    if not isinstance(p, dict) or p.get("status") != "fail":
        return False
    return "people_count" in str(p.get("why") or "")


def vqa_gaze_verdict(pf: dict) -> bool | None:
    """L-200：看图（Q9）对视线 / 排排站的结论。True = 看图真看过（evidence.model）且没报 eye_contact / lineup；
    False = 报了；None = 没有看图结论（没跑 / 排队超时 / 出错）"""
    q9 = next((i for i in (pf or {}).get("items") or [] if i.get("id") == "Q9"), None)
    ev = (q9 or {}).get("evidence") or {}
    if not ev.get("model"):
        return None
    return not (set(ev.get("defects") or []) & GAZE_DEFECTS)


def _is_hard(it: dict, hard: set, vqa_gaze: bool | None = None) -> bool:
    iid, ev = it.get("id"), it.get("evidence") or {}
    if iid in hard:
        return True
    if iid == "G1":
        # L-200：gaze 硬项时 YuNet 的 G1 挡，但看图真看过且没报视线缺陷 → 以看图为准（G1 只记录，防 YuNet 误报）
        return "gaze" in hard and vqa_gaze is not True
    if iid == "Q6":
        return "text" in hard
    if iid == "Q9":
        defects = set(ev.get("defects") or [])
        if any(defects & Q9_HARD[k] for k in Q9_HARD if k in hard):
            return True
        return False
    if iid == "Q10":
        if any(_lab_bad(ev, k) for h, ks in Q10_HARD.items() if h in hard for k in ks):
            return True
        # REVIEW-B 11-05：L-191 的“看图人数闸”（tools/vqa/accept.prompt_check：visible_people vs cast → people_count 不符）落在 Q10 的
        # prompt 子项，不在 count（检测器，gpu33 上常 deferred）。count 是硬项时它判出的“多画了人 / 少人”同样要挡，否则 35 步多画人直接放行
        return "count" in hard and _q10_prompt_people_bad(ev)

    if iid == "QB":
        lab = ev.get("label") or {}
        return any(_lab_bad(lab, k) for h, ks in QB_HARD.items() if h in hard for k in ks)
    return False


def apply(pf: dict, conf: dict | None = None) -> dict:
    hard = hard_set(conf)
    if hard is None or not isinstance(pf, dict) or not pf.get("items"):
        return pf
    kept, recorded = [], []
    vqa_gaze = vqa_gaze_verdict(pf) if "gaze" in hard else None
    for it in pf["items"]:
        if it.get("status") in BAD and it.get("blocking", True) is not False and not _is_hard(it, hard, vqa_gaze):
            it["status_recorded"] = it["status"]
            it["record_only"] = True
            it["detail"] = "只记录（L-196 全自动闸门，不挡）：" + str(it.get("detail") or "")
            it["status"] = "na"
            recorded.append(it.get("id"))
        elif it.get("status") in BAD and it.get("blocking", True) is not False:
            kept.append(it.get("id"))
    if not recorded:
        return pf
    pf["blocking"] = sorted(set(kept))
    pf["record_only_items"] = recorded
    pf["reasons"] = [r for r in pf.get("reasons") or [] if not any(str(r).startswith(str(x)) for x in recorded)]
    if pf.get("ok") is not None or kept or recorded:
        pf["ok"] = not kept and not (pf.get("error") or pf.get("remote_error"))
    if not any(i.get("status") == "untested" for i in pf["items"]):
        pf.pop("score_infra", None)
        pf.pop("accept_retry", None)
    return pf
