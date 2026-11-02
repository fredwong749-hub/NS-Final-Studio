"""镜头首帧 / 尾帧“修改”的异步通道（L-123 延伸；项目方 16:58 / 17:0x）。

项目方原话：“点击修改之后可以快速把信息记录下来，排队要不要让我等那么久啊？”“我反馈了，它还反驳我”“局部修改，局部显示状态和等待状态；
提示整个系统的排队阵列。”
→ 项目方的反馈永远不被拒收：
  POST /api/shots/{shot}/frame-edit        只做一件事——把这条修改原样记下（一句话、点过的建议 chip、对象、版本、时间），立刻 202。
                                           不在请求里跑改写 / 检查 / 出图。
  后台线程依次做：写作模型改写（prompt_rewrite kind=shot_frame）→ 出图前检查（系统自己带原因再改，最多 2 次）→ 交 producer 的正式队列
  （producer.py reject --n 0 --edit-file；复用 master_reject 的插队通道，不另开队列；排序 = K-OPS-E30：按集、集内插队 / 驳回先、尾帧先、镜号）。
  检查还不过 / 写作模型一直连不上 → 状态 needs_look（“需要你看一眼”），抽屉 log 里用大白话说卡在哪；界面不出现技术词。
  GET  /api/shots/{shot}/frame-edits       这一镜的修改记录 + 现在的状态（排队第 N / 出图中 / 打分中 / 完成 / 需要你看一眼）+ 预计完成时间
  GET  /api/frame-queue                    全系统出图队列（producer registry 里 ready / running 的对象，按 E30 排序）+ 你提交的几条排第几
预计时间：每镜 PER_SHOT_S（总调度给的历史中位 740 秒）、并行道数 lanes（partition.json 里出图的道，默认 3）：
  eta = ceil((在跑 + 排在我前面 + 1) / lanes) x 740。读本机已同步的 registry 文件，不开 ssh。
"""
from __future__ import annotations

import json
import math
import queue
import re
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[3]
STATE = ROOT / "data" / "state" / "frame_edit_requests.json"
REGISTRY = ROOT / "data" / "producer" / "registry.json"
PARTITION = ROOT / "data" / "state" / "netfix" / "partition.json"
PER_SHOT_S = 740.0
MAX_AUTO_FIX = 2
STAGES = {"first": "image", "last": "last"}
router = APIRouter(tags=["frame-edit-queue"])
_lock = threading.RLock()
_q: "queue.Queue[str]" = queue.Queue()
_worker: threading.Thread | None = None

# 出图前检查的失败原因 → 大白话（界面和抽屉 log 不出现 GEN_CONTRACT / preflight 这类词）
PLAIN = {
    "I1": "画面里的人物和站位没有写清楚",
    "I2": "缺少这个人的脸部参考图",
    "I3": "参考图和画面里的人物对不上",
    "I4": "参考图数量超出了模型能看的张数",
    "I5": "服装参考和这一镜的造型不一致",
    "I6": "修改要求缺少这一镜原来的画面描述",
    "I7": "修改要求里有系统不允许的词（旧的出图风格词）",
    "I8": "用到了没登记的风格模型",
}
TECH = re.compile(r"GEN_CONTRACT|preflight|postflight|I\d{1,2}\b|契约", re.I)


def plain(items: list[dict]) -> list[str]:
    out = []
    for it in items:
        if str(it.get("status")) != "fail":
            continue
        out.append(PLAIN.get(str(it.get("id")), "这一镜的检查有一项没通过"))
    return list(dict.fromkeys(out))


# ---------------------------------------------------------------- 存储
def _load() -> list[dict]:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):  # arch-ok: 没有记录文件 = 还没有任何修改，调用方按空列表处理；写入走 _save，坏文件不会被覆盖掉原话（见 _save 先写临时文件再换）
        return []


def _save(rows: list[dict]) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(STATE)


def _update(rid: str, **kw) -> dict | None:
    with _lock:
        rows = _load()
        for r in rows:
            if r["id"] == rid:
                r.update(kw)
                r["log"] = (r.get("log") or []) + [{"at": time.strftime("%Y-%m-%dT%H:%M:%S"), **{k: v for k, v in kw.items() if k in ("state", "note")}}]
                _save(rows)
                return r
    return None


