"""S2.1（L209_S2_PLAN）：每个 take 的签名 + 当前版签名不符时自动换代。

签名 = {script_sig, prompt_sha, rule_fp}
  script_sig  本镜剧本输入（导入稿 data/import/runs/<run>/script_v2.json 这一镜的 INPUT_FIELDS，与 producer.input_sig 同口径，
              但读本剧的导入稿——producer.input_sig 读的是 data/import/script_v2.json，那是 V1 的稿）
  prompt_sha  编译出的首帧作业提示词 sha256[:16]（与 producer.shot_inputs_sig / compile_trace.prompt_sha 同口径）
  rule_fp     契约 / 出图预设 / 看图闸门三份配置的内容哈希（= producer.be_rule_sig）

写入：ns_render.pipeline.stamp_versions（_add_take 唯一入口，两台服务器的 producer / API / 视频都经过这里）。
检查：producer 每拍 take_sig_tick → check_run。开关 config/pipeline/state.json {"take_sig": {"mode": off|record|enforce}}，默认 record。
  record   只记 sig_stale / 计数，不动任何东西
  enforce  当前首帧签名不符 → 走 regen_shots（不计次，旧版保留到新版过闸；hold_regen_downstream 挡尾帧 / 视频）
"""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODES = ("off", "record", "enforce")
STATE_CFG = "config/pipeline/state.json"
RULE_FILES = ("config/gen_contract.json", "config/render_quality.json", "config/vqa.json")   # = producer.BE_RULE_FILES（单测核对）
INPUT_FIELDS = ("img_prompt", "motion_prompt", "cast_raw", "cast", "scene_id", "scene_detail", "decor_state", "duration")  # = producer.INPUT_FIELDS
PARTS = ("script_sig", "prompt_sha", "rule_fp")
STAGE_KIND = {"image": "first", "last": "last", "video": "video"}
BY = "TAKE_SIG"
JST = timezone(timedelta(hours=9))
# 旧导入事件只有无时区的 at（写它的机器可能是笔记本美东，也可能是服务器 JST）：取最晚的那种解读。
# 只用于“这一版早于导入”这一个条件，另一个条件（出图时的编译提示词 ≠ 现在的）兜底，不会误换代
LEGACY_AT_OFFSETS = (9, -4, -5)

_cache: dict = {}


def _sha16(s: str) -> str:
    return hashlib.sha256((s or "").encode("utf-8")).hexdigest()[:16]


def _mtime(p: Path) -> float | None:
    try:
        return p.stat().st_mtime
    except OSError:   # arch-ok: 文件不在 = 没有 mtime，_cached 按空表处理（该段不比）
        return None


def _jload(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):   # arch-ok: 读不到 = 调用方按“算不出”处理（签名缺这一段 → 不比这一段）
        return default


def cfg(root: Path = ROOT) -> dict:
    """开关：mode 默认 record；写错的值按 record（只记不动，安全方向）"""
    c = (_jload(Path(root) / STATE_CFG, {}) or {}).get("take_sig") or {}
    c = c if isinstance(c, dict) else {}
    mode = c.get("mode") if c.get("mode") in MODES else "record"

    def _num(k, d, f):   # 复审 11-07：写错的数值不能让每拍抛错（producer tick 停摆），按默认
        try:
            return f(c.get(k, d))
        except (TypeError, ValueError):  # arch-ok: 坏值 = 默认
            return f(d)
    return {"mode": mode, "max_regen_per_tick": _num("max_regen_per_tick", 2, int),
            "max_pending": _num("max_pending", 6, int), "every_s": _num("every_s", 60, float),
            # 复审 11-07：rule_fp（三份配置整文件哈希）任何改动都会让整季当前版“签名不符”→ 默认只记录不换代；
            # 真要按规则升级全季重出时，state.json 显式写 rule_fp_enforce=true（一次性）
            "rule_fp_enforce": c.get("rule_fp_enforce") is True,
            # 无签名旧版、出图时编译提示词不可恢复（V2 没有 first_frame_jobs.json，现编译随档位变）：leave = 记日志不动（默认）；
            # predates = 只凭“早于本镜最后一次改了本镜的导入（changed_shots）”换代
            "unknown_unrecoverable": "predates" if c.get("unknown_unrecoverable") == "predates" else "leave"}


