"""画布候选版本（UIRSI 2026-11-01，BE-5 前端配套）。

流水线出的图已由 SERIES 登记进 takes.json（source=pipeline，params.tentative / label=旧配方·新配方，不设当前）。
集摘要只给 latest_take 编号、不给图址和标签，画布要“候选 #n · 暂定 · 旧配方”就靠这里一次给全集：

  GET  /api/candidates?ep=2       每镜每阶段（image / last）的全部版本：n、图址、标签、暂定、规则过期角标；当前是哪版
  POST /api/shots/{id}/takes/{stage}/unset  {expect: n}
                                  撤销“用这张”：只有当前确实还是 n 时才撤（别人改过就 409），撤成“没有当前版本”。
                                  原来有当前版本的撤销 = 直接 activate 回原来那版（已有接口），不走这里。
tentative / stale 只做角标，不藏候选；但项目方判过不合格的配方（旧配方）、坏图、流水线没通过的标 ok=false，不作“挑一张用”的候选。
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(tags=["takes-ui"])
STAGES = ("image", "last")
# 项目方判过不合格的配方（总调度 11-01：“旧配方（v1）首帧是项目方判过不合格的，不应作为‘挑一张用’的候选……只给他看通过的”）
REJECTED_LABELS = {"旧配方": "旧配方 · 项目方判过不合格"}
BAD_STATUS = {"failed", "rejected", "error", "fail"}


# ---------------------------------------------------------------- 剧本版本（UIRSI r40，项目方 11-02 00:0x：“图片生成错误,你刷新了图片库没有?”）
# 23:21 HOLLYWOOD 逐集导入后镜头重新编号，新 S1 已不是旧 S1；候选按 epNN/SN 存放，旧剧本出的图还挂在新镜号底下。
# 口径：take 带 prompt_source.sha256 且等于现行剧本 sha → 现行；否则按出图时间——早于本集最后一次导入（data/import/import_log.jsonl）= 旧剧本版本。
# 旧版本不删、不改 takes.json，只在接口里标 ok=false / script="old"，不作候选、不计候选数；历史区仍可查看。
REPO = Path(__file__).resolve().parents[3]
IMPORT_LOG = REPO / "data" / "import" / "import_log.jsonl"
SCRIPT = REPO / "data" / "import" / "script_v2.json"
_EP_RE = re.compile(r"_ep(\d{2})_")
_imp_cache: dict = {"mt": None, "val": ({}, None)}
_sha_cache: dict = {"mt": None, "val": None}


def import_cutoffs() -> tuple[dict[int, str], str | None]:
    """→ ({集号: 本集最后一次导入时间 ISO}, 整本导入的最后时间)。逐集合并导入按路径里的 _epNN_ 或 episodes 字段归集；
    认不出集号的导入算整本（对所有集生效）"""
    try:
        mt = IMPORT_LOG.stat().st_mtime
    except OSError:
        return {}, None
    if _imp_cache["mt"] == mt:
        return _imp_cache["val"]
    per: dict[int, str] = {}
    whole: str | None = None
    for ln in IMPORT_LOG.read_text(encoding="utf-8").splitlines():
        try:
            e = json.loads(ln)
        except ValueError:
            continue
        if e.get("rc") not in (0, None) or not e.get("at"):
            continue
        eps = {int(x) for x in (e.get("episodes") or []) if str(x).isdigit()}
        if not eps:
            m = _EP_RE.search(str(e.get("path") or ""))
            eps = {int(m.group(1))} if m else set()
        if eps:
            for n in eps:
                per[n] = max(per.get(n, ""), e["at"])
        else:
            whole = max(whole or "", e["at"])
    _imp_cache.update(mt=mt, val=(per, whole))
    return per, whole


def script_sha() -> str | None:
    try:
        mt = SCRIPT.stat().st_mtime
    except OSError:
        return None
    if _sha_cache["mt"] != mt:
        _sha_cache.update(mt=mt, val=hashlib.sha256(SCRIPT.read_bytes()).hexdigest())
    return _sha_cache["val"]


def cutoff_for(ep: int) -> str | None:
    per, whole = import_cutoffs()
    c = [x for x in (per.get(ep), whole) if x]
    return max(c) if c else None


QDIR_NAME = "_quarantine_20261102_oldscript"


def is_quarantined(t: dict) -> bool:
    """已隔离：takes.json 里有 quarantined 标记；或者标记被别的进程整份重写冲掉了（r42 实测：服务器并回 takes.json“新者为准”覆盖，
    72 个标记丢了），但文件已不在 data/、在隔离区里——照样算已隔离，不显示、不当当前"""
    if t.get("quarantined"):
        return True
    f = t.get("file")
    if not f:
        return False
    data = _P().DATA                     # 跟 pipeline 的数据根走（测试会换成临时目录）
    return not (data / f).exists() and (data / QDIR_NAME / "data" / f).exists()


def _prompt_sha(t: dict) -> str | None:
    for src in (t, t.get("params") or {}, t.get("producer") if isinstance(t.get("producer"), dict) else {}):
        ps = src.get("prompt_source") if isinstance(src, dict) else None
        if isinstance(ps, dict) and ps.get("sha256"):
            return ps["sha256"]
    return None


def script_version(t: dict, ep: int) -> str:
    """'current' / 'old'（旧剧本版本）/ 'unknown'（没有导入记录）"""
    sha = _prompt_sha(t)
    if sha and sha == script_sha():
        return "current"
    cut = cutoff_for(ep)
    if not cut or not t.get("created_at"):     # 没有导入记录 / 这一版没记出图时间：判不了，不藏
        return "unknown"
    return "current" if t["created_at"] >= cut else "old"


def cutoff_label(ep: int) -> str:
    cut = cutoff_for(ep)
    return f"{cut[5:10].replace('-', '/')} {cut[11:16]}" if cut else "?"


def _verdict(t: dict, bad: str | None) -> tuple[bool, str | None]:
    """候选能不能给项目方挑：坏图 / 判过不合格的配方 / 流水线没通过（作业失败、质检 ok/pass=false）都不能"""
    prm = t.get("params") or {}
    if bad:
        return False, f"坏图：{bad}"
    if prm.get("rejected"):
        r = prm["rejected"]
        return False, f"你标了不要{('：' + r.get('reason')) if isinstance(r, dict) and r.get('reason') else ''}"
    if prm.get("label") in REJECTED_LABELS:
        return False, REJECTED_LABELS[prm["label"]]
    org = prm.get("origin") or {}
    if str(org.get("job_status") or "").lower() in BAD_STATUS:
        return False, "流水线没通过"
    qc = org.get("qc") if isinstance(org.get("qc"), dict) else {}
    if qc.get("ok") is False or qc.get("pass") is False or qc.get("passed") is False:
        return False, "质检没通过"
    return True, None


def _P():
    from ns_render import pipeline as P  # noqa: PLC0415
    return P


def _url(P, f: str | None) -> str | None:
    if not f:
        return None
    p = P.DATA / f
    try:
        v = int(p.stat().st_mtime)
    except OSError:
        return None
    return f"/files/{f}?v={v}"


@router.get("/api/candidates")
def candidates(ep: int, history: bool = False):
    """history=false（默认）：已隔离的版本（UIRSI r41 旧剧本版本，文件已移进 data/_quarantine_20261102_oldscript）不返回；
    history=true：连隔离的也返回（标 quarantined，给“历史”入口看）"""
    P = _P()
    root = P.RENDERS / f"ep{ep:02d}"
    out: dict[str, dict] = {}
    if not root.is_dir():
        return {"episode": ep, "shots": out}
    for d in sorted(root.iterdir()):
        m = re.fullmatch(r"S(\d{1,3})", d.name)
        if not m or not (d / "takes.json").is_file():
            continue
        sid = f"ep{ep:02d}-S{int(m.group(1))}"
        try:
            data = P.load_takes(sid)
        except Exception:  # noqa: BLE001 — 一镜读坏不影响别的镜
            continue
        row: dict[str, dict] = {}
        for st in STAGES:
            ts = [t for t in data.get("takes") or [] if t.get("stage") == st and (history or not is_quarantined(t))]
            if not ts:
                continue
            items = []
            for t in ts:
                prm = t.get("params") or {}
                bad = P.bad_reason(t) if hasattr(P, "bad_reason") else None
                ok, why = _verdict(t, bad)
                ver = script_version(t, ep)
                if ver == "old":     # 旧剧本版本：不作候选（不管它过没过契约）；历史区仍可看。原来的“不合格 / 脸不像”等原因保留在前面
                    old_why = f"旧剧本版本（剧本 {cutoff_label(ep)} 更新前出的，镜头可能已重新编号）"
                    ok, why = False, f"{why}；{old_why}" if why else old_why
                post = ((t.get("gen_contract") or {}).get("post") or {}) if isinstance(t.get("gen_contract"), dict) else {}
                q = t.get("quarantined") if isinstance(t.get("quarantined"), dict) else ({"moved_to": {"file": f"data/_quarantine_20261102_oldscript/data/{t.get('file')}"}} if is_quarantined(t) else None)
                qf = ((q or {}).get("moved_to") or {}).get("file")
                f_ = qf[len("data/"):] if qf and qf.startswith("data/") else t.get("file")   # r41：历史入口看隔离区里的原图
                if q:
                    ok, why = False, why or "已隔离（旧剧本版本）"
                items.append({"n": t["n"], "url": _url(P, f_), "label": prm.get("label"), "quarantined": bool(q),
                              "tentative": bool(prm.get("tentative")), "source": t.get("source"),
                              "bad": bad, "ok": ok, "why_not": why, "created_at": t.get("created_at"),
                              # 出图契约（GEN_CONTRACT postflight）结论：pass = 项目方授权“通过契约即自动采用”
                              "contract": post.get("status") if isinstance(post, dict) else None,
                              "rejected": bool(prm.get("rejected")), "script": ver})
            a = (data.get("active") or {}).get(st)
            aq = next((x for x in data.get("takes") or [] if x.get("stage") == st and x.get("n") == a and is_quarantined(x)), None)
            # r41：当前版本已隔离 = 没有当前（和集摘要 _active 同口径）
            row[st] = {"active": None if aq else a, "takes": [x for x in items if x["url"]], **({"active_quarantined": a} if aq else {})}
        # UIRSI r40：视频版本也标剧本版本（画布“视频 N 版待选”只数现行剧本出的）
        vt = [x for x in data.get("takes") or [] if x.get("stage") == "video" and (history or not is_quarantined(x))]
        if vt:
            row["video"] = {"active": (data.get("active") or {}).get("video"),
                            "takes": [{"n": x["n"], "script": script_version(x, ep), "created_at": x.get("created_at")} for x in vt]}
        # UIRSI r40（项目方：“哪些是重置的,过期的,就给它用不同的颜色 label 一下”）：状态标签，汇总 producer 登记 / 剧本版本 / 看图判定
        try:
            from ns_api import shot_status  # noqa: PLC0415
            row["status"] = shot_status.tags_for(sid, row, data)
        except Exception:  # noqa: BLE001 — 标签读坏不影响候选
            pass
        if row:
            out[sid] = row
    return {"episode": ep, "shots": out, "script_cutoff": cutoff_for(ep)}


class UnsetBody(BaseModel):
    expect: int


@router.post("/api/shots/{shot_id}/takes/{stage}/unset")
def unset(shot_id: str, stage: str, body: UnsetBody):
    if stage not in STAGES:
        raise HTTPException(400, "只能撤首帧 / 尾帧")
    P = _P()
    with P.shot_lock(shot_id):
        data = P.load_takes(shot_id)
        cur = (data.get("active") or {}).get(stage)
        if cur != body.expect:
            raise HTTPException(409, f"当前已经不是 #{body.expect}（现在是 {cur if cur is not None else '无'}），不撤")
        data["active"].pop(stage, None)
        P._save_takes(shot_id, data)
        (P.shot_dir(shot_id) / ("frame.png" if stage == "image" else "last.png")).unlink(missing_ok=True)
    P.audit_active(shot_id, stage, body.expect, None, "界面撤掉当前", "takes_ui.unset")   # K-OPS-Q23
    try:
        from ns_api.app import _summary_cache  # noqa: PLC0415
        _summary_cache.invalidate()
    except Exception:  # noqa: BLE001
        pass
    return P.load_takes(shot_id)


class RejectBody(BaseModel):
    reason: str = ""
    by: str | None = None


@router.post("/api/shots/{shot_id}/takes/{stage}/{n}/reject")
def reject(shot_id: str, stage: str, n: int, body: RejectBody):
    """“✗ 不要 · 只标记”：这一版记上“不要”（原因），不再作候选；如果它正是当前版本，撤成上一张没被标不要的（没有就清空）。
    返回 {was_active, active}：撤销用 unreject（带 was_active 就恢复成当前）"""
    if stage not in STAGES:
        raise HTTPException(400, "只能标首帧 / 尾帧")
    P = _P()
    with P.shot_lock(shot_id):
        data = P.load_takes(shot_id)
        t = next((x for x in data.get("takes") or [] if x.get("stage") == stage and x.get("n") == n), None)
        if not t:
            raise HTTPException(404, "没有这个版本")
        prm = t["params"] if isinstance(t.get("params"), dict) else {}
        t["params"] = prm
        prm["rejected"] = {"reason": body.reason[:300], "by": body.by or "", "at": P.now()}
        was = (data.get("active") or {}).get(stage) == n
        P._save_takes(shot_id, data)
    act = None
    if was:
        # deactivate 会退到最新一张“干净”的旧版；被标不要的不算候选，所以先清空再看有没有没被标的
        data = P.load_takes(shot_id)
        # K-OPS-Q23（ep01-S5 事故：退回到了总调度驳回过的 v3，且没留审计）：只退到可用的旧版（不是坏图 / 不要 / 总调度驳回）
        clean = [x for x in data["takes"] if x.get("stage") == stage and x["n"] != n and not P.ineligible_reason(x)]
        if clean:
            P.set_active(shot_id, stage, clean[-1]["n"], reason=f"v{n} 标了不要，退回最新一张可用的旧版",
                         actor=f"takes_ui.reject（{body.by or '界面'}）")
            act = clean[-1]["n"]
        else:
            P.clear_active(shot_id, stage, f"v{n} 标了不要，没有可用的旧版，清空当前", actor=f"takes_ui.reject（{body.by or '界面'}）")
            (P.shot_dir(shot_id) / ("frame.png" if stage == "image" else "last.png")).unlink(missing_ok=True)
    _invalidate()
    return {"was_active": was, "active": act}


class UnrejectBody(BaseModel):
    restore_active: bool = False


@router.post("/api/shots/{shot_id}/takes/{stage}/{n}/unreject")
def unreject(shot_id: str, stage: str, n: int, body: UnrejectBody):
    """撤销“不要”：去掉标记；restore_active=true 时恢复成当前版本"""
    if stage not in STAGES:
        raise HTTPException(400, "只能撤首帧 / 尾帧")
    P = _P()
    with P.shot_lock(shot_id):
        data = P.load_takes(shot_id)
        t = next((x for x in data.get("takes") or [] if x.get("stage") == stage and x.get("n") == n), None)
        if not t:
            raise HTTPException(404, "没有这个版本")
        (t.get("params") or {}).pop("rejected", None)
        P._save_takes(shot_id, data)
    if body.restore_active:
        P.set_active(shot_id, stage, n)
    _invalidate()
    return P.load_takes(shot_id)


def _invalidate():
    try:
        from ns_api.app import _summary_cache  # noqa: PLC0415
        _summary_cache.invalidate()
    except Exception:  # noqa: BLE001
        pass


# ------------------------------------------------------------------ 再生成（项目方 11-01 原话：“添加一个生成按钮,基于现在再生成一个新的图”）

class RegenBody(BaseModel):
    by: str | None = None              # 画布点的 = None（资料闸门只提示不拦）
    gpu: int | str | None = None
    seed: int | None = None            # 测试用；不给 = 随机新 seed（保证和这一版不同）
    # 项目方 11-01 第二句：“弹出需求提示词输入框,upload对应的装备(衣服,鞋子,视频,美甲等)图片,然后生图”
    instruction: str | None = None     # 这次的要求（给了 → 在这一版上按要求改；同时给了装备图 → 换参考再改）
    refs: list[dict] | None = None     # 装备参考图 [{path, role, label}]；上传已由前端先登记进资产库（人物 + 类别）


def regen_body(t: dict, stage: str, n: int, seed: int) -> dict:
    """以这一版为父版本，同提示词 / 同参考 / 同参数、换 seed 再出一版。按这一版是怎么来的决定 mode：
    改图版本（instruct / refs）→ 同一个父版本、同一句修改要求、同一档幅度、同一组参考，再改一次；
    整张出的（regen / 流水线 / 唯一出图路径）→ mode=regen、parent=这一版，提示词按剧本重新编译（唯一出图路径），
    旧路径里当时整段替换过提示词（basis_prompt 有值）的照原提示词。新版本进版本链，旧版本保留；
    过契约才设为当前（G3，由 frame_jobs / auto_current 负责，这里不设当前）"""
    api_stage = "first" if stage == "image" else "last"
    mode = t.get("mode") if t.get("mode") in ("instruct", "refs") else "regen"
    if mode == "regen":
        b = {"stage": api_stage, "mode": "regen", "parent": n, "seed": seed}
        if t.get("basis_prompt") and t.get("prompt"):
            b["prompt"] = t["prompt"]
        prm = t.get("params") if isinstance(t.get("params"), dict) else {}
        if prm.get("preset"):
            b["preset"] = prm["preset"]
        return b
    b = {"stage": api_stage, "mode": mode, "parent": t.get("parent"), "instruction": t.get("instruction") or t.get("prompt") or "",
         "seed": seed}
    if t.get("strength") in ("small", "medium", "large"):
        b["strength"] = t["strength"]
    refs = [{"path": r.get("path"), "role": r.get("role") or "item"} for r in (t.get("refs") or []) if isinstance(r, dict) and r.get("path")]
    if refs:
        b["refs"] = refs
    return b


@router.post("/api/shots/{shot_id}/takes/{stage}/{n}/regen")
def regen(shot_id: str, stage: str, n: int, body: RegenBody):
    """“↻ 再生成”：基于这一版再出一张新的（新 seed），返回出图任务 {job_id…, regen_of, mode, seed}。
    不给 instruction / refs = 同提示词同参考同参数换 seed；给了 = 在这一版上按要求 / 换装备参考再改"""
    if stage not in STAGES:
        raise HTTPException(400, "只能再生成首帧 / 尾帧")
    import random

    from ns_api import frame_jobs as FJ  # noqa: PLC0415
    P = _P()
    t = next((x for x in P.load_takes(shot_id).get("takes") or [] if x.get("stage") == stage and x.get("n") == n), None)
    if not t:
        raise HTTPException(404, "没有这个版本")
    seed = body.seed
    if seed is None:
        old = t.get("seed")
        seed = random.randint(1, 2**47)
        while str(seed) == str(old):
            seed = random.randint(1, 2**47)
    instr = (body.instruction or "").strip()
    given = [r for r in body.refs or [] if isinstance(r, dict) and r.get("path")]
    refs = [{"path": r["path"], "role": r.get("role") or "item"} for r in given]
    if refs or instr:
        # 有要求 / 有装备图：以这一版为父版本改图（同一条编辑链，契约参考沿用父版本槽位，过契约才设当前）
        labels = "、".join(f"{r.get('label') or '装备'}（图{i + 2}）" for i, r in enumerate(given))
        if refs and not instr:
            instr = f"把图1人物身上对应的{labels}换成参考图里的样子（款式、颜色、材质、细节一致），其余人物、场景、机位、光线保持不变"
        elif refs:
            instr = f"{instr}（参考：{labels}）"
        b = {"stage": "first" if stage == "image" else "last", "mode": "refs" if refs else "instruct", "parent": n,
             "instruction": instr, "seed": seed, **({"refs": refs} if refs else {})}
    else:
        b = regen_body(t, stage, n, seed)
    if body.gpu is not None:
        b["gpu"] = body.gpu
    if body.by:
        b["by"] = body.by
    out = FJ.create_frame_job(shot_id, FJ.FrameJobBody(**b))
    return {**(out if isinstance(out, dict) else {"job": out}), "regen_of": n, "mode": b["mode"], "seed": seed}


@router.get("/api/shots/{shot_id}/takes/{stage}/{n}/checks")
def take_checks(shot_id: str, stage: str, n: int):
    """UIRSI r43（总调度 02:2x 详情抽屉“检查结果”两列表）：这一版的出图检查逐项结论，只读。
    来源：takes.json 这一版的 postflight.items（Q1 身份 / Q2 造型 / Q3 景别 …，GEN_CONTRACT 后检）+ 最后一轮看图判定 params.vqa_rounds[-1].judge。
    → {items: [{id, title, status: pass|fail|warn|untested|…, detail}], judge: {verdict, reasons[]} | None}"""
    if stage not in STAGES:
        raise HTTPException(400, "只有首帧 / 尾帧有检查结果")
    P = _P()
    t = next((x for x in P.load_takes(shot_id).get("takes") or [] if x.get("stage") == stage and x.get("n") == n), None)
    if not t:
        raise HTTPException(404, "没有这个版本")
    pf = t.get("postflight") if isinstance(t.get("postflight"), dict) else {}
    items = [{"id": it.get("id"), "title": it.get("title") or it.get("id"), "status": it.get("status"), "detail": it.get("detail") or ""}
             for it in pf.get("items") or [] if isinstance(it, dict)]
    rounds = (t.get("params") or {}).get("vqa_rounds") if isinstance(t.get("params"), dict) else None
    j = ((rounds[-1] or {}).get("judge") or {}) if rounds else {}
    judge = {"verdict": j.get("verdict"), "reasons": [str(x) for x in (j.get("reasons") or [])][:4],
             "failed": [str(x) for x in (j.get("failed_checks") or [])]} if j else None
    # 出场人物的身份相似度（Q1 ArcFace 余弦，cid → 值），详情抽屉“出场人物”一栏用
    q1 = next((it for it in pf.get("items") or [] if isinstance(it, dict) and it.get("id") == "Q1"), None)
    sims = ((q1 or {}).get("evidence") or {}).get("sims") if isinstance((q1 or {}).get("evidence"), dict) else None
    return {"shot": shot_id, "stage": stage, "n": n, "items": items, "judge": judge,
            "identity": {str(k): v for k, v in sims.items() if isinstance(v, (int, float))} if isinstance(sims, dict) else {}}
