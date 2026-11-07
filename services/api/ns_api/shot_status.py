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
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
# legacy（V1）位置；真正读哪一份见 registry_path()（当前剧 data/producer/runs/<run>/registry.json）。测试可直接改 REGISTRY 指向临时文件
REGISTRY = ROOT / "data" / "producer" / "registry.json"
_REGISTRY_DEFAULT = REGISTRY


def registry_path() -> Path:
    """UIUX-LOOP r1：状态标签只认当前剧那份活的登记表（run_paths.producer_registry，K-OPS-F24）。REGISTRY 被改过（测试）就用改过的"""
    if REGISTRY is not _REGISTRY_DEFAULT:
        return REGISTRY
    try:
        from ns_api import run_paths as _RP
        return _RP.producer_registry(ROOT)
    except Exception:  # noqa: BLE001  # arch-ok: 剧目登记表读不到 = 退回旧位置（只影响标签，不影响出图）
        return REGISTRY
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
HOSTS = ("gpu33", "gpu36")
HOST_REG_MAX_AGE_S = 6 * 3600     # 那台登记表心跳超过这么久 = 旧的，不参与合并
_MERGED: dict = {"key": None, "val": {}}


def _host_copies(p: Path) -> list[Path]:
    """resident_sync.pull 拉回的两台登记表：data/_offline_pull/<host>/<同一相对路径>（只对仓库里的登记表；测试临时文件 = 无）"""
    try:
        rel = p.resolve().relative_to(ROOT.resolve())
    except ValueError:
        return []
    return [ROOT / "data" / "_offline_pull" / h / rel for h in HOSTS]


def _mt(f: Path) -> float | None:
    try:
        return f.stat().st_mtime
    except OSError:  # arch-ok: 没有 / 正被替换 = 当作缺
        return None


def _rm():
    from tools.brain import reg_merge as _RMG  # noqa: PLC0415
    return _RMG._rm()


def _merged_file(p: Path) -> dict | None:
    """L-209 S2.5：登记表旁边笔记本每拍写的 registry_merged.json（唯一合并表）；新鲜 = 它，缺 / 过期 / off = None（退回本机，
    registry_merged_fallback 每 10 分钟记一条到 stderr）"""
    try:
        RM = _rm()
        return RM.fresh_path(p.parent / RM.NAME, ROOT, log=RM.default_log("ns_api"), actor="ns_api")
    except Exception:  # noqa: BLE001  # arch-ok: 合并表模块读不到 = 退回本机（只影响显示）
        return None


def reg_key(p: Path) -> tuple:
    """缓存键：本机登记表 + 两台拉回的 + 合并表（mtime、是否新鲜）"""
    m = _merged_file(p)
    return (str(p), _mt(p), tuple(_mt(f) for f in _host_copies(p)), (m or {}).get("computed_t"))


def merged_registry(p: Path | None = None) -> dict:
    """L-209 S2.5：先读唯一合并表 registry_merged.json（笔记本每拍写，tools/autopilot/registry_merged.merge）；
    缺 / 过期 → 退回 W-FIX-PIPE #8：本机登记表为底 + 两台拉回的登记表只补已定下（tools/brain/reg_merge 转调同一个合并函数）。
    网页标签 / 阶段块 / 首尾帧 / 视频页 / KPI 面板都读这一份。按 (路径, mtime) 缓存"""
    import time as _t
    p = p or registry_path()
    m = _merged_file(p)
    if m is not None:
        return m
    files = [p] + _host_copies(p)
    key = tuple((str(f), _mt(f)) for f in files)
    if _MERGED["key"] == key:
        return _MERGED["val"]
    try:
        base = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        base = {}
    others = {}
    for h, f in zip(HOSTS, files[1:]):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):  # arch-ok: 那台的登记表还没拉回 / 正在写 = 这一拍不合并它
            continue
        if _t.time() - float(d.get("heartbeat") or 0) <= HOST_REG_MAX_AGE_S:
            others[h] = d
    val = base
    if others:
        try:
            from tools.brain import reg_merge as _RM  # noqa: PLC0415
            val = _RM.merge_registries(base, others)
        except Exception:  # noqa: BLE001  # arch-ok: 合并出错 = 退回本机那份（只影响显示）
            val = base
    _MERGED.update(key=key, val=val)
    return val