def _cached(key: str, path: Path, build):
    mt = _mtime(path)
    hit = _cache.get(key)
    if hit and hit[0] == mt:
        return hit[1]
    val = build() if mt is not None else {}
    _cache[key] = (mt, val)
    return val


def rule_fp(root: Path = ROOT) -> str:
    h = hashlib.sha256()
    for f in RULE_FILES:
        try:
            h.update((Path(root) / f).read_bytes())
        except OSError:
            h.update(b"-")
    return h.hexdigest()[:16]


def script_sigs(script_path: Path) -> dict:
    def build():
        d = _jload(script_path, {}) or {}
        out = {}
        for ep in d.get("episodes") or []:
            for sh in ep.get("shots") or []:
                k = f"ep{int(ep.get('number') or 0):02d}-S{sh.get('index')}"
                out[k] = _sha16(json.dumps({x: sh.get(x) for x in INPUT_FIELDS}, ensure_ascii=False, sort_keys=True))
        return out
    return _cached(f"script:{script_path}", script_path, build)


def job_prompt_shas(jobs_path: Path) -> dict:
    def build():
        jobs = (_jload(jobs_path, {}) or {}).get("jobs") or []
        return {(j.get("shot") or j.get("id")): _sha16(j.get("prompt") or "") for j in jobs if j.get("shot") or j.get("id")}
    return _cached(f"jobs:{jobs_path}", jobs_path, build)


def run_files(root: Path, run: str) -> tuple[Path, Path]:
    """本剧的导入稿 + 首帧作业表"""
    import sys
    if str(Path(root) / "tools" / "autopilot") not in sys.path:
        sys.path.insert(0, str(Path(root) / "tools" / "autopilot"))
    import runs as RN
    return RN.import_path(run, Path(root)), Path(root) / "data" / "pipeline" / "runs" / run / "assets" / "first_frame_jobs.json"


def current(root: Path, sid: str, script_path: Path, jobs_path: Path) -> dict:
    return {"script_sig": script_sigs(script_path).get(sid), "prompt_sha": job_prompt_shas(jobs_path).get(sid),
            "rule_fp": rule_fp(root)}


def trace_prompt_sha(t: dict) -> str | None:
    """出图时编译器给的提示词指纹（unified_frame 记在 params.compile_trace.prompt_sha）；没有 = 不可恢复"""
    ct = (t.get("params") or {}).get("compile_trace") if isinstance(t.get("params"), dict) else None
    return ct.get("prompt_sha") if isinstance(ct, dict) else None


def for_new_take(root: Path, sid: str, stage: str, take: dict, script_path: Path, jobs_path: Path) -> dict | None:
    """新 take 入库时盖的签名（mode=off 不盖）。首帧的 prompt_sha 优先取出图那一刻的 compile_trace（防出图途中导入新稿）"""
    if cfg(root)["mode"] == "off":
        return None
    cur = current(root, sid, script_path, jobs_path)
    if stage == "image" and trace_prompt_sha(take):
        cur["prompt_sha"] = trace_prompt_sha(take)
    return {**cur, "v": 1}


def diff(rec: dict, cur: dict, stage: str) -> list[str]:
    """签名不符的段。首帧比三段；尾帧 / 视频的 prompt_sha 是首帧作业的，不比（由首帧换代带动）。现在算不出的段不比"""
    parts = PARTS if stage == "image" else ("script_sig", "rule_fp")
    return [p for p in parts if cur.get(p) and rec.get(p) and rec[p] != cur[p]]


# ------------------------------------------------------------------ 导入作废线（epoch；旧事件无时区按最晚解读）
def _at_epochs(r: dict) -> float | None:
    if isinstance(r.get("ts"), (int, float)):
        return float(r["ts"])
    try:
        d = datetime.fromisoformat(str(r.get("at")).strip().replace("Z", "+00:00"))
    except ValueError:   # arch-ok: 时间串坏 = 这条事件不算作废线
        return None
    if d.tzinfo is not None:
        return d.timestamp()
    return max(d.replace(tzinfo=timezone(timedelta(hours=h))).timestamp() for h in LEGACY_AT_OFFSETS)


