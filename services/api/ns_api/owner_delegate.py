"""代选模式（L-136，项目方 11-03 02:2x 原话：“你代替我选择，我睡觉了，我希望看到全部 ep，同时看到系统变得自动化。”）。

开关 config/pipeline/owner_delegate.json（enabled / authority / expiry / scope）。:8800 正式实例启动后起一个后台线程，每 interval_s 秒：
  ① 到期检查：data/audit 里 enabled_at 之后有登录项目方的写请求（2xx，ignore_paths 除外）= 项目方在网页上做了决定 → 自动关闭；
     项目方在 #/queue 点“撤销” / CLI revoke 也关闭。关闭后一条都不再代。
  ② pick 代选：data/owner_queue/requests.json 里 face / scene / voice / sheet / item / look 的待选（统一入口 wired、项目方没动过），
     按分数选最优，走 owner_pick.accept + owner_pick.process（与项目方本人点选同一条登记链），by=总调度代选，via=delegate:L-136。
     条目留在通知里，显示“已代选：候选 N（可修改）”；项目方点“修改”/ 改选 = 原有修改机制（owner_pick.accept 里转成 revise）。
  ③ 写作闸门代选：P1（等项目方看 / 低于门槛转项目方定方向）与各集 awaiting_owner 闸门：评委均分 ≥ gate.min_mean 且没有任何一项 ≤ gate.max_low_item
     → owner_gate.act(approve, delegate=…)；不满足：普通闸门 = 带评委意见退回补丁环（revise），owner_direction 状态 = 不放行、只登记卡点
     （在 owner_direction 下点“修改”会被 autoflow 记成“项目方接手”，代选不能冒充项目方）。
硬规定（写死，配置打不开）：成人相关条目、删除 / 花钱 / 推翻旧审美 / 导入新季（kind=decide）、项目方动过的条目、escalate / owner_direction 升级，一律不代。
审计：每次代选（含跳过原因，同一原因只记一次）追加 data/owner_queue/delegate_log.jsonl；汇总页 data/review_pages/delegate/index.html。

接口：GET /api/owner/delegate（状态，网页横幅用）· POST /api/owner/delegate/revoke（登录项目方一键撤销）
④ 首帧超时代选（L-142 常设，W18）：主剧首帧过“出图检测”、项目方 first_frame.timeout_min 分钟没定 → 按契约分 + bundle 顺序定稿，标“系统代选·可改”
   （与画布同一定稿入口 frame_jobs.lock_take，L-147 定稿档按 final_tier.auto_final_on_lock 自动接上）；不受 L-136 开关影响，硬规定同上。
CLI：python services/api/ns_api/owner_delegate.py status | enable | revoke | tick | page | frames [--dry]
"""
from __future__ import annotations

import glob
import html
import importlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

REPO = Path(__file__).resolve().parents[3]
_CODE_ROOT = REPO
router = APIRouter(tags=["owner-delegate"])
_lock = threading.Lock()

CFG_REL = Path("config/pipeline/owner_delegate.json")
LOG_REL = Path("data/owner_queue/delegate_log.jsonl")
SEEN_REL = Path("data/owner_queue/delegate_seen.json")
PAGE_REL = Path("data/review_pages/delegate/index.html")
BY = "总调度代选"
VIA = "delegate:L-136"
PICK_KINDS = ("face", "scene", "voice", "sheet", "item", "look", "golden")   # golden：总调度 11-03 裁定 ISS-1103-023748-abe6 纳入
ALIASES = {"voice_v2": "voice", "image": "face"}
ADULT_WORDS = ("成人", "adult", "nsfw", "情色", "裸")
NEVER_CATEGORIES = ("spend", "license", "delete", "overturn", "import_season")
ADVANCE_STATUSES = ("preparing", "active", "producing")


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _atomic_json(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=p.name + ".", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(obj, ensure_ascii=False, indent=1) + "\n")
    os.replace(tmp, p)