def _registry() -> dict[str, dict]:
    p = registry_path()
    try:
        p.stat()
    except OSError:
        return {}
    mt = reg_key(p)
    if _reg["mt"] != mt:
        d = merged_registry(p)
        val = {}
        for ep in d.get("episodes") or []:
            for s in ep.get("shots") or []:
                val[s.get("shot")] = s.get("objects") or {}
        _reg.update(mt=mt, val=val)
    return _reg["val"]


_STAGE_KEY = {"image": "first", "first": "first", "last": "last", "video": "video"}


def ledger_passed(shot: str, stage: str, n: int | None = None) -> bool:
    """UIUX-LOOP r4：活的登记表说这一镜这一阶段已 passed（给了 take 号就要对上）。
    用处：导入作废线（import_events changed_shots）只是“这镜的某个字段变了”，producer 导入时按编译后的提示词判断没变、把当前版保留为 passed——
    这时当前版不是“旧剧本版本”，也不该把之后系统自动重试失败的一版当“看图没过”挂在镜头上（项目方只看通过的）。"""
    o = (_registry().get(shot) or {}).get(_STAGE_KEY.get(stage, stage))
    if not isinstance(o, dict) or o.get("status") != "passed":
        return False
    return n is None or o.get("take") is None or o.get("take") == n


LEDGER_WORD = {"ready": "排队等空闲的卡", "running": "正在出", "pending": "等上一步", "failed": "没出来，系统在重试",
               "best_effort": "尽力版", "passed": "已定下", "blocked": "卡住了"}


def ledger_obj(shot: str, stage: str) -> dict | None:
    """UIUX-LOOP-2 r7：活的登记表里这一镜这一阶段的对象（status / take / reason…）；没有 = None"""
    o = (_registry().get(shot) or {}).get(_STAGE_KEY.get(stage, stage))
    return o if isinstance(o, dict) else None


def ledger_cell(shot: str, stage: str) -> dict | None:
    """给页面格子用：{state, word, take, why}——没有本机图 / 片时写登记表说的状态（排队 / 正在出 / 等上一步 / 没出来），不写“还没出图”"""
    o = ledger_obj(shot, stage)
    if not o or not o.get("status"):
        return None
    st = str(o.get("status"))
    return {"state": st, "word": LEDGER_WORD.get(st, st), "take": o.get("take"), "why": (str(o.get("reason") or o.get("last_error") or "")[:160] or None)}


def ledger_shots(ep: int | None = None) -> list[tuple[int, int]]:
    """活的登记表登记过的镜 [(集, 镜号)]（r7：出图页 / 视频页不再只认有 takes.json 目录的镜——排队中的镜也要看得见）"""
    out = []
    for sid in _registry():
        m = re.fullmatch(r"ep(\d+)-S(\d+)", str(sid))
        if m and (ep is None or int(m.group(1)) == ep):
            out.append((int(m.group(1)), int(m.group(2))))
    return sorted(out)


def _full_redo(o: dict) -> bool:
    """registry 对象是不是 L-088 全量重做（现行生产计划）挂上的“重出”"""
    txt = f"{o.get('master_reject') or ''} {o.get('reason') or ''}"
    return "全量重做" in txt or "L-088" in txt


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
    fb = _last_fallback(takes)   # r5：尾帧兜底（L-204 D8 I2VA）生效 = 这一镜不出尾帧，尾帧阶段的标签一律不挂

    def add(kind: str, stage: str, text: str):
        if fb and STAGE_WORD.get(stage, stage) == "尾帧":
            return
        tags.append({"kind": kind, "label": KINDS[kind], "stage": STAGE_WORD.get(stage, stage), "text": text})

    for st in ("first", "last", "video"):
        o = objs.get(st)
        if not isinstance(o, dict):
            continue
        status = o.get("status")
        if status != "passed" and o.get("last_error") and "契约没过" in str(o.get("last_error")):   # 通过后的 last_error 是旧记录
            add("vqa_fail", st, _why_contract(o.get("last_error")))
        full = _full_redo(o)
        # r42（总调度：“每集都挂过期”核实）：L-088 全量重做是现行生产计划，不是“过期”——在出就是“出图中”，没轮到就是“排队中”；
        # 只有真被驳回（总调度 / 看图闸门）才算“待重出”
        if (o.get("redo") or o.get("master_reject")) and not full:
            add("redo", st, "被驳回，等重出")
        if o.get("stale") and not full:
            add("stale", st, "剧本或输入改了，当前版要重出")
        if status == "best_effort":
            add("best", st, "试了几次没全过，先用最好的一版")
        elif status == "running":
            add("busy", st, "正在出" + ("（全量重做）" if full else ""))
        elif status == "ready" and (full or not (o.get("redo") or o.get("stale"))):
            add("queued", st, "全量重做，排队等空闲的卡" if full else "排队等空闲的卡")
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
    # 看图判定：现行剧本版本里最新一版首帧 / 尾帧（r4：这一阶段登记表已 passed 且有当前版 → 最新一版没过只是系统内部重试，不挂到镜头上）
    if takes:
        act_all = takes.get("active") or {}
        for st in ("image", "last"):
            if act_all.get(st) is not None and ledger_passed(shot, st, act_all.get(st)):
                continue
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
    m5 = main5(shot, objs, cand_row, takes)
    tags.sort(key=lambda t: ORDER.index(t["kind"]))
    seen, uniq = set(), []
    for t in tags:
        k = (t["kind"], t["stage"], t["text"])
        if k not in seen:
            seen.add(k)
            uniq.append(t)
    return {"main": uniq[0]["kind"] if uniq else None, "tags": uniq, **m5, "last_fallback": bool(fb)}