# ---------------------------------------------------------------- 队列（producer registry，只读）
_reg = {"mt": None, "val": []}


def registry_objects() -> list[dict]:
    """[{oid, ep, idx, kind(first|last), status, redo, shot, attempts, reason}]（只含首尾帧对象）"""
    try:
        mt = REGISTRY.stat().st_mtime
    except OSError:  # arch-ok: registry 文件还没同步到本机 = 队列看不到，调用方显示“排队中”不给位置
        return []
    if _reg["mt"] != mt:
        try:
            d = json.loads(REGISTRY.read_text(encoding="utf-8"))
        except (OSError, ValueError):  # arch-ok: registry 读到半截 JSON：当作空，下一次轮询（文件一写完就变）会读到完整的
            d = {}
        rows = []
        for E in d.get("episodes") or []:
            for S in E.get("shots") or []:
                for k in ("first", "last"):
                    o = (S.get("objects") or {}).get(k)
                    if isinstance(o, dict):
                        rows.append({"oid": o.get("id") or f"{k}:{S.get('shot')}", "ep": E.get("ep"), "idx": S.get("index"), "kind": k, "status": o.get("status"),
                                     "redo": bool(o.get("redo")), "shot": S.get("shot"), "attempts": o.get("attempts") or 0,
                                     "waiting_for": o.get("waiting_for"), "where": o.get("where")})
        _reg.update(mt=mt, val=rows)
    return _reg["val"]


def order_key(r: dict) -> tuple:
    """K-OPS-E30（tools/autopilot/producer.episode_order_key 同一公式）：(集, 驳回 / 插队先, 尾帧先, 镜序)"""
    return (r["ep"] or 0, 0 if r.get("redo") else 1, 0 if r["kind"] == "last" else 1, r["idx"] or 0)


def lanes() -> int:
    try:
        d = json.loads(PARTITION.read_text(encoding="utf-8"))
        hosts = [h for h, eps in (d.get("images") or {}).items() if eps]
        retired = set(d.get("retired_lanes") or [])
        n = sum(1 for h in hosts for ln in (d.get("lanes") or {}).get(h, []) if ln not in retired)
        return max(1, n)
    except (OSError, ValueError):  # arch-ok: 读不到分区表 = 按默认 3 条道估时，只影响预计时间
        return 3


_eta = {"at": 0.0, "val": None}


def eta_table() -> dict | None:
    """DEBUG-RSI 的 tools/autopilot/queue_eta.compute（真实历史中位时长、按主机分池）；20 秒缓存。算不出 → None，退回下面自己的 740 秒口径"""
    if time.time() - _eta["at"] < 20:
        return _eta["val"]
    val = None
    try:
        sys.path.insert(0, str(ROOT / "tools" / "autopilot"))
        import queue_eta as QE
        val = QE.compute(ROOT)
    except Exception:  # noqa: BLE001  # arch-ok: 排队估时模块读不到 = 退回自己的 740 秒口径（snapshot），界面照常显示位置，只是估时更粗
        val = None
    _eta.update(at=time.time(), val=val)
    return val


@router.get("/api/queue_eta")
def queue_eta():
    t = eta_table()
    if t is None:
        raise HTTPException(503, "排队估时暂时算不出来")
    return t


def snapshot() -> dict:
    objs = registry_objects()
    running = [o for o in objs if o["status"] == "running"]
    ready = sorted([o for o in objs if o["status"] == "ready"], key=order_key)
    n_lane = lanes()
    now = time.time()
    items = []
    for o in running:
        items.append({**o, "state": "running", "pos": 0, "eta_at": now + PER_SHOT_S / 2})
    for i, o in enumerate(ready):
        waves = math.ceil((len(running) + i + 1) / n_lane)
        items.append({**o, "state": "queued", "pos": i + 1, "eta_at": now + waves * PER_SHOT_S})
    stale = None
    tbl = eta_table()
    if tbl:      # 用真实历史中位时长和主机分池的估时覆盖粗口径；排序口径本来就一致（K-OPS-E30）
        stale = bool((tbl.get("basis") or {}).get("stale"))
        for it in items:
            o = (tbl.get("objects") or {}).get(it["oid"])
            if o and o.get("eta_s"):
                it["eta_at"] = float(o["eta_s"])
                if it["state"] == "queued" and o.get("pos"):
                    it["pos"] = int(o["pos"])
    return {"per_shot_s": PER_SHOT_S, "lanes": n_lane, "running": len(running), "queued": len(ready), "items": items, "stale": stale}


