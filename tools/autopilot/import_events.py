"""剧本导入事件（WORKFLOW 11-02，总调度派；DISTILL 冷启动演练：新集不能只靠 CHANGELOG 里一行字发现；规则 K-OPS-W15）。

导入方（producer import_staged 成功之后，或任何正式导入入口）调 append_import()，往 data/autopilot/imports.jsonl 追加一行：
    {"at": ISO, "episodes": [4], "script_sha": "<data/import/script_v2.json 的 sha256>", "source": "<暂存稿路径>", "by": "...", "note": "..."}
episode_pipeline 读这个文件触发逐集准备；CHANGELOG 那行只给人看，不再作为触发。

    from import_events import append_import   # tools/autopilot 在 sys.path 上时
    append_import([4], by="PRODUCER import_staged", source=path, note=note)
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVENTS = ROOT / "data/autopilot/imports.jsonl"
_REAL_EVENTS = EVENTS
SCRIPT = ROOT / "data/import/script_v2.json"


def script_sha(path: Path = SCRIPT) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else ""


def _primary() -> str:
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    import runs as RN
    return RN.primary_run()


SIG_FIELDS = ("img_prompt", "motion_prompt", "h3_prompt", "cast_raw", "cast")     # 镜级“提示词变了”的口径（img / motion / h3 / cast）


def shot_sigs(script) -> dict[str, str]:
    """导入稿（路径或已读 dict）→ {镜号 'ep01-S3': 提示词指纹}。指纹 = img/motion/h3/cast 的 sha256[:16]（K-OPS-E09 同口径）"""
    d = script
    if not isinstance(script, dict):
        d = json.loads(Path(script).read_text(encoding="utf-8"))      # 读不到 / 坏文件直接报错（不静默当空）
    out: dict[str, str] = {}
    for ep in d.get("episodes") or []:
        for sh in ep.get("shots") or []:
            k = f"ep{int(sh.get('episode') or ep.get('number') or 0):02d}-S{sh.get('index')}"
            body = json.dumps([sh.get(f) for f in SIG_FIELDS], ensure_ascii=False, sort_keys=True)
            out[k] = hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]
    return out


def changed_shots(old, new) -> list[str]:
    """新稿相对旧稿提示词变了的镜（新增镜也算 changed）；old 缺失 = 全部算 changed"""
    a, b = shot_sigs(old) if old else {}, shot_sigs(new)
    return sorted((k for k, v in b.items() if a.get(k) != v), key=lambda x: (x[:4], int(x.split("-S")[1])))


def append_import(episodes: list[int], by: str, source: str | None = None, note: str | None = None,
                  events: Path | None = None, script: Path | None = None, run_id: str | None = None,
                  old_script: Path | None = None) -> dict:
    """多剧并行（§0.1）：每条事件必须带 run_id；不给 = primary。新 run 的导入稿在 data/import/runs/<run>/script_v2.json"""
    run_id = run_id or _primary()
    if script is None:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        import runs as RN
        script = RN.import_path(run_id)
    # ts：S2.1 无歧义时刻（at 是写入机本地时间，笔记本美东 / 服务器 JST 不一）
    rec = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "ts": round(time.time(), 1), "run_id": run_id, "episodes": sorted({int(e) for e in episodes}),
           "script_sha": script_sha(script), "source": source, "by": by, "note": note}
    if old_script is not None:      # 镜级作废口径：只有提示词变了的镜，导入前的候选才算旧版本（无此字段的旧事件按整集）
        rec["changed_shots"] = changed_shots(old_script if Path(old_script).exists() else None, script)
    p = events or EVENTS
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    if p.resolve() == _REAL_EVENTS.resolve():   # L-216（W-KICKOFF）：开项目常设授权 → 新导入的成人镜自动入触发清单（只按 id）；测试换了事件文件就不动真清单
        rec["kickoff_adult"] = _kickoff_adult(run_id)
    return rec


def _kickoff_adult(run_id: str) -> dict:
    try:
        import sys
        if str(ROOT / "tools" / "pipeline") not in sys.path:
            sys.path.insert(0, str(ROOT / "tools" / "pipeline"))
        import kickoff as KO
        r = KO.sync_adult(run_id)
        return {"added": len(r.get("added") or []), **({"skipped": r["skipped"]} if r.get("skipped") else {})}
    except Exception as e:  # noqa: BLE001  # arch-ok: 导入已成功；入清单失败带回调用方，owner_delegate 每拍还会再同步
        return {"error": f"{type(e).__name__}: {e}"[:200]}


def read_events(events: Path | None = None) -> list[dict]:
    p = events or EVENTS
    out = []
    try:
        for ln in p.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(ln))
            except ValueError:
                continue
    except OSError:
        pass
    return out


def episodes_imported(events: Path | None = None, run_id: str | None = None) -> list[int]:
    """run_id 给定：只看这部剧的事件（旧事件没有 run_id 的算 primary）"""
    prim = _primary()
    want = run_id or prim
    seen: list[int] = []
    for ev in read_events(events):
        if (ev.get("run_id") or prim) != want:
            continue
        for e in ev.get("episodes") or []:
            if int(e) not in seen:
                seen.append(int(e))
    return seen


def cutoff_table(run_id: str, events: Path | None = None) -> dict:
    """某剧的“导入后才算现行”时间表（镜级作废口径，PS-MASTER 11-04）：
      shot  {镜号 'ep01-S3': 最后一次“该镜提示词变了”的导入时间}（来自事件的 changed_shots；历史事件由 changed_shots_backfill 补记事件提供）
      ep    {集号: 最后一次没有任何镜级信息的导入时间}（旧事件，保守按整集）
      whole 没有集号也没有镜级信息的导入（对所有集生效）
    镜的 cutoff = max(shot.get(镜), ep.get(集), whole)"""
    rows = [r for r in read_events(events) if r.get("at") and r.get("run_id") == run_id]
    back = {r.get("orig_at"): r.get("changed_shots") for r in rows if r.get("kind") == "changed_shots_backfill"}
    shot: dict[str, str] = {}
    ep: dict[int, str] = {}
    whole = ""
    for r in rows:
        if r.get("kind") == "changed_shots_backfill":
            continue
        ch = r.get("changed_shots")
        if ch is None:
            ch = back.get(r["at"])
        if ch is not None:
            for k in ch:
                shot[k] = max(shot.get(k, ""), r["at"])
            continue
        eps = [int(x) for x in (r.get("episodes") or []) if str(x).isdigit()]
        if eps:
            for n in eps:
                ep[n] = max(ep.get(n, ""), r["at"])
        else:
            whole = max(whole, r["at"])
    return {"shot": shot, "ep": ep, "whole": whole}


def shot_cutoff(tbl: dict, ep: int, shot: int | None = None) -> str:
    c = [tbl["ep"].get(ep, ""), tbl["whole"]]
    if shot is not None:
        c.append(tbl["shot"].get(f"ep{ep:02d}-S{shot}", ""))
    else:                                           # 不指定镜：本集最晚一次有镜改动的导入（集级展示用）
        c += [v for k, v in tbl["shot"].items() if k.startswith(f"ep{ep:02d}-")]
    return max(c)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("episodes", help="逗号分隔集号，如 4 或 1,2")
    ap.add_argument("--by", required=True)
    ap.add_argument("--source")
    ap.add_argument("--note")
    ap.add_argument("--run", default=None, help="run_id；不给 = primary")
    a = ap.parse_args()
    print(append_import([int(x) for x in a.episodes.split(",") if x.strip()], a.by, a.source, a.note, run_id=a.run))