def _last_fallback(takes: dict | None) -> dict | None:
    """尾帧兜底（frames_index.last_fallback 同一口径）且没有当前尾帧 → 兜底记录；否则 None"""
    if not takes or (takes.get("active") or {}).get("last") is not None:
        return None
    try:
        from ns_api import frames_index as FI  # noqa: PLC0415
        return FI.last_fallback(takes)
    except Exception:  # noqa: BLE001  # arch-ok: 兜底记录读坏 = 按没有兜底的旧口径
        return None


# ---------------------------------------------------------------- 板块层面（UIRSI r40；项目方 00:3x：“用颜色区分一下：哪个板块已经确认,
# 哪个板块正在进行中,哪个板块是过期的.layout一下”）：每集 + 每阶段一个状态，和镜头格标签同一口径（同一份 registry / 剧本版本 / 看图判定）
BLOCK_WORD = {"stale": "过期", "doing": "进行中", "done": "已确认", "todo": "未开始"}
STAGES_EP = [("script", "剧本"), ("assets", "资产"), ("first", "首帧"), ("last", "尾帧"), ("video", "视频"), ("assembly", "成片")]
_REG_EP: dict = {"mt": None, "val": {}}


def _registry_eps() -> dict[int, dict]:
    p = registry_path()
    try:
        p.stat()
    except OSError:
        return {}
    mt = reg_key(p)
    if _REG_EP["mt"] != mt:
        d = merged_registry(p)
        _REG_EP.update(mt=mt, val={int(e.get("ep") or 0): e for e in d.get("episodes") or []})
    return _REG_EP["val"]


def _obj_state(o: dict | None) -> str:
    st = (o or {}).get("status")
    if not o:
        return "todo"
    if (o.get("stale") or o.get("redo") or o.get("master_reject")) and not _full_redo(o):
        return "stale"
    if _full_redo(o) and st not in ("passed", "best_effort"):
        return "doing"            # r42：全量重做在出 / 排队 = 进行中，不是过期
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
                if key == "last" and (s.get("status") or {}).get("last_fallback"):
                    stt = "done"        # r5：尾帧兜底（I2VA）= 这一镜不出尾帧，不算缺、不算过期
                elif stt != "doing" and any(t["kind"] in ("old", "stale", "redo") and t["stage"] == word for t in tags):
                    stt = "stale"       # r5：登记表已排进重出（ready / running）= 进行中；“过期”只给还没排进重出的（main5 同口径）
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
    need_n = sum(1 for s in shots if (s.get("status") or {}).get("main5") == "need")
    stale_n = sum(1 for s in shots if (s.get("status") or {}).get("main5") == "stale")
    return {"state": state, "text": text, "stages": stages, "need_n": need_n, "stale_n": stale_n}


# ---------------------------------------------------------------- 五态主状态（UIRSI r43，OVERVIEW_REDESIGN §3；K6 / K7）
# 一镜的主状态 = 流水线上最前面一个还没确认的步骤（首帧 → 尾帧 → 视频 → 你审）的状态；上游在重做时下游的旧结论自动作废。
MAIN5_WORD = {"need": "需要你看", "stale": "过期", "doing": "进行中", "todo": "未开始", "done": "已确认"}
STEP_WORD = {"first": "首帧", "last": "尾帧", "video": "视频"}