def position_of(oid: str, snap: dict | None = None) -> dict | None:
    s = snap or snapshot()
    return next((i for i in s["items"] if i["oid"] == oid), None)


# ---------------------------------------------------------------- 状态（给界面）
def _takes(shot: str) -> dict:
    from ns_render import pipeline as P
    return P.load_takes(shot)


def _passing(t: dict) -> bool:
    from ns_api import takes_ui as TU
    if t.get("quarantined") or t.get("void"):
        return False
    return bool(TU._verdict(t, None)[0])


def live_state(r: dict, snap: dict | None = None) -> dict:
    """一条修改记录现在的状态 → {state, word, pos, eta_at, ahead:[shot…], new_n, msg}"""
    st = r.get("state")
    base = {"id": r["id"], "shot": r["shot"], "stage": r["stage"], "text": r["text"], "zh_summary": r.get("zh_summary"), "at": r["at"], "pos": None, "eta_at": None,
            "ahead": [], "new_n": None, "retry": 0, "msg": r.get("note") or ""}
    if st in ("received", "rewriting", "checking"):
        return {**base, "state": "preparing", "word": "排队中：已记下，正在整理你的要求"}
    if st == "needs_look":
        return {**base, "state": "needs_look", "word": "需要你看一眼", "msg": r.get("note") or ""}
    stage = STAGES[r["stage"]]
    data = _takes(r["shot"])
    after = [t for t in data.get("takes") or [] if t.get("stage") == stage and str(t.get("created_at") or "") >= str(r.get("queued_at") or r["at"])]
    good = [t for t in after if _passing(t)]
    if good:
        return {**base, "state": "done", "word": "完成", "new_n": max(t["n"] for t in good)}
    snap = snap or snapshot()
    oid = f"{r['stage']}:{r['shot']}"
    me = position_of(oid, snap)
    obj = next((o for o in registry_objects() if o["oid"] == oid), None)
    retry = sum(1 for t in after if not _passing(t))
    scoring = any((t.get("postflight") or {}).get("state") == "running" for t in after)
    if scoring:
        return {**base, "state": "scoring", "word": "打分中", "retry": retry}
    if me and me["state"] == "running" or (obj and obj["status"] == "running"):
        return {**base, "state": "rendering", "word": "修改中" + (f"（系统在重出，第 {retry + 1} 次）" if retry else ""), "retry": retry,
                "eta_at": (me or {}).get("eta_at") or time.time() + PER_SHOT_S / 2}
    if me:
        ahead = [i["shot"] for i in snap["items"] if (i["state"] == "running" or i["pos"] < me["pos"]) and i["oid"] != oid][:12]
        return {**base, "state": "queued", "word": f"排队中，排第 {me['pos']}", "pos": me["pos"], "eta_at": me["eta_at"], "ahead": ahead, "retry": retry}
    return {**base, "state": "queued", "word": "排队中", "retry": retry}


# ---------------------------------------------------------------- 提交（只记账，立刻返回）
class FrameEditBody(BaseModel):
    stage: str                      # first | last
    n: int | None = None            # 底图版本；不给 = 当前版
    text: str = ""                  # 一句话；空 = 只换个种子
    chips: list[str] = []


def _actor(request: Request | None) -> str:
    try:
        from ns_api import character_hub as H
        return H._actor(request)
    except Exception:  # noqa: BLE001  取不到登录名不挡记账
        return "未登录"


