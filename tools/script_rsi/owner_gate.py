"""写作链的项目方闸门（总调度 11-02，L-123：只有“用这版”和“修改”，没有“不要”；“修改”先收下、异步处理、原位显示状态）。

<run>/owner_gates.json：{"enabled": true, "gates": {"P1": {...}, "ep01": {...}}, "history": [...]}
  P1     故事线 + 造型表：收下后停在 pending，等项目方点“用这版”（approved）或“修改”（revise_requested + 一句话）。
  epNN   每集 P2–P4：默认自动通过（不停）；项目方随时可以点“修改”→ revise_requested，下一次推进时出整集返修包。
状态：pending → approved；revise_requested → revising（返修包已出）→ pending（P1 新稿回来）/ approved（集返修稿收下）。
读方：autoflow_agent（推进时按闸门停 / 出返修包）、ns_api.script_autoflow（网页按钮 + 状态）。
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

FILE = "owner_gates.json"
ACTIONS = ("approve", "revise")


def enabled(run_dir: Path) -> bool:
    """有 owner_gates.json 的 run 设闸门（新建剧本页 / V2 起）；完全切割的 run（CLEAN_CUT.json）一律有闸门——
    11-02 19:17 事故：V2 的 owner_gates.json 还没建（19:17:57 才建），19:17:06 一次命令行推进就越过 P1 出了 P2 包"""
    return (run_dir / FILE).exists() or (run_dir / "CLEAN_CUT.json").exists()


def p1_review_ok(run_dir: Path) -> tuple[bool, str]:
    """P1 三评委过没过（V2-WALK W-25：“用这版”不能绕过 34 分门槛）：judge_p1/STATE.json 最后一轮 passed=True，且那一轮评的 sha = 当前 P1_storyline.json 的 sha。
    没有评审状态：完全切割的 run 算没过（V2 必须评审）；旧 run 不设这道门槛"""
    import hashlib
    sp = run_dir / "judge_p1" / "STATE.json"
    canon = run_dir / "P1_storyline.json"
    rounds0 = (json.loads(sp.read_text(encoding="utf-8")).get("rounds") or []) if sp.exists() else []
    last = rounds0[-1] if rounds0 else None
    if last and last.get("revise_issued") and not last.get("passed"):      # 先说评审状态（总调度 11-02：返修期间 P1 正式稿被改名留档，不能报“没有故事线”）
        mean = (last.get("result") or {}).get("mean")
        return False, (f"第 {last.get('n')} 轮评审均分 {mean}/40，没到门槛，正在返修第 {int(last.get('n') or 0) + 1} 稿；"
                       "新稿评审过了门槛才能用这版")
    if not canon.exists():
        return False, "还没有 P1 故事线"
    if not sp.exists():
        return (False, "故事线还没过三评委评审") if (run_dir / "CLEAN_CUT.json").exists() else (True, "")
    rounds = json.loads(sp.read_text(encoding="utf-8")).get("rounds") or []
    if not rounds:
        return False, "故事线还没过三评委评审"
    cur = rounds[-1]
    sha = hashlib.sha256(canon.read_text(encoding="utf-8").encode("utf-8")).hexdigest()[:16]
    if cur.get("sha") != sha:
        return False, f"当前故事线还没评审（第 {len(rounds) + 1} 轮评审包出来、评分过了门槛才能用这版）"
    if not cur.get("passed"):
        return False, f"故事线还在评审：第 {cur.get('n')} 轮评审分出来、过了门槛才能用这版" if cur.get("passed") is None else \
            f"第 {cur.get('n')} 轮评审没过门槛（{'；'.join(cur.get('why') or [])}），在返修"
    return True, ""


def p1_approved(run_dir: Path) -> bool:
    if not enabled(run_dir):
        return True
    return get(run_dir, "P1").get("status") == "approved" and p1_review_ok(run_dir)[0]


def _read(run_dir: Path) -> dict:
    p = run_dir / FILE
    if not p.exists():
        return {"enabled": False, "gates": {}, "history": []}
    return json.loads(p.read_text(encoding="utf-8"))          # 坏文件直接抛出：闸门状态读不准时不能放行


def _write(run_dir: Path, d: dict) -> None:
    p = run_dir / FILE
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    for i in range(40):
        try:
            os.replace(tmp, p)
            return
        except PermissionError:
            time.sleep(0.05 * (i + 1))
    os.replace(tmp, p)


def enable(run_dir: Path, by: str = "system") -> dict:
    d = _read(run_dir)
    d["enabled"] = True
    d.setdefault("gates", {})
    d.setdefault("history", []).append({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "key": "*", "action": "enable", "by": by})
    _write(run_dir, d)
    return d


def get(run_dir: Path, key: str) -> dict:
    g = _read(run_dir).get("gates", {}).get(key)
    if g is None:
        return {"status": "approved" if key.startswith("ep") else "pending"}      # 集默认自动通过；P1 默认等人
    return g


def set_status(run_dir: Path, key: str, status: str, **extra) -> dict:
    d = _read(run_dir)
    g = d.setdefault("gates", {}).setdefault(key, {})
    g.update(status=status, at=time.strftime("%Y-%m-%dT%H:%M:%S"), **extra)
    d.setdefault("history", []).append({"at": g["at"], "key": key, "status": status, **{k: v for k, v in extra.items() if k != "note"}})
    _write(run_dir, d)
    return g


def act(run_dir: Path, key: str, action: str, note: str = "", by: str = "项目方") -> dict:
    """网页按钮：approve =“用这版”；revise =“修改”（一句话）。先收下，推进由 autoflow 异步处理"""
    if action not in ACTIONS:
        raise ValueError(f"只认 {ACTIONS}（L-123：没有“不要”）")
    if action == "revise" and not note.strip():
        raise ValueError("“修改”要写一句话")
    if not (key == "P1" or (key.startswith("ep") and key[2:].isdigit())):
        raise ValueError("闸门只有 P1 和 epNN")
    if action == "approve" and key == "P1":
        ok, why = p1_review_ok(run_dir)
        if not ok:
            raise PermissionError(why)          # “修改”照常收；“用这版”只有过了三评委门槛才收（W-25）
    d = _read(run_dir)
    g = d.setdefault("gates", {}).setdefault(key, {})
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    if action == "approve":
        g.update(status="approved", at=now, by=by)
    else:
        g.update(status="revise_requested", note=note.strip()[:2000], at=now, by=by, handled=False)
    d.setdefault("history", []).append({"at": now, "key": key, "action": action, "by": by, "note": note.strip()[:300]})
    d["enabled"] = True
    _write(run_dir, d)
    return g


def summary(run_dir: Path) -> dict:
    d = _read(run_dir)
    return {"enabled": bool(d.get("enabled")), "gates": d.get("gates", {}), "history": (d.get("history") or [])[-20:]}