def import_cutoffs(run: str, events: Path) -> dict:
    """{镜号: 最后一次影响本镜的导入 epoch}，口径同 import_events.cutoff_table（changed_shots 镜级 / 无镜级按整集 / 无集号按整本）"""
    def build():
        rows = []
        for ln in events.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(ln)
            except ValueError:   # arch-ok: 坏行跳过（与 import_events.read_events 同口径）
                continue
            if r.get("run_id") == run and r.get("at"):
                rows.append(r)
        back = {r.get("orig_at"): r.get("changed_shots") for r in rows if r.get("kind") == "changed_shots_backfill"}
        shot, ep, whole = {}, {}, 0.0
        for r in rows:
            if r.get("kind") == "changed_shots_backfill":
                continue
            t = _at_epochs(r)
            if t is None:
                continue
            ch = r.get("changed_shots")
            if ch is None:
                ch = back.get(r["at"])
            if ch is not None:
                for k in ch:
                    shot[k] = max(shot.get(k, 0.0), t)
                continue
            eps = [int(x) for x in (r.get("episodes") or []) if str(x).isdigit()]
            for n in eps:
                ep[n] = max(ep.get(n, 0.0), t)
            if not eps:
                whole = max(whole, t)
        return {"shot": shot, "ep": ep, "whole": whole}
    return _cached(f"imports:{run}:{events}", events, build) or {"shot": {}, "ep": {}, "whole": 0.0}


def shot_cutoff(tbl: dict, sid: str) -> float:
    ep = int(sid.split("-")[0][2:])
    return max(tbl.get("shot", {}).get(sid, 0.0), tbl.get("ep", {}).get(ep, 0.0), tbl.get("whole", 0.0))


def take_epoch(t: dict) -> float | None:
    try:
        d = datetime.fromisoformat(str(t.get("created_at")).strip().replace("Z", "+00:00"))
    except ValueError:   # arch-ok: 没出图时间 = 判不了“早于导入”，不换代
        return None
    return (d if d.tzinfo else d.replace(tzinfo=JST)).timestamp()


# ------------------------------------------------------------------ 每拍检查
def classify(td: dict, sid: str, cur: dict, cutoff: float, unrecoverable: str = "leave") -> dict:
    """本镜三阶段当前版 → {kind: {"state": fresh|stale|unknown, "parts": [...], "n": n, "regen_ok": bool, "why": str}}"""
    out = {}
    act = td.get("active") or {}
    for stage, kind in STAGE_KIND.items():
        n = act.get(stage)
        t = next((x for x in td.get("takes") or [] if x.get("stage") == stage and x.get("n") == n), None) if n else None
        if not t:
            continue
        rec = t.get("sig") if isinstance(t.get("sig"), dict) else None
        if rec:
            parts = diff(rec, cur, stage)
            out[kind] = {"state": "stale" if parts else "fresh", "parts": parts, "n": n, "regen_ok": bool(parts)}
            continue
        row = {"state": "unknown", "parts": [], "n": n, "regen_ok": False}
        if stage == "image":                     # 无签名的旧版：早于本镜最后一次导入 且 出图时的编译提示词 ≠ 现在的 → 才换代
            te, tp = take_epoch(t), trace_prompt_sha(t)
            if not (te and cutoff and te < cutoff):
                row["why"] = "不早于本镜最后一次导入"
            elif not tp or not cur.get("prompt_sha"):
                row["why"] = "出图时的编译提示词不可恢复"
                if unrecoverable == "predates":
                    row.update(regen_ok=True, parts=["imported_after"], why="早于本镜最后一次导入（提示词不可比，按开关换代）")
            elif tp == cur["prompt_sha"]:
                row["why"] = "编译提示词没变"
            else:
                row.update(regen_ok=True, parts=["prompt_sha"], why="早于导入且编译提示词已变")
        out[kind] = row
    return out


