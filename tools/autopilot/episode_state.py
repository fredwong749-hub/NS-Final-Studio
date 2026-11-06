"""L-209 S2.2 集关闭标记（W-S22，11-07）：合成过闸的集 = 已关闭，所有执行器不再给它派活，除非重新打开。

开关：config/pipeline/state.json 键 episode_closed = "off" | "record" | "enforce"（或 {"mode": ...}）；缺省 = record。
  off     = 不算、不记、不挡（旧行为）；
  record  = 照算照记：会被跳过的派单记 ep_closed_skip（mode=record，skipped=false），照常派；
  enforce = 关闭的集 0 新派单（出图首尾帧 / 只重打分 / 换代与重出扫描 / 视频编排 / L-207 占卡），记 ep_closed_skip（skipped=true）。
  日志：每对象每小时最多一条，写 data/pipeline/runs/<run>/episode_closed_skips.jsonl（各机本地）。

唯一一份状态：data/pipeline/runs/<run>/episode_state.json（原子写；只有笔记本 resident_sync / API 写；
经 resident_sync.control_files() 推两台，整文件覆盖，merge_pull 不回拉）。服务器上的 producer / night / vidgen 只读。

“关闭”的口径（compute）：
  ① 成片目录 data/episodes/<剧>/ 里本集最新一版 epNN_vN.mp4（night finalize 只在硬规矩 HARD_RULES 过了才拷进来）
     且同名 timeline.json 的合成闸门 gates.verdict == "pass"（缺镜 / 对白溢出 = fail = 不关闭；11-07 03:04 ep01 v71 缺 S1 = fail）；
  ② 或项目方标了定稿（owner_final，mark_final）。
重新打开（reopen）：
  · 自动：本集关闭后项目方又提交了某镜的“修改 / 重出”（master_rejects 里项目方的新条目），或触发了本集新的成人镜（owner_triggers）；
  · 手动：POST /api/owner/episode-reopen（项目方登录，审计）或 CLI `episode_state.py reopen`（总调度按项目方对话指示）。
  重开一直有效，直到本集出了新一版过闸的成片（新版本号）才再次关闭。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CFG_REL = "config/pipeline/state.json"
KEY = "episode_closed"
MODES = ("off", "record", "enforce")
DEFAULT_MODE = "record"
RULE = "L-209 S2.2"
SKIP_EVERY_S = 3600.0
AUDIT_REL = "data/pipeline/episode_reopen_audit.jsonl"
_FINAL = re.compile(r"^ep(\d+)_v(\d+)\.mp4$")
_SID = re.compile(r"ep(\d+)-S\d+")
_mu = threading.Lock()
_logged: dict[tuple, float] = {}          # (run, obj, actor) → 上次记日志的时间（每对象每小时一条）


# ------------------------------------------------------------------ 小工具
def _jl(p: Path, d=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):   # arch-ok: 读不到 / 写了一半 = 默认值（状态读不到 = 没有集关闭，旧行为）
        return d


def _atomic_json(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=p.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False, indent=1))
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _iso(t: float | None = None) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() if t is None else t))


def _append(p: Path, rec: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _root(root) -> Path:
    return Path(root or ROOT)


_RUNS_MOD = None


def _runs():
    global _RUNS_MOD
    if _RUNS_MOD is None:
        import importlib.util
        sp = importlib.util.spec_from_file_location("ns_runs_episode_state", Path(__file__).resolve().parent / "runs.py")
        m = importlib.util.module_from_spec(sp)
        sp.loader.exec_module(m)
        _RUNS_MOD = m
    return _RUNS_MOD


def _legacy(run: str, root: Path) -> bool:
    try:
        return bool(_runs().is_legacy(run, root))
    except Exception:  # noqa: BLE001  # arch-ok: 剧目表读不到 = 按非 legacy（V2 路径）
        return False


def ep_of(x) -> int | None:
    """对象 id / 镜号 / 集号 → 集号（first:ep02-S5 / ep02-S5 / 2 / "2"）；认不出 = None"""
    if isinstance(x, int):
        return x
    s = str(x or "")
    if s.isdigit():
        return int(s)
    m = _SID.search(s)
    return int(m.group(1)) if m else None


# ------------------------------------------------------------------ 开关 / 路径
def mode(root: Path | None = None) -> str:
    v = (_jl(_root(root) / CFG_REL, {}) or {}).get(KEY, DEFAULT_MODE)
    if isinstance(v, dict):
        v = v.get("mode", DEFAULT_MODE)
    v = str(v or DEFAULT_MODE).strip().lower()
    return v if v in MODES else DEFAULT_MODE


def state_path(run: str, root: Path | None = None) -> Path:
    return _root(root) / "data/pipeline/runs" / str(run) / "episode_state.json"


def skips_path(run: str, root: Path | None = None) -> Path:
    return _root(root) / "data/pipeline/runs" / str(run) / "episode_closed_skips.jsonl"


def episodes_out(run: str, root: Path | None = None) -> Path:
    r = _root(root)
    return r / "data/episodes" / ("series10" if _legacy(run, r) else str(run))


def producer_dir(run: str, root: Path | None = None) -> Path:
    r = _root(root)
    return r / "data/producer" if _legacy(run, r) else r / "data/producer/runs" / str(run)


def load(run: str, root: Path | None = None) -> dict:
    d = _jl(state_path(run, root), {}) or {}
    return d if isinstance(d, dict) else {}


def closed_eps(run: str, root: Path | None = None) -> set[int]:
    """状态文件里 closed=true 的集（不看开关；off 也照读——开关只决定挡不挡）"""
    out = set()
    for k, v in (load(run, root).get("episodes") or {}).items():
        if isinstance(v, dict) and v.get("closed"):
            try:
                out.add(int(k))
            except (TypeError, ValueError):
                continue
    return out


# ------------------------------------------------------------------ 执行器侧：挡 / 记
def skip(run: str, ep_or_obj, obj: str | None = None, actor: str = "?", root: Path | None = None,
         closed: set | None = None, now: float | None = None, log=None, mode_now: str | None = None) -> bool:
    """执行器派单前调：True = 这一单不派（只有 enforce 且本集关闭）。record 只记不挡；off 什么都不做。
    closed / mode_now 可由调用方一拍算一次传进来（省得每个对象读一次文件）。日志每 (对象, 执行器) 每小时最多一条"""
    m = mode_now if mode_now in MODES else mode(root)
    if m == "off":
        return False
    ep = ep_of(ep_or_obj)
    if ep is None:
        return False
    cs = closed_eps(run, root) if closed is None else closed
    if ep not in cs:
        return False
    obj = str(obj or ep_or_obj)
    t = time.time() if now is None else now
    k = (str(run), obj, actor)
    with _mu:
        due = k not in _logged or t - _logged[k] >= SKIP_EVERY_S
        if due:
            _logged[k] = t
    if due:
        rec = {"ev": "ep_closed_skip", "at": _iso(t), "t": round(t, 1), "run": run, "ep": ep, "obj": obj, "actor": actor,
               "mode": m, "skipped": m == "enforce", "host": os.environ.get("OFFLINE_SELF") or "laptop", "rule": RULE}
        try:
            _append(skips_path(run, root), rec)
        except OSError:   # arch-ok: 日志写不了不影响挡 / 不挡
            pass
        if log:
            try:
                log("ep_closed_skip", obj=obj, ep=ep, actor=actor, mode=m, skipped=m == "enforce", counted=False)
            except Exception:  # noqa: BLE001  # arch-ok: 调用方日志出错不影响判定
                pass
    return m == "enforce"


def enforce_closed(run: str, root: Path | None = None) -> set[int]:
    """enforce 下的关闭集（给 L-207 占卡 / 视频 control 用：record / off = 空集，行为不变）"""
    return closed_eps(run, root) if mode(root) == "enforce" else set()


# ------------------------------------------------------------------ 笔记本侧：算 / 写
def latest_assembly(run: str, ep: int, root: Path | None = None) -> dict | None:
    """本集最新一版成片（epNN_vN.mp4，不含 _post）+ timeline 合成闸门结论；没有 = None"""
    d = episodes_out(run, root)
    best = None
    if d.is_dir():
        for f in d.iterdir():
            m = _FINAL.match(f.name)
            if m and int(m.group(1)) == int(ep) and (best is None or int(m.group(2)) > best[0]):
                best = (int(m.group(2)), f)
    if not best:
        return None
    n, f = best
    tl = _jl(f.with_suffix(".timeline.json"), None)
    gates = (tl or {}).get("gates") if isinstance(tl, dict) else None
    verdict = (gates or {}).get("verdict") if isinstance(gates, dict) else None
    try:
        mt = f.stat().st_mtime
    except OSError:
        mt = 0.0
    miss = [str(x.get("shot") if isinstance(x, dict) else x) for x in ((gates or {}).get("missing_shots") or [])] if isinstance(gates, dict) else []
    lip = lip_redo_shots(tl) if isinstance(tl, dict) else []
    return {"file": f"{d.relative_to(_root(root)).as_posix()}/{f.name}", "version": n, "verdict": verdict or "unknown",
            "missing": miss[:20], "lip_redo": lip[:20], "mtime": round(mt, 1), "key": f"v{n}"}   # 版本号单调递增；不用 mtime（拉取会改 mtime）


_LIP = None


def lip_redo_shots(tl: dict) -> list[str]:
    """K-EDT-805：合成 timeline 里画内对白被 TTS 兜底的镜（tools/director/lip_redo.blocking，与 night finalize → director 同一判法）。
    非空 = 本集要口型重出，不算关闭。判法模块读不到 = 空（只看合成闸门）"""
    global _LIP
    try:
        if _LIP is None:
            import importlib.util
            sp = importlib.util.spec_from_file_location("lip_redo_for_episode_state", ROOT / "tools" / "director" / "lip_redo.py")
            m = importlib.util.module_from_spec(sp)
            sp.loader.exec_module(m)
            _LIP = m
        return [str(r.get("shot")) for r in _LIP.blocking(tl) or []]
    except Exception:  # noqa: BLE001  # arch-ok: 口型判法不可用 = 不加这条限制（只看合成闸门 verdict）
        return []


def _is_owner_reject(v: dict) -> bool:
    by = str(v.get("by") or "")
    return bool(v.get("edit")) or "项目方" in by or "界面" in by or str(v.get("reason") or "").startswith("项目方")


def owner_signals(run: str, ep: int, root: Path | None = None) -> dict:
    """本集项目方信号快照：{"triggers": [本集成人镜触发对象], "rejects": {对象: 指纹}}（只认项目方的修改 / 重出）"""
    pd = producer_dir(run, root)
    trig = (_jl(pd / "owner_triggers.json", {}) or {}).get("objects") or []
    tr = sorted({str(o) for o in trig if ep_of(o) == ep})
    rj = _jl(pd / "master_rejects.json", {}) or {}
    rs = {}
    for k, v in (rj.items() if isinstance(rj, dict) else []):
        if ep_of(k) == ep and isinstance(v, dict) and _is_owner_reject(v):
            rs[str(k)] = hashlib.sha1(json.dumps([v.get("at"), v.get("reject_n"), v.get("edit"), v.get("reason")],
                                                 ensure_ascii=False, default=str).encode("utf-8")).hexdigest()[:12]
    return {"triggers": tr, "rejects": rs}


def _new_owner_input(basis: dict | None, cur: dict) -> str | None:
    if not isinstance(basis, dict):
        return None
    nt = sorted(set(cur["triggers"]) - set(basis.get("triggers") or []))
    if nt:
        return "项目方触发了本集成人镜：" + "、".join(nt[:6])
    old = basis.get("rejects") or {}
    nr = sorted(k for k, v in cur["rejects"].items() if old.get(k) != v)
    if nr:
        return "项目方提交了修改 / 重出：" + "、".join(nr[:6])
    return None


def episodes_of(run: str, root: Path | None = None) -> list[int]:
    """本剧有哪些集：登记表 + 成片目录 + 现有状态文件（任一出现过就算）"""
    eps = set()
    reg = _jl(producer_dir(run, root) / "registry.json", {}) or {}
    for E in reg.get("episodes") or []:
        if ep_of(E.get("ep")) is not None:
            eps.add(int(ep_of(E.get("ep"))))
    d = episodes_out(run, root)
    if d.is_dir():
        for f in d.iterdir():
            m = _FINAL.match(f.name)
            if m:
                eps.add(int(m.group(1)))
    for k in (load(run, root).get("episodes") or {}):
        if ep_of(k) is not None:
            eps.add(int(ep_of(k)))
    return sorted(eps)


def audit_entries(run: str, root: Path | None = None, tail: int = 5000) -> dict[int, list]:
    """审计（data/pipeline/episode_reopen_audit.jsonl）按集 → [记录]（按 t 排序）。审计是重开 / 定稿的真相来源：
    API / CLI 先写审计再改状态；resident_sync 的 compute 与 API 跨进程同时写状态时，丢掉的那次由这里补回"""
    out: dict[int, list] = {}
    try:
        lines = (_root(root) / AUDIT_REL).read_text(encoding="utf-8").splitlines()[-tail:]
    except OSError:   # arch-ok: 没有审计 = 没有手动重开 / 定稿
        return out
    for x in lines:
        try:
            a = json.loads(x)
        except ValueError:   # arch-ok: 审计行写了一半 = 跳过这一行（其它行照读）
            continue
        if isinstance(a, dict) and a.get("run") == run and a.get("action") in ("reopen", "final") and ep_of(a.get("ep")) is not None:
            out.setdefault(int(a["ep"]), []).append(a)
    for v in out.values():
        v.sort(key=lambda a: float(a.get("t") or 0))
    return out


def _replay(rec: dict, prev: dict, audit: list | None) -> None:
    """把状态里还没反映的审计记录补进 rec（只补比本集关闭时刻 / 已有重开 / 已有定稿更新的）"""
    for a in audit or []:
        t = float(a.get("t") or 0)
        reo_t = float((rec.get("reopened") or {}).get("t") or 0)
        fin_t = float((rec.get("owner_final") or {}).get("t") or 0)
        if a["action"] == "reopen" and t > reo_t and t > fin_t and t > float(prev.get("closed_t") or 0):
            rec["reopened"] = {"at": a.get("at"), "t": t, "by": a.get("by"), "why": a.get("why") or "项目方要求重新打开",
                               "source": a.get("source"), "asm_key": a.get("asm_key")}
            rec.pop("owner_final", None)
        elif a["action"] == "final" and t > fin_t and t > reo_t:
            rec["owner_final"] = {"at": a.get("at"), "t": t, "by": a.get("by"), "why": a.get("why")}
            rec.pop("reopened", None)


def _decide(run: str, ep: int, prev: dict, root: Path | None, now: float, audit: list | None = None) -> tuple[dict, list]:
    """一集：→ (新记录, 事件)。prev = 状态文件里本集旧记录；audit = 本集审计（重开 / 定稿）"""
    ev = []
    asm = latest_assembly(run, ep, root)
    sig = owner_signals(run, ep, root)
    rec = {k: prev.get(k) for k in ("owner_final", "reopened", "basis", "closed_at", "closed_t") if prev.get(k) is not None}
    _replay(rec, prev, audit)
    rec["assembly"] = asm
    akey = (asm or {}).get("key")
    reo = rec.get("reopened") if isinstance(rec.get("reopened"), dict) else None
    if reo and reo.get("asm_key") != akey and (asm or {}).get("verdict") == "pass" and not (asm or {}).get("lip_redo"):
        rec.pop("reopened", None)          # 重开之后出了新一版过闸成片 → 重开结束
        ev.append(("reopen_done", f"重开后新成片 v{asm['version']} 过闸"))
        reo = None
    fin = rec.get("owner_final") if isinstance(rec.get("owner_final"), dict) else None
    if fin and reo and float(reo.get("t") or 0) > float(fin.get("t") or 0):
        rec.pop("owner_final", None)       # 定稿后又重开 = 定稿作废
        fin = None
    if reo:
        closed, why = False, f"已重新打开（{reo.get('by')}：{reo.get('why')}）"
    elif fin:
        closed, why = True, f"项目方标了定稿（{fin.get('by')}）"
    elif asm and asm.get("verdict") == "pass" and asm.get("lip_redo"):
        closed, why = False, f"成片 v{asm['version']} 过合成闸门，但有口型重出镜 {'、'.join(asm['lip_redo'])}（K-EDT-805）"
    elif asm and asm.get("verdict") == "pass":
        closed, why = True, f"成片 v{asm['version']} 过合成闸门（{asm['file']}）"
    elif asm:
        closed, why = False, f"最新成片 v{asm['version']} 合成闸门 {asm['verdict']}" + (f"（缺 {'、'.join(asm['missing'])}）" if asm.get("missing") else "")
    else:
        closed, why = False, "还没有成片"
    if closed and prev.get("closed"):
        auto = _new_owner_input(rec.get("basis"), sig)
        if auto:                            # 关闭之后项目方又动了本集 → 自动重开
            rec["reopened"] = {"at": _iso(now), "t": round(now, 1), "by": "项目方", "why": auto, "source": "auto", "asm_key": akey}
            rec.pop("owner_final", None)
            closed, why = False, f"已重新打开（项目方：{auto}）"
            ev.append(("reopen_auto", auto))
    if closed and not prev.get("closed"):
        rec["closed_at"] = _iso(now)
        rec["closed_t"] = round(now, 3)
        rec["basis"] = sig                  # 关闭那一刻的项目方信号快照（之后有新的 = 自动重开）
        ev.append(("closed", why))
    elif not closed:
        rec.pop("basis", None)
        rec.pop("closed_at", None)
        rec.pop("closed_t", None)
        if prev.get("closed"):
            ev.append(("opened", why))
    rec.update(closed=closed, why=why)
    return rec, ev


def compute(run: str, root: Path | None = None, now: float | None = None, write: bool = True, log=None) -> dict:
    """笔记本每拍算一次（resident_sync 推送前）：按口径重算每集 closed，变了才原子写。off = 不写（保留旧文件，执行器也不挡）"""
    r = _root(root)
    t = time.time() if now is None else now
    old = load(run, r)
    olde = old.get("episodes") or {}
    eps = {}
    events = []
    aud = audit_entries(run, r)
    for ep in sorted(set(episodes_of(run, r)) | set(aud)):
        rec, ev = _decide(run, ep, olde.get(str(ep)) or {}, r, t, aud.get(ep))
        eps[str(ep)] = rec
        events += [(ep, a, b) for a, b in ev]
    doc = {"run": run, "rule": RULE, "mode": mode(r), "episodes": eps,
           "closed": sorted(int(k) for k, v in eps.items() if v.get("closed")),
           "_doc": "集关闭标记：closed=true 的集执行器不再派单（enforce）；只有笔记本写，两台只读。口径见 tools/autopilot/episode_state.py"}
    same = {k: v for k, v in old.items() if k not in ("updated_at", "updated_t")} == doc
    if write and not same and doc["mode"] != "off":
        doc.update(updated_at=_iso(t), updated_t=round(t, 1))
        _atomic_json(state_path(run, r), doc)
    for ep, a, b in events:
        if log:
            log("episode_state", run, f"ep{ep:02d}", a, b)
    return doc


def laptop_only() -> None:
    """集关闭状态只有笔记本写（服务器只读推来的副本）：OFFLINE_SELF 有值 = 在服务器上 → 拒绝"""
    if os.environ.get("OFFLINE_SELF"):
        raise RuntimeError(f"episode_state 只在笔记本写；本机是服务器 {os.environ.get('OFFLINE_SELF')}（OFFLINE_SELF），拒绝")


def _edit_ep(run: str, ep: int, root: Path | None, fn) -> dict:
    laptop_only()
    r = _root(root)
    with _mu:
        doc = load(run, r) or {"run": run, "rule": RULE, "episodes": {}}
        e = doc.setdefault("episodes", {}).setdefault(str(int(ep)), {})
        fn(e)
        _atomic_json(state_path(run, r), doc)
    return compute(run, r)


def reopen(run: str, ep: int, by: str, why: str = "", source: str = "owner_api", root: Path | None = None) -> dict:
    """重新打开一集（项目方 API / 总调度按项目方对话指示）。先写审计再改状态；重开到出新一版过闸成片为止"""
    laptop_only()
    r = _root(root)
    t = time.time()
    akey = (latest_assembly(run, int(ep), r) or {}).get("key")
    _append(r / AUDIT_REL, {"at": _iso(t), "t": round(t, 3), "run": run, "ep": int(ep), "action": "reopen", "by": by,
                            "why": why, "source": source, "asm_key": akey})
    doc = _edit_ep(run, ep, r, lambda e: (e.update(reopened={"at": _iso(t), "t": round(t, 3), "by": by, "why": why or "项目方要求重新打开",
                                                             "source": source, "asm_key": akey}), e.pop("owner_final", None)))
    return (doc.get("episodes") or {}).get(str(int(ep))) or {}


def mark_final(run: str, ep: int, by: str, why: str = "", source: str = "owner_api", root: Path | None = None) -> dict:
    """项目方标定稿：不论合成闸门结论，本集关闭（之后重开才作废）"""
    laptop_only()
    r = _root(root)
    t = time.time()
    _append(r / AUDIT_REL, {"at": _iso(t), "t": round(t, 3), "run": run, "ep": int(ep), "action": "final", "by": by,
                            "why": why, "source": source})
    doc = _edit_ep(run, ep, r, lambda e: (e.update(owner_final={"at": _iso(t), "t": round(t, 3), "by": by, "why": why}),
                                          e.pop("reopened", None)))
    return (doc.get("episodes") or {}).get(str(int(ep))) or {}


def _cli(argv: list[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="episode_state.py")
    ap.add_argument("cmd", choices=["show", "compute", "reopen", "final"])
    ap.add_argument("--run", default=None)
    ap.add_argument("--ep", type=int)
    ap.add_argument("--by", default="")
    ap.add_argument("--why", default="")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args(argv)
    run = a.run or _runs().current_run(ROOT)
    if a.cmd in ("reopen", "final", "compute") and os.environ.get("OFFLINE_SELF"):
        print(f"拒绝：episode_state 只在笔记本写（本机 OFFLINE_SELF={os.environ.get('OFFLINE_SELF')}）", file=sys.stderr)
        return 2
    if a.cmd in ("reopen", "final"):
        if not a.ep or not a.by.strip():
            ap.error("reopen / final 要 --ep 和 --by（写明“按项目方对话指示”）")
        fn = reopen if a.cmd == "reopen" else mark_final
        out = fn(run, a.ep, a.by.strip(), a.why, source="cli")
    elif a.cmd == "compute":
        out = compute(run, write=not a.dry)
    else:
        out = {"mode": mode(), **load(run)}
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