def _reviewed(shot: str, takes: dict | None) -> str | None:
    """review.json 对当前版本有效时的审核结论（passed / rejected），否则 None（和 app._review 同口径）"""
    try:
        from ns_render import pipeline as P  # noqa: PLC0415
        r = json.loads((P.shot_dir(shot) / "review.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    act = (takes or {}).get("active") or {}
    cur = {"image": act.get("image"), "last": act.get("last"), "video": act.get("video")}
    got = {k: (r.get("takes") or {}).get(k) for k in cur}
    return r.get("state") if got == cur else None


def main5(shot: str, objs: dict, cand_row: dict | None = None, takes: dict | None = None) -> dict:
    """→ {main5: need|stale|doing|todo|done, why: 一句大白话, running: bool, step}"""
    act = (takes or {}).get("active") or {}
    fb = _last_fallback(takes)
    for step in ("first", "last", "video"):
        o = objs.get(step)
        if step == "last" and fb:
            continue    # r5：尾帧兜底生效 = 这一镜不出尾帧，往视频看
        # r45（FILMUI 查出 /api/season 自相矛盾：ep01-S1 首帧已定稿 active image=19，状态却写“首帧未开始（等上一步）”）：
        # 这一步已经有定稿（当前）版本、登记表又没有在重出（没在跑 / 排队），就算这一步已确认，往下一步看
        has_cur = act.get({"first": "image", "last": "last", "video": "video"}[step]) is not None
        if not isinstance(o, dict):
            if has_cur:
                continue
            return {"main5": "todo", "why": f"{STEP_WORD[step]}还没排上", "running": False, "step": step}
        st = o.get("status")
        if st == "passed" or (has_cur and st in (None, "pending") and not o.get("stale")):
            continue
        name = STEP_WORD[step]
        a, mx = int(o.get("attempts") or 0), o.get("max_attempts")
        full = _full_redo(o)
        if st == "running":
            return {"main5": "doing", "why": f"{name}正在出" + ("（全量重做）" if full else ""), "running": True, "step": step}
        if st == "best_effort":
            return {"main5": "need", "why": f"{name}是尽力版，等你接受", "running": False, "step": step}
        err = str(o.get("last_error") or "")
        if "契约没过" in err:
            why = _why_contract(err)
            if mx and a >= int(mx):
                return {"main5": "need", "why": f"{name}重试 {a} 次都没过：{why}", "running": False, "step": step}
            return {"main5": "doing", "why": f"{name}没过（{why}），自动重试 {a}/{mx or '?'}", "running": False, "step": step}
        if st == "ready":
            if full or o.get("redo") or o.get("master_reject") or o.get("stale"):
                return {"main5": "doing", "why": f"{name}排队重出" + (f"（第 {a + 1}/{mx} 次）" if mx else ""), "running": False, "step": step}
            return {"main5": "doing", "why": f"{name}排队", "running": False, "step": step}
        if o.get("stale"):
            return {"main5": "stale", "why": f"{name}按旧输入出的，还没排进重出", "running": False, "step": step}
        wf = str(o.get("waiting_for") or "")
        if st == "pending":
            up = "首帧" if "首帧" in wf else "尾帧" if "尾帧" in wf else "上一步"
            prev = {"last": "image", "video": "last"}.get(step)
            if prev and act.get(prev) is not None:      # 上一步已有定稿：不再说“等上一步”，说清是还没排上
                return {"main5": "todo", "why": f"{name}还没排上（{'首帧' if prev == 'image' else '尾帧'}已定稿）", "running": False, "step": step}
            return {"main5": "todo", "why": f"{name}未开始（等{up}）", "running": False, "step": step}
        return {"main5": "doing", "why": f"{name}{st or '处理中'}", "running": False, "step": step}
    rv = _reviewed(shot, takes)
    if rv == "passed":
        return {"main5": "done", "why": "已确认", "running": False, "step": "review"}
    if rv == "rejected":
        return {"main5": "need", "why": "视频被打回，等你定怎么改", "running": False, "step": "review"}
    return {"main5": "need", "why": "视频待你审", "running": False, "step": "review"}
