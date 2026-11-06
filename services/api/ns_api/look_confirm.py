"""资产包剧（V2 等）的“确认本集造型”——画布入口和待办通知中心（/api/owner/inbox）走同一个后端（V2CUT-O 11-03，总调度派）。

项目方 00:48 截图“确认造型：lead_f”的三个问题，根因都在后端只给了角色 id、按 V1 的造型库取“本集用”：
  · 每集一条：本集在画 / 局部的全部人物，每人带 display_name（清单）/ 本集造型（hub_episode_looks 排期 → 清单 looks）/ 缩略图 URL；
  · 一键确认整集：写 data/pipeline/runs/<run>/assets/look_confirm.json {集: {looks: {cid: 造型}, by, at, quote, via}}；
  · 确认记录绑定当时的造型快照：排期改了 → 快照对不上 → 重新要确认（旧通知作废，换新 id）；
  · 通知中心：owner_pick.enqueue_pick 投 pick:look:<run>:epNN:<快照> 一条，候选只有“确认本集造型”；处理器登记为 look
    （owner_pick.register，只调用公开接口）。画布确认后在 decisions.jsonl 记一行关掉这条通知；通知里确认后画布入口同时消失（同一份记录）。
V1（legacy 剧）/ 没有资产包清单的剧不走这里（返回 None，SOP 保持旧的逐角色确认）。
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
ADULT_NOTE = "成人造型，网页不显示图"


def _sop():
    from ns_api import sop as SOP  # noqa: PLC0415
    return SOP


def current_run(root: Path = REPO) -> str | None:
    """资产包剧（非 V1、有清单）的 run；否则 None。口径 = sop._current_run（同一份代码）"""
    return _sop()._current_run(Path(root))


def _script(root: Path, run: str):
    from ns_agent import run_paths as RPA  # noqa: PLC0415
    from ns_schema.script import ScriptImport  # noqa: PLC0415
    p = Path(RPA.runs_module(root).script_path(run, root))
    return ScriptImport.model_validate_json(p.read_text(encoding="utf-8")) if p.is_file() else None


def _thumb(rel: str | None) -> str | None:
    if not rel or not (REPO / rel).is_file():
        return None
    from ns_api import v2_assets as V2  # noqa: PLC0415
    return V2._url(rel)


def person(root: Path, run: str, cid: str, name: str, ep: int, man_chars: dict | None = None) -> dict:
    """一个人物在本集的造型卡：{cid, display_name, look_id, look_name, thumb_url, thumb_note, ready, wait}"""
    from ns_agent import asset_refs as AR  # noqa: PLC0415
    if man_chars is None:
        man_chars = (AR.manifest(run) or {}).get("characters") or {}
    mc = man_chars.get(cid) or {}
    display = mc.get("display_name") or (name if name != cid else "") or AR.MANIFEST_DEFAULT_ALIAS.get(cid) or "未命名人物"
    look_id = AR.episode_look_override(run, cid, ep)
    lk = (mc.get("looks") or {}).get(look_id) if look_id else None
    thumb, note = None, None
    if lk:
        if lk.get("adult"):
            note = ADULT_NOTE
        else:
            sheet = AR._manifest_file(lk.get("sheet")) if lk.get("sheet") else None
            item = next((AR._manifest_file(it) for it in (lk.get("items") or {}).values() if isinstance(it, dict) and AR._manifest_file(it)), None)
            thumb = _thumb(sheet or item)
    if thumb is None and note is None:
        thumb = _thumb(AR.face_of(run, cid))
    st = _sop().look_asset_state(Path(root), cid, display, ep)
    return {"cid": cid, "display_name": display, "look_id": look_id,
            "look_name": (lk.get("name") if lk else None) or ("本集还没排造型" if not look_id else f"造型 {look_id}"),
            "thumb_url": thumb, "thumb_note": note, "ready": bool(st["ready"]), "wait": st["wait"]}


def episode_people(root: Path, run: str, ep: int) -> list[dict]:
    """本集在画 / 局部的全部人物（剧本 **人物** 行，按出场顺序；与出图 asset_refs.cast_on_screen 同口径）"""
    from ns_agent import asset_refs as AR  # noqa: PLC0415
    er = _sop()._episode_ready_module()
    sc = _script(Path(root), run)
    e = next((x for x in (sc.episodes if sc else []) if x.number == ep), None)
    if e is None:
        return []
    try:
        AR.register_manifest_names(run)
    except Exception:  # noqa: BLE001
        pass
    man_chars = (AR.manifest(run) or {}).get("characters") or {}
    seen: dict[str, str] = {}
    for s in e.shots:
        for name, _pr in AR.cast_on_screen(s):
            cid = er.resolve_cid(run, AR.NAME_ID.get(name, name), name)
            seen.setdefault(cid, name)
    return [person(Path(root), run, cid, name, ep, man_chars) for cid, name in seen.items()]


def snapshot(people: list[dict]) -> dict[str, str | None]:
    return {p["cid"]: p["look_id"] for p in people}


def pick_id(run: str, ep: int, people: list[dict]) -> str:
    sig = hashlib.sha256(json.dumps(snapshot(people), sort_keys=True).encode()).hexdigest()[:10]
    return f"pick:look:{run}:ep{ep:02d}:{sig}"


def record_path(root: Path, run: str) -> Path:
    return Path(root) / "data" / "pipeline" / "runs" / run / "assets" / "look_confirm.json"


def records(root: Path, run: str) -> dict:
    p = record_path(root, run)
    if not p.is_file():
        return {}                     # 还没确认过任何一集（显式默认）
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError) as e:
        print(f"[look_confirm] {p} 读不出：{e} → 按未确认（失败关闭）", file=sys.stderr)
        return {}


def is_confirmed(root: Path, run: str, ep: int, people: list[dict]) -> bool:
    """确认过，且确认时的造型快照与现在的排期一致"""
    rec = records(root, run).get(str(ep)) or {}
    return bool(people) and rec.get("looks") == snapshot(people)


def episode_state(root: Path, run: str, ep: int) -> dict:
    """一集的确认造型状态（画布 SOP 动作和通知中心共用）"""
    people = episode_people(root, run, ep)
    waits = [p["wait"] for p in people if not p["ready"] and p["wait"]]
    return {"run": run, "episode": ep, "people": people, "confirmed": is_confirmed(root, run, ep, people),
            "ready": bool(people) and not waits, "waits": waits, "pick_id": pick_id(run, ep, people)}


def _atomic(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=p.name + ".", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(obj, ensure_ascii=False, indent=1) + "\n")
    os.replace(tmp, p)


def confirm(root: Path, run: str, ep: int, by: str, quote: str = "", via: str = "canvas") -> dict:
    """确认整集造型（唯一写入口）。人物资产没齐（身份脸 / 清单 / 排期）→ ValueError（原因是给项目方看的话）"""
    stt = episode_state(root, run, ep)
    if not stt["people"]:
        raise ValueError(f"第 {ep} 集剧本里没有在画的人物，不用确认造型")
    if not stt["ready"]:
        raise ValueError("；".join(stt["waits"]))
    rec = {"looks": snapshot(stt["people"]), "names": {p["cid"]: p["display_name"] for p in stt["people"]},
           "by": by, "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "quote": quote[:300], "via": via, "pick_id": stt["pick_id"]}
    d = records(root, run)
    d[str(ep)] = rec
    _atomic(record_path(root, run), d)
    if via != "owner_pick":                     # 画布确认：关掉通知中心里同一条（通知里确认的由 owner_pick 自己标 done）
        _close_pick(root, stt["pick_id"], "confirm", by, "画布确认")
    return {"episode": ep, "run": run, **rec}


def _close_pick(root: Path, item_id: str, choice: str, by: str, reason: str) -> None:
    from ns_api import owner_queue as OQ  # noqa: PLC0415
    OQ._record(Path(root), {"id": item_id, "kind": "pick", "choice": choice, "by": by, "reason": reason, "via": "look_confirm"})


def _open_look_picks(root: Path) -> list[dict]:
    from ns_api import owner_queue as OQ  # noqa: PLC0415
    closed = OQ._closed(Path(root), time.time())
    return [r for r in OQ.requests(Path(root)) if str(r.get("id", "")).startswith("pick:look:") and str(r["id"]) not in closed]


AUTO_BY = "系统（开项目规则 L-215：造型按排期自动确认）"


def look_auto(root: Path, run: str) -> bool:
    """开项目确认单 look_confirm=auto（缺省零等待）：每集造型来自 P1 排期 / hub_episode_looks / shot_looks，不再逐集问项目方"""
    import importlib.util  # noqa: PLC0415
    try:
        sp = importlib.util.spec_from_file_location("kickoff_for_look", REPO / "tools" / "pipeline" / "kickoff.py")
        m = importlib.util.module_from_spec(sp)
        sp.loader.exec_module(m)
        return bool(m.is_on("look_confirm", run, Path(root)))
    except Exception:  # noqa: BLE001  # arch-ok: 确认单读不到 = 旧行为（投通知等项目方确认）
        return False


def sync_picks(root: Path = REPO) -> list[str]:
    """把当前资产包剧每集“确认造型”投进通知中心（每集一条，已有不重投）；确认过 / 排期改了的旧条目关掉。返回现在开着的 id"""
    from ns_api import owner_pick as OP  # noqa: PLC0415
    run = current_run(root)
    if run is None:
        return []
    sc = _script(Path(root), run)
    want: dict[str, dict] = {}
    auto = look_auto(root, run)
    for e in (sc.episodes if sc else []):
        st = episode_state(root, run, e.number)
        if st["people"] and st["ready"] and not st["confirmed"]:
            if auto:                # L-215：开项目定了 look_confirm=auto → 按排期直接确认，不投通知（旧条目下面一并作废）
                try:
                    confirm(root, run, e.number, AUTO_BY, quote="开项目确认单 look_confirm=auto（L-215）", via="kickoff")
                except ValueError:  # arch-ok: 资产刚好变得不齐 = 下拍再确认（不投通知，不等项目方）
                    pass
                continue
            want[st["pick_id"]] = st
    opened = {str(r["id"]) for r in _open_look_picks(root)}
    for old in opened - set(want):
        _close_pick(root, old, "superseded", "SYSTEM", "本集造型已确认或排期改了，这条作废")
    for pid, st in want.items():
        if pid in opened:
            continue
        people = st["people"]
        first = next((p["thumb_url"] for p in people if p["thumb_url"]), None)
        names = "、".join(f"{p['display_name']}（{p['look_name']}）" for p in people)
        OP.enqueue_pick(Path(root), {
            "id": pid, "title": f"确认第 {st['episode']} 集造型：{'、'.join(p['display_name'] for p in people)}",
            "detail": f"本集造型：{names}。点“确认本集造型”一次确认全部人物；想换造型去资产页。",
            "source": "确认造型", "run": run, "episode": st["episode"], "link": "#/assets",
            "people": people, "recommend": "confirm",
            "candidates": [{"key": "confirm", "label": "确认本集造型", "contract_ok": True, "thumb": None, "file": None,
                            "thumb_url": first}]})
    return sorted(want)


def apply_pick(root: Path, req: dict, choice: str, by: str, verify=None) -> dict:
    """owner_pick 的 look 处理器：通知里点“确认本集造型”"""
    from ns_api import owner_pick as OP  # noqa: PLC0415
    run, ep = req.get("run"), req.get("episode")
    if not run or ep is None:
        try:
            _, _, run, eps, _sig = str(req.get("id")).split(":")
            ep = int(eps[2:])
        except ValueError as e:
            raise OP.PickError(f"看不懂这条确认造型通知：{req.get('id')}") from e
    if pick_id(run, int(ep), episode_people(root, run, int(ep))) != req.get("id"):
        raise OP.PickError("本集造型排期在通知发出后改过，这条已作废；刷新后按新的一条确认")
    try:
        return confirm(root, run, int(ep), by, "", via="owner_pick")
    except ValueError as e:
        raise OP.PickError(str(e)) from e


def register() -> None:
    from ns_api import owner_pick as OP  # noqa: PLC0415
    OP.register("look", apply_pick)


register()