def _read_json(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


# ------------------------------------------------------------------ 开关 / 到期
def load_cfg(root: Path = REPO) -> dict:
    d = _read_json(Path(root) / CFG_REL, None)
    return d if isinstance(d, dict) else {"enabled": False}


def _save_cfg(root: Path, d: dict) -> None:
    _atomic_json(Path(root) / CFG_REL, d)


def owner_decision_since(root: Path, since: str, ignore: list[str] | tuple = ()) -> dict | None:
    """enabled_at 之后第一条“项目方在网页上做的决定”：data/audit/*.jsonl 里 role=owner、写请求、2xx、路径不在 ignore 里"""
    if not since:
        return None
    day = since[:10].replace("-", "")
    for f in sorted(glob.glob(str(Path(root) / "data" / "audit" / "*.jsonl"))):
        if Path(f).stem < day:
            continue
        try:
            lines = Path(f).read_text(encoding="utf-8").splitlines()
        except OSError as e:
            print(f"[owner_delegate] 审计日志 {f} 读不了：{e}（这一天的决定看不到）", file=sys.stderr)
            continue
        for ln in lines:
            try:
                r = json.loads(ln)
            except ValueError:
                r = None   # 坏行 / 写到一半的尾行 = 不是一条决定
            if not isinstance(r, dict) or r.get("role") != "owner" or str(r.get("method", "")).upper() in ("GET", "HEAD", "OPTIONS"):
                continue
            if str(r.get("at", "")) <= since:
                continue
            try:
                ok = 200 <= int(r.get("status") or 0) < 300
            except (TypeError, ValueError):
                ok = False
            path = str(r.get("path") or "")
            if ok and not any(path.startswith(p) for p in ignore):
                return r
    return None


def _close(root: Path, cfg: dict, reason: str, kind: str) -> dict:
    cfg = {**cfg, "enabled": False}
    cfg["expiry"] = {**(cfg.get("expiry") or {}), "expired_at": _now(), "expired_reason": reason, "expired_kind": kind}
    _save_cfg(root, cfg)
    log(root, {"event": "closed", "kind": kind, "reason": reason})
    render_page(root)
    return cfg


def active(root: Path = REPO) -> tuple[bool, str]:
    """代选现在是否生效（顺带做到期检查：到期 = 把 enabled 写成 false，留原因）"""
    cfg = load_cfg(root)
    if not cfg.get("enabled"):
        return False, (cfg.get("expiry") or {}).get("expired_reason") or "开关没开"
    if not cfg.get("enabled_at"):
        return False, "开关开着但没有 enabled_at（不知道从哪一刻起算到期），不代选"
    exp = cfg.get("expiry") or {}
    if exp.get("on_owner_decision", True):
        r = owner_decision_since(root, str(cfg["enabled_at"]), exp.get("ignore_paths") or [])
        if r:
            why = f"项目方 {r.get('at')} 在网页上做了决定（{r.get('method')} {r.get('path')}），代选到期自动关闭"
            _close(root, cfg, why, "owner_decision")
            return False, why
    return True, ""


def enable(root: Path = REPO, by: str = "总调度") -> dict:
    cfg = load_cfg(root)
    cfg.update(enabled=True, enabled_at=_now(), enabled_by=by)
    cfg["expiry"] = {**(cfg.get("expiry") or {}), "expired_at": None, "expired_reason": None, "expired_kind": None}
    _save_cfg(root, cfg)
    log(root, {"event": "enabled", "by": by, "authority": (cfg.get("authority") or {}).get("ledger")})
    render_page(root)
    return cfg


def revoke(root: Path = REPO, by: str = "项目方", why: str = "") -> dict:
    cfg = load_cfg(root)
    if not cfg.get("enabled"):
        return cfg
    return _close(root, cfg, f"{by} 撤销代选" + (f"：{why}" if why else ""), "revoked")


# ------------------------------------------------------------------ 审计
def log(root: Path, row: dict) -> dict:
    p = Path(root) / LOG_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    row = {"at": _now(), "by": BY, "via": VIA, **row}
    with _lock, p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def log_rows(root: Path = REPO) -> list[dict]:
    out = []
    try:
        lines = (Path(root) / LOG_REL).read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        lines = []   # 还没有代选记录（显式默认）
    except OSError as e:
        print(f"[owner_delegate] {LOG_REL} 读不了：{e} → 按无记录", file=sys.stderr)
        lines = []
    for ln in lines:
        try:
            r = json.loads(ln)
        except ValueError:
            r = None   # 坏行跳过
        if isinstance(r, dict):
            out.append(r)
    return out


def _skip_once(root: Path, item_id: str, reason: str, extra: dict | None = None) -> None:
    """跳过原因同一条同一原因只记一次（每拍都跑，不刷屏）"""
    p = Path(root) / SEEN_REL
    seen = _read_json(p, {})
    if seen.get(item_id) == reason:
        return
    seen[item_id] = reason
    _atomic_json(p, seen)
    log(root, {"event": "skip", "item": item_id, "reason": reason, **(extra or {})})


# ------------------------------------------------------------------ 硬规定
def never_reason(req: dict) -> str | None:
    """不在授权范围内的条目（写死）：成人相关、拍板类（删除 / 花钱 / 推翻旧审美 / 下载许可 / 导入新季）"""
    if req.get("kind") != "pick":
        return "不是挑选类（拍板 / 抽检 / 升级不代选）"
    if str(req.get("category") or "") in NEVER_CATEGORIES:
        return f"拍板类（{req.get('category')}）不代选"
    if req.get("adult") or req.get("route") == "local_only":
        return "成人相关（只能项目方本人）"
    for c in req.get("candidates") or []:
        if isinstance(c, dict) and (c.get("adult") or c.get("route") == "local_only"):
            return "候选里有成人 / 本地专用资产（只能项目方本人）"
    for pp in req.get("people") or []:
        if isinstance(pp, dict) and (pp.get("adult") or "成人" in str(pp.get("thumb_note") or "")):
            return "本集有成人造型（只能项目方本人）"
    text = " ".join(str(req.get(k) or "") for k in ("id", "title", "detail", "source", "why")).lower()
    if any(w in text for w in ADULT_WORDS):
        return "条目文字涉及成人内容（只能项目方本人）"
    return None


# ------------------------------------------------------------------ 打分
def _v(s) -> float:
    return {"pass": 1.0, "na": 0.5}.get(str(s or "").lower(), 0.0)


def _cand_record(root: Path, c: dict) -> dict:
    f = str(c.get("file") or "")
    if not f:
        return {}
    d = _read_json((Path(root) / f).with_suffix(".json"), {})
    return d if isinstance(d, dict) else {}


def image_parts(root: Path, c: dict) -> dict:
    """一张候选图的分项：identity（身份余弦 / 标签）、age（年龄观感）、q9（本地看图缺陷）、vlm（看图逐项通过率）、faces（检出人脸数）、fails"""
    rec = _cand_record(root, c)
    lab = {**(rec.get("label") if isinstance(rec.get("label"), dict) else {}),       # 候选记录的检查标签（asset_worker 出图记录）
           **(c.get("checks") if isinstance(c.get("checks"), dict) else {})}          # 旧式候选（CAST-S v2cast-*）直接带 checks；c.label 是给人看的名字
    pf = {i.get("id"): i for i in ((rec.get("postflight") or {}).get("items") or []) if isinstance(i, dict)}
    q1 = pf.get("Q1") or {}
    ev = q1.get("evidence") or {}
    sims = [float(v) for v in (ev.get("sims") or {}).values() if isinstance(v, (int, float))]
    identity = max(sims) if sims else _v(lab.get("identity"))
    vlm = rec.get("vlm") or {}
    age_s = (vlm.get("age") or {}).get("status") or lab.get("age")
    q9i = pf.get("Q9") or {}
    q9_s = q9i.get("status") or lab.get("q9")
    defects = len((q9i.get("evidence") or {}).get("defects") or [])
    its = [x for x in (vlm.get("items") or []) if isinstance(x, dict)]
    ratio = (sum(1 for x in its if x.get("ok")) / len(its)) if its else _v(lab.get("prompt_vlm"))
    fails = sorted(k for k in ("age", "q9", "prompt_vlm", "count", "ocr", "identity") if str(lab.get(k) or "") == "fail")
    if str(age_s or "") == "fail" and "age" not in fails:
        fails.append("age")
    faces = ev.get("faces") if isinstance(ev.get("faces"), int) else None
    return {"identity": round(identity, 4), "age": _v(age_s), "q9": round(max(0.0, _v(q9_s) - 0.1 * defects), 4),
            "vlm": round(ratio, 4), "faces": faces, "fails": fails}


def voice_parts(root: Path, req: dict, c: dict) -> dict:
    """voice_v2 check 分：逐项通过率 + (1 − CER)；读候选目录 meta.json 的 checks（tools/v2style/voice_v2.py check 写的）"""
    role = str(req.get("id")).split(":")[2] if str(req.get("id")).count(":") >= 2 else ""
    cfg = _read_json(Path(root) / "config" / "voices_v2.json", {})
    sup = (((cfg.get("support_candidates") or {}).get("roles") or {}).get(role) or {}).get("candidates") or []
    m = next((x for x in sup if str(x.get("cand")) == str(c.get("key"))), None)
    if not m:
        return {"fails": ["没有这个候选的 support_candidates 记录"], "check": 0.0}
    meta = _read_json(Path(root) / str(m.get("dir") or "_") / "meta.json", {})
    ck = (meta or {}).get("checks") or {}
    items = ck.get("items") or {}
    if not items:
        return {"fails": ["没有 voice_v2 check 结果"], "check": 0.0}
    ratio = sum(1 for v in items.values() if (v or {}).get("pass")) / len(items)
    cer = float(((items.get("cer") or {}).get("value")) or m.get("cer") or 0.0)
    return {"check": round(ratio, 4), "cer": cer, "fails": [] if ck.get("pass") else [k for k, v in items.items() if not (v or {}).get("pass")]}


def score_candidate(root: Path, kind: str, req: dict, c: dict) -> tuple[float | None, dict, str]:
    """→ (分数 | None=不可选, 分项, 不可选原因)"""
    if not c.get("contract_ok"):
        return None, {}, "没过契约"
    if kind == "voice":
        p = voice_parts(root, req, c)
        if p["fails"]:
            return None, p, "check 不过：" + "、".join(p["fails"])
        return round(p["check"] + (1.0 - min(1.0, p["cer"])), 4), p, ""
    if kind == "look":
        waits = [pp.get("wait") for pp in req.get("people") or [] if isinstance(pp, dict) and not pp.get("ready")]
        if not req.get("people") or waits:
            return None, {"waits": waits}, "本集资产没齐：" + "；".join(str(w) for w in waits if w)
        return 1.0, {"people": len(req["people"])}, ""
    p = image_parts(root, c)
    if p["fails"]:
        return None, p, "检查不过：" + "、".join(p["fails"])
    if kind == "scene":
        if (p["faces"] or 0) > 0:
            return None, p, f"场景底图里检出 {p['faces']} 张人脸（底图要无人）"
        return round(p["vlm"] + p["q9"], 4), p, ""
    if kind == "face":
        return round(p["identity"] + p["age"] + p["q9"] + p["vlm"], 4), p, ""
    if kind == "golden":                                                    # 金样首帧：契约分 + Q1 身份 + 看图通过率 + Q9
        return round(_contract_score(c) + p["identity"] + p["vlm"] + p["q9"], 4), p, ""
    return round(p["identity"] + p["vlm"] + p["q9"], 4), p, ""            # sheet / item：asset_worker.cand_score 同口径 + Q9


def _contract_score(c: dict) -> float:
    """候选自带的契约分（score / contract_score，0–1 之外的按 0 计入，避免出图顺序号冒充分数）"""
    for k in ("contract_score", "score"):
        v = c.get(k)
        if isinstance(v, (int, float)) and 0 <= float(v) <= 1:
            return float(v)
    return 1.0 if c.get("contract_ok") else 0.0


def choose(root: Path, kind: str, req: dict) -> dict:
    """→ {key, label, score, scores[], why} 或 {skip: 原因, scores[]}"""
    rows = []
    for i, c in enumerate(req.get("candidates") or []):
        if not isinstance(c, dict):
            continue
        s, parts, why = score_candidate(root, kind, req, c)
        rows.append({"key": str(c.get("key")), "label": c.get("label") or str(c.get("key")), "score": s, "parts": parts, "why": why, "i": i})
    ok = [r for r in rows if r["score"] is not None]
    if not ok:
        return {"skip": "没有可选的候选（" + "；".join(f"{r['key']}：{r['why']}" for r in rows) + "）" if rows else "没有候选", "scores": rows}
    rec = str(req.get("recommend") or "")
    best = max(ok, key=lambda r: (r["score"], r["key"] == rec, -r["i"]))
    why = {"face": "身份质量 + 年龄观感 + Q9 + 看图逐项通过率", "scene": "看图逐项通过率 + Q9，且底图无人", "voice": "voice_v2 check 逐项通过率 + (1 − CER)",
           "look": "本集资产齐全", "golden": "契约分 + Q1 身份 + 看图逐项通过率 + Q9", "sheet": "身份相似度 + 看图逐项通过率 + Q9", "item": "身份相似度 + 看图逐项通过率 + Q9"}[kind]
    return {"key": best["key"], "label": best["label"], "score": best["score"], "scores": rows,
            "why": f"按分数选最优（{why}）：{best['label']} = {best['score']}" + ("；与系统推荐一致" if best["key"] == rec else "")}


# ------------------------------------------------------------------ ② pick 代选
def _op():
    from ns_api import owner_pick as OP  # noqa: PLC0415
    return OP


def pending_picks(root: Path) -> list[dict]:
    """项目方还没动过、统一入口已接的挑选（requests.json；已关闭 / 已有任何状态的不算）"""
    from ns_api import owner_queue as OQ  # noqa: PLC0415
    OP = _op()
    closed = OQ._closed(Path(root), time.time())
    out = []
    for r in OQ.requests(Path(root)):
        iid = str(r.get("id"))
        if r.get("kind") != "pick" or iid in closed or not OP.wired(iid) or OP.state_of(Path(root), iid):
            continue
        if r.get("auto_picked") or r.get("notice"):    # 系统已按分数自动选用并登记（asset_worker.auto_pick 的“已自动选用，可修改”告知）：不再代选，免得重复登记
            continue
        out.append(r)
    return out


def pick_tick(root: Path, apply_fn=None) -> list[dict]:
    OP = _op()
    cfg = load_cfg(root)
    scope = set(cfg.get("scope") or PICK_KINDS)
    done = []
    for req in pending_picks(root):
        iid = str(req["id"])
        k = OP.kind_of(iid)
        kind = ALIASES.get(k, k)
        if kind not in PICK_KINDS or kind not in scope:
            _skip_once(root, iid, f"{kind or '未知'} 类不在代选范围")
            continue
        nr = never_reason(req)
        if nr:
            _skip_once(root, iid, nr, {"title": req.get("title")})
            continue
        ch = choose(root, kind, req)
        if ch.get("skip"):
            _skip_once(root, iid, ch["skip"], {"title": req.get("title"), "scores": ch["scores"]})
            continue
        reason = f"代选（L-136）：{ch['why']}"
        try:
            r = OP.accept(Path(root), iid, ch["key"], reason, BY)
        except HTTPException as e:
            _skip_once(root, iid, f"统一入口不收：{e.detail}")
            continue
        if r.get("duplicate"):
            continue
        OP._set_state(Path(root), iid, delegate={"at": _now(), "by": BY, "via": VIA, "choice": ch["key"], "label": ch["label"], "score": ch["score"],
                                                 "ledger": "L-136"})
        row = OP.process(Path(root), iid, ch["key"], BY, apply_fn, via=VIA)
        ent = log(root, {"event": "pick", "item": iid, "kind": kind, "title": req.get("title"), "choice": ch["key"], "label": ch["label"],
                         "score": ch["score"], "scores": [{k2: v for k2, v in s.items() if k2 != "i"} for s in ch["scores"]],
                         "reason": ch["why"], "state": row.get("state"), "error": row.get("error"),
                         "thumbs": {str(c.get("key")): c.get("thumb") or c.get("file") or c.get("audio") for c in req.get("candidates") or [] if isinstance(c, dict)}})
        done.append(ent)
    return done


# ------------------------------------------------------------------ ③ 写作闸门代选
def _og():
    sp = importlib.util.spec_from_file_location("owner_gate_for_delegate", _CODE_ROOT / "tools" / "script_rsi" / "owner_gate.py")
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


def judge_scores(root: Path, run_dir: Path, key: str) -> dict | None:
    """评委分：{round, sha, mean, item_mean, judge_items{judge:{item:score}}, top_fixes}。P1 = judge_p1/STATE.json；各集 = judge_epNN/STATE.json（有才算）"""
    sp = run_dir / ("judge_p1" if key == "P1" else f"judge_{key}") / "STATE.json"
    st = _read_json(sp, None)
    rounds = (st or {}).get("rounds") or []
    if not rounds:
        return None
    cur = rounds[-1]
    rdir = Path(root) / str(cur.get("dir") or "_none_")
    res = _read_json(rdir / "RESULT.json", None) or cur.get("result") or {}
    if res.get("mean") is None:
        return None
    jitems = {}
    for f in sorted(glob.glob(str(rdir / "judge_*" / "out" / "*.json"))):
        d = _read_json(Path(f), {})
        its = {str(i.get("id")): i.get("score") for i in (d.get("items") or []) if isinstance(i, dict)}
        if its:
            jitems[str(d.get("judge_id") or Path(f).parent.parent.name)] = its
    return {"round": cur.get("n"), "sha": cur.get("sha"), "mean": res.get("mean"), "totals": res.get("totals"),
            "item_mean": res.get("item_mean") or {}, "judge_items": jitems, "top_fixes": (res.get("top_fixes") or [])[:8]}


def gate_ok(js: dict, cfg: dict) -> tuple[bool, list[str]]:
    g = cfg.get("gate") or {}
    min_mean, low = float(g.get("min_mean", 30)), float(g.get("max_low_item", 2))
    why = []
    if float(js.get("mean") or 0) < min_mean:
        why.append(f"均分 {js.get('mean')} < {g.get('min_mean', 30)}")
    lows = [f"{k}={v}" for k, v in (js.get("item_mean") or {}).items() if isinstance(v, (int, float)) and v <= low]
    for j, its in (js.get("judge_items") or {}).items():
        lows += [f"{j}:{k}={v}" for k, v in its.items() if isinstance(v, (int, float)) and v <= low]
    if lows:
        why.append(f"有条目 ≤ {g.get('max_low_item', 2)}：" + "、".join(lows[:8]))
    return not why, why


def _spawn_autoflow(run_dir: Path, ep: int) -> dict:
    cmd = [sys.executable, str(_CODE_ROOT / "tools/script_rsi/autoflow.py"), "run", "--run-dir", str(run_dir), "--episode", str(ep),
           "--import", "dry", "--source", "daemon"]
    out = open(run_dir / "autoflow.stdout.log", "a", encoding="utf-8")
    p = subprocess.Popen(cmd, cwd=str(_CODE_ROOT), stdout=out, stderr=subprocess.STDOUT, env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
    return {"pid": p.pid}


def _report(run: str, ep: int, step: str, what: str, hint: str) -> str | None:
    try:
        sp = importlib.util.spec_from_file_location("report_issue_for_delegate", _CODE_ROOT / "tools" / "master" / "report_issue.py")
        m = importlib.util.module_from_spec(sp)
        sp.loader.exec_module(m)
        return m.report(run, ep, step, "DELEGATE（L-136 代选）", what, True, hint)["id"]
    except Exception as e:  # noqa: BLE001  登记失败只记进代选日志
        return f"登记失败：{e!r}"[:200]


def waiting_gates(root: Path) -> list[dict]:
    """每部在做的剧里等项目方的写作闸门：P1（awaiting_owner_p1 / owner_direction）+ 各集 awaiting_owner_*（导入除外）"""
    reg = _read_json(Path(root) / "config" / "pipeline" / "runs.json", {}).get("runs") or {}
    out = []
    for run, meta in sorted(reg.items()):
        if (meta or {}).get("status") not in ADVANCE_STATUSES:
            continue
        rd = Path(root) / "data" / "pipeline" / "runs" / run
        af = _read_json(rd / "autoflow.json", None)
        if not af or not ((rd / "owner_gates.json").exists() or (rd / "CLEAN_CUT.json").exists()):
            continue
        if af.get("verdict") in ("awaiting_owner_p1", "owner_direction"):
            out.append({"run": run, "run_dir": rd, "key": "P1", "ep": 1, "verdict": af.get("verdict")})
        for f in sorted(rd.glob("autoflow_ep*.json")):
            e = _read_json(f, {})
            v = str(e.get("verdict") or "")
            n = f.stem.replace("autoflow_ep", "")
            if n.isdigit() and v.startswith("awaiting_owner") and v not in ("awaiting_owner_p1",) and (e.get("awaiting") or "") != "import":
                out.append({"run": run, "run_dir": rd, "key": f"ep{int(n):02d}", "ep": int(n), "verdict": v})
    return out


def gate_tick(root: Path, spawn=None) -> list[dict]:
    cfg = load_cfg(root)
    if "gate" not in (cfg.get("scope") or []):
        return []
    OG = _og()
    spawn = spawn or _spawn_autoflow
    done = []
    for w in waiting_gates(root):
        rd, key, run = w["run_dir"], w["key"], w["run"]
        iid = f"gate:{run}:{key}"
        g = OG.get(rd, key)
        if g.get("status") not in (None, "pending"):
            continue                                   # 项目方 / 别人已经动过：不推翻
        js = judge_scores(root, rd, key)
        if not js:
            _skip_once(root, iid, "没有评委分，不代选（只按评委分放行）")
            continue
        sig = f"{js['round']}:{js['sha']}"
        if _read_json(Path(root) / SEEN_REL, {}).get(iid + "#sig") == sig:
            continue                                   # 这一稿已经处理过（放行 / 退回 / 登记过卡点）
        ok, why = gate_ok(js, cfg)
        deleg = {"at": _now(), "by": BY, "via": VIA, "ledger": "L-136", "round": js["round"], "mean": js["mean"], "sha": js["sha"]}
        row = {"item": iid, "kind": "gate", "run": run, "key": key, "verdict": w["verdict"], "mean": js["mean"], "totals": js.get("totals"),
               "item_mean": js["item_mean"], "judge_items": js["judge_items"]}
        if ok:
            try:
                OG.act(rd, key, "approve", "", BY, delegate=deleg)
            except (PermissionError, ValueError) as e:
                _skip_once(root, iid, f"闸门不收“用这版”：{e}")
                continue
            started = spawn(rd, w["ep"])
            done.append(log(root, {**row, "event": "gate_approve", "reason": f"评委均分 {js['mean']} ≥ {(cfg.get('gate') or {}).get('min_mean', 30)}、没有任何一项 ≤ 2 → 代选放行",
                                   "started": started}))
        elif w["verdict"] == "owner_direction":
            iss = _report(run, w["ep"], key, f"代选不放行 {key}（{'；'.join(why)}）；owner_direction 状态下代点“修改”会被记成项目方接手，代选不冒充，等项目方 / 总调度定",
                          "项目方醒来在 #/queue 定方向；或总调度决定是否让补丁环在 owner_direction 下以系统身份返修（要改 autoflow_agent）")
            done.append(log(root, {**row, "event": "gate_hold", "reason": "不放行：" + "；".join(why), "issue": iss}))
        else:
            note = "代选（L-136）不放行：" + "；".join(why) + "。按评委意见改：" + "；".join(js.get("top_fixes") or [])[:1500]
            try:
                OG.act(rd, key, "revise", note, BY, delegate=deleg)
            except (PermissionError, ValueError) as e:
                _skip_once(root, iid, f"闸门不收“修改”：{e}")
                continue
            started = spawn(rd, w["ep"])
            iss = _report(run, w["ep"], key, f"代选不放行 {key}（{'；'.join(why)}），已退回补丁环重写", "看下一稿评分")
            done.append(log(root, {**row, "event": "gate_revise", "reason": "不放行，退回补丁环：" + "；".join(why), "issue": iss, "started": started}))
        seen = _read_json(Path(root) / SEEN_REL, {})
        seen[iid + "#sig"] = sig
        _atomic_json(Path(root) / SEEN_REL, seen)
    return done


# ------------------------------------------------------------------ ④ 首帧超时代选（L-142，W18）
# 与 L-136 代选模式无关（L-136 到期后照样生效）：L-142 是项目方的常设点选——“ep01 首帧由系统代选（过检后），项目方事后可在 #/queue 修改”。
# 主剧每镜：首帧有版本过“出图检测”（与 sop_gate.shot_frames 同口径：postflight ok + Q9 pass + 没被驳回）、还没定稿、
# 项目方 first_frame.timeout_min 分钟（默认 30）内没定 → 按契约分（Q1 身份 + 合并看图逐条通过率）+ bundle 顺序（同分取先出的版本）选一版定稿，
# 标“系统代选·可改”（takes.json locked_by.image）；写 delegate_log.jsonl + delegate_frames.json + V2_LIVE。
# 定稿走 frame_jobs.lock_take（与画布定稿同一入口）→ L-147：final_tier.auto_final_on_lock(剧) 为 true 时自动排定稿档重出，定稿档过同一份共用验收。
# 硬规定（写死）：成人镜 / 成人或本地专用候选 / 拍板类一律 never_reason 拦；项目方动过这镜首帧（锁过 / 解锁过 / 撤过系统代选）不再代；只定稿，不删、不花钱。
FRAME_SEEN_REL = Path("data/owner_queue/delegate_frames.json")
FRAME_LEDGER = "L-142"
FRAME_LABEL = "系统代选·可改"
FRAME_DEFAULT = {"enabled": False, "timeout_min": 30}          # 配置缺 = 不代（失败关闭）；开关 owner_delegate.json first_frame.enabled


def _ts(s) -> float | None:
    try:
        return time.mktime(time.strptime(str(s)[:19], "%Y-%m-%dT%H:%M:%S"))
    except (TypeError, ValueError):
        return None


def _q9_ok(pf: dict) -> bool:
    q9 = next((i for i in pf.get("items") or [] if isinstance(i, dict) and i.get("id") == "Q9"), None)
    return bool(q9) and q9.get("status") == "pass"


def frame_candidates(root: Path, td: dict) -> list[dict]:
    """过“出图检测”的首帧版本（sop_gate.shot_frames 同口径）+ 契约分。返回 [{n, score, q1, bundle, at, take}]"""
    out = []
    for t in td.get("takes") or []:
        if t.get("stage") != "image" or not t.get("file") or t.get("quarantined") or t.get("master_reject") or t.get("bad"):
            continue
        if not (Path(root) / "data" / str(t["file"])).is_file():
            continue
        pf = t.get("postflight") or t.get("contract") or {}
        if not (isinstance(pf, dict) and pf.get("ok") and _q9_ok(pf)) or pf.get("accept_retry"):
            continue
        items = {i.get("id"): i for i in pf.get("items") or [] if isinstance(i, dict)}
        ev = (items.get("Q1") or {}).get("evidence") or {}
        q1 = next((float(ev[k]) for k in ("value", "min", "score") if isinstance(ev.get(k), (int, float))), 0.0)
        rows = ((((items.get("QB") or {}).get("evidence") or {}).get("bundle") or {}).get("items")) or []
        rows = [r for r in rows if isinstance(r, dict)]
        bundle = (sum(1 for r in rows if r.get("ok")) / len(rows)) if rows else 0.0
        at = _ts(pf.get("ts")) or _ts(t.get("created_at"))
        out.append({"n": int(t["n"]), "score": round(q1 + bundle, 4), "q1": round(q1, 4), "bundle": round(bundle, 4), "at": at,
                    "blocking": len(pf.get("blocking") or []), "take": t})
    return out


def frame_choose(cands: list[dict]) -> dict:
    """契约分最高；同分 = bundle 顺序（先出的版本号小的）"""
    return max(cands, key=lambda c: (-c["blocking"], c["score"], -c["n"]))


FRAME_AUDIT_RE = re.compile(r"^/api/shots/(ep\d+-S\d+)/takes/(?:image|first)/\d+/(?:lock|unlock)\b")
LOCAL_ONLY_MARKS = ("本地生成", "占位", "暂缓")       # 与 producer.LOCAL_ONLY_MARKS 同口径（剧本 H3校验）
LOCAL_LANE_PREFIX = "laptop:"                       # W18b P1-3：producer 记录的道以 laptop: 开头 = 本地专用


class _Unknown(Exception):
    """判不出来（读不了 / 坏数据）：调用方失败关闭"""


def _row_before(r: dict, since: str | None) -> bool:
    """W29 P2-8：audit / decisions 行不带剧名 → 本剧创建时间（runs.json created_at）之前的行是上一剧的痕迹，不算。
    行没有可解析的 at → 判不出来，按“本剧的”算（失败关闭）"""
    if not since:
        return False
    at = str(r.get("at") or "")
    if len(at) < 19 or not at[:4].isdigit():
        return False
    return at[:19].replace(" ", "T") < since[:19].replace(" ", "T")


def _owner_marks(root: Path, since: str | None = None) -> dict:
    """W18b P1-4：项目方在网页 / #/queue 动过首帧的镜 → {sid: 说明}。
    来源：data/audit/*.jsonl 里 /api/shots/<sid>/takes/image|first/<n>/lock|unlock（网页定稿 / 解锁，frame_edit.unlock 不留 locked_history）
    + data/owner_queue/decisions.jsonl 里提到该镜的任何非代选动作。目录 / 文件不存在 = 没有记录；读不了 → _Unknown（按动过算）"""
    out: dict[str, str] = {}
    adir = Path(root) / "data" / "audit"
    files = sorted(adir.glob("*.jsonl")) if adir.is_dir() else []
    dec = Path(root) / "data" / "owner_queue" / "decisions.jsonl"
    if dec.is_file():
        files.append(dec)
    for f in files:
        try:
            lines = f.read_text(encoding="utf-8").splitlines()
        except OSError as e:
            raise _Unknown(f"{f.name} 读不了：{e}") from e
        for ln in lines:
            if "ep" not in ln:
                continue
            try:
                r = json.loads(ln)
            except ValueError as e:
                print(f"[owner_delegate] 坏行跳过 {f.name}: {e!r}", file=sys.stderr, flush=True)
                continue                                               # 坏行跳过（其它行照读）
            if not isinstance(r, dict) or _row_before(r, since):
                continue
            if f is dec:
                if str(r.get("by") or "") == BY or str(r.get("via") or "").startswith("delegate"):
                    continue                                           # 代选自己的动作不算
                for sid in set(re.findall(r"ep\d+-S\d+(?!\d)", json.dumps(r, ensure_ascii=False))):
                    out.setdefault(sid, f"#/queue 有项目方动作（{r.get('id')} {r.get('at')}）")
            else:
                m = FRAME_AUDIT_RE.match(str(r.get("path") or ""))
                if m and str(r.get("method") or "POST").upper() == "POST":
                    act = "解锁" if r["path"].rstrip("/").endswith("unlock") else "定稿"
                    out.setdefault(m.group(1), f"网页{act}过首帧（{r.get('user') or '?'} {r.get('at')}）")
    return out


def _owner_touched(td: dict, seen_row: dict | None, mark: str | None = None) -> str | None:
    if seen_row and (td.get("locked") or {}).get("image") is None:
        return f"系统代选过 v{seen_row.get('n')}，之后被撤掉（项目方 / 总调度改过），不再代（不推翻）"
    for h in td.get("locked_history") or []:
        if isinstance(h, dict) and h.get("stage") == "image":
            return f"这镜首帧以前锁过 / 解锁过（{h.get('released_by') or '?'}），按项目方动过算，不代"
    lb = (td.get("locked_by") or {}).get("image")
    if isinstance(lb, dict) and lb.get("by") not in (None, "delegate"):
        return f"这镜首帧以前由 {lb.get('by')} 定过稿（locked_by 留痕），按项目方动过算，不代"
    if mark:
        return f"{mark}，按项目方动过算，不代"
    return None


def _script_flags(root: Path, run: str, ep: int) -> tuple[set[int], set[int]]:
    """导入稿（runs.import_path）里本集的 (成人镜, 本地专用镜)。成人 = shot.adult（sop_gate.adult_shots_of 同口径）；
    本地专用 = H3校验写了“本地生成 / 占位 / 暂缓”或 route=local_only（producer.local_only_shots 同口径）。
    W18b P0-1：导入稿不存在 / 读不了 / 没有这一集 / 镜号坏 → 抛（调用方整集失败关闭；sop_gate.adult_shots_of 读不到时返回空集 = 放行，不能用）"""
    sys.path.insert(0, str(_CODE_ROOT / "tools" / "autopilot"))
    import runs as R  # noqa: PLC0415
    doc = json.loads(Path(R.import_path(run, Path(root))).read_text(encoding="utf-8"))
    eps = [e for e in (doc.get("episodes") or []) if isinstance(e, dict) and str(e.get("number")) == str(int(ep))]
    if not eps:
        raise LookupError(f"导入稿里没有第 {ep} 集")
    adult, local = set(), set()
    for s in eps[0].get("shots") or []:
        n = int(s["index"])
        if s.get("adult"):
            adult.add(n)
        if any(m in str(s.get("h3_check") or "") for m in LOCAL_ONLY_MARKS) or s.get("route") == "local_only":
            local.add(n)
    return adult, local


def _producer_lanes(root: Path, run: str) -> dict:
    """producer 账本（runs.producer_dir(run)/attempts.json）→ {"first:<sid>": {take n: lane}}。没有账本 = {}；读不了 / 坏 → 抛（失败关闭）"""
    sys.path.insert(0, str(_CODE_ROOT / "tools" / "autopilot"))
    import runs as R  # noqa: PLC0415
    p = Path(R.producer_dir(run, Path(root))) / "attempts.json"
    if not p.is_file():
        return {}
    d = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(d, dict):
        raise ValueError(f"{p} 不是对象")
    out: dict = {}
    for oid, row in d.items():
        for h in (row or {}).get("history") or [] if isinstance(row, dict) else []:
            if isinstance(h, dict) and h.get("take") is not None and h.get("lane"):
                out.setdefault(oid, {})[int(h["take"])] = str(h["lane"])
    return out


def _cand_lane(take: dict, lanes: dict) -> str | None:
    pr = take.get("producer")
    if isinstance(pr, dict) and pr.get("lane"):
        return str(pr["lane"])
    return lanes.get(int(take.get("n") or -1))


def _primary_run(root: Path) -> tuple[str | None, dict]:
    reg = _read_json(Path(root) / "config" / "pipeline" / "runs.json", {}) or {}
    run = reg.get("primary")
    meta = (reg.get("runs") or {}).get(run) or {}
    if not run or run == reg.get("legacy_unprefixed_run") or meta.get("status") not in ADVANCE_STATUSES:
        return None, meta
    return run, meta


def _sop_gate():
    sp = importlib.util.spec_from_file_location("sop_gate_for_delegate", _CODE_ROOT / "tools" / "master" / "sop_gate.py")
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


def _default_frame_lock(root: Path, sid: str, n: int, meta: dict, takes_file: Path) -> dict:
    """与画布定稿同一入口 frame_jobs.lock_take（含 L-147 auto_final_on_lock → submit_final → 定稿档共用验收），再标 locked_by.image。
    API 进程当前剧的 takes.json 和本拍扫到的不是同一个文件 → 不定（防写错剧）"""
    from ns_api import frame_jobs as FJ  # noqa: PLC0415
    from ns_render import pipeline as P  # noqa: PLC0415
    if (P.shot_dir(sid) / "takes.json").resolve() != Path(takes_file).resolve():
        raise RuntimeError(f"API 当前剧的 {sid} takes.json 是 {P.shot_dir(sid)}，不是 {takes_file}，不定稿（防写错剧）")
    view = FJ.lock_take(sid, "image", n, FJ.LockBody())
    with P.shot_lock(sid):
        d = P.load_takes(sid)
        d.setdefault("locked_by", {})["image"] = meta
        P._save_takes(sid, d, op="delegate_first_frame", by=BY)
    return {"final_job": bool(view.get("final_job")), "auto_final_on_lock": bool(view.get("final_job")) or None}


def frame_tick(root: Path = REPO, now: float | None = None, lock_fn=None, adult_fn=None, live_fn=None, dry: bool = False,
               local_fn=None, lanes_fn=None, marks_fn=None) -> list[dict]:
    """→ 本拍代选（或 dry 下“会代选”）的行。超时没到 / 硬规定 / 项目方动过的只记一次 skip。
    W18b：dry 不受 first_frame.enabled 短路（开关关着也能先看“会代哪些镜”），且 dry 不落盘 delegate_seen / delegate_log / delegate_frames
    （skip 以 {"event": "skip", "dry": True} 行返回）。成人 / 本地专用 / 项目方动过 —— 判不出来一律失败关闭（不代）"""
    cfg = {**FRAME_DEFAULT, **(load_cfg(root).get("first_frame") or {})}
    if not cfg.get("enabled") and not dry:
        return []
    run, _meta = _primary_run(root)
    if not run:
        return []
    now = now or time.time()
    try:
        sys.path.insert(0, str(_CODE_ROOT / "tools" / "autopilot"))
        import runs as R  # noqa: PLC0415
        base = Path(R.renders_dir(run, Path(root)))
    except Exception:  # noqa: BLE001  # arch-ok: 读不到渲染根 = 不代（失败关闭）
        return []
    out: list[dict] = []

    def skip(iid: str, reason: str, extra: dict | None = None) -> None:
        if dry:
            out.append({"event": "skip", "item": iid, "reason": reason, "dry": True, **(extra or {})})
        else:
            _skip_once(root, iid, reason, extra)

    seen = _read_json(Path(root) / FRAME_SEEN_REL, {})
    try:                                                                 # P1-4：项目方网页定稿 / 解锁 / #/queue 动作
        marks, marks_err = (marks_fn(root) if marks_fn else _owner_marks(root, _meta.get("created_at"))), None
    except Exception as e:  # noqa: BLE001  # arch-ok: 判不出来动没动过 = 按动过算（不代）
        marks, marks_err = {}, f"{type(e).__name__}: {e}"[:200]
    try:                                                                 # P1-3：producer 记录的道（laptop: = 本地专用）
        lanes_all, lanes_err = (lanes_fn or _producer_lanes)(root, run), None
    except Exception as e:  # noqa: BLE001  # arch-ok: 判不出来 = 不代
        lanes_all, lanes_err = {}, f"{type(e).__name__}: {e}"[:200]
    adult_cache: dict[int, set | str] = {}
    local_cache: dict[int, set | str] = {}

    def ep_set(cache: dict, ep: int, fn) -> set | str:
        if ep not in cache:
            try:
                cache[ep] = set(fn(run, ep))
            except Exception as e:  # noqa: BLE001  # arch-ok: 判不了 = 整集失败关闭（P0-1：不是只关当前镜）
                cache[ep] = f"{type(e).__name__}: {e}"[:200]
        return cache[ep]

    for tj in sorted(base.glob("ep*/S*/takes.json")):
        ep_s, s_s = tj.parent.parent.name, tj.parent.name
        if not (ep_s[2:].isdigit() and s_s[1:].isdigit()):
            continue
        ep, sn, sid = int(ep_s[2:]), int(s_s[1:]), f"{ep_s}-{s_s}"
        iid = f"first:{run}/{sid}"
        td = _read_json(tj, {}) or {}
        if (td.get("locked") or {}).get("image") is not None:
            continue                                                     # 已定稿（项目方或已代选）
        if marks_err:
            skip(iid, f"项目方动没动过这镜判不出来（{marks_err}），按动过算，不代")
            continue
        touched = _owner_touched(td, seen.get(iid), marks.get(sid))
        if touched:
            skip(iid, touched)
            continue
        cands = frame_candidates(root, td)
        if not cands:
            continue                                                     # 还没有过检的版本：等出图检测
        adult = ep_set(adult_cache, ep, adult_fn or (lambda r, e: _script_flags(Path(root), r, e)[0]))
        if isinstance(adult, str):
            skip(iid, f"剧本读不到 / 成人判定失败（第 {ep} 集整集不代）：{adult}")
            continue
        local = ep_set(local_cache, ep, local_fn or (lambda r, e: _script_flags(Path(root), r, e)[1]))
        if isinstance(local, str):
            skip(iid, f"剧本读不到 / 本地专用判定失败（第 {ep} 集整集不代）：{local}")
            continue
        if lanes_err:
            skip(iid, f"producer 记录读不了，候选是不是本地专用判不出来（{lanes_err}），不代")
            continue
        lanes = lanes_all.get(f"first:{sid}") or {}
        cl = [_cand_lane(c["take"], lanes) for c in cands]
        if any(x is None for x in cl):
            unk = [c["n"] for c, x in zip(cands, cl) if x is None]
            skip(iid, f"候选 v{unk} 没有 producer 道记录，是不是本地专用判不出来，不代")
            continue
        req = {"kind": "pick", "id": iid, "title": f"{run} {sid} 首帧", "adult": sn in adult,
               "route": "local_only" if sn in local else None,
               "candidates": [{"adult": c["take"].get("adult"),
                               "route": "local_only" if (c["take"].get("route") == "local_only" or x.startswith(LOCAL_LANE_PREFIX))
                               else c["take"].get("route"), "lane": x} for c, x in zip(cands, cl)]}
        nr = never_reason(req)
        if nr:
            skip(iid, nr, {"title": req["title"]})
            continue
        first_ok = min((c["at"] for c in cands if c["at"]), default=None)
        if first_ok is None:
            skip(iid, "过检版本没有时间戳，算不了等了多久，不代")
            continue
        waited = (now - first_ok) / 60
        if waited < float(cfg["timeout_min"]):
            continue
        best = frame_choose(cands)
        meta = {"by": "delegate", "label": FRAME_LABEL, "ledger": FRAME_LEDGER, "via": "delegate:L-142", "n": best["n"], "at": _now(),
                "score": best["score"], "why": f"出图检测通过 {waited:.0f} 分钟项目方没定（门槛 {cfg['timeout_min']} 分钟）"}
        row = {"event": "frame_pick", "item": iid, "kind": "first", "run": run, "shot": sid, "choice": best["n"], "label": FRAME_LABEL,
               "score": best["score"], "ledger": FRAME_LEDGER, "waited_min": round(waited, 1),
               "scores": [{k: c[k] for k in ("n", "score", "q1", "bundle", "blocking")} for c in cands],
               "reason": f"按契约分（Q1 身份 + 合并看图逐条通过率）+ bundle 顺序选 v{best['n']}（{best['score']}）；{meta['why']}"}
        if dry:
            out.append({**row, "dry": True, "enabled": bool(cfg.get("enabled"))})
            continue
        try:
            res = (lock_fn or _default_frame_lock)(root, sid, best["n"], meta, tj)
        except Exception as e:  # noqa: BLE001  # 定稿失败（坏图 / 剧不对 / 接口不收）：只记一次，不重试刷屏
            skip(iid, f"定稿没成：{type(e).__name__}: {e}"[:300])
            continue
        seen = _read_json(Path(root) / FRAME_SEEN_REL, {})
        seen[iid] = {"n": best["n"], "at": _now(), "score": best["score"]}
        _atomic_json(Path(root) / FRAME_SEEN_REL, seen)
        ent = log(root, {**row, "via": "delegate:L-142", "result": res})
        try:
            (live_fn or _frame_live)(root, f"🖼 首帧代选（L-142，{FRAME_LABEL}）：{run} {sid} → v{best['n']}（契约分 {best['score']}，"
                                           f"过检后等了 {waited:.0f} 分钟）" + ("；已排定稿档重出（L-147）" if (res or {}).get("final_job") else ""))
        except OSError:
            pass
        out.append(ent)
    return out


def _frame_live(root: Path, line: str) -> None:
    sp = importlib.util.spec_from_file_location("report_issue_for_delegate", _CODE_ROOT / "tools" / "master" / "report_issue.py")
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    m._insert_live(f"{time.strftime('%H:%M')} {line}", Path(root) / "docs" / "master" / "V2_LIVE.md")


# ------------------------------------------------------------------ 一拍
def tick(root: Path = REPO, apply_fn=None, spawn=None, sync_looks=True, frame_lock=None) -> dict:
    frames, ferr = [], None
    try:                            # ④ 首帧超时代选（L-142 常设授权，不受 L-136 开关 / 到期影响）
        frames = frame_tick(root, lock_fn=frame_lock)
    except Exception as e:  # noqa: BLE001  一类出错不拖累另一类
        ferr = f"frames: {e!r}"[:300]
        log(root, {"event": "error", "where": "frames", "error": repr(e)[:300]})
    ok, why = active(root)
    if not ok:
        return {"active": False, "why": why, "frames": frames, "errors": [ferr] if ferr else []}
    if sync_looks:
        try:                        # 项目方睡着、网页没开时 inbox 不会被读：先把“确认本集造型”投进通知
            from ns_api import look_confirm as LC  # noqa: PLC0415
            LC.sync_picks(Path(root))
        except Exception:  # noqa: BLE001
            pass
    out = {"active": True, "picks": [], "gates": [], "frames": frames, "errors": [ferr] if ferr else []}
    for name, fn in (("picks", lambda: pick_tick(root, apply_fn)), ("gates", lambda: gate_tick(root, spawn))):
        try:
            out[name] = fn()
        except Exception as e:  # noqa: BLE001  一类出错不拖累另一类
            out["errors"].append(f"{name}: {e!r}"[:300])
            log(root, {"event": "error", "where": name, "error": repr(e)[:300]})
    if out["picks"] or out["gates"] or out["frames"] or out["errors"]:
        render_page(root)
    return out


# ------------------------------------------------------------------ 汇总页（项目方早上看）
def _rel_url(root: Path, rel: str | None) -> str | None:
    if not rel:
        return None
    p = Path(root) / rel
    if not p.is_file():
        return None
    return os.path.relpath(p, Path(root) / PAGE_REL.parent).replace(os.sep, "/")


def render_page(root: Path = REPO) -> Path:
    root = Path(root)
    cfg = load_cfg(root)
    rows = log_rows(root)
    acts = [r for r in rows if r.get("event") in ("pick", "gate_approve", "gate_revise", "gate_hold")]
    skips = [r for r in rows if r.get("event") == "skip"]
    life = [r for r in rows if r.get("event") in ("enabled", "closed", "error")]
    e = html.escape
    st = "开启中" if cfg.get("enabled") else "已关闭"
    exp = cfg.get("expiry") or {}
    parts = [f"<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>代选汇总</title>",
             "<style>:root{--bg:#111;--fg:#eee;--mut:#999;--ac:#e0b050;--ok:#6c6;--bad:#e66}body{background:var(--bg);color:var(--fg);font:14px/1.6 system-ui,sans-serif;margin:0 auto;max-width:1100px;padding:16px}"
             "h1{font-size:20px}h2{font-size:16px;margin-top:28px;border-bottom:1px solid #333}.c{border:1px solid #333;border-radius:8px;padding:10px 12px;margin:10px 0}"
             ".m{color:var(--mut);font-size:12px}.row{display:flex;gap:8px;flex-wrap:wrap}.row figure{margin:0;width:150px}.row img{width:150px;border-radius:4px}"
             ".pick{outline:2px solid var(--ac)}table{border-collapse:collapse;font-size:12px}td,th{border:1px solid #333;padding:2px 6px}</style>",
             f"<h1>代选汇总（L-136）· {e(st)}</h1>",
             f"<p class=m>授权：{e(str((cfg.get('authority') or {}).get('quote') or ''))}（{e(str((cfg.get('authority') or {}).get('ledger') or ''))}）<br>"
             f"开启：{e(str(cfg.get('enabled_at') or '—'))} · 到期规则：{e(str(exp.get('rule') or ''))}"
             + (f"<br>已关闭：{e(str(exp.get('expired_at')))} · {e(str(exp.get('expired_reason')))}" if exp.get("expired_at") else "") + "</p>",
             f"<p>代选 {sum(1 for r in acts if r.get('event') == 'pick')} 条挑选、{sum(1 for r in acts if r.get('event') != 'pick')} 个写作闸门。"
             "每一条都可以在 #/queue 里点“修改”（或直接改选别的候选）推翻。</p>", "<h2>代选了什么</h2>"]
    for r in reversed(acts):
        if r.get("event") == "pick":
            figs = []
            for s in r.get("scores") or []:
                u = _rel_url(root, (r.get("thumbs") or {}).get(s.get("key")))
                media = (f"<audio controls preload=none src='{e(u)}'></audio>" if u and u.endswith(".wav") else f"<img src='{e(u)}' loading=lazy>") if u else ""
                figs.append(f"<figure class='{'pick' if s.get('key') == r.get('choice') else ''}'>{media}<figcaption class=m>{e(str(s.get('label')))}<br>"
                            f"分 {e(str(s.get('score')))}{'（不可选：' + e(str(s.get('why'))) + '）' if s.get('score') is None else ''}</figcaption></figure>")
            parts.append(f"<div class=c><b>{e(str(r.get('title') or r.get('item')))}</b> → 选 <b>{e(str(r.get('label')))}</b>（分 {e(str(r.get('score')))}）"
                         f"<div class=m>{e(str(r.get('at')))} · {e(str(r.get('item')))} · 结果 {e(str(r.get('state')))}{' · ' + e(str(r.get('error'))) if r.get('error') else ''}<br>理由：{e(str(r.get('reason')))}</div>"
                         f"<div class=row>{''.join(figs)}</div></div>")
        else:
            jt = "".join(f"<tr><td>{e(j)}</td>{''.join(f'<td>{e(k)}={e(str(v))}</td>' for k, v in its.items())}</tr>" for j, its in (r.get("judge_items") or {}).items())
            parts.append(f"<div class=c><b>写作闸门 {e(str(r.get('run')))} {e(str(r.get('key')))}</b> → {e({'gate_approve': '代选放行', 'gate_revise': '退回补丁环', 'gate_hold': '不放行、等你定'}[r['event']])}"
                         f"<div class=m>{e(str(r.get('at')))} · 均分 {e(str(r.get('mean')))} · 各家 {e(str(r.get('totals')))} · {e(str(r.get('reason')))}"
                         f"{' · 卡点 ' + e(str(r.get('issue'))) if r.get('issue') else ''}</div><table>{jt}</table></div>")
    if not acts:
        parts.append("<p class=m>还没有代选任何条目。</p>")
    parts.append("<h2>没代选的（原因）</h2>" + ("".join(f"<div class=m>{e(str(r.get('at')))} · {e(str(r.get('item')))} {e(str(r.get('title') or ''))}：{e(str(r.get('reason')))}</div>" for r in reversed(skips[-200:])) or "<p class=m>无</p>"))
    parts.append("<h2>开关记录</h2>" + "".join(f"<div class=m>{e(str(r.get('at')))} · {e(str(r.get('event')))} · {e(str(r.get('reason') or r.get('by') or r.get('error') or ''))}</div>" for r in life))
    p = root / PAGE_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text("\n".join(parts), encoding="utf-8")
    os.replace(tmp, p)
    return p


# ------------------------------------------------------------------ 状态 / HTTP
def status(root: Path = REPO) -> dict:
    cfg = load_cfg(root)
    rows = log_rows(root)
    since = str(cfg.get("enabled_at") or "")
    picks = [r for r in rows if r.get("event") == "pick" and str(r.get("at", "")) >= since]
    gates = [r for r in rows if str(r.get("event", "")).startswith("gate_") and str(r.get("at", "")) >= since]
    return {"enabled": bool(cfg.get("enabled")), "label": "代选模式开启中（L-136）" if cfg.get("enabled") else None,
            "authority": cfg.get("authority"), "enabled_at": cfg.get("enabled_at"), "expiry": cfg.get("expiry"),
            "picked": len(picks), "gates": len(gates), "page": "/files/review_pages/delegate/index.html"}


@router.get("/api/owner/delegate")
def get_delegate():
    return status(REPO)


@router.post("/api/owner/delegate/revoke")
def post_revoke(request: Request):
    from ns_api import auth  # noqa: PLC0415
    u = auth.user_of(request)
    if not u or u.get("role") != "owner":
        raise HTTPException(403, "只有登录的项目方本人能撤销代选")
    revoke(REPO, by=f"项目方 {u.get('name')}", why="#/queue 一键撤销")
    return status(REPO)


# ------------------------------------------------------------------ :8800 后台线程（每拍重新加载本模块代码）
def _loop(root: Path) -> None:
    try:
        from ns_api import instance as INST  # noqa: PLC0415
        if not INST.holds_port():
            return
    except Exception:  # noqa: BLE001
        return
    while True:
        interval = 60
        try:
            mod = importlib.reload(sys.modules[__name__])
            interval = int(mod.load_cfg(root).get("interval_s") or 60)
            mod.tick(root)
        except Exception as e:  # noqa: BLE001  一拍出错只记，线程不退
            try:
                log(root, {"event": "error", "where": "loop", "error": repr(e)[:300]})
            except OSError:
                pass
        time.sleep(max(15, interval))


def start_thread(root: Path = REPO) -> threading.Thread:
    t = threading.Thread(target=_loop, args=(root,), name="owner_delegate", daemon=True)
    t.start()
    return t


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "enable":
        print(json.dumps(enable(REPO, by="总调度（CLI）"), ensure_ascii=False, indent=1))
    elif cmd == "revoke":
        print(json.dumps(revoke(REPO, by="总调度（CLI）"), ensure_ascii=False, indent=1))
    elif cmd == "tick":
        print(json.dumps(tick(REPO), ensure_ascii=False, indent=1, default=str))
    elif cmd == "page":
        print(render_page(REPO))
    elif cmd == "frames":       # W18 / L-142：首帧超时代选；frames --dry 只列会代选的镜
        print(json.dumps(frame_tick(REPO, dry="--dry" in sys.argv), ensure_ascii=False, indent=1, default=str))
    else:
        print(json.dumps(status(REPO), ensure_ascii=False, indent=1))
