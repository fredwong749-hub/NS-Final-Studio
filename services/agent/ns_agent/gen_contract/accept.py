"""共用验收（PRODMERGE-O 11-03，PLAN_V2_MASTER v4 1-5，L-151）：golden_v2 的出图后判定并进契约 postflight，producer 出图 /
定稿档（final_tier.render_final）/ 以后任何出图入口都用这一份，不再各写一套。

一张已出的图（postflight 已打完分）→ evaluate()：
  ① Q9 本地看图复核：远端打分没带（untested）→ ensure_q9 在笔记本补跑一次（图只进自有机器，K-REV-V01）；排队超时再要一次
  ② anomaly 人数 / 头数 / 手数（tools/vqa/anomaly.check）
  ③ 合并看图 bundle（tools/pipeline/asset_checks.bundle_check）：本镜核对项（check_items：人数 + 人物 + 造型单品 + 场景 + 景别 + 分镜描述，
     全部从本镜编译结果动态生成，不写死服装 / 场景）+ 年龄观感 + OCR，一次问完
  ④ judge_bundle → verdict 三态：pass / reject（任何一项判了 fail，逐项写原因）/ retry（没有 fail、只是有项没拿到结论——
     Q9 排队超时、合并看图没答、Q1 没打出分：**不判 fail**，同一张图重新复核，不重出、不换种子、不算一次尝试）
apply() 把结论写回 postflight：加一项 QB；reject → ok=False、blocking 加 QB；retry → accept_retry=True + score_infra=True
（producer 已有的“只重打分、不计次”通道）。

开关：config/pipeline/producer.json accept.enabled；只对资产包模式的剧（runs.json 有 assets_manifest、不是 legacy）生效——
V1 的 Q 口径不变（REVIEW_GLOBAL_OPUS F.1）。
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
CFG = "config/pipeline/producer.json"
DEFAULT = {"enabled": True, "scope": "asset_bundle_runs", "max_rechecks": 2}
_MODS: dict = {}


def _load(name: str, rel: str, root: Path = ROOT):
    key = (name, str(root))
    if key not in _MODS:
        src = root / rel if (root / rel).is_file() else ROOT / rel      # 临时根（测试 / 演练）没有工具文件 → 用本仓库的
        if str(src.parent) not in sys.path:
            sys.path.insert(0, str(src.parent))
        sp = importlib.util.spec_from_file_location(f"{name}_{abs(hash(str(src)))}", src)
        m = importlib.util.module_from_spec(sp)
        sp.loader.exec_module(m)
        _MODS[key] = m
    return _MODS[key]


def config(root: Path = ROOT) -> dict:
    try:
        d = json.loads((root / CFG).read_text(encoding="utf-8")).get("accept") or {}
    except (OSError, ValueError):   # arch-ok: 没有配置 = 默认（开、只对资产包剧）
        d = {}
    return {**DEFAULT, **d}


def enabled(run: str | None, root: Path = ROOT) -> bool:
    """资产包模式的剧才走共用验收（V1 legacy / 没登记清单的剧 = False，口径不变）"""
    if not run or not config(root).get("enabled"):
        return False
    try:
        R = _load("runs_for_accept", "tools/autopilot/runs.py", root)
        return not R.is_legacy(run, root) and R.asset_manifest(run, root) is not None
    except Exception:  # noqa: BLE001  # arch-ok: 登记表读不到 = 不加判（postflight 原口径照旧，失败不放宽）
        return False


# ------------------------------------------------------------------ Q9
def q9_timeout(post: dict) -> bool:
    """Q9 没拿到看图结论（排队超时 / 没跑：evidence 里没有 model）= 不是图的问题 → retry，不判 fail（asset_worker.q9_queue_timeout 同口径）"""
    q9 = next((i for i in (post or {}).get("items") or [] if i.get("id") == "Q9"), None)
    return bool(q9 is None or (q9.get("status") in ("untested", None) and not (q9.get("evidence") or {}).get("model")))


def ensure_q9(post: dict, img: str, job: dict) -> dict:
    """远端打分不带本地看图复核（Q9 untested）时，在笔记本补跑一次（图只进本地 Qwen3-VL，K-REV-V01），替换 Q9 项（原 golden_v2.ensure_q9）"""
    from . import postflight as PO
    items = (post or {}).get("items") or []
    q9 = next((i for i in items if i.get("id") == "Q9"), None)
    if q9 and q9.get("status") not in ("untested", None):
        return post
    VQ = PO._vqa()
    if VQ is None:
        return post
    req = {k: job.get(k) for k in ("cast", "asset_refs", "prompt", "refs")}
    v = VQ.cached_for(img) or PO._q9_live(VQ, img, req)
    if v is None:                                   # _q9_live 只认 data/renders/epNN/SN 下的图；别处的图直接调本地看图
        from ..vqa import client as VC
        v = VC.inspect_image(img, job.get("prompt") or "", list(job.get("refs") or []), wait_s=900)
    st, d, ev = PO._q9_item(VQ, VQ.q9(v))
    new = {"id": "Q9", "title": (q9 or {}).get("title") or "本地看图复核", "status": st, "detail": d, "evidence": ev}
    post = dict(post or {})
    post["items"] = [i for i in items if i.get("id") != "Q9"] + [new]
    return post


# ------------------------------------------------------------------ 本镜核对项（原 golden_v2.check_items）
def _g(o, k, d=None):
    return o.get(k, d) if isinstance(o, dict) else getattr(o, k, d)


def check_items(job: dict, shot, looks: dict | None = None, run: str | None = None) -> list[str]:
    """人数 + 人物 + 造型单品 ← job.asset_refs.characters + 造型表（asset_refs.load_looks）；场景 ← 本镜 scene_id + scene_detail；
    景别 ← asset_refs.size；分镜描述 ← 本镜 img_prompt。造型缺单品登记时如实写，不拿别的顶替（ISS-1103-003851-4541）"""
    ar = job.get("asset_refs") or {}
    on = [c for c in ar.get("characters") or [] if (c.get("presence") or "在画") == "在画"]
    if looks is None:
        from .. import asset_refs as AR
        looks = AR.load_looks(run)
    names = "、".join(c.get("name") or c.get("character") or "?" for c in on) or "无人"
    items = [f"画面里恰好 {len(on)} 个人（{names}），每个人都是成年人"]
    zones = set(ar.get("zones") or [])        # 编译器判定的可见部位：鞋 / 配饰 / 美甲不在画就不核，服装本体总是核
    for c in on:
        name, lid = c.get("name") or c.get("character"), c.get("look")
        lk = (looks.get(c.get("character")) or {}).get(lid) if lid else None
        parts = [p.label for p in (lk.parts if lk else []) if not getattr(p, "extra", False)
                 and (not zones or getattr(p, "slot", "outfit") == "outfit" or getattr(p, "zone", None) in zones)]
        if parts:
            items.append(f"{name}的穿着与造型 {lid} 一致：{'；'.join(parts)}")
        else:
            items.append(f"{name}的造型 {lid or '未定'} 在造型表里没有单品登记：只核对穿着与分镜描述一致")
    sid, sdet = _g(shot, "scene_id"), _g(shot, "scene_detail")
    items.append(f"场景是 {sid or '未登记场景'}" + (f"：{sdet}" if sdet else ""))
    if ar.get("size"):
        items.append(f"景别是{ar['size']}")
    items.append(f"画面内容与下面这段分镜描述一致（姿势、视线、手里的物件）：{_g(shot, 'img_prompt') or ''}")
    items += ["画面里没有文字、水印、logo", "手指数量正常、没有多出来的手"]
    return items


# ------------------------------------------------------------------ 判定（原 golden_v2.judge_bundle / verdict）
def judge_bundle(post: dict, an: dict, bundle: dict) -> tuple[dict, dict]:
    """identity = Q1；outfit = Q2（判了就用它；Q2=na 用合并看图第 2 条 = 第一个在画人物的造型）；prompt = 合并看图逐条核对；
    count = anomaly；vlm_review = Q9（na = 只记录不阻断，算过）；age / ocr = 合并看图的年龄观感 / 读字"""
    items = {i.get("id"): i for i in (post or {}).get("items") or []}
    q2 = (items.get("Q2") or {}).get("status", "untested")
    rows = bundle.get("items") or []
    b2 = ("pass" if rows[1].get("ok") else "fail") if len(rows) >= 2 and bundle.get("status") != "untested" else "untested"
    q9 = str((items.get("Q9") or {}).get("status"))
    lab = {"identity": (items.get("Q1") or {}).get("status", "untested"),
           "outfit": q2 if q2 in ("pass", "fail") else b2,
           "prompt": bundle.get("status") or "untested",
           "count": {"pass": "pass", "fail": "fail", "na": "na"}.get(str(an.get("status")), "untested"),
           "vlm_review": {"pass": "pass", "na": "pass", "fail": "fail"}.get(q9, "untested"),
           "age": (bundle.get("age") or {}).get("status") or "untested",
           "ocr": (bundle.get("ocr") or {}).get("status") or "untested"}
    src = {"outfit": "Q2" if q2 in ("pass", "fail") else "合并看图第 2 条（Q2=na：清单造型没有设定图，单品行不可比）"}
    return lab, src


def verdict(post: dict, lab: dict, bundle: dict) -> tuple[str, list[str]]:
    """→ (pass | reject | retry, 原因)。retry = 没有一项 fail、只是有项没拿到结论（不判 fail，重新复核同一张图）"""
    reasons = [f"{k}={v}" for k, v in lab.items() if v not in ("pass", "na")]
    by_id = {i.get("id"): i for i in (post or {}).get("items") or []}
    for qid in ("Q1", "Q9"):
        q = by_id.get(qid)
        if q and q.get("status") not in ("pass", "na"):
            reasons.append(f"{qid}：{str(q.get('detail') or q.get('status'))[:100]}")
    for it in bundle.get("items") or []:
        if not it.get("ok"):
            reasons.append(f"看图第{it.get('n')}条：{str(it.get('text') or '')[:80]}")
    if (bundle.get("age") or {}).get("status") == "fail":
        reasons.append(f"年龄：{str(bundle['age'].get('text'))[:60]}")
    if (bundle.get("ocr") or {}).get("status") == "fail":
        reasons.append(f"读到文字：{str(bundle['ocr'].get('text'))[:60]}")
    if bundle.get("error"):
        reasons.append(f"合并看图出错：{str(bundle['error'])[:80]}")
    if all(v in ("pass", "na") for v in lab.values()):
        return "pass", []
    if not any(v == "fail" for v in lab.values()):
        return "retry", ["没拿到结论（看图 / 打分服务排队或超时），重试复核：" + "、".join(reasons)]
    return "reject", reasons


def evaluate(img: str, post: dict, job: dict, shot, run: str, *, q9_fn=None, anomaly_fn=None, bundle_fn=None,
             looks: dict | None = None, root: Path = ROOT) -> dict:
    """一张已打完 postflight 的图过共用验收 → {status, label, label_source, reasons, check_items, anomaly, bundle, post}。
    各外部服务可注入（测试）；默认 = 本地看图 / gpu36 anomaly / 本地合并看图"""
    q9_fn = q9_fn or ensure_q9
    post = q9_fn(post, img, job)
    if q9_timeout(post):
        post = q9_fn(post, img, job)
    on = [c for c in (job.get("asset_refs") or {}).get("characters") or [] if (c.get("presence") or "在画") == "在画"]
    if on:
        if anomaly_fn is None:
            anomaly_fn = _load("anomaly_for_accept", "tools/vqa/anomaly.py", root).check
        an = anomaly_fn(img, [{"name": c.get("name"), "presence": "在画", "faced": True, "x": c.get("x") or "中"}
                              for c in job.get("cast") or [] if (c.get("presence") or "在画") == "在画"], host="gpu36")
    else:
        an = {"status": "na", "note": "空镜 / 物件：不判人数"}
    items = check_items(job, shot, looks, run)
    if bundle_fn is None:
        bundle_fn = _load("asset_checks_for_accept", "tools/pipeline/asset_checks.py", root).bundle_check
    bundle = bundle_fn(img, items, bool(on))
    lab, src = judge_bundle(post, an, bundle)
    status, reasons = verdict(post, lab, bundle)
    return {"status": status, "label": lab, "label_source": src, "reasons": reasons, "check_items": items, "anomaly": an,
            "bundle": {k: bundle.get(k) for k in ("status", "text", "items", "age", "ocr", "error", "summary")}, "post": post}


def apply(pf: dict, acc: dict) -> dict:
    """把共用验收结论写回 postflight（同一份 dict，原地改并返回）：Q9 用补跑后的；加 QB；reject 不过；retry 走只重打分"""
    post = acc.get("post") or {}
    q9 = next((i for i in post.get("items") or [] if i.get("id") == "Q9"), None)
    items = [i for i in (pf.get("items") or []) if i.get("id") not in ("QB",) and not (q9 and i.get("id") == "Q9")]
    if q9:
        items.append(q9)
    st = {"pass": "pass", "reject": "fail", "retry": "untested"}[acc["status"]]
    items.append({"id": "QB", "title": "共用验收（看图逐条 + 年龄 + OCR + 人数，PRODMERGE-O）", "status": st,
                  "detail": "；".join(acc.get("reasons") or [])[:400],
                  "evidence": {k: acc.get(k) for k in ("label", "label_source", "check_items", "anomaly", "bundle")}})
    pf["items"] = items
    pf["accept"] = {"status": acc["status"], "label": acc.get("label"), "reasons": acc.get("reasons")}
    if acc["status"] == "reject":
        pf["ok"] = False
        pf["blocking"] = sorted(set(pf.get("blocking") or []) | {"QB"})
        pf.setdefault("reasons", []).extend(acc.get("reasons") or [])
    elif acc["status"] == "retry":
        pf["accept_retry"] = True
        pf["score_infra"] = True          # producer：图已入库，只重打分、不重出、不计次
    return pf


def accept(file_rel: str, job: dict, host: str | None, shot, run: str, *, post: dict | None = None, data_dir: Path | None = None,
           **kw) -> dict:
    """完整一步（定稿档等没有自己打分的入口用）：postflight（unified_frame._postflight）→ evaluate → apply → 返回 postflight"""
    if post is None:
        from ns_render import unified_frame as UF
        post = UF._postflight(file_rel, job, host)
    if data_dir is None:
        from ns_render import pipeline as P
        data_dir = P.DATA
    pf = dict(post or {})
    if not enabled(run, kw.get("root", ROOT)):
        return pf
    acc = evaluate(str(Path(data_dir) / file_rel), pf, job, shot, run, **kw)
    return apply(pf, acc)


__all__ = ["accept", "apply", "check_items", "config", "enabled", "ensure_q9", "evaluate", "judge_bundle", "q9_timeout", "verdict"]
