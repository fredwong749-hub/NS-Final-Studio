"""镜头状态标签（UIRSI r40；项目方 11-02 00:1x：“在 UI 里面做一个错误标志吧.比如哪些是重置的,过期的,就给它用不同的颜色 label 一下,
这样我在全剧总览的时候,就能看到细节”）。

只读汇总后端已有的真实数据，不在前端猜：
  · data/producer/registry.json 每镜 first / last / video 对象：status（passed / ready / running / pending / best_effort）、
    redo + master_reject（L-088 全量重做、总调度 / 看图闸门驳回）、stale（剧本 / 输入改了）、last_error（契约没过的原因）；
  · /api/candidates（takes_ui.candidates）：每版 script（current / old）、契约结论；
  · 现行剧本版本的最新一版 take：params.vqa_rounds[-1].judge（看图判定 pass / fail / 未测，failed_checks）、postflight Q9 未测。
每镜给 tags（全部）和 main（最严重的一个）；kind 固定为下面 KINDS 的键，前端按 kind 上色、写图例。文案全是大白话。
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
REGISTRY = ROOT / "data" / "producer" / "registry.json"
# 严重程度从高到低（main = 第一个命中的）
KINDS = {
    "vqa_fail": "看图没过",
    "old": "旧剧本版本",
    "redo": "已重置 / 驳回待重出",
    "stale": "过期",
    "judge": "待补判",
    "best": "尽力版",
    "busy": "出图中",
    "queued": "排队中",
    "ok": "通过 / 已设为当前",
}
ORDER = list(KINDS)
STAGE_WORD = {"first": "首帧", "last": "尾帧", "video": "视频", "image": "首帧"}
# 看图 / 契约检查项 → 大白话（项目方点名的几类）
CHECK_WORD = {"Q1": "身份脸不像 / 缺身份脸", "Q2": "造型不对（缺外套 / 鞋 / 饰品）", "Q3": "景别不对", "Q4": "质感问题",
              "Q5": "多肢 / 坏手", "Q6": "画面里有文字", "Q7": "跨镜不连贯", "Q8": "发色不对", "Q9": "看图检查",
              "gaze": "看镜头", "gaze_camera": "看镜头", "looking_at_camera": "看镜头", "outer": "缺外套", "missing_outer": "缺外套",
              "outerwear_missing": "缺外套", "hair": "发色", "hair_color": "发色", "identity": "缺身份脸", "identity_mismatch": "身份脸不像",
              "continuity": "跨镜不连贯", "cross_shot": "跨镜不连贯", "limbs": "多肢", "extra_limbs": "多肢", "bad_hands": "坏手",
              "accessory_mismatch": "饰品不对", "outfit_mismatch": "服装不对", "shoes_mismatch": "鞋不对", "plastic_doll": "塑料感",
              "people": "人数不对", "text": "画面里有文字", "framing": "景别不对"}
_reg: dict = {"mt": None, "val": {}}


def _registry() -> dict[str, dict]:
    try:
        mt = REGISTRY.stat().st_mtime
    except OSError:
        return {}
    if _reg["mt"] != mt:
        try:
            d = json.loads(REGISTRY.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            d = {}
        val = {}
        for ep in d.get("episodes") or []:
            for s in ep.get("shots") or []:
                val[s.get("shot")] = s.get("objects") or {}
        _reg.update(mt=mt, val=val)
    return _reg["val"]


def _why_contract(err: str | None) -> str:
    e = (err or "").replace("契约没过：", "").strip()
    return e or "没写原因"


def _vqa(take: dict) -> tuple[str | None, str]:
    """→ ('fail' | 'untested' | 'pass' | None, 原因)"""
    rounds = ((take.get("params") or {}).get("vqa_rounds")) if isinstance(take.get("params"), dict) else None
    if rounds:
        j = (rounds[-1] or {}).get("judge") or {}
        v = str(j.get("verdict") or "").lower()
        if v in ("fail", "failed", "reject"):
            raw = [str(x) for x in j.get("failed_checks") or []]
            fc = list(dict.fromkeys(CHECK_WORD[x] for x in raw if x in CHECK_WORD))
            other = len([x for x in raw if x not in CHECK_WORD])
            txt = "、".join(fc) + (f"{'等 ' if fc else ''}{other} 项其他问题" if other else "")
            return "fail", txt or "看图判定没过"
        if v in ("pass", "ok"):
            return "pass", ""
        return "untested", "看图结果还没出"
    for it in ((take.get("postflight") or {}).get("items") or []) if isinstance(take.get("postflight"), dict) else []:
        if it.get("id") == "Q9" and it.get("status") == "untested":
            return "untested", "看图检查未测"
    return None, ""


def tags_for(shot: str, cand_row: dict | None, takes: dict | None = None) -> dict:
    """一镜的状态标签。cand_row = takes_ui.candidates 的 shots[shot]；takes = 该镜 takes.json（看图判定用，可省）"""
    tags: list[dict] = []
    objs = _registry().get(shot) or {}

    def add(kind: str, stage: str, text: str):
        tags.append({"kind": kind, "label": KINDS[kind], "stage": STAGE_WORD.get(stage, stage), "text": text})

    for st in ("first", "last", "video"):
        o = objs.get(st)
        if not isinstance(o, dict):
            continue
        status = o.get("status")
        if status != "passed" and o.get("last_error") and "契约没过" in str(o.get("last_error")):   # 通过后的 last_error 是旧记录
            add("vqa_fail", st, _why_contract(o.get("last_error")))
        if o.get("redo") or o.get("master_reject"):
            mr = str(o.get("master_reject") or o.get("reason") or "")
            add("redo", st, "全量重做，等重出" if "全量重做" in mr else "被驳回，等重出")
        if o.get("stale"):
            add("stale", st, "剧本或输入改了，当前版要重出")
        if status == "best_effort":
            add("best", st, "试了几次没全过，先用最好的一版")
        elif status == "running":
            add("busy", st, "正在出")
        elif status == "ready" and not (o.get("redo") or o.get("stale")):
            add("queued", st, "排队等空闲的卡")
        elif status == "passed":
            add("ok", st, "已通过并设为当前")
    # 旧剧本版本：这一阶段只剩旧剧本出的图（或当前版本就是旧剧本出的），没有现行版本的图
    for st in ("image", "last"):
        x = (cand_row or {}).get(st) or {}
        tk = x.get("takes") or []
        cur_old = x.get("active") is not None and any(t.get("n") == x["active"] and t.get("script") == "old" for t in tk)
        has_new = any(t.get("script") == "current" for t in tk)
        if (cur_old or (tk and not has_new and x.get("active") is None)) and any(t.get("script") == "old" for t in tk):
            add("old", st, "只剩剧本更新前出的旧图，没有新图")
    # 看图判定：现行剧本版本里最新一版首帧 / 尾帧
    if takes:
        for st in ("image", "last"):
            cur = [t for t in takes.get("takes") or [] if t.get("stage") == st]
            x = (cand_row or {}).get(st) or {}
            curn = {t.get("n") for t in x.get("takes") or [] if t.get("script") == "current"}
            cur = [t for t in cur if t.get("n") in curn]
            if cur:
                v, why = _vqa(cur[-1])
                if v == "fail":
                    add("vqa_fail", st, why)
                elif v == "untested":
                    add("judge", st, why)
    tags.sort(key=lambda t: ORDER.index(t["kind"]))
    seen, uniq = set(), []
    for t in tags:
        k = (t["kind"], t["stage"], t["text"])
        if k not in seen:
            seen.add(k)
            uniq.append(t)
    return {"main": uniq[0]["kind"] if uniq else None, "tags": uniq}


# ---------------------------------------------------------------- 板块层面（UIRSI r40；项目方 00:3x：“用颜色区分一下：哪个板块已经确认,
# 哪个板块正在进行中,哪个板块是过期的.layout一下”）：每集 + 每阶段一个状态，和镜头格标签同一口径（同一份 registry / 剧本版本 / 看图判定）
BLOCK_WORD = {"stale": "过期", "doing": "进行中", "done": "已确认", "todo": "未开始"}
STAGES_EP = [("script", "剧本"), ("assets", "资产"), ("first", "首帧"), ("last", "尾帧"), ("video", "视频"), ("assembly", "成片")]
_REG_EP: dict = {"mt": None, "val": {}}


def _registry_eps() -> dict[int, dict]:
    try:
        mt = REGISTRY.stat().st_mtime
    except OSError:
        return {}
    if _REG_EP["mt"] != mt:
        try:
            d = json.loads(REGISTRY.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            d = {}
        _REG_EP.update(mt=mt, val={int(e.get("ep") or 0): e for e in d.get("episodes") or []})
    return _REG_EP["val"]


def _obj_state(o: dict | None) -> str:
    st = (o or {}).get("status")
    if not o:
        return "todo"
    if o.get("stale") or o.get("redo") or o.get("master_reject"):
        return "stale"
    if st in ("passed", "best_effort"):
        return "done"
    if st in ("running", "ready"):
        return "doing"
    return "todo"


def episode_blocks(ep: int, shots: list[dict]) -> dict:
    """shots = /api/season 本集 shots（已带 status）。→ {state, text, stages: [{key, label, state, counts, text}]}"""
    reg = _registry_eps().get(ep) or {}
    objs = reg.get("objects") or {}
    shot_objs = {s.get("shot"): s.get("objects") or {} for s in reg.get("shots") or []}
    stages = []
    for key, label in STAGES_EP:
        cnt = {"stale": 0, "doing": 0, "done": 0, "todo": 0}
        if key in ("script", "assembly"):
            if key == "assembly":
                cnt[_obj_state(objs.get("assembly"))] += 1
            else:   # 剧本 = 写作 + 导入，两样都在的取较差的那个
                ss = [_obj_state(objs.get(k)) for k in ("script", "import") if objs.get(k)] or ["todo"]
                cnt[next((x for x in ("stale", "doing", "todo") if x in ss), "done")] += 1
        else:
            for s in shots:
                o = shot_objs.get(s["id"], {}).get(key)
                stt = _obj_state(o)
                tags = (s.get("status") or {}).get("tags") or []
                word = STAGE_WORD.get(key)
                if any(t["kind"] in ("old", "stale", "redo") and t["stage"] == word for t in tags):
                    stt = "stale"
                elif stt != "stale" and any(t["kind"] in ("busy", "queued", "judge") and t["stage"] == word for t in tags):
                    stt = "doing"
                cnt[stt] += 1
        total = sum(cnt.values()) or 1
        state = "stale" if cnt["stale"] else "doing" if cnt["doing"] or (cnt["done"] and cnt["todo"]) else "done" if cnt["done"] == total else "todo"
        parts = [f"{BLOCK_WORD[k]} {v}" for k, v in cnt.items() if v]
        stages.append({"key": key, "label": label, "state": state, "counts": cnt, "text": f"{label}：{BLOCK_WORD[state]}（{' · '.join(parts)}）"})
    # 上游过期了，下游“已确认”的也跟着过期（例如首帧要重出，旧成片就不能算已确认）
    up_stale = False
    for x in stages:
        if up_stale and x["state"] == "done":
            x["state"] = "stale"
            x["text"] = f"{x['label']}：过期（上游要重出，这一步是按旧的做的）"
        up_stale = up_stale or x["state"] == "stale"
    sts = [x["state"] for x in stages]
    state = "stale" if "stale" in sts else "doing" if "doing" in sts else "done" if all(x == "done" for x in sts) else ("doing" if "done" in sts else "todo")
    bad = [x["label"] for x in stages if x["state"] == "stale"]
    text = f"本集{BLOCK_WORD[state]}" + (f"：{'、'.join(bad)}要重出" if bad else "")
    return {"state": state, "text": text, "stages": stages}
