"""待办通知中心里“直接挑选并生效”的统一入口（INBOXPICK-S；项目方原话：“这些请在网页系统里面通知我选择，这样才是正确。”）。

POST /api/owner/pick {id, choice, reason?}
  · by 只从登录会话取（不信前端传的）；没登录 / 不是项目方 → 403。
  · 先回 202 收下，再异步处理；处理成功 → 这条请求标 done（pick_state.json + decisions.jsonl 一行），通知从页面上消失；
    处理失败 → 标 failed 并带原因，通知重新出现（可再点）。
  · 同一条请求重复提交，只处理第一次（accepted / processing / done 再提交只回 202 + duplicate）。
  · choice="revise"（“修改”）：不动任何配置，记下意见，通知保留并显示“已提修改意见”。L-123：没有“不要”。
按条目类型分派（id 形如 pick:<类型>:<对象>）：
  voice_v2  把选中的候选从 config/voices_v2.json 的 support_candidates 挪进 roles（enabled + selected），更新 cast_voice.map，
            未选中的标 archived；写之前核对 sha、原子写；写完跑 run_media.voice_config(run) 确认每个槽恰好 1 个启用音色，不通过就回滚。
  face / scene / sheet / item  已接（AUTOPIPE-A 11-03，M-AUTOPIPE-01 阶段 A）：登记进 assets_v2/manifest.json（file + sha256，face 连 display_name）、
            推两台并核 sha、重跑 episode_ready（READY_HOOK → tools/pipeline/asset_jobs.after_pick）。旧式 id v2cast-<对象>（CAST-S）同样消费。
给新类型接入：写一个 apply(root, req, choice, by) -> dict，登记进 HANDLERS（wired=True），并在 audio_for / media_for 里补候选的试听 / 缩略图地址。
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

REPO = Path(__file__).resolve().parents[3]
router = APIRouter(tags=["owner-pick"])
_lock = threading.Lock()
BLOCKING = ("accepted", "processing", "done")     # 这些状态下再提交 = 重复，不再处理
REPLAY_TIMEOUT_S = 1800      # 启动补执行的总时限：超时后剩下的条目留给下次启动 / CLI（不阻塞启动，ISS-1103-004547-6260）


class PickError(Exception):
    """处理失败（原因写给项目方看，中文一句话）"""


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _atomic_json(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=p.name + ".", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False, indent=1))
    os.replace(tmp, p)


def _sha_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


# ------------------------------------------------------------------ 状态
def _state_path(root: Path) -> Path:
    return root / "data" / "owner_queue" / "pick_state.json"


def state(root: Path) -> dict:
    p = _state_path(root)
    if not p.is_file():
        return {}
    d = None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except ValueError as e:                        # 坏了不当成“没有”：写警告，按空处理，下次成功写入会覆盖
        from ns_api import owner_queue as OQ  # noqa: PLC0415
        OQ._warn(f"{p} 读不出来，按空处理：{e!r}")
    return d if isinstance(d, dict) else {}


def hidden_ids(root: Path) -> set[str]:
    """已收下 / 处理中 / 已完成的挑选：不再出现在通知里（L-136 代选完成的除外：留在通知里显示“已代选，可修改”）"""
    keep = delegated_ids(root)
    return {i for i, s in state(root).items() if (s or {}).get("state") in BLOCKING and i not in keep}


DELEGATE_SHOW_S = 72 * 3600     # L-136：代选的条目在通知里保留这么久（显示“已代选：候选 N（可修改）”）


def delegated_ids(root: Path) -> set[str]:
    """代选（ns_api.owner_delegate）选定、项目方还没处理完的条目：done（已代选）/ revise_requested（项目方点了修改）"""
    out = set()
    for i, s in state(root).items():
        dg = (s or {}).get("delegate") or {}
        if not dg or (s or {}).get("state") not in ("done", "revise_requested", "processing", "accepted", "failed"):
            continue
        try:
            age = time.time() - time.mktime(time.strptime(str(dg.get("at")), "%Y-%m-%dT%H:%M:%S"))
        except ValueError:
            age = 0
        if age < DELEGATE_SHOW_S:
            out.add(i)
    return out


def state_of(root: Path, item_id: str) -> dict:
    return state(root).get(item_id) or {}


def _set_state(root: Path, item_id: str, **kw) -> dict:
    with _lock:
        st = state(root)
        row = {**(st.get(item_id) or {}), **kw, "updated": _now()}
        st[item_id] = row
        _atomic_json(_state_path(root), st)
        return row


# ------------------------------------------------------------------ 分派
def kind_of(item_id: str) -> str:
    """pick:<kind>:<对象> → kind；旧式 v2cast-<对象>（CAST-S 11-03 投的 4 条）：ch_* = face、sk_* = scene（asset_jobs.pick_object 同一口径）"""
    parts = str(item_id).split(":")
    if len(parts) >= 3 and parts[0] == "pick":
        return parts[1]
    if str(item_id).startswith("v2cast-"):
        return "scene" if str(item_id)[7:].startswith("sk_") else "face"
    return ""


def _file_url(rel: str) -> str:
    rel = rel.replace("\\", "/")
    return "/files/" + (rel[5:] if rel.startswith("data/") else rel)


def _voice_support(root: Path, item_id: str) -> tuple[dict, dict, str]:
    role = item_id.split(":")[2]
    d = json.loads((root / "config" / "voices_v2.json").read_text(encoding="utf-8"))
    return d, ((d.get("support_candidates") or {}).get("roles") or {}).get(role) or {}, role


def audio_for(root: Path, item_id: str, key: str) -> str | None:
    """候选的试听地址（/files/…）；没有就 None"""
    if ALIASES.get(kind_of(item_id), kind_of(item_id)) != "voice":
        return None
    try:
        _, sup, role = _voice_support(root, item_id)
    except (OSError, ValueError, IndexError):
        return None
    c = next((c for c in sup.get("candidates") or [] if str(c.get("cand")) == str(key)), None)
    if not c:
        return None
    for rel in (f"data/review_pages/v2_style/voice/{role}_{key}_sample.wav", f"{c.get('dir', '')}/sample.wav"):
        p = root / rel
        if p.is_file():
            return f"{_file_url(rel)}?v={int(p.stat().st_mtime)}"
    return None


# ------------------------------------------------------------------ voice_v2
def voice_run(root: Path, req: dict | None = None) -> str:
    """音色挑选对应的剧（AUTOFIX-O 11-03：不再写死 series10_v2）：请求里写的 run（须在 runs.json 登记且是资产包模式）→
    否则 runs.json primary（须是资产包模式）；都不满足 = PickError（voices_v2.json 只属于资产包模式的剧，不回退 V1）"""
    try:
        reg = json.loads((root / "config" / "pipeline" / "runs.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise PickError(f"config/pipeline/runs.json 读不出来：{e}") from e
    runs = reg.get("runs") or {}
    for r in ((req or {}).get("run"), reg.get("primary")):
        if r and (runs.get(r) or {}).get("assets_manifest"):
            return str(r)
    raise PickError(f"找不到这条音色挑选对应的资产包模式剧（请求 run={(req or {}).get('run')!r}，primary={reg.get('primary')!r}）")


def _verify_voice(root: Path, run: str | None = None) -> None:
    """写完后跑 run_media.voice_config(run)：每个槽恰好 1 个启用音色、ref sha 对得上、cast_voice 映射到的槽都在"""
    for p in (str(root / "services" / "post"), str(root / "services" / "agent")):
        if p not in sys.path:
            sys.path.insert(0, p)
    from ns_post import run_media as RM  # noqa: PLC0415
    try:
        RM.voice_config(run or voice_run(root), root)
    except Exception as e:  # noqa: BLE001  V2MediaError / 任何读不出来都算不通过
        raise PickError(f"写入后 voice_config 加载不通过：{e}") from e


def apply_voice_v2(root: Path, req: dict, choice: str, by: str, verify=None) -> dict:
    cfg_p = root / "config" / "voices_v2.json"
    raw = cfg_p.read_bytes()
    sha0 = _sha_bytes(raw)
    d = json.loads(raw.decode("utf-8"))
    role = str(req["id"]).split(":")[2]
    sup = ((d.get("support_candidates") or {}).get("roles") or {}).get(role)
    if not sup:
        raise PickError(f"support_candidates 里没有 {role}（可能已经挑过了）")
    if role in (d.get("roles") or {}):
        raise PickError(f"roles 里已经有 {role}，不重复挪入")
    cands = copy.deepcopy(sup.get("candidates") or [])
    chosen = next((c for c in cands if str(c.get("cand")) == choice), None)
    if not chosen:
        raise PickError(f"{role} 没有候选 {choice}")
    ref = root / chosen["dir"] / "ref.wav"
    sample = root / chosen["dir"] / "sample.wav"
    if not ref.is_file() or _sha_bytes(ref.read_bytes()) != chosen.get("ref_sha256"):
        raise PickError(f"候选 {choice} 的 ref.wav 不存在或 sha 不符，不启用")
    if not sample.is_file():
        raise PickError(f"候选 {choice} 的 sample.wav 不存在")
    for c in cands:
        if c is chosen:
            c.update(enabled=True, selected=True, ref_wav=f"{c['dir']}/ref.wav", sample_wav=f"{c['dir']}/sample.wav",
                     sample_sha256=_sha_bytes(sample.read_bytes()), picked_by=by, picked_at=_now())
            c.pop("status", None)
            c.pop("archived", None)
        else:
            c.update(enabled=False, archived=True)
            c.pop("selected", None)
            c.pop("status", None)
    d.setdefault("roles", {})[role] = {"persona": sup.get("persona"), "char_id": sup.get("char_id"), "candidates": cands, "selected": choice}
    cv = d.setdefault("cast_voice", {})
    if sup.get("char_id"):
        cv.setdefault("map", {})[sup["char_id"]] = role
        (cv.setdefault("why", {}))[sup["char_id"]] = f"{by} 在待办通知中心挑定 {role}_{choice}（{_now()}）"
    left = d["support_candidates"]["roles"]
    left.pop(role, None)
    if left:
        cv["unvoiced_note"] = "还没选定音色的配角：" + "、".join(str(v.get("char_id") or k) for k, v in left.items()) + "（待项目方挑）"
    else:
        cv.pop("unvoiced_note", None)
        d["support_candidates"]["status"] = "已全部选定"
    # 写之前核对 sha（读到现在文件没被别人动过），原子写；写完验，不通过就把原文件换回去
    if _sha_bytes(cfg_p.read_bytes()) != sha0:
        raise PickError("config/voices_v2.json 在处理途中被别人改了，没写入；请再点一次")
    _atomic_json(cfg_p, d)
    try:
        if verify:
            verify(root)
        else:
            _verify_voice(root, voice_run(root, req))
    except Exception:
        fd, tmp = tempfile.mkstemp(dir=str(cfg_p.parent), prefix=cfg_p.name + ".", suffix=".tmp")
        with os.fdopen(fd, "wb") as f:
            f.write(raw)
        os.replace(tmp, cfg_p)
        raise
    return {"role": role, "picked": f"{role}/{choice}", "cast_voice": sup.get("char_id"), "config_sha_before": sha0[:12],
            "config_sha_after": _sha_bytes(cfg_p.read_bytes())[:12], "archived": [c["cand"] for c in cands if c is not chosen]}


# ---- 处理器注册表（M-AUTOPIPE-01：/api/owner/pick 是整条流水线统一的选定入口；按 id 里的类型分派：pick:<kind>:<对象>）
# 约定：apply(root, req, choice, by, verify=None) -> dict（写进 decisions.jsonl 的 applied）。
#   · 入参 req = requests.json 里那条 pick 请求；choice = 候选 key；by = 登录会话里的项目方名字。
#   · 必须：写之前核对 sha、原子写、写完自检，不通过就回滚并抛 PickError(中文原因) —— 条目会带原因重新出现。
#   · 登记哪些字段、写完后做什么，见各 kind 的 CONTRACT。写完后统一重跑 episode_ready（RERUN_READY 钩子，见 after_apply）。
HANDLERS: dict = {}
ALIASES = {"voice_v2": "voice", "image": "face"}      # 旧 id 类型 → 注册名
CONTRACT = {
    "voice": "已实现。roles[槽] 挪入 voices_v2.json（enabled+selected+ref_wav+sample_sha256+picked_by），cast_voice.map[char_id]=槽，其余候选 archived；写后跑 run_media.voice_config 自检。",
    "face": "已实现（AUTOPIPE-A 11-03，tools/pipeline/asset_jobs.register_pick）。候选带 file/thumb/sha256；选中 → 拷进 assets_v2/characters/<cid>/face/，"
            "写清单 characters[cid].face（file + sha256 + picked_by + candidates_archived），display_name 没有就从 P1 人物表补；已有脸不覆盖（抛 PickError）；"
            "推两台（sync.verified_install 核 sha，失败登记卡点不回滚）；写后经 READY_HOOK 重跑 episode_ready。",
    "scene": "已实现。选中 → 拷进 assets_v2/scenes/<sid>/，写清单 scenes[sid].base（file + sha256），其余 archived；推两台并核 sha；重跑 episode_ready。",
    "sheet": "已实现。配角造型设定图：选中 → assets_v2/characters/<cid>/looks/，写清单 characters[cid].looks[look].sheet（file + sha256）；推两台并核 sha。",
    "item": "已实现。单品图：选中 → assets_v2/characters/<cid>/items/，写清单 looks[look].items[<id>]（file + sha256 + no_brand）；推两台并核 sha。",
}


_AJ = None     # tools/pipeline/asset_jobs 模块缓存（测试可直接塞进来）
_CODE_ROOT = Path(__file__).resolve().parents[3]     # 代码永远从本仓库取（REPO 在测试里会被换成临时数据目录）


def _asset_jobs():
    global _AJ
    if _AJ is None:
        import importlib.util as _u  # noqa: PLC0415
        sp = _u.spec_from_file_location("asset_jobs_for_owner_pick", _CODE_ROOT / "tools" / "pipeline" / "asset_jobs.py")
        m = _u.module_from_spec(sp)
        sp.loader.exec_module(m)
        _AJ = m
    return _AJ


def _asset_apply(kind: str):
    """face / scene / sheet / item 处理器：登记逻辑在 tools/pipeline/asset_jobs.register_pick（可独立测试），这里只做 PickError 转换"""
    def apply(root: Path, req: dict, choice: str, by: str, verify=None) -> dict:
        AJ = _asset_jobs()
        try:
            return AJ.register_pick(root, kind, req, choice, by, pusher=verify)
        except AJ.RegisterError as e:
            raise PickError(str(e)) from e
    apply.__name__ = f"apply_{kind}"
    return apply


def enqueue_pick(root: Path, req: dict) -> dict:
    """投一条 pick 到待办通知（data/owner_queue/requests.json，列表；同 id 已有则替换）。各线投候选统一走这里（CAST-S 卡点 ⑤）。
    req 至少要有 id / kind=pick / title / candidates[{key,label,contract_ok,file|audio,...}]；detail 没写就用 pick_detail 模板"""
    from ns_api import owner_queue as OQ  # noqa: PLC0415
    if not req.get("id") or not req.get("candidates"):
        raise ValueError("pick 请求至少要有 id 和 candidates")
    req = {"kind": "pick", "at": _now(), **req}
    if not req.get("detail"):
        req["detail"] = pick_detail(str(req.get("title") or req["id"]), len(req["candidates"]))
    p = OQ._paths(root)["requests"]
    with _lock:
        rows = OQ.requests(root) if p.is_file() else []
        rows = [r for r in rows if str(r.get("id")) != str(req["id"])] + [req]
        _atomic_json(p, rows)
    return req


def register(kind: str, fn, wired: bool = True) -> None:
    fn.wired = wired
    HANDLERS[kind] = fn


def _todo(kind: str):
    def apply(root: Path, req: dict, choice: str, by: str, verify=None) -> dict:
        # TODO(资产线)：按 CONTRACT[kind] 实现，然后 register(kind, fn, wired=True)；实现前 wired=False，该类条目仍走 /api/owner/decide
        raise PickError(f"{kind} 类挑选的落地还没接（资产线 TODO）")
    return apply


def after_apply(root: Path, kind: str, res: dict) -> None:
    """登记完成后重跑 episode_ready，让流水线自动进入下一阶段（阶段 A → B）。钩子：READY_HOOK = fn(root, kind, res)，res 带 pick_id"""
    hook = READY_HOOK
    if hook:
        hook(root, kind, res)


def _ready_hook(root: Path, kind: str, res: dict) -> None:
    """AUTOPIPE-A 11-03：对应的资产作业标 done → 重跑 episode_ready（asset_jobs.generate，幂等）→ 全部就绪时写阶段 B 作业 golden-epNN"""
    _asset_jobs().after_pick(root, kind, res)


READY_HOOK = _ready_hook


register("voice", apply_voice_v2)
for _k in ("face", "scene", "sheet", "item"):
    register(_k, _asset_apply(_k))



def handler_of(item_id: str):
    k = kind_of(item_id)
    return HANDLERS.get(ALIASES.get(k, k))


def wired(item_id: str) -> bool:
    h = handler_of(item_id)
    return bool(h and getattr(h, "wired", False))


# ------------------------------------------------------------------ 提交 / 处理
def _request_of(root: Path, item_id: str) -> dict | None:
    from ns_api import owner_queue as OQ  # noqa: PLC0415
    return next((r for r in OQ.requests(root) if str(r.get("id")) == item_id and r.get("kind") == "pick"), None)


def accept(root: Path, item_id: str, choice: str, reason: str, by: str) -> dict:
    """同步部分：校验 + 占位（重复提交在这里挡掉）。返回 {"duplicate": bool, "state": row}"""
    req = _request_of(root, item_id)
    if not req:
        raise HTTPException(404, f"通知里没有 {item_id}（可能已经处理过）")
    keys = {str(c.get("key")) for c in req.get("candidates") or [] if isinstance(c, dict)}
    if choice != "revise" and choice not in keys:
        raise HTTPException(400, f"{item_id} 只能选：{'、'.join(sorted(keys))}，或点“修改”")
    if choice != "revise" and not wired(item_id):
        raise HTTPException(501, f"{kind_of(item_id) or item_id} 类挑选的落地还没接，先走 /api/owner/decide")
    with _lock:
        cur = state(root).get(item_id) or {}
        if choice != "revise" and cur.get("delegate") and cur.get("state") == "done" and not str(by).startswith("总调度代选"):
            # L-136：项目方在已代选的条目上改选别的候选 = “修改”（登记处理器不覆盖已登记的脸 / 音色，按原有修改机制由下游重做）
            reason = f"改选候选 {choice}（推翻代选的 {cur.get('choice')}）" + (f"：{reason}" if reason else "")
            choice = "revise"
        if choice != "revise" and cur.get("state") in BLOCKING:
            return {"duplicate": True, "state": cur}
        row = {**cur, "state": "revise_requested" if choice == "revise" else "accepted", "choice": choice, "by": by, "reason": reason[:300],
               "accepted_at": _now(), "error": None, "updated": _now()}
        st = state(root)
        st[item_id] = row
        _atomic_json(_state_path(root), st)
    return {"duplicate": False, "state": row, "choice": choice}


def process(root: Path, item_id: str, choice: str, by: str, apply_fn=None, replayed_from: str | None = None, via: str = "owner_pick") -> dict:
    """异步部分：按类型分派；成功标 done 并写 decisions.jsonl，失败标 failed（通知重新出现）。
    via：项目方点选 = owner_pick；补执行 = owner_pick:startup（API 启动）/ owner_pick:cli（命令行）；都带 pid（RESTARTFIX-O）"""
    if choice == "revise":
        _record(root, item_id, "revise", by, state_of(root, item_id).get("reason", ""), None, via)
        return state_of(root, item_id)
    _set_state(root, item_id, state="processing")
    try:
        req = _request_of(root, item_id) or {"id": item_id}
        fn = apply_fn or handler_of(item_id)
        res = fn(root, req, choice, by)
        if isinstance(res, dict):
            res.setdefault("pick_id", item_id)
        after_apply(root, kind_of(item_id), res)
        if replayed_from:
            res = {**res, "replayed_from": replayed_from}
    except PickError as e:
        return _set_state(root, item_id, state="failed", error=str(e))
    except Exception as e:  # noqa: BLE001  任何异常都别吞：标 failed、带原因
        return _set_state(root, item_id, state="failed", error=f"{type(e).__name__}: {e}"[:300])
    row = _set_state(root, item_id, state="done", result=res, done_at=_now(), error=None)
    _record(root, item_id, choice, by, "", res, via)
    return row


def _record(root: Path, item_id: str, choice: str, by: str, reason: str, res: dict | None, via: str = "owner_pick") -> None:
    from ns_api import owner_queue as OQ  # noqa: PLC0415
    OQ._record(root, {"id": item_id, "kind": "pick", "choice": choice, "by": by, "reason": reason, "via": via, "pid": os.getpid(), "applied": res})


# ------------------------------------------------------------------ replay：旧入口（/decide）留下的选择补执行一次
REPLAY_STALE_S = 1800      # 补执行占位（accepted / processing）超过这么久还没收尾 = 当时的进程已经没了，可以重补


def _held(row: dict, stale_s: float | None) -> bool:
    """这一条现在算“已收下 / 处理中 / 已完成”吗。AUTOFIX-O 11-03：11-03 00:59 有一次补执行进程中途没了，
    v2cast-ch_tang_yao 停在 accepted（replay=true）永远不再补；补执行留下的占位超过 stale_s 没更新 → 视为陈旧、允许重补"""
    st = (row or {}).get("state")
    if st not in BLOCKING:
        return False
    if st == "done" or stale_s is None or not row.get("replay"):
        return True
    try:
        age = time.time() - time.mktime(time.strptime(str(row.get("updated") or row.get("accepted_at")), "%Y-%m-%dT%H:%M:%S"))
    except ValueError:
        return True
    return age < stale_s


def replay(root: Path = REPO, apply_fn=None, deadline: float | None = None, stale_s: float | None = REPLAY_STALE_S,
           via: str = "owner_pick:cli") -> list[dict]:
    """凡是走统一入口的条目，decisions.jsonl 里已有项目方经旧入口做的选择、但处理器还没执行过 → 用同一个处理器补执行一次。
    by 取原记录里的项目方名字；applied.replayed_from = "<原决定时间> <id>"；每条只补一次（补完标 done，再跑不会重复写）。
    只补 wired 的类型；POLICY 自动选的、later / undo、via=owner_pick 的不补。时机：API 启动时（后台线程，不阻塞启动）+ CLI `owner_pick.py replay`。
    deadline：到点后不再开始新条目（state=deferred，不占位，下次照补）"""
    from ns_api import owner_queue as OQ  # noqa: PLC0415
    last: dict[str, dict] = {}
    for d in OQ.decisions(root):
        if d.get("id"):
            last[str(d["id"])] = d
    out = []
    for r in OQ.requests(root):
        iid = str(r.get("id"))
        d = last.get(iid)
        if r.get("kind") != "pick" or not d or not wired(iid) or _held(state_of(root, iid), stale_s):
            continue
        keys = {str(c.get("key")) for c in r.get("candidates") or [] if isinstance(c, dict)}
        if d.get("kind") != "pick" or str(d.get("via") or "").startswith("owner_pick") or d.get("by") in (None, "", "POLICY") or str(d.get("choice")) not in keys:
            continue
        if deadline is not None and time.time() > deadline:     # 到时限：不再开始新条目（不占位，下次照补）
            out.append({"id": iid, "choice": d["choice"], "by": d["by"], "state": "deferred", "error": "补执行到时限，留到下次"})
            continue
        with _lock:       # 占位：并发的第二个 replay / 手点会被当成重复
            st = state(root)
            if _held(st.get(iid) or {}, stale_s):
                continue
            if (st.get(iid) or {}).get("state") in BLOCKING:
                OQ._warn(f"owner_pick replay：{iid} 的补执行占位 {st[iid].get('state')}（{st[iid].get('updated')}）已陈旧，重补")
            st[iid] = {"state": "accepted", "choice": str(d["choice"]), "by": d["by"], "reason": "", "accepted_at": _now(), "updated": _now(), "replay": True,
                       "via": via, "pid": os.getpid()}
            _atomic_json(_state_path(root), st)
        row = process(root, iid, str(d["choice"]), str(d["by"]), apply_fn, replayed_from=f"{d.get('at')} {iid}", via=via)
        out.append({"id": iid, "choice": d["choice"], "by": d["by"], "state": row.get("state"), "error": row.get("error")})
    return out


def _replay_bg(root: Path, timeout_s: float, require_port: bool = False) -> None:
    try:
        if require_port:
            from ns_api import instance as INST  # noqa: PLC0415
            if not INST.holds_port():
                from ns_api import owner_queue as OQ  # noqa: PLC0415
                OQ._warn(f"owner_pick replay 启动补执行跳过：本进程（pid {os.getpid()}）没有在 :{INST.port()} 上服务（端口被别的实例占着 / 没起来）")
                return
        res = replay(root, deadline=time.time() + timeout_s, via="owner_pick:startup")
        left = [r["id"] for r in res if r.get("state") == "deferred"]
        if left:
            from ns_api import owner_queue as OQ  # noqa: PLC0415
            OQ._warn(f"owner_pick replay 启动补执行超过 {int(timeout_s)} s，剩 {len(left)} 条留到下次（或 CLI owner_pick.py replay）：{left}")
    except Exception as e:  # noqa: BLE001  补执行失败不拖垮服务：写警告，条目仍在通知里可以手点
        from ns_api import owner_queue as OQ  # noqa: PLC0415
        OQ._warn(f"owner_pick replay 启动补执行失败：{e!r}")


def start_replay_thread(root: Path = REPO, timeout_s: float = REPLAY_TIMEOUT_S, require_port: bool = False) -> threading.Thread:
    """ISS-1103-004547-6260：启动补执行放后台守护线程（里面有 SSH 推送 + 重跑 episode_ready，可能要几分钟），
    启动事件立刻返回；带总时限（到点后不再开始新条目，剩下的留给下次）。require_port：先确认本进程在 :8800 上服务"""
    t = threading.Thread(target=_replay_bg, args=(root, timeout_s, require_port), name="owner_pick_replay", daemon=True)
    t.start()
    return t


@router.on_event("startup")
def _replay_on_startup():
    """API 启动时在后台补执行（不阻塞启动）。RESTARTFIX-O（ISS-1103-011049-7420）：只在看门狗管理的正式实例上跑
    （NS_API_MANAGED=1 + 单实例锁；TestClient / 手起 uvicorn / 预检 / pytest 都不跑），且后台线程先确认本进程确实在 :8800 上服务"""
    if os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("NS_API_PREFLIGHT"):
        return
    from ns_api import instance as INST  # noqa: PLC0415
    if not INST.startup_side_effects_allowed():
        return
    start_replay_thread(REPO, require_port=True)
    from ns_api import owner_delegate as OD  # noqa: PLC0415  L-136 代选后台拍（开关关着时每拍只读一次配置）
    OD.start_thread(REPO)


# 投递模板（VOICE-S / CAST-S 等投 pick 请求统一用它，文字固定为“直接在这里试听 / 看图，点‘用这个’就选定”）
PICK_DETAIL = "{who}有 {n} 个候选{extra}。直接在这里试听 / 查看，点“用这个”就选定并生效；都不合适点“修改”写一句意见。"


def pick_detail(who: str, n: int, extra: str = "") -> str:
    return PICK_DETAIL.format(who=who, n=n, extra=f"（{extra}）" if extra else "")


# ------------------------------------------------------------------ HTTP
class Pick(BaseModel):
    id: str
    choice: str
    reason: str = ""


@router.post("/api/owner/pick")
def post_pick(body: Pick, request: Request, bg: BackgroundTasks):
    from ns_api import auth  # noqa: PLC0415
    u = auth.user_of(request)
    if not u or u.get("role") != "owner":      # by 只从登录会话取，不看前端传来的
        raise HTTPException(403, "只有登录的项目方本人能在这里挑选（登录即本人，不用打字）")
    r = accept(REPO, body.id, body.choice, body.reason, u["name"])
    if not r["duplicate"]:
        bg.add_task(process, REPO, body.id, r.get("choice", body.choice), u["name"])
    return JSONResponse({"ok": True, "accepted": True, "duplicate": r["duplicate"], "state": r["state"].get("state")}, status_code=202)


@router.get("/api/owner/pick/{item_id:path}")
def get_pick_state(item_id: str):
    return state_of(REPO, item_id) or {"state": "none"}


from ns_api import owner_delegate as _OD  # noqa: E402  L-136 代选：状态 / 一键撤销接口挂在本路由上（app.py 不用另加 include_router）
router.include_router(_OD.router)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "replay":
        for p_ in (str(REPO / "services" / "api"),):
            if p_ not in sys.path:
                sys.path.insert(0, p_)
        stale = next((float(a.split("=", 1)[1]) for a in sys.argv[2:] if a.startswith("--stale-s=")), REPLAY_STALE_S)
        res = replay(REPO, stale_s=stale, via="owner_pick:cli")
        print(json.dumps(res, ensure_ascii=False, indent=1) if res else "没有需要补执行的旧决定")
        sys.exit(1 if any(r["state"] != "done" for r in res) else 0)
    print("用法：python services/api/ns_api/owner_pick.py replay")
    sys.exit(2)