@router.post("/api/shots/{shot}/frame-edit", status_code=202)
def submit(shot: str, body: FrameEditBody, request: Request):
    if body.stage not in STAGES:
        raise HTTPException(422, "stage 只能是 first | last")
    if not re.fullmatch(r"ep\d+-S\d+", shot):
        raise HTTPException(422, "镜头号写法：ep06-S7")
    text = body.text.strip()
    rid = "fe-" + uuid.uuid4().hex[:10]
    rec = {"id": rid, "shot": shot, "stage": body.stage, "base_n": body.n, "text": text or "同样的要求，换个种子再出一版", "seed_only": not text,
           "chips": body.chips[:8], "by": _actor(request), "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "state": "received", "log": []}
    with _lock:
        rows = _load()
        rows.append(rec)
        _save(rows)
    _kick(rid)
    pos = position_of(f"{body.stage}:{shot}")
    return {"ok": True, "id": rid, "state": "received", "queue": {"pos": (pos or {}).get("pos"), "ahead_total": snapshot()["queued"]}}


@router.get("/api/shots/{shot}/frame-edits")
def list_for_shot(shot: str, stage: str | None = None):
    snap = snapshot()
    rows = [r for r in _load() if r["shot"] == shot and (not stage or r["stage"] == stage)]
    return {"edits": [live_state(r, snap) | {"log": [x.get("note") or x.get("state") for x in r.get("log") or []]} for r in reversed(rows)][:20]}


@router.get("/api/frame-queue")
def frame_queue(mine: str | None = None):
    snap = snapshot()
    mine_rows = []
    for r in _load()[-200:]:
        ls = live_state(r, snap)
        if ls["state"] in ("done",):
            continue
        mine_rows.append({k: ls[k] for k in ("id", "shot", "stage", "state", "word", "pos", "eta_at", "text", "msg")})
    return {**{k: snap[k] for k in ("per_shot_s", "lanes", "running", "queued", "stale")},
            "items": [{k: i[k] for k in ("oid", "shot", "ep", "idx", "kind", "state", "pos", "eta_at", "redo")} for i in snap["items"]],
            "mine": mine_rows}


# ---------------------------------------------------------------- 后台：改写 → 检查 → 交 producer
def _kick(rid: str) -> None:
    global _worker
    _q.put(rid)
    with _lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_loop, daemon=True, name="frame-edit-worker")
            _worker.start()


def _loop() -> None:
    while True:
        try:
            rid = _q.get(timeout=300)
        except queue.Empty:
            return
        try:
            process(rid)
        except Exception as e:  # noqa: BLE001  任何意外都不能让这条修改消失：标“需要你看一眼”，记下原话仍在
            _update(rid, state="needs_look", note="系统整理这条修改时出了点问题，你的话已经记着，我们会处理。", error=repr(e)[:300])


def _context(shot: str, stage: str, n: int | None) -> dict:
    from ns_api import edits as E
    st = STAGES[stage]
    ctx = E.describe("image", f"take:{shot}/{st}/{n}" if n else f"take:{shot}/{st}")
    return ctx


def _cast_line(ctx: dict) -> str:
    sp = ctx.get("spec") or {}
    try:
        return json.dumps(sp.get("cast") or sp.get("characters") or sp, ensure_ascii=False)[:400]
    except (TypeError, ValueError):  # arch-ok: 站位字段取不出来 = 改写时少一行背景，改写仍照常做
        return ""


def _check(ctx: dict, instruction: str) -> list[str]:
    """出图前检查（和提交编辑时同一个检查）；返回大白话原因列表，空 = 通过。检查本身出错 = 不拦"""
    from ns_api import edits as E
    try:
        eid, eng = E.pick_engine(None)
        ci = E.contract_inputs(ctx, instruction, eng)
        pre = E.gen_contract("preflight", {**ci["req"], "edit": {"object": ctx["id"], "action": "edit", "source": ctx["file"], "engine": eid, "feedback": instruction[:200]}})
    except Exception:  # noqa: BLE001  检查器自己出错不拦项目方的修改
        return []
    return plain(pre.get("items") or []) if pre.get("status") == "fail" else []


def _clean(prompt: str) -> str:
    from ns_api import edits as E
    return E.clean_instruction(prompt)[0]