def check_run(root: Path, run: str, shots: list, load_takes, *, mode: str, adult_shots: set, triggers: set,
              run_status: str | None, rejects: dict, state_file: Path, regen_fn, log, c: dict | None = None,
              events: Path | None = None) -> dict:
    """一拍：算本剧每镜当前版签名状态；record 只记，enforce 按限额换代首帧。返回心跳计数"""
    c = c or cfg(root)
    hb = {"mode": mode, "stale": {"first": 0, "last": 0, "video": 0}, "unknown": {"first": 0, "last": 0, "video": 0},
          "regen": [], "skipped": {}}
    if mode == "off":
        return hb
    if run_status in ("frozen", "archived"):
        hb["skipped"]["*"] = f"run {run_status}"
        return hb
    script_path, jobs_path = run_files(root, run)
    tbl = import_cutoffs(run, events or Path(root) / "data" / "autopilot" / "imports.jsonl")
    memo = _cache.setdefault(f"memo:{run}", {})
    cands = []
    for sid in shots:
        cur = current(root, sid, script_path, jobs_path)
        cut = shot_cutoff(tbl, sid)
        td = load_takes(sid)
        key = json.dumps([td.get("active"), len(td.get("takes") or []), td.get("seq"), cur, cut, c["unknown_unrecoverable"]],
                         sort_keys=True, default=str)
        hit = memo.get(sid)
        fresh_calc = not hit or hit[0] != key
        res = classify(td, sid, cur, cut, c["unknown_unrecoverable"]) if fresh_calc else hit[1]
        memo[sid] = (key, res)
        for kind, r in res.items():
            if r["state"] in ("stale", "unknown"):
                hb[r["state"]][kind] += 1
            if fresh_calc and r["state"] == "stale":
                log("sig_stale", obj=f"{kind}:{sid}", take=r["n"], parts=r["parts"], mode=mode, counted=False)
            if fresh_calc and r["state"] == "unknown" and kind == "first" and mode == "enforce" and not r["regen_ok"]:
                log("sig_unknown_left", obj=f"first:{sid}", take=r["n"], why=r.get("why"), counted=False)
        f = res.get("first")
        if f and f["regen_ok"]:
            cands.append((sid, f, json.dumps(cur, sort_keys=True)))
    if mode != "enforce" or not cands:
        return hb
    st = _jload(state_file, {}) or {}
    pending = sum(1 for k, v in (rejects or {}).items()
                  if k.startswith("first:") and isinstance(v, dict) and not v.get("cleared") and (v.get("regen") or {}).get("by") == BY)
    room = max(0, min(c["max_regen_per_tick"], c["max_pending"] - pending))
    pick = []
    for sid, f, target in cands:
        oid = f"first:{sid}"
        parts = set(((f or {}).get("parts") if isinstance(f, dict) else []) or [])
        if parts and parts <= {"rule_fp"} and not c.get("rule_fp_enforce"):
            hb["skipped"][sid] = "只是规则配置变了（rule_fp 只记录，需 rule_fp_enforce 才全季换代）"
            continue
        if sid in adult_shots and not ({oid, f"{run}/{oid}"} & set(triggers or ())):
            hb["skipped"][sid] = "成人镜未经项目方触发（L-128）"
            continue
        if (st.get(sid) or {}).get("target") == target:
            hb["skipped"][sid] = "这一签名已换代过"
            continue
        td = load_takes(sid)
        if (td.get("locked") or {}).get("image") is not None or td.get("active", {}).get("image") in _upload_ns(td):
            hb["skipped"][sid] = "项目方定稿 / 上传版不动"
            continue
        if len(pick) >= room:
            hb["skipped"][sid] = "本拍换代名额用完"
            continue
        pick.append((sid, f, target))
    if not pick:
        return hb
    by_sid = {sid: (f, target) for sid, f, target in pick}
    res = regen_fn([s for s, _, _ in pick], "签名不符自动换代（S2.1）：" + "；".join(f"{s} {'/'.join(by_sid[s][0]['parts'])}" for s in by_sid))
    for sid in res.get("regen") or []:
        st[sid] = {"target": by_sid[sid][1], "parts": by_sid[sid][0]["parts"], "take": by_sid[sid][0]["n"],
                   "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        log("sig_regen", obj=f"first:{sid}", parts=by_sid[sid][0]["parts"], take=by_sid[sid][0]["n"], counted=False)
    hb["regen"] = list(res.get("regen") or [])
    hb["skipped"].update(res.get("skipped") or {})
    state_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = state_file.with_name(state_file.name + ".tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(state_file)
    return hb


def _upload_ns(td: dict) -> set:
    return {t.get("n") for t in td.get("takes") or [] if t.get("stage") == "image" and (t.get("source") == "upload" or t.get("mode") == "upload")}
