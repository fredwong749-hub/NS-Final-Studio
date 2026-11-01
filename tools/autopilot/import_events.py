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
SCRIPT = ROOT / "data/import/script_v2.json"


def script_sha(path: Path = SCRIPT) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else ""


def _primary() -> str:
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    import runs as RN
    return RN.primary_run()


def append_import(episodes: list[int], by: str, source: str | None = None, note: str | None = None,
                  events: Path | None = None, script: Path | None = None, run_id: str | None = None) -> dict:
    """多剧并行（§0.1）：每条事件必须带 run_id；不给 = primary。新 run 的导入稿在 data/import/runs/<run>/script_v2.json"""
    run_id = run_id or _primary()
    if script is None:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        import runs as RN
        script = RN.import_path(run_id)
    rec = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "run_id": run_id, "episodes": sorted({int(e) for e in episodes}),
           "script_sha": script_sha(script), "source": source, "by": by, "note": note}
    p = events or EVENTS
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


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