def process(rid: str, rewrite=None, check=None, ctx_fn=None, submit_fn=None) -> dict:
    """改写 → 检查（≤2 次自动重改）→ 交 producer。参数都可注入（测试用）"""
    from ns_api import prompt_rewrite as PR
    rewrite = rewrite or PR.rewrite
    rec = next(r for r in _load() if r["id"] == rid)
    shot, stage = rec["shot"], rec["stage"]
    if rec.get("seed_only"):
        _update(rid, state="queued", note="已交给出图队列（同样的要求换个种子）", prompt="", queued_at=time.strftime("%Y-%m-%dT%H:%M:%S"))
        return _submit(rid, rec, {"id": rid, "text": rec["text"], "prompt": ""}, submit_fn)
    _update(rid, state="rewriting", note="正在把你的话整理成修改要求")
    try:
        ctx = (ctx_fn or _context)(shot, stage, rec.get("base_n"))
    except Exception:  # noqa: BLE001  上下文取不到：仍然改写，只是少一些背景
        ctx = {}
    rctx = {"shot": shot, "stage": "首帧" if stage == "first" else "尾帧", "base_prompt": ctx.get("prompt") or ctx.get("compiled_prompt") or "", "cast": _cast_line(ctx)}
    fail = ""
    rw = None
    for attempt in range(MAX_AUTO_FIX + 1):
        try:
            rw = rewrite("shot_frame", rec["text"], {**rctx, "fail_reason": fail} if fail else rctx)
        except PR.RewriteError as e:
            if attempt < MAX_AUTO_FIX:
                time.sleep(0 if rewrite is not PR.rewrite else 8)
                continue
            _update(rid, state="needs_look", note="写作助手暂时没连上，你的话已经记下，连上后会自动继续。", error=str(e)[:200])
            return {"state": "needs_look"}
        delta = _clean(rw["prompt"])
        _update(rid, state="checking", note="正在核对这条修改", prompt=delta, zh_summary=rw.get("zh_summary"))
        reasons = (check or _check)(ctx, delta) if ctx or check else []
        if not reasons:
            break
        fail = "；".join(reasons)
        rw = None
    if rw is None:
        _update(rid, state="needs_look", note=f"卡在这里：{fail}。你的话已经记下，需要你看一眼。")
        return {"state": "needs_look"}
    _update(rid, state="queued", note="已交给出图队列", queued_at=time.strftime("%Y-%m-%dT%H:%M:%S"))
    return _submit(rid, rec, {"id": rid, "text": rec["text"], "prompt": delta, "zh_summary": rw.get("zh_summary"), "negative_add": rw.get("negative_add") or None,
                             "base_n": rec.get("base_n")}, submit_fn)


def _submit(rid: str, rec: dict, edit: dict, submit_fn=None) -> dict:
    oid = f"{rec['stage']}:{rec['shot']}"
    why = f"项目方修改：{rec['text']}"
    try:
        res = (submit_fn or _producer_submit)(oid, why, ["frame_v9", "frame_v9"], edit, f"界面修改（{rec['by']}）")
    except Exception as e:  # noqa: BLE001
        res = {"ok": False, "err": repr(e)[:200]}
    if not res.get("ok"):
        _update(rid, state="needs_look", note="没能交给出图队列，你的话已经记下，稍后会再试。", error=res.get("err"))
        return {"state": "needs_look"}
    return {"state": "queued"}


def _producer_submit(oid: str, reason: str, plan: list[str], edit: dict, by: str) -> dict:
    """复用 producer 的插队通道（master_reject，n=0：不撤下当前版）；edit 通过临时文件传"""
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(edit, f, ensure_ascii=False)
        path = f.name
    r = subprocess.run([sys.executable, str(ROOT / "tools/autopilot/producer.py"), "reject", "--obj", oid, "--n", "0", "--reason", reason,
                        "--plan", ",".join(plan), "--by", by, "--edit-file", path], capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=120, cwd=str(ROOT), env={**__import__("os").environ, "PYTHONUTF8": "1"})
    return {"ok": r.returncode == 0, "err": (r.stderr or "")[-300:] if r.returncode else ""}
